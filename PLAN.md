# Minecraft Sky Sync — Handoff

**Status:** design complete, no code written yet.
**Supersedes:** `minecraft-sky-sync-plan.md` (earlier draft assumed TLauncher and an unconfirmed bulb).

Drop this in the repo root as `PLAN.md`. It is self-contained — nothing from the originating conversation is needed beyond what's here.

---

## 1. What we're building

Mirror the Minecraft (Java Edition) sky onto a WiZ Colors smart bulb in real time, so a dark room's ambient lighting tracks the in-game daylight cycle, weather, and cave depth.

**Definition of done:** launch the bridge, launch Minecraft, load a world. Over one full 20-minute day the bulb tracks the sky without intervention, transitions look smooth rather than steppy, and walking into a torchlit cave shifts the room to warm orange within about two seconds.

### In scope

- Overworld daylight cycle driven by game tick.
- Weather: rain and thunder darken and desaturate; lightning strikes flash the bulb.
- Sky exposure: blend toward torchlight under a roof or underground; go dark in an unlit cave.
- Nether and End get fixed moods.
- Client-side only — works in singleplayer and on any multiplayer server.

### Out of scope for v1

- Multiple bulbs or zones.
- Biome-specific sky tint (the mod reports it; the bridge ignores it in v1).
- Any GUI. Config is source constants.
- Bedrock Edition — impossible with this architecture.

---

## 2. Confirmed inventory

| Item | Status |
|---|---|
| WiZ Colors B22 bulb (RGB) | Owned |
| Minecraft Java Edition, official | Owned |
| Prism Launcher | Installed |
| A B22 socket to put the bulb in | **Unverified — confirm before M0** |
| JDK 21 | **Unverified — required by MC 1.21 and Fabric Loom** |
| 2.4 GHz Wi-Fi available | **Unverified — WiZ cannot see 5 GHz at all** |

Target Minecraft version: **1.21.x**.

---

## 3. Decision log

Recorded so these aren't relitigated. Each was considered and rejected for the stated reason.

**Hardware-modifying the existing USB desk lamp.** The original idea was an ESP32 driving the lamp's two LED strings through logic-level MOSFETs (low-side switching, 20 kHz LEDC PWM, gamma correction). Fully worked out and viable, but rejected — no hardware tampering wanted. Worth noting it would still beat the bulb on one axis: it fades smoothly to true black, which WiZ cannot.

**Bulb selection.** The deciding criterion was **local API vs cloud API**. Cloud-only means every change is a round trip to a remote server: 300–800 ms, rate-limited, dead when Wi-Fi drops. WiZ speaks local UDP on port 38899 and has a mature Python library. Rejected: Philips Hue (best API, but ~₹7,000 with the bridge), TP-Link Tapo (local control needs cloud credentials for the handshake), Tuya-based Indian brands — Wipro, Halonix, Syska, Havells (require extracting a device local key from the Tuya IoT portal), Govee (LAN API on some models only), WLED strip (excellent, but more hardware than wanted).

**Colors model, not Tunable White.** Night sky is deep blue and dusk is red-violet. A warm/cool-white bulb cannot reach either.

**Screen capture for sky detection — rejected.** Sampling sky pixels with `mss` breaks when you look down, open an inventory, or go underground. Reading game state directly is strictly better.

**RCON against a dedicated server — rejected.** Would force playing on a local server, and weather queries are awkward. A client-side Fabric mod works in singleplayer and on anyone else's server, because the client already knows world time.

**Transport: fire-and-forget UDP**, not HTTP or a shared file. The mod must never block the render thread. A dropped packet is harmless because the next one arrives 500 ms later carrying full state, not a delta.

**TLauncher — resolved, no longer relevant.** Briefly considered; it's a cracked launcher with repackaged Fabric profiles, a bundled JRE that's often the wrong Java version, and a Malwarebytes PUP classification. User owns the game and has Prism. Dead issue.

---

## 4. Architecture

