#!/usr/bin/env python3
"""
Adaptive (variable) layer height for the ElegooSlicer / OrcaSlicer CLI.

Why this exists: the CLI ignores `adaptive_layer_height=1` in a process profile (it
is a legacy key Orca drops on load; the G-code config dump does not even list it).
In the GUI, "Adaptive" in the variable layer height dialog computes a per-object
layer height profile from the mesh, and the 3MF stores it as
Metadata/layer_heights_profile.txt. The CLI DOES honour that file. So this module
computes the same profile in Python and writes it into a copy of the 3MF.

The algorithm is a port of OrcaSlicer's (from PrusaSlicer, after Florens Wasserfall):
src/libslic3r/SlicingAdaptive.cpp next_layer_height(), Slicing.cpp
layer_height_profile_adaptive() and smooth_height_profile():
  - each facet allows a layer height from its slope: min(dev / 0.184,
    1.44 * dev * sqrt(sin / cos)) (flat tops get thin layers, walls get thick ones)
  - dev comes from the Quality/Speed factor q (0 = finest, 0.5 = base layer
    height, 1 = fastest): lerp(min, base, 2q) below 0.5, lerp(max, base, 2(1-q)) above
  - a layer is the thinnest any facet it crosses allows, clamped to [min, max],
    and changes by at most 0.04 mm from the previous layer (Bambu/Orca rule)
  - optional smoothing: the GUI "Smooth" button (Gaussian blur over the profile,
    6 passes, radius in layers, biased towards thin layers)
Stdlib only. Profile format: "object_id=N|z0;h0;z1;h1;...", N = 1-based object
order in the 3MF, z from the object bottom, last z = object height (else the slicer
discards the profile).

    python adaptive_layers.py in.3mf|in.stl out.3mf [--quality 0.5] [--smooth 0]
                              [--layer 0.20] [--min 0.08] [--max 0.28] [--first 0.20]
"""
import math, os, re, struct, sys, zipfile
from bisect import bisect_left

PROFILE_FILE = "Metadata/layer_heights_profile.txt"
CHANGE_STEP = 0.04     # Orca LAYER_HEIGHT_CHANGE_STEP
EPS = 1e-4
GRID = 0.005           # mm, z grid for the "facets crossing this z" lookup


def surface_deviation(quality, base, lo, hi):
    """Orca's Quality/Speed factor (0..1) to the allowed surface deviation."""
    q = min(max(float(quality), 0.0), 1.0)
    if q < 0.5:
        return lo + (base - lo) * 2 * q
    return hi + (base - hi) * 2 * (1 - q)


def _slope_ratio(a, b, c):
    """sqrt(sin/cos) of the facet normal against Z (inf for vertical facets)."""
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    ln = math.sqrt(nx * nx + ny * ny + nz * nz)
    if ln == 0:
        return None
    cos = abs(nz) / ln
    if cos <= 1e-5:
        return math.inf
    return math.sqrt(math.sqrt(max(0.0, 1 - cos * cos)) / cos)


class _Faces:
    """Facets of one object (z from the object's bottom) indexed for layer queries."""

    def __init__(self, tris):
        z0 = min(min(p[2] for p in t) for t in tris)
        rows = []
        for t in tris:
            r = _slope_ratio(*t)
            if r is None:
                continue
            zs = [p[2] - z0 for p in t]
            rows.append((min(zs), max(zs), r))
        self.height = max(r[1] for r in rows)
        rows.sort()
        self.zmin = [r[0] for r in rows]
        self.rows = rows
        # grid[k]: smallest slope ratio of the facets crossing z = k * GRID
        n = int(self.height / GRID) + 2
        grid = [math.inf] * n
        for lo, hi, r in sorted(rows, key=lambda x: -x[2]):
            k0, k1 = int(lo / GRID) + 1, min(n, int(math.ceil((hi - EPS) / GRID)))
            if k1 > k0:
                grid[k0:k1] = [r] * (k1 - k0)
        self.grid = grid

    @staticmethod
    def _h(r, dev):
        return min(dev / 0.184, 1.44 * dev * r)

    def next_height(self, z, dev, lo, hi):
        k = int(round(z / GRID))
        h = hi
        if k < len(self.grid):
            h = min(h, self._h(self.grid[k], dev))
        h = max(h, lo)
        if h > lo:  # facets starting inside the new layer
            i = bisect_left(self.zmin, z)
            while i < len(self.rows) and self.rows[i][0] < z + h:
                fl, fh, r = self.rows[i]
                i += 1
                if fh < z + EPS:
                    continue
                red, zd = self._h(r, dev), fl - z
                if red < zd:
                    h = max(zd, lo)
                elif red < h:
                    h = red
            h = max(h, lo)
        return h


