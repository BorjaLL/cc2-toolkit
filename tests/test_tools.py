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


class TestApi(unittest.TestCase):
    def test_all_names_exist(self):
        for m in (sc, snd):
            for k in m.__all__:
                self.assertTrue(hasattr(m, k), f"{m.__name__}.{k}")
        self.assertEqual(sc.API_VERSION, gc.API_VERSION)


if __name__ == "__main__":
    unittest.main()
