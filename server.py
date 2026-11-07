"""JARVIS backend: serves the HUD, talks to Claude, keeps the trading journal.

Run:  Jarvis.bat (app window) or python server.py --browser (opens in your browser)
      Brain: Claude Code on your Claude plan, or the API if ANTHROPIC_API_KEY is set
Test: python server.py --test (journal self-check)
Tool: python server.py tool <name> '<json args>'  (the commands Claude Code runs)
"""
import urllib.request
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

VERSION = "1.44.0"  # shown at the bottom of the HUD; bump it with every update
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
note on what he's doing (the app he's in, a game, the hour): read the room. Mid-game, one short line. That note is
background: don't mention the time or how late it is unless he asks or it truly matters.
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
    # MetaTrader's initialize() starts the terminal when it isn't running: Jarvis only ever uses an MT5 that's
    # already open, and opens it himself only when asked (open_app)
    if os.name == "nt" and "terminal64.exe" not in features.running():
        raise RuntimeError("MetaTrader 5 isn't open, and Jarvis doesn't open it by himself. If he wants live MT5 "
                           "data, ask whether to open it (open_app 'MetaTrader 5'); his journal still works without it.")
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


MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "mute": 0xAD, "volume_up": 0xAF, "volume_down": 0xAE}


def media(action):
    if action not in MEDIA_KEYS:
        return {"error": f"action must be one of {list(MEDIA_KEYS)}"}
    _key(MEDIA_KEYS[action], 5 if action.startswith("volume") else 1)  # volume: 10% a time
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
import speech     # the voice itself: online neural, or Kokoro on this PC (see speech.py)
import undo       # "undo that": a short history of what Jarvis changed (see undo.py)
import life       # recipes, bills, habits, PC clean-up, game mode, finding files (see life.py)
import dnd        # Jarvis as Dungeon Master: adventures with real dice on the HUD (see dnd.py)
import commands   # "what can you do?": every command as a searchable panel (see commands.py)
import gamecoach  # watches his gameplay: live tips and a review of his mistakes (see gamecoach.py)
import power      # "sleep the PC", and the quiet wake when his phone wakes it (see power.py)
import spendview  # the full-screen spending report: Spend Breakdown inside Jarvis (see spendview.py)
import deepseek  # DeepSeek as a brain: cheap, online, through Claude Code (see deepseek.py)
import local_brain  # the free AI that runs on this PC: Jarvis's third brain (see local_brain.py)
import web        # free web search and page reading (see web.py)
import inventory  # what the desk camera has seen: "where did I leave my phone?" (see inventory.py)
import leftoff    # where I left off: what was open, offered back after a break (see leftoff.py)
import workshop   # the hologram workshop: 3D models from his projects (see workshop.py)
for m in (features, trading, spending, devhelper, learn, tv, hud, coach, personas, undo, life, dnd, commands, gamecoach, power, spendview,
          web, inventory, leftoff, workshop, *custom_loader.load()):
    if not hasattr(m, "FUNCS"):
        continue
    FUNCS.update(m.FUNCS)
    TOOLS += m.TOOLS
FUNCS["set_brain"] = lambda brain: set_brain(brain)


def voice_mute(on=True):
    """Mute: Jarvis ignores the microphone entirely, even "Hey Jarvis" (unmute: the mini core's mic button, the tray,
    or type "unmute")."""
    features._save("settings.json", {**features.settings(), "voice_muted": bool(on)})
    try:
        import voice as voice_mod
        voice_mod.set_muted(bool(on))
    except Exception:
        pass
    try:
        import mini as mini_mod
        mini_mod.send("muted", bool(on))
    except Exception:
        pass
    push_event({"type": "status"})
    return {"muted": bool(on)}


FUNCS["voice_mute"] = voice_mute


# ---- "Finish this": Jarvis looks at the window you were in, drafts the missing part, and types it once you say so ----
FINISH = {}  # the window being finished, and the draft


def finish_capture():
    """Step Jarvis aside, note the window he was using and take a picture of the screen. Returns {photo, app, title}."""
    if os.name != "nt":
        return {"error": "Only on the Windows PC."}
    import ctypes
    import io
    from PIL import ImageGrab
    hide, show = LIVE.get("shot_hide"), LIVE.get("shot_show")
    if hide:
        hide()
        time.sleep(0.6)
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        exe, title, _ = awareness.foreground()
        img = ImageGrab.grab()
    finally:
        if show:
            show()
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=90)
    FINISH.clear()
    FINISH.update(hwnd=hwnd, app=exe.removesuffix(".exe"), title=title)
    return {"photo": save_upload(buf.getvalue(), "image/jpeg"), "app": FINISH["app"], "title": title}


def fill_in(text):
    """Show the draft for "finish this"; nothing is typed until he says "type it" (or presses Type it)."""
    if not FINISH.get("hwnd"):
        return {"error": "Nothing to finish: he needs to say 'finish this' first."}
    FINISH["text"] = str(text)
    features._panel({"type": "panel", "kind": "text", "title": f"Ready to type into {FINISH['title'][:40] or FINISH['app']}",
                     "text": FINISH["text"], "stay": True, "actions": [["Type it", "type it"], ["Scrap it", "don't type it"]]})
    return {"shown": True, "note": "It's on the HUD. Tell him to click where it should go, then say 'type it'. "
                                   "Nothing is sent or submitted."}


def type_it():
    """Type the "finish this" draft into the window it's for, at its cursor. New lines go in as Shift+Enter (so a
    chat box doesn't send early). Never presses Send or Submit."""
    if os.name != "nt" or not FINISH.get("text"):
        return {"error": "No draft to type. Say 'finish this' first."}
    import ctypes
    import ctypes.wintypes as wt
    u = ctypes.windll.user32
    hwnd = FINISH["hwnd"]
    if LIVE.get("shot_hide"):
        LIVE["shot_hide"]()
        time.sleep(0.4)
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)
    me, them = ctypes.windll.kernel32.GetCurrentThreadId(), u.GetWindowThreadProcessId(hwnd, None)
    u.AttachThreadInput(me, them, True)  # lets Windows hand the keyboard to his window
    u.SetForegroundWindow(hwnd)
    u.AttachThreadInput(me, them, False)
    time.sleep(0.4)

    class KI(ctypes.Structure):
        _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KI), ("pad", ctypes.c_byte * 32)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wt.DWORD), ("u", _U)]

    def send(*keys):
        arr = (INPUT * len(keys))(*[INPUT(type=1, ki=KI(wVk=vk, wScan=sc, dwFlags=fl)) for vk, sc, fl in keys])
        u.SendInput(len(keys), arr, ctypes.sizeof(INPUT))

    text = FINISH["text"].replace("\r\n", "\n")
    for ch in text:
        if ch == "\n":  # Shift+Enter
            send((0x10, 0, 0), (0x0D, 0, 0), (0x0D, 0, 2), (0x10, 0, 2))
        else:
            data = ch.encode("utf-16-le")  # (emoji are two units)
            for i in range(0, len(data), 2):
                code = int.from_bytes(data[i:i + 2], "little")
                send((0, code, 4), (0, code, 4 | 2))  # KEYEVENTF_UNICODE, then key up
        time.sleep(0.004)
    n = len(text)
    FINISH.pop("text", None)
    return {"typed": n, "into": FINISH.get("title")}


def drop_draft():
    had = bool(FINISH.pop("text", None))
    return {"dropped": had}


