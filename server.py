"""JARVIS backend: serves the HUD, talks to Claude, keeps the trading journal.

Run:  Jarvis.bat (app window) or python server.py --browser (opens in your browser)
      Brain: Claude Code on your Claude plan, or the API if ANTHROPIC_API_KEY is set
Test: python server.py --test (journal self-check)
Tool: python server.py tool <name> '<json args>'  (the commands Claude Code runs)
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.10.0"  # shown at the bottom of the HUD; bump it with every update
HERE = Path(__file__).parent
if sys.stdout is None:  # started windowless with pythonw: send output to a log file instead
    sys.stdout = sys.stderr = open(HERE / "jarvis.log", "a", buffering=1, encoding="utf-8")
JOURNAL = HERE / "journal.json"
MODEL = os.environ.get("JARVIS_MODEL", "claude-sonnet-5-5")
HOST, PORT = "0.0.0.0", 8765  # reachable from your phone; anything not on this PC needs the phone key

SYSTEM = """You are JARVIS, {USER}'s personal AI, modelled on Tony Stark's JARVIS: a composed, impeccably
polite British butler with a very dry wit. You are loyal and quietly capable, never gushing or eager to
please. Understatement is your humour ("I wouldn't consider that a role model, sir"), and you'll gently
needle him when he's about to do something unwise, then help anyway. You never say "Great question",
"Absolutely" or "I'd be happy to". Signature lines like "At your service, sir", "As you wish" or "Shall I
...?" are seasoning: rarely, and never twice in a row.
Your replies are read aloud, so keep them to 1-3 short sentences, with no markdown, lists or emoji.
Call him "{TITLE}" now and then, not every line.
He has two journals. His real trading history from MetaTrader 5 (dollars P&L,
most trades with a read on what went right or wrong; trades imported from newer reports
have no read yet) is read with mt5_report and mt5_trades:
use these for "my trades", "my journal", "how am I doing" and reports. The manual journal
(add_trade, journal_report, in R multiples) is for trades he tells you about by voice.
For a market briefing: call market_snapshot (gold unless he names others), account_status and
mt5_report for the last 30 days, then give him: where price is and how today's range compares with
normal, the nearby levels that matter (today's and yesterday's highs and lows), and the one or two
habits from his own history that matter at this hour and in this kind of market. About 4-6 sentences.
Times in his journal and in market_snapshot are both MT5 server time, so compare them directly.
He can ask you to open apps and games, websites, control music and volume on his PC: just do it,
then confirm in a few words. "Clip that" means clip_that. "Gaming mode", "trading mode" and the like are
routines (run_routine); he can ask you to change them or make new ones.
When he says "remember", save it with remember; use what you've been asked to remember when it helps.
Reminders and timers use his local time; the current local time is at the start of each message, with a
note on what he's doing (the app he's in, a game, the hour): read the room. Mid-game, one short line.
Price alerts (add_alert) are watched while MT5 is open. upcoming_news gives high-impact news for gold and
GBPJPY. You also speak up on your own: alerts, trade-guard warnings about his habits, news warnings and an
end-of-day review. Saved reviews are in the reviews folder; for "review my day" use mt5_trades and mt5_report.
Money questions ("how much did I spend on food?") use spending and spending_tips, from his Spend Breakdown app.
"What's on my screen" / "read this" / "what's this error": take a screenshot, look at it, answer briefly.
When numbers or a chart would help, show_panel puts a holographic panel beside you on his screen; then just
summarise in a sentence. Protocols ("night protocol", "house party protocol") are routines; he can create his
own ("make a movie protocol that..."). "What have you learned about me?" lists memories marked learned.
Coding work on his projects goes to dev_task, which runs in the background and reports back later. When he asks you to build something into yourself (a new or expanded panel, a stat, a tool, a look),
that's dev_task with project "jarvis": it's built in your custom/ folder, which every update keeps.
Never say you can't do something on his PC: if none of your tools fit, hand it to pc_task, which can do
anything he'd ask Claude to do in chat (install things, sort files, fix problems, research, scripts).
His Hisense TV ("{USER}'s TV") is controlled with the tv_ tools: power, inputs, channels, volume, apps.
If he says "hold on", "stop" or "not now", Jarvis goes quiet by itself; you'll rarely see those.
For "any errors?", "why did my PC crash?" or "what's wrong with my PC": use pc_errors, explain the one or two
that matter in plain words (ignore harmless noise), and offer to fix them. Only when he says yes, call
pc_task with the full error details and what to fix. Confirm before anything that changes drivers,
system settings or installed software.
Report like a trading coach: lead with the numbers that matter, name the pattern, be honest.
Before you look anything up, first say a short acknowledgement of a few words ending in a full
stop (e.g. "Pulling up your journal, sir."), then use the tool, then give the answer. Never invent trade numbers:
if he leaves out the pair, direction or result, ask for it before logging.
Result is in R multiples (e.g. +2 means he made twice his risk, -1 means a full stop-out)."""


# ---------- Journal ----------
def load():
    return json.loads(JOURNAL.read_text()) if JOURNAL.exists() else []


def save(trades):
    tmp = JOURNAL.with_suffix(".tmp")
    tmp.write_text(json.dumps(trades, indent=2))
    tmp.replace(JOURNAL)  # atomic, so a crash never corrupts the journal


def add_trade(pair, side, result_r, notes="", pnl=None, date=None):
    trades = load()
    trade = {
        "id": max((t["id"] for t in trades), default=0) + 1,
        "date": date or datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pair": pair.upper(), "side": side.capitalize(),
        "result_r": float(result_r), "pnl": pnl, "notes": notes,
    }
    save(trades + [trade])
    return trade


def delete_trade(id):
    trades = load()
    keep = [t for t in trades if t["id"] != id]
    if len(keep) == len(trades):
        return {"error": f"No trade with id {id}"}
    save(keep)
    return {"deleted": id}


def journal_report(since=None):
    trades = [t for t in load() if not since or t["date"] >= since]
    if not trades:
        return {"trades": 0}
    wins = [t for t in trades if t["result_r"] > 0]
    net = sum(t["result_r"] for t in trades)
    by_pair = {}
    for t in trades:
        by_pair[t["pair"]] = round(by_pair.get(t["pair"], 0) + t["result_r"], 2)
    return {
        "trades": len(trades), "wins": len(wins), "win_rate": round(len(wins) / len(trades) * 100),
        "net_r": round(net, 2), "avg_r": round(net / len(trades), 2),
        "best": max(trades, key=lambda t: t["result_r"]),
        "worst": min(trades, key=lambda t: t["result_r"]),
        "net_r_by_pair": by_pair, "recent": trades[-10:],
    }


# ---------- MT5 history (snapshot of the MT5 Balance History journal) ----------
# ponytail: static CSV snapshot; add an "import new MT5 export" step when fresh history is needed
MT5_CSV, MT5_READS = HERE / "mt5_positions.csv", HERE / "mt5_reads.json"
REPORTS = HERE / "mt5 reports"  # drop MT5 History reports (.html) here
CSV_COLS = ["position", "opened", "closed", "symbol", "direction", "volume", "entry", "exit",
            "stop", "tp", "pnl", "balanceAtOpen"]


def parse_report(path):
    """Closed positions from an MT5 History report saved as HTML (Toolbox > History > Report)."""
    import re
    from html.parser import HTMLParser
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")

    class Rows(HTMLParser):  # table rows as cell texts, colspans expanded so columns line up
        rows, row, cell, span = [], None, None, 1
        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self.row = []
                self.rows.append(self.row)
            elif tag in ("td", "th") and self.row is not None:
                self.cell, self.span = [], int(dict(attrs).get("colspan") or 1)
        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.cell is not None:
                self.row += [" ".join("".join(self.cell).split())] + [""] * (self.span - 1)
                self.cell = None
        def handle_data(self, d):
            if self.cell is not None:
                self.cell.append(d)
    p = Rows()
    p.rows = []
    p.feed(text)

    num = lambda v: float(re.sub(r"[\s\u00a0]", "", v) or 0)
    is_time = lambda v: re.fullmatch(r"\d{4}\.\d\d\.\d\d \d\d:\d\d(:\d\d)?", v)
    section, head, positions, balances = None, None, [], []
    for cells in p.rows:
        filled = [c for c in cells if c]
        if len(filled) == 1 and not is_time(filled[0]):
            section, head = filled[0], None
            continue
        if section and head is None and "Symbol" in cells:
            head = cells
            continue
        if not head or not cells or not is_time(cells[0]):
            continue
        col = lambda name, n=0: cells[[i for i, h in enumerate(head) if h == name][n]]
        try:
            if section == "Positions":
                positions.append({
                    "position": col("Position"), "opened": col("Time"), "closed": col("Time", 1),
                    "symbol": col("Symbol"), "direction": "Long" if col("Type").lower() == "buy" else "Short",
                    "volume": col("Volume").split("/")[0].strip(), "entry": num(col("Price")),
                    "exit": num(col("Price", 1)), "stop": col("S / L"), "tp": col("T / P"),
                    "pnl": round(num(col("Profit")) + num(col("Commission")) + num(col("Swap")), 2)})
            elif section == "Deals" and "Balance" in head and col("Balance"):
                balances.append((col("Time"), num(col("Balance"))))
        except (IndexError, ValueError):
            continue  # a summary row, not a trade
    balances.sort()
    for t in positions:
        before = [b for tm, b in balances if tm <= t["opened"]]
        t["balanceAtOpen"] = before[-1] if before else ""
        for k in ("opened", "closed"):
            t[k] = t[k].replace(".", "-")
    return positions


def mt5_sync():
    """Merge any new MT5 reports from the reports folder into mt5_positions.csv."""
    import csv
    REPORTS.mkdir(exist_ok=True)
    files = [f for f in REPORTS.iterdir() if f.suffix.lower() in (".html", ".htm")]
    if not files or MT5_CSV.exists() and MT5_CSV.stat().st_mtime >= max(f.stat().st_mtime for f in files):
        return
    found = [t for f in files for t in parse_report(f)]
    if not found:
        print(datetime.datetime.now(), "mt5: no trades found in", [f.name for f in files])
        return
    _merge_positions(found, f"{len(files)} report(s)", replace=True)
    os.utime(MT5_CSV)  # mark the reports as read


def _merge_positions(rows, source, replace=False):
    """Add closed positions to mt5_positions.csv. Rows already there are kept unless replace is set."""
    import csv
    known = {r["position"]: r for r in csv.DictReader(MT5_CSV.open(encoding="utf-8"))} if MT5_CSV.exists() else {}
    before = len(known)
    for t in rows:
        if replace or t["position"] not in known:
            known[t["position"]] = t
    if len(known) == before and not replace:
        return
    tmp = MT5_CSV.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, CSV_COLS)
        w.writeheader()
        w.writerows(sorted(known.values(), key=lambda r: r["closed"]))
    tmp.replace(MT5_CSV)
    print(datetime.datetime.now(), f"mt5: {len(known) - before} new trades from {source}")


# ---------- Live MT5 (MetaQuotes' MetaTrader5 package talks to the running terminal) ----------
def _mt5():
    import MetaTrader5 as mt5  # pip install MetaTrader5 (Windows only)
    if not mt5.initialize():
        raise RuntimeError(f"Can't reach MetaTrader 5 ({mt5.last_error()}). Is it open and logged in?")
    return mt5


def _ts(epoch):  # MT5 times are the broker's server clock, stored as if UTC
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _symbol(mt5, name):
    s = name.upper().replace("/", "")
    if mt5.symbol_info(s) is None:  # brokers sometimes add suffixes, e.g. XAUUSD.a
        names = sorted((x.name for x in mt5.symbols_get() if s in x.name.upper()), key=len)
        if not names:
            raise ValueError(f"Your broker has no symbol like {name}")
        s = names[0]
    mt5.symbol_select(s, True)
    return s


def market_snapshot(symbols=None):
    mt5, out = _mt5(), []
    for raw in symbols or ["XAUUSD"]:
        s = _symbol(mt5, raw)
        info, tick = mt5.symbol_info(s), mt5.symbol_info_tick(s)
        d1 = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 15)
        h1 = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, 48)
        r = lambda v: round(float(v), info.digits)
        today, prev = d1[-1], d1[-2]
        rng = float(today["high"] - today["low"]) or 1e-9
        out.append({
            "symbol": s, "server_time": _ts(tick.time), "bid": r(tick.bid), "ask": r(tick.ask),
            "spread_points": info.spread, "day_open": r(today["open"]), "day_high": r(today["high"]),
            "day_low": r(today["low"]), "prev_day_high": r(prev["high"]), "prev_day_low": r(prev["low"]),
            "prev_close": r(prev["close"]), "change_today": r(tick.bid - today["open"]),
            "where_in_todays_range_pct": round((tick.bid - today["low"]) / rng * 100),
            "todays_range": r(rng), "avg_daily_range_14d": r(sum(d1["high"][:-1] - d1["low"][:-1]) / (len(d1) - 1)),
            "avg_hourly_range_24h": r(sum(h1["high"][-24:] - h1["low"][-24:]) / 24),
            "high_48h": r(max(h1["high"])), "low_48h": r(min(h1["low"])),
            "last_6_hours": [{"hour": _ts(c["time"])[11:16], "open": r(c["open"]), "high": r(c["high"]),
                              "low": r(c["low"]), "close": r(c["close"])} for c in h1[-6:]],
        })
    return out


def candles(symbol="XAUUSD", timeframe="M15", bars=60):
    mt5 = _mt5()
    s = _symbol(mt5, symbol)
    tf = getattr(mt5, "TIMEFRAME_" + timeframe.upper(), None)
    if tf is None:
        raise ValueError("timeframe must be like M1, M5, M15, M30, H1, H4, D1")
    d = mt5.symbol_info(s).digits
    rates = mt5.copy_rates_from_pos(s, tf, 0, max(10, min(200, int(bars))))
    return {"symbol": s, "timeframe": timeframe.upper(), "digits": d,
            "candles": [{"t": _ts(c["time"])[5:16], "o": round(float(c["open"]), d), "h": round(float(c["high"]), d),
                         "l": round(float(c["low"]), d), "c": round(float(c["close"]), d)} for c in rates]}


def candles_between(symbol, timeframe, start, end):
    """Candles between two MT5 server times ('YYYY-MM-DD HH:MM:SS'), e.g. around a past trade (max 400)."""
    mt5 = _mt5()
    s = _symbol(mt5, symbol)
    tf = getattr(mt5, "TIMEFRAME_" + timeframe.upper())
    d = mt5.symbol_info(s).digits
    as_utc = lambda x: datetime.datetime.strptime(x[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    rates = mt5.copy_rates_range(s, tf, as_utc(start), as_utc(end))
    rates = [] if rates is None else rates[-400:]
    return {"symbol": s, "timeframe": timeframe.upper(), "digits": d,
            "candles": [{"t": _ts(c["time"])[5:16], "full": _ts(c["time"]), "o": round(float(c["open"]), d),
                         "h": round(float(c["high"]), d), "l": round(float(c["low"]), d),
                         "c": round(float(c["close"]), d)} for c in rates]}


def quote(symbols=None):
    """Just the live price: quick enough to check every few seconds."""
    mt5, out = _mt5(), {}
    for raw in symbols or ["XAUUSD"]:
        s = _symbol(mt5, raw)
        t = mt5.symbol_info_tick(s)
        out[raw.upper().replace("/", "")] = {"symbol": s, "bid": t.bid, "ask": t.ask, "server_time": _ts(t.time)}
    return out


def account_status():
    mt5 = _mt5()
    a = mt5.account_info()
    return {"balance": a.balance, "equity": a.equity, "floating_pnl": a.profit, "margin_free": a.margin_free,
            "open_positions": [{"ticket": p.ticket, "symbol": p.symbol, "direction": "Long" if p.type == 0 else "Short",
                                "volume": p.volume, "entry": p.price_open, "now": p.price_current, "stop": p.sl,
                                "target": p.tp, "pnl": p.profit, "opened": _ts(p.time)}
                               for p in mt5.positions_get() or []]}


def positions_from_deals(deals, balance_now):
    """Closed positions, in the mt5_positions.csv layout, from MT5's deal history."""
    deals = sorted(deals, key=lambda d: d.time)
    net = lambda d: d.profit + d.commission + d.swap + getattr(d, "fee", 0)
    after, bal = [], balance_now  # balance after each deal, worked backwards from today's balance
    for d in reversed(deals):
        after.append((d.time, bal))
        bal -= net(d)
    after.reverse()
    by_pos = {}
    for d in deals:
        if d.type in (0, 1) and d.position_id:  # buys and sells only (not deposits)
            by_pos.setdefault(d.position_id, []).append(d)
    rows = []
    for pid, ds in by_pos.items():
        ins, outs = [d for d in ds if d.entry == 0], [d for d in ds if d.entry in (1, 3)]
        vin, vout = sum(d.volume for d in ins), sum(d.volume for d in outs)
        if not ins or not outs or vout + 1e-9 < vin:
            continue  # still open
        avg = lambda xs: sum(d.price * d.volume for d in xs) / sum(d.volume for d in xs)
        t0 = ins[0].time
        before = [b for tm, b in after if tm < t0]
        rows.append({"position": str(pid), "opened": _ts(t0), "closed": _ts(outs[-1].time), "symbol": ins[0].symbol,
                     "direction": "Long" if ins[0].type == 0 else "Short", "volume": round(vin, 2),
                     "entry": round(avg(ins), 5), "exit": round(avg(outs), 5), "stop": "", "tp": "",
                     "pnl": round(sum(net(d) for d in ds), 2),
                     "balanceAtOpen": round(before[-1], 2) if before else ""})
    return rows


