"""Where I left off: Jarvis notes what you had open (every 10 minutes while you're at the PC, when you step away,
and before the PC sleeps). When you come back after a few hours, or start the PC the next day, he shows it and
offers to reopen it all ("reopen them"). Apps like VS Code and most browsers bring back their own windows and tabs
when reopened.
"""
import os
import time

import features

SKIP = {"jarvis", "python", "pythonw", "explorer", "textinputhost", "applicationframehost", "shellexperiencehost",
        "searchhost", "startmenuexperiencehost", "systemsettings", "lockapp", "searchapp", "msedgewebview2",
        "steelseriesgg", "steelseriesggclient", "nvidia overlay", "gamebar", "widgets", "phoneexperiencehost",
        "rtkuwp", "taskmgr"}
NICE = {"code": "VS Code", "chrome": "Chrome", "msedge": "Edge", "opera": "Opera", "firefox": "Firefox",
        "discord": "Discord", "spotify": "Spotify", "terminal64": "MetaTrader 5", "devenv": "Visual Studio",
        "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint", "windowsterminal": "Terminal",
        "steamwebhelper": "Steam", "steam": "Steam", "notepad": "Notepad", "obs64": "OBS"}
S = {"type": "string"}


def windows():
    """The real app windows open now: [{app, exe, title}] (no tool windows, hidden ones or Jarvis himself)."""
    if os.name != "nt":
        return []
    import ctypes
    import ctypes.wintypes as wt
    u, k, dwm = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.dwmapi
    out, seen = [], set()

    def each(hwnd, _):
        if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, 4) or u.GetWindowLongW(hwnd, -20) & 0x80:
            return True  # hidden, owned by another window, or a tool window
        cloaked = ctypes.c_int(0)
        dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        n = u.GetWindowTextLengthW(hwnd)
        if cloaked.value or not n:
            return True
        title = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, title, n + 1)
        pid = wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        h = k.OpenProcess(0x1000, False, pid.value)
        if h:
            buf, size = ctypes.create_unicode_buffer(512), wt.DWORD(512)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                exe = buf.value
            k.CloseHandle(h)
        name = os.path.splitext(os.path.basename(exe))[0].lower()
        if exe and name not in SKIP and title.value.strip() and title.value != "JARVIS" and (exe, title.value) not in seen:
            seen.add((exe, title.value))
            out.append({"app": NICE.get(name, name.title()), "exe": exe, "title": title.value.strip()[:120]})
        return len(out) < 15
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(each)
    u.EnumWindows(proc, 0)
    return out


def snapshot(open_windows=None):
    """Note what's open now (skipped when nothing is: e.g. a locked screen)."""
    w = windows() if open_windows is None else open_windows
    if not w:
        return {"saved": False}
    jobs = features._load("dev_jobs.json", [])
    jobs = jobs if isinstance(jobs, list) else list(jobs.values()) if isinstance(jobs, dict) else []
    job = jobs[-1] if jobs else None
    state = features._load("state.json", {})
    state["left_off"] = {"at": time.time(), "windows": w,
                         "job": {"request": str(job.get("request", ""))[:200], "status": job.get("status")} if job else None}
    features._save("state.json", state)
    return {"saved": True, "windows": len(w)}


_last = {"t": 0.0}


def tick(idle_s):
    """From the watcher: every 10 minutes while he's at the PC."""
    if idle_s < 120 and time.time() - _last["t"] > 600:
        _last["t"] = time.time()
        snapshot()


def _ago(h):
    return "earlier today" if h < 12 else "yesterday" if h < 36 else f"{int(h // 24)} days ago"


def _say(x):
    """'save.py - Gun Bros - Visual Studio Code' in VS Code -> 'save.py - Gun Bros in VS Code'."""
    head, _, tail = x["title"].rpartition(" - ")
    if head and (tail in ("Visual Studio Code", "Google Chrome", "Mozilla Firefox", "Microsoft Edge", "Microsoft\u200b Edge")
                 or any(wd in tail.lower() for wd in x["app"].lower().split())):
        return f"{head[:50]} in {x['app']}"
    return x["title"][:60] if x["app"].lower() in x["title"].lower() else f"{x['title'][:50]} in {x['app']}"


def where_i_left_off():
    """What he had open last time (and how long ago), with a ready-made line to say."""
    lo = features._load("state.json", {}).get("left_off")
    if not lo or not lo.get("windows"):
        return {"found": False, "note": "Nothing noted yet: I start noting what's open while you use the PC."}
    age_h = (time.time() - lo["at"]) / 3600
    w = lo["windows"]
    first = [_say(x) for x in w[:3]]
    line = f"{_ago(age_h).capitalize()} you had " + (", ".join(first[:-1]) + " and " + first[-1] if len(first) > 1
                                                       else first[0]) + " open."
    if lo.get("job") and lo["job"].get("status") not in ("done", "failed", None):
        line += f" A coding job was still going: {lo['job']['request'][:80]}."
    return {"found": True, "age_hours": round(age_h, 1), "windows": w, "job": lo.get("job"), "line": line}


def reopen_left_off():
    """Reopen the apps he had open last time (the ones not already running)."""
    r = where_i_left_off()
    if not r["found"]:
        return r
    running = features.running() if os.name == "nt" else set()
    done = []
    for exe in dict.fromkeys(x["exe"] for x in r["windows"]):
        if os.path.basename(exe).lower() in running:
            continue
        try:
            os.startfile(exe)
            done.append(os.path.splitext(os.path.basename(exe))[0])
        except OSError:
            pass
    return {"reopened": done, "already_open": len(r["windows"]) and not done}


FUNCS = {"where_i_left_off": where_i_left_off, "reopen_left_off": reopen_left_off}
TOOLS = [
    {"name": "where_i_left_off", "description": "What he had open on the PC last time (apps and window titles, how "
     "long ago, any unfinished coding job). For 'where was I', 'what was I doing', 'where did I leave off'.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "reopen_left_off", "description": "Reopen the apps he had open last time ('reopen them', 'bring it all "
     "back'). Apps like VS Code and browsers restore their own windows and tabs.",
     "input_schema": {"type": "object", "properties": {}}},
]


def selftest():
    import tempfile
    from pathlib import Path
    real = features.HERE
    features.HERE = Path(tempfile.mkdtemp())
    try:
        assert not where_i_left_off()["found"] and snapshot([])["saved"] is False
        snapshot([{"app": "VS Code", "exe": r"C:\Code\Code.exe", "title": "save.py - Gun Bros - Visual Studio Code"},
                  {"app": "Chrome", "exe": r"C:\Chrome\chrome.exe", "title": "Godot docs - Google Chrome"}])
        st = features._load("state.json", {})
        st["left_off"]["at"] -= 20 * 3600
        features._save("state.json", st)
        r = where_i_left_off()
        assert r["found"] and r["age_hours"] == 20.0, r
        assert r["line"] == "Yesterday you had save.py - Gun Bros in VS Code and Godot docs in Chrome open.", r["line"]
    finally:
        features.HERE = real
    print("leftoff self-test passed")


if __name__ == "__main__":
    selftest()
