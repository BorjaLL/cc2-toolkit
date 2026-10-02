#!/usr/bin/env python3
"""
Reusable CC2 slicer: flattens the stock ElegooSlicer CC2 profiles, bakes in a
small set of PLA print-quality overrides (see guides/tuning.md), and slices a
model to G-code via the ElegooSlicer CLI.

Why this exists: the CLI does NOT resolve `inherits:` chains from --load-settings
file paths, so profiles must be pre-flattened. This merges the inherit chain,
applies the tuning overrides, and calls the slicer.

Usage:
    python slice_cc2.py <input.3mf|stl> [--out DIR] [--name NAME]
                        [--filament pla|plaplus|plapro|plamatte|petghf|asa|abs]
                        [--layer 0.20|0.12] [--accel capped|antiwobble|night|night2|night3|balanced|stock]
                        [--temp C] [--flow RATIO] [--bed C] [--pure-stock]

Calibrated values live in filaments/<slug>.md frontmatter (this script does not
read them; pass them explicitly). Example, emoji PLA:
    python slice_cc2.py model.stl --filament pla --temp 210 --flow 1.00

Defaults: PLA PRO filament, 0.20mm layer, stock accel. NOTE: --accel stock only
leaves ACCELERATION at the Elegoo profile value. The author's quality overrides
(QUALITY below: cubic infill, monotonic top, 5 top layers, Textured
PEI, solid_infill_direction=0, auto_brim) and the 55 C PLA-family bed are ALWAYS
applied. Pass --pure-stock to skip all of them (process, filament, bed temp) and
slice with the flattened stock Elegoo profiles only. What remains with
--pure-stock: the curr_bed_type=Textured PEI Plate and brim_type CLI fixes, M600
stripping, and anything you pass explicitly (--temp, --bed, --proc, --fil ...).
The author's own accel sets (capped / antiwobble) are documented in guides/tuning.md and examples/.
Keys/enums/value formats were verified against the installed profiles 2026-09-21.

Slicer location: C:/Program Files/ElegooSlicer by default; set ELEGOO_SLICER_DIR
to the install folder if yours is elsewhere.
"""
import json, os, sys, glob, argparse, subprocess, shutil, re

SLICER_DIR = os.environ.get("ELEGOO_SLICER_DIR", r"C:\Program Files\ElegooSlicer")
EXE = os.path.join(SLICER_DIR, "elegoo-slicer.exe")
PROFILES = os.path.join(SLICER_DIR, "resources", "profiles")

# --- base profiles (by file) -------------------------------------------------
MACHINE = os.path.join(PROFILES, r"Elegoo\machine\ECC2\Elegoo Centauri Carbon 2 0.4 nozzle.json")
PROCESS = {
    "0.20": os.path.join(PROFILES, r"Elegoo\process\ECC2\0.20mm Standard @Elegoo CC2 0.4 nozzle.json"),
    "0.12": os.path.join(PROFILES, r"Elegoo\process\ECC2\0.12mm Fine @Elegoo CC2 0.4 nozzle.json"),
}
FILAMENT = {
    "pla":    os.path.join(PROFILES, r"Elegoo\filament\ECC2\Elegoo PLA @ECC2.json"),
    "plaplus": os.path.join(PROFILES, r"Elegoo\filament\ECC2\Elegoo PLA+ @ECC2.json"),
    "plapro": os.path.join(PROFILES, r"Elegoo\filament\ECC2\Elegoo PLA PRO @ECC2.json"),
    "plamatte": os.path.join(PROFILES, r"Elegoo\filament\ECC2\Elegoo PLA Matte @ECC2.json"),
    # stock Elegoo PETG HF (high flow; 240 C nozzle, flow 0.99, fan max 50%). NOT tuned or validated here.
    "petghf": os.path.join(PROFILES, r"Elegoo\filament\ECC2\Elegoo PETG HF @ECC2.json"),
    # stock Elegoo ASA / ABS (270 C nozzle, 90 C textured plate). NOT tuned or validated here.
    "asa":    os.path.join(PROFILES, r"Elegoo\filament\ECC2\Elegoo ASA @ECC2.json"),
    "abs":    os.path.join(PROFILES, r"Elegoo\filament\ECC2\Elegoo ABS @ECC2.json"),
}

