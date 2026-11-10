"""Everything you can ask Jarvis, as a searchable panel: "what can you do?", "show your commands", "help".

Phrases marked * are instant (done on the PC, no Claude, no tokens). The rest are examples: say them your own way.
"""
import features

COMMANDS = {
    "Talking to Jarvis": ["*Hey Jarvis…", "*Hold on", "*Undo that", "*Quiet mode",
                          "*Quiet mode off", "*Stop listening", "*Unmute", "*Restart yourself", "*Power down", "*Jarvis split", "*Jarvis merge",
                          "*Merge with ChatGPT", "*Switch to ChatGPT", "*Switch to Claude", "*Switch to DeepSeek", "*Switch to local", "*Online mode", "*Offline mode", "*Swap brain", "*Auto mode",
                          "*Switch to FRIDAY", "*Casual mode", "*Back to Jarvis", "*What can you do?"],
    "Looks and the HUD": ["*Make the HUD red", "*Change the background to stars",
                          "*Set the background to a picture of a city at night", "*Reset the background",
                          "Show me a picture of ...", "*Close the MT5 journal", "*Show all panels",
                          "*Boot up", "*Wake up, daddy's home", "*Enlarge the systems panel",
                          "*Enlarge the weather", "*Shrink it", "*Holo mode", "*Exit holo mode"],
    "Desk camera": ["*Desk view", "*What am I holding?", "*Room scan", "*What's on my desk?", "*Inventory mode",
                    "Where did I leave my phone?", "*Gesture control", "*Gestures off", "*Count my squats",
                    "*Spot my push-ups", "*Count my curls", "*Count my jumping jacks", "*I'm done",
                    "*Enlarge desk view", "*Close desk view"],
    "Morning radio": ["*Morning radio", "*Jarvis FM"],
    "Blueprint mode": ["*Blueprint this (hold something up to the camera)", "*Attach a photo + blueprint this", "*Pull it apart",
                       "*What's inside it?", "*Put it back together",
                       "*Enlarge blueprint (3D: click a part, drag to move, drag again to turn)",
                       "*Export it for 3D printing", "*Save it as a GLB", "*Pull the engine apart (open up one section)"],
    "Simulations": ["Simulate saving $50 a week for a year", "Compare saving $50, $100 and $150 a week for 2 years",
                    "What if I pay $200 more a month off the car loan?", "Simulate cutting my takeaway spending in half"],
    "Hologram workshop": ["*Hologram workshop", "*Show me the model player", "*Hologram of the pistol",
                          "Drop a .glb/.obj/.stl/.fbx on the panel", "*Spin it", "*Stop spinning", "*Close the workshop",
                          "With gestures on: move your hand to turn it, pinch to zoom"],
    "Picking up where you left off": ["*Where was I?", "*What was I doing?", "*Reopen them",
                                      "*Finish this (an email, form or message on screen)", "*Type it", "*Don't type it",
                                      "Walk away from the PC: your phone picks up the conversation"],
    "Music and your PC": ["*Pause the music", "*Next song", "*Volume up", "*Quieter", "*Set volume to 30", "*Mute", "*Open Discord",
                          "Close Chrome", "Clip that", "What's on my screen?", "What's this error?",
                          "Clean up my PC", "What's hogging my memory?",
                          "Game mode: close Chrome and Spotify when I game", "Find the bank PDF from last month",
                          "Any errors on my PC today?", "Take a screenshot", "*Put the PC to sleep",
                          "*Goodnight Jarvis"],
    "TV": ["*Turn on the TV", "*Turn off the TV", "*Open Netflix on the TV", "*TV volume 15",
           "*Switch the TV to HDMI 2", "*TV channel 7", "*Turn the TV down"],
    "Time, reminders and weather": ["*What time is it?", "*Timer 20 minutes", "Remind me to call Mum at 6",
                                    "What are my reminders?", "Cancel that reminder", "What's the weather tomorrow?",
                                    "Give me my morning brief"],
    "Notes and lists": ["*Note: ask the landlord about the leak", "*Read my notes",
                        "What did I note about the landlord?", "Add milk to my list", "What's on my list?",
                        "Got the milk", "Clear my list"],
    "Food and shopping": ["What can I make with chicken, rice and capsicum?", "Show that recipe again",
                          "How much is coffee at Coles?", "Tell me when coffee beans are under $10",
                          "Watch this PS5 and tell me under $600 (paste the link)", "What prices am I watching?"],
    "Money and bills": ["*Pull up my spending report", "*Close the spending report", "Add my car rego, $420, due 12 December, yearly", "Show my bills", "I paid the rego",
                        "How's my spending this month?", "Set a spending plan", "*Split $142 four ways with a 10% tip",
                        "*10% tip on $80", "*100 US dollars to Aussie dollars"],
    "Health and habits": ["Give me a 20-minute workout", "Quick ab workout, no equipment", "*Pause the workout",
                          "*Skip the exercise", "*Stop the workout", "I went to the gym",
                          "Track running, 3 times a week", "How are my habits going?"],
    "Handy": ["Search the web for the best budget headphones", "Read this page for me (paste a link)", "*What's 15% of 240?", "*12 times 7 plus 3", "*180 Celsius in Fahrenheit", "*5 km in miles",
              "*2 cups in ml", "How do I say 'where's the bathroom' in Japanese?",
              "Translate 'thank you very much' into French"],
    "Gaming": ["Coach me", "Watch my gameplay and only give me a review at the end", "Coach every game from now on",
               "What am I doing wrong?", "Stop coaching", "How did I play?"],
    "Fun": ["Run a D&D adventure for me, Josh and Liam", "Continue our adventure", "Roll a d20", "End the adventure",
            "Triple-click the core: Claude vs ChatGPT, pros and cons"],
    "Coding and PC jobs": ["Ask the coder to add a dark mode to my Gun Bros project", "Do this on my PC: tidy my Downloads",
                           "How's that job going?", "Add my project Tavern Table at C:\\Projects\\tavern",
                           "Test ChatGPT coding (finds what's blocking it)", "*Disk doctor", "*What's filling my drive?", "*Token usage", "*How many tasks have I got left?", "*Go incognito", "*Leave incognito", "*Install REA", "*Bring up my work shifts", "Here's my roster (send a photo)",
                           "*Free up space"],
    "Trading": ["Bring up my trading journal", "Give me a report", "Market briefing", "Show the gold chart",
                "Buy 0.1 gold, stop 2310, target 2350 (you click Confirm)", "Move my stop to break-even", "Close my gold trade",
                "*Make me money (trading autopilot)", "*Stop trading", "*Test trade", "*Screens off", "How's the autopilot doing?", "Set my risk per trade to 1%",
                "Replay my last loss", "Pre-trade check", "Am I on tilt?", "Session debrief",
                "Alert me when gold hits 2400", "Log a trade: long gold at 2380, closed +$40",
                "Set my trading rules: no trades after 11pm"],
    "Memory and routines": ["Remember that my sister's birthday is 3 March", "What do you know about me?",
                            "Forget that", "Run night protocol", "Save a routine called movie night: dim the TV, "
                            "open Netflix"],
}


