"""Dungeon master: Jarvis runs a voice tabletop adventure for {USER} and his mates, with real dice on the HUD.

"Jarvis, run a D&D adventure for me, Josh and Liam" starts one: Jarvis switches to the Dungeon Master voice and
style (personas.py "dm"), keeps the party (HP, items, gold), the place and the quest in dnd.json, rolls real dice
on the HUD and shows pictures of new places. "Continue our adventure" picks it up later; "end the adventure"
saves it and Jarvis is himself again.
"""
import random
import re
import time

import features
from features import _load, _save

S, I = {"type": "string"}, {"type": "integer"}


def _party_panel(st):
    items = [{"label": f"{p['name']} ({p['cls']})" + (" · DOWN" if p["hp"] <= 0 else ""), "value": max(0, p["hp"]),
              "max": p["max_hp"]} for p in st["party"]]
    note = " · ".join(x for x in (st.get("location") and f"At: {st['location']}", st.get("quest") and f"Quest: {st['quest']}",
                                 f"Gold: {st.get('gold', 0)}") if x)
    try:
        features._panel({"type": "panel", "kind": "progress", "title": st["title"], "items": items, "note": note,
                         "stay": True})
    except OSError:
        pass


def dnd_start(players, title="The Adventure", setting="classic fantasy"):
    """Start a new adventure. players: [{name, cls (class, e.g. fighter, rogue, wizard), hp}]."""
    party = []
    for p in players[:6]:
        p = {"name": p} if isinstance(p, str) else p
        hp = int(p.get("hp") or {"fighter": 14, "barbarian": 16, "paladin": 13, "ranger": 12, "rogue": 10,
                                   "cleric": 11, "bard": 10, "wizard": 8, "sorcerer": 8}.get(str(p.get("cls", "")).lower(), 11))
        party.append({"name": str(p.get("name", "Hero")), "cls": str(p.get("cls") or "adventurer"), "hp": hp,
                      "max_hp": hp, "items": [str(i) for i in p.get("items", [])][:12]})
    st = {"title": title, "setting": setting, "party": party, "location": "", "quest": "", "gold": 0, "log": [],
          "started": time.strftime("%Y-%m-%d %H:%M"), "rolls": []}
    _save("dnd.json", st)
    features.REGISTRY.get("set_persona", lambda name: None)("dm")
    _party_panel(st)
    return {"started": title, "party": party, "note": "You're the Dungeon Master now. Set the scene."}


def dnd_state():
    """The saved adventure (party, place, quest, the story so far), to continue it."""
    st = _load("dnd.json", None)
    if not st:
        return {"error": "No adventure saved yet."}
    _party_panel(st)
    return {**st, "log": st["log"][-15:], "rolls": st["rolls"][-5:]}


def dnd_roll(dice="1d20", who="", why="", dc=None):
    """Roll real dice on the HUD: '1d20+3', '2d6', 'd8-1'. dc: the number to beat, if there is one."""
    m = re.fullmatch(r"\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*", str(dice).lower())
    if not m:
        return {"error": "dice like 1d20+3 or 2d6"}
    n, sides, mod = int(m.group(1) or 1), int(m.group(2)), int((m.group(3) or "0").replace(" ", ""))
    if not (1 <= n <= 20 and 2 <= sides <= 100):
        return {"error": "1-20 dice of 2-100 sides"}
    rolls = [random.randint(1, sides) for _ in range(n)]
    total = sum(rolls) + mod
    r = {"dice": dice, "rolls": rolls, "modifier": mod, "total": total, "who": who, "why": why}
    if sides == 20 and n == 1:
        r["natural"] = "20" if rolls[0] == 20 else "1" if rolls[0] == 1 else ""
    if dc is not None:
        r["dc"], r["success"] = int(dc), total >= int(dc)
    st = _load("dnd.json", None)
    if st:
        st["rolls"] = (st["rolls"] + [r])[-30:]
        _save("dnd.json", st)
    try:
        features._panel({"type": "panel", "kind": "dice", "title": who or "Roll", **r})
    except OSError:
        pass
    return r


