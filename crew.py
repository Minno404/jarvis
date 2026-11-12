"""Crews: shared memory between friends' Jarvises (a D&D campaign, a Gun Bros session, a trip).

Making one ("make a crew called Friday D&D") gives a crew code like JV-7KQ2M-X9PLD-4TRWH-HB3NC. Only someone
with the code can join: friends type "join crew JV-..." in their own Jarvis. Each Jarvis says who it belongs to
(the owner's name and its own ID), so notes show who added them; "who's in the crew" lists everyone.

How it stays private: everything goes through ntfy.sh (the same service as phone alerts), on a topic name worked
out from the code, and every message is encrypted and signed with a key also worked out from the code (a SHA-256
key stream and an HMAC signature, Python's standard library). Without the code nobody can find the topic, read a
note or slip one in; ntfy only ever sees scrambled text. To remove someone, "new crew code" starts a fresh crew with
the same notes and a new code to give the others.
ntfy keeps messages for about 12 hours, so each Jarvis keeps its own copy of the notes (crew.json) and, when it
comes online, asks the crew for anything it missed; any Jarvis that's on answers with its copy.
"""
import base64
import datetime
import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.request

import features

FILE = "crew.json"
ABC = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I to misread


def new_code():
    return "JV-" + "-".join("".join(secrets.choice(ABC) for _ in range(5)) for _ in range(4))  # 100 bits


def norm(code):
    c = "".join(ch for ch in str(code).upper() if ch in ABC)
    c = c[2:] if c.startswith("JV") and len(c) == 22 else c
    return "JV-" + "-".join(c[i:i + 5] for i in range(0, 20, 5)) if len(c) == 20 else None


def _keys(code):
    h = lambda tag: hashlib.sha256(f"jarvis-crew:{tag}:{code}".encode()).digest()
    return "jarvis-crew-" + h("topic").hex()[:28], h("enc"), h("mac")


