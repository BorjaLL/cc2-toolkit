# CC2 tools

Command-line slicing and sending for the Elegoo Centauri Carbon 2. Tested on
Windows with ElegooSlicer 1.5.3.x and stock CC2 firmware OTA 01.03.02.36.

| File | What |
|---|---|
| `slice_cc2.py` | Flattens the stock ElegooSlicer CC2 profiles, applies a few overrides, slices with the slicer CLI |
| `send_cc2.py` | Uploads G-code to the printer over SFTP, lists / deletes files, starts a print remotely |
| `mf2stl.py` | 3MF (production extension) to binary STL: `python mf2stl.py in.3mf out.stl [build_objectid]` |
| `adaptive_layers.py` | adaptive layer height profile into a copy of a 3MF/STL (used by `slice_cc2.py --adaptive`; also standalone: `python adaptive_layers.py in.3mf out.3mf --quality 0.5`) |

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
plates for what does not fit (one `plate_N.gcode` each).

Each run slices into a fresh `_run-*` folder inside `--out` and only then moves
its own `plate_N.gcode` files into `--out`, so G-code left there by an earlier run
is never renamed, finished or sent (it is listed as a `note:` and in
`stale_in_out`). A failed slice keeps no G-code at all (nothing is post-processed).

Exit codes (stable, small; the slicer's own code is still printed on the
`exit N | log: ...` line):

| Exit | Status | Meaning |
|---|---|---|
| 0 | `ok` | G-code written (and sent with `--send`) |
| 1 | | bad input, slicer not installed, other error (message on stderr) |
| 2 | | bad command-line options |
| 3 | `refused` | a wrapper's policy check refused the G-code (`hooks.finish`) |
| 4 | `slicer_failed` | the slicer exited non-zero (`slicer_exit`, `diagnostics`) |
| 5 | `no_output` | the slicer exited 0 but wrote no G-code |

Every run that reaches the slicer writes `<out>/slice_result.json`: `status`,
`exit_code`, `slicer_exit` (+ `slicer_exit_signed`, e.g. -6), `outputs` (final
path, plate, md5, M600 stripped), `stale_in_out`, `checks` (added by wrappers),
`diagnostics` (error lines from `slice.log`), `toolkit_version` and the effective
`settings`. `--json` also prints it as the last stdout line.

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
| `--slots N` (alias `--slot-count N`) | `1` | a count: load the filament into the first N slicer slots, i.e. tools T0..T(N-1) (needed when a 3MF uses slots above 1). The physical CANVAS slot per tool is picked at start (`slot_map`), not here |
| `--plate N` | `0` (all) | slice one plate of a multi-plate 3MF |
| `--supports` | off | normal(auto) supports, build plate only, 25 degree threshold |
| `--no-iron` / `--no-brim` / `--no-arrange` | off | skip ironing / brim / auto-arrange |
| `--adaptive [QUALITY]` | off (`0.5` when given alone) | adaptive layer height, see below. QUALITY 0 = finest .. 0.5 = base layer .. 1 = fastest |
| `--adaptive-smooth RADIUS` | `0` (off) | with `--adaptive`: smooth the profile like the GUI Smooth button (radius in layers; GUI default 5) |
| `--keep-pauses` | off | keep `M600` lines (default strips them, the CC2 hangs on them) |
| `--send [NAME]` | off | upload the result with `send_cc2.py` after slicing |
| `--json` | off | print the run result (`slice_result.json`) as one JSON line at the end |
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

### `--adaptive` (variable layer height)

The slicer CLI ignores `adaptive_layer_height=1`: it is a legacy key that
ElegooSlicer/OrcaSlicer drops on load (the G-code config dump does not list it,
and the layer count does not change). What the CLI does honour is a 3MF's
per-object variable layer profile, `Metadata/layer_heights_profile.txt`, which
the GUI writes when you press Adaptive in the variable layer height dialog.

