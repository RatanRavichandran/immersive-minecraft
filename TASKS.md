# Implementation Plan: Minecraft Sky Sync

Task breakdown derived from `PLAN.md`. PLAN.md remains the design authority —
colours, constants, and rationale live there. This file is the execution order.

## Overview

Two independent processes joined by one UDP datagram. A client-side Fabric mod
reads game state each tick and emits JSON to localhost; a Python bridge models
the sky and drives a WiZ bulb. The mod is dumb, the bridge holds all logic.

## Environment: verified 2026-09-13

| Prerequisite | Status |
|---|---|
| JDK 21 | OK — `21.0.12.1 LTS` on PATH |
| Python 3.11+ | OK — `3.14.5` default; `3.13` also installed |
| Git | OK — `2.54.0` |
| 2.4 GHz Wi-Fi | OK — `TP-Link_F8F5`, ch 4, laptop at `192.168.0.105/24` |
| B22 socket | OK — confirmed |
| Bulb on LAN | OK — `192.168.0.102`, MAC `9877d5e8ade2` |
| Bulb accepts commands | OK — after enabling local control in the WiZ app |
| **M0** | **PASSED 2026-09-13** |

**Device:** module `ESP25_SHRGB_01`, firmware `1.38.0`, region `eu`,
5-channel `BP5758D` driver (RGB + CW + WW), `cctRange` 2200–6500.

## M0 findings — four things that will bite again

Recorded because each one cost time and none is discoverable from the code.

**1. Local control must be enabled in the WiZ app, per device.**
Out of the box this firmware answered every read (`getPilot`,
`getSystemConfig`, `getModelConfig`, `getUserConfig`) and even `registration`
with `success: true`, while rejecting *every* `setPilot` — including bare
`{"state":false}` — with `-32602 Invalid params`. Enabling local control in
the app fixed all of it. Tell-tale: in the locked state every response carried
`hmac` and `sigTs` fields; once unlocked, those fields disappear entirely.
**If writes start failing again, check this toggle first** — the error code
suggests a malformed payload and sends you hunting in the wrong place.

**2. `pywizlight.cli discover` has a hardcoded broadcast default.**
`-b` defaults to `192.168.1.255` with no adapter detection. This LAN is
`192.168.0.0/24`, so the bare command prints "No bulbs found" — visually
identical to the 2.4 GHz band failure in PLAN.md §11. Always pass
`-b 192.168.0.255`.

**3. `updateState()` returns a list in pywizlight 0.6.6.**
Multi-head support changed the return type. Unwrap with
`s = s[0] if isinstance(s, list) else s` before calling `get_rgb()` etc.

**4. `PilotBuilder(rgb=...)` drives warm white only — use `rgbww=` instead.**
The `rgb=` path decomposes colour into chroma plus a white component, which is
correct, but it puts all of it in warm white and leaves cold white at 0. Every
desaturated colour therefore skews warm. Measured:

| Sent | Via `rgb=` | Via `rgbww=` with explicit white split |
|---|---|---|
| slate `(105,118,135)` | `rgb=(0,22,52)` `warm=128` `cold=0` | `rgb=(0,13,30)` `warm=105` `cold=105` |
| pale day `(175,212,255)` | `rgb=(0,64,138)` `warm=128` `cold=0` | `rgb=(0,37,80)` `warm=175` `cold=175` |

This matters most for PLAN.md §7.2, where storms desaturate toward slate: on
the `rgb=` path a storm sky reads as warm grey rather than neutral. Split the
achromatic component out yourself and send it to both white channels:

```python
w = min(r, g, b)
PilotBuilder(rgbww=(r - w, g - w, b - w, w, w), brightness=...)
```

Folded into Task 2.8's acceptance criteria.

## Deviations from PLAN.md, and why

These are corrections to the handoff, not rescopes. Each is small.

1. **Windows venv activation.** PLAN.md §5 Step 2 gives
   `source .venv/bin/activate`. On this machine it is
   `.venv\Scripts\Activate.ps1`. Cosmetic but it will bite on first run.

