---
name: White PLA (slot 2 Elegoo confirmed, others unknown)
material: PLA
base_preset: Elegoo PLA @ECC2
slicer_key: pla
user_preset: Elegoo PLA emoji (calibrated)  # inherited from elegoo-pla-emoji.md
preset_json:
temp: 210                  # inherited from elegoo-pla-emoji.md, not separately calibrated
flow: 1.00                 # inherited from elegoo-pla-emoji.md, not separately calibrated
retraction_mm: 0.8         # inherited from elegoo-pla-emoji.md, not separately calibrated
tolerance_free_at_mm:
---

# White PLA (slot 2 Elegoo confirmed, others unknown)

Slot 2 spool confirmed Elegoo PLA, plain white (same line as the emoji spool,
different colour). Per the run-book rule "same line, new colour -> reuse the
preset" (`calibration/README.md`), this reuses the emoji preset's values as-is;
they are inherited from `elegoo-pla-emoji.md`, not separately calibrated for
this spool.

Slice with:
`python tools/slice_cc2.py model.stl --filament pla --temp 210 --flow 1.00`

The other white spools have unchecked brands. Total white on hand (all
spools incl. slots 1-2) is ~2 kg per owner, 2026-09-26. Check the label before printing: if Elegoo PLA, this preset applies;
otherwise run `calibration/README.md` Steps 1-3 from `Elegoo PLA @ECC2`.

Planned use: a print-in-place puzzle box.

## Log

- 2026-09-23 owner confirmed slot 2 spool is Elegoo PLA white; reusing emoji preset.
- 2026-09-26 owner: ~2 kg white in total (stock table corrected; was "3 rolls + slots").
