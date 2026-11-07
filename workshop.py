"""The hologram workshop: 3D models from your projects (or dropped on the HUD) shown as a spinning hologram you can
turn with the mouse, or with your hand in front of the desk camera.

show_model("player") finds the best match among .glb .gltf .obj .stl .fbx files in your projects, Desktop, Documents
and Downloads, and puts it on the HUD. The files are served read-only from those folders (so a .gltf's textures and
.bin load too).
"""
import base64
import os
import time
from pathlib import Path

import features

EXTS = (".glb", ".gltf", ".obj", ".stl", ".fbx")
SKIP_DIRS = {"node_modules", ".git", ".godot", ".import", "library", "temp", "__pycache__", "appdata", ".venv", "venv"}
S = {"type": "string"}
_cache = {"at": 0.0, "files": []}


def roots():
    """Where models are looked for (and the only places they're served from)."""
    import devhelper
    home = Path.home()
    r = [Path(p) for p in devhelper.list_projects().values()] + [home / "Desktop", home / "Documents", home / "Downloads"]
    return [p.resolve() for p in r if p.is_dir()]


def scan(limit=40000):
    if time.time() - _cache["at"] < 120:
        return _cache["files"]
    found, seen = [], 0
    for root in roots():
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIRS and not x.startswith(".")]
            if d[len(str(root)):].count(os.sep) > 7:
                dirs[:] = []
            for f in files:
                seen += 1
                if f.lower().endswith(EXTS):
                    found.append(os.path.join(d, f))
            if seen > limit:
                break
    _cache.update(at=time.time(), files=found)
    return found


def best(query, files):
    words = [w for w in query.lower().replace("_", " ").split() if w not in ("the", "my", "a", "model", "3d")]
    def score(p):
        name, path = os.path.basename(p).lower(), p.lower()
        return (sum(3 for w in words if w in name) + sum(1 for w in words if w in path), p.lower().endswith(".glb"))
    ranked = sorted(files, key=score, reverse=True)
    return [p for p in ranked if score(p)[0] > 0]


def url_for(path):
    """/api/modelfile/<folder, encoded>/<file name>: relative files (textures, .bin) resolve next to it."""
    p = Path(path)
    folder = base64.urlsafe_b64encode(str(p.parent).encode()).decode().rstrip("=")
    return f"/api/modelfile/{folder}/{p.name}"


def resolve(rest):
    """/api/modelfile/... back to a file, only inside the model folders. None if not allowed."""
    folder, _, rel = rest.partition("/")
    try:
        base = Path(base64.urlsafe_b64decode(folder + "=" * (-len(folder) % 4)).decode())
    except Exception:
        return None
    from urllib.parse import unquote
    f = (base / unquote(rel)).resolve()
    if not any(f.is_relative_to(r) for r in roots()) or not f.is_file():
        return None
    return f


def show_model(query):
    """Find a 3D model by name in his projects (or Desktop/Documents/Downloads) and show it as a hologram."""
    files = scan()
    hits = best(query, files)
    if not hits:
        return {"found": False, "note": f"No 3D model matching '{query}' ({len(files)} models looked at: .glb, .gltf, "
                                        ".obj, .stl, .fbx). He can also drop one on the workshop panel."}
    path = hits[0]
    features._panel({"type": "model", "url": url_for(path), "name": os.path.basename(path),
                     "ext": os.path.splitext(path)[1].lower()})
    return {"shown": os.path.basename(path), "folder": os.path.dirname(path),
            "others": [os.path.basename(p) for p in hits[1:6]]}


def list_models(query=""):
    files = scan()
    return {"models": [os.path.basename(p) for p in (best(query, files) if query else files)[:30]], "total": len(files)}


FUNCS = {"show_model": show_model, "list_models": list_models}
TOOLS = [
    {"name": "show_model", "description": "Show a 3D model from his projects as a hologram in the workshop panel "
     "('show me the player model', 'hologram of the gun'). Searches .glb/.gltf/.obj/.stl/.fbx files by name.",
     "input_schema": {"type": "object", "required": ["query"], "properties": {"query": S}}},
    {"name": "list_models", "description": "List the 3D model files Jarvis can show (optionally matching a word).",
     "input_schema": {"type": "object", "properties": {"query": S}}},
]


def selftest():
    files = [r"C:\Projects\GunBros\models\player_soldier.glb", r"C:\Projects\GunBros\models\gun_pistol.fbx",
             r"C:\Users\x\Downloads\chair.obj"]
    assert best("player", files)[0].endswith("player_soldier.glb") and best("the pistol model", files)[0].endswith(".fbx")
    assert best("dragon", files) == []
    u = url_for(r"/tmp/a b/ship.gltf")
    assert u.endswith("/ship.gltf") and resolve(u.split("/api/modelfile/")[1].replace("ship.gltf", "../../etc/passwd")) is None
    print("workshop self-test passed")


if __name__ == "__main__":
    selftest()
