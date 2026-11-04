"""Jarvis's extra abilities: memory, reminders and timers, clips, routines, PC stats and weather.

Each public function here is a tool Jarvis can run (`python server.py tool <name> '<json>'`).
Small JSON files in the Jarvis folder hold what needs to survive a restart.
"""
import datetime
import json
import os
import re
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).parent
REGISTRY = {}  # every tool by name, filled in by server.py (routines call other tools through it)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _load(name, default):
    f = HERE / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default


def _save(name, obj):
    f = HERE / name
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    tmp.replace(f)  # atomic: a crash never leaves half a file


def _next_id(items):
    return max((i["id"] for i in items), default=0) + 1


def _now():
    return datetime.datetime.now()


# ---------- Who Jarvis works for (asked on first launch, kept in settings.json) ----------
def settings():
    return {"name": "", "city": "", "title": "sir", **_load("settings.json", {})}


def save_settings(name, city="", title="sir"):
    s = {**settings(), "name": name.strip(), "city": city.strip(), "title": title.strip() or "sir"}
    _save("settings.json", s)
    return s


def personal(text):
    """Fill in the user's name in anything Jarvis says or is told ({USER} in prompts and tool descriptions)."""
    return text.replace("{USER}", settings()["name"] or "the user")


def address(text):
    """Jarvis's own lines say 'sir'; use whatever the user asked to be called instead."""
    title = settings()["title"]
    return text if title.lower() == "sir" else re.sub(r"\bsir\b", title, text)


# ---------- Memory ----------
def remember(fact, source="asked"):
    """source: 'asked' (he told Jarvis to remember it) or 'learned' (picked up from conversation)."""
    mem = _load("memory.json", [])
    mem.append({"id": _next_id(mem), "fact": fact.strip(), "saved": _now().strftime("%Y-%m-%d"), "source": source})
    _save("memory.json", mem)
    return {"remembered": fact}


def forget(id=None, text=None):
    mem = _load("memory.json", [])
    keep = [m for m in mem if not (m["id"] == id or (text and text.lower() in m["fact"].lower()))]
    _save("memory.json", keep)
    return {"forgot": len(mem) - len(keep)}


def memories():
    return _load("memory.json", [])


def memory_prompt():
    mem = memories()
    if not mem:
        return ""
    return personal("\nWhat you know about {USER} (id: fact; 'learned' = picked up from conversation, not asked):\n"
            + "\n".join(f"{m['id']}: {m['fact']}" + (" (learned)" if m.get("source") == "learned" else "")
                         for m in mem))


# ---------- Reminders and timers ----------
def add_reminder(text, at=None, in_minutes=None):
    if in_minutes is not None:
        when = _now() + datetime.timedelta(minutes=float(in_minutes))
    elif at:
        when = datetime.datetime.strptime(at.strip()[:16], "%Y-%m-%d %H:%M")
    else:
        return {"error": "Give either at ('YYYY-MM-DD HH:MM', local time) or in_minutes"}
    rem = _load("reminders.json", [])
    item = {"id": _next_id(rem), "at": when.strftime("%Y-%m-%d %H:%M:%S"), "text": text}
    _save("reminders.json", rem + [item])
    return {"set": item}


def list_reminders():
    return sorted(_load("reminders.json", []), key=lambda r: r["at"])


def cancel_reminder(id):
    rem = _load("reminders.json", [])
    keep = [r for r in rem if r["id"] != id]
    _save("reminders.json", keep)
    return {"cancelled": len(rem) - len(keep)}


def due_reminders(now=None):
    """Take the reminders that are due off the list and return them."""
    now = (now or _now()).strftime("%Y-%m-%d %H:%M:%S")
    rem = _load("reminders.json", [])
    due = [r for r in rem if r["at"] <= now]
    if due:
        _save("reminders.json", [r for r in rem if r["at"] > now])
    return due


# ---------- Keys, processes, clips ----------
VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, **{f"f{n}": 0x6F + n for n in range(1, 13)}}


