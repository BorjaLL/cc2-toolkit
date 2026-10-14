# /// script
# dependencies = ["DracoPy", "trimesh", "numpy", "pillow"]
# ///
"""Max volumetric speed (MVS) ramp tower for the CC2, headless (see README.md).

Run (repo root):
  uv run calibration/mvs/build_mvs_tower.py [--filament plamatte] [--lo 10] [--hi 40] [--temp 215]

1. Model: OrcaSlicer's own max-flowrate test shape, SpeedTestStructure.drc from the
   ElegooSlicer install (resources/calib/volumetric_speed/), decoded at run time: a
   180 x 100 mm meander with ~1140 mm of wall per layer, long straights (140-150 mm) and
   R ~10-20 mm U-turns. Cut at 60 mm (Orca cuts at (end - start + 1) / step mm; 10-40 at
   Orca's 0.5 mm3/s per mm is 62 mm). Why not a small cylinder: a 126 mm loop gives
   ~0.5 s layers at the top (heat sag reads as a melt failure) and its R20 curve keeps
   the toolhead below the commanded speed (false pass).
2. Slices with tools/slice_cc2.py the way Orca's calib does: spiral vase, 1 wall,
   line 1.75 x nozzle = 0.7 mm, layer 0.8 x nozzle = 0.32 mm, no top, no infill, slow-down
   layer time 0, outer wall accel --wall-accel (default 5000),
   filament_max_volumetric_speed 40 so the slicer does not clip. Orca uses 0 bottom layers
   and a 5 mm inner+outer brim; here 1 bottom layer (a solid first layer holds the meander
   together) and no brim.
3. Post-processes F on every extrusion move above the first layer so the volumetric flow
   ramps linearly with Z: flow(z) = LO + (HI - LO) * z / 60 mm3/s (Orca: same linear
   ramp, start + z x step). Speed per move = flow / cross-section, cross-section = E x
   filament area / XY length of that move, floored at the nominal wall line (so spiral
   start/end tapers and bottom infill never run faster than a full wall line would).
   Travel, retraction and start/end G-code keep their F; the slicer's modal F is restored
   on the first non-extrusion move after a rewritten one. Exception: the start purge
   `G1 E6 F...` is computed from filament_max_volumetric_speed, so it is reset to the value
   the preset's stock MVS gives.
4. Verifies the output independently (flow per layer from E, XY and F; wall accel; nozzle
   temp; layer time; a Klipper lookahead model of how much of the top band reaches the
   commanded speed) and writes CC2_<tag>_MVSTower_<lo>-<hi>_T<temp>.gcode,
   <same name>_ramp-table.md and verification_<tag>.json into --out.

Print at 100% speed (screen mode balanced, M220 S100), not sport, or the ramp is off by
1.3x. Nothing is sent to the printer.
ElegooSlicer install: ELEGOO_SLICER_DIR (default C:/Program Files/ElegooSlicer).
"""
import argparse
import hashlib
import json
import math
import os
import pathlib
import re
import statistics
import subprocess
import sys
import tempfile

import DracoPy
import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parents[1]
TOOLS = REPO / "tools"
INSTALL = pathlib.Path(os.environ.get("ELEGOO_SLICER_DIR", r"C:/Program Files/ElegooSlicer"))
SHAPE = INSTALL / "resources/calib/volumetric_speed/SpeedTestStructure.drc"
FIL_AREA = math.pi * 0.875 ** 2  # 1.75 mm filament
HEIGHT = 60.0
LAYER = 0.32  # Orca: 0.8 x nozzle
WIDTH = 0.7  # Orca: 1.75 x nozzle
NOMINAL_RATIO = WIDTH * LAYER  # rectangle flow = width x height x speed
SCV = 9.0  # printer square_corner_velocity, mm/s
TOP_BAND_MM = 5.0  # band at the top checked for layer time and reaching speed
PURGE_DIV = 2 * 2.5043  # CC2 start G-code: purge F = filament_max_volumetric_speed x 60 / (2 x 2.5043)
MOVE = re.compile(r"^G[01] ")
AXIS = re.compile(r"\b([XYZEF])(-?\d*\.?\d+)")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_thumbnail(path):
    """Printer file-list preview (CLI slices have none) via tools/thumbnail.py, if present."""
    sys.path.insert(0, str(TOOLS))
    try:
        import thumbnail
    except ImportError:
        print("tools/thumbnail.py not found: G-code has no printer preview", flush=True)
        return
    thumbnail.add(str(path))


