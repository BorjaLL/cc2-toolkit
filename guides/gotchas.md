# CC2 gotchas

Things that cost me a print or a debugging session, mostly found while slicing
from the command line with `tools/slice_cc2.py`. Dates are when I hit them. The
first two items are corrections to advice I found elsewhere.

## Fans and door

1. **Aux/side fan.** The stock **PLA PRO** profile already runs the side fan at
   **70%** (plain PLA ships it off). 70% can **warp large flat PLA parts** while
   helping small detailed ones. For a big flat print, use `--auxfan 0` (or
   20-30). For small, detailed parts, leave it stock. On ABS/ASA it is harmful.
   Main part-cooling fan stays ~100% for PLA.
2. **Door shut is fine for PLA (2026-09-28, from the printer's own log).** The
   back (cavity) fan is a thermostat: 10% below 36 C, 20% at 36 C, faster only
   above 37-39 C, PLA limit 40 C. Door shut, the chamber sat at 34-36 C and the
   fan never needed more than 20%. Open the door only if a long print starts
   clean and then under-extrudes or fades; do not crack a closed door mid-print,
   the temperature swing leaves a layer mark. More: `tuning.md`.

## Slicing from the command line

3. **Multi-part / multi-color 3MFs.** If a 3MF assigns its objects to different
   filament slots, the CLI slices it as a multi-color print: a filament swap
   every layer, exploding the time (one test hit 601 changes / 23 h vs 5 h for
   the single-material version). For single-color output from a multi-part 3MF,
   assign all objects to one filament in the ElegooSlicer GUI and re-export, or
   slice a single-object STL. Ordinary single-object models slice clean.
4. **M600 pauses hang the CC2.** Designer 3MFs can add a filament-change pause
   (`M600`). On the CC2 with CANVAS the printer froze there with the nozzle on
   the part and melted it; resume after power-off hung again (2026-09-24).
   `tools/slice_cc2.py` **strips `M600` automatically** and prints how many it
   removed; `--keep-pauses` keeps them (with a warning). For G-code sliced
   elsewhere: `tools/send_cc2.py` refuses files with `M600` before upload and
   before every `--start` (it reads the printer file back). A plain
   `grep -c '^M600'` misses `M600 ; comment` style lines; the tools do not.
   For a planned CANVAS colour swap, use a ToolChange (type 2) in the 3MF's
   `custom_gcode_per_layer.xml`, not `M600`. With CANVAS auto refill on
   (Settings > CANVAS Options, present on 01.03.02.36) and the same filament in
   two slots, a runout should continue from the second slot (available; a real
   runout not yet tested).
5. **Designer 3MF settings are replaced, per-object ones are kept.**
   `--load-settings` swaps in the CC2 process, so the 3MF's own process values
   (layer height, infill, ...) are dropped. Keys the tool leaves unset fall back
   to the 3MF (this is how a designer `no_brim` once leaked through).
   Per-object overrides in `Metadata/model_settings.config` (e.g.
   `enable_support`, `support_type`) ARE honoured. For a 3MF the script prints a
   **preflight**: the designer values it replaced and every per-object override.
   Keep a designer value with `--proc KEY=VALUE`.
6. **Tall thin parts standing on their end.** A 50 x 13.5 x 119.5 mm part with a
   5 mm wall (a toy-train trim piece, 2026-09-25) printed to the right length
   (119 mm measured) but with bands at ~0-10, ~20 and ~38 mm from the bed end.
   What the gcode shows:
   - once the short plate-mates end (Z 15-18) it prints alone at **~3.7 s/layer**
     all the way to Z 119; stock min layer time is 4 s, so there is almost no
     cooling slowdown. Hot, soft layers squash and widen.
   - baked-in ironing makes long dwells: Z 9.6 (126 s, top of the bed-end
     block), Z 15.0 (187 s, ironing the other parts), Z 37.8 (13.5 s, an
     internal top face), against ~15 s before and ~3.7 s after. Each lines up
     with a band.
   - first 3 layers: fan ramps up, elephant-foot compensation 0.1 on layer 1 only.
   The mating face of that block was designed with **0.0 mm** clearance to its
   base, so any widening binds. In the tool:
   - `brim_type=auto_brim` is set explicitly (`--no-brim` still turns it off), so
     a 3MF's `no_brim` cannot remove it. General hardening, not proven for this case.
   - `--min-layer-time N` (filament `slow_down_layer_time`).
   - a preflight WARNING for parts >= 40 mm tall with height / smallest footprint
     side >= 4, saying whether they print alone above their plate-mates.
   Recommended, NOT validated: for a flagged part use `--min-layer-time 8`,
   `--proc ironing_type=topmost` (or `no_ironing`), add a second copy or a
   cooling tower, or give it its own plate. For zero-clearance mating parts,
   caliper-check the mating face before gluing and sand it if needed.
7. **Bambu Studio 2.x 3MFs.** The CLI rejects them as "newer" with a silent exit
   -24 (4294967272). The script always passes `--allow-newer-file`. Run the
   slicer with `--debug 5` to see the real error text. The next error I hit on
   one such 3MF was `raft_first_layer_expansion: -1 not in range`; fix with
   `--proc raft_first_layer_expansion=2`. Designer colour slots above 4 must be
   remapped in the 3MF (`extruder` in `model_settings.config`, plus
   `paint_color` states).
8. **More slots than the 3MF has filaments crashes the CLI** (exit 3221225477 /
   0xC0000005, empty log), e.g. `--slots 4` on a 2-filament Bambu 3MF. Pad the
   3MF's per-filament arrays in `Metadata/project_settings.config` (and
   `filament_maps` in `model_settings.config`) to the slot count.
