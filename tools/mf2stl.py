#!/usr/bin/env python3
"""Minimal 3MF (production extension) -> binary STL. Usage: mf2stl.py in.3mf out.stl [build_objectid]. Resolves build items,
components across per-object .model files, and 4x3 affine transforms."""
import argparse, os, sys, zipfile, struct
import xml.etree.ElementTree as ET

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"

def mat(s):
    """3MF 12-number transform -> 4x4 row-vector matrix (list of lists)."""
    if not s:
        return [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    v = [float(x) for x in s.split()]
    return [[v[0],v[1],v[2],0],[v[3],v[4],v[5],0],
            [v[6],v[7],v[8],0],[v[9],v[10],v[11],1]]

def mul(a,b):
    return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

def apply(m,x,y,z):
    return (x*m[0][0]+y*m[1][0]+z*m[2][0]+m[3][0],
            x*m[0][1]+y*m[1][1]+z*m[2][1]+m[3][1],
            x*m[0][2]+y*m[1][2]+z*m[2][2]+m[3][2])

# --- load every model part: {(path,objid): element} ---
zf = None
parts = {}          # (path,id) -> object element
build = []           # (root_path, objid, transform)
def load(path):
    root = ET.fromstring(zf.read(path.lstrip("/")))
    res = root.find(NS+"resources")
    if res is not None:
        for obj in res.findall(NS+"object"):
            parts[(path, obj.get("id"))] = obj
    b = root.find(NS+"build")
    if b is not None:
        for it in b.findall(NS+"item"):
            build.append((path, it.get("objectid"), mat(it.get("transform"))))

ROOT = "/3D/3dmodel.model"

def collect(path, objid, M, out):
    obj = parts.get((path, objid))
    if obj is None:
        return
    mesh = obj.find(NS+"mesh")
    if mesh is not None:
        vs = [(float(v.get("x")),float(v.get("y")),float(v.get("z")))
              for v in mesh.find(NS+"vertices").findall(NS+"vertex")]
        wv = [apply(M,*p) for p in vs]
        for t in mesh.find(NS+"triangles").findall(NS+"triangle"):
            a,b,c = int(t.get("v1")),int(t.get("v2")),int(t.get("v3"))
            out.append((wv[a],wv[b],wv[c]))
    comps = obj.find(NS+"components")
    if comps is not None:
        for comp in comps.findall(NS+"component"):
            cpath = comp.get("{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}path") or path
            collect(cpath, comp.get("objectid"), mul(mat(comp.get("transform")), M), out)


def main():
    global zf
    ap = argparse.ArgumentParser(description="Convert a 3MF (production extension, per-object "
                                 ".model files) to binary STL; each build item is dropped to Z=0.")
    ap.add_argument("src", help="input .3mf")
    ap.add_argument("out", help="output .stl")
    ap.add_argument("objectid", nargs="?", default=None,
                    help="only convert this build objectid")
    a = ap.parse_args()
    SRC, OUT, ONLY = a.src, a.out, a.objectid
    if not os.path.isfile(SRC):
        sys.exit(f"{SRC}: no such file")
    try:
        zf = zipfile.ZipFile(SRC)
        names = zf.namelist()
        if ROOT.lstrip("/") not in names:
            sys.exit(f"{SRC}: no {ROOT} inside, not a 3MF this tool can convert")
        load(ROOT)
        for n in names:
            if n.startswith("3D/Objects/") and n.endswith(".model"):
                load("/"+n)
        tris = build_tris(ONLY)
    except zipfile.BadZipFile:
        sys.exit(f"{SRC}: not a valid 3MF (zip) file")
    except (KeyError, ET.ParseError, AttributeError, ValueError, IndexError) as e:
        sys.exit(f"{SRC}: unsupported 3MF layout ({type(e).__name__}: {e}); only the "
                 "production-extension layout (3D/3dmodel.model + 3D/Objects/*.model) "
                 "with plain meshes/components is handled")
    if not tris:
        sys.exit(f"{SRC}: no triangles found" + (f" for build objectid {ONLY}" if ONLY else ""))
    write_stl(OUT, tris)


def build_tris(ONLY):
    tris = []  # merged, each build item dropped so its base sits on Z=0
    for path, objid, B in build:
        if ONLY and objid != ONLY:
            continue
        grp = []
        collect(path, objid, B, grp)
        if not grp:
            continue
        minz = min(v[2] for tri in grp for v in tri)
        for a,b,c in grp:
            tris.append(tuple((x, y, z-minz) for (x,y,z) in (a,b,c)))
        print(f"  build item {objid}: {len(grp)} tris, dropped {minz:.2f}mm to bed")

    return tris


def write_stl(OUT, tris):
    with open(OUT,"wb") as f:
        f.write(b"3mf2stl".ljust(80,b"\0"))
        f.write(struct.pack("<I", len(tris)))
        for a,b,c in tris:
            f.write(struct.pack("<12fH", 0,0,0, *a, *b, *c, 0))
    print(f"tris={len(tris)} -> {OUT}")


if __name__ == "__main__":
    main()
