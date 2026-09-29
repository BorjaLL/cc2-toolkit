# Filaments

One file per filament **brand + type** (not per colour of the same line), named
`<slug>.md`:

- **Frontmatter** = the numbers (base preset, slicer key, temp, flow,
  retraction, tolerance, preset JSON path). No slot field: slots are state, and
  live only in the table below.
- **Body** = a dated log of calibration runs and what was picked and why.
- **`presets/<slug>.json`** = the exported ElegooSlicer user preset, same slug.

`tools/slice_cc2.py` does **not** read these files. You read the
frontmatter and pass the values explicitly:
`--filament <slicer_key> --temp <temp> --flow <flow>`.

How to calibrate a new filament: `calibration/README.md`.

## CANVAS slots (current state)

This is the **only** place slots are recorded. Updated: **2026-09-23**.

| Slot | Filament | Source |
|---|---|---|
| 1 (T0, per temp tower gcode) | [Elegoo PLA RFID emoji edition (white)](elegoo-pla-emoji.md) | owner, 2026-09-23 |
| 2 | [Elegoo PLA, plain white](white-pla.md) | owner, 2026-09-23 |
| 3 | empty | owner, 2026-09-23 |
| 4 | [Elegoo PLA+ black](elegoo-pla-plus-black.md) | owner, 2026-09-23 |

## Stock

| Qty | Filament | Source | Record |
|---|---|---|---|
| ~2 kg total | White PLA, all white incl. slot 1 (emoji white) + slot 2 (plain white); spares brand unknown | owner, 2026-09-26 (was listed as 3 rolls: 2 gifted + 1 prior) | [white-pla.md](white-pla.md) |
| 1 | Elegoo PLA-CF black | free promo roll | [elegoo-pla-cf-black.md](elegoo-pla-cf-black.md) |
| in the ~2 kg white above | Elegoo PLA RFID "emoji" edition (white, slot 1) | owner, 2026-09-26 | [elegoo-pla-emoji.md](elegoo-pla-emoji.md) |
| 1 | Elegoo PLA+ black | bought for a puzzle project | [elegoo-pla-plus-black.md](elegoo-pla-plus-black.md) |

