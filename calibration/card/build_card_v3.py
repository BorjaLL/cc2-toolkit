#!/usr/bin/env python3
"""CC2 calibration card v3 (2026-10-01): flow, fit and retraction as SEPARATE objects,
printed one after the other (print_sequence "by object").

Why: v2 was one merged object
printed by layer, so the 0.0 retraction control strung onto the tester and the
other rows, the flow pads carried a hidden +9% top-surface boost and could not be
read, and the fit tester picked up ooze. v3:
  - object 1, flow: 5 of Orca's own YOLO patches (Orca-LinearFlow.3mf, 30 x 30 x 2 mm,
    labels -0.04 -0.02 0 +0.02 +0.04 embossed), E scaled per patch to base flow + label,
    with Orca's top-surface settings (archimedean chords, top_solid_infill_flow_ratio 1:
    v2's pads had a hidden +9% top boost). New flow = base + smoothest label; for 0.01
    resolution run the full 11-patch YOLO (calibration/flow/build_yolo.py).
  - object 2, fit: the v2 4 mm rail with 6 hex holes (labels 0-40 = mm per side
    x 100), an info plate and the loose 6 mm hex tester. Stock retraction only.
  - object 3, retraction: Orca's own retraction tower (resources/calib/retraction/
    retraction_tower.drc, two grooved pillars 25 mm apart on a 40 x 15 base),
    cut at 1.4 + (end - start) / step mm exactly as Plater::calib_retraction does.
    Retraction length = start + floor(z - 0.4) x step, the rule in Orca's
    GCode.cpp (Calib_Retraction_tower), applied here by rewriting the E of every
    retract / wipe / unretract sequence of that object. One groove = one step.
  - Head path: the objects are > extruder_clearance_radius apart, the short one
    prints first, and verify() walks every move after an object is finished:
    none may pass over it below its top + z-hop, and nothing in the second
    object's layers may pass over the first at all.

Run (repo root):
  uv run calibration/card/build_card_v3.py --filament plamatte --temp 215 --flow 0.98 --tag PLAMATTE
  --no-flow: fit + retraction only; --retraction-only: the tower alone; --out DIR (default: this folder)
Needs build_card_v2.py next to it, tools/slice_cc2.py and ElegooSlicer (ELEGOO_SLICER_DIR,
default C:/Program Files/ElegooSlicer). The three STLs are written next to the G-code: the flow
patches and the retraction tower are derived from ElegooSlicer's bundled models (AGPL-3.0).
"""
# /// script
# dependencies = ["DracoPy", "trimesh", "numpy", "pillow"]
# ///
import argparse
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_card_v2 as v2
from build_card_v2 import (_box, _hex, _prism, _label_flat, label_width, _hex_rail_with_holes, write_stl,
                        _params, _sub_e, _objects, add_thumbnail, sha256, fmt_flow)

ROOT = v2.ROOT
REPO = v2.REPO
REVISION = "V3"
LAYER = 0.2
BED = 256.0
INSTALL = pathlib.Path(os.environ.get("ELEGOO_SLICER_DIR", r"C:/Program Files/ElegooSlicer"))
DRC = INSTALL / "resources/calib/retraction/retraction_tower.drc"

# Orca calib_retraction: the per-object settings it sets that differ from the repo's stock CC2
# process (stock already has wall_loops 2, bottom 3, seam aligned, inner/outer, no scarf, no
# alternate wall, no precise Z, no wrapping detection, no resonance avoidance, firmware retraction
# off). Sparse infill 0 is global here: the fit rail is walls only anyway and the tester just
# becomes hollow. top_shell_layers stays stock (5): it only caps the last band of the pillars.
ORCA_PROC = ["sparse_infill_density=0%",
             # flow patches: Orca's linear YOLO top settings (Plater.cpp adjust_settings_for_flowrate_calib);
             # harmless on the fit rail and the tower (they have almost no top surface)
             "top_surface_pattern=archimedeanchords", "top_solid_infill_flow_ratio=1",
             "top_surface_line_width=0.48", "internal_solid_infill_line_width=0.48",
             "only_one_wall_top=1", "calib_flowrate_topinfill_special_order=1",
             "min_width_top_surface=100%", "infill_direction=45", "solid_infill_direction=135",
             "align_infill_direction_to_model=1",
             # with sparse 0 a 2 mm patch must be solid: 5 bottom + 5 top layers (YOLO: 2 + 35% + 5)
             "bottom_shell_layers=5"]
