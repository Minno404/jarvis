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


# ---------- His trading rules (editable by voice; used by the checklist and the session debrief) ----------
DEFAULT_RULES = {"max_losses": trading.LOSSES_A_DAY, "cooldown_min": trading.REVENGE_MIN * 2,
                 "daily_loss_pct": trading.DAILY_LOSS_PCT, "max_size_x": trading.SIZE_UP_X, "news_buffer_min": 15,
                 "max_trades": None, "no_trade_before": None, "no_trade_after": None}
RULE_WORDS = {"max_losses": "stop after {} losses in a day", "cooldown_min": "wait {} minutes after a loss",
              "daily_loss_pct": "stop at a {}% daily loss", "max_size_x": "no more than {}× your usual size",
              "news_buffer_min": "no entries within {} minutes of high-impact news", "max_trades": "at most {} trades a day",
              "no_trade_before": "no trading before {}", "no_trade_after": "no trading after {}"}


def rules():
    return {**DEFAULT_RULES, **features.settings().get("trading_rules", {})}


def set_trading_rules(max_losses=None, cooldown_min=None, daily_loss_pct=None, max_size_x=None, news_buffer_min=None,
                      max_trades=None, no_trade_before=None, no_trade_after=None):
    """Change his trading rules. Give only what changes; 0 or "" turns a rule back to its default (or off)."""
    s = features.settings()
    mine = dict(s.get("trading_rules", {}))
    given = {k: v for k, v in locals().items() if k in DEFAULT_RULES and v is not None}
    for k, v in given.items():
        if v in (0, "", "off", "none"):
            mine.pop(k, None)
        elif k in ("no_trade_before", "no_trade_after"):
            import re
            m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?", str(v).strip().lower())
            h = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0) if m and m.group(3) else int(m.group(1)) if m else 99
            if not m or h > 23 or int(m.group(2) or 0) > 59:
                return {"error": f"{k} must be a time like 23:00 or 11pm"}
            mine[k] = f"{h:02d}:{int(m.group(2) or 0):02d}"
        else:
            mine[k] = float(v) if k in ("daily_loss_pct", "max_size_x") else int(v)
    features._save("settings.json", {**s, "trading_rules": mine})
    return {"rules": [RULE_WORDS[k].format(v) for k, v in rules().items() if v not in (None, "")]}


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
        buf = rules()["news_buffer_min"]
        news = [e for e in trading.upcoming_news(hours=1) if -buf <= e["in_minutes"] <= max(30, buf)]
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
    rl = rules()
    losses = sum(t["pnl"] < 0 for t in closed)
    checks.append(("fail" if losses >= rl["max_losses"] else "warn" if losses == rl["max_losses"] - 1 else "ok",
                   f"{losses} loss{'es' if losses != 1 else ''} today (your limit is {rl['max_losses']})"))
    loss = -sum(t["pnl"] for t in closed)
    pct = loss / start * 100 if start and loss > 0 else 0
    checks.append(("fail" if pct >= rl["daily_loss_pct"] else "warn" if pct >= rl["daily_loss_pct"] / 2 else "ok",
                   f"Day's result {'-' if loss > 0 else '+'}${abs(loss):.0f} ({pct:.1f}% of balance lost)" if loss > 0
                   else "Not down on the day"))
    last = closed[-1] if closed else None
    if last and last["pnl"] < 0:
        gap = (now - _t(last["closed"])).total_seconds() / 60
        checks.append(("fail" if gap < rl["cooldown_min"] else "ok",
                       f"Last trade was a loss {round(gap)} min ago" + (f": your rule is {rl['cooldown_min']} min" if gap < rl["cooldown_min"] else "")))
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


# ---------- Session debrief: each entry against his own rules, and the mistakes that keep coming back ----------
BREAKS = {"over_loss_limit": "Traded on after hitting your loss limit", "cooldown": "Re-entered before the cool-down after a loss",
          "flip": "Flipped direction straight after a loss", "oversize": "Sized up beyond your limit",
          "past_daily_loss": "Kept trading past your daily loss limit", "hours": "Traded outside your hours",
          "overtrading": "Went over your trades-per-day limit", "news": "Entered right around high-impact news"}


