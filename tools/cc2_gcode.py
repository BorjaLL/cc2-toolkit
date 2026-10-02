"""Shared G-code helpers for slice_cc2.py and send_cc2.py.

One command tokenizer is used both to strip M600 after slicing and to refuse it
before upload or start, so the two can never disagree about what counts as M600.
"""
import re

# Optional line number (N123), then the command word. Klipper upper-cases commands,
# so m600 runs too. M600 must not be followed by a digit or a dot (M6000 is not M600);
# parameters may follow with or without a space (M600 B1, M600B1).
_CMD = re.compile(r"^\s*(?:N\d+\s+)?([A-Za-z]\d+(?:\.\d+)?(?![\d._])|[A-Za-z_][A-Za-z0-9_]*)")


def code_part(line):
    """The command part of a G-code line: comment (';' to end) and checksum (*NN) removed."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", "replace")
    code = line.split(";", 1)[0]
    star = code.find("*")
    if star >= 0:
        code = code[:star]
    return code.strip()


def command(line):
    """Upper-case command word of a G-code line ('M600', 'G1', 'SET_VELOCITY_LIMIT'),
    or '' for blank and comment-only lines."""
    m = _CMD.match(code_part(line))
    return m.group(1).upper() if m else ""


def is_m600(line):
    """True if the line runs M600 (filament change), whatever the case, inline comment,
    line number or parameters: 'M600', 'm600 ; pause', 'M600 B1', 'N5 M600*12', 'M600B1'.
    False for comments (';M600'), 'M6000' and anything else."""
    return command(line) == "M600"


def m600_lines(lines):
    """1-based line numbers of the M600 lines in an iterable of lines (str or bytes)."""
    return [n for n, l in enumerate(lines, 1) if is_m600(l)]


def m600_count_file(path):
    """Number of M600 lines in a G-code file."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return len(m600_lines(f))


def strip_m600(lines, tag="slice_cc2"):
    """Comment out every M600 line in a list of lines (in place). Returns how many.
    The original text is kept after the marker so it stays readable."""
    n = 0
    for i, l in enumerate(lines):
        if is_m600(l):
            lines[i] = f";M600 removed by {tag} (CC2 hangs on it): {l.strip()}\n"
            n += 1
    return n
