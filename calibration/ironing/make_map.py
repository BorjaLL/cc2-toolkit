#!/usr/bin/env python3
"""Draw ironing_grid_map.png - the legend for the ironing calibration grid.

Ranges are read from build_ironing_grid.py so the map always matches the plate.
Run: python calibration/ironing/make_map.py
"""
import importlib.util
import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("b", ROOT / "build_ironing_grid.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
SPEEDS, FLOWS, N = b.SPEEDS, b.FLOWS, b.N

cell = 88
pad = 72
ox = 150
oy = 110
W = ox + N * cell + 50
H = oy + N * cell + 150
img = Image.new("RGB", (W, H), (15, 17, 21))
d = ImageDraw.Draw(img)


def font(sz):
    for p in ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except OSError:
            pass
    return ImageFont.load_default()


def ctext(x, y, t, fill, sz, anchor="mm"):
    d.text((x, y), t, fill=fill, font=font(sz), anchor=anchor)


ctext(ox + N * cell / 2, 42, "CC2 Ironing Calibration Grid", (230, 230, 230), 30)
ctext(ox + N * cell / 2, 74,
      "print one plate - keep the smoothest square (values engraved on each chip)",
      (140, 170, 170), 14)
for j, f in enumerate(FLOWS):
    ctext(ox + j * cell + cell / 2, oy - 16, f"{f}%", (120, 230, 200), 18)
for i, sp in enumerate(SPEEDS):
    row = N - 1 - i
    ctext(ox - 30, oy + row * cell + cell / 2, f"{sp}", (255, 215, 120), 18, "rm")
for i in range(N):
    row = N - 1 - i
    for j in range(N):
        x = ox + j * cell + (cell - pad) / 2
        y = oy + row * cell + (cell - pad) / 2
        d.rounded_rectangle([x, y, x + pad, y + pad], radius=6,
                            fill=(42, 47, 58), outline=(69, 75, 87), width=2)
        ctext(x + pad / 2, y + pad / 2 - 9, f"S{SPEEDS[i]}", (150, 170, 200), 15)
        ctext(x + pad / 2, y + pad / 2 + 9, f"F{FLOWS[j]}", (150, 170, 200), 15)
ey = oy + (N - 1) * cell + cell
d.rounded_rectangle([ox + 8, ey, ox + 8 + pad, ey + 22], radius=4, fill=(198, 102, 85))
ctext(ox + 8 + pad / 2, ey + 11, "EAR", (20, 20, 20), 14)
ctext(ox - 30, oy - 16, "mm/s", (255, 215, 120), 15, "rm")
ctext(ox + N * cell / 2, ey + 52, "flow %  (columns -> right, +X)", (120, 230, 200), 17)
ctext(ox + N * cell / 2, ey + 80,
      "EAR = front-left = slowest + lowest flow corner", (160, 160, 160), 14)
lbl = Image.new("RGBA", (360, 26), (0, 0, 0, 0))
ImageDraw.Draw(lbl).text((180, 13), "speed mm/s (rows -> back, +Y)",
                         fill=(255, 215, 120), font=font(17), anchor="mm")
lbl = lbl.rotate(90, expand=True)
img.paste(lbl, (6, oy + N * cell // 2 - 180), lbl)
img.save(ROOT / "ironing_grid_map.png")
print("wrote", ROOT / "ironing_grid_map.png", img.size)
