#!/usr/bin/env python3
"""Draw card_preview.png: the labelled map of the CC2 calibration card.

Geometry and values come from build_card.layout(), so the picture always
matches the plate. Run: python calibration/card/make_preview.py [--temp 210 --flow 0.98]
"""
import argparse
import importlib.util
import math
import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("b", ROOT / "build_card.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

ap = argparse.ArgumentParser()
ap.add_argument("--temp", type=int, default=210)
ap.add_argument("--flow", type=float, default=0.98)
ap.add_argument("--out", default=str(ROOT / "card_preview.png"))
a = ap.parse_args()
_, _, man = b.layout(a.temp, a.flow, tower=True)

S = 7.0                      # px per mm
OX, OY = 60, 130             # plate origin on the image
CW, CD = man["card"]["w"], man["card"]["d"]
PW, PD = man["plate"]["x1"], man["plate"]["y1"]      # the whole plate: card + gap + tower
SIDE_X = OX + int(PW * S) + 70   # tower elevation panel
W = SIDE_X + 430
H = OY + int(PD * S) + 330
BG, INK, DIM = (15, 17, 21), (232, 232, 232), (150, 160, 170)
SHEET, FEAT, EDGE = (38, 42, 52), (70, 78, 96), (110, 120, 140)
FLOW_C, RET_C, TOL_C, TEMP_C = (120, 230, 200), (255, 215, 120), (200, 160, 255), (255, 140, 110)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)


def font(sz):
    for p in ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except OSError:
            pass
    return ImageFont.load_default()


def P(x, y):
    """plate mm -> image px (Y up on the bed = towards the top of the image)."""
    return OX + x * S, OY + (PD - y) * S


def rect(x0, y0, x1, y1, fill, outline=None, w=1):
    ax, ay = P(x0, y1)
    bx, by = P(x1, y0)
    d.rectangle([ax, ay, bx, by], fill=fill, outline=outline, width=w)


def text(x, y, t, fill, sz, anchor="mm"):
    d.text((x, y), t, fill=fill, font=font(sz), anchor=anchor)


# title
text(OX, 34, "CC2 calibration card", INK, 30, "lm")
text(OX, 68, "one print, two objects in sequence: the flat card (flow pads, retraction pairs, tolerance holes) "
     "first, then the temperature tower alone (card printed at T%d, flow %s)" % (a.temp, b.fmt_flow(a.flow)), DIM, 14, "lm")
text(OX, 90, "top view, as it sits on the bed: front of the printer is at the BOTTOM of this picture", DIM, 13, "lm")

# object 1: the card outline + sheet (strips, plates)
rect(0, 0, CW, CD, (24, 27, 33), (60, 66, 78), 2)
for sy in man["card"]["strips_y"]:
    rect(0, sy, CW, sy + man["card"]["strip_d"], SHEET)
info = man["info"]
rect(info["x0"], info["y0"], info["x1"], info["y1"], SHEET)
for h in man["holes"]:
    rect(h["x"] - b.HOLE_PLATE_W / 2, 0, h["x"] + b.HOLE_PLATE_W / 2, b.RAIL_Y0, SHEET)

# row A: rail with hex holes
r = man["card"]["rail"]
rect(r["x0"], r["y0"], r["x1"], r["y1"], FEAT, EDGE)
for h in man["holes"]:
    pts = [P(x, y) for x, y in b._hex(h["x"], h["y"], h["across_flats_mm"])]
    d.polygon(pts, fill=BG, outline=TOL_C)
    text(*P(h["x"], 3.0), h["label"], TOL_C, 15)
t = man["tester"]
pts = [P(x, y) for x, y in b._hex(t["x"], t["y"], t["across_flats_mm"])]
d.polygon(pts, fill=FEAT, outline=TOL_C, width=2)
tx, ty = P(t["x"], t["y"])
text(tx, ty, "6.0", TOL_C, 12)
text(tx, ty + 34, "loose tester", TOL_C, 12)
text(*P(info["x0"] + (info["x1"] - info["x0"]) / 2, 3.0), info["text"], DIM, 15)

# row B: flow pads
for p in man["pads"]:
    rect(p["x0"], p["y0"], p["x1"], p["y1"], FEAT, FLOW_C)
    text(*P((p["x0"] + p["x1"]) / 2, (p["y0"] + p["y1"]) / 2), "%.2f" % p["flow"], FLOW_C, 14)
    text(*P((p["x0"] + p["x1"]) / 2, b.STRIP_B_Y0 + 3.0), p["label"], FLOW_C, 15)

# row C: retraction pairs
for c in man["cells"]:
    for py in (b.POST_A_Y0, b.POST_B_Y0):
        rect(c["x0"], py, c["x1"], py + b.POST, FEAT, RET_C)
    cx = (c["x0"] + c["x1"]) / 2
    ax, ay = P(cx, b.POST_A_Y0 + b.POST + 0.8)
    bx, by = P(cx, b.POST_B_Y0 - 0.8)
    d.line([ax, ay, bx, by], fill=RET_C, width=1)
    text(*P(cx + 4.5, c["y_mid"]), "%.1f" % c["retraction_mm"], RET_C, 13, "lm")
    text(*P(cx, b.STRIP_C_Y0 + 3.0), c["label"], RET_C, 15)

# object 2: the tower footprint, TOWER_GAP_X to the right of the card
tw = man["tower"]
rect(tw["x0"], tw["y0"], tw["x1"], tw["y1"], FEAT, TEMP_C, 2)
tcx = (tw["x0"] + tw["x1"]) / 2
text(*P(tcx, tw["y1"] + 3.5), "TEMP tower (see right)", TEMP_C, 13)
text(*P(tcx, tw["y0"] - 3.5), "object 2: printed after the card, alone", TEMP_C, 12)
text(*P(tcx, tw["y0"] - 7.0), "digits face the front, chin on the back", DIM, 11)
gy = tw["y1"] + 12.0
ax, ay = P(CW, gy)
bx, by = P(tw["x0"], gy)
d.line([ax, ay, bx, by], fill=DIM, width=1)
for xx in (ax, bx):
    d.line([xx, ay - 6, xx, ay + 6], fill=DIM, width=1)
