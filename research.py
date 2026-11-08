"""Research an object before drawing it (blueprint mode): Jarvis identifies what's on camera, then this gathers what's
known about it, all at once: iFixit teardowns (the real parts in order, tools, step photos), web pages on its
teardown, exploded view, dimensions and how it works (read, with the measurements pulled out), and reference
pictures. The HUD shows the research as it happens; the brain then draws the blueprint from the dossier.
"""
import concurrent.futures as cf
import json
import re
import time
import urllib.parse
import urllib.request

import features

IFIXIT = "https://www.ifixit.com/api/2.0"
S = {"type": "string"}
DIM = re.compile(r"[^.\n]{0,90}\b\d+(?:\.\d+)?\s?(?:mm|millimet(?:er|re)s?|cm|centimet(?:er|re)s?|inch(?:es)?|in\b|\")"
                 r"[^.\n]{0,90}", re.I)


def _json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0 (personal assistant)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(3_000_000))


def _progress(name, stage, **more):
    try:
        features._panel({"type": "research", "title": name[:60], "stage": stage, **more})
    except OSError:
        pass


def ifixit(name, limit=2):
    """iFixit teardowns / disassembly guides for it: [{title, url, parts, tools, steps, images}]."""
    out = []
    for q in (f"{name} teardown", name):
        try:
            res = _json(f"{IFIXIT}/suggest/{urllib.parse.quote(q)}?doctypes=guide")
        except Exception:
            continue
        guides = [g for g in (res.get("results") or []) if isinstance(g, dict) and g.get("guideid")]
        guides.sort(key=lambda g: not re.search(r"teardown|disassembl|opening|replacement", g.get("title", ""), re.I))
        for g in guides:
            if len(out) >= limit or any(o["id"] == g["guideid"] for o in out):
                continue
            try:
                d = _json(f"{IFIXIT}/guides/{g['guideid']}")
            except Exception:
                continue
            steps, imgs = [], []
            for st in (d.get("steps") or [])[:25]:
                text = " ".join((ln.get("text_raw") or ln.get("text") or "") for ln in (st.get("lines") or []))
                text = re.sub(r"\[[^\]]*\]", "", text).strip()
                if text:
                    steps.append(((st.get("title") or "").strip() + ": " + text)[:260].lstrip(": "))
                for m in ((st.get("media") or {}).get("data") or [])[:1]:
                    if isinstance(m, dict) and m.get("standard") and len(imgs) < 6:
                        imgs.append(m["standard"])
            out.append({"id": g["guideid"], "title": d.get("title") or g.get("title", ""),
                        "url": d.get("url") or g.get("url", ""),
                        "parts": [p.get("text", "") for p in (d.get("parts") or []) if isinstance(p, dict)][:20],
                        "tools": [p.get("text", "") for p in (d.get("tools") or []) if isinstance(p, dict)][:12],
                        "steps": steps[:18], "images": imgs})
        if out:
            break
    return out


def dimensions(text, limit=8):
    """Sentences in a page that give measurements."""
    seen, out = set(), []
    for m in DIM.finditer(text):
        s = " ".join(m.group(0).split())
        if len(s) > 20 and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
        if len(out) >= limit:
            break
    return out


STOP = {"the", "and", "with", "for", "watch", "steel", "two", "tone", "mm", "edition", "new", "model", "series", "black",
        "white", "silver", "gold", "blue", "of", "a", "an", "in"}


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in STOP}


def relevant(img, must, also=()):
    """Keep a picture only if its title or page mentions the thing (image search is too literal: 'quartz' finds
    crystals, a film tie-in finds film stills)."""
    blob = (img.get("title", "") + " " + img.get("page", "")).lower() if isinstance(img, dict) else ""
    if re.search(r"minecraft|redstone|lego|roblox|movie|film|scene|cosplay|wallpaper", blob):
        return False
    return any(w in blob for w in must) and (not also or any(w in blob for w in also))


