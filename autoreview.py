"""The autopilot's report card.

- Trade review: when one of its trades closes, Jarvis says how it went and sends it to his phone, and keeps a review
  (autopilot_reviews.json): entry, exit, profit, R, what each brain said, and the M15 candles around it.
  "Show my autopilot trades" draws them with their charts.
- Weekly summary: Sunday from 6 pm, the week's trades, win rate and total, said and sent to his phone.
- Test run: "test the autopilot" replays past moments (random 15-minute candles in the last 60 days, outside quiet
  hours and weekends) through both brains exactly like the live autopilot, then follows the price afterwards to see
  whether the stop or the target came first. It shows the win rate and total in R and $ before any money is risked.
  Each moment costs one ChatGPT question, plus one for Claude when ChatGPT sees a trade.
"""
import datetime
import json
import random
import threading
from pathlib import Path

import features
import mt5trade as m

REVIEWS = Path(__file__).parent / "autopilot_reviews.json"
TEST = Path(__file__).parent / "autopilot_test.json"


def _load(p, default):
    return m._load(p, default)


def _bars(mt5, s, start, end, tf="M15"):
    """Candles between two MT5 server times (seconds): [[time, open, high, low, close]]."""
    r = mt5.copy_rates_range(s, getattr(mt5, "TIMEFRAME_" + tf), int(start), int(end))
    return [] if r is None else [[int(c["time"]), float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])]
                                 for c in r]


# ---------- Trade review ----------
def check_closed(mt5, say):
    """Called every minute by the autopilot: review each of its trades that has closed since."""
    log = _load(m.AUTO_LOG, [])
    done = {r["ticket"] for r in _load(REVIEWS, [])}
    open_now = {p.ticket for p in mt5.positions_get() or []}
    week = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    for e in log[-60:]:
        t, r = e.get("trade"), e.get("result") or {}
        ticket = r.get("order")
        if not (t and r.get("done") and ticket) or ticket in done or ticket in open_now or e["at"] < week:
            continue
        deals = mt5.history_deals_get(position=ticket) or []
        outs = [d for d in deals if d.entry == 1]  # DEAL_ENTRY_OUT: closing
        if not outs:
            continue
        rev = review(mt5, e, deals, outs)
        reviews = _load(REVIEWS, [])[-300:] + [rev]
        m._save(REVIEWS, reviews)
        line = (f"Autopilot trade closed: {t['side']} {t['lots']} {t['symbol']}, "
                f"{'up' if rev['profit'] >= 0 else 'down'} ${abs(rev['profit']):,.2f} ({rev['r']:+.1f}R).")
        say(line)
        import alerts
        alerts.notify(line, "Autopilot", tags="chart_with_upwards_trend" if rev["profit"] >= 0 else "chart_with_downwards_trend")


def review(mt5, e, deals, outs):
    t = e["trade"]
    info = mt5.symbol_info(t["symbol"])
    profit = round(sum(d.profit + d.commission + d.swap for d in deals), 2)
    risk = m.loss_per_lot(info, t["entry"], t["stop"]) * t["lots"] if info else 0
    opened = min(d.time for d in deals)  # MT5 server time
    closed = max(d.time for d in outs)
    bars = _bars(mt5, t["symbol"], opened - 5 * 3600, closed + 3600)[-120:]
    return {"ticket": e["result"]["order"], "symbol": t["symbol"], "side": t["side"], "lots": t["lots"],
            "opened": e["at"], "closed": datetime.datetime.now().isoformat(timespec="seconds"), "entry": t["entry"], "stop": t["stop"],
            "target": t["target"], "exit": outs[-1].price, "profit": profit, "r": round(profit / risk, 2) if risk else 0,
            "why": e.get("why") or [], "bars": [b[1:] for b in bars]}


