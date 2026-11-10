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
MAGIC_MANUAL, MAGIC_AUTO = 404, 405  # marks Jarvis's trades in MT5 (his own trades are left alone by the autopilot)
TICKET_SECONDS = 120  # a ticket not confirmed within 2 minutes expires (the price will have moved)
CLAUDE = None  # set by server.py (the Claude Code CLI)
IS_OUT = lambda name: False  # set by server.py: is that brain out of allowance right now?
LIMITS = {  # his settings override these ("trade_" keys in settings.json)
    "trade_max_lots": 1.0,          # biggest order Jarvis will send
    "trade_max_risk_pct": 2.0,      # most of his balance one trade may risk (trades he asks for)
    "trade_live": False,            # trades on a real-money account (else demo only)
    "auto_live": False,             # the autopilot on a real-money account (separate switch)
    "auto_risk_pct": 0.5,           # what one autopilot trade risks
    "auto_daily_loss_pct": 2.0,     # the autopilot stops for the day after losing this much
    "auto_max_trades": 3,           # autopilot trades a day
    "auto_min_rr": 1.5,             # reward to risk at least this
    "auto_symbols": ["XAUUSD"],     # what the autopilot looks at
}


def limits():
    s = features.settings()
    return {k: s.get(k, v) for k, v in LIMITS.items()}


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
    if os.name == "nt" and "terminal64.exe" not in features.running():
        raise RuntimeError("MetaTrader 5 isn't open, and Jarvis doesn't open it by himself. If he wants live MT5 "
                           "data, ask whether to open it (open_app 'MetaTrader 5'); his journal still works without it.")
    if not mt5.initialize():
        raise RuntimeError(f"Can't reach MetaTrader 5 ({mt5.last_error()}). Is it open and logged in?")
    return mt5


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


def _chart(mt5, s, tf="M15", bars=60):
    rates = mt5.copy_rates_from_pos(s, getattr(mt5, "TIMEFRAME_" + tf), 0, bars)
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
    bal = mt5.account_info().balance
    if lots:
        lots = min(float(lots), lim["trade_max_lots"])
    else:
        lots = size_lots(info, entry, stop, bal * float(risk_pct or 1.0) / 100, lim["trade_max_lots"])
    if not lots:
        return {"error": "The stop is too far for even the smallest lot size within his risk limit."}
    risk = loss_per_lot(info, entry, stop) * lots
    if risk > bal * lim["trade_max_risk_pct"] / 100:
        return {"error": f"That risks ${risk:,.2f}, over his limit of {lim['trade_max_risk_pct']}% "
                         f"(${bal * lim['trade_max_risk_pct'] / 100:,.2f}). Use a smaller size or closer stop."}
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
    return send(mt5, t, MAGIC_MANUAL)


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


def trading_settings(live=None, max_lots=None, max_risk_pct=None, auto_live=None, auto_risk_pct=None,
                     auto_daily_loss_pct=None, auto_max_trades=None, auto_symbols=None):
    """Change his trading limits. Switching live trading ON needs his click on a HUD card; everything else
    (including switching live off, or making limits stricter or looser) is set straight away."""
    s = features.settings()
    changes = {"trade_max_lots": max_lots, "trade_max_risk_pct": max_risk_pct, "auto_risk_pct": auto_risk_pct,
               "auto_daily_loss_pct": auto_daily_loss_pct, "auto_max_trades": auto_max_trades}
    new = {k: max(0.0, float(v)) for k, v in changes.items() if v is not None}
    if auto_symbols:
        new["auto_symbols"] = [str(x).upper().replace("/", "")[:12] for x in auto_symbols][:4]
    if live is False:
        new["trade_live"] = False
    if auto_live is False:
        new["auto_live"] = False
    features._save("settings.json", {**s, **new})
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
    cmd = [CLAUDE, "-p", "--output-format", "text", "--model", "sonnet", "--tools", "",
           "--setting-sources", "project", "--strict-mcp-config", "--disable-slash-commands",
           "--system-prompt", "You are a careful trading analyst. Reply with one JSON object only."]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=300, cwd=HERE,
                       env=deepseek.env() if ds else None, creationflags=NO_WINDOW)
    if r.returncode:
        raise RuntimeError((r.stdout + r.stderr)[-300:])
    return r.stdout


def ask_chatgpt(prompt):
    import gpt_brain
    cmd = gpt_brain.command(None)
    cmd[cmd.index("-s") + 1] = "read-only"  # it only answers: it runs nothing
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300, cwd=HERE, creationflags=NO_WINDOW)
    _, texts, err = gpt_brain.parse(r.stdout.splitlines())
    if err or not texts:
        raise RuntimeError(err or "no answer")
    return texts[-1]


