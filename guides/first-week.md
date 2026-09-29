# CC2 Combo: what to do and print first

Researched 2026-09-12 for a CC2 Combo (with CANVAS) ordered 2026-09-11, then
trimmed for this repo. It is a practical starting guide from owner accounts,
manufacturer instructions and model creators' descriptions. It is not a survey of
all owners, and the print order is my recommendation, not a measured popularity
ranking. I had not touched the printer when I wrote it; where something was later
checked on the real machine it says so.

The recurring starting points among owners are a **Benchy, a purge-waste bin, and
small useful objects**, then decorative samples and personal projects.

## Suggested print queue

| Order | Print | What it accomplishes |
|---|---|---|
| 1 | One plain-PLA Benchy | Shows loading, extrusion, adhesion and basic motion work together. Keep it as a reference. |
| 2 | A CC2 purge chute and bin | Catches the filament discarded at the rear; useful before experimenting with colour changes. |
| 3 | A small sample of any fit-critical joint you plan to print | A good Benchy does not establish that a mating joint fits. Cut out a small region around the joint in the slicer, keep scale and orientation. |
| 4 | The full fit-critical part, once the sample fits | Do not apply XY compensation before checking fit. |
| 5 | A small two-colour nameplate or raised-letter label | Introduces CANVAS slot mapping and colour changes with a manageable print. |
| 6 | Tool storage, organisers or an articulated model | Choose something you want; add printer accessories when they solve an observed problem. |

