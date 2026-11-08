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


def research_object(name, kind=""):
    """Research an object (its exact name, brand and model if known) before drawing it. Returns a dossier."""
    import hud
    import web
    name = (name or "").strip()[:80]
    if not name:
        return {"error": "Give the object's name (brand and model if you can read them)."}
    t0 = time.time()
    _progress(name, "Identified: " + name)
    queries = {"teardown": f"{name} teardown", "exploded": f"{name} exploded view parts diagram",
               "size": f"{name} dimensions mm specifications", "how": f"how does a {kind or name} work"}
    with cf.ThreadPoolExecutor(8) as ex:
        fx = ex.submit(ifixit, name)
        fs = {k: ex.submit(web.web_search, q, 5) for k, q in queries.items()}
        fimg = ex.submit(hud.bing_images, f"{name} exploded view")
        _progress(name, "Searching teardowns, exploded views, specifications and how it works")
        found = {k: (f.result().get("results") or []) if not f.exception() else [] for k, f in fs.items()}
        guides = fx.result() if not fx.exception() else []
        if guides:
            n_parts = len(guides[0]["parts"])
            _progress(name, f"iFixit: {guides[0]['title']} ({len(guides[0]['steps'])} steps"
                            + (f", {n_parts} parts)" if n_parts else ")"), sources=[{"title": g["title"], "url": g["url"]} for g in guides])
        # read the best pages: one each for the teardown, the size and how it works (skipping videos)
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
        imgs = fimg.result() if not fimg.exception() else []
    dims = []
    for k, u, _ in pick:
        if k in ("size", "teardown"):
            dims += dimensions(texts.get(u, ""))
    how = next((texts[u][:1500] for k, u, _ in pick if k == "how" and texts.get(u)), "")
    images = [g for guide in guides for g in guide["images"]][:4]
    images += [i["src"] if isinstance(i, dict) else i for i in (imgs or [])][:8 - len(images)]
    sources = [{"title": g["title"], "url": g["url"]} for g in guides] + [{"title": t, "url": u} for _, u, t in pick]
    _progress(name, f"Research done in {time.time() - t0:.0f} s: {len(sources)} sources. Building the model",
              sources=sources, images=images, done=True)
    return {"name": name, "ifixit": [{k: g[k] for k in ("title", "url", "parts", "tools", "steps")} for g in guides],
            "dimensions": dims[:12], "how_it_works": how,
            "snippets": [{"title": r.get("title", ""), "snippet": r.get("snippet", "")} for k in ("exploded", "teardown")
                         for r in found[k][:3]],
            "sources": sources,
            "note": ("Use this to draw it: the iFixit parts and steps give the real components in the order they come "
                     "out (front to back); the dimension sentences give real sizes (put them in mm). Pass sources on.")}


FUNCS = {"research_object": research_object}
TOOLS = [{"name": "research_object", "description": (
    "Research an object before drawing its blueprint: iFixit teardowns (real parts in order, tools, steps), web pages "
    "on its teardown, exploded view, dimensions and how it works, and reference pictures, all at once (the HUD shows "
    "the research as it happens). name: what it is, as exactly as you can (brand and model if visible, else e.g. "
    "'automatic wristwatch'). kind: the general kind of thing ('mechanical watch'), for how-it-works searches."),
    "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S, "kind": S}}}]


def selftest():
    t = "The watch measures 42 mm across and 12.5mm thick. Battery: CR2032, 20 mm x 3.2 mm. Nothing here."
    d = dimensions(t)
    assert any("42 mm" in x for x in d) and any("20 mm" in x for x in d) and len(d) == 2, d
    assert "error" in research_object("")
    print("research self-test passed")


if __name__ == "__main__":
    selftest()
