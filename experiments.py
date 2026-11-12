"""Experiments on his life: one question, two weeks of data, an honest answer.

start_experiment("do I trade better after 7 hours of sleep?", factor="sleep_hours", outcome="trading_pnl", days=14,
factor_ask="How many hours did you sleep?"). Each day Jarvis gathers the two numbers:
- Automatic ones: trading_pnl, trades, win_rate (his own MT5 trades that day), worked (a shift that day),
  night_shift (a shift starting 6 pm to 5 am the day before), shift_hours.
- Anything else is asked once a day (factors from 9 am, outcomes from 8 pm) and logged when he answers
  ("I slept 6 hours" -> log_day).
At the end (or "how's the experiment going"), the days are split in two by the factor (yes/no, or above/below the
middle value) and the outcome's average compared, with the number of days on each side. Under 5 days a side, the
report says the result can't be trusted yet. No AI in the numbers.
"""
import datetime
import statistics

import features

FILE = "experiments.json"
AUTO = {"trading_pnl", "trades", "win_rate", "worked", "night_shift", "shift_hours"}


def _state():
    return features._load(FILE, {"log": {}, "experiments": [], "asked": {}})


def _auto(key, day):
    if key in ("trading_pnl", "trades", "win_rate"):
        try:
            t = features.REGISTRY["mt5_trades"](since=day, until=day, limit=500)
        except Exception:
            return None
        if not t:
            return None
        pnl = [float(x["pnl"]) for x in t]
        return round(sum(pnl), 2) if key == "trading_pnl" else len(pnl) if key == "trades" else round(100 * sum(p > 0 for p in pnl) / len(pnl))
    import shifts
    rows = shifts._load()
    if key == "worked":
        return int(any(s["date"] == day for s in rows))
    if key == "shift_hours":
        return sum(shifts._hours(s) for s in rows if s["date"] == day)
    prev = (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()
    return int(any(s["date"] == prev and (s["start"] >= "18:00" or s["start"] < "05:00") for s in rows))


def _value(st, key, day):
    return _auto(key, day) if key in AUTO else st["log"].get(day, {}).get(key)


def log_day(key, value, date=None):
    """Record one number for a day (today unless date YYYY-MM-DD): 'I slept 6 hours' -> key sleep_hours, value 6."""
    st = _state()
    day = date or datetime.date.today().isoformat()
    try:
        st["log"].setdefault(day, {})[str(key)] = float(value)
    except (TypeError, ValueError):
        return {"error": "value must be a number (use 1/0 for yes/no)"}
    features._save(FILE, st)
    return {"logged": {day: {key: float(value)}}}


def start_experiment(question, factor, outcome, days=14, factor_ask="", outcome_ask=""):
    """Start an experiment: does `factor` change `outcome`? Asked values need their question (factor_ask/outcome_ask)."""
    for k, ask in ((factor, factor_ask), (outcome, outcome_ask)):
        if k not in AUTO and not ask:
            return {"error": f"'{k}' isn't something I can measure myself: give the question to ask him each day."}
    st = _state()
    e = {"id": len(st["experiments"]) + 1, "question": question, "factor": factor, "outcome": outcome,
         "factor_ask": factor_ask, "outcome_ask": outcome_ask, "days": max(5, min(int(days), 60)),
         "start": datetime.date.today().isoformat(), "status": "running"}
    st["experiments"].append(e)
    features._save(FILE, st)
    return {"started": e, "note": f"Running for {e['days']} days; I'll report at the end."}


def report(id=None, show=True):
    """Where an experiment stands: the outcome's average on each side of the factor."""
    st = _state()
    e = next((x for x in reversed(st["experiments"]) if id in (None, x["id"])), None)
    if not e:
        return {"error": "No experiment yet."}
    start = datetime.date.fromisoformat(e["start"])
    end = min(datetime.date.today(), start + datetime.timedelta(days=e["days"] - 1))
    rows = []
    d = start
    while d <= end:
        f, o = _value(st, e["factor"], d.isoformat()), _value(st, e["outcome"], d.isoformat())
        if f is not None and o is not None:
            rows.append((f, o))
        d += datetime.timedelta(days=1)
    res = {"question": e["question"], "days_with_data": len(rows), "status": e["status"]}
    if len(rows) >= 2 and len({f for f, _ in rows}) > 1:
        fs = [f for f, _ in rows]
        cut = 0.5 if set(fs) <= {0, 1} else statistics.median(fs)
        hi, lo = [o for f, o in rows if f > cut], [o for f, o in rows if f <= cut]
        if hi and lo:
            label = (f"{e['factor']} yes", f"{e['factor']} no") if cut == 0.5 else (f"{e['factor']} above {cut:g}", f"{e['factor']} {cut:g} or less")
            res.update(high={"label": label[0], "days": len(hi), "avg": round(statistics.mean(hi), 2)},
                       low={"label": label[1], "days": len(lo), "avg": round(statistics.mean(lo), 2)})
            diff = res["high"]["avg"] - res["low"]["avg"]
            res["verdict"] = (f"{e['outcome']} averaged {res['high']['avg']:g} on {label[0]} days and {res['low']['avg']:g} on "
                              f"{label[1]} days, a difference of {diff:+.2f}. "
                              + ("Too few days on one side to trust it yet." if min(len(hi), len(lo)) < 5 else
                                 "That's a pattern in these days, not proof of cause."))
    res.setdefault("verdict", "Not enough days with both numbers yet.")
    if show:
        features._panel({"type": "panel", "kind": "stats", "title": f"Experiment {e['id']}", "stay": True,
                         "rows": [["Question", e["question"]], ["Days with data", f"{len(rows)} of {e['days']}"]]
                         + [[res[k]["label"], f"{res[k]['avg']:g} avg over {res[k]['days']} days"] for k in ("high", "low") if k in res]
                         + [["Verdict", res["verdict"]]]})
    return res


def tick(say, now=None):
    """Once a day per asked value: ask him; and close experiments that have run their days."""
    now = now or datetime.datetime.now()
    st = _state()
    day, changed = now.date().isoformat(), False
    for e in st["experiments"]:
        if e["status"] != "running":
            continue
        if (now.date() - datetime.date.fromisoformat(e["start"])).days >= e["days"]:
            e["status"], changed = "done", True
            features._save(FILE, st)
            r = report(e["id"])
            say(f"Your experiment is finished, {{TITLE}}: {e['question']} {r['verdict']}")
            continue
        for key, ask, hour in ((e["factor"], e["factor_ask"], 9), (e["outcome"], e["outcome_ask"], 20)):
            tag = f"{day}:{key}"
            if ask and now.hour >= hour and tag not in st["asked"] and key not in st["log"].get(day, {}):
                st["asked"] = {**{k: v for k, v in st["asked"].items() if k[:10] >= day}, tag: 1}
                changed = True
                say(f"For your experiment, {{TITLE}}: {ask}")
    if changed:
        features._save(FILE, st)


FUNCS = {"start_experiment": start_experiment, "log_day": log_day, "experiment_report": report}
S, N = {"type": "string"}, {"type": "number"}
TOOLS = [
    {"name": "start_experiment", "description": "Run an experiment on his life ('do I trade better after 7 hours of "
     "sleep?', 'does working nights hurt my trading?'). factor and outcome are short keys. Measured automatically: "
     "trading_pnl, trades, win_rate, worked, night_shift (worked last night), shift_hours. Any other key (sleep_hours, "
     "mood, coffee) needs factor_ask / outcome_ask: the question to ask him each day, answered with a number.",
     "input_schema": {"type": "object", "required": ["question", "factor", "outcome"], "properties": {
         "question": S, "factor": S, "outcome": S, "days": {"type": "integer"}, "factor_ask": S, "outcome_ask": S}}},
    {"name": "log_day", "description": "Record a daily number for his experiments when he tells you one ('I slept 6 "
     "hours' -> sleep_hours 6; yes/no as 1/0). date only if not today.",
     "input_schema": {"type": "object", "required": ["key", "value"], "properties": {"key": S, "value": N, "date": S}}},
    {"name": "experiment_report", "description": "How an experiment is going or how it ended.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}}},
]
COMMANDS = {"Experiments": ["Test whether I trade better after 7 hours of sleep", "How's the experiment going?"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    today = datetime.date.today()
    day = lambda n: (today - datetime.timedelta(days=n)).isoformat()
    pnl = {day(i): v for i, v in enumerate([50, -30, 40, -20, 60, -40, 45, -25, 55, -35])}
    features.REGISTRY["mt5_trades"] = lambda since=None, until=None, limit=500: [{"pnl": str(pnl[since])}] if since in pnl else []
    assert start_experiment("sleep?", "sleep_hours", "trading_pnl").get("error")
    e = start_experiment("Do I trade better after 7 hours of sleep?", "sleep_hours", "trading_pnl", 14, "How many hours did you sleep?")["started"]
    st = _state()
    st["experiments"][0]["start"] = day(9)
    features._save(FILE, st)
    for i in range(10):
        log_day("sleep_hours", 8 if i % 2 == 0 else 5, day(i))
    shown, said = [], []
    features._panel = shown.append
    r = report()
    assert r["high"] == {"label": "sleep_hours above 6.5", "days": 5, "avg": 50} and r["low"]["avg"] == -30, r
    assert "difference of +80.00" in r["verdict"] and "not proof" in r["verdict"]
    st = _state()
    st["log"].pop(day(0))
    features._save(FILE, st)
    tick(said.append, datetime.datetime.combine(today, datetime.time(9, 5)))
    tick(said.append, datetime.datetime.combine(today, datetime.time(9, 6)))
    assert said == ["For your experiment, {TITLE}: How many hours did you sleep?"]
    tick(said.append, datetime.datetime.combine(today + datetime.timedelta(days=6), datetime.time(9)))
    assert "finished" in said[-1] and _state()["experiments"][0]["status"] == "done"
    print("experiments self-test passed")
