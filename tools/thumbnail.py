#!/usr/bin/env python3
"""
Add the printer's file-list preview image to CC2 G-code sliced from the CLI.

ElegooSlicer only renders the preview (the 3D picture the CC2 shows when you tap a
file) from the GUI; CLI slices carry "; thumbnails = 144x144/PNG" in the config but
no image. This renders the toolpaths themselves (no mesh needed) and inserts the
same block the GUI writes:

    ; THUMBNAIL_BLOCK_START / ; thumbnail begin 144x144 <len> / base64 PNG / ...

Idempotent: a file that already has a thumbnail is left alone unless --force.
Needs Pillow (pip install pillow); slice_cc2.py --thumbnail calls add().

Usage:
    python tools/thumbnail.py <file.gcode> [more.gcode ...] [--force] [--png out.png]
From code (with tools/ on sys.path):
    import thumbnail; thumbnail.add(path)
"""
import argparse, base64, io, math, re, struct, sys, zlib

__all__ = ["SIZE", "B64_LIMIT", "have_pillow", "toolpaths", "colour", "render", "pad3",
           "small_png", "block", "add", "main"]

SIZE = 144
SS = 4  # supersampling
B64_LIMIT = 10004  # largest preview seen working on the CC2; bigger is untested
VIEW_AZ, VIEW_EL = math.radians(40), math.radians(32)  # viewer front-left (-X, -Y), above
SKIP = {"Custom", "Skirt", "Brim"}  # not part of the model
LIGHT = (-0.8, -0.6)  # horizontal light direction (unit), from front-left
MOVE = re.compile(r"^G[01]\s")
AXIS = re.compile(r"([XYZE])(-?\d*\.?\d+)")
PILLOW_HINT = "the G-code preview needs Pillow: pip install pillow"


def have_pillow():
    """True if Pillow can be imported (only render() and small_png() need it)."""
    try:
        import PIL.Image, PIL.ImageDraw  # noqa: F401
        return True
    except ImportError:
        return False


def _pil():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise RuntimeError(PILLOW_HINT) from None
    return Image, ImageDraw


def toolpaths(lines):
    """Extruding segments (x0, y0, x1, y1, z) from printed features only (;TYPE: set,
    not Custom / Skirt / Brim)."""
    x = y = z = 0.0
    e_abs = False
    e_last = 0.0
    ftype = None
    segs = []
    for ln in lines:
        if ln.startswith(";TYPE:"):
            ftype = ln[6:].strip()
            continue
        if ln.startswith("M82"):
            e_abs = True
        elif ln.startswith("M83"):
            e_abs = False
        elif ln.startswith("G92"):
            m = re.search(r"E(-?\d*\.?\d+)", ln)
            if m:
                e_last = float(m.group(1))
        if not MOVE.match(ln):
            continue
        code = ln.split(";", 1)[0]
        vals = dict(AXIS.findall(code))
        nx = float(vals["X"]) if "X" in vals else x
        ny = float(vals["Y"]) if "Y" in vals else y
        if "Z" in vals:
            z = float(vals["Z"])
        extruding = False
        if "E" in vals:
            e = float(vals["E"])
            de = e - e_last if e_abs else e
            if e_abs:
                e_last = e
            extruding = de > 0
        if extruding and ftype and ftype not in SKIP and (nx != x or ny != y):
            segs.append((x, y, nx, ny, z))
        x, y = nx, ny
    return segs


def colour(lines):
    """First filament colour from the G-code's config block, else orange."""
    for ln in reversed(lines[-3000:]):
        m = re.match(r"; filament_colour = (#[0-9A-Fa-f]{6})", ln)
        if m:
            return tuple(int(m.group(1)[i:i + 2], 16) for i in (1, 3, 5))
    return (242, 117, 78)


