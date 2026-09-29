---
name: Elegoo PLA RFID "emoji" edition
material: PLA
base_preset: Elegoo PLA @ECC2
slicer_key: pla            # slice_cc2.py --filament
user_preset: Elegoo PLA emoji (calibrated)
preset_json: filaments/presets/elegoo-pla-emoji.json
temp: 210                  # stock 210
flow: 1.00                 # stock 0.98
retraction_mm: 0.8         # stock 0.8, kept
tolerance_free_at_mm: 0.2  # by hand; tester/hole not measured
ironing: v1 pick ~25 mm/s / 25% (pads too small to judge well); v2 grid not printed
colour: white              # swatch card line 1 (filaments/swatch/)
swatch_label: Elegoo PLA emoji   # swatch card line 1 (default would be the long name above)
---

# Elegoo PLA RFID "emoji" edition

Calibrated. Slice with:
`python tools/slice_cc2.py model.stl --filament pla --temp 210 --flow 1.00`

The exported preset JSON holds only the flow change (1.00). Temperature stayed at
the stock 210, so it is not in the JSON.

## Log

- 2026-09-21 temp tower 230-190: bend test snapped the 190 block, 195/200 creaked
  and broke a bit, so the cool end has weak layer bond. 205+ solid; overhangs and
  surface clean 205-215; surface still fine at 230 (no upper limit). Picked 210
  for bond margin over the 200 failure zone. 215 is the hotter alternative.
- 2026-09-21 flow YOLO: 0.98 -> 1.00. Retraction tower: 0.8 clean, kept.
  Tolerance test: free at 0.2 by hand; tester and hole not measured.
- 2026-09-22 ironing grid v1 printed: best around 25 mm/s / 25% flow, but pads
  too small to judge. v2 grid (bigger labelled chips, 19-31 sweep) sliced in
  `calibration/ironing/`, not printed yet.