def press(combo):
    """Press a key combo like 'f8' or 'alt+f9' the way a keyboard would (games and recorders see it)."""
    import ctypes
    u = ctypes.windll.user32
    keys = [VK.get(k) or ord(k.upper()) for k in combo.lower().replace(" ", "").split("+")]
    for k in keys:
        u.keybd_event(k, u.MapVirtualKeyW(k, 0), 0, 0)
    time.sleep(0.05)
    for k in reversed(keys):
        u.keybd_event(k, u.MapVirtualKeyW(k, 0), 2, 0)


def running():
    """Names of running programs, e.g. {'medal.exe', 'terminal64.exe'}."""
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    return {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line}


CLIP_KEY = os.environ.get("JARVIS_CLIP_KEY", "f8")  # Medal's default clip key


def clip_that():
    if "medal.exe" not in running():
        REGISTRY["open_app"]("Medal")
        return {"error": "Medal wasn't running, so there was nothing to clip. I've opened it, so clips work from now on."}
    press(CLIP_KEY)
    return {"clipped": True}


def is_clip_command(text):
    """'clip that', 'Jarvis, clip it!' and the like: handled instantly, without asking Claude."""
    t = re.sub(r"[^a-z ]", "", text.lower()).strip()
    return bool(re.fullmatch(r"(hey )?(jarvis )?(clip|clip (that|it|this)|clip that jarvis)", t))


APP_EXES = {"metatrader": "terminal64.exe", "mt5": "terminal64.exe", "discord": "discord.exe",
            "league": "leagueclient.exe", "spotify": "spotify.exe", "chrome": "chrome.exe",
            "medal": "medal.exe", "steam": "steam.exe", "edge": "msedge.exe"}


def close_app(name):
    """Ask an app to close normally (like clicking X), so nothing unsaved is lost without it asking."""
    q = name.lower().replace(" ", "")
    exe = next((e for k, e in APP_EXES.items() if k in q), None)
    procs = running()
    if not exe or exe not in procs:
        exe = next((p for p in sorted(procs) if q in p.replace(" ", "")), None)
    if not exe:
        return {"error": f"Nothing called '{name}' is running"}
    subprocess.run(["taskkill", "/IM", exe], capture_output=True, creationflags=NO_WINDOW)
    return {"asked_to_close": exe}


# ---------- Routines ----------
DEFAULT_ROUTINES = {
    "night protocol": [{"do": "media", "args": {"action": "play_pause"}},
                       {"do": "close_app", "args": {"name": "MetaTrader"}},
                       {"do": "learn", "args": {}},
                       {"do": "say", "args": {"text": "Markets closed, music off. Goodnight, sir."}}],
    "focus protocol": [{"do": "close_app", "args": {"name": "Discord"}},
                       {"do": "open_app", "args": {"name": "MetaTrader 5"}},
                       {"do": "set_volume", "args": {"percent": 20}},
                       {"do": "say", "args": {"text": "Distractions closed. The markets are all yours, sir."}}],
    "house party protocol": [{"do": "set_volume", "args": {"percent": 60}},
                             {"do": "spotify_search", "args": {"query": "party anthems"}},
                             {"do": "say", "args": {"text": "House Party Protocol initiated, sir. You'll have to pick "
                                                            "the playlist; I'm a butler, not a DJ."}}],
    "trading mode": [{"do": "open_app", "args": {"name": "MetaTrader 5"}}],
    "gaming mode": [{"do": "close_app", "args": {"name": "MetaTrader"}},
                    {"do": "open_app", "args": {"name": "Medal"}},
                    {"do": "open_app", "args": {"name": "Discord"}},
                    {"do": "open_app", "args": {"name": "League of Legends"}}],
}
ROUTINE_STEPS = ("open_app", "close_app", "open_website", "media", "set_volume", "spotify_search", "add_reminder",
                 "say", "learn", "tv_power", "tv_input", "tv_app", "tv_volume", "tv_channel")


def list_routines():
    return {**DEFAULT_ROUTINES, **_load("routines.json", {})}  # his own versions win over the built-in ones


