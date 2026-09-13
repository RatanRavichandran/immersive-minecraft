"""UDP receiver for the mod's telemetry datagrams (PLAN.md section 6).

One JSON object per datagram, full state every time, no deltas. This module
only parses and hands off — it holds no game-state knowledge itself so it
can't drift out of sync with skymodel.py's expectations.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

PacketCallback = Callable[[dict[str, Any]], None]


class TelemetryProtocol(asyncio.DatagramProtocol):
    """Parses incoming datagrams as JSON and forwards the dict to a callback.

    Malformed datagrams are logged and dropped, never raised — one garbled
    packet must not take the listener down. The next one arrives in half a
    second carrying full state anyway (PLAN.md section 3: fire-and-forget
    UDP, full state not a delta).
    """

    def __init__(self, on_packet: PacketCallback) -> None:
        self._on_packet = on_packet

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("dropping malformed datagram from %s: %s", addr, exc)
            return

        if not isinstance(payload, dict):
            logger.warning("dropping non-object datagram from %s: %r", addr, payload)
            return

        try:
            self._on_packet(payload)
        except Exception:
            # A bug in the callback (skymodel/bulb) must not kill the
            # listener either — log it and keep receiving.
            logger.exception("packet callback raised for payload: %r", payload)

    def error_received(self, exc: Exception) -> None:
        logger.warning("UDP listener error: %s", exc)


async def start_listener(
    on_packet: PacketCallback,
    host: str,
    port: int,
) -> asyncio.DatagramTransport:
    """Bind a UDP listener and return its transport.

    Call ``transport.close()`` to shut it down. Binding does not block the
    event loop — this is a plain asyncio datagram endpoint.
    """
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: TelemetryProtocol(on_packet),
        local_addr=(host, port),
    )
    logger.info("listening for telemetry on %s:%d", host, port)
    return transport
