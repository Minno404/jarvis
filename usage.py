"""Token usage: "Jarvis, how many tokens have I got left?" / "token usage".

Every brain call Jarvis makes (chat, jobs, the trading autopilot) is logged to usage_log.jsonl with its tokens.
report() turns that into a panel: what each brain used today, how much of its allowance is left, and about how many
more messages and jobs that allows. The panel only shows when asked.

Where "left" comes from:
- ChatGPT: Codex writes its plan's limits (5-hour and weekly, % used, reset times) into its session files in
  ~/.codex/sessions. Tokens in the current window / % used = tokens per 1%, so the rest of the window converts to tasks.
- Claude: Claude Code reports a rate-limit status while chatting. When it gives a %, that's used the same way;
  otherwise the estimate comes from how much Jarvis had used the last time Claude ran out (unknown until then).
- DeepSeek: its account balance, and the cost per task measured from how the balance falls.
- Local AI: free, no limit.
"""
import datetime
import json
import os
import time
import urllib.request
from pathlib import Path

import features

HERE = Path(__file__).resolve().parent
LOG = HERE / "usage_log.jsonl"
STATE = HERE / "usage_state.json"  # Claude's last rate-limit status, its learned capacity, DeepSeek balance readings
KEEP_DAYS = 8


def _state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(s):
    try:
        STATE.write_text(json.dumps(s), encoding="utf-8")
    except OSError:
        pass


def weight(e):
    """Tokens that count toward a plan's limit: new input and output in full, cached input at a tenth."""
    return e.get("in", 0) + e.get("out", 0) + e.get("cached", 0) / 10


def record(brain, source, inp=0, out=0, cached=0, cost=0.0):
    e = {"t": round(time.time()), "brain": brain, "src": source, "in": int(inp), "out": int(out),
         "cached": int(cached), "cost": round(float(cost or 0), 5)}
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(e) + "\n")
    except OSError:
        pass
    return e


def claude(result, source, ds=False):
    """Log a Claude Code result (its JSON or stream-json 'result' event)."""
    try:
        u = (result or {}).get("usage") or {}
        record("DeepSeek" if ds else "Claude", source,
               u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0), u.get("output_tokens", 0),
               u.get("cache_read_input_tokens", 0), 0 if ds else result.get("total_cost_usd", 0))
    except Exception:
        pass


def codex(lines, source, local=False):
    """Log Codex's turn.completed usage from its --json output lines."""
    try:
        inp = out = cached = 0
        for line in lines:
            if '"turn.completed"' not in line:
                continue
            u = json.loads(line).get("usage") or {}
            c = u.get("cached_input_tokens", 0)
            inp, out, cached = inp + u.get("input_tokens", 0) - c, out + u.get("output_tokens", 0), cached + c
        if inp or out:
            record("Local" if local else "ChatGPT", source, inp, out, cached)
    except Exception:
        pass


def rate_event(ev):
    """Claude Code's rate_limit_event while chatting: keep the latest, as it came."""
    info = ev.get("rate_limit_info") or ev
    s = _state()
    s["claude_limit"] = {"at": time.time(), **{k: v for k, v in info.items() if isinstance(v, (int, float, str, bool))}}
    _save(s)


def limit_hit(brain):
    """A brain ran out: remember how much Jarvis had used in the 5 hours before, as that brain's capacity."""
    used = sum(weight(e) for e in entries(time.time() - 5 * 3600) if e["brain"] == brain)
    if used > 0:
        s = _state()
        s.setdefault("capacity", {})[brain] = {"tokens": used, "at": time.time()}
        _save(s)


