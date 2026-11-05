"""'Undo that': Jarvis keeps a short history of what he changed for you and can reverse the last one.

Saved data (journal entries, memories, reminders, alerts, routines, the budget plan) is undone by putting the
file back exactly as it was. Live changes (HUD colour, personality, brain, panels, an app he opened, the TV)
are undone by doing the opposite. The history lives in undo.json, so it works across tools and restarts.
"""
import json
import time
from pathlib import Path

import features

STACK, KEEP = "undo.json", 20
_undoing = {"now": False}  # while undoing, the reversing action isn't itself recorded

# tool -> the saved files it changes (relative to the Jarvis folder; "plan" is the Spend Breakdown plan)
FILE_TOOLS = {"add_trade": ["journal.json"], "delete_trade": ["journal.json"], "remember": ["memory.json"],
              "forget": ["memory.json"], "add_reminder": ["reminders.json"], "cancel_reminder": ["reminders.json"],
              "add_alert": ["alerts.json"], "cancel_alert": ["alerts.json"], "save_routine": ["routines.json"],
              "set_spending_plan": ["plan"], "set_trading_rules": ["settings.json"],
              "add_bill": ["bills.json"], "bill_paid": ["bills.json"], "remove_bill": ["bills.json"],
              "add_habit": ["habits.json"], "log_habit": ["habits.json"], "remove_habit": ["habits.json"],
              "game_mode": ["settings.json"]}
LIVE_TOOLS = ("hud_background", "hud_colour", "set_persona", "set_brain", "hud_panel", "open_app", "tv_power", "quiet_mode")
SAY = {"add_trade": "logging that trade", "delete_trade": "deleting that trade", "remember": "remembering that",
       "forget": "forgetting that", "add_reminder": "that reminder", "cancel_reminder": "cancelling that reminder",
       "add_alert": "that price alert", "cancel_alert": "cancelling that alert", "save_routine": "that routine change",
       "set_spending_plan": "the budget change", "set_trading_rules": "the trading rules change",
       "hud_colour": "the colour change", "hud_background": "the background change", "set_persona": "the personality switch", "set_brain": "the brain switch",
       "hud_panel": "that panel change", "open_app": "opening {name}", "tv_power": "the TV power change",
       "quiet_mode": "the quiet mode change", "add_bill": "that bill", "bill_paid": "marking that bill paid",
       "remove_bill": "removing that bill", "add_habit": "that habit", "log_habit": "that habit log",
       "remove_habit": "removing that habit", "game_mode": "the game mode change"}


def _path(rel):
    if rel == "plan":
        import spending
        return Path(spending.app().DATA_DIR) / "plan.json"
    return features.HERE / rel


def _read(rel):
    try:
        p = _path(rel)
        return p.read_text(encoding="utf-8") if p.exists() else None
    except Exception:
        return None


def _push(entry):
    stack = features._load(STACK, [])
    features._save(STACK, (stack + [dict(entry, t=time.time())])[-KEEP:])


def _inverse(name, args, before, result):
    """The opposite of a live change, as (tool, args), or None if it can't be undone."""
    s = before
    if name == "hud_colour":
        return "hud_colour", {"colour": s.get("theme") or "blue"}
    if name == "hud_background":
        prev = s.get("background") or {}
        return "hud_background", ({"style": prev["style"], "dim": prev.get("dim", .55)} if prev.get("kind") == "style"
                                  else {"style": "default"})  # a replaced picture can't come back
    if name == "set_persona":
        return "set_persona", {"name": s.get("persona") or "jarvis"}
    if name == "set_brain":
        return "set_brain", {"brain": s.get("brain") or "auto"}
    if name == "quiet_mode":
        return "quiet_mode", {"on": bool(s.get("quiet"))}
    if name == "hud_panel":
        return "hud_panel", {"panel": args.get("panel"), "show": not args.get("show", True)}
    if name == "open_app" and isinstance(result, dict) and result.get("opened"):
        return "close_app", {"name": result["opened"]}
    if name == "tv_power":
        return "tv_power", {"on": not args.get("on")}
    return None


