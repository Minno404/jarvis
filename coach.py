"""Trading coach: trade replays, a pre-trade checklist and a tilt detector, all from his own MT5 history.

Times are MT5 server time throughout (as stored in mt5_positions.csv), so they compare directly.
"""
import datetime
import statistics

import features
import trading

R = features.REGISTRY
_panel = lambda ev: features._panel(ev)  # sends a panel to the HUD
TIMEFRAMES = [(15, "M1"), (120, "M5"), (480, "M15"), (2880, "H1")]  # trade length in minutes -> chart timeframe


def _t(s):
    return datetime.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- Trade replay ----------
def _pick(trades, which, position):
    if position:
        return next((t for t in trades if str(t["position"]) == str(position)), None)
    pool = {"last": trades, "last_loss": [t for t in trades if t["pnl"] < 0],
            "last_win": [t for t in trades if t["pnl"] > 0]}.get(which)
    if pool is not None:
        return pool[-1] if pool else None
    if which in ("biggest_loss", "biggest_win"):
        return (min if which == "biggest_loss" else max)(trades, key=lambda t: t["pnl"]) if trades else None
    return None


def excursions(trade, candles):
    """How far price went for (MFE) and against (MAE) him while the trade was open, in price units."""
    o, c = trade["opened"][:16], trade["closed"][:16]
    during = [k for k in candles if o <= k["full"][:16] <= c] or candles[-1:]
    entry, long = float(trade["entry"]), trade["direction"] == "Long"
    hi, lo = max(k["h"] for k in during), min(k["l"] for k in during)
    return (round(hi - entry if long else entry - lo, 5), round(entry - lo if long else hi - entry, 5))


