"""Sleep and quiet wake.

sleep_pc:    "Jarvis, sleep the PC". Closes the apps that stop real sleep (SteelSeries GG / Sonar by default: its
             virtual audio driver keeps the PC in a fake sleep, fans on), then sleeps. They reopen when it wakes.
Quiet wake:  when his phone wakes the PC (Wake-on-LAN), Windows wakes it with the screens off and the lock screen
             up. Jarvis keeps running behind the lock screen, so the phone can use him straight away. While nobody
             is at the PC he keeps it awake for the phone, doesn't talk out loud on the PC, and puts it back to
             sleep 10 minutes after the phone goes quiet. Touching the keyboard or mouse ends all that.
"""
import datetime
import os
import subprocess
import time

import features

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SLEEP_BLOCKERS = ["steelseriesgg", "steelseriesggclient", "steelseriesengine", "steelseriessonar"]
RESLEEP_AFTER = 600  # seconds of no phone use before the PC goes back to sleep
S = {"type": "string"}


def _blockers():
    return [b.lower().removesuffix(".exe") for b in (features.settings().get("sleep_close") or SLEEP_BLOCKERS)]


def sleep_pc(reopen=True):
    """Put the PC to real sleep, closing the apps that block it first (reopened when it wakes)."""
    if os.name != "nt":
        return {"error": "Only on Windows."}
    import psutil
    want, paths = _blockers(), {}
    for p in psutil.process_iter(["name", "exe"]):
        n = (p.info["name"] or "").lower().removesuffix(".exe")
        if any(n.startswith(w) for w in want):
            if p.info["exe"] and n not in paths:
                paths[n] = p.info["exe"]
            try:
                p.kill()
            except psutil.Error:
                pass
    main = [path for n, path in paths.items() if n in ("steelseriesgg",)] or list(paths.values())[:1]
    state = features._load("state.json", {})
    state["reopen_after_wake"] = main if reopen else []
    features._save("state.json", state)
    time.sleep(1.5)
    # SetSuspendState(hibernate=False, force=True, disable wake events=False): sleep, and let the phone wake it
    subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], creationflags=NO_WINDOW)
    return {"sleeping": True, "closed_first": list(paths)}


def set_sleep_blockers(apps):
    """Which apps to close before sleeping (names like 'steelseriesgg' or 'discord'); an empty list closes none."""
    s = features.settings()
    features._save("settings.json", {**s, "sleep_close": [a.lower().strip().removesuffix(".exe") for a in apps]})
    return {"closing_before_sleep": _blockers()}


class Waker:
    """In Jarvis's watcher: notices waking up, reopens what sleep_pc closed, and runs the quiet phone wake."""

    def __init__(self):
        self.last_tick, self.woke_at, self.phone_at, self.awake_req = time.time(), None, 0.0, False

    def phone_used(self):
        self.phone_at = time.time()

    def quiet(self, idle_s, now=None):
        """True while the PC is awake only for the phone (nobody's touched it since it woke)."""
        return self.woke_at is not None and idle_s >= (now or time.time()) - self.woke_at - 5

    def _keep_awake(self, on):
        if on != self.awake_req and os.name == "nt":
            import ctypes
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED: don't fall back asleep while the phone is using Jarvis
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x1 if on else 0))
            self.awake_req = on

    def tick(self, idle_s, now=None):
        """Every few seconds. Returns 'woke' on waking, 'sleep' when it's time to go back to sleep, else None."""
        now = now or time.time()
        gap, self.last_tick = now - self.last_tick, now
        if gap > 90:  # the clock jumped: the PC was asleep
            self.woke_at = now
            state = features._load("state.json", {})
            for path in state.pop("reopen_after_wake", []) or []:
                try:
                    os.startfile(path)
                except OSError as e:
                    print(datetime.datetime.now(), "couldn't reopen", path, repr(e))
            features._save("state.json", state)
            return "woke"
        if self.woke_at is None:
            return None
        if not self.quiet(idle_s, now):  # he's at the PC now: back to normal
            self.woke_at = None
            self._keep_awake(False)
            return None
        last = max(self.woke_at, self.phone_at)
        using = now - self.phone_at < RESLEEP_AFTER
        self._keep_awake(using)
        if now - last > RESLEEP_AFTER and features.settings().get("phone_resleep", True):
            self.woke_at = None
            self._keep_awake(False)
            return "sleep"
        return None


FUNCS = {"sleep_pc": sleep_pc, "set_sleep_blockers": set_sleep_blockers}
TOOLS = [
    {"name": "sleep_pc", "description": "Put his PC to sleep ('sleep the PC', 'go to sleep', 'goodnight'). Closes the "
     "apps that stop real sleep first (SteelSeries GG by default) and reopens them when it wakes; his phone can "
     "wake it again. Say goodnight briefly first: it sleeps a couple of seconds later.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "set_sleep_blockers", "description": "Change which apps get closed before the PC sleeps (they stop real "
     "sleep), e.g. ['steelseriesgg']. Empty list = close none.",
     "input_schema": {"type": "object", "required": ["apps"], "properties": {"apps": {"type": "array", "items": S}}}},
]


def selftest():
    import tempfile
    from pathlib import Path
    real = features.HERE
    features.HERE = Path(tempfile.mkdtemp())
    try:
        w, t = Waker(), 1000.0
        w.last_tick = t
        assert w.tick(5, t + 10) is None and w.woke_at is None  # normal
        features._save("state.json", {"reopen_after_wake": []})
        t += 3600
        assert w.tick(3600, t) == "woke" and w.quiet(3600, t)  # woken by the phone: nobody at the PC
        w.phone_used()
        w.phone_at = t + 60
        step = lambda idle, now: (setattr(w, "last_tick", now - 10), w.tick(idle, now))[1]  # watcher ticks
        assert step(120, t + 120) is None and w.woke_at  # phone in use: stays awake
        assert step(60 + RESLEEP_AFTER + 61, t + 60 + RESLEEP_AFTER + 61) == "sleep"  # phone quiet 10 min
        t2 = t + 5000
        assert w.tick(5000, t2) == "woke"
        assert step(2, t2 + 30) is None and w.woke_at is None  # he touched the keyboard: back to normal
        assert set_sleep_blockers(["Discord.exe"])["closing_before_sleep"] == ["discord"]
    finally:
        features.HERE = real
    print("power self-test passed")


if __name__ == "__main__":
    selftest()
