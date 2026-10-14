# Licenses and third-party material

- **Code** (`*.py`): MIT, see `LICENSE`.
- **Docs, models and G-code made here**: CC BY 4.0,
  https://creativecommons.org/licenses/by/4.0/
- **Exception, meshes from ElegooSlicer / OrcaSlicer calibration resources**:
  these files, and any G-code sliced from them, are derived from the
  calibration models bundled with ElegooSlicer
  ([ElegooSlicer v1.5.3.5](https://github.com/elegooofficial/ElegooSlicer/tree/v1.5.3.5/resources/calib),
  an OrcaSlicer fork). ElegooSlicer is AGPL-3.0; these files stay under its
  license, not CC BY:
  - `calibration/temperature/Elegoo_TempTower_*.stl` (cropped from
    `resources/calib/temperature_tower/temperature_tower.drc`)
  - `calibration/flow/Orca-LinearFlow_bed.stl` (the YOLO flow test)
  - `calibration/card/card_v3_*.stl` (the v3 card's flow patches and
    retraction tower, from Orca's YOLO and `retraction_tower.drc` models)
  - the max volumetric speed tower mesh `calibration/mvs/` cuts from
    `resources/calib/volumetric_speed/SpeedTestStructure.drc`

  Only the 230-190 C tower STL is committed; the generators (`build_tower.py`,
  `calibration/flow/`, `build_card_v3.py`, `calibration/mvs/`) build the rest
  from your own ElegooSlicer install. G-code sliced from any of them is
  AGPL-3.0 too.
- **Slicer profiles**: `slice_cc2.py` and the calibration scripts read the stock
  Elegoo profiles from your ElegooSlicer install at run time; flattened copies
  under `calibration/temperature/profiles/` and `calibration/flow/profiles/`
  are derived from those profiles (AGPL-3.0).
- **Not included**: the print-in-place hinge tolerance test referenced in
  `calibration/README.md` is [MakerWorld 388977](https://makerworld.com/en/models/388977)
  (CC BY-SA); download it from there.