2. **Pin the bridge to Python 3.13, not 3.14.** `pywizlight` and its transitive
   deps are unlikely to have 3.14 wheels yet. 3.13 is installed and satisfies
   the 3.11+ floor. Costs nothing now; costs an afternoon if discovered at M2.

3. **Pull `--simulate` forward from the v2 backlog (§14) into v1.** PLAN.md
   makes calibration (M9) a full uninterrupted 20-minute day in a dark room.
   Every constant tweak then costs 20 minutes. A flag that replays ticks
   0–24000 in 30 seconds with no Minecraft running is roughly 20 lines and pays
   for itself on the first tuning loop. Scheduled as Task 2.9, used by Task 3.5.
   Say the word if you would rather keep v1 to the letter and tune the slow way.

4. **Channel-switch discontinuity is unhandled in the design.** See Open
   Questions below. Folded into Task 3.5 as something to measure.

## Dependency graph

```
0.1 repo skeleton
 |
 +-- 0.2 Wi-Fi band  --GATE--> 0.3 bulb reachable (M0) ------+
 |                                                           |
 +-- TRACK A (mod, Java)          TRACK B (bridge, Python)    |
 |   1.1 scaffold builds          2.1 venv + package layout   |
 |   1.2 tick hook + UDP          2.2 UDP listener            |
 |       |                        2.3 keyframes (pure)        |
 |       |                        2.4 weather                 |
 |       |                        2.5 exposure/cave           |
 |       |                        2.6 dimensions              |
 |       |                        2.7 continuity tests        |
 |       |                        2.8 bulb driver <-----------+
 |       |                        2.9 --simulate
 |       |                             |
 |       +-------- CHECKPOINT ---------+
 |                 1.2 + 2.2 = packets print at 2 Hz (PLAN.md §5.4 gate)
 |                             |
 |   1.3 real telemetry -------+
 |                             |
 |                   2.10 main.py wiring
 |                             |
 +------------ 3.1 .. 3.7 integration, calibration, packaging
```

**Tracks A and B are fully independent** until the checkpoint. PLAN.md's linear
M0–M10 hides this. If you want to parallelize across sessions, that is the seam.
`skymodel.py` in particular needs no bulb, no mod, and no Minecraft — Tasks
2.3–2.7 are pure functions with unit tests and can be done entirely offline,
even while the Wi-Fi gate is still blocked.

---

## Phase 0: Gates and skeleton

### Task 0.1: Repo skeleton and git init

**Description:** Create the directory layout from PLAN.md §4, initialise git,
add a `.gitignore` covering `.venv/`, `__pycache__/`, `mod/build/`,
`mod/.gradle/`, and `run/`. No source logic yet — empty placeholder modules only.

**Acceptance criteria:**
- [ ] Layout matches PLAN.md §4 exactly
- [ ] `git log` shows one commit; `git status` is clean
- [ ] `.gitignore` covers build, venv, and Gradle run dirs

**Verification:** `git status --short` prints nothing.

**Dependencies:** None. **Scope:** S.

---

### Task 0.2: Resolve the 2.4 GHz Wi-Fi gate — BLOCKING, manual

**Description:** The laptop is associated at 5 GHz on channel 36 with a single
merged SSID. WiZ bulbs are 2.4 GHz only, and UDP broadcast discovery does not
cross bands on consumer routers. This must be resolved before Task 0.3 can
possibly succeed.

**Options, best first:**
1. Split the bands in the Airtel router admin page — give 2.4 GHz its own SSID
   (e.g. `Airtel_rata_7666_2G`), join the laptop to it. Permanent fix.
2. Pair the bulb via phone, reserve its IP by DHCP, then address it by IP
   directly. `pywizlight` can talk to a known IP without discovery — but only
   if the router bridges the two bands at layer 2, which most do for unicast.
3. Temporarily disable the 5 GHz radio during setup.

**Acceptance criteria:**
- [ ] `netsh wlan show interfaces` reports `Band : 2.4 GHz`, **or** the bulb's
      reserved IP answers unicast from the 5 GHz laptop
