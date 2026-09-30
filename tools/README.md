# CC2 tools

Command-line slicing and sending for the Elegoo Centauri Carbon 2. Tested on
Windows with ElegooSlicer 1.5.3.x and stock CC2 firmware OTA 01.03.02.36.

| File | What |
|---|---|
| `slice_cc2.py` | Flattens the stock ElegooSlicer CC2 profiles, applies a few overrides, slices with the slicer CLI |
| `send_cc2.py` | Uploads G-code to the printer over SFTP, lists / deletes files, starts a print remotely |
| `mf2stl.py` | 3MF (production extension) to binary STL: `python mf2stl.py in.3mf out.stl [build_objectid]` |

`slice_cc2.py` exists because the slicer CLI cannot resolve `inherits:` chains
from `--load-settings` files, so the profiles must be flattened first. The GUI
works just as well; this is for repeatable, scriptable slices.

## Slice

```bash
python tools/slice_cc2.py <model.3mf|stl> [more models ...] [options]
```

The slicer is expected in `C:/Program Files/ElegooSlicer`. If yours is
elsewhere, set `ELEGOO_SLICER_DIR` to the install folder.

Several models are sliced together: auto-arranged, and the slicer opens extra
plates for what does not fit (one `plate_N.gcode` each). The script's own exit
code overflows for big slicer codes (-18 becomes -1); read the `exit N` line it
prints instead.

| Option | Default | Notes |
|---|---|---|
| `--out DIR` | `./cc2_out` | G-code (`plate_N.gcode`), flattened profiles and `slice.log` land here |
| `--name NAME` | none | rename the G-code to `NAME.gcode` in `--out` (`_plateN` added for several plates) |
| `--filament pla\|plaplus\|plapro\|plamatte\|petghf\|asa\|abs` | `plapro` | stock Elegoo PLA / PLA+ / PLA PRO / PLA Matte / PETG HF / ASA / ABS @ECC2 (PETG HF/ASA/ABS are stock presets, untuned) |
| `--layer 0.20\|0.12` | `0.20` | 0.20 Standard or 0.12 Fine base process |
| `--accel stock\|capped\|antiwobble\|balanced` | `stock` | acceleration only, see below. `stock` does NOT turn off the quality overrides |
| `--pure-stock` | off | skip ALL the author's overrides (quality set, accel, 55 C PLA bed) and use the flattened stock Elegoo profiles only, see below |
| `--bed C` | 55 for the PLA family, else stock | bed temp; `--bed 60` for large flat or tall thin PLA parts |
| `--auxfan N` | stock | side-fan %; 0-30 for large flat PLA parts (see `guides/gotchas.md`) |
| `--temp C` / `--flow R` | stock | nozzle temp / flow ratio, e.g. from `filaments/<slug>.md` |
| `--min-layer-time N` | stock (4 s) | filament `slow_down_layer_time` |
| `--proc KEY=VALUE` | none | extra process override, applied last (repeatable) |
| `--fil KEY=VALUE` | none | extra filament override (repeatable) |
| `--slot-filament N=KIND[:TEMP[:FLOW]]` | none | a different filament in slot N |
| `--slots N` | `1` | load the filament into N slots (needed when a 3MF uses slots above 1) |
| `--plate N` | `0` (all) | slice one plate of a multi-plate 3MF |
| `--supports` | off | normal(auto) supports, build plate only, 25 degree threshold |
| `--no-iron` / `--no-brim` / `--no-arrange` | off | skip ironing / brim / auto-arrange |
| `--keep-pauses` | off | keep `M600` lines (default strips them, the CC2 hangs on them) |
| `--send [NAME]` | off | upload the result with `send_cc2.py` after slicing |
| `--dry-run` | off | write the flattened profiles only |
| `--verify` | off | self-test: stock Elegoo PLA @ECC2 must resolve to flow 0.98 / aux fan 0 / min fan 50 |

### What gets baked in

These are applied on **every** run, including `--accel stock`. `--accel` only
picks the acceleration values; it does not switch the rest off. Use
`--pure-stock` for that (below).

Process: `sparse_infill_pattern=cubic`, `top_surface_pattern=monotonic`,
`ironing_type=top` (flow 15%, speed 15), `top_shell_layers=5`,
`top_shell_thickness=0.9`, `curr_bed_type=Textured PEI Plate`,
`brim_type=auto_brim`, and `solid_infill_direction=0` (untested on a print: it
comes from a gcode-only estimate, see `guides/tuning.md`). Filament: bed temp 55 C
(textured and smooth plate, first layer and after) for `pla`/`plaplus`/`plapro`/`plamatte`
unless you pass `--bed`. Flow and aux fan stay at the profile stock. Anything you disagree with: override it with
`--proc KEY=VALUE`, which wins over everything baked in.

