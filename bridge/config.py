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
# RAW_MIN alone was bumped another +30% on 2026-09-14 ("increase the min
# brightness by 30%... without tinkering with white blend") — night/cave
# brightness was reading too dim after WHITE_MIX dropped to 0.0, and this
# raises the floor directly rather than reopening that knob.

# Night / unlit-cave floor, in pywizlight's 0-255 raw brightness units.
# This is a HARDWARE FLOOR, not taste: WiZ ignores brightness below
# roughly 25, so anything lower just reads as off. Do not "clean this up"
# to 0 — it will make the midnight and cave states silently do nothing.
RAW_MIN = 51

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

# How much of an RGB colour's shared white component gets mixed into the
# bulb's cold/warm white LEDs, 0-1. 0.0 = pure colour, drive R/G/B alone.
# 1.0 = the old behaviour, split the full min(r,g,b) evenly into both white
# channels.
#
# Set to 0.0 on 2026-09-14 per user feedback ("these don't seem too
# vibrant... okay with darker shades"). The bulb's own hardware report
# gives the reason: colour LED drive current is roughly a third of white
# LED drive current (R=10mA, G=8mA, B=6mA vs C=23mA, W=22mA), so even a
# modest white contribution punches far above its numeric weight and
# washes out saturation — noon blue (80,160,255) was being sent as
# rgbww=(0,80,175,80,80), and that (80,80) of white diluted it badly.
# Pure colour means less total brightness (no "free" lumens borrowed from
# the much-stronger white LEDs) in exchange for accurate, saturated hue —
# exactly the trade that was asked for. Raise this back up if colours ever
# end up feeling too dim rather than too pale; storm slate in particular
# was the original reason a nonzero value existed (PLAN.md section 7.2 —
# pywizlight's own rgb= path skews warm without an even white split, this
# is what keeps a fully-desaturated grey neutral instead).
WHITE_MIX = 0.0