def profile(tris, quality=0.5, layer=0.20, lo=0.08, hi=0.28, first=0.20, smooth=0):
    """Layer height profile [z0, h0, z1, h1, ...] of one object.
    tris: [((x,y,z), (x,y,z), (x,y,z)), ...] in print orientation (any z offset).
    smooth: 0 = off, else the GUI smoothing radius (layers)."""
    f = _Faces(tris)
    H = f.height
    dev = surface_deviation(quality, layer, lo, hi)
    prof = [0.0, first, first, first]
    z = first
    while z + EPS < H:
        h = min(f.next_height(z, dev, lo, hi), hi)
        last = prof[-1]
        if h > last + CHANGE_STEP:
            h = last + CHANGE_STEP
        elif h < last - CHANGE_STEP:
            h = last - CHANGE_STEP
        prof += [z, h]
        z += h
    gap = H - prof[-2]
    if gap > 0:
        prof += [H, min(max(gap, lo), hi)]
    if smooth:
        for _ in range(6):
            prof = _blur(prof, int(smooth), layer, lo, hi)
    return prof


def _blur(prof, radius, layer, lo, hi, skip=4):
    """Orca smooth_height_profile gauss_blur (keep_min off), first layer untouched."""
    if len(prof) - skip < 6:
        return prof
    radius = max(radius, 1)
    sigma = 0.3 * (radius - 1) + 0.8
    kern = [math.exp(-(x * x) / (2 * sigma * sigma)) for x in range(-radius, radius + 1)]
    inv_dh = 1.0 / (hi - lo) if hi != lo else 1.0
    out = prof[:skip]
    n = len(prof)
    for i in range(skip, n, 2):
        zi, hi_ = prof[i], prof[i + 1]
        tot = wsum = 0.0
        for j in range(max(i - 2 * radius, skip), min(i + 2 * radius, n - 2) + 1, 2):
            if abs(zi - prof[j]) * layer <= radius * layer:
                w = kern[radius + (j - i) // 2] * math.sqrt(abs(hi - prof[j + 1]) * inv_dh)
                tot += w * prof[j + 1]
                wsum += w
        out += [zi, min(max(tot / wsum if wsum else hi_, lo), hi)]
    return out


def layer_stats(prof):
    """(layer count, min height, max height) the slicer will roughly produce."""
    hs, z, H = [], prof[0], prof[-2]
    pts = list(zip(prof[0::2], prof[1::2]))
    j = 0
    while z + EPS < H:
        while j + 1 < len(pts) and pts[j + 1][0] <= z + EPS:
            j += 1
        h = pts[j][1]
        hs.append(h)
        z += h
    return len(hs), min(hs), max(hs)


# --- 3MF / STL I/O --------------------------------------------------------------

def _mat(s):
    v = [float(x) for x in s.split()]
    return [v[0:3], v[3:6], v[6:9]], v[9:12]


_IDENT = ([[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0])


def _xf(p, T):
    r, t = T
    return (p[0] * r[0][0] + p[1] * r[1][0] + p[2] * r[2][0] + t[0],
            p[0] * r[0][1] + p[1] * r[1][1] + p[2] * r[2][1] + t[1],
            p[0] * r[0][2] + p[1] * r[1][2] + p[2] * r[2][2] + t[2])


_VTX = re.compile(r'<vertex\s+x="([^"]+)"\s+y="([^"]+)"\s+z="([^"]+)"')
_VTX_ANY = re.compile(r'<vertex\b([^>]*)>')
_TRI = re.compile(r'<triangle\s+v1="(\d+)"\s+v2="(\d+)"\s+v3="(\d+)"')
_TRI_ANY = re.compile(r'<triangle\b([^>]*)>')
_ATTR = re.compile(r'(\w+)="([^"]*)"')


def _mesh(xml):
    """(vertices, triangles) of the first <mesh> in an <object> body."""
    vs = [tuple(map(float, m)) for m in _VTX.findall(xml)]
    if len(vs) != xml.count("<vertex"):
        vs = []
        for m in _VTX_ANY.findall(xml):
            a = dict(_ATTR.findall(m))
            vs.append((float(a["x"]), float(a["y"]), float(a["z"])))
    ts = [tuple(map(int, m)) for m in _TRI.findall(xml)]
    if len(ts) != xml.count("<triangle"):
        ts = []
        for m in _TRI_ANY.findall(xml):
            a = dict(_ATTR.findall(m))
            ts.append((int(a["v1"]), int(a["v2"]), int(a["v3"])))
    return vs, ts


def _objects(xml):
    """{id: body} of the <object> elements of a model file."""
    return {m.group(1): m.group(2) for m in
            re.finditer(r'<object\s[^>]*?\bid="(\d+)"[^>]*>(.*?)</object>', xml, re.S)}


def read_3mf_objects(path):
    """[(object order 1.., name, triangles in print orientation)] of a 3MF, one per
    build object (first instance's transform), in the order the slicer numbers them."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        cache = {}

        def model(p):
            p = p.lstrip("/")
            if p not in cache:
                cache[p] = _objects(z.read(p).decode("utf-8", "replace")) if p in names else {}
            return cache[p]

        names_cfg = {}  # Bambu/Orca object names (Metadata/model_settings.config)
        if "Metadata/model_settings.config" in names:
            cfg = z.read("Metadata/model_settings.config").decode("utf-8", "replace")
            for m in re.finditer(r'<object id="(\d+)">\s*<metadata key="name" value="([^"]*)"', cfg):
                names_cfg[m.group(1)] = m.group(2)
        root_path = "3D/3dmodel.model"
        root_xml = z.read(root_path).decode("utf-8", "replace")
        root = model(root_path)
        items, seen = [], set()
        for m in re.finditer(r'<item\b([^>]*)>', root_xml):
            a = dict(_ATTR.findall(m.group(1).replace("p:path", "path")))
            oid = a.get("objectid")
            if oid in seen or oid not in root:
                continue
            seen.add(oid)
            items.append((oid, _mat(a["transform"]) if a.get("transform") else _IDENT))
        out = []
        for n, (oid, T) in enumerate(items, 1):
            body = root[oid]
            tris = []
            for c in re.finditer(r'<component\b([^>]*)>', body):
                a = dict(_ATTR.findall(c.group(1).replace("p:path", "path")))
                sub = model(a.get("path", root_path)).get(a["objectid"], "")
                C = _mat(a["transform"]) if a.get("transform") else _IDENT
                vs, ts = _mesh(sub)
                pts = [_xf(_xf(v, C), T) for v in vs]
                tris += [(pts[i], pts[j], pts[k]) for i, j, k in ts]
            if "<mesh" in body:
                vs, ts = _mesh(body)
                pts = [_xf(v, T) for v in vs]
                tris += [(pts[i], pts[j], pts[k]) for i, j, k in ts]
            nm = re.search(r'\bname="([^"]*)"', re.search(r'<object\s[^>]*?\bid="%s"[^>]*>' % oid,
                                                          root_xml).group(0))
            if tris:
                out.append((n, names_cfg.get(oid) or (nm.group(1) if nm else oid), tris))
        return out


def read_stl(path):
    """Triangles of a binary or ASCII STL."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * n == len(data):
            tris = []
            for i in range(n):
                v = struct.unpack_from("<12f", data, 84 + 50 * i)
                tris.append((v[3:6], v[6:9], v[9:12]))
            return tris
    nums = re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)
    pts = [tuple(float(x) for x in p) for p in nums]
    return [tuple(pts[i:i + 3]) for i in range(0, len(pts) - 2, 3)]


def stl_to_3mf(tris, dst, name="model"):
    """Minimal single-object 3MF (shared vertices, so the slicer sees a closed mesh)."""
    idx, vs, ts = {}, [], []
    for t in tris:
        tri = []
        for p in t:
            k = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
            if k not in idx:
                idx[k] = len(vs)
                vs.append(k)
            tri.append(idx[k])
        if len(set(tri)) == 3:
            ts.append(tri)
    body = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<model unit=\"millimeter\" xml:lang=\"en-US\" "
            "xmlns=\"http://schemas.microsoft.com/3dmanufacturing/core/2015/02\">\n<resources>\n"
            f"<object id=\"1\" name=\"{name}\" type=\"model\"><mesh><vertices>\n"]
    body += [f"<vertex x=\"{x:g}\" y=\"{y:g}\" z=\"{z:g}\"/>\n" for x, y, z in vs]
    body.append("</vertices><triangles>\n")
    body += [f"<triangle v1=\"{a}\" v2=\"{b}\" v3=\"{c}\"/>\n" for a, b, c in ts]
    body.append("</triangles></mesh></object>\n</resources>\n<build><item objectid=\"1\"/></build>\n</model>\n")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Default Extension="rels" ContentType="application/'
                   'vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" '
                   'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats'
                   '.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" '
                   'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", "".join(body))


