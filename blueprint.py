"""Blueprint mode: "Jarvis, blueprint this" (holding something up to the desk camera). The brain looks at the photo
and calls blueprint() with what the object is, where it is in the photo, its visible features, a size estimate and
what's typically inside it. The HUD draws it as a blueprint: an edge-traced sketch of the real photo with labelled
callouts; "pull it apart" flies the inside components out of the outline (no second AI call).
"""
import features

S, N = {"type": "string"}, {"type": "number"}
PT = {"type": "array", "items": N, "description": "[x, y], fractions 0 to 1"}
SHAPES = ("rect", "rounded", "circle", "cylinder", "board", "coil", "battery", "screw", "lens", "wire", "spring", "fan",
          # proper parts, built in detail in 3D (detail: teeth, spokes, subdials, count, holes)
          "gear", "ring", "gasket", "dial", "hands", "dome", "coin_cell", "quartz", "motor", "case", "rotor",
          "balance", "hairspring", "pusher", "crown", "display", "speaker", "links", "keypad", "chip", "magnet", "plate",
          "custom")  # custom: built from pieces, for any part the others don't match
PIECES = ("box", "rounded", "cylinder", "tube", "cone", "sphere", "torus", "wedge")
import re
PHOTO = re.compile(r"(?:uploads/)?([0-9a-f]{6,40}\.(?:png|jpe?g|webp))", re.I)


def _f(v, lo=0.0, hi=1.0, default=0.5):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _pt(p, default=(0.5, 0.5)):
    return [_f(p[0], default=default[0]), _f(p[1], default=default[1])] if isinstance(p, (list, tuple)) and len(p) >= 2 \
        else list(default)


SHELLS = ("box", "rounded", "outline", "disc", "cylinder", "sphere")


def _mm(v):
    """[w, h, d] in millimetres, or None."""
    if not isinstance(v, (list, tuple)) or len(v) < 2:
        return None
    out = [_f(x, 0, 5000, 0) for x in list(v)[:3]]
    return out if out[0] > 0 and out[1] > 0 else None


import json
import time
from pathlib import Path

STATE = Path(__file__).parent / "blueprint_state.json"  # the last blueprint, and which ones were sent back to fix
# (each tool call is its own process, so this lives in a file)


def _load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(st):
    try:
        STATE.write_text(json.dumps(st), encoding="utf-8")
    except OSError:
        pass


def remember_images(images):
    """research_parts found a real photo of each part: kept so blueprint() puts it on the matching part."""
    st = _load()
    _save({**st, "images": {**(st.get("images") or {}), **{k.lower(): v for k, v in images.items()}}})


def _image_for(name, images):
    n = name.lower()
    if n in images:
        return images[n]
    words = set(re.findall(r"[a-z0-9]{3,}", n))
    for k, v in images.items():  # one name's words all in the other ('main board' and 'main circuit board', not 'rear shell')
        kw = set(re.findall(r"[a-z0-9]{3,}", k))
        if kw and words and (kw <= words or words <= kw):
            return v
    return ""


def fit_check(mm, parts, wall=1.0):
    """1:1 check: every part (real mm) must fit inside the object (real mm, less its walls). Returns the problems."""
    if not mm:
        return ["the object's real size (mm) is missing: look it up"]
    room = [max(1.0, v - 2 * wall) for v in (mm + [mm[0] * 0.25])[:3]] if len(mm) < 3 else [max(1.0, v - 2 * wall) for v in mm]
    bad = []
    for p in parts:
        if not p["mm"]:
            bad.append(f"{p['name']}: no real size (mm)")
            continue
        pm = (p["mm"] + [0])[:3]
        shell = p["layer"] in (0.0, 1.0) and pm[0] >= mm[0] * 0.8  # the front/back covers are the outside itself
        lim = mm if shell else room
        over = [f"{'whd'[i]} {pm[i]:g} > {lim[i]:g}" for i in range(3) if pm[i] > lim[i] * 1.02]
        if over:
            bad.append(f"{p['name']} ({' x '.join(f'{v:g}' for v in pm)} mm) doesn't fit: " + ", ".join(over))
    return bad


def _vec(v, n=3, lo=-5000.0, hi=5000.0, default=0.0):
    v = list(v)[:n] if isinstance(v, (list, tuple)) else []
    return [_f(x, lo, hi, default) for x in v + [default] * (n - len(v))]


