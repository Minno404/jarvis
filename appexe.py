"""Jarvis.exe: a copy of pythonw named Jarvis, with the Jarvis icon and name, so Task Manager and the taskbar
show "Jarvis" instead of Python. Jarvis.bat runs this and starts whatever it prints.

The copy sits next to your pythonw.exe (it has to, to find Python's files). If that folder can't be written to
(Python installed for all users) or anything fails, it prints "pythonw" and Jarvis starts as before.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RCEDIT = "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe"
STAMP = HERE / "jarvis_exe.json"  # which Python and icon it was built from, so it's rebuilt when they change
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def build():
    base = Path(sys.base_prefix)
    src, exe, ico = base / "pythonw.exe", base / "Jarvis.exe", HERE / "web" / "jarvis.ico"
    want = {"python": sys.version, "icon": ico.stat().st_mtime, "exe": str(exe)}
    if exe.exists() and STAMP.exists() and json.loads(STAMP.read_text()) == want:
        return exe
    with tempfile.TemporaryDirectory() as tmp:
        tmp_exe, rc = Path(tmp) / "Jarvis.exe", Path(tmp) / "rcedit.exe"
        shutil.copy2(src, tmp_exe)
        req = urllib.request.Request(RCEDIT, headers={"User-Agent": "Jarvis"})
        with urllib.request.urlopen(req, timeout=60) as r:
            rc.write_bytes(r.read())
        subprocess.run([str(rc), str(tmp_exe), "--set-icon", str(ico),
                        "--set-version-string", "FileDescription", "Jarvis",
                        "--set-version-string", "ProductName", "Jarvis"], check=True, timeout=60, creationflags=NO_WINDOW)
        shutil.copy2(tmp_exe, exe)  # fails if Python's folder is read-only: fine, pythonw it is
    # make sure the copy really runs Jarvis before trusting it
    subprocess.run([str(exe), "-c", "import webview"], check=True, timeout=60, creationflags=NO_WINDOW)
    STAMP.write_text(json.dumps(want))
    return exe


if __name__ == "__main__":
    try:
        print(build())
    except Exception as e:
        print("Jarvis.exe unavailable, using pythonw:", repr(e), file=sys.stderr)
        print("pythonw")
