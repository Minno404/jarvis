"""Dream mode: overnight, Jarvis thinks over the last week and plans three things he could do for {USER} tomorrow.

At Settings 'dream_time' (default 04:00; empty turns it off), he reads the week's conversations (the last 150
exchanges), what he remembers about {USER}, tomorrow's shifts, his agents and ventures, and asks Claude (Sonnet,
one question) for exactly three proposals: useful, specific, doable with his own tools, each with the command that
starts it. In the morning, when {USER} is back, a "Dreamt up overnight" panel shows them with a "Do it" button each,
and Jarvis says them in one breath. Nothing is done until {USER} presses a button or says so.
"""
import datetime
import json

import features

FILE = "dream.json"

ASK = """You are Jarvis, {USER}'s assistant, thinking overnight about how to help him tomorrow.

What you remember about him:
{about}

His shifts in the next two days: {shifts}
His agents and ventures: {work}

The last week of your conversations (oldest first):
{convo}

Propose exactly 3 things YOU could do for him tomorrow that would genuinely help: follow-ups on things he
mentioned, problems you noticed, chances he might miss, or projects to push forward. Each must be specific and
something you can start yourself with your tools (research, a coding job, a reminder, a panel, an agent task, a
council question). No generic advice, nothing already done. Reply with JSON only:
{{"ideas": [{{"title": "short", "why": "one sentence: what you noticed", "do": "the exact request to give you to start it, in his words, e.g. 'research cheap CLA45 exhaust options under 1500'"}}]}}"""


def _convo(limit=150, days=7):
    d = features.HERE / "conversations"
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = []
    for f in sorted(d.glob("*.jsonl")) if d.exists() else []:
        if f.stem < since:
            continue
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                x = json.loads(line)
            except ValueError:
                continue
            rows.append(f"[{f.stem[5:]} {x.get('t', '')}] He: {str(x.get('user', ''))[:300]} | Jarvis: {str(x.get('jarvis', ''))[:200]}")
    return "\n".join(rows[-limit:])


def dream(now=None):
    """Think over the week and save three proposals for the morning."""
    import council
    import shifts
    now = now or datetime.datetime.now()
    convo = _convo()
    if not convo:
        return {"error": "No conversations this week to think about."}
    up = [f"{s['date']} {s['start']}-{s['end']}" for s in shifts._load()
          if now.date().isoformat() <= s["date"] <= (now.date() + datetime.timedelta(days=2)).isoformat()]
    work = []
    try:
        import agents
        work.append(agents.board() or "no agents")
    except Exception:
        pass
    vs = features._load("ventures.json", {}).get("ventures", {})
    work += [f"venture {v['name']}: {v['status']}" for v in vs.values()]
    q = features.personal(ASK).format(about=features.memory_prompt().strip()[:3000] or "(little yet)",
                                      shifts=", ".join(up) or "none", work="; ".join(work) or "none", convo=convo)
    ideas = (council._json(council._claude(q, "sonnet")) or {}).get("ideas", [])[:3]
    if not ideas:
        return {"error": "Nothing came of it."}
    res = {"made": now.isoformat(timespec="minutes"), "ideas": ideas, "shown": False}
    features._save(FILE, res)
    return res


def morning(say):
    """When he's back in the morning: show the night's ideas (once)."""
    d = features._load(FILE, None)
    if not d or d.get("shown") or d["made"][:10] != datetime.date.today().isoformat():
        return False
    features._save(FILE, {**d, "shown": True})
    show_dreams()
    say("I had some thoughts overnight, {TITLE}. " + " ".join(
        f"{['One', 'Two', 'Three'][i]}: {x['title']}." for i, x in enumerate(d["ideas"])) + " They're on the panel if you want any.")
    return True


def show_dreams():
    """The ideas Jarvis came up with overnight (a panel with a button each)."""
    d = features._load(FILE, None)
    if not d:
        return {"error": "I haven't dreamt anything up yet."}
    features._panel({"type": "panel", "kind": "list", "title": "Dreamt up overnight", "stay": True,
                     "items": [{"text": x["title"], "sub": x.get("why", "")} for x in d["ideas"]],
                     "actions": [[f"Do: {x['title'][:24]}", x["do"]] for x in d["ideas"] if x.get("do")]})
    return {"ideas": d["ideas"], "made": d["made"]}


def due(now=None):
    now = now or datetime.datetime.now()
    t = features.settings().get("dream_time", "04:00")
    st = features._load("state.json", {})
    if not t or now.strftime("%H:%M") < t or st.get("dream_day") == now.date().isoformat():
        return False
    features._save("state.json", {**st, "dream_day": now.date().isoformat()})
    return True


FUNCS = {"dream_now": lambda: dream(), "show_dreams": show_dreams}
TOOLS = [
    {"name": "dream_now", "description": "Think over the last week now and come up with 3 things you could do for him "
     "(normally done overnight). Takes a minute.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "show_dreams", "description": "Show the ideas you dreamt up overnight ('what did you dream up').",
     "input_schema": {"type": "object", "properties": {}}},
]
COMMANDS = {"Jarvis": ["What did you dream up?"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    assert dream().get("error")
    (features.HERE / "conversations").mkdir()
    today = datetime.date.today().isoformat()
    (features.HERE / "conversations" / f"{today}.jsonl").write_text(
        json.dumps({"t": "21:00", "user": "my exhaust is rattling", "jarvis": "That could be a loose heat shield."}) + "\n")
    import council
    asked = []
    council._claude = lambda q, model="": asked.append(q) or json.dumps({"ideas": [
        {"title": "Exhaust rattle fix", "why": "You mentioned a rattle.", "do": "research CLA45 exhaust rattle fixes"},
        {"title": "B", "why": "b", "do": "b"}, {"title": "C", "why": "c", "do": "c"}, {"title": "D", "why": "d", "do": "d"}]})
    r = dream()
    assert len(r["ideas"]) == 3 and "exhaust is rattling" in asked[0]
    shown, said = [], []
    features._panel = shown.append
    assert morning(said.append) and not morning(said.append)  # once
    assert "One: Exhaust rattle fix." in said[0] and shown[-1]["actions"][0][1] == "research CLA45 exhaust rattle fixes"
    features._save("settings.json", {"dream_time": "04:00"})
    assert not due(datetime.datetime(2026, 11, 13, 3, 59)) and due(datetime.datetime(2026, 11, 13, 4, 1))
    assert not due(datetime.datetime(2026, 11, 13, 5))
    print("dream self-test passed")
