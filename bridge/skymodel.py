"""Pure functions from game state to a light target. No I/O anywhere in this
module — that is what makes it testable with no bulb and no running game
(PLAN.md section 4). See PLAN.md section 7 for the full design writeup;
this module mirrors it section by section.

Pipeline, in order (resolve() at the bottom wires it all together):

    keyframes (7.1) -> weather (7.2) -> exposure/cave blend (7.3)

...with dimensions (7.4) bypassing all three entirely when applicable.

Colour is always RGB, at every tick, no exceptions. An earlier version
switched daytime to the bulb's white/colour-temperature LEDs for extra
brightness — that channel is physically incapable of true blue, so noon
read as washed-out white instead of sky blue. Removed 2026-09-13 per user
feedback: the light should track the sky's actual colour through the whole
cycle. See PLAN.md section 7.1 for the fuller writeup.
"""

from __future__ import annotations

import bisect
from typing import NamedTuple

Rgb = tuple[int, int, int]


class LightState(NamedTuple):
    """What the bulb should show right now.

    ``brightness`` is 0-100 (percent), not a raw pywizlight unit — mapping
    to raw units and applying RAW_MIN/RAW_MAX/FLASH_MAX lives in bulb.py,
    which is the only place config.py's calibration constants belong.
    """

    rgb: Rgb
    brightness: float
    flash: bool  # True during a lightning strike: bypass easing/dedupe


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_rgb(a: Rgb, b: Rgb, t: float) -> Rgb:
    return (
        round(_clamp(_lerp(a[0], b[0], t), 0, 255)),
        round(_clamp(_lerp(a[1], b[1], t), 0, 255)),
        round(_clamp(_lerp(a[2], b[2], t), 0, 255)),
    )


# --- 7.1 Keyframes -------------------------------------------------------

# (tick, rgb, brightness 0-100). The final row is tick 24000, identical to
# tick 0 — it exists so the wrap is just another segment, not a special
# case.
#
# The daytime span (1000-11000) has been retuned toward blue twice now.
# Original (205,228,255)/(175,212,255)/(200,215,255) had only a ~50-unit
# gap between the highest and lowest channel — read as pale white-ish on
# an RGB LED, not sky blue. 2026-09-13 roughly doubled that gap. Still not
# blue enough per 2026-09-14 feedback, so R and G were both cut further
# here, pushing the blue/red gap past 160 at every daytime keyframe (was
# ~110). Revisit during Task 3.5 calibration if it's too saturated now.
KEYFRAMES: list[tuple[int, Rgb, float]] = [
    (0, (255, 140, 60), 22),  # first light
    (1000, (90, 160, 255), 78),  # day begins
    (6000, (40, 130, 255), 100),  # noon — peak sky blue
    (11000, (85, 155, 250), 80),  # late afternoon, warming back down
    (12000, (255, 152, 66), 50),  # sunset
    (12800, (196, 84, 92), 20),  # last red
    (13800, (38, 48, 120), 8),  # night, mobs spawn
    (18000, (22, 32, 96), 5),  # midnight
    (22200, (34, 50, 126), 8),
    (23000, (150, 96, 150), 15),  # pre-dawn violet
    (23600, (255, 132, 72), 24),
    (24000, (255, 140, 60), 22),  # wraps to 0
]

_KEYFRAME_TICKS = [k[0] for k in KEYFRAMES]
_KEYFRAME_BY_TICK = {k[0]: k for k in KEYFRAMES}


def sky_at_tick(tick: int) -> LightState:
    """The overworld sky colour/brightness for a tick, with no weather or
    exposure applied. Wraps at 24000. Pure keyframe interpolation — this is
    the function Task 2.7's continuity sweep tests directly.

    A tick that lands exactly on a keyframe is looked up directly rather
    than interpolated, purely to keep table rows bit-exact (no float
    rounding drift) — not load-bearing for correctness the way it used to
    be back when kelvin made the two neighbouring segments genuinely
    disagree at the boundary.
    """
    tick = tick % 24000

    exact = _KEYFRAME_BY_TICK.get(tick)
    if exact is not None:
        _, rgb, brightness = exact
        return LightState(rgb=rgb, brightness=brightness, flash=False)

    idx = bisect.bisect_right(_KEYFRAME_TICKS, tick) - 1
    idx = max(0, min(idx, len(KEYFRAMES) - 2))
    t0, rgb0, b0 = KEYFRAMES[idx]
    t1, rgb1, b1 = KEYFRAMES[idx + 1]

    t = (tick - t0) / (t1 - t0)

    rgb = _lerp_rgb(rgb0, rgb1, t)
    brightness = _lerp(b0, b1, t)

    return LightState(rgb=rgb, brightness=brightness, flash=False)