# --- tuning overrides (see guides/tuning.md) ---------------------------------
# Process values are bare strings; filament values are single-element arrays.
ACCEL = {
    # the author's wobbly-desk set: near-silent, minimal shake. Example values, not a
    # recommendation: find yours with guides/find-your-numbers.md.
    "antiwobble": {"default_acceleration": "3000", "outer_wall_acceleration": "2000",
                   "inner_wall_acceleration": "3000", "top_surface_acceleration": "1500",
                   "outer_wall_speed": "120"},
    # the author's floor-slab set (2026-09-29): stock speeds, accel under the Y
    # input-shaper estimate on that bench. See examples/ for the measurements.
    "capped":     {"default_acceleration": "5000", "outer_wall_acceleration": "3000",
                   "initial_layer_travel_acceleration": "5000"},
    # overnight / bedroom prints: antiwobble accel plus half-speed travel. The screen's
    # silent mode is only M220 S50 (speed, not accel), so a large part with many short
    # walls and 500 mm/s hops still clattered (battery crate, 2026-09-30).
    "night":      {"default_acceleration": "3000", "outer_wall_acceleration": "2000",
                   "inner_wall_acceleration": "3000", "top_surface_acceleration": "1500",
                   "travel_acceleration": "3000", "initial_layer_travel_acceleration": "3000",
                   "outer_wall_speed": "120", "travel_speed": "250"},
    # quieter still (2026-09-30, Fable planner model + phone logs): printer shake tracks
    # ACCEL (force = moving mass x accel), speed only shortens the pulse, so accel and
    # travel accel go down hardest; hops are ~2 mm and never reach travel speed.
    # SQUARE_CORNER_VELOCITY left alone (lower modelled slightly worse). ~+14% time vs night.
    "night2":     {"default_acceleration": "2000", "outer_wall_acceleration": "1500",
                   "inner_wall_acceleration": "2000", "sparse_infill_acceleration": "2000",
                   "internal_solid_infill_acceleration": "2000", "top_surface_acceleration": "1000",
                   "travel_acceleration": "1500", "initial_layer_travel_acceleration": "1500",
                   "initial_layer_acceleration": "500",
                   "travel_speed": "150", "outer_wall_speed": "100", "inner_wall_speed": "120",
                   "sparse_infill_speed": "120", "internal_solid_infill_speed": "120",
                   "top_surface_speed": "100", "gap_infill_speed": "80",
                   "support_speed": "100", "support_interface_speed": "60"},
    # night2 accels at half speed (2026-10-02): the first night2 overnight print was still
    # too loud in balanced mode and fine in silent (M220 S50, accel unchanged), so audible
    # noise tracks speed. Bakes silent mode into the slice: no screen input, honest time
    # estimate. ~1.4x night2 time.
    "night3":     {"default_acceleration": "2000", "outer_wall_acceleration": "1500",
                   "inner_wall_acceleration": "2000", "sparse_infill_acceleration": "2000",
                   "internal_solid_infill_acceleration": "2000", "top_surface_acceleration": "1000",
                   "travel_acceleration": "1500", "initial_layer_travel_acceleration": "1500",
                   "initial_layer_acceleration": "500",
                   "travel_speed": "75", "outer_wall_speed": "50", "inner_wall_speed": "60",
                   "sparse_infill_speed": "60", "internal_solid_infill_speed": "60",
                   "top_surface_speed": "50", "gap_infill_speed": "40",
                   "support_speed": "50", "support_interface_speed": "30"},
    # solid bench: fast, lean on the CC2's input shaping for ringing.
    "balanced":   {"default_acceleration": "8000", "outer_wall_acceleration": "5000",
                   "outer_wall_speed": "150"},
    # leave firmware/profile stock accel untouched.
    "stock": {},
}
# Surface-quality wins that are safe regardless of accel choice.
QUALITY = {
    "sparse_infill_pattern": "cubic",     # stock rectilinear -> quieter/faster, ~same strength
    "solid_infill_direction": "0",        # solid lines along X (the author's stiff axis); untested on a print (gcode proxy only)
    # ...on EVERY layer: without a template the slicer still turns solid infill 90 deg
    # each layer, so every other layer ran along Y (phone log 2026-09-30: those layers
    # shook ~2.5x more)
    "solid_infill_rotate_template": "0",
    "top_surface_pattern":   "monotonic", # cleanest top finish
    # ironing ON/OFF is the designer's call (3MF ironing_type, else --iron); these
    # only tune it when it is on
    "ironing_flow":          "15%",
    "ironing_speed":         "15",
    "top_shell_layers":      "5",         # avoid pillowing/pinholes on tops
    "top_shell_thickness":   "0.9",
    "curr_bed_type":         "Textured PEI Plate",  # else defaults to Cool Plate 35C
}
# Filament: aux fan left at profile stock (70% on PLA PRO can warp large flat parts,
# see guides/gotchas.md). Flow left at profile default; calibrate per spool instead.
FIL_OVERRIDES = {}

# --- inherit resolver (VENDOR-SCOPED; mirrors build_tower.py) -----------------
# Generic ancestor names (fdm_filament_pla, fdm_filament_common, fdm_machine_common,
# ...) repeat under EVERY vendor. A global setdefault index let a foreign vendor's
# file win the name race (Afinia's fdm_filament_pla/common indexed first), which
# resolved "Elegoo PLA @ECC2" to flow=1 / aux fan=70 / min fan=100 instead of the
# stock Elegoo 0.98 / 0 / 50. Fix: only ever search within the
# selected profile's own vendor tree (Elegoo) and kind (machine|process|filament),
# and fail LOUDLY on an ambiguous (same name > 1 file) or missing parent.
VENDOR = os.path.join(PROFILES, "Elegoo")
_scope_index = {}

