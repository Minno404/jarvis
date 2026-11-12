"""Jarvis improving himself: each week he studies where he went wrong, writes new rules for himself, tests them
against his old self on {USER}'s past requests, and shows the result for approval.

Evidence (last 14 days): replies {USER} corrected ("no, I said...", "that's wrong", "stop doing..."), the autopilot's
losing trades with the brains' reasons, and the nightly check-up's findings. Claude Sonnet turns that into up to 5
short rules ("lessons"), each for chatting or for trading, and names old rules to drop. The trial: for up to 6
corrected requests, Haiku answers once with the current rules and once with the new ones; a judge who sees
{USER}'s correction picks the better answer without knowing which is which. A panel shows the rules and the score
with Approve and Reject; nothing changes until he approves. Approved chat rules join Jarvis's instructions;
trading rules join the autopilot's prompt. Sundays from 05:00, or "improve yourself".
(New abilities are separate: "learn to ..." writes add-ons, see skills.py.)
"""
import datetime
import json
import random
import re

import features

FILE = "evolve.json"
CORRECT = re.compile(r"^\W*(no[,. !]|nope|wrong|that'?s (?:not|wrong)|not what i|i (?:said|meant|asked)|stop (?:doing|saying|that)|"
                     r"don'?t (?:do|say)|you (?:got|misunderstood|keep|didn'?t)|incorrect|that didn'?t work)", re.I)


def _state():
    return features._load(FILE, {"active": [], "proposal": None, "history": []})


def corrections(days=14):
    """[(his request, Jarvis's reply, his correction)] from the conversation log."""
    d = features.HERE / "conversations"
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    out = []
    for f in sorted(d.glob("*.jsonl")) if d.exists() else []:
        if f.stem < since:
            continue
        rows = []
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
        for prev, cur in zip(rows, rows[1:]):
            if CORRECT.match(str(cur.get("user", ""))):
                out.append((str(prev.get("user", ""))[:400], str(prev.get("jarvis", ""))[:500], str(cur["user"])[:300]))
    return out


def evidence():
    ev = {"corrections": corrections()[-20:], "losing_trades": [], "health": []}
    week = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat()
    for r in features._load("autopilot_reviews.json", []):
        if r.get("closed", "") >= week and r.get("profit", 0) < 0:
            ev["losing_trades"].append(f"{r['side']} {r['symbol']} {r.get('r')}R; reasons: {' | '.join(r.get('why', []))[:300]}")
    ev["health"] = [f"{d.get('problem')}: {d.get('cause')}" for d in features._load("selfcare.json", {}).get("diagnosis", [])
                    if d.get("who") != "harmless"][:5]
    return ev


def _rules(rules, area="chat"):
    return "\n".join(f"- {r['rule']}" for r in rules if r.get("area", "chat") == area)


def prompt():
    r = _rules(_state()["active"])
    return ("\nLessons you taught yourself from his corrections (follow them):\n" + r) if r else ""


def trading_prompt():
    r = _rules(_state()["active"], "trading")
    return ("Lessons from the autopilot's own losing trades:\n" + r + "\n") if r else ""


def propose(ev, active):
    import council
    q = features.personal(
        "You are Jarvis reviewing your own mistakes to improve yourself. Your current self-taught rules:\n"
        + (json.dumps([r["rule"] for r in active]) if active else "(none)")
        + "\n\nReplies {USER} corrected (his request | your reply | his correction):\n"
        + "\n".join(f"- {a} | {b} | {c}" for a, b, c in ev["corrections"])
        + "\n\nThe trading autopilot's losing trades:\n" + "\n".join(f"- {x}" for x in ev["losing_trades"][:12])
        + "\n\nYour health check's findings:\n" + "\n".join(f"- {x}" for x in ev["health"])
        + "\n\nWrite up to 5 new rules for yourself that would have prevented these: short, concrete, general enough "
        "to help again, never against safety or honesty. area 'chat' for how you answer him, 'trading' for the "
        "autopilot's trade decisions. Also list current rules that are now wrong or duplicated. JSON only: "
        '{"lessons": [{"rule": "...", "why": "the evidence, one line", "area": "chat|trading"}], "drop": ["exact rule text"]}')
    out = council._json(council._claude(q, "sonnet")) or {}
    return [l for l in out.get("lessons", []) if l.get("rule")][:5], out.get("drop", [])