def _pieces(ps):
    """A custom part's pieces: [{type, at: [x, y, z] mm, size: [w, h, d] mm, rot: [x, y, z] degrees, hole: mm}]."""
    out = []
    for q in (ps or [])[:80]:
        if not isinstance(q, dict):
            continue
        size = _vec(q.get("size"), lo=0.01, default=1.0)
        out.append({"type": q.get("type") if q.get("type") in PIECES else "box", "at": _vec(q.get("at")), "size": size,
                    "rot": _vec(q.get("rot"), lo=-360, hi=360), **({"hole": _f(q["hole"], 0, 5000, 0)} if "hole" in q else {})})
    return out


def _photo(v):
    m = PHOTO.fullmatch(str(v or "").strip())
    return m.group(1) if m else ""


def blueprint(title, bbox, features_=None, inside=None, size="", material="", note="", shell="box", explode="radial",
              source="", mm=None, how=None, sources=None, tilt=0, photo="",
              back_photo="", back_bbox=None, back_tilt=0, **kw):
    """Draw the blueprint on the HUD (see the tool description for the fields)."""
    feats = kw.get("features", features_) or []
    box = [_f(v) for v in (list(bbox) + [0, 0, 1, 1])[:4]] if isinstance(bbox, (list, tuple)) else [0, 0, 1, 1]
    if box[2] - box[0] < .05 or box[3] - box[1] < .05:
        box = [0.1, 0.1, 0.9, 0.9]
    ev = {"type": "blueprint", "title": str(title)[:60], "bbox": box, "size": str(size)[:60],
          "material": str(material)[:80], "note": str(note)[:200], "shell": shell if shell in SHELLS else "box",
          "explode": "layers" if explode == "layers" else "radial", "tilt": _f(tilt, -45, 45, 0),
          **({"photo": _photo(photo)} if _photo(photo) else {}),
          **({"back_photo": _photo(back_photo), "back_bbox": [_f(v) for v in (list(back_bbox or []) + [0, 0, 1, 1])[:4]],
              "back_tilt": _f(back_tilt, -45, 45, 0)} if _photo(back_photo) else {}), "source": str(source)[:120], "mm": _mm(mm),
          "how": [str(h)[:200] for h in (how or [])[:8] if str(h).strip()],
          "sources": [{"title": str(s.get("title", ""))[:80], "url": str(s.get("url", ""))[:300]}
                      for s in (sources or [])[:8] if isinstance(s, dict) and str(s.get("url", "")).startswith("http")],
          "features": [{"name": str(f.get("name", ""))[:40], "at": _pt(f.get("at")), "note": str(f.get("note", ""))[:80]}
                       for f in feats[:10] if isinstance(f, dict) and f.get("name")],
          "inside": [{"name": str(p.get("name", ""))[:40], "note": str(p.get("note", ""))[:80],
                      "shape": p.get("shape") if p.get("shape") in SHAPES else "rect",
                      "at": _pt(p.get("at")), "size": _pt(p.get("size"), (0.25, 0.2)),
                      "layer": _f(p.get("layer"), default=0.5), "thick": _f(p.get("thick"), 0.02, 1, 0.3), "mm": _mm(p.get("mm")),
                      "detail": {k: int(_f(v, 0, 200, 0)) for k, v in (p.get("detail") or {}).items()
                                 if k in ("teeth", "spokes", "subdials", "count", "holes")} if isinstance(p.get("detail"), dict) else {},
                      **({"pieces": _pieces(p.get("pieces"))} if p.get("shape") == "custom" else {})}
                     for p in (inside or [])[:40] if isinstance(p, dict) and p.get("name")]}
    bad = fit_check(ev["mm"], ev["inside"]) if ev["inside"] else []
    st = _load()
    checked = {k: v for k, v in (st.get("checked") or {}).items() if time.time() - v < 900}
    if bad and ev["title"] not in checked:  # sent back once to fix the sizes, never twice (so it can't loop)
        checked[ev["title"]] = time.time()
        _save({**st, "checked": checked})
        return {"drawn": False, "not_to_scale": bad, "fix": (
            "The 3D model is 1:1 scale: every part must be its real size and fit inside the object (inside the walls, "
            f"about {', '.join(f'{v:g}' for v in (ev['mm'] or []))} mm overall). Look up the real sizes of the parts "
            "listed (research_parts), then call blueprint again with corrected mm for every part.")}
    ev["scale"] = "1:1" if not bad else "approx"
    images = st.get("images") or {}
    for p in ev["inside"]:  # each part's real photo, from the research
        img = _image_for(p["name"], images)
        if img and re.fullmatch(r"[0-9a-f]{16}\.(?:jpg|png|webp|gif)", img):
            p["image"] = img
    features._panel(ev)
    _save({**st, "checked": checked, "last": ev})
    return {"drawn": True, "features": len(ev["features"]), "inside": len(ev["inside"]),
            "pictures": sum(1 for p in ev["inside"] if p.get("image")),
            "next": ("It's on the HUD, but it isn't finished: now call blueprint_detail for EVERY part that isn't a plain "
                     "shape, one per call, building it from pieces with all its fine details (ports, buttons, ribs, screw "
                     "posts, clips, connectors, chips, vents), real mm throughout. Don't stop until each part is done. "
                     f"Parts: {', '.join(p['name'] for p in ev['inside'])}.")}


