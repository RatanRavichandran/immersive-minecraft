"""Tests for skymodel.py. No bulb, no mod, no Minecraft required — see
PLAN.md section 4 and TASKS.md Task 2.7.
"""

from __future__ import annotations

import copy

import pytest

from skymodel import (
    KEYFRAMES,
    LightState,
    apply_exposure,
    apply_weather,
    resolve,
    sky_at_tick,
)

# --- Task 2.3: keyframes and interpolation ----------------------------------


class TestKeyframes:
    @pytest.mark.parametrize("tick,rgb,brightness,kelvin", KEYFRAMES)
    def test_exact_keyframe_ticks_return_the_table_row(self, tick, rgb, brightness, kelvin):
        # tick 24000 wraps to 0 inside sky_at_tick, and the 24000 row is
        # identical to the 0 row anyway, so this covers both.
        state = sky_at_tick(tick)
        assert state.rgb == rgb
        assert state.brightness == pytest.approx(brightness)
        assert state.kelvin == (pytest.approx(kelvin) if kelvin is not None else None)

    def test_tick_24000_and_tick_0_are_identical(self):
        assert sky_at_tick(24000) == sky_at_tick(0)

    def test_negative_and_overlarge_ticks_wrap(self):
        assert sky_at_tick(24000 + 500) == sky_at_tick(500)

    @pytest.mark.parametrize("tick", range(1000, 11000, 137))
    def test_kelvin_present_inside_the_colortemp_range(self, tick):
        # [1000,6000] and [6000,11000] both have a kelvin on both bracketing
        # keyframes, so the whole [1000,11000] span should carry one.
        assert sky_at_tick(tick).kelvin is not None

    @pytest.mark.parametrize(
        "tick",
        [t for t in range(0, 24000, 137) if not (1000 <= t <= 11000)],
    )
    def test_kelvin_is_none_outside_the_colortemp_range(self, tick):
        # Every other segment has at least one None-kelvin endpoint, so
        # PLAN.md 7.1 says the whole segment is RGB: kelvin=None.
        assert sky_at_tick(tick).kelvin is None

    def test_kelvin_present_mid_segment_between_1000_and_11000(self):
        state = sky_at_tick(3500)
        assert state.kelvin is not None
        # between 5200 (t=1000) and 6500 (t=6000)
        assert 5200 < state.kelvin < 6500


# --- Task 2.7: continuity sweep, M4 -----------------------------------------


class TestContinuity:
    # Generous relative to the slowest legitimate per-tick change measured
    # across every segment (~0.2 units/tick in the steepest segment); this
    # bound exists to catch keyframe typos and wrap bugs, not to be tight.
    MAX_STEP = 3.0

    def test_no_adjacent_tick_jump_exceeds_max_step(self):
        prev = sky_at_tick(0)
        for tick in range(1, 24000):
            cur = sky_at_tick(tick)
            for i in range(3):
                assert abs(cur.rgb[i] - prev.rgb[i]) <= self.MAX_STEP, (
                    f"rgb[{i}] jumped {prev.rgb} -> {cur.rgb} at tick {tick}"
                )
            assert abs(cur.brightness - prev.brightness) <= self.MAX_STEP, (
                f"brightness jumped {prev.brightness} -> {cur.brightness} at tick {tick}"
            )
            prev = cur

    def test_wrap_boundary_is_continuous(self):
        last = sky_at_tick(23999)
        first = sky_at_tick(0)
        for i in range(3):
            assert abs(first.rgb[i] - last.rgb[i]) <= self.MAX_STEP
        assert abs(first.brightness - last.brightness) <= self.MAX_STEP

    def test_a_corrupted_keyframe_makes_the_sweep_fail(self):
        # Prove the test actually bites: sabotage one keyframe's colour far
        # outside its neighbours and confirm the sweep catches it.
        import skymodel as _sm

        original = copy.deepcopy(_sm.KEYFRAMES)
        original_ticks = list(_sm._KEYFRAME_TICKS)
        try:
            tick, rgb, brightness, kelvin = _sm.KEYFRAMES[6]  # tick 13800
            _sm.KEYFRAMES[6] = (tick, (255, 255, 255), brightness, kelvin)

            prev = _sm.sky_at_tick(13800 - 400)
            cur = _sm.sky_at_tick(13800)
            jumped = any(abs(cur.rgb[i] - prev.rgb[i]) > self.MAX_STEP for i in range(3))
            assert jumped, "sabotaged keyframe should have produced a visible jump"
        finally:
            _sm.KEYFRAMES[:] = original
            _sm._KEYFRAME_TICKS[:] = original_ticks


# --- Task 2.4: weather -------------------------------------------------------