def show_trades(days=7):
    """His autopilot's closed trades from the last `days` days, with their charts."""
    since = (datetime.datetime.now() - datetime.timedelta(days=int(days))).isoformat()
    rows = [r for r in _load(REVIEWS, []) if r["closed"] >= since]
    s = summary(rows)
    features._panel({"type": "panel", "title": f"Autopilot trades · {days} days", "kind": "trades", "stay": True,
                     "trades": rows[-12:][::-1], "note": s["text"]})
    return {k: v for k, v in s.items()}


def summary(rows):
    wins = [r for r in rows if r["profit"] > 0]
    total = round(sum(r["profit"] for r in rows), 2)
    text = (f"{len(rows)} trade{'s' if len(rows) != 1 else ''}, {len(wins)} won "
            f"({100 * len(wins) // len(rows)}%), {'up' if total >= 0 else 'down'} ${abs(total):,.2f}, "
            f"{sum(r['r'] for r in rows):+.1f}R" if rows else "No autopilot trades closed in that time.")
    return {"trades": len(rows), "wins": len(wins), "total": total, "text": text}


def weekly_due(now=None):
    """Sunday from 6 pm, once a week."""
    now = now or datetime.datetime.now()
    st = features._load("state.json", {})
    week = now.strftime("%G-%V")
    if now.weekday() != 6 or now.hour < 18 or st.get("auto_week") == week:
        return False
    features._save("state.json", {**st, "auto_week": week})
    return True


def weekly(say):
    since = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    rows = [r for r in _load(REVIEWS, []) if r["closed"] >= since]
    if not rows:
        return None
    s = summary(rows)
    text = f"The autopilot's week: {s['text']}."
    best = max(rows, key=lambda r: r["profit"])
    if len(rows) > 1:
        text += f" Best: {best['side']} {best['symbol']} {best['opened'][5:10]}, ${best['profit']:,.2f}."
    say(text)
    import alerts
    alerts.notify(text, "Autopilot weekly review", tags="bar_chart")
    show_trades(7)
    return text


# ---------- Test run ----------
RUN = {"on": False, "done": 0, "of": 0}


def outcome(side, entry, stop, target, bars):
    """R from the candles after entry: the stop or the target, whichever is hit first (both in one candle counts as
    the stop, to be safe); neither within the candles: closed at the last close."""
    risk = abs(entry - stop)
    for _, h, lo, c in bars:
        hit_stop = lo <= stop if side == "buy" else h >= stop
        hit_target = h >= target if side == "buy" else lo <= target
        if hit_stop:
            return -1.0, "stop"
        if hit_target:
            return round(abs(target - entry) / risk, 2), "target"
    last = bars[-1][3] if bars else entry
    return round(((last - entry) if side == "buy" else (entry - last)) / risk, 2), "time"


def filled(side, order, entry, bars):
    """Index of the candle where a planned entry is reached (0 for a market entry), else None."""
    if order == "market":
        return 0
    for i, (_, h, lo, _c) in enumerate(bars):
        if lo <= entry <= h or (order == "stop") == (side == "buy") and h >= entry or (order == "stop") != (side == "buy") and lo <= entry:
            return i
    return None


def moments(n, days, lim, now=None):
    """n random past 15-minute candle closes on weekdays, outside his quiet hours, at least a day back."""
    now = now or datetime.datetime.now()
    q_from, q_to = lim.get("auto_quiet_from"), lim.get("auto_quiet_to")
    out, tries = set(), 0
    while len(out) < n and tries < n * 50:
        tries += 1
        t = now - datetime.timedelta(days=1, minutes=random.randint(0, (days - 1) * 1440))
        t = t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0)
        hm = t.strftime("%H:%M")
        quiet = q_from and q_to and ((q_from <= hm < q_to) if q_from < q_to else (hm >= q_from or hm < q_to))
        if t.weekday() < 5 and not quiet:
            out.add(t)
    return sorted(out)