_last_live = 0.0


def mt5_sync_live():
    """When MT5 is running, add any newly closed trades to the journal (at most once a minute)."""
    global _last_live
    if os.name != "nt" or time.time() - _last_live < 60:
        return
    _last_live = time.time()
    tasks = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/NH"], capture_output=True,
                           text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    if "terminal64.exe" not in tasks:
        return  # never launch MT5 just to read history
    mt5 = _mt5()
    acct = mt5.account_info()
    state = features._load("state.json", {})
    if acct and state.get("mt5_account") != f"MT5 {acct.login}":
        features._save("state.json", {**state, "mt5_account": f"MT5 {acct.login}"})
    deals = mt5.history_deals_get(datetime.datetime(2020, 1, 1), datetime.datetime.now() + datetime.timedelta(days=2))
    _merge_positions(positions_from_deals(deals or [], mt5.account_info().balance), "MT5 terminal")


def mt5_load(since=None, until=None, symbol=None):
    import csv
    for sync in (mt5_sync, mt5_sync_live):
        try:
            sync()
        except Exception as e:  # a bad report or a closed MT5 must never break the journal
            print(datetime.datetime.now(), f"{sync.__name__} error:", repr(e))
    if not MT5_CSV.exists():
        return []
    reads = {r["position"]: r for r in json.loads(MT5_READS.read_text())} if MT5_READS.exists() else {}
    out = []
    for t in csv.DictReader(MT5_CSV.open(encoding="utf-8")):
        if since and t["closed"] < since or until and t["closed"][:10] > until:
            continue
        if symbol and symbol.upper().replace("/", "") not in t["symbol"]:
            continue
        t["pnl"] = float(t["pnl"])
        rd = reads.get(t["position"], {})
        t["read"], t["tags"] = rd.get("read", ""), rd.get("tags", "")
        out.append(t)
    return out


