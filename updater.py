"""Updates from GitHub: the HUD checks for a newer version and offers an Update button.

Updating downloads the repo's latest code, copies it over the Jarvis folder and restarts through Jarvis.bat
(which also installs any new components). Personal files (settings, memory, journal, TV pairing...) are
never in the repo, so they're left alone.
"""
import io
import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

REPO = "Minno404/jarvis"
HERE = Path(__file__).resolve().parent
KEEP = {"settings.json", "memory.json", "state.json", "projects.json", "config.yaml", "tokens.json",
        "phone_key.txt", "dev_jobs.json"}  # never overwritten, even if one ever lands in the repo by mistake
KEEP_DIRS = {"custom", "voices", "webdata", "backups", "conversations", "uploads", "images", "reviews", "screens", "mt5 reports"}


def _get(url, timeout=10, **headers):
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-updater", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _v(s):
    return tuple(int(x) for x in s.strip().lstrip("v").split("."))


def latest():
    """The newest version on GitHub and its notes, e.g. {'version': '1.2.0', 'notes': '...'}."""
    # through GitHub's API: the raw file address is cached for ~5 minutes, so a fresh update wasn't seen at first
    return json.loads(_get(f"https://api.github.com/repos/{REPO}/contents/version.json?ref=main",
                           Accept="application/vnd.github.raw+json"))


def check(current):
    try:
        new = latest()
    except Exception as e:
        return {"update": False, "error": f"Couldn't check for updates: {e}"}
    return {"update": _v(new["version"]) > _v(current), "current": current, **new}


def install(data=None, dest=HERE):
    """Copy the latest code over the Jarvis folder. Returns the files written."""
    z = zipfile.ZipFile(io.BytesIO(data or _get(f"https://github.com/{REPO}/archive/refs/heads/main.zip", 60)))
    written = []
    for info in z.infolist():
        rel = Path(*Path(info.filename).parts[1:])  # drop the "jarvis-main/" top folder
        if info.is_dir() or not rel.parts or rel.name in KEEP or ".." in rel.parts or rel.parts[0] in KEEP_DIRS:
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, open(out, "wb") as f:
            shutil.copyfileobj(src, f)
        written.append(str(rel))
    for leftover in [*dest.rglob("*.upstream"), dest / ".update_base.json"]:  # from an older updater
        if leftover.is_file() and "custom" not in leftover.parts:
            leftover.unlink()
    return written


def restart():
    """Start Jarvis again through Jarvis.bat once this copy has closed, then close this one."""
    # ping is a 2 s wait that works without a console; the new copy then gets the port
    subprocess.Popen('cmd /c "ping -n 3 127.0.0.1 >nul & call Jarvis.bat"', cwd=HERE,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    os._exit(0)


def selftest():
    import tempfile
    assert _v("1.10.0") > _v("1.9.3") and not _v("1.1.0") > _v("v1.1.0")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("jarvis-main/server.py", "new code")
        z.writestr("jarvis-main/web/index.html", "<html>")
        z.writestr("jarvis-main/settings.json", "{}")
        z.writestr("jarvis-main/web/", "")
        z.writestr("jarvis-main/custom/panel.js", "from the repo")
    d = Path(tempfile.mkdtemp())
    (d / "settings.json").write_text('{"name": "Alex"}')
    (d / "custom").mkdir()
    (d / "custom" / "panel.js").write_text("mine")
    (d / "server.py.upstream").write_text("old leftover")
    assert sorted(install(buf.getvalue(), d)) == ["server.py", str(Path("web/index.html"))]
    assert (d / "server.py").read_text() == "new code" and "Alex" in (d / "settings.json").read_text()
    assert (d / "custom" / "panel.js").read_text() == "mine" and not (d / "server.py.upstream").exists()
    shutil.rmtree(d)
    print("updater self-test passed")


if __name__ == "__main__":
    selftest()
