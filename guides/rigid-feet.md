# CC2 rigid feet (parked 2026-09-28)

Status: researched, nothing bought or printed yet. Treat the candidates as
leads, not tested fixes.

Problem: on a floor slab the CC2 rocks on its soft stock silicone feet. Soft
feet protect a table surface; on a slab that buys nothing, so the fix is stiff
feet. Background on the shake problem: `tuning.md` ("Hardware / one-time").

Constraints:
- Keep at least stock height: the CC2 pulls mainboard intake air through bottom vents.
- CC1 feet and parts do not fit: the CC2 foot screw is smaller than the CC1's M6
  (3 sources), likely M4 or M5. Unmeasured.
- Re-run input shaping after any foot change (`find-your-numbers.md`).

Blocking step: tip the printer, undo one foot (3 mm Allen key), record screw
size x length and foot height/diameter. Everything below depends on that.

Candidates (prices are UK, 2026-09-28):
- Any thread: Adam Hall 4911 PVC feet, 38x25 mm, bolt-through,
  https://www.amazon.co.uk/dp/B00SJFDYL0 (3.20 GBP; the 33 mm tall version 5.28).
  Needs a longer screw.
- M5: BORDSTRACT levelling feet https://www.amazon.co.uk/dp/B0DNSMTBH1
  (7.39 for 2, 10 kg per foot rating, thin margin).
- M6: RUBBERGIANT https://www.amazon.co.uk/dp/B0C6FJ2FMR (12.50 for 4, 100 kg per foot).
- Printable: Printables 1579825 (the only confirmed CC2 fit; adapter in PETG-CF
  plus a TPU part. Printing that part in PETG for a rigid foot is untested).
  Printables 1409510 is the best rigid CC1 design (M6 pattern, needs a remix).
- Rejected: soft/bellows feet (YUYUEMI B0FQ5N93XR), sorbothane isolation
  (a reddit recipe), squash-ball / Hula / TPU feet.
- Soft stuff, if any, goes UNDER the slab, never under the printer.
- Mats and pads bought for the purpose did not fix rocking in any account I read.

Side find (Z lead screw, not the feet): I did not find the cap-plus-foam model an
owner described. Closest: MakerWorld 2396264 Rod Hole Covers, Printables 1266085
Z bearing cover (limits max print height to 250 mm).

Sources: my table-shake notes (2026-09-16), reddit r/elegoo 1kdfqd9, an
Elegoo CC/CC2 Facebook group post.

## Other first prints from the same Facebook comment (searched 2026-09-28)

- Spool dust cover, CC2-specific: Thingiverse 7361381 (Sienek). Slides onto the
  CC2 spool holder, print 2 + 2 mirrored, PLA, 0 makes when I looked.
- Z-rod hole covers (bottom plate): Printables 1402357 (NoG, CC2 fit confirmed,
  5 makes, rigid, press-fit halves) or Printables 1709530 (TPU one-piece, CC2).
  MakerWorld 2396264 says only "Centauri Carbon". For all of them: the rod
  bearings drop into these holes, so remove the covers or cap max print height at
  ~225 mm, or the bed jams.
- Lead screw top cap with foam: not found; Elegoo stock has a silicone sleeve and
  a fixing block there.
