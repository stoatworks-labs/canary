"""
Tests for the board test runner.

A test rig that has never been run is not evidence about anything, so this
suite does two things:

  1. Tests the console transcript parser directly. That parser has to survive
     ESP-IDF log lines interleaved with the self-test output, because the
     logger and printf share one UART and neither waits for the other. It also
     has to notice a TRUNCATED transcript - a run that was cut off halfway
     looks exactly like a clean run with fewer checks.

  2. Runs the whole runner end to end against tools/r70_emu.py. Every stage
     except the serial console and the CAN wire exercises the same code paths
     it will use against a real board, today, with no hardware.
"""

import json
import socket

import pytest

import board_test
from board_test import FAIL, PASS, SKIP, parse_selftest


# --- ports -----------------------------------------------------------------
def free_port(kind: int) -> int:
    """A port the OS says is free. Beats a hard-coded one: these tests must be
    able to run alongside a real emulator, and on CI in parallel."""
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def ports():
    return free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)


# --- transcript parsing ----------------------------------------------------
CLEAN = """\
I (312) selftest: LED walk: D301 LAN should be the ONLY one lit
RESULT chip INFO ESP32-S3 rev v0.2, 2 core(s), idf v5.5.5
RESULT flash.size PASS 8 MB (expect >= 8 MB for the -N8 module)
RESULT mac.eth PASS 84:FC:E6:00:11:22
RESULT eth.versionr PASS 0x04 at 4 MHz
RESULT can.loopback PASS 8-byte frame round-tripped
SELFTEST-END pass=4 fail=0 skip=0 info=1
JSON {"schema":"canary.selftest/1","results":[],"pass":4,"fail":0,"skip":0,"info":1}
OK
"""


def test_parses_a_clean_transcript():
    results, tally, blob = parse_selftest(CLEAN)
    assert [r["name"] for r in results] == [
        "chip", "flash.size", "mac.eth", "eth.versionr", "can.loopback"]
    assert tally == {"pass": 4, "fail": 0, "skip": 0, "info": 1}
    assert blob["schema"] == "canary.selftest/1"
    assert results[0]["detail"].startswith("ESP32-S3")


def test_survives_interleaved_log_lines():
    """The logger writes to the same UART as printf and does not wait for it,
    so a log line can land in the middle of the results."""
    noisy = CLEAN.replace(
        "RESULT mac.eth",
        "W (400) spi: bus already initialised\nRESULT mac.eth")
    results, tally, _ = parse_selftest(noisy)
    assert len(results) == 5
    assert tally["fail"] == 0


def test_a_failure_is_not_lost():
    text = CLEAN.replace("RESULT can.loopback PASS 8-byte frame round-tripped",
                         "RESULT can.loopback FAIL nothing received within 200 ms")
    results, _, _ = parse_selftest(text)
    bad = [r for r in results if r["verdict"] == FAIL]
    assert len(bad) == 1
    assert bad[0]["name"] == "can.loopback"


def test_truncated_transcript_has_no_tally():
    """The whole point of SELFTEST-END: without it, a cut-off run is
    indistinguishable from a short clean one."""
    truncated = "\n".join(CLEAN.splitlines()[:4])
    results, tally, _ = parse_selftest(truncated)
    assert results          # some results did arrive
    assert tally == {}      # but the runner must not treat this as complete


def test_unparseable_json_line_is_reported_not_swallowed():
    text = CLEAN.replace('JSON {"schema"', 'JSON {oops "schema"')
    _, _, blob = parse_selftest(text)
    assert blob == {"error": "unparseable JSON line"}


def test_no_results_at_all():
    results, tally, blob = parse_selftest("canary> \nhelp\nOK\n")
    assert results == [] and tally == {} and blob == {}


# --- end to end against the emulator ---------------------------------------
def test_simulated_run_passes(ports, tmp_path, capsys):
    udp, tcp = ports
    record = tmp_path / "record.json"
    rc = board_test.main([
        "--simulate", "--udp-port", str(udp), "--tcp-port", str(tcp),
        "--serial-number", "SIM-0001", "--record", str(record),
    ])
    assert rc == 0, capsys.readouterr().out

    data = json.loads(record.read_text())
    assert data["schema"] == "canary.board-test/1"
    assert data["serial_number"] == "SIM-0001"
    assert data["simulated"] is True
    assert data["summary"]["fail"] == 0
    assert data["summary"]["pass"] > 10


def test_simulated_run_records_what_it_could_not_test(ports, tmp_path):
    """A summary that says "0 skipped" is claiming it looked at everything.
    A simulated run has no serial console and no CAN wire and must say so."""
    udp, tcp = ports
    record = tmp_path / "record.json"
    board_test.main(["--simulate", "--udp-port", str(udp), "--tcp-port", str(tcp),
                     "--record", str(record)])
    data = json.loads(record.read_text())

    skipped = {c["stage"] for c in data["checks"] if c["verdict"] == SKIP}
    assert skipped == {"console", "can"}
    assert "SIMULATED" in data["note"]


def test_every_rmbcp_check_runs(ports, tmp_path):
    """Guards against a stage quietly returning early and still reporting a
    clean run - the failure mode that makes a test rig worse than none."""
    udp, tcp = ports
    record = tmp_path / "record.json"
    board_test.main(["--simulate", "--udp-port", str(udp), "--tcp-port", str(tcp),
                     "--record", str(record)])
    names = {c["name"] for c in json.loads(record.read_text())["checks"]
             if c["stage"] == "rmbcp"}
    assert names == {
        "connect", "device-id", "version", "error-status", "busload",
        "can-baud", "block-time-echo", "reset-answers-device-id",
        "silent-interfaces-version", "silent-baud-calc-interval",
        "alive-after-can-frame",
    }


def test_discovery_failure_is_a_failure_not_a_skip(tmp_path):
    """Nothing is listening on this port. The runner must report FAIL, not
    quietly pass because it found nothing to disagree with."""
    udp, tcp = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)
    record = tmp_path / "record.json"
    rc = board_test.main([
        "--broadcast", "127.0.0.1", "--udp-port", str(udp), "--tcp-port", str(tcp),
        "--timeout", "0.4", "--record", str(record),
    ])
    assert rc == 1

    checks = json.loads(record.read_text())["checks"]
    discover = [c for c in checks if c["stage"] == "discover"]
    assert discover and discover[0]["verdict"] == FAIL
    # And rmbcp must say it had no address, not invent one.
    rmbcp_checks = [c for c in checks if c["stage"] == "rmbcp"]
    assert rmbcp_checks and rmbcp_checks[0]["verdict"] == SKIP


def test_r1_probe_is_the_real_capture():
    """The discovery stage sends R1's own bytes. If someone regenerates this
    from our encoder it stops being evidence about R1 and starts being evidence
    about us."""
    assert len(board_test.R1_PROBE) == 68
    assert board_test.R1_PROBE[2] == 0x80          # OP_REQUEST
    assert board_test.R1_PROBE[18:22] == b"R70 "   # the tag R1 asks for