def _index_for(kind):
    """Cache {name: [paths]} within Elegoo/<kind>. A name mapping to >1 path is a
    genuine in-scope ambiguity and is surfaced (not silently collapsed) by _find."""
    if kind not in _scope_index:
        idx = {}
        for p in glob.glob(os.path.join(VENDOR, kind, "**", "*.json"), recursive=True):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                continue
            if isinstance(d, dict) and "name" in d:
                idx.setdefault(d["name"], []).append(p)
        _scope_index[kind] = idx
    return _scope_index[kind]

def _find(kind, name):
    matches = _index_for(kind).get(name, [])
    if not matches:
        raise RuntimeError(f"MISSING ancestor preset '{name}' in Elegoo/{kind}")
    if len(matches) > 1:
        raise RuntimeError(
            f"AMBIGUOUS preset '{name}' under Elegoo/{kind}: "
            + ", ".join(os.path.relpath(m, PROFILES) for m in matches))
    return matches[0]

def _resolve(kind, name, seen=None):
    seen = seen or set()
    if name in seen:
        raise RuntimeError(f"inherit cycle at {name}")
    seen.add(name)
    with open(_find(kind, name), "r", encoding="utf-8") as f:
        d = json.load(f)
    base = _resolve(kind, d["inherits"], seen) if d.get("inherits") else {}
    base.update({k: v for k, v in d.items() if k != "inherits"})
    return base

def resolve_leaf(path, kind, overrides=None):
    """Flatten a leaf profile file's inherit chain within its vendor+kind scope."""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    merged = _resolve(kind, d["inherits"]) if d.get("inherits") else {}
    merged.update({k: v for k, v in d.items() if k != "inherits"})
    merged.update(overrides or {})
    for k in ("inherits", "instantiation"):
        merged.pop(k, None)
    return merged

def flatten(path, kind, overrides, out):
    merged = resolve_leaf(path, kind, overrides)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=1)
    return merged

# --- verification: stock Elegoo PLA @ECC2 must resolve to known-good values ---
STOCK_PLA_EXPECT = {
    "filament_flow_ratio":          ["0.98"],  # foreign fdm_filament_pla would give 1
    "additional_cooling_fan_speed": ["0"],     # aux fan; foreign gives 70
    "fan_min_speed":                ["50"],     # min fan; foreign gives 100
}

def verify_stock():
    """Prove the vendor-scoped resolver returns the correct Elegoo stock values,
    and that the machine + process bases resolve without cross-vendor ambiguity."""
    merged = resolve_leaf(FILAMENT["pla"], "filament")
    ok = True
    for k, want in STOCK_PLA_EXPECT.items():
        got = merged.get(k)
        if got != want:
            ok = False
        print(f"  {k:30s} = {str(got):8s} (expect {want}) [{'OK' if got == want else 'MISMATCH'}]")
    resolve_leaf(MACHINE, "machine")          # raises on ambiguous/missing base
    resolve_leaf(PROCESS["0.20"], "process")  # raises on ambiguous/missing base
    if not ok:
        raise SystemExit("VERIFY FAILED: stock Elegoo PLA @ECC2 resolved to wrong "
                         "values (cross-vendor inheritance regression)")
    print("VERIFY OK: stock Elegoo PLA @ECC2 = flow 0.98 / aux 0 / min fan 50; "
          "machine + process bases resolved with no ambiguity.")

# --- 3MF pre-flight: designer settings + standing (tall/thin) parts -----------
# A 119.5 mm tall, 5 mm wall part (2026-09-25)
# stood on its end. Gcode was dimensionally right, but once the short parts on the
# plate finished (Z 15-18) it ran ALONE at ~3.7 s/layer (min layer time 4 s, so
# almost no slowdown) up to Z 119, with long ironing dwells at Z 9.6 / 15 / 37.8.
# The user saw bands at ~0-10, ~20 and ~38 mm, and the bed-end block fits badly
# on the Base (0.0 mm designed clearance there). These checks make such parts and
# the designer settings this tool replaces visible BEFORE printing. See
# guides/gotchas.md items 5-6.
DESIGNER_KEYS = ("layer_height", "sparse_infill_density", "wall_loops", "brim_type",
                 "brim_width", "elefant_foot_compensation", "enable_support",
                 "support_type")
TALL_RATIO = 4.0    # height / smallest footprint side
TALL_MIN_H = 40.0   # mm; short stubby parts are fine

def _mat(s):
    """3MF transform 'm00 m01 m02 m10 ... m22 tx ty tz' -> (3x3 rows, t)."""
    v = [float(x) for x in s.split()]
    return [v[0:3], v[3:6], v[6:9]], v[9:12]

def _apply(p, T):
    (r, t) = T
    return [p[0]*r[0][j] + p[1]*r[1][j] + p[2]*r[2][j] + t[j] for j in range(3)]

