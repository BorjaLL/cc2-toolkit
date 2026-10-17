---
name: Elegoo PETG HF
material: PETG
base_preset: Elegoo PETG HF @ECC2
slicer_key: petghf         # slice_cc2.py --filament
user_preset:
preset_json:
temp: 240                  # stock 240, kept
flow: 1.00                 # stock 0.99, +0.01 from the YOLO test
retraction_mm: 0.8         # stock 0.8, kept: no stringing at any band
tolerance_free_at_mm: 0.4  # print-in-place hinge, provisional (tops over-extruded, see log)
---

# Elegoo PETG HF (black)

Calibrated 2026-10-17 from the stock `Elegoo PETG HF @ECC2` preset (240 C,
flow 0.99, bed 70 C on the textured PEI plate, fan up to 50%, max volumetric
18 mm3/s). Spool dried 8 h at 65 C first (the label's numbers). First PETG
on the author's printer. Top surfaces are still rough: not solved yet.

Slice with:
`python tools/slice_cc2.py model.stl --filament petghf --temp 240 --flow 1.00`

## Log

- 2026-10-17 temperature tower 260-220 (5 C blocks, bed 70): 245-255 hairy
  tops and wisps (ooze), 225-230 slightly rough labels and overhang lips,
  235-240 cleanest; overhangs and bridges fine throughout. Picked **240**.
  The tower fell at the 225 C block: plate adhesion held, the tower snapped
  through its 15% base infill after the nozzle caught a curled edge
  (`../guides/gotchas.md` item 26). Blocks 230-260 were complete.
- 2026-10-17 flow YOLO at 240 / 0.99: +0.01 looked best, +0.02 to +0.05
  blobby. **1.00**. Diagonal streaks on the patches at the right of the bed
  showed at every flow, so they come from position (Z or mesh), not flow.
- 2026-10-17 retraction tower 0.0-1.2 mm (card v3 `--retraction-only`): no
  stringing at any band, even 0.0. Stock 0.8 kept. The temperature tower's
  strings came from the hot blocks, not from retraction.
- 2026-10-17 hinge test ([MakerWorld 388977](https://makerworld.com/en/models/388977)):
  free at 0.4 (maybe 0.3); 0.10 and 0.15 fused (the 0.10 arm broke before it
  moved). Much looser than the PLA records. Provisional: that slice used the
  stock process `top_solid_infill_flow_ratio` 1.09, so its tops were 9% over
  the calibrated flow.
- 2026-10-17 rough tops: a hinge re-slice at `top_solid_infill_flow_ratio`
  1.00 (nothing else changed) was still pitted and blobby. A 3-bar top test
  (control, flow 0.95, concentric top) was rough on all three; 0.95 slightly
  better lines, concentric worst; strings and blobs at line ends and bar edges
  curling up. Open. Inference, not tested: the stock top speed (200 mm/s) is
  about 17 mm3/s at 0.42 x 0.2 mm, close to the preset's 18 mm3/s limit, so
  slower tops are the next thing to try; also check the nozzle is clean (a
  white PLA control bar on the same plate).