| Component | Language | Responsibility |
|---|---|---|
| `skysync-mod` | Java 21, Fabric, client-side | Read game state each tick, emit UDP JSON to localhost |
| `skysync-bridge` | Python 3.11+ | Receive UDP, run the sky model, drive the bulb |
| WiZ Colors B22 | — | Physical output, driven by pywizlight over local UDP |

Transport: JSON datagrams to `127.0.0.1:25566`, every 10 game ticks (2 Hz).

The mod is stateless and dumb. All modelling, easing, and calibration lives in Python, so tuning never requires a Minecraft restart. That separation is the single most important structural decision here.

### Repo layout

```
minecraft-sky-sync/
├── README.md
├── PLAN.md                      ← this document
├── mod/                         ← Fabric mod, its own Gradle project
│   └── src/main/java/com/ratan/skysync/
└── bridge/
    ├── pyproject.toml
    ├── config.py                ← bulb IP, calibration constants
    ├── skymodel.py              ← keyframes, interpolation, weather, cave blend
    ├── bulb.py                  ← pywizlight wrapper, easing, rate limiting
    ├── listener.py              ← UDP receiver
    ├── main.py                  ← wiring + asyncio entrypoint
    └── tests/
        └── test_skymodel.py
```

Keep `skymodel.py` free of I/O — pure functions from game state to `(rgb, brightness)`. That's what makes it testable without a bulb or a running game.

---

## 5. Setup, step by step

### Step 1 — Pair and pin the bulb

1. Install the WiZ app. Pair over **2.4 GHz** Wi-Fi. This step needs internet; nothing afterward does. If the router broadcasts one merged SSID, split the bands temporarily for pairing.
2. In the router admin page, find the bulb's MAC and create a **DHCP reservation** so the IP never changes. Record it.
3. Verify local control before touching project code:
   ```
   pip install pywizlight
   python -m pywizlight.cli discover
   python -m pywizlight.cli on <BULB_IP> --brightness 200
   python -m pywizlight.cli off <BULB_IP>
   ```
4. **Gate.** If `discover` finds nothing, stop. Usual cause: the laptop is on 5 GHz while the bulb is on 2.4 GHz, and UDP broadcast doesn't cross bands on most consumer routers. Nothing downstream works until this does.

### Step 2 — Python environment

```
cd bridge
python -m venv .venv && source .venv/bin/activate
pip install pywizlight pytest
```

pywizlight requires Python 3.11+.

### Step 3 — Fabric mod scaffold

1. Generate a project from `fabricmc.net/develop/template`, targeting Minecraft 1.21.x and JDK 21. Place it in `mod/`.
2. Mod id `skysync`, package `com.ratan.skysync`.
3. Register a **client** entrypoint only — there is no server-side component.
4. `./gradlew build` must succeed before adding any logic.
5. `./gradlew runClient` is the development loop. It launches a dev Minecraft with the mod loaded, in offline dev mode, with no launcher involved. Use this for all of M1–M8; Prism is only for actually playing.

### Step 4 — Verify the transport skeleton

Before any sky logic exists:

1. Mod: every 10 ticks, send a fixed placeholder JSON string to `127.0.0.1:25566`.
2. Bridge: an asyncio datagram endpoint that prints whatever arrives.
3. Run both. Packets should print roughly twice a second.
4. **Gate.** Don't proceed until this works. It isolates every build and networking problem from every modelling problem.

### Step 5 — Prism instance for real play

1. New instance → Minecraft 1.21.x → Mod Loader: **Fabric**. Prism fetches the official loader.
2. Instance → Settings → Java → point at **JDK 21** explicitly rather than trusting the default.
3. Instance → Mods → Download mods → grab **Fabric API** for the matching version from Modrinth.
4. `./gradlew build`, then take **the plain jar** from `mod/build/libs/` — e.g. `skysync-1.0.0.jar`. Not `-sources.jar`, and not `-dev.jar`. The dev jar uses development mappings, loads without complaint, then crashes on the first mapped method call.
5. Instance → Mods → Add file, or the folder button and drop it in.
6. **Confirm load via `logs/latest.log`** — look for the mod id at startup. Do not use "the bulb changed colour" as the test; a silent mod failure and a bridge misconfiguration look identical from the room.