- [ ] Bulb's DHCP reservation created and IP recorded

**Verification:** `netsh wlan show interfaces | findstr Band`

**Dependencies:** None. **Scope:** manual, no files.

---

### Task 0.3: Bulb reachable — M0 — **DONE 2026-09-13**

Verified end to end through pywizlight, not just raw UDP:

| Step | Result |
|---|---|
| `discover -b 192.168.0.255` | Found `192.168.0.102` |
| `colortemp=6500, brightness=185` | `dim=186 temp=6500` — the daylight channel |
| `rgb=(255,152,66), brightness=128` | sunset orange |
| `rgb=(22,32,96), brightness=30` | midnight blue at the `RAW_MIN` floor |
| `rgb=(255,147,41), brightness=46` | torch orange |
| `turn_off()` then restore | clean |

Both channels the sky model needs — `colortemp` for day, `rgb` for everything
else — are confirmed working on real hardware.

**Acceptance criteria:**
- [x] `discover` returns the bulb's IP
- [x] Colour, colour-temperature, brightness, and on/off all work
- [ ] **Remaining:** DHCP reservation for `192.168.0.102` so the IP never
      drifts. Do this before hardcoding it in `config.py` (PLAN.md §5 Step 1.2)

**Dependencies:** 0.2. **Scope:** manual.

### CHECKPOINT: Gates

Do not start Task 2.8 or Phase 3 until 0.3 passes. Tracks A and B up to the
transport checkpoint are safe to start regardless.

---

## Phase 1: Track A — the mod

### Task 1.1: Fabric scaffold builds and launches — M1

**Description:** Generate from `fabricmc.net/develop/template` into `mod/`,
targeting MC 1.21.x + JDK 21. Mod id `skysync`, package `com.ratan.skysync`,
**client entrypoint only** — no server entrypoint, no mixins yet.

**Acceptance criteria:**
- [ ] `./gradlew build` succeeds
- [ ] `./gradlew runClient` opens Minecraft to the title screen with skysync loaded
- [ ] `fabric.mod.json` declares only `client` under `entrypoints`

**Verification:** dev client log contains the skysync mod id at startup.

**Dependencies:** 0.1. **Scope:** S (generated).

---

### Task 1.2: Tick hook and UDP emitter with placeholder payload

**Description:** `ClientTickEvents.END_CLIENT_TICK`, a counter firing every 10
ticks, one `DatagramSocket` created once and reused, sending a fixed JSON
string to `127.0.0.1:25566`. No game state read yet — this task exists purely
to isolate networking problems from modelling problems (PLAN.md §5.4).

**Acceptance criteria:**
- [ ] Fires every 10 ticks, not every tick
- [ ] Socket is created once, never per-send
- [ ] Whole send is wrapped in `catch (Throwable)` — a lighting toy must never
      stall or crash the render thread (PLAN.md §11)

**Verification:** covered by the transport checkpoint below.

**Dependencies:** 1.1. **Scope:** S. **Files:** 1–2 Java files.

---

## Phase 2: Track B — the bridge

### Task 2.1: Python package and config

**Description:** venv on **3.13** (`py -3.13 -m venv .venv`, activate with
`.venv\Scripts\Activate.ps1`), `pyproject.toml`, and `config.py` holding the
PLAN.md §8 constants verbatim — `RAW_MIN=30`, `RAW_MAX=185`, `FLASH_MAX=130`,
`SEND_HZ=2.0`, `EASE=0.22`, plus `BULB_IP` and `LISTEN_PORT=25566`.

**Acceptance criteria:**
- [ ] `pip install pywizlight pytest` succeeds on 3.13
- [ ] `config.py` carries PLAN.md's reasoning as comments — especially that
      `RAW_MIN=30` is a hardware floor, not taste, and must not be "cleaned up"
      to 0
- [ ] `python -c "import pywizlight"` exits 0

**Dependencies:** 0.1. **Scope:** S.

---

### Task 2.2: UDP listener

