"""{USER}'s Hisense (VIDAA) TV, through the vidaa-control library (pip install vidaa-control).

One-time pairing: python tv_pair.py <TV IP>, run in the Jarvis folder. The library keeps the TV's address
(config.yaml) and login (tokens.json) there, and Jarvis uses that default TV. Each command connects,
does its thing and disconnects, so Jarvis never holds the TV.
"""
import time

import features

# Friendly words -> the library's key names
KEYS = {"channel up": "channelup", "channel down": "channeldown", "volume up": "volumeup",
        "volume down": "volumedown", "mute": "mute", "home": "home", "back": "back", "ok": "ok", "up": "up",
        "down": "down", "left": "left", "right": "right", "play": "play", "pause": "pause", "stop": "stop",
        "menu": "menu", "info": "info", "exit": "exit", "subtitles": "subtitle"}


def _paired():
    import os
    os.chdir(features.HERE)  # the pairing (config.yaml, tokens.json) lives in the Jarvis folder
    from vidaa.config import list_tvs
    tvs = list_tvs()
    if not tvs:
        raise ConnectionError("The TV isn't paired yet. Run: python tv_pair.py <TV IP> in the Jarvis folder.")
    return next((x for x in tvs if x.get("is_default")), tvs[0])


def _tv(timeout=4):
    from vidaa.client import VidaaTV
    from vidaa.protocol import AuthMethod
    t = _paired()
    # The paired ID is the TV entry's key (device_id); the library's own loader misses it. Its protocol check
    # times out on this TV (5 s every time), so use the login that worked when pairing and skip the check.
    tv = VidaaTV(host=t["host"], port=t.get("port", 36669), mac_address=t["device_id"], use_dynamic_auth=True,
                 brand=t.get("brand", "his"), auth_method=AuthMethod.MODERN, auto_detect_protocol=False)
    if not tv.connect(timeout=timeout, try_fallback=False):
        raise ConnectionError("Can't reach the TV. It may be fully off: Jarvis can wake it once he knows its MAC "
                              "address and 'Wake on LAN' is on in the TV's network settings.")
    _learn_mac(t["host"])
    return tv


