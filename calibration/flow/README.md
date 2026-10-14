# Flow ratio: Orca YOLO patches (CC2, no GUI)

**What it tests:** the filament flow ratio, in 0.01 steps. `build_yolo.py` makes the same
print as ElegooSlicer **Calibration > Flow ratio > YOLO (Recommended)**: the bundled
`Orca-LinearFlow.3mf` (11 patches 30 x 30 x 2 mm, labelled -0.05 .. +0.05 around the
current flow) with the GUI's overrides (`Plater.cpp adjust_settings_for_flowrate_calib`:
1 wall, 2 bottom / 5 top layers, 35% sparse infill, 0.48 mm top lines, archimedean-chords
top, `top_solid_infill_flow_ratio` 1, top and solid speeds capped by the filament's max
volumetric speed). The GUI's per-object `print_flow_ratio` is a pure E multiplier, so the
script slices all patches together and scales E inside each patch's footprint, then checks
the per-patch E ratio.

**Status:** printed by the author on 3 PLA / PLA+ filaments (results below).

## Run

Needs ElegooSlicer 1.5.3.5 installed (`ELEGOO_SLICER_DIR`, default
`C:/Program Files/ElegooSlicer`) and Python with `trimesh numpy networkx lxml`
(`uv run` installs them from the script header).

```powershell
uv run calibration/flow/build_yolo.py --preset "Elegoo PLA Matte @ECC2" --tag PLAMatte --temp 215 --flow 0.98
```

- `--preset`: a stock Elegoo CC2 filament preset name.
- `--temp`: the nozzle temperature you picked with the temperature tower.
- `--flow`: the current flow ratio (stock presets: 0.98).
- `--out DIR`: output folder (default: this folder).

Output: `CC2_<tag>_FlowYOLO_T<temp>_F<flow>.gcode` (about 31 min, 14.3 g), `verification_<tag>.json`
(source hashes, speed caps, per-patch E ratio, slicer estimate), the bed-placed patch STL
and the flattened profiles. If `tools/thumbnail.py` is present, the G-code also gets a
printer file-list preview. The G-code selects CANVAS slot 1 (`T0`).

## Read it

Light at a low angle, fingernail across each patch. The smoothest top wins: the arcs
blend, no line between the inner spiral and the outer arcs. Gaps between arcs = too
little; bumpy or rough = too much. Ties: the one nearer 0.
**New flow = old flow + patch label** (for example 0.98 + 0.02 = 1.00).

Why not the calibration card's flow pads: the stock 0.20 mm process prints top surfaces
with `top_solid_infill_flow_ratio` 1.09, so pads sliced with it are all over-extruded on
top and give no flow answer. YOLO sets that ratio to 1 (see `../card/README.md`).

## Author's results (one printer, 2026-10)

| Filament (preset) | Temp / base flow | Smoothest patch | Flow |
|---|---|---|---|
| Elegoo PLA Matte (`Elegoo PLA Matte @ECC2`) | 215 / 0.98 | 0 | 0.98 |
| DEEPLEE PLA+ 2.0 (`Elegoo PLA+ @ECC2`) | 220 / 0.98 | +0.02 | 1.00 |
| SUNLU PLA+ (`Elegoo PLA+ @ECC2`) | 215 / 0.98 | 0 (read from a photo, not confirmed by hand) | 0.98 |

The positive patches on the SUNLU run showed a raised ring at the circle edge, the
negative ones rougher labels.

## License

`build_yolo.py` is part of this toolkit. The patch model (`Orca-LinearFlow.3mf`) and the
profiles it flattens come from ElegooSlicer (AGPL-3.0); the patch STL,
`profiles/flat_*.json` and the G-code it writes are derived from them and stay under
AGPL-3.0 (see `NOTICE.md`). None of them is committed here: the script regenerates them
from your own ElegooSlicer install.
