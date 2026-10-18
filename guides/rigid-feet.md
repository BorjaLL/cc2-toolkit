# CC2 feet: printed rigid feet vs Elegoo anti-vibration feet (tested 2026-10-18)

The rigid foot: a solid PLA+ cup, 40 mm across x 18 mm, 32 mm bore 13 mm
deep that slips over the stock foot (interface from Printables 1579825).
Older notes on it: git history of this file.

## Result: the soft feet won

After Reddit replies said soft feet are there for a reason, I ran the same dry
head-move tests (no heat, no filament) on my rigid feet and on Elegoo's
anti-vibration feet. Phones: one taped on top of the printer (acceleration),
one beside it and one in the next room (sound). Printer on a stone slab that
sits on 9 half tennis balls. Dry head moves only: print quality was not compared.

Everyday moves (lines 40-500 mm/s, accel 1000-20000, diagonals, circles,
zigzag, z-hops, random travel):

![everyday moves](img/feet-test-everyday-moves.png)

Violent test (back-and-forth at 2.5-7 cycles per second, accel 20000, aimed at
the printer's own rocking range; it shook hard on both sets of feet):

![violent test](img/feet-test-violent.png)

Chart caveat: in the violent chart the z-hop bars and the "after each stop"
panel are not reliable (the second pass of each run lines up one block late).
The table uses only numbers that do not depend on that alignment.

| | Elegoo AV feet | Rigid PLA feet |
|---|---|---|
| Violent: shake at the top of the printer (median of each pass) | 1.67 m/s2 (two runs: 1.67, 1.70) | 2.00 m/s2 |
| Violent: estimated sway, whole run (1-50 Hz) | 2.7-2.9 mm | 2.6 mm |
| Everyday: estimated sway, whole run | 0.45-0.47 mm | 0.42 mm (two installs) |
| Everyday: shake while moving / after stops | about equal | about equal |
| Rocking frequency | about 3-3.3 Hz | about 3.7-4.7 Hz |
| Noise beside / next room | within about 1 dB on average | within about 1 dB on average |

- Under hard back-and-forth the Elegoo feet shake about 15-20% less at the
  top of the printer. That is the one difference that held up.
- How far the printer sways is a draw: the rigid feet raise the rocking
  frequency, they do not make the rock smaller.
- On everyday moves the two are a draw; the rigid feet sway very slightly less.
- Noise: no reliable winner.
- Likely cause of the rocking (not tested): the printer and slab swaying
  together on the tennis balls. Removing the balls is the next test.
- My pick: Elegoo's feet, with modest confidence (slightly less shake under
  hard moves, nothing worse). An earlier measurement (2026-09-30, slab on the
  floor on 12 half tennis balls) had the rigid feet moving the sway from about
  6.5 Hz to about 19 Hz; that did not repeat on the current setup and is
  unexplained.
- Not tested: print quality, and whether the printer's 20000 accel limit
  still prints clean on soft feet.
- Re-run input shaping after any foot change (`find-your-numbers.md`).