def seal(code, obj):
    _, enc, mac = _keys(code)
    raw, nonce = json.dumps(obj, separators=(",", ":")).encode(), secrets.token_bytes(16)
    stream = b"".join(hashlib.sha256(enc + nonce + i.to_bytes(4, "big")).digest() for i in range(len(raw) // 32 + 1))
    ct = bytes(a ^ b for a, b in zip(raw, stream))
    tag = hmac.new(mac, nonce + ct, hashlib.sha256).digest()
    return base64.b64encode(nonce + ct + tag).decode()


def unseal(code, text):
    """The message, or None if it isn't from someone with this code (wrong key, tampered, or not ours)."""
    _, enc, mac = _keys(code)
    try:
        b = base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        return None
    nonce, ct, tag = b[:16], b[16:-32], b[-32:]
    if len(b) < 49 or not hmac.compare_digest(tag, hmac.new(mac, nonce + ct, hashlib.sha256).digest()):
        return None
    stream = b"".join(hashlib.sha256(enc + nonce + i.to_bytes(4, "big")).digest() for i in range(len(ct) // 32 + 1))
    try:
        return json.loads(bytes(a ^ b for a, b in zip(ct, stream)))
    except ValueError:
        return None


def me():
    s = features.settings()
    if not s.get("jarvis_id"):
        s = {**s, "jarvis_id": secrets.token_hex(4)}
        features._save("settings.json", s)
    return {"name": s.get("name") or "Someone", "id": s["jarvis_id"]}


def _server():
    return (features.settings().get("ntfy_server") or "https://ntfy.sh").rstrip("/")


def _post(code, obj):
    topic = _keys(code)[0]
    req = urllib.request.Request(f"{_server()}/{topic}", data=seal(code, obj).encode(), method="POST")
    urllib.request.urlopen(req, timeout=15).close()


def _fetch(code, since="12h"):
    topic = _keys(code)[0]
    with urllib.request.urlopen(f"{_server()}/{topic}/json?poll=1&since={since}", timeout=20) as r:
        lines = r.read().decode("utf-8", "ignore").splitlines()
    out = []
    for line in lines:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("event") == "message":
            obj = unseal(code, m.get("message", ""))
            if obj:  # anything without the crew's key is ignored
                out.append((m["id"], obj))
    return out


def _load():
    return features._load(FILE, {"crews": {}})


def _save(d):
    features._save(FILE, d)


def _find(d, crew=None):
    cs = d["crews"]
    if not cs:
        return None
    if crew is None:
        return next(iter(cs.values())) if len(cs) == 1 else None
    c = str(crew).lower()
    return next((x for x in cs.values() if x["name"].lower() == c or x["code"] == norm(crew)), None)


def _apply(crew, obj):
    """Merge one message into the crew's copy. -> True if it changed anything."""
    who = obj.get("from") or {}
    if who.get("id"):
        crew["members"][who["id"]] = {"name": who.get("name", "?"), "seen": obj.get("at", "")}
    if obj.get("t") == "note" and obj.get("note", {}).get("id") not in {n["id"] for n in crew["notes"]}:
        crew["notes"] = sorted(crew["notes"] + [obj["note"]], key=lambda n: n["at"])[-500:]
        return True
    if obj.get("t") == "snapshot":
        have = {n["id"] for n in crew["notes"]}
        new = [n for n in obj.get("notes", []) if n.get("id") not in have]
        crew["notes"] = sorted(crew["notes"] + new, key=lambda n: n["at"])[-500:]
        if obj.get("crew_name") and not crew.get("named"):
            crew["name"], crew["named"] = obj["crew_name"], True
        return bool(new)
    return False


def _msg(t, **kw):
    return {"t": t, "from": me(), "at": datetime.datetime.now().isoformat(timespec="seconds"), **kw}


def create_crew(name):
    """Start a crew; returns the code to give friends (only people with it can join)."""
    d = _load()
    code = new_code()
    d["crews"][code] = {"name": str(name)[:40] or "Crew", "named": True, "code": code, "owner": me(), "members": {},
                        "notes": [], "last": "12h"}
    _save(d)
    try:
        _post(code, _msg("hello", crew_name=name))
    except OSError:
        pass
    return {"crew": name, "code": code, "note": "Give this code to your friends privately; they say 'join crew' and "
            "the code in their own Jarvis. Anyone with it can read and add notes."}


def join_crew(code):
    """Join a friend's crew with its code (asks the others for the notes so far)."""
    c = norm(code)
    if not c:
        return {"error": "That isn't a crew code (they look like JV-XXXXX-XXXXX-XXXXX-XXXXX)."}
    d = _load()
    if c in d["crews"]:
        return {"error": f"Already in that crew ({d['crews'][c]['name']})."}
    try:
        msgs = _fetch(c)
    except OSError as e:
        return {"error": f"Couldn't reach the crew right now: {e}"}
    crew = {"name": "Crew", "named": False, "code": c, "members": {}, "notes": [], "last": "12h"}
    for _id, obj in msgs:
        if obj.get("crew_name") and not crew["named"]:
            crew["name"], crew["named"] = obj["crew_name"], True
        _apply(crew, obj)
    d["crews"][c] = crew
    _save(d)
    _post(c, _msg("hello"))
    _post(c, _msg("sync"))  # anyone online sends what they have
    return {"joined": crew["name"], "members": [m["name"] for m in crew["members"].values()],
            "note": "Joined. Notes from the others arrive within a minute when one of their Jarvises is on."
            if not msgs else f"Joined, {len(crew['notes'])} notes so far."}


def crew_note(text, crew=None, topic=""):
    """Add a note to a crew's shared memory (topic: e.g. 'D&D', 'Gun Bros')."""
    d = _load()
    c = _find(d, crew)
    if not c:
        return {"error": "Which crew?" if d["crews"] else "You're not in a crew yet.", "crews": [x["name"] for x in d["crews"].values()]}
    note = {"id": secrets.token_hex(6), "at": datetime.datetime.now().isoformat(timespec="minutes"), "by": me()["name"],
            "topic": str(topic)[:30], "text": str(text)[:1000]}
    _apply(c, _msg("note", note=note))
    _save(d)
    try:
        _post(c["code"], _msg("note", note=note))
    except OSError:
        return {"saved": True, "note": "Saved here; it'll reach the crew when the connection's back."}
    return {"shared": note}


def crew_notes(crew=None, search="", show=True):
    """The crew's shared notes (newest last), optionally only those mentioning `search`."""
    d = _load()
    c = _find(d, crew)
    if not c:
        return {"error": "Which crew?" if d["crews"] else "You're not in a crew yet.", "crews": [x["name"] for x in d["crews"].values()]}
    notes = [n for n in c["notes"] if search.lower() in (n["text"] + n.get("topic", "")).lower()]
    if show:
        features._panel({"type": "panel", "kind": "list", "title": f"Crew: {c['name']}", "stay": True,
                         "items": [{"text": n["text"], "sub": f"{n['by']} · {n['at'][5:16].replace('T', ' ')}"
                                    + (f" · {n['topic']}" if n.get("topic") else "")} for n in notes[-12:][::-1]]
                         or [{"text": "No notes yet", "sub": "Say 'add to the crew notes: ...'"}],
                         "note": f"{len(c['members']) + 1} Jarvises: " + ", ".join(
                             [me()["name"] + " (you)"] + [m["name"] for k, m in c["members"].items() if k != me()["id"]])})
    return {"crew": c["name"], "notes": notes[-40:]}


def crew_members(crew=None):
    d = _load()
    c = _find(d, crew)
    if not c:
        return {"error": "Which crew?" if d["crews"] else "You're not in a crew yet."}
    return {"crew": c["name"], "members": [{"name": m["name"], "jarvis": k, "last_seen": m["seen"]}
                                          for k, m in c["members"].items() if k != me()["id"]]}


def my_crews():
    return {"crews": [{"name": c["name"], "notes": len(c["notes"]), "members": len(c["members"])} for c in _load()["crews"].values()]}


def crew_code(crew=None):
    """The crew's code, to invite someone (say it only to people you want in)."""
    c = _find(_load(), crew)
    return {"crew": c["name"], "code": c["code"]} if c else {"error": "Which crew?"}


def new_crew_code(crew=None):
    """Lock someone out: a fresh crew (new code) with the same notes. Give the new code to the people you keep."""
    d = _load()
    c = _find(d, crew)
    if not c:
        return {"error": "Which crew?"}
    code = new_code()
    d["crews"].pop(c["code"])
    d["crews"][code] = {**c, "code": code, "members": {}, "last": "12h"}
    _save(d)
    try:
        _post(code, _msg("hello", crew_name=c["name"]))
    except OSError:
        pass
    return {"crew": c["name"], "code": code, "note": "The old code no longer reaches this crew. Give the new one to "
            "the friends you want to keep; they join with it."}


def leave_crew(crew=None):
    d = _load()
    c = _find(d, crew)
    if not c:
        return {"error": "Which crew?"}
    d["crews"].pop(c["code"])
    _save(d)
    return {"left": c["name"]}


def sync_once():
    """Read every crew's new messages; answer 'sync' requests with our copy."""
    d = _load()
    changed = False
    for c in d["crews"].values():
        try:
            msgs = _fetch(c["code"], c.get("last", "12h"))
        except OSError:
            continue
        for mid, obj in msgs:
            c["last"] = mid
            changed |= _apply(c, obj)
            if obj.get("t") == "sync" and (obj.get("from") or {}).get("id") != me()["id"] and c["notes"]:
                try:  # a friend just came online: send the notes they may have missed (in parts: ntfy's size limit)
                    for i in range(0, len(c["notes"]), 8):
                        _post(c["code"], _msg("snapshot", notes=c["notes"][i:i + 8], crew_name=c["name"]))
                except OSError:
                    pass
        changed = True
    if changed:
        _save(d)


def start():
    """Keep crews in sync every 30 seconds (asks for missed notes once at start)."""
    def loop():
        for c in _load()["crews"].values():
            try:
                _post(c["code"], _msg("sync"))
            except OSError:
                pass
        while True:
            if _load()["crews"]:
                try:
                    sync_once()
                except Exception as e:
                    print("crew sync:", repr(e)[:120])
            time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()


FUNCS = {f.__name__: f for f in (create_crew, join_crew, crew_note, crew_notes, crew_members, my_crews, crew_code,
                                 new_crew_code, leave_crew)}
S = {"type": "string"}
C = {"crew": {"type": "string", "description": "crew name (only needed if he's in more than one)"}}
TOOLS = [
    {"name": "create_crew", "description": "Start a crew: shared memory with friends' Jarvises (a D&D campaign, a game "
     "group). Returns a code only people he gives it to can join with.", "input_schema": {"type": "object",
                                                                                     "required": ["name"], "properties": {"name": S}}},
    {"name": "join_crew", "description": "Join a friend's crew with the code they gave him (JV-XXXXX-...).",
     "input_schema": {"type": "object", "required": ["code"], "properties": {"code": S}}},
    {"name": "crew_note", "description": "Add to a crew's shared memory (campaign events, loot, plans, who owes what). "
     "During a D&D adventure with a crew, add the important events here too so every Jarvis remembers them.",
     "input_schema": {"type": "object", "required": ["text"], "properties": {"text": S, "topic": S, **C}}},
    {"name": "crew_notes", "description": "Show a crew's shared notes ('what happened last session', 'crew notes'), "
     "search: only notes mentioning it.", "input_schema": {"type": "object", "properties": {"search": S, **C}}},
    {"name": "crew_members", "description": "Who's in a crew (each friend's Jarvis, by owner).",
     "input_schema": {"type": "object", "properties": C}},
    {"name": "my_crews", "description": "The crews he's in.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "crew_code", "description": "A crew's code, to invite someone. Only when he asks.",
     "input_schema": {"type": "object", "properties": C}},
    {"name": "new_crew_code", "description": "Lock someone out of a crew: a new code (same notes). Only when he asks.",
     "input_schema": {"type": "object", "properties": C}},
    {"name": "leave_crew", "description": "Leave a crew.", "input_schema": {"type": "object", "properties": C}},
]
COMMANDS = {"Crews": ["Make a crew called Friday D&D", "Join crew JV-…", "Show the crew notes"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    features._save("settings.json", {"name": "Halen"})
    code = new_code()
    assert norm(code) == code and norm(code.lower().replace("-", " ")) == code and norm("JV-123") is None
    sealed = seal(code, {"t": "note", "x": "secret loot"})
    assert "secret" not in base64.b64decode(sealed).decode("latin-1")
    assert unseal(code, sealed) == {"t": "note", "x": "secret loot"}
    assert unseal(new_code(), sealed) is None  # wrong code: unreadable
    b = bytearray(base64.b64decode(sealed))
    b[20] ^= 1
    assert unseal(code, base64.b64encode(bytes(b)).decode()) is None  # tampered: rejected
    # two Jarvises on a fake ntfy
    bus = {}

    def fake_post(c, obj):
        bus.setdefault(_keys(c)[0], []).append((str(len(bus.get(_keys(c)[0], [])) + 1), obj))

    def fake_fetch(c, since="12h"):
        msgs = bus.get(_keys(c)[0], [])
        return msgs if since == "12h" else [m for m in msgs if int(m[0]) > int(since)]
    _post, _fetch = fake_post, fake_fetch
    r = create_crew("Friday D&D")
    assert crew_note("The party found the Sunstone", topic="D&D")["shared"]["by"] == "Halen"
    halen = features.HERE
    features.HERE = Path(tempfile.mkdtemp())  # Josh's PC
    features._save("settings.json", {"name": "Josh"})
    j = join_crew(r["code"].lower())
    assert j["joined"] == "Friday D&D" and j["members"] == ["Halen"]
    assert crew_notes(show=False)["notes"][0]["text"] == "The party found the Sunstone"
    crew_note("Liam owes 20 gold")
    features.HERE = halen
    sync_once()
    n = crew_notes(show=False)["notes"]
    assert [x["text"] for x in n] == ["The party found the Sunstone", "Liam owes 20 gold"] and n[1]["by"] == "Josh"
    assert crew_members()["members"][0]["name"] == "Josh"
    assert join_crew("JV-AAAAA-BBBBB-CCCCC-DDDDD").get("joined") == "Crew"  # empty topic: a crew with no messages
    leave_crew("Crew")
    nc = new_crew_code()
    assert nc["code"] != r["code"] and crew_notes(show=False)["crew"] == "Friday D&D" and len(crew_notes(show=False)["notes"]) == 2
    print("crew self-test passed")
