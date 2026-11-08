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


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")  # image sites answer a normal browser, not a script


def _fetch(url, referer=None, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **({"Referer": referer} if referer else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get_content_type()


def _get(url):
    return json.loads(_fetch(url)[0])


def bing_images(query):
    """Image links from a Bing image search (the whole web), best first."""
    html = _fetch("https://www.bing.com/images/search?form=HDRSC2&first=1&q=" + urllib.parse.quote(query))[0]
    import html as H
    out = []
    for blob in re.findall(r'\bm="(\{[^"]*\})"', html.decode("utf-8", "replace")):  # each result's details
        try:
            d = json.loads(H.unescape(blob))
        except ValueError:
            continue
        if str(d.get("murl", "")).startswith("http"):
            out.append({"src": d["murl"], "page": d.get("purl", ""), "title": H.unescape(d.get("t", ""))})
    return out


def wiki_images(query):
    """Fallback: the lead photo of matching Wikipedia articles, then Wikimedia Commons."""
    q, out = urllib.parse.quote(query), []
    d = _get("https://en.wikipedia.org/w/api.php?action=query&format=json&generator=search&gsrlimit=5"
             f"&gsrsearch={q}&prop=pageimages&piprop=thumbnail&pithumbsize=1000&pilicense=any")
    for p in sorted((d.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99)):
        if p.get("thumbnail", {}).get("source"):
            out.append({"src": p["thumbnail"]["source"], "page": "Wikipedia: " + p["title"]})
    d = _get("https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrnamespace=6"
             f"&gsrlimit=5&gsrsearch={q}%20filetype:bitmap&prop=imageinfo&iiprop=url|mime&iiurlwidth=1000")
    for p in sorted((d.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99)):
        info = (p.get("imageinfo") or [{}])[0]
        if info.get("mime") in ("image/jpeg", "image/png", "image/webp"):
            out.append({"src": info.get("thumburl") or info["url"], "page": "Wikimedia Commons"})
    return out


def find_images(query):
    for search in (bing_images, wiki_images):
        try:
            found = search(query)
        except Exception:
            continue
        if found:
            return found
    return []


IMAGES = "images"  # downloaded pictures, served to the HUD from Jarvis itself (works on the phone too)
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def download(src, referer=None):
    """Save a picture into Jarvis's images folder. Returns its file name, or None if it isn't a usable image."""
    import hashlib
    try:
        data, kind = _fetch(src, referer, timeout=10)
    except Exception:
        return None
    if kind not in EXT or len(data) < 3000 or len(data) > 15_000_000:
        return None
    d = features.HERE / IMAGES
    d.mkdir(exist_ok=True)
    name = hashlib.sha1(src.encode()).hexdigest()[:16] + EXT[kind]
    (d / name).write_bytes(data)
    for old in sorted(d.iterdir(), key=lambda f: f.stat().st_mtime)[:-150]:  # keep the last 150 (a blueprint has a picture per part)
        old.unlink(missing_ok=True)
    return name


def show_image(query=None, url=None, title=None, count=1, skip=0):
    """Show pictures on the HUD: searched for anywhere on the web, or from a direct image link."""
    if url:
        if not re.match(r"https?://", url):
            return {"error": "url must start with http(s)://"}
        candidates = [{"src": url, "page": urllib.parse.urlsplit(url).netloc}]
    elif query:
        candidates = find_images(query)[int(skip or 0):]
    else:
        return {"error": "Give a query or a url"}
    shown = []
    for c in candidates[:12]:
        name = download(c["src"], c.get("page") if str(c.get("page", "")).startswith("http") else None)
        if name:
            shown.append({"src": f"/api/img/{name}", "from": urllib.parse.urlsplit(c["page"]).netloc or c["page"]
                          if str(c.get("page", "")).startswith("http") else c.get("page", "")})
        if len(shown) >= max(1, min(int(count or 1), 4)):
            break
    if not shown:
        return {"error": f"Couldn't get a picture of '{query or url}'. Try other words."}
    PUSH({"type": "panel", "kind": "image", "title": title or query or "Image", "srcs": [x["src"] for x in shown],
          "src": shown[0]["src"], "note": " · ".join(dict.fromkeys(x["from"] for x in shown if x["from"]))})
    return {"shown": len(shown), "sources": [x["from"] for x in shown],
            "next": "For different ones, call again with skip set higher."}


BACKGROUNDS = {"default": "the glowing default", "dark": "plain dark", "grid": "a holographic grid",
               "stars": "a moving starfield", "nebula": "a deep-space nebula", "hex": "a hexagon mesh",
               "rain": "falling code"}
BG_ALIASES = {"normal": "default", "original": "default", "reset": "default", "black": "dark", "plain": "dark",
              "space": "stars", "starfield": "stars", "galaxy": "nebula", "hexagon": "hex", "hexagons": "hex",
              "matrix": "rain", "code": "rain"}


def hud_background(style=None, query=None, url=None, photo=False, dim=None):
    """Change the HUD's background: a built-in style, a picture found on the web (query), a picture link (url),
    or the last photo he sent (photo=True). dim 0-0.9 darkens a picture so the HUD stays readable."""
    s = features.settings()
    bg = {"dim": max(0.0, min(0.9, float(dim))) if dim is not None else s.get("background", {}).get("dim", 0.55)}
    if dim is not None and not (style or query or url or photo) and s.get("background", {}).get("kind") == "image":
        bg = {**s["background"], "dim": bg["dim"]}  # just darker or lighter: keep the picture
        features._save("settings.json", {**s, "background": bg})
        PUSH({"type": "background", **bg})
        return {"background": "picture", "dim": bg["dim"]}
    if query or url or photo:
        src_file = None
        if photo:
            ups = sorted((features.HERE / "uploads").glob("*.*"), key=lambda f: f.stat().st_mtime)
            if not ups:
                return {"error": "He hasn't sent a photo yet."}
            src_file = ups[-1]
        else:
            cands = [{"src": url, "page": url}] if url else find_images(query + " wallpaper")
            for c in cands[:8]:
                name = download(c["src"], c.get("page") if str(c.get("page", "")).startswith("http") else None)
                if name:
                    src_file = features.HERE / IMAGES / name
                    break
            if not src_file:
                return {"error": f"Couldn't get a picture for '{query or url}'."}
        d = features.HERE / "custom" / "backgrounds"  # kept through updates
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("background.*"):
            old.unlink()
        dest = d / ("background" + src_file.suffix.lower())
        dest.write_bytes(src_file.read_bytes())
        bg.update(kind="image", file=dest.name, v=int(dest.stat().st_mtime))
    else:
        key = BG_ALIASES.get((style or "default").lower().strip(), (style or "default").lower().strip())
        if key not in BACKGROUNDS:
            return {"error": f"Unknown background '{style}'", "styles": list(BACKGROUNDS)}
        bg.update(kind="style", style=key)
    features._save("settings.json", {**features.settings(), "background": bg})
    PUSH({"type": "background", **bg})
    return {"background": bg.get("style") or "picture", "dim": bg["dim"]}


PANELS = {"time": "time", "clock": "time", "local time": "time", "systems": "systems", "system": "systems",
          "stats": "systems", "pc stats": "systems", "protocols": "protocols", "mt5": "mt5", "mt5 journal": "mt5",
          "trading journal": "mt5", "journal": "journal", "voice journal": "journal", "report": "report",
          "journal report": "report", "voice journal report": "report", "activity": "activity", "status": "activity", "status panel": "activity", "all": "all", "everything": "all"}


def hud_panel(panel, show=True):
    """Close or bring back one of the HUD's side panels (or all of them)."""
    name = panel.lower().replace(" panel", "").strip()
    pid = PANELS.get(name) or re.sub(r"[^a-z0-9]+", "-", name).strip("-")  # custom panels go by their own id/title
    if not pid:
        return {"error": "Which panel?", "panels": ["time", "systems", "protocols", "mt5 journal", "voice journal",
                                                    "journal report", "all", "or any custom panel by its title"]}
    PUSH({"type": "hud_panel", "panel": pid, "show": bool(show)})
    return {"panel": pid, "shown": bool(show)}


FUNCS = {"hud_background": hud_background, "hud_colour": hud_colour, "show_image": show_image, "hud_panel": hud_panel}
TOOLS = [
    {"name": "hud_colour", "description": "Change the HUD's colour when he asks: blue (default), red, gold, yellow, "
     "orange, green, teal, purple, pink, white, silver, or any hex code. It stays until changed.",
     "input_schema": {"type": "object", "required": ["colour"], "properties": {"colour": {"type": "string"}}}},
    {"name": "hud_background", "description": "Change the HUD's background when he asks: style = default, dark, grid, "
     "stars (moving starfield), nebula, hex or rain (falling code); or a picture: query = what to find on the web "
     "('a city at night', 'Halo ring'), url = a picture link, or photo = true for the last photo he sent. dim 0-0.9 "
     "darkens a picture (default 0.55). It stays until changed.",
     "input_schema": {"type": "object", "properties": {"style": {"type": "string", "enum": list(BACKGROUNDS)},
                      "query": {"type": "string"}, "url": {"type": "string"}, "photo": {"type": "boolean"},
                      "dim": {"type": "number"}}}},
    {"name": "hud_panel", "description": "Close or reopen one of the HUD's side panels: time, systems, protocols, "
     "mt5 journal, voice journal, journal report, any custom panel by its title, or all. show false to close.",
     "input_schema": {"type": "object", "required": ["panel"], "properties": {"panel": {"type": "string"},
                                                                               "show": {"type": "boolean"}}}},
    {"name": "show_image", "description": "Show pictures on his HUD (and phone) as a holographic panel. ALWAYS use "
     "this for 'show me a picture/photo of...': never open his browser for it. query = what to find (searched across "
     "the whole web), count = 1-4 pictures side by side, skip = how many results to pass over ('show me another one'); "
     "or url = a direct image link. Keep the spoken reply short.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "url": {"type": "string"},
                                                        "title": {"type": "string"}, "count": {"type": "integer"},
                                                        "skip": {"type": "integer"}}}},
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
        assert hud_panel("Task Manager")["panel"] == "task-manager" and hud_panel("activity")["panel"] == "activity"
        assert hud_background("space")["background"] == "stars" and sent[-1]["style"] == "stars"
        assert features.settings()["background"]["style"] == "stars" and "error" in hud_background("lava lamp")
        assert "error" in hud_background(photo=True)  # no photos yet
        (features.HERE / "uploads").mkdir()
        (features.HERE / "uploads" / "a1.jpg").write_bytes(b"\xff\xd8pic")
        r = hud_background(photo=True, dim=0.3)
        assert r == {"background": "picture", "dim": 0.3} and sent[-1]["file"] == "background.jpg"
        assert (features.HERE / "custom" / "backgrounds" / "background.jpg").read_bytes() == b"\xff\xd8pic"
        assert hud_background(dim=0.7) == {"background": "picture", "dim": 0.7} and sent[-1]["file"] == "background.jpg"
        jpg = b"\xff\xd8" + b"x" * 5000
        pages = {"bing": ('<a m="{&quot;purl&quot;:&quot;https://example.com/a&quot;,&quot;murl&quot;:'
                          '&quot;https://example.com/a.jpg&quot;}" ></a><a m="{&quot;murl&quot;:&quot;https://x/tiny.png'
                          '&quot;,&quot;purl&quot;:&quot;https://x&quot;}">').encode()}
        def fake(url, referer=None, timeout=8):
            if "bing.com" in url:
                return pages["bing"], "text/html"
            if url.endswith("tiny.png"):
                return b"\x89PNG", "image/png"  # too small to be a real picture: skipped
            return jpg, "image/jpeg"
        global _fetch
        real_fetch, _fetch = _fetch, fake
        try:
            assert [x["src"] for x in bing_images("x")] == ["https://example.com/a.jpg", "https://x/tiny.png"]
            r = show_image("x", count=2)
            assert r["shown"] == 1 and r["sources"] == ["example.com"], r
            ev = sent[-1]
            assert ev["kind"] == "image" and ev["src"].startswith("/api/img/") and ev["src"].endswith(".jpg")
            assert (features.HERE / "images" / ev["src"].split("/")[-1]).read_bytes() == jpg
            pages["bing"] = b"<html>nothing</html>"
            _get = lambda url: ({"query": {"pages": {"1": {"index": 1, "title": "Everest",
                                                           "thumbnail": {"source": "https://up/e.jpg"}}}}}
                                if "wikipedia" in url else {})
            assert show_image("everest")["sources"] == ["Wikipedia: Everest"]  # Bing empty: Wikipedia instead
            _get = lambda url: {}
            assert "error" in show_image("nothing") and "error" in show_image(url="file:///c:/x.png")
        finally:
            _fetch = real_fetch
    finally:
        _get, features.HERE = real_get, real_here
    print("hud self-test passed")


if __name__ == "__main__":
    selftest()
