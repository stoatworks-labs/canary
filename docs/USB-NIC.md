# The USB network device (CDC-NCM)

Plug a CANary into a laptop and it comes up as a second Ethernet adapter. R1
then finds it and drives amplifiers over the USB cable, with no switch, no
router and no LAN cable at all.

> **Status: proven on a macOS host (2026-09-26)** — enumerates, leases, and
> carries every service. R1 over USB and Windows are not yet tested. Details at
> the end, under [What is proven](#7-what-is-proven).

---

## 1. Why NCM, and why this is nearly free

Decision **H16** picked USB-NIC before R60 emulation, and the reason is that
NCM changes nothing above the network interface. The unit gets a second IPv4
address; the discovery responder, the RM Byte Command Protocol codec, the TCP
data socket and the CAN bridge are the same code, unaware that a cable rather
than a switch is carrying them. Everything R1 was proven against in July is
still what runs.

So **R1 never sees USB.** It sees an interface at an IP address, exactly as it
does on the LAN jack. Nothing here claims to be an R70 USB device: the R70 has
no USB port, so there is nothing to be compatible with. R60 emulation — a different thing, the
same RM protocol over a *serial* port — is still unwritten.

---

## 2. What it costs: the USB-C port stops being a serial port

**The ESP32-S3 has one USB PHY and two peripherals that want it.** Out of reset
the internal FSLS PHY is wired to USB_SERIAL_JTAG. Installing TinyUSB moves the
mux to USB-OTG in software — `usb_wrap_ll_phy_enable_external()` sets
`RTC_CNTL.usb_conf.sw_hw_usb_phy_sel`, no eFuse is burnt, and a reset puts it
back. From that moment the port enumerates as a network adapter and **not** as a
serial port.

On this board that matters more than it would elsewhere, because **J102 is the
only power path, the only console and the only programming port.** So a unit
running the NCM image:

| | default image | NCM image |
|---|---|---|
| USB-C shows up as | USB JTAG/serial debug unit | serial port for 8 s, then network adapter "CANary" |
| App console | USB-C, always | USB-C, **for the first 8 s** |
| Reflash | `idf.py flash`, auto-reset | `idf.py flash` **within the first 8 s**, else hold BOOT (SW302) and tap EN |
| LAN jack | works | works, unchanged |

Reflashing still works either way because the mux is software-only: the ROM
bootloader is not affected, so BOOT+EN brings USB_SERIAL_JTAG straight back and
esptool behaves normally for the download.

That is why **NCM is a build-time overlay and not the default.** A converter
whose only programming port silently changes character is not something to ship
by accident.

### The start delay

`usbnet` installs TinyUSB **8 s after boot**, not immediately
(`usbnet_config_t.start_delay_ms`). Everything else — the netif, the DHCP
server, the MAC derivation — happens at boot and claims no peripheral, so the
only thing the delay holds back is the moment the port stops being a serial
port.

That window is not a nicety on these boards. **J301 is a DNP and is not
fitted** — `BRINGUP-LOG-0001.md` says so explicitly — so the UART fallback does
not physically exist, and without the delay a unit that fails to enumerate
would have no console at all and no way in but the BOOT button. With it, every
power-up gives you:

- the whole boot log over USB-C with `idf.py monitor`, including `usbnet`'s
  address and lease lines and any failure to install TinyUSB;
- a window in which esptool can reset into download mode and reflash with no
  button pressed.

The cost is that a laptop waits 8 s for the adapter to appear. Once, per
power-up — and on a bus-powered unit that is once per plug-in.

Logging *after* the switch is safe rather than slow: the USB-Serial-JTAG
console is gated by a SOF-based connection monitor, so with the PHY gone it
reports "not connected" and every write fails fast instead of spinning on the
50 ms TX flush timeout.

### What the LEDs say about USB

D301 is a **reachability** lamp, not an Ethernet lamp — the question it answers,
"can R1 get to us", is the same whichever interface carries it. So a unit with
no patch lead and a laptop on USB shows 1 Hz and **no fault code**; it is
working, and must not blink red at an operator who can see that.

One state gets its own pattern:

| D301 | means |
|---|---|
| off | no Ethernet link *and* no USB host |
| 4 Hz | a link, but no address |
| **double-pulse heartbeat** | **USB host attached, but it has taken no address of its own** |
| 1 Hz | addressable, waiting for R1 |
| steady | R1 connected |

The heartbeat is the failure this feature is most likely to hit: macOS and
Windows both fall back to a self-assigned `169.254` address when no DHCP offer
arrives, and a host that has done that can never reach us however healthy we
are. From this end the link looks perfect. If you see it, check the host's own
address on that adapter — it should be `192.168.7.2`.

> **Not done, and the obvious next step:** a composite device — NCM *plus*
> CDC-ACM — would put the console back on the same cable as the network
> interface, so only the automatic-reset trick would be lost. `esp_tinyusb`
> supports the combination. It is left out of this first cut deliberately:
> composite enumeration is where host-OS differences bite, and none of this has
> met a host yet.

---

## 3. Building and flashing

```sh
cd firmware
idf.py -B build-usbnet -DSDKCONFIG=build-usbnet/sdkconfig \
       -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.usb-ncm" build
```

**`-DSDKCONFIG` is not optional.** Every build otherwise shares
`firmware/sdkconfig`, and `SDKCONFIG_DEFAULTS` is only consulted while that file
is being *created* — so on a tree that has been built before, the overlay is
read, ignored, and reported as a successful build of the image you asked for.
The first attempt at this overlay produced a binary 512 bytes different from the
default one, with no NCM in it, and reported success.

Then, with BOOT held and EN tapped:

```sh
idf.py -B build-usbnet -p /dev/cu.usbmodem1101 flash
```

The **first** flash needs no button at all: the board is still running the
ordinary image, so its serial port is there for the taking. Afterwards, either
flash inside the 8 s window or hold BOOT.

To get back to the ordinary image, flash `build/` the usual way — nothing is
persistent, the mux resets with the chip.

---

## 4. Addressing

| | |
|---|---|
| Unit | `192.168.7.1/24` |
| Host | `192.168.7.2`–`192.168.7.9`, by DHCP from the unit |
| Gateway offered | **none** |
| DNS offered | none |
| Lease | lwip default |

**No gateway, deliberately.** lwip's DHCP server advertises the router option by
default (`dhcps_offer = 0xFF`), which would tell the laptop that CANary is its
way to the rest of the world. macOS and Windows both rank a newly appeared wired
adapter *above* Wi-Fi in their automatic service order, so the laptop would move
its default route onto a point-to-point link that routes nowhere — the operator
loses the internet, the venue network, and very likely the amplifiers, by
plugging in a converter. Clearing the option leaves the host with an on-link
route to `192.168.7.0/24` and nothing else, which is all R1 needs.

**Why 192.168.7:** it is deliberately not 192.168.0, .1 or .2, which is what the
venue's own network is most likely to be using. A collision would leave the host
with two interfaces claiming one subnet; it would pick one, and R1 would reach
either the unit or the amplifiers but not both. 192.168.7 is what Linux's
`g_ether` and a long tail of USB gadgets use, for the same reason.

The USB netif carries `route_prio` 5, below the W5500's 50, so it can never
become the default interface even if something else offers it one.

### If the lease does not take

The DHCP server exists so that the unit and the host land on one subnet with no
configuration at all. The one way that fails is a host that never accepts an
offer: macOS and Windows both fall back to a self-assigned `169.254` address,
and the two ends are then on different subnets with no route between them. From
this end the link looks perfect — which is why it gets the D301 heartbeat.

**Setting the address by hand is a complete bypass**, and takes twenty seconds:

| | |
|---|---|
| Address | `192.168.7.2` |
| Subnet mask | `255.255.255.0` |
| Router | **leave empty** |
| DNS | leave empty |

On macOS: System Settings → Network → the `CANary` adapter → Details → TCP/IP
→ Configure IPv4: Manually. Leaving the router field empty matters for the same
reason the unit does not offer one.

With that plus R1's *Dedicated R70 addresses* (§6), you can reach a unit over
USB with neither DHCP nor discovery involved — which is also the cleanest way
to work out which of the two is at fault.

---

## 5. Two interfaces, one discovery answer

This is the part that needed new logic rather than new plumbing.

R1 discards the UDP sender of a discovery probe and connects to whatever address
the *record* carries (`docs/PROTOCOL.md` §4). With one interface that address
was unambiguous. With two it is not: answering a probe that arrived over USB
with the Ethernet address produces a device that appears in R1's list and then
refuses every connection — the failure that is hardest to read from the R1 end.

So the address is now chosen **per probe, from the probe's source address**:

- an interface whose subnet contains the peer wins; longest prefix if several do;
- otherwise the first interface that holds an address at all, in the order
  `ETH_DEF`, `WIFI_STA_DEF`, `USB_NCM_DEF`.

That order is policy, not incident. A peer we cannot place reached us over the
wired side or not at all, so the USB link — point to point, routing nowhere —
must never be the fallback.

The rule lives in `firmware/components/net/net_select.c`, kept free of ESP-IDF
so it can be tested on a host; `firmware/components/net/test/` has 19 checks
covering R1 on the wired side, R1 on the USB link, an off-link peer, either
interface half-configured, AUTOIP on both, overlapping subnets and a `/32`.
`bridge_local_ip_for()` in `net.c` builds the table from esp_netif and calls it;
`hostsim` answers the same contract from the host's own routing table, which is
a better oracle than a stub.

---

## 6. Host support

Only macOS has been tried (§7). What can be said from the specifications:

- **macOS** has an in-box NCM driver and binds by class.
- **Linux** has `cdc_ncm`, likewise.
- **Windows 10 1703 and later** ship `usbncm.sys`, but class binding is less
  reliable than on the other two, and some NCM gadgets need a Microsoft OS 2.0
  descriptor before Windows will attach without an INF. If Windows shows an
  unknown device, that descriptor is the first thing to add.

The device reports Espressif's vendor ID (`0x303A`) with TinyUSB's automatic
product ID. This project has no USB-IF vendor ID of its own, and the part really
is an Espressif one, so borrowing a VID it is not entitled to would be worse.

---

## 7. What is proven

| Claim | Evidence |
|---|---|
| The image builds warning-free under `-Werror` | `idf.py build`, clean tree, both images |
| It boots, the deferred install fires after the delay, and a USB stack that fails to start does not take the unit down | `firmware/qemu/run_qemu.sh --usbnet --check`. QEMU has no USB device controller, so TinyUSB asserts out at t+8 s — which is the useful half: it is logged and the bridge carries on |
| Address selection is right for the pairs that occur | 19 host checks, each of which fails against a planted bug |
| Nothing above the netif changed | the whole suite still passes: 57 Python, 758 firmware host checks, hostsim 20/20, fuzzers clean |
| A macOS host enumerates it, leases from it, and reaches every service over it | First bench session, 2026-09-26, board #1 on macOS 26.4: adapter `CANary` (`en25`), lease 192.168.7.2/24 with **no router and no DNS** offered, default route stayed on Wi-Fi, ping ~1 ms, `http://192.168.7.1/` 200 with `usb.link: true`, and `board_test.py --host 192.168.7.1 --broadcast 192.168.7.255 --skip console,can` **19/19** — discovery advertising 192.168.7.1 as `db-70`, full RM Byte Command Protocol walk on TCP 30000 |
| BOOT+EN reflashing, and reflashing in the 8 s window with no button | both done repeatedly in the same session; esptool's `default_reset` catches the window if it is already waiting for the port |

**Four bugs that session found, all invisible without a host** (fixed in the
same commit):

1. **The link never came up.** TinyUSB 0.21's NCM driver declares
   `tud_network_init_cb()` and never calls it, so `on_net_init` never ran:
   no netif, no DHCP server, every transmit refused. The Mac saw an *active*
   adapter, sent 166 frames, received 0, self-assigned 169.254. Link-up now
   hangs off `TINYUSB_EVENT_ATTACHED` (mount).
2. **The DHCP server never started.** `make_netif()` stops it (INIT →
   STOPPED) to be allowed to set options, and `esp_netif_action_start()` only
   starts it from INIT — returning ESP_OK either way. Started explicitly now.
3. **The web UI reset every connection.** With `CONFIG_LWIP_IPV6` the httpd
   socket is dual-stack, so the USB host arrives as `::ffff:192.168.7.2` and
   the `AF_INET`-only guard refused it. Mapped addresses are unwrapped now.
4. **Discovery advertised a garbage host name** — on EVERY image since the
   config component, Ethernet included. `bridge_config_t.hostname` pointed into
   `app_main`'s stack, freed when app_main returns. `bridge_start()` copies it.

Also: `CONFIG_LWIP_DHCPS_ADD_DNS=n`, because lwip otherwise offers the unit
itself as DNS whenever DNS is "off".

**What is still not proven:**

- R1 has never discovered a unit over USB (step 9 below);
- Windows has never enumerated it;
- throughput, and NCM's behaviour when the host suspends the bus, are unknown.

### The first bench session, in order

1. **Flash it** — no button needed, the board is still on the ordinary image.
2. **Watch the boot** with `idf.py monitor` and read the 8 s window: the
   `NCM will be at 192.168.7.1/24` line, then `starting USB-OTG`, then the port
   drops. Anything failing before that is visible here and nowhere else.
3. **Enumerate** — the adapter should appear in macOS Network settings as
   `CANary`.
4. **Check the host's address on that adapter.** It must be `192.168.7.2`.
   A `169.254` address means DHCP did not take — D301 will be heartbeating.
5. **Confirm the host did NOT take a default route** (`netstat -rn | grep
   default`). It should be unchanged; the DHCP server offers no router on
   purpose.
6. `ping 192.168.7.1`.
7. **Open `http://192.168.7.1/`** — the configuration UI ([WEBUI.md](WEBUI.md)).
   If the page loads, the NCM link is carrying real traffic in both directions
   and everything below is a formality.
8. `tools/board_test.py --host 192.168.7.1 --broadcast 192.168.7.255 --skip console,can`
9. **R1.** If discovery does not list it, add `192.168.7.1` to R1's *Dedicated
   R70 addresses* list by hand — that path skips discovery entirely and isolates which half failed.

Leave the LAN cable plugged in throughout. Ethernet is unchanged in this image,
so it stays a known-good way to reach the unit while the USB side is in
question.

---

## 8. Files

```
firmware/components/usbnet/          TinyUSB + NCM + netif + DHCP server
firmware/components/net/net_select.c per-peer source address (pure, host tested)
firmware/sdkconfig.usb-ncm           the overlay that turns it on
firmware/qemu/run_qemu.sh --usbnet   boot the NCM image
```
