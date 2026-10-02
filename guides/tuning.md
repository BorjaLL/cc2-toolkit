# CC2 print-quality tuning

Rewritten 2026-09-21 after a research pass that checked the original
claims against CC2 and community sources and mapped each fix to the real
ElegooSlicer profile key. Trimmed for this repo 2026-09-29.

Use the key table at the bottom if you are building your own profile or using
`tools/slice_cc2.py`. Everything above it is the reasoning.

Verdict tags: **[confirmed]**, **[partly]**, **[corrected]**, **[refuted]**.

## Two corrections to earlier advice (read first)

1. **Aux/side fan at 70% for PLA is wrong as a default. [corrected]** The side fan
   *is* off by default in the plain PLA profile (`additional_cooling_fan_speed
   = ["0"]`), but forcing it to 70% for PLA causes **warping, corner-lift and
   adhesion loss on large flat parts**. It only helps *small, detailed* parts
   with short layer times. On ABS/ASA it is actively harmful. (The stock PLA PRO
   profile ships it at 70%: see `gotchas.md`.)
2. **Door shut is fine for PLA on the CC2 [updated 2026-09-28 from the printer's
   own log].** The firmware runs the back (cavity) fan as a thermostat for PLA:
   10% below 36 C, 20% at 36 C, faster only above 37-39 C, PLA limit 40 C
   (`[cavity_fan]` in `/opt/inst/printer_dsp.cfg`). With the door shut the
   chamber sat at 34-36 C and the fan never needed more than 20%. Open the door
   only if a long print starts clean and then under-extrudes or fades (heat
   creep); don't crack a *closed* door mid-print - that swing leaves a layer mark.
   Read the log yourself (needs SSH, see `firmware-and-ssh.md`):
   `/opt/usr/logs/elegoo.log`, lines `cavity_fan ... cur_box_temp`.

The real PLA cooling story: **main part-cooling fan ~100%**, chamber kept under
~38 C by the cavity fan (door shut is fine), not the side fan.

## What actually improves prints (ranked)

1. **Cooling done right for PLA.** Main part fan ~100%; door shut is fine (chamber 34-36 C).
   Bump the side fan only for small detailed models. [partly/corrected]
2. **Calibrate flow per filament; don't blanket-bump. [partly]** Stock flow:
   plain PLA `0.98`, **PLA PRO already `0.99`**. Better than guessing: run
   ElegooSlicer's **temp tower, then flow rate (pass 1+2)** per spool, save to the
   *filament* profile. A top surface that starts clean then fades mid-print is
   *chamber heat*, not flow.
3. **Motion: acceleration trades speed against ringing, smoothing and shake.**
   Input shaping removes most ringing, and Klipper's own guide says acceleration
   still affects both ringing and shaper smoothing. On the author's printer the
   visible problem at stock accel was the printer rocking, not ringing. Find
   your own estimate (`find-your-numbers.md`) and compare test prints. The
   author's experience:
   - On a solid/heavy bench: keep accel high (the author used ~8-10k at one point),
     just cap outer-wall speed ~150 mm/s.
   - On a wobbly desk: **mass-load it** (paver + mat) first; that beats crippling
     accel. An aggressive 3000/2000 "antiwobble" set works but is overkill for
     quality and costs speed on infill/travel - use it only if you can't fix the desk.
   - Overnight next to a bedroom: start with `--accel night` (antiwobble accel,
     250 mm/s travel); `night2` (2000 accel, slower) and `night3` (night2 at half
     speed) are quieter. The author's first night2 overnight print was still too loud
     at full speed and fine at half speed; night3 is not printed yet. The screen's
     silent mode is only `M220 S50`: it halves speed but keeps acceleration.
   - What number to pick is a measurement, not a copy-paste:
     `find-your-numbers.md`. One worked example with dates and firmware:
     `../examples/borja-floor-slab/`.
4. **Top-surface quality levers (bigger wins than flow):** ironing (`slice_cc2.py`
   follows the designer's 3MF `ironing_type`, STL = off, `--iron` to force; topmost
   surface only, flow ~10-18%, ~15 mm/s) + **Monotonic** top pattern; top shell
   >= 4-5 layers / ~0.8-1.0 mm; "slow down for top surface". [confirmed, generic]
