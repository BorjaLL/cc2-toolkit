"""Offline regression tests for tools/ (no slicer, no printer, no extra packages).

Run from the toolkit folder:  python -m unittest discover -s tests
"""
import contextlib, hashlib, importlib.util, io, json, os, shutil, sys, tempfile, unittest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


def load(name):
    """Import tools/<name>.py the way wrappers do (module 'cc2toolkit_<name>')."""
    mod = "cc2toolkit_" + name
    if mod not in sys.modules:
        spec = importlib.util.spec_from_file_location(mod, os.path.join(TOOLS, name + ".py"))
        m = importlib.util.module_from_spec(spec)
        sys.modules[mod] = m
        spec.loader.exec_module(m)
    return sys.modules[mod]


gc = load("cc2_gcode")
sc = load("slice_cc2")
snd = load("send_cc2")

M600_FORMS = ["M600", "M600\n", "  M600  ", "m600", "M600 ; filament change", "M600;pause",
              "M600 B1", "M600 X10 Y10", "M600B1", "N12 M600*34", "M600\r\n", b"M600\r\n"]
NOT_M600 = [";M600", "; M600 removed", "M6000", "M600.1", "M600_CUSTOM", "G1 X1 ; M600",
            "M60", "", "   ", "; comment only", "T0"]


class FakeConn:
    """paramiko SSHClient stand-in: md5sum and SFTP get over an in-memory file table."""

    def __init__(self, files):
        self.files, self.cmds = dict(files), []

    def exec_command(self, cmd, timeout=None):
        self.cmds.append(cmd)
        out = ""
        if cmd.startswith("md5sum "):
            data = self.files.get(cmd.rsplit("/", 1)[-1].strip("'"))
            out = f"{hashlib.md5(data).hexdigest()}  file\n" if data is not None else ""
        return None, io.BytesIO(out.encode()), io.BytesIO(b"")

    def open_sftp(self):
        conn = self

        class Sftp:
            def get(self, remote, local):
                with open(local, "wb") as f:
                    f.write(conn.files[remote.rsplit("/", 1)[-1]])

            def close(self):
                pass
        return Sftp()


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class TestM600(unittest.TestCase):
    def test_variants_detected(self):
        for s in M600_FORMS:
            self.assertTrue(gc.is_m600(s), s)

    def test_non_m600(self):
        for s in NOT_M600:
            self.assertFalse(gc.is_m600(s), s)

    def test_strip_keeps_text_and_counts(self):
        lines = ["G1 X1\n", "M600 ; pause\n", "m600 B1\n", ";M600 already a comment\n"]
        self.assertEqual(gc.strip_m600(lines), 2)
        self.assertEqual(gc.m600_lines(lines), [])
        self.assertIn("M600 ; pause", lines[1])
        self.assertTrue(lines[1].startswith(";"))

    def test_send_refuses_inline_forms(self):
        with tempfile.TemporaryDirectory() as d:
            for i, form in enumerate(["M600 ; x", "m600", "M600 B1"]):
                p = os.path.join(d, f"f{i}.gcode")
                with open(p, "w") as f:
                    f.write(f"G1 X1\n{form}\nG1 X2\n")
                with self.assertRaises(SystemExit):
                    snd.check_file(p, allow_m600=False)
                snd.check_file(p, allow_m600=True)  # override still works


class TestVerifyRemote(unittest.TestCase):
    def test_downloads_and_refuses_m600(self):
        c = FakeConn({"a.gcode": b"G1\nM600 ; pause\n"})
        with quiet(), self.assertRaises(SystemExit) as e:
            snd.verify_remote(c, "a.gcode")
        self.assertIn("M600", str(e.exception.code))

    def test_clean_file_runs_checks_on_same_bytes(self):
        data = b"G1 X1\n;M600 comment\n"
        c = FakeConn({"b.gcode": data})
        seen = []

        def check(label, path):
            with open(path, "rb") as f:
                seen.append(f.read())
        with quiet():
            md5 = snd.verify_remote(c, "b.gcode", checks=[check])
        self.assertEqual(md5, hashlib.md5(data).hexdigest())
        self.assertEqual(seen, [data])

    def test_local_copy_used_only_when_md5_matches(self):
        data = b"G1 X1\n"
        with tempfile.TemporaryDirectory() as d:
            same, other = os.path.join(d, "same.gcode"), os.path.join(d, "other.gcode")
            write(same, data)
            write(other, b"G1 X2\nM600\n")
            paths = []
            c = FakeConn({"c.gcode": data})
            with quiet():
                snd.verify_remote(c, "c.gcode", local=same, checks=[lambda l, p: paths.append(p)])
                snd.verify_remote(c, "c.gcode", local=other, checks=[lambda l, p: paths.append(p)])
            self.assertEqual(paths[0], same)
            self.assertNotEqual(paths[1], other)  # md5 differs: the printer bytes are read

    def test_missing_file(self):
        with quiet(), self.assertRaises(SystemExit):
            snd.verify_remote(FakeConn({}), "nope.gcode")