def trade_replay(which="last", position=None):
    """Replay a closed trade on a chart panel (entry, exit, stop, target marked) with what price did around it."""
    trades = R["mt5_trades"](limit=500)
    t = _pick(trades, which, position)
    if not t:
        return {"error": f"No trade found for {position or which}."}
    mins = max(1, (_t(t["closed"]) - _t(t["opened"])).total_seconds() / 60)
    tf = next((f for m, f in TIMEFRAMES if mins <= m), "H4")
    step = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}[tf]
    start = _t(t["opened"]) - datetime.timedelta(minutes=step * 40)
    end = _t(t["closed"]) + datetime.timedelta(minutes=step * 15)
    data = R["candles_between"](t["symbol"], tf, start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"))
    k = data["candles"]
    if not k:
        return {"error": "MT5 has no chart history for that period."}
    idx = lambda s: min(range(len(k)), key=lambda i: abs((_t(k[i]["full"]) - _t(s)).total_seconds()))
    mfe, mae = excursions(t, k)
    marks = {"entry": {"i": idx(t["opened"]), "price": float(t["entry"])},
             "exit": {"i": idx(t["closed"]), "price": float(t["exit"])},
             "stop": _f(t.get("stop")), "target": _f(t.get("tp")), "long": t["direction"] == "Long"}
    sign = "+" if t["pnl"] >= 0 else "-"
    _panel({"type": "panel", "kind": "chart", "title": f"Replay · {t['symbol']} {t['direction']} "
                     f"{sign}${abs(t['pnl']):.2f}", "symbol": data["symbol"], "timeframe": tf, "digits": data["digits"],
                     "candles": k, "marks": marks,
                     "note": f"{t['opened'][5:16]} → {t['closed'][11:16]} · {round(mins)} min · went "
                             f"{mfe:g} in your favour, {mae:g} against" + (f" · {t['read']}" if t.get("read") else "")})
    risk = abs(float(t["entry"]) - marks["stop"]) if marks["stop"] else None
    return {"trade": {k2: t.get(k2) for k2 in ("position", "symbol", "direction", "volume", "opened", "closed",
                                               "entry", "exit", "stop", "tp", "pnl", "read")},
            "minutes_held": round(mins), "best_move_for_him": mfe, "worst_move_against_him": mae,
            "best_move_in_R": round(mfe / risk, 2) if risk else None,
            "note": "Shown on his HUD. Tell him in 2-3 sentences what happened and the lesson."}


# ---------- Tilt detector ----------
def tilt(closed_today, history, open_now=(), start_balance=None, now=None):
    """A 0-100 tilt score from today's trading, with the reasons. history: recent trades (for his usual pace)."""
    now = now or (_t(closed_today[-1]["closed"]) if closed_today else datetime.datetime.now())
    reasons, score = [], 0
    trades = sorted(closed_today, key=lambda t: t["opened"])
    losses = [t for t in trades if t["pnl"] < 0]
    streak = 0
    for t in reversed(sorted(closed_today, key=lambda t: t["closed"])):
        if t["pnl"] >= 0:
            break
        streak += 1
    if streak >= 2:
        score += min(30, streak * 10)
        reasons.append(f"{streak} losses in a row")
    revenge = sizeups = flips = 0
    entries = trades + [dict(p, closed=None, pnl=0) for p in open_now]
    for prev, nxt in zip(trades, entries[1:]):
        if prev["pnl"] >= 0:
            continue
        gap = (_t(nxt["opened"]) - _t(prev["closed"])).total_seconds() / 60
        if 0 <= gap <= trading.REVENGE_MIN * 2:
            revenge += 1
            if nxt["symbol"] == prev["symbol"] and nxt["direction"] != prev["direction"]:
                flips += 1
        if float(nxt["volume"]) >= float(prev["volume"]) * 1.5:
            sizeups += 1
    if revenge:
        score += min(30, revenge * 12)
        reasons.append(f"{revenge} quick re-entr{'y' if revenge == 1 else 'ies'} straight after a loss")
    if flips:
        score += min(15, flips * 8)
        reasons.append(f"flipped direction after a loss {flips} time{'s' if flips > 1 else ''}")
    if sizeups:
        score += min(25, sizeups * 12)
        reasons.append(f"sized up after a loss {sizeups} time{'s' if sizeups > 1 else ''}")
    hour_ago = (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    last_hour = sum(t["opened"] >= hour_ago for t in entries)
    days = {t["opened"][:10] for t in history} or {1}
    usual_per_hour = max(1.0, len(history) / len(days) / 4)  # ponytail: assumes ~4 active hours a day
    if last_hour >= 3 and last_hour >= 2 * usual_per_hour and losses:
        score += 15
        reasons.append(f"{last_hour} trades in the last hour, about {last_hour / usual_per_hour:.0f} times your usual pace")
    loss = -sum(t["pnl"] for t in trades)
    if start_balance and loss > 0:
        pct = loss / start_balance * 100
        if pct >= trading.DAILY_LOSS_PCT / 2:
            score += min(20, round(pct / trading.DAILY_LOSS_PCT * 20))
            reasons.append(f"down {pct:.1f}% of your balance today")
    score = min(100, score)
    return {"score": score, "level": "tilted" if score >= 70 else "heating up" if score >= 40 else "calm",
            "reasons": reasons}


def _today_and_history():
    server_now = R["quote"](["XAUUSD"])["XAUUSD"]["server_time"]
    acct = R["account_status"]()
    closed = R["mt5_trades"](since=server_now[:10], limit=200)
    history = R["mt5_trades"](limit=200)
    start = acct["balance"] - sum(t["pnl"] for t in closed)
    return server_now, acct, closed, history, start


def tilt_check():
    """'Am I tilting?' The tilt score now, shown as a meter on the HUD."""
    server_now, acct, closed, history, start = _today_and_history()
    r = tilt(closed, history, acct["open_positions"], start, _t(server_now))
    _show_tilt(r)
    return r


def _show_tilt(r):
    try:
        _panel({"type": "panel", "kind": "progress", "title": f"Tilt meter · {r['level']}",
                     "items": [{"label": "Tilt", "value": r["score"], "max": 100, "risk": True}],
                "note": "; ".join(r["reasons"]) or "Nothing worrying today."})
    except OSError:
        pass  # the HUD isn't open: the spoken warning still goes out


# ---------- Pre-trade checklist ----------
def pre_trade_check(symbol="XAUUSD", direction=None):
    """Before he enters: his own rules and history checked now. Returns a go / caution / no-go with each check."""
    server_now, acct, closed, history, start = _today_and_history()
    now = _t(server_now)
    checks = []  # (status ok|warn|fail, text)
    try:
        news = [e for e in trading.upcoming_news(hours=1) if -15 <= e["in_minutes"] <= 30]
    except Exception:
        news = None
    if news is None:
        checks.append(("warn", "Couldn't check the news calendar"))
    elif news:
        e = news[0]
        when = f"in {e['in_minutes']} min" if e["in_minutes"] >= 0 else f"{-e['in_minutes']} min ago"
        checks.append(("fail", f"High-impact news: {e['currency']} {e['event']} {when}"))
    else:
        checks.append(("ok", "No high-impact news in the next 30 minutes"))
    losses = sum(t["pnl"] < 0 for t in closed)
    checks.append(("fail" if losses >= trading.LOSSES_A_DAY else "warn" if losses == trading.LOSSES_A_DAY - 1 else "ok",
                   f"{losses} loss{'es' if losses != 1 else ''} today (your limit is {trading.LOSSES_A_DAY})"))
    loss = -sum(t["pnl"] for t in closed)
    pct = loss / start * 100 if start and loss > 0 else 0
    checks.append(("fail" if pct >= trading.DAILY_LOSS_PCT else "warn" if pct >= trading.DAILY_LOSS_PCT / 2 else "ok",
                   f"Day's result {'-' if loss > 0 else '+'}${abs(loss):.0f} ({pct:.1f}% of balance lost)" if loss > 0
                   else "Not down on the day"))
    last = closed[-1] if closed else None
    if last and last["pnl"] < 0:
        gap = (now - _t(last["closed"])).total_seconds() / 60
        checks.append(("warn" if gap < trading.REVENGE_MIN * 3 else "ok",
                       f"Last trade was a loss {round(gap)} min ago" + (": take a breather" if gap < trading.REVENGE_MIN * 3 else "")))
    t = tilt(closed, history, acct["open_positions"], start, now)
    checks.append(("fail" if t["level"] == "tilted" else "warn" if t["score"] >= 40 else "ok",
                   f"Tilt {t['score']}/100 ({t['level']})" + (f": {t['reasons'][0]}" if t["reasons"] else "")))
    hour = server_now[11:13]
    at_hour = [x for x in history if x["opened"][11:13] == hour]
    if len(at_hour) >= 8:
        net, wins = sum(x["pnl"] for x in at_hour), sum(x["pnl"] > 0 for x in at_hour)
        checks.append(("ok" if net > 0 else "warn", f"At {hour}:00 you're {wins}/{len(at_hour)} wins, "
                       f"{'+' if net >= 0 else '-'}${abs(net):.0f} overall"))
    if direction:
        side = [x for x in history if x["direction"].lower() == direction.lower() and trading._sym(x["symbol"]) == trading._sym(symbol)]
        if len(side) >= 8:
            net = sum(x["pnl"] for x in side)
            checks.append(("ok" if net > 0 else "warn", f"Your {direction.lower()}s on {trading._sym(symbol)}: "
                           f"{'+' if net >= 0 else '-'}${abs(net):.0f} over {len(side)} trades"))
    n_open = len(acct["open_positions"])
    if n_open:
        checks.append(("warn" if n_open >= 2 else "ok", f"{n_open} trade{'s' if n_open > 1 else ''} already open"))
    verdict = "no-go" if any(s == "fail" for s, _ in checks) else "caution" if any(s == "warn" for s, _ in checks) else "go"
    _panel({"type": "panel", "kind": "list", "title": f"Pre-trade check · {verdict.upper()}",
                     "items": [{"text": txt, "status": s} for s, txt in checks]})
    return {"verdict": verdict, "checks": [{"status": s, "check": txt} for s, txt in checks],
            "note": "Shown on his HUD. Say the verdict and the one or two reasons that matter."}


# ---------- Watching live: tilt warnings as it builds ----------
class TiltWatch:
    """Called by the trade watcher after each new trade: warns once per level per day as tilt builds."""

    def __init__(self):
        self.day, self.said = None, set()

    def after_trade(self, closed_today, history, open_now, start, server_now):
        day = server_now[:10]
        if day != self.day:
            self.day, self.said = day, set()
        r = tilt(closed_today, history, open_now, start, _t(server_now))
        if r["level"] != "calm" and r["level"] not in self.said:
            self.said.add(r["level"])
            _show_tilt(r)
            return (("Sir, I think you're on tilt: " if r["level"] == "tilted" else "Sir, a word of caution: ")
                    + ", ".join(r["reasons"][:3]) + ". " + ("Step away for a while." if r["level"] == "tilted"
                                                             else "Maybe slow down."))
        return None


FUNCS = {f.__name__: f for f in (trade_replay, pre_trade_check, tilt_check)}
TOOLS = [
    {"name": "trade_replay", "description": "Replay one of his closed MT5 trades as a chart on his HUD with entry, "
     "exit, stop and target marked, plus how far price went for and against him. which: last, last_loss, last_win, "
     "biggest_loss, biggest_win; or position (id). Then tell him what happened and the lesson in 2-3 sentences.",
     "input_schema": {"type": "object", "properties": {"which": {"type": "string", "enum": ["last", "last_loss",
                      "last_win", "biggest_loss", "biggest_win"]}, "position": {"type": "string"}}}},
    {"name": "pre_trade_check", "description": "His pre-trade checklist, before he enters a trade ('should I take "
     "this?', 'can I trade now?', 'run the checklist'): news, losses today, daily loss, tilt, how he does at this "
     "hour and in this direction. Gives go / caution / no-go and shows the checklist on his HUD.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"},
                                                        "direction": {"type": "string", "enum": ["long", "short"]}}}},
    {"name": "tilt_check", "description": "'Am I tilting?': a 0-100 tilt score from today's trading (losing streak, "
     "revenge re-entries, sizing up or flipping after losses, overtrading, daily loss), shown as a meter.",
     "input_schema": {"type": "object", "properties": {}}},
]


