"""Your own additions to Jarvis, kept in the custom/ folder so updates never touch them.

What goes in custom/ (see CUSTOM.md for the full guide):
  *.py   Python add-ons. Each can have FUNCS / TOOLS (new tools Jarvis can use, same shape as the built-in
         ones) and STATS() (a dict merged into the PC stats the HUD gets every 2 seconds).
  *.js   Loaded into the HUD after it starts. Use the JarvisHUD helpers to add panels and react to live stats.
  *.css  Extra styles for the HUD.
A broken add-on is skipped and logged; it never stops Jarvis from starting.
"""
import datetime
import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CUSTOM = HERE / "custom"
modules, errors = [], {}


def load():
    """Import every custom/*.py. Returns the modules that loaded."""
    if not CUSTOM.is_dir():
        return []
    for f in sorted(CUSTOM.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"custom_{f.stem}", f)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            modules.append(m)
        except Exception as e:
            errors[f.name] = f"{type(e).__name__}: {e}"
            print(datetime.datetime.now(), f"custom add-on {f.name} skipped:", errors[f.name])
    return modules


def stats():
    """Extra live stats from every add-on that has STATS()."""
    out = {}
    for m in modules:
        if hasattr(m, "STATS"):
            try:
                out.update(m.STATS() or {})
            except Exception as e:
                errors[m.__name__] = f"STATS: {type(e).__name__}: {e}"
    return out


def web_files():
    """The .js and .css files the HUD should load, in name order."""
    if not CUSTOM.is_dir():
        return []
    return sorted(f.name for f in CUSTOM.iterdir() if f.suffix in (".js", ".css") and SAFE.fullmatch(f.name))


SAFE = re.compile(r"[A-Za-z0-9_.-]+")


def file(name):
    """A custom web file's bytes and type, or None."""
    f = CUSTOM / name
    if not SAFE.fullmatch(name) or f.suffix not in (".js", ".css") or not f.is_file():
        return None
    return f.read_bytes(), "text/css" if f.suffix == ".css" else "application/javascript"


def selftest():
    import shutil
    import tempfile
    global CUSTOM
    real, CUSTOM = CUSTOM, Path(tempfile.mkdtemp())
    try:
        (CUSTOM / "good.py").write_text("FUNCS = {'hello': lambda: 'hi'}\nTOOLS = []\ndef STATS():\n    return {'x': 1}\n")
        (CUSTOM / "bad.py").write_text("this is not python")
        (CUSTOM / "panel.js").write_text("// js")
        (CUSTOM / "look.css").write_text("/* css */")
        (CUSTOM / "notes.txt").write_text("ignored")
        ms = load()
        assert [m.FUNCS["hello"]() for m in ms] == ["hi"] and "bad.py" in errors
        assert stats() == {"x": 1} and web_files() == ["look.css", "panel.js"]
        assert file("panel.js")[1] == "application/javascript" and file("../server.py") is None and file("notes.txt") is None
    finally:
        shutil.rmtree(CUSTOM)
        CUSTOM = real
        modules.clear()
        errors.clear()
    print("custom loader self-test passed")


if __name__ == "__main__":
    selftest()
