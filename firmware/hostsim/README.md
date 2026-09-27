# hostsim — the shipping firmware, as a host process

`canaryd` links the **real** C from `firmware/components` (bridge, rmbcp,
r70_ddt, dbcan) against stand-ins for the slice of ESP-IDF it uses, and puts it
on real sockets.

## Why this exists

`tools/r70_emu.py` is the emulator that was proven against real R1 V3.46, and
it is excellent evidence — but it is a Python *re-implementation*. The C that
actually goes on the board had only ever been checked one component at a time,
against unit vectors. Nothing had exercised the assembled bridge: the session
state machine, the discovery responder and the CAN return path, together, under
a client that did not come from this repo.

Point R1 at `canaryd` and R1 is driving the code that ships.

```
    R1 / board_test.py  <--TCP 30000 / UDP 33333-->  canaryd
                                                         |
                                                     vcan hub
                                                         |
                                                  tools/vamp.py
```

## Running it

```sh
./build.sh                       # -> ./canaryd
./canaryd --ip 127.0.0.1

# the project's own acceptance runner, against the C instead of a board:
python3 ../../tools/board_test.py --host 127.0.0.1 --broadcast 127.0.0.1 \
        --skip console,can
```

The whole integration suite, including the virtual CAN loop and a short fuzz:

```sh
test/run_tests.sh
```

`../../run_tests.sh` calls that after the unit tests. `SKIP_HOSTSIM=1` omits it;
`FUZZ_ITERATIONS=0` keeps it but drops the fuzzing.

## What it does and does not prove

**Does:** framing and checksums on a real stream with real packet boundaries;
the discovery answer to R1's byte-exact probe; the session state machine;
one-master-at-a-time; the two commands that must stay silent; CAN frames out to
the bus and device replies back; behaviour under malformed and hostile input.
`bridge_local_ip_for()` is answered here from the host's own routing table -
connect() on a UDP socket picks the source address the kernel would really use
for that peer - so the per-peer contract the two-interface firmware depends on
is exercised rather than stubbed.

**Does not:** W5500 over SPI, TWAI silicon, `net.c`, boot, NVS, partitions, task
stack sizing, or anything about timing. Host stacks are not the target's and the
shim ignores stack depth and priority deliberately rather than pretending.
For the boot path use `firmware/qemu`; for the peripherals there is no
substitute for a board.

## Layout

```
shim/          ESP-IDF stand-ins: esp_err, esp_log, FreeRTOS tasks as pthreads,
               lwip headers redirected to the host's BSD sockets, and
               driver/twai.h backed by the virtual bus
runtime.c      the shim implementations
vcan.c         virtual TWAI over UDP -> tools/vcan.py
host_main.c    argument parsing, bridge_local_ip_for(), start-up
fuzz/          the two network-facing parsers under ASan+UBSan
test/          integration and soak
```

The component sources are compiled **unmodified**. If one stops building here it
has grown a dependency the shim does not cover — extend the shim, do not adapt
the component.

## The virtual CAN bus

`tools/vcan.py hub` reflects each UDP datagram to every participant except the
sender, which is what a CAN bus looks like from a node. SocketCAN's `vcan` would
be the obvious choice and is Linux-only; this project is developed on a Mac.

There is no arbitration, no bit timing, no error counters and no real bus-off.
Use it for protocol and plumbing, never for a timing claim.

`tools/vamp.py` puts `dbcan_device.VirtualDevice` instances on that bus. Read
its scope warning before believing anything it tells you about R1: dbCAN's
identifier layout is documented, its application layer is not, so the devices
address frames correctly and cannot speak an amplifier's language.

## Fuzzing

```sh
fuzz/run_fuzz.sh --iterations 2000000
```

Targets are written to libFuzzer's `LLVMFuzzerTestOneInput` interface. Apple's
clang ships no libFuzzer, so `standalone_main.c` drives them instead — a seeded,
deterministic mutator over a corpus of real protocol vectors. The bug detector
is ASan/UBSan either way; libFuzzer would add coverage feedback. A clean run
here is weaker evidence than a clean libFuzzer run, and `run_fuzz.sh` says so.

This is not theoretical. The first real run found a remotely triggerable
out-of-bounds read in `rmbcp_decoder_next` — see the Length=0 regression vectors
in `components/rmbcp/test/test_rmbcp.c`.

**A note on sanitizers.** `rmbcp_frame_t` is `{command; data[254]; len;}`, so a
write one byte past `data` lands on `len` — inside the same object, where ASan
cannot see it. The fuzz harness asserts the decoder's state invariants
explicitly for that reason. Do not assume the sanitizers are enough on structs
like this.
