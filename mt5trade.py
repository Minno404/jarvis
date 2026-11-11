"""Trading on MetaTrader 5: trades he asks for, and the autopilot ("make me money").

Trades he asks for ("buy 0.1 gold, stop at 2310, target 2350"): propose_trade() checks it (a stop loss is required,
stop and target on the right sides, size within his limits), works out the dollar risk and shows a ticket on the
HUD with the chart and the entry, stop and target lines. Nothing is sent until he clicks Confirm on the ticket: a
misheard word must never place a trade. Moving a stop or target and closing trades go through the same tickets.

The autopilot ("make me money"): every 15 minutes it reads the charts (M15, H1, H4), his account, the news calendar
and how he trades (from his journal), and asks two brains (Claude and ChatGPT, or DeepSeek if one is out) for the
best trade, separately. It trades only when both independently pick the same symbol and direction, sized to his
risk limit, with the wider stop and the nearer target of the two. Hard limits it can't break: a daily loss limit
(then it stops for the day), a maximum number of trades a day, one autopilot trade open at a time, nothing within
30 minutes of high-impact news, a wide-spread check, and a demo account unless he has switched live trading on
(with a click on a HUD card). It moves its stop to break-even at 1R. "Stop trading" stops it at once. Everything it
decides, and why, goes in autopilot_log.json and on the HUD.
"""
import csv
import datetime
import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

import features

HERE = Path(__file__).resolve().parent
PENDING = HERE / "trade_tickets.json"   # tickets waiting for his click
AUTO_STATE = HERE / "autopilot_state.json"
AUTO_LOG = HERE / "autopilot_log.json"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAGIC_MANUAL, MAGIC_AUTO, MAGIC_TEST = 404, 405, 406  # marks Jarvis's trades in MT5 (his own trades are left alone by the autopilot)
TICKET_SECONDS = 120  # a ticket not confirmed within 2 minutes expires (the price will have moved)
CLAUDE = None  # set by server.py (the Claude Code CLI)
IS_OUT = lambda name: False  # set by server.py: is that brain out of allowance right now?
LIMITS = {  # his settings override these ("trade_" keys in settings.json)
    "trade_max_lots": 1.0,          # biggest order Jarvis will send
    "trade_max_risk_pct": 2.0,      # most of his balance one trade may risk (trades he asks for)
    "trade_live": False,            # trades on a real-money account (else demo only)
    "auto_live": False,             # the autopilot on a real-money account (separate switch)
    # His own numbers, from the Trading section of Settings ($ or % of his account size):
    "trade_account_size": 0.0,      # what % limits are taken of (0: the live balance)
    "trade_size": 0.5,              # the size he wants: risk per trade ...
    "trade_size_unit": "%",         # ... as % of the account, $ risked, or fixed "lots"
    "trade_daily_loss": 2.0,        # daily loss limit: no new trades past it (the autopilot stops for the day)
    "trade_daily_loss_unit": "%",
    "trade_equity_floor": 0.0,      # equity must never go below this ($, 0: none)
    "trade_daily_target": 0.0,      # daily profit target: the autopilot stops for the day once it's reached
    "trade_daily_target_unit": "%",
    "auto_max_trades": 3,           # autopilot trades a day
    "auto_min_rr": 1.5,             # reward to risk at least this
    "auto_order_hours": 2.0,        # a planned entry (limit or stop order) not reached within this is cancelled
    "auto_min_stop_atr": 1.0,       # the stop is at least this many M15 ATRs from the entry (tighter: widened)
    "auto_news_min": 30,            # no new trades this many minutes before and after high-impact news (0 = off)
    "auto_symbols": ["XAUUSD"],     # what the autopilot looks at
    # Quiet hours (this PC's clock): the autopilot doesn't look at charts or ask the brains. Empty times: none.
    "auto_quiet_from": "04:00",     # every day from ...
    "auto_quiet_to": "10:30",       # ... until (thin market overnight)
    "auto_weekend_off": True,       # and from Saturday's quiet_from until Monday's quiet_to (markets shut)
}


UNITS = {"trade_size_unit": ("%", "$", "lots"), "trade_daily_loss_unit": ("%", "$"), "trade_daily_target_unit": ("%", "$")}


def limits():
    s = features.settings()
    return {k: s.get(k, v) for k, v in LIMITS.items()}


def save_limits(d):
    """The Trading section of Settings. Numbers are checked; real-money switches can only be turned OFF here
    (turning them on needs the click on a HUD card, via trading_settings)."""
    s = features.settings()
    for k, v in (d or {}).items():
        if k in UNITS:
            if v not in UNITS[k]:
                raise ValueError(f"{k} must be one of {', '.join(UNITS[k])}")
            s[k] = v
        elif k in ("trade_live", "auto_live"):
            if not v:
                s[k] = False
        elif k in ("auto_quiet_from", "auto_quiet_to"):
            v = str(v or "").strip()
            if v and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", v):
                raise ValueError(f"{k} must be a time like 04:00")
            s[k] = v.zfill(5) if v else ""
        elif k == "auto_weekend_off":
            s[k] = v in (True, 1, "1", "true", "on", "yes")
        elif k == "auto_symbols":
            s[k] = [str(x).strip().upper().replace("/", "")[:12] for x in (v if isinstance(v, list) else str(v).split(",")) if str(x).strip()][:4] or ["XAUUSD"]
        elif k in LIMITS:
            try:
                n = float(v or 0)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be a number")
            if n < 0:
                raise ValueError(f"{k} can't be negative")
            s[k] = int(n) if k == "auto_max_trades" else n
    features._save("settings.json", s)
    return limits()


def quiet_until(lim=None, now=None):
    """In his quiet hours (no chart checks, no brains): when they end, else None."""
    lim = lim or limits()
    now = now or datetime.datetime.now()
    hm = lambda v: datetime.time(*map(int, v.split(":"))) if v else None
    f, t = hm(lim.get("auto_quiet_from")), hm(lim.get("auto_quiet_to"))

    def quiet(d):
        x, wd = d.time(), d.weekday()  # Monday 0 ... Sunday 6
        if lim.get("auto_weekend_off") and f and t and ((wd == 5 and x >= f) or wd == 6 or (wd == 0 and x < t)):
            return True
        if not (f and t) or f == t:
            return False
        return f <= x < t if f < t else (x >= f or x < t)  # a window past midnight, e.g. 22:00 to 06:00

    if not quiet(now):
        return None
    d = now.replace(second=0, microsecond=0)
    for _ in range(4 * 24 * 60):  # minute by minute, at most 4 days
        d += datetime.timedelta(minutes=1)
        if not quiet(d):
            return d
    return None


def money(value, unit, base):
    """$ from a setting given in $ or % of the account."""
    return float(value) if unit == "$" else base * float(value) / 100


def base_size(acc, lim):
    return lim["trade_account_size"] or acc.balance


def day_state(mt5):
    """Today's starting equity and trade count (shared by his trades and the autopilot)."""
    st = _load(AUTO_STATE, {})
    today = datetime.date.today().isoformat()
    if st.get("date") != today:
        st = {"date": today, "start_equity": mt5.account_info().equity, "trades": 0}
        _save(AUTO_STATE, st)
    return st


def open_risk(mt5):
    """($ that all open trades lose if every stop is hit, [trades with no stop])."""
    total, naked = 0.0, []
    for p in mt5.positions_get() or []:
        if not p.sl:
            naked.append(f"#{p.ticket} {p.symbol}")
            continue
        info = mt5.symbol_info(p.symbol)
        lost = (p.price_current - p.sl) if p.type == 0 else (p.sl - p.price_current)
        total += max(0.0, lost / (info.trade_tick_size or info.point) * info.trade_tick_value * p.volume)
    return total, naked