def save_routine(name, steps):
    bad = [s for s in steps if s.get("do") not in ROUTINE_STEPS]
    if bad:
        return {"error": f"Steps can only use {list(ROUTINE_STEPS)}", "bad_steps": bad}
    r = _load("routines.json", {})
    r[name.lower().strip()] = steps
    _save("routines.json", r)
    return {"saved": name, "steps": len(steps)}


def run_routine(name):
    r = list_routines()
    q = name.lower().strip()
    key = q if q in r else next((k for k in r if q in k or k.split()[0] in q), None)
    if not key:
        return {"error": f"No routine called '{name}'", "routines": list(r)}
    results = []
    for step in r[key]:
        try:
            if step["do"] == "say":  # a line for Jarvis to speak
                results.append({"say": step["args"]["text"]})
            else:
                results.append(REGISTRY[step["do"]](**step.get("args", {})))
        except Exception as e:
            results.append({"error": f"{step['do']}: {e}"})
        time.sleep(0.5)
    return {"ran": key, "results": results, "say": " ".join(r["say"] for r in results if "say" in r)}


def protocol_name(text):
    """'Jarvis, initiate night protocol' -> 'night protocol'; 'goodnight Jarvis' -> 'night protocol'. Else None."""
    t = re.sub(r"[^a-z ]", "", text.lower()).strip()
    t = re.sub(r"^(hey )?jarvis ", "", t)
    if re.fullmatch(r"(good ?night|night night)( jarvis)?", t):
        return "night protocol"
    m = re.fullmatch(r"(?:(?:initiate|activate|engage|run|start|begin) )?(?:the )?([a-z ]+? protocol)(?: jarvis)?", t)
    return m.group(1) if m and m.group(1) in list_routines() else None


# ---------- PC stats ----------
_gpu = {"t": 0.0, "v": None}


def pc_stats():
    import psutil  # pip install psutil
    out = {"cpu_percent": psutil.cpu_percent(interval=None), "ram_percent": psutil.virtual_memory().percent}
    if time.time() - _gpu["t"] > 5:  # NVIDIA cards only; asked at most every 5 s
        _gpu["t"] = time.time()
        try:
            line = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
                                   "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3,
                                  creationflags=NO_WINDOW).stdout.splitlines()[0]
            u, t, used, total = (float(x) for x in line.split(","))
            _gpu["v"] = {"gpu_percent": u, "gpu_temp_c": t, "vram_percent": round(used / total * 100)}
        except Exception:
            _gpu["v"] = None
    return {**out, **(_gpu["v"] or {})}


# ---------- Weather (Open-Meteo: free, no key) ----------
WEATHER = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
           51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
           65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow", 80: "showers", 81: "showers",
           82: "heavy showers", 95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail"}


def _get(url):
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Jarvis"}), timeout=10) as r:
        return json.loads(r.read())


def weather(place=None):
    from urllib.parse import quote
    place = place or settings()["city"] or "Sydney"
    g = _get(f"https://geocoding-api.open-meteo.com/v1/search?name={quote(place)}&count=1")
    if not g.get("results"):
        return {"error": f"Couldn't find {place}"}
    p = g["results"][0]
    w = _get(f"https://api.open-meteo.com/v1/forecast?latitude={p['latitude']}&longitude={p['longitude']}"
             "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
             "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
             "&timezone=auto&forecast_days=2")
    c, d = w["current"], w["daily"]
    day = lambda i: {"date": d["time"][i], "high_c": d["temperature_2m_max"][i], "low_c": d["temperature_2m_min"][i],
                     "rain_chance_pct": d["precipitation_probability_max"][i],
                     "sky": WEATHER.get(d["weather_code"][i], "mixed")}
    return {"place": f"{p['name']}, {p.get('country', '')}", "now_c": c["temperature_2m"],
            "feels_like_c": c["apparent_temperature"], "sky_now": WEATHER.get(c["weather_code"], "mixed"),
            "wind_kmh": c["wind_speed_10m"], "today": day(0), "tomorrow": day(1)}