def blueprint_detail(part, pieces, mm=None, note=""):
    """Build one part of the blueprint on the HUD in fine detail, from pieces (adds to the last blueprint)."""
    st = _load()
    ev = st.get("last")
    if not ev:
        return {"error": "No blueprint yet: draw one with blueprint first."}
    names = [p["name"] for p in ev["inside"]]
    i = next((k for k, n in enumerate(names) if n.lower() == str(part).strip().lower()), None)
    if i is None:
        i = next((k for k, n in enumerate(names) if str(part).strip().lower() in n.lower()), None)
    if i is None:
        return {"error": f"No part called '{part}'. The parts are: {', '.join(names)}"}
    pc = _pieces(pieces)
    if not pc:
        return {"error": "Give the pieces it's built from."}
    p = ev["inside"][i]
    p.update(shape="custom", pieces=pc)
    if _mm(mm):
        p["mm"] = _mm(mm)
    if note:
        p["note"] = str(note)[:80]
    bad = fit_check(ev["mm"], [p]) if ev.get("mm") else []
    features._panel({**ev, "update": True})
    _save({**st, "last": ev})
    left = [n for n in names if not any(q["name"] == n and q.get("pieces") for q in ev["inside"])]
    return {"updated": p["name"], "pieces": len(pc), **({"too_big": bad} if bad else {}), "left": left,
            "next": f"Now blueprint_detail '{left[0]}'." if left else "Every part is detailed. Tell him it's done."}


FUNCS = {"blueprint": blueprint, "blueprint_detail": blueprint_detail}
PIECE_SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "type": {"type": "string", "enum": list(PIECES)}, "at": {"type": "array", "items": {"type": "number"}},
    "size": {"type": "array", "items": {"type": "number"}}, "rot": {"type": "array", "items": {"type": "number"}},
    "hole": {"type": "number"}}}}
