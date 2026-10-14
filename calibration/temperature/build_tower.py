# /// script
# dependencies = ["DracoPy", "trimesh", "manifold3d", "numpy", "pillow"]
# ///
"""Generate the bundled Elegoo temperature tower for CC2, without GUI state.

Run: uv run calibration/temperature/build_tower.py [--preset "Elegoo PLA Matte @ECC2" --tag PLAMatte] [--top 260]
(default: plain "Elegoo PLA @ECC2", the committed emoji PLA tower)
Uses ElegooSlicer 1.5.3.5's model, vendor-scoped profiles, and native CLI.
The layer-change template changes nozzle temperature during slicing.
ElegooSlicer install: ELEGOO_SLICER_DIR (default C:/Program Files/ElegooSlicer).
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import DracoPy
import manifold3d
import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parents[1]
INSTALL = pathlib.Path(os.environ.get("ELEGOO_SLICER_DIR", r"C:/Program Files/ElegooSlicer"))
VENDOR = INSTALL / "resources/profiles/Elegoo"
MODEL = INSTALL / "resources/calib/temperature_tower/temperature_tower.drc"
PRESET = "Elegoo PLA @ECC2"
TAG = None  # None = the original emoji PLA file names
OUTPUT = ROOT / "CC2_Emoji_PLA_TempTower_230-190C_0.4mm.gcode"
OUT = ROOT  # --out
ACCEL = "stock"  # --accel: a tools/slice_cc2.py ACCEL profile name
BRIM = 5  # mm, outer brim; --brim 10 for filaments that lift off the bed
TOP = 230  # hottest (bottom) block; nine 5 C blocks down to TOP - 40 (PETG: --top 260)
EXPECT = {}  # stock values the verifier checks, read from the resolved filament preset


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path):
    """Install-relative path for the report (no machine-specific prefix)."""
    try:
        return pathlib.Path(path).relative_to(INSTALL).as_posix()
    except ValueError:
        return pathlib.Path(path).name


def add_thumbnail(path):
    """Printer file-list preview (CLI slices have none) via tools/thumbnail.py, if present."""
    sys.path.insert(0, str(REPO / "tools"))
    try:
        import thumbnail
    except ImportError:
        print("tools/thumbnail.py not found: G-code has no printer preview", flush=True)
        return
    thumbnail.add(str(path))


def resolve_profile(kind, name, chain=None):
    # Generic base names repeat across vendors. Never search all vendors.
    chain = [] if chain is None else chain
    assert name not in chain, f"Profile inheritance cycle: {name}"
    found = []
    for path in (VENDOR / kind).rglob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("name") == name:
            found.append((path, data))
    assert len(found) == 1, (kind, name, [str(p) for p, _ in found])
    path, data = found[0]
    if data.get("inherits"):
        merged, sources = resolve_profile(kind, data["inherits"], chain + [name])
    else:
        merged, sources = {}, []
    merged.update(data)
    for key in ("inherits", "instantiation"):
        merged.pop(key, None)
    sources.append({"path": rel(path), "sha256": sha256(path)})
    return merged, sources


def build_geometry():
    decoded = DracoPy.decode(MODEL.read_bytes())
    solid = manifold3d.Manifold(manifold3d.Mesh(
        np.asarray(decoded.points, dtype=np.float32),
        np.asarray(decoded.faces, dtype=np.uint32),
    ))
    assert solid.status() == manifold3d.Error.NoError
    # Matches Plater::calib_temp: the complete model starts at 500C,
    # with a 10mm block per 5C. Keep nine blocks: TOP through TOP - 40 (embossed labels match).
    low = (500 - TOP) * 2
    solid = solid.trim_by_plane((0, 0, 1), low + 0.0001)
    solid = solid.trim_by_plane((0, 0, -1), -(low + 90) + 0.0001)
    assert solid.status() == manifold3d.Error.NoError
    raw = solid.to_mesh()
    mesh = trimesh.Trimesh(vertices=raw.vert_properties[:, :3], faces=raw.tri_verts)
    center = mesh.bounds.mean(axis=0)
    mesh.apply_translation([-center[0], -center[1], -mesh.bounds[0, 2]])
    assert mesh.is_watertight and mesh.volume > 0
    assert np.allclose(mesh.extents, [44.49907, 10.000023, 89.999756], atol=0.002)
    path = OUT / f"Elegoo_TempTower_{TOP}-{TOP - 40}C.stl"
    mesh.export(path)
    return path, {"watertight": True, "size_mm": mesh.extents.tolist(),
                  "volume_mm3": mesh.volume, "faces": len(mesh.faces)}


def build_profiles():
    machine, ms = resolve_profile("machine", "Elegoo Centauri Carbon 2 0.4 nozzle")
    process, ps = resolve_profile("process", "0.20mm Standard @Elegoo CC2 0.4 nozzle")
    filament, fs = resolve_profile("filament", PRESET)
    if PRESET == "Elegoo PLA @ECC2":
        assert filament["filament_flow_ratio"] == ["0.98"]
        assert filament["textured_plate_temp"] == ["60"]
    assert filament.get("additional_cooling_fan_speed", ["0"]) == ["0"]  # unset in PETG HF = off
    EXPECT["pa"] = filament["pressure_advance"][0]
    assert filament["enable_pressure_advance"] == ["1"]
    assert filament["textured_plate_temp_initial_layer"] == filament["textured_plate_temp"]
    EXPECT["flow"] = filament["filament_flow_ratio"][0]
    EXPECT["bed"] = filament["textured_plate_temp"][0]
    assert machine["retraction_length"] == ["0.8"]
    assert machine["retraction_speed"] == ["30"]

    # Native temperature calibration disables resonance avoidance and uses
    # these object/process overrides. Support stays off for bridge testing.
    machine["resonance_avoidance"] = "0"
    expression = f"{{if layer_z < 10.1}}{TOP}"
    for boundary, temperature in zip(range(20, 81, 10), range(TOP - 5, TOP - 40, -5)):
        expression += f"{{elsif layer_z < {boundary}.1}}{temperature}"
    expression += f"{{else}}{TOP - 40}{{endif}}"
    machine["layer_change_gcode"] += (
        "\n; CC2_TEMP_TOWER Z={layer_z}\nM104 S" + expression
    )
    process.update({
        "name": "CC2 stock temperature calibration 0.20mm",
        "curr_bed_type": "Textured PEI Plate",
        "layer_height": "0.2", "initial_layer_print_height": "0.2",
        "brim_type": "outer_only", "brim_width": str(BRIM), "brim_object_gap": "0",
        "alternate_extra_wall": "0", "seam_slope_type": "none",
        "overhang_reverse": "0", "precise_z_height": "0",
        "enable_wrapping_detection": "0", "enable_support": "0",
        "enable_prime_tower": "0", "ironing_type": "no ironing",
    })
    # Optional: the accel profile you print real parts with (tools/slice_cc2.py ACCEL), so the
    # tower is judged at the same accelerations. Default stock = the Elegoo profile values.
    if ACCEL != "stock":
        sys.path.insert(0, str(REPO / "tools"))
        import slice_cc2
        assert ACCEL in slice_cc2.ACCEL, (ACCEL, sorted(slice_cc2.ACCEL))
        process.update(slice_cc2.ACCEL[ACCEL])
    filament["nozzle_temperature_initial_layer"] = [str(TOP)]
    filament["nozzle_temperature"] = [str(TOP)]
    profiles = OUT / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    paths = []
    for kind, data in [("machine", machine), ("process", process), ("filament", filament)]:
        path = profiles / f"flat_{kind}.json"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return paths, {"machine": ms, "process": ps, "filament": fs}


def verify_gcode(path):
    text = path.read_text(encoding="utf-8")
    assert "generated by ElegooSlicer 1.5.3.5 " in text
    entries = re.findall(r"^; CC2_TEMP_TOWER Z=([\d.]+)\s*\nM104 S(\d+)", text, re.M)
    assert len(entries) == 450, f"Expected 450 layers, got {len(entries)}"
    groups = []
    for index, (z, temperature) in enumerate(entries):
        assert abs(float(z) - (index + 1) * 0.2) < 0.002
        expected = TOP - 5 * (index // 50)
        assert int(temperature) == expected, (index, z, temperature, expected)
        if index % 50 == 0:
            groups.append({"first_layer_z_mm": float(z), "nozzle_c": expected})
    assert "BED_MESH_CALIBRATE " in text
    assert "M6211 A1 L200 T0 " in text
    assert re.search(r"^SET_PRESSURE_ADVANCE ADVANCE=%s\b" % re.escape(EXPECT["pa"]), text, re.M)
    assert re.search(r"^M190 S%s\b" % EXPECT["bed"], text, re.M)
    assert re.search(r"^M109 S%d\b" % TOP, text, re.M)
    assert re.search(r"^M104 S0\b", text, re.M)
    assert re.search(r"^M140 S0\b", text, re.M)
    assert re.search(r"^; filament_flow_ratio = %s\s*$" % re.escape(EXPECT["flow"]), text, re.M)
    assert re.search(r"^; retraction_length = 0\.8\s*$", text, re.M)
    assert not re.search(r"^T[1-9]\d*\b|^M600\b|^M6211 T", text, re.M)
    assert not re.search(r"^M106 P2 S(?!0\b)\d+", text, re.M)
    # Check the printed geometry/brim, excluding the vendor's off-bed purge.
    body = text.split("; CC2_TEMP_TOWER Z=", 1)[1].split(";===== CC2_END_GCODE", 1)[0]
    position = {"X": None, "Y": None, "Z": None}
    points = []
    for line in body.splitlines():
        if not re.match(r"G[01] ", line):
            continue
        for axis, value in re.findall(r"\b([XYZ])(-?[\d.]+)", line):
            position[axis] = float(value)
        extrusion = re.search(r"\bE(-?[\d.]+)", line)
        if (extrusion and float(extrusion[1]) > 0 and
                re.search(r"\b[XY][-\d.]", line) and
                all(value is not None for value in position.values())):
            points.append(tuple(position.values()))
    assert points
    bounds = {}
    for index, axis in enumerate("XYZ"):
        lo, hi = min(p[index] for p in points), max(p[index] for p in points)
        assert 0 <= lo <= hi <= 256, (axis, lo, hi)
        bounds[axis] = [lo, hi]
    # Check the effective nozzle target throughout the body, so an unrelated
    # slicer temperature command cannot silently override a tower band.
    active_z = None
    target = None
    extrusions = 0
    for line in text.splitlines():
        if line.startswith("; CC2_TEMP_TOWER Z="):
            active_z = float(line.split("=")[1])
        temperature = re.match(r"M10[49]\s+S([\d.]+)", line)
        if temperature:
            target = float(temperature[1])
        if active_z is not None and re.match(r"G[123]\s", line) and re.search(r"\b[XY][-\d.]", line):
            extrusion = re.search(r"\bE(-?[\d.]+)", line)
            if extrusion and float(extrusion[1]) > 0:
                expected = TOP - min(8, int((active_z - 0.1) // 10)) * 5
                assert target == expected, (active_z, target, expected, line)
                extrusions += 1
    assert extrusions > 1000
    stats = [line for line in text.splitlines() if any(term in line for term in (
        "estimated printing time", "total estimated time", "total filament used [g]",
        "total filament used [mm]", "total filament change", "model printing time"))]
    return {"layer_count": len(entries), "temperature_bands": groups,
            "printed_bounds_mm": bounds, "canvas_slot": 1,
            "verified_extrusion_moves": extrusions, "statistics": stats}


def main():
    global PRESET, TAG, OUTPUT, TOP, BRIM, OUT, ACCEL
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", default=PRESET, help="stock Elegoo CC2 filament preset name")
    ap.add_argument("--top", type=int, default=TOP, help="hottest block C (default 230 for PLA; PETG 260)")
    ap.add_argument("--tag", help="file name tag, e.g. PLAMatte (required with a non-default --preset)")
    ap.add_argument("--brim", type=int, default=BRIM, help="outer brim width mm (default 5)")
    ap.add_argument("--accel", default=ACCEL,
                    help="tools/slice_cc2.py ACCEL profile name (default stock = Elegoo profile accels)")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT, help="output folder (default: this folder)")
    a = ap.parse_args()
    assert (INSTALL / "elegoo-slicer.exe").is_file(), f"ElegooSlicer not found in {INSTALL}: set ELEGOO_SLICER_DIR"
    BRIM, ACCEL = a.brim, a.accel
    OUT = a.out.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    OUTPUT = OUT / OUTPUT.name
    PRESET, TAG, TOP = a.preset, a.tag, a.top
    if PRESET != "Elegoo PLA @ECC2" and not TAG:
        ap.error("--tag is required with --preset (keeps the emoji PLA files intact)")
    if TAG:
        OUTPUT = OUT / f"CC2_{TAG}_TempTower_{TOP}-{TOP - 40}C_0.4mm.gcode"
    suffix = f"_{TAG}" if TAG else ""
    model, geometry = build_geometry()
    (machine, process, filament), sources = build_profiles()
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="cc2-temperature-slice-"))
    command = [str(INSTALL / "elegoo-slicer.exe"),
               "--load-settings", f"{machine};{process}",
               "--load-filaments", str(filament),
               "--slice", "0", "--arrange", "1", "--outputdir", str(scratch), str(model)]
    print("Slicing the nine-block tower with stock Elegoo CC2 profiles...", flush=True)
    with (OUT / f"slice{suffix}.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=300)
    assert result.returncode == 0, f"Slicer exited {result.returncode}; see {OUT / f'slice{suffix}.log'}"
    candidates = list(scratch.glob("*.gcode"))
    assert len(candidates) == 1, f"Expected one G-code in {scratch}, found {candidates}"
    validation = verify_gcode(candidates[0])
    # Only publish printable output after validation succeeds.
    OUTPUT.write_bytes(candidates[0].read_bytes())
    add_thumbnail(OUTPUT)
    report = {"slicer_version": "1.5.3.5", "model_source": rel(MODEL), "filament_preset": PRESET,
              "accel": ACCEL, "brim_mm": BRIM,
              "source_model_sha256": sha256(MODEL), "geometry": geometry,
              "profiles": sources, "gcode": OUTPUT.name, "gcode_sha256": sha256(OUTPUT),
              "validation": validation, "physical_print_tested": False}
    (OUT / f"verification{suffix}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, indent=2))
    print("Validated G-code:", OUTPUT)


if __name__ == "__main__":
    main()
