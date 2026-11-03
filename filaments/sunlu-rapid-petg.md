---
name: SUNLU Rapid PETG (matte black)
material: PETG
base_preset: Elegoo PETG HF @ECC2
slicer_key: petghf         # slice_cc2.py --filament
user_preset:
preset_json:
temp: 240                  # stock PETG HF 240, kept
flow: 1.00                 # stock PETG HF value, no flow test yet
retraction_mm:             # stock 0.8 used, not tested
tolerance_free_at_mm:      # not tested
pressure_advance: 0.110    # line test, good band 0.070-0.110 (stock 0.05)
max_volumetric_mm3s: 14    # provisional, see log
---

# SUNLU Rapid PETG (matte black)

Calibrated 2026-10-30 from the stock `Elegoo PETG HF @ECC2` preset. The
roll was dried overnight and fed from an active dryer. Sold as "high speed
30-600 mm/s".

Slice with:
`python tools/slice_cc2.py model.stl --filament petghf --temp 240 --flow 1.00`
plus `--proc pressure_advance=0.11 --fil filament_max_volumetric_speed=14`.

## Log

- 2026-10-30 pressure advance line test (240 C, 100 / 20 mm/s, accel 5000):
  even lines from 0.070 to 0.110; low values bulge at the speed changes.
  Kept **0.110**, confirmed the same day by a 4-layer chevron test
  (0.060-0.140: 0.105-0.110 best, 0.060-0.075 rounded corners).
- 2026-10-30 temperature tower 265-225 (bed 80, PA 0.110): no stringing and
  fine overhangs at every block; 250-265 glossier (loses the matte look) with
  more droop on hole tops; 225-245 matte and cleaner. Picked **240**. Ceilings
  (bridges, hole tops) rough at every temperature: a bridge-settings
  question, not temperature (open).
- 2026-10-30 max volumetric speed tower 8-36 mm3/s at 240 C: walls never
  fully under-extruded up to 36, but scattered zits and single-line gaps on
  long straights from about 16-19 mm3/s. Set **14** (about 85% of the onset).
  A later 14-36 tower at 250 C failed from about 20-22 mm3/s.
- 2026-10-31 brim at gap 0 fused to the parts (`../guides/gotchas.md` item 30).
- Open (2026-10-31): a production plate still showed intermittent thin or
  missing lines in the lowest walls, where the commanded flow was only about
  6 mm3/s, so the flow limit alone does not explain them. Feed path or
  extrusion steadiness is the suspect; not resolved.