def risk_check(mt5, lim, risk):
    """Why a new trade risking $risk breaks his limits (or None): the daily loss limit and the equity floor."""
    acc = mt5.account_info()
    st = day_state(mt5)
    base = base_size(acc, lim)
    daily = money(lim["trade_daily_loss"], lim["trade_daily_loss_unit"], base)
    lost = max(0.0, st["start_equity"] - acc.equity)
    if daily and lost + risk > daily:
        return (f"that could take today's loss to ${lost + risk:,.2f}, past his daily limit of ${daily:,.2f} "
                f"(down ${lost:,.2f} so far)")
    floor = lim["trade_equity_floor"]
    if floor:
        held, naked = open_risk(mt5)
        if naked:
            return f"his equity floor can't be protected while {', '.join(naked)} has no stop loss"
        worst = acc.equity - held - risk
        if worst < floor:
            return (f"if every stop were hit, equity would fall to ${worst:,.2f}, below his floor of ${floor:,.2f}")
    return None


def wanted_size(info, entry, stop, acc, lim):
    """Lots for the size he wants (Settings: % or $ risked, or fixed lots)."""
    if lim["trade_size_unit"] == "lots":
        step = info.volume_step or 0.01
        return round(int(min(float(lim["trade_size"]), lim["trade_max_lots"]) / step) * step, 2)
    return size_lots(info, entry, stop, money(lim["trade_size"], lim["trade_size_unit"], base_size(acc, lim)),
                     lim["trade_max_lots"])


def sizing(info, price, acc, lim):
    """The lot size calculator the brains get for one symbol: $ per 1.0 price move per lot, the risk per trade, and
    the lots (and $ at risk) for a range of stop distances, so they can see a wider stop just means fewer lots."""
    per = loss_per_lot(info, price, price + 1.0)  # $ per 1.0 move per 1 lot
    fixed = lim["trade_size_unit"] == "lots"
    risk = None if fixed else round(money(lim["trade_size"], lim["trade_size_unit"], base_size(acc, lim)), 2)
    out = {"usd_per_1.0_move_per_lot": round(per, 4), "min_lot": info.volume_min, "lot_step": info.volume_step}
    table = {}
    for d in (2, 3, 5, 8, 12, 16, 20, 30):
        lots = wanted_size(info, price, price - d, acc, lim)
        table[str(d)] = {"lots": lots, "usd_at_risk": round(lots * d * per, 2)} if lots else "too wide: even the smallest lot risks too much"
    out["stop_distance_to_lots"] = table
    if risk and per:
        out["risk_per_trade_usd"] = risk
        out["widest_stop_the_smallest_lot_allows"] = round(risk / (per * info.volume_min), 2)
    return out


def risk_rules(lim):
    """How risk works, for the brains: the stop goes where the chart needs it, and the lot size absorbs it."""
    if lim["trade_size_unit"] == "lots":
        return (f"Size: a fixed {lim['trade_size']} lots each trade, so a wider stop risks more money; 'sizing' shows "
                "the $ at risk for each stop distance. Keep the stop where the chart needs it, and skip the trade if that "
                "risk is too much for this account.\n")
    return ("Risk: every trade risks the same money, his setting ('sizing' > risk_per_trade_usd). The system works out "
            "the lot size from your stop with this lot size calculator: lots = risk / (stop distance x "
            "usd_per_1.0_move_per_lot), rounded down to the lot step. So put the stop where the setup is proven wrong "
            "(beyond the swing or level, with room for the spread and normal noise), even if that is wider than his "
            "usual stop: a wider stop means a smaller lot, the same money at risk. His typical stop distance is only a "
            "reference. 'stop_distance_to_lots' shows the lots for each distance; the stop can't be wider than "
            "widest_stop_the_smallest_lot_allows. Set the target at a real level that gives the minimum reward:risk; "
            "don't skip a good setup only because it needs a wider stop.\n")


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, obj):
    try:
        Path(path).write_text(json.dumps(obj, indent=1), encoding="utf-8")
    except OSError:
        pass


def _panel(ev):
    try:
        features._panel(ev)
    except OSError:
        pass


# ---------- MT5 ----------
def _mt5():
    import MetaTrader5 as mt5  # pip install MetaTrader5 (Windows only)
    # MetaTrader's initialize() starts the terminal when it isn't running: Jarvis only ever uses an MT5 that's
    # already open, and opens it himself only when asked (open_app)
    if os.name == "nt" and not mt5_pids():
        raise RuntimeError("MetaTrader 5 isn't open, and Jarvis doesn't open it by himself. If he wants live MT5 "
                           "data, ask whether to open it (open_app 'MetaTrader 5'); his journal still works without it.")
    exe = _mt5_exe() if os.name == "nt" else None
    if not (mt5.initialize(path=exe) if exe else mt5.initialize()):  # that MT5, when a broker's copy is open too
        raise RuntimeError(f"Can't reach MetaTrader 5 ({mt5.last_error()}). Is it open and logged in?")
    return mt5


def _mt5_exe():
    """Which MT5 to use: the plain "MetaTrader 5" install (not a broker's own copy like "EightCap MetaTrader 5"),
    else the one remembered from when MT5 last ran, else any install."""
    import glob
    hits = [p for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""))
            if root for p in glob.glob(os.path.join(root, "*", "terminal64.exe"))]
    plain = [p for p in hits if os.path.basename(os.path.dirname(p)).lower() == "metatrader 5"]
    if plain:
        return plain[0]
    seen = features._load("state.json", {}).get("mt5_exe")
    if seen and os.path.exists(seen):
        return seen
    return hits[0] if hits else None


def remember_mt5_exe():
    """While MT5 runs, note where it's installed (brokers install it under their own name)."""
    try:
        import psutil
        p = next((p for p in psutil.process_iter(["name", "exe"]) if (p.info["name"] or "").lower() == "terminal64.exe"), None)
        if p and p.info["exe"]:
            st = features._load("state.json", {})
            if st.get("mt5_exe") != p.info["exe"]:
                features._save("state.json", {**st, "mt5_exe": p.info["exe"]})
    except Exception:
        pass


def _minimise(name="terminal64.exe"):
    """Minimise MT5's windows (no focus stolen)."""
    import ctypes
    import psutil
    from ctypes import wintypes
    pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == name}
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and u.IsWindowVisible(hwnd) and not u.GetWindow(hwnd, 4):  # top-level, no owner
            found.append(hwnd)
        return True
    u.EnumWindows(each, 0)
    for h in found:
        u.ShowWindow(h, 7)  # SW_SHOWMINNOACTIVE
    return bool(found)


def mt5_pids(exe=None):
    """Running copies of that MT5 (by its install path; any MT5 when none is known)."""
    try:
        import psutil
    except ImportError:
        return []
    exe = os.path.normcase(exe or _mt5_exe() or "")
    out = []
    for p in psutil.process_iter(["name", "exe"]):
        if (p.info["name"] or "").lower() == "terminal64.exe" and (not exe or os.path.normcase(p.info["exe"] or "") == exe):
            out.append(p.pid)
    return out


def open_mt5(wait=90):
    """Open MT5 minimised (for the autopilot) and wait until it's logged in. -> True if Jarvis opened it."""
    if os.name != "nt" or mt5_pids():
        return False
    exe = _mt5_exe()
    if not exe:
        raise RuntimeError("Couldn't find MetaTrader 5 on this PC. Open it once yourself so Jarvis learns where it is.")
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7  # start minimised, without taking focus
    subprocess.Popen([exe], startupinfo=si, cwd=os.path.dirname(exe))
    import MetaTrader5 as mt5
    end = time.time() + wait
    while time.time() < end:
        time.sleep(2)
        try:
            _minimise()  # MT5 sometimes restores its window while it loads
        except Exception:
            pass
        if mt5_pids(exe) and mt5.initialize(path=exe) and mt5.account_info():
            time.sleep(2)
            try:
                _minimise()
            except Exception:
                pass
            return True
    raise RuntimeError("MetaTrader 5 opened but didn't log in within a minute and a half. Check it's logged in.")


def close_mt5():
    """Close MT5 the normal way (like clicking X). Stops and targets stay on the broker's server."""
    try:
        import MetaTrader5 as mt5
        mt5.shutdown()
    except Exception:
        pass
    if os.name == "nt":  # only that MT5: a broker's own copy that's open stays open
        for pid in mt5_pids():
            subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)


