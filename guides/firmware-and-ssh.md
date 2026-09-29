# Firmware, SSH and getting files off the CC2

Checked 2026-09-12 (documents), verified on a real printer 2026-09-29. Read the
table first: what you can do depends on the firmware version you have.

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
- OpenCentauri patched firmware (v0.4.0) and COSMOS (full Klipper, 26.08.0) are
  **CC1 only**. Neither supports the CC2 today. CC1 CANVAS support says nothing
  about CC2.

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
| `/opt/usr/logs/elegoo.log` | Main log: `print_state`, `cmd_SDCARD_PRINT_FILE`, `cavity_fan ... cur_box_temp` lines |
| `/opt/usr/logs/gui.log` | The touchscreen's log; every socket message it sends, as `Send OK: ... msg:{...}` |
| `/opt/inst/firmware_version/versions.json` | Installed versions: `ota_version` and `os_version` |
| `/opt/inst/printer.cfg` | Stock printer config, e.g. `max_accel = 20000` (a config ceiling, not a recommendation) |
| `/opt/inst/printer_dsp.cfg` | Printer config, including `[cavity_fan]` (thermostat: 10% below 36 C, 20% at 36 C, PLA limit 40 C) |
| `/opt/usr/gcode/local` | Where sent G-code and USB copies land |

Input shaper (SHAPER_CALIBRATE) results live only in `elegoo.log`, which rotates
to `elegoo.1.log` at about 10 MB, so copy them out soon after a run. How to read
them: `find-your-numbers.md`.

Without SSH, Settings -> Export Log File on the touchscreen writes logs to a
FAT32 USB stick (16 GB or smaller).

## Send G-code and remote start

`tools/send_cc2.py` uploads over SFTP to `/opt/usr/gcode/local` (same folder USB
copies land in), verifies the MD5 and refuses G-code with `M600`. See
`../tools/README.md`.

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
- The tool refuses if the last `print_state` in `elegoo.log` is printing or paused,
  and confirms `cmd_SDCARD_PRINT_FILE` in `elegoo.log` afterwards. It cannot see
  the bed: clear it first.
- Any gcode works the same way: `printf 'SET_PIN PIN=led_pin VALUE=0\n' > /dev/pts/0`
  turns the chamber light off.
- MQTT (a local broker user) logs in, but `elegoo_printer` ignores the local
  broker in cloud mode.

**Never `strace -f` the GUI.** On 2026-09-29 it froze the touchscreen at print
start and the printer needed a power cycle. `gui.log` already has the messages
you would trace.

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

1. Photograph the label and note every firmware version the printer shows.
2. Write down the exact version an update offers and its notes before accepting.
3. Print a small plain-PLA baseline first (`first-week.md`); check USB, LAN Only,
   camera and reboot behaviour separately.
