"""What's going on around Jarvis: which app you're in, whether you're in a game, how long since you
last touched the keyboard or mouse, and the time of day. No camera: "away" means no input for a while.
"""
import datetime
import os

import features

AWAY_AFTER_S = 600     # no keyboard/mouse for 10 minutes = away
GAMES = {"league of legends.exe": "League of Legends (in a game)", "valorant-win64-shipping.exe": "Valorant",
         "7daystodie.exe": "7 Days to Die", "risk of rain 2.exe": "Risk of Rain 2", "readyornot.exe": "Ready or Not",
         "readyornot-win64-shipping.exe": "Ready or Not"}
NOTABLE = {"terminal64.exe": "MT5", "leagueclientux.exe": "League client", "discord.exe": "Discord",
           "spotify.exe": "Spotify", "medal.exe": "Medal", "obs64.exe": "OBS", "steam.exe": "Steam"}


def idle_seconds():
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000


def foreground():
    """(program name, window title, fills the whole screen?) for the window you're using."""
    import ctypes
    import ctypes.wintypes as wt
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    hwnd = u.GetForegroundWindow()
    title = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(hwnd, title, 256)
    pid = wt.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    h = k.OpenProcess(0x1000, False, pid.value)  # query limited information
    if h:
        buf, n = ctypes.create_unicode_buffer(512), wt.DWORD(512)
        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            exe = os.path.basename(buf.value).lower()
        k.CloseHandle(h)
    r = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
    mi = MONITORINFO(ctypes.sizeof(MONITORINFO))
    u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
    m = mi.rcMonitor
    full = exe not in ("explorer.exe", "") and (r.left, r.top, r.right, r.bottom) == (m.left, m.top, m.right, m.bottom)
    return exe, title.value, full


def situation():
    if os.name != "nt":
        return {}
    procs = features.running()
    exe, title, full = foreground()
    game = next((name for e, name in GAMES.items() if e in procs), None)
    if not game and full and exe not in ("chrome.exe", "msedge.exe", "firefox.exe", "pythonw.exe", "python.exe", "jarvis.exe"):
        game = title or exe  # some other fullscreen game
    return {"now": datetime.datetime.now(), "idle_s": idle_seconds(), "app": exe, "title": title[:80],
            "game": game, "open": sorted({v for e, v in NOTABLE.items() if e in procs})}


def describe(s):
    """One line about the moment, added to every message so Jarvis can read the room."""
    if not s:
        return ""
    bits = [f"using {s['title'] or s['app']}" if s.get("app") else ""]
    if s.get("game"):
        bits.append(f"playing {s['game']}: keep it very short")
    if s.get("open"):
        bits.append("open: " + ", ".join(s["open"]))
    if 1 <= s["now"].hour < 5:
        bits.append("it's the middle of the night")
    return "Right now he's " + "; ".join(b for b in bits if b) if any(bits) else ""


class Presence:
    """Turns idle time into 'away' and 'back' moments."""

    def __init__(self):
        self.away_since, self.last_gone = None, 0  # last_gone: how long the last time away lasted (seconds)

    def update(self, idle_s, now=None):
        now = now or datetime.datetime.now()
        if self.away_since is None and idle_s >= AWAY_AFTER_S:
            self.away_since = now - datetime.timedelta(seconds=idle_s)
            return "away"
        if self.away_since is not None and idle_s < 5:
            gone = (now - self.away_since).total_seconds()
            self.away_since, self.last_gone = None, gone
            return "back" if gone >= AWAY_AFTER_S else None
        return None

    @property
    def away(self):
        return self.away_since is not None


def late_night_due(s, state):
    """Once a night, between 1 and 5 am, while he's actually at the PC and not mid-game."""
    if not s or not 1 <= s["now"].hour < 5 or s["idle_s"] > 120 or s.get("game"):
        return False
    night = (s["now"] - datetime.timedelta(hours=6)).strftime("%Y-%m-%d")
    if state.get("nudged") == night:
        return False
    state["nudged"] = night
    return True


