#!/usr/bin/env python3
"""Generate the one-print CC2 calibration card: flow, retraction, tolerance and a
temperature bracket on a single small plate.

Replaces the 4 separate prints in calibration/README.md (temp tower, flow YOLO,
retraction tower, tolerance hex, ~1.75 h) with one card for a filament whose
stock values are roughly known. The card BRACKETS the values you pass in
(--temp/--flow), it does not sweep the whole material range: that is what keeps
it short. If the card says a value is off by more than its range, run the full
test for that one setting.

How each test varies (and why that is honest):
  flow        7 pads, E-scaled per pad in post-processing (= per-object flow
              ratio, the same thing the slicer's flow ratio does). Pads are
              isolated islands above layer 2, so every move inside a pad
              footprint belongs to that pad.
  retraction  5 pairs of posts. The retract/wipe/unretract E values of every
              retraction that STARTS inside a pair are rescaled to that pair's
              length (explicit E rewrite, relative E mode; each sequence is
              re-balanced so no filament position drifts). Retraction speed,
              z-hop and wipe stay stock.
  tolerance   pure geometry: hex holes 6.0-6.8 mm across flats + a 6.0 tester.
  temperature Z-banded mini tower (5 bands x 5 C around --temp) printed as a
              SEPARATE OBJECT after the card (ElegooSlicer print_sequence
              "by object", 2026-09-27): the card is finished entirely at --temp,
              then the head moves over and prints the tower alone. Because the
              tower prints alone, each band starts with M109 (wait), so the band
              really is at its temperature instead of drifting towards it. The
              tower sits TOWER_GAP_X to the right of the card, more than the
              slicer's head clearance rule (extruder_clearance_radius). Per-island
              temperature switching is deliberately NOT done: a nozzle cannot
              settle in the seconds an island takes. --no-tower drops it (the
              flat card is a single object, print_sequence by layer as before).
  cooling     slow_down_layer_time 8 s (stock 4) so the hollow posts and tower
              pillars get time to cool; everything else is the repo's stock
              CC2 process. Sheet ribs are routed around the hex holes.

Run (from the repo root):
  python calibration/card/build_card.py --filament pla --temp 210 --flow 0.98
  python calibration/card/make_preview.py      # refresh card_preview.png
Then print the .gcode it writes next to this file (CANVAS slot 1 / T0).
"""
import argparse
import hashlib
import json
import math
import pathlib
import re
import struct
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
REPO = next(p for p in ROOT.parents if (p / "tools" / "slice_cc2.py").is_file())
SLICER = REPO / "tools" / "slice_cc2.py"

LAYER = 0.2                      # mm; the card only works on the 0.20 process
FIL_DIAMETER = 1.75
MIN_LAYER_TIME_S = 8             # slow_down_layer_time (stock 4): small hollow posts / pillars get time to cool

# --- what the card varies -----------------------------------------------------
FLOW_DELTAS = [-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03]   # added to --flow
RETRACTIONS = [0.4, 0.6, 0.8, 1.0, 1.2]                       # mm, per pair
TEMP_DELTAS = [10, 5, 0, -5, -10]                             # C, bottom band first
HOLE_GAPS = [0.0, 0.05, 0.10, 0.20, 0.30, 0.40]               # mm per side
TESTER_AF = 6.0                                               # mm across flats

# --- sequential printing (full card only) ---------------------------------------
# The tower is its own object, printed AFTER the card. Slicer rule, read from the
# flattened CC2 machine profile (tools/, 2026-09-27) and confirmed by
# the CLI's own arrange (it placed the two objects exactly 65.2 mm apart): two
# objects may print sequentially when their convex hulls are at least
# extruder_clearance_radius apart, and an object lower than
# extruder_clearance_height_to_rod never meets the X gantry. Both the card (7 mm)
# and the tower (27 mm) are far below the rod height and the lid height (90).
# The two bodies are two STL files sliced together; slice_cc2.py --no-arrange
# passes the CLI's --arrange 0 so they stay where the files put them (without it
# the CLI packs plain STLs itself, at exactly the 65 mm rule, and a pair placed
# too close is refused: "is too close to others", exit 127).
CLEARANCE_RADIUS = 65.0          # extruder_clearance_radius: minimum hull-to-hull gap
CLEARANCE_HEIGHT_TO_ROD = 36.0   # extruder_clearance_height_to_rod
CLEARANCE_HEIGHT_TO_LID = 90.0   # extruder_clearance_height_to_lid
TOWER_GAP_X = 80.0               # card right edge -> tower left edge (15 mm over the rule)
TEMP_WAIT_LIFT = 2.0             # mm above the band's first layer while M109 waits
TEMP_WAIT_PARK_DX = 15.0         # the wait happens this far beyond the tower's right edge (off both objects)
BED = 256.0
BED_CENTRE = (128.0, 128.0)
BED_EXCLUDE = (246.0, 256.0, 0.0, 20.0)   # bed_exclude_area (front-right corner): x0, x1, y0, y1

# --- geometry (mm), card-local coordinates: origin front-left, +X right, +Y back
PX = 1.0            # label pixel (3x5 glyphs -> 3 x 5 mm)
SHEET_Z = 0.4       # label strips and connector ribs: 2 layers (below every rewritten layer)
LABEL_Z = 0.8       # raised label top: 2 layers above the sheet
RIB_W = 4.0
RIB_HOLE_MARGIN = 1.0   # a rib stops this far before a hex hole edge (inside the rail wall, never in the hole)
STRIP_D = 6.0       # label strip depth (Y)
CARD_W = 96.0