def entries(since=0):
    out = []
    try:
        with LOG.open(encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("t", 0) >= since:
                    out.append(e)
    except OSError:
        pass
    return out


def trim():
    """Drop entries older than KEEP_DAYS (run now and then)."""
    keep = entries(time.time() - KEEP_DAYS * 86400)
    try:
        LOG.write_text("".join(json.dumps(e) + "\n" for e in keep), encoding="utf-8")
    except OSError:
        pass


def codex_limits(home=None):
    """ChatGPT's plan limits from Codex's newest session files, with the tokens used in each window.
    -> {"5h": {...}, "week": {...}} each {used, resets, tokens, per_pct}, or {}."""
    root = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    try:
        files = sorted(root.rglob("rollout-*.jsonl"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return {}
    files = [f for f in files if f.stat().st_mtime > time.time() - 8 * 86400]
    events = []  # (time, tokens this call, rate_limits)
    for f in files:
        last = 0
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"token_count"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    p = d.get("payload") or {}
                    total = ((p.get("info") or {}).get("total_token_usage") or {})
                    tok = total.get("input_tokens", 0) - total.get("cached_input_tokens", 0) + total.get("output_tokens", 0) \
                        + total.get("cached_input_tokens", 0) / 10
                    t = datetime.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
                    events.append((t, max(0.0, tok - last), p.get("rate_limits") or {}))
                    last = max(last, tok)
        except (OSError, KeyError, ValueError):
            continue
    events = [e for e in events if e[2].get("primary")]
    if not events:
        return {}
    events.sort(key=lambda e: e[0])
    latest = events[-1][2]
    out = {}
    for name, key in (("5h", "primary"), ("week", "secondary")):
        w = latest.get(key)
        if not w:
            continue
        resets = w.get("resets_at") or 0
        start = resets - (w.get("window_minutes") or 0) * 60
        tokens = sum(e[1] for e in events if e[0] >= start)
        used = float(w.get("used_percent") or 0)
        if resets and resets < time.time():
            used, tokens = 0.0, 0  # that window has reset since
        out[name] = {"used": used, "resets": resets, "tokens": tokens, "per_pct": tokens / used if used >= 1 else None}
    out["plan"] = latest.get("plan_type")
    return out


def deepseek_balance():
    import deepseek
    if not deepseek.available():
        return None
    try:
        req = urllib.request.Request("https://api.deepseek.com/user/balance",
                                     headers={"Authorization": f"Bearer {deepseek.key()}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        infos = d.get("balance_infos") or []
        b = next((i for i in infos if i.get("currency") == "USD"), infos[0] if infos else None)
        return b and {"amount": float(b.get("total_balance", 0)), "currency": b.get("currency", "")}
    except Exception:
        return None


def _avg(es):
    es = es[-40:]
    return sum(weight(e) for e in es) / len(es) if es else None


def _left(rest, per_task):
    return int(rest // per_task) if rest is not None and per_task else None


def report(home=None, balance=None):
    """Everything the usage panel shows."""
    now = time.time()
    day = datetime.datetime.combine(datetime.date.today(), datetime.time()).timestamp()
    week = entries(now - 7 * 86400)
    today = [e for e in week if e["t"] >= day]
    s = _state()
    brains = []
    for name in ("Claude", "ChatGPT", "DeepSeek", "Local"):
        mine = [e for e in week if e["brain"] == name]
        if not mine and name in ("DeepSeek", "Local"):
            continue
        chats = [e for e in mine if e["src"] == "chat"]
        jobs = [e for e in mine if e["src"] == "job"]
        tday = [e for e in today if e["brain"] == name]
        b = {"name": name, "today_calls": len(tday), "today_tokens": round(sum(weight(e) for e in tday)),
             "today_cost": round(sum(e["cost"] for e in tday), 3),
             "per_chat": _avg(chats), "per_job": _avg(jobs), "limits": [], "note": ""}
        rest = None  # tokens left in the tightest window
        if name == "ChatGPT":
            lim = codex_limits(home)
            b["per_pct"] = (lim.get("5h") or {}).get("per_pct")
            for key, label in (("5h", "5-hour limit"), ("week", "Weekly limit")):
                w = lim.get(key)
                if not w:
                    continue
                b["limits"].append({"label": label, "used": w["used"], "resets": w["resets"]})
                per = w["per_pct"] or (lim.get("5h") or {}).get("per_pct")
                if per:
                    r = (100 - w["used"]) * per
                    rest = r if rest is None else min(rest, r)
            if not lim:
                b["note"] = "No Codex session files found yet, so its limits aren't known."
            elif rest is None:
                b["note"] = "Too little used this window to measure tokens per 1% yet."
        elif name == "Claude":
            cl = s.get("claude_limit") or {}
            util = cl.get("utilization")
            if isinstance(util, (int, float)) and now - cl.get("at", 0) < 5 * 3600:
                pct = util * 100 if util <= 1 else util
                b["limits"].append({"label": (cl.get("rateLimitType") or "limit").replace("_", " "),
                                    "used": round(pct, 1), "resets": cl.get("resetsAt") or 0})
                window = sum(weight(e) for e in week if e["brain"] == name and e["t"] >= now - 5 * 3600)
                if pct >= 1 and window:
                    rest = (100 - pct) * window / pct
            cap = (s.get("capacity") or {}).get(name)
            if rest is None and cap:
                window = sum(weight(e) for e in week if e["brain"] == name and e["t"] >= now - 5 * 3600)
                rest = max(0.0, cap["tokens"] - window)
                b["note"] = "Estimated from how much Jarvis had used the last time Claude ran out."
            if rest is None:
                b["note"] = ("Claude only says how much is left once it's close to the limit, so this is unknown "
                             "until the first warning or the first time it runs out.")
            if cl.get("status") in ("rejected",) and now < (cl.get("resetsAt") or 0):
                rest = 0
        elif name == "DeepSeek":
            bal = balance if balance is not None else deepseek_balance()
            if bal:
                b["balance"] = bal
                snaps = s.setdefault("ds_snaps", [])
                count = len([e for e in week if e["brain"] == name])
                snaps.append([now, bal["amount"], count])
                del snaps[:-50]
                _save(s)
                old = next((x for x in snaps if x[0] > now - 7 * 86400), None)
                if old and old[1] > bal["amount"] and count > old[2]:
                    per_task = (old[1] - bal["amount"]) / (count - old[2])
                    b["cost_per_task"] = round(per_task, 4)
                    b["tasks_left"] = int(bal["amount"] // per_task)
                else:
                    b["note"] = "Cost per task shows once the balance has gone down after a few messages."
        elif name == "Local":
            b["note"] = "Runs on this PC: free, no limit."
        if name != "DeepSeek":
            b["chats_left"] = _left(rest, b["per_chat"])
            b["jobs_left"] = _left(rest, b["per_job"])
        b["per_chat"] = b["per_chat"] and round(b["per_chat"])
        b["per_job"] = b["per_job"] and round(b["per_job"])
        brains.append(b)
    return {"type": "usage", "brains": brains, "autopilot": autopilot(week, day, brains)}


def autopilot(week, day, brains):
    """What the trading autopilot used today, per 15-minute check, and what a full day of it costs."""
    ap = [e for e in week if e["src"] == "autopilot"]
    tday = [e for e in ap if e["t"] >= day]
    per_brain = {}
    for e in tday:
        p = per_brain.setdefault(e["brain"], {"calls": 0, "tokens": 0.0, "cost": 0.0})
        p["calls"] += 1
        p["tokens"] += weight(e)
        p["cost"] += e["cost"]
    avg = _avg(ap)
    ts = sorted(e["t"] for e in ap)
    checks = sum(1 for i, t in enumerate(ts) if not i or t - ts[i - 1] > 120)  # calls a minute or two apart: one check
    per_check = len(ap) / checks if checks else 1  # ChatGPT screens; Claude is only asked when it sees a trade
    out = {"today_calls": len(tday), "today_tokens": round(sum(weight(e) for e in tday)),
           "per_call": avg and round(avg),
           "brains": [{"name": k, "calls": v["calls"], "tokens": round(v["tokens"]), "cost": round(v["cost"], 3)}
                      for k, v in per_brain.items()],
           "per_check": round(per_check, 2),
           "per_day": avg and round(avg * per_check * 96)}  # every 15 minutes, all day
    try:
        import mt5trade
        out["running"] = bool(mt5trade.trading_now())
    except Exception:
        out["running"] = None
    gpt = next((b for b in brains if b["name"] == "ChatGPT"), None)
    per = gpt and gpt.pop("per_pct", None)
    if avg and per:  # how much of ChatGPT's 5-hour limit an hour of autopilot takes (4 checks an hour)
        out["gpt_pct_per_hour"] = round(4 * avg / per, 1)
    return out


def token_usage():
    """Tool: show the usage panel and return a short spoken summary."""
    trim()
    r = report()
    features._panel(r)
    said = []
    for b in r["brains"]:
        if b.get("chats_left") is not None:
            said.append(f"{b['name']} has room for about {b['chats_left']} more messages")
        elif b.get("tasks_left") is not None:
            said.append(f"DeepSeek's balance covers about {b['tasks_left']} more")
        elif b["limits"]:
            said.append(f"{b['name']} is at {b['limits'][0]['used']:.0f}% of its {b['limits'][0]['label']}")
    a = r["autopilot"]
    if a["today_calls"]:
        said.append(f"the autopilot made {a['today_calls']} brain calls today, {a['today_tokens']:,} tokens")
    return {"summary": "; ".join(said) or "Not enough use logged yet to estimate.", "panel": "shown"}


FUNCS = {"token_usage": token_usage}
TOOLS = [{"name": "token_usage", "description": (
    "Token usage panel ('how many tokens have I got left?', 'token usage', 'how many more tasks can you do?', 'what "
    "does the autopilot use?'): each brain's tokens today, its plan limits (% used, reset time), about how many more "
    "messages and jobs fit, DeepSeek's balance, and what the trading autopilot uses. Only show it when asked."),
    "input_schema": {"type": "object", "properties": {}}}]


def selftest():
    import tempfile
    global LOG, STATE
    real = LOG, STATE
    tmp = Path(tempfile.mkdtemp())
    LOG, STATE = tmp / "log.jsonl", tmp / "state.json"
    try:
        sess = tmp / ".codex" / "sessions" / "2026"
        sess.mkdir(parents=True)
        reset = time.time() + 3600
        start = datetime.datetime.fromtimestamp(reset - 300 * 60 + 60, datetime.timezone.utc)
        rows = []
        for i, total in enumerate((40000, 100000)):
            ts = (start + datetime.timedelta(minutes=i)).isoformat().replace("+00:00", "Z")
            rows.append(json.dumps({"timestamp": ts, "type": "event_msg", "payload": {
                "type": "token_count", "info": {"total_token_usage": {"input_tokens": total, "cached_input_tokens": 0,
                                                                       "output_tokens": 0}},
                "rate_limits": {"primary": {"used_percent": 10.0, "window_minutes": 300, "resets_at": reset},
                                "secondary": {"used_percent": 20.0, "window_minutes": 10080, "resets_at": reset + 86400}}}}))
        (sess / "rollout-x.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
        lim = codex_limits(tmp / ".codex")
        assert lim["5h"]["tokens"] == 100000 and lim["5h"]["per_pct"] == 10000, lim
        codex(['{"type":"turn.completed","usage":{"input_tokens":5000,"cached_input_tokens":4000,"output_tokens":600}}'], "chat")
        codex(['{"type":"turn.completed","usage":{"input_tokens":3000,"cached_input_tokens":0,"output_tokens":0}}'], "autopilot")
        claude({"usage": {"input_tokens": 10, "cache_creation_input_tokens": 990, "cache_read_input_tokens": 0,
                          "output_tokens": 0}, "total_cost_usd": 0.01}, "chat")
        r = report(tmp / ".codex", balance=None)
        g = next(b for b in r["brains"] if b["name"] == "ChatGPT")
        assert g["per_chat"] == 2000 and g["chats_left"] == 200, g  # weekly is tighter: 80% x 5,000 per % / 2,000
        c = next(b for b in r["brains"] if b["name"] == "Claude")
        assert c["chats_left"] is None and "unknown" in c["note"]
        limit_hit("Claude")
        c = next(b for b in report(tmp / ".codex")["brains"] if b["name"] == "Claude")
        assert c["chats_left"] == 0  # ran out with what's in the window now
        assert r["autopilot"]["today_calls"] == 1 and r["autopilot"]["per_day"] == 3000 * 96
        rate_event({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed_warning", "utilization": 0.5,
                                                                   "rateLimitType": "five_hour", "resetsAt": reset}})
        c = next(b for b in report(tmp / ".codex")["brains"] if b["name"] == "Claude")
        assert c["chats_left"] == 1 and c["limits"][0]["used"] == 50, c
        print("usage self-test passed")
    finally:
        LOG, STATE = real


if __name__ == "__main__":
    selftest()