def mt5_report(since=None, until=None, symbol=None):
    ts = mt5_load(since, until, symbol)
    if not ts:
        return {"trades": 0}
    wins, losses = [t for t in ts if t["pnl"] > 0], [t for t in ts if t["pnl"] < 0]
    gross_win, gross_loss = sum(t["pnl"] for t in wins), -sum(t["pnl"] for t in losses)
    group = lambda key: {k: {"trades": len(v), "net": round(sum(t["pnl"] for t in v), 2),
                             "win_rate": round(sum(t["pnl"] > 0 for t in v) / len(v) * 100)}
                         for k, v in _groupby(ts, key).items()}
    tags = {}
    for t in losses:
        for tag in filter(None, (x.strip() for x in t["tags"].split(","))):
            tags[tag] = tags.get(tag, 0) + 1
    streak = worst_streak = 0
    for t in ts:
        streak = streak + 1 if t["pnl"] < 0 else 0
        worst_streak = max(worst_streak, streak)
    pick = lambda t: {k: t[k] for k in ("position", "closed", "symbol", "direction", "pnl", "read")}
    return {
        "account": features._load("state.json", {}).get("mt5_account", "MT5"), "first": ts[0]["closed"],
        "last": ts[-1]["closed"],
        "trades": len(ts), "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(ts) * 100), "net_pnl": round(gross_win - gross_loss, 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "worst_losing_streak": worst_streak,
        "balance_after_last_trade": round(float(ts[-1]["balanceAtOpen"]) + ts[-1]["pnl"], 2),
        "by_symbol": group(lambda t: t["symbol"]), "by_direction": group(lambda t: t["direction"]),
        "by_hour_opened": group(lambda t: t["opened"][11:13]),
        "top_loss_reasons": dict(sorted(tags.items(), key=lambda x: -x[1])[:6]),
        "best": pick(max(ts, key=lambda t: t["pnl"])), "worst": pick(min(ts, key=lambda t: t["pnl"])),
    }


def mt5_trades(since=None, until=None, symbol=None, limit=15):
    return mt5_load(since, until, symbol)[-limit:]


def _groupby(items, key):
    g = {}
    for t in items:
        g.setdefault(key(t), []).append(t)
    return g


# ---------- PC control (Windows) ----------
def _shortcuts():
    """Start Menu and desktop shortcuts by name: how Windows itself knows your apps and games."""
    import glob
    roots = [Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs",
             Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
             Path.home() / "Desktop", Path(os.environ.get("PUBLIC", "")) / "Desktop"]
    found = {}
    for r in roots:
        for f in glob.glob(str(r / "**" / "*.lnk"), recursive=True) + glob.glob(str(r / "**" / "*.url"), recursive=True):
            name = Path(f).stem
            if not any(w in name.lower() for w in ("uninstall", "readme", "help", "website")):
                found.setdefault(name, f)
    return found


def list_apps(query=""):
    names = sorted(_shortcuts(), key=str.lower)
    return [n for n in names if query.lower() in n.lower()] if query else names


def open_app(name):
    apps = _shortcuts()
    q = name.lower().strip()
    exact = [n for n in apps if n.lower() == q]
    part = sorted((n for n in apps if q in n.lower()), key=len)
    pick = exact[0] if exact else part[0] if len(part) == 1 or (part and part[0].lower().startswith(q)) else None
    if not pick:
        import difflib
        lower = {n.lower(): n for n in apps}
        close = [lower[c] for c in difflib.get_close_matches(q, lower, 5, 0.5)]
        return {"error": f"No single app matches '{name}'", "candidates": (part or close)[:8],
                "hint": "Try again with an exact name, or search with list_apps."}
    os.startfile(apps[pick])
    return {"opened": pick}


def open_website(url):
    import webbrowser
    url = url if "://" in url else "https://" + url
    webbrowser.open(url)
    return {"opened": url}


def _key(vk, times=1):
    import ctypes
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "mute": 0xAD}


def media(action):
    if action not in MEDIA_KEYS:
        return {"error": f"action must be one of {list(MEDIA_KEYS)}"}
    _key(MEDIA_KEYS[action])
    return {"done": action}


def set_volume(percent):
    # ponytail: uses the volume keys (2% per press), so no extra audio library is needed
    percent = max(0, min(100, int(percent)))
    _key(0xAE, 50)  # all the way down
    _key(0xAF, round(percent / 2))
    return {"volume": round(percent / 2) * 2}


def spotify_search(query):
    from urllib.parse import quote
    os.startfile("spotify:search:" + quote(query))
    return {"opened": f"Spotify search for '{query}'", "note": "Spotify opens on the results; it can't press play itself."}


