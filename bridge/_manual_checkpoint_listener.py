"""Throwaway manual verification for Task 1.3 (real telemetry) and the M2
transport checkpoint — not part of the automated suite. Prints every
datagram with its resolved LightState alongside, so field changes from
/time set, /weather, and digging are visible directly.
"""

import asyncio
import time

from listener import start_listener
from skymodel import resolve

COUNT = 0
START = time.monotonic()


def on_packet(packet: dict) -> None:
    global COUNT
    COUNT += 1
    elapsed = time.monotonic() - START
    state = resolve(packet)
    print(
        f"[{COUNT:4d}] {elapsed:6.1f}s  {packet}\n"
        f"          -> rgb={state.rgb} brightness={state.brightness:.1f} flash={state.flash}"
    )


async def main() -> None:
    transport = await start_listener(on_packet, "127.0.0.1", 25566)
    print("listening on 127.0.0.1:25566 -- Ctrl+C to stop")
    try:
        await asyncio.Event().wait()
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
