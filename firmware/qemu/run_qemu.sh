#!/bin/sh
# Boot the real ESP32-S3 image under Espressif's QEMU and capture the log.
#
# WHY: everything else in this project tests the firmware's logic on a host.
# None of it executes the boot path — the bootloader, the partition table, task
# stacks, driver init order — and that is where a first board wastes its first
# hour. This runs the actual canary.bin.
#
# `idf.py qemu monitor` does the same thing but needs a TTY, so it cannot run
# from a script or CI. This drives QEMU directly instead.
#
#   ./run_qemu.sh                 boot for 30 s, print the log
#   ./run_qemu.sh --seconds 90
#   ./run_qemu.sh --check         boot and FAIL on a panic or stack overflow
#   ./run_qemu.sh --usbnet        boot the USB-NCM image instead
#
# --usbnet stacks sdkconfig.usb-ncm AND sdkconfig.uart-console, in that order.
# The NCM overlay deliberately KEEPS the console on USB-Serial-JTAG -- the whole
# point of usbnet's start delay is that the port stays a serial console for the
# first few seconds -- and that is the one sink QEMU's -nographic cannot carry,
# which is the trap described above. The UART overlay comes second so it wins.
#
# QEMU has no USB device controller, so TinyUSB cannot come up there: what this
# checks is that the image BOOTS, that the deferred install runs at all, and
# that a USB stack which fails to start leaves the bridge running. It proves
# nothing about NCM itself. Note the install waits out the start delay, so give
# it --seconds well above that.
#
# WHAT IT PROVES, AND WHAT IT DOES NOT
#
# Proves: the image boots, the partition table is right, init order is sane,
# task stacks survive bring-up, and nothing panics before the network.
#
# Does not: QEMU has no W5500 on SPI and no TWAI, so net.c and dbcan.c stop at
# the point they would touch hardware. The log ending after the LED line is
# expected, not a hang.
#
# WHICH IMAGE THIS BOOTS, AND WHY IT IS NOT ../build
#
# The shipping console is USB-Serial-JTAG (see sdkconfig.defaults), because the
# self-test REPL has to be reachable over the USB-C port that is also power and
# programming. QEMU's -nographic routes the emulated UART0 to stdout and does
# not carry USB-Serial-JTAG, so booting ../build here produced a log that
# stopped dead at "entry 0x403c8920" -- and because the checks below were all
# NEGATIVE greps, an empty log scored a PASS. The harness silently proved
# nothing.
#
# So this builds its own image with the sdkconfig.uart-console overlay, which
# changes the console sink and nothing else, and asserts POSITIVELY that the
# app actually reached app_main before it starts looking for failures.
#
# One known QEMU artefact — do NOT chase it as a firmware bug:
#   - a panic inside esp_core_dump_flash -> esp_mmu_paddr_find_caps while
#     SAVING a dump. Every frame is ESP-IDF cache/MMU code; QEMU's ESP32-S3
#     cache emulation does not support that path. It only appears after some
#     other panic, so fix the panic and it goes away.
set -e
cd "$(dirname "$0")"

FW=..
BUILD=build-qemu
OVERLAY=sdkconfig.uart-console
LABEL="UART-console"
SECONDS_TO_RUN=30
CHECK=0

while [ $# -gt 0 ]; do
    case $1 in
        --seconds) SECONDS_TO_RUN=$2; shift 2 ;;
        --check)   CHECK=1; shift ;;
        --usbnet)  BUILD=build-qemu-usbnet
                   OVERLAY="sdkconfig.usb-ncm;sdkconfig.uart-console"
                   LABEL="USB-NCM"
                   shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

QEMU=$(find "$HOME/.espressif/tools/qemu-xtensa" -name qemu-system-xtensa -type f 2>/dev/null | head -1)
if [ -z "$QEMU" ]; then
    echo "Espressif QEMU not found. Install it with:" >&2
    echo "  python3 \$IDF_PATH/tools/idf_tools.py install qemu-xtensa" >&2
    echo "(Homebrew's qemu-system-xtensa will NOT do - it has no esp32s3 machine.)" >&2
    exit 1
fi

