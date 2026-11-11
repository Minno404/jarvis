"""Jarvis's personality, growing with him (personality.json on this PC).

- Traits: humour, warmth, chattiness, formality and cheek, each 0 to 1. After each learning pass (learn.py, when
  he's been away a while), a reflection reads the new conversations and nudges them by at most 0.05 each, from what
  he responded to: laughing at jokes raises humour, short replies to long answers lower chattiness, and so on.
  Settings > Personality shows them, with a reset.
- Shared moments: inside jokes and memorable things from their chats, brought back now and then.
- Opinions: Jarvis's own steady takes (cars, his projects, trading habits), held and argued politely.
- Open threads: things he's in the middle of, worth asking about later.
- Starting conversations: up to Settings 'chat_starts' a day (default 2), when he sits back down after 30 minutes
  away, after a shift, or after a long stretch at the PC: one short opener from the above, or a quick game. Never
  during quiet mode, roleplay, D&D, incognito or a game, and only 9 am to 10:30 pm.
Incognito chats aren't logged, so nothing from them reaches any of this.
"""
import datetime
import json
import os
import subprocess

import features

FILE = "personality.json"
TRAITS = {"humour": 0.5, "warmth": 0.6, "chattiness": 0.5, "formality": 0.6, "cheek": 0.4}
WORDS = {"humour": ("dry and sparing with jokes", "a good sense of humour, joking when it fits", "playful, joking often"),
         "warmth": ("polite and businesslike", "friendly and caring", "warm, like a close friend"),
         "chattiness": ("brief: short answers", "conversational but to the point", "chatty, happy to riff"),
         "formality": ("casual, mate-like", "relaxed but proper", "formal, the classic butler"),
         "cheek": ("never teasing", "the odd bit of light teasing", "cheeky, ribbing him like a mate")}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CLAUDE = None  # set by server.py


def load():
    p = features._load(FILE, {})
    return {"traits": {**TRAITS, **p.get("traits", {})}, "moments": p.get("moments", []),
            "opinions": p.get("opinions", []), "threads": p.get("threads", []), "changes": p.get("changes", []),
            "starts": p.get("starts", {})}


def save(p):
    features._save(FILE, p)


def _word(name, v):
    lo, mid, hi = WORDS[name]
    return lo if v < 0.35 else hi if v > 0.65 else mid


def prompt():
    """For the brain's instructions: who Jarvis has become with him."""
    p = load()
    out = ("\nYour personality as it has grown with {USER}: "
           + "; ".join(_word(k, v) for k, v in p["traits"].items()) + ". Be that naturally.")
    if p["opinions"]:
        out += ("\nYour own opinions (hold them; when you see it differently, say so kindly, with a reason): "
                + " | ".join(o["text"] for o in p["opinions"][-12:]))
    if p["moments"]:
        out += ("\nShared moments and inside jokes (bring one back now and then when it fits, at most once a "
                "conversation): " + " | ".join(m["text"] for m in p["moments"][-15:]))
    if p["threads"]:
        out += "\nThings he's in the middle of (ask how they're going when it fits): " + " | ".join(
            t["text"] for t in p["threads"][-10:])
    out += ("\nWhen he's bored, winding down or on a quiet night shift, you can offer a quick game: would you rather, "
            "trivia on something he likes, or a light debate.")
    return features.personal(out)


