# CANary firmware

ESP32-S3 firmware for the R70-compatible IP-to-CAN bridge. Build with ESP-IDF
v5.x — v5.5.5 is what it is developed against:

```sh
idf.py set-target esp32s3
idf.py build flash monitor
```

The S3 has native USB, so J102 is both power and programming port — unless the
image was built with `sdkconfig.usb-ncm`, in which case that port is a network
adapter instead and reflashing needs BOOT held. See
[../docs/USB-NIC.md](../docs/USB-NIC.md).

## Layout

| Component | Purpose | Host tests |
|---|---|---|
| `rmbcp` | RM Byte Command Protocol codec + dbCAN identifier helpers | yes |
| `r70_ddt` | UDP 33333 device-detection (discovery) protocol | yes |
| `dbcan` | TWAI driver at dbCAN's fixed 100 kbit/s | no (hardware) |
| `net` | W5500 Ethernet bring-up over SPI; Wi-Fi STA as a devkit option | `net_select` only |
| `usbnet` | USB network device (CDC-NCM) — a second Ethernet adapter over the USB-C cable. Build overlay, not the default image | no |
| `config` | settings in NVS: host name, port, socket count, static IP | `config_check` only |
| `webui` | configuration UI + OTA + diagnostics, bound to the USB link | page only, via `mock/` |
| `bridge` | discovery responder, TCP data socket, CAN forwarding | no |
| `board` | pin map for rev A — the single source of truth for GPIOs | n/a |
| `led` | status LED patterns and fault-code blinking | yes |

`main/status.c` maps link, address (a DHCP lease or the link-local one AUTOIP
self-assigns when no server answers), R1-connected and CAN bus state onto the
three LEDs. It lives in `main/` rather than in `led/` so that `led` depends on
nothing but `board` and `driver`.

## Status — read this before trusting it

**It builds** against ESP-IDF v5.5.5 for `esp32s3`, warning-free from a clean
tree: a 419 KB image in a 1.81 MB app partition.

The **pure logic components pass host tests**, including the worked examples from
the vendor spec and a byte-exact capture of R1 scanning:

```sh
components/rmbcp/test/run_tests.sh        # 50 checks
components/r70_ddt/test/run_tests.sh      # 34 checks
components/led/test/run_tests.sh          # 608 checks
components/net/test/run_tests.sh          # 19 checks (address selection)
components/config/test/run_tests.sh       # 40 checks (settings validation)
```

`components/config`'s suite is the one to read if you are adding a setting: every
one of its 19 planted bugs is caught, and two guards were rewritten because the
first version of the tests could not fail against them.

The LED suite is not padding: it counts real rising edges rather than checking
the formula, and it caught the 4 Hz pattern running at 4.17 Hz because 250 ms is
12.5 ticks at the tick rate originally chosen.

**It runs on rev A board #1** (Ethernet and USB, discovered by R1). On 2026-10-28 development
firmware newer than this tree carried the control application's traffic to two d&b amplifiers
and back (`hardware/fab/test/BRINGUP-LOG-0001.md` §12), and showed that `dbcan` does not recover
after a CAN cable pull: recovery runs only on the gateway's CAN-reset command (`0x58`), which the
control application never sends. The code here has the same recovery path. `dbcan`, `net`,
`led` and `bridge` mirror `tools/r70_emu.py`, which is proven end to end against R1 V3.46 —
treat the Python emulator as the reference implementation where the two disagree.

## The USB network device

`sdkconfig.usb-ncm` builds an image in which the USB-C port is a network
adapter rather than a serial port, so a laptop reaches the unit at
`192.168.7.1` with no LAN cable:

```sh
idf.py -B build-usbnet -DSDKCONFIG=build-usbnet/sdkconfig \
       -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.usb-ncm" build
```

`-DSDKCONFIG` is not optional — without it the overlay is silently ignored on
any tree that has been built before. The console moves to UART0 on J301 and
reflashing needs BOOT held; the whole trade-off, and the list of what has and
has not been proven, is in [../docs/USB-NIC.md](../docs/USB-NIC.md).

## Testing without CANary hardware

`net` retains a Wi-Fi STA path so the bridge can be exercised on a plain
ESP32-S3 devkit plus any 3.3 V CAN transceiver on the pins in
`components/board/include/board.h`:

```sh
idf.py build -DCANARY_USE_WIFI=1 \
             -DCANARY_WIFI_SSID=myssid -DCANARY_WIFI_PASS=mypass
```

Those reach the preprocessor through `main/CMakeLists.txt`, which turns the CMake
cache variables into compile definitions — `idf.py -D` on its own only sets a
CMake variable, which nothing would read. Note the cache **persists**: to go back
to Ethernet, `idf.py fullclean` or set `-DCANARY_USE_WIFI=0` explicitly, or a
plain rebuild silently stays on Wi-Fi.

The LEDs work on a devkit too, but the pins are the rev A board's (GPIO15/16/17,
active HIGH — this line said "active low" until 2026-09-21, which is the error
`components/board/include/board.h` and AGENTS.md §6 both exist to warn against),
so on a bare devkit expect nothing visible unless you wire them.

## Connecting from R1

Scan in **Extras > Options > CAN**, then **go Offline, tick the interface's
activation checkbox, and go back Online**. The checkbox is mode-gated and cannot
be ticked while R1 is Online; the bus scan only starts once Online. This is not
something the firmware controls — see `docs/PROTOCOL.md` §6.
