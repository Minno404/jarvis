"""Wake your PC from anywhere: runs on an always-on Android tablet (or any spare device) at home.

Your phone can't wake the PC over Tailscale (wake-up packets don't travel over the internet), but a device at home
can. This serves a tiny page on the tablet: open it on your phone (over Tailscale), press Wake, and the tablet sends
the wake-up packet on your home Wi-Fi. The page shows when Jarvis is up.

On the tablet (Termux):  python wake_helper.py --mac AA:BB:CC:DD:EE:FF --pc 100.x.y.z
  --mac   the PC's network card address (the one your phone's wake app uses)
  --pc    the PC's Tailscale address (from the Tailscale app), to check whether Jarvis is up
Then on your phone open  http://<the tablet's Tailscale address>:8766  and add it to the home screen.
Only Tailscale devices and this home network can use it.
"""
import argparse
import ipaddress
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8766
ALLOWED = [ipaddress.ip_network(n) for n in ("100.64.0.0/10", "fd7a:115c:a1e0::/48", "127.0.0.0/8",
                                             "10.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12")]

PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Wake Jarvis</title><style>body{background:#07090d;color:#ff4d5e;font:16px monospace;text-align:center;
padding:40px 16px}button{background:none;border:2px solid #ff4d5e;color:#ff4d5e;font:20px monospace;
padding:18px 40px;letter-spacing:4px}a{color:#ff9aa4}</style>
<h2>J A R V I S</h2><p id=s>Checking…</p><button onclick=wake()>WAKE</button><p id=l></p>
<script>
const JARVIS = "http://%(pc)s:8765/";
async function check(){const r=await (await fetch('status')).json();
  s.textContent=r.up?'PC is awake. Jarvis is online.':'PC is asleep.';
  l.innerHTML=r.up?'<a href="'+JARVIS+'">Open Jarvis</a>':''; return r.up}
async function wake(){await fetch('wake',{method:'POST'}); s.textContent='Waking the PC… (up to a minute)';
  for(let i=0;i<40;i++){await new Promise(r=>setTimeout(r,3000)); if(await check()){location.href=JARVIS;return}}
  s.textContent="It didn't wake. Is the tablet on the home Wi-Fi?"}
check()
</script>"""


def magic_packet(mac):
    raw = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    assert len(raw) == 6, "a MAC address is 6 pairs, like AA:BB:CC:DD:EE:FF"
    return b"\xff" * 6 + raw * 16


def wake(mac):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        targets = {"255.255.255.255"}
        try:  # also this network's own broadcast address (e.g. 10.0.0.255), which some routers need
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("8.8.8.8", 80))  # no packet is sent: it just picks the Wi-Fi address
                targets.add(probe.getsockname()[0].rsplit(".", 1)[0] + ".255")
        except OSError:
            pass
        for host in targets:
            for port in (9, 7):
                s.sendto(magic_packet(mac), (host, port))


def is_up(pc, port=8765):
    try:
        socket.create_connection((pc, port), timeout=2).close()
        return True
    except OSError:
        return False


def allowed(ip):
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
        a = getattr(a, "ipv4_mapped", None) or a
        return any(a in n for n in ALLOWED if a.version == n.version)
    except ValueError:
        return False


def serve(mac, pc, port=PORT):
    class H(BaseHTTPRequestHandler):
        def send(self, code, body, kind="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self):
            if not allowed(self.client_address[0]):
                return self.send(403, "{}")
            if self.path == "/status":
                return self.send(200, json.dumps({"up": is_up(pc)}))
            self.send(200, PAGE % {"pc": pc}, "text/html")

        def do_POST(self):
            if not allowed(self.client_address[0]) or self.path != "/wake":
                return self.send(403, "{}")
            wake(mac)
            self.send(200, '{"sent": true}')

        def log_message(self, *a):
            pass

    print(f"Wake helper on port {port}: open http://<this tablet's Tailscale address>:{port} on your phone")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mac", help="the PC's network card address")
    ap.add_argument("--pc", help="the PC's Tailscale address")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        p = magic_packet("AA:BB:CC:DD:EE:FF")
        assert len(p) == 102 and p[:6] == b"\xff" * 6 and p[6:12] == bytes.fromhex("AABBCCDDEEFF")
        assert allowed("100.101.102.103") and allowed("10.0.0.5") and allowed("::ffff:100.70.1.2")
        assert not allowed("8.8.8.8") and not allowed("2001:4860::1")
        print("wake helper self-test passed")
    elif not (a.mac and a.pc):
        ap.error("give --mac and --pc")
    else:
        serve(a.mac, a.pc, a.port)
