# Find your numbers: input shaper vs slicer acceleration

Your CC2 measures its own resonances during calibration and writes the results
to a log. The slicer never reads that log. This guide shows you how to read it
and check your G-code against it, so you choose acceleration from your
printer's numbers, not from someone else's.

Time: about 15 min, plus one or two test prints if the check flags anything.

## What the printer measures (and what it does not do with it)

The CC2 firmware is Klipper-based. During input shaper calibration it shakes
each axis, fits several shaper types, picks one per axis and saves it. For every
shaper it tries, it also logs:

```
Fitted shaper: mzv frequency = 45.2 Hz (vibrations = 0%, smoothing ~= 0.108)
To avoid too much smoothing with 'mzv', suggested max_accel <= 5800 mm/sec^2
Recommended shaper_type_y = mzv, shaper_freq_y = 45.200000 Hz
```

What that `max_accel` number is:

- **A smoothing estimate.** Above it, the shaper starts to round corners and
  soften detail. Klipper's docs describe it this way
  ([Measuring resonances](https://www.klipper3d.org/Measuring_Resonances.html)).
- **Not a hard limit.** The printer still moves faster if asked to.
- **Not applied.** The calibration saves the shaper type and frequency only.
  The stock `printer.cfg` has `max_accel = 20000`, and the slicer sends
  `SET_VELOCITY_LIMIT ACCEL=...` per feature (walls, infill, travel), which is
  what the printer actually uses.

So the stock ElegooSlicer profile (`default_acceleration = 10000`) can run most
of a print above your estimate, and nothing tells you. Whether that matters
depends on your printer and what it stands on. On a solid bench it may look
fine. On a table that rocks, it can wobble.

## 1. Run the calibration

Run the input shaping calibration from the touchscreen (or the full
auto-calibration, which includes it) with the printer where it normally lives.
Moving it to a different table changes the result, so recalibrate after a move.

## 2. Get the log

The results are in `/opt/usr/logs/elegoo.log`. The log rotates to
`elegoo.1.log` at about 10 MB (a few days of printing), so copy it soon after
calibrating.

**SSH (firmware before 02.00.02.00):** see `firmware-and-ssh.md` for access.

```bash
ssh root@<printer-ip> "grep -h 'suggested max_accel\|Recommended shaper' /opt/usr/logs/elegoo*.log"
scp root@<printer-ip>:/opt/usr/logs/elegoo.log .
```

**No SSH (02.00.02.00 and later):** Elegoo documents Settings -> Export Log
File (FAT32 USB stick, 16 GB or smaller). Not verified by us that the export
contains `elegoo.log` with these lines. If you try it, please open an issue so
the answer can go here.

## 3. Read your numbers

Find the two `Recommended shaper_type_` lines (one per axis). For each, the
`suggested max_accel` that matters is the one for **that** shaper type, in the
block just above it. Write down:

| Axis | Shaper | Frequency | Suggested max_accel |
|---|---|---|---|
| X | | | |
| Y | | | |

The lower of the two is the one to watch: on a CoreXY most moves use both
axes.

## 4. Check your G-code

```bash
python tools/check_accel.py --log elegoo.log model.gcode
# or type your own numbers in:
python tools/check_accel.py --x <your X estimate> --y <your Y estimate> model.gcode
```

It lists every acceleration the G-code uses, how many moves use it, which
features (walls, infill, ...) and flags the ones above your lower estimate.
Shares are counts of moves, not print time. Example output with the author's
numbers (yours will differ):

```
X: zv 51.6 Hz, suggested max_accel <= 9500
Y: mzv 45.2 Hz, suggested max_accel <= 5800
  accel    moves   share  features
   5000    32747   25.8%  Custom, Inner wall, Outer wall
  10000    81834   64.4%  Bottom surface, Gap infill, Inner wall, ...  ABOVE
65% of moves run above your lower estimate.
```

"ABOVE" is a prompt to test, not a failure.

## 5. Decide with a test print

1. Print a part you care about at stock settings. Look for wobble, ringing
   next to corners, rounded corners, a shaking table.
2. If it looks fine: keep stock. Faster prints, and you know the check.
3. If not: cap `default_acceleration` near your lower estimate (and
   `outer_wall_acceleration` below it), print the same part, compare.
   In ElegooSlicer: Process > Speed > Acceleration. With
   `tools/slice_cc2.py`: `--proc default_acceleration=5000`.
4. Fixing what the printer stands on (rigid feet, heavy slab) often gives back
   more than lowering accel. See `rigid-feet.md`, then recalibrate and re-check.

## Share your numbers

The spread between printers is the useful part. Open an issue with the
"CC2 results" template: firmware, what it stands on, both shapers with their
estimates, the accel you settled on and what the print looked like.

One worked example: `../examples/borja-floor-slab/`.