FLOW_DELTAS = [-0.04, -0.02, 0.0, 0.02, 0.04]      # which YOLO patches go on the card
YOLO = INSTALL / "resources/calib/filament_flow/Orca-LinearFlow.3mf"
PATCH_PITCH = 32.0
RET_START, RET_END, RET_STEP = 0.0, 1.2, 0.1      # mm; stock 0.8 sits inside the range
SAFE_DZ = 0.3                                      # over a finished object the nozzle must be this far above it
CLEARANCE_RADIUS = 65.0
GAP = 75.0                                         # between objects, hull to hull (10 over the rule)
MARGIN = 20.0                                      # bed edge

# fit object, local mm: origin front-left
HOLE_GAPS = v2.HOLE_GAPS
TESTER_AF = v2.TESTER_AF
HOLE_PITCH = v2.HOLE_PITCH
RAIL_Y0, RAIL_D, RAIL_Z = 8.0, 10.0, 4.0
RAIL_X1 = HOLE_PITCH * len(HOLE_GAPS)
INFO_Y0, INFO_D = RAIL_Y0 + RAIL_D, 9.0
TESTER_Y = INFO_Y0 + INFO_D + 15.0                # 15 mm clear of the plate
TESTER_Z = 7.0
PX, SHEET_Z, LABEL_Z, LABEL_INSET, HOLE_PLATE_W = v2.PX, v2.SHEET_Z, v2.LABEL_Z, v2.LABEL_INSET, v2.HOLE_PLATE_W


def fit_object(temp, flow):
    tris, holes_man = [], []
    holes = [(HOLE_PITCH / 2 + i * HOLE_PITCH, RAIL_Y0 + RAIL_D / 2, TESTER_AF + 2 * g)
             for i, g in enumerate(HOLE_GAPS)]
    for g, (cx, cy, af) in zip(HOLE_GAPS, holes):
        text = str(int(round(g * 100)))
        tris += _box(cx - HOLE_PLATE_W / 2, 0, 0, cx + HOLE_PLATE_W / 2, RAIL_Y0, SHEET_Z)
        tris += _label_flat(text, cx - label_width(text) / 2, RAIL_Y0 - LABEL_INSET, SHEET_Z, LABEL_Z)
        holes_man.append({"gap_per_side_mm": g, "across_flats_mm": round(af, 3), "x": cx, "y": cy, "label": text})
    tris += _hex_rail_with_holes(0, RAIL_X1, RAIL_Y0, RAIL_Y0 + RAIL_D, 0, RAIL_Z, holes)
    info = "T%d F%s" % (temp, fmt_flow(flow))
    tris += _box(0, INFO_Y0, 0, RAIL_X1, INFO_Y0 + INFO_D, SHEET_Z)      # info plate behind the rail
    tris += _label_flat(info, RAIL_X1 / 2 - label_width(info) / 2, INFO_Y0 + INFO_D - LABEL_INSET, SHEET_Z, LABEL_Z)
    tx = RAIL_X1 / 2
    tris += _prism(_hex(tx, TESTER_Y, TESTER_AF), 0, TESTER_Z)
    return tris, {"holes": holes_man, "info": info, "tester_xy": [tx, TESTER_Y],
                  "size_mm": [RAIL_X1, round(TESTER_Y + TESTER_AF / 2, 2), TESTER_Z]}