TOOLS = [{"name": "blueprint", "description": (
    "Blueprint mode: after looking at a desk-camera photo of something he's holding, draw it as a blueprint on the "
    "HUD. Call research_object first and draw from its dossier, so the components, their order and their real sizes "
    "are right for THAT object. mm: the object's real size [width, height, depth] in millimetres as seen from the "
    "front (from the research; estimate if nothing says). Each inside part can have mm [w, h, d] too (real sizes "
    "make the 3D model to scale). The 3D model is 1:1: give every part its real mm, and every part must fit inside the object (a part bigger than the object is sent back to fix). how: 3 to 6 short steps on how it works. sources: [{title, url}] from the research. "
    "bbox: where the object is in the photo [x0, y0, x1, y1] as fractions (0 to 1) of the photo's width and "
    "height. tilt: how many degrees the object is turned in the photo (clockwise positive, so the HUD can straighten the photo it puts on the front of the 3D model). features: 3 to 8 visible parts, each {name, at: [x, y] fraction of the PHOTO, note}. size: a rough size "
    "estimate ('about 15 x 7 x 1 cm'). material: what it's made of. inside: 4 to 10 components typically inside this "
    "kind of object (an informed guess is fine), each {name, shape, at: [x, y] centre as a fraction of the OBJECT's box, size: [w, h] "
    "fraction of the object's box, layer: 0 front (the side facing the camera) to 1 back, thick: its thickness as a "
    "fraction of the object's depth, detail: {teeth, spokes, subdials, count, holes} where it applies (a gear's teeth "
    "and spokes, a dial's subdials, how many bracelet links or keys), note: what it does}. Up to 40 parts. Detail matters more than speed: take the time to get every part right. Pick shapes for what the part really is (a games console's front shell is 'rounded' or 'plate', not 'case'; 'case' is a watch case). Shapes: gear, ring, gasket, "
    "dial, hands, dome (a domed crystal or lens), coin_cell, quartz (crystal oscillator), motor (stepper/vibration), "
    "case (with lugs), rotor (half-disc weight), balance (wheel with spokes), hairspring, pusher, crown, display, "
    "speaker, links (bracelet/strap), keypad, chip, magnet, plate, board (circuit board), battery, screw, spring, coil, "
    "lens, wire, fan, rect, rounded, circle, cylinder: or custom: when no shape matches the real part closely, build it from pieces (custom, with pieces: [{type: box, rounded, cylinder, tube, cone, sphere, torus or wedge, at: [x, y, z] its centre in mm from the part's centre, size: [w, h, d] mm, rot: [x, y, z] degrees, hole: a tube's inner diameter in mm}], up to 80 pieces, including the fine details: ribs, screw bosses, clips, ports, buttons, vents, cables). Cylinders, tubes and cones run along h (up) unless rotated. Pick the one that matches the real part. shell: the object's overall 3D shape (outline: traced from the photo, best for anything that isn't a plain box, disc or tube; box, rounded, disc "
    "for flat round things like a watch or a puck, cylinder for cans and bottles, sphere). explode: 'layers' when "
    "the parts stack front to back (watch, phone, remote, laptop) so the 3D view pulls them apart along that stack, "
    "else 'radial'. source: where the parts list came from (a site name). photo: the photo it's drawn from (uploads/...), if he sent one. back_photo, back_bbox, back_tilt: a second photo of its back, if he sent one, so the back looks real too. Big things with hundreds of parts (a car, a PC, a drill): draw the main sections as the parts (engine, gearbox, seats...); when he asks to open one ('pull the engine apart'), research and draw a new blueprint of just that section, titled e.g. 'Engine · Mazda 3'. If nothing about it is online (homemade, rare), draw it from how that kind of object is usually built and say so in note. note: one line about it."),
    "input_schema": {"type": "object", "required": ["title", "bbox", "inside"], "properties": {
        "title": S, "bbox": {"type": "array", "items": N}, "tilt": N, "photo": S, "back_photo": S,
        "back_bbox": {"type": "array", "items": N}, "back_tilt": N, "size": S, "material": S, "note": S, "source": S,
        "mm": {"type": "array", "items": N}, "how": {"type": "array", "items": S},
        "sources": {"type": "array", "items": {"type": "object", "properties": {"title": S, "url": S}}},
        "shell": {"type": "string", "enum": list(SHELLS)}, "explode": {"type": "string", "enum": ["layers", "radial"]},
        "features": {"type": "array", "items": {"type": "object", "properties": {"name": S, "at": PT, "note": S}}},
        "inside": {"type": "array", "items": {"type": "object", "properties": {
            "name": S, "shape": {"type": "string", "enum": list(SHAPES)}, "at": PT, "size": PT, "note": S,
            "layer": N, "thick": N, "mm": {"type": "array", "items": N}, "detail": {"type": "object"},
            "pieces": {"type": "array", "items": {"type": "object", "properties": {
                "type": {"type": "string", "enum": list(PIECES)}, "at": {"type": "array", "items": N},
                "size": {"type": "array", "items": N}, "rot": {"type": "array", "items": N}, "hole": N}}}}}}}}},
    {"name": "blueprint_detail", "description": (
        "After blueprint: build ONE part in fine detail from pieces, so the 3D replica matches the real part (its ribs, "
        "screw bosses, clips, ports, buttons, vents, pins...). Call it once per part that isn't a plain shape; the HUD "
        "updates as you go. part: its name. pieces: [{type: box, rounded, cylinder, tube, cone, sphere, torus or wedge, "
        "at: [x, y, z] centre in mm from the part's centre (x right, y up, z towards the front), size: [w, h, d] mm, "
        "rot: [x, y, z] degrees, hole: a tube's inner diameter}], up to 80. Cylinders, tubes and cones run along y "
        "unless rotated. mm: its real size, if it needs correcting."),
     "input_schema": {"type": "object", "required": ["part", "pieces"], "properties": {
         "part": S, "pieces": PIECE_SCHEMA, "mm": {"type": "array", "items": N}, "note": S}}}]