class FakeSlicer:
    """Stands in for the slicer CLI (subprocess.call) and its install."""

    def __init__(self, root, rc=0, plates=1, body="G1 X1\nM600 ; designer pause\n"):
        self.root, self.rc, self.plates, self.body, self.calls = root, rc, plates, body, []
        prof = os.path.join(root, "profiles")
        os.makedirs(prof)
        self.files = {}
        for kind, extra in (("machine", {}), ("process", {"default_acceleration": "10000"}),
                            ("filament", {"filament_flow_ratio": ["0.98"],
                                          "additional_cooling_fan_speed": ["0"],
                                          "fan_min_speed": ["50"]})):
            p = os.path.join(prof, kind + ".json")
            with open(p, "w") as f:
                json.dump(dict({"name": "fake " + kind}, **extra), f)
            self.files[kind] = p
        self.exe = os.path.join(root, "slicer.exe")
        write(self.exe, b"")

    def __enter__(self):
        self.saved = {k: getattr(sc, k) for k in ("EXE", "MACHINE", "PROCESS", "FILAMENT", "VENDOR")}
        self.saved_call = sc.subprocess.call
        sc.EXE, sc.MACHINE, sc.VENDOR = self.exe, self.files["machine"], self.root
        sc.PROCESS = {"0.20": self.files["process"]}
        sc.FILAMENT = {k: self.files["filament"] for k in self.saved["FILAMENT"]}
        sc.subprocess.call = self.call
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(sc, k, v)
        sc.subprocess.call = self.saved_call

    def call(self, cmd, stdout=None, stderr=None):
        self.calls.append(cmd)
        out = cmd[cmd.index("--outputdir") + 1]
        for n in range(1, self.plates + 1):
            with open(os.path.join(out, f"plate_{n}.gcode"), "w") as f:
                f.write(self.body)
        if stdout:
            stdout.write("fake slicer\n" + ("error: something failed\n" if self.rc else ""))
        return self.rc


def run_main(argv, hooks=None):
    with quiet():
        try:
            sc.main(argv, hooks)
        except SystemExit as e:
            return e.code
    return None


