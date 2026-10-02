#!/usr/bin/env python3
"""
Send G-code to the CC2 over the LAN (SFTP), no USB stick.

Files land in /opt/usr/gcode/local, the same folder USB copies go to, so they
show up in the printer's file list. --start starts the print remotely.

Needs SSH on the printer: stock firmware before 02.00.02.00 (see
guides/firmware-and-ssh.md). Needs `pip install paramiko`.

Settings come from environment variables, nothing is stored in this file:
    CC2_HOST      printer IP or hostname (required, or pass --host)
    CC2_PASSWORD  root password (required). Use the published default root
                  password from the OpenCentauri docs, or your own if changed.

Usage:
    python send_cc2.py <file.gcode> [more.gcode ...] [--name NEW.gcode] [--force]
    python send_cc2.py --list
    python send_cc2.py --delete NAME.gcode
    python send_cc2.py <file.gcode> --start      # send, then start printing
    python send_cc2.py --start NAME.gcode        # start a file already on the printer

Refuses files containing M600 (the CC2 hangs on it) unless --allow-m600: before
upload, and before --start of any file, including one already on the printer (its
bytes are read back and checked, verify_remote()). M600 with an inline comment,
parameters or in lower case counts too (cc2_gcode.py, shared with slice_cc2.py).
Verifies the upload by MD5. Remote names must be plain basenames matching
[A-Za-z0-9._ -]+.gcode (no slashes, quotes, leading dot or dash).

Remote start is verified ONLY on stock OTA 01.03.02.36 with CANVAS slot 1. It fails
closed: it refuses if elegoo.log cannot be read or has no print_state line (override
with --force-start), or if /dev/pts/0 is not a character device.
"""
import argparse, hashlib, os, posixpath, re, shlex, sys, tempfile

try:
    import paramiko
except ImportError:  # keep --help working without the dependency
    paramiko = None



def _sibling(name):
    """Import tools/<name>.py next to this file as 'cc2toolkit_<name>' (no sys.path change,
    so a wrapper's own modules with the same name are never shadowed)."""
    import importlib.util
    mod = "cc2toolkit_" + name
    if mod not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            mod, os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py"))
        m = importlib.util.module_from_spec(spec)
        sys.modules[mod] = m
        spec.loader.exec_module(m)
    return sys.modules[mod]


gcode_util = _sibling("cc2_gcode")
TOOLKIT_VERSION = gcode_util.TOOLKIT_VERSION
API_VERSION = gcode_util.API_VERSION

# The public API for wrapper scripts (tools/README.md "Using the tools from your own
# scripts"). Anything else may change without an API_VERSION bump.
__all__ = ["TOOLKIT_VERSION", "API_VERSION", "DEST", "NAME_RE", "valid_name", "default_host",
           "connect", "run", "md5", "m600_count", "check_file", "verify_remote", "send",
           "upload", "list_files", "pty", "color_table", "start", "main"]

DEST = "/opt/usr/gcode/local"
# Remote names end up in shell commands and in a gcode line: allow a plain basename only.
NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._ -]*\.gcode$")


def valid_name(name):
    """Return name if it is a simple basename ending in .gcode, else exit with an error."""
    if not NAME_RE.match(name or ""):
        sys.exit(f"bad remote filename {name!r}: use letters, digits, . _ - and space "
                 "only, no slashes or quotes, not starting with a dot or dash, "
                 "ending in .gcode")
    return name


def env_or_exit(name, hint):
    v = os.environ.get(name)
    if not v:
        sys.exit(f"{name} is not set. {hint}")
    return v


def default_host():
    return os.environ.get("CC2_HOST")


def connect(host):
    if paramiko is None:
        sys.exit("paramiko is missing: pip install paramiko")
    if not host:
        sys.exit("CC2_HOST is not set (and no --host given). Set it to the printer's "
                 "IP, e.g. export CC2_HOST=<printer-ip>")
    pw = env_or_exit("CC2_PASSWORD", "Set it to the printer's root password (the "
                     "published default is in the OpenCentauri docs).")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username="root", password=pw, timeout=10,
              look_for_keys=False, allow_agent=False)
    return c