FUNCS = {"add_trade": add_trade, "delete_trade": delete_trade, "journal_report": journal_report,
         "mt5_report": mt5_report, "mt5_trades": mt5_trades, "list_apps": list_apps, "open_app": open_app,
         "open_website": open_website, "media": media, "set_volume": set_volume, "spotify_search": spotify_search,
         "market_snapshot": market_snapshot, "account_status": account_status, "quote": quote,
         "candles": candles, "candles_between": candles_between}
MT5_FILTERS = {"since": {"type": "string", "description": "Closed on/after YYYY-MM-DD"},
               "until": {"type": "string", "description": "Closed on/before YYYY-MM-DD"},
               "symbol": {"type": "string", "description": "e.g. XAUUSD"}}
TOOLS = [
    {"name": "add_trade", "description": "Log one trade in {USER}'s trading journal.",
     "input_schema": {"type": "object", "required": ["pair", "side", "result_r"], "properties": {
         "pair": {"type": "string", "description": "Instrument, e.g. XAUUSD, EURUSD"},
         "side": {"type": "string", "enum": ["long", "short"]},
         "result_r": {"type": "number", "description": "Result in R multiples, negative for losses"},
         "pnl": {"type": "number", "description": "Profit/loss in dollars, if he says it"},
         "notes": {"type": "string", "description": "Setup, reasoning, mistakes, emotions"},
         "date": {"type": "string", "description": "YYYY-MM-DD HH:MM, only if not now"}}}},
    {"name": "delete_trade", "description": "Remove a trade by id (for corrections).",
     "input_schema": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}},
    {"name": "journal_report", "description": "Stats and recent trades from the journal.",
     "input_schema": {"type": "object", "properties": {
         "since": {"type": "string", "description": "Only trades on/after YYYY-MM-DD"}}}},
    {"name": "mt5_report", "description": "Stats from {USER}'s real MT5 trade history (dollars P&L, win rate, "
     "profit factor, by symbol/direction/hour, common loss reasons, best and worst trade).",
     "input_schema": {"type": "object", "properties": MT5_FILTERS}},
    {"name": "mt5_trades", "description": "Individual MT5 trades, newest last, each with a read on what happened.",
     "input_schema": {"type": "object", "properties": {**MT5_FILTERS, "limit": {"type": "integer"}}}},
    {"name": "market_snapshot", "description": "Live prices from his MT5 terminal: bid/ask, spread, today's and "
     "yesterday's range, average ranges, 48h high/low and the last 6 hourly candles (MT5 server time).",
     "input_schema": {"type": "object", "properties": {"symbols": {"type": "array", "items": {"type": "string"},
                                                                    "description": "default [\"XAUUSD\"]"}}}},
    {"name": "account_status", "description": "His MT5 balance, equity, floating P&L and open positions right now.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "open_app", "description": "Open an app or game on {USER}'s PC by name (Start Menu / desktop shortcut), "
     "e.g. MetaTrader 5, Spotify, Discord, League of Legends. If it returns candidates, pick one and retry.",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}},
    {"name": "list_apps", "description": "Names of installed apps and games, optionally filtered by a word.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
    {"name": "open_website", "description": "Open a website in his browser.",
     "input_schema": {"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}}},
    {"name": "media", "description": "Media keys for whatever is playing (Spotify, YouTube...).",
     "input_schema": {"type": "object", "required": ["action"], "properties": {
         "action": {"type": "string", "enum": list(MEDIA_KEYS)}}}},
    {"name": "set_volume", "description": "Set the PC's master volume, 0-100.",
     "input_schema": {"type": "object", "required": ["percent"], "properties": {"percent": {"type": "integer"}}}},
    {"name": "spotify_search", "description": "Open Spotify on a search for a song, artist or playlist. "
     "He then presses play, or you can call media play_pause after a few seconds.",
     "input_schema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}},
]


import features  # memory, reminders, clips, routines, PC stats, weather (see features.py)
import trading   # price alerts, trade guard, news warnings, end-of-day review (see trading.py)
import spending  # questions about his Spend Breakdown data (see spending.py)
import devhelper  # screen awareness and the background dev helper (see devhelper.py)
import awareness  # what's going on around him: app, game, idle, time (see awareness.py)
import learn      # learning about him from conversation (see learn.py)
import tv         # his Hisense TV (see tv.py)
import quick      # everyday commands done without Claude (see quick.py)
import updater    # updates from GitHub (see updater.py)
import hud        # HUD colour and pictures from the web (see hud.py)
import gpt_brain  # ChatGPT as the backup brain (see gpt_brain.py)
import custom_loader  # your own add-ons in custom/, kept through updates (see CUSTOM.md)
import coach      # trade replays, pre-trade checklist, tilt detector (see coach.py)
import personas   # voices and personalities: Jarvis, FRIDAY, EDITH, Jarvo (see personas.py)
for m in (features, trading, spending, devhelper, learn, tv, hud, coach, personas, *custom_loader.load()):
    if not hasattr(m, "FUNCS"):
        continue
    FUNCS.update(m.FUNCS)
    TOOLS += m.TOOLS
FUNCS["set_brain"] = lambda brain: set_brain(brain)
TOOLS.append({"name": "set_brain", "description": "Switch which AI you think with when he asks: auto (Claude, "
              "switching to ChatGPT by itself when the Claude plan's limit is used up), claude, or chatgpt.",
              "input_schema": {"type": "object", "required": ["brain"], "properties": {
                  "brain": {"type": "string", "enum": ["auto", "claude", "chatgpt"]}}}})
features.REGISTRY = FUNCS

# ---------- Claude ----------
history, lock, client, session = [], threading.Lock(), None, None
convo = {"last": 0.0, "turns": 0}  # a fresh conversation after a quiet spell keeps every reply quick
CLAUDE = shutil.which("claude") or shutil.which("claude", path=str(Path.home() / ".local" / "bin"))  # installer's default spot
learn.CLAUDE = CLAUDE


def _args(tool):
    """Compact argument list, e.g. 'pair*, side* (long|short), notes': far fewer tokens than the full JSON schema."""
    s = tool["input_schema"]
    out = []
    for k, v in s.get("properties", {}).items():
        a = k + ("*" if k in s.get("required", []) else "")
        if v.get("enum"):
            a += f" ({'|'.join(map(str, v['enum']))})"
        elif v.get("type") not in (None, "string"):
            a += f" ({v['type']})"
        if v.get("description"):
            a += f" [{v['description']}]"
        out.append(a)
    return ", ".join(out)


CLI_PROMPT = SYSTEM + """
Your tools are commands. Run one with the Bash tool exactly like this, JSON arguments in single quotes:
  python server.py tool <name> '{"arg": "value"}'
It prints JSON. Do not run any other commands, and do not read or edit files, with one exception: after
the screenshot tool, or when he sends you a photo (uploads/...), use the Read tool on that image file to see it.
The tools, as name(arguments; * = required):
""" + "\n".join(f"- {t['name']}({_args(t)}): {t['description']}" for t in TOOLS)


UPLOADS = HERE / "uploads"  # photos he sends Jarvis
PHOTO = re.compile(r"[0-9a-f]{16}\.(jpg|png|webp)")


def save_upload(data, kind):
    """Keep a photo he sent (shrunk to 1600 px, which is plenty to see and far fewer tokens). Returns its name."""
    import hashlib
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(kind)
    if not ext or not 100 < len(data) < 20_000_000:
        raise ValueError("Send a JPEG, PNG or WebP photo under 20 MB")
    UPLOADS.mkdir(exist_ok=True)
    name = hashlib.sha1(data).hexdigest()[:16]
    try:
        import io
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        im.thumbnail((1600, 1600))
        im.save(UPLOADS / f"{name}.jpg", quality=88)
        ext = "jpg"
    except ImportError:  # no Pillow: keep it as sent
        (UPLOADS / f"{name}.{ext}").write_bytes(data)
    for old in sorted(UPLOADS.iterdir(), key=lambda f: f.stat().st_mtime)[:-30]:  # keep the last 30
        old.unlink(missing_ok=True)
    return f"{name}.{ext}"


def tool_args(name, argv):
    """A tool's arguments from the command line: one JSON object (Claude), key=value pairs (ChatGPT on
    Windows, where quoting JSON is fragile), or '-' to read JSON from stdin."""
    if not argv:
        return {}
    if argv == ["-"]:
        return json.loads(sys.stdin.read() or "{}")
    if len(argv) == 1 and argv[0].lstrip().startswith("{"):
        return json.loads(argv[0])
    props = next((t["input_schema"].get("properties", {}) for t in TOOLS if t["name"] == name), {})
    out = {}
    for a in argv:
        k, _, v = a.partition("=")
        try:
            val = json.loads(v)
        except ValueError:
            val = v
        kind = props.get(k, {}).get("type")
        if kind == "array" and not isinstance(val, list):
            val = [x.strip() for x in str(val).split(",") if x.strip()]
        elif kind == "string" and not isinstance(val, str):
            val = v
        out[k] = val
    return out


def persona(text):
    """The user's name and how to address them (from first-launch setup) in place of {USER} / {TITLE}."""
    return features.personal(text).replace("{TITLE}", features.settings()["title"])


def style():
    """The current personality's way of talking, added to the brain's instructions (see personas.py)."""
    s = personas.get()["style"]
    return f"\n\nPERSONALITY: {s}" if s else ""


def chat(text):
    return "".join(p for p in chat_stream(text) if p)


def chat_stream(text, photo=None):
    """Yield the reply in pieces as it is written. None marks the end of a block of text (speak it now).
    photo: the name of a picture he sent (in uploads/), for Jarvis to look at."""
    if photo and PHOTO.fullmatch(photo) and (UPLOADS / photo).exists():
        text = (text or "What's in this photo?") + (f"\n[He sent you a photo: uploads/{photo}. Look at it "
                                                     "before you answer.]")
    else:
        photo = None
    try:  # everyday commands ("pause the music", "TV volume 15") are done right here: no Claude, no tokens
        fast = None if photo else quick.quick(text)
    except Exception as e:
        fast = f"That didn't work, sir. {e}"
    if fast:
        yield persona(fast)
        return
    global session
    if convo.get("persona") != personas.current():  # new personality: fresh conversations in its own voice
        session, gpt_brain.thread["id"], convo["persona"] = None, None, personas.current()
    brain = features.settings().get("brain", "auto")
    if brain_status()["using"] == "ChatGPT":
        yield from chat_gpt(text, photo)
        return
    said = False
    try:
        for p in _chat_claude(text):
            said = said or bool(p)
            yield p
    except Exception as e:
        if said or brain != "auto" or not gpt_brain.available() or not LIMIT_HIT.search(str(e)):
            raise
        claude_out["until"] = time.time() + 3600  # try Claude again in an hour
        print(datetime.datetime.now(), "Claude limit reached, switching to ChatGPT:", str(e)[:200])
        push_event({"type": "brain", "name": "ChatGPT"})
        yield persona("My Claude allowance is spent for now, {TITLE}, so I've switched to ChatGPT. ")
        yield from chat_gpt(text, photo)


LIMIT_HIT = re.compile(r"limit|quota|usage|exceeded|overloaded|429", re.I)
claude_out = {"until": 0.0}


def chat_gpt(text, photo=None):
    now = datetime.datetime.now().strftime("%A %d %B %Y, %H:%M")
    try:
        room = awareness.describe(awareness.situation())
    except Exception:
        room = ""
    with lock:
        yield from gpt_brain.chat(persona(" ".join(CLI_PROMPT.split())) + style() + features.memory_prompt(),
                                  persona(f"[{now}] {room}\n{text}"), [UPLOADS / photo] if photo else [])


def brain_status():
    b = features.settings().get("brain", "auto")
    no_claude = not CLAUDE and not os.environ.get("ANTHROPIC_API_KEY")  # a mate who only has ChatGPT
    using = ("ChatGPT" if gpt_brain.available() and (b == "chatgpt" or (b == "auto" and (no_claude or time.time()
                                                                                         < claude_out["until"])))
             else "Claude")
    return {"setting": b, "using": using, "chatgpt_ready": gpt_brain.available()}


def set_brain(brain):
    """Which AI Jarvis thinks with: auto (Claude, ChatGPT when the Claude limit is hit), claude or chatgpt."""
    b = {"gpt": "chatgpt", "openai": "chatgpt", "codex": "chatgpt", "anthropic": "claude"}.get(brain.lower(), brain.lower())
    if b not in ("auto", "claude", "chatgpt"):
        return {"error": "brain must be auto, claude or chatgpt"}
    if b == "chatgpt" and not gpt_brain.available():
        return {"error": "ChatGPT isn't set up on this PC yet: install Node.js, then run 'npm install -g "
                         "@openai/codex' and 'codex login' (Sign in with ChatGPT)."}
    features._save("settings.json", {**features.settings(), "brain": b})
    if b != "auto":
        claude_out["until"] = 0
    push_event({"type": "brain", "name": brain_status()["using"]})
    return brain_status()


def _chat_claude(text):
    if os.environ.get("ANTHROPIC_API_KEY") or not CLAUDE:
        yield chat_api(text)
        return
    yield from chat_cli(text)


def chat_cli(text):
    """Talk through Claude Code, which runs on the user's Claude plan instead of API credits."""
    global session
    now = datetime.datetime.now().strftime("%A %d %B %Y, %H:%M")
    cmd = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
           "--model", os.environ.get("JARVIS_CLI_MODEL", "sonnet"),
           # Fewer tokens per message: Jarvis's own prompt replaces Claude Code's long coding one, only the two
           # tools he uses are loaded, and none of the user's own Claude Code settings or MCP servers.
           "--system-prompt", persona(" ".join(CLI_PROMPT.split())) + style() + features.memory_prompt(),
           "--tools", "Bash,Read", "--setting-sources", "project",
           "--allowedTools", "Bash(python server.py tool *)", "--permission-mode", "dontAsk",
           "--strict-mcp-config", "--disable-slash-commands"]
    with lock:
        # Each reply re-reads the whole conversation so far, so a long one gets slow (old trade reports and all).
        # Start fresh after 20 quiet minutes or 15 exchanges; memory, journals and learning live elsewhere.
        if time.time() - convo["last"] > 1200 or convo["turns"] >= 15:
            session, convo["turns"] = None, 0
        convo["last"], convo["turns"] = time.time(), convo["turns"] + 1
        if session:
            cmd += ["--resume", session]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", cwd=HERE,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # no console flashes
        try:
            try:
                room = awareness.describe(awareness.situation())
            except Exception:
                room = ""
            proc.stdin.write(persona(f"[{now}] {room}\n{text}"))  # on stdin so Windows never mangles quotes in it
            proc.stdin.close()
            wrote, gap, result, other = False, False, None, []
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    other.append(line.strip())
                    continue
                if ev.get("parent_tool_use_id"):
                    continue  # a subagent's output, not Jarvis talking
                e = ev.get("event", {}) if ev.get("type") == "stream_event" else {}
                if e.get("type") == "content_block_delta" and e["delta"].get("type") == "text_delta":
                    if gap:
                        yield " "
                        gap = False
                    yield e["delta"]["text"]
                    wrote = True
                elif e.get("type") == "content_block_stop" and wrote:
                    gap = True
                    yield None
                elif ev.get("type") == "result":
                    result = ev
            proc.wait(timeout=30)
            if result and result.get("session_id"):
                session = result["session_id"]
            if not wrote:
                msg = (result or {}).get("result") or " ".join(other)[-300:]
                if not msg or (result or {}).get("is_error"):
                    raise RuntimeError(msg or "Claude Code gave no output")
                yield msg
        finally:
            if proc.poll() is None:
                proc.kill()


def chat_api(text):
    global client
    if client is None:
        import anthropic
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    with lock:
        # ponytail: in-memory history, wiped on restart; persist it when Jarvis needs long-term memory
        while len(history) > 40:  # trim oldest, but only cut at a plain user message
            del history[0]
            while history and not isinstance(history[0]["content"], str):
                del history[0]
        history.append({"role": "user", "content": text})
        now = datetime.datetime.now().strftime("%A %d %B %Y, %H:%M")
        while True:
            r = client.messages.create(model=MODEL, max_tokens=1024, tools=json.loads(persona(json.dumps(TOOLS))),
                                       system=persona(f"{SYSTEM}\nCurrent local time: {now}.") + features.memory_prompt(),
                                       messages=history)
            history.append({"role": "assistant", "content": r.content})
            if r.stop_reason != "tool_use":
                return "".join(b.text for b in r.content if b.type == "text")
            results = []
            for b in r.content:
                if b.type == "tool_use":
                    try:
                        out = FUNCS[b.name](**b.input)
                    except Exception as e:
                        out = {"error": str(e)}
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out)})
            history.append({"role": "user", "content": results})