class TestSliceOutputs(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.out = os.path.join(self.d, "out")
        os.makedirs(self.out)
        self.model = os.path.join(self.d, "m.stl")
        write(self.model, b"")
        self.old = os.path.join(self.out, "plate_9.gcode")  # stale, from an earlier run
        with open(self.old, "w") as f:
            f.write("M600\n")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def result(self):
        with open(os.path.join(self.out, sc.RESULT_FILE), encoding="utf-8") as f:
            return json.load(f)

    def test_stale_gcode_ignored(self):
        seen = []
        hooks = type("H", (), {"finish": staticmethod(lambda a, plates, rc: seen.extend(plates) or plates)})
        with FakeSlicer(self.d):
            code = run_main([self.model, "--out", self.out], hooks)
        self.assertEqual(code, sc.EXIT_OK)
        self.assertEqual([os.path.basename(g) for g, _ in seen], ["plate_1.gcode"])
        self.assertEqual(read(self.old), "M600\n")  # not stripped, not touched
        r = self.result()
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["stale_in_out"], ["plate_9.gcode"])
        self.assertEqual([o["plate"] for o in r["outputs"]], ["plate_1"])
        self.assertEqual(r["outputs"][0]["m600_stripped"], 1)
        self.assertFalse(gc.m600_lines(read(os.path.join(self.out, "plate_1.gcode")).splitlines()))
        self.assertFalse([p for p in os.listdir(self.out) if p.startswith("_run-")])

    def test_slicer_failure_keeps_nothing(self):
        called = []
        hooks = type("H", (), {"finish": staticmethod(lambda a, p, rc: called.append(1) or p)})
        with FakeSlicer(self.d, rc=4294967290):
            code = run_main([self.model, "--out", self.out], hooks)
        self.assertEqual(code, sc.EXIT_SLICER_FAILED)
        self.assertEqual(called, [])
        self.assertFalse(os.path.exists(os.path.join(self.out, "plate_1.gcode")))
        r = self.result()
        self.assertEqual((r["status"], r["slicer_exit_signed"]), ("slicer_failed", -6))
        self.assertTrue(r["diagnostics"])
        self.assertNotIn("slicer_exit_hint", r)

    def test_arrange_failure_hint(self):
        # -21: a 255 mm part on the 256 mm CC2 bed with its exclude zone (2026-10-08)
        with FakeSlicer(self.d, rc=4294967275), quiet():
            code = run_main([self.model, "--out", self.out])
        self.assertEqual(code, sc.EXIT_SLICER_FAILED)
        r = self.result()
        self.assertEqual(r["slicer_exit_signed"], -21)
        self.assertIn("--no-arrange", r["slicer_exit_hint"])
        self.assertIn("already --no-arrange", sc.slicer_exit_hint(-50, no_arrange=True))
        self.assertIsNone(sc.slicer_exit_hint(-6))

    def test_no_output(self):
        with FakeSlicer(self.d, plates=0):
            code = run_main([self.model, "--out", self.out])
        self.assertEqual(code, sc.EXIT_NO_OUTPUT)

    def test_hook_refusal_recorded(self):
        def finish(a, plates, rc):
            a.checks.append({"check": "policy", "ok": False})
            sys.exit(3)
        with FakeSlicer(self.d):
            code = run_main([self.model, "--out", self.out],
                            type("H", (), {"finish": staticmethod(finish)}))
        self.assertEqual(code, sc.EXIT_REFUSED)
        r = self.result()
        self.assertEqual(r["status"], "refused")
        self.assertEqual(r["checks"], [{"check": "policy", "ok": False}])

    def test_name_rename_does_not_touch_stale(self):
        with FakeSlicer(self.d, plates=2):
            code = run_main([self.model, "--out", self.out, "--name", "box"])
        self.assertEqual(code, sc.EXIT_OK)
        names = sorted(os.listdir(self.out))
        self.assertIn("box_plate1.gcode", names)
        self.assertIn("box_plate2.gcode", names)
        self.assertEqual(read(self.old), "M600\n")


def tower(r=10.0, h=10.0, cap=2.0, n=24):
    """Closed mesh: vertical cylinder of height h with a shallow cone cap (triangles)."""
    import math
    ring = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    tris = []
    for i in range(n):
        (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % n]
        a, b, c, d = (x0, y0, 0.0), (x1, y1, 0.0), (x1, y1, h), (x0, y0, h)
        tris += [(a, b, c), (a, c, d), ((0.0, 0.0, 0.0), b, a), (d, c, (0.0, 0.0, h + cap))]
    return tris


def ascii_stl(tris):
    body = "".join("facet normal 0 0 0\nouter loop\n" + "".join(f"vertex {x} {y} {z}\n" for x, y, z in t)
                   + "endloop\nendfacet\n" for t in tris)
    return ("solid t\n" + body + "endsolid t\n").encode()


