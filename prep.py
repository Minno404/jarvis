"""Market prep: before his session, Jarvis studies each pair he trades and briefs him.

For each autopilot pair (Settings > Trading): the last 48 hourly candles, the key levels (the chart watcher's: H1
swing highs and lows, yesterday's high and low), the H1 trend, the overnight move (last 8 hours), the M15 ATR, and
today's high-impact news for its currencies. A panel draws each pair's chart with its levels; one short AI brief
(Claude Haiku, a few hundred tokens) is said and sent to his phone.
Automatic on weekdays at Settings 'prep_time' (default 10:00, off when empty), or "prep me for the session".
"""
import datetime

import features


def study(mt5, s):
    """One pair's numbers, straight from MT5 (no AI)."""
    import mt5trade as m
    import watcher
    h1, d1, m15 = m._closed(mt5, s, "H1", 120), m._closed(mt5, s, "D1", 3), m._closed(mt5, s, "M15", 40)
    tick = mt5.symbol_info_tick(s)
    info = mt5.symbol_info(s)
    night = h1[-8:]
    price = tick.bid if tick else h1[-1][4]
    lv = sorted(watcher.levels(h1, d1), key=lambda v: abs(v - price))[:6]
    news = []
    try:
        import trading
        news = [f"{e['currency']} {e['event']} at {e['time'][11:16]}" for e in
                trading.high_impact(trading._calendar(), datetime.datetime.now(), 14, watcher.currencies(s))]
    except Exception:
        pass
    d = info.digits if info else 2
    return {"symbol": s, "price": round(price, d), "trend": watcher.trend(h1), "atr_m15": round(watcher.atr(m15), d),
            "overnight": {"high": round(max(c[2] for c in night), d), "low": round(min(c[3] for c in night), d),
                          "change": round(price - night[0][1], d)} if night else {},
            "levels": [round(v, d) for v in sorted(lv)], "news": news, "candles": [c[1:] for c in h1[-48:]]}


def brief(pairs):
    """A short spoken brief from the numbers (Claude Haiku); a plain one if that fails."""
    facts = "\n".join(f"{p['symbol']}: price {p['price']}, H1 trend {p['trend']}, overnight {p['overnight']}, M15 ATR "
                      f"{p['atr_m15']}, key levels {p['levels']}, news: {', '.join(p['news']) or 'none'}" for p in pairs)
    try:
        import council
        r = council._claude(features.personal(
            "Write {USER}'s market prep before his trading session, as Jarvis would say it: 3 to 5 short spoken "
            "sentences, plain words, no lists or symbols. For each pair: the trend, the nearest levels above and below "
            "price, what overnight did, and any news to avoid. End with the one setup most worth watching. Facts:\n"
            + facts + '\nReply as JSON: {"brief": "..."}'), "haiku")
        return (council._json(r) or {}).get("brief") or r
    except Exception as e:
        print("market prep brief:", repr(e)[:120])
        return " ".join(f"{p['symbol']} is in an H1 {p['trend']}trend at {p['price']}, levels {', '.join(map(str, p['levels'][:4]))}."
                        .replace("rangetrend", "range") for p in pairs)


def market_prep(show=True):
    """Study his pairs now and brief him (panel, spoken, phone)."""
    import mt5trade as m
    mt5 = m._mt5()
    why = m.ready(mt5)
    if why:
        return {"error": why}
    pairs = []
    for raw in m.limits()["auto_symbols"]:
        try:
            pairs.append(study(mt5, m._symbol(mt5, raw)))
        except Exception as e:
            print("market prep", raw, repr(e)[:120])
    if not pairs:
        return {"error": "No prices from MT5 right now (market closed?)."}
    text = brief(pairs)
    if show:
        features._panel({"type": "panel", "kind": "prep", "title": "Market prep", "stay": True, "pairs": pairs,
                         "brief": text})
        try:
            import alerts
            alerts.notify(text, "Market prep", tags="chart_with_upwards_trend")
        except Exception:
            pass
    return {"brief": text, "pairs": [{k: v for k, v in p.items() if k != "candles"} for p in pairs]}


def due(now=None):
    """Weekdays at Settings 'prep_time', once a day."""
    now = now or datetime.datetime.now()
    t = features.settings().get("prep_time", "10:00")
    st = features._load("state.json", {})
    if not t or now.weekday() >= 5 or now.strftime("%H:%M") < t or st.get("prep_day") == now.date().isoformat():
        return False
    if now.strftime("%H:%M") > (datetime.datetime.strptime(t, "%H:%M") + datetime.timedelta(hours=2)).strftime("%H:%M"):
        return False  # PC was off then: not hours later
    features._save("state.json", {**st, "prep_day": now.date().isoformat()})
    return True


FUNCS = {"market_prep": market_prep}
TOOLS = [{"name": "market_prep", "description": "Study his trading pairs and brief him before a session ('prep me "
          "for the session', 'what's the market doing'): trend, key levels, overnight move, news, drawn on a panel.",
          "input_schema": {"type": "object", "properties": {}}}]
COMMANDS = {"Trading": ["Prep me for the session"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    features._save("settings.json", {"prep_time": "10:00"})
    assert not due(datetime.datetime(2026, 11, 12, 9, 59)) and due(datetime.datetime(2026, 11, 12, 10, 5))
    assert not due(datetime.datetime(2026, 11, 12, 10, 30))  # once a day
    assert not due(datetime.datetime(2026, 11, 13, 13, 0))  # 3 hours late: skipped
    assert not due(datetime.datetime(2026, 11, 14, 10, 5))  # Saturday
    import council
    council._claude = lambda p, model="sonnet": '{"brief": "Gold is trending up at 4012, sir."}'
    assert brief([{"symbol": "XAUUSD", "price": 4012, "trend": "up", "overnight": {}, "atr_m15": 3, "levels": [4000],
                   "news": []}]) == "Gold is trending up at 4012, sir."
    print("prep self-test passed")
