"""The mirror: a model of how {USER} decides, built from his own record, that plays a decision forward.

build_mirror (weekly on Mondays, or "study how I decide"): Claude Sonnet reads the last 30 days of conversations,
his MT5 report (win rate, by hour, loss reasons, streaks), his trading twin's patterns and his shifts, and writes
his decision profile: up to 8 habits, each with the evidence and what it costs or earns him, in numbers where the
record has them (mirror.json).
simulate ("what would I do about ...", "should I ... what does my mirror say"): with the profile and today's
situation (hours since his last shift, today's trades), Sonnet predicts what he'd most likely do, where that has
gone wrong before with his own numbers, and what the better-day version of him does. A panel shows it.
It's a model built from his record, so it only knows what he's told Jarvis and what his journal shows.
"""
import datetime
import json

import features

FILE = "mirror.json"


def _convo(days=30, limit=400):
    import dream
    return dream._convo(limit, days)


def _record():
    out = {}
    R = features.REGISTRY
    try:
        r = R["mt5_report"]()
        out["trading"] = {k: r.get(k) for k in ("trades", "win_rate", "net_pnl", "avg_win", "avg_loss", "worst_losing_streak",
                                                 "by_hour_opened", "by_direction", "top_loss_reasons")}
    except Exception:
        pass
    t = features._load("twin.json", None)
    if t:
        out["setups"] = {k: {x: p[x] for x in ("n", "win_rate", "net")} for k, p in t["patterns"].items()}
    try:
        import shifts
        rows = shifts._load()[-30:]
        out["shifts"] = {"count_last_30_saved": len(rows), "nights": sum(s["start"] >= "18:00" or s["start"] < "05:00" for s in rows)}
    except Exception:
        pass
    return out


def build_mirror():
    """Study how he decides and save his decision profile."""
    import council
    convo = _convo()
    rec = _record()
    if not convo and not rec.get("trading"):
        return {"error": "Not enough history yet: I need some conversations or trades to study."}
    q = features.personal(
        "Study how {USER} makes decisions, from his record below, and write his decision profile: up to 8 habits "
        "(when he's rash or careful, what tiredness, losses, wins, money and time pressure do to his choices, what he "
        "puts off, what he follows through on). Each needs evidence from the record and, where the numbers exist, what "
        "it costs or earns him in dollars or percent. Only what the record supports; no flattery, no diagnosis.\n\n"
        f"What you remember about him:\n{features.memory_prompt().strip()[:2500]}\n\nHis numbers:\n{json.dumps(rec)[:5000]}\n\n"
        f"Conversations (last 30 days):\n{convo}\n\nJSON only: "
        '{"habits": [{"habit": "...", "evidence": "...", "cost": "e.g. -$340 this month, or unknown"}], "summary": "2 sentences"}')
    out = council._json(council._claude(q, "sonnet")) or {}
    if not out.get("habits"):
        return {"error": "I couldn't build a profile from the record."}
    res = {"built": datetime.datetime.now().isoformat(timespec="minutes"), **out}
    features._save(FILE, res)
    show_mirror()
    return res


def show_mirror():
    m = features._load(FILE, None)
    if not m:
        return {"error": "I haven't studied how you decide yet: say 'study how I decide'."}
    features._panel({"type": "panel", "kind": "list", "title": "Your mirror", "stay": True,
                     "items": [{"text": h["habit"], "sub": f"{h.get('evidence', '')} · {h.get('cost', '')}"} for h in m["habits"]],
                     "note": m.get("summary", "") + f" (built {m['built'][:10]})"})
    return m


def _today():
    now = datetime.datetime.now()
    out = [f"It's {now:%A %H:%M}."]
    try:
        import dayplan
        if dayplan.ended_recently(12):
            out.append("He finished a work shift in the last 12 hours.")
        t = features.REGISTRY["mt5_trades"](since=now.date().isoformat(), limit=50)
        if t:
            out.append(f"Today he has taken {len(t)} trades, net ${sum(float(x['pnl']) for x in t):.2f}.")
    except Exception:
        pass
    return " ".join(out)


