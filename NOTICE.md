# Licenses and third-party material

- **Code** (`*.py`): MIT, see `LICENSE`.
- **Docs, models and G-code made here**: CC BY 4.0,
  https://creativecommons.org/licenses/by/4.0/
- **Exception, temperature tower**: `calibration/temperature/Elegoo_TempTower_230-190C.stl`
  and the G-code sliced from it are cropped from ElegooSlicer's bundled
  `resources/calib/temperature_tower/temperature_tower.drc`
  ([ElegooSlicer v1.5.3.5](https://github.com/elegooofficial/ElegooSlicer/tree/v1.5.3.5/resources/calib/temperature_tower)).
  ElegooSlicer is AGPL-3.0; these files stay under its license, not CC BY.
  `build_tower.py` rebuilds them from your own ElegooSlicer install.
- **Slicer profiles**: `slice_cc2.py` and the calibration scripts read the stock
  Elegoo profiles from your ElegooSlicer install at run time; flattened copies
  under `calibration/temperature/profiles/` are derived from those profiles
  (AGPL-3.0).