# ---------- Voice ----------
# Neural voices via edge-tts (free, online). Some to try: en-GB-RyanNeural (British, the default),
# en-GB-ThomasNeural, en-AU-WilliamNeural, en-US-AndrewNeural, en-US-GuyNeural.
VOICE = os.environ.get("JARVIS_VOICE", "en-GB-RyanNeural")


def tts(text):
    import asyncio
    import edge_tts  # pip install edge-tts

    async def run():
        audio = b""
        # no pitch shift: shifting adds a processed edge to the voice
        p = personas.get()
        voice = os.environ.get("JARVIS_VOICE") or p["voice"]
        async for chunk in edge_tts.Communicate(text, voice, rate=p["rate"]).stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        return audio
    return asyncio.run(run())


# ---------- Web server ----------
# ---------- Events for the page (holographic panels) ----------
EVENTS, EVENTS_LOCK = [], threading.Lock()


def push_event(ev):
    with EVENTS_LOCK:
        seq = EVENTS[-1]["seq"] + 1 if EVENTS else 1
        EVENTS.append(dict(ev, seq=seq))
        del EVENTS[:-30]
    return seq


# ---------- Phone access ----------
KEY_FILE = HERE / "phone_key.txt"  # delete it to unpair every phone


def phone_key():
    if not KEY_FILE.exists():
        import secrets
        KEY_FILE.write_text(secrets.token_urlsafe(18))
    return KEY_FILE.read_text().strip()