**Description:** `listener.py` — an asyncio `DatagramProtocol` bound to
`127.0.0.1:25566` that parses JSON and hands a dict to a callback. Malformed
datagrams are logged and dropped, never raised.

**Acceptance criteria:**
- [ ] Binds and receives without blocking the event loop
- [ ] Malformed JSON is dropped with a log line, listener survives
- [ ] Callback receives a plain dict

**Verification:** transport checkpoint below.

**Dependencies:** 2.1. **Scope:** S.

---

### CHECKPOINT: Transport — M2 (PLAN.md §5.4 gate)

Run `./gradlew runClient` and the bridge together.

- [ ] Placeholder packets print in the bridge terminal at roughly 2 Hz
- [ ] Rate is steady; no bursts, no gaps
- [ ] Closing Minecraft stops the packets; the bridge keeps running cleanly

**Do not proceed past this point until it works.** Everything after assumes
the pipe is sound.

---

### Task 2.3: Sky keyframes and interpolation — pure

**Description:** `skymodel.py`. The PLAN.md §7.1 keyframe table, linear
interpolation wrapping at 24000, returning `(rgb, brightness, kelvin|None)`.
Kelvin interpolates **only when both bracketing keyframes carry one**;
otherwise the segment is RGB. No I/O in this module, ever.

**Acceptance criteria:**
- [ ] Every keyframe tick returns its exact table row
- [ ] `tick=24000` and `tick=0` return identical values
- [ ] Segments with a `None` endpoint return `kelvin=None`

**Verification:** `pytest tests/test_skymodel.py -k keyframe`

**Dependencies:** 2.1. **Scope:** S. **Note:** no bulb, no mod, no Minecraft
needed — implementable while the Wi-Fi gate is still blocked.

---

### Task 2.4: Weather

**Description:** PLAN.md §7.2. `storm = max(rain, thunder)`; blend RGB toward
slate `(105,118,135)` by `storm*0.7`; scale brightness by
`1 - 0.5*rain - 0.35*thunder`; force RGB when `rain>0.3 or thunder>0.1`;
lightning overrides colour to `(255,250,235)` and flags bypass-easing.

**Acceptance criteria:**
- [ ] `rain=thunder=0` is a no-op against Task 2.3 output
- [ ] `rain=1.0` desaturates toward slate and returns `kelvin=None`
- [ ] Lightning sets a `flash` flag the driver can read

**Verification:** `pytest -k weather`

**Dependencies:** 2.3. **Scope:** S.

---

### Task 2.5: Sky exposure and cave blend

**Description:** PLAN.md §7.3. `exposure = skyLight/15`, linear blend of colour
and brightness between the sky result and torchlight `(255,147,41)` at
`18*(blockLight/15)**0.7`. Force RGB when `exposure<=0.7`. `blockLight==0` and
`exposure==0` yields brightness 0 — the unlit-cave blackout is deliberate.

**Acceptance criteria:**
- [ ] `exposure=1.0` is a no-op against Task 2.4 output
- [ ] `exposure=0, blockLight=0` returns brightness 0
- [ ] `exposure=0, blockLight=15` returns torch orange at brightness 18

**Verification:** `pytest -k exposure`

**Dependencies:** 2.4. **Scope:** S.

---

### Task 2.6: Dimension overrides

**Description:** PLAN.md §7.4. Nether and End bypass the overworld path
entirely — they have no sky light anywhere, so the cave blend would black them
out. Fixed RGB moods, no weather, no exposure.

**Acceptance criteria:**
- [ ] `the_nether` returns `(190,62,28)` at 30, RGB path, regardless of other
      fields
- [ ] `the_end` returns `(58,30,82)` at 11
- [ ] Unknown dimension ids fall through to the overworld path

**Verification:** `pytest -k dimension`

**Dependencies:** 2.5. **Scope:** XS.

---

### Task 2.7: Continuity test sweep — M4

