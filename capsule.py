"""The time capsule: what {USER} predicted, planned and promised, replayed when its day comes.

Jarvis saves these as they're said: the brain calls capsule_add when he states one with a time ("I'll be trading full
time by June", "gold hits 4500 this year", "I'll finish the Gun Bros demo by Christmas"), and each learning pass
(learn.py) reads the new conversations for any that were missed (one Haiku question). When the date arrives, from
10 am when he's around, Jarvis reads his own words back with how long ago he said them, shows them on a panel, and
asks how it went; his answer is saved with it ("capsule_result"), building a record of how his calls turn out.
"""
import datetime
import json
import secrets

import features

FILE = "capsule.json"


def _load():
    return features._load(FILE, [])


def capsule_add(text, due, kind="plan"):
    """Save a prediction, plan or promise with its date (YYYY-MM-DD)."""
    try:
        due = datetime.date.fromisoformat(str(due)[:10]).isoformat()
    except ValueError:
        return {"error": "due must be a date, YYYY-MM-DD"}
    items = _load()
    if any(x["text"].lower() == str(text).lower() for x in items):
        return {"already": True}
    item = {"id": secrets.token_hex(3), "said": datetime.date.today().isoformat(), "text": str(text)[:300],
            "kind": kind if kind in ("prediction", "plan", "promise") else "plan", "due": due, "opened": False, "result": ""}
    features._save(FILE, items + [item])
    return {"saved": item}


def extract(convo):
    """Find dated predictions, plans and promises in conversation text (called by the learning pass)."""
    import council
    have = [x["text"] for x in _load()][-40:]
    q = features.personal(
        f"Today is {datetime.date.today().isoformat()}. From these conversations, list things {{USER}} himself predicted, "
        "planned or promised that have a time attached (a date, 'by June', 'in six months', 'this year', 'next week'). "
        "His own statements only, in his words, each with the date it falls due (work it out from when he said it). "
        "Skip reminders and anything already listed: " + json.dumps(have)
        + '\nJSON only: {"items": [{"text": "...", "kind": "prediction|plan|promise", "due": "YYYY-MM-DD"}]}\n\n' + convo)
    out = council._json(council._claude(q, "haiku")) or {}
    return [capsule_add(i["text"], i.get("due", ""), i.get("kind", "plan")) for i in out.get("items", [])[:8] if i.get("text")]


def _ago(said, now):
    days = (now - datetime.date.fromisoformat(said)).days
    return "today" if days < 1 else f"{days} days ago" if days < 14 else f"{days // 7} weeks ago" if days < 60 else \
        f"{round(days / 30.4)} months ago" if days < 700 else f"{round(days / 365)} years ago"


def tick(say, now=None):
    """Open what's due (once), from 10 am."""
    now = now or datetime.datetime.now()
    items = _load()
    due = [x for x in items if not x["opened"] and x["due"] <= now.date().isoformat()]
    if not due or now.hour < 10:
        return []
    for x in due:
        x["opened"] = True
    features._save(FILE, items)
    features._panel({"type": "panel", "kind": "list", "title": "Time capsule", "stay": True,
                     "items": [{"text": f"“{x['text']}”", "sub": f"Your {x['kind']}, {_ago(x['said'], now.date())} ({x['said']})"} for x in due],
                     "note": "Tell me how each went and I'll keep the record."})
    first = due[0]
    say(f"Time capsule, {{TITLE}}. {_ago(first['said'], now.date()).capitalize()} you said: {first['text']}. "
        + (f"And {len(due) - 1} more on the panel. " if len(due) > 1 else "") + "How did it go?")
    return due


def capsule_result(text, result, came_true=None):
    """Record how one turned out. text: enough of it to find it."""
    items = _load()
    x = next((i for i in reversed(items) if str(text).lower()[:40] in i["text"].lower() or i["id"] == text), None)
    if not x:
        return {"error": "I can't find that one in the capsule."}
    x["result"], x["came_true"] = str(result)[:300], came_true
    features._save(FILE, items)
    done = [i for i in items if i.get("came_true") is not None]
    return {"recorded": x["text"], "record": f"{sum(bool(i['came_true']) for i in done)} of {len(done)} came true so far"}


def show_capsule():
    """What's in the capsule: waiting, and how the opened ones went."""
    items = _load()
    if not items:
        return {"error": "The capsule is empty: tell me a prediction or a plan with a date."}
    features._panel({"type": "panel", "kind": "list", "title": "Time capsule", "stay": True,
                     "items": [{"text": x["text"], "sub": (f"opens {x['due']}" if not x["opened"] else f"opened {x['due']}: {x['result'] or 'no answer yet'}")
                                + f" · said {x['said']}"} for x in sorted(items, key=lambda x: x["due"])[-15:]]})
    return {"waiting": sum(not x["opened"] for x in items), "opened": sum(x["opened"] for x in items)}


FUNCS = {"capsule_add": capsule_add, "capsule_result": capsule_result, "show_capsule": show_capsule}
S = {"type": "string"}
TOOLS = [
    {"name": "capsule_add", "description": "Save to his time capsule whenever he predicts, plans or promises something "
     "with a time ('I'll be trading full time by June', 'gold will hit 4500 this year'): his words, the date it falls "
     "due, kind prediction|plan|promise. Do it quietly; it's read back to him on that date.",
     "input_schema": {"type": "object", "required": ["text", "due"], "properties": {"text": S, "due": S, "kind": S}}},
    {"name": "capsule_result", "description": "Record how a time capsule item turned out when he tells you.",
     "input_schema": {"type": "object", "required": ["text", "result"],
                      "properties": {"text": S, "result": S, "came_true": {"type": "boolean"}}}},
    {"name": "show_capsule", "description": "Show his time capsule.", "input_schema": {"type": "object", "properties": {}}},
]
COMMANDS = {"Jarvis": ["Show my time capsule"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    assert capsule_add("x", "soon").get("error")
    capsule_add("I'll be trading full time by now", "2026-11-13", "prediction")
    items = _load()
    items[0]["said"] = "2026-05-13"
    features._save(FILE, items)
    capsule_add("Finish the demo", "2027-01-01")
    assert capsule_add("finish the demo", "2027-01-01") == {"already": True}
    shown, said = [], []
    features._panel = shown.append
    assert not tick(said.append, datetime.datetime(2026, 11, 13, 9)) and len(tick(said.append, datetime.datetime(2026, 11, 13, 10, 5))) == 1
    assert said[0].startswith("Time capsule, {TITLE}. 6 months ago you said: I'll be trading full time by now.")
    assert not tick(said.append, datetime.datetime(2026, 11, 13, 11))
    assert capsule_result("trading full time", "Not yet, part time", False)["record"] == "0 of 1 came true so far"
    import council
    council._claude = lambda q, model="": json.dumps({"items": [{"text": "Gold hits 4500 this year", "kind": "prediction", "due": "2026-12-31"}]})
    assert extract("He: gold hits 4500 this year")[0]["saved"]["due"] == "2026-12-31" and show_capsule()["waiting"] == 2
    print("capsule self-test passed")
