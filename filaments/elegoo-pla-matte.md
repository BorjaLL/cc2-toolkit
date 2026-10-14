---
name: Elegoo PLA Matte
material: PLA
base_preset: Elegoo PLA Matte @ECC2
slicer_key: plamatte       # slice_cc2.py --filament
user_preset:
preset_json:
temp: 215                  # stock 220
flow: 0.98                 # stock 0.98, kept
retraction_mm: 0.8         # stock 0.8, kept; anything from 0.2 is clean
tolerance_free_at_mm: 0.1  # per side, 4 mm rail
max_volumetric_mm3s: 20    # stock preset 16
---

# Elegoo PLA Matte

Calibrated 2026-10-01 on white. One record for every colour of the line
(same line, new colour: reuse the values, per `calibration/README.md`).

Slice with:
`python tools/slice_cc2.py model.stl --filament plamatte --temp 215 --flow 0.98 --fil filament_max_volumetric_speed=20`

## Log

- 2026-10-01 temperature tower 230-190: overhang droops at 205 and colder,
  surface chalky at 190-195, bridges flat 205-220. The snap test did not follow
  temperature (read as seam / handling noise), so picked on looks: **215**, the
  middle of the 210-230 good-looking band. 220 (stock) is the hotter
  alternative.
- 2026-10-01 retraction (calibration card with a 0.0 control): 0.0 strings
  heavily, every length from 0.2 up is clean. Stock 0.8 kept.
- 2026-10-01 fit: tester free at 0.1 mm per side on a 4 mm thick rail. An
  earlier card with a 2.4 mm rail read 0.05, but the thin rail feels looser
  than a real part.
- 2026-10-01 flow YOLO at 215 / 0.98: patch 0 best, **0.98 kept**.
- 2026-10-05 max volumetric speed tower (`calibration/mvs/`, 215 C, 0.7 x
  0.32 mm lines, ramp 10-40 mm3/s): wall clean to 23.5 mm3/s, first gaps from
  24, clearly under-extruded from 25.5. Set **20 mm3/s** (85% of the last clean
  value); the stock preset caps it at 16. Untested at 225 C.
