# cc2-toolkit

Notes, calibration prints and scripts for the **Elegoo Centauri Carbon 2 (CC2)**,
from one owner's first weeks with the printer. It is a mix: some results come
from real prints, some files are only checked in software (sliced, measured,
not printed yet). Each calibration folder says which in its README and
`verification.json` (`physical_print_tested`).

Your printer, bench and filament differ from mine. The guides show you how to
find **your** numbers; my results live in `examples/` as one worked example, not
as recommended values.

## What's inside

| Folder | What |
|---|---|
| `guides/` | Find your numbers (input shaper vs slicer accel), tuning, SSH / firmware access, rigid feet |
| `calibration/` | Printable tests with generators: calibration card, temperature tower, ironing grid |
| `filaments/` | Per-filament results template + worked results (Elegoo PLA, PLA+, PLA-CF) |
| `tools/` | Slice from the command line, send to the printer, check gcode accel against your calibration |
| `examples/` | My measured numbers with full setup details |

## Share your results

Open an issue with the "CC2 results" template: firmware, bench, shaper
results, the accel you chose and what the print looked like.

## License

Code MIT (`LICENSE`), docs and models CC BY 4.0, with one AGPL-3.0
exception (the ElegooSlicer temperature tower mesh). Details: `NOTICE.md`.