def designer_setting(path, key):
    """Value of a process key in a 3MF's Metadata/project_settings.config, else None.
    Bambu writes display names ("no ironing"); the CLI wants no_ironing."""
    if not path or not path.lower().endswith(".3mf"):
        return None
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            v = json.loads(z.read("Metadata/project_settings.config")).get(key)
    except (KeyError, ValueError, OSError, zipfile.BadZipFile):
        return None
    if isinstance(v, list):
        v = v[0] if v else None
    return v.replace(" ", "_") if isinstance(v, str) else None


def preflight_3mf(path, proc):
    """Print designer-vs-used settings and warn about tall/thin standing parts.
    Read-only; never blocks slicing."""
    import zipfile, re
    try:
        z = zipfile.ZipFile(path)
    except Exception:
        return
    names = z.namelist()
    rd = lambda n: z.read(n).decode("utf-8", "replace") if n in names else ""
    # 1. designer process settings the tool's --load-settings replaces
    try:
        proj = json.loads(rd("Metadata/project_settings.config") or "{}")
    except ValueError:
        proj = {}
    diffs = []
    for k in DESIGNER_KEYS:
        if k in proj:
            used = proc.get(k, proj[k])   # keys the tool leaves unset fall back to the 3MF
            if str(used) != str(proj[k]):
                diffs.append(f"{k}: 3MF {proj[k]} -> used {used}")
    if diffs:
        print("preflight: designer settings REPLACED by the CC2 profile "
              "(add --proc KEY=VALUE to keep one):")
        for d in diffs:
            print("   ", d)
    # 2. per-object overrides (these ARE honoured by the CLI) + plate membership
    ms = rd("Metadata/model_settings.config")
    obj_name, obj_over, plate_of = {}, {}, {}
    for m in re.finditer(r'<object id="(\d+)">(.*?)</object>', ms, re.S):
        body = m.group(2).split("<part", 1)[0]
        kv = dict(re.findall(r'<metadata key="([^"]+)" value="([^"]*)"', body))
        obj_name[m.group(1)] = kv.pop("name", m.group(1))
        kv.pop("extruder", None)
        if kv:
            obj_over[m.group(1)] = kv
    for m in re.finditer(r'<plate>(.*?)</plate>', ms, re.S):
        pid = re.search(r'key="plater_id" value="(\d+)"', m.group(1))
        for oid in re.findall(r'key="object_id" value="(\d+)"', m.group(1)):
            plate_of[oid] = pid.group(1) if pid else "?"
    for oid, kv in obj_over.items():
        print(f"preflight: per-object override P{plate_of.get(oid, '?')} "
              f"'{obj_name.get(oid, oid)}': "
              + ", ".join(f"{k}={v}" for k, v in kv.items()))
    # 3. tall/thin standing parts (bbox after the 3MF's own rotation)
    root = rd("3D/3dmodel.model")
    comps = {}
    for m in re.finditer(r'<object id="(\d+)"[^>]*>(.*?)</object>', root, re.S):
        comps[m.group(1)] = re.findall(
            r'<component[^>]*p:path="([^"]+)"[^>]*objectid="(\d+)"(?:[^>]*transform="([^"]+)")?',
            m.group(2))
    verts = {}
    def mesh(p, oid):
        key = (p, oid)
        if key not in verts:
            txt = rd(p.lstrip("/"))
            o = re.search(r'<object id="%s"[^>]*>(.*?)</object>' % oid, txt, re.S)
            verts[key] = [tuple(map(float, v)) for v in re.findall(
                r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', o.group(1) if o else "")]
        return verts[key]
    brim = str(proc.get("brim_type", proj.get("brim_type", "auto_brim")))
    boxes = {}
    for m in re.finditer(r'<item objectid="(\d+)"[^>]*?transform="([^"]+)"', root):
        oid, T = m.group(1), _mat(m.group(2))
        lo, hi = [1e9] * 3, [-1e9] * 3
        for p, sub, ct in comps.get(oid, []):
            C = _mat(ct) if ct else ([[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0])
            for v in mesh(p, sub):
                q = _apply(_apply(v, C), T)
                lo = [min(a, b) for a, b in zip(lo, q)]
                hi = [max(a, b) for a, b in zip(hi, q)]
        if hi[0] < lo[0]:
            continue
        boxes[oid] = tuple(hi[i] - lo[i] for i in range(3))
    for oid, (dx, dy, dz) in boxes.items():
        foot = min(dx, dy)
        if dz >= TALL_MIN_H and foot > 0 and dz / foot >= TALL_RATIO:
            pl = plate_of.get(oid, "?")
            others = [b[2] for o, b in boxes.items() if o != oid and plate_of.get(o) == pl]
            alone = max(others) if others else 0.0
            print(f"WARNING standing part P{pl} '{obj_name.get(oid, oid)}': "
                  f"{dx:.1f} x {dy:.1f} x {dz:.1f} mm (height/footprint {dz / foot:.1f}), "
                  f"brim={brim}, "
                  + (f"prints ALONE above Z {alone:.0f}. " if alone < dz - 5 else
                     f"plate-mates reach Z {alone:.0f}. ")
                  + "Short layers + "
                  "ironing dwells band/squash it: consider --min-layer-time 8, "
                  "--proc ironing_type=topmost (or no_ironing), a second copy or "
                  "its own plate (guides/gotchas.md item 6).")

def _hook(hooks, name):
    return getattr(hooks, name, None) if hooks is not None else None


def main(argv=None, hooks=None):
    """Command-line entry point. argv: argument list (default sys.argv[1:]).

    hooks: optional object for wrapper scripts that reuse this module (for example
    a private repo that files the G-code into its own folders). Any of these
    attributes may be set, all are optional and the default run uses none:
        add_arguments(ap)        add or change argparse options (e.g. ap.set_defaults)
        prepare(a)               called after the argument checks, before --out is
                                 defaulted and output folders are created
        finish(a, plates, rc)    called after slicing when the slicer exits 0 (plates:
                                 [(gcode path, 'plate_N')], after M600 stripping and the
                                 --name rename); returns the (possibly moved) plate list
        upload(pairs, force, allow_m600)
                                 used by --send instead of send_cc2.upload; pairs are
                                 [(local gcode, remote name)]
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("model", nargs="?", help="input model (.3mf/.stl); omit only with --verify")
    ap.add_argument("more", nargs="*", help="extra model files sliced together with the first "
                    "(e.g. all STLs of a set; auto-arranged, overflow goes to extra plates)")
    ap.add_argument("--out", default=None,
                    help="output folder (G-code as plate_N.gcode + _profiles/ + slice.log). "
                         "Default ./cc2_out")
    ap.add_argument("--name", metavar="NAME",
                    help="rename the output G-code to NAME.gcode in --out (+ _plateN when "
                         "several plates); default plate_N.gcode")
    ap.add_argument("--filament", choices=list(FILAMENT), default="plapro")
    ap.add_argument("--layer", choices=list(PROCESS), default="0.20")
    ap.add_argument("--accel", choices=list(ACCEL), default="stock",
                    help="stock (default) only leaves ACCELERATION at the Elegoo profile "
                         "value: the author's quality overrides (cubic infill, monotonic "
                         "top, 5 top layers, solid_infill_direction=0, "
                         "Textured PEI, auto_brim) and the 55 C PLA bed are still applied "
                         "unless --pure-stock. capped / antiwobble / night / night2 / night3 / balanced are the "
                         "author's accel values, see guides/tuning.md")
    ap.add_argument("--pure-stock", action="store_true",
                    help="skip ALL the author's overrides (quality set, accel, 55 C PLA "
                         "bed default) and slice with the flattened stock Elegoo "
                         "profiles only. Still applied: curr_bed_type=Textured PEI Plate "
                         "and brim_type (needed so the CLI does not use Cool Plate / a "
                         "designer's no_brim), M600 stripping, and your explicit options.")
    ap.add_argument("--auxfan", type=int, default=None,
                    help="side/aux fan %% (leave unset = profile stock; PLA PRO ships 70). "
                         "Set 0-30 for large flat PLA parts to avoid warping.")
    ap.add_argument("--min-layer-time", type=int, default=None,
                    help="filament slow_down_layer_time in s (stock 4). A lone tall "
                         "thin part runs ~3.7 s/layer at stock and bands/squashes "
                         "(guides/gotchas.md item 6); 8-10 gives each layer time to cool.")
    ap.add_argument("--temp", type=int, default=None,
                    help="nozzle temp C (leave unset = profile stock). Drop ~10C to cut "
                         "stringing/ooze; pair with a dry spool.")
    ap.add_argument("--flow", type=float, default=None,
                    help="filament flow ratio (leave unset = profile stock 0.98). "
                         "Calibrated values: filaments/<slug>.md.")
    ap.add_argument("--bed", type=int, default=None,
                    help="bed temp C, first layer + throughout. Unset = 55 for the PLA "
                         "family (pla/plaplus/plapro/plamatte; chamber heat, 2026-09-28) or the "
                         "profile stock otherwise. Use --bed 60 for large flat or tall "
                         "thin PLA parts. Sets both textured_plate_temp and "
                         "hot_plate_temp (+ their initial-layer variants).")
    ap.add_argument("--supports", action="store_true",
                    help="enable normal(auto) supports on build plate only, 25deg "
                         "threshold (needed for overhang models). "
                         "Tune further with --proc support_* keys.")
    ap.add_argument("--proc", action="append", default=[], metavar="KEY=VALUE",
                    help="extra process-profile override, applied LAST so it wins over "
                         "the baked quality/accel tuning (repeatable). e.g. "
                         "--proc layer_height=0.16 --proc seam_position=back.")
    ap.add_argument("--fil", action="append", default=[], metavar="KEY=VALUE",
                    help="extra filament-profile override (stored as a one-element array), "
                         "applied after the named options (repeatable). A literal \\n in "
                         "VALUE becomes a newline (for *_gcode keys).")
    ap.add_argument("--no-arrange", action="store_true",
                    help="keep the model's own coordinates (passes --arrange 0; do NOT auto-arrange). "
                         "Required for print-in-place assemblies "
                         "so interlocking parts stay in their designed positions, and for "
                         "several STLs that must keep their spacing (sequential printing).")
    ap.add_argument("--slots", type=int, default=1,
                    help="load the filament into N slots. Needed when a 3MF's objects use "
                         "slots >1 (e.g. NOAMS per-colour plates), else the CLI exits -101.")
    ap.add_argument("--slot-filament", action="append", default=[], metavar="N=KIND[:TEMP[:FLOW]]",
                    help="load a different filament into slot N (repeatable), e.g. "
                         "--slot-filament 4=plaplus:210:0.98 for a 2-colour print with black "
                         "PLA+ in slot 4. Other slots get --filament. Implies --slots >= N.")
    ap.add_argument("--plate", type=int, default=0,
                    help="slice only this plate number of a multi-plate 3MF (0 = all). "
                         "E.g. plate 3 of a 30-plate 3MF.")
    ap.add_argument("--no-brim", action="store_true",
                    help="disable the brim (brim_type=no_brim). Print-in-place models "
                         "require no brim or it welds part bases.")
    ap.add_argument("--keep-pauses", action="store_true",
                    help="keep M600 pause lines. Default strips them: the CC2 hangs at M600 "
                         "with the nozzle parked on the part (melted a print, 2026-09-24).")
    ap.add_argument("--no-iron", action="store_true",
                    help="no ironing, even if the designer's 3MF irons (test coupons)")
    ap.add_argument("--iron", choices=["top", "topmost", "solid"],
                    help="iron although the model does not ask for it. Default: the "
                         "designer's 3MF ironing_type; STL input = no ironing")
    ap.add_argument("--send", nargs="?", const="", metavar="NAME",
                    help="upload the G-code to the printer over SSH (send_cc2.py) after "
                         "slicing. Optional NAME for the file on the printer; default is "
                         "the model name (+ _plateN for multi-plate output).")
    ap.add_argument("--dry-run", action="store_true", help="flatten only, do not slice")
    ap.add_argument("--verify", action="store_true",
                    help="self-test the vendor-scoped resolver against stock Elegoo "
                         "PLA @ECC2 (flow 0.98 / aux 0 / min fan 50) and exit")
    if _hook(hooks, "add_arguments"):
        hooks.add_arguments(ap)
    a = ap.parse_args(argv)

    if a.pure_stock and a.accel != "stock":
        ap.error("--pure-stock cannot be combined with --accel " + a.accel)
    # Check the install BEFORE doing any work or creating output folders.
    need = [MACHINE, PROCESS[a.layer], FILAMENT[a.filament], VENDOR]
    if not (a.dry_run or a.verify):
        need.insert(0, EXE)
    for p in need:
        if not os.path.exists(p):
            sys.exit(f"not found: {p}\nElegooSlicer install not found or incomplete. "
                     f"Set ELEGOO_SLICER_DIR to its install folder (currently {SLICER_DIR}).")

    if a.verify:
        verify_stock()
        return

    if not a.model:
        ap.error("model is required (or pass --verify)")
    for m in [a.model] + a.more:
        if not os.path.isfile(m):
            sys.exit(f"model not found: {m}")
    slot_specs = []
    for spec in a.slot_filament:  # validate before creating anything
        n, sep, rest = spec.partition("=")
        kind = rest.split(":")[0]
        if not sep or kind not in FILAMENT or not n.strip().isdigit():
            sys.exit(f"--slot-filament needs N=KIND[:TEMP[:FLOW]] (KIND one of "
                     f"{', '.join(FILAMENT)}), got: {spec!r}")
        if not 1 <= int(n) <= 4:
            sys.exit(f"--slot-filament {spec!r}: slot must be 1..4 (the CANVAS has 4 slots)")
        slot_specs.append((int(n), rest.split(":")))
    if not 1 <= a.slots <= 4:
        sys.exit(f"--slots {a.slots}: must be 1..4 (the CANVAS has 4 slots)")
    if _hook(hooks, "prepare"):
        hooks.prepare(a)
    if a.out is None:
        a.out = os.path.join(os.getcwd(), "cc2_out")
    work = os.path.join(a.out, "_profiles")
    os.makedirs(work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)

    if a.pure_stock:
        # only the CLI fixes: without curr_bed_type the CLI picks Cool Plate 35C
        proc_over = {"name": "CC2 stock", "curr_bed_type": QUALITY["curr_bed_type"]}
    else:
        proc_over = {"name": f"CC2 PLA Quality ({a.accel})"}
        proc_over.update(QUALITY)
        proc_over.update(ACCEL[a.accel])
    # Brim is set explicitly: the stock CC2 process leaves brim_type unset, so a
    # designer 3MF's "no_brim" used to leak through and tall standing parts got
    # no brim at all (2026-09-25). auto_brim only adds
    # one where the slicer judges the footprint too small for the height.
    proc_over["brim_type"] = "no_brim" if a.no_brim else "auto_brim"
    if a.supports:
        proc_over.update({"enable_support": "1", "support_type": "normal(auto)",
                          "support_threshold_angle": "25",
                          "support_on_build_plate_only": "1"})
    # Ironing follows the designer (3MF project ironing_type); STLs carry none -> off.
    iron = designer_setting(a.model, "ironing_type") or "no_ironing"
    if a.iron:
        iron = a.iron
    if a.no_iron:
        iron = "no_ironing"
    if not a.pure_stock or a.iron or a.no_iron:
        proc_over["ironing_type"] = iron
    for spec in a.proc:                       # applied last: user overrides win
        k, sep, v = spec.partition("=")
        if not sep:
            sys.exit(f"--proc needs KEY=VALUE, got: {spec!r}")
        proc_over[k.strip()] = v.strip()

    # PLA bed default 55 C (stock 60): enough grip on textured PEI for normal
    # parts, less heat in the closed chamber. --bed 60 for large flat / tall thin.
    PLA_BED_DEFAULT, PLA_BED_DEFAULT_FILAMENTS = 55, ("pla", "plaplus", "plapro", "plamatte")
    fil_over = dict(FIL_OVERRIDES)
    if a.auxfan is not None:
        fil_over["additional_cooling_fan_speed"] = [str(a.auxfan)]
    if a.min_layer_time is not None:
        fil_over["slow_down_layer_time"] = [str(a.min_layer_time)]
    if a.temp is not None:
        fil_over["nozzle_temperature"] = [str(a.temp)]
    if a.flow is not None:
        fil_over["filament_flow_ratio"] = [str(a.flow)]
    if a.bed is None and a.filament in PLA_BED_DEFAULT_FILAMENTS and not a.pure_stock:
        a.bed = PLA_BED_DEFAULT
    if a.bed is not None:
        b = [str(a.bed)]
        for k in ("textured_plate_temp", "textured_plate_temp_initial_layer",
                  "hot_plate_temp", "hot_plate_temp_initial_layer"):
            fil_over[k] = b
    for spec in a.fil:                        # applied last: user overrides win
        k, sep, v = spec.partition("=")
        if not sep:
            sys.exit(f"--fil needs KEY=VALUE, got: {spec!r}")
        fil_over[k.strip()] = [v.strip().replace("\\n", "\n")]

    fm = os.path.join(work, "flat_machine.json")
    fp = os.path.join(work, "flat_process.json")
    ff = os.path.join(work, "flat_filament.json")
    m_merged = flatten(MACHINE, "machine", None, fm)
    p_merged = flatten(PROCESS[a.layer], "process", proc_over, fp)
    f_merged = flatten(FILAMENT[a.filament], "filament", fil_over, ff)
    print("flat_machine :", len(m_merged), "keys")
    print("flat_process :", len(p_merged), "keys",
          "(pure stock Elegoo)" if a.pure_stock else
          f"(infill=cubic, ironing={proc_over.get('ironing_type', 'profile')}, accel={a.accel})")
    print("flat_filament:", len(f_merged), "keys",
          f"(temp {f_merged.get('nozzle_temperature')} "
          f"flow {f_merged.get('filament_flow_ratio')} "
          f"bed {f_merged.get('textured_plate_temp')})")
    # Guard the exact bug (cross-vendor inheritance): stock Elegoo PLA @ECC2 with no
    # flow/aux override must never resolve to a foreign vendor's flow=1/aux=70.
    if a.filament == "pla" and a.flow is None and a.auxfan is None:
        assert f_merged.get("filament_flow_ratio") == ["0.98"], \
            f"stock PLA flow wrong: {f_merged.get('filament_flow_ratio')} (cross-vendor bug?)"
        assert f_merged.get("additional_cooling_fan_speed") == ["0"], \
            f"stock PLA aux fan wrong: {f_merged.get('additional_cooling_fan_speed')}"
        assert f_merged.get("fan_min_speed") == ["50"], \
            f"stock PLA min fan wrong: {f_merged.get('fan_min_speed')}"
    slot_files = [ff] * a.slots
    for n, parts in slot_specs:
        so = dict(fil_over)
        if len(parts) > 1 and parts[1]:
            so["nozzle_temperature"] = [parts[1]]
        if len(parts) > 2 and parts[2]:
            so["filament_flow_ratio"] = [parts[2]]
        fs = os.path.join(work, f"flat_filament_slot{n}.json")
        sm = flatten(FILAMENT[parts[0]], "filament", so, fs)
        print(f"slot {n} filament: {parts[0]} (temp {sm.get('nozzle_temperature')} "
              f"flow {sm.get('filament_flow_ratio')})")
        while len(slot_files) < n:
            slot_files.append(ff)
        slot_files[n - 1] = fs
    # The CLI treats slots loaded from profiles with the same name as one used
    # filament when deciding whether to keep a prime tower, even if the 3MF
    # switches between them. Give each slot a distinct preset name without
    # changing any print parameters (including flow and temperature).
    if len(slot_files) > 1:
        named_slots = []
        for n, source in enumerate(slot_files, 1):
            with open(source, encoding="utf-8") as f:
                slot = json.load(f)
            slot["name"] = f"{slot['name']} (slot {n})"
            named = os.path.join(work, f"flat_filament_slot{n}.json")
            with open(named, "w", encoding="utf-8") as f:
                json.dump(slot, f, indent=1)
            named_slots.append(named)
        slot_files = named_slots
    if a.model.lower().endswith(".3mf"):
        preflight_3mf(a.model, p_merged)
    if a.dry_run:
        print("dry-run: profiles written to", work)
        return

    # ElegooSlicer/OrcaSlicer CLI: settings are ';'-joined; --slice 0 = all plates, N = plate N.
    # --allow-newer-file: Bambu Studio 2.x 3MFs are "newer" than this Orca fork
    # and fail with exit -24 (silent) without it (2026-09-25).
    cmd = [EXE, "--allow-newer-file",
           "--load-settings", f"{fm};{fp}",
           "--load-filaments", ";".join(slot_files),
           "--slice", str(a.plate)]
    # --arrange 0 is passed explicitly: with no --arrange at all the CLI still packs
    # plain STLs and generic 3MFs itself, so --no-arrange did not keep STL positions
    # (calibration/card: two STL objects printed sequentially must stay 80 mm apart).
    cmd += ["--arrange", "0" if a.no_arrange else "1"]
    cmd += ["--outputdir", a.out, a.model] + a.more
    log = os.path.join(a.out, "slice.log")
    print("slicing ->", a.out)
    with open(log, "w", encoding="utf-8") as lf:
        rc = subprocess.call(cmd, stdout=lf, stderr=subprocess.STDOUT)
    print("exit", rc, "| log:", log)
    gcodes = glob.glob(os.path.join(a.out, "*.gcode"))
    print("gcode:", gcodes or "(none - check slice.log)")
    for g in gcodes:
        with open(g, encoding="utf-8", newline="") as f:
            lines = f.readlines()
        hits = [i for i, l in enumerate(lines) if l.strip() == "M600"]
        if not hits:
            continue
        if a.keep_pauses:
            print(f"WARNING {os.path.basename(g)}: {len(hits)} M600 kept - CC2 hangs on it")
            continue
        for i in hits:
            lines[i] = ";M600 removed by slice_cc2 (CC2 hangs on it)\n"
        with open(g, "w", encoding="utf-8", newline="") as f:
            f.writelines(lines)
        print(f"{os.path.basename(g)}: stripped {len(hits)} M600 pause(s)")
    plates = [(g, os.path.splitext(os.path.basename(g))[0]) for g in sorted(gcodes)]  # (file, "plate_1")
    if a.name and gcodes and rc == 0:
        plates = move_to_name(a, plates, a.out)
    if rc == 0 and _hook(hooks, "finish"):
        plates = hooks.finish(a, plates, rc)
    if a.send is not None and plates and rc == 0:
        send_to_printer(a, plates, _hook(hooks, "upload"))
    sys.exit(rc)


def move_to_name(a, plates, dest):
    """--name: rename plate_N.gcode to <name>[_plateN].gcode in dest. Never overwrites
    (an existing name gets _2, _3 ...)."""
    base = a.name[:-6] if a.name.lower().endswith(".gcode") else a.name
    base = re.sub(r"[^A-Za-z0-9._+-]+", "_", base).strip("_")
    out = []
    for g, plate in plates:
        name = base if len(plates) == 1 else f"{base}_{plate.replace('_', '')}"
        target, n = os.path.join(dest, name + ".gcode"), 2
        while os.path.exists(target):
            target, n = os.path.join(dest, f"{name}_{n}.gcode"), n + 1
        shutil.move(g, target)
        print("gcode ->", target)
        out.append((target, plate))
    return out


def send_to_printer(a, plates, upload=None):
    """plates: [(G-code path, 'plate_N')] (the plate label survives --name renames).
    upload: callable(pairs, force, allow_m600); default send_cc2.upload."""
    if upload is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import send_cc2
        upload = lambda pairs, force, allow_m600: send_cc2.upload(
            pairs, force=force, allow_m600=allow_m600)
    stem = a.send[:-6] if a.send.lower().endswith(".gcode") else a.send
    stem = stem or os.path.splitext(os.path.basename(a.model))[0]
    gcodes = [g for g, _ in plates]
    pairs = []
    for g, plate in plates:
        name = stem if len(gcodes) == 1 else f"{stem}_{plate.replace('_', '')}"
        pairs.append((g, name + ".gcode"))
    upload(pairs, True, a.keep_pauses)

if __name__ == "__main__":
    main()