FUNCS["fill_in"], FUNCS["type_it"], FUNCS["drop_draft"] = fill_in, type_it, drop_draft
TOOLS += [{"name": "fill_in", "description": "For 'finish this': show him the text you've drafted to complete the "
           "form, email or message in the screenshot (only the missing part, in his voice). He checks it, then says "
           "'type it' to have it typed at his cursor. Never claims anything was sent.",
           "input_schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}}]
FUNCS["jarvis_power"] = lambda action: jarvis_power(action)
TOOLS.append({"name": "jarvis_power", "description": "Restart yourself (Jarvis) or power yourself down when he asks "
              "('restart yourself', 'power down', 'shut down Jarvis'). This closes Jarvis, not the PC. Say a short "
              "goodbye; it happens a few seconds later.",
              "input_schema": {"type": "object", "required": ["action"], "properties": {
                  "action": {"type": "string", "enum": ["restart", "shutdown"]}}}})
TOOLS.append({"name": "set_brain", "description": "Switch which AI you think with when he asks: auto (Claude, "
              "switching to ChatGPT by itself when the Claude plan's limit is used up), claude, or chatgpt.",
              "input_schema": {"type": "object", "required": ["brain"], "properties": {
                  "brain": {"type": "string", "enum": ["auto", "claude", "chatgpt"]}}}})
FUNCS["quiet_mode"] = lambda on=True: quiet_mode(on)
TOOLS.append({"name": "quiet_mode", "description": "Quiet mode when he asks ('quiet mode', 'hold my messages'): you "
              "hold routine announcements (reviews, briefs, job reports, budget notes) until he turns it off; "
              "reminders, price alerts and trade warnings still come through. Same as what happens during a game.",
              "input_schema": {"type": "object", "properties": {"on": {"type": "boolean"}}}})
for _n in set(undo.FILE_TOOLS) | set(undo.LIVE_TOOLS):  # changes Jarvis makes get an undo step
    if _n in FUNCS:
        FUNCS[_n] = undo.wrap(_n, FUNCS[_n])
features.REGISTRY = FUNCS

# ---------- Claude ----------
history, lock, client, session = [], threading.Lock(), None, None
convo = {"last": 0.0, "turns": 0}  # a fresh conversation after a quiet spell keeps every reply quick
CLAUDE = shutil.which("claude") or shutil.which("claude", path=str(Path.home() / ".local" / "bin"))  # installer's default spot
gamecoach.CLAUDE = CLAUDE
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
It prints JSON. Do not run any other commands and do not edit files. You may use the Read tool to read files
when it helps you answer: your own docs and code here (README.md, CUSTOM.md, *.py, custom/...), the screenshot
image after the screenshot tool, or a photo he sends you (uploads/...). To change or add to anything, including
yourself (new panels, features, fixes), don't do it in chat: hand it to the coder with dev_task (project
"jarvis" for changes to you; it reads CUSTOM.md and builds in custom/, kept through updates) and say it's on it.
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


# ---------- Settings from the HUD: listening mode, push-to-talk key, avatar model ----------
LIVE = {"voice": None}  # the voice module once the desktop app has started it
MODELS = HERE / "custom" / "models"  # your own 3D avatar models (.glb), kept through updates
MODEL_NAME = re.compile(r"[A-Za-z0-9 _.-]{1,80}\.glb")


def apply_prefs():
    s = features.settings()
    import hotkey
    hotkey.set_key(s.get("ptt_key"))
    if LIVE["voice"]:
        LIVE["voice"].set_mode(s.get("listen_mode", "wake"))


def startup_link():
    """The old 'start with Windows' shortcut in the Startup folder (Windows starts those last, after a delay)."""
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Jarvis.lnk"


def autostart_on():
    return bool(features.settings().get("autostart")) or (os.name == "nt" and startup_link().exists())


def set_autostart(on):
    """Start Jarvis as soon as he logs in to Windows: a scheduled task that runs at log-on with no delay, at a
    higher priority than normal startup apps (the Run key if Windows won't allow the task). Made by PowerShell,
    so it lands in the real Windows settings even with the Microsoft Store Python."""
    bat = str(HERE / "Jarvis.bat").replace("'", "''")
    here = str(HERE).replace("'", "''")
    run_key = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"
    old = "Remove-Item -LiteralPath ([Environment]::GetFolderPath('Startup')+'\\Jarvis.lnk') -ErrorAction SilentlyContinue;"
    if on:
        ps = (old + f"$a=New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c start \"\" /min \"' + '{bat}' + '\" --startup') "
              f"-WorkingDirectory '{here}';"
              "$t=New-ScheduledTaskTrigger -AtLogOn -User \"$env:USERDOMAIN\\$env:USERNAME\";"
              "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
              "-ExecutionTimeLimit ([TimeSpan]::Zero) -Priority 4 -StartWhenAvailable;"
              "try{Register-ScheduledTask -TaskName 'Jarvis' -Action $a -Trigger $t -Settings $s -Force "
              f"-ErrorAction Stop | Out-Null; Remove-ItemProperty -Path '{run_key}' -Name Jarvis -ErrorAction SilentlyContinue; 'task'}}"
              f"catch{{Set-ItemProperty -Path '{run_key}' -Name Jarvis -Value ('\"' + '{bat}' + '\" --startup'); 'runkey'}}")
    else:
        ps = (old + "Unregister-ScheduledTask -TaskName 'Jarvis' -Confirm:$false -ErrorAction SilentlyContinue;"
              f"Remove-ItemProperty -Path '{run_key}' -Name Jarvis -ErrorAction SilentlyContinue; 'off'")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError(f"Couldn't change the startup setting: {e}")
    how = (r.stdout or "").strip().splitlines()[-1:] or [""]
    if how[0] not in ("task", "runkey", "off"):
        raise ValueError("Windows didn't let Jarvis change its startup setting. " + (r.stderr or "")[-200:])
    features._save("settings.json", {**features.settings(), "autostart": bool(on), "autostart_how": how[0]})
    return how[0]


def save_prefs(d):
    """Listening mode, push-to-talk key and avatar choices from the HUD's settings."""
    s = features.settings()
    if d.get("listen_mode") in ("wake", "ptt", "both"):
        s["listen_mode"] = d["listen_mode"]
    if "ptt_key" in d:
        import hotkey
        if d["ptt_key"] and d["ptt_key"] not in hotkey.VK:
            raise ValueError("Jarvis can't watch that key; pick another (letters, F-keys, ` or the mouse side buttons)")
        s["ptt_key"] = d["ptt_key"] or ""
    if "avatar" in d:
        if d["avatar"] and not (MODEL_NAME.fullmatch(d["avatar"]) and (MODELS / d["avatar"]).exists()):
            raise ValueError("No such model in custom/models")
        s["avatar"] = d["avatar"] or ""
    if d.get("avatar_style") in ("hologram", "original"):
        s["avatar_style"] = d["avatar_style"]
    if d.get("voice_engine") in ("edge", "kokoro"):
        s["voice_engine"] = d["voice_engine"]
        if d["voice_engine"] == "kokoro":
            speech.install_kokoro()  # first time: installs and downloads in the background
    if "kokoro_voice" in d:
        if d["kokoro_voice"] and d["kokoro_voice"] not in speech.KOKORO_VOICES:
            raise ValueError("Unknown voice")
        s["kokoro_voice"] = d["kokoro_voice"] or ""
    if "panel_alpha" in d:
        s["panel_alpha"] = max(0.05, min(0.9, float(d["panel_alpha"])))
        if LIVE.get("pin_alpha"):
            threading.Timer(0.1, LIVE["pin_alpha"]).start()  # pinned panels fade to match
    for k in ("split_claude_voice", "split_gpt_voice", "local_voice"):
        if k in d:
            if d[k] and d[k] not in speech.SPLIT_VOICES:
                raise ValueError("Unknown voice")
            s[k] = d[k] or ""
            if d[k] in speech.KOKORO_VOICES and not speech.kokoro_ready():
                speech.install_kokoro()  # first time: installs and downloads in the background
    if "autostart" in d:
        set_autostart(bool(d["autostart"]))
        s = features.settings()
    if isinstance(d.get("features"), dict):
        s["features"] = {k: bool(d["features"].get(k, features.feature(k))) for k in features.FEATURES}
    if d.get("local_on") in ("gpu", "ram"):
        s["local_on"] = d["local_on"]  # where the local AI runs (local_brain.model)
        def move():  # let go of where it was loaded, get RAM mode's model ready, and have it read up
            local_brain.unload_all()
            warm_local()
        threading.Thread(target=move, daemon=True).start()
    if d.get("stt_quality") in ("fast", "accurate", "best"):
        s["stt_quality"] = d["stt_quality"]  # takes effect next time Jarvis starts
    for k in ("ambient", "ambient_music", "bootup", "close_to_tray"):
        if k in d:
            s[k] = bool(d[k])
    if "text_size" in d:
        s["text_size"] = max(0.7, min(1.3, float(d["text_size"])))
    if "voice_speed" in d:
        s["voice_speed"] = max(0.7, min(1.4, float(d["voice_speed"])))
    if "voice_volume" in d:
        s["voice_volume"] = max(0.0, min(1.5, float(d["voice_volume"])))
    features._save("settings.json", s)
    if isinstance(d.get("background"), dict):  # from Settings: a style, the last photo, or how dark a picture is
        b = {k: v for k, v in d["background"].items() if k in ("style", "photo", "dim")}
        r = FUNCS["hud_background"](**b)
        if r.get("error"):
            raise ValueError(r["error"])
        s = features.settings()
    apply_prefs()
    push_event({"type": "prefs", **{k: s.get(k) for k in ("listen_mode", "ptt_key", "avatar", "avatar_style",
                                                            "voice_engine", "kokoro_voice", "voice_speed", "voice_volume",
                                                            "panel_alpha", "text_size", "ambient", "ambient_music", "bootup", "close_to_tray", "features", "stt_quality",
                                                            "local_voice", "local_on", "split_claude_voice",
                                                            "split_gpt_voice")}, "autostart": autostart_on()})
    return {**s, "voice": speech.status, "autostart": autostart_on()}


def models():
    return sorted(f.name for f in MODELS.glob("*.glb")) if MODELS.is_dir() else []


BLEND_MAGIC = (b"BLENDER", b"\x1f\x8b", b"\x28\xb5\x2f\xfd")  # plain, gzip- or zstd-compressed .blend
BLEND_EXPORT = """import bpy, os, sys
out = sys.argv[sys.argv.index("--") + 1]
try:  # textures saved with paths from the creator's PC: look for them beside the .blend instead
    bpy.ops.file.find_missing_files(directory=os.path.dirname(bpy.data.filepath))
except Exception as e:
    print("find_missing_files:", e)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_apply=True, export_animations=True)
"""


def find_blender():
    """Blender's program, if it's installed: on the PATH, the usual install folders, or Steam's."""
    import glob
    found = shutil.which("blender")
    if found:
        return found
    roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""),
             os.environ.get("LOCALAPPDATA", "")]
    pats = [os.path.join(r, "Blender Foundation", "Blender*", "blender.exe") for r in roots if r]
    pats += [os.path.join(r, "Steam", "steamapps", "common", "Blender", "blender.exe") for r in roots if r]
    hits = sorted((h for p in pats for h in glob.glob(p)), reverse=True)  # newest version first
    return hits[0] if hits else None