def flow_object():
    """5 YOLO patches in a row, local mm (origin front-left); boxes = (delta, x0, x1, y0, y1)."""
    scene = trimesh.load(str(YOLO))
    by = {}
    for name, mesh in scene.geometry.items():
        m = re.fullmatch(r"flowrate_(m?)([\d.]+)", name)
        assert m, name
        by[round((-1 if m.group(1) else 1) * float(m.group(2)), 2)] = mesh.copy()
    meshes, boxes = [], []
    for j, d in enumerate(FLOW_DELTAS):
        m = by[round(d, 2)]
        m.apply_translation([j * PATCH_PITCH - m.bounds[0][0], -m.bounds[0][1], -m.bounds[0][2]])
        (x0, y0, _), (x1, y1, _) = m.bounds
        meshes.append(m)
        boxes.append((d, float(x0), float(x1), float(y0), float(y1)))
    return trimesh.util.concatenate(meshes), boxes


def tower_object():
    import DracoPy
    m = DracoPy.decode(DRC.read_bytes())
    mesh = trimesh.Trimesh(np.array(m.points).reshape(-1, 3), np.array(m.faces).reshape(-1, 3))
    height = 1.0 + 0.4 + (RET_END - RET_START) / RET_STEP - 1e-6        # Plater::calib_retraction
    mesh = mesh.slice_plane([0, 0, height], [0, 0, -1], cap=True)
    mesh.apply_translation(-np.array([mesh.bounds[0][0], mesh.bounds[0][1], 0]))
    return mesh, round(float(mesh.bounds[1][2]), 3)


def length_at(z):
    # clamped: the cut top (1.4 + n - eps) leaves one layer at z = 1.4 + n, which Orca's own
    # double arithmetic floors into the last band too
    return round(min(RET_END, RET_START + math.floor(max(0.0, round(z - 0.4, 6))) * RET_STEP), 3)


def slice_plate(models, a, out_dir):
    cmd = [sys.executable, str(v2.SLICER)] + [str(m) for m in models] + [
        "--out", str(out_dir), "--filament", a.filament, "--layer", "0.20", "--no-iron", "--no-brim",
        "--no-arrange", "--temp", str(a.temp), "--flow", str(a.flow),
        "--fil", "nozzle_temperature_initial_layer=%d" % a.temp,
        "--proc", "print_sequence=by object", "--proc", "print_order=as_obj_list"]
    for p in ORCA_PROC:
        cmd += ["--proc", p]
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=False, cwd=str(REPO))
    g = list(pathlib.Path(out_dir).glob("*.gcode"))
    assert len(g) == 1, ("expected one G-code", g, out_dir)
    return g[0]


