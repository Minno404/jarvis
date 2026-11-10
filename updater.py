"""Updates from GitHub: the HUD checks for a newer version and offers an Update button.

Updating downloads the repo's latest code, copies it over the Jarvis folder and restarts Jarvis directly (see restart()). Personal files (settings, memory, journal, TV pairing...) are
never in the repo, so they're left alone.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "Minno404/jarvis"
HERE = Path(__file__).resolve().parent
KEEP = {"settings.json", "memory.json", "state.json", "projects.json", "config.yaml", "tokens.json",
        "phone_key.txt", "deepseek_key.txt", "dev_jobs.json"}  # never overwritten, even if one ever lands in the repo by mistake
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
    """Start a fresh Jarvis straight away and close this one. It skips Jarvis.bat's component checks (a few seconds
    each, and they can wait forever on an install), starts detached so nothing closing this copy takes it down, and
    waits for this copy to close before it opens the port (--after)."""
    exe = HERE / "Jarvis.exe"
    if os.name == "nt" and exe.exists() and (HERE / "jarvis_exe.json").exists():
        run = [str(exe)]
    else:
        w = Path(sys.executable).with_name("pythonw.exe")
        run = [str(w if w.exists() else sys.executable)]
    args = run + ["server.py", "--after", str(os.getpid())] + [a for a in sys.argv[1:] if a == "--browser"]
    flags = 0x8 | 0x200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(args, cwd=HERE, creationflags=(flags | 0x01000000) if os.name == "nt" else 0, close_fds=True)
    except OSError:  # not allowed to leave its job: start it inside
        try:
            subprocess.Popen(args, cwd=HERE, creationflags=flags if os.name == "nt" else 0, close_fds=True)
        except OSError:  # last resort: the old way, through Jarvis.bat
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
    (d / "settings.json").write_text('{"name": "Sam"}')
    (d / "custom").mkdir()
    (d / "custom" / "panel.js").write_text("mine")
    (d / "server.py.upstream").write_text("old leftover")
    assert sorted(install(buf.getvalue(), d)) == ["server.py", str(Path("web/index.html"))]
    assert (d / "server.py").read_text() == "new code" and "Sam" in (d / "settings.json").read_text()
    assert (d / "custom" / "panel.js").read_text() == "mine" and not (d / "server.py.upstream").exists()
    shutil.rmtree(d)
    print("updater self-test passed")


if __name__ == "__main__":
    selftest()