def check_entries(day_trades, rl, usual_volume, start_balance=None, offset=datetime.timedelta(0), news=()):
    """Which of his rules each entry broke. day_trades: one day's closed trades. offset: server time - local time.
    news: high-impact event times (local). Returns [(trade, [break keys])] in entry order."""
    out, ts = [], sorted(day_trades, key=lambda t: t["opened"])
    for i, t in enumerate(ts):
        opened, b = _t(t["opened"]), []
        prior = [p for p in ts[:i] if p["closed"] <= t["opened"]]
        losses = [p for p in prior if p["pnl"] < 0]
        if len(losses) >= rl["max_losses"]:
            b.append("over_loss_limit")
        last = max(prior, key=lambda p: p["closed"]) if prior else None
        if last and last["pnl"] < 0 and (opened - _t(last["closed"])).total_seconds() / 60 < rl["cooldown_min"]:
            b.append("cooldown")
            if last["symbol"] == t["symbol"] and last["direction"] != t["direction"]:
                b.append("flip")
        if usual_volume and float(t["volume"]) >= rl["max_size_x"] * usual_volume:
            b.append("oversize")
        down = -sum(p["pnl"] for p in prior)
        if start_balance and down >= start_balance * rl["daily_loss_pct"] / 100:
            b.append("past_daily_loss")
        local = (opened - offset).strftime("%H:%M")
        if (rl["no_trade_before"] and local < rl["no_trade_before"]) or (rl["no_trade_after"] and local >= rl["no_trade_after"]):
            b.append("hours")
        if rl["max_trades"] and i >= rl["max_trades"]:
            b.append("overtrading")
        if any(abs((opened - offset - n).total_seconds()) / 60 <= rl["news_buffer_min"] for n in news):
            b.append("news")
        out.append((t, b))
    return out


def _news_times():
    try:
        out = []
        for e in trading._calendar():
            if e.get("impact") == "High" and e.get("country") in trading.NEWS_CURRENCIES:
                out.append(datetime.datetime.fromisoformat(e["date"]).astimezone().replace(tzinfo=None))
        return out
    except Exception:
        return []  # calendar unavailable: the news rule just isn't checked


def debrief(day, history, rl, offset=datetime.timedelta(0), news=(), sessions=10):
    """The day's entries against his rules, plus recurring mistakes over his last `sessions` trading days."""
    days = sorted({t["closed"][:10] for t in history})
    if day not in days:
        return None
    usual = statistics.median(float(t["volume"]) for t in history[-60:])
    by_day = {d: [t for t in history if t["closed"][:10] == d] for d in days[-sessions:] + ([day] if day not in days[-sessions:] else [])}
    start = lambda ts: _f(sorted(ts, key=lambda t: t["opened"])[0].get("balanceAtOpen"))
    checked = {d: check_entries(ts, rl, usual, start(ts), offset, news) for d, ts in by_day.items()}
    today = checked[day]
    cost = lambda rows: round(sum(t["pnl"] for t, _ in rows), 2)
    kept = [(t, b) for t, b in today if not b]
    broken = [(t, b) for t, b in today if b]
    counts = {}
    for t, b in broken:
        for k in b:
            counts.setdefault(k, []).append(t)
    recent = [d for d in checked if d <= day][-sessions:]
    recurring = []
    for k in BREAKS:
        hit = [d for d in recent if any(k in b for _, b in checked[d])]
        if len(hit) >= 3:
            recurring.append({"mistake": BREAKS[k], "key": k, "sessions": len(hit), "of": len(recent),
                              "cost": round(sum(t["pnl"] for d in hit for t, b in checked[d] if k in b), 2)})
    recurring.sort(key=lambda r: (-r["sessions"], r["cost"]))
    focus = (recurring[0]["mistake"] if recurring else BREAKS[max(counts, key=lambda k: len(counts[k]))] if counts else None)
    return {"day": day, "entries": len(today), "followed_rules": len(kept), "pnl_following_rules": cost(kept),
            "pnl_breaking_rules": cost(broken),
            "broken_today": [{"mistake": BREAKS[k], "times": len(v), "pnl": round(sum(t["pnl"] for t in v), 2),
                              "at": [t["opened"][11:16] for t in v]} for k, v in counts.items()],
            "recurring": recurring[:3], "focus_tomorrow": focus}