5. **Infill: stock is `rectilinear`, not gyroid. [corrected]** Switching to
   **cubic** (or grid / adaptive cubic) is quieter and a bit faster at ~same
   strength. Safe change.
6. **Acceleration vs wobble:** moved out of this guide. The method is in
   `find-your-numbers.md` and my measured numbers are in
   `../examples/borja-floor-slab/`.

Multicolor only: redirect purge with **flush-into-infill / flush-into-object**,
or split by color across plates + glue - a bigger win than tuning flush *volume*.

## Don't bother / don't break

- **Don't run the slicer Pressure Advance test; keep the stock value.**
  Corrected 2026-09-21: the stock `Elegoo PLA @ECC2` preset ships
  `enable_pressure_advance = 1`, `pressure_advance = 0.04`, and the G-code
  sends `SET_PRESSURE_ADVANCE ADVANCE=0.04`. Elegoo's product page says the
  printer's full calibration also tunes PA. Which value wins is unverified,
  so leave each material preset's stock PA (plain PLA/PLA+ 0.04, PLA PRO and
  PLA-CF 0.032, PETG 0.05, PETG PRO 0.1) and do not re-tune it per filament
  until that is tested. Re-run the on-printer calibration after a
  nozzle/hotend swap.
- **Firmware: stay on your delivered stock version; update only to fix a real
  problem.** The earlier note here said "No Klipper/SSH on the CC2". That was
  wrong: SSH works on stock firmware before 02.00.02.00 (the author's printer
  runs OTA 01.03.02.36 and SSH works). What is true: OpenCentauri's patched firmware
  and COSMOS (full Klipper) do not support the CC2, and 02.00.02.00 is reported
  to remove SSH. Details and a per-version table: `firmware-and-ssh.md`.
- **Don't grease the carbon X-rods.** Grease + dust = abrasive paste = play =
  ringing "no software can fix." Clean with 99% IPA ~every 50 h.
- **Stay on stock ElegooSlicer CC2 profiles** - they're CC2-tuned and well
  regarded for PLA. Community packs (Botmans, Willow) are optional starting
  points, not proven upgrades.

## Hardware / one-time