def simulate(decision):
    """Play a decision forward through his mirror: what he'd likely do, the risk from his own record, the better move."""
    import council
    m = features._load(FILE, None)
    if not m:
        b = build_mirror()
        if b.get("error"):
            return b
        m = b
    q = features.personal(
        "You are a model of how {USER} decides, built from his record. His decision profile:\n" + json.dumps(m["habits"])
        + f"\n\nRight now: {_today()}\n\nThe decision in front of him: {decision}\n\nPredict honestly. JSON only: "
        '{"likely": "what he will most likely do, one sentence", "why": "which habits drive it", "risk": "where this '
        'has gone wrong before, with his own numbers when the profile has them", "better": "what the best version of '
        'him does instead, concrete", "confidence": 0-100}')
    out = council._json(council._claude(q, "sonnet")) or {}
    if not out.get("likely"):
        return {"error": "The mirror couldn't answer that."}
    features._panel({"type": "panel", "kind": "stats", "title": "Your mirror says", "stay": True,
                     "rows": [["Decision", decision[:120]], ["You'd likely", out["likely"]], ["Because", out.get("why", "")],
                              ["The risk", out.get("risk", "")], ["Better", out.get("better", "")],
                              ["Confidence", f"{out.get('confidence', '?')}%"]]})
    return out


def weekly_due(now=None):
    now = now or datetime.datetime.now()
    m = features._load(FILE, None)
    due = bool(m) and now.weekday() == 0 and now.hour >= 5 and m["built"][:10] < (now.date() - datetime.timedelta(days=3)).isoformat()
    if due:
        features._save(FILE, {**m, "built": now.isoformat(timespec="minutes")})
    return due


FUNCS = {"build_mirror": build_mirror, "show_mirror": show_mirror, "mirror_simulate": simulate}
TOOLS = [
    {"name": "build_mirror", "description": "Study how he makes decisions from his conversations, trades and shifts, "
     "and save his decision profile ('study how I decide'). A minute or two.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "show_mirror", "description": "Show his decision profile ('show my mirror', 'what are my habits').",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "mirror_simulate", "description": "Before a big decision, run it through his mirror ('what would I do', "
     "'what does my mirror say about ...', 'should I take this trade / buy this / quit'): what he'd likely do, where "
     "that's cost him before with his own numbers, and the better move.",
     "input_schema": {"type": "object", "required": ["decision"], "properties": {"decision": {"type": "string"}}}},
]
COMMANDS = {"Mirror": ["Study how I decide", "What does my mirror say about taking this trade?"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    assert build_mirror().get("error")
    features.REGISTRY["mt5_report"] = lambda: {"trades": 40, "win_rate": 45, "net_pnl": -120, "by_hour_opened": {}}
    features.REGISTRY["mt5_trades"] = lambda since=None, limit=50: [{"pnl": "-20"}, {"pnl": "-15"}]
    import council
    asked = []
    council._claude = lambda q, model="": asked.append(q) or (
        json.dumps({"habits": [{"habit": "Re-enters fast after a loss", "evidence": "3 revenge trades", "cost": "-$90"}], "summary": "Careful when rested."})
        if "write his decision profile" in q else json.dumps({"likely": "Take it", "why": "revenge", "risk": "-$90 so far", "better": "Wait 30 min", "confidence": 70}))
    shown = []
    features._panel = shown.append
    assert build_mirror()["habits"][0]["cost"] == "-$90" and '"win_rate": 45' in asked[0]
    r = simulate("take another gold trade now")
    assert r["better"] == "Wait 30 min" and "taken 2 trades, net $-35.00" in asked[-1] and shown[-1]["rows"][1][1] == "Take it"
    assert not weekly_due(datetime.datetime.now())
    print("mirror self-test passed")
