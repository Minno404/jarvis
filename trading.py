"""Jarvis keeping an eye on the markets for you: price alerts, the trade guard, news warnings and the
end-of-day review. The decisions are plain functions (tested below); `Watch.tick()` feeds them live
data from MT5 every few seconds while MT5 is open.
"""
import datetime
import json
import statistics
from pathlib import Path

import features
from features import _load, _save, _next_id

# Trade guard rules: change these to suit you
SIZE_UP_X = 2.0          # warn when a new trade is this many times your usual size
REVENGE_MIN = 5          # warn when you re-enter within this many minutes of a loss
LOSSES_A_DAY = 3         # warn when you open another trade after this many losses in a day
DAILY_LOSS_PCT = 5.0     # warn once when the day's losses reach this % of the starting balance
NEWS_CURRENCIES = {"USD", "GBP", "JPY"}  # gold and GBPJPY
NEWS_WARN_MIN = 15       # minutes of warning before high-impact news
REVIEW_QUIET_MIN = 90    # end-of-day review once there's been no trading for this long


def _sym(s):
    return s.upper().replace("/", "")


# ---------- Price alerts ----------
def add_alert(symbol, price, note=""):
    symbol = _sym(symbol)
    now = features.REGISTRY["quote"]([symbol])[symbol]["bid"]
    alerts = _load("alerts.json", [])
    a = {"id": _next_id(alerts), "symbol": symbol, "price": float(price),
         "when": "above" if float(price) > now else "below", "note": note}
    _save("alerts.json", alerts + [a])
    return {"set": a, "price_now": now}


def list_alerts():
    return _load("alerts.json", [])


def cancel_alert(id):
    alerts = _load("alerts.json", [])
    keep = [a for a in alerts if a["id"] != id]
    _save("alerts.json", keep)
    return {"cancelled": len(alerts) - len(keep)}


def triggered_alerts(prices):
    """prices: {symbol: bid}. Removes and returns alerts whose level has been reached."""
    alerts = _load("alerts.json", [])
    hit = [a for a in alerts if a["symbol"] in prices and
           (prices[a["symbol"]] >= a["price"] if a["when"] == "above" else prices[a["symbol"]] <= a["price"])]
    if hit:
        _save("alerts.json", [a for a in alerts if a not in hit])
    return hit


# ---------- Trade guard ----------
def _mins(a, b):
    f = "%Y-%m-%d %H:%M:%S"
    return (datetime.datetime.strptime(b, f) - datetime.datetime.strptime(a, f)).total_seconds() / 60


def guard_new_trade(pos, closed_today, usual_volume):
    """Warnings for a trade he has just opened. closed_today: today's closed trades, oldest first."""
    out = []
    if usual_volume and float(pos["volume"]) >= SIZE_UP_X * usual_volume:
        out.append(f"that's {float(pos['volume']) / usual_volume:.0f} times your usual size")
    if closed_today:
        last = closed_today[-1]
        gap = _mins(last["closed"], pos["opened"])
        if last["pnl"] < 0 and 0 <= gap <= REVENGE_MIN:
            out.append(f"you're back in {max(1, round(gap))} minute{'s' if round(gap) > 1 else ''} after a loss")
    losses = sum(t["pnl"] < 0 for t in closed_today)
    if losses >= LOSSES_A_DAY:
        out.append(f"you've already had {losses} losses today")
    return out


def guard_day(closed_today, start_balance, warned):
    """Warnings about the day so far, each at most once a day (warned is the set already given)."""
    out = []
    loss = -sum(t["pnl"] for t in closed_today)
    if start_balance and loss >= start_balance * DAILY_LOSS_PCT / 100 and "daily_loss" not in warned:
        warned.add("daily_loss")
        out.append(f"you're down {loss:.0f} dollars today, {loss / start_balance * 100:.0f} percent of your "
                   "balance. This might be the day to stop")
    streak = 0
    for t in reversed(closed_today):
        if t["pnl"] >= 0:
            break
        streak += 1
    if streak >= 3 and f"streak{streak}" not in warned:
        warned.add(f"streak{streak}")
        out.append(f"that's {streak} losses in a row")
    return out


# ---------- News ----------
NEWS_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"  # the ForexFactory calendar feed


def _calendar():
    cache = _load("news_cache.json", {})
    age = datetime.datetime.now().timestamp() - cache.get("fetched", 0)
    if age > 3 * 3600 or not cache.get("events"):
        try:
            cache = {"fetched": datetime.datetime.now().timestamp(), "events": features._get(NEWS_URL)}
            _save("news_cache.json", cache)
        except Exception as e:
            if not cache.get("events"):
                raise RuntimeError(f"Couldn't load the economic calendar: {e}")
    return cache["events"]