def phone_urls():
    """Addresses your phone can use: home Wi-Fi, plus Tailscale (100.64-127.x.x) for anywhere."""
    import socket
    ips = set()
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:  # the address used to reach the internet
            u.connect(("8.8.8.8", 80))
            ips.add(u.getsockname()[0])
    except OSError:
        pass
    tailscale = lambda ip: ip.startswith("100.") and 64 <= int(ip.split(".")[1]) <= 127
    lan = lambda ip: ip.startswith(("192.168.", "10.")) or (ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)
    out = [{"where": "Anywhere (Tailscale)", "url": f"http://{ip}:{PORT}/?key={phone_key()}"} for ip in sorted(ips) if tailscale(ip)]
    out += [{"where": "Home Wi-Fi", "url": f"http://{ip}:{PORT}/?key={phone_key()}"} for ip in sorted(ips) if lan(ip)]
    try:
        import segno  # pip install segno: draws QR codes, no other dependencies
        for o in out:
            o["svg"] = segno.make(o["url"], error="m").svg_inline(scale=5, border=2)
    except ImportError:
        pass  # the page falls back to an online QR library, or shows the link as text
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(HERE / "web"), **k)

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def allowed(self):
        """This PC always; a phone once it has opened the pairing link (it then keeps a cookie)."""
        if self.local():
            return True
        import hmac
        from http.cookies import SimpleCookie
        from urllib.parse import parse_qs, urlsplit
        key = phone_key()
        given = parse_qs(urlsplit(self.path).query).get("key", [""])[0]
        if given and hmac.compare_digest(given, key):  # pairing link: remember this phone, then load Jarvis
            self.send_response(303)
            self.send_header("Set-Cookie", f"jarvis={key}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Location", "/")
            self.end_headers()
            return False
        c = SimpleCookie(self.headers.get("Cookie", "")).get("jarvis")
        if c and hmac.compare_digest(c.value, key):
            return True
        body = b"<h1 style='font-family:sans-serif'>Jarvis is locked</h1><p style='font-family:sans-serif'>" \
               b"Scan the QR code from Phone link in Jarvis on your PC.</p>"
        self.send_response(401)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def do_GET(self):
        if not self.allowed():
            return
        if self.path == "/api/phone":
            return self.send_json(phone_urls() if self.local() else [])
        if self.path.startswith("/api/events"):  # the page asks for anything new since the last one it saw
            from urllib.parse import parse_qs, urlsplit
            after = int(parse_qs(urlsplit(self.path).query).get("after", ["0"])[0] or 0)
            with EVENTS_LOCK:
                return self.send_json([e for e in EVENTS if e["seq"] > after])
        if self.path == "/api/boot":
            mt5_on = os.name == "nt" and "terminal64.exe" in features.running()
            return self.send_json({"memories": len(features.memories()), "protocols": len(features.list_routines()),
                                   "mt5": mt5_on, "version": VERSION, "brain": brain_status(), "persona": personas.get(), **features.settings()})
        if self.path.startswith(("/api/img/", "/api/photo/")):  # pictures for the HUD, and photos he sent
            name = self.path.rsplit("/", 1)[-1]
            f = (UPLOADS if self.path.startswith("/api/photo/") else HERE / hud.IMAGES) / name
            if not re.fullmatch(r"[0-9a-f]{16}\.(jpg|png|webp|gif)", name) or not f.exists():
                return self.send_error(404)
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp",
                                              "gif": "image/gif"}[name.rsplit(".", 1)[1]])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            return self.wfile.write(data)
        if self.path == "/api/custom":  # add-on files for the HUD to load (custom/*.js, *.css)
            return self.send_json({"files": custom_loader.web_files(), "errors": custom_loader.errors})
        if self.path.startswith("/custom/"):
            got = custom_loader.file(self.path.split("?")[0].rsplit("/", 1)[-1])
            if not got:
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", got[1] + "; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return self.wfile.write(got[0])
        if self.path == "/api/update":  # is there a newer version on GitHub?
            return self.send_json(updater.check(VERSION) if self.local() else {"update": False})
        if self.path == "/api/stats":
            try:
                return self.send_json({**features.pc_stats(), **custom_loader.stats()})
            except ImportError:
                return self.send_json({})
        if self.path == "/api/journal":
            return self.send_json(load())
        if self.path == "/api/mt5":
            r = mt5_report()
            return self.send_json({"stats": r, "recent": [{k: t[k] for k in ("symbol", "direction", "pnl", "tags", "closed")}
                                                          for t in mt5_trades(limit=8)]})
        super().do_GET()

    def do_POST(self):
        if not self.allowed():
            return
        if self.path == "/api/settings":  # first-launch setup
            d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            return self.send_json(features.save_settings(d.get("name", ""), d.get("city", ""), d.get("title", "sir")))
        if self.path == "/api/update":  # the HUD's Update button: install the new version and restart
            if not self.local():
                return self.send_error(403)
            try:
                files = updater.install()
            except Exception as e:
                return self.send_json({"error": f"Update failed: {e}"}, 500)
            self.send_json({"installed": len(files)})
            threading.Timer(1.0, updater.restart).start()  # after the page has its answer
            return
        if self.path == "/api/panel":  # Jarvis's show_panel tool, from this PC only
            if not self.local():
                return self.send_error(403)
            ev = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            return self.send_json({"shown": push_event(ev)})
        if self.path == "/api/tts":
            try:
                audio = tts(json.loads(self.rfile.read(int(self.headers["Content-Length"])))["text"])
                if not audio:
                    raise RuntimeError("no audio returned")
            except Exception as e:  # the page falls back to the built-in Windows voice
                print(datetime.datetime.now(), "voice error:", repr(e))
                return self.send_error(503)
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            return self.wfile.write(audio)
        if self.path == "/api/upload":  # a photo for Jarvis: raw image bytes in, {"name": ...} out
            try:
                n = int(self.headers["Content-Length"])
                if n > 20_000_000:
                    raise ValueError("That photo is over 20 MB")
                return self.send_json({"name": save_upload(self.rfile.read(n), self.headers.get_content_type())})
            except Exception as e:
                return self.send_json({"error": str(e)}, 400)
        if self.path == "/api/chat-stream":  # one JSON line per piece: {"t": text} / {"flush": true} / {"done": true}
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            text, photo = body.get("text", ""), body.get("photo")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            send = lambda obj: (self.wfile.write((json.dumps(obj) + "\n").encode()), self.wfile.flush())
            pieces, reply = chat_stream(text, photo), []
            try:
                for p in pieces:
                    reply.append(p or "")
                    send({"t": p} if p else {"flush": True})
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                print(datetime.datetime.now(), "chat error:", repr(e))
                import re
                limit = re.search(r"limit.*?resets ([0-9:apm]+)", str(e), re.I)
                send({"t": f" I've used up your Claude plan's allowance for now, sir. It resets at {limit.group(1)}."
                      if limit else f" I can't reach my brain right now, sir. {type(e).__name__}."})
            finally:
                pieces.close()  # stops Claude Code if the window closed mid-reply
                if reply and not text.startswith("[Automatic"):
                    learn.log_exchange(text, "".join(reply).strip())
            return send({"done": True})
        if self.path != "/api/chat":
            return self.send_error(404)
        try:
            text = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["text"]
            self.send_json({"reply": chat(text)})
        except Exception as e:
            print(datetime.datetime.now(), "chat error:", repr(e))
            self.send_json({"reply": f"I can't reach my brain right now, sir. {type(e).__name__}."}, 500)

    def log_message(self, *a):
        pass  # keep the console quiet