`--adaptive` computes that profile with a port of Orca's own algorithm
(`adaptive_layers.py`: layer height from each facet's slope, the Quality/Speed
factor, the 0.04 mm per-layer change limit, optional Gaussian smoothing) and
slices a copy of the model (`<out>/_profiles/adaptive_N_<model>.3mf`; an STL is
wrapped in a minimal 3MF first). The base is the process `layer_height` (`--layer`
or `--proc layer_height=...`), the limits are the machine `min_layer_height` /
`max_layer_height` (0.08 / 0.28 on the CC2 0.4 nozzle). A variable layer profile
the 3MF already has is replaced. Per-object results (height, estimated layers,
min/max) are printed and stored as `adaptive` in `slice_result.json`.

Example (a 41 mm ghost figure, 2026-10-02): fixed 0.20 = 207 layers / 52 min,
fixed 0.12 = 344 layers / 1h41, `--adaptive 0.37 --adaptive-smooth 10` = 236 layers
(0.11-0.26 mm) / 58 min, with the thin layers on the rounded head.

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

One action per run: files (optionally with `--start`), `--start NAME`, `--list`
or `--delete`; other combinations are refused before connecting.

Files go to `/opt/usr/gcode/local` (the folder USB copies land in), are
MD5-verified, and files with `M600` are refused (`M600 ; comment`, `M600 B1` and
lower case count too: `cc2_gcode.py` is the one tokenizer used for stripping and
refusing). Remote names must be plain
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
log after sending. It cannot see the bed: clear it first. Before every start,
also of a file already on the printer, it checks the bytes that will print: the
printer file's md5 is read, a local copy with the same md5 is checked or the file
is downloaded, and `M600` is refused (`--allow-m600` to override).

## Not included

Things that were repo-private in the original setup and are not here: project
folders, gcode approval bookkeeping, a per-file manifest of what is on the
printer, and a GUI trace helper.

## Using the tools from your own scripts

The tools can be imported and extended instead of copied, so fixes stay in one
place. Nothing below changes the command-line behaviour.

- The supported API is each module's `__all__` (plus `cc2_gcode.py`). Wrappers
  should import only those names and check `API_VERSION` (2 since toolkit 1.2.0;
  it goes up only on an incompatible change to that list, a hook or a signature;
  toolkit 1.3.0 added `adaptive_models()` and `adaptive_layers.py`, API still 2).
  `TOOLKIT_VERSION` is reported in `slice_result.json`.
- `slice_cc2.main(argv=None, hooks=None)`: `hooks` is any object with optional
  `add_arguments(ap)` (add options, change defaults), `parsed(a)` (right after
  parsing, before any check: rewrite options), `prepare(a)` (after the
  argument checks, before output folders are made), `finish(a, plates, rc)`
  (after a successful slice; `plates` is `[(gcode, "plate_N")]`, return the
  possibly moved list) and `upload(pairs, force, allow_m600)` (replaces
  `send_cc2.upload` for `--send`). Module values such as `FILAMENT`, `PROCESS`,
  `QUALITY`, `ACCEL`, `resolve_leaf()` and `flatten()` can be used directly.
- Offline regression tests: `python -m unittest discover -s tests` from the
  toolkit folder (no slicer, printer or extra packages needed).
- `send_cc2.send(..., skip_same=True)` skips a file already on the printer with
  the same MD5 instead of refusing; `send()` returns the MD5 when it uploaded.
- `send_cc2.verify_remote(c, name, allow_m600=False, local=None, checks=())`:
  checks the printer file's bytes before a start (M600, then each
  `check(label, path)` callable, which refuses by exiting); returns the md5.
- `send_cc2.start(c, name, force_start, slot_map=None, level=True)`:
  `slot_map` `{tool: slot 1-4}` maps every tool the G-code uses to a CANVAS
  slot (only slot 1 has been verified); `level=False` skips bed levelling.
  `send_cc2.pty(c, lines)` types gcode lines into the printer's gcode pty.
