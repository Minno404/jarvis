"""Lag watch: "monitor my PC while I game". Every second, Jarvis logs what could make a game jitter or lag, then
reports the spikes and what was happening at the time.

Each second: CPU (total and the busiest core, since many games lean on one core), RAM, GPU load and temperature
(NVIDIA), disk reads and writes, the busiest app, and two pings: to the router (Wi-Fi or cable trouble) and to the
internet (1.1.1.1, his connection or the game's servers). A spike is a second over a limit; spikes within 3 s of
each other are one event. When the game closes (or "stop monitoring", or after 4 hours) he gets a panel of the
events and a spoken summary of the main cause. Nothing leaves the PC and no AI is used.
Frame times aren't measured (Windows has no free way without admin tools); in-game stutter with none of these
spiking points at the game itself or its settings.
"""
import datetime
import re
import statistics
import subprocess
import threading
import time

import features

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_S = 4 * 3600
# what counts as a spike, and how it's named in the report
LIMITS = {"cpu": (90, "CPU at {v:.0f}%"), "core": (98, "one CPU core maxed ({v:.0f}%)"), "ram": (90, "RAM at {v:.0f}%"),
          "gpu": (98, "GPU maxed ({v:.0f}%)"), "gpu_temp": (85, "GPU hot ({v:.0f}°C)"),
          "disk": (150, "disk busy ({v:.0f} MB/s)"), "router": (30, "router ping {v:.0f} ms"), "net": (None, "internet ping {v:.0f} ms")}
CAUSE = {"router": "your Wi-Fi or network cable (the ping to your own router jumped, so it's inside the house)",
         "net": "your internet connection or the game's servers (the router was fine, the internet ping jumped)",
         "cpu": "the CPU running out of headroom", "core": "one CPU core maxing out (the game or an app is limited by a single core)",
         "ram": "RAM running out, so Windows swaps to disk", "gpu": "the GPU at its limit (lower graphics settings or cap the frame rate)",
         "gpu_temp": "the GPU running hot and slowing itself down (check fans and dust)",
         "disk": "heavy disk activity (an update, download or virus scan)"}


class Watch:
    current = None

    def __init__(self, game=""):
        self.game, self.start, self.samples, self.on = game, time.time(), [], True
        self.ping = {"router": None, "net": None}
        self.gateway = gateway()
        threading.Thread(target=self._pings, daemon=True).start()
        threading.Thread(target=self._loop, daemon=True).start()

    def _pings(self):
        while self.on:
            t = time.time()
            out = {}

            def one(key, host):
                out[key] = ping(host)
            ths = [threading.Thread(target=one, args=("net", "1.1.1.1"))]
            if self.gateway:
                ths.append(threading.Thread(target=one, args=("router", self.gateway)))
            for th in ths:
                th.start()
            for th in ths:
                th.join()
            self.ping = out
            time.sleep(max(0, 1 - (time.time() - t)))

    def _loop(self):
        import psutil
        procs, last_io = {}, psutil.disk_io_counters()
        psutil.cpu_percent(percpu=True)
        while self.on and time.time() - self.start < MAX_S:
            time.sleep(1)
            cores = psutil.cpu_percent(percpu=True)
            io = psutil.disk_io_counters()
            s = {"t": time.time(), "cpu": sum(cores) / len(cores), "core": max(cores), "ram": psutil.virtual_memory().percent,
                 "disk": ((io.read_bytes + io.write_bytes) - (last_io.read_bytes + last_io.write_bytes)) / 1e6}
            last_io = io
            s.update(gpu_now())
            s.update({k: v for k, v in self.ping.items() if k in ("router", "net")})
            s["top"] = top_app(procs, psutil)
            self.samples.append(s)
        self.on = False


def gateway():
    try:
        out = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW).stdout
        return next((m for m in re.findall(r"Default Gateway[ .]*: ([\d.]+)", out) if m), None)
    except Exception:
        return None


def ping(host):
    """Round trip in ms, or -1 when lost."""
    try:
        out = subprocess.run(["ping", "-n", "1", "-w", "900", host], capture_output=True, text=True, timeout=3,
                             creationflags=NO_WINDOW).stdout
        m = re.search(r"time[=<](\d+)ms", out)
        return float(m.group(1)) if m else -1
    except Exception:
        return -1