# --- 7.2 Weather -----------------------------------------------------------

_STORM_RGB: Rgb = (105, 118, 135)
_LIGHTNING_RGB: Rgb = (255, 250, 235)
_LIGHTNING_BRIGHTNESS = 100.0  # full-scale; bulb.py caps this at FLASH_MAX


def apply_weather(sky: LightState, rain: float, thunder: float, lightning: int) -> LightState:
    """PLAN.md section 7.2. ``rain``/``thunder`` are 0-1 gradients, already
    smoothed by the game (PLAN.md is explicit: don't add more smoothing on
    top). ``lightning`` is ticks remaining on the flash, 0 when none.
    """
    rain = _clamp(rain, 0.0, 1.0)
    thunder = _clamp(thunder, 0.0, 1.0)
    storm = max(rain, thunder)

    rgb = _lerp_rgb(sky.rgb, _STORM_RGB, storm * 0.7)
    brightness = _clamp(sky.brightness * (1.0 - 0.5 * rain - 0.35 * thunder), 0.0, 100.0)

    if lightning > 0:
        # Full override: a flash reads the same regardless of how heavy the
        # storm already was. The exposure blend below still dilutes this
        # toward torchlight if you're not actually under open sky.
        return LightState(rgb=_LIGHTNING_RGB, brightness=_LIGHTNING_BRIGHTNESS, flash=True)

    return LightState(rgb=rgb, brightness=brightness, flash=False)


# --- 7.3 Sky exposure and caves --------------------------------------------

_TORCH_RGB: Rgb = (255, 147, 41)


def apply_exposure(weathered: LightState, sky_light: int, block_light: int) -> LightState:
    """PLAN.md section 7.3. ``sky_light``/``block_light`` are the raw 0-15
    values from the wire protocol. ``exposure`` measures whether there is a
    path to the sky, not how bright it is — it stays 15 at midnight in the
    open, which is exactly what makes it a clean indoors/outdoors signal.

    At exposure 0 this is pure torchlight and time of day is ignored
    entirely; at exposure 1 it is the untouched weathered sky. The
    blockLight==0, exposure==0 unlit-cave blackout falls out of the torch
    brightness formula for free (0 ** 0.7 == 0) — no special case needed.
    """
    exposure = _clamp(sky_light / 15.0, 0.0, 1.0)
    block_light = max(0, min(15, block_light))

    torch_brightness = 18.0 * (block_light / 15.0) ** 0.7
    torch = LightState(rgb=_TORCH_RGB, brightness=torch_brightness, flash=False)

    rgb = _lerp_rgb(torch.rgb, weathered.rgb, exposure)
    brightness = _lerp(torch.brightness, weathered.brightness, exposure)

    # flash propagates unconditionally: at low exposure the blended colour
    # is already mostly/fully torch, so bypassing easing for it is at worst
    # a no-op, never a visible artifact.
    return LightState(rgb=rgb, brightness=brightness, flash=weathered.flash)


# --- 7.4 Dimensions ---------------------------------------------------------

_NETHER = LightState(rgb=(190, 62, 28), brightness=30, flash=False)
_END = LightState(rgb=(58, 30, 82), brightness=11, flash=False)

_DIMENSION_OVERRIDES = {
    "minecraft:the_nether": _NETHER,
    "minecraft:the_end": _END,
}


# --- Top-level resolve -------------------------------------------------------


def resolve(state: dict) -> LightState:
    """The full pipeline, from one telemetry packet to one LightState.

    Expects the wire-protocol fields from PLAN.md section 6: tick, rain,
    thunder, lightning, skyLight, blockLight, dimension. (y and skyColor are
    accepted but unused in v1, per PLAN.md.) Unknown dimension ids fall
    through to the overworld path rather than erroring.
    """
    dimension = state.get("dimension", "minecraft:overworld")
    override = _DIMENSION_OVERRIDES.get(dimension)
    if override is not None:
        return override

    sky = sky_at_tick(int(state.get("tick", 0)))
    weathered = apply_weather(
        sky,
        rain=float(state.get("rain", 0.0)),
        thunder=float(state.get("thunder", 0.0)),
        lightning=int(state.get("lightning", 0)),
    )
    return apply_exposure(
        weathered,
        sky_light=int(state.get("skyLight", 15)),
        block_light=int(state.get("blockLight", 0)),
    )
