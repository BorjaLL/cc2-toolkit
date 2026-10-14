# CC2 emoji PLA temperature tower

Print **`CC2_Emoji_PLA_TempTower_230-190C_0.4mm.gcode`** directly from USB.
Generated with ElegooSlicer 1.5.3.5 on 2026-09-21. Estimated print time:
**55 min 4 s**; estimated filament: **16.84 g**.

The file selects **CANVAS slot 1 (`T0`)**. Put the emoji PLA in that slot;
using another slot or the external spool requires the corresponding mapping.
(Slot 1 is what the gcode selects, not a record of what is loaded.)
It is for the **Centauri Carbon 2 with a 0.4 mm nozzle** and the **textured PEI
plate**. Run at normal / 100% speed, and inspect the first layer for adhesion.
Keep the same enclosure conditions for calibration and subsequent PLA prints.

| Setting | Value |
|---|---|
| Nozzle temperature | 230 to 190 C, decreasing 5 C per block |
| Bed temperature | 60 C throughout |
| Layer height | 0.20 mm; 450 layers |
| Model height | 90 mm |
| Brim | 5 mm, outer only |
| Flow ratio | Stock Elegoo PLA: 0.98 |
| Retraction | Stock: 0.8 mm at 30 mm/s |
| Pressure advance | Stock enabled: 0.04 |
| Auxiliary fan | Stock plain PLA: off |
| Supports / ironing / prime tower | Off |
| Filament changes during the print | None |

The embossed labels match the temperature bands. From bottom to top:
**230, 225, 220, 215, 210, 205, 200, 195, 190 C**. After cooling, compare
bridging, overhangs, stringing, and layer bonding. Choose the middle of a range
that performs well; use the hotter end if higher printing speeds need it.

## Generation and verification

`build_tower.py` decodes ElegooSlicer's bundled temperature-tower mesh and crops
the same nine 10 mm blocks as the built-in temperature calibration. It slices
with the installed stock Elegoo CC2 / PLA profiles and calibration overrides.
An explicit layer-change G-code template sets each band's temperature during
slicing; there is no manual temperature editing required.

Rebuild with:

```powershell
uv run calibration/temperature/build_tower.py
```

The three resolved profiles are preserved in `profiles/`. Profile inheritance
is restricted to the Elegoo vendor directory because unrelated vendors reuse
base-profile names. The general slicing helper in `tools/` is not used.

`verification.json` records source hashes, output SHA-256, mesh validation,
all nine transitions, print bounds, and the slicer's estimates. The validator
checks the effective temperature at all 56,588 printed extrusion moves,
CC2 startup/bed leveling, final heater shutdown, and stock flow/retraction/PA.
The mesh is watertight and the printed geometry fits within the build area.
This file has been checked programmatically, and the author printed it on
2026-09-21 (results below).

The STL is included for inspection. Reslicing that STL alone will lose the
temperature changes: use the provided G-code or rebuild through the script.

Source model and matching calibration implementation:
[ElegooSlicer v1.5.3.5](https://github.com/elegooofficial/ElegooSlicer/tree/v1.5.3.5/resources/calib/temperature_tower),
[Plater::calib_temp](https://github.com/elegooofficial/ElegooSlicer/blob/v1.5.3.5/src/slic3r/GUI/Plater.cpp#L13313-L13390).

## Other filaments and ranges

```powershell
uv run calibration/temperature/build_tower.py --preset "Elegoo PLA Matte @ECC2" --tag PLAMatte
uv run calibration/temperature/build_tower.py --preset "Elegoo PLA+ @ECC2" --tag PLAPlus --top 240
uv run calibration/temperature/build_tower.py --preset "Elegoo PETG HF @ECC2" --tag PETGHF --top 260 --out D:/towers
```

| Option | Meaning |
|---|---|
| `--preset` | any stock Elegoo CC2 filament preset; its bed temp, flow and PA are used and checked in the output |
| `--tag` | file name tag, required with a non-default preset (keeps the committed emoji PLA files intact) |
| `--top` | hottest (bottom) block in C; the tower always spans `top` down to `top - 40` in 5 C blocks, labels match (the bundled model is cropped at that height) |
| `--brim` | outer brim width in mm (default 5); 10 for a filament that lifts off the bed |
| `--accel` | a `tools/slice_cc2.py` ACCEL profile name, to judge the tower at the accelerations you print with (default `stock`) |
| `--out` | output folder (default: this folder) |

It writes `CC2_<Tag>_TempTower_<top>-<top-40>C_0.4mm.gcode`, `verification_<Tag>.json`,
the cropped STL and `profiles/flat_*.json` into the output folder. With the default
`--out`, the profiles in `profiles/` are rewritten: restore them with `git checkout`
afterwards, or use `--out`. If `tools/thumbnail.py` is present, the G-code also gets a
printer file-list preview. ElegooSlicer is found through `ELEGOO_SLICER_DIR`
(default `C:/Program Files/ElegooSlicer`).

Only the emoji PLA tower is committed. The other ranges (for example 240-200 or
220-180) are cropped from the same ElegooSlicer model on every run, so their STLs are not
stored here.

## Reading page

Open [evaluate-temp-tower.html](evaluate-temp-tower.html) in a browser: what each part of
a block tests, cold / right / hot pictures for the five checks, and a guided reading
(set the hottest block, click one answer per block and check) that picks the temperature
and writes a summary to copy into your filament notes. Nothing leaves the browser.

## Author's results (one printer, 2026-09 to 2026-10)

| Filament (preset) | Tower | Picked | Notes |
|---|---|---|---|
| Elegoo PLA "emoji" (`Elegoo PLA @ECC2`) | 230-190 | 210 | 190 snapped, 195-200 creaked, 205 and up solid; no upper limit found |
| Elegoo PLA Matte (`Elegoo PLA Matte @ECC2`) | 230-190, bed 65 C | 215 | |
| DEEPLEE PLA+ 2.0 (`Elegoo PLA+ @ECC2`) | 230-190 | 220 | 215 near-identical |
| SUNLU PLA+ (`Elegoo PLA+ @ECC2`) | 240-200 | 215 | 200-215 crisp; from 220 the numbers blob; 230-240 string |

## License

`build_tower.py` and `evaluate-temp-tower.html` are part of this toolkit. Every
`Elegoo_TempTower_*.stl`, the G-code sliced from them and `profiles/flat_*.json` are
derived from ElegooSlicer (AGPL-3.0) and stay under its license (see `NOTICE.md`).