def selftest():
    global _panel
    shown, _panel = [], lambda ev: shown.append(ev)
    T = lambda o, c, d, v, pnl, sym="XAUUSD": {"position": o, "opened": f"2026-11-05 {o}:00", "closed": f"2026-11-05 {c}:00",
                                               "symbol": sym, "direction": d, "volume": v, "pnl": pnl, "entry": "4000",
                                               "exit": "3990", "stop": "", "tp": ""}
    calm = tilt([T("10:00", "10:20", "Long", 0.1, 25), T("11:00", "11:30", "Short", 0.1, -10)], [], (), 1000)
    assert calm["level"] == "calm", calm
    bad = [T("10:00", "10:10", "Long", 0.1, -20), T("10:12", "10:15", "Short", 0.2, -30),  # flip + size-up
           T("10:17", "10:20", "Short", 0.4, -45), T("10:21", "10:25", "Long", 0.8, -60)]
    r = tilt(bad, [], (), 1000, datetime.datetime(2026, 11, 5, 10, 30))
    assert r["level"] == "tilted" and any("in a row" in x for x in r["reasons"]) and any("sized up" in x for x in r["reasons"]), r
    w = TiltWatch()
    assert w.after_trade(bad, [], (), 1000, "2026-11-05 10:30:00").startswith("Sir, I think you're on tilt")
    assert w.after_trade(bad, [], (), 1000, "2026-11-05 10:31:00") is None  # said once per level per day
    assert shown[-1]["kind"] == "progress" and shown[-1]["title"] == "Tilt meter · tilted"
    k = [{"full": f"2026-11-05 10:{m:02d}:00", "h": 4000 + m, "l": 3995 - m, "o": 0, "c": 0} for m in range(0, 30)]
    mfe, mae = excursions({"opened": "2026-11-05 10:05:00", "closed": "2026-11-05 10:10:00", "entry": "4000",
                           "direction": "Long"}, k)
    assert (mfe, mae) == (10, 15), (mfe, mae)
    assert _pick([T("10:00", "10:10", "Long", 0.1, -5), T("11:00", "11:10", "Long", 0.1, 9)], "last_loss", None)["pnl"] == -5
    print("coach self-test passed")


if __name__ == "__main__":
    selftest()