def profile_text(profiles):
    """layer_heights_profile.txt body from {object order: profile}."""
    return "".join(f"object_id={n}|" + ";".join("%f" % v for v in p) + "\n"
                   for n, p in sorted(profiles.items()))


def write_adaptive_3mf(src, dst, quality=0.5, layer=0.20, lo=0.08, hi=0.28, first=0.20, smooth=0):
    """Copy model src (.3mf or .stl) to dst (.3mf) with an adaptive layer height profile
    for every object (an existing profile in the 3MF is replaced). Returns
    [{"object", "name", "height", "layers", "min", "max"}] (estimated from the profile)."""
    if src.lower().endswith(".stl"):
        stl_to_3mf(read_stl(src), dst, os.path.splitext(os.path.basename(src))[0])
        src = dst
        objs = read_3mf_objects(dst)
    else:
        objs = read_3mf_objects(src)
    if not objs:
        raise ValueError(f"{src}: no meshes found")
    profiles, info = {}, []
    for n, name, tris in objs:
        p = profile(tris, quality, layer, lo, hi, first, smooth)
        profiles[n] = p
        cnt, hmin, hmax = layer_stats(p)
        info.append({"object": n, "name": name, "height": round(p[-2], 3), "layers": cnt,
                     "min": round(hmin, 3), "max": round(hmax, 3)})
    tmp = dst + ".tmp"
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zi.infolist():
            if it.filename != PROFILE_FILE:
                zo.writestr(it, zi.read(it.filename))
        zo.writestr(PROFILE_FILE, profile_text(profiles))
    os.replace(tmp, dst)
    return info


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Write an adaptive layer height profile into a 3MF")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--quality", type=float, default=0.5, help="0 finest .. 1 fastest (GUI default 0.5)")
    ap.add_argument("--smooth", type=int, default=0, help="smoothing radius in layers, 0 = off")
    ap.add_argument("--layer", type=float, default=0.20)
    ap.add_argument("--min", type=float, default=0.08)
    ap.add_argument("--max", type=float, default=0.28)
    ap.add_argument("--first", type=float, default=0.20)
    a = ap.parse_args(argv)
    for o in write_adaptive_3mf(a.src, a.dst, a.quality, a.layer, a.min, a.max, a.first, a.smooth):
        print(o)


if __name__ == "__main__":
    main()