def session_debrief(day=None):
    """His session's entries checked against his own rules, the recurring mistakes, and one thing to fix tomorrow."""
    history = sorted(R["mt5_trades"](limit=2000), key=lambda t: t["closed"])
    if not history:
        return {"error": "No MT5 trades to debrief."}
    day = day or history[-1]["closed"][:10]
    try:
        server_now = _t(R["quote"](["XAUUSD"])["XAUUSD"]["server_time"])
        offset = datetime.timedelta(minutes=round((server_now - datetime.datetime.now()).total_seconds() / 1800) * 30)
    except Exception:
        offset = datetime.timedelta(0)  # MT5 closed: treat server time as local
    r = debrief(day, history, rules(), offset, _news_times())
    if not r:
        return {"error": f"No trades on {day}."}
    money = lambda v: f"{'+' if v >= 0 else '-'}${abs(v):.2f}"
    items = [{"text": f"{r['followed_rules']} of {r['entries']} entries followed your rules",
              "sub": f"Those made {money(r['pnl_following_rules'])}; the rest made {money(r['pnl_breaking_rules'])}",
              "status": "ok" if r["followed_rules"] == r["entries"] else "warn"}]
    items += [{"text": f"{b['mistake']} ×{b['times']}", "sub": f"{money(b['pnl'])} · at {', '.join(b['at'][:5])}",
               "status": "fail"} for b in r["broken_today"]]
    items += [{"text": f"Recurring: {x['mistake'].lower()}", "sub": f"{x['sessions']} of your last {x['of']} sessions · "
               f"{money(x['cost'])}", "status": "warn"} for x in r["recurring"]]
    if r["focus_tomorrow"]:
        items.append({"text": f"Tomorrow, watch for: {r['focus_tomorrow'].lower()}", "status": "warn"})
    try:
        _panel({"type": "panel", "kind": "list", "title": f"Session debrief · {day}", "items": items})
    except OSError:
        pass
    return {**r, "rules": [RULE_WORDS[k].format(v) for k, v in rules().items() if v not in (None, "")],
            "note": "Shown on his HUD. In 3-5 spoken sentences: rules kept vs broken and what each cost, the recurring "
                    "mistake, and the one thing to watch tomorrow."}


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


FUNCS = {f.__name__: f for f in (trade_replay, pre_trade_check, tilt_check, session_debrief, set_trading_rules)}
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
    {"name": "session_debrief", "description": "Debrief a trading session: every entry checked against his own rules "
     "(loss limit, cool-down after a loss, size, daily loss, hours, news), what rule-breaking cost, the mistakes that "
     "keep recurring across his last 10 sessions, and the one thing to watch tomorrow. Shown on his HUD. day = "
     "YYYY-MM-DD (MT5 server date; default his latest session).",
     "input_schema": {"type": "object", "properties": {"day": {"type": "string"}}}},
    {"name": "set_trading_rules", "description": "Change his trading rules when he asks ('stop me after 2 losses', "
     "'no trading after 11pm', 'wait 15 minutes after a loss'). Only pass what changes; 0 resets one. Times are his "
     "local time, 24-hour. Returns all his rules.",
     "input_schema": {"type": "object", "properties": {"max_losses": {"type": "integer"}, "cooldown_min": {"type": "integer"},
                      "daily_loss_pct": {"type": "number"}, "max_size_x": {"type": "number", "description": "times usual size"},
                      "news_buffer_min": {"type": "integer"}, "max_trades": {"type": "integer"},
                      "no_trade_before": {"type": "string"}, "no_trade_after": {"type": "string"}}}},
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
    rl = dict(DEFAULT_RULES, max_losses=2, cooldown_min=10, no_trade_after="23:00")
    day = [T("10:00", "10:10", "Long", 0.1, -20), T("10:15", "10:20", "Short", 0.1, -10),  # 5 min after a loss, flipped
           T("10:40", "10:50", "Long", 0.3, -15),  # after 2 losses (limit) and 3x size
           dict(T("23:00", "23:10", "Long", 0.1, 30), opened="2026-11-05 23:05:00", closed="2026-11-05 23:30:00")]
    got = [b for _, b in check_entries(day, rl, 0.1)]
    assert got == [[], ["cooldown", "flip"], ["over_loss_limit", "oversize"], ["over_loss_limit", "hours"]], got
    hist = []
    for d in range(1, 6):  # five sessions, each with a quick re-entry after a loss
        hist += [dict(T("09:00", "09:10", "Long", 0.1, -5), closed=f"2026-11-0{d} 09:10:00", opened=f"2026-11-0{d} 09:00:00"),
                 dict(T("09:12", "09:20", "Long", 0.1, -7), closed=f"2026-11-0{d} 09:20:00", opened=f"2026-11-0{d} 09:12:00")]
    r = debrief("2026-11-05", hist, dict(DEFAULT_RULES))
    assert r["entries"] == 2 and r["followed_rules"] == 1 and r["pnl_breaking_rules"] == -7
    assert r["recurring"][0]["key"] == "cooldown" and r["recurring"][0]["sessions"] == 5
    assert r["focus_tomorrow"] == BREAKS["cooldown"]
    import tempfile
    from pathlib import Path
    real, features.HERE = features.HERE, Path(tempfile.mkdtemp())
    try:
        assert "no trading after 23:00" in set_trading_rules(no_trade_after="11pm")["rules"]
        assert "no trading before 07:30" in set_trading_rules(no_trade_before="7:30am")["rules"]
        assert "error" in set_trading_rules(no_trade_after="late")
        assert rules()["max_losses"] == DEFAULT_RULES["max_losses"] and set_trading_rules(max_losses=2) and rules()["max_losses"] == 2
    finally:
        features.HERE = real
    print("coach self-test passed")


if __name__ == "__main__":
    selftest()