def rewrite(text, boxes, flow):
    """Per-patch E on the flow object (object 1), per-Z retraction length on the
    tower (last object); the fit object is untouched. boxes == [] (--no-flow):
    no flow object, fit + tower only."""
    src = text.splitlines()
    assert re.search(r"^; use_relative_e_distances = 1\s*$", text, re.M), "need relative E"
    assert re.search(r"^; use_firmware_retraction = 0\s*$", text, re.M), "firmware retraction on"
    stock = float(re.search(r"^; retraction_length = ([\d.]+)", text, re.M).group(1))
    start = next(i for i, l in enumerate(src) if l.startswith(";LAYER:1"))
    end = next(i for i, l in enumerate(src) if "CC2_END_GCODE" in l)
    objs = _objects(src, start, end)
    assert len(objs) in ((3,) if boxes else (1, 2)), ("print objects", len(objs))
    tower_marker = objs[-1]["marker"]
    if boxes:
        fo = objs[0]
        # locate the patches from the flow object's own extrusions (the CLI may shift the plate)
        mx0, mx1 = min(b[1] for b in boxes), max(b[2] for b in boxes)
        my0, my1 = min(b[3] for b in boxes), max(b[4] for b in boxes)
        dx = (fo["x"][0] + fo["x"][1]) / 2 - (mx0 + mx1) / 2
        dy = (fo["y"][0] + fo["y"][1]) / 2 - (my0 + my1) / 2
        assert abs(dx) < 5 and abs(dy) < 5, ("flow object is not where the model put it", dx, dy)
        boxes = [(d, x0 + dx, x1 + dx, y0 + dy, y1 + dy) for d, x0, x1, y0, y1 in boxes]
    else:
        fo = {"first_e": 1, "last_e": 0}
        dx = dy = 0.0

    def box_at(px, py):
        if px is None or py is None:
            return None
        for k, (d, x0, x1, y0, y1) in enumerate(boxes):
            if x0 - 0.45 <= px <= x1 + 0.45 and y0 - 0.45 <= py <= y1 + 0.45:
                return k
        return None
    sums = [[0.0, 0.0] for _ in boxes]
    out = list(src[:start])
    z = pending = LAYER
    seq = None
    in_tower = False
    per_band = {}
    x = y = None
    tower_x_mid = (objs[-1]["x"][0] + objs[-1]["x"][1]) / 2
    for i in range(start, end):
        line = src[i]
        if line.startswith(";Z:"):
            pending = float(line[3:])
        elif line.startswith(";LAYER:"):
            if i == tower_marker:
                in_tower = True
            z = round(pending, 3)
        if not line.startswith(("G0", "G1")):
            out.append(line)
            continue
        p = _params(line)
        x0, y0 = x, y
        x, y = p.get("X", x), p.get("Y", y)
        e = p.get("E")
        if fo["first_e"] <= i <= fo["last_e"] and e is not None and e > 0 and ("X" in p or "Y" in p):
            a, b = box_at(x0, y0), box_at(x, y)
            if a is not None and a == b:
                ne = round(e * (flow + boxes[a][0]) / flow, 5)
                sums[a][0] += e
                sums[a][1] += ne
                line = _sub_e(line, ne)
            else:
                assert a is None and b is None, ("extrusion crosses a patch edge", i, line)
            out.append(line)
            continue
        if e is None or not in_tower:
            out.append(line)
            continue
        if e < 0:
            if seq is None:
                seq = {"z": z, "lines": [], "sum": 0.0, "from": x0}
            seq["lines"].append(len(out))
            seq["sum"] += e
            out.append(line)
            continue
        if seq is not None:
            assert "X" not in p and "Y" not in p, ("extrusion resumed without unretract", line)
            assert abs(seq["sum"] + e) < 1e-4, ("unbalanced retraction", seq["sum"], e)
            L = length_at(seq["z"])
            k = L / stock
            total = 0.0
            for li in seq["lines"]:
                ne = round(_params(out[li])["E"] * k, 5)
                total += ne
                out[li] = _sub_e(out[li], ne)
            line = _sub_e(line, round(-total, 5) + 0.0) + " ; CC2_CARD retract %.1f" % L
            b = per_band.setdefault(L, {"sequences": 0, "pillar_to_pillar": 0, "retract_mm": []})
            b["sequences"] += 1
            if seq["from"] is not None and (seq["from"] - tower_x_mid) * (x - tower_x_mid) < 0:
                b["pillar_to_pillar"] += 1
            b["retract_mm"].append(round(-total / 1.0, 4))
            seq = None
        out.append(line)
    out.extend(src[end:])
    for b in per_band.values():
        b["retract_mm"] = sorted(set(b["retract_mm"]))
    ratios = [round(b / a, 5) if a else None for a, b in sums]
    for (d, *_), r in zip(boxes, ratios):
        assert r is not None and abs(r - (flow + d) / flow) < 3e-4, ("patch ratio", d, r)
    return "\n".join(out) + "\n", {"stock_retraction_mm": stock, "objects": objs, "bands": per_band,
                                    "patch_e_ratio": dict(zip(["%+.2f" % b[0] for b in boxes], ratios)),
                                    "patch_shift_xy": [round(dx, 3), round(dy, 3)]}