def gpu_now():
    try:
        line = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=2, creationflags=NO_WINDOW).stdout.splitlines()[0]
        u, t = (float(x) for x in line.split(","))
        return {"gpu": u, "gpu_temp": t}
    except Exception:
        return {}


def top_app(procs, psutil):
    """The app using the most CPU this second (cpu_percent needs the same Process object each time)."""
    best, name = 0, ""
    for p in psutil.process_iter(["name"]):
        q = procs.setdefault(p.pid, p)
        try:
            c = q.cpu_percent()
        except Exception:
            procs.pop(p.pid, None)
            continue
        if c > best and p.info["name"] not in ("System Idle Process", "Idle"):
            best, name = c, p.info["name"]
    return name


def spikes(samples):
    """[(start time, end time, {kind: worst value}, {top apps})]: seconds over a limit, grouped when <= 3 s apart."""
    nets = [s["net"] for s in samples if s.get("net", -1) > 0]
    base = statistics.median(nets) if nets else 0
    net_lim = max(80, base * 3)
    events = []
    for s in samples:
        hit = {}
        for k, (lim, _) in LIMITS.items():
            v = s.get(k)
            if v is None:
                continue
            lim = net_lim if k == "net" else lim
            if v == -1 and k in ("router", "net"):
                hit[k] = -1  # lost
            elif v >= lim:
                hit[k] = v
        if not hit:
            continue
        if events and s["t"] - events[-1][1] <= 3:
            e = events[-1]
            e[1] = s["t"]
            for k, v in hit.items():
                e[2][k] = -1 if -1 in (v, e[2].get(k)) else max(v, e[2].get(k, 0))
            e[3].add(s.get("top", ""))
        else:
            events.append([s["t"], s["t"], hit, {s.get("top", "")}])
    return events, base


def _what(hit):
    return ", ".join(("lost packets to the router" if k == "router" else "lost internet packets") if v == -1
                     else LIMITS[k][1].format(v=v) for k, v in hit.items())


def report(samples, game=""):
    events, base = spikes(samples)
    mins = round(len(samples) / 60)
    count = {}
    for e in events:
        for k in e[2]:
            count[k] = count.get(k, 0) + 1
    main = max(count, key=count.get) if count else None
    avg = lambda k: statistics.mean(s[k] for s in samples if s.get(k, -1) >= 0) if any(s.get(k, -1) >= 0 for s in samples) else None
    items = [{"text": f"{len(events)} spike{'s' if len(events) != 1 else ''} in {mins} min" + (f" of {game}" if game else ""),
              "sub": f"Usual: CPU {avg('cpu') or 0:.0f}%, RAM {avg('ram') or 0:.0f}%"
              + (f", GPU {avg('gpu'):.0f}%" if avg("gpu") is not None else "") + f", internet ping {base:.0f} ms"}]
    for e in sorted(events, key=lambda e: -len(e[2]))[:10]:
        when = datetime.datetime.fromtimestamp(e[0]).strftime("%H:%M:%S")
        apps = ", ".join(a for a in e[3] if a)[:60]
        items.append({"text": f"{when} ({round(e[1] - e[0]) + 1} s): {_what(e[2])}", "sub": f"Busiest app: {apps}" if apps else ""})
    if not events:
        said = (f"No spikes in {mins} minutes, {{TITLE}}: CPU, RAM, GPU, disk and your connection all stayed steady. "
                "If it still jittered, it's the game itself or its settings: try capping the frame rate or turning off V-Sync.")
    else:
        apps = [a for e in events for a in e[3] if a and e[2].keys() & {"cpu", "core", "disk", "ram"}]
        app = max(set(apps), key=apps.count) if apps else ""
        said = (f"{len(events)} spikes in {mins} minutes, {{TITLE}}. Most of them were {CAUSE[main]}."
                + (f" The busiest app during them was {app}." if app else "") + " The panel has each one.")
    return {"events": len(events), "minutes": mins, "main_cause": CAUSE.get(main, "none"), "panel_items": items, "say": said}


