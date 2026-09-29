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
not apply it (the stock printer.cfg sets max_accel = 20000 and the slicer's
SET_VELOCITY_LIMIT / M204 commands set the real value per feature). This
script only tells you where your G-code goes above your own estimate, so you
know what to test. It does not say a print will fail.

Usage:
    python check_accel.py --log elegoo.log [--log elegoo.1.log] model.gcode
    python check_accel.py --x 9500 --y 5800 model.gcode    # numbers typed in

Get the log: see guides/find-your-numbers.md (SSH or USB).
"""
import argparse, collections, re, sys

FIT = re.compile(r"^\[(?P<ts>[^\]]+)\].*Fitted shaper: (?P<type>\w+) frequency = (?P<freq>[\d.]+) Hz")
SUGGEST = re.compile(r"^\[(?P<ts>[^\]]+)\].*smoothing with '(?P<type>\w+)', suggested max_accel <= (?P<acc>\d+)")
PICK = re.compile(r"^\[(?P<ts>[^\]]+)\].*Recommended shaper_type_(?P<axis>[xy]) = (?P<type>\w+), shaper_freq_\w = (?P<freq>[\d.]+) Hz")
ACCEL = re.compile(r"^(?:SET_VELOCITY_LIMIT\b.*\bACCEL=(?P<a>[\d.]+)|M204\b(?P<m204>.*))", re.I)
M204_ARG = re.compile(r"\b([SPT])([\d.]+)", re.I)
FEATURE = re.compile(r"^;\s*(?:TYPE|FEATURE):\s*(.+)", re.I)


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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("gcode")
    ap.add_argument("--log", action="append", default=[], help="elegoo.log (repeatable)")
    ap.add_argument("--x", type=int, help="X max_accel estimate, instead of --log")
    ap.add_argument("--y", type=int, help="Y max_accel estimate, instead of --log")
    a = ap.parse_args()

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


if __name__ == "__main__":
    main()