def run(c, cmd):
    _, o, e = c.exec_command(cmd, timeout=60)
    return o.read().decode(), e.read().decode()


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def m600_count(path):
    """M600 lines in a local G-code, any form (inline comment, parameters, lower case):
    the same tokenizer slice_cc2 strips with (cc2_gcode.py)."""
    return gcode_util.m600_count_file(path)


def check_file(path, allow_m600):
    if not os.path.isfile(path):
        sys.exit(f"{path}: no such file")
    n = m600_count(path)
    if n and not allow_m600:
        sys.exit(f"{path}: {n} M600 line(s) - the CC2 hangs on them. "
                 "Strip them or pass --allow-m600.")


def verify_remote(c, name, allow_m600=False, local=None, checks=()):
    """Check the bytes of printer file NAME right before starting it, whoever sliced it.

    The printer file's md5 is read first. If `local` is a file with that same md5 it is
    checked instead of downloading; otherwise the printer file is downloaded to a temp
    file and its md5 must match. Refuses (exits) on M600 unless allow_m600, then runs
    each `checks` callable as check(label, path_with_the_same_bytes); a check refuses by
    exiting. Returns the verified md5."""
    path = posixpath.join(DEST, valid_name(name))
    remote_md5 = (run(c, f"md5sum {shlex.quote(path)}")[0].split() or [""])[0]
    if not re.fullmatch(r"[0-9a-f]{32}", remote_md5):
        sys.exit(f"not on printer: {path}")
    tmp = None
    if local and os.path.isfile(local) and md5(local) == remote_md5:
        src, label = local, f"{name} (= {local}, same md5)"
    else:
        fd, tmp = tempfile.mkstemp(prefix="cc2_verify_", suffix=".gcode")
        os.close(fd)
        sftp = c.open_sftp()
        try:
            sftp.get(path, tmp)
        finally:
            sftp.close()
        if md5(tmp) != remote_md5:
            os.remove(tmp)
            sys.exit(f"{name}: the printer file changed while it was read, not starting")
        src, label = tmp, f"{name} (read from the printer)"
    try:
        n = m600_count(src)
        if n and not allow_m600:
            sys.exit(f"{label}: {n} M600 line(s) - the CC2 hangs on them. Not starting; "
                     "re-slice (slice_cc2 strips them) or pass --allow-m600.")
        for check in checks:
            check(label, src)
    finally:
        if tmp:
            os.remove(tmp)
    print(f"verified {name}: md5 {remote_md5}" + (", no M600" if not n else f", {n} M600 allowed"))
    return remote_md5


# ---- send -------------------------------------------------------------------

def send(c, sftp, path, name, force, allow_m600, skip_same=False):
    """Upload one file. Returns its md5 when uploaded, None when skipped.
    skip_same: if the remote file exists with the same md5, skip it instead of
    refusing (without force an existing different file is still refused)."""
    check_file(path, allow_m600)
    valid_name(name)
    remote = posixpath.join(DEST, name)
    try:
        sftp.stat(remote)
        if not force:
            if skip_same and run(c, f"md5sum {shlex.quote(remote)}")[0].split()[:1] == [md5(path)]:
                print(f"{name} already on printer (same md5), not re-sending")
                return None
            sys.exit(f"{name} already on printer"
                     + (" (different file)" if skip_same else "")
                     + ". Pass --force to overwrite.")
    except FileNotFoundError:
        pass
    size = os.path.getsize(path)
    last = [-1]

    def progress(done, total):
        pct = done * 100 // max(total, 1)
        if pct // 10 != last[0]:
            last[0] = pct // 10
            print(f"  {pct:3d}%", end="\r", flush=True)

    tmp = remote + ".part"
    sftp.put(path, tmp, callback=progress)
    print()
    remote_md5 = run(c, f"md5sum {shlex.quote(tmp)}")[0].split()[0]
    local_md5 = md5(path)
    if remote_md5 != local_md5:
        run(c, f"rm -f {shlex.quote(tmp)}")
        sys.exit(f"{name}: MD5 mismatch after upload, removed. Retry.")
    run(c, f"mv {shlex.quote(tmp)} {shlex.quote(remote)} && sync")
    print(f"sent {name} ({size / 1e6:.1f} MB, md5 ok) -> {remote}")
    return local_md5


