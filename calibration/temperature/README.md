# CC2 emoji PLA temperature tower

Print **`CC2_Emoji_PLA_TempTower_230-190C_0.4mm.gcode`** directly from USB.
Generated with ElegooSlicer 1.5.3.5 on 2026-09-21. Estimated print time:
**55 min 4 s**; estimated filament: **16.84 g**.

The file selects **CANVAS slot 1 (`T0`)**. Put the emoji PLA in that slot;
using another slot or the external spool requires the corresponding mapping.
(Slot 1 is what the gcode selects, not a record of what is loaded; current
slots are in `filaments/README.md`.)
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
This file has been checked programmatically, **not physically print-tested**.

The STL is included for inspection. Reslicing that STL alone will lose the
temperature changes: use the provided G-code or rebuild through the script.

Source model and matching calibration implementation:
[ElegooSlicer v1.5.3.5](https://github.com/elegooofficial/ElegooSlicer/tree/v1.5.3.5/resources/calib/temperature_tower),
[Plater::calib_temp](https://github.com/elegooofficial/ElegooSlicer/blob/v1.5.3.5/src/slic3r/GUI/Plater.cpp#L13313-L13390).
