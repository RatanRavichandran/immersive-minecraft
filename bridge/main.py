"""Wiring and asyncio entrypoint (PLAN.md section 4). Joins
listener -> skymodel -> bulb.

Also doubles as the --simulate harness from TASKS.md Task 2.9: replay a
full day in about 30 seconds with no Minecraft running, for fast colour
tuning without a 20-minute wait each time. Pulled forward from the
PLAN.md section 14 v2 backlog — see TASKS.md "Deviation 3" for why.

Usage (run from inside bridge/, matching how the tests import its modules):

    python main.py                       listen for the mod's UDP telemetry, drive the real bulb
    python main.py --simulate            replay ticks 0-24000 in ~30s, drive the real bulb
    python main.py --simulate --no-bulb  same, but print the resolved colours instead of sending
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import config
from bulb import BulbDriver, WizBulb
from listener import start_listener
from skymodel import resolve

logger = logging.getLogger(__name__)

SIMULATED_DAY_SECONDS = 30.0
SIMULATED_TICKS_PER_SECOND = 24000 / SIMULATED_DAY_SECONDS  # ~800 ticks/sec


class _PrintingBulb:
    """--no-bulb stand-in: prints instead of sending UDP anywhere. Handy
    for tuning colours with no bulb plugged in at all.
    """

    async def turn_on(self, pilot_builder) -> None:
        print(f"  on   {dict(pilot_builder.pilot_params)}")

    async def turn_off(self) -> None:
        print("  off")

    async def async_close(self) -> None:
        pass


def _make_real_bulb() -> WizBulb:
    from pywizlight import wizlight

    return wizlight(config.BULB_IP)


async def _consume(queue: "asyncio.Queue[dict]", driver: BulbDriver) -> None:
    """The one task allowed to call driver.update() (BulbDriver is not
    safe to call concurrently — see its docstring). The listener callback
    only ever enqueues; this loop is the single consumer.
    """
    while True:
        packet = await queue.get()
        try:
            await driver.update(resolve(packet))
        except Exception:
            # A bad packet or a bulb hiccup must not take the bridge down —
            # the next packet arrives in half a second with full state
            # anyway (PLAN.md section 3).
            logger.exception("failed to process packet: %r", packet)


async def run_listener() -> None:
    bulb = _make_real_bulb()
    driver = BulbDriver(bulb)
    queue: "asyncio.Queue[dict]" = asyncio.Queue(maxsize=4)

    def on_packet(packet: dict) -> None:
        # Called synchronously from the datagram protocol — must never
        # block. If the queue is already full (the consumer fell behind,
        # or is stuck on a slow bulb send), drop the oldest queued packet
        # rather than the newest: only the most recent state matters for a
        # real-time sync, PLAN.md section 3 already treats every packet as
        # full state, never a delta.
        try:
            queue.put_nowait(packet)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(packet)

    transport = await start_listener(on_packet, config.LISTEN_HOST, config.LISTEN_PORT)
    consumer = asyncio.ensure_future(_consume(queue, driver))
    logger.info(
        "bridge running on %s:%d — waiting for the mod's telemetry, Ctrl+C to stop",
        config.LISTEN_HOST, config.LISTEN_PORT,
    )
    try:
        await consumer
    finally:
        # Deliberately does NOT turn the bulb off — the last state it was
        # driven to is left exactly as it was. Stepping away from the
        # bridge shouldn't plunge the room into darkness.
        consumer.cancel()
        transport.close()
        await bulb.async_close()


async def run_simulation(use_bulb: bool) -> None:
    bulb = _make_real_bulb() if use_bulb else _PrintingBulb()
    driver = BulbDriver(bulb)
    tick_step = max(1, round(SIMULATED_TICKS_PER_SECOND / config.SEND_HZ))
    delay = tick_step / SIMULATED_TICKS_PER_SECOND

    logger.info(
        "simulating a full day in ~%.0fs (%d ticks/step, %.3fs/step)%s",
        SIMULATED_DAY_SECONDS, tick_step, delay,
        "" if use_bulb else " [--no-bulb: printing instead of sending]",
    )
    try:
        for tick in range(0, 24000, tick_step):
            state = resolve({
                "tick": tick, "rain": 0.0, "thunder": 0.0, "lightning": 0,
                "skyLight": 15, "blockLight": 0, "dimension": "minecraft:overworld",
            })
            sent = await driver.update(state)
            if sent and not use_bulb:
                print(
                    f"tick={tick:5d}  rgb={state.rgb}  "
                    f"brightness={state.brightness:5.1f}  kelvin={state.kelvin}"
                )
            await asyncio.sleep(delay)
        logger.info("simulated day complete")
    finally:
        await bulb.async_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--simulate", action="store_true",
        help="replay a full day in ~30s instead of listening for the mod",
    )
    parser.add_argument(
        "--no-bulb", action="store_true",
        help="with --simulate, print resolved colours instead of driving the real bulb",
    )
    args = parser.parse_args()

    if args.no_bulb and not args.simulate:
        parser.error("--no-bulb only makes sense together with --simulate")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        if args.simulate:
            asyncio.run(run_simulation(use_bulb=not args.no_bulb))
        else:
            asyncio.run(run_listener())
    except KeyboardInterrupt:
        logger.info("stopped")


if __name__ == "__main__":
    main()
