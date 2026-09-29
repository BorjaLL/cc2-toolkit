# Worked example: CC2 on a floor slab, stock soft feet

One printer, one setup, one date. Your numbers will differ: use
`guides/find-your-numbers.md` to get yours. These are here to show what the
process looks like, not as values to copy.

## Setup

| | |
|---|---|
| Printer | Centauri Carbon 2 (CANVAS combo) |
| Firmware | OTA 01.03.02.36 (`/opt/inst/firmware_version/versions.json`) |
| Stands on | floor slab, stock soft silicone feet (the printer rocks a little on them) |
| Calibrated | 2026-09-29 |
| Slicer | ElegooSlicer 1.5.3, stock CC2 0.20 mm process (`default_acceleration = 10000`) |

## Calibration result (from elegoo.log)

X, picked `zv`:

| shaper | freq Hz | suggested max_accel |
|---|---|---|
| **zv** | **51.6** | **9500** |
| mzv | 53.4 | 8400 |
| ei | 63.8 | 7600 |
| 2hump_ei | 79.4 | 6700 |
| 3hump_ei | 95.6 | 6300 |

Y, picked `mzv`:

| shaper | freq Hz | suggested max_accel |
|---|---|---|
| zv | 44.4 | 6600 |
| **mzv** | **45.2** | **5800** |
| ei | 54.0 | 5300 |
| 2hump_ei | 67.2 | 4500 |
| 3hump_ei | 81.0 | 4200 |

Y is the softer axis here: lower frequency, lower estimate.

## What the check showed

`tools/check_accel.py` on a stock-profile slice of a small hinge test part:
64% of moves at 10000, above the 5800 Y estimate (infill, solid infill,
inner walls, bottom surface).

## What the print showed

At stock accel (10000) a part with solid infill and a top surface at
13-14 mm height wobbled visibly. That is one print, not a controlled test.

## What I chose

`default_acceleration = 5000`, `outer_wall_acceleration = 3000`, first-layer
travel 5000, stock speeds (the `--accel capped` preset in `tools/slice_cc2.py`).

Cost, same part, from the slicer's time estimate:

| variant | time |
|---|---|
| stock 10000 accel | 48m 54s |
| capped 5000 | 56m 41s |
| capped + `solid_infill_direction=0` | 54m 48s |

`solid_infill_direction=0` lays solid infill along X, the stiffer axis here.
In the G-code it cut Y direction reversals by 17% and saved 4% time.
**(Untested on a print)**: that is a G-code count, not a measurement.

## Next on this printer

Rigid feet (see `guides/rigid-feet.md`), then recalibrate. If Y rises, the
cap can go back up.