text((ax + bx) / 2, ay - 12, "%.0f mm gap (slicer head-clearance rule: %.0f mm, extruder_clearance_radius)"
     % (tw["gap_to_card_mm"], tw["head_clearance_rule_mm"]), DIM, 12)
text(*P(CW / 2, -4.0), "object 1: the card, %.0f x %.0f mm, %.0f mm tall, all at T%d" % (CW, CD, man["card"]["top_z"], a.temp), DIM, 12)
text(*P(tcx, -4.0), "%.0f x %.1f mm, %.0f mm tall" % (tw["x1"] - tw["x0"], tw["y1"] - tw["y0"], tw["top_z"]), DIM, 12)

# row captions (left of the card)
cap = [(b.RAIL_Y0 + b.RAIL_D / 2, "TOLERANCE", TOL_C),
       ((man["pads"][0]["y0"] + man["pads"][0]["y1"]) / 2, "FLOW", FLOW_C),
       (man["cells"][0]["y_mid"], "RETRACTION", RET_C)]
for y, t_, col in cap:
    lbl = Image.new("RGBA", (200, 22), (0, 0, 0, 0))
    ImageDraw.Draw(lbl).text((100, 11), t_, fill=col, font=font(15), anchor="mm")
    lbl = lbl.rotate(90, expand=True)
    _, yy = P(0, y)
    img.paste(lbl, (OX - 40, int(yy) - 100), lbl)

# tower elevation (right panel)
bx0 = SIDE_X
by_base = OY + int(PD * S)
scale = 6.5
text(bx0, OY - 20, "temperature tower, front view", TEMP_C, 15, "lm")
text(bx0, OY, "Prints alone after the card. Each band starts with M109:", DIM, 11, "lm")
text(bx0, OY + 16, "nozzle lifts 2 mm, parks beside the tower, WAITS, comes back.", DIM, 11, "lm")
text(bx0, OY + 32, "Read each band: wall gloss, chin (back), bridge; then flex.", DIM, 11, "lm")
pw, gap = b.PILLAR_W * scale, b.TOWER_GAP * scale
zpx = lambda z: by_base - z * scale
for i, px0 in enumerate((bx0, bx0 + pw + gap)):
    d.rectangle([px0, zpx(tw["top_z"]), px0 + pw, zpx(0)], fill=FEAT, outline=EDGE)
d.rectangle([bx0 + pw, zpx(tw["pedestal_z"]), bx0 + pw + gap, zpx(tw["pedestal_z"] - b.DECK_H)], fill=EDGE)
text(bx0 + pw + gap / 2, zpx(tw["pedestal_z"] / 2), "T%d" % a.temp, DIM, 12)
text(bx0 + pw + gap / 2, zpx(tw["pedestal_z"] / 2) + 16, "pedestal", DIM, 10)
for band in man["bands"]:
    z0, z1 = band["z0"], band["z1"]
    d.rectangle([bx0 + pw, zpx(z1), bx0 + pw + gap, zpx(z1 - b.DECK_H)], fill=EDGE)   # bridge deck
    d.line([bx0 - 6, zpx(z0), bx0 + 2 * pw + gap + 6, zpx(z0)], fill=TEMP_C, width=1)
    text(bx0 + pw / 2, zpx((z0 + z1) / 2), band["label"], TEMP_C, 16)
    text(bx0 + 2 * pw + gap + 12, zpx(z0), "Z %.0f, tower layer %d: M109 S%d" % (z0, band["first_layer_of_tower"], band["temp"]), DIM, 11, "lm")
    text(bx0 + pw + gap / 2, zpx(z1 - b.DECK_H / 2), "bridge", DIM, 9)
text(bx0 + pw + gap + pw / 2, zpx(tw["top_z"]) - 14, "chin on the back", DIM, 10)
text(bx0 + pw / 2, zpx(tw["top_z"]) - 14, "digits on the front", DIM, 10)

# legend
ly = by_base + 50
lines = [
    (TOL_C, "TOLERANCE   push the loose 6.0 hex into each hole. Label = extra gap per side, in 0.01 mm."),
    (TOL_C, "            Smallest hole it slides into freely = your number. Then try a 6 mm Allen key too."),
    (FLOW_C, "FLOW        hold the 7 pads to the light, fingernail across. Smoothest top wins."),
    (FLOW_C, "            Label = flow ratio x 100 (98 = 0.98). If an edge pad wins, re-run the card centred there."),
    (RET_C, "RETRACTION  look only BETWEEN the two posts of each pair. Label = retraction mm."),
    (RET_C, "            Lowest pair with no strings = your number (strings crossing to other pairs do not count)."),
    (TEMP_C, "TEMP        tower bands, hottest at the bottom, digits on the front. Best band = card temp + that step."),
    (TEMP_C, "            Printed after the card, alone; every band waits for its temperature (M109), so ignore only its first 2-3 layers."),
    (TEMP_C, "            A bracket of +-10 C only. If 200 or 220 wins, or all look alike, run the full tower."),
]
for col, t_ in lines:
    text(OX, ly, t_, col, 13, "lm")
    ly += 22
text(OX, ly + 6, "Card body (pads, posts, holes, tester) prints at the T/F on the info plate. Nothing else on the card is varied.", DIM, 12, "lm")

img.save(a.out)
print("wrote", a.out, img.size)