def test_autopilot(samples=30, days=60):
    """Start the test run in the background (results on a panel and said when done)."""
    if RUN["on"]:
        return {"running": True, "done": RUN["done"], "of": RUN["of"]}
    samples = max(5, min(int(samples), 120))
    mt5 = m._mt5()
    why = m.ready(mt5)
    if why:
        return {"error": why}
    if len(m.brains()) < 2:
        return {"error": "The test needs both brains set up, like the autopilot."}
    RUN.update(on=True, done=0, of=samples, fails=0)
    threading.Thread(target=_run, args=(samples, int(days)), daemon=True).start()
    return {"started": True, "samples": samples,
            "note": f"Replaying {samples} past moments; takes about {samples} minutes. Each one asks ChatGPT once."}


def _run(samples, days):
    import server_bridge
    try:
        res = _replay(samples, days)
        s = res["summary"]
        server_bridge.say(f"Autopilot test done: {s['text']}")
    except Exception as e:
        server_bridge.say(f"The autopilot test stopped: {str(e)[:120]}")
    finally:
        RUN["on"] = False


def _replay(samples, days):
    mt5 = m._mt5()
    lim = m.limits()
    acc = mt5.account_info()
    s = m._symbol(mt5, lim["auto_symbols"][0])
    info, tick = mt5.symbol_info(s), mt5.symbol_info_tick(s)
    spread = tick.ask - tick.bid
    offset = round((tick.time - datetime.datetime.now().timestamp()) / 1800) * 1800  # MT5 server time vs real time
    rows = []
    for i, local in enumerate(moments(samples, days, lim)):
        at = int(local.timestamp() + offset)  # the same moment in MT5 server time
        snap = m.snapshot(mt5, s, info, 0, 0, acc, lim, at=at)
        if not snap["M15"]:
            continue
        bid = snap["M15"][-1][3]
        snap.update(bid=bid, ask=round(bid + spread, info.digits), sizing=m.sizing(info, bid, acc, lim))
        errs = []
        picks, names = m.ask_brains(m.build_prompt({s: snap}, acc, lim), errs.append)
        if errs and not any(picks):
            fails = RUN["fails"] = RUN.get("fails", 0) + 1
            if fails >= 3:  # the brain isn't answering at all: stop instead of burning through every moment
                raise RuntimeError(errs[0])
            continue
        RUN["fails"] = 0
        row = {"at": local.isoformat(timespec="minutes"), "brains": dict(zip(names, picks))}
        if len(picks) == 2 and all(picks):
            deal = m.agree({**picks[0], "symbol": s}, {**picks[1], "symbol": s}, None, info.digits, bid, snap["ask"])
            if deal and deal["rr"] >= lim["auto_min_rr"]:
                after = [b[1:] for b in _bars(mt5, s, at, at + 86400) if b[0] >= at]
                trade = {k: deal[k] for k in ("side", "order", "entry", "stop", "target")}
                start = filled(deal["side"], deal["order"], deal["entry"], after[:int(lim["auto_order_hours"] * 4)])
                if start is None:
                    row.update(trade=trade, how="not reached")  # the planned entry expired: no trade
                else:
                    r, how = outcome(deal["side"], deal["entry"], deal["stop"], deal["target"], after[start:])
                    row.update(trade=trade, r=r, how=how)
        rows.append(row)
        RUN["done"] = i + 1
        _panel(rows, samples, lim, acc, done=False)
    res = {"ran": datetime.datetime.now().isoformat(timespec="minutes"), "symbol": s, "rows": rows,
           "summary": _test_summary(rows, lim, acc)}
    m._save(TEST, res)
    _panel(rows, samples, lim, acc, done=True)
    return res


def _test_summary(rows, lim, acc):
    trades = [r for r in rows if "r" in r]
    wins = [r for r in trades if r["r"] > 0]
    total_r = round(sum(r["r"] for r in trades), 2)
    risk = m.money(lim["trade_size"], lim["trade_size_unit"], m.base_size(acc, lim)) if lim["trade_size_unit"] != "lots" else 0
    text = (f"{len(rows)} moments checked, {len(trades)} trade{'s' if len(trades) != 1 else ''}, {len(wins)} won"
            + (f" ({100 * len(wins) // len(trades)}%)" if trades else "")
            + f", {total_r:+.1f}R" + (f", about {'+' if total_r >= 0 else '-'}${abs(total_r * risk):,.0f} at your "
                                     "risk per trade" if risk else ""))
    return {"moments": len(rows), "trades": len(trades), "wins": len(wins), "r": total_r, "text": text}


