# Max volumetric speed (MVS) ramp tower (CC2, no GUI)

**What it tests:** how many mm3/s of filament the hotend can melt before the wall
thins, gaps or the extruder clicks. That number is the filament's
`filament_max_volumetric_speed`, the cap the slicer uses to slow down fast features.

`build_mvs_tower.py` is the headless version of OrcaSlicer's **Max flowrate** test:

- **Shape:** OrcaSlicer's own `SpeedTestStructure.drc`, decoded from your ElegooSlicer
  install at run time: a 180 x 100 mm meander with ~1140 mm of wall per layer, long
  straights and R 10-20 mm U-turns, cut at 60 mm. Long layers keep the wall from
  overheating, and the straights let the toolhead reach the commanded speed (a small
  cylinder fails on both: short layers sag and read as a melt failure, tight curves keep
  the head slow and give a false pass).
- **Slice:** through `tools/slice_cc2.py`: spiral vase, 1 wall, Orca's 0.7 mm line and
  0.32 mm layer, no top or infill, no brim, 1 solid bottom layer, outer wall accel
  `--wall-accel` (default 5000), MVS raised to 40 so the slicer does not clip the ramp.
- **Ramp:** post-processing sets F on every wall move above the first layer so the flow
  rises linearly from `--lo` at the bottom to `--hi` at 60 mm (default 10 -> 40 mm3/s,
  0.5 mm3/s per mm, like Orca). Speed per move is computed from that move's real E per
  mm, so the flow column is what the nozzle actually melts.
- **Check:** flow per layer re-measured from the output (each 5 mm table row within 5%),
  wall accel, nozzle temp, and a Klipper lookahead model of how much of the top band runs
  at full speed. Default settings: 94% of the top-band path at full speed, delivered flow
  0.4% under commanded, top layers 5.5 s.

**Status:** printed by the author once (Elegoo PLA Matte, results below).

## Run

Needs ElegooSlicer 1.5.3.5 (`ELEGOO_SLICER_DIR`, default `C:/Program Files/ElegooSlicer`)
and Python with `DracoPy trimesh numpy` (`uv run` installs them from the script header).

```powershell
uv run calibration/mvs/build_mvs_tower.py --filament plamatte --tag PLAMatte --temp 215
```

- `--filament`: a `tools/slice_cc2.py --filament` key (`pla`, `plaplus`, `plapro`, `plamatte`, ...).
- `--lo` / `--hi`: flow at the bottom and at the top, mm3/s (default 10 / 40).
- `--temp`: nozzle C (default 215). `--out DIR`: output folder (default: this folder).

Output: `CC2_<tag>_MVSTower_<lo>-<hi>_T<temp>.gcode` (default settings: about 38 min, 56 g),
`<same name>_ramp-table.md` (flow and speed every 5 mm, with an empty "Wall OK?" column
to fill in) and `verification_<tag>.json`. If `tools/thumbnail.py` is present, the G-code
also gets a printer file-list preview. The G-code selects CANVAS slot 1 (`T0`).

**Print at 100% speed** (screen mode balanced, M220 S100). Sport mode (130%) multiplies
every flow on the tower by 1.3 and the table no longer applies.

## Read it

Caliper the wall every 5 mm on a long straight. The failure point is the first height
with more than 10% thinning, gaps in the wall, or extruder clicks. Read that height's flow
from the ramp table, then set the filament's max volumetric speed to **85% of the last
height that passed**. If the tower never fails, re-run with a higher `--hi`; if it fails
below 20 mm3/s, try 10 C hotter.

## Author's result (one printer, 2026-10-05)

Elegoo PLA Matte, 215 C, 10 -> 40 mm3/s: clean to ~27 mm (23.5 mm3/s), first gaps at
~28 mm (24 mm3/s), clearly under-extruded from ~31 mm (25.5 mm3/s). Limit set to
**20 mm3/s** (85%); the stock preset has 16.

## License

`build_mvs_tower.py` is part of this toolkit. The test shape comes from ElegooSlicer /
OrcaSlicer (`resources/calib/volumetric_speed/SpeedTestStructure.drc`, AGPL-3.0); the cut
mesh and the G-code made from it are derived from it and stay under AGPL-3.0 (see
`NOTICE.md`). Neither is committed here: the script rebuilds them from your own
ElegooSlicer install.