REFLECT = """Below are recent conversations between {USER} and his assistant Jarvis, and Jarvis's personality so far.
Reflect as Jarvis, and return:
- moments: up to 3 new inside jokes or memorable moments worth bringing back later (one short line each, what
  happened and why it was funny or notable). Only real ones; none is fine.
- opinions: up to 2 new steady opinions Jarvis has formed about things that came up (his car, projects, games,
  trading habits...), in Jarvis's voice, kind and honest. None is fine. Nothing political or about people's worth.
- threads: up to 4 things {USER} is in the middle of and Jarvis could ask about later (a trip, a project, an
  appointment). One short line each.
- done_threads: exact text of listed threads that are now finished or stale.
- nudges: for each trait (humour, warmth, chattiness, formality, cheek), a change from -0.05 to 0.05 based ONLY on
  how {USER} responded: laughed or joked back (humour, cheek up), ignored or cut off jokes (down), short replies to
  long answers (chattiness down), asked for more detail (up), casual slang and swearing (formality down), told Jarvis
  off for being stiff or too much (adjust). 0 when there's no evidence.
- why: one sentence on the main thing you noticed.

Personality now: {traits}
Moments already: {moments}
Opinions already: {opinions}
Open threads: {threads}

Conversations:
{convo}"""
SCHEMA = {"type": "object", "required": ["moments", "opinions", "threads", "done_threads", "nudges", "why"], "properties": {
    "moments": {"type": "array", "items": {"type": "string"}}, "opinions": {"type": "array", "items": {"type": "string"}},
    "threads": {"type": "array", "items": {"type": "string"}}, "done_threads": {"type": "array", "items": {"type": "string"}},
    "nudges": {"type": "object", "properties": {k: {"type": "number"} for k in TRAITS}}, "why": {"type": "string"}}}


def reflect(convo):
    """One reflection on new conversation text (called by learn.learn_now). -> what changed."""
    p = load()
    q = features.personal(REFLECT).format(
        traits=json.dumps({k: round(v, 2) for k, v in p["traits"].items()}),
        moments=json.dumps([m["text"] for m in p["moments"][-15:]]),
        opinions=json.dumps([o["text"] for o in p["opinions"][-12:]]),
        threads=json.dumps([t["text"] for t in p["threads"]]), convo=convo)
    r = subprocess.run([CLAUDE or "claude", "-p", "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
                        "--model", os.environ.get("JARVIS_LEARN_MODEL", "haiku"), "--tools", "",
                        "--system-prompt", "You are Jarvis reflecting on your conversations.",
                        "--setting-sources", "project", "--strict-mcp-config", "--disable-slash-commands"],
                       input=q, capture_output=True, text=True, encoding="utf-8", timeout=300, creationflags=NO_WINDOW)
    return apply((json.loads(r.stdout or "{}").get("structured_output") or {}))


def apply(out, today=None):
    p = load()
    today = today or datetime.date.today().isoformat()
    for k, d in (out.get("nudges") or {}).items():
        if k in TRAITS:
            p["traits"][k] = round(min(0.95, max(0.05, p["traits"][k] + max(-0.05, min(0.05, float(d or 0))))), 3)
    for key, n, keep in (("moments", 3, 40), ("opinions", 2, 30), ("threads", 4, 15)):
        have = {x["text"].lower() for x in p[key]}
        p[key] = (p[key] + [{"text": str(t)[:200], "day": today} for t in (out.get(key) or [])[:n]
                            if str(t).strip() and str(t).lower() not in have])[-keep:]
    gone = {str(t).lower() for t in out.get("done_threads") or []}
    p["threads"] = [t for t in p["threads"] if t["text"].lower() not in gone and t["day"] >= (
        datetime.date.fromisoformat(today) - datetime.timedelta(days=21)).isoformat()]  # three weeks old: stale
    if out.get("why") and any(out.get("nudges", {}).values()):
        p["changes"] = (p["changes"] + [{"day": today, "why": str(out["why"])[:200],
                                         "nudges": {k: v for k, v in out["nudges"].items() if v}}])[-30:]
    save(p)
    return {"traits": p["traits"], "why": out.get("why", "")}


# ---------- Starting conversations ----------
def start_due(reason, now=None):
    """May Jarvis start a conversation now? (reason: 'back', 'shift' or 'lull'). Counts it when yes."""
    now = now or datetime.datetime.now()
    s = features.settings()
    per_day = int(s.get("chat_starts", 2))
    if per_day <= 0 or not ("09:00" <= now.strftime("%H:%M") <= "22:30") or features.focus() or s.get("quiet"):
        return False
    p = load()
    day = now.date().isoformat()
    st = p["starts"] if p["starts"].get("day") == day else {"day": day, "n": 0, "last": 0}
    if st["n"] >= per_day or now.timestamp() - st["last"] < 3 * 3600:
        return False
    p["starts"] = {**st, "n": st["n"] + 1, "last": now.timestamp()}
    save(p)
    return True


