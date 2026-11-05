"""Pair Jarvis with a Hisense (VIDAA) TV, run once in the Jarvis folder:  python tv_pair.py <TV IP address>

Uses this PC's MAC address as Jarvis's ID with the TV (the vidaa tool's own 'config add' stores the IP
there, which the TV rejects), shows each step, then saves the pairing as the default TV for Jarvis.
"""
import logging
import sys
import uuid

from vidaa.client import VidaaTV
from vidaa.config import add_tv, set_default_tv, DEFAULT_PORT
from vidaa.protocol import detect_protocol

logging.basicConfig(level=logging.INFO, format="  %(message)s")
ip = sys.argv[1] if len(sys.argv) > 1 else input("TV IP address (TV Settings > Network > Network Information): ").strip()
mac = ":".join(f"{(uuid.getnode() >> s) & 0xFF:02X}" for s in range(40, -1, -8))  # this PC's MAC
print(f"Jarvis ID: {mac}\nTV: {ip}")

version = detect_protocol(ip, timeout=5)
print(f"TV software protocol: {version or 'could not read it (fine if the TV answers below)'}")

tv = VidaaTV(host=ip, port=DEFAULT_PORT, mac_address=mac, use_dynamic_auth=True, brand="his")
print("Connecting...")
if not tv.connect(timeout=10):
    print("\nThe TV refused the connection. Check that this is the TV's IP (TV Settings > Network >\n"
          "Network Information) and that the TV is on, then send Claude a screenshot of this window.")
    sys.exit(1)
print("Connected. Asking the TV for a PIN...")
tv.start_pairing()
pin = input("Type the PIN shown on the TV and press Enter: ").strip()
if not tv.authenticate(pin):
    print("The TV didn't accept that PIN. Run this again to get a new one.")
    tv.disconnect()
    sys.exit(1)
add_tv(mac, ip, alias="tv", name="Living room TV", mac=mac)  # 'mac' too, so the vidaa command line finds it
set_default_tv("tv")
print("\nPaired! Jarvis can now control the TV. Testing: TV volume to 10...")
tv.set_volume(10)
sources = tv.get_sources() or []
print("Inputs:", ", ".join(s if isinstance(s, str) else f"{s.get('sourcename', s.get('name'))} ({s.get('sourceid')})"
                           for s in sources) or "(none listed)")
tv.disconnect()
