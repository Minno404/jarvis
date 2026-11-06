"""Inventory mode: while desk view is open, the HUD reports what the camera's object detector sees, with a snapshot
when something new turns up. "Where did I leave my phone?" is answered from that (where_is), and a brain that can
see is pointed at the snapshot to say where exactly.
"""
import datetime
import re
import time

import features

FILE = "inventory.json"
S = {"type": "string"}


def seen(items, photo=None):
    """From the HUD: the objects the desk camera sees right now (and a snapshot, uploads/<photo>)."""
    inv = features._load(FILE, {})
    now = time.time()
    for it in {str(i).lower().strip()[:40] for i in items or [] if str(i).strip()}:
        e = inv.get(it, {})
        e["last_seen"] = now
        e.setdefault("first_seen", now)
        if photo and re.fullmatch(r"[\w.-]+\.(?:jpe?g|png|webp)", photo):
            e["photo"] = photo
        inv[it] = e
    features._save(FILE, inv)
    return {"saved": len(inv)}


def _ago(t):
    s = int(time.time() - t)
    if s < 90:
        return "just now"
    if s < 5400:
        return f"{s // 60} minutes ago"
    if s < 86400 * 2:
        return f"{s // 3600} hours ago"
    return datetime.datetime.fromtimestamp(t).strftime("%A %d %B at %H:%M")


def where_is(item):
    """When (and in which snapshot) the desk camera last saw something."""
    inv = features._load(FILE, {})
    want = item.lower().strip()
    want = {"phone": "cell phone", "mobile": "cell phone", "mug": "cup", "glasses": "wine glass",
            "controller": "remote", "tv remote": "remote"}.get(want, want)
    hits = [k for k in inv if want in k or k in want or want.rstrip("s") == k.rstrip("s")]
    if not hits:
        return {"found": False, "known": sorted(inv),
                "note": "The desk camera hasn't seen that. It only knows the things listed (common objects), and only "
                        "while desk view is open."}
    k = max(hits, key=lambda h: inv[h]["last_seen"])
    e = inv[k]
    out = {"found": True, "item": k, "last_seen": _ago(e["last_seen"]), "where": "on the desk camera"}
    if e.get("photo"):
        out["photo"] = f"uploads/{e['photo']}"
        out["note"] = "Look at the photo (Read it) to say where on the desk it was, if you can see pictures."
    return out


FUNCS = {"where_is": where_is}
TOOLS = [{"name": "where_is", "description": "Where/when the desk camera last saw an object ('where did I leave my "
          "phone?', 'have you seen my cup?'). Works for common objects seen while desk view was open.",
          "input_schema": {"type": "object", "required": ["item"], "properties": {"item": S}}}]


def selftest():
    import tempfile
    from pathlib import Path
    real = features.HERE
    features.HERE = Path(tempfile.mkdtemp())
    try:
        seen(["Cell phone", "cup"], "cam1.jpg")
        r = where_is("phone")
        assert r["found"] and r["item"] == "cell phone" and r["photo"] == "uploads/cam1.jpg" and r["last_seen"] == "just now"
        assert where_is("cups")["item"] == "cup" and not where_is("keys")["found"]
        seen(["book"], "../../evil.jpg")
        assert "photo" not in features._load(FILE, {})["book"]
    finally:
        features.HERE = real
    print("inventory self-test passed")


if __name__ == "__main__":
    selftest()
