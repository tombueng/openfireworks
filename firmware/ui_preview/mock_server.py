#!/usr/bin/env python3
"""Preview of the firmware web UI (firmware/openfireworks_node_v2/webui.h) with mock /api/status data, so the channel
display can be looked at without a board. Run: python3 firmware/ui_preview/mock_server.py [port] [SAFE|ARMED]
Mock only: no hardware, no security; every POST just answers {"ok":true}."""
import http.server, json, os, re, sys, random

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
src = open(os.path.join(ROOT, "firmware", "openfireworks_node_v2", "webui.h")).read()
HTML = re.search(r'R"HTML\((.*)\)HTML"', src, re.S).group(1).replace("%N%", "mock")
STATE = sys.argv[2] if len(sys.argv) > 2 else "SAFE"


def status():
    random.seed(3)
    ch = []
    for i in range(24):
        if i in (5, 6, 17, 22, 23):
            c = dict(cls="noplug", v=3.30, r=None)
        elif i == 11:
            c = dict(cls="open", v=2.10, r=-1)
        elif i == 14:
            c = dict(cls="short", v=0.02, r=0)
        else:
            c = dict(cls="ok", v=round(0.05 + random.random() * 0.03, 2), r=1800 + random.randint(0, 600))
        c.update(fired=False, elig=(c["cls"] == "ok"), ovr=False, fault=None)
        ch.append(c)
    ch[2].update(fired=True, firedAgo=42000, res="ok", fms=4.0, elig=False)
    ch[9]["fault"] = "sense lag 1.8 ms (corrected)"
    return dict(csrf="x", name="node-north", ssid="node-3F2A", state=STATE, vsys=5.62, vrest=6.12, vfire=5.58 if STATE == "ARMED" else 0.0,
                v5led=4.98, temp=31, fwArm=1 if STATE == "ARMED" else 0, fwOe=0, oeRb=1, armBtn=1, armPending=False, armPendingMs=0,
                armedMs=95000, armTimeoutS=900, fault="", pulse=4.0, clients=1, rssiMin=-58, uptime=1234000, wdt=2000,
                latched="000000", serial="OFW-3F2A-7C19-0B44", birthUnknown=False, fw="2.3.0", variant="show", build="a1b2c3d4e5f6",
                st={"T0": "pass", "T1": "pass", "scan": "pass", "T2": "pass", "T3": "pass", "T5": "pass", "OE_RB": "pass",
                    "all": "pass", "at": 1100000},
                batt=dict(ok="pass", rest=6.12, load=5.71, loadMa=520, r=0.79, ipred=3.4, at=1150000),
                seqRun=False, seqIdx=0, seqN=3, seqT=0, ch=ch,
                ev=[dict(t=1100000, m="self-test pass"), dict(t=1150000, m="battery pass: 6.12 V rest, 0.79 ohm"),
                    dict(t=1190000, m="J3 fired ok 4.0 ms")])


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        b = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/status"):
            self._send(200, json.dumps(status()), "application/json")
        else:
            self._send(200, HTML, "text/html; charset=utf-8")

    def do_POST(self):
        self._send(200, json.dumps({"ok": True, "n": 3}), "application/json")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8020), H).serve_forever()
