"""Blueprint mode: "Jarvis, blueprint this" (holding something up to the desk camera). The brain looks at the photo
and calls blueprint() with what the object is, where it is in the photo, its visible features, a size estimate and
what's typically inside it. The HUD draws it as a blueprint: an edge-traced sketch of the real photo with labelled
callouts; "pull it apart" flies the inside components out of the outline (no second AI call).
"""
import features

S, N = {"type": "string"}, {"type": "number"}
PT = {"type": "array", "items": N, "description": "[x, y], fractions 0 to 1"}
SHAPES = ("rect", "rounded", "circle", "cylinder", "board", "coil", "battery", "screw", "lens", "wire", "spring", "fan")


def _f(v, lo=0.0, hi=1.0, default=0.5):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _pt(p, default=(0.5, 0.5)):
    return [_f(p[0], default=default[0]), _f(p[1], default=default[1])] if isinstance(p, (list, tuple)) and len(p) >= 2 \
        else list(default)


SHELLS = ("box", "rounded", "disc", "cylinder", "sphere")


def blueprint(title, bbox, features_=None, inside=None, size="", material="", note="", shell="box", explode="radial",
              source="", **kw):
    """Draw the blueprint on the HUD (see the tool description for the fields)."""
    feats = kw.get("features", features_) or []
    box = [_f(v) for v in (list(bbox) + [0, 0, 1, 1])[:4]] if isinstance(bbox, (list, tuple)) else [0, 0, 1, 1]
    if box[2] - box[0] < .05 or box[3] - box[1] < .05:
        box = [0.1, 0.1, 0.9, 0.9]
    ev = {"type": "blueprint", "title": str(title)[:60], "bbox": box, "size": str(size)[:60],
          "material": str(material)[:80], "note": str(note)[:200], "shell": shell if shell in SHELLS else "box",
          "explode": "layers" if explode == "layers" else "radial", "source": str(source)[:120],
          "features": [{"name": str(f.get("name", ""))[:40], "at": _pt(f.get("at")), "note": str(f.get("note", ""))[:80]}
                       for f in feats[:10] if isinstance(f, dict) and f.get("name")],
          "inside": [{"name": str(p.get("name", ""))[:40], "note": str(p.get("note", ""))[:80],
                      "shape": p.get("shape") if p.get("shape") in SHAPES else "rect",
                      "at": _pt(p.get("at")), "size": _pt(p.get("size"), (0.25, 0.2)),
                      "layer": _f(p.get("layer"), default=0.5), "thick": _f(p.get("thick"), 0.02, 1, 0.3)}
                     for p in (inside or [])[:12] if isinstance(p, dict) and p.get("name")]}
    features._panel(ev)
    return {"drawn": True, "features": len(ev["features"]), "inside": len(ev["inside"]),
            "note": "It's on the HUD. He can say 'pull it apart' to see the inside."}


FUNCS = {"blueprint": blueprint}
TOOLS = [{"name": "blueprint", "description": (
    "Blueprint mode: after looking at a desk-camera photo of something he's holding, draw it as a blueprint on the "
    "HUD. Look it up first (web_search for its teardown / parts diagram / how it works) so the components, their "
    "arrangement and sizes are right for THAT kind of object. bbox: where the object is in the photo [x0, y0, x1, y1] as fractions (0 to 1) of the photo's width and "
    "height. features: 3 to 8 visible parts, each {name, at: [x, y] fraction of the PHOTO, note}. size: a rough size "
    "estimate ('about 15 x 7 x 1 cm'). material: what it's made of. inside: 4 to 10 components typically inside this "
    "kind of object (an informed guess is fine), each {name, shape (rect, rounded, circle, cylinder, board, coil, "
    "battery, screw, lens, wire, spring, fan), at: [x, y] centre as a fraction of the OBJECT's box, size: [w, h] "
    "fraction of the object's box, layer: 0 front (the side facing the camera) to 1 back, thick: its thickness as a "
    "fraction of the object's depth, note: what it does}. shell: the object's overall 3D shape (box, rounded, disc "
    "for flat round things like a watch or a puck, cylinder for cans and bottles, sphere). explode: 'layers' when "
    "the parts stack front to back (watch, phone, remote, laptop) so the 3D view pulls them apart along that stack, "
    "else 'radial'. source: where the parts list came from (a site name). note: one line about it."),
    "input_schema": {"type": "object", "required": ["title", "bbox", "inside"], "properties": {
        "title": S, "bbox": {"type": "array", "items": N}, "size": S, "material": S, "note": S, "source": S,
        "shell": {"type": "string", "enum": list(SHELLS)}, "explode": {"type": "string", "enum": ["layers", "radial"]},
        "features": {"type": "array", "items": {"type": "object", "properties": {"name": S, "at": PT, "note": S}}},
        "inside": {"type": "array", "items": {"type": "object", "properties": {
            "name": S, "shape": {"type": "string", "enum": list(SHAPES)}, "at": PT, "size": PT, "note": S,
            "layer": N, "thick": N}}}}}}]


def selftest():
    sent = []
    real = features._panel
    features._panel = sent.append
    try:
        r = blueprint("TV remote", [0.2, 0.1, 0.6, 0.95], features=[{"name": "Power", "at": [0.4, 0.15]}],
                      inside=[{"name": "Circuit board", "shape": "board", "at": [0.5, 0.5], "size": [0.8, 0.9]},
                              {"name": "Batteries", "shape": "battery", "at": [0.5, 0.85], "size": [2, "x"]},
                              {"name": "", "shape": "rect"}, {"name": "Thing", "shape": "teapot"}])
        ev = sent[0]
        assert r["inside"] == 3 and ev["inside"][1]["size"] == [1.0, 0.2] and ev["inside"][2]["shape"] == "rect"
        assert ev["features"][0]["at"] == [0.4, 0.15] and ev["bbox"] == [0.2, 0.1, 0.6, 0.95]
        assert ev["shell"] == "box" and ev["inside"][0]["layer"] == 0.5 and ev["inside"][0]["thick"] == 0.3
        blueprint("x", [0.5, 0.5, 0.51, 0.52], inside=[])
        assert sent[1]["bbox"] == [0.1, 0.1, 0.9, 0.9]
    finally:
        features._panel = real
    print("blueprint self-test passed")


if __name__ == "__main__":
    selftest()
