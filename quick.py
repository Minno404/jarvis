"""Everyday commands handled instantly on the PC, without asking Claude: zero tokens, and faster.

Only exact, simple phrasings are caught ("pause the music", "TV volume 15", "timer 20 minutes",
"open Discord"). Anything longer or unclear goes to Claude as normal.
"""
import datetime
import random
import re

import calc
import features
import hud

DONE = ["Done, {TITLE}.", "Right away, {TITLE}.", "As you wish.", "Done.", "Of course, {TITLE}."]
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
       "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50,
       "sixty": 60, "ninety": 90, "a": 1, "an": 1}
TV_APPS = r"(netflix|youtube|disney\+?|disney plus|amazon|prime video|stan|binge|kayo|spotify)"


def _clean(text):
    t = text.lower().strip()
    t = re.sub(r"^(hey |ok |okay )?jarvis[,.!]?\s*", "", t)
    t = re.sub(r"\b(please|could you|can you|would you|for me|now|thanks|thank you)\b", " ", t)
    t = re.sub(r"[^a-z0-9%+ ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _n(word):
    return int(word) if word.isdigit() else NUM.get(word)


def _ok(result, line=None):
    if isinstance(result, dict) and result.get("error"):
        return result["error"]
    return line or random.choice(DONE)


def custom_panels():
    """Titles and ids of panels that custom/ add-ons create, so 'show the task manager' works instantly."""
    names = set()
    for f in (features.HERE / "custom").glob("*.js"):
        for m in re.finditer(r"addPanel\(\s*\{([^}]*)\}", f.read_text(encoding="utf-8", errors="replace")):
            names |= {v.lower() for v in re.findall(r"(?:id|title)\s*:\s*['\"]([^'\"]+)['\"]", m.group(1))}
    return names


def quick(text):
    """A spoken reply if this was an everyday command that's now been done, else None (ask Claude)."""
    R, t = features.REGISTRY, _clean(text)
    if not t:
        return None
    if re.fullmatch(r"(?:what (?:else )?do|what are you able to do|help|help me|what do you do|"
                    r"(?:show|list|give)(?: me)?(?: all)?(?: of)?(?: the| your| my)?(?: possible| available)?(?: feature)? "
                    r"(?:commands|features|abilities)|what (?:are )?(?:your|the) (?:commands|features)|commands)", t) \
            and "show_commands" in R:
        R["show_commands"]()
        return "Here's everything I can do, {TITLE}. The starred ones are instant."
    sums = calc.answer(text)  # sums, tips, splits, conversions
    if sums:
        return sums
    # --- voice notes ---
    m = re.match(r"^\W*(?:(?:hey |ok )?jarvis\W*)?(?:take a note|make a note|note to self|note)(?: that)?[:,]?\s+(.{3,})$",
                 text.strip(), re.I)
    if m and "add_note" in R:
        return _ok(R["add_note"](m.group(1).strip().rstrip(".")), "Noted, {TITLE}.")
    if re.fullmatch(r"(?:read|what are|show|read me) (?:back )?my (?:latest |recent )?notes(?: this week| today)?", t) and "notes" in R:
        r = R["notes"](days=7)
        ns = r.get("notes", [])[-5:]
        if not ns:
            return "You've no notes this week, {TITLE}."
        return f"Your last {len(ns)} note{'s' if len(ns) > 1 else ''}: " + " ".join(f"{n['text']}." for n in ns)
    if re.fullmatch(r"(?:run |start |play |do )?(?:the |your |a )?boot ?up(?: sequence)?|(?:run |start |play )(?:the |your )?boot sequence|"
                    r"wake up(?: jarvis| daddy s home)?|daddy s home", t) and "boot_up" in R:
        R["boot_up"]()
        return "Initiating boot sequence."
    if re.fullmatch(r"(?:put |send )?(?:the |my )?(?:pc|computer) to sleep|sleep (?:the |my )?(?:pc|computer)|"
                    r"good ?night jarvis", t) and "sleep_pc" in R:
        import threading
        threading.Timer(4, R["sleep_pc"]).start()  # after the goodnight is said
        return "Goodnight, {TITLE}. Putting the PC to sleep."
    # --- workout ---
    m = re.fullmatch(r"(stop|end|cancel|pause|resume|skip)(?: the| my)? (?:workout|exercise)", t)
    if m:
        try:
            features._panel({"type": "workout_ctl", "do": m.group(1)})
        except OSError:
            pass
        return {"stop": "Workout stopped. Good effort, {TITLE}.", "end": "Workout over. Good effort, {TITLE}.",
                "cancel": "Workout cancelled.", "pause": "Paused.", "resume": "Back to it.", "skip": "Skipping."}[m.group(1)]
    if re.fullmatch(r"(?:what s|what is) the time|what time is it", t):
        now = datetime.datetime.now()
        return f"It's {now.hour % 12 or 12}:{now:%M} {now:%p}, {{TITLE}}."
    # --- music on the PC ---
    if re.fullmatch(r"(pause|play|resume|stop)( the)?( music| song| spotify| it)?", t):
        return _ok(R["media"]("play_pause"))
    if re.fullmatch(r"(next|skip)( the)?( song| track| one)?|skip this( song| track)?", t):
        return _ok(R["media"]("next"))
    if re.fullmatch(r"(previous|last|go back)( a)?( song| track)|previous", t):
        return _ok(R["media"]("previous"))
    # --- the TV ---
    if "tv" in t.split() or "telly" in t.split():
        m = re.fullmatch(r"(?:turn|switch|put) (on|off) the (?:tv|telly)|(?:turn|switch|put) the (?:tv|telly) (on|off)|"
                         r"(?:tv|telly) (on|off)", t)
        if m:
            on = (m.group(1) or m.group(2) or m.group(3)) == "on"
            return _ok(R["tv_power"](on), "The TV's on, {TITLE}." if on else "TV's off.")
        m = re.fullmatch(r"(?:(?:switch|change|put|set) )?(?:the )?tv (?:to |on )?(?:input )?(hdmi ?\d|av|tv|antenna)|"
                         r"(?:switch|change|put) (?:the tv )?to (hdmi ?\d)(?: on the tv)?", t)
        if m:
            src = (m.group(1) or m.group(2)).replace(" ", "").replace("antenna", "tv")
            return _ok(R["tv_input"](src), f"Switching to {src.upper()}.")
        m = re.fullmatch(r"(?:set )?(?:the )?tv volume (?:to )?(\w+)(?: percent)?|turn the tv (up|down)", t)
        if m:
            if m.group(2):
                return _ok(R["tv_volume"](change=3 if m.group(2) == "up" else -3))
            n = _n(m.group(1))
            return _ok(R["tv_volume"](level=n)) if n is not None else None
        m = re.fullmatch(r"(?:open|put on|launch|start) " + TV_APPS + r" on (?:the )?tv", t)
        if m:
            app = {"disney plus": "disney", "disney+": "disney", "prime video": "amazon"}.get(m.group(1), m.group(1))
            return _ok(R["tv_app"](app), f"Opening {m.group(1).title()} on the TV.")
        m = re.fullmatch(r"(?:tv )?channel (up|down)(?: on the tv)?", t)
        if m:
            return _ok(R["tv_keys"]([f"channel {m.group(1)}"]))
        m = re.fullmatch(r"(?:put the tv on |tv )?channel (\d+)(?: on the tv)?", t)
        if m:
            return _ok(R["tv_channel"](int(m.group(1))), f"Channel {m.group(1)}.")
        return None
    # --- the HUD's side panels ---
    m = re.fullmatch(r"(close|hide|remove|get rid of|open|show|reopen|bring up|bring back|restore) (?:the )?"
                     r"([a-z0-9 ]+?)(?: panels?)?", t)
    if m and (m.group(2) in hud.PANELS or m.group(2) in custom_panels()):
        show = m.group(1) in ("open", "show", "reopen", "bring up", "bring back", "restore")
        r = R["hud_panel"](m.group(2), show)
        return _ok(r, ("Done, {TITLE}." if not show else "Here you are, {TITLE}."))
    # --- Jarvis himself: restart or power down (never the PC: that needs saying "PC" and goes to Claude) ---
    if re.fullmatch(r"(?:restart|reboot|reload|reset) (?:yourself|jarvis|your ?self)|(?:restart|reboot) (?:your )?systems", t):
        return _ok(R["jarvis_power"]("restart"), "Restarting, {TITLE}. Back in a moment.")
    if re.fullmatch(r"power (?:yourself )?down|power off|shut (?:yourself|jarvis) down|shut ?down (?:yourself|jarvis)|"
                    r"close (?:yourself|jarvis)|(?:switch|turn) (?:yourself|jarvis) off", t):
        return _ok(R["jarvis_power"]("shutdown"), "Powering down. Goodbye, {TITLE}.")
    # --- undo the last thing Jarvis changed ---
    if re.fullmatch(r"undo(?: that| it| the last (?:thing|action|change)| last| your last (?:action|change))?|take that back|"
                    r"revert that|reverse that", t):
        r = R["undo_last"]()
        return r["error"] if r.get("error") else f"Undone: {r.get('undone', 'that')}."
    # --- quiet mode: hold routine announcements ---
    if re.fullmatch(r"(?:turn on |enable |start |switch to )?quiet mode(?: on)?|go quiet|hold (?:my|your) messages", t):
        return _ok(R["quiet_mode"](on=True), "Quiet mode. I'll hold anything routine until you say otherwise.")
    if re.fullmatch(r"(?:turn off |disable |end |stop |exit )quiet mode|quiet mode off|you can talk again", t):
        return _ok(R["quiet_mode"](on=False), "Quiet mode off.")
    # --- voices and personalities ---
    m = re.fullmatch(r"(?:switch to|change to|swap to|use|go|be|become|bring back|back to) (?:the )?(jarvis|friday|edith|"
                     r"jarvo|casual|aussie|mate|tactical|normal)(?: mode| voice| personality)?|(jarvis|friday|edith|jarvo|"
                     r"casual|aussie|tactical|normal) (?:mode|voice|personality)", t)
    if m:
        r = R["set_persona"](m.group(1) or m.group(2))
        hello = {"jarvis": "Back at your service, {TITLE}.", "friday": "FRIDAY here, boss. What do you need?",
                 "edith": "EDITH online. Standing by.", "mate": "G'day mate, Jarvo here. What are we up to?"}
        return _ok(r, hello.get(r.get("now"), "Done."))
    # --- which AI Jarvis thinks with ---
    m = re.fullmatch(r"(?:switch to|use|swap to|change to) (chat ?gpt|gpt|claude|auto(?:matic)?)(?: brain| mode)?|"
                     r"(chat ?gpt|claude|auto) mode", t)
    if m:
        b = (m.group(1) or m.group(2)).replace(" ", "")
        b = "chatgpt" if "gpt" in b else "auto" if b.startswith("auto") else "claude"
        r = R["set_brain"](b)
        return _ok(r, {"chatgpt": "Switching to ChatGPT, {TITLE}.", "claude": "Back on Claude, {TITLE}.",
                       "auto": "Automatic it is: Claude first, ChatGPT if the Claude allowance runs out."}[b])
    # --- the HUD's background ---
    m = re.fullmatch(r"(?:change|set|make|switch|turn) (?:the |your |my )?(?:hud )?background (?:to |into )?(?:a |an |the )?"
                     r"(?:picture of |photo of |image of )?(.+?)|(?:reset|default) (?:the )?background|background (\w+)", t)
    if m:
        what = (m.group(1) or m.group(2) or "default").strip()
        what = re.sub(r"^(?:a|an|the) ", "", what)
        if re.fullmatch(r"(?:my |the )?(?:last )?photo(?: i sent)?|(?:my|that) picture", what):
            return _ok(R["hud_background"](photo=True), "Your photo it is, {TITLE}.")
        key = hud.BG_ALIASES.get(what, what)
        if key in hud.BACKGROUNDS:
            return _ok(R["hud_background"](style=key), f"Background set to {hud.BACKGROUNDS[key]}.")
        r = R["hud_background"](query=what)
        return _ok(r, f"Background changed to {what}, {{TITLE}}.")
    # --- the HUD's colour ---
    m = re.fullmatch(r"(?:change|switch|set|make|turn) (?:the |your )?(?:hud |interface |screen )?(?:colou?r )?(?:to |into )?"
                     r"([a-z ]+?)(?: colou?r)?|(?:go|be) ([a-z]+)", t)
    if m and (m.group(1) or m.group(2)) in hud.COLOURS:
        name = m.group(1) or m.group(2)
        return _ok(R["hud_colour"](name), f"{name.title()} it is, {{TITLE}}.")
    # --- PC volume ---
    m = re.fullmatch(r"(?:set )?(?:the )?(?:pc |computer )?volume (?:to )?(\w+)(?: percent| %)?", t)
    if m and _n(m.group(1)) is not None:
        return _ok(R["set_volume"](_n(m.group(1))))
    if re.fullmatch(r"mute(?: the)?(?: pc| computer| sound| audio)?|unmute(?: the)?(?: pc| computer| sound)?", t):
        return _ok(R["media"]("mute"))
    # --- timers ---
    m = re.fullmatch(r"(?:set )?(?:a )?timer (?:for )?(\w+(?: five)?) (second|minute|min|hour)s?|"
                     r"(\w+(?: five)?) (second|minute|min|hour)s? timer", t)
    if m:
        n, unit = _n(m.group(1) or m.group(3)), (m.group(2) or m.group(4))
        if n:
            mins = n / 60 if unit == "second" else n * 60 if unit == "hour" else n
            label = f"{n} {'min' if unit == 'min' else unit}{'s' if n != 1 else ''}"
            r = R["add_reminder"](f"timer for {label}", in_minutes=mins)
            try:  # a live countdown on the HUD too
                R["show_panel"](f"Timer · {label}", "countdown", seconds=round(mins * 60))
            except Exception:
                pass
            return _ok(r, f"Timer set for {label}, {{TITLE}}.")
    # --- opening apps ---
    m = re.fullmatch(r"(?:open|launch|start|run) (?:up )?(?:the )?([a-z0-9+ ]{2,30})", t)
    if m and not re.search(r"\b(chart|journal|report|panel|briefing|my|trade|trades|on the tv)\b", m.group(1)):
        r = R["open_app"](m.group(1))
        return f"Opening {r['opened']}." if r.get("opened") else None  # not sure which app: let Claude sort it out
    return None


def selftest():
    calls = []
    rec = lambda name: (lambda *a, **k: calls.append((name, a, k)) or {"ok": True})
    for n in ("media", "tv_power", "tv_input", "tv_volume", "tv_app", "tv_keys", "tv_channel", "set_volume",
              "add_reminder", "hud_colour", "hud_panel", "show_panel", "set_brain", "set_persona", "jarvis_power", "undo_last", "quiet_mode", "hud_background"):
        features.REGISTRY[n] = rec(n)
    features.REGISTRY["open_app"] = lambda name: calls.append(("open_app", (name,), {})) or (
        {"opened": "Discord"} if name == "discord" else {"error": "no", "candidates": []})
    cases = {
        "Hey Jarvis, pause the music.": ("media", ("play_pause",), {}),
        "next song": ("media", ("next",), {}),
        "Jarvis turn on the TV": ("tv_power", (True,), {}),
        "turn the TV off please": ("tv_power", (False,), {}),
        "switch the TV to HDMI 2": ("tv_input", ("hdmi2",), {}),
        "TV volume 15": ("tv_volume", (), {"level": 15}),
        "turn the tv down": ("tv_volume", (), {"change": -3}),
        "open Netflix on the TV": ("tv_app", ("netflix",), {}),
        "channel 7": None,  # no 'tv' word: ambiguous on its own, so Claude decides
        "tv channel 7": ("tv_channel", (7,), {}),
        "set volume to 30": ("set_volume", (30,), {}),
        "timer 20 minutes": ("add_reminder", ("timer for 20 minutes",), {"in_minutes": 20}),
        "set a timer for five minutes": ("add_reminder", ("timer for 5 minutes",), {"in_minutes": 5}),
        "open Discord": ("open_app", ("discord",), {}),
        "Jarvis, change the colour to red": ("hud_colour", ("red",), {}),
        "make the HUD gold": ("hud_colour", ("gold",), {}),
        "switch your colour to iron man": ("hud_colour", ("iron man",), {}),
        "go purple": ("hud_colour", ("purple",), {}),
        "close the MT5 journal": ("hud_panel", ("mt5 journal", False), {}),
        "Jarvis, bring back the systems panel": ("hud_panel", ("systems", True), {}),
        "show all panels": ("hud_panel", ("all", True), {}),
        "switch to ChatGPT": ("set_brain", ("chatgpt",), {}),
        "use claude": ("set_brain", ("claude",), {}),
        "auto mode": ("set_brain", ("auto",), {}),
        "switch to FRIDAY": ("set_persona", ("friday",), {}),
        "Jarvis, casual mode": ("set_persona", ("casual",), {}),
        "back to Jarvis": ("set_persona", ("jarvis",), {}),
        "Jarvis, restart yourself": ("jarvis_power", ("restart",), {}),
        "power down": ("jarvis_power", ("shutdown",), {}),
        "Jarvis, undo that": ("undo_last", (), {}),
        "take that back": ("undo_last", (), {}),
        "quiet mode": ("quiet_mode", (), {"on": True}),
        "quiet mode off": ("quiet_mode", (), {"on": False}),
        "change the background to stars": ("hud_background", (), {"style": "stars"}),
        "make the background black": ("hud_background", (), {"style": "dark"}),
        "set the background to a picture of a city at night": ("hud_background", (), {"query": "city at night"}),
        "reset the background": ("hud_background", (), {"style": "default"}),
        "shut yourself down": ("jarvis_power", ("shutdown",), {}),
    }
    for said, want in cases.items():
        calls.clear()
        reply = quick(said)
        if want is None:
            assert reply is None, (said, reply)
        else:
            assert calls and calls[0] == want and reply, (said, calls, reply)
    for said in ("open the gold chart", "how did I go today", "pause my trading for a week and review it",
                 "what's the TV doing tonight", "turn the lights red", "change my red trades to green",
                 "restart my PC", "shut down the computer", "open the thing I used yesterday", "remind me to call Mum at 6"):
        calls.clear()
        assert quick(said) is None or calls[0][0] == "open_app", said
    assert quick("open the thing I used yesterday") is None  # app not found: Claude handles it
    assert quick("what's 15% of 240") == "15% of 240 is 36."
    features.REGISTRY["show_commands"] = rec("show_commands")
    for said in ("what can you do", "Jarvis, show all commands", "help", "show me all possible feature commands", "list your features"):
        calls.clear()
        assert quick(said) and calls[0][0] == "show_commands", said
    features.REGISTRY["sleep_pc"] = rec("sleep_pc")
    import threading
    real_timer = threading.Timer
    threading.Timer = lambda d, f: type("T", (), {"start": lambda self: f()})()
    calls.clear()
    assert quick("Jarvis, put the PC to sleep") and calls[0][0] == "sleep_pc"
    threading.Timer = real_timer
    features.REGISTRY["boot_up"] = rec("boot_up")
    calls.clear()
    assert quick("Jarvis, run the boot sequence") and calls[0][0] == "boot_up"
    calls.clear()
    assert quick("wake up, daddy's home") and calls[0][0] == "boot_up"
    features.REGISTRY["add_note"] = rec("add_note")
    calls.clear()
    assert quick("Jarvis, take a note: ask the landlord about the leak") and calls[0] == ("add_note", ("ask the landlord about the leak",), {})
    assert quick("what time is it").startswith("It's")
    print("quick self-test passed")


if __name__ == "__main__":
    selftest()