def upload(pairs, host=None, force=False, allow_m600=False):
    """Send [(local_path, remote_name), ...] in one SSH session."""
    for path, name in pairs:  # refuse before connecting
        check_file(path, allow_m600)
        valid_name(name)
    c = connect(host or default_host())
    try:
        sftp = c.open_sftp()
        for path, name in pairs:
            send(c, sftp, path, name, force, allow_m600)
        sftp.close()
    finally:
        c.close()


def list_files(c):
    out, _ = run(c, f"cd {shlex.quote(DEST)} && ls -lt | grep '^-'")
    for l in out.splitlines():
        p = l.split(None, 8)
        print(f"{int(p[4]) / 1e6:7.1f} MB  {p[5]} {p[6]} {p[7]}  {p[8]}")
    print(run(c, "df -h /opt/usr | tail -1")[0].split()[3], "free")


def pty(c, lines):
    """Type gcode lines into elegoo_printer's gcode pty /dev/pts/0, 1 s apart.
    Nothing reads the pty's output: check results in /opt/usr/logs/elegoo.log."""
    run(c, "; ".join(f"printf '%s\\n' {shlex.quote(l)} > /dev/pts/0; sleep 1" for l in lines))


def color_table(c, path, slot_map):
    """CANVAS_SET_COLOR_TABLE line mapping every tool the G-code uses (T0..T3) to a
    CANVAS slot: slot_map {tool: slot 1-4}, missing tools default to tool N -> slot N+1.
    Colours come from the G-code's filament_colour line."""
    q = shlex.quote(path)
    tools = sorted({int(t) for t in run(c, f"grep -o '^T[0-9]' {q} | sort -u | tr -d T")[0].split()}) or [0]
    cols = run(c, f"grep -m1 '^; filament_colour =' {q}")[0].split("=", 1)[-1].strip().split(";")
    chans, colours = [], []
    for t in tools:
        slot = slot_map.get(t, t + 1)
        if not 1 <= slot <= 4:
            sys.exit(f"T{t}: slot {slot} is not 1-4")
        chans.append(str(slot - 1))
        col = cols[t] if t < len(cols) and re.match(r"#[0-9A-Fa-f]{6}", cols[t]) else "#FFFFFF"
        colours.append(hex(int(col[1:7], 16)))
    return (f"CANVAS_SET_COLOR_TABLE T={','.join(map(str, tools))} "
            f"CHANNEL={','.join(chans)} COLOR={','.join(colours)}")


def start(c, name, force_start=False, slot_map=None, level=True):
    """Start a print by typing the touchscreen's own start sequence (copied from
    gui.log) into elegoo_printer's gcode pty /dev/pts/0.
    Verified on stock OTA 01.03.02.36 with CANVAS slot 1 only. Fails closed: refuses
    if the state log is unreadable (unless force_start) or the pty is not a char device.

    slot_map: None (default) = single colour, CANVAS slot 1. A dict {tool: slot 1-4}
    (may be empty) maps every tool the G-code uses instead, see color_table().
    level: True (default) runs the G-code's bed levelling (BED_MESH_CALIBRATE, ~5 min);
    False skips it and uses the saved mesh, like the screen's levelling toggle off."""
    valid_name(name)
    state = run(c, "grep -a 'handle_print_state print_state:' /opt/usr/logs/elegoo.log | tail -1")[0]
    if "print_state:" not in state:
        msg = "cannot read a print_state line from /opt/usr/logs/elegoo.log"
        if not force_start:
            sys.exit(f"{msg}: cannot tell if the printer is idle, refusing to start "
                     "(pass --force-start to override)")
        print(f"warning: {msg}, starting anyway (--force-start)")
    elif "print_state:printing" in state or "print_state:paused" in state:
        sys.exit(f"printer busy, not starting: {state.strip()[-60:]}")
    if run(c, "[ -c /dev/pts/0 ] && echo ok")[0].strip() != "ok":
        sys.exit("/dev/pts/0 is missing or not a character device (different firmware?), "
                 "refusing to start")
    path = posixpath.join(DEST, name)
    if run(c, f"[ -f {shlex.quote(path)} ] && echo ok")[0].strip() != "ok":
        sys.exit(f"not on printer: {path}")
    table = ("CANVAS_SET_COLOR_TABLE T=0 CHANNEL=0 COLOR=0xffffff" if slot_map is None
             else color_table(c, path, slot_map))
    if slot_map is not None:
        print("  " + table)
    lines = ["PRINT_SURFACE_SET PLANE=0",
             f"BED_MESH_CALIBRATE_SET EXECUTE_CALIBRATE_FROM_SLICER={int(bool(level))}",
             "USED_CANVAS_DEV USED_CANVAS=1",
             table,
             f'SDCARD_PRINT_FILE FILENAME="local/{name}" SLICE_CFG_MODEL=1 AUTO_DETECT=0']
    count = "grep -ac 'cmd_SDCARD_PRINT_FILE' /opt/usr/logs/elegoo.log"
    before = int(run(c, count)[0].strip() or 0)
    pty(c, lines)
    out = run(c, f"sleep 3; {count}; grep -a 'cmd_SDCARD_PRINT_FILE' /opt/usr/logs/elegoo.log | tail -1")[0]
    first, _, last = out.partition("\n")
    # only a NEW cmd_SDCARD_PRINT_FILE line (count grew since before we sent) counts
    if int(first.strip() or 0) <= before or name not in last:
        sys.exit("start not confirmed by a new cmd_SDCARD_PRINT_FILE line in elegoo.log, "
                 "check the screen")
    print(f"started {name}")


