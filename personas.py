"""Jarvis's voices and personalities: switch with "switch to FRIDAY", "casual mode", "back to Jarvis".

Each one has its own neural voice (edge-tts), name on the HUD and way of talking. The tools, memory and
everything else stay the same.
"""
import features

PERSONAS = {
    "jarvis": {"name": "J A R V I S", "voice": "en-GB-RyanNeural", "rate": "+6%", "style": ""},
    "friday": {"name": "F R I D A Y", "voice": "en-IE-EmilyNeural", "rate": "+8%", "style": (
        "For now you are FRIDAY instead of JARVIS: Tony Stark's later AI, with an Irish lilt. Warmer, quicker "
        "and more direct than JARVIS, with a cheeky streak; you call him 'boss' and get straight to the point. "
        "Still short, spoken replies.")},
    "edith": {"name": "E . D . I . T . H", "voice": "en-US-AriaNeural", "rate": "+4%", "style": (
        "For now you are EDITH instead of JARVIS: a crisp, tactical AI. Calm, precise and efficient, like mission "
        "control: facts first, then the recommendation. No small talk, no jokes unless he jokes first. Call him "
        "by name or not at all.")},
    "mate": {"name": "J A R V O", "voice": "en-AU-WilliamNeural", "rate": "+8%", "style": (
        "For now you are 'Jarvo', a laid-back Aussie mate rather than a butler: casual, friendly, a bit of banter "
        "and light Aussie slang ('no worries', 'reckon', 'mate'), never over the top. Call him by his first name "
        "or 'mate', never 'sir'. Still helpful, still honest, still short.")},
}
ALIASES = {"j.a.r.v.i.s": "jarvis", "normal": "jarvis", "butler": "jarvis", "f.r.i.d.a.y": "friday",
           "e.d.i.t.h": "edith", "tactical": "edith", "casual": "mate", "aussie": "mate", "jarvo": "mate"}


def current():
    key = features.settings().get("persona", "jarvis")
    return key if key in PERSONAS else "jarvis"


def get():
    return {"key": current(), **PERSONAS[current()]}


def set_persona(name):
    """Switch Jarvis's voice and personality: jarvis, friday, edith or mate (casual Aussie)."""
    key = name.lower().strip().replace(" mode", "")
    key = ALIASES.get(key, key)
    if key not in PERSONAS:
        return {"error": f"Unknown personality '{name}'", "choices": sorted(PERSONAS)}
    features._save("settings.json", {**features.settings(), "persona": key})
    try:
        features._panel({"type": "persona", **get()})
    except OSError:
        pass  # the HUD isn't open
    return {"now": key, "note": "Reply in the new voice and style from now on."}


FUNCS = {"set_persona": set_persona}
TOOLS = [{"name": "set_persona", "description": "Switch your voice and personality when he asks: jarvis (the "
          "default British butler), friday (Irish, warm and cheeky), edith (crisp and tactical) or mate (a casual "
          "Aussie mate). Your tools and memory stay the same.",
          "input_schema": {"type": "object", "required": ["name"], "properties": {
              "name": {"type": "string", "enum": sorted(PERSONAS)}}}}]


def selftest():
    import tempfile
    from pathlib import Path
    real, features.HERE = features.HERE, Path(tempfile.mkdtemp())
    sent, real_panel = [], features._panel
    features._panel = sent.append
    try:
        assert current() == "jarvis" and set_persona("FRIDAY mode")["now"] == "friday" and current() == "friday"
        assert sent[-1]["type"] == "persona" and sent[-1]["voice"] == "en-IE-EmilyNeural"
        assert set_persona("casual")["now"] == "mate" and "error" in set_persona("ultron")
    finally:
        features.HERE, features._panel = real, real_panel
    print("personas self-test passed")


if __name__ == "__main__":
    selftest()