def high_impact(events, now, hours):
    """High-impact events for his currencies from now until `hours` ahead, in his local time."""
    out = []
    for e in events:
        if e.get("impact") != "High" or e.get("country") not in NEWS_CURRENCIES:
            continue
        try:
            t = datetime.datetime.fromisoformat(e["date"]).astimezone().replace(tzinfo=None)
        except (KeyError, ValueError):
            continue
        if now - datetime.timedelta(minutes=1) <= t <= now + datetime.timedelta(hours=hours):
            out.append({"time": t.strftime("%Y-%m-%d %H:%M"), "in_minutes": round((t - now).total_seconds() / 60),
                        "currency": e["country"], "event": e["title"],
                        "forecast": e.get("forecast", ""), "previous": e.get("previous", "")})
    return sorted(out, key=lambda x: x["time"])


def upcoming_news(hours=24):
    return high_impact(_calendar(), datetime.datetime.now(), float(hours))


# ---------- End-of-day review ----------
def review_due(closed_today, open_positions, now_server, done_dates):
    """The day's review is due once he has traded today and then stopped for a while."""
    if not closed_today or open_positions:
        return None
    day = closed_today[-1]["closed"][:10]
    if day in done_dates or _mins(closed_today[-1]["closed"], now_server) < REVIEW_QUIET_MIN:
        return None
    return day


REVIEW_PROMPT = ("[Automatic end-of-day review, not typed by {USER}] Debrief his trading for {day} (MT5 server date): "
                 "call session_debrief with day {day} (it checks every entry against his own rules and finds the "
                 "mistakes that keep recurring, and shows it on his HUD), and mt5_report with since and until set "
                 "to {day} for the numbers. In 4-6 spoken sentences: the day's result, how many entries kept his rules "
                 "and what breaking them cost, the recurring mistake, and the one thing to watch tomorrow.")


def save_review(day, text):
    d = features.HERE / "reviews"
    d.mkdir(exist_ok=True)
    (d / f"{day}.md").write_text(f"# Trading review {day}\n\n{text}\n", encoding="utf-8")


# ---------- The watch loop's single step ----------
class Watch:
    def __init__(self, say, review, tilt=None):
        self.say, self.review = say, review  # review(day) asks Claude for the day's review
        self.tilt = tilt                       # coach.TiltWatch: warns as tilt builds through the day
        self.seen = None                       # tickets of positions already open
        self.warned_day, self.warned = None, set()
        self.news_warned, self.news_retry = set(), 0.0

    def tick(self):
        """Trading off (features): only the price alerts he set himself; no guard, tilt, news or review."""
        R, full = features.REGISTRY, features.feature("trading")
        alerts = list_alerts()
        if not full and not alerts:
            return
        if full:
            self.news()
        if "terminal64.exe" not in features.running():
            return
        if alerts:
            q = R["quote"](sorted({a["symbol"] for a in alerts}))
            for a in triggered_alerts({k: v["bid"] for k, v in q.items()}):
                self.say(f"Sir, {a['symbol']} is {a['when']} {a['price']:g}."
                         + (f" You said: {a['note']}." if a["note"] else ""))
        if not full:
            return
        acct = R["account_status"]()
        server_now = R["quote"](["XAUUSD"])["XAUUSD"]["server_time"]
        today = server_now[:10]
        if self.warned_day != today:
            self.warned_day, self.warned = today, set()
        closed_today = R["mt5_trades"](since=today, limit=200)
        history = R["mt5_trades"](limit=30)
        usual = statistics.median(float(t["volume"]) for t in history) if history else 0
        open_now = {p["ticket"]: p for p in acct["open_positions"]}
        if self.seen is None:
            self.seen = set(open_now)  # don't warn about trades that were open before Jarvis started
        for ticket, p in open_now.items():
            if ticket not in self.seen:
                self.seen.add(ticket)
                w = guard_new_trade(p, closed_today, usual)
                if w:
                    self.say("Careful, sir: " + ", and ".join(w) + ".")
        start = acct["balance"] - sum(t["pnl"] for t in closed_today)
        for w in guard_day(closed_today, start, self.warned):
            self.say("Sir, " + w + ".")
        if self.tilt:
            w = self.tilt.after_trade(closed_today, history, list(open_now.values()), start, server_now)
            if w:
                self.say(w)
        state = _load("state.json", {})
        day = review_due(closed_today, open_now, server_now, state.get("reviewed", []))
        if day:
            state["reviewed"] = (state.get("reviewed", []) + [day])[-30:]
            _save("state.json", state)
            self.review(day)

    def news(self):
        if datetime.datetime.now().timestamp() < self.news_retry:
            return
        try:
            for e in upcoming_news(hours=NEWS_WARN_MIN / 60 + 0.05):
                key = e["time"] + e["event"]
                if key not in self.news_warned and 0 <= e["in_minutes"] <= NEWS_WARN_MIN:
                    self.news_warned.add(key)
                    self.say(f"Heads up, sir: {e['currency']} {e['event']} in {e['in_minutes']} minutes. "
                             "Expect gold to whip around.")
        except Exception as e:
            self.news_retry = datetime.datetime.now().timestamp() + 600  # calendar down: try again in 10 min
            print(datetime.datetime.now(), "news check:", repr(e))