def selftest():
    sent = []
    real = features._panel
    features._panel = sent.append
    global STATE
    real_state, STATE = STATE, Path("/tmp" if Path("/tmp").is_dir() else ".") / "bp_selftest.json"
    _save({"checked": {"TV remote": time.time(), "x": time.time()}})  # these have no real sizes: already sent back once
    try:
        r = blueprint("TV remote", [0.2, 0.1, 0.6, 0.95], features=[{"name": "Power", "at": [0.4, 0.15]}],
                      inside=[{"name": "Circuit board", "shape": "board", "at": [0.5, 0.5], "size": [0.8, 0.9]},
                              {"name": "Batteries", "shape": "battery", "at": [0.5, 0.85], "size": [2, "x"]},
                              {"name": "", "shape": "rect"}, {"name": "Thing", "shape": "teapot"}])
        ev = sent[0]
        assert r["inside"] == 3 and ev["inside"][1]["size"] == [1.0, 0.2] and ev["inside"][2]["shape"] == "rect"
        assert ev["features"][0]["at"] == [0.4, 0.15] and ev["bbox"] == [0.2, 0.1, 0.6, 0.95]
        assert ev["shell"] == "box" and ev["inside"][0]["layer"] == 0.5 and ev["inside"][0]["thick"] == 0.3
        assert ev["mm"] is None and _mm([42, 42, 12]) == [42.0, 42.0, 12.0] and _mm([0, 5]) is None
        blueprint("x", [0.5, 0.5, 0.51, 0.52], inside=[])
        assert sent[1]["bbox"] == [0.1, 0.1, 0.9, 0.9]
        big = blueprint("Game Boy", [0, 0, 1, 1], mm=[90, 148, 32],
                        inside=[{"name": "Board", "mm": [80, 110, 1.6], "layer": 0.5},
                                {"name": "Battery box", "mm": [60, 60, 40], "layer": 0.9}])
        assert big["drawn"] is False and "Battery box" in big["not_to_scale"][0] and len(big["not_to_scale"]) == 1
        again = blueprint("Game Boy", [0, 0, 1, 1], mm=[90, 148, 32], inside=[{"name": "Battery box", "mm": [60, 60, 40]}])
        assert again["drawn"] and sent[-1]["scale"] == "approx"  # sent back once only, then drawn
        blueprint("Gear", [0, 0, 1, 1], mm=[50, 50, 10], photo="uploads/abcdef12.png", back_photo="nope/../x.png",
                  inside=[{"name": "Hub", "shape": "custom", "mm": [20, 20, 8], "layer": 0.5,
                           "pieces": [{"type": "tube", "at": [0, 0], "size": [20, 8, 20], "hole": 6}, {"type": "teapot"}, 5]}])
        ev = sent[-1]
        assert ev["photo"] == "abcdef12.png" and "back_photo" not in ev
        pc = ev["inside"][0]["pieces"]
        assert len(pc) == 2 and pc[0]["at"] == [0.0, 0.0, 0.0] and pc[0]["hole"] == 6 and pc[1]["type"] == "box"
        r = blueprint_detail("hub", [{"type": "cylinder", "size": [10, 4, 10]}])
        assert r["updated"] == "Hub" and sent[-1]["update"] and sent[-1]["inside"][0]["pieces"][0]["type"] == "cylinder"
        assert "error" in blueprint_detail("wheel", [{"type": "box"}]) and "error" in blueprint_detail("hub", [])
        remember_images({"Main board": "0123456789abcdef.jpg"})
        blueprint("Toy", [0, 0, 1, 1], mm=[100, 100, 30], inside=[{"name": "Main circuit board", "mm": [80, 80, 2]},
                                                                   {"name": "Lid", "mm": [90, 90, 3]}])
        assert sent[-1]["inside"][0]["image"] == "0123456789abcdef.jpg" and "image" not in sent[-1]["inside"][1]
        assert _image_for("Front shell", {"rear shell": "a"}) == "" and _image_for("Speaker", {"speaker": "b"}) == "b"
        assert not fit_check([90, 148, 32], [{"name": "Front shell", "mm": [90, 148, 15], "layer": 0.0}])
    finally:
        features._panel = real
        STATE.unlink(missing_ok=True)
        STATE = real_state
    print("blueprint self-test passed")


if __name__ == "__main__":
    selftest()
