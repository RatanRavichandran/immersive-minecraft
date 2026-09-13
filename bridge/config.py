"""Bulb IP, network settings, and calibration constants.

Nothing here does I/O. This module is just numbers — see PLAN.md section 8
for the reasoning behind each one, repeated inline below so it survives a
casual skim. Tune ``RAW_MIN``/``RAW_MAX`` before touching any colour in
skymodel.py (PLAN.md section 10): colours are far easier to judge once the
brightness envelope fits the room.
"""

# --- Network -----------------------------------------------------------

# Reserve this in the router's DHCP settings (PLAN.md section 5, Step 1.2)
# so it never drifts out from under a hardcoded constant.
BULB_IP = "192.168.0.102"

# Where the Fabric mod sends its UDP telemetry (PLAN.md section 6).
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 25566

# --- Calibration: dark room (PLAN.md section 8) -------------------------

# All three brightness constants below were bumped +30% on 2026-09-13 per
# user feedback ("increase the base brightness by 30% or so") from the
# original 30/185/130. That undoes some of the original 255-is-uncomfortable
# margin PLAN.md section 8 built in — if RAW_MAX starts feeling too hot for
# the room, that margin is the first thing to give back, not RAW_MIN.

# Night / unlit-cave floor, in pywizlight's 0-255 raw brightness units.
# This is a HARDWARE FLOOR, not taste: WiZ ignores brightness below
# roughly 25, so anything lower just reads as off. Do not "clean this up"
# to 0 — it will make the midnight and cave states silently do nothing.
RAW_MIN = 39

# Noon brightness, out of 255. Tune this first, before any keyframe colour.
RAW_MAX = 240

# Lightning-flash brightness cap, out of 255. Lower than RAW_MAX on
# purpose: a full-white flash in a dark room stops being fun around the
# third thunderstorm (PLAN.md section 8).
FLASH_MAX = 169

# Bulb updates per second. WiZ bulbs drop packets above roughly 10-15
# commands/sec and can lock up until power-cycled — this is the hard
# ceiling the driver's rate limiter enforces, not a suggestion.
SEND_HZ = 2.0

# Exponential easing factor, 0-1. Lower is smoother and laggier. At the
# default 0.22 and SEND_HZ=2.0, a step reaches ~63% of the way in about
# 2 seconds and ~90% in about 4.5 seconds — keep that in mind against the
# "within about two seconds" cave-transition target in PLAN.md section 1.
# Raise this before adding any cave-specific special case (PLAN.md
# section 7.3 / TASKS.md Task 3.3).
EASE = 0.22
