"""His trading twin: Jarvis learns which setups HE wins with, from his own MT5 journal, and nudges him when one forms.

Learning ("learn my trading", and again each Monday): for each of his closed trades, the chart watcher (watcher.py)
looks at the 15 minutes before he entered: was there a breakout or a rejection at a key level, and did he trade
with it or against it? Grouped by pair and setup, that gives his own win rate and profit for each kind of trade
(twin.json). A pattern counts as his strength with at least 5 trades, a win rate of 55% or more and a profit; a
weakness with 5+ trades and a loss.
Nudges: every 5-minute candle close (free, no AI), the watcher checks the pairs he trades; when a setup that's one
of his strengths forms, Jarvis tells him (and his phone), with his own numbers. At most once per pair and level in
2 hours, never during quiet mode, and only on his own trades' pairs. Settings 'twin_nudges' (on by default).
"""
import datetime
import time

import features

FILE = "twin.json"
MIN_TRADES, MIN_WIN = 5, 55


def _key(symbol, kind, with_it):
    return f"{symbol}|{kind}|{'with' if with_it else 'against'}" if kind else f"{symbol}|none|-"


def describe(key):
    s, kind, w = key.split("|")
    return f"{s} with no setup" if kind == "none" else f"{s} {kind}s, trading {w} {'it' if w == 'with' else 'the setup'}"


