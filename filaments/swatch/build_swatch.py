#!/usr/bin/env python3
"""Per-filament swatch card for the Elegoo Centauri Carbon 2.

One card per spool, kept in a box as the reference for that filament: its
colour and finish, a recessed-text label generated from filaments/<slug>.md
(brand/material/colour, temp, flow, retraction, ironing, tolerance, date) and a
row of small VISUAL checks tuned to what the CC2 shows at 0.20 mm layers.
Verify-only: nothing on the card is varied; the finding is done by
calibration/card/. Original geometry (inspired by PolyNova's V3 card and
Makkuro's swatch, no mesh copied).

Card: 76 x 46 mm, 1.8 mm max (ironed pad), 1.6 mm label plateau and rim, 0.8 mm body.
Print flat, top up, no supports, no brim, single colour, CANVAS slot 1 (T0).

Checks (numbers = the key in README.md and on preview.png):
  1 label       recessed text (0.4 deep) in the plateau's plain monotonic top (Z 1.6).
                Not ironed on purpose: letters chop ironing lines into 1 mm pieces
                and cost 4-5 min; a plain top reads the same
  2 top surface 9 x 11.5 pad at Z 1.8, the only topmost surface, so
                ironing_type=topmost irons it and nothing else: ironed vs the plateau
  3 translucency 5 steps of 1-5 layers (0.2-1.0 mm; step 4 is the body, step 5 stands proud)
  4 text ladder recessed 2 / 2.5 / 3 mm caps, raised 2.5 / 3.5 mm caps (the digit
                is its own cap height): which size still reads on this filament
  5 bridge      two 3 mm bars over a 17 mm window, printed at Z 0.4-0.8
  6 overhang    four tongues stepping 0.2/0.3/0.4/0.5 mm per layer = 45/56/63/68 deg
                from vertical, 7 layers, hanging from the 1.6 mm lip (look at the back)
  7 thin walls  fins 0.4 / 0.6 / 0.8 / 1.0 / 1.2 mm, 0.8 tall, in a window (classic walls,
                detect_thin_wall off: shows what the profile drops or gap-fills)
  8 small holes 1.0 / 1.5 / 2.0 / 2.2 / 2.3 / 2.4 mm vertical holes for a 1.75 mm
                filament pin (CC2 reference: 2.2 friction, 2.3 free, 2.4 loose)
  9 pins        0.8 / 1.2 / 1.6 mm posts, 0.6 mm tall (smallest post that prints)
 10 wall/layers 1.0 mm fin, 1.6 mm tall (8 layers), free-standing across a window:
                local layer quality with light behind it (8 layers cannot show
                periodic Z banding); the rim's outer wall is the 8-layer seam patch
 11 tolerance   two open comparison notches on the bottom edge sized for another
                card's 1.6 mm top edge (rim + plateau): 1.6 + 2 x tolerance and
                1.6 + 2 x (tolerance - 0.1), labelled with the per-side gap. Which
                one slides is an observation to record, not a proven pass/fail

Run (from the repo root), one command per filament:
  python filaments/swatch/build_swatch.py elegoo-pla-emoji
Outputs: filaments/swatch/cards/<slug>/{card.stl, CC2_Swatch_<slug>.gcode,
preview.png, manifest.json, verification.json}.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import numpy as np
import shapely
import shapely.geometry as sg
import shapely.ops
import trimesh
import yaml
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

ROOT = pathlib.Path(__file__).resolve().parent
REPO = next(p for p in ROOT.parents if (p / "tools" / "slice_cc2.py").is_file())
SLICER = REPO / "tools" / "slice_cc2.py"
FILAMENTS = REPO / "filaments"
CARDS = ROOT / "cards"

LAYER = 0.2
FIL_DIAMETER = 1.75
FONT_CANDIDATES = ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ARIALBD.TTF",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]

# --- card geometry (mm, card-local: origin front-left, +X right, +Y back = top of the label)
W, H = 76.0, 46.0
CORNER_R = 3.0
RIM_W, RIM_Z = 2.0, 1.6
BODY_Z = 0.8
PLATEAU = (3.0, 29.5, 72.0, 44.0)          # label plateau, plain monotonic top (not ironed)
PLATEAU_Z = 1.6
TEXT_DEPTH = 0.4                            # recessed text: 2 layers
RAISED = 0.4                                # raised text / ladder: 2 layers
PAD = (44.5, 15.5, 53.5, 27.0)              # ironed pad: the only surface at the top Z, ironing_type=topmost
PAD_Z = 1.8
TOP_Z = PAD_Z                               # card max thickness
LABEL_MARGIN_X = 1.3
LABEL_CAPS = [3.6, 3.0, 3.0]                # line 1 name, line 2 values, line 3 tol/date
LABEL_MIN_CAP = 2.6                         # 0.19 x cap = 0.5 mm stroke, the classic-wall floor
LABEL_MARGIN_Y = 1.2                        # plateau edge to the first line's real ink top
LABEL_ROW_CLEAR = 0.6                       # real ink-to-ink clearance between rows (descenders included): > one 0.42 wall
LABEL_MIN_CLEAR = 0.5                       # asserted on the final polygons
TRANS_X0, TRANS_W, TRANS_Y = 3.0, 5.0, (16.0, 28.0)
TRANS_FLOORS = [0.2, 0.4, 0.6, BODY_Z, 1.0]  # step 4 = the body, step 5 stands one layer proud
LADDER_X0 = 29.5
LADDER_RECESSED = [2.0, 2.5, 3.0]           # caps; the text is the size itself
LADDER_RAISED = [2.5, 3.5]
LADDER_Y_REC, LADDER_Y_RAI = 23.5, 17.0     # baselines
WINDOW = (55.0, 15.0, 72.0, 27.0)           # bridge + overhang window (through)
LIP = (54.0, 27.0, 73.0, 29.0)              # overhang root, Z 1.8
LIP_Z = 1.6
BAR_W, BAR_Y = 3.0, [15.5, 19.5]            # bridge bars: y0 of each, Z 0.6-1.0
BAR_Z = (BODY_Z - 0.4, BODY_Z)
TONGUE_STEPS = [0.2, 0.3, 0.4, 0.5]         # mm out per 0.2 layer = 45 / 56 / 63 / 68 deg
TONGUE_W, TONGUE_GAP, TONGUE_LAYERS = 2.0, 0.6, list(range(2, 9))   # layers 2..8 = 7 steps
TONGUE_CX = 63.5
COMB = (3.0, 3.0, 17.0, 12.0)
FINS = [0.4, 0.6, 0.8, 1.0, 1.2]
FIN_GAP = 2.0
HOLES = [1.0, 1.5, 2.0, 2.2, 2.3, 2.4]
HOLE_X0, HOLE_PITCH, HOLE_Y = 20.5, 3.4, 8.0
PINS = [0.8, 1.2, 1.6]
PIN_X0, PIN_PITCH, PIN_Z = 41.0, 2.5, (BODY_Z, BODY_Z + 0.6)
ZWIN = (48.0, 4.0, 58.0, 12.0)
ZFIN = (47.5, 7.5, 58.5, 8.5)
ZFIN_Z = 1.6
SLOT_CX, SLOT_DEPTH = [62.5, 69.5], 9.0
SLOT_NOMINAL = RIM_Z                        # a neighbour card's top edge (rim + label plateau) is 1.6 thick
SLOT_LABEL_CAP, SLOT_LABEL_Y = 2.6, 10.0
TRANS_LABEL_CAP, TRANS_LABEL_Y = 2.4, 13.2
TRACKING = 0.06                             # em, extra letter spacing (keeps recessed strokes apart)
SIMPLIFY_MM = 0.02                          # glyph outline simplification tolerance


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- filaments/<slug>.md frontmatter --------------------------------------------------
def read_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        sys.exit("%s: no frontmatter" % path)
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        sys.exit("%s: frontmatter is not valid YAML: %s" % (path, e))
    if not isinstance(fm, dict):
        sys.exit("%s: frontmatter is not a key: value mapping" % path)
    return {str(k): ("" if val is None else val) for k, val in fm.items()}


def parse_ironing(text):
    """'v1 pick ~25 mm/s / 25%' -> (25, 25); None when not calibrated."""
    if not text:
        return None
    m = re.search(r"(\d+)\s*mm/s\s*/\s*(\d+)\s*%", str(text))
    return (int(m.group(1)), int(m.group(2))) if m else None


# --- TrueType text -> shapely polygons ----------------------------------------------------
class _PolyPen(BasePen):
    def __init__(self, glyph_set):
        super().__init__(glyph_set)
        self.contours, self.cur = [], None

    def _moveTo(self, p):
        self.cur = [p]

    def _lineTo(self, p):
        self.cur.append(p)

    def _curveToOne(self, p1, p2, p3):
        p0 = self.cur[-1]
        for i in range(1, 9):
            t = i / 8
            u = 1 - t
            self.cur.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                             u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))

    def _closePath(self):
        if self.cur and len(self.cur) >= 3:
            self.contours.append(self.cur)
        self.cur = None

    def _endPath(self):
        self._closePath()


class Font:
    def __init__(self, path):
        self.path = path
        self.tt = TTFont(path)
        self.gs = self.tt.getGlyphSet()
        self.cmap = self.tt.getBestCmap()
        self.upem = self.tt["head"].unitsPerEm
        self.cache = {}
        os2 = self.tt.get("OS/2")
        self.cap = int(getattr(os2, "sCapHeight", 0) or 0) if os2 is not None else 0
        if self.cap <= 0:                       # OS/2 v1 fonts have no sCapHeight: measure 'H'
            poly, _ = self.glyph("H")
            self.cap = int(poly.bounds[3]) if poly is not None and not poly.is_empty else int(self.upem * 0.716)

    def glyph(self, ch):
        if ch not in self.cache:
            name = self.cmap.get(ord(ch)) or self.cmap[ord("?")]
            pen = _PolyPen(self.gs)
            g = self.gs[name]
            g.draw(pen)
            poly = None
            for c in pen.contours:
                p = sg.Polygon(c).buffer(0)
                if p.is_empty:
                    continue
                poly = p if poly is None else poly.symmetric_difference(p)   # even-odd (counters)
            self.cache[ch] = (poly, g.width)
        return self.cache[ch]

    def width(self, text, cap_mm):
        s = cap_mm / self.cap
        adv = 0.0
        for ch in text:
            adv += self.glyph(ch)[1] + TRACKING * self.upem
        return (adv - TRACKING * self.upem) * s

    def polygons(self, text, cap_mm, x0, baseline):
        """Text as a (Multi)Polygon in mm, left edge x0, baseline y. Returns (poly, width)."""
        s = cap_mm / self.cap
        x = 0.0
        parts = []
        for ch in text:
            poly, adv = self.glyph(ch)
            if poly is not None and not poly.is_empty:
                parts.append(shapely.affinity.translate(shapely.affinity.scale(poly, s, s, origin=(0, 0)),
                                                        x0 + x * s, baseline))
            x += adv + TRACKING * self.upem
        w = (x - TRACKING * self.upem) * s
        poly = shapely.ops.unary_union(parts) if parts else sg.Polygon()
        # 8 samples per curve is far finer than a 0.4 nozzle resolves; every vertex is a G-code
        # move (~40 ms each on the CC2), so simplify to 0.02 mm (3x fewer vertices, 0.3% area)
        return poly.simplify(SIMPLIFY_MM, preserve_topology=True), w

    def stroke_mm(self, cap_mm):
        """Stem width of 'l' at this cap height (Arial Bold: 0.19 x cap)."""
        poly, _ = self.glyph("l")
        b = poly.bounds
        return (b[2] - b[0]) * cap_mm / self.cap


def load_font(explicit=None):
    for p in ([explicit] if explicit else []) + FONT_CANDIDATES:
        if p and pathlib.Path(p).is_file():
            return Font(p)
    sys.exit("no TrueType font found; pass --font PATH")


# --- solids ---------------------------------------------------------------------------------
def prism(poly, z0, z1):
    """Extrude a shapely (Multi)Polygon between z0 and z1 -> list of trimesh meshes."""
    out = []
    geoms = poly.geoms if hasattr(poly, "geoms") else [poly]
    for g in geoms:
        if g.is_empty or g.area < 1e-6:
            continue
        m = trimesh.creation.extrude_polygon(g, z1 - z0)
        m.apply_translation((0, 0, z0))
        out.append(m)
    return out


def rbox(x0, y0, x1, y1, r=0.0):
    b = sg.box(x0, y0, x1, y1)
    if r > 0:
        b = sg.box(x0 + r, y0 + r, x1 - r, y1 - r).buffer(r, quad_segs=12)
    return b


def circle(cx, cy, d):
    return sg.Point(cx, cy).buffer(d / 2, quad_segs=24)


def boolean(op, meshes):
    meshes = [m for m in meshes if m is not None and len(m.faces)]
    if not meshes:
        return None
    if len(meshes) == 1:
        return meshes[0]
    return getattr(trimesh.boolean, op)(meshes, engine="manifold")


# --- the card -------------------------------------------------------------------------------
def label_lines(v):
    """Three label lines from the frontmatter values (missing values are left out)."""
    l1 = v["label"]
    if v.get("colour") and v["colour"].lower() not in l1.lower():
        l1 = l1 + " " + v["colour"]
    parts = []
    if v.get("temp") is not None:
        parts.append("%dC" % v["temp"])
    if v.get("flow") is not None:
        parts.append("F%.2f" % v["flow"])
    if v.get("retraction") is not None:
        parts.append("R%g" % v["retraction"])
    if v.get("ironing"):
        parts.append("IR%d/%d" % v["ironing"])
    l2 = " ".join(parts)
    l3 = []
    if v.get("tolerance") is not None:
        l3.append("TOL %g" % v["tolerance"])
    l3.append(v["date"])
    return [l1, l2, " ".join(l3)]


def fit_line(font, text, cap, max_w):
    """Shrink the cap height until the line fits (down to LABEL_MIN_CAP), then truncate."""
    while font.width(text, cap) > max_w and cap > LABEL_MIN_CAP + 1e-9:
        cap = round(max(LABEL_MIN_CAP, cap - 0.1), 2)
    while font.width(text, cap) > max_w and len(text) > 3:
        text = text[:-2].rstrip() + "~"
    return text, cap


def layout(v, font):
    """Build the card mesh. Returns (mesh, manifest)."""
    man = {"card": {"w": W, "h": H, "corner_r": CORNER_R, "rim_w": RIM_W, "rim_z": RIM_Z,
                    "body_z": BODY_Z, "plateau_z": PLATEAU_Z, "max_z": TOP_Z},
           "checks": [], "texts": []}
    p1, n1, p2 = [], [], []      # stage 1 positives, cuts, stage 2 positives (inside cuts)

    outline = rbox(0, 0, W, H, CORNER_R)
    inner = rbox(RIM_W, RIM_W, W - RIM_W, H - RIM_W, max(CORNER_R - RIM_W, 0.5))
    p1 += prism(outline, 0, BODY_Z)
    p1 += prism(outline.difference(inner), 0, RIM_Z)

    # 1 label plateau + recessed text
    plat = rbox(*PLATEAU, r=1.0)
    p1 += prism(plat, 0, PLATEAU_Z)
    lines = label_lines(v)
    max_w = (PLATEAU[2] - PLATEAU[0]) - 2 * LABEL_MARGIN_X
    caps = list(LABEL_CAPS)
    while True:
        # rows are stacked by their REAL ink bounds (descenders of g/j/p/y included), not by cap
        # height: the gap between rows must survive as a wall of the plateau top
        texts, polys = [], []
        top = PLATEAU[3] - LABEL_MARGIN_Y
        for i, (text, cap) in enumerate(zip(lines, caps)):
            text, cap = fit_line(font, text, cap, max_w)
            probe, w = font.polygons(text, cap, PLATEAU[0] + LABEL_MARGIN_X, 0.0)   # baseline 0 -> bounds = ascent/descent
            asc, desc = probe.bounds[3], -probe.bounds[1]
            base = top - asc
            polys.append(shapely.affinity.translate(probe, 0, base))
            texts.append({"line": i + 1, "text": text, "cap_mm": cap, "width_mm": round(w, 2),
                          "stroke_mm": round(font.stroke_mm(cap), 2), "baseline_y": round(base, 3),
                          "ink_y": [round(base - desc, 3), round(top, 3)],
                          "style": "recessed %.1f mm into the plateau top" % TEXT_DEPTH})
            top = base - desc - LABEL_ROW_CLEAR
        ink_bottom = top + LABEL_ROW_CLEAR
        if ink_bottom >= PLATEAU[1] + 0.8 or min(caps) <= LABEL_MIN_CAP + 1e-9:
            break
        caps = [round(max(LABEL_MIN_CAP, c - 0.1), 2) for c in caps]      # too tall: shrink every row and retry
    assert ink_bottom >= PLATEAU[1] + 0.8, ("label lines overflow the plateau", ink_bottom)
    clearances = [round(float(polys[i].distance(polys[i + 1])), 3) for i in range(len(polys) - 1)]
    assert all(c >= LABEL_MIN_CLEAR for c in clearances), ("label rows too close", clearances)
    for poly in polys:
        n1 += prism(poly, PLATEAU_Z - TEXT_DEPTH, PLATEAU_Z + 1)
    man["label"] = {"plateau": PLATEAU, "top_z": PLATEAU_Z, "recess_z": PLATEAU_Z - TEXT_DEPTH, "ironed": False,
                    "row_clearance_mm": clearances, "lines": texts}
    man["checks"].append({"n": 1, "name": "label", "box": PLATEAU,
                          "what": "recessed text, 0.4 deep, in the plateau's plain monotonic top (Z %g, not ironed)" % PLATEAU_Z})

    # 2 not-ironed pad
    p1 += prism(rbox(*PAD, r=1.0), 0, PAD_Z)
    man["checks"].append({"n": 2, "name": "top surface", "box": PAD,
                          "what": "the only surface at the top Z (%g): ironed with the filament's values; compare with the plateau" % PAD_Z})

    # 3 translucency ladder
    steps = []
    for k, floor in enumerate(TRANS_FLOORS):
        x0 = TRANS_X0 + k * TRANS_W
        box = (x0, TRANS_Y[0], x0 + TRANS_W, TRANS_Y[1])
        if floor < BODY_Z:
            n1 += prism(sg.box(*box), floor, BODY_Z + 1)
        elif floor > BODY_Z:
            p1 += prism(sg.box(*box), 0, floor)
        steps.append({"layers": k + 1, "floor_mm": floor, "box": box})
        text = str(k + 1)
        w = font.width(text, TRANS_LABEL_CAP)
        poly, _ = font.polygons(text, TRANS_LABEL_CAP, x0 + TRANS_W / 2 - w / 2, TRANS_LABEL_Y)
        n1 += prism(poly, BODY_Z - TEXT_DEPTH, BODY_Z + 1)
    man["checks"].append({"n": 3, "name": "translucency", "steps": steps,
                          "box": (TRANS_X0, TRANS_Y[0], TRANS_X0 + 5 * TRANS_W, TRANS_Y[1]),
                          "what": "1-5 layers thick (step 4 = the body, step 5 stands one layer proud), labelled with the layer count"})

    # 4 text ladder
    ladder = []
    x = LADDER_X0
    for cap in LADDER_RECESSED:
        text = ("%g" % cap)
        poly, w = font.polygons(text, cap, x, LADDER_Y_REC)
        n1 += prism(poly, BODY_Z - TEXT_DEPTH, BODY_Z + 1)
        ladder.append({"style": "recessed", "cap_mm": cap, "x": round(x, 2), "width": round(w, 2),
                       "stroke_mm": round(font.stroke_mm(cap), 2)})
        x += w + 1.2
    x = LADDER_X0
    for cap in LADDER_RAISED:
        text = ("%g" % cap)
        poly, w = font.polygons(text, cap, x, LADDER_Y_RAI)
        p2 += prism(poly, BODY_Z, BODY_Z + RAISED)
        ladder.append({"style": "raised", "cap_mm": cap, "x": round(x, 2), "width": round(w, 2),
                       "stroke_mm": round(font.stroke_mm(cap), 2)})
        x += w + 1.2
    man["checks"].append({"n": 4, "name": "text ladder", "items": ladder,
                          "box": (LADDER_X0 - 0.5, LADDER_Y_RAI - 0.8, LADDER_X0 + 14.0, LADDER_Y_REC + 3.4),
                          "what": "each digit is its own cap height: top row recessed, bottom row raised"})

    # 5 + 6 bridge bars and overhang tongues in one window, lip on top
    n1 += prism(sg.box(*WINDOW), -1, TOP_Z + 1)
    p1 += prism(sg.box(*LIP), 0, LIP_Z)
    bars = []
    for y0 in BAR_Y:
        p2 += prism(sg.box(WINDOW[0] - 0.5, y0, WINDOW[2] + 0.5, y0 + BAR_W), BAR_Z[0], BAR_Z[1])
        bars.append({"y0": y0, "y1": y0 + BAR_W, "span_mm": WINDOW[2] - WINDOW[0], "z": BAR_Z})
    man["checks"].append({"n": 5, "name": "bridge", "bars": bars, "box": (WINDOW[0], WINDOW[1], WINDOW[2], BAR_Y[-1] + BAR_W),
                          "what": "two 3 mm bars over a %g mm window, 2 layers at Z %g-%g" % (WINDOW[2] - WINDOW[0], BAR_Z[0], BAR_Z[1])})
    tongues = []
    total = len(TONGUE_STEPS) * TONGUE_W + (len(TONGUE_STEPS) - 1) * TONGUE_GAP
    tx = TONGUE_CX - total / 2
    for s in TONGUE_STEPS:
        for L in TONGUE_LAYERS:
            reach = s * (L - 1)
            p2 += prism(sg.box(tx, WINDOW[3] - reach, tx + TONGUE_W, WINDOW[3] + 0.5), (L - 1) * LAYER, L * LAYER)
        tongues.append({"step_mm_per_layer": s, "angle_deg": round(math.degrees(math.atan2(s, LAYER)), 1),
                        "x0": round(tx, 2), "x1": round(tx + TONGUE_W, 2),
                        "reach_mm": round(s * (TONGUE_LAYERS[-1] - 1), 2)})
        tx += TONGUE_W + TONGUE_GAP
    man["checks"].append({"n": 6, "name": "overhang", "tongues": tongues, "lip": LIP,
                          "box": (tongues[0]["x0"], WINDOW[3] - 3.6, tongues[-1]["x1"], WINDOW[3]),
                          "what": "tongues step out per layer from the lip: 45/56/63/68 deg, read the underside"})

    # 7 thin-wall comb
    n1 += prism(sg.box(*COMB), -1, TOP_Z + 1)
    fins = []
    x = COMB[0] + 1.0
    for wdt in FINS:
        p2 += prism(sg.box(x, COMB[1] - 0.5, x + wdt, COMB[3] + 0.5), 0, BODY_Z)
        fins.append({"width_mm": wdt, "x0": round(x, 2)})
        x += wdt + FIN_GAP
    assert x - FIN_GAP + 1.0 <= COMB[2] + 1e-6, ("comb overflow", x)
    man["checks"].append({"n": 7, "name": "thin walls", "fins": fins, "box": COMB,
                          "what": "fins 0.4-1.2 mm, 0.8 tall, thinnest on the left"})

    # 8 holes, 9 pins
    holes = []
    for i, d in enumerate(HOLES):
        cx = HOLE_X0 + i * HOLE_PITCH
        n1 += prism(circle(cx, HOLE_Y, d), -1, TOP_Z + 1)
        holes.append({"dia_mm": d, "x": cx, "y": HOLE_Y})
    man["checks"].append({"n": 8, "name": "small holes", "holes": holes,
                          "box": (HOLE_X0 - 1.5, HOLE_Y - 1.5, HOLE_X0 + (len(HOLES) - 1) * HOLE_PITCH + 1.5, HOLE_Y + 1.5),
                          "what": "1.0-2.4 mm through holes for a 1.75 filament pin; 2.2 friction, 2.3 free on the CC2"})
    pins = []
    for i, d in enumerate(PINS):
        cx = PIN_X0 + i * PIN_PITCH
        p2 += prism(circle(cx, HOLE_Y, d), PIN_Z[0], PIN_Z[1])
        pins.append({"dia_mm": d, "x": cx, "y": HOLE_Y, "z": PIN_Z})
    man["checks"].append({"n": 9, "name": "pins", "pins": pins,
                          "box": (PIN_X0 - 1.2, HOLE_Y - 1.5, PIN_X0 + (len(PINS) - 1) * PIN_PITCH + 1.2, HOLE_Y + 1.5),
                          "what": "0.8 / 1.2 / 1.6 mm posts, 0.6 mm tall"})

    # 10 wall / Z fin
    n1 += prism(sg.box(*ZWIN), -1, TOP_Z + 1)
    p2 += prism(sg.box(*ZFIN), 0, ZFIN_Z)
    man["checks"].append({"n": 10, "name": "wall / layers", "box": ZWIN, "fin": ZFIN, "fin_z": ZFIN_Z,
                          "what": "1.0 mm fin, %g mm tall (%d layers): local layer quality with light behind it (too short for periodic banding)"
                          % (ZFIN_Z, int(round(ZFIN_Z / LAYER)))})

    # 11 tolerance notches
    tol = v["tolerance"] if v.get("tolerance") is not None else 0.2
    slots = []
    for cx, gap in zip(SLOT_CX, [tol, round(tol - 0.1, 3)]):
        wdt = round(SLOT_NOMINAL + 2 * gap, 3)
        n1 += prism(sg.box(cx - wdt / 2, -1, cx + wdt / 2, SLOT_DEPTH), -1, TOP_Z + 1)
        text = "%g" % gap
        w = font.width(text, SLOT_LABEL_CAP)
        poly, _ = font.polygons(text, SLOT_LABEL_CAP, cx - w / 2, SLOT_LABEL_Y)
        n1 += prism(poly, BODY_Z - TEXT_DEPTH, BODY_Z + 1)
        slots.append({"x": cx, "width_mm": wdt, "gap_per_side_mm": gap, "depth_mm": SLOT_DEPTH, "label": text})
    man["checks"].append({"n": 11, "name": "tolerance", "slots": slots, "nominal_mm": SLOT_NOMINAL,
                          "tolerance_from_frontmatter": v.get("tolerance") is not None,
                          "box": (SLOT_CX[0] - 3.0, 0, SLOT_CX[1] + 3.0, SLOT_LABEL_Y + SLOT_LABEL_CAP + 0.3),
                          "what": "comparison notches for another card's %g mm top edge: label = gap per side (calibrated value, and 0.1 tighter); note which slides, measure before calling it pass/fail" % SLOT_NOMINAL})

    # booleans: (P1 - N1) + P2
    base = boolean("union", p1)
    cuts = boolean("union", n1)
    base = boolean("difference", [base, cuts])
    mesh = boolean("union", [base] + p2)
    mesh.merge_vertices()
    mesh.fix_normals()
    assert mesh.is_watertight, "card mesh is not watertight"
    assert mesh.is_volume, "card mesh is not a volume"
    man["mesh"] = {"triangles": int(len(mesh.faces)), "volume_mm3": round(float(mesh.volume), 1),
                   "grams_at_1.24": round(float(mesh.volume) * 1.24 / 1000, 2),
                   "bounds": [[round(float(x), 3) for x in b] for b in mesh.bounds.tolist()]}
    return mesh, man


# --- slicing ---------------------------------------------------------------------------------
def slice_card(stl, v, out_dir, extra):
    cmd = [sys.executable, str(SLICER), str(stl), "--out", str(out_dir),
           "--filament", v["slicer_key"], "--layer", "0.20", "--no-brim", "--no-arrange",
           "--proc", "ironing_type=topmost"]
    if v.get("temp") is not None:
        cmd += ["--temp", str(v["temp"])]
    if v.get("flow") is not None:
        cmd += ["--flow", "%.2f" % v["flow"]]
    if v.get("retraction") is not None:
        cmd += ["--fil", "filament_retraction_length=%g" % v["retraction"]]
    if v.get("ironing"):
        cmd += ["--proc", "ironing_speed=%d" % v["ironing"][0], "--proc", "ironing_flow=%d%%" % v["ironing"][1]]
    cmd += extra
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=False, cwd=str(REPO))
    gcodes = list(pathlib.Path(out_dir).glob("*.gcode"))
    assert len(gcodes) == 1, "expected one G-code, got %r (see %s/slice.log)" % (gcodes, out_dir)
    return gcodes[0], cmd


_PARAM = re.compile(r"\b([XYZEF])(-?\d*\.?\d+)")


def _params(line):
    return {k: float(val) for k, val in _PARAM.findall(line.split(";", 1)[0])}


def verify(text, man, v):
    """Static checks on the sliced G-code. Raises on anything wrong."""
    hdr = lambda key: re.search(r"^; %s = (.*)$" % re.escape(key), text, re.M)
    m600 = len(re.findall(r"^M600\b", text, re.M))
    assert m600 == 0, "M600 present (CC2 hangs on it)"
    # every tool-selection form: bare Tn lines and M6211 with T in any argument position
    tools = set(int(t) for t in re.findall(r"^T(\d+)\b", text, re.M))
    tools |= set(int(t) for t in re.findall(r"^M6211\b[^;\n]*?\bT(\d+)\b", text, re.M))
    assert tools == {0}, ("tools other than T0 (CANVAS slot 1) selected", sorted(tools))
    assert re.search(r"^M6211\b[^;\n]*?\bT0\b", text, re.M), "CANVAS slot 1 selection missing"
    assert not re.search(r"^(G91|M82)\b", text, re.M), "relative XYZ / absolute E not supported by this check"
    assert hdr("layer_height").group(1).strip() == "0.2"
    assert hdr("brim_type").group(1).strip() == "no_brim"
    assert hdr("ironing_type").group(1).strip() == "topmost", hdr("ironing_type").group(0)
    assert hdr("enable_support").group(1).strip() == "0"
    temp = int(float(hdr("nozzle_temperature").group(1).split(",")[0]))
    flow = float(hdr("filament_flow_ratio").group(1).split(",")[0])
    if v.get("temp") is not None:
        assert temp == v["temp"], (temp, v["temp"])
        assert re.search(r"^M109 S%d\b" % temp, text, re.M) or re.search(r"^M104 S%d\b" % temp, text, re.M)
    if v.get("flow") is not None:
        assert abs(flow - v["flow"]) < 1e-6, (flow, v["flow"])
    ret_eff = None
    if v.get("retraction") is not None:
        m = hdr("filament_retraction_length")
        assert m and abs(float(m.group(1).split(",")[0]) - v["retraction"]) < 1e-6, m.group(0) if m else "no filament_retraction_length"
        ret_eff = v["retraction"]
    ironing = {"speed": hdr("ironing_speed").group(1).strip(), "flow": hdr("ironing_flow").group(1).strip(),
               "spacing": hdr("ironing_spacing").group(1).strip()}
    if v.get("ironing"):
        assert int(float(ironing["speed"])) == v["ironing"][0], ironing
        assert int(float(ironing["flow"].rstrip("%"))) == v["ironing"][1], ironing

    start = text.index(";LAYER:1")
    end = text.index("CC2_END_GCODE") if "CC2_END_GCODE" in text else len(text)
    body = text[start:end].splitlines()
    # Z is tracked from the motion commands themselves (z-hops included), never inferred from ;LAYER:
    layer_marks = 0
    z = None
    for line in text[:start].splitlines():               # Z reached in the start G-code
        if line.startswith(("G0", "G1")):
            z = _params(line).get("Z", z)
    kind = None
    iron_z, iron_len, iron_moves = set(), 0.0, 0
    extrude_z = set()
    x = y = None
    bounds = [1e9, -1e9, 1e9, -1e9]
    e_total = 0.0
    types = {}
    for line in body:
        if line.startswith(";LAYER:"):
            layer_marks += 1
            continue
        if line.startswith(";TYPE:"):
            kind = line[6:].strip()
            continue
        if not line.startswith(("G0", "G1")):
            continue
        p = _params(line)
        xp, yp = x, y
        if "X" in p:
            x = p["X"]
        if "Y" in p:
            y = p["Y"]
        if "Z" in p:
            z = p["Z"]
        e = p.get("E", 0.0)
        if e > 0 and ("X" in p or "Y" in p):
            assert z is not None, "extrusion before any Z move"
            zr = round(z, 3)
            extrude_z.add(zr)
            e_total += e
            types[kind] = types.get(kind, 0) + 1
            bounds = [min(bounds[0], x), max(bounds[1], x), min(bounds[2], y), max(bounds[3], y)]
            if kind == "Ironing":
                iron_z.add(zr)
                iron_moves += 1
                if xp is not None and yp is not None:
                    iron_len += math.hypot(x - xp, y - yp)
    layers = len(extrude_z)
    assert layers == int(round(TOP_Z / LAYER)), ("layers with extrusion", sorted(extrude_z))
    assert layer_marks == layers, ("layer markers vs extrusion layers", layer_marks, layers)
    assert abs(max(extrude_z) - TOP_Z) < 1e-6, ("top extrusion Z", max(extrude_z))
    assert all(abs(zz / LAYER - round(zz / LAYER)) < 1e-6 for zz in extrude_z), ("off-grid Z", sorted(extrude_z))
    assert iron_z == {TOP_Z}, ("ironing at the wrong Z", sorted(iron_z))
    assert iron_moves > 100, ("too few ironing moves", iron_moves)
    assert "Bridge" in types or "Internal Bridge" in types or any("ridge" in k for k in types), ("no bridge extrusions", types)
    assert 0 < bounds[0] < bounds[1] < 256 and 0 < bounds[2] < bounds[3] < 256, bounds
    pw, ph = bounds[1] - bounds[0], bounds[3] - bounds[2]
    assert abs(pw - (W - 0.42)) < 0.6 and abs(ph - (H - 0.42)) < 0.6, ("printed size", pw, ph)
    density = float(hdr("filament_density").group(1).split(",")[0])
    grams = e_total * math.pi * (FIL_DIAMETER / 2) ** 2 * density / 1000
    est = {}
    for key in ("estimated printing time (normal mode)", "total filament used [g]", "total layers count",
                "total filament length [mm]"):
        m = re.search(r"^; %s = (.*)$" % re.escape(key), text, re.M)
        if m:
            est[key] = m.group(1).strip()
    minutes = 0
    m = re.search(r"(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?$", est.get("estimated printing time (normal mode)", "").strip())
    if m:
        minutes = int(m.group(1) or 0) * 60 + int(m.group(2) or 0) + int(m.group(3) or 0) / 60
    return {"nozzle_temp_c": temp, "flow": flow, "retraction_mm_effective": ret_eff, "ironing": ironing,
            "ironing_only_at_z": sorted(iron_z), "ironing_moves": iron_moves, "ironing_path_mm": round(iron_len),
            "layers": layers, "extrusion_z_mm": sorted(extrude_z), "extrusion_moves_by_type": types,
            "label_row_clearance_mm": man["label"]["row_clearance_mm"],
            "printed_bounds_xy_mm": [[round(bounds[0], 2), round(bounds[1], 2)], [round(bounds[2], 2), round(bounds[3], 2)]],
            "printed_size_mm": [round(pw, 2), round(ph, 2)],
            "grams_from_e": round(grams, 2), "slicer_estimate": est, "estimated_minutes": round(minutes, 1),
            "m600_count": m600, "tools": ["T%d" % t for t in sorted(tools)]}


# --- preview -----------------------------------------------------------------------------------
def preview(mesh, man, shift, path, font_path):
    from PIL import Image, ImageDraw, ImageFont
    S = 10                       # px per mm
    OX, OY = 40, 70
    cw, ch = int(W * S), int(H * S)
    LEG_X = OX + cw + 40
    IMG_W, IMG_H = LEG_X + 640, OY + ch + 40
    BG = (14, 16, 20)
    img = Image.new("RGB", (IMG_W, IMG_H), BG)
    d = ImageDraw.Draw(img)

    def fnt(sz):
        for p in (font_path, "C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/arial.ttf"):
            try:
                return ImageFont.truetype(p, sz)
            except OSError:
                pass
        return ImageFont.load_default()

    # heightmap: paint upward-facing triangles, low to high, grey by Z
    v = mesh.vertices - np.array([shift[0], shift[1], 0.0])
    f = mesh.faces
    n = mesh.face_normals
    up = np.where(n[:, 2] > 0.5)[0]
    zc = v[f[up]][:, :, 2].mean(axis=1)
    order = up[np.argsort(zc)]
    zmax = TOP_Z
    for fi in order:
        tri = v[f[fi]]
        zz = float(tri[:, 2].mean())
        g = int(60 + 165 * (zz / zmax))
        col = (g, g, g)
        pts = [(OX + p[0] * S, OY + (H - p[1]) * S) for p in tri]
        d.polygon(pts, fill=col)
    d.rectangle([OX - 1, OY - 1, OX + cw, OY + ch], outline=(70, 76, 90))

    # callouts
    COL = (255, 196, 90)
    for c in man["checks"]:
        b = c["box"]
        x0, y0 = OX + b[0] * S, OY + (H - b[3]) * S
        x1, y1 = OX + b[2] * S, OY + (H - b[1]) * S
        d.rectangle([x0, y0, x1, y1], outline=COL, width=1)
        d.rectangle([x0, y0, x0 + 18, y0 + 16], fill=COL)
        d.text((x0 + 9, y0 + 8), str(c["n"]), fill=(20, 20, 20), font=fnt(12), anchor="mm")

    d.text((OX, 20), "CC2 swatch card: %s" % man["label"]["lines"][0]["text"], fill=(235, 235, 235), font=fnt(24), anchor="lm")
    d.text((OX, 48), "top view (heightmap: brighter = higher; black = through). Front of the printer is the bottom edge. "
           "%g x %g x %g mm" % (W, H, TOP_Z), fill=(150, 160, 170), font=fnt(13), anchor="lm")
    ly = OY
    d.text((LEG_X, ly), "Key", fill=(235, 235, 235), font=fnt(18), anchor="lm")
    ly += 28
    for c in man["checks"]:
        d.rectangle([LEG_X, ly - 8, LEG_X + 18, ly + 8], fill=COL)
        d.text((LEG_X + 9, ly), str(c["n"]), fill=(20, 20, 20), font=fnt(12), anchor="mm")
        d.text((LEG_X + 26, ly), c["name"], fill=COL, font=fnt(14), anchor="lm")
        d.text((LEG_X + 26, ly + 16), c["what"], fill=(170, 178, 190), font=fnt(11), anchor="lm")
        ly += 40
    ly += 6
    for t in man["label"]["lines"]:
        d.text((LEG_X, ly), "label %d: \"%s\"  cap %.1f mm, stroke %.2f mm" % (t["line"], t["text"], t["cap_mm"], t["stroke_mm"]),
               fill=(170, 178, 190), font=fnt(11), anchor="lm")
        ly += 16
    img.save(path)
    return img.size


# --- main --------------------------------------------------------------------------------------
def load_values(a):
    md = FILAMENTS / (a.filament + ".md") if not a.filament.endswith(".md") else pathlib.Path(a.filament)
    if not md.is_file():
        sys.exit("no such filament file: %s" % md)
    fm = read_frontmatter(md)
    slug = md.stem

    def num(key, override, cast=float):
        """Frontmatter number; an empty value means 'not calibrated' (None), anything else that is
        not a number (e.g. '210C', 'tbd') is an error, never a silent fallback to stock."""
        if override is not None:
            return cast(override)
        s = fm.get(key, "")
        if s == "" or s is None or (isinstance(s, str) and not s.strip()):
            return None
        try:
            f = float(s)
        except (TypeError, ValueError):
            sys.exit("%s: '%s: %r' is not a number; fix the frontmatter or pass the CLI override" % (md, key, s))
        if cast is int and f != int(f):
            sys.exit("%s: '%s: %r' must be a whole number" % (md, key, s))
        return cast(f)

    md = md.resolve()
    v = {"slug": slug, "md": str(md.relative_to(REPO) if REPO in md.parents else md).replace("\\", "/"),
         "slicer_key": a.slicer_key or str(fm.get("slicer_key") or ""),
         "temp": num("temp", a.temp, int), "flow": num("flow", a.flow),
         "retraction": num("retraction_mm", a.retraction), "tolerance": num("tolerance_free_at_mm", a.tolerance),
         "ironing": parse_ironing(a.ironing or fm.get("ironing", "")),
         "colour": a.colour or str(fm.get("colour") or fm.get("color") or ""),
         "label": a.line1 or str(fm.get("swatch_label") or fm.get("name") or slug).replace('"', ""),
         "material": str(fm.get("material", "")),
         "date": a.date or dt.date.today().isoformat()}
    if not v["slicer_key"]:
        sys.exit("%s: slicer_key is empty (not in slice_cc2.py yet); pass --slicer-key pla|plaplus|plapro|asa|abs" % md)
    # missing temp/flow: use the stock filament preset (and say so on the card)
    spec = importlib.util.spec_from_file_location("slice_cc2", SLICER)
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)
    if v["slicer_key"] not in sc.FILAMENT:
        sys.exit("slicer_key %r is not one of %s" % (v["slicer_key"], sorted(sc.FILAMENT)))
    stock = sc.resolve_leaf(sc.FILAMENT[v["slicer_key"]], "filament")
    v["stock_used"] = []
    if v["temp"] is None:
        v["temp"] = int(float(stock["nozzle_temperature"][0]))
        v["stock_used"].append("temp")
    if v["flow"] is None:
        v["flow"] = float(stock["filament_flow_ratio"][0])
        v["stock_used"].append("flow")
    return v


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("filament", help="filaments/<slug>.md slug (or a path to the .md)")
    ap.add_argument("--colour", help="colour word for line 1 (frontmatter 'colour:' if present)")
    ap.add_argument("--line1", help="line 1 text (default: frontmatter 'swatch_label:', else 'name:')")
    ap.add_argument("--temp", type=int, help="override nozzle temp C")
    ap.add_argument("--flow", type=float, help="override flow ratio")
    ap.add_argument("--retraction", type=float, help="override retraction mm")
    ap.add_argument("--tolerance", type=float, help="override tolerance gap per side mm (notch sizing + label)")
    ap.add_argument("--ironing", help="override ironing as 'SPEED mm/s / FLOW %%' (e.g. '25 mm/s / 25%%')")
    ap.add_argument("--slicer-key", help="slice_cc2.py --filament key when the frontmatter has none")
    ap.add_argument("--date", help="date on the card (default today, ISO)")
    ap.add_argument("--font", help="TrueType font file (default Arial Bold)")
    ap.add_argument("--no-slice", action="store_true", help="geometry + preview only")
    ap.add_argument("--raw", help="dev: reuse this already-sliced G-code instead of slicing")
    ap.add_argument("--slicer-arg", action="append", default=[], help="extra slice_cc2.py argument (repeatable)")
    a = ap.parse_args()

    v = load_values(a)
    font = load_font(a.font)
    out = CARDS / v["slug"]
    out.mkdir(parents=True, exist_ok=True)

    mesh, man = layout(v, font)
    shift = (128 - W / 2, 128 - H / 2)
    mesh.apply_translation((shift[0], shift[1], 0))
    stl = out / "card.stl"
    mesh.export(stl)
    man["values"] = {k: v[k] for k in ("slug", "md", "slicer_key", "temp", "flow", "retraction", "tolerance",
                                       "ironing", "colour", "label", "material", "date", "stock_used")}
    man["font"] = font.path
    man["bed_shift_mm"] = shift
    (out / "manifest.json").write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8")
    print("card: %s triangles, %.1f mm3 (~%.2f g), lines: %s" % (
        man["mesh"]["triangles"], man["mesh"]["volume_mm3"], man["mesh"]["grams_at_1.24"],
        [t["text"] for t in man["label"]["lines"]]), flush=True)
    png = out / "preview.png"
    print("preview:", png, preview(mesh, man, shift, png, font.path), flush=True)
    if a.no_slice:
        return

    scratch = pathlib.Path(tempfile.mkdtemp(prefix="cc2-swatch-"))
    if a.raw:
        raw, cmd = pathlib.Path(a.raw), ["(reused %s)" % a.raw]
    else:
        raw, cmd = slice_card(stl, v, scratch, a.slicer_arg)
    text = raw.read_text(encoding="utf-8", errors="ignore")
    report = verify(text, man, v)
    gcode = out / ("CC2_Swatch_%s.gcode" % v["slug"])
    gcode.write_text(text, encoding="utf-8")
    shown = [pathlib.Path(c).name if os.path.isabs(c) else c for c in cmd[2:]]      # no machine paths
    shown = [c for i, c in enumerate(shown) if c != "--out" and (i == 0 or shown[i - 1] != "--out")]
    verification = {
        "slicer": "ElegooSlicer via tools/slice_cc2.py " + " ".join(shown) if not a.raw else cmd[0],
        "command": "python filaments/swatch/build_swatch.py " + " ".join(sys.argv[1:]),
        "filament_md": v["md"], "values_on_card": man["values"],
        "card_mm": [W, H, TOP_Z], "mesh": man["mesh"],
        "stl": stl.name, "stl_sha256": sha256(stl), "gcode": gcode.name, "gcode_sha256": sha256(gcode),
        "validation": report, "raw_gcode_kept_at": str(scratch),
        "budget": {"grams_target": "3-6", "minutes_target": "< 20",
                   "grams_ok": 3 <= float(report["slicer_estimate"].get("total filament used [g]", 0)) <= 6.5,
                   "minutes_ok": report["estimated_minutes"] <= 20},
        "physical_print_tested": False}
    (out / "verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("Validated G-code:", gcode)


if __name__ == "__main__":
    main()
