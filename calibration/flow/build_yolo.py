# /// script
# dependencies = ["trimesh", "numpy", "networkx", "lxml"]
# ///
"""Orca "YOLO (Recommended)" flow-ratio calibration for the CC2, without the GUI.

Same model and settings as ElegooSlicer 1.5.3.5 Calibration > Flow ratio > YOLO
(Plater::calib_flowrate(linear, pass 1, archimedean chords) +
adjust_settings_for_flowrate_calib): resources/calib/filament_flow/Orca-LinearFlow.3mf,
11 patches 30 x 30 x 2 mm labelled -0.05 .. +0.05 around the current flow ratio,
and the GUI's per-object overrides (1 wall, 2 bottom / 5 top layers, 35% rectilinear
sparse infill, 0.48 mm top and solid lines, archimedean-chords top, top/solid speeds
capped by the filament's max volumetric speed, ...).

The one difference: the GUI sets each object's print_flow_ratio = (flow + delta) / flow.
print_flow_ratio is a pure E multiplier, so this script slices the patches together
with the shared overrides and multiplies every extrusion inside a patch's footprint by
that factor, then verifies the per-patch E ratio.

Run (repo root):
  uv run calibration/flow/build_yolo.py --preset "Elegoo PLA Matte @ECC2" --tag PLAMatte --temp 215 --flow 0.98
Writes CC2_<tag>_FlowYOLO_T<temp>_F<flow>.gcode, verification_<tag>.json, the patch STL and the
flattened profiles into --out (default: this folder). The STL and profiles are derived from
ElegooSlicer's bundled files (AGPL-3.0) and are regenerated on every run.
ElegooSlicer install: ELEGOO_SLICER_DIR (default C:/Program Files/ElegooSlicer).
"""
import argparse
import hashlib
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parents[1]
INSTALL = pathlib.Path(os.environ.get("ELEGOO_SLICER_DIR", r"C:/Program Files/ElegooSlicer"))
MODEL = INSTALL / "resources/calib/filament_flow/Orca-LinearFlow.3mf"
BED_CENTRE = (128.0, 128.0)
NOZZLE = 0.4

VENDOR = INSTALL / "resources/profiles/Elegoo"


def resolve_profile(kind, name, chain=None):
    """Same as calibration/temperature/build_tower.py: generic base names repeat across
    vendors, so inheritance is resolved inside the Elegoo vendor folder only."""
    chain = [] if chain is None else chain
    assert name not in chain, f"Profile inheritance cycle: {name}"
    found = []
    for path in (VENDOR / kind).rglob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("name") == name:
            found.append((path, data))
    assert len(found) == 1, (kind, name, [str(p) for p, _ in found])
    path, data = found[0]
    if data.get("inherits"):
        merged, sources = resolve_profile(kind, data["inherits"], chain + [name])
    else:
        merged, sources = {}, []
    merged.update(data)
    for key in ("inherits", "instantiation"):
        merged.pop(key, None)
    sources.append({"path": rel(path), "sha256": sha256(path)})
    return merged, sources


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def rel(path):
    """Install-relative path for the report (no machine-specific prefix)."""
    try:
        return pathlib.Path(path).relative_to(INSTALL).as_posix()
    except ValueError:
        return pathlib.Path(path).name


def add_thumbnail(path):
    """Printer file-list preview (CLI slices have none) via tools/thumbnail.py, if present."""
    sys.path.insert(0, str(REPO / "tools"))
    try:
        import thumbnail
    except ImportError:
        print("tools/thumbnail.py not found: G-code has no printer preview", flush=True)
        return
    thumbnail.add(str(path))


def patches():
    """[(delta, mesh)] from the bundled 3mf, object name flowrate_<x> / flowrate_m<x>."""
    scene = trimesh.load(str(MODEL))
    out = []
    for name, mesh in scene.geometry.items():
        m = re.fullmatch(r"flowrate_(m?)([\d.]+)", name)
        assert m, name
        out.append(((-1 if m.group(1) else 1) * float(m.group(2)), mesh.copy()))
    out.sort(key=lambda p: p[0])
    assert [round(d, 2) for d, _ in out] == [round(-0.05 + 0.01 * i, 2) for i in range(11)]
    return out


