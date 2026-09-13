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


def colortemp_state(brightness: float, kelvin: float, flash: bool = False) -> LightState:
    return LightState(rgb=(255, 255, 255), brightness=brightness, kelvin=kelvin, flash=flash)


def rgb_state(brightness: float, rgb: tuple[int, int, int], flash: bool = False) -> LightState:
    return LightState(rgb=rgb, brightness=brightness, kelvin=None, flash=flash)


OFF = LightState(rgb=(0, 0, 0), brightness=0, kelvin=None, flash=False)
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
        assert split_white(105, 118, 135) == (0, 13, 30, 105)
        assert split_white(255, 147, 41) == (214, 106, 0, 41)
        assert split_white(10, 10, 10) == (0, 0, 0, 10)


# --- rule 1: hard rate ceiling ------------------------------------------------


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_never_exceeds_send_hz(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        sent = 0
        for _ in range(50):
            if await driver.update(colortemp_state(80, 6000), now=t):
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
        assert await driver.update(colortemp_state(50, 5000), now=0.0) is True
        flash = LightState(rgb=(255, 250, 235), brightness=100, kelvin=None, flash=True)
        assert await driver.update(flash, now=0.001) is False
        assert len(bulb.calls) == 1


# --- rule 3: dedupe -----------------------------------------------------------


class TestDedupe:
    @pytest.mark.asyncio
    async def test_identical_resolved_payload_is_not_resent(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        state = colortemp_state(80, 6000)
        assert await driver.update(state, now=0.0) is True
        assert await driver.update(state, now=INTERVAL * 2) is False
        assert len(bulb.calls) == 1


# --- rule 2/3 together: easing converges, then goes quiet ---------------------


class TestEasing:
    @pytest.mark.asyncio
    async def test_first_update_snaps_straight_to_target(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        target = colortemp_state(80, 6000)
        assert await driver.update(target, now=0.0) is True
        _, params = bulb.calls[-1]
        assert params["dimming"] == wire_dimming(percent_to_raw(80, flash=False))
        assert params["temp"] == 6000

    @pytest.mark.asyncio
    async def test_a_large_jump_eases_in_over_several_updates_then_stops_sending(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        # A small but nonzero baseline — brightness=0 exactly is the "off"
        # path (tested separately below) and never touches easing at all.
        await driver.update(colortemp_state(5, 5000), now=t)
        t += INTERVAL

        target = colortemp_state(100, 5000)  # raw target = RAW_MAX, a big jump
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
    async def test_switching_channel_snaps_colour_but_keeps_easing_brightness(self):
        # Colour and brightness are independent axes. There is no sensible
        # "ease between" an RGB triple and a kelvin value, so colour snaps
        # fresh on a channel switch — but brightness is the same continuous
        # quantity on both paths (PilotBuilder's brightness= kwarg either
        # way), so it keeps right on easing through the switch. That is a
        # deliberate choice: it smooths out exactly the channel-switch
        # brightness step flagged in TASKS.md's open questions, rather than
        # compounding it with an extra snap.
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        await driver.update(rgb_state(50, (255, 152, 66)), now=t)
        t += INTERVAL
        await driver.update(colortemp_state(80, 6000), now=t)
        _, params = bulb.calls[-1]
        assert params["temp"] == 6000  # colour snapped straight to the new target
        eased_brightness_target = percent_to_raw(80, flash=False)
        assert params["dimming"] != wire_dimming(eased_brightness_target), (
            "brightness should still be mid-ease this soon after a jump, not already arrived"
        )


# --- rule 4: lightning bypasses both easing and dedupe ------------------------


class TestFlash:
    @pytest.mark.asyncio
    async def test_flash_snaps_to_the_flash_cap_not_raw_max(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        await driver.update(colortemp_state(20, 5000), now=t)
        t += INTERVAL
        flash = LightState(rgb=(255, 250, 235), brightness=100, kelvin=None, flash=True)
        assert await driver.update(flash, now=t) is True
        _, params = bulb.calls[-1]
        assert params["dimming"] == wire_dimming(config.FLASH_MAX)

    @pytest.mark.asyncio
    async def test_repeated_identical_flash_is_not_deduped(self):
        bulb = FakeBulb()
        driver = BulbDriver(bulb)
        t = 0.0
        flash = LightState(rgb=(255, 250, 235), brightness=100, kelvin=None, flash=True)
        assert await driver.update(flash, now=t) is True
        t += INTERVAL
        assert await driver.update(flash, now=t) is True
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
        lit = colortemp_state(80, 6000)
        assert await driver.update(lit, now=t) is True
        _, params = bulb.calls[-1]
        assert params["dimming"] == wire_dimming(percent_to_raw(80, flash=False))