# ---------- Holographic panels ----------
def _panel(ev):
    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:8765/api/panel", data=json.dumps(ev).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def show_panel(title, kind, symbol=None, timeframe="M15", bars=60, rows=None, items=None, note=""):
    """kind 'chart' (live MT5 candles), 'stats' (rows of [label, value]) or 'bars' (items of {label, value})."""
    ev = {"type": "panel", "title": title, "kind": kind, "note": note}
    if kind == "chart":
        ev.update(REGISTRY["candles"](symbol or "XAUUSD", timeframe, bars))
    elif kind == "stats":
        ev["rows"] = [[str(a), str(b)] for a, b in (rows or [])][:12]
    elif kind == "bars":
        ev["items"] = [{"label": str(i["label"]), "value": float(i["value"])} for i in (items or [])][:12]
    else:
        return {"error": "kind must be chart, stats or bars"}
    _panel(ev)
    return {"shown": title}


def hide_panels():
    _panel({"type": "clear"})
    return {"hidden": True}


# ---------- Tool list ----------
FUNCS = {f.__name__: f for f in (remember, forget, memories, add_reminder, list_reminders, cancel_reminder,
                                 clip_that, close_app, list_routines, save_routine, run_routine, pc_stats, weather,
                                 show_panel, hide_panels)}
S, I = {"type": "string"}, {"type": "integer"}
TOOLS = [
    {"name": "remember", "description": "Save a fact {USER} asks you to remember. It's shown to you in every chat.",
     "input_schema": {"type": "object", "required": ["fact"], "properties": {"fact": S}}},
    {"name": "forget", "description": "Delete remembered facts by id, or every fact containing some text.",
     "input_schema": {"type": "object", "properties": {"id": I, "text": S}}},
    {"name": "memories", "description": "Everything he's asked you to remember.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "add_reminder", "description": "Reminder or timer. Jarvis says it out loud when due. Use in_minutes for "
     "timers and 'in X', or at = 'YYYY-MM-DD HH:MM' in his local time.",
     "input_schema": {"type": "object", "required": ["text"], "properties": {
         "text": S, "at": S, "in_minutes": {"type": "number"}}}},
    {"name": "list_reminders", "description": "Upcoming reminders and timers.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "cancel_reminder", "description": "Cancel a reminder or timer by id.",
     "input_schema": {"type": "object", "required": ["id"], "properties": {"id": I}}},
    {"name": "clip_that", "description": "Save a clip of the last moments of his game with Medal.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "close_app", "description": "Close an app normally (like clicking X). Confirm with him first, unless "
     "it's part of a routine he set up.",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S}}},
    {"name": "list_routines", "description": "His routines and protocols (e.g. 'gaming mode', 'night protocol', "
     "'house party protocol') and their steps.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "save_routine", "description": "Create or replace a routine or protocol. steps: list of {do, args}, "
     f"where do is one of {list(ROUTINE_STEPS)} and args are that tool's arguments (say: {{text}}, learn: {{}}). "
     "To change one, list it first.",
     "input_schema": {"type": "object", "required": ["name", "steps"], "properties": {
         "name": S, "steps": {"type": "array", "items": {"type": "object"}}}}},
    {"name": "run_routine", "description": "Run a routine or protocol by name. Speak its 'say' text afterwards.",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S}}},
    {"name": "pc_stats", "description": "CPU, RAM and (NVIDIA) GPU load and temperature right now.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "weather", "description": "Weather now, today and tomorrow (Celsius). Defaults to his city.",
     "input_schema": {"type": "object", "properties": {"place": S}}},
    {"name": "show_panel", "description": "Float a holographic panel out of the core on his screen (and phone), like "
     "Tony's holograms. Use it whenever numbers or a chart help: 'show me gold' (kind chart: live MT5 candles; "
     "timeframe M1-D1, bars 20-200), a report's key figures (kind stats: rows [[label, value], ...]), or a "
     "comparison like P&L by hour or spending by category (kind bars: items [{label, value}], negatives show red). "
     "Panels fade after a minute; keep your spoken reply short when a panel shows the detail.",
     "input_schema": {"type": "object", "required": ["title", "kind"], "properties": {
         "title": S, "kind": {"type": "string", "enum": ["chart", "stats", "bars"]}, "symbol": S, "timeframe": S,
         "bars": I, "rows": {"type": "array", "items": {"type": "array"}},
         "items": {"type": "array", "items": {"type": "object"}}, "note": S}}},
    {"name": "hide_panels", "description": "Clear the holographic panels.",
     "input_schema": {"type": "object", "properties": {}}},
]