def _seg_hits_box(p, q, box):
    """Liang-Barsky: does segment p-q touch the axis-aligned box (x0, x1, y0, y1)?"""
    x0, x1, y0, y1 = box
    t0, t1 = 0.0, 1.0
    dx, dy = q[0] - p[0], q[1] - p[1]
    for pp, qq in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if pp == 0:
            if qq < 0:
                return False
        else:
            t = qq / pp
            if pp < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


CELL = 1.0          # footprint grid, mm
STEP = 0.25         # path sampling, mm


def _cells(p, q):
    n = max(1, int(math.hypot(q[0] - p[0], q[1] - p[1]) / STEP))
    for j in range(n + 1):
        t = j / n
        yield (int(math.floor((p[0] + (q[0] - p[0]) * t) / CELL)),
               int(math.floor((p[1] + (q[1] - p[1]) * t) / CELL))), t


def head_path(text, objs):
    """Footprint check: every extrusion of each object is rasterised (1 mm cells,
    plus one cell of margin). After the object is done (first lift above its top
    following its last extrusion; the retract + wipe on its own last layer still
    belong to it), every XY move is sampled every 0.25 mm. A sample over a cell of
    a finished object counts as "over it"; below its top + SAFE_DZ counts as low.
    The departure starts over the spot the nozzle just finished: samples are
    ignored until the path first leaves the footprint; any re-entry counts."""
    src = text.splitlines()
    start = next(i for i, l in enumerate(src) if l.startswith(";LAYER:1"))
    foot = [dict() for _ in objs]
    x = y = None
    z = 0.0
    for i, line in enumerate(src[start:], start):
        if not line.startswith(("G0", "G1")):
            continue
        p = _params(line)
        nx, ny, nz = p.get("X", x), p.get("Y", y), p.get("Z", z)
        if p.get("E", 0) > 0 and ("X" in p or "Y" in p) and x is not None:
            k = next((k for k, o in enumerate(objs) if o["first_e"] <= i <= o["last_e"]), None)
            if k is not None:
                for (cx, cy), _ in _cells((x, y), (nx, ny)):
                    for ddx in (-1, 0, 1):
                        for ddy in (-1, 0, 1):
                            c = (cx + ddx, cy + ddy)
                            foot[k][c] = max(foot[k].get(c, 0.0), nz)
        x, y, z = nx, ny, nz
    report = []
    for k, o in enumerate(objs):
        top = o["z_top"]
        nxt = objs[k + 1]["first_e"] if k + 1 < len(objs) else None
        over_low = over_safe = over_during_next = 0
        min_clear = None
        x = y = None
        z = 0.0
        done = False
        leaving = False
        for i, line in enumerate(src[start:], start):
            if not line.startswith(("G0", "G1")):
                continue
            p = _params(line)
            nx, ny, nz = p.get("X", x), p.get("Y", y), p.get("Z", z)
            if not done and i > o["last_e"] and nz > top + 1e-6:
                done = True
                leaving = True
            if done and x is not None and nx is not None and ("X" in p or "Y" in p):
                zz = min(z, nz)
                hit = False
                low = False
                for c, t in _cells((x, y), (nx, ny)):
                    if leaving:
                        if c in foot[k]:
                            continue          # still over the spot it just finished
                        leaving = False
                    if c in foot[k]:
                        hit = True
                        clear = zz - foot[k][c]
                        min_clear = clear if min_clear is None else min(min_clear, clear)
                        low = low or clear < SAFE_DZ - 1e-6
                if hit:
                    over_low += low
                    over_safe += not low
                    if nxt is not None and i > nxt:
                        over_during_next += 1
            x, y, z = nx, ny, nz
        report.append({"object": k + 1, "top_z": top, "footprint_cells": len(foot[k]),
                       "moves_over_it_after_done_below_safe": over_low,
                       "moves_over_it_after_done_at_safe_height": over_safe,
                       "moves_over_it_while_later_objects_print": over_during_next,
                       "lowest_clearance_over_it_mm": None if min_clear is None else round(min_clear, 3)})
    return report