def render(segs, rgb, size=SIZE):
    """Shaded isometric-ish picture of the toolpaths (PIL RGBA image, size x size)."""
    Image, ImageDraw = _pil()
    if not segs:
        raise ValueError("no printed toolpaths found")
    ca, sa = math.cos(VIEW_AZ), math.sin(VIEW_AZ)
    ce, se = math.cos(VIEW_EL), math.sin(VIEW_EL)

    def proj(px, py, pz):
        near = -(px * sa + py * ca)      # horizontal distance toward the viewer
        u = px * ca - py * sa            # screen right
        v = pz * ce - near * se          # screen up: farther back = higher
        d = near * ce + pz * se          # depth: bigger = nearer the viewer
        return u, v, d

    pts = []
    for x0, y0, x1, y1, z in segs:
        u0, v0, d0 = proj(x0, y0, z)
        u1, v1, d1 = proj(x1, y1, z)
        # wall facing: segment normal vs a light from the viewer's left; edges and holes show up
        ln = math.hypot(x1 - x0, y1 - y0) or 1.0
        nx, ny = (y1 - y0) / ln, -(x1 - x0) / ln
        lit = abs(nx * LIGHT[0] + ny * LIGHT[1])
        pts.append((u0, v0, u1, v1, (d0 + d1) / 2, z, lit))
    us = [p[0] for p in pts] + [p[2] for p in pts]
    vs = [p[1] for p in pts] + [p[3] for p in pts]
    zs = [p[5] for p in pts]
    umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)
    zmin, zmax = min(zs), max(zs)
    big = size * SS
    pad = big * 0.06
    scale = (big - 2 * pad) / max(umax - umin, vmax - vmin, 1e-6)
    ox = (big - (umax - umin) * scale) / 2
    oy = (big - (vmax - vmin) * scale) / 2
    width = max(1, round(0.45 * scale))
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    pts.sort(key=lambda p: p[4])        # painter's order: far first
    for u0, v0, u1, v1, d, z, lit in pts:
        hz = (z - zmin) / (zmax - zmin) if zmax > zmin else 1.0
        k = 0.45 + 0.45 * lit + 0.15 * hz  # lit faces and higher layers brighter
        c = tuple(min(255, int(ch * k)) for ch in rgb) + (255,)
        a = (ox + (u0 - umin) * scale, big - (oy + (v0 - vmin) * scale))
        b = (ox + (u1 - umin) * scale, big - (oy + (v1 - vmin) * scale))
        dr.line([a, b], fill=c, width=width)
    return img.resize((size, size), Image.LANCZOS)


def pad3(png):
    """Make the PNG length a multiple of 3 so its base64 has no '=' padding: the CC2
    silently drops any preview whose base64 ends in '=' or '==' (2026-10-01: every
    failing preview had padding, every working one had none; adding this chunk fixed a
    failing one). Adds a tiny tEXt chunk before IEND. Pure bytes, no Pillow needed."""
    k = (-(len(png) + 14)) % 3
    data = b"c" + bytes(1) + b"x" * k   # keyword "c", NUL separator, k filler bytes
    chunk = (struct.pack(">I", len(data)) + b"tEXt" + data
             + struct.pack(">I", zlib.crc32(b"tEXt" + data) & 0xffffffff))
    i = png.rindex(b"IEND") - 4
    out = png[:i] + chunk + png[i:]
    assert len(out) % 3 == 0
    return out


def small_png(img):
    """RGBA PNG under B64_LIMIT base64 chars (the size proven on the printer), fewer
    colours until it fits, padded so the base64 has no '='. Returns (image, png bytes)."""
    Image, _ = _pil()
    for colours in (None, 64, 32, 16, 8):
        im = img if colours is None else img.quantize(colours, method=Image.FASTOCTREE).convert("RGBA")
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        data = pad3(buf.getvalue())
        if len(base64.b64encode(data)) <= B64_LIMIT:
            return im, data
    raise ValueError("preview does not fit in %d base64 chars" % B64_LIMIT)


def block(png_bytes, size=SIZE):
    """G-code comment lines of a thumbnail block, as the GUI writes them."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    rows = [b64[i:i + 78] for i in range(0, len(b64), 78)]
    out = ["", "", "; THUMBNAIL_BLOCK_START", "", ";", f"; thumbnail begin {size}x{size} {len(b64)}"]
    out += ["; " + r for r in rows]
    out += ["; thumbnail end", "; THUMBNAIL_BLOCK_END", ""]
    return out


def add(path, force=False, png=None):
    """Insert (or with force, replace) the preview in a G-code file. png: also save the
    image to this path. Returns True if the file changed. Raises RuntimeError without
    Pillow, ValueError when the file has no printed toolpaths."""
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    nl = "\r\n" if "\r\n" in text[:2000] else "\n"
    lines = text.split(nl)
    has = any(ln.startswith("; THUMBNAIL_BLOCK_START") for ln in lines[:200])
    if has and not force:
        return False
    if has:
        s = next(i for i, ln in enumerate(lines) if ln.startswith("; THUMBNAIL_BLOCK_START"))
        e = next(i for i, ln in enumerate(lines) if ln.startswith("; THUMBNAIL_BLOCK_END"))
        while s > 0 and lines[s - 1] == "":
            s -= 1
        del lines[s:e + 1]
    img, data = small_png(render(toolpaths(lines), colour(lines)))
    if png:
        img.save(png)
    # after the header (last "; HEADER_BLOCK_END" in the first lines), like the GUI
    ends = [i for i, ln in enumerate(lines[:60]) if ln.startswith("; HEADER_BLOCK_END")]
    at = ends[-1] + 1 if ends else 0
    lines[at:at] = block(data)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(nl.join(lines))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gcode", nargs="+")
    ap.add_argument("--force", action="store_true", help="replace an existing thumbnail")
    ap.add_argument("--png", help="also save the image here (single file only)")
    a = ap.parse_args(argv)
    if a.png and len(a.gcode) > 1:
        ap.error("--png takes a single G-code file")
    if not have_pillow():
        sys.exit(PILLOW_HINT)
    for p in a.gcode:
        changed = add(p, a.force, a.png)
        print(("added preview: " if changed else "already has a preview: ") + p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
