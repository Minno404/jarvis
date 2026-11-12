"""The life map (holo mode): what's going on in his life, as things orbiting Jarvis's core.

nodes() gathers one line from each part of Jarvis that has something to show: his next shift, this week's pay,
today's trading, the autopilot, each project agent, ventures, a running experiment, the team, the time capsule,
last night's ideas, reminders. Each has the command that opens it; the HUD (holo mode) draws them in orbit and a
tap, a pinch or saying its name opens it. Parts with nothing to show are left out. No AI.
"""
import datetime

import features


def nodes():
    out = []

    def add(kind, label, value, say, hot=False):
        out.append({"kind": kind, "label": label, "value": str(value)[:40], "say": say, "hot": bool(hot)})
    R = features.REGISTRY
    today = datetime.date.today().isoformat()
    for fn in (_shifts, _trading, _work, _self):
        try:
            fn(add, R, today)
        except Exception as e:
            print("life map:", fn.__name__, repr(e)[:100])
    return out


def _shifts(add, R, today):
    import shifts
    m = shifts.my_shifts(show=False)
    if m["next"]:
        d, st = m["next"].split(" ")[0], m["next"].split(" ")[1]
        day = "today" if d == today else datetime.date.fromisoformat(d).strftime("%a")
        add("shift", "Next shift", f"{day} {st}", "bring up my work shifts", d == today)
    p = shifts.pay_estimate()
    if p.get("gross"):
        add("pay", "This week's pay", f"${p['gross']:,.0f}", "how much will I get paid this week")


def _trading(add, R, today):
    t = R["mt5_trades"](since=today, limit=200) if "mt5_trades" in R else []
    if t:
        net = sum(float(x["pnl"]) for x in t)
        add("trades", "Today's trades", f"{len(t)} · {'+' if net >= 0 else '-'}${abs(net):,.0f}", "show my journal for today", net < 0)
    import mt5trade
    if mt5trade.AUTO.on:
        st = mt5trade._load(mt5trade.AUTO_STATE, {})
        add("autopilot", "Autopilot", f"on · {st.get('trades', 0)} trades", "show my autopilot trades", True)
    tw = features._load("twin.json", None)
    if tw:
        add("twin", "Your setups", f"{sum(p['strong'] for p in tw['patterns'].values())} strengths", "what are my best setups")


def _work(add, R, today):
    for a in features._load("agents.json", {"agents": {}})["agents"].values():
        add("agent", a["name"], "working" if a.get("doing") else "idle", "what are my agents up to", a.get("doing"))
    for v in features._load("ventures.json", {}).get("ventures", {}).values():
        if v["status"] not in ("stopped", "plan done"):
            add("venture", v["name"][:22], v["status"][:24], "venture status", v["status"] == "waiting for you")
    co = features._load("company.json", {})
    live = [c for c in co.values() if c["status"] in ("planning", "working")]
    if live:
        add("team", "The team", f"task {live[-1]['task'] + 1} of {len(live[-1]['tasks']) or '?'}", "how's the team going", True)
    ns = features._load("nightshift.json", {})
    if ns:
        add("night", "Night shift", f"{len(ns)} to review", "keep tonight's work")


def _self(add, R, today):
    ex = [e for e in features._load("experiments.json", {}).get("experiments", []) if e["status"] == "running"]
    if ex:
        add("experiment", "Experiment", ex[-1]["question"][:30], "how's the experiment going")
    cap = [c for c in features._load("capsule.json", []) if not c["opened"]]
    if cap:
        add("capsule", "Time capsule", f"{len(cap)} waiting · next {min(c['due'] for c in cap)[5:]}", "show my time capsule")
    dr = features._load("dream.json", None)
    if dr and dr["made"][:10] == today:
        add("dream", "Overnight ideas", f"{len(dr['ideas'])} ideas", "what did you dream up", True)
    if (features._load("evolve.json", {}) or {}).get("proposal"):
        add("evolve", "Improvements", "waiting for you", "show your improvements", True)
    lp = features._load("live_panels.json", {})
    for p in list(lp.values())[:3]:
        add("panel", p["title"], "live panel", f"show the {p['title']} panel")


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    import shifts
    d1 = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    shifts.save_shifts([{"date": d1, "start": "09:00", "end": "17:00"}])
    features._save("capsule.json", [{"opened": False, "due": "2027-01-01"}])
    features._save("agents.json", {"agents": {"g": {"name": "Gun Bros Jarvis", "doing": "reload"}}})
    features.REGISTRY["mt5_trades"] = lambda since=None, limit=200: [{"pnl": "-12.5"}]
    n = {x["kind"]: x for x in nodes()}
    assert n["shift"]["value"].endswith("09:00") and n["trades"]["value"] == "1 · -$12" and n["trades"]["hot"]
    assert n["agent"]["value"] == "working" and n["capsule"]["value"] == "1 waiting · next 01-01" and "pay" not in n
    print("lifemap self-test passed")