def brains():
    """The two brains to ask: Claude and ChatGPT, or DeepSeek standing in for whichever is missing."""
    import deepseek
    import gpt_brain
    out = []
    if CLAUDE and not IS_OUT("Claude"):
        out.append(("Claude", lambda p: ask_claude(p)))
    if gpt_brain.available() and not IS_OUT("ChatGPT"):
        out.append(("ChatGPT", ask_chatgpt))
    if len(out) < 2 and CLAUDE and deepseek.available() and not IS_OUT("DeepSeek"):
        out.append(("DeepSeek", lambda p: ask_claude(p, ds=True)))
    return out[:2]


def agree(a, b, side_entry, digits):
    """Both brains' picks -> the trade (or None). Same symbol and direction; the wider stop (size is set by risk,
    so a wider stop means fewer lots, not more risk) and the nearer target."""
    if not a or not b or a.get("action") not in ("buy", "sell") or a.get("action") != b.get("action"):
        return None
    if str(a.get("symbol", "")).upper() != str(b.get("symbol", "")).upper():
        return None
    side, entry = a["action"], side_entry
    try:
        stops = [float(a["stop"]), float(b["stop"])]
        targets = [float(a["target"]), float(b["target"])]
    except (KeyError, TypeError, ValueError):
        return None
    stop = min(stops) if side == "buy" else max(stops)
    target = min(targets) if side == "buy" else max(targets)
    if check_levels(side, entry, stop, target):
        return None
    return {"symbol": a["symbol"], "side": side, "stop": round(stop, digits), "target": round(target, digits),
            "rr": abs(target - entry) / abs(entry - stop), "confidence": min(int(a.get("confidence", 0)), int(b.get("confidence", 0))),
            "why": [str(a.get("reason", ""))[:200], str(b.get("reason", ""))[:200]]}


# ---------- The autopilot ----------
class Autopilot:
    def __init__(self):
        self.on, self.thread, self.last = False, None, {}

    def status(self):
        st = _load(AUTO_STATE, {})
        return {"on": self.on, "today": st.get("date"), "trades_today": st.get("trades", 0),
                "start_equity": st.get("start_equity"), "last": self.last, "limits": limits()}

    def start(self):
        if self.on:
            return {"already": True, **self.status()}
        mt5 = _mt5()  # fails here (and says why) if MT5 isn't open
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
        return {"started": True, **self.status()}

    def stop(self, why="Stopped"):
        self.on = False
        self.show(why)
        return {"stopped": True, "note": "Its open trades keep their stops and targets; ask to close them if he wants."}

    def show(self, msg):
        self.last = {**self.last, "msg": msg, "at": datetime.datetime.now().strftime("%H:%M")}
        _panel({"type": "autopilot", **self.status()})

    def say(self, text):
        import server_bridge
        server_bridge.say(text)

    def loop(self):
        next_look = 0.0
        while self.on:
            try:
                self.manage()
                if time.time() >= next_look:
                    self.cycle()
                    now = time.time()
                    next_look = now - now % 900 + 900 + 20  # just after each 15-minute candle closes
            except Exception as e:
                self.show(f"Error: {type(e).__name__}: {str(e)[:120]}")
            for _ in range(60):
                if not self.on:
                    return
                time.sleep(1)

    def day(self, mt5):
        st = _load(AUTO_STATE, {})
        today = datetime.date.today().isoformat()
        if st.get("date") != today:
            st = {"date": today, "start_equity": mt5.account_info().equity, "trades": 0}
            _save(AUTO_STATE, st)
        return st

    def manage(self):
        """Break-even at 1R for the autopilot's own trades."""
        mt5 = _mt5()
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
        loss = (st["start_equity"] - acc.equity) / max(1, st["start_equity"]) * 100
        if loss >= lim["auto_daily_loss_pct"]:
            self.on = False
            self.say(f"Autopilot stopped for today: down {loss:.1f}%, its daily limit.")
            return f"daily loss limit hit ({loss:.1f}%)"
        if st["trades"] >= lim["auto_max_trades"]:
            return f"{st['trades']} trades today, its limit"
        if any(p.magic == MAGIC_AUTO for p in mt5.positions_get() or []):
            return "it already has a trade open"
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
        st = self.day(mt5)
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
            spread = tick.ask - tick.bid
            market[s] = {"bid": tick.bid, "ask": tick.ask, "spread": round(spread, info.digits), "digits": info.digits,
                         "M15": _chart(mt5, s, "M15", 48), "H1": _chart(mt5, s, "H1", 48), "H4": _chart(mt5, s, "H4", 30)}
        if not market:
            self.show("Waiting: the market is closed")
            return
        prompt = (
            "Decide whether to open ONE trade now, trading the way this trader does. Be selective: 'none' is the "
            "right answer most of the time, unless there is a clear setup.\n"
            f"Trader's style: {his_style()}\n"
            f"Account: balance {acc.balance:.2f}, equity {acc.equity:.2f}. Risk per trade is fixed by the system.\n"
            f"Minimum reward:risk {lim['auto_min_rr']}.\n"
            "Candles are [open, high, low, close], oldest first, MT5 server time:\n"
            + json.dumps(market) +
            '\nReply with one JSON object only: {"action": "buy" | "sell" | "none", "symbol": "...", '
            '"stop": price, "target": price, "confidence": 0-100, "reason": "one sentence"}')
        picks, names = [], []
        for name, ask in brains():
            try:
                picks.append(_json_in(ask(prompt)))
            except Exception as e:
                picks.append(None)
                self.show(f"{name} didn't answer: {str(e)[:80]}")
            names.append(name)
        self.log({"at": datetime.datetime.now().isoformat(timespec="seconds"), "brains": dict(zip(names, picks))})
        if len(picks) < 2 or not all(picks):
            self.show("No trade: both brains must answer")
            return
        a = picks[0]
        s = next((k for k in market if k.upper().startswith(str(a.get("symbol", "")).upper()[:6])), None)
        if not s:
            self.show(f"No trade: {names[0]} said {a.get('action')}, {names[1]} said {picks[1].get('action')}")
            return
        tick, info = mt5.symbol_info_tick(s), mt5.symbol_info(s)
        entry = tick.ask if a.get("action") == "buy" else tick.bid
        deal = agree({**a, "symbol": s}, {**picks[1], "symbol": s if str(picks[1].get("symbol", "")).upper()[:6] == s.upper()[:6] else picks[1].get("symbol")},
                     entry, info.digits)
        if not deal:
            self.show(f"No trade: {names[0]} said {a.get('action')}, {names[1]} said {picks[1].get('action')}")
            return
        if deal["rr"] < lim["auto_min_rr"]:
            self.show(f"No trade: both said {deal['side']} {s}, but reward:risk is only {deal['rr']:.1f}")
            return
        lots = size_lots(info, entry, deal["stop"], acc.balance * lim["auto_risk_pct"] / 100, lim["trade_max_lots"])
        if not lots:
            self.show("No trade: the stop is too far for the smallest lot within the risk limit")
            return
        t = {"kind": "open", "symbol": s, "side": deal["side"], "order": "market", "entry": entry, "stop": deal["stop"],
             "target": deal["target"], "lots": lots}
        r = send(mt5, t, MAGIC_AUTO)
        self.log({"at": datetime.datetime.now().isoformat(timespec="seconds"), "trade": t, "result": r, "why": deal["why"]})
        if r.get("done"):
            st["trades"] += 1
            _save(AUTO_STATE, st)
            risk = loss_per_lot(info, entry, deal["stop"]) * lots
            self.say(f"Autopilot: {deal['side']} {lots} {s}, stop {deal['stop']}, target {deal['target']}, "
                     f"risking ${risk:,.0f}. Both brains agreed: {deal['why'][0]}")
            self.show(f"Traded: {deal['side']} {lots} {s}")
        else:
            self.show("Trade refused: " + r.get("error", "?"))

    def log(self, entry):
        log = _load(AUTO_LOG, [])[-500:]
        log.append(entry)
        _save(AUTO_LOG, log)