def trial(lessons, active, cases):
    """Old rules vs new on his corrected requests, judged blind. -> {"new": n, "old": n, "tie": n}"""
    import council
    base = "You are Jarvis, {USER}'s personal assistant. Answer his request briefly."
    new_rules = active + lessons

    def reply(rules, req):
        r = council._claude(features.personal(base) + ("\nYour rules:\n" + _rules(rules) if _rules(rules) else "")
                            + f"\n\nHis request: {req}\nJSON only: {{\"reply\": \"...\"}}", "haiku")
        return (council._json(r) or {}).get("reply", r)[:600]
    score = {"new": 0, "old": 0, "tie": 0}
    for req, _old_reply, fix in cases[:6]:
        try:
            a, b = reply(active, req), reply(new_rules, req)
            flip = random.random() < 0.5
            x, y = (b, a) if flip else (a, b)
            v = (council._json(council._claude(
                f"A person asked: {req}\nLast time the assistant got it wrong and he said: {fix}\n\nAnswer A: {x}\n\n"
                f"Answer B: {y}\n\nWhich answer better avoids that mistake? JSON only: {{\"better\": \"A|B|tie\"}}", "haiku")) or {}).get("better", "tie")
            score["tie" if v not in ("A", "B") else "new" if (v == "A") == flip else "old"] += 1
        except Exception as e:
            print("evolve trial:", repr(e)[:120])
    return score


def improve(say=None):
    """Study the evidence, propose rules, trial them, and show the proposal for his approval."""
    st = _state()
    ev = evidence()
    if not (ev["corrections"] or ev["losing_trades"] or ev["health"]):
        return {"error": "Nothing to learn from in the last two weeks: no corrections, losing trades or errors."}
    lessons, drop = propose(ev, st["active"])
    if not lessons and not drop:
        return {"error": "I found nothing worth changing."}
    kept = [r for r in st["active"] if r["rule"] not in drop]
    score = trial([l for l in lessons if l.get("area", "chat") == "chat"], kept, ev["corrections"][-6:]) if ev["corrections"] else None
    st["proposal"] = {"made": datetime.datetime.now().isoformat(timespec="minutes"), "lessons": lessons, "drop": drop, "score": score}
    features._save(FILE, st)
    show_proposal()
    if say:
        say(f"I've been working on myself, {{TITLE}}: {len(lessons)} new rule{'s' if len(lessons) != 1 else ''} to approve"
            + (f"; in a blind test the new me won {score['new']} of {sum(score.values())}, the old me {score['old']}." if score else "."))
    return st["proposal"]


def show_proposal():
    p = _state()["proposal"]
    if not p:
        return {"error": "No self-improvement waiting for approval."}
    s = p.get("score")
    features._panel({"type": "panel", "kind": "list", "title": "Jarvis: proposed self-improvements", "stay": True,
                     "items": [{"text": f"{i}. {'TRADING' if l.get('area') == 'trading' else 'CHAT'}: {l['rule']}", "sub": l.get("why", "")}
                               for i, l in enumerate(p["lessons"], 1)] + [{"text": "DROP: " + d, "sub": ""} for d in p["drop"]],
                     "note": (f"Blind test on your corrected requests: new rules won {s['new']}, old won {s['old']}, {s['tie']} ties."
                              if s else "No chat test (the evidence was trading or errors only)."),
                     "actions": [["Approve all", "approve your improvements"], ["Reject all", "reject your improvements"]]
                     + [[f"Remove {i}", f"remove improvement {i}"] for i in range(1, len(p["lessons"]) + 1)]})
    return p


def approve_improvements():
    st = _state()
    p = st["proposal"]
    if not p:
        return {"error": "Nothing waiting for approval."}
    st["active"] = ([r for r in st["active"] if r["rule"] not in p["drop"]] + p["lessons"])[-25:]
    st["history"] = (st["history"] + [{**p, "approved": True}])[-20:]
    st["proposal"] = None
    features._save(FILE, st)
    return {"active_rules": len(st["active"])}


def change_proposal(number, rule=None):
    """His say on one proposed rule before approving: rule=None removes it, else its new wording."""
    st = _state()
    p = st["proposal"]
    if not p or not 1 <= int(number) <= len(p["lessons"]):
        return {"error": "No proposed rule with that number."}
    if rule:
        p["lessons"][int(number) - 1].update(rule=str(rule)[:300], why="reworded by him")
    else:
        p["lessons"].pop(int(number) - 1)
    features._save(FILE, st)
    show_proposal()
    return {"left": [l["rule"] for l in p["lessons"]]}


def add_rule(rule, area="chat"):
    """A rule he gives Jarvis himself: active straight away (he said it, so no approval step)."""
    st = _state()
    st["active"] = (st["active"] + [{"rule": str(rule)[:300], "why": "his own rule", "area": "trading" if area == "trading" else "chat"}])[-25:]
    features._save(FILE, st)
    return {"active_rules": len(st["active"])}


def reject_improvements():
    st = _state()
    if st["proposal"]:
        st["history"] = (st["history"] + [{**st["proposal"], "approved": False}])[-20:]
    st["proposal"] = None
    features._save(FILE, st)
    return {"rejected": True}