def dnd_update(hp=None, items_add=None, items_remove=None, gold=None, location=None, quest=None, note=None):
    """Keep the adventure up to date. hp: {name: change like -4 or +3}; items_add / items_remove: {name: [items]};
    gold: change; location, quest: new values; note: one line for the story so far."""
    st = _load("dnd.json", None)
    if not st:
        return {"error": "No adventure running. Start one with dnd_start."}
    by = {p["name"].lower(): p for p in st["party"]}
    find = lambda n: by.get(str(n).lower()) or next((p for k, p in by.items() if str(n).lower() in k), None)
    out = []
    for n, ch in (hp or {}).items():
        p = find(n)
        if p:
            p["hp"] = max(0, min(p["max_hp"], p["hp"] + int(ch)))
            out.append(f"{p['name']} {p['hp']}/{p['max_hp']} HP" + (" (down!)" if p["hp"] == 0 else ""))
    for n, its in (items_add or {}).items():
        p = find(n)
        if p:
            p["items"] = (p["items"] + [str(i) for i in its])[-20:]
    for n, its in (items_remove or {}).items():
        p = find(n)
        if p:
            for i in its:
                hit = next((x for x in p["items"] if str(i).lower() in x.lower()), None)
                if hit:
                    p["items"].remove(hit)
    if gold:
        st["gold"] = max(0, st.get("gold", 0) + int(gold))
    if location:
        st["location"] = location
    if quest:
        st["quest"] = quest
    if note:
        st["log"] = (st["log"] + [f"{time.strftime('%d %b')}: {note}"])[-200:]
    _save("dnd.json", st)
    _party_panel(st)
    return {"updated": out or True, "gold": st.get("gold", 0), "location": st["location"], "quest": st["quest"]}


def dnd_end(note=None):
    """End the session: save it and be Jarvis again."""
    if note:
        dnd_update(note=note)
    features.REGISTRY.get("set_persona", lambda name: None)("jarvis")
    return {"saved": True, "note": "Back to being Jarvis. 'Continue our adventure' picks it up later."}


FUNCS = {f.__name__: f for f in (dnd_start, dnd_state, dnd_roll, dnd_update, dnd_end)}
TOOLS = [
    {"name": "dnd_start", "description": "Start a tabletop (D&D-style) adventure with you as Dungeon Master, when he "
     "asks to play D&D / run an adventure / be the dungeon master. Ask who's playing and their class if he didn't say "
     "(keep it quick). players: [{name, cls, hp}]. Then set the opening scene.",
     "input_schema": {"type": "object", "required": ["players"], "properties": {
         "players": {"type": "array", "items": {"type": "object"}}, "title": S, "setting": S}}},
    {"name": "dnd_state", "description": "The saved adventure, to continue it ('continue our adventure'): party, "
     "place, quest and the story so far. Switch to the dm personality with set_persona and recap in 2 sentences.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "dnd_roll", "description": "Roll real dice on his HUD for anything left to chance (attacks, checks, "
     "saves, damage). Never make up a roll. dice like 1d20+3; who; why; dc = the number to beat.",
     "input_schema": {"type": "object", "required": ["dice"], "properties": {
         "dice": S, "who": S, "why": S, "dc": I}}},
    {"name": "dnd_update", "description": "Keep the adventure's state: hp changes {name: -4}, items_add/items_remove "
     "{name: [items]}, gold change, new location or quest, and a one-line note of what happened.",
     "input_schema": {"type": "object", "properties": {
         "hp": {"type": "object"}, "items_add": {"type": "object"}, "items_remove": {"type": "object"},
         "gold": I, "location": S, "quest": S, "note": S}}},
    {"name": "dnd_end", "description": "End the adventure session ('end the adventure', 'that's it for tonight'): "
     "saves it and switches you back to Jarvis. note: where they left off.",
     "input_schema": {"type": "object", "properties": {"note": S}}},
]


def selftest():
    import tempfile
    from pathlib import Path
    real = features.HERE
    features.HERE = Path(tempfile.mkdtemp())
    personas = []
    reg = features.REGISTRY.copy()
    features.REGISTRY["set_persona"] = personas.append
    try:
        s = dnd_start([{"name": "Sam", "cls": "rogue"}, {"name": "Josh", "cls": "wizard", "hp": 9}], "The Sunken Keep")
        assert [p["max_hp"] for p in s["party"]] == [10, 9] and personas == ["dm"]
        random.seed(1)
        r = dnd_roll("1d20+3", "Sam", "sneak past the guard", dc=12)
        assert r["total"] == r["rolls"][0] + 3 and r["success"] == (r["total"] >= 12)
        assert sum(dnd_roll("3d6")["rolls"]) <= 18 and "error" in dnd_roll("lots of dice")
        u = dnd_update(hp={"josh": -12, "Sam": +5}, items_add={"Sam": ["rusty key"]}, gold=15,
                       location="The flooded crypt", note="Found a key")
        assert u["updated"] == ["Josh 0/9 HP (down!)", "Sam 10/10 HP"] and u["gold"] == 15
        dnd_update(items_remove={"sam": ["key"]})
        st = dnd_state()
        assert st["party"][0]["items"] == [] and st["log"][-1].endswith("Found a key") and len(st["rolls"]) == 2
        dnd_end("At the crypt door")
        assert personas == ["dm", "jarvis"]
    finally:
        features.HERE = real
        features.REGISTRY.clear()
        features.REGISTRY.update(reg)
    print("dnd self-test passed")


if __name__ == "__main__":
    selftest()