# row A: tolerance
RAIL_Y0, RAIL_D, RAIL_Z = 6.0, 10.0, 2.4
HOLE_PITCH = 10.0
RAIL_X0, RAIL_X1 = 0.0, HOLE_PITCH * len(HOLE_GAPS)
HOLE_X0 = HOLE_PITCH / 2
HOLE_PLATE_W = 8.0
INFO_PX = 0.9
# row B: flow pads
PAD, PAD_GAP, PAD_Z = 12.0, 2.0, 1.4
STRIP_B_Y0 = 20.0
PAD_Y0 = STRIP_B_Y0 + STRIP_D + 1.5
PAD_SCALE_Z_MIN = 2 * LAYER + 1e-6      # layers 1-2 of a pad stay at base flow
# row C: retraction post pairs (square tubes: two wall loops, no infill)
POST, POST_WALL, POST_GAP = 4.0, 0.84, 10.0    # 0.84 = two 0.42 outer loops (outside + hole), no gap fill (tested 0.84-0.95)
STRIP_C_Y0 = 42.0
POST_A_Y0 = STRIP_C_Y0 + STRIP_D + 1.5
POST_B_Y0 = POST_A_Y0 + POST + POST_GAP
POST_Z = 5.0                            # 25 layers = 25 post-to-post travels per pair
CELL_PITCH = 19.0
CELL_X0 = 10.0                          # first pair centre
RETRACT_Z_MIN = SHEET_Z + 1e-6         # posts are isolated islands above the sheet
# row D: the loose hex tester (the card's back row)
ROW_D_Y0 = POST_B_Y0 + POST + 1.5
TESTER_XY = (20.0, ROW_D_Y0 + 5.0)
TESTER_Z = 7.0
CARD_D = TESTER_XY[1] + TESTER_AF / 2   # 77: card depth, tower or not
CARD_TOP = max(RAIL_Z, PAD_Z, POST_Z, TESTER_Z)
# temperature tower: its own object, right of the card, centred on the card's depth
PILLAR_W, PILLAR_D, TOWER_GAP = 9.0, 6.0, 10.0
PILLAR_WALL = 0.84                      # hollow pillars: two 0.42 loops, no infill, no gap fill
TOWER_W = 2 * PILLAR_W + TOWER_GAP
PEDESTAL_Z = 7.0                        # bands start above the card's height: the pedestal is the reference at --temp
BAND_H = 4.0
DECK_H = 1.0                            # bridge deck closing the gap at each band top
CHIN_STEP, CHIN_STEPS = 0.3, 8          # 0.3 mm out per 0.2 layer = 56 deg overhang
CHIN_Z0 = 1.4                           # chin starts 7 layers into the band (the band is already at temperature: M109)
TPX = 0.7                               # tower digit pixel (digits 2.1 x 3.5 mm)
TDEPTH = 1.0                            # digit protrusion from the pillar face
TOWER_TOP = PEDESTAL_Z + BAND_H * len(TEMP_DELTAS)
TOWER_D = PILLAR_D + CHIN_STEP * CHIN_STEPS   # footprint depth including the chin
TOWER_X0 = CARD_W + TOWER_GAP_X
TOWER_Y0 = CARD_D / 2 - TOWER_D / 2

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
    "+": ["000", "010", "111", "010", "000"],
    "-": ["000", "000", "111", "000", "000"],
    ".": ["000", "000", "000", "000", "010"],
    "T": ["111", "010", "010", "010", "010"],
    "F": ["111", "100", "110", "100", "100"],
    "R": ["110", "101", "110", "101", "101"],
    "C": ["111", "100", "100", "100", "111"],
    " ": ["000", "000", "000", "000", "000"],
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fmt_flow(flow):
    """Flow label = flow x 100 as an integer: 0.98 -> '98', 1.02 -> '102'."""
    return str(int(round(flow * 100)))