def my_rules(forget=None):
    """The rules Jarvis has taught himself; forget: the exact text of one to remove."""
    st = _state()
    if forget:
        st["active"] = [r for r in st["active"] if r["rule"] != forget]
        features._save(FILE, st)
    return {"rules": st["active"]}


def due(now=None):
    now = now or datetime.datetime.now()
    st = features._load("state.json", {})
    week = now.strftime("%G-%V")
    if now.weekday() != 6 or now.hour < 5 or st.get("evolve_week") == week:
        return False
    features._save("state.json", {**st, "evolve_week": week})
    return True


FUNCS = {"improve_yourself": lambda: improve(), "approve_improvements": approve_improvements,
         "reject_improvements": reject_improvements, "my_rules": my_rules, "show_improvements": show_proposal,
         "change_improvement": change_proposal, "add_my_rule": add_rule}
O = {"type": "object", "properties": {}}
TOOLS = [
    {"name": "improve_yourself", "description": "Study your own mistakes now (his corrections, losing autopilot trades, "
     "errors), write new rules for yourself, test them against your old self, and show them for approval. Takes a few minutes.",
     "input_schema": O},
    {"name": "approve_improvements", "description": "He approved your proposed self-improvements (only when he says).", "input_schema": O},
    {"name": "reject_improvements", "description": "He rejected your proposed self-improvements.", "input_schema": O},
    {"name": "show_improvements", "description": "Show the self-improvements waiting for his approval.", "input_schema": O},
    {"name": "change_improvement", "description": "His input on one proposed self-improvement before he approves: "
     "number (as on the panel); rule: its new wording ('change 2 to ...'), or leave out to remove it.",
     "input_schema": {"type": "object", "required": ["number"], "properties": {"number": {"type": "integer"}, "rule": {"type": "string"}}}},
    {"name": "add_my_rule", "description": "A rule he gives you himself ('new rule: never ...', 'from now on always ...'): "
     "active at once. area chat or trading (the autopilot).",
     "input_schema": {"type": "object", "required": ["rule"], "properties": {"rule": {"type": "string"}, "area": {"type": "string"}}}},
    {"name": "my_rules", "description": "The rules you've taught yourself ('what have you learned about yourself'); "
     "forget: exact text of one to remove when he asks.", "input_schema": {"type": "object", "properties": {"forget": {"type": "string"}}}},
]
COMMANDS = {"Jarvis": ["Improve yourself", "What rules have you taught yourself?"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    (features.HERE / "conversations").mkdir()
    today = datetime.date.today().isoformat()
    rows = [{"t": "10:00", "user": "what's my next shift", "jarvis": "You have 3 shifts this week: ..."},
            {"t": "10:01", "user": "No, I said my NEXT shift, just one", "jarvis": "Monday 9am."},
            {"t": "10:02", "user": "thanks", "jarvis": "Welcome."}]
    (features.HERE / "conversations" / f"{today}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    c = corrections()
    assert len(c) == 1 and c[0][0] == "what's my next shift" and c[0][2].startswith("No, I said")
    import council
    def fake(q, model=""):
        if "reviewing your own mistakes" in q:
            return json.dumps({"lessons": [{"rule": "Answer exactly what was asked, one item when he asks for the next one.",
                                            "why": "next shift", "area": "chat"},
                                           {"rule": "Skip buys under the H1 EMA50.", "why": "losers", "area": "trading"}], "drop": []})
        if "Which answer better" in q:
            a = q.split("Answer A: ")[1].split("\n\nAnswer B")[0]
            return json.dumps({"better": "A" if "ONE" in a else "B"})
        return json.dumps({"reply": "ONE: Monday 9am." if "one item" in q else "You have 3 shifts"})
    council._claude = fake
    shown, said = [], []
    features._panel = shown.append
    p = improve(said.append)
    assert p["score"] == {"new": 1, "old": 0, "tie": 0} and "won 1 of 1" in said[0] and shown[-1]["actions"][0][0] == "Approve all"
    assert change_proposal(2, "Skip buys under the H1 EMA50.")["left"][1].startswith("Skip buys") and shown[-1]["actions"][2] == ["Remove 1", "remove improvement 1"]
    assert prompt() == "" and approve_improvements()["active_rules"] == 2
    assert add_rule("Call me boss")["active_rules"] == 3 and "Call me boss" in prompt() and my_rules(forget="Call me boss")
    assert "one item" in prompt() and "EMA50" in trading_prompt() and "EMA50" not in prompt()
    assert my_rules(forget="Skip buys under the H1 EMA50.")["rules"].__len__() == 1 and trading_prompt() == ""
    assert due(datetime.datetime(2026, 11, 15, 5, 1)) and not due(datetime.datetime(2026, 11, 15, 6))
    print("evolve self-test passed")