def blend_to_glb(src, dest):
    """Convert a .blend to .glb with Blender itself (in the background, no window). Raises with the reason."""
    blender = find_blender()
    if not blender:
        raise ValueError("A .blend file needs Blender installed to convert it (free from blender.org). "
                         "Or open it in Blender and use File → Export → glTF 2.0, format .glb.")
    script = MODELS / "_export.py"
    script.write_text(BLEND_EXPORT)
    TASKS["model"] = {"label": f"Converting {Path(src).name} with Blender", "progress": None}
    try:
        r = subprocess.run([blender, "-b", str(src), "--python", str(script), "--", str(dest)], capture_output=True,
                           text=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise ValueError("Blender took too long converting that model (over 5 minutes).")
    finally:
        script.unlink(missing_ok=True)
        TASKS.pop("model", None)
    if not dest.exists() or dest.read_bytes()[:4] != b"glTF":
        err = [l for l in (r.stdout + r.stderr).splitlines() if "Error" in l or "error" in l][-1:]
        raise ValueError("Blender couldn't convert that file" + (f": {err[0].strip()}" if err else "."))


def unzip_model(name, data):
    """A zipped model (a .blend with its textures, or a .glb): unpacked into custom/models/blend/<name>/.
    Returns the model file inside it."""
    import io
    import zipfile
    folder = MODELS / "blend" / re.sub(r"[^A-Za-z0-9 _.-]", "_", name[:-4])
    z = zipfile.ZipFile(io.BytesIO(data))
    if sum(i.file_size for i in z.infolist()) > 600_000_000:
        raise ValueError("That zip unpacks to over 600 MB")
    for i in z.infolist():
        rel = Path(i.filename)
        if i.is_dir() or rel.is_absolute() or ".." in rel.parts:
            continue
        out = folder / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(z.read(i))
    found = sorted(folder.rglob("*.blend")) or sorted(folder.rglob("*.glb"))
    if not found:
        raise ValueError("No .blend or .glb model inside that zip")
    return found[0]


def save_model(name, data):
    """A 3D model for the core: a .glb as is, a .blend converted to .glb with Blender, or a zip of either
    (a .blend with its texture images beside it)."""
    name = Path(name).name
    MODELS.mkdir(parents=True, exist_ok=True)
    if name.lower().endswith(".zip") and data[:2] == b"PK":
        inner = unzip_model(name, data)
        glb = re.sub(r"[^A-Za-z0-9 _.-]", "_", inner.stem)[:70] + ".glb"
        if inner.suffix.lower() == ".glb":
            (MODELS / glb).write_bytes(inner.read_bytes())
        else:
            blend_to_glb(inner, MODELS / glb)
        return glb
    if name.lower().endswith(".blend") and data.startswith(BLEND_MAGIC):
        glb = name[:-6] + ".glb"
        if not MODEL_NAME.fullmatch(glb):
            raise ValueError("Rename the file using letters, numbers, spaces, - or _")
        src = MODELS / "blend" / name  # the original is kept beside the converted model
        src.parent.mkdir(exist_ok=True)
        src.write_bytes(data)
        blend_to_glb(src, MODELS / glb)
        return glb
    if not MODEL_NAME.fullmatch(name) or data[:4] != b"glTF":
        raise ValueError("Send a .glb, .blend or .zip 3D model")
    (MODELS / name).write_bytes(data)
    return name


def boot_up(held=None):
    """The Iron Man boot-up: a cinematic systems check on the HUD, then 'Welcome home' with the time, weather and
    today's reminders (and anything held while he was away)."""
    now = datetime.datetime.now()
    st = features.pc_stats()
    try:
        w = WEATHER_CACHE["w"] if time.time() - WEATHER_CACHE["at"] < 1200 else features.weather()
    except Exception:
        w = None
    today = now.strftime("%Y-%m-%d")
    rem = [r for r in features.list_reminders() if r["at"].startswith(today)]
    lines = ["Arc reactor · online", f"CPU {st['cpu_percent']:.0f}% · memory {st['ram_percent']:.0f}%"]
    if st.get("gpu_temp_c") is not None:
        lines.append(f"GPU {st['gpu_percent']:.0f}% · {st['gpu_temp_c']:.0f}°C")
    lines += [f"Neural link · {brain_status()['using']}", "Voice systems · online"]
    if w and not w.get("error"):
        lines.append(f"Atmosphere · {round(w['now_c'])}°, {w['sky_now']}")
    lines += [f"Reminders today · {len(rem)}", "All systems nominal"]
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"
    say = f"Welcome home, {{TITLE}}. Good {part}. It's {now.hour % 12 or 12}:{now:%M}"
    if w and not w.get("error"):
        say += f", {round(w['now_c'])} degrees and {w['sky_now']} outside"
    say += "." + (f" You have {len(rem)} reminder{'s' if len(rem) != 1 else ''} today." if rem else "")
    if held:
        say += " While you were away: " + " ".join(held[:6])
    features._panel({"type": "bootup", "lines": lines, "say": persona(features.address(say))})
    return {"booting": True}


WEATHER_CACHE = {"at": 0, "w": None}


def ambient():
    """What the HUD's ambient light follows: the sky outside, day or night, and how soon the next timer ends."""
    if time.time() - WEATHER_CACHE["at"] > 1200:
        WEATHER_CACHE["at"] = time.time()
        try:
            WEATHER_CACHE["w"] = features.weather()
        except Exception:
            WEATHER_CACHE["w"] = None
    w, now = WEATHER_CACHE["w"] or {}, datetime.datetime.now()
    soon = [(datetime.datetime.strptime(r["at"][:16], "%Y-%m-%d %H:%M") - now).total_seconds()
            for r in features.list_reminders() if r["text"].lower().startswith("timer")]
    return {"sky": w.get("sky_now", ""), "temp": w.get("now_c"), "hour": now.hour + now.minute / 60,
            "timer_s": min((x for x in soon if x > -5), default=None)}


FUNCS["boot_up"] = lambda: boot_up()
TOOLS.append({"name": "boot_up", "description": "Run the Iron Man boot-up sequence on his HUD ('boot up', 'wake up "
              "Jarvis', 'run the boot sequence'). It speaks its own welcome, so just say nothing or a word.",
              "input_schema": {"type": "object", "properties": {}}})


def jarvis_power(action):
    """Restart Jarvis or close him: 'restart' or 'shutdown'. Runs in the main Jarvis, after he's said goodbye."""
    if action not in ("restart", "shutdown"):
        return {"error": "action is restart or shutdown"}
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/power", data=json.dumps({"action": action}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def take_over(url):
    """Launched while a Jarvis is already running. If it has its window open, bring that to the front and
    let this copy close (returns False). If it has no window (left running in the background, or an older
    version), ask it to shut down and wait for the port (returns True: this copy carries on starting)."""
    import urllib.request

    def call(path, data=None):
        req = urllib.request.Request(url + path, data=None if data is None else json.dumps(data).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read() or b"{}")
    try:
        if call("/api/alive").get("window"):
            call("/api/show", {})
            return False
    except Exception:
        pass  # no /api/alive (an older version) or no answer: replace it
    try:
        call("/api/power", {"action": "shutdown", "now": True})
    except Exception:
        pass
    import socket
    for _ in range(40):  # up to ~12 s for it to let go of the port
        time.sleep(0.3)
        with socket.socket() as sk:
            if sk.connect_ex(("127.0.0.1", PORT)):
                return True
    return False


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


SCREEN_Q = re.compile(r"\b(?:on|at|of) (?:my|the) (?:screen|monitor|display)\b|\bmy screen\b|\bthis (?:error|popup|pop-up|"
                      r"message|window|warning)\b|\bwhat am i looking at\b|\bexplain (?:this|what'?s (?:up|on))\b|"
                      r"\bwhat (?:does|is) (?:this|that) (?:mean|say)\b|\bread (?:this|my screen)\b", re.I)


def screen_photo():
    """A screenshot saved like a photo he sent, for the brain to look at. Jarvis's own window steps aside for it."""
    try:
        from PIL import ImageGrab
        hide, show = LIVE.get("shot_hide"), LIVE.get("shot_show")
        mine = hide and awareness.foreground()[1].strip().upper() == "JARVIS"
        if mine:
            hide()
            time.sleep(0.5)
        try:
            img = ImageGrab.grab(all_screens=True)
        finally:
            if mine:
                show()
        img.thumbnail((2400, 2400))
        UPLOADS.mkdir(exist_ok=True)
        name = os.urandom(8).hex() + ".png"
        img.save(UPLOADS / name)
        return name
    except Exception as e:
        print(datetime.datetime.now(), "screen look:", repr(e))
        return None


def chat_stream(text, photo=None):
    """Yield the reply in pieces as it is written. None marks the end of a block of text (speak it now).
    photo: the name of a picture he sent (in uploads/), for Jarvis to look at."""
    spoken = LIVE.get("spoken")
    spoken = bool(spoken and spoken[0] == text and time.time() - spoken[1] < 60)
    shot = not photo and SCREEN_Q.search(text or "") and screen_photo()  # "what's this error?": look first
    if shot:
        text, photo = text + (f"\n[A screenshot of his screen right now: uploads/{shot}. Look at it, then explain "
                              "what's on it in plain English: what it means and what to do.]"), None
        if brain_status()["using"] == "ChatGPT":
            photo = shot  # ChatGPT gets it attached
    elif photo and PHOTO.fullmatch(photo) and (UPLOADS / photo).exists():
        text = (text or "What's in this photo?") + (f"\n[He sent you a photo: uploads/{photo}. Look at it "
                                                     "before you answer.]")
    else:
        photo = None
    try:  # everyday commands ("pause the music", "TV volume 15") are done right here: no Claude, no tokens
        fast = None if photo or shot else quick.quick(text)
    except Exception as e:
        fast = f"That didn't work, sir. {e}"
    if fast:
        yield persona(fast)
        return
    if spoken:
        text += ("\n[He said this out loud; speech-to-text can mishear words. If it doesn't quite make sense, or could "
                 "mean something else, ask a short yes/no question to check before doing anything that changes "
                 "something (opening or closing apps, the TV, deleting, sending, buying, trades).]")
    global session
    if convo.get("persona") != personas.current():  # new personality: fresh conversations in its own voice
        session, gpt_brain.thread["id"], convo["persona"] = None, None, personas.current()
    brain = features.settings().get("brain", "auto")
    using = brain_status()["using"]
    said = False
    try:
        for p in brain_reply(using, text, photo):
            said = said or bool(p)
            yield p
    except Exception as e:
        if said or brain != "auto" or not LIMIT_HIT.search(str(e)):
            raise
        OUT[using]["until"] = time.time() + 3600  # try it again in an hour
        nxt = brain_status()["using"]
        if nxt == using:
            raise
        print(datetime.datetime.now(), f"{using} limit reached, switching to {nxt}:", str(e)[:200])
        push_event({"type": "brain", "name": nxt})
        yield from brain_reply(nxt, text, photo)


def brain_reply(using, text, photo=None):
    if using == "Local":
        return chat_local(text, photo)
    if using == "ChatGPT":
        return chat_gpt(text, photo)
    if using == "DeepSeek":
        return chat_cli(text, ds=True)
    return _chat_claude(text)


DEBATE = ("[Split mode, not a normal reply: {{USER}} triple-clicked you into two avatars to weigh something up. You are "
          "the {me} half and argue ONLY the {side}; the {other_ai} half is arguing the {other_side}. Give the 3-5 "
          "strongest, most specific {side}, best first, as plain spoken sentences (no lists, markdown or headings), "
          "under 130 words, then one sentence on when the {side} should win. Use your tools if real facts would help "
          "(prices, his journal, the web). The question: {q}]")


def debate_stream(q):
    """Split mode: Claude argues the pros, then ChatGPT the cons. Yields (side, piece); a piece of None marks
    the end of a block (speak it now), and "" ends that side."""
    for side, me, stance, other_ai, other in (("claude", "Claude", "pros", "ChatGPT", "cons"),
                                              ("gpt", "ChatGPT", "cons", "Claude", "pros")):
        prompt = persona(DEBATE.format(me=me, side=stance, other_ai=other_ai, other_side=other, q=q))
        try:
            if side == "gpt" and not gpt_brain.available():
                raise RuntimeError("ChatGPT isn't set up on this PC (Settings: the ChatGPT backup)")
            run = chat_gpt(prompt) if side == "gpt" else _chat_claude(prompt)
            for p in run:
                yield side, p
        except Exception as e:
            print(datetime.datetime.now(), f"debate ({me}):", repr(e))
            yield side, f"{me} couldn't give the {stance}: {str(e)[:140]}"
        yield side, ""


WAKER = power.Waker()  # quiet wake: the phone woke the PC (see power.py)
YES = re.compile(r"^\W*(?:yes|yeah|yep|yup|ya|correct|right|that'?s right|that'?s it|exactly|do it|go ahead|affirmative|"
                 r"sure|please|yes please)\b", re.I)
NO = re.compile(r"^\W*(?:no|nope|nah|wrong|that'?s wrong|not quite|cancel|never ?mind)\b", re.I)

LIMIT_HIT = re.compile(r"limit|quota|usage|exceeded|overloaded|429|402|insufficient balance", re.I)
claude_out = {"until": 0.0}


def chat_gpt(text, photo=None, local=False):
    now = datetime.datetime.now().strftime("%A %d %B %Y, %H:%M")
    try:
        room = awareness.describe(awareness.situation())
    except Exception:
        room = ""
    with lock:
        yield from gpt_brain.chat(persona(" ".join(CLI_PROMPT.split())) + style() + features.memory_prompt() + features.feature_prompt(),
                                  persona(f"[{now}] {room}\n{text}"), [UPLOADS / photo] if photo else [], local=local)


def quiet_mode(on=True):
    """Hold routine announcements until he turns it off (urgent ones still come through)."""
    features._save("settings.json", {**features.settings(), "quiet": bool(on)})
    try:
        push_event({"type": "status"})
    except Exception:
        pass
    return {"quiet": bool(on)}


TASKS = {}  # things in progress for the Activity panel: name -> {"label", "progress"}


def activity():
    """What Jarvis is busy with, for the Activity panel: jobs, downloads, reminders, held messages."""
    st = LIVE.get("st") or {}
    now = datetime.datetime.now()
    jobs = []
    for j in reversed(devhelper.dev_status()):
        done = j.get("finished")
        if j["status"] in ("queued", "running") or (done and (now - datetime.datetime.strptime(done, "%Y-%m-%d %H:%M"))
                                                    .total_seconds() < 3600):
            jobs.append({"what": j["request"][:90], "project": j.get("project"), "status": j["status"],
                         "since": j.get("finished") or j.get("asked")})
    if local_brain.progress["running"]:
        TASKS["local_ai"] = {"label": "Local AI: " + local_brain.progress["step"], "progress": local_brain.progress["pct"]}
    downloads = [dict(v, name=k) for k, v in TASKS.items()]
    if speech.status["kokoro"] in ("installing", "downloading"):
        downloads.append({"name": "kokoro", "label": "Kokoro voice: " + speech.status["kokoro"],
                          "progress": speech.status.get("progress")})
    rem = [{"text": r["text"], "at": r["at"]} for r in features.list_reminders()[:4]]
    return {"quiet": bool(features.settings().get("quiet")), "game": st.get("game"), "away": bool(st.get("away")),
            "held": list(st.get("held", []))[:6], "jobs": jobs[:5], "downloads": downloads, "reminders": rem,
            "brain": brain_status()["using"]}


def brain_status():
    """Which brain answers now. auto: Claude, then ChatGPT when Claude's limit is hit, then DeepSeek, then the
    local AI (whichever of them this PC has)."""
    b = features.settings().get("brain", "auto")
    gpt, local, ds, now = gpt_brain.available(), local_brain.ready(), deepseek.available(), time.time()
    have = {"Claude": bool(CLAUDE or os.environ.get("ANTHROPIC_API_KEY")), "ChatGPT": gpt, "DeepSeek": ds,
            "Local": local}
    chosen = {"claude": "Claude", "chatgpt": "ChatGPT", "deepseek": "DeepSeek", "local": "Local"}.get(b)
    if chosen and (have[chosen] or chosen == "Claude"):
        using = chosen
    else:  # auto: the first one set up whose limit hasn't been hit, else the first one set up
        fresh = [n for n in have if have[n] and now >= OUT[n]["until"]]
        using = (fresh or [n for n in have if have[n]] or ["Claude"])[0]
    return {"setting": b, "using": using, "chatgpt_ready": gpt, "local_ready": local, "deepseek_ready": ds}


gpt_out = {"until": 0.0}  # ChatGPT's limit was hit: the next brain fills in for an hour
ds_out = {"until": 0.0}   # DeepSeek's credit ran out
OUT = {"Claude": claude_out, "ChatGPT": gpt_out, "DeepSeek": ds_out, "Local": {"until": 0.0}}


def set_brain(brain):
    """Which AI Jarvis thinks with: auto (Claude, ChatGPT when the Claude limit is hit), claude or chatgpt."""
    b = {"gpt": "chatgpt", "openai": "chatgpt", "codex": "chatgpt", "anthropic": "claude", "ollama": "local",
         "offline": "local", "deep seek": "deepseek"}.get(brain.lower(), brain.lower())
    if b not in ("auto", "claude", "chatgpt", "deepseek", "local"):
        return {"error": "brain must be auto, claude, chatgpt, deepseek or local"}
    if b == "deepseek" and not deepseek.available():
        return {"error": "DeepSeek isn't set up yet: paste your API key in Settings > Brain."}
    if b == "local" and not local_brain.ready():
        return {"error": "The local AI isn't set up yet: Settings > Local AI > Install."}
    if b == "chatgpt" and not gpt_brain.available():
        return {"error": "ChatGPT isn't set up on this PC yet: install Node.js, then run 'npm install -g "
                         "@openai/codex' and 'codex login' (Sign in with ChatGPT)."}
    features._save("settings.json", {**features.settings(), "brain": b})
    if b == "local":
        threading.Thread(target=warm_local, daemon=True).start()
    if b != "auto":
        claude_out["until"] = 0
    push_event({"type": "brain", "name": brain_status()["using"]})
    return brain_status()


def _chat_claude(text):
    if os.environ.get("ANTHROPIC_API_KEY") or not CLAUDE:
        yield chat_api(text)
        return
    yield from chat_cli(text)


def chat_cli(text, ds=False):
    """Talk through Claude Code, which runs on the user's Claude plan instead of API credits. ds: on DeepSeek's
    servers instead (deepseek.py)."""
    global session
    now = datetime.datetime.now().strftime("%A %d %B %Y, %H:%M")
    cmd = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
           "--model", os.environ.get("JARVIS_CLI_MODEL", "sonnet"),
           # Fewer tokens per message: Jarvis's own prompt replaces Claude Code's long coding one, only the two
           # tools he uses are loaded, and none of the user's own Claude Code settings or MCP servers.
           "--system-prompt", persona(" ".join(CLI_PROMPT.split())) + style() + features.memory_prompt() + features.feature_prompt(),
           "--tools", "Bash,Read", "--setting-sources", "project",
           "--allowedTools", "Bash(python server.py tool *)", "--permission-mode", "dontAsk",
           "--strict-mcp-config", "--disable-slash-commands"]
    with lock:
        # Each reply re-reads the whole conversation so far, so a long one gets slow (old trade reports and all).
        # Start fresh after 20 quiet minutes or 15 exchanges; memory, journals and learning live elsewhere.
        if time.time() - convo["last"] > 1200 or convo["turns"] >= 15 or convo.get("ds", False) != ds:
            session, convo["turns"] = None, 0  # (and a fresh one when switching between Claude and DeepSeek)
        convo["last"], convo["turns"], convo["ds"] = time.time(), convo["turns"] + 1, ds
        if session:
            cmd += ["--resume", session]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", cwd=HERE, env=deepseek.env() if ds else None,
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