---

## 6. Wire protocol

One JSON object per datagram. Full state every time, no deltas. Every 10 game ticks.

| Field | Type | Source | Meaning |
|---|---|---|---|
| `tick` | int 0–23999 | `world.getTimeOfDay() % 24000` | Position in the day cycle |
| `rain` | float 0–1 | `world.getRainGradient(1.0f)` | Rain intensity, eases over ~30 s |
| `thunder` | float 0–1 | `world.getThunderGradient(1.0f)` | Storm intensity |
| `lightning` | int | `world.getLightningTicksLeft()` | `> 0` during a screen flash |
| `skyLight` | int 0–15 | `world.getLightLevel(LightType.SKY, pos)` | Geometric sky exposure |
| `blockLight` | int 0–15 | `world.getLightLevel(LightType.BLOCK, pos)` | Torches, lava, glowstone |
| `y` | int | `pos.getY()` | Reported, unused in v1 |
| `skyColor` | int | biome sky colour, packed RGB | Reported, unused in v1 |
| `dimension` | string | `world.getRegistryKey().getValue()` | e.g. `minecraft:overworld` |

Implementation notes:

- **`skyLight` measures whether there's a path to the sky, not how bright it is.** It stays at 15 at midnight in the open. That's exactly what makes it a clean indoors/outdoors signal, and why it must not be used as a brightness value.
- `getRainGradient` and `getThunderGradient` are the values the game uses to darken its own sky, so build-up and clearing are already smoothed. Don't add more smoothing.
- Guard `client.world == null` and `client.player == null` — both are null on the title screen and during world load.
- Wrap the socket send in a catch-everything. A lighting toy must never crash or stall the game.

---

## 7. The sky model

### 7.1 Keyframes

24,000 ticks over 20 real minutes. Linear interpolation between keyframes, wrapping at 24,000.

| Tick | RGB | Brightness (0–100) | Phase |
|---|---|---|---|
| 0 | 255, 140, 60 | 22 | first light |
| 1000 | 150, 195, 255 | 78 | day begins |
| 6000 | 80, 160, 255 | 100 | noon |
| 11000 | 140, 185, 250 | 80 | late afternoon |
| 12000 | 255, 152, 66 | 50 | sunset |
| 12800 | 196, 84, 92 | 20 | last red |
| 13800 | 38, 48, 120 | 8 | night, mobs spawn |
| 18000 | 22, 32, 96 | 5 | midnight |
| 22200 | 34, 50, 126 | 8 | |
| 23000 | 150, 96, 150 | 15 | pre-dawn violet |
| 23600 | 255, 132, 72 | 24 | |
| 24000 | 255, 140, 60 | 22 | wraps to 0 |