def _symbol(mt5, name):
    s = name.upper().replace("/", "")
    if s in ("GOLD",):
        s = "XAUUSD"
    if mt5.symbol_info(s) is None:  # brokers sometimes add suffixes, e.g. XAUUSD.a
        names = sorted((x.name for x in mt5.symbols_get() if s in x.name.upper()), key=len)
        if not names:
            raise ValueError(f"Your broker has no symbol like {name}")
        s = names[0]
    mt5.symbol_select(s, True)
    return s


def is_demo(mt5):
    return mt5.account_info().trade_mode == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)


def _filling(mt5, info):
    fm = getattr(info, "filling_mode", 0)
    return mt5.ORDER_FILLING_FOK if fm & 1 else mt5.ORDER_FILLING_IOC if fm & 2 else mt5.ORDER_FILLING_RETURN


def loss_per_lot(info, entry, stop):
    """Dollars lost per 1.0 lot if the stop is hit."""
    tick = info.trade_tick_size or info.point
    return abs(entry - stop) / tick * info.trade_tick_value


def size_lots(info, entry, stop, risk_money, max_lots):
    """The lot size that risks about risk_money, rounded down to the broker's step, within limits."""
    per = loss_per_lot(info, entry, stop)
    if per <= 0:
        return 0.0
    step = info.volume_step or 0.01
    lots = int(min(risk_money / per, max_lots, info.volume_max) / step) * step
    return round(lots, 2) if lots >= info.volume_min else 0.0


def check_levels(side, entry, stop, target):
    """Problems with the stop and target, else []."""
    bad = []
    if not stop:
        bad.append("a stop loss is required")
    elif side == "buy" and stop >= entry:
        bad.append(f"a buy's stop ({stop}) must be below the entry ({entry})")
    elif side == "sell" and stop <= entry:
        bad.append(f"a sell's stop ({stop}) must be above the entry ({entry})")
    if target and side == "buy" and target <= entry:
        bad.append(f"a buy's target ({target}) must be above the entry ({entry})")
    elif target and side == "sell" and target >= entry:
        bad.append(f"a sell's target ({target}) must be below the entry ({entry})")
    return bad


TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}


def _chart(mt5, s, tf="M15", bars=60, at=None):
    """The last `bars` candles; at (MT5 server time in seconds, for the test run): only candles closed by then."""
    if at is None:
        rates = mt5.copy_rates_from_pos(s, getattr(mt5, "TIMEFRAME_" + tf), 0, bars)
    else:
        rates = mt5.copy_rates_from(s, getattr(mt5, "TIMEFRAME_" + tf), int(at), bars + 1)
        rates = [c for c in (rates if rates is not None else []) if int(c["time"]) + TF_SECONDS[tf] <= at][-bars:]
    return [[round(float(c["open"]), 5), round(float(c["high"]), 5), round(float(c["low"]), 5), round(float(c["close"]), 5)]
            for c in (rates if rates is not None else [])]


# ---------- Trades he asks for: tickets he confirms with a click ----------
def propose_trade(symbol, side, stop, target=None, lots=None, risk_pct=None, order="market", price=None, note=""):
    """A trade ticket on the HUD (nothing is sent until he clicks Confirm)."""
    side = str(side).lower()
    if side not in ("buy", "sell"):
        return {"error": "side must be buy or sell"}
    mt5 = _mt5()
    lim = limits()
    if not is_demo(mt5) and not lim["trade_live"]:
        return {"error": "This is a real-money account and live trading is off. He can switch it on with "
                         "trading_settings(live=true), which asks him to confirm on the HUD."}
    s = _symbol(mt5, symbol)
    info, tick = mt5.symbol_info(s), mt5.symbol_info_tick(s)
    order = order if order in ("market", "limit", "stop") else "market"
    entry = (tick.ask if side == "buy" else tick.bid) if order == "market" else float(price or 0)
    if not entry:
        return {"error": "A limit or stop order needs its price."}
    stop, target = float(stop or 0), float(target or 0)
    bad = check_levels(side, entry, stop, target)
    if bad:
        return {"error": "; ".join(bad)}
    acc = mt5.account_info()
    bal = base_size(acc, lim)
    if lots:
        lots = min(float(lots), lim["trade_max_lots"])
    elif risk_pct:
        lots = size_lots(info, entry, stop, bal * float(risk_pct) / 100, lim["trade_max_lots"])
    else:
        lots = wanted_size(info, entry, stop, acc, lim)  # the size he set in Settings
    if not lots:
        return {"error": "The stop is too far for even the smallest lot size within his risk limit."}
    risk = loss_per_lot(info, entry, stop) * lots
    if risk > bal * lim["trade_max_risk_pct"] / 100:
        return {"error": f"That risks ${risk:,.2f}, over his limit of {lim['trade_max_risk_pct']}% "
                         f"(${bal * lim['trade_max_risk_pct'] / 100:,.2f}). Use a smaller size or closer stop."}
    why = risk_check(mt5, lim, risk)
    if why:
        return {"error": "Not allowed: " + why + "."}
    t = {"id": uuid.uuid4().hex[:10], "kind": "open", "symbol": s, "side": side, "order": order, "entry": entry,
         "stop": stop, "target": target or None, "lots": lots, "risk": round(risk, 2),
         "reward": round(loss_per_lot(info, entry, target) * lots, 2) if target else None,
         "digits": info.digits, "note": str(note)[:120], "demo": is_demo(mt5), "expires": time.time() + TICKET_SECONDS}
    return _ticket(t, _chart(mt5, s))


def propose_change(ticket, stop=None, target=None, close=False, lots=None):
    """A ticket to move a trade's stop/target, or close it (all or part)."""
    mt5 = _mt5()
    pos = next(iter(mt5.positions_get(ticket=int(ticket)) or []), None)
    if not pos:
        return {"error": f"No open trade #{ticket}."}
    side = "buy" if pos.type == 0 else "sell"
    info = mt5.symbol_info(pos.symbol)
    t = {"id": uuid.uuid4().hex[:10], "symbol": pos.symbol, "side": side, "position": pos.ticket, "entry": pos.price_open,
         "digits": info.digits, "demo": is_demo(mt5), "expires": time.time() + TICKET_SECONDS, "pnl": pos.profit}
    if close:
        t.update(kind="close", lots=min(float(lots or pos.volume), pos.volume), stop=pos.sl or None, target=pos.tp or None)
    else:
        new_stop = pos.sl if stop is None else float(stop)
        new_target = pos.tp if target is None else float(target)
        bad = check_levels(side, pos.price_current if new_stop else pos.price_open, new_stop, new_target) if new_stop else \
            ["keep a stop loss on it"]
        if bad:
            return {"error": "; ".join(bad)}
        t.update(kind="modify", lots=pos.volume, stop=new_stop, target=new_target or None, old_stop=pos.sl, old_target=pos.tp)
    return _ticket(t, _chart(mt5, pos.symbol))


def _ticket(t, chart):
    tickets = {k: v for k, v in _load(PENDING, {}).items() if v["expires"] > time.time()}
    tickets[t["id"]] = t
    _save(PENDING, tickets)
    _panel({"type": "trade_ticket", **t, "chart": chart, "seconds": TICKET_SECONDS})
    return {"ticket": t["id"], "shown": True, "risk": t.get("risk"), "lots": t.get("lots"),
            "note": "The ticket is on the HUD. He must click Confirm on it to send it (voice can't). Tell him the "
                    "key numbers in one sentence."}


