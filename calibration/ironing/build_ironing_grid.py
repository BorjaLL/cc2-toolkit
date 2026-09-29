#!/usr/bin/env python3
"""Generate a per-filament ironing calibration grid for the Centauri Carbon 2.

Sweeps ironing SPEED (rows, +Y) against ironing FLOW (columns, +X) on one plate
of 25 flat swatches. Method: notes/this-setting-makes-3d-prints-perfectly-smooth.md
(NuggetsInclusive) - print one plate, read the smoothest square, use its
speed/flow for that filament.

How it works (the XY analog of build_tower.py's per-Z temperature injection):
  1. Build a slab + 5x5 grid of raised pads as a single STL (pure boxes).
  2. Slice ONCE with tools/slice_cc2.py, which bakes the validated
     CC2 tuning plus ironing_type=top at a KNOWN base flow/speed.
  3. Rewrite the ;TYPE:Ironing moves per grid cell: feedrate F per row (speed),
     extrusion E per column (flow). Base-slab gap ironing is left untouched.

Every pad's top is an isolated top surface, so the slicer irons each as its own
island - each ironing move's XY maps cleanly to one grid cell.

Run:  python calibration/ironing/build_ironing_grid.py [--filament pla|plaplus|plapro]
Re-run per filament (ironing behaviour is filament-specific).
"""
import argparse
import hashlib
import json
import pathlib
import re
import struct
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
REPO = next(p for p in ROOT.parents if (p / "tools" / "slice_cc2.py").is_file())
SLICER = REPO / "tools" / "slice_cc2.py"

# --- calibration axes -------------------------------------------------------
# v2: centred on E2 (25 mm/s, 25%) with shorter jumps, so the finer differences
# around the chosen cell are visible. Edit and re-run to sweep a new range.
SPEEDS = [19, 22, 25, 28, 31]   # rows, +Y direction, mm/s   (centre = 25)
FLOWS = [19, 22, 25, 28, 31]    # columns, +X direction, percent (centre = 25)
# --- geometry, mm -----------------------------------------------------------
# Pads sit on the bed and are tied together by thin low ribs (not a full slab):
# the ribs keep the plate one piece to lift and read, while leaving almost no
# exposed flat top between pads, so the slicer only irons the pad tops (the
# swatches) - not a large wasted base area. Each pad has its speed/flow engraved
# on a low nameplate in front of it (recessed digits, so ironing the raised
# background flat leaves the strokes as legible matte recesses).
N = 5
PAD = 18.0        # pad edge (ironed swatch) - big enough to read the finish
GAP = 12.0        # gap between pads (fits the label nameplate + ribs)
PADH = 1.2        # pad height from the bed (6 layers; top 5 are solid shell)
RIB = 0.4         # connector rib height (2 layers)
RIBW = 3.0        # connector rib width
PX = 0.8          # label pixel size
LBL_BASE = 0.4    # nameplate solid height (below the recessed strokes)
LBL_TOP = 0.9     # nameplate raised background height (strokes recess to LBL_BASE)
PITCH = PAD + GAP
TOPZ = PADH
SPAN = N * PAD + (N - 1) * GAP