**Colour is always RGB, at every tick, no exceptions.** The original design
drove the daytime span through the bulb's white/colour-temperature LEDs
instead — a `kelvin` column selected between `colortemp` (brighter, but
achromatic) and `rgb` (dimmer, but true colour) depending on the segment.
That made physical sense (WiZ's white LEDs really are the brighter ones)
but the tradeoff was wrong in practice: colour-temperature can't render
blue at all, so noon read as washed-out white instead of sky blue. Removed
2026-09-13 per user feedback — the light should track the sky's actual
colour through the whole cycle, full stop. The daytime RGB values above
were also retuned at the same time: the originals (205,228,255) /
(175,212,255) / (200,215,255) are close enough to white (~50-unit channel
gap) that they'd have looked pale and washed out even in RGB — these
values roughly double that gap so the hue actually reads as blue. The lost
lumens from dropping the white-LED channel are made up in `RAW_MIN`/
`RAW_MAX` directly (section 8) rather than with a separate per-channel
compensation constant, since there is only one channel now.

Note the compression: everything interesting happens between ticks 11,000 and 14,000 — about 2.5 real minutes. That's where tuning effort goes.

### 7.2 Weather

- `storm = max(rain, thunder)`. Blend sky RGB toward slate `(105, 118, 135)` by `storm * 0.7`.
- Scale brightness by `1.0 - 0.5*rain - 0.35*thunder`.
- When `lightning > 0`: override colour to `(255, 250, 235)`, jump straight to the flash cap bypassing easing, then ease back down naturally.

### 7.3 Sky exposure and caves

```
exposure = skyLight / 15.0
```

- `1.0` → pure sky model.
- `0.0` → pure torchlight; time of day ignored entirely.
- Between → linear blend of both colour and brightness.

Torchlight target: colour `(255, 147, 41)`, brightness `18 * (blockLight/15) ** 0.7`. The exponent keeps a single torch feeling meaningfully lit rather than nearly black.

This blend handles the interesting middle cases for free — a tree canopy, a doorway, a cave mouth at sunset. Walking out of a mine into an orange sunset should have no visible seam.

**Deliberate behaviour:** `blockLight == 0` and `exposure == 0` is a genuinely unlit cave, and the bulb turns off. The room goes dark exactly when the game does. If that proves too aggressive, raise the torchlight floor rather than special-casing it.

### 7.4 Dimensions

Nether and End have no sky light anywhere, so the cave blend would black them out. Bypass the overworld path entirely:

| Dimension | RGB | Brightness |
|---|---|---|
| `minecraft:the_nether` | 190, 62, 28 | 30 |
| `minecraft:the_end` | 58, 30, 82 | 11 |

---

## 8. Bulb driver

### Calibration — dark room

Lives in `config.py`. First thing to tune; sets the dynamic range everything else lives inside.

| Constant | Value | Meaning |
|---|---|---|
| `RAW_MIN` | 39 | Night / unlit-cave floor, in pywizlight's 0–255 units |
| `RAW_MAX` | 240 | Noon |
| `FLASH_MAX` | 169 | Lightning cap |
| `SEND_HZ` | 2.0 | Bulb updates per second |
| `EASE` | 0.22 | Exponential easing factor, 0–1. Lower is smoother and laggier |

`RAW_MIN`/`RAW_MAX`/`FLASH_MAX` were bumped +30% from their original
30/185/130 on 2026-09-13 per user feedback ("increase the base brightness
by 30% or so") — this also absorbs the lumens lost by dropping the
white-LED colour-temperature channel (section 7.1). If `RAW_MAX` ever
needs to come back down, that original margin below 255 (a dark-adapted
eye finds full brightness uncomfortable) is the first thing to give back,
not `RAW_MIN`.

Reasoning to preserve when editing:

- `RAW_MIN` is a **hardware floor, not taste.** WiZ ignores brightness below roughly 25, so anything lower reads as off. Don't "clean this up" to 0.
- `RAW_MAX` is deliberately under 255 because a dark-adapted eye finds full brightness uncomfortable — currently spending less of that margin than the original design did, per the brightness bump above.
- `FLASH_MAX` is lower than `RAW_MAX` because a full-white flash in a dark room stops being fun around the third thunderstorm.

### Rate limiting

WiZ bulbs drop packets above roughly 10–15 commands per second and can lock up until physically power-cycled. The driver must:

1. Send at most `SEND_HZ` times per second.
2. Ease toward the target rather than jumping, so 2 Hz reads as continuous.
3. Skip the send entirely when the resolved payload is identical to the last one. A stable afternoon should produce almost no traffic.
4. Exempt lightning from both easing and deduplication.
5. Track on/off state so `turn_off()` fires once at the transition, not repeatedly.

---

## 9. Milestones

| # | Milestone | Acceptance criterion |
|---|---|---|
| M0 | Bulb reachable | `pywizlight.cli` turns it on and off from the laptop |
| M1 | Mod builds | `./gradlew runClient` opens Minecraft with the mod loaded |
| M2 | Transport | Placeholder packets print in the bridge terminal at ~2 Hz |
| M3 | Real telemetry | Fields change correctly under `/time set` and `/weather` |
| M4 | Sky model | Unit tests pass over ticks 0–24000; no discontinuity at the wrap |
| M5 | Bulb driven | Overworld cycle drives the bulb; `/time set 12000` gives orange |
| M6 | Weather | `/weather thunder` dims and desaturates; strikes flash |
| M7 | Caves | Digging down shifts to torch orange; sealing off unlit goes dark |
| M8 | Dimensions | Nether and End produce their fixed moods |
| M9 | Calibrated | A full uninterrupted 20-minute day feels right in the dark room |
| M10 | Packaged | Jar loads in the Prism instance, confirmed in `logs/latest.log` |

M4 deserves real unit tests: sweep every tick 0–24000 and assert that brightness and each RGB channel never jump more than a small delta between adjacent ticks. That catches keyframe typos and wrap-around bugs with no bulb and no running game.

---

## 10. Test procedure

With `/gamerule doDaylightCycle false`:

| Command | Checks |
|---|---|
| `/time set 6000` | Noon. Is `RAW_MAX` too hot for the room? |
| `/time set 11500` → `12200` → `12800` → `13500` | The sunset ramp — the part that matters most |
| `/time set 18000` | Midnight. Is `RAW_MIN` actually visible? |
| `/weather thunder` | Desaturation, dimming, strike flashes |
| `/weather clear` | Clears smoothly, not abruptly |
| Dig down 5 blocks with a torch | Exposure blend, down and back up |
| Seal yourself in, break the torch | Bulb goes off |
| `/execute in the_nether run tp ~ ~ ~` | Dimension override |

**Tune `RAW_MAX` and `RAW_MIN` before touching any keyframe colours.** Colours are far easier to judge once the brightness envelope fits the room.

---

## 11. Known pitfalls

- **Yarn mapping names shift between Minecraft versions.** This targets 1.21.x. If a method won't resolve, check Linkie for the equivalent rather than guessing.
- **2.4 GHz only**, for pairing and for discovery. Most common failure, and it presents as a silent timeout.
- **Never block the render thread.** No synchronous HTTP, no file I/O, no waiting on a response.
- **Don't spam the bulb.** Exceeding the rate limit can require physically power-cycling it.
- **Sub-25 brightness reads as off.** Anything below `RAW_MIN` is wasted range.
- **Use the plain jar, not `-dev.jar`.** The dev jar loads fine and then crashes on the first mapped call.

---

## 12. Bulb placement

Not a code concern, but the largest single factor in whether this feels immersive or irritating: put the bulb **behind the monitor or off to one side, bouncing off a wall.** Never in direct line of sight. A colour-changing point source in peripheral vision reads as a distraction; the same light bounced off a wall reads as atmosphere.

---

## 13. Conventions

- Commit messages follow Conventional Commits: `<type>(<optional scope>): <short description>`, e.g. `feat(bridge): add cave exposure blend`.
- Bridge code targets Python 3.11+, asyncio throughout.
- Mod targets Java 21, Fabric for 1.21.x, client entrypoint only.

---

## 14. Backlog for v2

- Use the reported `skyColor` for biome-specific tint — swamp green, badlands amber, mushroom island.
- A second bulb behind the desk running a desaturated version, for depth.
- Health-based red pulse below 6 hearts.
- Player-held light source (torch, lantern, soul lantern) selecting the cave colour, not just its brightness.
- A `--simulate` flag on the bridge that plays a full day in 30 seconds with no Minecraft running, for fast colour tuning.

---

## 15. Suggested opening prompt for Claude Code

> Read PLAN.md. Set up the repo skeleton described in section 4, then work milestone by milestone from section 9. Stop at each gate (sections 5.1 and 5.4) and tell me what to verify manually — I'll confirm before you continue. Start with M0: I'll run the pywizlight CLI checks myself, so just give me the exact commands and tell me what output means success.