def confirm(ticket_id, cancel=False):
    """His click on a HUD ticket. Sends the order (re-checked against the live price) or cancels it."""
    tickets = _load(PENDING, {})
    t = tickets.pop(ticket_id, None)
    _save(PENDING, tickets)
    if not t:
        return {"error": "That ticket isn't waiting any more."}
    if cancel:
        return {"cancelled": True}
    if t["expires"] < time.time():
        return {"error": "That ticket expired (the price has moved). Ask again for a fresh one."}
    if t["kind"] == "live":
        s = features.settings()
        features._save("settings.json", {**s, t["key"]: True})
        return {"done": True, "text": t["text"] + " is on."}
    mt5 = _mt5()
    if not is_demo(mt5) and not limits()["trade_live"]:
        return {"error": "Live trading is off."}
    if t["kind"] == "open":
        why = risk_check(mt5, limits(), t["risk"])  # things may have changed since the ticket was made
        if why:
            return {"error": "Not sent: " + why + "."}
    r = send(mt5, t, MAGIC_MANUAL)
    if r.get("done") and t["kind"] == "open":
        st = day_state(mt5)
        st["trades"] = st.get("trades", 0) + 1
        _save(AUTO_STATE, st)
    return r


def send(mt5, t, magic):
    info, tick = mt5.symbol_info(t["symbol"]), mt5.symbol_info_tick(t["symbol"])
    if t["kind"] == "modify":
        req = {"action": mt5.TRADE_ACTION_SLTP, "position": t["position"], "symbol": t["symbol"],
               "sl": t["stop"] or 0.0, "tp": t["target"] or 0.0}
    elif t["kind"] == "close":
        buy = t["side"] == "sell"  # closing a sell is a buy
        req = {"action": mt5.TRADE_ACTION_DEAL, "position": t["position"], "symbol": t["symbol"], "volume": t["lots"],
               "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL, "price": tick.ask if buy else tick.bid,
               "deviation": 30, "magic": magic, "comment": "Jarvis close", "type_filling": _filling(mt5, info)}
    else:
        buy = t["side"] == "buy"
        if t["order"] == "market":
            entry = tick.ask if buy else tick.bid
            bad = check_levels(t["side"], entry, t["stop"], t["target"])  # the price moved past the stop/target?
            if bad:
                return {"error": "The price has moved: " + "; ".join(bad)}
            req = {"action": mt5.TRADE_ACTION_DEAL, "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
                   "price": entry}
        else:
            kind = {("buy", "limit"): mt5.ORDER_TYPE_BUY_LIMIT, ("sell", "limit"): mt5.ORDER_TYPE_SELL_LIMIT,
                    ("buy", "stop"): mt5.ORDER_TYPE_BUY_STOP, ("sell", "stop"): mt5.ORDER_TYPE_SELL_STOP}[(t["side"], t["order"])]
            req = {"action": mt5.TRADE_ACTION_PENDING, "type": kind, "price": t["entry"],
                   "type_time": mt5.ORDER_TIME_GTC}
        req.update(symbol=t["symbol"], volume=t["lots"], sl=t["stop"], tp=t["target"] or 0.0, deviation=30,
                   magic=magic, comment="Jarvis" if magic == MAGIC_MANUAL else "Jarvis autopilot",
                   type_filling=_filling(mt5, info))
    r = mt5.order_send(req)
    if r is None or r.retcode not in (mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_PLACED", 10008)):
        why = getattr(r, "comment", "") or str(mt5.last_error())
        return {"error": f"MT5 refused it: {why} (code {getattr(r, 'retcode', '?')})."}
    did = (f"{t['side']} {t['lots']} {t['symbol']}" if t["kind"] == "open" else
           f"moved the stop/target on #{t['position']}" if t["kind"] == "modify" else f"closed {t['lots']} of #{t['position']}")
    return {"done": True, "text": f"Done: {did}" + (f" at {r.price}" if getattr(r, "price", 0) else "") + ".",
            "order": getattr(r, "order", None)}


def trading_settings(live=None, auto_live=None, **changes):
    """Change his trading limits (the same as the Trading section of Settings). Switching real money ON needs his
    click on a HUD card; everything else is set straight away."""
    new = {k: v for k, v in changes.items() if v is not None and (k in LIMITS or k in UNITS)}
    if live is False:
        new["trade_live"] = False
    if auto_live is False:
        new["auto_live"] = False
    try:
        save_limits(new)
    except ValueError as e:
        return {"error": str(e)}
    out = {"limits": limits()}
    for key, on, text in (("trade_live", live, "Live trading (trades you confirm, on your real-money account)"),
                          ("auto_live", auto_live, "The autopilot on your real-money account")):
        if on:
            t = {"id": uuid.uuid4().hex[:10], "kind": "live", "key": key, "text": text, "expires": time.time() + TICKET_SECONDS}
            tickets = _load(PENDING, {})
            tickets[t["id"]] = t
            _save(PENDING, tickets)
            _panel({"type": "trade_ticket", **t, "seconds": TICKET_SECONDS})
            out["note"] = "Switching that on needs his click on the HUD card (real money at risk)."
    return out


# ---------- How he trades (from his journal), for the autopilot ----------
def his_style(path=None):
    path = Path(path or HERE / "mt5_positions.csv")
    try:
        rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))[-300:]
    except OSError:
        return "No trading history found."
    if not rows:
        return "No trading history found."
    f = lambda r, k: float(r.get(k) or 0)
    wins = [r for r in rows if f(r, "pnl") > 0]
    syms, hours, holds, stops, rr = {}, {}, [], [], []
    for r in rows:
        syms[r["symbol"]] = syms.get(r["symbol"], 0) + 1
        try:
            o = datetime.datetime.fromisoformat(r["opened"][:19])
            c = datetime.datetime.fromisoformat(r["closed"][:19])
            hours[o.hour] = hours.get(o.hour, 0) + 1
            holds.append((c - o).total_seconds() / 60)
        except (KeyError, ValueError):
            pass
        if f(r, "stop") and f(r, "entry"):
            stops.append(abs(f(r, "entry") - f(r, "stop")))
            if f(r, "tp"):
                rr.append(abs(f(r, "tp") - f(r, "entry")) / max(1e-9, abs(f(r, "entry") - f(r, "stop"))))
    med = lambda v: sorted(v)[len(v) // 2] if v else None
    top_h = sorted(hours, key=hours.get, reverse=True)[:4]
    return (f"His last {len(rows)} trades: {', '.join(f'{k} {v}' for k, v in sorted(syms.items(), key=lambda x: -x[1])[:4])}; "
            f"win rate {100 * len(wins) // len(rows)}%; typical hold {med(holds) and round(med(holds))} min; "
            f"typical stop distance {med(stops) and round(med(stops), 2)}; typical reward:risk {med(rr) and round(med(rr), 2)}; "
            f"busiest opening hours (MT5 server time) {top_h}.")


# ---------- The two brains ----------
def _json_in(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


def ask_claude(prompt, ds=False):
    import deepseek
    import usage
    cmd = [CLAUDE, "-p", "--output-format", "json", "--model", "sonnet", "--tools", "",
           "--setting-sources", "project", "--strict-mcp-config", "--disable-slash-commands",
           "--system-prompt", "You are a careful trading analyst. Reply with one JSON object only."]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=300, cwd=HERE,
                       env=deepseek.env() if ds else None, creationflags=NO_WINDOW)
    if r.returncode:
        raise RuntimeError((r.stdout + r.stderr)[-300:])
    try:
        out = json.loads(r.stdout)
    except ValueError:
        return r.stdout
    usage.claude(out, "autopilot", ds)
    if out.get("is_error"):
        raise RuntimeError(str(out.get("result"))[-300:])
    return out.get("result", "")


def ask_chatgpt(prompt):
    import gpt_brain
    cmd = gpt_brain.command(None)
    cmd[cmd.index("-s") + 1] = "read-only"  # it only answers: it runs nothing
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300, cwd=HERE, creationflags=NO_WINDOW)
    import usage
    usage.codex(r.stdout.splitlines(), "autopilot")
    _, texts, err = gpt_brain.parse(r.stdout.splitlines())
    if err or not texts:  # say why: Codex's own error, or the last thing it printed
        why = err or next((l.strip() for l in reversed((r.stderr or "").splitlines() + r.stdout.splitlines())
                           if l.strip() and "WARN" not in l), "") or f"Codex exited with code {r.returncode} and said nothing"
        print(datetime.datetime.now(), "ChatGPT (autopilot) gave no answer:", (r.stderr or "")[-600:], r.stdout[-400:])
        raise RuntimeError(why[:300])
    return texts[-1]