def build_profiles(preset, temp, flow, out):
    machine, ms = resolve_profile("machine", "Elegoo Centauri Carbon 2 0.4 nozzle")
    process, ps = resolve_profile("process", "0.20mm Standard @Elegoo CC2 0.4 nozzle")
    filament, fs = resolve_profile("filament", preset)
    machine["resonance_avoidance"] = "0"
    # Plater.cpp adjust_settings_for_flowrate_calib, linear pass 1
    layer = NOZZLE / 2
    w = NOZZLE * 1.2
    mm3_per_mm = (w - layer * (1 - math.pi / 4)) * layer          # Flow::mm3_per_mm, rounded rectangle
    max_vol = float(filament["filament_max_volumetric_speed"][0])
    max_infill_speed = max_vol / (mm3_per_mm * (flow + 0.05) / flow)
    solid_speed = math.floor(min(float(process["internal_solid_infill_speed"]), max_infill_speed))
    top_speed = math.floor(min(float(process["top_surface_speed"]), max_infill_speed))
    process.update({
        "name": "CC2 Orca YOLO flow calibration 0.20mm",
        "curr_bed_type": "Textured PEI Plate",
        "wall_loops": "1", "only_one_wall_top": "1", "thick_internal_bridges": "0",
        "enable_extra_bridge_layer": "disabled", "internal_bridge_density": "100%",
        "sparse_infill_density": "35%", "min_width_top_surface": "100%",
        "bottom_shell_layers": "2", "top_shell_layers": "5",
        "top_shell_thickness": "0", "bottom_shell_thickness": "0",
        "detect_thin_wall": "1", "filter_out_gap_fill": "0",
        "sparse_infill_pattern": "rectilinear",
        "top_surface_line_width": "%g" % w, "internal_solid_infill_line_width": "%g" % w,
        "top_surface_pattern": "archimedeanchords", "top_solid_infill_flow_ratio": "1",
        "infill_direction": "45", "solid_infill_direction": "135",
        "align_infill_direction_to_model": "1", "ironing_type": "no ironing",
        "internal_solid_infill_speed": str(solid_speed), "top_surface_speed": str(top_speed),
        "seam_slope_type": "none", "gap_fill_target": "nowhere",
        "max_volumetric_extrusion_rate_slope": "0",
        "calib_flowrate_topinfill_special_order": "1",
        "layer_height": "%g" % layer, "initial_layer_print_height": "%g" % layer,
        "alternate_extra_wall": "0", "reduce_crossing_wall": "1", "enable_wrapping_detection": "0",
        "enable_support": "0", "enable_prime_tower": "0",
    })
    filament["nozzle_temperature"] = [str(temp)]
    filament["nozzle_temperature_initial_layer"] = [str(temp)]
    filament["filament_flow_ratio"] = ["%g" % flow]
    prof = out / "profiles"
    prof.mkdir(parents=True, exist_ok=True)
    paths = []
    for kind, data in [("machine", machine), ("process", process), ("filament", filament)]:
        p = prof / f"flat_{kind}.json"
        p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        paths.append(p)
    return paths, {"machine": ms, "process": ps, "filament": fs}, {"top_surface_speed": top_speed,
                                                                    "internal_solid_infill_speed": solid_speed}


P = re.compile(r"\b([XYZEF])(-?\d*\.?\d+)")


def fmt_e(v):
    s = ("%.5f" % v).rstrip("0").rstrip(".")
    return s if s not in ("", "-", "-0") else "0"