class TestAdaptive(unittest.TestCase):
    al = load("adaptive_layers")

    def test_profile_walls_thick_cap_thin(self):
        p = self.al.profile(tower(), quality=0.5, layer=0.2, lo=0.08, hi=0.28, first=0.2)
        self.assertEqual(len(p) % 2, 0)
        self.assertAlmostEqual(p[-2], 12.0, places=4)   # last z = object height, else the slicer drops it
        self.assertEqual(p[:4], [0.0, 0.2, 0.2, 0.2])   # first layer kept
        hs = dict(zip(p[0::2], p[1::2]))
        walls = [h for z, h in hs.items() if 3 < z < 9]
        cap = [h for z, h in hs.items() if 10.8 < z < 11.8]  # after the 0.04 mm/layer ramp
        self.assertTrue(walls and min(walls) > 0.27)    # vertical walls: max height
        self.assertTrue(cap and max(cap) < 0.15)        # shallow cone: thinner than base
        for h0, h1 in zip(p[3:-2:2], p[5:-2:2]):        # 0.04 mm max step (the last top-up entry may jump)
            self.assertLessEqual(abs(h1 - h0), 0.04 + 1e-9)
        finer = self.al.profile(tower(), quality=0.1, layer=0.2, lo=0.08, hi=0.28, first=0.2)
        self.assertGreater(self.al.layer_stats(finer)[0], self.al.layer_stats(p)[0])
        smooth = self.al.profile(tower(), quality=0.5, smooth=5)
        self.assertAlmostEqual(smooth[-2], 12.0, places=4)
        self.assertTrue(all(0.08 <= h <= 0.28 for h in smooth[1::2]))

    def test_stl_to_adaptive_3mf(self):
        import zipfile
        d = tempfile.mkdtemp()
        try:
            src, dst = os.path.join(d, "t.stl"), os.path.join(d, "t.3mf")
            write(src, ascii_stl(tower()))
            info = self.al.write_adaptive_3mf(src, dst, 0.5)
            self.assertEqual([(o["object"], o["name"], o["height"]) for o in info], [(1, "t", 12.0)])
            with zipfile.ZipFile(dst) as z:
                txt = z.read(self.al.PROFILE_FILE).decode()
            self.assertTrue(txt.startswith("object_id=1|0.000000;0.200000;"))
            objs = self.al.read_3mf_objects(dst)             # mesh survives the round trip
            self.assertEqual(len(objs[0][2]), len(tower()))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_slice_main_passes_adaptive_copy(self):
        d = tempfile.mkdtemp()
        try:
            out, model = os.path.join(d, "out"), os.path.join(d, "tower.stl")
            write(model, ascii_stl(tower()))
            with FakeSlicer(d) as fs:
                code = run_main([model, "--out", out, "--adaptive", "--adaptive-smooth", "3"])
            self.assertEqual(code, sc.EXIT_OK)
            used = fs.calls[0][-1]
            self.assertTrue(os.path.basename(used).startswith("adaptive_1_tower") and used.endswith(".3mf"))
            self.assertTrue(os.path.isfile(used))
            with open(os.path.join(out, sc.RESULT_FILE), encoding="utf-8") as f:
                r = json.load(f)
            self.assertEqual((r["settings"]["adaptive"], r["settings"]["adaptive_smooth"]), (0.5, 3))
            self.assertEqual(r["adaptive"][0]["height"], 12.0)
            with FakeSlicer(d + "/plain") as fs:  # off by default: the model goes in unchanged
                run_main([model, "--out", out])
            self.assertEqual(fs.calls[0][-1], model)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run_main([model, "--out", out, "--adaptive", "1.5"]), 2)
        finally:
            shutil.rmtree(d, ignore_errors=True)


def png_bytes(extra=b""):
    """Minimal valid 1x1 RGBA PNG, built by hand (no Pillow); extra = tEXt payload to
    vary the length."""
    import struct, zlib

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    if extra:
        out += chunk(b"tEXt", b"k\x00" + extra)
    return out + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff")) + chunk(b"IEND", b"")


def png_chunks(data):
    """[(type, ok crc)] of a PNG."""
    import struct, zlib
    i, out = 8, []
    while i < len(data):
        n, = struct.unpack(">I", data[i:i + 4])
        kind, body = data[i + 4:i + 8], data[i + 8:i + 8 + n]
        crc, = struct.unpack(">I", data[i + 8 + n:i + 12 + n])
        out.append((kind, crc == zlib.crc32(kind + body) & 0xffffffff))
        i += 12 + n
    return out


GCODE_HEAD = ("; HEADER_BLOCK_START\n; estimated printing time = 1m\n; HEADER_BLOCK_END\n\n"
              "G28\nM83\n;TYPE:Custom\nG1 X0 Y0 E5\n")