local_convo = {"history": [], "last": 0.0}
LOCAL_TOOL = {"type": "function", "function": {
    "name": "tool", "description": "Use one of your tools from the list in your instructions.",
    "parameters": {"type": "object", "required": ["name"], "properties": {
        "name": {"type": "string", "description": "the tool's name, e.g. web_search"},
        "args": {"type": "object", "description": "its arguments, e.g. {\"query\": \"cat photo\"}"}}}}}


def local_system():
    """The local AI's instructions: Jarvis's own, with the tools listed by name and arguments only. A local model
    reads every word before it answers (slow on a processor), so this is about a third of what Claude gets."""
    tools = "; ".join(f"{t['name']}({', '.join(t['input_schema'].get('properties', {}))})" for t in TOOLS)
    return (persona(f"{SYSTEM}\nYour tools (call the `tool` function with name and args): {tools}.\n") + style()
            + features.memory_prompt() + features.feature_prompt()
            + "\nYou are running on this PC as the local brain. You can't read files or see pictures. Be brief.")


def local_body(messages, **extra):
    import local_brain
    ram = features.settings().get("local_on") == "ram"
    return {"model": local_brain.model(), "messages": [{"role": "system", "content": local_system()}] + messages,
            "tools": [LOCAL_TOOL], "think": False, "keep_alive": "30m",
            # on the processor a smaller memory window is quicker (and Jarvis's chats are short)
            **({"options": {"num_ctx": 8192}} if ram else {}), **extra}


