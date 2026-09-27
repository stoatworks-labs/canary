# qemu — booting the real image without a board

`hostsim` runs the firmware's *logic* on the host. It never executes the boot
path. This does: Espressif's QEMU fork boots `build/canary.bin` on an emulated
ESP32-S3, through the second-stage bootloader, the partition table, the heap and
`app_main`.

That is where a first prototype wastes its first hour, and none of it needs
hardware.

```sh
python3 $IDF_PATH/tools/idf_tools.py install qemu-xtensa   # once
idf.py build
./run_qemu.sh --check
```

Homebrew's `qemu-system-xtensa` will **not** work — it has no `esp32s3` machine.
It must be Espressif's fork, which is what `idf_tools.py` installs.

`--check` fails the run on a panic, a stack overflow, a reboot loop, or a driver
registering an ISR with no service installed.

## What this found

Three real bugs, on the first boot ever attempted:

1. **`main_task` overflowed its stack during bring-up.** FreeRTOS's own detector
   reported it. `app_main` does NVS, diag (which promotes any coredump from the
   last boot), `selftest_post`, the network and the bridge, and the 3584-byte
   default was not enough. Fixed by `CONFIG_ESP_MAIN_TASK_STACK_SIZE=6144` in
   `sdkconfig.defaults`.

2. **The W5500 driver registered its interrupt handler with no GPIO ISR service
   installed.** `net.c` set `int_gpio_num` but never called
   `gpio_install_isr_service()`. The failure is one log line and the driver comes
   up anyway — with nothing on the INT line. The link would have gone up and not
   one frame would ever have been received. This is the expensive kind of bug:
   everything looks fine.

3. **`diag_vprintf` kept two 160-byte buffers on the stack** in what is the
   global `esp_log` hook, so every log line anywhere cost ~350 bytes of the
   logging task's stack. Now one buffer, sanitised in place.

## Known QEMU artefacts — do not chase these

- **`RESULT flash.size FAIL 4 MB`** — QEMU emulates 4 MB. Note separately that
  `sdkconfig.defaults` really does set `CONFIG_ESPTOOLPY_FLASHSIZE_4MB` while
  the BOM module is an **-N8 with 8 MB**, which is worth a decision; but this
  log line is not evidence of it.
- **A panic inside `esp_core_dump_flash` → `esp_mmu_paddr_find_caps` while
  *saving* a dump.** Every frame is ESP-IDF cache/MMU code; QEMU's ESP32-S3
  cache emulation does not support the flush path the panic handler uses. It
  only appears after some other panic, so fix that and it goes away. It is not
  evidence that the coredump path is broken on silicon — and it is not evidence
  that it works, either. That remains untested.

## What it cannot tell you

QEMU has no W5500 on SPI and no TWAI. `net.c` and `dbcan.c` stop where they
would touch hardware, so the log ending shortly after the LED line is expected,
not a hang. Timing, power, and every peripheral still need a board.