# ---------- Things Jarvis says without being asked ----------
def morning_pending(now=None):
    now = now or _now()
    return 5 <= now.hour < 13 and _load("state.json", {}).get("briefed") != now.strftime("%Y-%m-%d")


def morning_due(now=None):
    """True once a day, the first time Jarvis is running between 5 am and 1 pm."""
    now = now or _now()
    if not morning_pending(now):
        return False
    state, today = _load("state.json", {}), now.strftime("%Y-%m-%d")
    state["briefed"] = today
    _save("state.json", state)
    return True


MORNING_PROMPT = ("[Automatic morning brief, not typed by {USER}] Give {USER} his morning brief, as if he just sat "
                  "down: a short greeting, the weather (weather tool), today's reminders (list_reminders), high-impact "
                  "news in the next 24 hours (upcoming_news), and gold with market_snapshot if MT5 is open (skip it "
                  "quietly if not). 4-6 spoken sentences.")


def selftest():
    import shutil
    import tempfile
    global HERE
    real, HERE = HERE, Path(tempfile.mkdtemp())
    try:
        remember("Car service due at 60,000 km")
        remember("Alex's birthday is 12 March")
        assert forget(text="car service") == {"forgot": 1} and len(memories()) == 1
        assert "Alex" in memory_prompt()
        add_reminder("call Alex", at="2029-12-31 18:00")
        t = add_reminder("pizza", in_minutes=20)["set"]
        assert [r["text"] for r in list_reminders()][-1] == "call Alex"
        soon = _now() + datetime.timedelta(minutes=21)
        assert [r["text"] for r in due_reminders(soon)] == ["pizza"]  # the timer, not tomorrow's reminder
        assert [r["text"] for r in due_reminders(datetime.datetime(2030, 1, 1))] == ["call Alex"]
        assert list_reminders() == []
        assert cancel_reminder(t["id"]) == {"cancelled": 0}
        assert is_clip_command("Clip that!") and is_clip_command("Jarvis, clip it") and is_clip_command("hey jarvis clip that")
        assert not is_clip_command("clip that and open discord") and not is_clip_command("how do I clip")
        assert "gaming mode" in list_routines()
        assert "error" in save_routine("bad", [{"do": "delete_files"}])
        calls = []
        REGISTRY.update(open_app=lambda name: calls.append(name) or {"opened": name})
        save_routine("Chill", [{"do": "open_app", "args": {"name": "Spotify"}}])
        assert run_routine("chill")["ran"] == "chill" and calls == ["Spotify"]
        assert "error" in run_routine("nope")
        assert protocol_name("Jarvis, initiate house party protocol!") == "house party protocol"
        assert protocol_name("goodnight Jarvis") == "night protocol" and protocol_name("Night protocol") == "night protocol"
        assert protocol_name("what is the night protocol for") is None and protocol_name("toaster protocol") is None
        save_routine("Test", [{"do": "say", "args": {"text": "Hello."}}, {"do": "open_app", "args": {"name": "X"}}])
        assert run_routine("test")["say"] == "Hello."
        assert morning_due(datetime.datetime(2026, 11, 5, 8)) and not morning_due(datetime.datetime(2026, 11, 5, 9))
        assert not morning_due(datetime.datetime(2026, 11, 6, 22))
        assert all(t["name"] in FUNCS for t in TOOLS)
    finally:
        shutil.rmtree(HERE)
        HERE = real
    print("features self-test passed")


if __name__ == "__main__":
    selftest()