def main():
    ap = argparse.ArgumentParser(description="Send G-code to the CC2 over SSH "
                                 "(needs CC2_HOST and CC2_PASSWORD env vars)")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--name", help="remote filename (single file only)")
    ap.add_argument("--host", default=default_host(),
                    help="printer IP/hostname (default: $CC2_HOST)")
    ap.add_argument("--force", action="store_true", help="overwrite existing file")
    ap.add_argument("--allow-m600", action="store_true")
    ap.add_argument("--list", action="store_true", help="list files on the printer")
    ap.add_argument("--delete", metavar="NAME", help="delete a file on the printer")
    ap.add_argument("--force-start", action="store_true",
                    help="with --start: start even if the printer state cannot be read "
                         "from elegoo.log (not recommended)")
    ap.add_argument("--start", nargs="?", const=True, metavar="NAME",
                    help="start a print: NAME on the printer, or the one file just sent "
                         "(verified only on OTA 01.03.02.36, CANVAS slot 1)")
    a = ap.parse_args()

    if not (a.files or a.list or a.delete or a.start):
        ap.error("give a file, --list, --delete or --start")
    if a.start is True and len(a.files) != 1:
        ap.error("bare --start needs exactly one file (or --start NAME)")
    if a.name and len(a.files) != 1:
        ap.error("--name needs exactly one file")
    # one action per run (files + bare --start = send then start); refused before connecting
    acts = [n for n, on in (("files", bool(a.files)), ("--start NAME", a.start not in (None, True)),
                            ("--list", a.list), ("--delete", bool(a.delete))) if on]
    if len(acts) > 1:
        ap.error("one action per run, got " + " + ".join(acts) + " (only FILE --start combines)")
    if a.force_start and not a.start:
        ap.error("--force-start needs --start")

    for f in a.files:  # refuse before connecting
        check_file(f, a.allow_m600)

    def gname(n):
        return valid_name(n if n.lower().endswith(".gcode") else n + ".gcode")

    if a.delete:
        a.delete = valid_name(a.delete)
    for f in a.files:
        gname(a.name or os.path.basename(f))
    if a.start and a.start is not True:
        gname(a.start)

    c = connect(a.host)
    try:
        if a.delete:
            out, err = run(c, f"rm -v {shlex.quote(posixpath.join(DEST, a.delete))} && sync")
            print(out.strip() or err.strip())
        if a.files:
            sftp = c.open_sftp()
            for f in a.files:
                name = gname(a.name or os.path.basename(f))
                send(c, sftp, f, name, a.force, a.allow_m600)
            sftp.close()
        if a.start:
            name = gname(a.start if a.start is not True else (a.name or os.path.basename(a.files[0])))
            # check the bytes about to print, also for files that were already on the printer
            verify_remote(c, name, a.allow_m600, local=a.files[0] if a.files else None)
            start(c, name, a.force_start)
        if a.list:
            list_files(c)
    finally:
        c.close()


if __name__ == "__main__":
    main()