def stock_mvs(filament):
    """filament_max_volumetric_speed of the stock preset behind a slice_cc2.py --filament key."""
    sys.path.insert(0, str(TOOLS))
    import slice_cc2
    prof = slice_cc2.resolve_leaf(slice_cc2.FILAMENT[filament], "filament")
    return float(prof["filament_max_volumetric_speed"][0])


def target_flow(z, lo, hi):
    return lo + (hi - lo) * min(max(z, 0.0), HEIGHT) / HEIGHT


def build_model(scratch):
    d = DracoPy.decode(SHAPE.read_bytes())
    mesh = trimesh.Trimesh(np.array(d.points).reshape(-1, 3), np.array(d.faces).reshape(-1, 3))
    mesh.apply_translation(-mesh.bounds[0])
    mesh = trimesh.intersections.slice_mesh_plane(mesh, [0, 0, -1], [0, 0, HEIGHT], cap=True)
    assert mesh.is_watertight and abs(mesh.bounds[1][2] - HEIGHT) < 1e-6, mesh.bounds
    path = scratch / "mvs_tower_orca_shape.stl"
    mesh.export(path)
    return path, [round(float(v), 2) for v in mesh.extents]


def slice_model(model, out, temp, filament, wall_accel):
    proc = {"spiral_mode": "1", "layer_height": LAYER, "initial_layer_print_height": LAYER,
            "line_width": WIDTH, "outer_wall_line_width": WIDTH, "initial_layer_line_width": WIDTH,
            "wall_loops": "1", "bottom_shell_layers": "1", "top_shell_layers": "0",
            "sparse_infill_density": "0%", "outer_wall_speed": "200",
            "outer_wall_acceleration": str(wall_accel), "enable_overhang_speed": "0"}
    fil = {"filament_max_volumetric_speed": "40", "slow_down_layer_time": "0",
           "nozzle_temperature_initial_layer": str(temp)}
    cmd = [sys.executable, str(TOOLS / "slice_cc2.py"), str(model), "--out", str(out),
           "--filament", filament, "--temp", str(temp), "--no-iron", "--no-brim"]
    for k, v in proc.items():
        cmd += ["--proc", f"{k}={v}"]
    for k, v in fil.items():
        cmd += ["--fil", f"{k}={v}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    print(result.stdout[-1500:], result.stderr[-1500:])
    assert result.returncode == 0, f"slice_cc2 exit {result.returncode}"
    gcodes = list(out.glob("*.gcode"))
    assert len(gcodes) == 1, gcodes
    args = ["MODEL.stl", "--out", "OUT"] + cmd[5:]  # no machine-specific paths in the report
    return gcodes[0], {"proc": proc, "fil": fil, "args": args}


def body_range(lines):
    start = next(i for i, l in enumerate(lines) if l.startswith(";LAYER_CHANGE"))
    end = next(i for i, l in enumerate(lines) if l.startswith(";===== CC2_END_GCODE"))
    return start, end


def nominal_area(lines, start, end):
    """Median cross-section of outer-wall moves = the full wall line (WIDTH x LAYER)."""
    areas, x, y, typ = [], None, None, None
    for line in lines[start:end]:
        if line.startswith(";TYPE:"):
            typ = line[6:]
        if not MOVE.match(line):
            continue
        p = dict(AXIS.findall(line.split(";")[0]))
        nx, ny = float(p.get("X", x if x is not None else "nan")), float(p.get("Y", y if y is not None else "nan"))
        if typ == "Outer wall" and float(p.get("E", 0)) > 0 and x is not None:
            d = math.hypot(nx - x, ny - y)
            if d > 0.05:
                areas.append(float(p["E"]) * FIL_AREA / d)
        x, y = nx, ny
    return statistics.median(areas)


def naive_time(lines, start, end):
    """Sum of move length / F (no accel) over the body, seconds."""
    pos = {"X": None, "Y": None, "Z": None}
    f, t = None, 0.0
    for line in lines[start:end]:
        if not MOVE.match(line):
            continue
        p = dict(AXIS.findall(line.split(";")[0]))
        if "F" in p:
            f = float(p["F"]) / 60
        new = {a: float(p[a]) if a in p else pos[a] for a in "XYZ"}
        if all(v is not None for v in pos.values()) and all(v is not None for v in new.values()) and f:
            d = math.dist([pos[a] for a in "XYZ"], [new[a] for a in "XYZ"])
            if d == 0 and "E" in p:
                d = abs(float(p["E"]))
            t += d / f
        pos = new
    return t


def ramp(lines, lo, hi, area_nom, purge_f):
    start, end = body_range(lines)
    out = list(lines)
    pos = {"X": None, "Y": None, "Z": None}
    slicer_f = None  # modal F the slicer intended
    emitted_f = None  # modal F the printer will actually have
    first_layer_z = LAYER + 1e-6
    rewritten = 0
    for i in range(start, end):
        line = lines[i]
        if not MOVE.match(line):
            continue
        code, _, comment = line.partition(";")
        p = dict(AXIS.findall(code))
        if "F" in p:
            slicer_f = float(p["F"])
        new = {a: float(p[a]) if a in p else pos[a] for a in "XYZ"}
        e = float(p.get("E", 0))
        xy = None
        if pos["X"] is not None and ("X" in p or "Y" in p):
            xy = math.hypot(new["X"] - pos["X"], new["Y"] - pos["Y"])
        if e > 0 and xy and new["Z"] is not None and new["Z"] > first_layer_z:
            area = max(e * FIL_AREA / xy, area_nom)
            f = target_flow(new["Z"], lo, hi) / area * 60
            code = re.sub(r"\s*\bF-?[\d.]+", "", code).rstrip()
            out[i] = f"{code} F{f:.0f}" + (f" ;{comment}" if comment else "")
            emitted_f = round(f)
            rewritten += 1
        else:
            if "F" in p:
                emitted_f = slicer_f
            elif emitted_f != slicer_f and slicer_f is not None:
                out[i] = f"{code.rstrip()} F{slicer_f:g}" + (f" ;{comment}" if comment else "")
                emitted_f = slicer_f
        pos = new
    # Start purge: F derives from filament_max_volumetric_speed; restore the stock value.
    purge = [i for i in range(start) if re.match(r"^G1 E6 F[\d.]+", lines[i])]
    assert len(purge) == 1, purge
    out[purge[0]] = f"G1 E6 F{purge_f:.3f} ; MVS tower: stock purge rate, not the raised 40"
    out.insert(start, f"; MVS_TOWER ramp {lo}-{hi} mm3/s over Z 0-{HEIGHT:g} mm, "
                      f"first layer stock speed; print at 100% speed (M220 S100)")
    return out, rewritten


def verify(lines, lo, hi, temp, wall_accel):
    """Independent check: actual flow per layer from E, XY distance and F."""
    start, end = body_range(lines)
    pos = {"X": None, "Y": None, "Z": None}
    f, typ, layer = None, None, None
    per_layer = {}
    for line in lines[start:end]:
        if line.startswith(";Z:"):
            layer = float(line[3:])
        if line.startswith(";TYPE:"):
            typ = line[6:]
        if not MOVE.match(line):
            continue
        p = dict(AXIS.findall(line.split(";")[0]))
        if "F" in p:
            f = float(p["F"]) / 60
        new = {a: float(p[a]) if a in p else pos[a] for a in "XYZ"}
        e = float(p.get("E", 0))
        if e > 0 and pos["X"] is not None and typ == "Outer wall" and layer and layer > LAYER + 1e-6:
            xy = math.hypot(new["X"] - pos["X"], new["Y"] - pos["Y"])
            if xy > 0:
                L = per_layer.setdefault(layer, {"vol": 0.0, "time": 0.0, "flows": [], "z": []})
                L["vol"] += e * FIL_AREA
                L["time"] += xy / f
                L["flows"].append(e * FIL_AREA / xy * f)
                L["z"].append(new["Z"])
        pos = new
    rows, worst = [], 0.0
    nominal = sorted(per_layer)[:-1]
    for z in nominal:
        L = per_layer[z]
        flow = L["vol"] / L["time"]
        zmid = statistics.median(L["z"])
        want = target_flow(zmid, lo, hi)
        dev = flow / want - 1
        rows.append({"layer_z": z, "z_mid": round(zmid, 3), "flow": round(flow, 3),
                     "target": round(want, 3), "dev_pct": round(dev * 100, 2)})
    # Spiral start (first wall-only layer) and the final flat layer taper E: they are slower
    # by design (floored cross-section). Exclude tapered layers from the 5% rule, report them.
    taper = [r for r in rows if abs(r["dev_pct"]) >= 5]
    checked = [r for r in rows if abs(r["dev_pct"]) < 5]
    worst = max(abs(r["dev_pct"]) for r in checked)
    assert len(taper) <= 2, taper
    table_check = []
    for h in range(5, int(HEIGHT) + 1, 5):
        r = min(checked, key=lambda r: abs(r["z_mid"] - h))
        table_check.append({"height_mm": h, "table": target_flow(h, lo, hi), "measured_layer_z": r["layer_z"],
                            "measured_flow": r["flow"], "dev_vs_table_pct": round((r["flow"] / target_flow(h, lo, hi) - 1) * 100, 2)})
        assert abs(table_check[-1]["dev_vs_table_pct"]) <= 5, table_check[-1]
    text = "\n".join(lines)
    accels = [float(v) for v in re.findall(r"^SET_VELOCITY_LIMIT ACCEL=([\d.]+)", text, re.M)]
    accels += [float(v) for v in re.findall(r"^M204 S([\d.]+)", text, re.M)]
    assert accels, "no accel commands in the G-code"
    temps = [int(float(v)) for v in re.findall(r"^M10[49] S([\d.]+)", text, re.M)]
    hot = [t for t in temps if t > 0 and t != 140]  # 140 = preheat before homing
    assert hot and set(hot) == {temp}, temps
    all_flows = [fl for z in [r["layer_z"] for r in checked] for fl in per_layer[z]["flows"]]
    speeds = [fl / (WIDTH * LAYER) for fl in (min(all_flows), max(all_flows))]
    return {"layers_checked": len(checked), "taper_layers_excluded": taper,
            "max_layer_dev_pct": round(worst, 2),
            "measured_flow_min": round(min(r["flow"] for r in checked), 3),
            "measured_flow_max": round(max(r["flow"] for r in checked), 3),
            "move_flow_min": round(min(all_flows), 3), "move_flow_max": round(max(all_flows), 3),
            "table_check": table_check, "max_accel": max(accels),
            "nozzle_temps": sorted(set(temps)), "per_layer": rows,
            "nominal_speed_range_mm_s_at_width_x_layer": [round(s, 1) for s in speeds]}


def motion_check(lines, lo, hi):
    """Klipper lookahead model (toolhead.py: junction deviation from square_corner_velocity,
    centripetal limit, minimum_cruise_ratio 0.5 smoothing) on the ramped body, using the
    accel the G-code sets. Reports, for the top band, how much wall path runs at the
    commanded speed and the flow actually delivered vs the flow commanded."""
    start, end = body_range(lines)
    seqs, cur = [], []
    pos, f, accel, typ = [None] * 3, None, None, None
    for line in lines[start:end]:
        if line.startswith(";TYPE:"):
            typ = line[6:]
        m = re.match(r"^(?:SET_VELOCITY_LIMIT ACCEL=|M204 S)([\d.]+)", line)
        if m:
            accel = float(m[1])
            continue
        if not MOVE.match(line):
            continue
        p = dict(AXIS.findall(line.split(";")[0]))
        if "F" in p:
            f = float(p["F"]) / 60
        new = [float(p[a]) if a in p else pos[i] for i, a in enumerate("XYZ")]
        if None in pos:
            pos = new
            continue
        d = math.dist(pos, new)
        e = float(p.get("E", 0))
        if d < 1e-9:
            if e and cur:  # extrude-only move: toolhead stops
                seqs.append(cur)
                cur = []
            pos = new
            continue
        xy = math.hypot(new[0] - pos[0], new[1] - pos[1])
        cur.append({"d": d, "u": [(n - o) / d for n, o in zip(new, pos)], "v2": f * f, "a": accel,
                    "wall": e > 0 and typ == "Outer wall" and xy > 0, "z": new[2],
                    "area": e * FIL_AREA / xy if xy else 0.0})
        pos = new
    if cur:
        seqs.append(cur)

    def jd(a):
        return SCV ** 2 * (math.sqrt(2) - 1) / a

    band = {"len": 0.0, "full": 0.0, "vol": 0.0, "t": 0.0, "t_cmd": 0.0}
    layer_t = {}
    for seq in seqs:
        for i, mv in enumerate(seq):
            mv["dv2"] = 2 * mv["d"] * mv["a"]
            mv["sdv2"] = mv["dv2"] * 0.5  # minimum_cruise_ratio 0.5
            if i == 0:
                mv["ms"], mv["mss"] = 0.0, 0.0
                continue
            pm = seq[i - 1]
            lim = min(mv["v2"], pm["v2"], pm["ms"] + pm["dv2"])
            cos = -sum(a * b for a, b in zip(pm["u"], mv["u"]))
            sin2 = math.sqrt(max(0.5 * (1 - cos), 0))
            cos2 = math.sqrt(max(0.5 * (1 + cos), 0))
            if 1 - sin2 > 1e-12 and cos2 > 0:
                r_jd = sin2 / (1 - sin2)
                qt = 0.25 * sin2 / cos2
                lim = min(lim, r_jd * jd(mv["a"]) * mv["a"], r_jd * jd(pm["a"]) * pm["a"],
                          mv["dv2"] * qt, pm["dv2"] * qt)
            mv["ms"] = lim
            mv["mss"] = min(lim, pm["mss"] + pm["sdv2"])
        nxt, nxts = 0.0, 0.0
        for mv in reversed(seq):
            sv = min(mv["ms"], nxt + mv["dv2"])
            ss = min(mv["mss"], nxts + mv["sdv2"])
            peak = min(mv["v2"], (ss + nxts + mv["sdv2"]) * 0.5, sv + mv["dv2"], nxt + mv["dv2"])
            peak = max(peak, sv, nxt)
            a, d = mv["a"], mv["d"]
            vs, ve, vc = math.sqrt(sv), math.sqrt(nxt), math.sqrt(peak)
            acc_d, dec_d = (peak - sv) / (2 * a), (peak - nxt) / (2 * a)
            cruise = max(d - acc_d - dec_d, 0.0)
            t = (vc - vs) / a + (vc - ve) / a + cruise / vc if vc > 0 else 0.0
            if mv["wall"]:
                lz = round(mv["z"] / LAYER)
                layer_t[lz] = layer_t.get(lz, 0.0) + t
                if mv["z"] > HEIGHT - TOP_BAND_MM:
                    band["len"] += d
                    band["full"] += cruise if peak >= 0.98 * mv["v2"] else 0.0
                    band["vol"] += mv["area"] * d
                    band["t"] += t
                    band["t_cmd"] += d / math.sqrt(mv["v2"])
            nxt, nxts = sv, ss
    top_layers = [t for lz, t in layer_t.items() if lz * LAYER > HEIGHT - TOP_BAND_MM + LAYER]
    cmd_flow = band["vol"] / band["t_cmd"]
    real_flow = band["vol"] / band["t"]
    return {"model": f"Klipper lookahead, square_corner_velocity {SCV:g}, minimum_cruise_ratio 0.5, accel as set in the G-code",
            "top_band_mm": [HEIGHT - TOP_BAND_MM, HEIGHT],
            "wall_accels_seen": sorted({mv["a"] for sq in seqs for mv in sq if mv["wall"]}),
            "top_band_pct_path_at_full_speed": round(100 * band["full"] / band["len"], 1),
            "top_band_flow_commanded": round(cmd_flow, 2), "top_band_flow_delivered": round(real_flow, 2),
            "top_band_flow_shortfall_pct": round(100 * (1 - real_flow / cmd_flow), 2),
            "top_band_min_layer_time_s": round(min(top_layers[:-1] or top_layers), 2),
            "min_wall_layer_time_s_above_floor": round(min(t for lz, t in layer_t.items() if lz > 3 and lz * LAYER < HEIGHT - LAYER), 2)}


def write_table(path, lo, hi, area_nom, out_name, flow):
    rows = [f"| Height mm | Flow mm3/s | Speed mm/s ({WIDTH:g} x {LAYER:g} = {NOMINAL_RATIO:.3f}) | Speed mm/s commanded (real line {area_nom:.4f} mm2) | Wall OK? |",
            "|---|---|---|---|---|"]
    for h in range(0, int(HEIGHT) + 1, 5):
        fl = target_flow(h, lo, hi)
        rows.append(f"| {h} | {fl:.1f} | {fl / NOMINAL_RATIO:.0f} | {fl / area_nom:.0f} | |")
    path.write_text(
        f"# MVS ramp table: {out_name}\n\n"
        f"Shape: OrcaSlicer's SpeedTestStructure (180 x 100 mm meander, ~1140 mm of wall per layer), cut at {HEIGHT:g} mm. "
        f"Flow ramps linearly {lo:g} -> {hi:g} mm3/s over 0-{HEIGHT:g} mm (first {LAYER:g} mm layer at stock speed). "
        f"Print at 100% speed (M220 S100). Caliper the wall every 5 mm on a long straight; the fail point is >10% thinning, "
        f"gaps or extruder clicks; use 85% of the last passing flow (calibration/mvs/README.md).\n\n"
        f"The slicer's real {WIDTH:g} x {LAYER:g} line is a rounded rectangle ({area_nom:.4f} mm2 incl. flow {flow:g}), not {NOMINAL_RATIO:.3f} mm2, "
        f"so the commanded speed is set from the real E per mm: the flow column is what the nozzle actually melts.\n\n"
        + "\n".join(rows) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filament", default="plamatte",
                    help="tools/slice_cc2.py --filament key (pla, plaplus, plapro, plamatte, ...; default plamatte)")
    ap.add_argument("--tag", default=None, help="file name tag (default: the --filament key)")
    ap.add_argument("--lo", type=float, default=10, help="flow at the bottom, mm3/s (default 10)")
    ap.add_argument("--hi", type=float, default=40, help="flow at the top (60 mm), mm3/s (default 40)")
    ap.add_argument("--temp", type=int, default=215, help="nozzle temperature C (default 215)")
    ap.add_argument("--wall-accel", type=int, default=5000, help="outer wall acceleration mm/s2 (default 5000)")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT, help="output folder (default: this folder)")
    a = ap.parse_args()
    assert SHAPE.is_file(), f"{SHAPE} not found: set ELEGOO_SLICER_DIR to your ElegooSlicer install"
    tag = a.tag or a.filament
    out_dir = a.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"CC2_{tag}_MVSTower_{a.lo:g}-{a.hi:g}_T{a.temp}.gcode"
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="cc2-mvs-tower-"))
    model, extents = build_model(scratch)
    gcode, settings = slice_model(model, scratch / "out", a.temp, a.filament, a.wall_accel)
    lines = gcode.read_text(encoding="utf-8").split("\n")
    flow = float(re.search(r"^; filament_flow_ratio = ([\d.]+)", "\n".join(lines), re.M)[1])
    start, end = body_range(lines)
    area_nom = nominal_area(lines, start, end)
    slicer_est = re.search(r"^; estimated printing time \(normal mode\) = (.+)$", "\n".join(lines), re.M)[1]
    t_before = naive_time(lines, start, end)
    purge_f = stock_mvs(a.filament) * 60 / PURGE_DIV
    out_lines, rewritten = ramp(lines, a.lo, a.hi, area_nom, purge_f)
    result = verify(out_lines, a.lo, a.hi, a.temp, a.wall_accel)
    motion = motion_check(out_lines, a.lo, a.hi)
    # first-layer walls run at the initial layer accel; every other wall at --wall-accel
    assert max(motion["wall_accels_seen"]) == a.wall_accel, ("wall accel not applied", motion["wall_accels_seen"])
    s2, e2 = body_range(out_lines)
    t_after = naive_time(out_lines, s2, e2)
    output = out_dir / name
    output.write_text("\n".join(out_lines), encoding="utf-8")
    add_thumbnail(output)
    write_table(out_dir / (output.stem + "_ramp-table.md"), a.lo, a.hi, area_nom, name, flow)
    est_s = None
    m = re.match(r"(?:(\d+)h )?(?:(\d+)m )?(\d+)s", slicer_est)
    if m:
        est_s = int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3])
    report = {
        "gcode": name, "gcode_sha256": sha256(output), "model": f"OrcaSlicer SpeedTestStructure (resources/calib/volumetric_speed/{SHAPE.name}, sha256 {sha256(SHAPE)[:16]}), cut to {extents[0]:g} x {extents[1]:g} x {extents[2]:g} mm",
        "filament": a.filament, "slice_settings": settings, "ramp": {"lo": a.lo, "hi": a.hi, "z_range_mm": [0, HEIGHT]},
        "nominal_cross_section_mm2": round(area_nom, 5), "extrusion_moves_rewritten": rewritten,
        "slicer_estimate_before_ramp": slicer_est,
        "print_time_estimate_s": None if est_s is None else round(est_s - t_before + t_after),
        "print_time_note": "slicer total minus body feed time (length/F, no accel) of the slice, plus the same for the ramped body; header M73/estimate lines are stale",
        "validation": result, "motion": motion, "physical_print_tested": False, "sent_to_printer": False,
    }
    (out_dir / f"verification_{tag}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = {k: result[k] for k in ("layers_checked", "max_layer_dev_pct", "measured_flow_min",
                                      "measured_flow_max", "max_accel", "nozzle_temps")}
    print(json.dumps({**summary, "taper_excluded": [r["layer_z"] for r in result["taper_layers_excluded"]],
                      "time_s": report["print_time_estimate_s"], "rewritten": rewritten, "motion": motion}, indent=2))
    print("Validated G-code:", output)


if __name__ == "__main__":
    main()
