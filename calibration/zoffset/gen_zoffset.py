#!/usr/bin/env python3
"""Generate a single-layer first-layer / Z-offset test patch STL sized to the
CC2's first-layer height, so it slices to exactly ONE layer for a clean squish read."""
import json, glob, os, struct, sys

PROFILES = os.path.join(os.environ.get("ELEGOO_SLICER_DIR", r"C:/Program Files/ElegooSlicer"),
                        "resources", "profiles")
idx = {}
for p in glob.glob(PROFILES + "/**/*.json", recursive=True):
    try:
        d = json.load(open(p, encoding="utf-8"))
        if isinstance(d, dict) and "name" in d:
            idx.setdefault(d["name"], p)
    except Exception:
        pass

def res(n, seen=None):
    seen = seen or set()
    if n in seen or n not in idx:
        return {}
    seen.add(n)
    d = json.load(open(idx[n], encoding="utf-8"))
    b = res(d["inherits"], seen) if d.get("inherits") else {}
    b.update({k: v for k, v in d.items() if k != "inherits"})
    return b

proc = res("0.20mm Standard @Elegoo CC2 0.4 nozzle")
flh = proc.get("initial_layer_print_height") or proc.get("initial_layer_height") or "0.2"
try:
    H = float(flh if not isinstance(flh, list) else flh[0])
except Exception:
    H = 0.2
print("first-layer height =", H, "mm")

# 80 x 80 mm patch, exactly one first-layer tall, centered on origin.
S = 80.0
x0, y0, x1, y1, z0, z1 = -S/2, -S/2, S/2, S/2, 0.0, H
v = [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
     (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
# 12 triangles (two per face), outward winding
tris = [
    (0,3,2),(0,2,1),        # bottom (z0)  normal -Z
    (4,5,6),(4,6,7),        # top    (z1)  normal +Z
    (0,1,5),(0,5,4),        # front  (y0)  normal -Y
    (2,3,7),(2,7,6),        # back   (y1)  normal +Y
    (1,2,6),(1,6,5),        # right  (x1)  normal +X
    (3,0,4),(3,4,7),        # left   (x0)  normal -X
]
out = sys.argv[1] if len(sys.argv) > 1 else "zoffset_patch.stl"
with open(out, "wb") as f:
    f.write(b"\0"*80)
    f.write(struct.pack("<I", len(tris)))
    for a,b_,c in tris:
        f.write(struct.pack("<3f", 0,0,0))       # normal (0 = let slicer compute)
        for idx3 in (a,b_,c):
            f.write(struct.pack("<3f", *v[idx3]))
        f.write(struct.pack("<H", 0))
print("wrote", out, "(", S, "x", S, "x", H, "mm, 1 layer )")