def verify(text, stats, a):
    assert not re.search(r"^M600\b", text, re.M), "M600 present"
    assert re.search(r"^M6211 A1 L200 T0 ", text, re.M), "CANVAS slot selection missing"
    assert re.search(r"^; print_sequence = by object\s*$", text, re.M), "not by object"
    for kv in ORCA_PROC:
        k, v = kv.split("=", 1)
        assert re.search(r"^; %s = %s\s*$" % (k, re.escape(v)), text, re.M), ("setting not in header", kv)
    assert re.search(r"^; nozzle_temperature = %d\s*$" % a.temp, text, re.M)
    m = re.search(r"^; filament_flow_ratio = ([\d.]+)\s*$", text, re.M)
    assert m and abs(float(m.group(1)) - a.flow) < 1e-9, ("flow ratio not in header", a.flow)
    objs = stats["objects"]
    gaps = {}
    for i in range(len(objs)):
        for j in range(i + 1, len(objs)):
            a_, b_ = objs[i], objs[j]
            gx = max(0.0, max(a_["x"][0], b_["x"][0]) - min(a_["x"][1], b_["x"][1]))
            gy = max(0.0, max(a_["y"][0], b_["y"][0]) - min(a_["y"][1], b_["y"][1]))
            gaps["%d-%d" % (i + 1, j + 1)] = round(math.hypot(gx, gy), 2)
    assert not gaps or min(gaps.values()) >= CLEARANCE_RADIUS, ("objects closer than the head clearance", gaps)
    tops = [o["z_top"] for o in objs]
    assert tops == sorted(tops), ("a taller object prints before a shorter one", tops)
    want = [length_at(z) for z in (0.6, 13.0)]
    bands = stats["bands"]
    levels = sorted(bands)
    assert levels[0] == RET_START and abs(levels[-1] - RET_END) < 1e-6, ("band range", levels)
    assert len(levels) == round((RET_END - RET_START) / RET_STEP) + 1, ("bands", levels)
    for L, b in bands.items():
        assert b["pillar_to_pillar"] >= 3, ("too few pillar-to-pillar travels", L, b)
        assert all(abs(r - L) < 0.002 for r in b["retract_mm"]), ("retraction not applied", L, b["retract_mm"])
    hp = head_path(text, objs)
    for r in hp:
        assert r["moves_over_it_after_done_below_safe"] == 0, ("head passes low over a finished object", r)
        assert r["moves_over_it_while_later_objects_print"] == 0, ("head crosses a finished object", r)
        assert r["moves_over_it_after_done_at_safe_height"] == 0, ("head passes over a finished object", r)
    return {"objects_gap_mm": gaps, "head_path": hp, "patch_e_ratio": stats["patch_e_ratio"], "length_rule": "start + floor(z - 0.4) x step",
            "range_mm": [RET_START, RET_END, RET_STEP], "spot_check": want,
            "bands": {("%.1f" % L): {"sequences": b["sequences"], "pillar_to_pillar": b["pillar_to_pillar"]}
                      for L, b in sorted(bands.items())}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filament", default="pla")
    ap.add_argument("--temp", type=int, default=210)
    ap.add_argument("--flow", type=float, default=0.98)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--no-flow", action="store_true",
                    help="fit + retraction only (flow already calibrated); file name gets RT")
    ap.add_argument("--retraction-only", action="store_true",
                    help="retraction tower alone (tolerance: the print-in-place hinge test,"
                         " calibration/README.md); file name gets R")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT, help="output folder (default: this folder)")
    a = ap.parse_args()
    assert DRC.is_file() and YOLO.is_file(), f"ElegooSlicer calib models not found in {INSTALL}: set ELEGOO_SLICER_DIR"
    out_dir = a.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    a.no_flow = a.no_flow or a.retraction_only

    flow_mesh, flow_boxes = flow_object()
    fit, fit_man = fit_object(a.temp, a.flow)
    tower, tower_h = tower_object()
    fw, fd = fit_man["size_mm"][0], fit_man["size_mm"][1]
    tw, td = float(tower.bounds[1][0]), float(tower.bounds[1][1])
    pw, pd = float(flow_mesh.bounds[1][0]), float(flow_mesh.bounds[1][1])
    # front row: fit (left) and tower (right), GAP apart, centred; back row: flow, GAP behind
    x0 = (BED - (fw + GAP + tw)) / 2
    fit_shift = (x0, MARGIN)
    tower_shift = (x0 + fw + GAP, MARGIN + (fd - td) / 2)
    flow_shift = ((BED - pw) / 2, MARGIN + fd + GAP)
    assert flow_shift[1] + pd <= BED - MARGIN, "flow row does not fit the bed"
    models = [out_dir / "card_v3_flow.stl", out_dir / "card_v3_fit.stl", out_dir / "card_v3_retraction.stl"]   # print order
    flow_mesh.apply_translation([flow_shift[0], flow_shift[1], 0])
    flow_mesh.export(str(models[0]))
    boxes = [(d, x0_ + flow_shift[0], x1_ + flow_shift[0], y0_ + flow_shift[1], y1_ + flow_shift[1])
             for d, x0_, x1_, y0_, y1_ in flow_boxes]
    write_stl(fit, models[1], fit_shift)
    tower.apply_translation([tower_shift[0], tower_shift[1], 0])
    tower.export(str(models[2]))
    if a.no_flow:
        models, boxes = models[1:], []
    if a.retraction_only:
        models = models[-1:]

    scratch = pathlib.Path(tempfile.mkdtemp(prefix="cc2-card3-"))
    raw = slice_plate(models, a, scratch)
    text, stats = rewrite(raw.read_text(encoding="utf-8", errors="ignore"), boxes, a.flow)
    report = verify(text, stats, a)
    tag = a.tag or a.filament.upper()
    out = out_dir / ("CC2_CalibCard%s%s_%s_T%d_F%s.gcode" % (REVISION, "R" if a.retraction_only else "RT" if a.no_flow else "", tag, a.temp, fmt_flow(a.flow)))
    out.write_text(text, encoding="utf-8")
    add_thumbnail(out)
    (scratch / "raw_prerewrite.gcode").write_bytes(raw.read_bytes())
    est = re.search(r"estimated printing time \(normal mode\) = (.+)", text)
    grams = re.search(r"filament used \[g\] = ([\d.]+)", text)
    verification = {
        "revision": REVISION, "filament": a.filament, "temp_c": a.temp, "flow": a.flow,
        "objects_in_print_order": ([] if a.no_flow else [
            {"file": models[0].name, "what": "flow: Orca YOLO patches, new flow = base + label",
             "bed_shift": flow_shift, "patches": [{"label": "%+.2f" % d, "flow": round(a.flow + d, 3)}
                                                  for d, *_ in boxes], "sha256": sha256(models[0])}]) + ([] if a.retraction_only else [
            {"file": models[-2].name, "what": "fit: 4 mm rail, hex holes, info plate, tester", "bed_shift": fit_shift,
             "holes": fit_man["holes"], "info": fit_man["info"], "size_mm": fit_man["size_mm"],
             "sha256": sha256(models[-2])}]) + [
            {"file": models[-1].name, "what": "Orca retraction tower (retraction_tower.drc) cut at %.1f mm" % tower_h,
             "bed_shift": tower_shift, "size_mm": [round(tw, 2), round(td, 2), tower_h], "sha256": sha256(models[-1])}],
        "slicer_extra": ["print_sequence=by object", "print_order=as_obj_list"] + ORCA_PROC,
        "estimated_time": est.group(1).strip() if est else None, "filament_g": float(grams.group(1)) if grams else None,
        "gcode": out.name, "gcode_sha256": sha256(out), "validation": report,
        "physical_print_tested": False}
    (out_dir / ("verification_v3%s.json" % ("_r" if a.retraction_only else "_rt" if a.no_flow else ""))).write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: verification[k] for k in ("estimated_time", "filament_g", "gcode")}, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