def brains():
    """The two brains to ask: ChatGPT then Claude, or DeepSeek standing in for whichever is missing. The first one
    screens: the second (usually Claude, his main brain for chatting) is only asked when the first sees a trade."""
    import deepseek
    import gpt_brain
    out = []
    if CLAUDE and not IS_OUT("Claude"):
        out.append(("Claude", lambda p: ask_claude(p)))
    if gpt_brain.available() and not IS_OUT("ChatGPT"):
        out.append(("ChatGPT", ask_chatgpt))
    import gemini_brain
    if len(out) < 2 and gemini_brain.available() and not IS_OUT("Gemini"):
        out.append(("Gemini", gemini_brain.ask))
    if len(out) < 2 and CLAUDE and deepseek.available() and not IS_OUT("DeepSeek"):
        out.append(("DeepSeek", lambda p: ask_claude(p, ds=True)))
    return sorted(out, key=lambda b: b[0] != "ChatGPT")[:2]  # ChatGPT first: it screens every check


def plan_entry(pick, side, bid, ask):
    """The entry a brain planned -> (order, price): 'market' now, or a limit/stop order at its price. A limit or stop
    price the market has already reached becomes a market entry; one on the wrong side of the price is refused."""
    order = str(pick.get("order") or "market").lower()
    now = ask if side == "buy" else bid
    if order not in ("limit", "stop"):
        return "market", now
    try:
        price = float(pick["entry"])
    except (KeyError, TypeError, ValueError):
        return "market", now
    below = price < now
    if (order == "limit") == (side == "buy"):  # buy limit / sell stop: below the price
        return (order, price) if below else ("market", now) if order == "limit" else (None, None)
    return (order, price) if not below and price != now else ("market", now) if order == "stop" else (None, None)


def agree(a, b, side_entry, digits, bid=None, ask=None, min_stop=0.0):
    """Both brains' picks -> the trade (or None). Same symbol and direction (the second brain confirms it), and the
    first brain's whole plan: its entry (now, or a limit/stop price), stop and target. A stop closer than min_stop
    (price distance) is widened to it; the reward:risk is then measured with the wider stop."""
    if not a or not b or a.get("action") not in ("buy", "sell") or a.get("action") != b.get("action"):
        return None
    if str(a.get("symbol", "")).upper() != str(b.get("symbol", "")).upper():
        return None
    side = a["action"]
    order, entry = plan_entry(a, side, side_entry if bid is None else bid, side_entry if ask is None else ask)
    if order is None:
        return None
    try:  # the first brain's own plan, kept whole (mixing one brain's stop with the other's entry breaks both)
        stop, target = float(a["stop"]), float(a["target"])
    except (KeyError, TypeError, ValueError):
        return None
    if min_stop and abs(entry - stop) < min_stop:  # too tight for the market's normal moves: widen it
        stop = entry - min_stop if side == "buy" else entry + min_stop
    if check_levels(side, entry, stop, target):
        return None
    return {"symbol": a["symbol"], "side": side, "order": order, "entry": round(entry, digits),
            "stop": round(stop, digits), "target": round(target, digits),
            "rr": abs(target - entry) / abs(entry - stop), "confidence": min(int(a.get("confidence", 0)), int(b.get("confidence", 0))),
            "why": [str(a.get("reason", ""))[:200], str(b.get("reason", ""))[:200]]}


def atr(candles, n=14):
    """Average true range of [open, high, low, close] candles (the last n)."""
    trs = [max(h - lo, abs(h - p[3]), abs(lo - p[3])) for p, (_o, h, lo, _c) in zip(candles, candles[1:])][-n:]
    return sum(trs) / len(trs) if trs else 0.0


def snapshot(mt5, s, info, bid, ask, acc, lim, at=None):
    """What the brains see of one symbol: prices, spread, the M15 ATR, the lot size calculator and the M15, H1 and
    H4 candles."""
    m15 = _chart(mt5, s, "M15", 48, at)
    return {"bid": bid, "ask": ask, "spread": round(ask - bid, info.digits), "digits": info.digits,
            "atr_m15": round(atr(m15), info.digits), "sizing": sizing(info, bid, acc, lim),
            "M15": m15, "H1": _chart(mt5, s, "H1", 48, at), "H4": _chart(mt5, s, "H4", 30, at)}


def build_prompt(market, acc, lim):
    return (
        "Decide whether to open ONE trade now, trading the way this trader does. Be selective: take a trade when "
        "there is a real setup with a clear plan, and say 'none' when there isn't.\n"
        f"Trader's style: {his_style()}\n"
        f"Account: balance {acc.balance:.2f}, equity {acc.equity:.2f}.\n"
        + risk_rules(lim) +
        f"Minimum reward:risk {lim['auto_min_rr']} (target distance / stop distance, measured from the entry).\n"
        f"Stop: at least {lim['auto_min_stop_atr']:g} x atr_m15 from the entry, beyond the level that proves the idea "
        "wrong; tighter stops get hit by normal noise (the system widens them). Trade with the H1/H4 trend unless "
        "there is a clear reversal, and put the target before the next opposing level.\n"
        "Entry: 'market' enters now. When the setup needs a trigger (a breakout, or a pullback to a level), plan it "
        "instead of waiting: 'stop' enters when price reaches your entry price moving your way (a buy stop above "
        "resistance, a sell stop below support), 'limit' enters when price comes back to it (a buy limit at support, a "
        f"sell limit at resistance). A planned entry not reached within {lim['auto_order_hours']:g} hours is cancelled. "
        "So 'no confirmed breakout yet' or 'wait for the retest' are reasons to plan the entry, not to say none.\n"
        "Candles are [open, high, low, close], oldest first, MT5 server time:\n"
        + json.dumps(market) +
        '\nReply with one JSON object only: {"action": "buy" | "sell" | "none", "symbol": "...", '
        '"order": "market" | "stop" | "limit", "entry": price (for stop or limit), '
        '"stop": price, "target": price, "confidence": 0-100, "reason": "one sentence"}')


def ask_brains(prompt, show=print):
    """ChatGPT screens; the second brain is only asked when the first sees a trade. -> (picks, names)"""
    picks, names = [], []
    for name, ask in brains():
        if picks and str((picks[0] or {}).get("action")).lower() not in ("buy", "sell"):
            break  # the first brain sees no trade (or didn't answer): the second isn't asked, saving its limit
        try:
            picks.append(_json_in(ask(prompt)))
        except Exception as e:
            picks.append(None)
            show(f"{name} didn't answer: {str(e)[:80]}")
        names.append(name)
    return picks, names