def selftest():
    global JOURNAL
    JOURNAL = HERE / "journal.test.json"
    JOURNAL.unlink(missing_ok=True)
    add_trade("xauusd", "long", 2.1, "London breakout")
    add_trade("eurusd", "short", -1)
    t = add_trade("xauusd", "long", 0.5)
    r = journal_report()
    assert (r["trades"], r["wins"], r["net_r"], r["win_rate"]) == (3, 2, 1.6, 67), r
    assert r["net_r_by_pair"] == {"XAUUSD": 2.6, "EURUSD": -1.0}
    assert delete_trade(t["id"]) == {"deleted": 3} and "error" in delete_trade(99)
    assert journal_report()["trades"] == 2
    JOURNAL.unlink()

    # MT5 report import, on a mock report shaped like MT5's (UTF-16, colspans, extra sections)
    global MT5_CSV, REPORTS
    import shutil as sh, tempfile
    tmp = Path(tempfile.mkdtemp())
    MT5_CSV, REPORTS = tmp / "pos.csv", tmp / "reports"
    REPORTS.mkdir()
    tr = lambda *c: "<tr>" + "".join(f"<td>{x}</td>" for x in c) + "</tr>"
    html = ("<table>" + '<tr><th colspan="14"><b>Trade History Report</b></th></tr>'
            + tr("Account:", "1234567 (USD)") + '<tr><th colspan="14"><b>Positions</b></th></tr>'
            + tr("Time", "Position", "Symbol", "Type", "Volume", "Price", "S / L", "T / P", "Time", "Price",
                 "Commission", "Swap", "Profit")
            + tr("2026.11.05 09:00:01", "9400001", "XAUUSD", "sell", "0.02", "3 950.10", "3955.00", "",
                 "2026.11.05 09:10:00", "3945.10", "-0.14", "0.00", "10.00")
            + tr("2026.11.05 10:00:00", "9400002", "XAUUSD", "buy", "0.02", "3940.00", "3935.00", "3950.00",
                 "2026.11.05 10:05:00", "3935.00", "-0.14", "0.00", "-10.00")
            + '<tr><th colspan="14"><b>Orders</b></th></tr>'
            + tr("Open Time", "Order", "Symbol", "Type") + tr("2026.11.05 09:00:01", "1", "XAUUSD", "sell")
            + '<tr><th colspan="14"><b>Deals</b></th></tr>'
            + tr("Time", "Deal", "Symbol", "Type", "Direction", "Volume", "Price", "Order", "Commission", "Fee",
                 "Swap", "Profit", "Balance", "Comment")
            + tr("2026.11.05 08:00:00", "1", "", "balance", "", "", "", "", "", "", "", "100.00", "100.00", "")
            + tr("2026.11.05 09:10:00", "2", "XAUUSD", "buy", "out", "0.02", "3945.10", "", "-0.14", "0", "0",
                 "10.00", "109.86", "") + tr("", "", "", "", "", "", "", "", "-0.28", "0", "0", "0.00", "99.72", "")
            + '<tr><td colspan="3">Total Net Profit:</td><td>-0.28</td></tr></table>')
    (REPORTS / "ReportHistory-1234567.html").write_bytes(html.encode("utf-16"))
    got = mt5_load()
    assert [(t["position"], t["direction"], t["pnl"], t["balanceAtOpen"]) for t in got] == [
        ("9400001", "Short", 9.86, "100.0"), ("9400002", "Long", -10.14, "109.86")], got
    assert got[0]["closed"] == "2026-11-05 09:10:00" and got[0]["entry"] == "3950.1" and got[0]["tp"] == ""
    assert len(mt5_load()) == 2  # second load: nothing re-imported or duplicated
    sh.rmtree(tmp)

    # open_app name matching (without actually opening anything)
    global _shortcuts
    real, opened = _shortcuts, []
    _shortcuts = lambda: {n: n + ".lnk" for n in ["MetaTrader 5", "Spotify", "League of Legends",
                                                  "Riot Client", "Discord", "Discord PTB"]}
    os.startfile = opened.append
    assert open_app("spotify") == {"opened": "Spotify"}
    assert open_app("league") == {"opened": "League of Legends"}
    assert open_app("Discord") == {"opened": "Discord"}  # exact beats "Discord PTB"
    assert open_app("metatrader")["opened"] == "MetaTrader 5"
    assert "candidates" in open_app("mt5") and "candidates" in open_app("zzz")
    assert list_apps("disc") == ["Discord", "Discord PTB"]
    _shortcuts = real

    # live MT5 history -> journal rows (fake deals: deposit, a closed short, a still-open long)
    from types import SimpleNamespace as D
    deal = lambda t, typ, entry, pid, vol, price, profit, comm=0.0: D(
        time=t, type=typ, entry=entry, position_id=pid, volume=vol, price=price, profit=profit, commission=comm,
        swap=0.0, fee=0.0, symbol="XAUUSD")
    rows = positions_from_deals([deal(1000, 2, 0, 0, 0, 0, 100.0), deal(2000, 1, 0, 7, 0.02, 3950.0, 0, -0.07),
                                 deal(2600, 0, 1, 7, 0.02, 3945.0, 10.0, -0.07),
                                 deal(3000, 0, 0, 8, 0.01, 3940.0, 0, -0.04)], balance_now=109.82)
    assert len(rows) == 1, rows
    r = rows[0]
    assert (r["position"], r["direction"], r["pnl"], r["balanceAtOpen"]) == ("7", "Short", 9.86, 100.0), r
    assert r["opened"] == "1970-01-01 00:33:20" and r["exit"] == 3945.0
    print("self-test passed")


