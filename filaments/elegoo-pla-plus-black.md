---
name: Elegoo PLA+ black
material: PLA+
base_preset: Elegoo PLA+ @ECC2
slicer_key: plaplus        # slice_cc2.py --filament
user_preset: Elegoo PLA+ (calibrated)
preset_json:               # export after Step 3
temp: 210
flow: 0.98                 # stock 0.98, kept (YOLO patch 0)
retraction_mm:             # Step 3 pending
tolerance_free_at_mm:  ok  # Step 4 passed 2026-09-23, no XY compensation needed
---

# Elegoo PLA+ black

Bought for a sliding-fit puzzle (a toy train, the Coal Train). Calibration in
progress: temp + flow done, retraction / tolerance still to run (see
`calibration/README.md`).

Slice with:
`python tools/slice_cc2.py model.stl --filament plaplus --temp 210 --flow 0.98`

## Log

- 2026-09-23 temp tower 230-190 (Orca tower, black PLA+). Bend test snapped at
  200, 210 and 220: a break every two blocks, because each bend snaps the weakest
  point left, so the test did not separate the blocks. Picked from photos, with
  two independent reads:
  - Reader 1: 205-220 clean, 190-200 overhang curl, 225 blobs, 230 heavy
    stringing. Pick 215.
  - Reader 2 (blind to reader 1's pick): 205 best, 195 runner-up; stringing
    climbs from 215; 225-230 too hot. Pick 205.
  Both rate 210 clean, so 210: the middle of the overlap and the same temp as the
  emoji PLA. Go to 215 if parts are weak, 205 if stringing shows.
- 2026-09-23 flow YOLO (Recommended, an Orca flow-test option) at 210C: smoothest patch was 0, so flow
  stayed at the stock 0.98 (no adjustment needed). Flow did not move, but
  Step 4 (tolerance) is still needed per the run-book because the puzzle
  is fit-critical: tolerance stays pending.
- 2026-09-23 tolerance test (Step 4): owner reports OK, so XY contour/hole
  compensation stays 0. The puzzle's black plates were sliced with these settings.