def lag_watch(on=True, game=""):
    """Start or stop the lag monitor. Stopping gives the report."""
    w = Watch.current
    if on:
        if w and w.on:
            return {"note": "Already monitoring.", "since": datetime.datetime.fromtimestamp(w.start).strftime("%H:%M")}
        if features.os.name != "nt":
            return {"error": "Lag watch runs on the Windows PC."}
        Watch.current = Watch(game)
        return {"started": True, "note": "Logging every second until the game closes or he says stop; then the report."}
    if not w:
        return {"error": "Not monitoring."}
    w.on = False
    Watch.current = None
    return finish(w)


def finish(w, say=None):
    if len(w.samples) < 10:
        return {"error": "Under 10 seconds logged: nothing to report."}
    r = report(w.samples, w.game)
    features._save("lagwatch.json", {"when": datetime.datetime.now().isoformat(timespec="minutes"),
                                     **{k: v for k, v in r.items() if k != "say"}})
    try:
        features._panel({"type": "panel", "kind": "list", "title": "Lag watch", "stay": True, "items": r["panel_items"][:12],
                         "note": f"Main cause: {r['main_cause']}"})
    except Exception:
        pass
    if say:
        say(r["say"])
    return {k: v for k, v in r.items() if k != "panel_items"}


def tick(game, say):
    """From the watcher every 10 s: once the game he was monitoring closes for a minute, report."""
    w = Watch.current
    if not w:
        return
    if game and w.on:
        w.game, w.gone = w.game or game, None
        return
    w.gone = getattr(w, "gone", None) or time.time()
    if not w.on or (w.game and time.time() - w.gone > 60):
        w.on = False
        Watch.current = None
        finish(w, say)


def last_lag_report():
    d = features._load("lagwatch.json", None)
    if not d:
        return {"error": "No lag report yet."}
    features._panel({"type": "panel", "kind": "list", "title": "Lag watch", "stay": True, "items": d["panel_items"][:12],
                     "note": f"Main cause: {d['main_cause']}"})
    return {k: v for k, v in d.items() if k != "panel_items"}


FUNCS = {"lag_watch": lag_watch, "last_lag_report": last_lag_report}
TOOLS = [
    {"name": "lag_watch", "description": "Monitor his PC for lag and jitter while he games ('monitor my PC while I game', "
     "'watch for lag'): logs CPU, cores, RAM, GPU, disk, the busiest app and router and internet ping every second, and "
     "when the game closes reports the spikes and what caused them. on=false stops it now and gives the report. "
     "game: the game's name if he said it. No AI is used while it runs.",
     "input_schema": {"type": "object", "properties": {"on": {"type": "boolean"}, "game": {"type": "string"}}}},
    {"name": "last_lag_report", "description": "Show the last lag watch report again.",
     "input_schema": {"type": "object", "properties": {}}},
]
COMMANDS = {"PC": ["Monitor my PC while I game", "Stop monitoring"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    t0 = 1_000_000.0
    base = {"cpu": 40, "core": 70, "ram": 50, "gpu": 80, "gpu_temp": 65, "disk": 2, "router": 2, "net": 20, "top": "game.exe"}
    smp = [{**base, "t": t0 + i} for i in range(300)]
    smp[100].update(router=-1, net=-1)          # Wi-Fi drop
    smp[101].update(router=45, net=180)         # same event (1 s later)
    smp[200].update(net=150)                    # internet only
    smp[250].update(core=100, top="MsMpEng.exe")  # one core maxed by a virus scan
    ev, b = spikes(smp)
    assert b == 20 and len(ev) == 3 and ev[0][2] == {"router": -1, "net": -1}, ev
    r = report(smp, "Rust")
    assert r["events"] == 3 and r["minutes"] == 5 and "MsMpEng.exe" in r["say"], r
    assert r["main_cause"].startswith("your internet")
    quiet = report([{**base, "t": t0 + i} for i in range(120)])
    assert quiet["events"] == 0 and "No spikes" in quiet["say"]
    shown, said = [], []
    features._panel = shown.append

    class W:
        samples, game, on, start = smp, "Rust", True, t0
    Watch.current = W()
    tick("Rust", said.append)
    assert Watch.current and not said
    tick(None, said.append)
    assert Watch.current and not said  # gone under a minute: keep going
    Watch.current.gone = time.time() - 61
    tick(None, said.append)
    assert not Watch.current and "3 spikes in 5 minutes" in said[0] and shown[-1]["title"] == "Lag watch"
    assert last_lag_report()["events"] == 3
    print("lagwatch self-test passed")
