"""The HUD itself: its colour, and pictures from the web shown as holographic panels.

Pictures come from Wikipedia (the main photo of the best-matching article), falling back to Wikimedia
Commons, so no API key is needed and the images are free to show.
"""
import json
import re
import urllib.parse
import urllib.request

import features

COLOURS = {"blue": "#5fe3ff", "cyan": "#5fe3ff", "default": "#5fe3ff", "red": "#ff4d5e", "iron man": "#ff4d5e",
           "gold": "#ffc845", "yellow": "#ffe14d", "orange": "#ff9a3c", "green": "#4dff9a", "purple": "#b98cff",
           "violet": "#b98cff", "pink": "#ff6bd6", "white": "#e8f4ff", "silver": "#c8d6e0", "teal": "#3dffe0"}
PUSH = features._panel  # sends an event to every open HUD (PC and phone) through the running Jarvis


def hud_colour(colour):
    """Change the HUD's colour: a name (red, gold, green, purple...) or a hex code like #ff8800."""
    c = colour.strip().lower()
    hexc = COLOURS.get(c) or (c if re.fullmatch(r"#?[0-9a-f]{6}", c) else None)
    if not hexc:
        return {"error": f"Unknown colour '{colour}'", "colours": sorted(set(COLOURS) - {"default", "cyan"})}
    hexc = "#" + hexc.lstrip("#")
    features._save("settings.json", {**features.settings(), "theme": hexc})
    PUSH({"type": "theme", "color": hexc})
    return {"colour": hexc}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-assistant/1.0 (personal desktop assistant)"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


def find_image(query):
    """The best picture for a search: the lead photo of the best-matching Wikipedia article, else Commons."""
    q = urllib.parse.quote(query)
    d = _get("https://en.wikipedia.org/w/api.php?action=query&format=json&generator=search&gsrlimit=5"
             f"&gsrsearch={q}&prop=pageimages&piprop=thumbnail&pithumbsize=1000&pilicense=any")
    pages = sorted((d.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in pages:
        if p.get("thumbnail", {}).get("source", "").lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
            return {"src": p["thumbnail"]["source"], "credit": f"Wikipedia: {p['title']}"}
    d = _get("https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrnamespace=6"
             f"&gsrlimit=5&gsrsearch={q}%20filetype:bitmap&prop=imageinfo&iiprop=url|mime&iiurlwidth=1000")
    pages = sorted((d.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        if info.get("mime") in ("image/jpeg", "image/png", "image/webp"):
            return {"src": info.get("thumburl") or info["url"], "credit": "Wikimedia Commons"}
    return None


def show_image(query=None, url=None, title=None):
    """Show a picture on the HUD: searched for by name, or a direct image link."""
    if url:
        if not re.match(r"https?://", url):
            return {"error": "url must start with http(s)://"}
        img = {"src": url, "credit": urllib.parse.urlsplit(url).netloc}
    elif query:
        img = find_image(query)
        if not img:
            return {"error": f"Couldn't find a picture of '{query}'. Try other words."}
    else:
        return {"error": "Give a query or a url"}
    PUSH({"type": "panel", "kind": "image", "title": title or query or "Image", "src": img["src"],
          "note": img["credit"]})
    return {"shown": img}


FUNCS = {"hud_colour": hud_colour, "show_image": show_image}
TOOLS = [
    {"name": "hud_colour", "description": "Change the HUD's colour when he asks: blue (default), red, gold, yellow, "
     "orange, green, teal, purple, pink, white, silver, or any hex code. It stays until changed.",
     "input_schema": {"type": "object", "required": ["colour"], "properties": {"colour": {"type": "string"}}}},
    {"name": "show_image", "description": "Show a picture on his HUD (and phone) as a holographic panel: query = what "
     "to find ('Mercedes CLA45 AMG', 'Mount Everest'), searched on Wikipedia/Wikimedia; or url = a direct image "
     "link. Keep the spoken reply short.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "url": {"type": "string"},
                                                        "title": {"type": "string"}}}},
]


def selftest():
    import tempfile
    from pathlib import Path
    global PUSH, _get
    sent, real_get, real_here = [], _get, features.HERE
    PUSH, features.HERE = sent.append, Path(tempfile.mkdtemp())
    try:
        assert hud_colour("Red")["colour"] == "#ff4d5e" and sent[-1] == {"type": "theme", "color": "#ff4d5e"}
        assert features.settings()["theme"] == "#ff4d5e"
        assert hud_colour("FF8800")["colour"] == "#ff8800" and "error" in hud_colour("blurple")
        _get = lambda url: ({"query": {"pages": {"1": {"index": 1, "title": "Mercedes-AMG CLA",
                                                       "thumbnail": {"source": "https://up/x.jpg"}}}}}
                            if "wikipedia" in url else {})
        assert show_image("cla45")["shown"]["src"] == "https://up/x.jpg" and sent[-1]["kind"] == "image"
        _get = lambda url: ({} if "wikipedia" in url else {"query": {"pages": {"2": {"index": 1, "imageinfo": [
            {"mime": "image/jpeg", "url": "https://c/full.jpg", "thumburl": "https://c/t.jpg"}]}}}})
        assert show_image("rare thing")["shown"]["src"] == "https://c/t.jpg"
        _get = lambda url: {}
        assert "error" in show_image("nothing") and "error" in show_image(url="file:///c:/x.png")
    finally:
        _get, features.HERE = real_get, real_here
    print("hud self-test passed")


if __name__ == "__main__":
    selftest()