def _learn_mac(host):
    """Remember the TV's own MAC address (from Windows' ARP table) so Jarvis can wake it later."""
    import re
    import subprocess
    state = features._load("state.json", {})
    if state.get("tv_mac"):
        return
    try:
        out = subprocess.run(["arp", "-a", host], capture_output=True, text=True, timeout=3,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        m = re.search(r"([0-9a-f]{2}[:-]){5}[0-9a-f]{2}", out, re.I)
        if m:
            state["tv_mac"] = m.group(0).upper().replace("-", ":")
            features._save("state.json", state)
    except Exception:
        pass


def _do(fn, timeout=4):
    tv = _tv(timeout)
    try:
        return fn(tv)
    finally:
        time.sleep(0.3)  # let the last command reach the TV before hanging up
        tv.disconnect()


def tv_power(on):
    if not on:
        return {"off": _do(lambda tv: tv.power_off())}
    try:  # in standby the TV usually still answers
        return {"on": _do(lambda tv: tv.power_on(), timeout=3)}
    except ConnectionError:
        pass
    mac = features._load("state.json", {}).get("tv_mac")
    if not mac:
        return {"error": "The TV's fully off and Jarvis doesn't know its MAC address yet. Turn it on with the remote "
                         "once while Jarvis is running (he'll learn it), and switch on 'Wake on LAN' in the TV's "
                         "network settings."}
    from vidaa.wol import wake_tv
    host = _paired()["host"]
    for attempt in range(6):  # wake packets, then short retries: about 20 s at most
        if attempt % 2 == 0:
            wake_tv(mac, host.rsplit(".", 1)[0])
        time.sleep(2.5)
        try:
            return {"on": _do(lambda tv: tv.power_on(), timeout=2)}
        except ConnectionError:
            continue
    return {"error": "Sent the wake signal but the TV didn't answer. Check 'Wake on LAN' (or 'Wake on Wireless "
                     "Network') is on in its network settings. Some Hisense TVs can't wake over Wi-Fi."}


def tv_input(source):
    s = source.lower().replace(" ", "")
    return {"switched_to": source, "sent": _do(lambda tv: tv.set_source(s))}


def tv_sources():
    # depending on the TV, inputs come back as plain names or as {sourcename, sourceid}
    return _do(lambda tv: [x if isinstance(x, str) else {"name": x.get("sourcename", x.get("name")),
                                                         "id": x.get("sourceid")} for x in (tv.get_sources() or [])])


def tv_keys(keys):
    """Remote buttons in order, e.g. ['channel up'] or ['7', 'ok'] for channel 7."""
    from vidaa.keys import KEY_NAME_MAP
    names = [KEYS.get(k.lower().strip(), k.lower().replace(" ", "")) for k in keys]
    bad = [k for k in names if k not in KEY_NAME_MAP]
    if bad:
        return {"error": f"Unknown buttons: {bad}", "buttons": sorted(set(KEYS) | {str(d) for d in range(10)})}

    def press(tv):
        for k in names:
            tv.send_key(KEY_NAME_MAP[k])
            time.sleep(0.35)
        return True
    return {"pressed": keys, "sent": _do(press)}


def tv_channel(number):
    return tv_keys(list(str(int(number))) + ["ok"])


def tv_volume(level=None, change=None):
    if level is not None:
        return {"volume": int(level), "sent": _do(lambda tv: tv.set_volume(int(level)))}
    steps = int(change or 0)
    return tv_keys(["volume up" if steps > 0 else "volume down"] * min(abs(steps), 20)) if steps else {"error": "Give level or change"}


def tv_app(name):
    return {"launched": name, "sent": _do(lambda tv: tv.launch_app(name))}


def tv_status():
    return _do(lambda tv: {"state": tv.get_state(timeout=3), "volume": tv.get_volume(timeout=3)})


def tv_set_mac(mac):
    """Save the TV's MAC address so Jarvis can wake it from standby."""
    mac = mac.strip().upper().replace("-", ":")
    state = features._load("state.json", {})
    state["tv_mac"] = mac
    features._save("state.json", state)
    return {"saved": mac}


FUNCS = {f.__name__: f for f in (tv_power, tv_input, tv_sources, tv_keys, tv_channel, tv_volume, tv_app,
                                 tv_status, tv_set_mac)}
S = {"type": "string"}
TOOLS = [
    {"name": "tv_power", "description": "Turn {USER}'s Hisense TV on or off.",
     "input_schema": {"type": "object", "required": ["on"], "properties": {"on": {"type": "boolean"}}}},
    {"name": "tv_input", "description": "Switch the TV's input: hdmi1, hdmi2, hdmi3, tv, av, or a name from "
     "tv_sources (e.g. the console he's named).",
     "input_schema": {"type": "object", "required": ["source"], "properties": {"source": S}}},
    {"name": "tv_sources", "description": "The TV's inputs and their names.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "tv_channel", "description": "Go to a TV channel by number.",
     "input_schema": {"type": "object", "required": ["number"], "properties": {"number": {"type": "integer"}}}},
    {"name": "tv_keys", "description": "Press TV remote buttons in order: channel up/down, volume up/down, mute, "
     "home, back, ok, up/down/left/right, play, pause, stop, menu, info, subtitles, digits 0-9.",
     "input_schema": {"type": "object", "required": ["keys"], "properties": {"keys": {"type": "array", "items": S}}}},
    {"name": "tv_volume", "description": "TV volume: level 0-100, or change by steps (+3, -2).",
     "input_schema": {"type": "object", "properties": {"level": {"type": "integer"}, "change": {"type": "integer"}}}},
    {"name": "tv_app", "description": "Open an app on the TV: netflix, youtube, amazon, disney, or any installed "
     "app by its name.", "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S}}},
    {"name": "tv_status", "description": "Whether the TV is on, what it's showing, and its volume.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "tv_set_mac", "description": "Save the TV's MAC address (from its network settings) so Jarvis can "
     "wake it from standby.", "input_schema": {"type": "object", "required": ["mac"], "properties": {"mac": S}}},
]


def selftest():
    import sys
    import types
    sent = []

    class FakeTV:
        def connect(self, timeout, try_fallback=True): return True
        def disconnect(self): sent.append("bye")
        def send_key(self, k): sent.append(k); return True
        def set_source(self, s): sent.append(("source", s)); return True
        def power_on(self): sent.append("on"); return True
    client, config, keys, proto = (types.ModuleType(n) for n in ("vidaa.client", "vidaa.config", "vidaa.keys",
                                                                   "vidaa.protocol"))
    proto.AuthMethod = types.SimpleNamespace(MODERN="modern")
    made = []
    client.VidaaTV = lambda **kw: made.append(kw) or FakeTV()
    config.list_tvs = lambda: [{"device_id": "AA:BB:CC:00:11:22", "is_default": True, "host": "192.168.1.50",
                                "port": 36669, "brand": "his"}]
    keys.KEY_NAME_MAP = {"channelup": "KEY_CHANNELUP", "ok": "KEY_OK", **{str(d): f"KEY_{d}" for d in range(10)},
                         "volumedown": "KEY_VOLUMEDOWN"}
    sys.modules.update({"vidaa": types.ModuleType("vidaa"), "vidaa.client": client, "vidaa.config": config,
                        "vidaa.keys": keys, "vidaa.protocol": proto})
    global _learn_mac
    real_learn, _learn_mac = _learn_mac, lambda host: None
    global time
    real, time = time, types.SimpleNamespace(sleep=lambda s: None)
    try:
        assert tv_channel(72)["sent"] and sent[:3] == ["KEY_7", "KEY_2", "KEY_OK"]
        sent.clear()
        tv_input("HDMI 2")
        assert sent[0] == ("source", "hdmi2")
        assert "error" in tv_keys(["self destruct"])
        sent.clear()
        tv_volume(change=-2)
        assert sent[:2] == ["KEY_VOLUMEDOWN", "KEY_VOLUMEDOWN"]
        assert tv_power(True) == {"on": True}
        assert made[0]["mac_address"] == "AA:BB:CC:00:11:22" and made[0]["use_dynamic_auth"]
        assert made[0]["auto_detect_protocol"] is False and made[0]["auth_method"] == "modern"
    finally:
        time = real
        _learn_mac = real_learn
        for m in ("vidaa", "vidaa.client", "vidaa.config", "vidaa.keys", "vidaa.protocol"):
            sys.modules.pop(m, None)
    print("tv self-test passed")


if __name__ == "__main__":
    selftest()
