# Sky Sync — Setup and Running

The working, confirmed-good way to run this project as of 2026-09-14. If
you're looking for the design/rationale, that's [PLAN.md](PLAN.md). If
you're looking for the task-by-task build log, that's [TASKS.md](TASKS.md).
This file is just: how do I turn it on.

## What's running, and where

Two independent processes:

| Process | What it is | How it's started |
|---|---|---|
| **The bridge** | Python — reads game state, drives the bulb | Auto-starts at Windows login (see below) |
| **The mod's Minecraft client** | A Fabric dev client with skysync loaded | You start this manually, every time |

They talk over UDP on `127.0.0.1:25566`. Neither needs the other to start
first — order doesn't matter, but nothing lights up until both are running.

## The bridge: already running, starts itself

The bridge is set up to launch automatically, silently, every time you log
into Windows. You should not normally need to do anything for it.

- **Where:** a shortcut named `SkySync Bridge` in your Startup folder.
  Open it with Win+R → `shell:startup` → Enter.
- **What it runs:** [bridge/start_bridge.vbs](bridge/start_bridge.vbs), which
  launches `bridge/main.py` under `pythonw.exe` (no console window) with
  the working directory set correctly.
- **Logs:** [bridge/bridge.log](bridge/bridge.log). Check here first if the
  bulb never responds after a login — this is the only place a crash would
  be visible, since there's no console attached.
- **No supervisor.** If the bridge process crashes, it stays down until the
  next login. If the bulb seems unresponsive and the log shows nothing
  recent, it's probably dead — see "Running the bridge by hand" below to
  restart it without logging out and back in.

### Running the bridge by hand

Only needed if it's not already running (check `tasklist` for `pythonw.exe`,
or just check whether `bridge.log` has recent activity):

```bash
cd bridge
.venv\Scripts\python.exe main.py
```

This runs it in a visible console instead — useful for watching it live,
which the silent auto-start version can't give you. Ctrl+C to stop it.

To disable auto-start entirely: delete the `SkySync Bridge` shortcut from
`shell:startup`.

## The mod's Minecraft client: manual, every time

**This is the part that has to be started by hand, every session.** There
is no packaged, double-click-to-play version yet — that's still on the
list (see "What's not done yet" below). Right now, "playing with the mod"
means running Minecraft's own dev environment via Gradle.

```bash
cd mod
./gradlew runClient
```

The first run after a while may re-download or re-decompile Minecraft —
can take several minutes. After that, it's fast (well under a minute).

This opens a real, playable Minecraft 1.21.1 window with the mod loaded.
It is **not** your normal Prism-launched game — it's a separate,
self-contained dev instance living entirely inside `mod/run/`. Worlds you
create here don't show up anywhere else, and vice versa. That's fine for
testing the mod; it's the reason this step can't just be "open Minecraft
normally" yet.

**How to tell it's actually working:** the mod sends nothing at all until
you're actually inside a world — the title screen deliberately stays
silent (no telemetry, no log spam). Load or create a Singleplayer world,
and the bulb should start tracking whatever the in-game sky is doing
within a couple of seconds. `/time set 6000` should shift it to a bright,
saturated blue.

**If the bulb doesn't respond:**
1. Check the bridge is actually running (`tasklist` for `pythonw.exe`, or
   run it by hand per above so you can see its output).
2. Check `mod/run/logs/latest.log` for a line from `(skysync)` near
   startup — confirms the mod itself loaded. If it's missing, the jar or
   loader didn't come up correctly.
3. Check `bridge/bridge.log` for anything unusual.

## Trying a full day fast, without touching Minecraft

For tuning colours/brightness without waiting through a real 20-minute
day:

```bash
cd bridge
.venv\Scripts\python.exe main.py --simulate            # drives the real bulb
.venv\Scripts\python.exe main.py --simulate --no-bulb  # prints instead of sending
```

Replays a full day in about 30 seconds.

## Editing the bulb's tuning

Everything about how bright, how saturated, how fast it eases — all in
[bridge/config.py](bridge/config.py). No restart of Minecraft needed after
a change, only the bridge:

```bash
cd bridge
.venv\Scripts\python.exe main.py --simulate --no-bulb
```

to preview it fast, then restart the bridge (or just wait for the next
login) to pick the change up for real play.

## What's not done yet

Tracking this honestly so nothing looks more finished than it is — see
[TASKS.md](TASKS.md) for the full breakdown:

- **No packaged Minecraft instance.** You always have to run
  `./gradlew runClient` from `mod/`, as above. An attempt was made
  (2026-09-14) to retarget the mod at a real Prism Launcher instance on
  Minecraft 1.21.9, which required re-verifying and fixing two yarn
  mapping changes (`Entity.getPos()` → `getEntityPos()`, and
  `ClientWorld.getSkyColor()` changing its return type from `Vec3d` to a
  packed `int`) — that part worked, but the actual launch through Prism
  didn't, and it was reverted back to the known-working 1.21.1 dev-client
  setup documented above. Revisiting this is future work, not abandoned
  outright.
- **Weather and cave verification still open.** Time-of-day telemetry is
  confirmed live and correct; `/weather thunder` and digging into an unlit
  cave haven't been watched live yet (Task 1.3 / M6 / M7 in TASKS.md).
- **No calibration pass.** The brightness envelope and daytime blue
  saturation in `config.py`/`skymodel.py` are first-pass values, not
  measured in the actual room the bulb sits in (Task 3.5).