# ---------- The autopilot ----------
def awake(on):
    """Keep Windows from sleeping (ES_CONTINUOUS | ES_SYSTEM_REQUIRED) while the autopilot's thread runs; the
    displays may still turn off. Off again when it stops."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x1 if on else 0))


class Autopilot:
    def __init__(self):
        self.on, self.thread, self.last = False, None, {}

    def status(self):
        st = _load(AUTO_STATE, {})
        return {"on": self.on, "today": st.get("date"), "trades_today": st.get("trades", 0),
                "start_equity": st.get("start_equity"), "last": self.last, "limits": limits(),
                "quiet_until": (lambda u: u and f"{u:%a %H:%M}")(quiet_until())}

    def start(self):
        if self.on:
            return {"already": True, **self.status()}
        opened = open_mt5()  # he asked for the autopilot: Jarvis opens MT5 himself (minimised) if it's closed
        remember_mt5_exe()
        mt5 = _mt5()
        why = ready(mt5)
        if why:
            return {"error": why + "."}
        lim = limits()
        if not is_demo(mt5) and not lim["auto_live"]:
            return {"error": "This is a real-money account and the autopilot is set to demo only. Open a demo "
                             "account in MT5, or switch it on for live with trading_settings(auto_live=true), "
                             "which he confirms on the HUD."}
        if len(brains()) < 2:
            return {"error": "The autopilot needs two brains to agree, and only one is set up (Claude, ChatGPT or DeepSeek)."}
        self.on = True
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        self.show("Autopilot on")
        out = {"started": True, **self.status()}
        if opened:
            out["mt5"] = "Opened MetaTrader 5 minimised."
        if out["quiet_until"]:
            out["note"] = f"It's quiet hours: the autopilot starts checking charts at {out['quiet_until']}."
        return out

    def stop(self, why="Stopped", close=False):
        """close: he stopped it himself, so MT5 closes too (the autopilot stopping itself, e.g. at the loss limit,
        leaves MT5 open)."""
        self.on = False
        self.show(why)
        out = {"stopped": True, "note": "Its open trades keep their stops and targets on the broker's server; ask to close them if he wants."}
        if close:
            close_mt5()
            out["mt5"] = "Closed MetaTrader 5."
        return out

    def show(self, msg):
        self.last = {**self.last, "msg": msg, "at": datetime.datetime.now().strftime("%H:%M")}
        if not features.focus():  # roleplay, D&D or incognito: it keeps trading, but its panel stays out of the way
            _panel({"type": "autopilot", **self.status()})

    def say(self, text):
        import server_bridge
        server_bridge.say(text)

    def loop(self):
        next_look = 0.0
        awake(True)  # asleep, it couldn't trade: the PC stays on (the screens can still turn off)
        try:
            self._loop(next_look)
        finally:
            awake(False)

    def _loop(self, next_look):
        while self.on:
            try:
                if os.name == "nt" and not mt5_pids():
                    open_mt5()  # MT5 was closed while the autopilot runs: open it again (minimised)
                self.manage()  # trades already open keep being looked after, quiet hours or not
                until = quiet_until()
                if until:
                    msg = f"Quiet hours: not checking charts until {until:%a %H:%M}."
                    if getattr(self, "_quiet", None) != msg:
                        self._quiet = msg
                        self.show(msg)
                elif time.time() >= next_look:
                    self._quiet = None
                    self.cycle()
                    now = time.time()
                    next_look = now - now % 900 + 900 + 20  # just after each 15-minute candle closes
            except Exception as e:
                self.show(f"Error: {type(e).__name__}: {str(e)[:120]}")
            for _ in range(60):
                if not self.on:
                    return
                time.sleep(1)

    def manage(self):
        """Break-even at 1R for the autopilot's own trades; a review of each one that has closed."""
        mt5 = _mt5()
        try:
            import autoreview
            autoreview.check_closed(mt5, self.say)
        except Exception as e:
            print("autopilot review:", repr(e)[:160])
        hours = limits()["auto_order_hours"]
        for o in mt5.orders_get() or []:
            tick = o.magic == MAGIC_AUTO and mt5.symbol_info_tick(o.symbol)
            if tick and tick.time - o.time_setup > hours * 3600:
                r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
                if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                    self.show(f"Cancelled its planned entry at {o.price_open}: not reached in {hours:g} h")
        for p in mt5.positions_get() or []:
            if p.magic != MAGIC_AUTO or not p.sl:
                continue
            risk = abs(p.price_open - p.sl)
            gain = (p.price_current - p.price_open) if p.type == 0 else (p.price_open - p.price_current)
            at_be = (p.type == 0 and p.sl >= p.price_open) or (p.type == 1 and p.sl <= p.price_open)
            if risk and gain >= risk and not at_be:
                r = send(mt5, {"kind": "modify", "position": p.ticket, "symbol": p.symbol, "stop": p.price_open,
                               "target": p.tp or None}, MAGIC_AUTO)
                if r.get("done"):
                    self.say(f"Autopilot: moved the {p.symbol} stop to break-even.")

    def guards(self, mt5, lim, st):
        """Why it mustn't trade now (or None)."""
        acc = mt5.account_info()
        if not is_demo(mt5) and not lim["auto_live"]:
            return "real-money account and the autopilot is demo only"
        base = base_size(acc, lim)
        lost = st["start_equity"] - acc.equity
        daily = money(lim["trade_daily_loss"], lim["trade_daily_loss_unit"], base)
        if daily and lost >= daily:
            self.on = False
            self.say(f"Autopilot stopped for today: down ${lost:,.0f}, your daily loss limit.")
            return f"daily loss limit hit (down ${lost:,.2f})"
        target = money(lim["trade_daily_target"], lim["trade_daily_target_unit"], base)
        if target and -lost >= target:
            self.on = False
            self.say(f"Autopilot stopped for today: up ${-lost:,.0f}, your daily profit target. Nicely done.")
            return f"daily profit target reached (up ${-lost:,.2f})"
        if lim["trade_equity_floor"] and acc.equity <= lim["trade_equity_floor"]:
            self.on = False
            return "equity is at his floor"
        if st["trades"] >= lim["auto_max_trades"]:
            return f"{st['trades']} trades today, its limit"
        if any(p.magic == MAGIC_AUTO for p in mt5.positions_get() or []):
            return "it already has a trade open"
        if any(o.magic == MAGIC_AUTO for o in mt5.orders_get() or []):
            return "its planned entry is waiting to be reached"
        if lim.get("auto_news_min"):
            try:
                import trading
                near = trading.news_near(lim["auto_news_min"])
            except Exception:
                near = []  # no calendar right now: trade as normal
            if near:
                e = near[0]
                return f"high-impact news ({e['currency']} {e['event']} at {e['time'][11:]}): waiting {lim['auto_news_min']:g} min either side"
        try:
            import trading
            soon = [e for e in trading.upcoming_news(0.5)]
            if soon:
                return f"high-impact news soon ({soon[0]['currency']} {soon[0]['event']})"
        except Exception:
            pass
        return None

    def cycle(self):
        mt5 = _mt5()
        lim = limits()
        st = day_state(mt5)
        why = self.guards(mt5, lim, st)
        if why:
            self.show(f"Waiting: {why}")
            return
        acc = mt5.account_info()
        market = {}
        for raw in lim["auto_symbols"]:
            s = _symbol(mt5, raw)
            info, tick = mt5.symbol_info(s), mt5.symbol_info_tick(s)
            if time.time() - tick.time > 600:
                continue  # no fresh prices: market closed
            market[s] = snapshot(mt5, s, info, tick.bid, tick.ask, acc, lim)
        if not market:
            self.show("Waiting: the market is closed")
            return
        picks, names = ask_brains(build_prompt(market, acc, lim), self.show)
        self.log({"at": datetime.datetime.now().isoformat(timespec="seconds"), "brains": dict(zip(names, picks))})
        if len(picks) == 1 and picks[0]:
            why = str(picks[0].get("reason", ""))[:110]
            self.show(f"No trade: {names[0]} sees no clear setup right now." + (f" {why}" if why else ""))
            return
        if len(picks) < 2 or not all(picks):
            self.show("No trade: both brains must answer")
            return
        a = picks[0]
        s = next((k for k in market if k.upper().startswith(str(a.get("symbol", "")).upper()[:6])), None)
        if not s:
            self.show(self.no_trade(names, picks))
            return
        tick, info = mt5.symbol_info_tick(s), mt5.symbol_info(s)
        deal = agree({**a, "symbol": s}, {**picks[1], "symbol": s if str(picks[1].get("symbol", "")).upper()[:6] == s.upper()[:6] else picks[1].get("symbol")},
                     None, info.digits, tick.bid, tick.ask, market[s]["atr_m15"] * lim["auto_min_stop_atr"])
        if not deal:
            self.show(self.no_trade(names, picks))
            return
        if deal["rr"] < lim["auto_min_rr"]:
            self.show(f"No trade: both said {deal['side']} {s}, but reward:risk is only {deal['rr']:.1f}")
            return
        entry = deal["entry"]
        lots = wanted_size(info, entry, deal["stop"], acc, lim)
        if not lots:
            self.show("No trade: the stop is too far for the smallest lot within the risk limit")
            return
        why = risk_check(mt5, lim, loss_per_lot(info, entry, deal["stop"]) * lots)
        if why:
            self.show("No trade: " + why)
            return
        t = {"kind": "open", "symbol": s, "side": deal["side"], "order": deal["order"], "entry": entry, "stop": deal["stop"],
             "target": deal["target"], "lots": lots}
        r = send(mt5, t, MAGIC_AUTO)
        self.log({"at": datetime.datetime.now().isoformat(timespec="seconds"), "trade": t, "result": r, "why": deal["why"]})
        if r.get("done"):
            st["trades"] += 1
            _save(AUTO_STATE, st)
            risk = loss_per_lot(info, entry, deal["stop"]) * lots
            how = "" if deal["order"] == "market" else f" {deal['order']} order at {entry} (cancelled if not reached in {lim['auto_order_hours']:g} h)"
            line = (f"Autopilot: {deal['side']} {lots} {s}{how}, stop {deal['stop']}, target {deal['target']}, "
                    f"risking ${risk:,.0f}. Both brains agreed: {deal['why'][0]}")
            self.say(line)
            import alerts
            alerts.notify(line, "Autopilot trade opened", tags="moneybag")
            self.show(f"Traded: {deal['side']} {lots} {s}")
        else:
            self.show("Trade refused: " + r.get("error", "?"))

    @staticmethod
    def no_trade(names, picks):
        """'No trade: both brains see no setup (Claude: ...)' for the card: what each said, and why."""
        acts = [str((p or {}).get("action") or "no answer") for p in picks]
        why = next((str(p.get("reason", ""))[:110] for p in picks if p and p.get("reason")), "")
        head = (f"both brains see no clear setup right now" if acts == ["none", "none"] else
                f"they disagree ({names[0]}: {acts[0]}, {names[1]}: {acts[1]})")
        return f"No trade: {head}." + (f" {names[0]}: {why}" if why else "")

    def log(self, entry):
        log = _load(AUTO_LOG, [])[-500:]
        log.append(entry)
        _save(AUTO_LOG, log)