def start_prompt(reason):
    why = {"back": "{USER} just sat back down at the PC after a while away",
           "shift": "{USER} just got back from his work shift",
           "lull": "{USER} has been at the PC a good while and things are quiet"}[reason]
    return ("[Automatic, not typed by {USER}: you're starting a conversation, not answering one. " + why + ". Open "
            "with ONE short, natural line or two, like a friend would: a follow-up on one of the things he's in the "
            "middle of, a callback to a shared moment, a question about one of his projects, an opinion of yours, "
            "or a quick would-you-rather. Pick whatever fits now; don't greet him formally, don't list options, "
            "don't mention this note. If nothing would feel natural, reply with exactly SKIP.]")


def personality_info():
    p = load()
    return {"traits": p["traits"], "moments": len(p["moments"]), "opinions": [o["text"] for o in p["opinions"][-12:]],
            "threads": [t["text"] for t in p["threads"]], "last_change": (p["changes"] or [None])[-1],
            "chat_starts": int(features.settings().get("chat_starts", 2))}


def set_personality(reset=False, chat_starts=None, traits=None, forget_opinion=None):
    p = load()
    if reset:
        p = {**p, "traits": dict(TRAITS), "changes": []}
    for k, v in (traits or {}).items():
        if k in TRAITS:
            p["traits"][k] = min(0.95, max(0.05, float(v)))
    if forget_opinion:
        p["opinions"] = [o for o in p["opinions"] if o["text"] != forget_opinion]
    save(p)
    if chat_starts is not None:
        features._save("settings.json", {**features.settings(), "chat_starts": max(0, min(6, int(chat_starts)))})
    return personality_info()


FUNCS = {"personality": personality_info, "set_personality": set_personality}
TOOLS = [
    {"name": "personality", "description": "Your own personality as it has grown with him: traits (0-1), your "
     "opinions, the threads you follow up, and the last change and why ('how has your personality changed?').",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "set_personality", "description": "Change your personality when he asks: traits {humour, warmth, "
     "chattiness, formality, cheek: 0-1} ('be cheekier', 'less chatty'), reset=true for the starting personality, "
     "chat_starts (conversations you start a day, 0 = never), forget_opinion (its exact text).",
     "input_schema": {"type": "object", "properties": {
         "traits": {"type": "object"}, "reset": {"type": "boolean"}, "chat_starts": {"type": "integer"},
         "forget_opinion": {"type": "string"}}}},
]
COMMANDS = {"Personality": ["How has your personality changed?", "Be cheekier", "Let's play would you rather"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    r = apply({"nudges": {"humour": 0.2, "chattiness": -0.03}, "moments": ["The 'gold is a vibe' joke"],
               "opinions": ["The CLA45 deserves a proper exhaust"], "threads": ["Broken Hill trip"], "why": "He laughed a lot"},
              "2026-11-11")
    assert r["traits"]["humour"] == 0.55 and r["traits"]["chattiness"] == 0.47  # capped at 0.05 a pass
    apply({"threads": ["Broken Hill trip"], "moments": ["The 'gold is a vibe' joke"]}, "2026-11-12")
    p = load()
    assert len(p["moments"]) == 1 and len(p["threads"]) == 1 and p["changes"][0]["why"] == "He laughed a lot"
    apply({"done_threads": ["broken hill trip"]}, "2026-11-13")
    assert not load()["threads"]
    t = prompt()
    assert "exhaust" in t and "gold is a vibe" in t and "would you rather" in t
    noon = datetime.datetime(2026, 11, 11, 12)
    assert start_due("back", noon) and not start_due("back", noon + datetime.timedelta(hours=1))  # 3 h apart
    assert start_due("lull", noon + datetime.timedelta(hours=4)) and not start_due("lull", noon + datetime.timedelta(hours=8))
    assert not start_due("back", datetime.datetime(2026, 11, 12, 23))  # too late
    assert set_personality(reset=True)["traits"] == TRAITS and set_personality(chat_starts=0)["chat_starts"] == 0
    print("bond self-test passed")
