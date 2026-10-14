---
name: SUNLU PLA+
material: PLA+
base_preset: Elegoo PLA+ @ECC2
slicer_key: plaplus        # slice_cc2.py --filament
user_preset:
preset_json:
temp: 215
flow: 0.98                 # stock 0.98, kept; read from a photo, not confirmed by the owner
retraction_mm: 0.8         # stock 0.8, kept
tolerance_free_at_mm: 0.25 # print-in-place hinge: free joint; 0.10-0.15 poseable
---

# SUNLU PLA+

Calibrated 2026-10-08/09 on green, from the stock `Elegoo PLA+ @ECC2` preset.

Slice with:
`python tools/slice_cc2.py model.stl --filament plaplus --temp 215 --flow 0.98`

## Log

- 2026-10-08 temperature tower 240-200: 200-215 crisp numbers, sharp cones, few
  hairs; from 220 the numbers blob; 230-240 string across the windows and
  roughen the overhang lip. No cold-end failure at 200; 215 and 235 held in a
  snap test. Picked **215**.
- 2026-10-08 flow YOLO at 215 / 0.98: patch 0 smoothest in a photo; positive
  patches show a raised ring at the circle edge, negative ones rougher labels.
  **0.98 kept** (read from the photo, not confirmed by the owner).
- 2026-10-09 retraction tower 0.0-1.2 mm (calibration card without flow pads,
  `--no-flow`): pillars clean the whole height, strings only in the 0.0
  control. Stock 0.8 kept.
- 2026-10-09 tolerance: the loose 6 mm hex tester came off the bed, so no
  reading from the card. Used the print-in-place hinge test instead
  ([MakerWorld 388977](https://makerworld.com/en/models/388977), about 30 min):
  0.25 mm and up swing freely, 0.20 swings but sticks in places, 0.10-0.15 move
  easily but hold their position (poseable joints). This is a hinge clearance,
  not the same number as the hex rail on the other records.