AUTO = Autopilot()


def trading_now():
    """Is the autopilot running (in the running Jarvis)?"""
    import server_bridge
    if server_bridge.IN_SERVER:
        return AUTO.on
    try:
        return bool(server_bridge.post("/api/autopilot", {"status": True}, timeout=5).get("on"))
    except OSError:
        return False


def ready(mt5):
    """Why MT5 can't take trades from Jarvis right now (or None)."""
    term, acc = mt5.terminal_info(), mt5.account_info()
    if term is not None and not getattr(term, "connected", True):
        return "MT5 isn't connected to the broker"
    if term is not None and not term.trade_allowed:
        return "Algo Trading is off in MT5: click the Algo Trading button on MT5's toolbar so it turns green"
    if acc is not None and not getattr(acc, "trade_allowed", True):
        return "this account doesn't allow trading (an investor or read-only login?)"
    return None


def test_trade(symbol=None):
    """Prove Jarvis can trade: the smallest buy on a demo account, with a stop and target, closed again after a few
    seconds. Each step is shown on the HUD and the result spoken."""
    steps = []

    def step(text, ok=True):
        steps.append({"text": text, "ok": ok})
        _panel({"type": "trade_test", "steps": steps})
    try:
        mt5 = _mt5()
        step("MT5 is open and logged in")
        why = ready(mt5)
        if why:
            step(why, False)
            return _test_end(steps, False)
        if not is_demo(mt5):
            step("This is a real-money account: the test only runs on a demo account", False)
            return _test_end(steps, False)
        s = _symbol(mt5, symbol or limits()["auto_symbols"][0])
        info, tick = mt5.symbol_info(s), mt5.symbol_info_tick(s)
        if time.time() - tick.time > 600:
            step(f"{s} has no fresh prices: the market looks closed", False)
            return _test_end(steps, False)
        gap = max(tick.ask * 0.003, (getattr(info, "trade_stops_level", 0) or 0) * info.point * 3)
        t = {"kind": "open", "symbol": s, "side": "buy", "order": "market", "entry": tick.ask,
             "stop": round(tick.ask - gap, info.digits), "target": round(tick.ask + gap, info.digits),
             "lots": info.volume_min}
        r = send(mt5, t, MAGIC_TEST)
        if not r.get("done"):
            step("Opening failed: " + r.get("error", "?"), False)
            return _test_end(steps, False)
        step(f"Opened: buy {t['lots']} {s}{r['text'].split(s, 1)[1][:-1]}, stop {t['stop']}, target {t['target']}")
        pos = None
        for _ in range(10):
            pos = next((p for p in mt5.positions_get(symbol=s) or [] if p.magic == MAGIC_TEST), None) \
                if _takes_symbol(mt5) else next((p for p in mt5.positions_get() or [] if p.magic == MAGIC_TEST), None)
            if pos:
                break
            time.sleep(0.5)
        if not pos:
            step("The trade didn't show up in open positions", False)
            return _test_end(steps, False)
        step(f"In MT5 as #{pos.ticket}; it'll close in 5 seconds")
        time.sleep(5)
        pos = next((p for p in mt5.positions_get(ticket=pos.ticket) or []), pos)
        r = send(mt5, {"kind": "close", "position": pos.ticket, "symbol": s, "side": "buy", "lots": pos.volume}, MAGIC_TEST)
        if not r.get("done"):
            step("Closing failed: " + r.get("error", "?") + f" (close #{pos.ticket} yourself in MT5)", False)
            return _test_end(steps, False)
        step(f"Closed #{pos.ticket}: about ${pos.profit:+.2f} (the spread)")
        return _test_end(steps, True)
    except Exception as e:
        step(f"{type(e).__name__}: {e}", False)
        return _test_end(steps, False)


def _takes_symbol(mt5):
    import inspect
    try:
        return "symbol" in inspect.signature(mt5.positions_get).parameters
    except (TypeError, ValueError):
        return True  # the real MetaTrader5 functions are built in: they take symbol=


def _test_end(steps, ok):
    import server_bridge
    text = ("Test trade worked, {t}: I opened and closed a trade on MT5." if ok else
            "The test trade didn't work, {t}: " + steps[-1]["text"] + ".").replace("{t}", features.settings().get("title", "sir"))
    _panel({"type": "trade_test", "steps": steps, "done": True, "ok": ok})
    server_bridge.say(text)
    return {"ok": ok, "steps": [s["text"] for s in steps]}


def floor_watch():
    """Every 30 seconds while MT5 is open (server.py runs it): if equity reaches his floor, close every trade Jarvis
    opened (his own manual ones are left alone, and he's told), stop the autopilot, and say so."""
    lim = limits()
    floor = lim["trade_equity_floor"]
    if not floor:
        return None
    mt5 = _mt5()
    acc = mt5.account_info()
    if acc.equity > floor:
        return None
    AUTO.on = False
    closed, others = [], []
    for p in mt5.positions_get() or []:
        if p.magic in (MAGIC_MANUAL, MAGIC_AUTO):
            r = send(mt5, {"kind": "close", "position": p.ticket, "symbol": p.symbol,
                           "side": "buy" if p.type == 0 else "sell", "lots": p.volume}, p.magic)
            if r.get("done"):
                closed.append(p.symbol)
        else:
            others.append(f"{p.symbol} #{p.ticket}")
    msg = (f"Equity floor hit, {features.settings().get('title', 'sir')}: equity is ${acc.equity:,.2f}, your floor is "
           f"${floor:,.2f}. " + (f"I've closed my {len(closed)} trade(s) and stopped the autopilot. " if closed else
                                 "The autopilot is stopped. ")
           + (f"Your own trades are still open: {', '.join(others)}." if others else ""))
    import server_bridge
    server_bridge.say(msg)
    return msg


def autopilot(on=True):
    """Start or stop the autopilot. It runs inside Jarvis (the server), so a tool call asks the server to do it."""
    import server_bridge
    if server_bridge.IN_SERVER:
        return AUTO.start() if on else AUTO.stop(close=True)
    return server_bridge.post("/api/autopilot", {"on": bool(on)}, timeout=150)  # opening MT5 can take a minute