**Description:** PLAN.md §9's specific ask. Sweep every tick 0–24000 and assert
no adjacent-tick jump in brightness or any RGB channel exceeds a small delta.
Include the 24000 to 0 wrap. This catches keyframe typos and wrap bugs with no
bulb and no running game.

**Acceptance criteria:**
- [x] Full 0–24000 sweep passes the adjacent-delta assertion
- [x] Wrap boundary is explicitly asserted, not just implied
- [x] A deliberately corrupted keyframe makes the test fail (verify the test
      actually bites)

**Status: done, 226 tests total across the bridge.** The sweep caught a real
bug on its first run: at tick 11000 exactly — the shared boundary between
the kelvin segment `[6000,11000]` and the forced-RGB segment `[11000,12000]`
— interpolating via "which segment starts here" silently picked the RGB
segment and dropped that keyframe's own `kelvin=5000`. Fixed by looking up
an exact keyframe tick directly rather than interpolating into it; see
`skymodel.sky_at_tick`'s docstring.

**Verification:** `pytest tests/test_skymodel.py`

**Dependencies:** 2.6. **Scope:** S.

---

### Task 2.8: Bulb driver

**Description:** `bulb.py` — a `pywizlight` wrapper implementing all five
rate-limit rules from PLAN.md §8. Sends at most `SEND_HZ`/sec, eases toward the
target, skips identical payloads, exempts lightning from both easing and
dedupe, and tracks on/off so `turn_off()` fires once at the transition.

**Acceptance criteria:**
- [x] Never exceeds `SEND_HZ` sends per second under any input
- [x] Eased value is rounded to integer raw units **before** the dedupe
      comparison, and snaps to target when within 1 unit — otherwise float
      easing never converges and dedupe never fires
- [x] `turn_off()` fires exactly once on the lit-to-dark transition
- [x] RGB path uses `rgbww=` with the achromatic component split into both
      white channels, not `rgb=` — see M0 finding 4. Storm slate must read
      neutral, not warm
- [x] `updateState()` results are unwrapped for the 0.6.6 list return type
      (only needed in ad-hoc live checks; the driver itself never calls it)

**Status: done, 20 unit tests + a live smoke test against the real bulb.**
Two real bugs the tests caught, worth keeping in mind if this gets touched:

1. **`_last_sent` must start as `None`, not "assume off".** It's tempting
   to initialize it to the off payload on the theory that a fresh driver
   probably faces a fresh-off bulb. Don't — the physical bulb's actual
   state at startup is unknown (could be on from a previous run), and
   dedupe against a guess means the first real command might silently
   never send. First call after construction must always go out.