def classify(trade, find):
    """The setup he traded into: find(at) -> the watcher's trigger at that MT5 server time (or None)."""
    opened = datetime.datetime.strptime(trade["opened"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    at = int(opened.timestamp())  # MT5 server time, stored as if UTC
    side = "buy" if trade["direction"].lower().startswith(("l", "b")) else "sell"
    for back in (0, 300, 600):  # the 5-minute candles that closed in the 15 minutes before he entered
        t = find(at - at % 300 - back)
        if t:
            return _key(trade["symbol"], t["kind"], t["side"] == side)
    return _key(trade["symbol"], None, None)


def build(trades, find):
    pats = {}
    for t in trades:
        try:
            k = classify(t, find)
        except (KeyError, ValueError):
            continue
        p = pats.setdefault(k, {"n": 0, "wins": 0, "net": 0.0})
        p["n"] += 1
        p["wins"] += float(t["pnl"]) > 0
        p["net"] = round(p["net"] + float(t["pnl"]), 2)
    for p in pats.values():
        p["win_rate"] = round(100 * p["wins"] / p["n"])
        p["strong"] = p["n"] >= MIN_TRADES and p["win_rate"] >= MIN_WIN and p["net"] > 0
        p["weak"] = p["n"] >= MIN_TRADES and p["net"] < 0
    return pats


def learn_twin(show=True):
    """Learn his setups from his MT5 journal (a minute or so: MT5 is asked about each trade)."""
    import mt5trade as m
    mt5 = m._mt5()
    why = m.ready(mt5)
    if why:
        return {"error": why}
    trades = features.REGISTRY["mt5_trades"](limit=500)
    if len(trades) < MIN_TRADES:
        return {"error": f"Only {len(trades)} trades in your journal: I need at least {MIN_TRADES} to learn from."}
    cache = {}

    def find(sym):
        s = m._symbol(mt5, sym)
        return lambda at: cache.setdefault((s, at), m.find_trigger(mt5, s, at))
    pats = {}
    for sym in sorted({t["symbol"] for t in trades}):
        part = build([t for t in trades if t["symbol"] == sym], find(sym))
        pats.update(part)
    features._save(FILE, {"built": datetime.datetime.now().isoformat(timespec="minutes"), "trades": len(trades),
                          "patterns": pats})
    return twin_report(show)


def twin_report(show=True):
    """What his twin knows: his best and worst setups, with his own numbers."""
    t = features._load(FILE, None)
    if not t:
        return {"error": "I haven't learned your trading yet: say 'learn my trading'."}
    pats = t["patterns"]
    rank = sorted(pats.items(), key=lambda kv: -kv[1]["net"])
    line = lambda k, p: {"text": f"{describe(k)}: {p['win_rate']}% won", "sub": f"{p['n']} trades, ${p['net']:,.2f}"}
    strong = [(k, p) for k, p in rank if p["strong"]]
    weak = [(k, p) for k, p in reversed(rank) if p["weak"]]
    if show:
        features._panel({"type": "panel", "kind": "list", "title": "Your trading twin", "stay": True,
                         "items": [{"text": "YOUR STRENGTHS", "sub": ""}] + [line(k, p) for k, p in strong[:5]]
                         + [{"text": "COSTING YOU", "sub": ""}] + [line(k, p) for k, p in weak[:4]],
                         "note": f"From {t['trades']} trades, learned {t['built'][:10]}. I'll nudge you when a strength forms."})
    return {"strengths": [describe(k) for k, _ in strong], "weaknesses": [describe(k) for k, _ in weak],
            "patterns": pats, "built": t["built"]}


class Nudger:
    """Every 5-minute close: his strong setups forming now -> a nudge."""

    def __init__(self):
        import watcher
        self.cool, self.next = watcher.Cooldown(2), 0

    def tick(self, say, now=None):
        now = now or time.time()
        if now < self.next:
            return None
        self.next = now - now % 300 + 305
        s = features.settings()
        t = features._load(FILE, None)
        if not t or not s.get("twin_nudges", True) or s.get("quiet") or features.focus():
            return None
        strong = {k: p for k, p in t["patterns"].items() if p["strong"] and "|none|" not in k}
        if not strong:
            return None
        import mt5trade as m
        mt5 = m._mt5()
        if m.ready(mt5):
            return None
        for sym in sorted({k.split("|")[0] for k in strong}):
            sname = m._symbol(mt5, sym)
            tick = mt5.symbol_info_tick(sname)
            if not tick or time.time() - tick.time > 600:
                continue
            trig = m.find_trigger(mt5, sname)
            p = trig and strong.get(_key(sym, trig["kind"], True))
            if p and self.cool.ok(sname, trig["level"], now, mt5.symbol_info(sname).point * 100):
                text = (f"{{TITLE}}, one of your setups: {sname} {trig['text']}. Your {trig['kind']}s like this won "
                        f"{p['win_rate']}% of {p['n']} trades, ${p['net']:,.0f} in total. Worth a look ({trig['side']}).")
                say(text)
                try:
                    import alerts
                    alerts.notify(features.address(text.replace("{TITLE}", "Sir")), "Your setup", tags="dart")
                except Exception:
                    pass
                return text
        return None


NUDGER = Nudger()


def weekly_due(now=None):
    """Relearn each Monday (new trades)."""
    now = now or datetime.datetime.now()
    t = features._load(FILE, None)
    due = bool(t) and now.weekday() == 0 and t["built"][:10] < (now.date() - datetime.timedelta(days=3)).isoformat()
    if due:
        features._save(FILE, {**t, "built": now.isoformat(timespec="minutes")})  # once, even if learning fails
    return due


FUNCS = {"learn_twin": learn_twin, "twin_report": twin_report}
TOOLS = [
    {"name": "learn_twin", "description": "Learn his own trading from his MT5 journal ('learn my trading'): which setups "
     "(breakouts, rejections at key levels, with or against them, by pair) he wins and loses with; then it nudges him "
     "when one of his strengths forms. Takes a minute.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "twin_report", "description": "His trading twin: his best and worst setups with his own numbers ('what "
     "are my best setups', 'what's costing me').", "input_schema": {"type": "object", "properties": {}}},
]
COMMANDS = {"Trading": ["Learn my trading", "What are my best setups?"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    trig = {"kind": "breakout", "side": "buy", "level": 4000, "text": "x"}
    find = lambda at: trig if at % 3600 < 1800 else None  # setups only in the first half of each hour (server time)
    trades = [{"symbol": "XAUUSD", "direction": "Long", "opened": f"2026-11-0{d} 10:{mm}:00", "pnl": pnl}
              for d, mm, pnl in [(2, "05", 30), (3, "10", 25), (4, "02", -10), (5, "20", 40), (6, "07", 15),
                                 (2, "45", -20), (3, "50", -15)]]
    trades.append({"symbol": "XAUUSD", "direction": "Short", "opened": "2026-11-09 10:05:00", "pnl": -12})
    pats = build(trades, find)
    w = pats["XAUUSD|breakout|with"]
    assert (w["n"], w["wins"], w["win_rate"], w["net"], w["strong"]) == (5, 4, 80, 100, True), w
    assert pats["XAUUSD|none|-"]["n"] == 2 and pats["XAUUSD|breakout|against"]["n"] == 1
    features._save(FILE, {"built": "2026-11-12T10:00", "trades": 8, "patterns": pats})
    shown = []
    features._panel = shown.append
    r = twin_report()
    assert r["strengths"] == ["XAUUSD breakouts, trading with it"] and shown[-1]["title"] == "Your trading twin"
    assert not weekly_due(datetime.datetime(2026, 11, 13, 9)) and weekly_due(datetime.datetime(2026, 11, 16, 9))
    assert not weekly_due(datetime.datetime(2026, 11, 16, 9, 1))  # once
    print("twin self-test passed")