def _panel(rows, of, lim, acc, done):
    s = _test_summary(rows, lim, acc)
    items = [{"text": f"{r['at'][5:16].replace('T', ' ')}  {r['trade']['side']} {r['trade'].get('order', '')} → {r['how']}"
                      + (f" {r['r']:+.1f}R" if "r" in r else ""),
              "sub": next((str(p.get('reason', ''))[:120] for p in r["brains"].values() if p), "")}
             for r in rows if "trade" in r][-10:]
    m._panel({"type": "panel", "title": "Autopilot test run" + ("" if done else f" · {len(rows)}/{of}"), "kind": "list",
              "stay": True, "items": items or [{"text": "No trades yet", "sub": f"{len(rows)} moments checked"}],
              "note": s["text"] + ("" if done else " (still running)")})


def last_test():
    """The last test run's result (or that none has run)."""
    t = _load(TEST, None)
    return {"running": RUN["on"], "done": RUN["done"], "of": RUN["of"],
            "last": t and {"ran": t["ran"], **t["summary"]}}


FUNCS = {"test_autopilot": test_autopilot, "autopilot_test_result": last_test, "autopilot_trades": show_trades}
TOOLS = [
    {"name": "test_autopilot", "description": "Test the trading autopilot on past charts before risking money ('test the "
     "autopilot', 'backtest it'): replays `samples` random past moments (default 30, last `days` days, default 60) "
     "through both brains and checks whether each trade would have hit its stop or target. Runs in the background "
     "and reports when done.", "input_schema": {"type": "object", "properties": {
         "samples": {"type": "integer"}, "days": {"type": "integer"}}}},
    {"name": "autopilot_test_result", "description": "The autopilot test run's progress or last result.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "autopilot_trades", "description": "The autopilot's closed trades with their charts, profit and what each "
     "brain said ('show my autopilot trades', 'how did the autopilot do this week'). days: default 7.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}}}},
]
COMMANDS = {"Trading": ["*Test the autopilot", "*Show my autopilot trades"]}


if __name__ == "__main__":
    import tempfile
    features.HERE = Path(tempfile.mkdtemp())
    assert outcome("buy", 100, 98, 104, [[100, 101, 99, 100], [100, 104.5, 99.5, 104]]) == (2.0, "target")
    assert outcome("sell", 100, 102, 96, [[100, 102.1, 95, 96]]) == (-1.0, "stop")  # both in one candle: the stop
    assert outcome("buy", 100, 98, 110, [[100, 101, 99, 101]]) == (0.5, "time")
    bars = [[100, 101, 99, 100], [100, 103, 100, 102]]
    assert filled("buy", "stop", 102, bars) == 1 and filled("buy", "limit", 98, bars) is None and filled("sell", "market", 0, []) == 0
    assert filled("sell", "limit", 102.5, bars) == 1 and filled("sell", "stop", 99.5, bars) == 0
    lim = {"auto_quiet_from": "04:00", "auto_quiet_to": "10:30"}
    ts = moments(40, 60, lim, datetime.datetime(2026, 11, 11, 18))
    assert len(ts) == 40 and all(t.weekday() < 5 and not ("04:00" <= t.strftime("%H:%M") < "10:30") and t.minute % 15 == 0 for t in ts)
    rows = [{"profit": 50, "r": 1.0}, {"profit": -25, "r": -0.5}]
    assert summary(rows)["text"] == "2 trades, 1 won (50%), up $25.00, +0.5R"
    assert weekly_due(datetime.datetime(2026, 11, 15, 18, 5)) and not weekly_due(datetime.datetime(2026, 11, 15, 19))
    print("autoreview self-test passed")