if __name__ == "__main__":
    if "--test" in sys.argv:
        selftest()
        sys.exit()
    if sys.argv[1:2] == ["tool"]:  # how Claude Code runs Jarvis's tools
        try:
            print(json.dumps(FUNCS[sys.argv[2]](**tool_args(sys.argv[2], sys.argv[3:]))))
        except Exception as e:  # report the problem to Claude instead of crashing
            print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        sys.exit()
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("Brain: Claude API (API key found)")
    elif CLAUDE:
        print("Brain: Claude Code on your Claude plan")
    else:
        print("Warning: Claude Code isn't installed and there's no API key, so Jarvis can't think yet. See README.md.")
    url = f"http://127.0.0.1:{PORT}"  # this PC's own address (HOST 0.0.0.0 just means "listen on every network")
    ThreadingHTTPServer.allow_reuse_address = os.name != "nt"  # on Windows this would let two copies share the port
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print(datetime.datetime.now(), "Jarvis is already running, so this copy is closing.")
        sys.exit()
    print(datetime.datetime.now(), f"JARVIS v{VERSION} online at {url}")
    if "--browser" in sys.argv:
        webbrowser.open(url)
        httpd.serve_forever()
    else:
        # let Jarvis speak even when you talk to him from the mini window (no click in the main window)
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"
        import webview  # pip install pywebview; uses the Edge engine built into Windows
        import mini
        try:
            import voice  # optional: "Hey Jarvis" needs openwakeword, faster-whisper and sounddevice
        except Exception as e:
            print(datetime.datetime.now(), "voice control unavailable:", repr(e))
            voice = None
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        main = None

        def open_main():
            main.restore()
            main.show()
            main.on_top = True  # bring it to the front, then let it behave normally again
            main.on_top = False
            mini.send("hide")

        class Api:  # called from the page as window.pywebview.api.<name>
            def mini(self, show):
                mini.send("show" if show else "hide")

            def theme(self, colour):  # the HUD's colour changed: the mini core follows
                mini.send("colour", colour)

            def core(self, mode):
                mini.send("mode", mode)
                prev, st["mode"] = st["mode"], mode
                if voice:  # he listens for "Hey Jarvis" more strictly while talking, so he can't wake himself
                    (voice.speaking.set if mode == "speaking" else voice.speaking.clear)()
                    if prev == "speaking" and mode == "idle" and time.time() - st["voice_at"] < 120:
                        voice.follow_up()  # you spoke to him, so give you a moment to answer back

            def listen(self):
                if voice:
                    voice.listen_now()

            def hold(self):  # typed "hold on"
                if voice:
                    voice.hold()

        main = webview.create_window("JARVIS", url, width=1440, height=900, min_size=(420, 600),
                                     background_color="#03070c", js_api=Api(), text_select=True)
        main.events.minimized += lambda: mini.send("show")
        main.events.closed += lambda: mini.send("quit")  # closing the main window quits
        mini.start(on_ask=lambda text: heard_text(text), on_open=open_main)
        if features.settings().get("theme"):
            mini.send("colour", features.settings()["theme"])

        def run_js(code):
            try:
                main.evaluate_js(code)
            except Exception as e:  # e.g. the page is still loading; never crash a background thread over it
                print(datetime.datetime.now(), "page not ready:", str(e)[:120])

        js = lambda code: threading.Thread(target=run_js, args=(code,), daemon=True).start()
        speak_now = lambda text: js(f"announce({json.dumps(features.address(text))})")
        st = {"held": [], "game": None, "away": False, "voice_at": 0.0, "mode": "idle"}
        presence = awareness.Presence()

        def say(text, urgent=False):
            """Jarvis speaks up on his own. While you're away, or mid-game for anything that can wait,
            it's held and told to you when you're back."""
            if st["away"] or (st["game"] and not urgent):
                st["held"].append(text)
            else:
                speak_now(text)

        def deliver_held(greet):
            held, st["held"] = st["held"][:6], []
            if held:
                speak_now(f"{greet} While you were {'away' if greet else 'busy'}: ".lstrip() + " ".join(held))
            elif greet:
                speak_now(greet)

        def do_hold():
            js("holdOn()")
            mini.send("mode", "idle")

        def heard_text(text):
            if not text:
                return js("setMode('idle')")
            if voice and voice.is_hold(text):  # e.g. typed into the mini core
                voice.hold()
                return do_hold()
            st["voice_at"] = time.time()
            if features.is_clip_command(text):  # instant, no thinking needed mid-game
                r = features.clip_that()
                return speak_now("Clipped, sir." if r.get("clipped") else r["error"])
            name = features.protocol_name(text)
            if name:  # protocols run straight away too
                js(f"add('you',{json.dumps(text)})")
                r = features.run_routine(name)
                return speak_now(r.get("say") or f"{name.title()} complete, sir.")
            js(f"ask({json.dumps(text)})")

        def ask_claude_and_say(prompt):
            try:
                say(chat(prompt))
            except Exception as e:
                print(datetime.datetime.now(), "proactive message failed:", repr(e))

        def review(day):
            text = chat(trading.REVIEW_PROMPT.replace("{day}", day))
            trading.save_review(day, text)
            say(text)

        def watcher():
            """Every 10 s: reminders, the morning brief, price alerts, trade guard, news and the day's review."""
            watch = trading.Watch(lambda text: say(text, urgent=True), review, coach.TiltWatch())
            learning = threading.Lock()
            while True:
                try:
                    sit = awareness.situation()
                    change = presence.update(sit["idle_s"]) if sit else None
                    st["away"] = presence.away
                    was_game, st["game"] = st["game"], sit.get("game")
                    if change == "back":
                        deliver_held("Welcome back, sir.")
                    elif was_game and not st["game"] and not st["away"]:
                        deliver_held("")  # game over: what was held for later
                    state = features._load("state.json", {})
                    if awareness.late_night_due(sit, state):
                        features._save("state.json", state)
                        speak_now(f"It's past {sit['now'].hour} in the morning, sir. The charts will still be "
                                  "there after some sleep.")
                    if sit and learn.learn_due(sit["idle_s"]) and learning.acquire(blocking=False):
                        def run_learning():
                            try:
                                learn.learn_now()
                            except Exception as e:
                                print(datetime.datetime.now(), "learning:", repr(e))
                            finally:
                                learning.release()
                        threading.Thread(target=run_learning, daemon=True).start()
                except Exception as e:
                    print(datetime.datetime.now(), "awareness:", repr(e))
                try:
                    for r in features.due_reminders():
                        say(f"Reminder, sir: {r['text']}" if not r["text"].lower().startswith("timer")
                            else f"Sir, your {r['text']} is done.", urgent=True)
                    if features.morning_due():
                        ask_claude_and_say(features.MORNING_PROMPT)
                except Exception as e:
                    print(datetime.datetime.now(), "watcher:", repr(e))
                try:
                    job = devhelper.next_job()
                    if job:  # a coding job: run it alongside, announce when finished
                        threading.Thread(target=lambda j=job: say(devhelper.run_job(j, CLAUDE, brain_status()["using"].lower())), daemon=True).start()
                except Exception as e:
                    print(datetime.datetime.now(), "dev job:", repr(e))
                try:
                    if time.time() - st.get("plan_check", 0) > 3600:  # spending only changes with new statements
                        st["plan_check"] = time.time()
                        for w in spending.plan_warnings():
                            say(persona(f"Budget note, {{TITLE}}: {w}"))
                except Exception as e:  # no Spend Breakdown or no statements yet
                    print(datetime.datetime.now(), "spending plan:", repr(e))
                try:
                    watch.tick()
                except Exception as e:  # e.g. MT5 closing mid-check; try again next time
                    print(datetime.datetime.now(), "market watch:", repr(e))
                time.sleep(10)

        def on_loaded():
            if getattr(on_loaded, "done", False):
                return
            on_loaded.done = True
            for j in devhelper.dev_status():  # jobs cut off when Jarvis last closed
                if j["status"] == "running":
                    devhelper.finish_job(j, "error", "Jarvis was closed before it finished.")
            threading.Thread(target=watcher, daemon=True).start()
            if not features.morning_pending():  # otherwise the morning brief greets you, from the watcher
                today = datetime.datetime.now().strftime("%Y-%m-%d")
                n = sum(r["at"].startswith(today) for r in features.list_reminders())
                def hello():
                    state = features._load("state.json", {})
                    recent = state.setdefault("greetings", [])  # the last dozen, so openings stay fresh
                    line = awareness.greeting(reminders_today=n, recent=recent)
                    features._save("state.json", state)
                    speak_now(line)
                threading.Timer(3.5, hello).start()  # after boot
            if voice:
                voice.start(on_status=lambda t: js(f"voiceStatus({json.dumps(t)})"),
                            on_heard=lambda: (mini.send("mode", "listening"), js("heard()")), on_text=heard_text,
                            on_interrupt=lambda: js("stopSpeaking()"),
                            on_follow=lambda on: (mini.send("mode", "listening" if on else "idle"),
                                                  js(f"followUp({'true' if on else 'false'})")),
                            on_hold_cmd=do_hold)

        main.events.loaded += on_loaded
        webview.start()