9. **Prime tower was silently off on every multi-slot slice before 2026-09-27.**
   The CLI turns the tower off when all `--load-filaments` presets have the same
   name (OrcaSlicer.cpp, "disable prime tower for only one filament!", OrcaSlicer
   PR #15636), and it does this after `--load-settings`, so
   `--proc enable_prime_tower=1` did nothing. `slice_cc2.py` now names each
   slot's preset "... (slot N)" (settings unchanged), so the Elegoo default
   `enable_prime_tower=1` works: **multi-colour slices now get a tower** (a little
   more time and filament). Why keep it: the CC2 purges into the chute, and the
   first lines after a swap came out thin without a tower. Turn it off with
   `--proc enable_prime_tower=0`. Older multi-colour gcodes made before that date
   have no tower.
10. **`--no-arrange` passes `--arrange 0`; sequential (by-object) printing works.**
    With no `--arrange` flag at all the CLI still packs plain STLs and generic
    3MFs by itself (only BBL-style 3MFs were left alone), so before 2026-09-27
    `--no-arrange` did not keep STL positions. Several STLs now keep their
    spacing, which `--proc "print_sequence=by object" --proc print_order=as_obj_list`
    needs: objects print one after the other in file order. The CLI refuses
    objects whose hulls are closer than `extruder_clearance_radius` (CC2: 65 mm;
    "is too close to others", exit 127) and its own arrange packs them at
    exactly that gap; keep them under `extruder_clearance_height_to_rod` (36 mm)
    or the gantry meets them. In the G-code `;LAYER:` runs on across objects
    while `;Z:` restarts per object, and the slicer emits
    `M104 S<first layer temp>` between objects. First use: `../calibration/card/`
    (card first, temperature tower alone afterwards, `M109` per band). A
    hand-written 3MF with the BambuStudio `Application` metadata but no project
    settings crashes the CLI (0xC0000005): use STLs or a complete Bambu 3MF.
11. **The slicer's exit codes are huge on Windows** (-6 shows as 4294967290). Since
    toolkit 1.2.0 `slice_cc2.py` exits with small stable codes (4 = slicer failed,
    see `tools/README.md`) and stores the slicer's own code in
    `slice_result.json` (`slicer_exit_signed`); the `exit N` line still shows it.
12. **CLI slices have no preview image.** If you add one, keep the PNG size a
    multiple of 3 bytes: the CC2 silently drops a thumbnail whose base64 ends in
    `=` padding (the largest that worked was about 10000 base64 characters).
13. **Ironing written as `nan`.** On one two-part object ElegooSlicer wrote the
    ironing pass with `WIDTH nan` and an E value of about -9.2e13. Search the
    G-code for `nan` before printing anything ironed (2026-10).
14. **Support gap rounds to layers.** At 0.2 mm layers,
    `support_top_z_distance = 0.3` printed as a 0.4 mm gap.

## Printer

15. **Never `strace -f` the GUI** (froze the touchscreen at print start, power
    cycle needed, 2026-09-29). See `firmware-and-ssh.md`.
16. **Cracked base panel, exposed CANVAS spools, thin ecosystem** were the risks
    I accepted at purchase; a small number of anecdotal cracked-panel reports, no
    recall, Elegoo replaces case by case. CANVAS spools hang exposed on the side
    and take up moisture in use.
17. **CC1 parts do not fit the CC2.** The "Multi-Size Hotend Kit for Centauri
    **Series**" fits the CC2; the "Assembled Extruder Hotend Kit for Centauri
    **Carbon**" is the CC1's. The product pages have a Compatibility tab that
    is collapsed by default and renders as empty text: expand it in a browser,
    do not trust the product name.
18. **Reboot only with the nozzle below about 50 C.** The hotend fan does not
    run during boot; two reboots soon after a print were each followed by a
    partial clog (suspected heat creep). See `firmware-and-ssh.md`.
19. **Files sent over SFTP look broken in the phone app** (0 layers, about
    1 min, no thumbnail) until the next boot; the touchscreen is fine. Reboot
    when idle and cool, or give a re-sent file a new name. See
    `firmware-and-ssh.md`.
20. **Seen and harmless so far:** thousands of `tmc_uart _decode_read` errors
    in the log (suspect them if layers shift); a single chamber reading jumping
    about 12 C for 10 s, which sends the cavity fan to 100% briefly (a sensor
    spike); one retried `LOAD_CELL_ERROR_TIMEOUT` (803) during levelling. Stock
    log timestamps are China time.

## Hotend and first layer

21. **Bumps, blobs and brown flecks on the first layer: look under the silicone
    sock first** (2026-10-12). On the author's printer plastic was weeping from
    the nozzle / heater-block joint and had built a burnt crust on the block.
    Every stop wetted the line and brown bits dropped onto the part. Slicer
    changes, bed temperature, speed and a fresh mesh did not help. Fix: heat to
    printing temperature, brass-brush the block and tip, check the nozzle is
    snug, and replace the nozzle if it keeps weeping. Re-run the full
    on-printer calibration after a nozzle swap.
22. **Caliper a new brand's filament.** One budget PLA roll measured
    1.70-1.82 mm (spec 1.75 +/- 0.02). That is up to about 8% more plastic per
    mm than nominal and a 15% swing along the roll, and it gave blobs, ooze and
    patchy adhesion; another roll ran the same file cleanly. Out-of-spec rolls may also leave residue on the hotend
    (suspected).
23. **First part on the plate blotchy: purge ooze** (2026-10-09). The CC2 start
    G-code draws a purge line at the front and then travels straight to the
    first part. With no skirt, the nozzle arrived still oozing. A 2-loop skirt
    3 mm out catches it.
