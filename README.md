# cc2-toolkit

Notes, calibration prints and scripts for the **Elegoo Centauri Carbon 2 (CC2)**,
from one owner's first weeks with the printer. It is a mix: some results come
from real prints, some files are only checked in software (sliced, measured,
not printed yet). Each calibration folder says which in its README and
`verification.json` (`physical_print_tested`).

Your printer, bench and filament differ from mine. The guides show you how to
find **your** numbers; my results live in `examples/` as one worked example, not
as recommended values.

## What changed (2026-10)

Firmware 01.03.02.36 throughout.

- **Accel:** walls printed clean up to the printer's 20000 limit on rigid feet,
  well above the shaper's estimate (`guides/find-your-numbers.md`,
  `examples/borja-floor-slab/`).
- **Rigid feet printed and in use:** sway moved from about 6.5 Hz to about
  19 Hz (`guides/rigid-feet.md`).
- **Noise:** belts ring in a speed band (50-62.5 mm/s on the author's printer);
  how to find yours, quiet profile and Z-hop notes (`guides/tuning.md`).
- **New gotchas:** a weeping hotend crust behind first-layer blobs, purge ooze
  on the first part, out-of-spec filament diameter, reboot only when cool
  (`guides/gotchas.md`).
- **Firmware / SSH:** log rotation, SFTP files missing from the app until
  reboot, queued commands during levelling, camera thread leak, TMC2209
  StealthChop findings, COSMOS CC2 alpha (`guides/firmware-and-ssh.md`).
- **Calibration:** headless generators for the flow (YOLO) test, max
  volumetric speed tower, card v3 and temperature towers for any range; the
  v1 card's flow and temperature rows were unreliable; tolerance now uses a
  print-in-place hinge test (`calibration/README.md`).
- **Filaments:** Elegoo PLA Matte, DEEPLEE PLA+ 2.0 and SUNLU PLA+ records;
  stock 0.8 mm retraction held on every PLA-family filament tested
  (`filaments/`).

## What's inside

| Folder | What |
|---|---|
| `guides/` | Find your numbers (input shaper vs slicer accel), tuning and noise, gotchas, SSH / firmware access, rigid feet |
| `calibration/` | Printable tests with headless generators: temperature tower, YOLO flow, max volumetric speed, calibration card, ironing grid |
| `filaments/` | Per-filament results template + worked results (Elegoo PLA, PLA Matte, PLA+, PLA-CF; DEEPLEE and SUNLU PLA+) |
| `tools/` | Slice from the command line (quiet accel presets, adaptive layers), send and start over SSH, check G-code accel against your calibration |
| `examples/` | My measured numbers with full setup details |
| `tests/` | Offline regression tests for `tools/` |

## Share your results

Open an issue with the "CC2 results" template: firmware, bench, shaper
results, the accel you chose and what the print looked like.

## License

Code MIT (`LICENSE`), docs and models CC BY 4.0, with AGPL-3.0 exceptions
for meshes and profiles derived from ElegooSlicer's calibration resources.
Details: `NOTICE.md`.
