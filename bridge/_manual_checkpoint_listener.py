"""Throwaway manual verification for the M2 transport checkpoint
(TASKS.md, PLAN.md section 5.4) — not part of the automated suite.

Prints every datagram the mod sends, with a running rate estimate, so it's
obvious at a glance whether packets are arriving at roughly 2 Hz. Run this
alongside `./gradlew runClient` in mod/.
"""

import asyncio
import time

from listener import start_listener

COUNT = 0
START = time.monotonic()


def on_packet(packet: dict) -> None:
    global COUNT
    COUNT += 1
    elapsed = time.monotonic() - START
    rate = COUNT / elapsed if elapsed > 0 else 0.0
    print(f"[{COUNT:4d}] {elapsed:6.1f}s  rate={rate:4.2f}/s  {packet}")


async def main() -> None:
    transport = await start_listener(on_packet, "127.0.0.1", 25566)
    print("listening on 127.0.0.1:25566 — Ctrl+C to stop")
    try:
        await asyncio.Event().wait()
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