def square_gcode(layers=5):
    """A small hollow square tower as sliced G-code (relative E)."""
    body = []
    for n in range(1, layers + 1):
        body += [f"G1 Z{0.2 * n:.1f}", ";TYPE:Outer wall", "G1 X10 Y10",
                 "G1 X30 Y10 E1", "G1 X30 Y30 E1", "G1 X10 Y30 E1", "G1 X10 Y10 E1"]
    return GCODE_HEAD + "\n".join(body) + "\n; filament_colour = #20A0FF\n"


class TestThumbnail(unittest.TestCase):
    th = load("thumbnail")

    def test_pad3_removes_base64_padding(self):
        import base64
        lens = set()
        for k in range(6):
            png = png_bytes(b"x" * k)
            lens.add(len(png) % 3)
            out = self.th.pad3(png)
            self.assertEqual(len(out) % 3, 0)
            self.assertFalse(base64.b64encode(out).endswith(b"="))
            self.assertTrue(out.startswith(png[:-12]) and out.endswith(png[-12:]))  # IEND last
            chunks = png_chunks(out)
            self.assertEqual(chunks[-1][0], b"IEND")
            self.assertTrue(all(ok for _, ok in chunks))
        self.assertEqual(lens, {0, 1, 2})  # every remainder was exercised

    def test_toolpaths_skip_custom_and_travel(self):
        segs = self.th.toolpaths(square_gcode(2).splitlines())
        self.assertEqual(len(segs), 8)                      # 4 walls x 2 layers, no purge line
        self.assertEqual(self.th.colour(square_gcode().splitlines()), (0x20, 0xA0, 0xFF))

    @unittest.skipUnless(load("thumbnail").have_pillow(), "Pillow not installed")
    def test_add_inserts_unpadded_block_once(self):
        import base64
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "t.gcode")
            write(p, square_gcode().encode())
            self.assertTrue(self.th.add(p))
            lines = read(p).splitlines()
            self.assertEqual(lines[2], "; HEADER_BLOCK_END")  # block right after the header
            s = lines.index("; THUMBNAIL_BLOCK_START")
            e = lines.index("; THUMBNAIL_BLOCK_END")
            begin = [l for l in lines[s:e] if l.startswith("; thumbnail begin ")][0]
            b64 = "".join(l[2:] for l in lines[s:e]
                          if l.startswith("; ") and not l.startswith(("; thumbnail", "; THUMB")))
            self.assertEqual(begin.split()[3:], ["144x144", str(len(b64))])
            self.assertFalse(b64.endswith("="))
            self.assertLessEqual(len(b64), self.th.B64_LIMIT)
            self.assertTrue(base64.b64decode(b64).startswith(b"\x89PNG"))
            self.assertFalse(self.th.add(p))                  # idempotent
            self.assertTrue(self.th.add(p, force=True))       # replaced, not duplicated
            self.assertEqual(read(p).count("; THUMBNAIL_BLOCK_START"), 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(load("thumbnail").have_pillow(), "Pillow not installed")
    def test_slice_thumbnail_flag(self):
        d = tempfile.mkdtemp()
        try:
            out, model = os.path.join(d, "out"), os.path.join(d, "m.stl")
            write(model, b"")
            with FakeSlicer(d, body=square_gcode()):
                self.assertEqual(run_main([model, "--out", out, "--thumbnail"]), sc.EXIT_OK)
            self.assertIn("; THUMBNAIL_BLOCK_START", read(os.path.join(out, "plate_1.gcode")))
            with FakeSlicer(d + "/plain", body=square_gcode()):
                run_main([model, "--out", out + "2"])          # off by default
            self.assertNotIn("THUMBNAIL", read(os.path.join(out + "2", "plate_1.gcode")))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestAccelCap(unittest.TestCase):
    ca = load("check_accel")

    def test_peak_from_commands_and_settings(self):
        pk = self.ca.peak_accel
        self.assertEqual(pk(["G1 X1", "; M204 S99999", "M204 S3000 ; walls"])[0], 3000)
        self.assertEqual(pk(["M204 P2000 T6000"]), (6000, "M204 T6000 (line 1)"))
        self.assertEqual(pk(["SET_VELOCITY_LIMIT ACCEL=7000 ACCEL_TO_DECEL=3500"])[0], 7000)
        # slicer settings: 0 = default, N% of default, machine_max_* ignored
        s = ["M204 S1000", "; default_acceleration = 4000",
             "; outer_wall_acceleration = 0", "; machine_max_acceleration_x = 20000"]
        self.assertEqual(pk(s)[0], 4000)
        self.assertEqual(pk(s + ["; travel_acceleration = 150%"]),
                         (6000, "; travel_acceleration = 150% (line 5)"))
        self.assertEqual(pk(["; top_surface_acceleration = 9000,5000"])[0], 9000)
        self.assertEqual(pk(["G1 X1", "; just a comment"]), (0, None))
        self.assertEqual(pk([b"M204 S2500\n"])[0], 2500)

    def test_max_accel_exit_codes(self):
        d = tempfile.mkdtemp()
        try:
            p, empty = os.path.join(d, "a.gcode"), os.path.join(d, "b.gcode")
            write(p, b"M204 S5000\nG1 X1\n; default_acceleration = 5000\n")
            write(empty, b"G1 X1\n")
            with quiet(), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.ca.main([p, "--max-accel", "5000"]), 0)
                self.assertEqual(self.ca.main([p, "--max-accel", "4999"]), self.ca.EXIT_OVER_CAP)
                self.assertEqual(self.ca.main([empty, "--max-accel", "5000"]), self.ca.EXIT_NO_ACCEL)
                self.assertEqual(self.ca.main([p, "--x", "9000", "--y", "4000",
                                               "--max-accel", "4000"]), self.ca.EXIT_OVER_CAP)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestNightProfile(unittest.TestCase):
    def test_night3_out_of_the_authors_ringing_band(self):
        n3 = sc.ACCEL["night3"]
        for k in ("outer_wall_speed", "inner_wall_speed", "sparse_infill_speed",
                  "internal_solid_infill_speed", "top_surface_speed"):
            self.assertFalse(50 <= float(n3[k]) <= 62.5, k)
        self.assertEqual(n3["travel_speed_z"], "5")