# Short commands Whisper tends to mishear ("swap brand", "DeskV"): snapped to the real phrase when close enough
EXTRA = ["desk view", "close desk view", "enlarge desk view", "enlarge blueprint", "shrink", "shrink it", "swap brain",
         "online mode", "offline mode", "holo mode", "exit holo mode", "blueprint this", "pull it apart",
         "put it back together", "room scan", "gesture control", "gestures off", "hologram workshop",
         "close the workshop", "morning radio", "what am i holding", "where was i", "reopen them", "type it",
         "finish this", "stop listening", "jarvis split", "jarvis merge", "close spending report",
         "pull up my spending report", "what can you do", "inventory mode", "i'm done", "count my squats"]


def _plain(t):
    import re
    t = re.sub(r"^(hey |ok |okay )?jarvis[,.!]?\s*", "", t.lower().strip())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]", " ", t)).strip()


def snap(text, exact=False):
    """A short thing he said that's very close to a known command -> that command (else None). exact: an exact
    match counts too."""
    import difflib
    t = _plain(text)
    if not t or len(t.split()) > 6:
        return None
    phrases = {_plain(p.lstrip("*").split("(")[0]) for v in COMMANDS.values() for p in v if p.startswith("*")}
    phrases |= set(EXTRA)
    if t in phrases:
        return t if exact else None  # already exactly right
    best, score = None, 0.0
    squash = t.replace(" ", "")
    for p in phrases:
        r = difflib.SequenceMatcher(None, t, p).ratio()
        if " " not in t and len(squash) >= 5 and len(p.split()) <= 2 and p.replace(" ", "").startswith(squash):
            r = max(r, 0.9)  # cut off: "DeskV" for "desk view"
        if r > score:
            best, score = p, r
    return best if score >= 0.88 else None


def show_commands(search=None):
    """Show everything Jarvis can do as a searchable panel on the HUD (optionally pre-filtered)."""
    groups = {k: v for k, v in COMMANDS.items() if k != "Trading" or features.feature("trading")}
    try:  # add-ons in custom/ can add their own: COMMANDS = {"Group": ["phrase", ...]}
        import custom_loader
        for m in custom_loader.modules:
            for k, v in (getattr(m, "COMMANDS", None) or {}).items():
                groups[k] = groups.get(k, []) + list(v)
    except Exception:
        pass
    try:
        features._panel({"type": "panel", "kind": "commands", "title": "What I can do", "stay": True,
                         "groups": [{"name": k, "items": v} for k, v in groups.items()], "search": search or ""})
    except OSError:
        pass
    return {"shown": True, "groups": list(groups),
            "note": "The panel lists example commands by topic; * ones are instant. Just say 'it's on your HUD'."}


FUNCS = {"show_commands": show_commands}
TOOLS = [{"name": "show_commands", "description": "Show everything you can do as a panel of example commands, when "
          "he asks what you can do / for help / for your commands (search: a topic to filter by, e.g. 'tv').",
          "input_schema": {"type": "object", "properties": {"search": {"type": "string"}}}}]


def selftest():
    assert all(isinstance(v, list) and v for v in COMMANDS.values())
    assert show_commands()["groups"][0] == "Talking to Jarvis"
    assert snap("swap brand.") == "swap brain" and snap("Hey Jarvis, DeskV") == "desk view"
    assert snap("what's the weather like in Sydney today") is None and snap("Hello,") is None
    assert snap("desk view") is None and snap("Shrink.") is None
    print("commands self-test passed")


if __name__ == "__main__":
    selftest()