def rewrite(text, boxes, flow):
    """Scale E of every extrusion that starts and ends inside one patch box (bed coords)."""
    assert re.search(r"^; use_relative_e_distances = 1\s*$", text, re.M), "need relative E"
    lines = text.split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith(";LAYER:1"))
    end = next(i for i, l in enumerate(lines) if "CC2_END_GCODE" in l)
    # the CLI may shift the plate a little: locate the print from the G-code itself
    x = y = None
    pts = []
    for l in lines[start:end]:
        if l.startswith("G1"):
            p = {k: float(v) for k, v in P.findall(l.split(";")[0])}
            x, y = p.get("X", x), p.get("Y", y)
            if p.get("E", 0) > 0 and ("X" in p or "Y" in p):
                pts.append((x, y))
    px, py = np.array(pts).T
    mx0, mx1 = min(b[1] for b in boxes), max(b[2] for b in boxes)
    my0, my1 = min(b[3] for b in boxes), max(b[4] for b in boxes)
    dx = (px.min() + px.max()) / 2 - (mx0 + mx1) / 2
    dy = (py.min() + py.max()) / 2 - (my0 + my1) / 2
    assert abs(dx) < 5 and abs(dy) < 5, ("print is not where the model put it", dx, dy)
    boxes = [(d, x0 + dx, x1 + dx, y0 + dy, y1 + dy) for d, x0, x1, y0, y1 in boxes]
    x = y = None
    sums = [[0.0, 0.0] for _ in boxes]
    outside = 0

    def box_at(px, py):
        for k, (d, x0, x1, y0, y1) in enumerate(boxes):
            if x0 - 0.45 <= px <= x1 + 0.45 and y0 - 0.45 <= py <= y1 + 0.45:
                return k
        return None
    for i in range(start, end):
        l = lines[i]
        if not l.startswith(("G1", "G2", "G3")):
            continue
        p = {k: float(v) for k, v in P.findall(l.split(";")[0])}
        nx, ny = p.get("X", x), p.get("Y", y)
        e = p.get("E")
        if e is not None and e > 0 and ("X" in p or "Y" in p):
            a, b = box_at(x, y), box_at(nx, ny)
            assert l.startswith("G1"), ("arc extrusion not handled", l)
            if a is not None and a == b:
                k = (flow + boxes[a][0]) / flow
                ne = round(e * k, 5)
                lines[i] = re.sub(r"\bE-?\d*\.?\d+", "E" + fmt_e(ne), l)
                sums[a][0] += e
                sums[a][1] += ne
            else:
                assert a is None and b is None, ("extrusion crosses a patch edge", i, l)
                outside += 1
        x, y = nx, ny
    ratios = [round(b / a, 5) if a else None for a, b in sums]
    for (d, *_), r in zip(boxes, ratios):
        want = (flow + d) / flow
        assert r is not None and abs(r - want) < 3e-4, ("patch ratio", d, r, want)
    return "\n".join(lines), {"patch_e_ratio": ratios, "extrusions_outside_patches": outside}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--temp", type=int, required=True)
    ap.add_argument("--flow", type=float, required=True, help="current flow ratio; patches are flow + -0.05..+0.05")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT, help="output folder (default: this folder)")
    a = ap.parse_args()
    assert (INSTALL / "elegoo-slicer.exe").is_file(), f"ElegooSlicer not found in {INSTALL}: set ELEGOO_SLICER_DIR"
    out_dir = a.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    ps = patches()
    lo = np.min([m.bounds[0] for _, m in ps], axis=0)
    hi = np.max([m.bounds[1] for _, m in ps], axis=0)
    shift = np.array([BED_CENTRE[0] - (lo[0] + hi[0]) / 2, BED_CENTRE[1] - (lo[1] + hi[1]) / 2, 0])
    meshes, boxes = [], []
    for d, m in ps:
        m.apply_translation(shift)
        meshes.append(m)
        (x0, y0, _), (x1, y1, _) = m.bounds
        boxes.append((d, x0, x1, y0, y1))
    stl = out_dir / "Orca-LinearFlow_bed.stl"
    trimesh.util.concatenate(meshes).export(stl)

    (machine, process, filament), sources, speeds = build_profiles(a.preset, a.temp, a.flow, out_dir)
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="cc2-yolo-"))
    cmd = [str(INSTALL / "elegoo-slicer.exe"), "--load-settings", f"{machine};{process}",
           "--load-filaments", str(filament), "--slice", "0", "--arrange", "0",
           "--outputdir", str(scratch), str(stl)]
    with (out_dir / f"slice_{a.tag}.log").open("w", encoding="utf-8") as log:
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=300).returncode
    assert rc == 0, f"slicer exit {rc}, see slice_{a.tag}.log"
    raw = list(scratch.glob("*.gcode"))
    assert len(raw) == 1, raw
    text = raw[0].read_text(encoding="utf-8")
    # the overrides really reached the slicer
    for key, val in [("top_surface_pattern", "archimedeanchords"), ("wall_loops", "1"),
                     ("top_shell_layers", "5"), ("bottom_shell_layers", "2"),
                     ("sparse_infill_density", "35%"), ("layer_height", "0.2"),
                     ("filament_flow_ratio", "%g" % a.flow), ("nozzle_temperature", str(a.temp))]:
        assert re.search(r"^; %s = %s\s*$" % (key, re.escape(val)), text, re.M), (key, val)
    assert not re.search(r"^T[1-9]\d*\b|^M600\b", text, re.M)
    # the patches sit where the boxes say: printed extrusion bounds ~ model bounds
    text, stats = rewrite(text, boxes, a.flow)
    out = out_dir / f"CC2_{a.tag}_FlowYOLO_T{a.temp}_F{int(round(a.flow * 100))}.gcode"
    out.write_text(text, encoding="utf-8")
    add_thumbnail(out)
    est = [l.strip() for l in text.splitlines() if "estimated printing time" in l or "total filament used [g]" in l]
    report = {"model_source": rel(MODEL), "model_sha256": sha256(MODEL), "filament_preset": a.preset,
              "temp_c": a.temp, "base_flow": a.flow,
              "patches": [{"label": "%+.2f" % d, "flow": round(a.flow + d, 3),
                           "bed_box_mm": [round(v, 2) for v in (x0, x1, y0, y1)]} for d, x0, x1, y0, y1 in boxes],
              "speeds_capped": speeds, "profiles": sources, "rewrite": stats,
              "gcode": out.name, "gcode_sha256": sha256(out), "slicer_estimate": est,
              "physical_print_tested": False}
    (out_dir / f"verification_{a.tag}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("rewrite", "speeds_capped", "slicer_estimate")}, indent=2))
    print("Validated G-code:", out)


if __name__ == "__main__":
    main()