class ShellConn:
    """Runs send_cc2's state-log command with a local sh, the log folder swapped for a temp
    dir; every other command answers nothing (so start() stops at the pty check)."""

    def __init__(self, logs):
        self.logs = logs.replace(os.sep, "/")

    def exec_command(self, cmd, timeout=None):
        import subprocess
        out = ""
        if "handle_print_state" in cmd:
            out = subprocess.run([shutil.which("sh"), "-c", cmd.replace("/opt/usr/logs", self.logs)],
                                 capture_output=True, text=True).stdout
        return None, io.BytesIO(out.encode()), io.BytesIO(b"")


@unittest.skipUnless(shutil.which("sh"), "needs a POSIX sh to run the printer-side command")
class TestStateLogRotation(unittest.TestCase):
    IDLE = "[2026-10-01 10:00:00.000] handle_print_state print_state:standby\n"
    BUSY = "[2026-10-01 09:00:00.000] handle_print_state print_state:printing\n"

    def start(self, files):
        d = tempfile.mkdtemp()
        try:
            for name, text in files.items():
                with open(os.path.join(d, name), "w") as f:
                    f.write("other line\n" + text)
            with quiet(), self.assertRaises(SystemExit) as e:
                snd.start(ShellConn(d), "a.gcode")
            return str(e.exception.code)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_rotated_log_is_read(self):
        # elegoo.log just rotated: no state line in it, the idle state is in elegoo.1.log
        self.assertIn("/dev/pts/0", self.start({"elegoo.log": "", "elegoo.1.log": self.IDLE}))
        self.assertIn("printer busy", self.start({"elegoo.log": "", "elegoo.1.log": self.BUSY}))

    def test_current_log_wins(self):
        self.assertIn("/dev/pts/0", self.start({"elegoo.log": self.IDLE, "elegoo.1.log": self.BUSY}))

    def test_no_state_line_refuses(self):
        self.assertIn("cannot read", self.start({"elegoo.log": ""}))


class TestApi(unittest.TestCase):
    def test_all_names_exist(self):
        for m in (sc, snd, load("thumbnail")):
            for k in m.__all__:
                self.assertTrue(hasattr(m, k), f"{m.__name__}.{k}")
        self.assertEqual(sc.API_VERSION, gc.API_VERSION)


if __name__ == "__main__":
    unittest.main()