def warm_local():
    """Load the local AI and have it read its instructions now, so the first real question is answered quickly
    (Ollama keeps what it has read and reuses it)."""
    import local_brain
    try:
        if local_brain.ready() and local_brain.ensure_running():
            if features.settings().get("local_on") == "ram":
                local_brain.prepare_ram()  # RAM mode's small model (downloads once, in the background)
            body = local_body([{"role": "user", "content": "Ready?"}], stream=False)
            body.setdefault("options", {})["num_predict"] = 1
            req = urllib.request.Request(local_brain.API + "/api/chat", json.dumps(body).encode(),
                                         {"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=900).close()
    except Exception as e:
        print(datetime.datetime.now(), "local AI warm-up:", repr(e))


def chat_local(text, photo=None):
    """The local AI, talking to Ollama directly (no Codex in between: far less to read per message, and no
    thinking out loud), with Jarvis's tools through one 'tool' function. Yields the reply in pieces."""
    import local_brain
    local_brain.ensure_running()
    now = datetime.datetime.now().strftime("%A %d %B %Y, %H:%M")
    try:
        room = awareness.describe(awareness.situation())
    except Exception:
        room = ""
    if photo:
        text += "\n[He sent a photo, but you can't see pictures: say so.]"
    with lock:
        h = local_convo["history"]
        if time.time() - local_convo["last"] > 1200 or len(h) > 40:  # same fresh-start rule as the other brains
            h.clear()
        local_convo["last"] = time.time()
        h.append({"role": "user", "content": persona(f"[{now}] {room}\n{text}")})
        for _ in range(6):  # up to 6 rounds of tool use
            body = local_body(h, stream=True)
            req = urllib.request.Request(local_brain.API + "/api/chat", json.dumps(body).encode(),
                                         {"Content-Type": "application/json"})
            said, calls = "", []
            with urllib.request.urlopen(req, timeout=600) as r:
                for line in r:
                    ev = json.loads(line or b"{}")
                    if ev.get("error"):
                        raise RuntimeError("Local AI: " + ev["error"])
                    m = ev.get("message") or {}
                    calls += m.get("tool_calls") or []
                    if m.get("content"):
                        said += m["content"]
                        yield m["content"]
            h.append({"role": "assistant", "content": said, **({"tool_calls": calls} if calls else {})})
            if said:
                yield None
            if not calls:
                return
            for c in calls:
                f = c.get("function") or {}
                args = f.get("arguments") or {}
                args = json.loads(args) if isinstance(args, str) else args
                name, args = (args.get("name"), args.get("args") or {}) if f.get("name") == "tool" else (f.get("name"), args)
                try:
                    out = FUNCS[name](**(args if isinstance(args, dict) else {}))
                except KeyError:
                    out = {"error": f"No tool called {name}"}
                except Exception as e:
                    out = {"error": f"{type(e).__name__}: {e}"}
                h.append({"role": "tool", "content": json.dumps(out, default=str)[:6000]})
        yield persona("I've gone round in circles on that one, {TITLE}. Try asking it another way.")


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
                                       system=persona(f"{SYSTEM}\nCurrent local time: {now}.") + features.memory_prompt() + features.feature_prompt(),
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


def tts(text, side=None):
    """Speech audio for the HUD: (bytes, mime type), in the current personality's voice (see speech.py).
    side "claude" / "gpt": an avatar in split mode, each with the voice picked in Settings (Split mode voices)."""
    s = features.settings()
    speed = float(s.get("voice_speed") or 1.0)
    if side == "gpt":
        return speech.say_voice(text, s.get("split_gpt_voice") or "Emma (British woman)", speed)
    if side == "claude" and s.get("split_claude_voice"):  # "" = the same voice as Jarvis
        return speech.say_voice(text, s["split_claude_voice"], speed)
    if not side and s.get("local_voice") and brain_status()["using"] == "Local":  # his own voice for the local AI
        return speech.say_voice(text, s["local_voice"], speed)
    return speech.say(text, personas.get())


# ---------- Web server ----------
# ---------- Events for the page (holographic panels) ----------
EVENTS, EVENTS_LOCK = [], threading.Lock()


def push_event(ev):
    with EVENTS_LOCK:
        seq = EVENTS[-1]["seq"] + 1 if EVENTS else 1
        EVENTS.append(dict(ev, seq=seq, at=time.time()))
        del EVENTS[:-30]
    return seq


def handoff():
    """What the phone needs to carry on from the PC: the last few exchanges and the panels from the last 15 minutes."""
    d, rows = HERE / "conversations", []
    for f in sorted(d.glob("*.jsonl"))[-2:] if d.exists() else []:
        rows += [json.loads(r) for r in f.read_text(encoding="utf-8").splitlines() if r.strip()]
    chat = [{"t": r.get("t", ""), "you": r.get("user", r.get("halen", "")), "jarvis": r.get("jarvis", "")} for r in rows[-4:]]
    with EVENTS_LOCK:
        panels = [e for e in EVENTS if e.get("type") == "panel" and time.time() - e.get("at", 0) < 900][-3:]
    return {"chat": chat, "panels": panels, "away": bool(LIVE.get("away"))}


# ---------- Phone access ----------
KEY_FILE = HERE / "phone_key.txt"  # delete it to unpair every phone


def phone_key():
    if not KEY_FILE.exists():
        import secrets
        KEY_FILE.write_text(secrets.token_urlsafe(18))
    return KEY_FILE.read_text().strip()


def tailscale_exe():
    return shutil.which("tailscale") or next((p for p in (r"C:\Program Files\Tailscale\tailscale.exe",) if os.path.exists(p)), None)


def tailscale_https():
    """Tailscale's secure link (https://<this PC>.<tailnet>.ts.net) to Jarvis, so a phone may use its microphone
    (iPhones only allow that on https pages). Sets it up with 'tailscale serve' (only his own devices can open it).
    Returns {"url"} when it's on, {"enable": link} when Tailscale needs HTTPS turned on first, or {}."""
    exe, name = tailscale_exe(), tailscale_name()
    if not (exe and name):
        return {}
    nw = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        st = subprocess.run([exe, "serve", "status"], capture_output=True, text=True, timeout=10, creationflags=nw)
        if f":{PORT}" in st.stdout:
            return {"url": f"https://{name}/"}
        r = subprocess.run([exe, "serve", "--bg", str(PORT)], capture_output=True, text=True, timeout=20, creationflags=nw)
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:  # it waits while HTTPS isn't enabled for his Tailscale account yet
        out = (e.stdout or b"").decode(errors="ignore") if isinstance(e.stdout, bytes) else (e.stdout or "")
    except Exception as e:
        return {"error": repr(e)}
    link = re.search(r"https://login\.tailscale\.com/\S+", out)
    if link:
        return {"enable": link.group(0)}
    return {"url": f"https://{name}/"} if f":{PORT}" in out or "https://" in out else {"error": out[-300:]}


def tailscale_name():
    """This PC's Tailscale name, or None."""
    exe = tailscale_exe()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=5,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (json.loads(r.stdout).get("Self") or {}).get("DNSName", "").rstrip(".") or None
    except Exception:
        return None


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
    ts = [ip for ip in sorted(ips) if tailscale(ip)]
    name = tailscale_name()
    # Tailscale: no key needed (only his own devices can reach this address), so this one link works anywhere
    out = [{"where": "Anywhere (Tailscale): no pairing needed", "url": f"http://{name or ts[0]}:{PORT}/"}] if ts else []
    sec = LIVE.get("ts_https") or {}
    if sec.get("url"):  # the secure link: the same, plus the phone's microphone works
        out.insert(0, {"where": "Anywhere, with voice (Tailscale, secure)", "url": sec["url"]})
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

    def end_headers(self):
        # The HUD page always comes fresh (the app window keeps its data between launches, which would
        # otherwise let it show an old copy after an update)
        if not self.path.startswith(("/api/", "/custom/")):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def local(self):
        # (Tailscale's secure link also arrives from this PC, but it's his phone: that counts as Tailscale)
        return self.client_address[0] in ("127.0.0.1", "::1") and not self.via_tailscale_https()

    def via_tailscale_https(self):
        return bool(self.headers.get("Tailscale-User-Login") or self.headers.get("X-Forwarded-For"))

    def tailnet(self):
        """Coming in through Tailscale: only his own devices (signed in to his Tailscale account) can do that."""
        ip = self.client_address[0]
        if ip.startswith("fd7a:115c:a1e0:") or (ip in ("127.0.0.1", "::1") and self.via_tailscale_https()):
            return True
        p = ip.split(".")
        return len(p) == 4 and p[0] == "100" and 64 <= int(p[1]) <= 127

    def allowed(self):
        """This PC always; his devices on Tailscale; a phone once it has opened the pairing link (it keeps a cookie)."""
        if self.local():
            return True
        LIVE["phone_seen"] = time.time()  # (allowed or not: only used to decide whether to hand off to the phone)
        if self.tailnet() and features.settings().get("trust_tailscale", True):
            if not self.path.startswith(("/api/events", "/api/stats", "/api/status")):
                WAKER.phone_used()
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
            if not self.path.startswith(("/api/events", "/api/stats", "/api/status")):  # not just the page polling
                WAKER.phone_used()  # the phone is using Jarvis: keep the PC awake for it
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
            # settings first: live status ("brain", "persona") must win over the saved setting of the same name
            return self.send_json({**features.settings(), "features": {k: features.feature(k) for k in features.FEATURES},
                                   "memories": len(features.memories()),
                                   "protocols": len(features.list_routines()), "mt5": mt5_on, "version": VERSION,
                                   "brain": brain_status(), "persona": personas.get(),
                                   "autostart": autostart_on()})
        if self.path.startswith("/api/modelfile/"):  # the hologram workshop's 3D models (and their textures)
            f = workshop.resolve(self.path[len("/api/modelfile/"):].split("?")[0])
            if not f or f.stat().st_size > 300_000_000:
                return self.send_error(404)
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", {".gltf": "model/gltf+json", ".glb": "model/gltf-binary", ".png": "image/png",
                                              ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(f.suffix.lower(),
                                                                                              "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
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
        if self.path.startswith("/api/background"):  # the background picture (hud_background)
            f = next((HERE / "custom" / "backgrounds").glob("background.*"), None) \
                if (HERE / "custom" / "backgrounds").is_dir() else None
            if not f:
                return self.send_error(404)
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
                             .get(f.suffix.lower(), "image/jpeg"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if self.path == "/api/alive":  # for a second launch: is this Jarvis's window open?
            return self.send_json({"window": bool(LIVE.get("window_open")), "version": VERSION})
        if self.path == "/api/status":  # the Activity panel
            return self.send_json(activity())
        if self.path.startswith("/api/spend"):  # the spending report's data (spendview.py)
            from urllib.parse import parse_qs, urlsplit
            q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
            try:
                if self.path.startswith("/api/spend/txns"):
                    return self.send_json(spendview.transactions(q.get("account"), q.get("month"), q.get("cat"),
                                                                 q.get("shop"), q.get("way")))
                return self.send_json(spendview.view(q.get("account", ""), q.get("month", "")))
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {e}"})
        if self.path == "/api/local":  # the local AI: what's set up, the recommended model, install progress
            return self.send_json(local_brain.status())
        if self.path == "/api/handoff":  # the phone picking up where the PC left off
            return self.send_json(handoff())
        if self.path == "/api/secure":  # Tailscale's secure link for the phone (its microphone needs https)
            return self.send_json(LIVE.get("ts_https") or {})
        if self.path == "/api/deepseek":  # whether a DeepSeek key is saved (never the key itself)
            return self.send_json({"ready": deepseek.available()})
        if self.path == "/api/ambient":
            return self.send_json(ambient())
        if self.path == "/api/voice":  # Kokoro setup progress and the voices to choose from, for Settings
            return self.send_json({**speech.status, "voices": list(speech.KOKORO_VOICES), "split": speech.SPLIT_VOICES,
                                   "auto": speech.PERSONA_KOKORO.get(personas.current())})
        if self.path == "/api/custom":  # add-on files for the HUD to load (custom/*.js, *.css), and 3D models
            return self.send_json({"files": custom_loader.web_files(), "errors": custom_loader.errors, "models": models()})
        if self.path.startswith("/custom/models/"):
            from urllib.parse import unquote
            name = unquote(self.path.split("?")[0].rsplit("/", 1)[-1])
            if not MODEL_NAME.fullmatch(name) or not (MODELS / name).is_file():
                return self.send_error(404)
            data = (MODELS / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
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
            return self.send_json(features.save_settings(d.get("name", ""), d.get("city", ""), d.get("title", "sir"),
                                                         d.get("features")))
        if self.path == "/api/update":  # the HUD's Update button: install the new version and restart
            if not self.local():
                return self.send_error(403)
            try:
                TASKS["update"] = {"label": "Installing the update", "progress": None}
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
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                audio, mime = (speech.say_lang(body["text"], body["lang"]) if body.get("lang")
                               else speech.say_voice(body["text"], body["voice"]) if body.get("voice") in speech.SPLIT_VOICES
                               else tts(body["text"], body.get("side")))
                if not audio:
                    raise RuntimeError("no audio returned")
            except Exception as e:  # the page falls back to the built-in Windows voice
                print(datetime.datetime.now(), "voice error:", repr(e))
                return self.send_error(503)
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            return self.wfile.write(audio)
        if self.path == "/api/show":  # a second launch: bring this window to the front
            if not self.local():
                return self.send_error(403)
            if LIVE.get("show_window"):
                threading.Thread(target=LIVE["show_window"], daemon=True).start()
            return self.send_json({"shown": bool(LIVE.get("show_window"))})
        if self.path == "/api/quiet":  # the Activity panel's quiet mode switch
            on = json.loads(self.rfile.read(int(self.headers["Content-Length"]))).get("on", True)
            return self.send_json(FUNCS["quiet_mode"](on=bool(on)))
        if self.path == "/api/prefs":  # the HUD's settings (from the PC or his own phone)
            try:
                return self.send_json(save_prefs(json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
        if self.path.startswith("/api/model?name="):  # a 3D model for the avatar, from the settings
            if not self.local():
                return self.send_error(403)
            from urllib.parse import unquote
            try:
                n = int(self.headers["Content-Length"])
                if n > 300_000_000:
                    raise ValueError("That model is over 300 MB")
                return self.send_json({"name": save_model(unquote(self.path.split("=", 1)[1]), self.rfile.read(n))})
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
        if self.path == "/api/power":  # restart or close Jarvis (jarvis_power, from this PC only)
            if not self.local():
                return self.send_error(403)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            action = body.get("action")
            if action not in ("restart", "shutdown"):
                return self.send_error(400)
            wait = 0.2 if body.get("now") else 6  # a few seconds so his goodbye is spoken first
            self.send_json({"ok": action, "in_seconds": wait})
            threading.Timer(wait, updater.restart if action == "restart" else lambda: os._exit(0)).start()
            return
        if self.path == "/api/finish":  # "finish this": the window he was in, and a picture of the screen
            try:
                return self.send_json(finish_capture())
            except Exception as e:
                return self.send_json({"error": repr(e)})
        if self.path == "/api/stt":  # the phone's microphone: a recording in, what was said out
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n < 15_000_000:
                return self.send_json({"error": "No recording"}, 400)
            data = self.rfile.read(n)
            kind = self.headers.get("Content-Type", "")
            import voice as voice_mod
            try:
                text, sure = voice_mod.transcribe_audio(data, ".webm" if "webm" in kind else ".ogg" if "ogg" in kind else ".m4a")
            except Exception as e:
                print(datetime.datetime.now(), "phone speech-to-text failed:", repr(e))
                return self.send_json({"error": "I couldn't make that out"}, 500)
            if text:
                LIVE["spoken"] = (text, time.time())  # the brain is told it was spoken, so may be misheard
            return self.send_json({"text": text, "sure": sure})
        if self.path == "/api/inventory":  # desk view: what the camera sees now (inventory.py)
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            return self.send_json(inventory.seen(d.get("items") or [], d.get("photo")))
        if self.path == "/api/upload":  # a photo for Jarvis: raw image bytes in, {"name": ...} out
            try:
                n = int(self.headers["Content-Length"])
                if n > 20_000_000:
                    raise ValueError("That photo is over 20 MB")
                return self.send_json({"name": save_upload(self.rfile.read(n), self.headers.get_content_type())})
            except Exception as e:
                return self.send_json({"error": str(e)}, 400)
        if self.path == "/api/debate":  # split mode: {"side": "claude"|"gpt", "t"/"flush"/"end": ...} lines
            q = json.loads(self.rfile.read(int(self.headers["Content-Length"]))).get("text", "")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            pieces = debate_stream(q)
            try:
                for side, p in pieces:
                    self.wfile.write((json.dumps({"side": side, **({"t": p} if p else {"end": True} if p == ""
                                                                    else {"flush": True})}) + "\n").encode())
                    self.wfile.flush()
                self.wfile.write(b'{"done": true}\n')
            except ConnectionError:
                pass
            finally:
                pieces.close()
            return
        if self.path == "/api/shop":  # supermarket prices (life.py's shopping list), from this PC only
            if not self.local():
                return self.send_error(403)
            items = json.loads(self.rfile.read(int(self.headers["Content-Length"]))).get("items", [])
            if not LIVE.get("shop"):
                return self.send_json({"error": "Price checks need the Jarvis app window (not browser mode)."})
            return self.send_json(LIVE["shop"]([str(i)[:60] for i in items][:25]))
        if self.path == "/api/spend":  # the spending report's buttons
            try:
                return self.send_json(spendview.act(json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {e}"})
        if self.path == "/api/page_price":  # a product page's price (life.py's price watch), from this PC only
            if not self.local():
                return self.send_error(403)
            url = json.loads(self.rfile.read(int(self.headers["Content-Length"]))).get("url", "")
            if not re.match(r"https?://", url) or not LIVE.get("page_price"):
                return self.send_json({"error": "Needs a web link, and the Jarvis app window (not browser mode)."})
            return self.send_json(LIVE["page_price"](url))
        if self.path == "/api/deepseek":  # save or remove the DeepSeek key: only from this PC
            if not self.local():
                return self.send_error(403)
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            r = deepseek.set_key(d.get("key", ""))
            if not r.get("ready") and features.settings().get("brain") == "deepseek":
                set_brain("auto")
            push_event({"type": "brain", "name": brain_status()["using"]})
            return self.send_json(r)
        if self.path == "/api/local":  # install the local AI (in the background; progress in Activity)
            if not self.local():
                return self.send_error(403)
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if local_brain.progress["running"]:
                return self.send_json({"error": "Already installing."})

            def go():
                TASKS["local_ai"] = {"label": "Setting up the local AI", "progress": None}
                try:
                    r = local_brain.install(d.get("model"))
                    push_event({"type": "brain", "name": brain_status()["using"]})
                    LIVE.get("say", print)(persona("Your local AI is ready, {TITLE}. I can think on this PC now, "
                                                   "for free." if r.get("ready")
                                                   else f"The local AI didn't finish setting up: {r.get('error')}"))
                finally:
                    TASKS.pop("local_ai", None)
            threading.Thread(target=go, daemon=True).start()
            return self.send_json({"started": True})
        if self.path == "/api/bootup":  # Settings' "Play the boot-up"
            if not self.local():
                return self.send_error(403)
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            threading.Thread(target=boot_up, daemon=True).start()
            return self.send_json({"ok": True})
        if self.path == "/api/brain":  # merging the split avatars: the one he clicked becomes the brain
            r = set_brain(json.loads(self.rfile.read(int(self.headers["Content-Length"])))["brain"])
            return self.send_json(r, 400 if r.get("error") else 200)
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
            except ConnectionError:  # the HUD stopped listening (he cut in, or closed the window)
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
    httpd = None
    for attempt in range(2):
        try:
            httpd = ThreadingHTTPServer((HOST, PORT), Handler)
            break
        except OSError:
            if attempt or not take_over(url):
                print(datetime.datetime.now(), "Jarvis is already running, so this copy is closing.")
                sys.exit()
    print(datetime.datetime.now(), f"JARVIS v{VERSION} online at {url}")
    threading.Thread(target=lambda: LIVE.update(ts_https=tailscale_https()), daemon=True).start()
    if features.settings().get("brain") == "local":  # he starts online; "offline mode" switches to the local AI
        features._save("settings.json", {**features.settings(), "brain": "auto"})
    if "--browser" in sys.argv:
        webbrowser.open(url)
        httpd.serve_forever()
    else:
        # let Jarvis speak even when you talk to him from the mini window (no click in the main window)
        # (and keep pages running at full speed in the background: pinned panels are fed from hidden pages)
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
            "--autoplay-policy=no-user-gesture-required --disable-background-timer-throttling "
            "--disable-renderer-backgrounding --disable-backgrounding-occluded-windows")
        import webview  # pip install pywebview; uses the Edge engine built into Windows
        import mini
        try:  # his own taskbar button and icon, not grouped under Python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Minno404.Jarvis")
        except Exception:
            pass
        try:
            import voice  # optional: "Hey Jarvis" needs openwakeword, faster-whisper and sounddevice
        except Exception as e:
            print(datetime.datetime.now(), "voice control unavailable:", repr(e))
            voice = None
        LIVE["voice"] = voice
        if voice:
            import hotkey
            hotkey.start(voice.ptt_down, voice.ptt_up)
        apply_prefs()
        if os.name == "nt" and startup_link().exists():  # the old Startup-folder way: move to the faster log-on task
            def move_autostart():
                try:
                    set_autostart(True)
                except Exception as e:
                    print(datetime.datetime.now(), "start with Windows:", repr(e))
            threading.Thread(target=move_autostart, daemon=True).start()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        main = None

        def open_main():
            main.restore()
            main.show()
            main.on_top = True  # bring it to the front, then let it behave normally again
            main.on_top = False
            mini.send("hide")
            show_pins(False)

        def drag_window():
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            try:
                hwnd = ctypes.c_void_p(main.native.Handle.ToInt64())
            except Exception:
                return

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                            ("dwFlags", wintypes.DWORD)]
            u.MonitorFromPoint.restype = ctypes.c_void_p
            pt, r = wintypes.POINT(), wintypes.RECT()
            u.GetCursorPos(ctypes.byref(pt))
            u.GetWindowRect(hwnd, ctypes.byref(r))
            frac, offy = (pt.x - r.left) / max(1, r.right - r.left), pt.y - r.top
            moved, edge, hint = False, "", ""
            start = (pt.x, pt.y)
            while u.GetAsyncKeyState(0x01) & 0x8000:  # while the left button is held
                u.GetCursorPos(ctypes.byref(pt))
                if not moved and abs(pt.x - start[0]) + abs(pt.y - start[1]) < 4:
                    time.sleep(0.008)
                    continue  # a click (or the first half of a double-click), not a drag
                if not moved:
                    moved = True
                    if win["max"]:  # dragging a maximised window: it comes back to its normal size under the mouse
                        main.restore()
                        time.sleep(0.05)
                u.GetWindowRect(hwnd, ctypes.byref(r))
                w = r.right - r.left
                u.SetWindowPos(hwnd, None, int(pt.x - frac * w), pt.y - offy, 0, 0, 0x0001 | 0x0004 | 0x0010)
                mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
                u.GetMonitorInfoW(ctypes.c_void_p(u.MonitorFromPoint(pt, 2)), ctypes.byref(mi))
                m = mi.rcMonitor
                edge = "top" if pt.y <= m.top + 1 else "left" if pt.x <= m.left + 1 else "right" if pt.x >= m.right - 2 else ""
                if edge != hint:
                    hint = edge
                    try:
                        main.evaluate_js(f"snapHint({json.dumps(edge)})")
                    except Exception:
                        pass
                time.sleep(0.008)
            if hint:
                try:
                    main.evaluate_js("snapHint('')")
                except Exception:
                    pass
            if edge == "top":
                main.maximize()
            if moved:
                try:  # the HUD's maximise button shows the right icon
                    main.evaluate_js(f"window.maxIcon&&maxIcon({{max:{'true' if edge == 'top' else 'false'}}})")
                except Exception:
                    pass
            if edge and edge != "top":
                wa = mi.rcWork
                half = (wa.right - wa.left) // 2
                u.SetWindowPos(hwnd, None, wa.left if edge == "left" else wa.left + half, wa.top, half,
                               wa.bottom - wa.top, 0x0004 | 0x0010)

        # ---- Pinned panels: up to 3 HUD panels that float over other windows while Jarvis is out of focus ----
        pins = {}  # panel id -> its little window

        def save_pin(pid, **kw):
            s = features.settings()
            features._save("settings.json", {**s, "pins": [dict(p, **kw) if p["id"] == pid else p
                                                           for p in s.get("pins", [])]})

        def pin_alpha():
            """How solid pinned panels are: follows the HUD's See-through slider (lower = more see-through)."""
            return min(1.0, 0.3 + float(features.settings().get("panel_alpha", 0.28)))

        def pin_moved(pid, x, y, w, h):
            save_pin(pid, x=x, y=y, w=w, h=h)

        mini.pin_events.update(moved=pin_moved, close=lambda pid: api.unpin(pid))
        LIVE["pin_alpha"] = lambda: mini.send("pin_alpha", pin_alpha())

        def make_pin(p):
            """A pinned panel: a hidden page keeps the panel live and sends what it shows to a see-through
            floating window drawn by mini.py (a browser window can't fade on Windows)."""
            from urllib.parse import quote
            mini.send("pin_alpha", pin_alpha())
            mini.send("pin_add", p["id"], p["title"], p.get("x"), p.get("y"), p.get("w", 300), p.get("h", 260))
            w = webview.create_window(f"Jarvis · {p['title']}", f"{url}/?pin={quote(p['id'])}&v={VERSION}", width=p.get("w", 300),
                                      height=p.get("h", 260), x=p.get("x"), y=p.get("y"), frameless=True,
                                      easy_drag=False, on_top=True, hidden=True, focus=False, min_size=(180, 110),
                                      background_color="#03070c", js_api=api)

            pins[p["id"]] = w
            return w

        # ---- Supermarket prices: Woolworths and Coles, read through hidden browser windows, like a person would ----
        shops, shop_lock = {}, threading.Lock()
        SHOPS = {
            "Woolworths": ("https://www.woolworths.com.au/", """(async()=>{const out={};for(const t of TERMS){try{
              const r=await fetch('/apis/ui/Search/products',{method:'POST',credentials:'include',headers:{'content-type':'application/json',accept:'application/json, text/plain, */*'},
                body:JSON.stringify({Filters:[],IsSpecial:false,Location:'/shop/search/products?searchTerm='+encodeURIComponent(t),PageNumber:1,PageSize:12,SearchTerm:t,SortType:'TraderRelevance',ExcludeSearchTypes:['UntraceableVendors'],GroupEdmVariants:true})});
              const j=await r.json(),ps=(j.Products||[]).flatMap(g=>g.Products||[g]);
              out[t]=ps.filter(p=>p&&p.Price!=null).slice(0,6).map(p=>({name:p.DisplayName||p.Name,price:p.Price,was:p.WasPrice||null,special:!!p.IsOnSpecial,size:p.PackageSize||'',unit:p.CupString||'',available:p.IsAvailable!==false}))
            }catch(e){out[t]={error:String(e)}}}window.__jv=JSON.stringify(out)})();"""),
            "Coles": ("https://www.coles.com.au/", """(async()=>{const out={};let id;try{id=JSON.parse(document.getElementById('__NEXT_DATA__').textContent).buildId}catch(e){}
              if(!id){window.__jv=JSON.stringify({error:'the Coles page did not load properly'});return}
              for(const t of TERMS){try{const r=await fetch('/_next/data/'+id+'/en/search/products.json?q='+encodeURIComponent(t),{credentials:'include'}),j=await r.json();
                const rs=((j.pageProps&&j.pageProps.searchResults&&j.pageProps.searchResults.results)||[]).filter(p=>p._type==='PRODUCT'&&p.pricing);
                out[t]=rs.slice(0,6).map(p=>({name:[p.brand,p.name].filter(Boolean).join(' '),price:p.pricing.now,was:p.pricing.was||null,special:!!(p.pricing.was&&p.pricing.was>p.pricing.now),size:p.size||'',unit:p.pricing.comparable||'',available:p.availability!==false}))
              }catch(e){out[t]={error:String(e)}}}window.__jv=JSON.stringify(out)})();"""),
        }

        def shop_prices(terms):
            """{store: {term: [products]}} for each supermarket, or {store: {"error": ...}}."""
            out = {}
            with shop_lock:
                for store, (site, code) in SHOPS.items():
                    try:
                        w = shops.get(store)
                        if not w:
                            ready = threading.Event()
                            w = webview.create_window(f"Jarvis · {store}", site, hidden=True, width=1100, height=800)
                            w.events.loaded += ready.set
                            ready.wait(40)
                            time.sleep(3)  # the site's own checks run just after it loads
                            shops[store] = w
                        w.evaluate_js("window.__jv=null")
                        w.evaluate_js(code.replace("TERMS", json.dumps(terms)))
                        for _ in range(90):  # up to ~45 s for all the searches
                            r = w.evaluate_js("window.__jv")
                            if r:
                                out[store] = json.loads(r)
                                break
                            time.sleep(0.5)
                        else:
                            out[store] = {"error": "no answer from the site"}
                    except Exception as e:
                        shops.pop(store, None)  # start that site fresh next time
                        out[store] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
            return out
        LIVE["shop"] = shop_prices
        PAGE_PRICE = """(()=>{const out={};for(const s of document.querySelectorAll('script[type="application/ld+json"]')){try{
            const d=JSON.parse(s.textContent);for(const x of [].concat(d['@graph']||d)){if(![].concat(x['@type']||[]).includes('Product'))continue;
              out.name=out.name||x.name;const o=[].concat(x.offers||[])[0];if(!o||out.price)continue;
              out.price=+(o.lowPrice||o.price||(o.priceSpecification&&[].concat(o.priceSpecification)[0].price)||0)||undefined;out.currency=o.priceCurrency}}catch(e){}}
          if(!out.price){const m=document.querySelector('meta[property="product:price:amount"],meta[property="og:price:amount"],[itemprop="price"]');
            if(m)out.price=+String(m.getAttribute('content')||m.textContent).replace(/[^0-9.]/g,'')||undefined}
          out.name=out.name||document.title;return JSON.stringify(out)})()"""

        def page_price(url):
            """A product page's name and price, read the way a browser sees it (the shop's own product data)."""
            ready = threading.Event()
            w = webview.create_window("Jarvis · price check", url, hidden=True, width=1100, height=800)
            w.events.loaded += ready.set
            try:
                ready.wait(45)
                for _ in range(6):  # pages that build themselves after loading
                    time.sleep(2)
                    r = json.loads(w.evaluate_js(PAGE_PRICE) or "{}")
                    if r.get("price"):
                        return r
                return {"error": "I couldn't find a price on that page.", "name": r.get("name")}
            except Exception as e:
                return {"error": f"{type(e).__name__}: {str(e)[:160]}"}
            finally:
                w.destroy()
        LIVE["page_price"] = page_price

        def show_pins(show):
            mini.send("pins_show", bool(show))

        class Api:  # called from the page as window.pywebview.api.<name>
            def mini(self, show):
                mini.send("show" if show else "hide")
                show_pins(show)

            def drag(self):
                """The HUD's title strip was pressed: move the window with the mouse, like a normal window. Hit the top
                of the screen to maximise, the left or right edge to fill that half (the HUD shows a prompt first)."""
                threading.Thread(target=drag_window, daemon=True).start()

            def win(self, action, w=None, h=None):  # the HUD's own window buttons and resize corner
                if action == "min":
                    main.minimize()
                elif action == "max":
                    main.restore() if win["max"] else main.maximize()
                elif action == "close":
                    main.destroy()
                elif action == "size":
                    if not win["max"]:
                        main.resize(max(420, int(w)), max(600, int(h)))
                return {"max": win["max"]}

            def pinned(self):
                return [p["id"] for p in features.settings().get("pins", [])]

            def pin(self, pid, title, w=300, h=260):
                s = features.settings()
                have = s.get("pins", [])
                if any(p["id"] == pid for p in have):
                    return {"pinned": pid}
                if len(have) >= 3:
                    return {"error": "You can pin up to 3 panels. Unpin one first."}
                p = {"id": pid, "title": title, "w": int(w), "h": int(h)}
                features._save("settings.json", {**s, "pins": have + [p]})
                make_pin(p)
                return {"pinned": pid}

            def unpin(self, pid):
                s = features.settings()
                features._save("settings.json", {**s, "pins": [p for p in s.get("pins", []) if p["id"] != pid]})
                w = pins.pop(pid, None)
                mini.send("pin_remove", pid)
                if w:
                    w.destroy()
                push_event({"type": "pins"})  # the HUD's + / - buttons catch up
                return {"unpinned": pid}

            def pin_frame(self, pid, rows):  # what a pinned panel shows right now, from its hidden page
                mini.send("pin_frame", pid, rows if isinstance(rows, list) else [])

            def resize_pin(self, pid, w, h):
                w, h = max(180, int(w)), max(110, int(h))
                if pid in pins:
                    pins[pid].resize(w, h)
                save_pin(pid, w=w, h=h)

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

        api = Api()
        # no Windows title bar: the HUD has its own minimise / maximise / close and a drag strip along the top
        to_tray = lambda: bool(features.settings().get("close_to_tray")) and bool(LIVE.get("tray_ok"))
        try:
            import pystray  # noqa: F401  (the tray icon is how he gets the window back)
            LIVE["tray_ok"] = True
        except ImportError:
            pass
        main = webview.create_window("JARVIS", f"{url}/?v={VERSION}", width=1440, height=900, min_size=(420, 600),
                                     background_color="#03070c", js_api=api, text_select=True, frameless=True,
                                     easy_drag=False, hidden="--startup" in sys.argv and to_tray())
        win = {"max": False}
        main.events.maximized += lambda: win.update(max=True)
        main.events.restored += lambda: win.update(max=False)
        for p in features.settings().get("pins", [])[:3]:
            make_pin(p)  # hidden until Jarvis goes out of focus
        main.events.minimized += lambda: (mini.send("show"), show_pins(True))
        LIVE["window_open"], LIVE["show_window"] = True, open_main
        LIVE["shot_hide"], LIVE["shot_show"] = main.minimize, open_main  # out of the way for "what's on my screen"

        quitting = {"now": False}

        def closing():
            """Close to the tray (Settings): the window hides and Jarvis keeps running by the clock."""
            if quitting["now"] or not to_tray():
                return True
            threading.Timer(0.05, lambda: (main.hide(), mini.send("hide"), show_pins(False))).start()
            return False  # cancels the close
        main.events.closing += closing

        def quit_jarvis():
            quitting["now"] = True
            main.destroy()

        def closed():  # closing the main window quits everything (pinned panels' hidden pages included)
            LIVE["window_open"] = False
            mini.send("quit")
            if LIVE.get("tray"):
                LIVE["tray"].stop()  # or its icon lingers by the clock until you hover it
            threading.Timer(0.5, lambda: os._exit(0)).start()
        main.events.closed += closed

        def set_icon():  # the Jarvis logo on the window and its taskbar button
            try:
                import ctypes
                u = ctypes.windll.user32
                u.LoadImageW.restype = u.FindWindowW.restype = ctypes.c_void_p
                try:
                    hwnd = main.native.Handle.ToInt64()
                except Exception:
                    hwnd = u.FindWindowW(None, "JARVIS")
                for size, which in ((16, 0), (32, 1)):  # small, big
                    ico = u.LoadImageW(None, str(HERE / "jarvis.ico"), 1, size, size, 0x10)  # LR_LOADFROMFILE
                    u.SendMessageW(ctypes.c_void_p(hwnd), 0x80, which, ctypes.c_void_p(ico))  # WM_SETICON
            except Exception as e:
                print(datetime.datetime.now(), "window icon:", repr(e))
        main.events.shown += set_icon

        def tray():
            """Jarvis in the system tray, by the clock and wifi: click to open, right-click for more."""
            try:
                import pystray
                from PIL import Image
            except ImportError:
                return print(datetime.datetime.now(), "no tray icon: pip install pystray")
            quiet = lambda *_: bool(features.settings().get("quiet"))
            menu = pystray.Menu(
                pystray.MenuItem("Open Jarvis", lambda *_: open_main(), default=True),
                pystray.MenuItem("Mini core", lambda *_: api.mini(True)),
                pystray.MenuItem("Quiet mode", lambda *_: FUNCS["quiet_mode"](on=not quiet()), checked=quiet),
                pystray.MenuItem("Mute (not listening)", lambda *_: FUNCS["voice_mute"](on=not features.settings().get("voice_muted")),
                                 checked=lambda *_: bool(features.settings().get("voice_muted"))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Restart", lambda *_: (LIVE["tray"].stop(), updater.restart())),
                pystray.MenuItem("Quit", lambda *_: quit_jarvis()))
            LIVE["tray"] = pystray.Icon("Jarvis", Image.open(HERE / "jarvis.ico"), "Jarvis", menu)
            LIVE["tray"].run()
        threading.Thread(target=tray, daemon=True).start()
        mini.start(on_ask=lambda text: heard_text(text), on_open=open_main,
                   on_mute=lambda: FUNCS["voice_mute"](on=not features.settings().get("voice_muted")))
        mini.send("muted", bool(features.settings().get("voice_muted")))
        if features.settings().get("theme"):
            mini.send("colour", features.settings()["theme"])

        def run_js(code):
            try:
                main.evaluate_js(code)
            except Exception as e:  # e.g. the page is still loading; never crash a background thread over it
                print(datetime.datetime.now(), "page not ready:", str(e)[:120])

        js = lambda code: threading.Thread(target=run_js, args=(code,), daemon=True).start()
        def speak_now(text):  # the HUD says it; phones in holo mode say it too
            text = features.address(text)
            push_event({"type": "say", "text": text})
            if not LIVE.get("quiet_wake"):  # woken by the phone with nobody at the PC: stay silent on the PC
                js(f"announce({json.dumps(text)})")
        st = {"held": [], "game": None, "away": False, "voice_at": 0.0, "mode": "idle", "quiet": False}
        LIVE["st"] = st
        presence = awareness.Presence()

        def say(text, urgent=False):
            """Jarvis speaks up on his own. While you're away, or mid-game or in quiet mode for anything that can
            wait, it's held and told to you when you're back."""
            if st["away"] and time.time() - LIVE.get("phone_seen", 0) < 120:
                push_event({"type": "phone_say", "text": persona(text)})  # he's left the PC but has his phone: tell him there
                return
            if st["away"] or ((st["game"] or features.settings().get("quiet")) and not urgent):
                st["held"].append(text)
            else:
                speak_now(text)
        LIVE["say"] = say

        def deliver_held(greet):
            held, st["held"] = st["held"][:6], []
            if held:
                speak_now(f"{greet} While you were {'away' if greet else 'busy'}: ".lstrip() + " ".join(held))
            elif greet:
                speak_now(greet)

        def do_hold():
            js("holdOn()")
            mini.send("mode", "idle")

        def heard_text(text, confident=True):
            if not text:
                return js("setMode('idle')")
            if voice and voice.is_hold(text):  # e.g. typed into the mini core
                voice.hold()
                return do_hold()
            st["voice_at"] = time.time()
            # Not sure he heard it right: check first ("I heard: ... Is that right?"), then act on yes
            pending, st["confirm"] = st.get("confirm"), None
            if pending and time.time() - pending["at"] < 45:
                if YES.match(text):
                    text, confident = pending["text"], True
                elif NO.match(text):
                    return speak_now("Sorry, sir. Say it again?")
            if not confident and len(text.split()) >= 2:
                st["confirm"] = {"text": text, "at": time.time()}
                js(f"add('you',{json.dumps(text + ' (?)')})")
                return speak_now(f"Just to check, sir: did you say \"{text.rstrip('.?!')}\"?")
            LIVE["spoken"] = (text, time.time())  # the brain is told it was spoken, so may be misheard
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

        def offer_left_off():
            """Back after a few hours (or the PC's just started): what he had open last time, and the offer to reopen."""
            try:
                r = leftoff.where_i_left_off()
                if not r.get("found") or not 3 <= r["age_hours"] <= 96:
                    return
                features._panel({"type": "panel", "kind": "stats", "title": "Where you left off", "stay": True,
                                 "rows": [[w["app"], w["title"][:70]] for w in r["windows"][:8]],
                                 "actions": [["Reopen them", "reopen them"]]})
                say(persona(r["line"] + " Say 'reopen them' and I'll bring it all back, {TITLE}."))
            except Exception as e:
                print(datetime.datetime.now(), "left off:", repr(e))

        def watcher():
            """Every 10 s: reminders, the morning brief, price alerts, trade guard, news and the day's review."""
            watch = trading.Watch(lambda text: say(text, urgent=True), review, coach.TiltWatch())
            learning = threading.Lock()
            threading.Timer(40, offer_left_off).start()  # just started (e.g. the next morning): where you left off
            while True:
                try:
                    sit = awareness.situation()
                    if sit:
                        if WAKER.tick(sit["idle_s"]) == "sleep":
                            print(datetime.datetime.now(), "the phone's done: back to sleep")
                            power.sleep_pc()
                        LIVE["quiet_wake"] = WAKER.quiet(sit["idle_s"])
                    change = presence.update(sit["idle_s"]) if sit else None
                    if sit:
                        leftoff.tick(sit["idle_s"])
                    if change == "away":
                        leftoff.snapshot()  # what was open when he stepped away
                        if time.time() - LIVE.get("phone_seen", 0) < 120:
                            push_event({"type": "handoff"})  # the phone picks up the conversation and panels
                    LIVE["away"] = bool(presence.away)
                    st["away"] = presence.away
                    was_game, st["game"] = st["game"], sit.get("game")
                    if change == "back" and presence.last_gone >= 3 * 3600:
                        threading.Timer(12, offer_left_off).start()  # after the welcome: where you left off
                    if change == "back":
                        if presence.last_gone >= 3 * 3600 and features.settings().get("bootup", True):
                            held, st["held"] = st["held"][:6], []
                            boot_up(held)  # long time away: the full Iron Man welcome
                        else:
                            deliver_held("Welcome back, sir.")
                    quiet = bool(features.settings().get("quiet"))
                    was_quiet, st["quiet"] = st["quiet"], quiet
                    if (was_game and not st["game"] or was_quiet and not quiet) and not st["away"] and not st["game"] \
                            and not quiet:
                        deliver_held("")  # game over or quiet mode off: what was held for later
                    state = features._load("state.json", {})
                    if awareness.late_night_due(sit, state):
                        features._save("state.json", state)
                        say(f"It's past {sit['now'].hour} in the morning, sir. "
                            + ("The charts will still be there after some sleep." if features.feature("trading")
                               else "Whatever it is will still be there after some sleep."))
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
                        ask_claude_and_say(features.morning_prompt())
                except Exception as e:
                    print(datetime.datetime.now(), "watcher:", repr(e))
                try:
                    job = devhelper.next_job()
                    if job:  # a coding job: run it alongside, announce when finished
                        threading.Thread(target=lambda j=job: say(devhelper.run_job(j, CLAUDE, brain_status()["using"].lower())), daemon=True).start()
                except Exception as e:
                    print(datetime.datetime.now(), "dev job:", repr(e))
                try:
                    if features.feature("spending") and time.time() - st.get("plan_check", 0) > 3600:
                        st["plan_check"] = time.time()
                        for w in spending.plan_warnings():
                            say(persona(f"Budget note, {{TITLE}}: {w}"))
                except Exception as e:  # no Spend Breakdown or no statements yet
                    print(datetime.datetime.now(), "spending plan:", repr(e))
                try:
                    gamecoach.tick(st["game"], say)  # coaching his gameplay, if he asked
                except Exception as e:
                    print(datetime.datetime.now(), "game coach:", repr(e))
                try:
                    for line in life.tick(st["game"]):  # game mode, and bills coming up
                        say(persona(line))
                except Exception as e:
                    print(datetime.datetime.now(), "life:", repr(e))
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
                if features.settings().get("voice_muted"):
                    voice.muted.set()  # still muted from last time
                voice.start(on_status=lambda t: js(f"voiceStatus({json.dumps(t)})"),
                            on_heard=lambda: (mini.send("mode", "listening"), js("heard()")), on_text=heard_text,
                            on_interrupt=lambda: js("stopSpeaking()"),
                            on_follow=lambda on: (mini.send("mode", "listening" if on else "idle"),
                                                  js(f"followUp({'true' if on else 'false'})")),
                            on_hold_cmd=do_hold)

        def music_meter():
            """How loud whatever the PC is playing is (0-1), fed to the HUD's ambient light while it's on."""
            meter = None
            while True:
                s = features.settings()
                if not (s.get("ambient") and s.get("ambient_music", True)) or not LIVE.get("window_open"):
                    meter = None
                    time.sleep(2)
                    continue
                try:
                    if meter is None:
                        import comtypes
                        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
                        comtypes.CoInitialize()
                        dev = AudioUtilities.GetSpeakers()
                        dev = getattr(dev, "_dev", dev)
                        meter = dev.Activate(IAudioMeterInformation._iid_, comtypes.CLSCTX_ALL, None).QueryInterface(
                            IAudioMeterInformation)
                    main.evaluate_js(f"ambLevel({meter.GetPeakValue():.3f})")
                    time.sleep(0.1)
                except Exception as e:
                    print(datetime.datetime.now(), "ambient music level unavailable:", repr(e)[:160])
                    meter = None
                    time.sleep(60)
        threading.Thread(target=music_meter, daemon=True).start()
        main.events.loaded += on_loaded
        # not private mode: panel positions, closed panels and other HUD choices are kept between launches
        webview.start(private_mode=False, storage_path=str(HERE / "webdata"))