# 3x5 pixel font (rows top->bottom). S and F are shaped to not read as digits.
FONT = {
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
    "S": ["011", "100", "010", "001", "110"],
    "F": ["111", "100", "110", "100", "100"],
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _box(x0, y0, z0, x1, y1, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    tris = []
    for a, b, c, d in quads:
        tris += [(v[a], v[b], v[c]), (v[a], v[c], v[d])]
    return tris


def _label_lit(text):
    """Lit (col,row) pixels for one text line; row 0 = top. Returns (set,width)."""
    lit = set()
    x = 0
    for ch in text:
        glyph = FONT[ch]
        for r in range(5):
            for c in range(3):
                if glyph[r][c] == "1":
                    lit.add((x + c, r))
        x += 4  # 3px glyph + 1px gap
    return lit, x - 1


def _nameplate(cx_center, y_front_edge, lines):
    """Recessed label plate centred at x=cx_center, its back edge (nearest the
    pad) at y=y_front_edge, growing toward -Y. Raised background is ironed flat;
    the strokes stay recessed and legible. line 0 prints at the back (upright
    when read from the front of the printer)."""
    gap = 1
    lit = set()
    width = 0
    for li, text in enumerate(lines):
        line_lit, w = _label_lit(text)
        width = max(width, w)
        base_r = li * (5 + gap)
        for (c, r) in line_lit:
            lit.add((c, base_r + r))
    cols = width + 2                          # +1px border each side
    rows = len(lines) * 5 + (len(lines) - 1) * gap + 2
    plate_w = cols * PX
    plate_h = rows * PX
    x0 = cx_center - plate_w / 2
    tris = _box(x0, y_front_edge - plate_h, 0, x0 + plate_w, y_front_edge, LBL_BASE)
    for r in range(rows):
        for c in range(cols):
            if (c - 1, r - 1) in lit:
                continue                      # recessed stroke: no top pixel
            px0 = x0 + c * PX
            py1 = y_front_edge - r * PX       # row 0 at the back (+Y)
            tris += _box(px0, py1 - PX, LBL_BASE, px0 + PX, py1, LBL_TOP)
    return tris


def build_geometry():
    tris = []
    # Orientation ear diagonally out from the row0/col0 corner. Shorter than the
    # pads so its top is off the ironed swatch plane.
    tris += _box(-10, -10, 0, -2, -2, 1.0)
    for i in range(N):                                  # +Y row -> speed
        for j in range(N):                              # +X col -> flow
            x0, y0 = j * PITCH, i * PITCH
            tris += _box(x0, y0, 0, x0 + PAD, y0 + PAD, PADH)   # pad (swatch)
            tris += _nameplate(x0 + PAD / 2, y0 - 1.0,
                               ["S%d" % SPEEDS[i], "F%d" % FLOWS[j]])
            c = RIBW / 2.0
            if j < N - 1:                               # rib to the +X neighbour
                tris += _box(x0 + PAD, y0 + PAD / 2 - c, 0,
                             x0 + PITCH, y0 + PAD / 2 + c, RIB)
            if i < N - 1:                               # rib to the +Y neighbour
                tris += _box(x0 + PAD / 2 - c, y0 + PAD, 0,
                             x0 + PAD / 2 + c, y0 + PITCH, RIB)
    path = ROOT / "ironing_grid.stl"
    with path.open("wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(tris)))
        for t in tris:
            f.write(struct.pack("<3f", 0, 0, 0))
            for vx in t:
                f.write(struct.pack("<3f", *vx))
            f.write(struct.pack("<H", 0))
    return path, {"span_mm": SPAN, "pads": N * N, "top_z_mm": TOPZ,
                  "triangles": len(tris)}


def slice_base(stl, filament, out_dir):
    cmd = [sys.executable, str(SLICER), str(stl),
           "--out", str(out_dir), "--filament", filament]
    subprocess.run(cmd, check=True, cwd=str(REPO))
    gcodes = list(pathlib.Path(out_dir).glob("*.gcode"))
    assert len(gcodes) == 1, f"expected one G-code, got {gcodes}"
    return gcodes[0]


def _coords(line):
    return (re.search(r"\bX(-?[\d.]+)", line), re.search(r"\bY(-?[\d.]+)", line),
            re.search(r"\bZ(-?[\d.]+)", line), re.search(r"\bE(-?[\d.]+)", line))


def rewrite(text):
    """Rescale ironing moves per grid cell. Returns (new_text, stats)."""
    src = text.splitlines()

    # Base ironing flow the slicer actually used, from the header - the E
    # rescale is relative to this, so read it rather than assume.
    m = re.search(r"^; ironing_flow = ([\d.]+)%", text, re.M)
    assert m, "no ironing_flow in G-code header - was ironing enabled?"
    base_flow = float(m.group(1))
    assert re.search(r"^; ironing_type = top", text, re.M), "ironing_type must be 'top'"

    # Pass 1: locate the pad-top plane and the grid origin.
    in_iron = False
    cx = cy = cz = None
    top_pts = []
    for line in src:
        if line.startswith(";TYPE:"):
            in_iron = "Ironing" in line
            continue
        if line.startswith(";WIPE_START"):
            in_iron = False
            continue
        if line.startswith(("G0", "G1")):
            xm, ym, zm, em = _coords(line)
            if xm:
                cx = float(xm.group(1))
            if ym:
                cy = float(ym.group(1))
            if zm:
                cz = float(zm.group(1))
            if in_iron and em and float(em.group(1)) > 0 and (xm or ym):
                top_pts.append((cx, cy, cz))
    top_z = max(p[2] for p in top_pts)
    plane = [p for p in top_pts if abs(p[2] - top_z) < 0.05]
    minx = min(p[0] for p in plane)
    miny = min(p[1] for p in plane)

    def cell(x, y, z):
        # Only pad tops sit on the top_z plane (ribs and ear are lower), so any
        # ironing move at top_z belongs to the nearest pad - no footprint gate,
        # which would otherwise reject edge passes and split a pad's feedrate.
        if z is None or abs(z - top_z) >= 0.05:
            return None
        # Floor, not round: a pad spans [j*PITCH, j*PITCH+PAD] of its slot, so
        # its fractional position is 0..PAD/PITCH (<1) and always floors to j.
        # (round() would push the outer part of each pad into the next column.)
        j = int((x - minx + 1e-6) // PITCH)
        i = int((y - miny + 1e-6) // PITCH)
        if not (0 <= i < N and 0 <= j < N):
            return None
        return (i, j)

    # Pass 2: rewrite. Drop the slicer's own bare ironing feedrate lines and
    # manage F ourselves so a cell's speed can never be reset mid-pad.
    out = []
    in_iron = False
    cx = cy = cz = None
    key = None
    moves = {}
    e_orig = {}
    e_new = {}
    base_moves = 0
    bare_f = re.compile(r"^G1 F[\d.]+\s*$")
    for line in src:
        if line.startswith(";TYPE:"):
            in_iron = "Ironing" in line
            if not in_iron:
                key = None
            out.append(line)
            continue
        if line.startswith(";WIPE_START"):
            in_iron = False
            key = None
            out.append(line)
            continue
        if line.startswith(("G0", "G1")):
            xm, ym, zm, em = _coords(line)
            if xm:
                cx = float(xm.group(1))
            if ym:
                cy = float(ym.group(1))
            if zm:
                cz = float(zm.group(1))
        if in_iron and line.startswith(("G0", "G1")):
            if bare_f.match(line):
                continue  # our inserted F lines replace these
            if em and float(em.group(1)) > 0 and (xm or ym):
                c = cell(cx, cy, cz)
                if c is not None:
                    i, j = c
                    if key != c:
                        out.append("G1 F%d ; IRON r%d c%d speed=%dmm/s flow=%d%%"
                                   % (SPEEDS[i] * 60, i, j, SPEEDS[i], FLOWS[j]))
                        key = c
                    e = float(em.group(1))
                    ne = e * (FLOWS[j] / base_flow)
                    out.append(re.sub(r"\bE-?[\d.]+", "E%.5f" % ne, line))
                    moves[c] = moves.get(c, 0) + 1
                    e_orig[c] = e_orig.get(c, 0.0) + e
                    e_new[c] = e_new.get(c, 0.0) + ne
                    continue
                else:
                    if key != "base":
                        out.append("G1 F%d ; IRON base slab" % (SPEEDS[1] * 60))
                        key = "base"
                    base_moves += 1
        out.append(line)

    stats = {"base_flow_pct": base_flow, "top_z_mm": top_z,
             "origin_mm": [round(minx, 3), round(miny, 3)],
             "grid_span_mm": round(max(p[0] for p in plane) - minx, 1),
             "cells": len(moves), "base_slab_iron_moves": base_moves,
             "moves": moves, "e_orig": e_orig, "e_new": e_new}
    return "\n".join(out) + "\n", stats


def verify(stats):
    assert stats["cells"] == N * N, f"cells={stats['cells']}"
    minx, miny = stats["origin_mm"]
    assert 0 <= minx and 0 <= miny, stats["origin_mm"]
    assert minx + SPAN <= 256 and miny + SPAN <= 256, "off bed"
    table = []
    for i in range(N):
        row = []
        for j in range(N):
            c = (i, j)
            assert c in stats["moves"], f"missing cell {c}"
            got = stats["e_new"][c] / stats["e_orig"][c]
            want = FLOWS[j] / stats["base_flow_pct"]
            assert abs(got - want) < 1e-4, (c, got, want)
            row.append(stats["moves"][c])
        table.append(row)
    return {"speeds_mm_s": SPEEDS, "flows_pct": FLOWS,
            "moves_per_cell": table, "base_slab_iron_moves": stats["base_slab_iron_moves"],
            "origin_mm": stats["origin_mm"], "top_z_mm": stats["top_z_mm"],
            "grid_span_mm": stats["grid_span_mm"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--filament", default="pla", choices=["pla", "plaplus", "plapro"])
    args = ap.parse_args()

    stl, geometry = build_geometry()
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="cc2-ironing-"))
    print("Slicing base grid with slice_cc2.py (ironing on)...", flush=True)
    base_gcode = slice_base(stl, args.filament, scratch)
    text, stats = rewrite(base_gcode.read_text(encoding="utf-8", errors="ignore"))
    report = verify(stats)

    out = ROOT / ("CC2_IroningGrid_%s_speed%d-%d_flow%d-%d.gcode" % (
        args.filament.upper(), SPEEDS[0], SPEEDS[-1], FLOWS[0], FLOWS[-1]))
    out.write_text(text, encoding="utf-8")
    est = [ln for ln in text.splitlines()
           if "estimated printing time" in ln or "total filament used [g]" in ln]
    verification = {"slicer": "ElegooSlicer via tools/slice_cc2.py",
                    "filament": args.filament, "geometry": geometry,
                    "axes": {"rows_speed_mm_s_+Y": SPEEDS, "cols_flow_pct_+X": FLOWS},
                    "base_flow_pct": stats["base_flow_pct"],
                    "gcode": out.name, "gcode_sha256": sha256(out),
                    "validation": report, "statistics": est,
                    "physical_print_tested": False}
    (ROOT / "verification.json").write_text(json.dumps(verification, indent=2) + "\n",
                                            encoding="utf-8")
    print(json.dumps(report, indent=2))
    for ln in est:
        print(ln.strip())
    print("Validated G-code:", out)


if __name__ == "__main__":
    main()
