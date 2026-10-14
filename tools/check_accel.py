#!/usr/bin/env python3
"""
Compare the accelerations in a sliced G-code with YOUR printer's input shaper
calibration.

The CC2 (Klipper-based firmware) logs, for every shaper it tries, a line like

    To avoid too much smoothing with 'mzv', suggested max_accel <= 5800 mm/sec^2

and then the shaper it picked per axis:

    Recommended shaper_type_y = mzv, shaper_freq_y = 45.200000 Hz

Klipper calls that number a smoothing estimate: above it, the shaper starts to
round corners and blur detail. It is not a hard limit, and the firmware does
not apply it (the firmware's own max_accel is far higher, 20000 on stock: it
appears in printer.cfg and in /opt/inst/printer_dsp.cfg, the file the running
process loads; the slicer's SET_VELOCITY_LIMIT / M204 commands set the real
value per feature). This script only tells you where your G-code goes above
your own estimate, so you know what to test. It does not say a print will fail.

--max-accel N is a hard check instead: it finds the highest acceleration the
G-code commands anywhere (M204 S/P/T, SET_VELOCITY_LIMIT ACCEL=, and the
slicer's '; *_acceleration = ' settings, so a --proc override cannot hide it)
and exits 3 if it is above N (4 if the G-code commands no acceleration at all,
so the firmware default would apply). Use it as a guard in your own scripts.

Usage:
    python check_accel.py --log elegoo.log [--log elegoo.1.log] model.gcode
    python check_accel.py --x 9500 --y 5800 model.gcode    # numbers typed in
    python check_accel.py --max-accel 8000 model.gcode     # your own hard cap

Get the log: see guides/find-your-numbers.md (SSH or USB).
"""
import argparse, collections, re, sys

FIT = re.compile(r"^\[(?P<ts>[^\]]+)\].*Fitted shaper: (?P<type>\w+) frequency = (?P<freq>[\d.]+) Hz")
SUGGEST = re.compile(r"^\[(?P<ts>[^\]]+)\].*smoothing with '(?P<type>\w+)', suggested max_accel <= (?P<acc>\d+)")
PICK = re.compile(r"^\[(?P<ts>[^\]]+)\].*Recommended shaper_type_(?P<axis>[xy]) = (?P<type>\w+), shaper_freq_\w = (?P<freq>[\d.]+) Hz")
ACCEL = re.compile(r"^(?:SET_VELOCITY_LIMIT\b.*\bACCEL=(?P<a>[\d.]+)|M204\b(?P<m204>.*))", re.I)
M204_ARG = re.compile(r"\b([SPT])([\d.]+)", re.I)
FEATURE = re.compile(r"^;\s*(?:TYPE|FEATURE):\s*(.+)", re.I)
SETTING = re.compile(r"^;\s*([a-z0-9_]*acceleration)\s*=\s*(.+?)\s*$")
EXIT_OVER_CAP = 3   # --max-accel: the G-code commands more than the cap
EXIT_NO_ACCEL = 4   # --max-accel: no acceleration found (the firmware default applies)


def read_log(paths):
    """Latest calibration per axis: {axis: (timestamp, type, freq, max_accel)}."""
    lines = []
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines += f.readlines()
    lines.sort(key=lambda l: l[:25])  # log lines start with [YYYY-MM-DD hh:mm:ss.mmm]
    result, block = {}, {}
    for line in lines:
        m = SUGGEST.match(line)
        if m:
            block[m["type"]] = int(m["acc"])
            continue
        m = PICK.match(line)
        if m:
            acc = block.get(m["type"])
            result[m["axis"]] = (m["ts"], m["type"], float(m["freq"]), acc)
            block = {}
    return result


def scan_gcode(path):
    """Counts of moves per accel value, and which features use each value."""
    counts, feats = collections.Counter(), collections.defaultdict(set)
    feature, accel = "start", None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = FEATURE.match(line)
            if m:
                feature = m.group(1).strip()
                continue
            m = ACCEL.match(line)
            if m:
                if m["a"]:
                    accel = float(m["a"])
                else:
                    # Klipper: M204 S<a>, or M204 P<print> T<travel> (uses the lower)
                    args = {k.upper(): float(v)
                            for k, v in M204_ARG.findall(m["m204"].split(";")[0])}
                    if "S" in args:
                        accel = args["S"]
                    elif "P" in args or "T" in args:
                        accel = min(args.get("P", 1e9), args.get("T", 1e9))
                continue
            if accel is not None and line[:3] in ("G1 ", "G0 ", "G2 ", "G3 "):
                counts[accel] += 1
                feats[accel].add(feature)
    return counts, feats