### `--pure-stock`

Skips every override above: the quality set, the accel presets and the 55 C bed
default. The result is the flattened stock Elegoo machine, process and filament
profiles. What remains: `curr_bed_type=Textured PEI Plate` and `brim_type` (CLI
fixes: without them the CLI uses Cool Plate 35 C or leaks a designer's `no_brim`),
`M600` stripping, and whatever you pass explicitly (`--temp`, `--bed`, `--proc`,
`--fil`, `--no-iron` ...). It cannot be combined with `--accel capped|antiwobble|balanced`.

### Accel

The default is **stock**: the tool leaves firmware and profile *acceleration* alone
(the quality overrides above are still applied). The
other presets are **the author's values from one bench**, kept as examples of
what a choice looks like, not as recommendations. Your bench and your input
shaper results decide your numbers: see `guides/find-your-numbers.md` and
`examples/`.

- `capped`: default 5000 / outer wall 3000 / first-layer travel 5000, stock speeds.
- `antiwobble`: default 3000 / outer wall 2000 / inner 3000 / top 1500 / outer wall speed 120.
- `balanced`: default 8000 / outer wall 5000 / outer wall speed 150.
- `stock`: acceleration left at the Elegoo profile value.

The checked-in test prints under `calibration/` and `filaments/swatch/` were
sliced with `antiwobble`. Their scripts call `slice_cc2.py` with default
(stock) accel now; pass `--slicer-arg "--accel antiwobble"` (where the script
offers it) to reproduce the checked-in G-code.

## Send to the printer (no USB)

Needs SSH on the printer (stock firmware before 02.00.02.00, see
`guides/firmware-and-ssh.md`) and `pip install paramiko`. Settings come from
environment variables so nothing private lives in the script:

```bash
export CC2_HOST=<printer-ip>
export CC2_PASSWORD=<root password>   # the published default is in the OpenCentauri docs
python tools/send_cc2.py out/plate_1.gcode --name lid.gcode
python tools/send_cc2.py --list
python tools/send_cc2.py --delete lid.gcode
python tools/slice_cc2.py model.3mf --name lid --send lid     # slice + send
```

Files go to `/opt/usr/gcode/local` (the folder USB copies land in), are
MD5-verified, and files with `M600` are refused. Remote names must be plain
basenames matching `[A-Za-z0-9._ -]+.gcode` (no slashes, quotes, leading dot or dash). Start from the touchscreen or
with `--start`.

### Remote start

```bash
python tools/send_cc2.py out/plate_1.gcode --name lid.gcode --start   # send + start
python tools/send_cc2.py --start lid.gcode                            # start a file already on the printer
```

Verified 2026-09-29 **only** on firmware OTA 01.03.02.36 with CANVAS slot 1, in
cloud mode (no LAN Only). Do not expect it to work on other firmware. How it
works is written up in `guides/firmware-and-ssh.md`. Single colour from CANVAS
slot 1 only. It fails closed: it refuses if the printer's log says it is printing
or paused, if `elegoo.log` cannot be read or has no `print_state` line (override:
`--force-start`), or if `/dev/pts/0` is not a character device. It confirms the
start only when a new `cmd_SDCARD_PRINT_FILE` line for your file appears in the
log after sending. It cannot see the bed: clear it first.

## Not included

Things that were repo-private in the original setup and are not here: project
folders, gcode approval bookkeeping, a per-file manifest of what is on the
printer, and a GUI trace helper.

## Using the tools from your own scripts

The tools can be imported and extended instead of copied, so fixes stay in one
place. Nothing below changes the command-line behaviour.

- `slice_cc2.main(argv=None, hooks=None)`: `hooks` is any object with optional
  `add_arguments(ap)` (add options, change defaults), `prepare(a)` (after the
  argument checks, before output folders are made), `finish(a, plates, rc)`
  (after a successful slice; `plates` is `[(gcode, "plate_N")]`, return the
  possibly moved list) and `upload(pairs, force, allow_m600)` (replaces
  `send_cc2.upload` for `--send`). Module values such as `FILAMENT`, `PROCESS`,
  `QUALITY`, `ACCEL`, `resolve_leaf()` and `flatten()` can be used directly.
- `send_cc2.send(..., skip_same=True)` skips a file already on the printer with
  the same MD5 instead of refusing; `send()` returns the MD5 when it uploaded.
- `send_cc2.start(c, name, force_start, slot_map=None, level=True)`:
  `slot_map` `{tool: slot 1-4}` maps every tool the G-code uses to a CANVAS
  slot (only slot 1 has been verified); `level=False` skips bed levelling.
  `send_cc2.pty(c, lines)` types gcode lines into the printer's gcode pty.