def research_object(name, kind="", similar=""):
    """Research an object before drawing it. name: exactly what it is. kind: its category ('quartz chronograph
    watch'). similar: a well-documented equivalent with the same insides (e.g. the movement it uses, 'Miyota OS20
    quartz chronograph movement'), used for the teardown when this exact one has none. Returns a dossier."""
    import hud
    import web
    name, kind, similar = (name or "").strip()[:80], (kind or "").strip()[:60], (similar or "").strip()[:80]
    if not name:
        return {"error": "Give the object's name (brand and model if you can read them)."}
    t0 = time.time()
    inside = similar or kind or name  # what's inside is researched on the best-documented equivalent
    _progress(name, "Identified: " + name + (f" (inside: same as {inside})" if inside != name else ""))
    queries = {"teardown": f"{inside} teardown", "exploded": f"{inside} exploded view parts",
               "size": f"{name} dimensions mm specifications", "how": f"how does a {kind or inside} work"}
    with cf.ThreadPoolExecutor(10) as ex:
        fx = ex.submit(lambda: ifixit(name) or (ifixit(similar) if similar else []) or (ifixit(kind) if kind else []))
        fs = {k: ex.submit(web.web_search, q, 5) for k, q in queries.items()}
        fimg = ex.submit(hud.bing_images, name)
        fdia = ex.submit(hud.bing_images, f"{inside} exploded diagram parts")
        _progress(name, f"Searching: {name} specifications, and teardowns of {inside}")
        found = {k: (f.result().get("results") or []) if not f.exception() else [] for k, f in fs.items()}
        guides = fx.result() if not fx.exception() else []
        if guides:
            n_parts = len(guides[0]["parts"])
            _progress(name, f"iFixit: {guides[0]['title']} ({len(guides[0]['steps'])} steps"
                            + (f", {n_parts} parts)" if n_parts else ")"),
                      sources=[{"title": g["title"], "url": g["url"]} for g in guides])
        pick = []
        for k in ("teardown", "size", "how", "exploded"):
            for r in found[k]:
                u = r.get("url", "")
                if u and "youtube." not in u and "ifixit.com" not in u and u not in [p[1] for p in pick]:
                    pick.append((k, u, r.get("title", "")))
                    break
        _progress(name, f"Reading {len(pick)} pages", sources=[{"title": t, "url": u} for _, u, t in pick])
        pages = {u: ex.submit(web.read_page, u, 12000) for _, u, _ in pick}
        texts = {u: (f.result() or {}).get("text", "") if not f.exception() else "" for u, f in pages.items()}
        photos = [i for i in (fimg.result() if not fimg.exception() else []) if relevant(i, _words(name))][:3]
        diagrams = [i for i in (fdia.result() if not fdia.exception() else [])
                    if relevant(i, _words(inside) | _words(kind), ("exploded", "diagram", "parts", "movement",
                                                                   "teardown", "inside", "components"))][:3]
    dims = []
    for k, u, _ in pick:
        if k in ("size", "teardown"):
            dims += dimensions(texts.get(u, ""))
    how = next((texts[u][:1500] for k, u, _ in pick if k == "how" and texts.get(u)), "")
    images = [g for guide in guides for g in guide["images"]][:3] + [i["src"] for i in photos + diagrams]
    sources = [{"title": g["title"], "url": g["url"]} for g in guides] + [{"title": t, "url": u} for _, u, t in pick]
    _progress(name, f"Research done in {time.time() - t0:.0f} s: {len(sources)} sources", sources=sources,
              images=images[:6])
    return {"name": name, "inside_based_on": inside,
            "ifixit": [{k: g[k] for k in ("title", "url", "parts", "tools", "steps")} for g in guides],
            "dimensions": dims[:12], "how_it_works": how,
            "snippets": [{"title": r.get("title", ""), "snippet": r.get("snippet", "")} for k in ("exploded", "teardown")
                         for r in found[k][:3]],
            "sources": sources,
            "note": ("Next: list every component inside (from the teardown steps, front to back) and call research_parts "
                     "with them, to get each one's real size and look before drawing.")}