- Anti-shake: **mass on a rigid base** (16x16" paver + rubber mat). Elegoo's soft
  AV feet let the unit *rock* - don't rely on them. See `rigid-feet.md`.
- First layer: inspect before touching Z, adjust in 0.05 mm steps, re-run the
  **bed mesh** (not a global offset) if uneven; clean the nozzle before leveling.
- Match plate side to material (textured = grippy/CF; smooth = glossy PLA) and
  **recalibrate Z when you flip** (different thickness). Handle by edges, IPA clean.
- Remove the 3 bed shipping screws; buy snips (not included).

## Key table: keys for your own profile or `tools/slice_cc2.py`

Anyone building a flattened profile, or using `tools/slice_cc2.py`, can use this
table. Values as they appear in the JSON. **Process** values are bare strings;
**filament** values are single-element arrays (one per loaded filament).
`inherits:` is NOT resolved by the slicer CLI, so these live in a *flattened*
profile (`slice_cc2.py` does the flattening). Typical install path:
`C:\Program Files\ElegooSlicer\elegoo-slicer.exe`.

| Fix | Key | Profile | Stock | Set to | Verdict |
|---|---|---|---|---|---|
| Infill pattern | `sparse_infill_pattern` | process | `rectilinear` | `cubic` | safe |
| Top pattern | `top_surface_pattern` | process | (check) | `monotonic` | safe |
| Ironing | `ironing_type` / `ironing_flow` / `ironing_speed` | process | off | `top` / `10-18` / `15` | safe |
| Top shell | `top_shell_layers` / `top_shell_thickness` | process | ~3 | `5` / `0.9` | safe |
| Solid infill direction | `solid_infill_direction` | process | 45 deg | `0` | untested on a print |
| Global accel | `default_acceleration` | process | `10000` | set from your own measurements, see `find-your-numbers.md` | your call |
| Outer-wall accel | `outer_wall_acceleration` | process | `5000` | set from your own measurements, see `find-your-numbers.md` | your call |
| Outer-wall speed | `outer_wall_speed` | process | ~`160` | `150` | safe |
| Flow (plain PLA) | `filament_flow_ratio` | filament | `["0.98"]` | calibrate (about `["0.99"]`) | calibrate |
| Aux fan (only small parts) | `additional_cooling_fan_speed` | filament | `["0"]` | leave `["0"]`; ~`["50"]` small detail only | do NOT blanket-set |
| Multicolor purge routing | `flush_into_infill` / `flush_into_object` | project | off | `1` | untested |

Accel is the one real decision and depends on your bench (see ranked #3). Jerk
keys are not in the Elegoo JSON (`default_jerk` defaults to firmware): leave
them. `flush_volumes_matrix` is project-scoped and may be ignored via a
flattened JSON: test before relying on it for multicolor.

## Calibration tests (do these to actually dial it in)

Benchy is a torture test, not a calibration test (community consensus, incl.
r/ElegooCentauriCarbon "Troubleshooting my CC2 Benchy"). To tune quality, run
the ElegooSlicer Calibration menu (it is an OrcaSlicer fork) per filament
brand/type. OrcaSlicer wiki order:

1. Temperature - https://github.com/OrcaSlicer/OrcaSlicer/wiki/temp_calib
2. Max Volumetric Speed - https://github.com/OrcaSlicer/OrcaSlicer/wiki/volumetric_speed_calib
3. Pressure Advance - https://github.com/OrcaSlicer/OrcaSlicer/wiki/pressure_advance_calib
4. Flow Ratio - https://github.com/OrcaSlicer/OrcaSlicer/wiki/flow_ratio_calib
5. Retraction - https://github.com/OrcaSlicer/OrcaSlicer/wiki/retraction_calib
6. Tolerance - https://github.com/OrcaSlicer/OrcaSlicer/wiki/tolerance_calib
7. Cornering (Jerk & Junction Deviation) - https://github.com/OrcaSlicer/OrcaSlicer/wiki/cornering_calib
8. Input Shaping - https://github.com/OrcaSlicer/OrcaSlicer/wiki/input_shaping_calib

Wiki index: https://github.com/OrcaSlicer/OrcaSlicer/wiki/Calibration

**CC2 note:** skip Pressure Advance (#3) and Input Shaping (#8) in the slicer.
Input shaping is measured on the printer. PA: each stock preset sends its own
PA (plain PLA 0.04) and the printer also tunes PA in its full calibration;
which wins is unverified, so keep the preset's stock value (see "Don't bother /
don't break" above). Practical per-filament sequence: **Temperature -> Flow
Ratio -> Retraction -> Tolerance.** Tolerance (#6) is the lever for sliding-fit
prints (e.g. a puzzle with sliding wagons). These are GUI-generated (the slicer
varies settings per band), so run them from the Calibration menu, not the
headless CLI. Step-by-step run-book (what to click, what to look at, what to
record): `../calibration/README.md`, with results per filament in `../filaments/`.

Extra troubleshooting resources:
- Simplify3D: https://www.simplify3d.com/resources/print-quality-troubleshooting/
- All3DP: https://all3dp.com/1/common-3d-printing-problems-troubleshooting-3d-printer-issues/
- Elegoo Z-offset fine-tune after re-level: https://wiki.elegoo.com/Centauri-carbon/tutorial-for-fine-tuning-after-automatic-re-leveling

## Sources

- Cooling: Elegoo aux-fan store/wiki pages, Bambu forum (aux fan on PLA), fixmyprint3d
- Motion: hackster/notebookcheck CC2 reviews, OpenCentauri docs, All3DP firmware
- Extrusion/surface: OrcaSlicer wiki (flow, ironing), Obico flow guide, Printago
- Discovery: whyitfailed, printer-hub known-issues, smith3d setup, xda (CANVAS waste)
- Profile keys were checked against the local ElegooSlicer CC2 profiles.