def wrap(name, fn):
    """fn with an undo step recorded after each successful call."""
    def run(*a, **kw):
        if _undoing["now"]:
            return fn(*a, **kw)
        files = FILE_TOOLS.get(name, [])
        snap = {rel: _read(rel) for rel in files}
        before = features.settings()
        result = fn(*a, **kw)
        if isinstance(result, dict) and result.get("error"):
            return result
        what = SAY.get(name, name).replace("{name}", str((result or {}).get("opened", "")) if isinstance(result, dict) else "")
        try:
            if files and any(_read(rel) != old for rel, old in snap.items()):
                _push({"what": what, "files": snap})
            elif name in LIVE_TOOLS:
                inv = _inverse(name, kw, before, result)
                if inv:
                    _push({"what": what, "do": inv[0], "args": inv[1]})
        except Exception as e:  # never let the history break the action itself
            print("undo history:", repr(e))
        return result
    run.__name__ = getattr(fn, "__name__", name)
    return run


def undo_last():
    """Undo the last thing Jarvis changed for him."""
    stack = features._load(STACK, [])
    if not stack:
        return {"error": "There's nothing to undo."}
    e = stack.pop()
    features._save(STACK, stack)
    if "files" in e:
        for rel, old in e["files"].items():
            p = _path(rel)
            if old is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(old, encoding="utf-8")
        if "reminders.json" in e["files"]:
            try:  # a cancelled timer's countdown shouldn't keep ticking on the HUD
                features._panel({"type": "clear_timers"})
            except OSError:
                pass
    else:
        _undoing["now"] = True
        try:
            r = features.REGISTRY[e["do"]](**e["args"])
        finally:
            _undoing["now"] = False
        if isinstance(r, dict) and r.get("error"):
            return {"error": f"Couldn't undo {e['what']}: {r['error']}"}
    return {"undone": e["what"], "left": len(stack)}


FUNCS = {"undo_last": undo_last}
TOOLS = [{"name": "undo_last", "description": "Undo the last thing you changed for him ('undo that', 'take that "
          "back'): a logged trade, memory, reminder, alert, routine, budget, colour, personality, panel, an app you "
          "opened, the TV. Say what you undid.",
          "input_schema": {"type": "object", "properties": {}}}]


def selftest():
    import tempfile
    real = features.HERE
    features.HERE = Path(tempfile.mkdtemp())
    reg = features.REGISTRY.copy()
    try:
        add = wrap("add_reminder", features.add_reminder)
        add("call Mum", in_minutes=30)
        assert len(features.list_reminders()) == 1
        assert undo_last() == {"undone": "that reminder", "left": 0} and features.list_reminders() == []
        assert undo_last()["error"] == "There's nothing to undo."
        rem = wrap("remember", features.remember)
        rem("first fact")
        rem("second fact")
        undo_last()
        assert [m["fact"] for m in features.memories()] == ["first fact"]
        calls = []
        features.REGISTRY["hud_colour"] = lambda colour: calls.append(colour) or {"colour": colour}
        features._save("settings.json", {"theme": "#ffc845"})
        wrap("hud_colour", lambda colour: (features._save("settings.json", {"theme": "#ff4d5e"}), {"colour": colour})[1])("red")
        assert undo_last()["undone"] == "the colour change" and calls == ["#ffc845"]
        features.REGISTRY["hud_colour"] = wrap("hud_colour", features.REGISTRY["hud_colour"])  # wrapped, as in Jarvis
        wrap("hud_colour", lambda colour: {"colour": colour})("red")
        n = len(features._load(STACK, []))
        undo_last()
        assert len(features._load(STACK, [])) == n - 1  # undoing doesn't add a new step
        features.REGISTRY["close_app"] = lambda name: calls.append(("close", name)) or {"closed": name}
        wrap("open_app", lambda name: {"opened": "Discord"})("discord")
        assert undo_last()["undone"] == "opening Discord" and calls[-1] == ("close", "Discord")
        n = len(features._load(STACK, []))
        assert wrap("add_reminder", features.add_reminder)("bad").get("error")  # failed calls leave no step
        assert len(features._load(STACK, [])) == n
    finally:
        features.HERE = real
        features.REGISTRY.clear()
        features.REGISTRY.update(reg)
    print("undo self-test passed")


if __name__ == "__main__":
    selftest()