# --- mesh primitives -----------------------------------------------------------
def _box(x0, y0, z0, x1, y1, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    tris = []
    for a, b, c, d in quads:
        tris += [(v[a], v[b], v[c]), (v[a], v[c], v[d])]
    return tris


def _prism(poly, z0, z1):
    """Extrude a convex CCW polygon [(x, y), ...] from z0 to z1."""
    n = len(poly)
    bot = [(x, y, z0) for x, y in poly]
    top = [(x, y, z1) for x, y in poly]
    tris = []
    for i in range(1, n - 1):
        tris.append((bot[0], bot[i + 1], bot[i]))       # bottom, facing -Z
        tris.append((top[0], top[i], top[i + 1]))       # top, facing +Z
    for i in range(n):
        j = (i + 1) % n
        tris += [(bot[i], bot[j], top[j]), (bot[i], top[j], top[i])]
    return tris


def _hex(cx, cy, across_flats):
    """Hexagon with corners on the X axis (flats parallel to X at +-af/2 in Y)."""
    r = across_flats / 2 / math.cos(math.radians(30))
    return [(cx + r * math.cos(math.radians(60 * k)),
             cy + r * math.sin(math.radians(60 * k))) for k in range(6)]


def _tube(x0, y0, x1, y1, z0, z1, wall):
    """Square tube = four wall boxes (union of overlapping shells)."""
    return (_box(x0, y0, z0, x1, y0 + wall, z1) + _box(x0, y1 - wall, z0, x1, y1, z1) +
            _box(x0, y0, z0, x0 + wall, y1, z1) + _box(x1 - wall, y0, z0, x1, y1, z1))


def _label_lit(text):
    lit = set()
    x = 0
    for ch in text:
        glyph = FONT[ch]
        for r in range(5):
            for c in range(3):
                if glyph[r][c] == "1":
                    lit.add((x + c, r))
        x += 4
    return lit, x - 1


def label_width(text, px=PX):
    return _label_lit(text)[1] * px


def _label_flat(text, x0, y_top, z0, z1, px=PX):
    """Raised text on a horizontal surface; row 0 at y_top, reads upright from the front."""
    lit, _ = _label_lit(text)
    tris = []
    for c, r in lit:
        tris += _box(x0 + c * px, y_top - (r + 1) * px, z0,
                     x0 + (c + 1) * px, y_top - r * px, z1)
    return tris


def _label_wall(text, x0, z_top, y_face, depth, px=TPX):
    """Raised text on a vertical face at y = y_face, protruding toward -Y."""
    lit, _ = _label_lit(text)
    tris = []
    for c, r in lit:
        tris += _box(x0 + c * px, y_face - depth, z_top - (r + 1) * px,
                     x0 + (c + 1) * px, y_face, z_top - r * px)
    return tris


def _hex_bbox(cx, cy, af):
    r = af / 2 / math.cos(math.radians(30))
    return cx - r, cx + r, cy - af / 2, cy + af / 2


def _rib_around_holes(x0, x1, y0, y1, z1, holes, margin):
    """Sheet rib x0..x1 by y0..y1, minus the Y span of every hex hole it would
    cross (plus margin), so a rib ends inside the rail wall next to a hole and
    never floors the hole. Returns (triangles, [(ya, yb), ...] kept spans)."""
    spans = [(y0, y1)]
    for cx, cy, af in holes:
        hx0, hx1, hy0, hy1 = _hex_bbox(cx, cy, af)
        if x1 <= hx0 or x0 >= hx1:
            continue
        cut0, cut1 = hy0 - margin, hy1 + margin
        kept = []
        for a, b in spans:
            if b <= cut0 or a >= cut1:
                kept.append((a, b))
                continue
            if a < cut0:
                kept.append((a, cut0))
            if b > cut1:
                kept.append((cut1, b))
        spans = kept
    tris = []
    for a, b in spans:
        tris += _box(x0, a, 0, x1, b, z1)
    return tris, spans


def _segment_in_convex(p, q, poly, margin=0.0):
    """True if any part of segment p-q lies strictly inside the convex CCW
    polygon shrunk by `margin` (Cyrus-Beck clipping)."""
    t0, t1 = 0.0, 1.0
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        length = math.hypot(ex, ey)
        nx, ny = -ey / length, ex / length          # inward normal of a CCW edge
        dp = nx * (p[0] - ax) + ny * (p[1] - ay) - margin
        dq = nx * (q[0] - ax) + ny * (q[1] - ay) - margin
        if dp <= 0 and dq <= 0:
            return False
        if dp > 0 and dq > 0:
            continue
        t = dp / (dp - dq)
        if dp <= 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 >= t1:
            return False
    return t1 - t0 > 1e-9


def _hex_rail_with_holes(x0, x1, y0, y1, z0, z1, holes):
    """Rectangle strip with hexagonal through-holes (corners on X), as a union
    of convex pieces: the slicer unions overlapping shells of one object, so no
    boolean library is needed."""
    tris = []
    cuts = []
    for cx, cy, af in holes:
        r = af / 2 / math.cos(math.radians(30))
        cuts.append((cx - r, cx + r, cy - af / 2, cy + af / 2, cx, cy, r))
    cuts.sort()
    left = x0
    for hx0, hx1, hy0, hy1, cx, cy, r in cuts:
        if hx0 > left:
            tris += _box(left, y0, z0, hx0, y1, z1)     # material between holes
        left = hx1
    if x1 > left:
        tris += _box(left, y0, z0, x1, y1, z1)
    for hx0, hx1, hy0, hy1, cx, cy, r in cuts:
        tris += _box(hx0, y0, z0, hx1, hy0, z1)         # wall in front of the hole
        tris += _box(hx0, hy1, z0, hx1, y1, z1)         # wall behind the hole
        # four corner triangles between the hole's bounding box and its slanted edges
        tris += _prism([(hx0, cy), (hx0 + r / 2, hy1), (hx0, hy1)], z0, z1)
        tris += _prism([(hx0, hy0), (hx0 + r / 2, hy0), (hx0, cy)], z0, z1)
        tris += _prism([(hx1 - r / 2, hy1), (hx1, cy), (hx1, hy1)], z0, z1)
        tris += _prism([(hx1 - r / 2, hy0), (hx1, hy0), (hx1, cy)], z0, z1)
    return tris


# --- the card -------------------------------------------------------------------
def layout(temp, flow, tower=True):
    """Return (card_triangles, tower_triangles, manifest). The card and the tower
    are separate bodies (separate print objects); the manifest holds every region
    the post-processor and the preview need, in card-local mm."""
    tris = []
    man = {"pads": [], "cells": [], "holes": [], "bands": [], "labels": [], "ribs": []}

    def label(text, x0, y_top, px=PX):
        tris.extend(_label_flat(text, x0, y_top, SHEET_Z, LABEL_Z, px))
        man["labels"].append({"text": text, "x": x0, "y_top": y_top, "px": px})

    # hex holes first: every sheet rib is routed around them
    holes = [(HOLE_X0 + i * HOLE_PITCH, RAIL_Y0 + RAIL_D / 2, TESTER_AF + 2 * gap)
             for i, gap in enumerate(HOLE_GAPS)]

    # label strips B and C (full width) + edge ribs tying rows A-C together.
    # The left rib runs under hole 0: it is split so it stops RIB_HOLE_MARGIN
    # before the hole edge (inside the rail wall) and resumes behind it.
    for sy in (STRIP_B_Y0, STRIP_C_Y0):
        tris += _box(0, sy, 0, CARD_W, sy + STRIP_D, SHEET_Z)
    for rx in (2.0, CARD_W - 2.0 - RIB_W):
        rib, spans = _rib_around_holes(rx, rx + RIB_W, 0, STRIP_C_Y0 + STRIP_D, SHEET_Z,
                                       holes, RIB_HOLE_MARGIN)
        tris += rib
        for ya, yb in spans:
            for cx, cy, af in holes:                       # geometry-level guard
                hx0, hx1, hy0, hy1 = _hex_bbox(cx, cy, af)
                assert rx + RIB_W <= hx0 or rx >= hx1 or yb <= hy0 or ya >= hy1, \
                    ("rib crosses a hex hole", rx, ya, yb, cx)
            man["ribs"].append({"x0": rx, "x1": rx + RIB_W, "y0": ya, "y1": yb, "z": SHEET_Z})

    # row A: tolerance rail with a small label plate under each hole
    for gap, (cx, cy, af) in zip(HOLE_GAPS, holes):
        text = str(int(round(gap * 100)))
        tris += _box(cx - HOLE_PLATE_W / 2, 0, 0, cx + HOLE_PLATE_W / 2, RAIL_Y0, SHEET_Z)
        label(text, cx - label_width(text) / 2, 5.5)
        man["holes"].append({"gap_per_side_mm": gap, "across_flats_mm": round(af, 3),
                             "x": cx, "y": cy, "label": text})
    tris += _hex_rail_with_holes(RAIL_X0, RAIL_X1, RAIL_Y0, RAIL_Y0 + RAIL_D, 0, RAIL_Z, holes)
    info = "T%d F%s" % (temp, fmt_flow(flow))
    iw = label_width(info, INFO_PX)
    tris += _box(RAIL_X1 + 2.0, 0, 0, CARD_W, RAIL_Y0, SHEET_Z)       # info plate
    tris += _box(RAIL_X1 - 0.5, 1.0, 0, RAIL_X1 + 2.5, RAIL_Y0 - 1.0, SHEET_Z)
    label(info, CARD_W - 1.0 - iw, 5.5, INFO_PX)
    man["info"] = {"text": info, "x0": RAIL_X1 + 2.0, "x1": CARD_W, "y0": 0, "y1": RAIL_Y0}

    # row B: flow pads (isolated islands above the sheet)
    for j, d in enumerate(FLOW_DELTAS):
        x0 = j * (PAD + PAD_GAP)
        tris += _box(x0, PAD_Y0, 0, x0 + PAD, PAD_Y0 + PAD, PAD_Z)
        tris += _box(x0 + PAD / 2 - RIB_W / 2, STRIP_B_Y0 + STRIP_D - 0.5, 0,
                     x0 + PAD / 2 + RIB_W / 2, PAD_Y0 + 0.5, SHEET_Z)
        f = round(flow + d, 3)
        text = fmt_flow(f)
        label(text, x0 + PAD / 2 - label_width(text) / 2, STRIP_B_Y0 + 5.5)
        man["pads"].append({"flow": f, "delta": d, "label": text,
                            "x0": x0, "x1": x0 + PAD, "y0": PAD_Y0, "y1": PAD_Y0 + PAD,
                            "z_scale_min": PAD_SCALE_Z_MIN, "z_top": PAD_Z})

    # row C: retraction post pairs
    for i, r in enumerate(RETRACTIONS):
        cx = CELL_X0 + i * CELL_PITCH
        for py in (POST_A_Y0, POST_B_Y0):
            tris += _tube(cx - POST / 2, py, cx + POST / 2, py + POST, 0, POST_Z, POST_WALL)
        tris += _box(cx - RIB_W / 2, STRIP_C_Y0 + STRIP_D - 0.5, 0,
                     cx + RIB_W / 2, POST_A_Y0 + 0.5, SHEET_Z)
        tris += _box(cx - 1.5, POST_A_Y0 + POST - 0.5, 0, cx + 1.5, POST_B_Y0 + 0.5, SHEET_Z)
        text = "%.1f" % r
        label(text, cx - label_width(text) / 2, STRIP_C_Y0 + 5.5)
        man["cells"].append({"retraction_mm": r, "label": text,
                             "x0": cx - POST / 2, "x1": cx + POST / 2,
                             "y0": POST_A_Y0, "y1": POST_B_Y0 + POST,
                             "y_mid": (POST_A_Y0 + POST + POST_B_Y0) / 2,
                             "z_min": RETRACT_Z_MIN, "z_top": POST_Z})

    # row D: loose hex tester (never touches the card)
    tris += _prism(_hex(TESTER_XY[0], TESTER_XY[1], TESTER_AF), 0, TESTER_Z)
    man["tester"] = {"x": TESTER_XY[0], "y": TESTER_XY[1], "across_flats_mm": TESTER_AF,
                     "height_mm": TESTER_Z}
    man["card"] = {"w": CARD_W, "d": CARD_D, "top_z": CARD_TOP, "temp": temp, "flow": flow,
                   "tower": tower, "strips_y": [STRIP_B_Y0, STRIP_C_Y0], "strip_d": STRIP_D,
                   "rail": {"x0": RAIL_X0, "x1": RAIL_X1, "y0": RAIL_Y0, "y1": RAIL_Y0 + RAIL_D,
                            "z": RAIL_Z}}

    # the temperature tower: a separate object, TOWER_GAP_X right of the card
    ttris = []
    plate_x1, plate_top = CARD_W, CARD_TOP
    if tower:
        lx0, rx0 = TOWER_X0, TOWER_X0 + PILLAR_W + TOWER_GAP
        ty0, ty1 = TOWER_Y0, TOWER_Y0 + PILLAR_D
        for px0 in (lx0, rx0):
            ttris += _tube(px0, ty0, px0 + PILLAR_W, ty1, 0, TOWER_TOP, PILLAR_WALL)
        ttris += _box(lx0 + PILLAR_W, ty0, PEDESTAL_Z - DECK_H, rx0, ty1, PEDESTAL_Z)  # reference bridge at --temp
        for b, d in enumerate(TEMP_DELTAS):
            z0 = PEDESTAL_Z + b * BAND_H
            z1 = z0 + BAND_H
            t = temp + d
            ttris += _box(lx0 + PILLAR_W, ty0, z1 - DECK_H, rx0, ty1, z1)           # bridge deck
            for k in range(1, CHIN_STEPS + 1):                                      # overhang chin, back face
                zs = z0 + CHIN_Z0 + (k - 1) * LAYER
                ttris += _box(rx0, ty1, zs, rx0 + PILLAR_W, ty1 + CHIN_STEP * k, zs + LAYER)
            ttris += _box(rx0, ty1, z0 + CHIN_Z0 + CHIN_STEPS * LAYER, rx0 + PILLAR_W,
                          ty1 + CHIN_STEP * CHIN_STEPS, z1)                          # lip up to the band top
            text = str(t)
            w = label_width(text, TPX)
            ttris += _label_wall(text, lx0 + (PILLAR_W - w) / 2, z0 + 0.3 + 5 * TPX, ty0, TDEPTH)
            man["bands"].append({"temp": t, "delta": d, "z0": z0, "z1": z1,
                                 "first_z": round(z0 + LAYER, 3),
                                 "first_layer_of_tower": int(round(z0 / LAYER)) + 1, "label": text})
        man["tower"] = {"x0": lx0, "x1": rx0 + PILLAR_W, "y0": ty0, "y1": ty1 + CHIN_STEP * CHIN_STEPS,
                        "pillar_y1": ty1, "pedestal_z": PEDESTAL_Z, "top_z": TOWER_TOP,
                        "chin_out_mm": CHIN_STEP * CHIN_STEPS, "bridge_mm": TOWER_GAP,
                        "gap_to_card_mm": TOWER_GAP_X, "head_clearance_rule_mm": CLEARANCE_RADIUS,
                        "digit_face": "front (-Y)", "chin_face": "back (+Y) of the right pillar",
                        "print_order": "after the card (print_sequence by object), bands M109"}
        assert TOWER_GAP_X > CLEARANCE_RADIUS and TOWER_TOP < CLEARANCE_HEIGHT_TO_ROD and \
            CARD_TOP < CLEARANCE_HEIGHT_TO_ROD, "layout breaks the sequential-print clearance"
        plate_x1, plate_top = rx0 + PILLAR_W, TOWER_TOP
    man["plate"] = {"x0": 0.0, "x1": plate_x1, "y0": 0.0, "y1": CARD_D, "top_z": plate_top}
    return tris, ttris, man


def write_stl(tris, path, shift):
    """Binary STL, translated by shift=(dx, dy) to bed coordinates."""
    with path.open("wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(tris)))
        for t in tris:
            f.write(struct.pack("<3f", 0, 0, 0))
            for x, y, z in t:
                f.write(struct.pack("<3f", x + shift[0], y + shift[1], z))
            f.write(struct.pack("<H", 0))


def model_bounds(tris):
    xs = [p[0] for t in tris for p in t]
    ys = [p[1] for t in tris for p in t]
    zs = [p[2] for t in tris for p in t]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


# --- slicing --------------------------------------------------------------------
def slice_card(models, filament, temp, flow, out_dir, extra, sequential):
    """models: one STL per print object, in print order (card first)."""
    cmd = [sys.executable, str(SLICER)] + [str(m) for m in models] + ["--out", str(out_dir),
           "--filament", filament, "--layer", "0.20", "--no-iron", "--no-brim",
           "--no-arrange", "--temp", str(temp), "--flow", str(flow),
           "--min-layer-time", str(MIN_LAYER_TIME_S),
           "--fil", "nozzle_temperature_initial_layer=%d" % temp]
    if sequential:
        # one object at a time, in file order: card first, tower last (verified in the header)
        cmd += ["--proc", "print_sequence=by object", "--proc", "print_order=as_obj_list"]
    cmd += extra
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=False, cwd=str(REPO))
    gcodes = list(pathlib.Path(out_dir).glob("*.gcode"))
    assert len(gcodes) == 1, "expected one G-code, got %r (see %s/slice.log)" % (gcodes, out_dir)
    return gcodes[0]


# --- post-processing --------------------------------------------------------------
_PARAM = re.compile(r"\b([XYZEF])(-?\d*\.?\d+)")


def _params(line):
    return {k: float(v) for k, v in _PARAM.findall(line.split(";", 1)[0])}


def _fmt_e(v):
    s = ("%.5f" % v).rstrip("0").rstrip(".")
    if s.startswith("0."):
        s = s[1:]
    elif s.startswith("-0."):
        s = "-" + s[2:]
    return s if s not in ("", "-") else "0"


def _sub_e(line, value):
    return re.sub(r"\bE-?\d*\.?\d+", "E" + _fmt_e(value), line)


def _objects(src, start, end):
    """The print objects in print order, from the G-code alone. Sequential G-code
    numbers ;LAYER: globally (card 1-35, tower 36-170) but ;Z: restarts at the
    first layer of every object, so an object begins at a ;LAYER: marker whose Z
    is lower than the previous layer's. Each entry: marker line, first / last
    extrusion line, top Z, extrusion bounding box."""
    objs = []
    z = None
    pending = LAYER            # ;Z:0.2 of layer 1 sits before `start`
    x = y = None
    for i in range(start, end):
        line = src[i]
        if line.startswith(";Z:"):
            pending = float(line[3:])
        elif line.startswith(";LAYER:"):
            if z is None or pending < z - 1e-6:
                objs.append({"marker": i, "first_e": None, "last_e": None, "z_top": 0.0,
                             "x": [1e9, -1e9], "y": [1e9, -1e9]})
            z = pending
        elif line.startswith(("G0", "G1")) and objs:
            p = _params(line)
            if "X" in p:
                x = p["X"]
            if "Y" in p:
                y = p["Y"]
            if p.get("E", 0) > 0 and ("X" in p or "Y" in p):
                o = objs[-1]
                if o["first_e"] is None:
                    o["first_e"] = i
                o["last_e"] = i
                o["z_top"] = max(o["z_top"], z)
                o["x"] = [min(o["x"][0], x), max(o["x"][1], x)]
                o["y"] = [min(o["y"][0], y), max(o["y"][1], y)]
    return objs


def rewrite(text, man, temp, base_flow):
    """Apply per-pad flow, per-pair retraction and per-band temperature.
    Returns (new_text, stats). Fails loudly on anything it does not model."""
    src = text.splitlines()
    assert re.search(r"^; use_relative_e_distances = 1\s*$", text, re.M), "need relative E"
    assert re.search(r"^; use_firmware_retraction = 0\s*$", text, re.M), "firmware retraction on"
    assert not re.search(r"^(G91|M82)\b", text, re.M), "absolute E / relative XYZ not supported"
    stock_retract = float(re.search(r"^; retraction_length = ([\d.]+)", text, re.M).group(1))
    m = re.search(r"^; filament_flow_ratio = ([\d.]+)", text, re.M)
    assert abs(float(m.group(1)) - base_flow) < 1e-6, ("header flow", m.group(1), base_flow)

    start = next(i for i, l in enumerate(src) if l.startswith(";LAYER:1"))
    end = next(i for i, l in enumerate(src) if "CC2_END_GCODE" in l)
    objs = _objects(src, start, end)
    want_objs = 2 if man["bands"] else 1
    assert len(objs) == want_objs, ("print objects found", len(objs), want_objs)
    card_end = objs[1]["marker"] if len(objs) > 1 else end

    # pass 1: the card's printed bounding-box centre (above layer 1) -> card-local
    # transform. The CLI re-centres the plate (Y -1.5 seen), so the print is
    # located from the G-code itself, not assumed. Only the card object is used.
    x = y = None
    z = LAYER
    pts = []
    for line in src[start:card_end]:
        if line.startswith(";Z:"):
            z = float(line[3:])
        if not line.startswith(("G0", "G1")):
            continue
        p = _params(line)
        if "X" in p:
            x = p["X"]
        if "Y" in p:
            y = p["Y"]
        if z > LAYER + 1e-6 and p.get("E", 0) > 0 and ("X" in p or "Y" in p):
            pts.append((x, y))
    (mx0, mx1), (my0, my1), _ = man["_card_bounds"]
    px0, px1 = min(q[0] for q in pts), max(q[0] for q in pts)
    py0, py1 = min(q[1] for q in pts), max(q[1] for q in pts)
    dx = (px0 + px1) / 2 - (mx0 + mx1) / 2
    dy = (py0 + py1) / 2 - (my0 + my1) / 2
    assert abs(dx) < 5 and abs(dy) < 5, ("print is not where the model put it", dx, dy)
    inset = ((mx1 - mx0) - (px1 - px0)) / 2      # outer wall centreline sits half a line inside
    assert 0.1 < inset < 0.4, ("unexpected wall inset", inset)
    ox, oy = man["_bed_shift"][0] + dx, man["_bed_shift"][1] + dy

    def pad_at(xg, yg, z):
        if xg is None or yg is None:
            return None
        xl, yl = xg - ox, yg - oy
        for k, pad in enumerate(man["pads"]):
            if (pad["x0"] - 0.5 <= xl <= pad["x1"] + 0.5 and pad["y0"] - 0.5 <= yl <= pad["y1"] + 0.5
                    and z > pad["z_scale_min"]):
                return k
        return None

    def cell_at(xg, yg, z):
        """(cell index, post 0/1) or None."""
        if xg is None or yg is None:
            return None
        xl, yl = xg - ox, yg - oy
        for k, c in enumerate(man["cells"]):
            if (c["x0"] - 1.0 <= xl <= c["x1"] + 1.0 and c["y0"] - 1.0 <= yl <= c["y1"] + 1.0
                    and z > c["z_min"]):
                return k, int(yl > c["y_mid"])
        return None

    band_at_z = {b["first_z"]: b for b in man["bands"]}
    tower_marker = objs[1]["marker"] if len(objs) > 1 else None
    travel_f = int(float(re.search(r"^; travel_speed = ([\d.]+)", text, re.M).group(1)) * 60)
    park_x = None
    if man["bands"]:
        # M109 park point: beyond the tower's right edge, on the bed, outside the
        # excluded corner, and further from the card than the head clearance rule
        park_x = round(ox + man["tower"]["x1"] + TEMP_WAIT_PARK_DX, 3)
        assert park_x < BED - 5 and park_x - (ox + CARD_W) >= CLEARANCE_RADIUS, ("park point", park_x)

    # pass 2: rewrite
    out = list(src[:start])
    x = y = None
    z = LAYER
    pending_z = LAYER
    layer = 1
    in_tower = False
    feed = None                    # modal F, restored after the park travels
    seq = None                     # open retraction sequence
    temp_cmds = []                 # (band temp, z, global layer, output line)
    pad_moves = [0] * len(man["pads"])
    pad_e = [[0.0, 0.0] for _ in man["pads"]]
    cell_seqs = [0] * len(man["cells"])
    cell_ab = [0] * len(man["cells"])
    other_seqs = other_moves = orphan_unretracts = 0
    retract_sums = []
    for i in range(start, end):
        line = src[i]
        if line.startswith(";Z:"):
            pending_z = float(line[3:])       # applied at the ;LAYER: marker: the layer-change retract still belongs to the old Z
            out.append(line)
            continue
        if line.startswith(";LAYER:"):
            layer = int(line[7:])
            if i == tower_marker:
                in_tower = True
            z_prev, z = z, round(pending_z, 3)
            out.append(line)
            if in_tower and z in band_at_z:
                b = band_at_z[z]
                # The nozzle sits retracted at the end of the previous layer. Lift
                # to band Z + 2 (Z only, current feed), park beside the tower, wait
                # for the band, come back over the same XY still lifted; the
                # slicer's own next move brings Z down to the layer. No E anywhere.
                assert x is not None and y is not None
                ex0, ex1, ey0, ey1 = BED_EXCLUDE
                assert not (ex0 <= park_x <= ex1 and ey0 <= y <= ey1), "park point in bed_exclude_area"
                z_wait = round(z + TEMP_WAIT_LIFT, 3)
                out.append("G1 Z%.3f ; CC2_CARD lift to band Z + %.0f mm (retracted)" % (z_wait, TEMP_WAIT_LIFT))
                out.append("G1 X%.3f Y%.3f F%d ; CC2_CARD park %.0f mm beside the tower" % (park_x, y, travel_f, TEMP_WAIT_PARK_DX))
                out.append("M109 S%d ; CC2_CARD band %+d C starts at Z%.1f (tower layer %d), wait for it"
                           % (b["temp"], b["delta"], b["z0"], b["first_layer_of_tower"]))
                out.append("G1 X%.3f Y%.3f F%d ; CC2_CARD resume over the layer start, still lifted" % (x, y, travel_f))
                if feed is not None and int(feed) != travel_f:
                    out.append("G1 F%s ; CC2_CARD restore feed" % _fmt_e(feed))
                temp_cmds.append((b["temp"], z, layer, len(out) - 1))
            continue
        if not line.startswith(("G0", "G1")):
            out.append(line)
            continue
        p = _params(line)
        x_prev, y_prev = x, y
        if "X" in p:
            x = p["X"]
        if "Y" in p:
            y = p["Y"]
        if "F" in p:
            feed = p["F"]
        e = p.get("E")
        moved = "X" in p or "Y" in p
        if e is None:
            out.append(line)
            continue
        if e < 0:
            if seq is None:
                seq = {"origin": (x_prev, y_prev), "z": z, "lines": [], "sum": 0.0}
            seq["lines"].append(len(out))
            seq["sum"] += e
            out.append(line)
            continue
        if seq is not None:                                   # e > 0 closes the sequence
            assert not moved, ("extrusion resumed without unretract", layer, line)
            assert abs(seq["sum"] + e) < 1e-4, ("unbalanced retraction", layer, seq["sum"], e)
            hit = cell_at(seq["origin"][0], seq["origin"][1], seq["z"])
            if hit is not None:
                cell, post = hit
                k = man["cells"][cell]["retraction_mm"] / stock_retract
                total = 0.0
                for li in seq["lines"]:
                    ne = round(_params(out[li])["E"] * k, 5)
                    total += ne
                    out[li] = _sub_e(out[li], ne)
                new_e = round(-total, 5)
                line = _sub_e(line, new_e) + " ; CC2_CARD retract %.1f" % man["cells"][cell]["retraction_mm"]
                cell_seqs[cell] += 1
                dest = cell_at(x, y, z)
                if dest is not None and dest[0] == cell and dest[1] != post:
                    cell_ab[cell] += 1
                retract_sums.append((cell, round(total, 5), new_e))
            else:
                other_seqs += 1
            seq = None
            out.append(line)
            continue
        if not moved:
            # unretract whose retract happened before ;LAYER:1 (start G-code)
            orphan_unretracts += 1
            assert orphan_unretracts <= 1 and layer == 1, ("positive E without motion", layer, line)
            out.append(line)
            continue
        pad = pad_at(x, y, z)
        pad_from = pad_at(x_prev, y_prev, z)
        if pad is not None:
            assert pad_from == pad, ("move crosses a pad boundary", layer, line)
            k = man["pads"][pad]["flow"] / base_flow
            ne = round(e * k, 5)
            out.append(_sub_e(line, ne))
            pad_moves[pad] += 1
            pad_e[pad][0] += e
            pad_e[pad][1] += ne
        else:
            assert pad_from is None, ("move leaves a pad while extruding", layer, line)
            other_moves += 1
            out.append(line)
    # the print's last retraction has no unretract: it stays stock (it is the
    # travel to the park position, nothing is printed after it)
    final_open = seq is not None
    out.extend(src[end:])
    stats = {"shift_xy_mm": [round(dx, 3), round(dy, 3)], "wall_inset_mm": round(inset, 3),
             "origin_xy_mm": [ox, oy],
             "printed_bounds_xy_mm": [[px0, px1], [py0, py1]],
             "temperature_commands": [{"m109_s": t, "z": zz, "global_layer": gl} for t, zz, gl, _ in temp_cmds],
             "stock_retraction_mm": stock_retract,
             "pad_moves": pad_moves, "pad_e_ratio": [round(b / a, 6) if a else None for a, b in pad_e],
             "cell_sequences": cell_seqs, "cell_post_to_post_travels": cell_ab,
             "other_sequences": other_seqs, "other_moves": other_moves,
             "final_retraction_left_open": final_open, "retract_sums": retract_sums}
    return "\n".join(out) + "\n", stats


# --- verification --------------------------------------------------------------------
def verify(text, man, temp, base_flow, stats):
    tower = bool(man["bands"])
    assert not re.search(r"^M600\b", text, re.M), "M600 present (CC2 hangs on it)"
    assert not re.search(r"^T[1-9]\d*\b|^M6211 T", text, re.M), "multi-tool commands present"
    assert re.search(r"^M6211 A1 L200 T0 ", text, re.M), "CANVAS slot 1 selection missing"
    assert re.search(r"^M109 S%d\b" % temp, text, re.M), "initial M109 missing"
    assert re.search(r"^M104 S0\b", text, re.M) and re.search(r"^M140 S0\b", text, re.M)
    assert re.search(r"^; nozzle_temperature = %d\s*$" % temp, text, re.M)
    assert re.search(r"^; nozzle_temperature_initial_layer = %d\s*$" % temp, text, re.M)
    assert re.search(r"^; retraction_length = %g\s*$" % stats["stock_retraction_mm"], text, re.M)
    assert re.search(r"^; ironing_type = no ironing", text, re.M)
    assert re.search(r"^; brim_type = no_brim", text, re.M)
    assert re.search(r"^; layer_height = 0\.2\s*$", text, re.M)
    assert re.search(r"^; slow_down_for_layer_cooling = 1\s*$", text, re.M)
    assert re.search(r"^; slow_down_layer_time = %d\s*$" % MIN_LAYER_TIME_S, text, re.M), "min layer time"
    assert re.search(r"^; print_sequence = %s\s*$" % ("by object" if tower else "by layer"), text, re.M), "print_sequence"
    assert re.search(r"^; extruder_clearance_radius = %g\s*$" % CLEARANCE_RADIUS, text, re.M), "clearance radius changed"
    assert re.search(r"^; extruder_clearance_height_to_rod = %g\s*$" % CLEARANCE_HEIGHT_TO_ROD, text, re.M), "rod height changed"
    assert re.search(r"^; extruder_clearance_height_to_lid = %g\s*$" % CLEARANCE_HEIGHT_TO_LID, text, re.M), "lid height changed"
    if tower:
        assert re.search(r"^; print_order = as_obj_list\s*$", text, re.M), "print_order"

    src = text.splitlines()
    start = next(i for i, l in enumerate(src) if l.startswith(";LAYER:1"))
    end = next(i for i, l in enumerate(src) if "CC2_END_GCODE" in l)
    objs = _objects(src, start, end)
    assert len(objs) == (2 if tower else 1), ("objects", len(objs))
    ox, oy = stats["origin_xy_mm"]
    park_x = ox + man["tower"]["x1"] + TEMP_WAIT_PARK_DX if tower else None
    card, seq_report = objs[0], None
    # the card object: every extrusion inside the card's footprint, all of it below the rod height
    assert ox - 1 < card["x"][0] and card["x"][1] < ox + CARD_W + 1, ("card X", card["x"])
    assert oy - 1 < card["y"][0] and card["y"][1] < oy + CARD_D + 1, ("card Y", card["y"])
    assert abs(card["z_top"] - CARD_TOP) < 1e-6, ("card top", card["z_top"])
    assert card["z_top"] < CLEARANCE_HEIGHT_TO_ROD
    if tower:
        tw, tman = objs[1], man["tower"]
        # the tower object: printed after the whole card, inside its own footprint, clear of the card
        assert card["last_e"] < tw["marker"] < tw["first_e"], "tower extrusion before the card finished"
        assert ox + tman["x0"] - 1 < tw["x"][0] and tw["x"][1] < ox + tman["x1"] + 1, ("tower X", tw["x"])
        assert oy + tman["y0"] - 1 < tw["y"][0] and tw["y"][1] < oy + tman["y1"] + 1, ("tower Y", tw["y"])
        assert abs(tw["z_top"] - TOWER_TOP) < 1e-6, ("tower top", tw["z_top"])
        assert tw["z_top"] < CLEARANCE_HEIGHT_TO_ROD < CLEARANCE_HEIGHT_TO_LID
        gap = tw["x"][0] - card["x"][1]           # wall centrelines; the hulls are ~0.2 mm further apart
        assert gap >= CLEARANCE_RADIUS + 10, ("head clearance gap", gap)
        # no temperature command while the card prints; only S<temp> between the objects
        for line in src[card["first_e"]:card["last_e"] + 1]:
            assert not re.match(r"M10[49]\b", line), ("temperature command inside the card", line)
        between = [l for l in src[card["last_e"]:tw["marker"]] if re.match(r"M10[49]\b", l)]
        assert all(re.match(r"M10[49]\s+S%d\b" % temp, l) for l in between), ("between objects", between)
        seq_report = {"card_gcode_lines": [card["first_e"] + 1, card["last_e"] + 1],
                      "tower_gcode_lines": [tw["first_e"] + 1, tw["last_e"] + 1],
                      "card_printed_xy_mm": [card["x"], card["y"]], "tower_printed_xy_mm": [tw["x"], tw["y"]],
                      "card_top_z_mm": card["z_top"], "tower_top_z_mm": tw["z_top"],
                      "gap_card_to_tower_mm": round(gap, 3),
                      "temperature_wait": {"lift_above_band_mm": TEMP_WAIT_LIFT,
                                           "park_x_mm": round(park_x, 3), "park_beyond_tower_mm": TEMP_WAIT_PARK_DX,
                                           "checked": "M109 at the park XY, lifted; no E between lift and Z restore; resume XY = pre-lift XY"},
                      "clearance_rule": {"extruder_clearance_radius_mm": CLEARANCE_RADIUS,
                                         "margin_mm": round(gap - CLEARANCE_RADIUS, 3),
                                         "extruder_clearance_height_to_rod_mm": CLEARANCE_HEIGHT_TO_ROD,
                                         "extruder_clearance_height_to_lid_mm": CLEARANCE_HEIGHT_TO_LID},
                      "slicer_temperature_commands_between_objects": between}
    # bed: everything inside 256 x 256 and outside the excluded front-right corner
    for o in objs:
        assert 0 < o["x"][0] < o["x"][1] < BED and 0 < o["y"][0] < o["y"][1] < BED, ("off the bed", o["x"], o["y"])
        ex0, ex1, ey0, ey1 = BED_EXCLUDE
        assert o["x"][1] < ex0 or o["x"][0] > ex1 or o["y"][1] < ey0 or o["y"][0] > ey1, "in bed_exclude_area"

    # effective nozzle target at every extrusion move + no extrusion inside a hex hole
    target = None
    for line in src[:start]:
        m = re.match(r"M10[49]\s+S(\d+)", line)
        if m:
            target = int(m.group(1))
    assert target == temp
    hole_polys = [_hex(h["x"] + ox, h["y"] + oy, h["across_flats_mm"]) for h in man["holes"]]
    hole_boxes = [_hex_bbox(h["x"] + ox, h["y"] + oy, h["across_flats_mm"]) for h in man["holes"]]
    hole_hits = [0] * len(hole_polys)          # extrusion segments entering the hole footprint
    hole_near = [0] * len(hole_polys)          # extrusion segments within 1 mm of it (its walls)
    z = LAYER
    pending_z = LAYER
    x = y = zm = None                          # modal XYZ from the moves themselves
    checked = 0
    per_band = {}
    m109 = []                                  # (S, z of the layer it opens, in tower?)
    in_tower = False
    tower_marker = objs[1]["marker"] if tower else None
    lift = None                                # open lift / park / wait / resume window
    windows = 0
    for i in range(start, end):
        line = src[i]
        if line.startswith(";Z:"):
            pending_z = float(line[3:])
        if line.startswith(";LAYER:"):
            z = round(pending_z, 3)
            in_tower = in_tower or i == tower_marker
        m = re.match(r"M10[49]\s+S(\d+)", line)
        if m:
            target = int(m.group(1))
            if line.startswith("M109"):
                assert lift is not None and lift["phase"] == "parked", ("M109 outside a park window", line)
                assert abs(x - park_x) < 1e-3 and abs(y - lift["pre"][1]) < 1e-3, ("M109 not at the park point", x, y)
                assert zm >= z + TEMP_WAIT_LIFT - 1e-6, ("M109 not lifted", zm, z)
                lift["phase"] = "waited"
                m109.append((target, z, in_tower))
        if not line.startswith(("G0", "G1")):
            continue
        p = _params(line)
        x_prev, y_prev = x, y
        if "X" in p:
            x = p["X"]
        if "Y" in p:
            y = p["Y"]
        if "Z" in p:
            zm = p["Z"]
        if "CC2_CARD lift" in line:
            assert lift is None and not ("X" in p or "Y" in p or "E" in p), line
            assert zm >= z + TEMP_WAIT_LIFT - 1e-6, ("lift too low", zm, z)
            lift = {"phase": "lifted", "pre": (x, y), "z": zm, "layer_z": z}
            windows += 1
            continue
        if lift is not None:
            assert p.get("E", 0) <= 0, ("extrusion inside a temperature wait window", line)
            if "CC2_CARD park" in line:
                assert lift["phase"] == "lifted" and abs(zm - lift["z"]) < 1e-6, line
                assert abs(x - park_x) < 1e-3 and abs(y - lift["pre"][1]) < 1e-3, line
                assert x >= ox + man["tower"]["x1"] + TEMP_WAIT_PARK_DX - 1e-3 and x < BED - 5, ("park off the bed", x)
                assert x - (ox + CARD_W) >= CLEARANCE_RADIUS, ("park too near the card", x)
                lift["phase"] = "parked"
                continue
            if "CC2_CARD resume" in line:
                assert lift["phase"] == "waited" and abs(zm - lift["z"]) < 1e-6, line
                assert abs(x - lift["pre"][0]) < 1e-3 and abs(y - lift["pre"][1]) < 1e-3, ("resume XY", x, y, lift["pre"])
                lift["phase"] = "resumed"
                continue
            if zm is not None and zm <= lift["layer_z"] + 1e-6:
                assert lift["phase"] == "resumed", ("Z restored before the resume move", line)
                lift = None                    # the slicer's own move brought Z down to the layer
        if line.startswith("G1") and p.get("E", 0) > 0 and ("X" in p or "Y" in p):
            want = temp
            if in_tower:
                for b in man["bands"]:
                    if z > b["z0"] + 1e-6:
                        want = b["temp"]
            assert target == want, ("nozzle target", z, target, want, line)
            checked += 1
            per_band[want] = per_band.get(want, 0) + 1
            if x_prev is not None and y_prev is not None:
                for k, (poly, (bx0, bx1, by0, by1)) in enumerate(zip(hole_polys, hole_boxes)):
                    if (max(x_prev, x) < bx0 - 1 or min(x_prev, x) > bx1 + 1
                            or max(y_prev, y) < by0 - 1 or min(y_prev, y) > by1 + 1):
                        continue
                    hole_near[k] += 1
                    if _segment_in_convex((x_prev, y_prev), (x, y), poly):
                        hole_hits[k] += 1
    assert checked > 5000, checked
    assert all(n > 50 for n in hole_near), ("hole walls not seen", hole_near)
    assert not any(hole_hits), ("extrusion inside a hex hole footprint (moves per hole)", hole_hits)
    expected_temps = {b["temp"] for b in man["bands"]} | {temp}
    assert set(per_band) == expected_temps, per_band
    # one M109 per band, in the tower, opening exactly the band's first layer
    assert m109 == [(b["temp"], b["first_z"], True) for b in man["bands"]], ("M109 per band", m109)
    assert len(stats["temperature_commands"]) == len(man["bands"])
    assert lift is None and windows == len(man["bands"]), ("lift/park windows", windows, lift)
    # pads: every pad got its exact ratio
    for k, pad in enumerate(man["pads"]):
        want = pad["flow"] / base_flow
        assert stats["pad_moves"][k] > 200, ("pad moves", k, stats["pad_moves"][k])
        assert abs(stats["pad_e_ratio"][k] - want) < 2e-4, (k, stats["pad_e_ratio"][k], want)
    # cells: at least one post-to-post travel per layer above the sheet
    layers_active = int(round((POST_Z - RETRACT_Z_MIN) / LAYER))
    for k, c in enumerate(man["cells"]):
        assert stats["cell_post_to_post_travels"][k] >= layers_active - 2, \
            ("post-to-post travels", k, stats["cell_post_to_post_travels"][k], layers_active)
    for cell, total, new_e in stats["retract_sums"]:
        want = -man["cells"][cell]["retraction_mm"]
        assert abs(total - want) < 1e-3 and abs(new_e + total) < 1e-6, (cell, total, new_e)
    (x0, x1), (y0, y1) = stats["printed_bounds_xy_mm"]
    assert 0 < x0 < x1 < BED and 0 < y0 < y1 < BED
    # material: recompute from the rewritten E (header grams are pre-rewrite)
    e_total = 0.0
    for line in src[start:end]:
        if line.startswith("G1") and "E" in line:
            e_total += _params(line).get("E", 0.0)
    density = float(re.search(r"^; filament_density = ([\d.]+)", text, re.M).group(1))
    grams = e_total * math.pi * (FIL_DIAMETER / 2) ** 2 * density / 1000
    est = [l.strip() for l in src if any(t in l for t in (
        "estimated printing time", "total filament used [g]", "total layers count"))]
    report = {"extrusion_moves_checked": checked, "moves_per_temperature": per_band,
              "min_layer_time_s": MIN_LAYER_TIME_S,
              "print_objects": len(objs), "sequential": seq_report,
              "temperature_commands": stats["temperature_commands"],
              "hex_hole_extrusion_hits": hole_hits, "hex_hole_wall_moves_seen": hole_near,
              "pad_moves": stats["pad_moves"], "pad_e_ratio": stats["pad_e_ratio"],
              "cell_sequences": stats["cell_sequences"],
              "cell_post_to_post_travels": stats["cell_post_to_post_travels"],
              "retractions_outside_cells_left_stock": stats["other_sequences"],
              "printed_bounds_xy_mm": stats["printed_bounds_xy_mm"],
              "shift_xy_mm": stats["shift_xy_mm"], "wall_inset_mm": stats["wall_inset_mm"],
              "grams_recomputed_after_rewrite": round(grams, 2),
              "slicer_statistics_pre_rewrite": est}
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filament", default="pla", help="slice_cc2.py --filament key (pla, plaplus, plapro, ...)")
    ap.add_argument("--temp", type=int, default=210, help="card nozzle temperature C; the tower brackets it +-10")
    ap.add_argument("--flow", type=float, default=0.98, help="base flow ratio; pads bracket it -0.03..+0.03")
    ap.add_argument("--no-tower", action="store_true", help="flat card only (no temperature bands)")
    ap.add_argument("--tag", default=None, help="name tag for the G-code (default: --filament upper-cased)")
    ap.add_argument("--slicer-arg", action="append", default=[], help="extra slice_cc2.py argument (repeatable)")
    ap.add_argument("--raw", default=None, help="dev: reuse this pre-rewrite G-code instead of slicing")
    a = ap.parse_args()

    tris, ttris, man = layout(a.temp, a.flow, tower=not a.no_tower)
    plate = man["plate"]
    shift = (BED_CENTRE[0] - (plate["x0"] + plate["x1"]) / 2, BED_CENTRE[1] - (plate["y0"] + plate["y1"]) / 2)
    (cx0, cx1), (cy0, cy1), (cz0, cz1) = model_bounds(tris)
    man["_card_bounds"] = ((cx0 + shift[0], cx1 + shift[0]), (cy0 + shift[1], cy1 + shift[1]), (cz0, cz1))
    man["_bed_shift"] = shift
    stem = "card" if not a.no_tower else "card_flat"
    geometry = {"triangles": len(tris) + len(ttris),
                "card_size_mm": [round(cx1 - cx0, 2), round(cy1 - cy0, 2), round(cz1, 2)],
                "plate_size_mm": [round(plate["x1"] - plate["x0"], 2), round(plate["y1"] - plate["y0"], 2),
                                  round(plate["top_z"], 2)],
                "bed_shift_mm": [round(shift[0], 3), round(shift[1], 3)]}
    if a.no_tower:
        models = [ROOT / "card_flat.stl"]
        write_stl(tris, models[0], shift)
        model_note = "one object, print_sequence by layer"
    else:
        (tx0, tx1), (ty0, ty1), (tz0, tz1) = model_bounds(ttris)
        geometry["tower_size_mm"] = [round(tx1 - tx0, 2), round(ty1 - ty0, 2), round(tz1, 2)]
        geometry["card_to_tower_gap_mm"] = round(tx0 - cx1, 2)
        models = [ROOT / "card.stl", ROOT / "card_tower.stl"]      # two print objects, in print order
        write_stl(tris, models[0], shift)
        write_stl(ttris, models[1], shift)
        model_note = "two objects (card.stl, card_tower.stl) sliced together, print_sequence by object, card first"
    print("card:", geometry, flush=True)

    scratch = pathlib.Path(tempfile.mkdtemp(prefix="cc2-card-"))
    raw = pathlib.Path(a.raw) if a.raw else slice_card(models, a.filament, a.temp, a.flow, scratch, a.slicer_arg,
                                                          sequential=not a.no_tower)
    text, stats = rewrite(raw.read_text(encoding="utf-8", errors="ignore"), man, a.temp, a.flow)
    report = verify(text, man, a.temp, a.flow, stats)

    tag = a.tag or a.filament.upper()
    out = ROOT / ("CC2_CalibCard%s_%s_T%d_F%s.gcode" % ("Flat" if a.no_tower else "", tag, a.temp, fmt_flow(a.flow)))
    out.write_text(text, encoding="utf-8")
    (scratch / "raw_prerewrite.gcode").write_bytes(raw.read_bytes())
    man.pop("_card_bounds")
    man.pop("_bed_shift")
    (ROOT / (stem + "_manifest.json")).write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8")
    verification = {
        "slicer": "ElegooSlicer via tools/slice_cc2.py (--no-iron --no-brim --no-arrange"
                  + (" --proc print_sequence=by object --proc print_order=as_obj_list)" if not a.no_tower else ")"),
        "filament": a.filament, "card_temp_c": a.temp, "card_flow": a.flow, "tower": not a.no_tower,
        "models": [{"file": m.name, "sha256": sha256(m)} for m in models], "model_note": model_note,
        "geometry": geometry,
        "varies": {"flow_pads": [p["flow"] for p in man["pads"]],
                   "retraction_pairs_mm": RETRACTIONS,
                   "temperature_bands_c_bottom_to_top": [b["temp"] for b in man["bands"]],
                   "temperature_band_first_z_mm": [b["first_z"] for b in man["bands"]],
                   "temperature_band_first_layer_of_tower": [b["first_layer_of_tower"] for b in man["bands"]],
                   "temperature_command": "M109 (wait) at each band's first layer, tower object only" if not a.no_tower else None,
                   "hex_holes_across_flats_mm": [h["across_flats_mm"] for h in man["holes"]],
                   "tester_across_flats_mm": TESTER_AF},
        "gcode": out.name, "gcode_sha256": sha256(out),
        "validation": report, "raw_gcode_kept_at": str(scratch),
        "physical_print_tested": False}
    vname = "verification.json" if not a.no_tower else "verification_flat.json"
    (ROOT / vname).write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("Validated G-code:", out)


if __name__ == "__main__":
    main()
