#!/usr/bin/env python3
"""A mock CANary, so the REAL page can be driven in a browser without a board.

WHY: components/webui only ever runs on a unit with a USB host attached, and
nothing has ever enumerated this device. Without this, the page could only be
reasoned about. It serves the ACTUAL www/index.html - not a copy - plus /api
responses, so what is exercised is the page that gets embedded in the firmware.

    python3 mock_device.py            # http://127.0.0.1:5211
    python3 mock_device.py --port N

It also fakes the states that are hard to produce deliberately on a bench.
GET /scenario/<name> switches between them:

    nominal     everything up, R1 connected
    nolease     USB host attached but it has taken no address  <- the D301
                heartbeat case, and the failure most likely in practice
    linklocal   no DHCP server on the LAN, so AUTOIP self-assigned
    usb-only    no LAN cable at all
    nocan       CAN bus-off
    crashed     a coredump is stored from a previous boot

WHAT IT DOES NOT PROVE: none of the C in webui.c runs here. The USB-subnet
check in webui_open(), the OTA path into the flash partitions, the real
validator and the chunked coredump reader all need a board. This proves the
PAGE: that it renders, populates, validates, shows the server's reasons, and
recovers after a reboot."""
import json, time, http.server, socketserver, urllib.parse

import argparse, os

# The real page, not a copy: this file sits next to it in the component.
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www",
                    "index.html")
START = time.time()

STATE = {
    "hostname": "CANary", "base_port": 30000, "socket_count": 4,
    "eth_mode": "dhcp", "eth_ip": "", "eth_netmask": "", "eth_gw": "",
    "stored": False, "hostname_max": 27,
}
SCENARIO = {"name": "nominal"}


def status():
    s = SCENARIO["name"]
    return {
        "version": "9cbc5f0-dirty", "idf": "v5.5.5", "built": "Sep 21 2026",
        "uptime_s": int(time.time() - START), "heap_free": 231424,
        "eth": {
            "link": s != "usb-only",
            "ip": {"nominal": "192.0.2.27", "linklocal": "169.254.8.3",
                   "usb-only": "", "nocan": "192.0.2.27"}.get(s, "192.0.2.27"),
            "link_local": s == "linklocal",
        },
        "usb": {"link": True, "ip": "192.168.7.1",
                "host_ip": "" if s == "nolease" else "192.168.7.2"},
        "r1": {"connected": s == "nominal"},
        "can": {"state": "bus-off" if s == "nocan" else "running",
                "busload": 0 if s == "nocan" else 137},
        "coredump": s == "crashed", "coredump_bytes": 17920 if s == "crashed" else 0,
    }


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            self._send(200, open(PAGE, "rb").read(), "text/html")
        elif path == "/api/status":
            self._send(200, json.dumps(status()))
        elif path == "/api/config":
            self._send(200, json.dumps(STATE))
        elif path == "/api/diagnostics":
            self._send(200, json.dumps({"schema": "stoatworks.diagnostics/1"}))
        elif path == "/api/diagnostics/coredump":
            self._send(200, b"\x7fELF" + b"\0" * 64, "application/octet-stream")
        elif path.startswith("/scenario/"):
            SCENARIO["name"] = path.rsplit("/", 1)[-1]
            self._send(200, json.dumps({"scenario": SCENARIO["name"]}))
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        if path == "/api/config":
            try:
                doc = json.loads(body)
            except Exception:
                return self._send(400, "that is not JSON", "text/plain")
            # Mirror the real validator's messages for the cases the page shows.
            if len(doc.get("hostname", "")) == 0:
                return self._send(400, "host name is empty", "text/plain")
            if doc.get("base_port", 0) < 1024:
                return self._send(400, "ports below 1024 are reserved", "text/plain")
            if doc.get("eth_mode") == "static" and not doc.get("eth_ip"):
                return self._send(
                    400, "static address is not one an interface can hold", "text/plain")
            STATE.update(doc)
            STATE["stored"] = True
            self._send(200, json.dumps({"saved": True,
                                        "note": "takes effect at the next boot"}))
        elif path == "/api/config/reset":
            STATE.update({"hostname": "CANary", "base_port": 30000,
                          "socket_count": 4, "eth_mode": "dhcp",
                          "eth_ip": "", "eth_netmask": "", "eth_gw": "",
                          "stored": False})
            self._send(200, json.dumps({"reset": True}))
        elif path == "/api/reboot":
            self._send(200, json.dumps({"rebooting": True}))
        elif path == "/api/ota":
            if len(body) < 1024:
                return self._send(
                    400, "that is not a valid image for this board", "text/plain")
            self._send(200, json.dumps({"written": True}))
        else:
            self._send(404, "not found", "text/plain")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=5211)
    args = ap.parse_args()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), H) as srv:
        print("mock CANary on http://127.0.0.1:%d/  "
              "(scenarios: /scenario/nolease etc.)" % args.port)
        srv.serve_forever()