AUTO = Autopilot()


def autopilot(on=True):
    """Start or stop the autopilot. It runs inside Jarvis (the server), so a tool call asks the server to do it."""
    import server_bridge
    if server_bridge.IN_SERVER:
        return AUTO.start() if on else AUTO.stop()
    return server_bridge.post("/api/autopilot", {"on": bool(on)})


def autopilot_status():
    import server_bridge
    if server_bridge.IN_SERVER:
        return AUTO.status()
    return server_bridge.post("/api/autopilot", {"status": True})


FUNCS = {"propose_trade": propose_trade, "propose_change": propose_change, "trading_settings": trading_settings,
         "autopilot": autopilot, "autopilot_status": autopilot_status}
S, N = {"type": "string"}, {"type": "number"}
TOOLS = [
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
        "His trading limits: max_lots, max_risk_pct (per trade), auto_risk_pct, auto_daily_loss_pct, auto_max_trades, "
        "auto_symbols; live / auto_live to switch real-money trading on (needs his click on a HUD card) or off. "
        "Call with nothing to see the current limits."),
     "input_schema": {"type": "object", "properties": {
         "live": {"type": "boolean"}, "auto_live": {"type": "boolean"}, "max_lots": N, "max_risk_pct": N,
         "auto_risk_pct": N, "auto_daily_loss_pct": N, "auto_max_trades": N, "auto_symbols": {"type": "array", "items": S}}}},
    {"name": "autopilot", "description": (
        "The trading autopilot ('make me money', 'stop trading'): every 15 minutes it reads the charts and asks two "
        "brains separately; it trades only when both pick the same trade, within his limits (risk per trade, daily "
        "loss limit, trades a day, no news, demo unless he switched it to live). on: true to start, false to stop."),
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
    assert d and d["stop"] == 2335 and d["target"] == 2370 and d["confidence"] == 60  # wider stop, nearer target
    assert agree(a, {**b, "action": "sell"}, 2350.0, 2) is None and agree(a, {**b, "action": "none"}, 2350, 2) is None
    assert agree(a, {**b, "symbol": "EURUSD"}, 2350.0, 2) is None and agree(a, None, 2350, 2) is None
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