2. **Dedupe has to compare the wire-quantized value, not the raw float.**
   `PilotBuilder(brightness=X)` runs `X` through pywizlight's own
   `hex_to_percent` (0-255 → 0-100) before it becomes the wire `dimming`
   field. Comparing pre-quantization raw values for dedupe means several
   genuinely-different internal values near the end of an ease — which all
   round to the identical wire byte — each trigger a real send. Harmless
   (rule 1's rate ceiling still holds), but it's exactly the redundant
   traffic dedupe exists to prevent on a settled scene. Fixed by comparing
   `hex_to_percent(raw_brightness)` instead of `raw_brightness` directly.

**Verification:** unit test with a mocked bulb asserting send count and payload
sequence. Then manually: bridge alone, feeding synthetic packets.

**Dependencies:** 0.3, 2.1. **Scope:** M.

---

### Task 2.9: `--simulate` flag

**Description:** Pulled forward from PLAN.md §14. Replays ticks 0–24000 through
the full pipeline in ~30 seconds with no Minecraft running, driving the real
bulb. Optional `--no-bulb` prints the resolved colour table instead.

**Acceptance criteria:**
- [x] `python main.py --simulate` (run from inside bridge/, matching how
      config/skymodel/bulb are imported everywhere else in this project —
      not `python -m bridge.main`, which would need bridge/ to be a real
      package with adjusted imports) runs a full day in ~30s
- [x] Respects the rate limiter — no bulb lockup
- [x] `--no-bulb` works with no bulb present

Verified live against the real bulb 2026-09-13: both a `--no-bulb` dry run
and a real-bulb run completed a full simulated day in ~30-39s with no
errors and no lockup.

**Verification:** run it; watch the bulb walk a day in half a minute.

**Dependencies:** 2.8. **Scope:** S.

---

### Task 2.10: `main.py` wiring

**Description:** asyncio entrypoint joining listener to skymodel to bulb.
Handles the mod not running (no packets means hold last state, then idle), and
Ctrl+C cleanly.

**Acceptance criteria:**
- [ ] Starts with no packets arriving and does not busy-spin
- [ ] Ctrl+C exits without a traceback
- [ ] Bulb state is left sane on exit

**Dependencies:** 2.2, 2.8. **Scope:** S.

---

### Task 1.3: Real telemetry — M3

**Description:** Replace the placeholder payload with the nine real fields from
PLAN.md §6. Guard `client.world == null` and `client.player == null` — both are
null on the title screen and during world load.

**Acceptance criteria:**
- [ ] All nine fields present and correctly typed
- [ ] Title screen sends nothing and logs nothing — no null-guard spam
- [ ] `skyLight` is emitted raw 0–15 and is **never** used as brightness

**Verification:** with the bridge printing, run `/time set 18000`,
`/weather thunder`, and dig down. Watch the fields change.

**Dependencies:** transport checkpoint. **Scope:** M.

---

### CHECKPOINT: Components

- [ ] `pytest` green across the whole model
- [ ] `./gradlew build` clean
- [ ] Real telemetry visibly correct in the bridge terminal
- [ ] Review before wiring the bulb to live game data

---

## Phase 3: Integration and calibration

### Task 3.1: Overworld cycle drives the bulb — M5

**Acceptance criteria:**
- [ ] `/time set 6000` gives bright daylight on the colortemp channel
- [ ] `/time set 12000` gives sunset orange on the RGB channel
- [ ] No visible stepping at 2 Hz — easing reads as continuous

**Dependencies:** 2.10, 1.3. **Scope:** S (integration only).

---

### Task 3.2: Weather — M6

**Acceptance criteria:**
- [ ] `/weather thunder` visibly dims and desaturates
- [ ] Strikes flash and ease back down
- [ ] `/weather clear` recovers smoothly, not abruptly

**Dependencies:** 3.1. **Scope:** XS.

---

### Task 3.3: Caves — M7

**Acceptance criteria:**
- [ ] Digging down with a torch shifts to torch orange
- [ ] Walking back up has no visible seam
- [ ] Sealing in and breaking the torch turns the bulb off

**Note:** PLAN.md's definition of done says the cave shift should land "within
about two seconds". At `EASE=0.22` and 2 Hz, two seconds gets you 63% of the
way; 90% takes closer to 4.5 s. If it feels sluggish, raise `EASE` rather than
special-casing the cave path.

**Dependencies:** 3.2. **Scope:** XS.

---

### Task 3.4: Dimensions — M8

**Acceptance criteria:**
- [ ] `/execute in the_nether run tp ~ ~ ~` gives the fixed ember mood
- [ ] The End gives its violet
- [ ] Returning to the overworld resumes the normal cycle

**Dependencies:** 3.3. **Scope:** XS.

---

### Task 3.5: Calibration — M9

**Description:** Dark room, bulb bounced off a wall behind the monitor
(PLAN.md §12). Tune `RAW_MAX` and `RAW_MIN` **before touching any keyframe
colour** — colours are far easier to judge once the brightness envelope fits
the room. Use `--simulate` for fast loops, then confirm with one real 20-minute
day. Also measure the channel-step problem (see Open Questions) and add a
compensation constant if it is visible.

**Acceptance criteria:**
- [ ] `RAW_MAX` is comfortable at noon in a dark room; `RAW_MIN` is visibly
      not-off at midnight
- [ ] Sunset ramp 11500 to 12200 to 12800 to 13500 reads as continuous
- [ ] Any colortemp/RGB channel step is either imperceptible or compensated

**Dependencies:** 3.4. **Scope:** tuning, `config.py` only.

---

### Task 3.6: Package into Prism — M10

**Description:** PLAN.md §5 Step 5. New 1.21.x Fabric instance, Java pointed
explicitly at JDK 21, Fabric API from Modrinth, then the **plain jar** from
`mod/build/libs/` — not `-sources.jar`, not `-dev.jar`. The dev jar uses
development mappings, loads without complaint, then crashes on the first
mapped method call.

**Acceptance criteria:**
- [ ] `logs/latest.log` shows the skysync mod id at startup
- [ ] Jar filename confirmed to have no `-dev` or `-sources` suffix
- [ ] Full cycle works from the Prism instance, not just `runClient`

**Note:** confirm load via the log, never via "the bulb changed colour" — a
silent mod failure and a bridge misconfiguration look identical from the room.

**Dependencies:** 3.5. **Scope:** S.

---

### Task 3.7: README

**Description:** Setup, run, and tune instructions. Both processes, Windows
command forms, and the recorded calibration values with the reasoning intact.

**Acceptance criteria:**
- [ ] A cold reader can go from clone to working bulb
- [ ] Records the bulb IP, reservation, and final constants
- [ ] Links PLAN.md as the design reference

**Dependencies:** 3.6. **Scope:** S.

---

### CHECKPOINT: Complete

- [ ] A full uninterrupted 20-minute day feels right in the dark room
- [ ] All eleven milestones M0–M10 met
- [ ] Repo clean, committed, README accurate

---

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| ~~5 GHz / merged SSID blocks discovery~~ | Resolved | Moved to `TP-Link_F8F5` 2.4 GHz; bulb found at `192.168.0.102` |
| ~~Firmware rejects all `setPilot`~~ | Resolved | Local control enabled in the WiZ app. If it recurs, that toggle is the first thing to check — see M0 finding 1 |
| Bulb IP drifts on DHCP lease renewal | Med | Reservation still outstanding — Task 0.3 |
| Desaturated colours skew warm on the `rgb=` path | Med | Use `rgbww=` with an explicit white split — M0 finding 4, Task 2.8 |
| Yarn mapping names shifted in 1.21.x | Med | Check Linkie for the equivalent rather than guessing (PLAN.md §11) |
| `pywizlight` lacks 3.14 wheels | Med | Pin the venv to 3.13 (Deviation 2) |
| Bulb locks up from packet spam | Med | Rate limiter is in Task 2.8's acceptance criteria, written before the bulb is ever driven live |
| colortemp/RGB channel step is visible | Med | Measured in Task 3.5; compensation constant if needed |
| Cave transition feels sluggish vs the 2s target | Low | Raise `EASE`; do not special-case the cave path |
| No B22 socket on hand | **High — blocks everything physical** | Physical check today; Tracks A and B still proceed without it |

## Open questions

1. **Channel-switch brightness step — the one real gap in the design.**
   PLAN.md §7.1 is explicit that WiZ white LEDs are substantially brighter than
   the colour LEDs. But the model switches channels mid-cycle: colortemp on
   [1000, 11000], RGB either side. So at tick 11000, and again whenever
   `rain>0.3` forces the RGB path at noon, brightness jumps even though every
   number in the table is "correct". The continuity test in Task 2.7 will not
   catch this — it tests the model's numbers, and the numbers are fine; the
   step is in the hardware.

   Proposed fix: measure the perceived brightness ratio between the two
   channels at equal raw value during Task 3.5, add
   `RGB_BRIGHTNESS_COMPENSATION` to `config.py`, and apply it on the RGB path.
   Cheap, and it keeps the keyframe table untouched.

2. **Is the unlit-cave blackout right?** PLAN.md §7.3 calls it deliberate and
   says to raise the torchlight floor rather than special-case it if it proves
   too aggressive. Flagging so it gets judged at Task 3.3 rather than debugged
   as a fault.

3. **Is `--simulate` in v1 acceptable?** Deviation 3. Say if you would rather
   hold the v1 line and tune the slow way.