def autopilot_status():
    import server_bridge
    if server_bridge.IN_SERVER:
        return AUTO.status()
    return server_bridge.post("/api/autopilot", {"status": True})


FUNCS = {"test_trade": lambda symbol=None: test_trade(symbol), "propose_trade": propose_trade, "propose_change": propose_change, "trading_settings": trading_settings,
         "autopilot": autopilot, "autopilot_status": autopilot_status}
S, N = {"type": "string"}, {"type": "number"}
TOOLS = [
    {"name": "test_trade", "description": "Check that Jarvis can trade on MT5 ('test trade'): on a demo account, opens "
     "the smallest buy with a stop and target and closes it a few seconds later, showing each step on the HUD (and "
     "what's wrong if it can't, e.g. Algo Trading off).", "input_schema": {"type": "object", "properties": {"symbol": S}}},
    {"name": "propose_trade", "description": (
        "Place a trade on MT5 when he asks ('buy 0.1 gold, stop 2310, target 2350'): shows a ticket on the HUD with "
        "the chart, entry, stop and target lines and the dollar risk; it's only sent when he clicks Confirm on it "
        "(voice can't confirm). side: buy or sell. stop: the stop loss price (required). target: take profit price. "
        "lots, or risk_pct (of his balance) to size it for him. order: market (default), limit or stop (with "
        "price). Never suggest or choose a trade for him here: only place what he asked for."),
     "input_schema": {"type": "object", "required": ["symbol", "side", "stop"], "properties": {
         "symbol": S, "side": {"type": "string", "enum": ["buy", "sell"]}, "stop": N, "target": N, "lots": N,
         "risk_pct": N, "order": {"type": "string", "enum": ["market", "limit", "stop"]}, "price": N, "note": S}}},
    {"name": "propose_change", "description": (
        "Move a trade's stop loss or take profit ('move my stop to break-even'), or close it (close=true, lots for "
        "part of it), as a HUD ticket he clicks to confirm. ticket: the position number (from account_status)."),
     "input_schema": {"type": "object", "required": ["ticket"], "properties": {
         "ticket": N, "stop": N, "target": N, "close": {"type": "boolean"}, "lots": N}}},
    {"name": "trading_settings", "description": (
        "His trading limits (also in Settings > Trading): trade_account_size ($, what % limits are taken of; 0 = "
        "live balance), trade_size + trade_size_unit (%, $ or lots: the size he wants per trade), trade_daily_loss + "
        "unit (% or $), trade_equity_floor ($ equity must never go below), trade_daily_target + unit (profit target; "
        "the autopilot stops for the day at it), trade_max_lots, trade_max_risk_pct, auto_max_trades, auto_min_rr, "
        "auto_symbols; live / auto_live to switch real money on (needs his click on a HUD card) or off. Call with "
        "nothing to see them."),
     "input_schema": {"type": "object", "properties": {
         "live": {"type": "boolean"}, "auto_live": {"type": "boolean"}, "trade_account_size": N, "trade_size": N,
         "trade_size_unit": {"type": "string", "enum": ["%", "$", "lots"]}, "trade_daily_loss": N,
         "trade_daily_loss_unit": {"type": "string", "enum": ["%", "$"]}, "trade_equity_floor": N,
         "trade_daily_target": N, "trade_daily_target_unit": {"type": "string", "enum": ["%", "$"]},
         "trade_max_lots": N, "trade_max_risk_pct": N, "auto_max_trades": N, "auto_min_rr": N, "auto_order_hours": N, "auto_min_stop_atr": N, "auto_news_min": N,
         "auto_symbols": {"type": "array", "items": S}}}},
    {"name": "autopilot", "description": (
        "The trading autopilot ('make me money', 'stop trading'): every 15 minutes it reads the charts and asks two "
        "brains separately; it trades only when both pick the same trade, within his limits (risk per trade, daily "
        "loss limit, trades a day, no news, demo unless he switched it to live). on: true to start, false to stop. "
        "Starting opens MetaTrader 5 minimised if it's closed (it can take a minute); stopping closes MT5."),
     "input_schema": {"type": "object", "properties": {"on": {"type": "boolean"}}}},
    {"name": "autopilot_status", "description": "How the trading autopilot is doing: on or off, trades today, "
     "last decision and its limits.", "input_schema": {"type": "object", "properties": {}}},
]


def selftest():
    import tempfile
    from types import SimpleNamespace as NS
    assert check_levels("buy", 100, 99, 103) == [] and check_levels("buy", 100, 101, 103)
    assert check_levels("sell", 100, 0, 95) == ["a stop loss is required"] and check_levels("sell", 100, 101, 102)
    gold = NS(trade_tick_size=0.01, trade_tick_value=1.0, point=0.01, volume_step=0.01, volume_min=0.01, volume_max=100)
    assert round(loss_per_lot(gold, 2350.0, 2340.0)) == 1000  # $10 move x 100 oz
    assert size_lots(gold, 2350.0, 2340.0, 50, 1.0) == 0.05 and size_lots(gold, 2350.0, 2340.0, 5000, 1.0) == 1.0
    assert size_lots(gold, 2350.0, 2000.0, 10, 1.0) == 0.0
    a = {"action": "buy", "symbol": "XAUUSD", "stop": 2340, "target": 2380, "confidence": 70, "reason": "x"}
    b = {"action": "buy", "symbol": "XAUUSD", "stop": 2335, "target": 2370, "confidence": 60, "reason": "y"}
    d = agree(a, b, 2350.0, 2)
    assert d and d["stop"] == 2340 and d["target"] == 2380 and d["confidence"] == 60  # the first brain's plan
    d = agree(a, b, 2350.0, 2, min_stop=15)
    assert d["stop"] == 2335 and round(d["rr"], 2) == 2.0  # too tight: widened to 15
    assert agree(a, {**b, "action": "sell"}, 2350.0, 2) is None and agree(a, {**b, "action": "none"}, 2350, 2) is None
    assert agree(a, {**b, "symbol": "EURUSD"}, 2350.0, 2) is None and agree(a, None, 2350, 2) is None
    p = {"order": "stop", "entry": 2360}
    assert plan_entry(p, "buy", 2350, 2350.3) == ("stop", 2360) and plan_entry(p, "buy", 2361, 2361.3) == ("market", 2361.3)
    assert plan_entry({"order": "limit", "entry": 2340}, "buy", 2350, 2350.3) == ("limit", 2340)
    assert plan_entry({"order": "limit", "entry": 2360}, "buy", 2350, 2350.3) == ("market", 2350.3)  # already there
    assert plan_entry({"order": "stop", "entry": 2340}, "sell", 2350, 2350.3) == ("stop", 2340)
    assert plan_entry({"order": "limit", "entry": 2340}, "sell", 2350, 2350.3) == (None, None)  # wrong side
    d = agree({**a, "order": "stop", "entry": 2355}, b, None, 2, 2350, 2350.3)
    assert d["order"] == "stop" and d["entry"] == 2355 and round(d["rr"], 2) == 1.67
    assert round(atr([[1, 2, 0, 1], [1, 3, 1, 2], [2, 2, 1, 1]]), 2) == 1.5
    assert _json_in('Sure: {"action": "none"} done') == {"action": "none"} and _json_in("no") is None
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "pos.csv"
        p.write_text("position,opened,closed,symbol,direction,volume,entry,exit,stop,tp,pnl,balanceAtOpen\n"
                     "1,2026-11-01 09:00:00,2026-11-01 09:30:00,XAUUSD,Long,0.1,2350,2360,2345,2360,100,1000\n"
                     "2,2026-11-02 10:00:00,2026-11-02 11:00:00,XAUUSD,Short,0.1,2360,2365,2365,2350,-50,1100\n")
        s = his_style(p)
        assert "XAUUSD 2" in s and "win rate 50%" in s, s
    print("mt5trade self-test passed")


if __name__ == "__main__":
    selftest()