# ---------- Tool list ----------
FUNCS = {f.__name__: f for f in (add_alert, list_alerts, cancel_alert, upcoming_news)}
S = {"type": "string"}
TOOLS = [
    {"name": "add_alert", "description": "Price alert: Jarvis speaks up when the symbol reaches the price "
     "(above or below is worked out from where price is now). MT5 must be open for it to be watched.",
     "input_schema": {"type": "object", "required": ["symbol", "price"], "properties": {
         "symbol": S, "price": {"type": "number"}, "note": S}}},
    {"name": "list_alerts", "description": "His price alerts.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "cancel_alert", "description": "Cancel a price alert by id.",
     "input_schema": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}},
    {"name": "upcoming_news", "description": "High-impact economic news for USD, GBP and JPY (moves gold and "
     "GBPJPY) in the next N hours, in his local time.",
     "input_schema": {"type": "object", "properties": {"hours": {"type": "number"}}}},
]


def selftest():
    import shutil
    import tempfile
    real, features.HERE = features.HERE, Path(tempfile.mkdtemp())
    try:
        features.REGISTRY["quote"] = lambda syms: {s: {"bid": 3950.0} for s in syms}
        assert add_alert("XAU/USD", 3960, "breakout")["set"]["when"] == "above"
        assert add_alert("XAUUSD", 3900)["set"]["when"] == "below"
        assert triggered_alerts({"XAUUSD": 3955}) == []
        hit = triggered_alerts({"XAUUSD": 3961})
        assert [a["note"] for a in hit] == ["breakout"] and len(list_alerts()) == 1
        assert [a["price"] for a in triggered_alerts({"XAUUSD": 3899.5})] == [3900.0] and list_alerts() == []

        t = lambda closed, pnl: {"closed": closed, "pnl": pnl}
        loss = [t("2026-11-05 10:00:00", -20)]
        p = {"volume": "0.04", "opened": "2026-11-05 10:03:00"}
        w = guard_new_trade(p, loss, usual_volume=0.01)
        assert "4 times your usual size" in w[0] and "back in 3 minutes after a loss" in w[1], w
        assert guard_new_trade({"volume": "0.01", "opened": "2026-11-05 10:30:00"}, loss, 0.01) == []
        three = [t(f"2026-11-05 0{h}:00:00", -10) for h in (8, 9)] + loss
        assert "3 losses today" in guard_new_trade({"volume": "0.01", "opened": "2026-11-05 11:00:00"}, three, 0.01)[0]
        warned = set()
        day = guard_day(three, 2000, warned)
        assert any("3 losses in a row" in x for x in day) and not any("percent" in x for x in day)
        assert guard_day(three, 2000, warned) == []  # once a day
        assert "percent" in guard_day(three + [t("2026-11-05 12:00:00", -5)], 100, set())[0]

        now = datetime.datetime(2026, 11, 5, 23, 0)
        tz = now.astimezone().strftime("%z")
        iso = lambda h, m: f"2026-11-05T{h:02d}:{m:02d}:00{tz[:3]}:{tz[3:]}"
        ev = [{"title": "CPI m/m", "country": "USD", "impact": "High", "date": iso(23, 10)},
              {"title": "Retail Sales", "country": "AUD", "impact": "High", "date": iso(23, 10)},
              {"title": "PMI", "country": "USD", "impact": "Medium", "date": iso(23, 10)},
              {"title": "BOE Rate", "country": "GBP", "impact": "High", "date": "2026-11-07T00:00:00+00:00"}]
        soon = high_impact(ev, now, 0.5)
        assert [(e["event"], e["in_minutes"]) for e in soon] == [("CPI m/m", 10)], soon

        closed = [t("2026-11-05 15:00:00", 12)]
        assert review_due(closed, {}, "2026-11-05 16:00:00", []) is None          # only an hour quiet
        assert review_due(closed, {}, "2026-11-05 16:31:00", []) == "2026-11-05"
        assert review_due(closed, {1: {}}, "2026-11-05 18:00:00", []) is None     # a trade is still open
        assert review_due(closed, {}, "2026-11-05 18:00:00", ["2026-11-05"]) is None
        assert review_due([], {}, "2026-11-05 18:00:00", []) is None
        assert all(x["name"] in FUNCS for x in TOOLS)
    finally:
        shutil.rmtree(features.HERE)
        features.HERE = real
    print("trading self-test passed")


if __name__ == "__main__":
    selftest()
