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
          "balance", "hairspring", "pusher", "crown", "display", "speaker", "links", "keypad", "chip", "magnet", "plate")


def _f(v, lo=0.0, hi=1.0, default=0.5):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _pt(p, default=(0.5, 0.5)):
    return [_f(p[0], default=default[0]), _f(p[1], default=default[1])] if isinstance(p, (list, tuple)) and len(p) >= 2 \
        else list(default)


SHELLS = ("box", "rounded", "disc", "cylinder", "sphere")


def _mm(v):
    """[w, h, d] in millimetres, or None."""
    if not isinstance(v, (list, tuple)) or len(v) < 2:
        return None
    out = [_f(x, 0, 5000, 0) for x in list(v)[:3]]
    return out if out[0] > 0 and out[1] > 0 else None


def blueprint(title, bbox, features_=None, inside=None, size="", material="", note="", shell="box", explode="radial",
              source="", mm=None, how=None, sources=None, **kw):
    """Draw the blueprint on the HUD (see the tool description for the fields)."""
    feats = kw.get("features", features_) or []
    box = [_f(v) for v in (list(bbox) + [0, 0, 1, 1])[:4]] if isinstance(bbox, (list, tuple)) else [0, 0, 1, 1]
    if box[2] - box[0] < .05 or box[3] - box[1] < .05:
        box = [0.1, 0.1, 0.9, 0.9]
    ev = {"type": "blueprint", "title": str(title)[:60], "bbox": box, "size": str(size)[:60],
          "material": str(material)[:80], "note": str(note)[:200], "shell": shell if shell in SHELLS else "box",
          "explode": "layers" if explode == "layers" else "radial", "source": str(source)[:120], "mm": _mm(mm),
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
                                 if k in ("teeth", "spokes", "subdials", "count", "holes")} if isinstance(p.get("detail"), dict) else {}}
                     for p in (inside or [])[:12] if isinstance(p, dict) and p.get("name")]}
    features._panel(ev)
    return {"drawn": True, "features": len(ev["features"]), "inside": len(ev["inside"]),
            "note": "It's on the HUD. He can say 'pull it apart' to see the inside."}


FUNCS = {"blueprint": blueprint}
TOOLS = [{"name": "blueprint", "description": (
    "Blueprint mode: after looking at a desk-camera photo of something he's holding, draw it as a blueprint on the "
    "HUD. Call research_object first and draw from its dossier, so the components, their order and their real sizes "
    "are right for THAT object. mm: the object's real size [width, height, depth] in millimetres as seen from the "
    "front (from the research; estimate if nothing says). Each inside part can have mm [w, h, d] too (real sizes "
    "make the 3D model to scale). how: 3 to 6 short steps on how it works. sources: [{title, url}] from the research. "
    "bbox: where the object is in the photo [x0, y0, x1, y1] as fractions (0 to 1) of the photo's width and "
    "height. features: 3 to 8 visible parts, each {name, at: [x, y] fraction of the PHOTO, note}. size: a rough size "
    "estimate ('about 15 x 7 x 1 cm'). material: what it's made of. inside: 4 to 10 components typically inside this "
    "kind of object (an informed guess is fine), each {name, shape, at: [x, y] centre as a fraction of the OBJECT's box, size: [w, h] "
    "fraction of the object's box, layer: 0 front (the side facing the camera) to 1 back, thick: its thickness as a "
    "fraction of the object's depth, detail: {teeth, spokes, subdials, count, holes} where it applies (a gear's teeth "
    "and spokes, a dial's subdials, how many bracelet links or keys), note: what it does}. Shapes: gear, ring, gasket, "
    "dial, hands, dome (a domed crystal or lens), coin_cell, quartz (crystal oscillator), motor (stepper/vibration), "
    "case (with lugs), rotor (half-disc weight), balance (wheel with spokes), hairspring, pusher, crown, display, "
    "speaker, links (bracelet/strap), keypad, chip, magnet, plate, board (circuit board), battery, screw, spring, coil, "
    "lens, wire, fan, rect, rounded, circle, cylinder: pick the one that matches the real part. shell: the object's overall 3D shape (box, rounded, disc "
    "for flat round things like a watch or a puck, cylinder for cans and bottles, sphere). explode: 'layers' when "
    "the parts stack front to back (watch, phone, remote, laptop) so the 3D view pulls them apart along that stack, "
    "else 'radial'. source: where the parts list came from (a site name). note: one line about it."),
    "input_schema": {"type": "object", "required": ["title", "bbox", "inside"], "properties": {
        "title": S, "bbox": {"type": "array", "items": N}, "size": S, "material": S, "note": S, "source": S,
        "mm": {"type": "array", "items": N}, "how": {"type": "array", "items": S},
        "sources": {"type": "array", "items": {"type": "object", "properties": {"title": S, "url": S}}},
        "shell": {"type": "string", "enum": list(SHELLS)}, "explode": {"type": "string", "enum": ["layers", "radial"]},
        "features": {"type": "array", "items": {"type": "object", "properties": {"name": S, "at": PT, "note": S}}},
        "inside": {"type": "array", "items": {"type": "object", "properties": {
            "name": S, "shape": {"type": "string", "enum": list(SHAPES)}, "at": PT, "size": PT, "note": S,
            "layer": N, "thick": N, "mm": {"type": "array", "items": N}, "detail": {"type": "object"}}}}}}}]


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
        assert ev["mm"] is None and _mm([42, 42, 12]) == [42.0, 42.0, 12.0] and _mm([0, 5]) is None
        blueprint("x", [0.5, 0.5, 0.51, 0.52], inside=[])
        assert sent[1]["bbox"] == [0.1, 0.1, 0.9, 0.9]
    finally:
        features._panel = real
    print("blueprint self-test passed")


if __name__ == "__main__":
    selftest()