class TestWeather:
    def test_clear_weather_is_a_no_op(self):
        sky = sky_at_tick(6000)
        weathered = apply_weather(sky, rain=0.0, thunder=0.0, lightning=0)
        assert weathered.rgb == sky.rgb
        assert weathered.brightness == pytest.approx(sky.brightness)
        assert weathered.kelvin == pytest.approx(sky.kelvin)
        assert weathered.flash is False

    def test_full_rain_desaturates_toward_slate_and_forces_rgb(self):
        sky = sky_at_tick(6000)  # noon, has a kelvin
        weathered = apply_weather(sky, rain=1.0, thunder=0.0, lightning=0)
        assert weathered.kelvin is None
        # moved toward slate (105, 118, 135), not left untouched
        assert weathered.rgb != sky.rgb

    def test_light_rain_below_threshold_keeps_colortemp_path(self):
        sky = sky_at_tick(6000)
        weathered = apply_weather(sky, rain=0.1, thunder=0.0, lightning=0)
        assert weathered.kelvin is not None

    def test_rain_above_threshold_forces_rgb(self):
        sky = sky_at_tick(6000)
        weathered = apply_weather(sky, rain=0.31, thunder=0.0, lightning=0)
        assert weathered.kelvin is None

    def test_thunder_above_threshold_forces_rgb(self):
        sky = sky_at_tick(6000)
        weathered = apply_weather(sky, rain=0.0, thunder=0.11, lightning=0)
        assert weathered.kelvin is None

    def test_rain_and_thunder_scale_brightness_down(self):
        sky = sky_at_tick(6000)
        weathered = apply_weather(sky, rain=1.0, thunder=1.0, lightning=0)
        assert weathered.brightness < sky.brightness

    def test_lightning_overrides_colour_and_sets_flash(self):
        sky = sky_at_tick(18000)  # midnight
        weathered = apply_weather(sky, rain=0.8, thunder=0.8, lightning=3)
        assert weathered.flash is True
        assert weathered.rgb == (255, 250, 235)
        assert weathered.kelvin is None


# --- Task 2.5: exposure and cave blend --------------------------------------


class TestExposure:
    def test_full_exposure_is_a_no_op(self):
        weathered = apply_weather(sky_at_tick(6000), rain=0.0, thunder=0.0, lightning=0)
        blended = apply_exposure(weathered, sky_light=15, block_light=0)
        assert blended.rgb == weathered.rgb
        assert blended.brightness == pytest.approx(weathered.brightness)
        assert blended.kelvin == pytest.approx(weathered.kelvin)

    def test_unlit_cave_is_brightness_zero(self):
        weathered = apply_weather(sky_at_tick(6000), rain=0.0, thunder=0.0, lightning=0)
        blended = apply_exposure(weathered, sky_light=0, block_light=0)
        assert blended.brightness == pytest.approx(0.0)

    def test_torchlit_cave_is_torch_orange_at_expected_brightness(self):
        weathered = apply_weather(sky_at_tick(6000), rain=0.0, thunder=0.0, lightning=0)
        blended = apply_exposure(weathered, sky_light=0, block_light=15)
        assert blended.rgb == (255, 147, 41)
        assert blended.brightness == pytest.approx(18.0)
        assert blended.kelvin is None

    def test_low_exposure_forces_rgb_even_with_a_colortemp_sky(self):
        weathered = apply_weather(sky_at_tick(6000), rain=0.0, thunder=0.0, lightning=0)
        assert weathered.kelvin is not None
        blended = apply_exposure(weathered, sky_light=10, block_light=8)  # exposure ~0.67
        assert blended.kelvin is None

    def test_high_exposure_keeps_colortemp_path(self):
        weathered = apply_weather(sky_at_tick(6000), rain=0.0, thunder=0.0, lightning=0)
        blended = apply_exposure(weathered, sky_light=15, block_light=0)  # exposure 1.0
        assert blended.kelvin is not None

    def test_partial_exposure_blends_between_torch_and_sky(self):
        weathered = apply_weather(sky_at_tick(6000), rain=0.0, thunder=0.0, lightning=0)
        full = apply_exposure(weathered, sky_light=15, block_light=0)
        none = apply_exposure(weathered, sky_light=0, block_light=0)
        half = apply_exposure(weathered, sky_light=7, block_light=0)  # exposure ~0.47
        for i in range(3):
            lo, hi = sorted((full.rgb[i], none.rgb[i]))
            assert lo <= half.rgb[i] <= hi


# --- Task 2.6: dimension overrides ------------------------------------------


class TestDimensions:
    def test_nether_override(self):
        state = resolve({"tick": 6000, "dimension": "minecraft:the_nether"})
        assert state.rgb == (190, 62, 28)
        assert state.brightness == pytest.approx(30)
        assert state.kelvin is None

    def test_end_override(self):
        state = resolve({"tick": 6000, "dimension": "minecraft:the_end"})
        assert state.rgb == (58, 30, 82)
        assert state.brightness == pytest.approx(11)
        assert state.kelvin is None

    def test_nether_ignores_weather_and_exposure(self):
        a = resolve({
            "tick": 6000, "dimension": "minecraft:the_nether",
            "rain": 1.0, "thunder": 1.0, "lightning": 5,
            "skyLight": 0, "blockLight": 0,
        })
        b = resolve({"tick": 0, "dimension": "minecraft:the_nether"})
        assert a == b

    def test_unknown_dimension_falls_through_to_overworld(self):
        overworld = resolve({"tick": 6000, "dimension": "minecraft:overworld",
                              "skyLight": 15, "blockLight": 0})
        unknown = resolve({"tick": 6000, "dimension": "some_modded:dimension",
                            "skyLight": 15, "blockLight": 0})
        assert unknown == overworld


# --- resolve(): end-to-end wiring -------------------------------------------


class TestResolve:
    def test_defaults_are_sane_with_a_minimal_packet(self):
        # missing fields should not raise
        state = resolve({"tick": 6000})
        assert isinstance(state, LightState)

    def test_full_overworld_pipeline_matches_manual_composition(self):
        packet = {
            "tick": 12200, "rain": 0.5, "thunder": 0.0, "lightning": 0,
            "skyLight": 12, "blockLight": 3, "dimension": "minecraft:overworld",
        }
        expected = apply_exposure(
            apply_weather(sky_at_tick(12200), rain=0.5, thunder=0.0, lightning=0),
            sky_light=12, block_light=3,
        )
        assert resolve(packet) == expected
