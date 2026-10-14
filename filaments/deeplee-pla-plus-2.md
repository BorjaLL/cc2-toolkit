---
name: DEEPLEE PLA+ 2.0
material: PLA+
base_preset: Elegoo PLA+ @ECC2
slicer_key: plaplus        # slice_cc2.py --filament
user_preset:
preset_json:
temp: 220                  # 215 near-identical
flow: 1.00                 # stock 0.98
retraction_mm: 0.8         # stock 0.8, kept
tolerance_free_at_mm: 0.2  # per side, 4 mm rail; looser than PLA Matte
---

# DEEPLEE PLA+ 2.0

Calibrated 2026-10-06 on white, from the stock `Elegoo PLA+ @ECC2` preset
(220 C, flow 0.98, bed 60 C).

Plastic spool with a hub hole of about 73 mm: it needs a CANVAS spool adapter.

Slice with:
`python tools/slice_cc2.py model.stl --filament plaplus --temp 220 --flow 1.00`

## Log

- 2026-10-06 temperature tower 230-190: 215 and 220 near-identical (cleanest
  post, clean overhang, straight bridges); 190-200 string most and roughen the
  overhang tips; 225-230 light webbing and bridge ridging. Picked **220**.
- 2026-10-06 flow YOLO at 220 / 0.98: patch +0.02 best, so **1.00**. Confirmed
  the same day on the calibration card's pads around 1.00 (patch 0 best).
- 2026-10-06 retraction tower 0.0-1.2 mm (calibration card): one thin strand in
  the 0.0-0.1 band, clean above it. Stock 0.8 kept.
- 2026-10-06 fit (4 mm rail): tester slides freely at 0.2 mm per side, 0.1 only
  with force, 0.05 does not go in. **0.2**, looser than PLA Matte (0.1).
