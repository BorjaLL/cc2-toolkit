# Filaments

One file per filament **brand + type** (not per colour of the same line), named
`<slug>.md`:

- **Frontmatter** = the numbers (base preset, slicer key, temp, flow,
  retraction, tolerance, preset JSON path). No slot field: which spool sits in
  which CANVAS slot is your printer's state, not a filament fact.
- **Body** = a dated log of calibration runs and what was picked and why.
- **`presets/<slug>.json`** = the exported ElegooSlicer user preset, same slug.

`tools/slice_cc2.py` does **not** read these files. You read the
frontmatter and pass the values explicitly:
`--filament <slicer_key> --temp <temp> --flow <flow>`.

How to calibrate a new filament: `calibration/README.md`.

## Records

| Filament | Base preset | Temp | Flow | Retraction | Fit (per side) |
|---|---|---|---|---|---|
| [Elegoo PLA RFID "emoji" (white)](elegoo-pla-emoji.md) | `Elegoo PLA @ECC2` | 210 | 1.00 | 0.8 | 0.2 |
| [White PLA (plain Elegoo)](white-pla.md) | `Elegoo PLA @ECC2` | 210 | 1.00 | 0.8 | inherited from emoji |
| [Elegoo PLA Matte](elegoo-pla-matte.md) | `Elegoo PLA Matte @ECC2` | 215 | 0.98 | 0.8 | 0.1 |
| [Elegoo PLA+ black](elegoo-pla-plus-black.md) | `Elegoo PLA+ @ECC2` | 210 | 0.98 | 0.8 | passed, no compensation |
| [DEEPLEE PLA+ 2.0](deeplee-pla-plus-2.md) | `Elegoo PLA+ @ECC2` | 220 | 1.00 | 0.8 | 0.2 |
| [SUNLU PLA+](sunlu-pla-plus.md) | `Elegoo PLA+ @ECC2` | 215 | 0.98 | 0.8 | 0.25 (hinge test) |
| [Elegoo PLA-CF black](elegoo-pla-cf-black.md) | `Elegoo PLA-CF @ECC2` | | | | not calibrated |
| [Elegoo PETG HF black](elegoo-petg-hf-black.md) | `Elegoo PETG HF @ECC2` | 240 | 1.00 | 0.8 | 0.4 (hinge test, provisional); rough tops open |

On four of these (PLA Matte, PLA+ black, DEEPLEE, SUNLU) the retraction
tests strung only at 0.0 mm or not at all, so the stock 0.8 mm needed no
change for PLA-family filament on the CC2; Elegoo PETG HF did not string
at any band either. Fit numbers come from
different tests (rail thickness, hinge) and are one printer's results:
measure your own.
