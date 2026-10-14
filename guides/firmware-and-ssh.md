# Firmware, SSH and getting files off the CC2

Checked 2026-09-12 (documents), verified on a real printer 2026-09-29, updated
2026-10-14 (firmware 01.03.02.36). Read the table first: what you can do depends on the firmware version you have.

## What works on which firmware

| Firmware | SSH | How to get files / logs |
|---|---|---|
| **OTA 01.03.02.36** (os_version 01.02.12.01) | **Works, as root (verified by the author, 2026-09-29).** | SSH / SFTP directly: `tools/send_cc2.py`, `scp`, `ssh root@<printer-ip>` |
| **Other 01.03.x** (e.g. 01.03.02.51) | Reported working (pycentauri maintainer measured stock SSH on 01.03.02.51, June/July 2026). Not verified by us. | Same as above |
| **02.00.02.00 and later** | **Reported removed** (OpenCentauri's archive, 2026-05-28). Not verified by us. | LAN Only mode + access code, e.g. via [pycentauri](https://github.com/bjan/pycentauri) (HTTP / MQTT / camera). Unverified by us. USB stick + Settings -> Export Log File for logs. |

Sources for the second and third rows are other people's reports:
[OpenCentauri CC2 firmware archive](https://docs.opencentauri.cc/software/updates-cc2/)
(their report that 02.00.02.00 removed SSH and blocks ordinary downgrades),
[pycentauri protocol notes](https://github.com/bjan/pycentauri/blob/main/docs/PROTOCOL.md).
Only the first row was checked on hardware here.

An earlier version of these notes said "no Klipper/SSH on the CC2". That was
wrong for stock firmware before 02.00.02.00. What is true: the CC2 runs a
Klipper-based `elegoo_printer` under Elegoo's own stack, and you get a shell
into it. A supported Klipper console, Moonraker or user-editable macros are not
established for stock CC2 firmware (I did not find any).

## Updating: the trade-off

- OpenCentauri's archive says 02.00.02.00 (2026-05-28) removed SSH and blocks
  ordinary downgrades to earlier versions. It also documents a repacked rollback
  to 01.03.02.51. Their page is a maintainer's account, not an Elegoo statement,
  and "downgrade is impossible" would overstate it.
- The same archive lists fixes in the newer releases (heating-error and
  power-loss-resume fixes), which rolling back can lose.
- A July 2026 Elegoo support post announced 02.01.00.00 (WAN reliability,
  print history, pause feed/retract fixes). pycentauri reports file list/delete
  and camera streaming working on 02.01.00.00 (captured 2026-07-10) in LAN Only
  mode, after failures on 01.03.02.51. So new firmware has local-control benefits
  too, just not SSH.
- Position of this repo: record the firmware you were delivered, get stock
  USB/LAN printing working, and update only to fix a demonstrated problem. If you
  want SSH, do not update past the last version that has it, and check first.
- OpenCentauri patched firmware (v0.4.0) is **CC1 only**. For COSMOS (full
  Klipper), a CC2 alpha was reported in the OpenCentauri community around
  2026-10-10: it needs a 3.3 V USB-UART adapter for recovery and testers
  report bugs. Not for daily use; not tried here. CC1 CANVAS support says
  nothing about CC2.
- Power-loss resume on 01.03.02.36: pausing on the screen, power-cycling and
  accepting the resume popup continued the print at the paused layer (one test,
  2026-10-07, about 90 s reheat). That is not a test of an unplanned power cut.

## Getting a shell

```bash
ssh root@<printer-ip>
```

The published default root password is in the OpenCentauri docs; it is not
repeated here. Use your own if you changed it. Scripts in `tools/` read the
address from `CC2_HOST` and the password from `CC2_PASSWORD`.

## Useful paths on the printer

| Path | What |
|---|---|
| `/opt/usr/logs/elegoo.log` | Main log: `print_state`, `cmd_SDCARD_PRINT_FILE`, `cavity_fan ... cur_box_temp` lines. Only the current file plus `elegoo.1.log` (about 10 MB each) |
| `/opt/usr/logs/gui.log` | The touchscreen's log; every socket message it sends, as `Send OK: ... msg:{...}`. Keeps days (`gui.log` + `.0`-`.4`) and logs `printer.print_job.current_file` at every start |
| `/opt/inst/firmware_version/versions.json` | Installed versions: `ota_version` and `os_version` |
| `/opt/inst/printer.cfg` | Stock printer config, e.g. `max_accel = 20000` (a config ceiling, not a recommendation) |
| `/opt/inst/printer_dsp.cfg` | The config the running process loads (seen in `ps`), including `[cavity_fan]` (thermostat: 10% below 36 C, 20% at 36 C, PLA limit 40 C) and the `[tmc2209 ...]` driver sections |
| `/opt/usr/record/elegoo.db` | The firmware's file index (layers, time, thumbnail for the app) |
| `/opt/usr/gcode/local` | Where sent G-code and USB copies land |

Input shaper (SHAPER_CALIBRATE) results live only in `elegoo.log`, which rotates
to `elegoo.1.log` at about 10 MB, so copy them out soon after a run. How to read
them: `find-your-numbers.md`. The phone app's file requests can flood
`elegoo.log` with an error every second, so on a long print the start and
`print_state` lines can rotate out of both files. `gui.log` still has the start,
and fresh `cmd_M73 ... current_layer` lines in `elegoo.log` also show a print is
running.

Stock log timestamps are China time (Asia/Shanghai).

Without SSH, Settings -> Export Log File on the touchscreen writes logs to a
FAT32 USB stick (16 GB or smaller).

## Send G-code and remote start

`tools/send_cc2.py` uploads over SFTP to `/opt/usr/gcode/local` (same folder USB
copies land in), verifies the MD5 and refuses G-code with `M600`. See
`../tools/README.md`.

Files copied in over SFTP are not added to the firmware's file index
(`/opt/usr/record/elegoo.db`) until the next boot. Until then the phone app
shows 0 total layers, about 1 min remaining and no thumbnail; the touchscreen
reads the file itself and is fine. A re-sent file with the same name keeps its
old entry. Fix: reboot when idle and cool, or give re-sent files a new name.

Remote start works in cloud mode, no LAN Only needed (verified 2026-09-29 on
OTA 01.03.02.36, with a small hinge coupon). How: `elegoo_printer` is Klipper-based
and keeps a gcode pty open at `/dev/pts/0`. `--start` writes the touchscreen's
own start sequence into it, copied from `gui.log`:

```
PRINT_SURFACE_SET PLANE=0
BED_MESH_CALIBRATE_SET EXECUTE_CALIBRATE_FROM_SLICER=1
USED_CANVAS_DEV USED_CANVAS=1
CANVAS_SET_COLOR_TABLE T=0 CHANNEL=0 COLOR=0xffffff
SDCARD_PRINT_FILE FILENAME="local/<name>.gcode" SLICE_CFG_MODEL=1 AUTO_DETECT=0
```

- Single colour from CANVAS slot 1 only. For other slots or multi-colour, tap
  Print once on the screen and copy the `CANVAS_SET_COLOR_TABLE` lines from `gui.log`.
- The tool refuses if the last `print_state` in `elegoo.log` (or the rotated
  `elegoo.1.log`) is printing or paused, and confirms `cmd_SDCARD_PRINT_FILE` in
  `elegoo.log` afterwards. It cannot see the bed: clear it first.
- Bed levelling: the CC2 probes the bed only when the levelling toggle is on
  (`EXECUTE_CALIBRATE_FROM_SLICER=1` above, about 5 min). With it off, the saved
  mesh is reused, possibly for days. The Python API's `level=False` skips it.
  Re-level after moving the printer or when the first layer changes.
- While the printer heats or probes, pty commands queue, and so does the
  screen's Cancel. A cancel or speed-mode change sent right after a start takes
  effect only when levelling ends. `CANCEL_PRINT`, `PAUSE` and `RESUME` are
  accepted on the pty; confirm with a new `print_state:` line in `elegoo.log`.
  At the end of every print the printer resets itself to Balanced (`M220 S100`).
- Seen once: after a reboot the pty accepted lines but nothing ran; a second
  reboot fixed it. Test with a harmless line (`M140 S0`) and check `elegoo.log`
  before retrying a start.
- Any gcode works the same way: `printf 'SET_PIN PIN=led_pin VALUE=0\n' > /dev/pts/0`
  turns the chamber light off.
- MQTT (a local broker user) logs in, but `elegoo_printer` ignores the local
  broker in cloud mode.

**Never `strace -f` the GUI.** On 2026-09-29 it froze the touchscreen at print
start and the printer needed a power cycle. `gui.log` already has the messages
you would trace.

## Camera

The chamber camera is the `ai_camera` daemon (MJPEG on port 8080). Every
client connection costs it a thread that is never freed; after a few hundred
connections it aborts and stays down until reboot (restarting a copy over SSH
did not bring video back). Use one long-lived client or a relay, and avoid
tools that reconnect per snapshot. Crash dumps go to
`/opt/usr/logs/<name>.core.log` and can be about 3 GB.

## Motor drivers (TMC2209)

Findings on 01.03.02.36 (2026-10-12/13), not a recipe. X and Y are TMC2209
drivers with StallGuard homing; stock runs them in SpreadCycle at all speeds
(`stealthchop_threshold` is commented out in `/opt/inst/printer_dsp.cfg`).
`DUMP_TMC` works on the pty.

- From G-code you can go StealthChop -> SpreadCycle but not back:
  `SET_TMC_FIELD ... VALUE=0` and `VELOCITY=999999` both fail with error 803
  "Specify either VALUE or VELOCITY".
- The only route found is editing `stealthchop_threshold` in
  `printer_dsp.cfg` and rebooting. Homing still worked in StealthChop.
- Full-time StealthChop on the author's printer: a loud belt growl at 20000
  accel and loud homing (rejected for day prints). A phone sweep showed
  2.5-7 dB quieter at 20-40 mm/s on most moves, louder on diagonals at
  60-70 mm/s. Usable only with slow, low-accel profiles. A hybrid threshold is
  untested.

Editing `printer_dsp.cfg` is at your own risk; back it up first.

## Network notes

- Cloud errors 2002/2003 are documented by Elegoo. The claim that all LAN
  printing depends on the cloud was too broad: Elegoo documents a LAN Only mode
  and local/USB prints. Test your firmware and connection mode before deciding.
  [Elegoo network troubleshooting](https://wiki.elegoo.com/centauri-carbon-2-combo/errorcode-2003).
- LAN Only can affect the existing cloud connection; do not assume both work at once.
- One owner report (ElegooSlicer issue #83) describes working LAN camera but
  failing cloud preview on Linux Mint, slicer 1.5.2.2, firmware 02.01.00.00. It
  is an owner report, not a vendor-confirmed defect.

## Other CC2 firmware work (not tried)

- OpenCentauri `cc2_camera_fix` targets one specific camera board layout
  (EF-S7-V1.0.30B, Ingenic T23, 8 MiB flash). Only relevant for a matching
  camera problem.
- Deeper eMMC backup/restore for the CC2 exists only as still-open pull requests
  in OpenCentauri repos (as of 2026-09-12). No vendor-endorsed CC2 unbrick path
  was established. Do not modify firmware without your own backup.

## Before you change anything

**Reboot only with the nozzle below about 50 C.** The hotend fan does not run
during boot. Two reboots a few minutes after a print were each followed by a
partial clog (suspected heat creep, unconfirmed).

1. Photograph the label and note every firmware version the printer shows.
2. Write down the exact version an update offers and its notes before accepting.
3. Print a small plain-PLA baseline first (`first-week.md`); check USB, LAN Only,
   camera and reboot behaviour separately.