Elegoo provides a CC2 Combo Benchy in its
[download centre](https://wiki.elegoo.com/en/download-center). For downloaded
models, select the CC2 and installed nozzle in ElegooSlicer, and check material
and build-plate settings before slicing: a downloaded project carries someone
else's settings.

## Arrival and first setup

Use the instructions supplied with your machine if its revision differs. In the
official V1.3 manual ([PDF](https://elegoo-downloads.oss-us-west-1.aliyuncs.com/tutorials/Centauri%20Carbon%202%20Combo/Centauri%20Carbon%202%20Combo%20User%20Manual-English-V1.3.pdf);
page numbers below are the printed ones, five less than the PDF's):

- [ ] **Inspect** the enclosure, glass, bed and accessories; photograph damage
  before going on. Stable surface, grounded outlet, room for the rear wiper/chute
  and the side-mounted spools (p. intro).
- [ ] **Unpack before powering or homing.** Remove the foam, thermal cover, nozzle
  wiper assembly and CANVAS module, and **all three blue-marked heated-bed
  transport screws** (2.5 mm Allen key). Identify them from the diagram; do not
  loosen other bed screws (p. 7).
- [ ] **Screen and rear wiper.** FPC gold contacts face up, screen slides in and
  locks. Wiper: two FM3x12 at the top, two PM3x6 at the bottom (p. 8).
- [ ] **CANVAS and hub.** Bracket with two PM3x50, feeder with three PM3x8, hub
  with two PM3x6; the hub's metal tube seats down into the printhead fitting (p. 9).
- [ ] **Holder numbers matter.** Eight HM3x14 screws for the brackets; each holder
  snaps into its numbered position (Elegoo ties numbering to filament rewinding).
  Clip the four PTFE tubes between feeder and hub (p. 10).
- [ ] **Cable and cover.** Four-pin cable with the angled end at the printer rear,
  straight end at CANVAS. Finish connections before applying power (p. 11).
- [ ] **Clean plate.** Warm water and washing-up liquid, rinse, dry, seat flat.
  Textured PEI face for the baseline. Let prints cool before flexing the plate (p. 15).
- [ ] **Startup self-check.** Elegoo documents Settings -> Calibration ->
  One-Click self-check -> All -> Start. This is distinct from tuning a filament's
  temperature, flow or pressure advance in the slicer. If a check fails, keep the
  error code and fix that first.
- [ ] **Load the PLA.** An RFID spool is scanned at CANVAS, then assigned to a
  holder on screen; otherwise enter brand, material and colour by hand. Seat the
  spool fully, check free rotation, feed into the matching numbered inlet. One
  occupied channel is enough to start (pp. 12-14).

Record the installed firmware version and read the release notes before changing
it (see `firmware-and-ssh.md`). Advice to install custom firmware immediately is
not a good default for the first week.

## Slicer baseline

Use **ElegooSlicer** first (v1.5.3.5, 2026-09-03, added build-plate selection and
tells you to check first-layer temperatures when you first use it; a copy on the
supplied USB may be older).

| Setting | Baseline |
|---|---|
| Printer | Elegoo Centauri Carbon 2 0.4 nozzle (not the original Centauri Carbon). The name does not need "Combo" |
| Process | 0.20mm Standard @Elegoo CC2 0.4 nozzle |
| Physical plate face | Textured PEI |
| Slicer plate | Textured PEI Plate (check it after opening a downloaded project) |
| Filament | The CC2 preset of the actual material, e.g. Elegoo PLA @ECC2. PLA Basic, PLA+, Rapid PLA+ and others have separate presets |
| Temperature check | Elegoo PLA @ECC2 resolves to 210 C nozzle / 60 C textured bed. Its cool-plate value is 35 C, so confusing the two surfaces changes the job a lot |
| Channel mapping | Check the selected material against the physically loaded CANVAS channel before sending; a matching colour is not a matching material |

Upstream OrcaSlicer v2.4.2 also bundles a CC2 0.4 mm profile. That confirms the
profile exists, not that connectivity works with your firmware.

Then: slice a small single-colour model, inspect the preview, print, watch the
first layer, let it cool, keep the project, preset names and a photo as your
baseline. If only part of the first layer is bad, Elegoo says to clean and reseat
the plate and repeat automatic levelling before touching the bed.

USB (exported G-code) and same-LAN pairing (Device tab) are both documented in the
manual (pp. 18-20). Cloud setup is not a prerequisite for every print.

## Machine calibration vs filament tuning

| Kind | What it does | When |
|---|---|---|
| Machine self-check, input shaping, auto levelling, auto Z offset | Hardware readiness, vibration compensation, nozzle-to-bed relationship | During commissioning; repeat after a fault or hardware change |
| Filament temperature, max volumetric speed, pressure advance, flow, retraction | Slicer settings for one material and nozzle | Optional once the baseline works, or to chase a repeatable defect. Save into a named filament preset |
| Fit / tolerance test | Whether your mating geometry fits | Before any fit-critical print |

"Full-auto calibration" and RFID identification do not mean every spool was
characterised. Elegoo advertises pressure-advance calibration, yet the stock PLA
preset also carries a fixed PA of 0.04; which one wins is unverified, so keep
hardware calibration and deliberate filament tuning separate. The run-book:
`../calibration/README.md`. Reasoning: `tuning.md`.

## Accessories worth considering

| Model | Evidence and requirements | Priority |
|---|---|---|
| [Steve's CC2 chute v2 and large waste bucket](https://www.nexprint.com/en/models/G6807748) | CC2 only, uses existing screws, chute prints without supports, PLA profile | Preferred first accessory; check rear clearance before choosing bucket position |
| [Julien Mairy's magnetic tool holder](https://www.nexprint.com/en/models/2015340673733353472) | Designed for CC2; needs eight 8 x 2 mm magnets | Later, once you have the magnets |
| [Official scraper download](https://elegoo-downloads.oss-us-west-1.aliyuncs.com/tutorials/Centauri%20Carbon%202%20Combo/Scraper.zip) | Listed in Elegoo's CC2 Combo downloads; the holder may need magnets | Small practical print after checking blade and fasteners |
| Spool adapter | Elegoo specifies a 53-58 mm spool bore; an adapter is needed for larger bores | Only for a spool that needs it |
| [Wukong's base with front waste drawer](https://www.nexprint.com/en/models/G0430968) | Creator warns of over 2 kg of filament and over two days of printing | A later workspace project |

"Compatible" here means the creator explicitly describes the model for the CC2. I
had not printed or fitted these when I wrote this. Prefer explicit CC2 creator
documentation over CC1 accessories: some shared parts do not mean a given chute,
riser or toolhead mod fits.

## First colour experiment

Two colours of ordinary PLA in a flat label with raised lettering, so colours
change at only a few heights. Check the slice preview's material use and colour
changes first. Frequent swaps can produce a lot of purge waste; one owner's month
of testing described prints where the purge outweighed the object
([account](https://mobilesyrup.com/2026/08/13/3d-printing-beginner-what-nobody-tells-you/)).

Later, consider printing differently coloured parts separately and assembling
them. The slicer also offers flushing into infill, with tradeoffs: colours can
show through translucent walls, and Orca's documentation says the option needs a
prime tower ([Orca flush options](https://github.com/OrcaSlicer/OrcaSlicer/wiki/multimaterial_settings_flush_options)).

## What other owners printed first

Seven first-person accounts (blogs and reddit, dates as published, not print
dates). Self-selected anecdotes: they show what these people tried, not failure
rates or what most owners do.

| Owner (date) | What they did | Limit |
|---|---|---|
| Warren Blackwell (2026-02-20) | Preloaded multicolour Benchy, then the preloaded white twirly vase. Liked both. [Blog](https://www.warrenblackwell.com/maker-box-part-two/) | Also mentions accumulated failed prints |
| Severe_Confusion_424 (date unconfirmed) | Printed the purge chute early; asked what else to do. [Thread](https://www.reddit.com/r/ElegooCentauriCarbon/comments/1rbwscy/i_just_got_my_new_cc2_and_love_it_and_im/) | Exact position in the print order unknown |
| bumjug427 (2026-02-26) | Benchy in PETG-CF, ~46 min, then a fidget shark; first file by USB, second by Wi-Fi. [Post](https://www.reddit.com/r/elegoo/comments/1rf08ya/2_firsts_in_one_shot/) | Returning Ender user; no completion report for the shark |
| rhodges_bob (2026-03-16) | Four spools, Benchy from the display; an unloading error interrupted the last colour change, recovered. [Post](https://www.reddit.com/r/ElegooCentauriCarbon/comments/1rvjrqp/first_print_with_new_cc2_failed_but_all_is_well/) | Not a validated recovery procedure |
| Dragonfish42 (date unconfirmed) | Combo: auto calibration, acceptable Benchy, then flow test pieces that detached; a ~150 mm planter tray first layer was rough, recalibration helped, trouble returned. [Thread](https://www.reddit.com/r/elegoo/comments/1to8mze/cc2_super_inconsistent_first_layer/) | Experienced A1 owner; causes proposed in the thread are not established |
| Epirox (2026-08-25) | First printer; standard Elegoo profiles, calibrated filament later; after about a week a multipart Master Sword (PETG blade pieces, PLA parts). [Comment](https://www.reddit.com/r/elegoo/comments/1vybt32/comment/p5vmr9p/) | Separately coloured parts are not one automatic multicolour job |
| NullType20 (2026-08-31) | After auto calibration and a firmware update, a Benchy via Elegoo Matrix with sample white PLA and default settings; asked whether the bow looked normal. [Thread](https://www.reddit.com/r/elegoo/comments/1w3rz6b/centauri_carbon_2_first_print_quality_3dbenchy/) | Replies disagree; no confirmed diagnosis |

Pattern in this small sample: start with a supplied Benchy, then a useful
accessory or a fun object; learning continues after auto setup (Epirox calibrated
filament later, Dragonfish42 used test pieces after the Benchy).

## Corrections to earlier advice

- **The blanket ban on PLA-CF through CANVAS was wrong.** Elegoo supports
  fibre-reinforced filament in CANVAS and advises inspecting and replacing feed
  parts because of abrasion. Ordinary PLA is still the sensible first material.
  [Elegoo note](https://ca.elegoo.com/products/centauri-carbon-2-combo-4-kg-fiber-reinforced-filament).
- **Cloud errors do not mean every local print needs the cloud.** The manual
  documents local/USB jobs and Elegoo documents a LAN Only setting.
  [Elegoo troubleshooting](https://wiki.elegoo.com/centauri-carbon-2-combo/errorcode-2003).
- **Follow the filament maker's drying instructions.** Elegoo recommends 60 C for
  eight hours for PETG Pro; a sealed spool is not evidence that it is dry.
  [Instructions](https://uk.elegoo.com/products/petg-pro-filament-1-75mm-colored-1kg).
- **Full-auto calibration does not replace per-filament tuning.** See above.
- **A drying oven, a printed dry box or manual bed levelling are not day-one
  requirements.** Manual levelling is for a visibly tilted bed or an abnormal
  first layer after auto levelling.