GREETINGS = {
    "any": [
        "All systems online, sir. Shall we begin?", "At your service, sir.", "Systems are up and running, sir.",
        "Good to see you, sir. Everything's ready.", "Online and fully operational, sir.",
        "Reactor core stable. All systems nominal, sir.", "Diagnostics complete. Nothing on fire, sir.",
        "I've warmed up the servers, sir. What are we building today?", "Ready when you are, sir.",
        "Back online, sir. I trust you missed me.", "All suits accounted for, sir. Figuratively speaking.",
        "Systems green across the board, sir.", "Initialising... done. Hello, sir.",
        "I've run a full sweep, sir. You're clear to proceed.", "Interface online. What's the mission, sir?",
        "Power levels optimal, sir. I'm all yours.", "Jarvis online. Shall I fetch the coffee, or just the charts?",
        "Boot sequence complete. Ready for instructions, sir.", "Hello again, sir. I kept the lights on for you.",
        "Every system checked twice, sir. We're good to go.",
    ],
    "morning": [
        "Good morning, sir. All systems online.", "Morning, sir. A fresh day and a clean slate.",
        "Good morning, sir. The markets are stirring, and so am I.", "Rise and shine, sir. Systems are ready.",
        "Good morning, sir. I trust you slept better than the servers did.",
        "Morning, sir. Coffee first, world domination after?", "Good morning, sir. Today's agenda awaits.",
    ],
    "afternoon": [
        "Good afternoon, sir. All systems online.", "Afternoon, sir. Picking up where we left off?",
        "Good afternoon, sir. The day's half done; let's make the other half count.",
        "Afternoon, sir. Everything is as you left it.", "Good afternoon, sir. Ready for round two?",
    ],
    "evening": [
        "Good evening, sir. All systems online.", "Welcome home, sir.", "Evening, sir. Long day?",
        "Good evening, sir. Shall I dim the lights and bring up the charts?",
        "Welcome back, sir. The evening's yours.", "Good evening, sir. New York session is wide awake, by the way.",
    ],
    "late": [
        "Working late, sir? I'm here for it.", "Evening, sir. Another late one, I see.",
        "Still up, sir? Then so am I.", "Night shift engaged, sir.",
    ],
    "small_hours": [
        "Online, sir. Burning the midnight oil again, I see.", "It's rather late, sir. Or very early. Either way, I'm here.",
        "Small hours, sir. The world's asleep; we're not.", "Up at this hour, sir? Something brilliant, I hope.",
        "Online, sir. Even the markets are quiet at this time.",
    ],
    "Monday": ["Monday, sir. Let's set the tone for the week."],
    "Friday": ["It's Friday, sir. Let's finish the week strong.", "Friday, sir. Nearly there."],
    "Saturday": ["Happy Saturday, sir. Work or play today?"],
    "Sunday": ["Sunday, sir. A good day to plan the week ahead.", "Happy Sunday, sir."],
}


def greeting(now=None, reminders_today=0, recent=None):
    """A fresh hello each time Jarvis opens. recent: lines said lately (they're skipped), updated in place."""
    import random
    now = now or datetime.datetime.now()
    h = now.hour
    part = ("small_hours" if 1 <= h < 5 else "morning" if h < 12 else "afternoon" if h < 17 else
            "evening" if h < 22 else "late")
    pool = GREETINGS[part] * 2 + GREETINGS.get(now.strftime("%A"), []) * 2
    if part not in ("small_hours", "late"):
        pool += GREETINGS["any"]
    recent = recent if recent is not None else []
    fresh = [g for g in pool if g not in recent] or pool
    first = random.choice(fresh)
    recent.append(first)
    del recent[:-12]
    if reminders_today:
        first += f" You have {reminders_today} reminder{'s' if reminders_today > 1 else ''} today."
    return first


def selftest():
    t = datetime.datetime(2026, 11, 5, 21, 0)
    p = Presence()
    assert p.update(30, t) is None and p.update(600, t) == "away" and p.away
    assert p.update(900, t) is None and p.update(2, t) == "back" and not p.away
    p.update(700, t)
    assert p.update(1, t + datetime.timedelta(seconds=1)) == "back"
    s = {"now": datetime.datetime(2026, 11, 5, 2, 30), "idle_s": 10, "game": None}
    state = {}
    assert late_night_due(s, state) and not late_night_due(s, state)
    assert not late_night_due(dict(s, game="League of Legends"), {})
    assert not late_night_due(dict(s, now=datetime.datetime(2026, 11, 5, 23, 0)), {})
    d = describe({"now": t, "idle_s": 1, "app": "leagueclientux.exe", "title": "League of Legends",
                  "game": "League of Legends (in a game)", "open": ["Discord", "MT5"]})
    assert "playing League of Legends" in d and "open: Discord, MT5" in d
    assert greeting(t, 2).endswith("You have 2 reminders today.")
    small = datetime.datetime(2026, 11, 5, 2, 0)
    assert greeting(small) in GREETINGS["small_hours"]
    recent, seen = [], set()
    for _ in range(5):
        seen.add(greeting(small, recent=recent))
    assert len(seen) == 5  # no repeats until the pool runs out
    print("awareness self-test passed")


if __name__ == "__main__":
    selftest()