# Dedicated UART-console build (see the header). Rebuilt on demand so this
# script is self-contained; idf.py is incremental, so a warm tree is quick.
if ! command -v idf.py >/dev/null 2>&1; then
    echo "idf.py not on PATH; run . \$IDF_PATH/export.sh first" >&2
    exit 1
fi
echo "--- building the $LABEL image for QEMU ($BUILD)"
( cd "$FW" && idf.py -B "$BUILD" -DSDKCONFIG="$BUILD/sdkconfig" \
    -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;$OVERLAY" build ) >/dev/null

if [ ! -f "$FW/$BUILD/canary.bin" ]; then
    echo "build produced no image" >&2
    exit 1
fi

# QEMU wants one flat image, not the separate binaries idf.py flashes. 8 MB to
# match the -N8 module, so selftest's flash.size check means something here.
echo "--- assembling flash image"
( cd "$FW/$BUILD" && esptool.py --chip=esp32s3 merge_bin \
    --output=qemu_flash.bin --fill-flash-size=8MB \
    --flash_mode dio --flash_freq 80m --flash_size 8MB \
    0x0 bootloader/bootloader.bin \
    0x8000 partition_table/partition-table.bin \
    0xf000 ota_data_initial.bin \
    0x20000 canary.bin ) >/dev/null

[ -f "$FW/$BUILD/qemu_efuse.bin" ] || dd if=/dev/zero of="$FW/$BUILD/qemu_efuse.bin" \
    bs=1 count=124 >/dev/null 2>&1

LOG=${LOG:-/tmp/canary-qemu.log}
echo "--- booting (${SECONDS_TO_RUN}s) -> $LOG"

"$QEMU" -M esp32s3 -m 32M \
    -drive file="$FW/$BUILD/qemu_flash.bin",if=mtd,format=raw \
    -drive file="$FW/$BUILD/qemu_efuse.bin",if=none,format=raw,id=efuse \
    -global driver=nvram.esp32s3.efuse,property=drive,value=efuse \
    -nic user,model=open_eth -nographic > "$LOG" 2>&1 &
QEMU_PID=$!

# `sleep` then kill: QEMU has no built-in run-for-N-seconds, and the firmware
# never exits by design.
sleep "$SECONDS_TO_RUN"
kill "$QEMU_PID" 2>/dev/null || true
wait "$QEMU_PID" 2>/dev/null || true

echo
sed -e '/terminating on signal/d' "$LOG"

if [ "$CHECK" = 1 ]; then
    echo
    fails=0
    # POSITIVE assertion first. Every check below is a negative grep, so without
    # this an empty or truncated log -- a QEMU that never started, a console on a
    # sink QEMU does not carry, a boot that died in the 2nd-stage bootloader --
    # scores a clean pass. It did exactly that once; do not remove this.
    if ! grep -q "Calling app_main()" "$LOG"; then
        echo "FAIL: no evidence the app ever reached app_main()"
        echo "      (log has $(wc -l < "$LOG" | tr -d ' ') lines; if it stops at"
        echo "       'entry 0x...' the console is not on the UART QEMU captures)"
        fails=$((fails + 1))
    fi
    if ! grep -q "diag: logging started" "$LOG"; then
        echo "FAIL: diag never initialised - app_main died very early"
        fails=$((fails + 1))
    fi
    if grep -q "stack overflow" "$LOG"; then
        echo "FAIL: a task overflowed its stack during bring-up"
        fails=$((fails + 1))
    fi
    if grep -q "Guru Meditation" "$LOG"; then
        echo "FAIL: the firmware panicked"
        fails=$((fails + 1))
    fi
    if grep -q "rst:0xc (RTC_SW_CPU_RST)" "$LOG"; then
        echo "FAIL: the firmware rebooted - it is boot-looping"
        fails=$((fails + 1))
    fi
    if grep -q "isr service is not installed" "$LOG"; then
        echo "FAIL: a driver registered an ISR with no service installed"
        fails=$((fails + 1))
    fi
    if [ "$fails" = 0 ]; then
        echo "OK: booted with no panic, no reboot and no stack overflow"
    else
        exit 1
    fi
fi
