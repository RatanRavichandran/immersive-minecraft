"""Tests for bulb.py's rate limiter, easing, dedupe, and on/off tracking.
A FakeBulb stands in for pywizlight — nothing here touches the network or
the real bulb. See PLAN.md section 8 and TASKS.md Task 2.8.
"""

from __future__ import annotations

import pytest
from pywizlight.utils import hex_to_percent

import config
from bulb import BulbDriver, percent_to_raw, split_white
from skymodel import LightState

# PilotBuilder(brightness=X) treats X as a 0-255 "raw" value but converts it
# through pywizlight's own hex_to_percent() before storing it as the wire
# "dimming" field (and back again on readback, which is what made the M0
# manual round-trip test look like an identity mapping). Tests that inspect
# pilot_params["dimming"] must go through the same conversion to compare
# against config.py's RAW_MIN/RAW_MAX/FLASH_MAX correctly.
def wire_dimming(raw: float) -> int:
    return hex_to_percent(raw)


class FakeBulb:
    """Records every call instead of sending UDP anywhere."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def turn_on(self, pilot_builder):
        self.calls.append(("on", dict(pilot_builder.pilot_params)))

    async def turn_off(self):
        self.calls.append(("off",))


def rgb_state(brightness: float, rgb: tuple[int, int, int], flash: bool = False) -> LightState:
    return LightState(rgb=rgb, brightness=brightness, flash=flash)


OFF = LightState(rgb=(0, 0, 0), brightness=0, flash=False)
FLASH = LightState(rgb=(255, 250, 235), brightness=100, flash=True)
INTERVAL = 1.0 / config.SEND_HZ


# --- pure helpers ------------------------------------------------------------


class TestPureHelpers:
    def test_percent_to_raw_spans_the_configured_envelope(self):
        assert percent_to_raw(0, flash=False) == config.RAW_MIN
        assert percent_to_raw(100, flash=False) == config.RAW_MAX
        mid = percent_to_raw(50, flash=False)
        assert config.RAW_MIN < mid < config.RAW_MAX

    def test_percent_to_raw_flash_uses_flash_max_regardless_of_percent(self):
        assert percent_to_raw(0, flash=True) == config.FLASH_MAX
        assert percent_to_raw(100, flash=True) == config.FLASH_MAX

    def test_split_white_pulls_the_shared_minimum_into_white(self):
        # mix=1.0 (the old default): full min(r,g,b) borrowed evenly.
        assert split_white(105, 118, 135, mix=1.0) == (0, 13, 30, 105)
        assert split_white(255, 147, 41, mix=1.0) == (214, 106, 0, 41)
        assert split_white(10, 10, 10, mix=1.0) == (0, 0, 0, 10)

    def test_split_white_mix_zero_is_pure_colour(self):
        # config.WHITE_MIX's current value (2026-09-14): no white borrowed
        # at all, full saturation on the colour LEDs alone.
        assert split_white(105, 118, 135, mix=0.0) == (105, 118, 135, 0)
        assert split_white(80, 160, 255, mix=0.0) == (80, 160, 255, 0)

    def test_split_white_mix_is_proportional(self):
        assert split_white(100, 100, 100, mix=0.5) == (50, 50, 50, 50)


# --- rule 1: hard rate ceiling ------------------------------------------------


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_never_exceeds_send_hz(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        sent = 0
        for _ in range(50):
            if await driver.update(rgb_state(80, (80, 160, 255)), now=t):
                sent += 1
            t += 0.01  # far faster than SEND_HZ allows
        # 50 * 0.01s = 0.5s of wall time; SEND_HZ=2.0 allows at most ~2 sends in it
        assert sent <= int(0.5 * config.SEND_HZ) + 1

    @pytest.mark.asyncio
    async def test_flash_still_respects_the_rate_limit(self):
        # This is the one PLAN.md is explicit about: lightning is exempt
        # from easing and dedupe (rules 2/3) but NOT from the send-rate
        # ceiling (rule 1) — a real storm firing several strikes in one
        # second must not be able to spam the bulb past its lockup point.
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        assert await driver.update(rgb_state(50, (150, 195, 255)), now=0.0) is True
        assert await driver.update(FLASH, now=0.001) is False
        assert len(bulb.calls) == 1


# --- rule 3: dedupe -----------------------------------------------------------


class TestDedupe:
    @pytest.mark.asyncio
    async def test_identical_resolved_payload_is_not_resent(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        state = rgb_state(80, (80, 160, 255))
        assert await driver.update(state, now=0.0) is True
        assert await driver.update(state, now=INTERVAL * 2) is False
        assert len(bulb.calls) == 1


# --- rule 2/3 together: easing converges, then goes quiet ---------------------


class TestEasing:
    @pytest.mark.asyncio
    async def test_first_update_snaps_straight_to_target(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        target = rgb_state(80, (80, 160, 255))
        assert await driver.update(target, now=0.0) is True
        _, params = bulb.calls[-1]
        assert params["dimming"] == wire_dimming(percent_to_raw(80, flash=False))
        r, g, b, w = split_white(80, 160, 255, mix=config.WHITE_MIX)
        assert (params["r"], params["g"], params["b"], params["c"], params["w"]) == (r, g, b, w, w)

    @pytest.mark.asyncio
    async def test_a_large_jump_eases_in_over_several_updates_then_stops_sending(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        # A small but nonzero baseline — brightness=0 exactly is the "off"
        # path (tested separately below) and never touches easing at all.
        await driver.update(rgb_state(5, (80, 160, 255)), now=t)
        t += INTERVAL

        target = rgb_state(100, (80, 160, 255))  # raw target = RAW_MAX, a big jump
        sent = []
        for _ in range(40):
            if await driver.update(target, now=t):
                sent.append(bulb.calls[-1][1]["dimming"])
            t += INTERVAL

        assert len(sent) >= 2, "a jump this big must not resolve in a single send"
        assert sent[0] < wire_dimming(config.RAW_MAX), "first step must be partway, not a snap"
        assert sent[-1] == wire_dimming(config.RAW_MAX)
        assert sent == sorted(sent), "must approach monotonically, never overshoot and bounce"

    @pytest.mark.asyncio
    async def test_colour_eases_toward_a_new_target_rather_than_snapping(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        await driver.update(rgb_state(50, (255, 152, 66)), now=t)  # sunset orange
        t += INTERVAL
        await driver.update(rgb_state(50, (80, 160, 255)), now=t)  # jump to noon blue
        _, params = bulb.calls[-1]
        # still mid-ease toward the new colour, not already arrived
        r, g, b, w = split_white(80, 160, 255, mix=config.WHITE_MIX)
        assert (params["r"], params["g"], params["b"], params["c"], params["w"]) != (r, g, b, w, w)


# --- rule 4: lightning bypasses both easing and dedupe ------------------------


class TestFlash:
    @pytest.mark.asyncio
    async def test_flash_snaps_to_the_flash_cap_not_raw_max(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        await driver.update(rgb_state(20, (34, 50, 126)), now=t)
        t += INTERVAL
        assert await driver.update(FLASH, now=t) is True
        _, params = bulb.calls[-1]
        assert params["dimming"] == wire_dimming(config.FLASH_MAX)

    @pytest.mark.asyncio
    async def test_repeated_identical_flash_is_not_deduped(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        assert await driver.update(FLASH, now=t) is True
        t += INTERVAL
        assert await driver.update(FLASH, now=t) is True
        assert len(bulb.calls) == 2


# --- rule 5: on/off transition -------------------------------------------------


class TestOnOff:
    @pytest.mark.asyncio
    async def test_turn_off_fires_once_at_the_transition(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        assert await driver.update(OFF, now=t) is True
        assert bulb.calls[-1] == ("off",)
        t += INTERVAL
        assert await driver.update(OFF, now=t) is False
        assert sum(1 for c in bulb.calls if c == ("off",)) == 1

    @pytest.mark.asyncio
    async def test_coming_back_on_after_off_snaps_immediately(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        await driver.update(OFF, now=t)
        t += INTERVAL
        lit = rgb_state(80, (80, 160, 255))
        assert await driver.update(lit, now=t) is True
        _, params = bulb.calls[-1]
        assert params["dimming"] == wire_dimming(percent_to_raw(80, flash=False))
