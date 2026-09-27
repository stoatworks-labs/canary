# The configuration UI

Plug a CANary into a laptop, open `http://192.168.7.1/`, and you get status,
settings, a firmware update and the diagnostics bundle. No app, no driver, no
toolchain.

> **Status: written, builds, boots, and the page itself has been driven in a
> browser against a mock device. Nothing has run on hardware** — it needs a USB
> host, and nothing has ever enumerated this unit. See
> [What is proven](#6-what-is-proven).

---

## 1. It lives on the USB cable, and only there

This is the one part of the firmware that can change what the unit *is* — its
name, its port, its address, its firmware. Everything else only carries CAN
frames. So it is confined to the USB link by **two independent mechanisms**:

1. **There is no listening socket unless a USB host is attached.** A watcher
   task follows `usbnet_link_up()` and starts the server on attach, stops it on
   detach. A unit in a rack on a show network has nothing on port 80 — not even
   a port that accepts and hangs up.
2. **Every accepted connection is checked against the USB subnet** in
   `webui_open()`, which `esp_http_server` calls just after `accept()` and
   before a single byte is read. lwip's server cannot bind to one interface, so
   this is what makes "USB only" true rather than aspirational. A connection
   from anywhere else is closed and logged.

The reasoning: TCP 30000 has no authentication, by design, exactly as a real
R70 has none — that is defensible for a transparent bridge on a locked-down
show network. A surface that can replace the firmware is a different risk
class. Putting it behind *"you are holding the other end of the cable"* is a
stronger guarantee than any password this project could ship and keep, and it
keeps the promise in `AGENTS.md` §1 intact: on the show network, the unit is
still nothing but a bridge.

---

## 2. What you can change

| Setting | Default | Notes |
|---|---|---|
| Name shown in R1 | `CANary` | Our own name; a real R70 ships as `db-70`. Two units on defaults appear in R1 as two identical entries, which is the main reason this exists. Max 27 characters — the discovery record's capacity. |
| Data port | `30000` | Socket 1. R70 default. |
| Sockets advertised | `4` | What a real R70 offers. R1 leaves its socket column read-only below two. |
| LAN jack address | Automatic | DHCP, falling back to link-local. Or a static address, mask and optional gateway. |

**Changes take effect at the next boot**, and the page says so. `net.c` hands
its address to lwip during bring-up and the bridge copies its configuration
when it starts, so applying half of it live would leave the two disagreeing.
A converter that says "reboot to apply" is being honest; one that quietly
applies some of it is not.

Settings live in their own NVS namespace, separate from `diag`'s — erasing
settings to recover a unit must not throw away the crash summary that explains
why it needed recovering.

**A bad setting cannot strand a unit.** `cfg_load()` validates the whole stored
set and falls back to factory defaults wholesale if it does not hold together,
logging what it replaced. And *Factory settings* on the page erases the
namespace outright.

---

## 3. Firmware updates

Upload a `canary.bin`; it goes into the spare OTA slot, is verified by
`esp_ota_end()` before anything points at it, and the unit reboots into it. A
corrupt file, a wrong-target image or a pulled cable all leave the running
firmware untouched.

**Rollback is on** (`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`). A freshly written
image boots on probation: unless it reaches
`esp_ota_mark_app_valid_cancel_rollback()` at the very end of `app_main` — by
which point the bridge is listening, the LEDs are running and the UI is up —
the bootloader reverts to the image it replaced.

That matters more here than on most boards. **J301 is a DNP and is not fitted**,
and on a USB-NCM image the serial port only exists for the first eight seconds
after boot ([USB-NIC.md](USB-NIC.md)). Automatic revert is the difference
between a bad upload being an inconvenience and being a trip to the bench with
a BOOT button.

---

## 4. Diagnostics

`GET /api/diagnostics` gives the bundle `diag_bundle_json()` has been building
since it was written — log ring, boot record, reset reason, crash summary.

`GET /api/diagnostics/coredump` streams the stored ELF coredump, chunked, so a
tens-of-kilobytes image never lands in RAM in one piece. **`diag.c` has been
printing that URL after every panic since it was written**, with no server
anywhere in the firmware to serve it. It is finally true.

---

## 5. Testing it without a board

```sh
python3 firmware/components/webui/mock/mock_device.py
```

Serves **the real `www/index.html`** — not a copy — with plausible `/api`
responses, at `http://127.0.0.1:5211/`. `GET /scenario/<name>` switches between
states that are awkward to produce deliberately on a bench:

| Scenario | What it fakes |
|---|---|
| `nominal` | everything up, R1 connected |
| `nolease` | USB host attached but it has taken no address — the D301 heartbeat case, and the failure most likely in practice |
| `linklocal` | no DHCP server on the LAN, so AUTOIP self-assigned |
| `usb-only` | no LAN cable at all |
| `nocan` | CAN bus-off |
| `crashed` | a coredump is stored from a previous boot |

It proves the page. It proves nothing about `webui.c`: the USB-subnet check,
the OTA path into flash, the real validator and the chunked coredump reader all
need a board.

---

## 6. What is proven

| Claim | Evidence |
|---|---|
| Settings validation refuses what would strand a unit | 40 host checks in `components/config/test/`, and **all 19 planted bugs are caught** — including two guards that were rewritten because the first version of the tests could not fail against them |
| Both images build warning-free under `-Werror` | clean builds of `build/` and `build-usbnet/` |
| The config store runs on the real boot path | `run_qemu.sh --usbnet --check`: `cfg: no stored settings (ESP_ERR_NVS_NOT_FOUND); using defaults` |
| The page renders, populates, validates and recovers | driven in a browser against `mock/mock_device.py`: every status scenario, the static/DHCP field gating, a rejected save showing the device's own reason, a valid save, a rejected firmware upload, a successful one with progress, and the post-reboot reload. No console errors; no horizontal overflow at 375 px; light and dark both checked |
| Nothing above it changed | the whole suite still passes: 57 Python, 798 firmware host checks, hostsim 20/20, fuzzers clean |

**What is not proven — everything that needs a board:**

- no browser has ever talked to `webui.c`; the C has only been compiled;
- the USB-subnet check in `webui_open()` has never refused anything;
- no firmware has been written over the air, and the rollback has never
  reverted anything;
- no setting has ever survived a reboot on real hardware;
- the coredump endpoint has never streamed a real dump;
- and it all sits on top of a USB network device that has itself never
  enumerated. **Prove NCM first** — [USB-NIC.md](USB-NIC.md) §7 has the bench
  order. Until a laptop gets an address over that cable, none of this page is
  reachable.

---

## 7. Files

```
firmware/components/config/     settings: cfg_validate() is pure and host-tested
firmware/components/webui/      the server, bound to the USB link
  www/index.html                the page - one file, no external references
  mock/mock_device.py           drive the page without a board
```

The page is embedded in the binary rather than served from a filesystem
partition: it is one small self-contained file, and a SPIFFS partition would
mean changing the partition table, which changes OTA compatibility. It has no
external references at all — the unit has no route to the internet, so a
stylesheet or font from a CDN would simply never load.
