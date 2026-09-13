"""pywizlight wrapper: easing, rate limiting, dedupe. PLAN.md section 8.

Five rules, enforced here in this order:
  1. At most SEND_HZ sends per second — a hard ceiling, not a nicety. WiZ
     bulbs can lock up until power-cycled above roughly 10-15 commands/sec.
     Lightning does NOT get an exemption from this one (PLAN.md section 8
     lists only easing and dedupe as lightning-exempt).
  2. Ease toward the target rather than jumping, so 2 Hz reads as continuous.
  3. Skip the send entirely when the resolved payload equals the last one sent.
  4. Exempt lightning from both easing and dedupe.
  5. Track on/off state so turn_off() fires once at the transition, not
     repeatedly — this falls out of rule 3 for free, since a repeated
     "off" resolves to the same payload as the one already sent.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from pywizlight import PilotBuilder
from pywizlight.utils import hex_to_percent

import config
from skymodel import LightState

logger = logging.getLogger(__name__)


class WizBulb(Protocol):
    """The slice of pywizlight.wizlight this driver actually calls. Tests
    substitute a fake implementing just this, never touching the network.
    """

    async def turn_on(self, pilot_builder: PilotBuilder) -> None: ...

    async def turn_off(self) -> None: ...


def percent_to_raw(percent: float, *, flash: bool) -> int:
    """skymodel's 0-100 percent -> pywizlight's 0-255 raw unit, through
    config.py's calibrated envelope. Callers keep brightness<=0 out of
    this entirely — that means off, handled as its own path below, never
    as a raw value (PilotBuilder clamps dimming to a minimum of 1 percent,
    so there is no raw value that actually means "off").
    """
    if flash:
        return int(round(config.FLASH_MAX))
    percent = max(0.0, min(100.0, percent))
    raw = config.RAW_MIN + (percent / 100.0) * (config.RAW_MAX - config.RAW_MIN)
    return int(round(max(0.0, min(255.0, raw))))


def split_white(r: int, g: int, b: int) -> tuple[int, int, int, int]:
    """Pull the achromatic component out of an RGB triple so both white
    channels get it evenly. See TASKS.md M0 finding 4: PilotBuilder(rgb=...)
    drives warm white only and leaves cold white at 0, so every desaturated
    colour skews warm. An explicit even split keeps storm slate neutral.
    """
    w = min(r, g, b)
    return (r - w, g - w, b - w, w)


@dataclass(frozen=True)
class _Payload:
    """Only the fields that matter for "is this the same as last time" —
    two LightStates that round to the same raw command are the same bulb
    state even if the floats that produced them differ.
    """

    on: bool
    raw_brightness: int
    kelvin: Optional[int] = None
    rgb: Optional[tuple[int, int, int]] = None


_OFF = _Payload(on=False, raw_brightness=0)


def _wire_equivalent(payload: _Payload) -> tuple:
    """What the dedupe check actually compares: the command as it will hit
    the wire, not our pre-quantization raw float. PilotBuilder(brightness=X)
    quantizes X through hex_to_percent (0-255 -> 0-100) before it becomes
    the "dimming" field, so several distinct raw_brightness values near
    convergence can all round to the same byte on the wire — sending each
    of those would be exactly the redundant traffic PLAN.md section 8 wants
    dedupe to suppress ("a stable afternoon should produce almost no
    traffic"). The rgb/rgbww channel values themselves are NOT quantized
    this way (pywizlight sends them as given), only the brightness kwarg is.
    """
    if not payload.on:
        return (False,)
    return (True, hex_to_percent(payload.raw_brightness), payload.kelvin, payload.rgb)


class BulbDriver:
    """One instance per bulb. Call update() from a single asyncio task at
    whatever rate packets arrive — it self-limits to SEND_HZ internally, so
    callers never need their own throttling.
    """

    def __init__(self, bulb: WizBulb) -> None:
        self._bulb = bulb
        self._min_interval = 1.0 / config.SEND_HZ
        self._last_send_at: float = float("-inf")
        # Deliberately None, not _OFF: we don't actually know the physical
        # bulb's state at startup (it may have been left on from a previous
        # run), so the first update() must always send regardless of what
        # it resolves to, never assume-and-dedupe against a guess.
        self._last_sent: Optional[_Payload] = None
        self._eased_brightness: Optional[float] = None
        self._eased_rgb: Optional[tuple[float, float, float]] = None
        self._eased_kelvin: Optional[float] = None

    async def update(self, state: LightState, *, now: Optional[float] = None) -> bool:
        """Feed one resolved LightState in. Returns True if a UDP send
        actually happened — useful for tests and logging — or False if the
        rate limiter, the dedupe check, or "nothing changed" skipped it.
        """
        now = time.monotonic() if now is None else now

        if state.brightness <= 0 and not state.flash:
            return await self._maybe_send(_OFF, now, bypass_dedupe=False)

        target_brightness = percent_to_raw(state.brightness, flash=state.flash)
        if state.kelvin is None:
            target_brightness = int(round(
                max(0.0, min(255.0, target_brightness * config.RGB_BRIGHTNESS_COMPENSATION))
            ))

        if state.flash:
            # Rule 4: snap straight to target, no easing. Also clear the
            # eased trackers so the *next* normal update eases in from
            # here rather than from wherever the bulb was before the
            # flash interrupted it.
            brightness = float(target_brightness)
            if state.kelvin is None:
                rgb: Optional[tuple[float, float, float]] = tuple(float(c) for c in state.rgb)
                kelvin: Optional[float] = None
            else:
                rgb = None
                kelvin = float(state.kelvin)
            self._eased_brightness = None
            self._eased_rgb = None
            self._eased_kelvin = None
        else:
            brightness = self._ease(self._eased_brightness, target_brightness)
            self._eased_brightness = brightness
            if state.kelvin is not None:
                kelvin = self._ease(self._eased_kelvin, state.kelvin)
                self._eased_kelvin = kelvin
                self._eased_rgb = None
                rgb = None
            else:
                rgb = self._ease_rgb(state.rgb)
                self._eased_rgb = rgb
                self._eased_kelvin = None
                kelvin = None

        payload = _Payload(
            on=True,
            raw_brightness=int(round(brightness)),
            kelvin=int(round(kelvin)) if kelvin is not None else None,
            rgb=tuple(int(round(c)) for c in rgb) if rgb is not None else None,
        )
        return await self._maybe_send(payload, now, bypass_dedupe=state.flash)

    def _ease(self, current: Optional[float], target: float) -> float:
        if current is None:
            return target
        next_value = current + (target - current) * config.EASE
        # Snap once within a unit — raw values round to int anyway, and
        # without this an exponential approach never quite reaches its
        # target, which means dedupe (rule 3) never fires and the bulb
        # never goes quiet on a stable scene.
        return target if abs(target - next_value) < 1.0 else next_value

    def _ease_rgb(self, target: tuple[int, int, int]) -> tuple[float, float, float]:
        current = self._eased_rgb
        if current is None:
            return tuple(float(c) for c in target)
        return (
            self._ease(current[0], target[0]),
            self._ease(current[1], target[1]),
            self._ease(current[2], target[2]),
        )

    async def _maybe_send(self, payload: _Payload, now: float, *, bypass_dedupe: bool) -> bool:
        if not bypass_dedupe and self._last_sent is not None:
            if _wire_equivalent(payload) == _wire_equivalent(self._last_sent):
                return False  # rule 3 (and, for _OFF, rule 5 for free)
        if now - self._last_send_at < self._min_interval:
            return False  # rule 1 — a hard ceiling, applies even to flashes

        if payload.on:
            if payload.rgb is not None:
                r, g, b, w = split_white(*payload.rgb)
                pilot = PilotBuilder(rgbww=(r, g, b, w, w), brightness=payload.raw_brightness)
            else:
                pilot = PilotBuilder(colortemp=payload.kelvin, brightness=payload.raw_brightness)
            await self._bulb.turn_on(pilot)
        else:
            await self._bulb.turn_off()
            self._eased_brightness = None
            self._eased_rgb = None
            self._eased_kelvin = None

        self._last_send_at = now
        self._last_sent = payload
        return True