def research_parts(context, parts):
    """Each component's real size and what it looks like, researched at once (one search per part), so the 3D
    replica is right. context: what they're inside ('quartz chronograph watch movement'). parts: their names."""
    import web
    parts = [str(p).strip()[:60] for p in (parts or []) if str(p).strip()][:30]
    if not parts:
        return {"error": "List the parts."}
    title = (context or "")[:60]
    _progress(title, f"Researching {len(parts)} parts one by one")
    out = {}

    def one(p):
        res = web.web_search(f"{context} {p} size mm diameter thickness", 4).get("results") or []
        text = " ".join(r.get("title", "") + ". " + r.get("snippet", "") for r in res)
        return {"dimensions": dimensions(text, 4), "looks": [r.get("snippet", "")[:200] for r in res[:2]],
                "source": res[0]["url"] if res else ""}
    with cf.ThreadPoolExecutor(8) as ex:
        futs = {p: ex.submit(one, p) for p in parts}
        for i, (p, f) in enumerate(futs.items(), 1):
            out[p] = f.result() if not f.exception() else {"dimensions": [], "looks": []}
            _progress(title, f"Part {i}/{len(parts)}: {p}" + (f": {out[p]['dimensions'][0][:60]}" if out[p]["dimensions"] else ""))
    _progress(title, "Parts researched. Building the 3D replica", done=True)
    return {"parts": out, "note": ("Use these real sizes (mm) and descriptions for each part's mm, shape and detail in "
                                   "the blueprint call (a custom shape built from pieces for anything the shapes don't match, "
                                   "with its fine details). Where nothing was found, use typical sizes for that part.")}


FUNCS = {"research_object": research_object, "research_parts": research_parts}
TOOLS = [{"name": "research_object", "description": (
    "Research an object before drawing its blueprint: iFixit teardowns (real parts in order, tools, steps), web pages "
    "on its teardown, exploded view, dimensions and how it works, and reference pictures, all at once (the HUD shows "
    "the research as it happens). name: what it is, as exactly as you can (brand and model if visible, else e.g. "
    "'automatic wristwatch'). kind: its category ('quartz chronograph watch'). similar: if this exact one is a branded "
    "version of something common (most watches, phones and gadgets share standard insides), name the well-documented "
    "equivalent to research the insides on, e.g. the movement it uses ('Miyota OS20 quartz chronograph movement') or "
    "the same-generation model."),
    "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S, "kind": S, "similar": S}}},
    {"name": "research_parts", "description": (
        "After research_object: research every component inside at once (real sizes in mm, what each looks like), so "
        "the 3D replica is accurate. context: what they're inside (e.g. 'quartz chronograph watch'). parts: the "
        "component names, front to back."),
     "input_schema": {"type": "object", "required": ["context", "parts"], "properties": {
         "context": S, "parts": {"type": "array", "items": S}}}}]


def selftest():
    t = "The watch measures 42 mm across and 12.5mm thick. Battery: CR2032, 20 mm x 3.2 mm. Nothing here."
    d = dimensions(t)
    assert any("42 mm" in x for x in d) and any("20 mm" in x for x in d) and len(d) == 2, d
    assert "error" in research_object("") and "error" in research_parts("x", [])
    assert relevant({"title": "Timex Q chronograph review", "page": "x"}, {"timex"})
    assert not relevant({"title": "Quartz crystal cluster", "page": "rocks.com"}, {"chronograph", "quartz"}, ("diagram",))
    assert not relevant({"title": "Harry Potter scene", "page": "film.com"}, {"harry", "potter"})
    print("research self-test passed")


if __name__ == "__main__":
    selftest()