def peak_accel(lines):
    """Highest acceleration a G-code commands: (value, where), where is e.g.
    'M204 S5000 (line 12)'. (0, None) when nothing is found.

    Reads M204 S/P/T and SET_VELOCITY_LIMIT ACCEL= (comments stripped) and the slicer's
    settings block '; <key>_acceleration = <value>' (machine_max_* skipped: firmware
    limits, not commanded). A setting of 0 means "use default_acceleration", N% is taken
    of default_acceleration, a per-extruder list counts its first value."""
    best, where = 0.0, None
    settings = {}
    for n, raw in enumerate(lines, 1):
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        line = raw.strip()
        if not line:
            continue
        if line[0] == ";":
            m = SETTING.match(line)
            if m and not m.group(1).startswith("machine_"):
                settings[m.group(1)] = (m.group(2), n)
            continue
        m = ACCEL.match(line.split(";", 1)[0].strip())
        if not m:
            continue
        if m["a"]:
            if float(m["a"]) > best:
                best, where = float(m["a"]), f"SET_VELOCITY_LIMIT ACCEL={m['a']} (line {n})"
            continue
        for k, v in M204_ARG.findall(m["m204"]):
            if float(v) > best:
                best, where = float(v), f"M204 {k.upper()}{v} (line {n})"
    default = settings.get("default_acceleration")
    try:
        base = float(default[0].split(",")[0]) if default else 0.0
    except ValueError:
        base = 0.0
    for key, (val, n) in settings.items():
        val = val.split(",")[0].strip()  # per-extruder lists: first value
        try:
            if val.endswith("%"):
                v = base * float(val[:-1]) / 100
            else:
                v = float(val)
                if v == 0:  # 0 = inherit the default acceleration
                    v = base
        except ValueError:
            continue
        if v > best:
            best, where = v, f"; {key} = {val} (line {n})"
    return best, where


def peak_accel_file(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return peak_accel(f)


def check_cap(path, cap):
    """--max-accel: 0 at or under cap, EXIT_OVER_CAP above it, EXIT_NO_ACCEL when the
    G-code commands no acceleration. Prints one line."""
    peak, where = peak_accel_file(path)
    if peak == 0:
        print(f"{path}: no M204 / SET_VELOCITY_LIMIT / *_acceleration setting found, so the "
              f"firmware default would apply; cannot check against {cap}", file=sys.stderr)
        return EXIT_NO_ACCEL
    if peak > cap:
        print(f"OVER CAP: {path}: max commanded accel {peak:.0f} > {cap} ({where})",
              file=sys.stderr)
        return EXIT_OVER_CAP
    print(f"accel cap OK: {path}: max {peak:.0f} <= {cap} ({where})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("gcode")
    ap.add_argument("--log", action="append", default=[], help="elegoo.log (repeatable)")
    ap.add_argument("--x", type=int, help="X max_accel estimate, instead of --log")
    ap.add_argument("--y", type=int, help="Y max_accel estimate, instead of --log")
    ap.add_argument("--max-accel", type=int, metavar="N",
                    help="hard cap: exit 3 if the G-code commands more than N mm/s^2 anywhere "
                         "(4 if it commands no accel at all). Alone or with --log / --x / --y")
    a = ap.parse_args(argv)

    if a.max_accel is not None and not (a.log or a.x or a.y):
        return check_cap(a.gcode, a.max_accel)
    limits = {}
    if a.log:
        cal = read_log(a.log)
        if not cal:
            sys.exit("No 'Recommended shaper_type_' lines in the log. Run the input "
                     "shaper calibration first, or pass --x / --y.")
        for axis, (ts, typ, freq, acc) in sorted(cal.items()):
            print(f"{axis.upper()}: {typ} {freq:.1f} Hz, suggested max_accel <= {acc}  ({ts})")
            limits[axis] = acc
    if a.x: limits["x"] = a.x
    if a.y: limits["y"] = a.y
    if not limits:
        sys.exit("Give --log or --x/--y.")

    # A CoreXY move can be all X, all Y or both, so the lower estimate is the
    # one that matters for a mixed part.
    low = min(v for v in limits.values() if v)
    counts, feats = scan_gcode(a.gcode)
    if not counts:
        sys.exit("No SET_VELOCITY_LIMIT ACCEL= or M204 S lines in the G-code.")
    total = sum(counts.values())
    print(f"\nG-code: {a.gcode}\nLower estimate: {low} mm/s^2\n")
    print(f"{'accel':>7}  {'moves':>7}  {'share':>6}  features   (share = of moves, not print time)")
    over = 0
    for acc in sorted(counts):
        flag = "  ABOVE" if acc > low else ""
        if acc > low:
            over += counts[acc]
        fs = ", ".join(sorted(feats[acc]))[:60]
        print(f"{acc:>7.0f}  {counts[acc]:>7}  {counts[acc] / total:>6.1%}  {fs}{flag}")
    if over:
        print(f"\n{over / total:.0%} of moves run above your lower estimate. Not an error:"
              " if the print shows wobble, ringing or rounded corners, try capping"
              f" those features near {low} and compare (guides/find-your-numbers.md).")
    else:
        print("\nAll moves are at or under your estimate.")
    if a.max_accel is not None:
        print()
        return check_cap(a.gcode, a.max_accel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
