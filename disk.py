"""Disk doctor: "Jarvis, what's filling my drive?" / "disk doctor".

scan() measures the drive, the biggest folders in his user folder and Program Files, the biggest files, and what
can be cleared safely: temporary files, crash dumps, browser, graphics-driver shader and developer caches, the Recycle
Bin, Windows Update downloads, old installers in Downloads and Jarvis's own old pictures. The HUD shows it as a panel
with tick boxes; nothing is removed until he picks what to clear (or says yes to Jarvis).

clean() only ever clears the items from the last scan, by id: caches and temp files are deleted (files in use are
skipped), old installers go to the Recycle Bin, never his own files. Links and junctions are never followed.
"""
import json
import os
import shutil
import string
import subprocess
import sys
import threading
import time
from pathlib import Path

import features

HERE = Path(__file__).resolve().parent
STATE = HERE / "disk_state.json"  # the last scan's cleanable items (the HUD and the brain clear them by id)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SCAN_SECONDS = 25  # a scan stops measuring after this long (sizes are then "at least")
GB = 1024 ** 3


def _env(name, default=""):
    return os.environ.get(name) or default


def _is_link(p):
    try:
        return p.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(p))
    except OSError:
        return True


def size_of(path, deadline=None, big=None, min_big=GB // 2, older_than=0):
    """Bytes in a folder (or file), not following links. big: collects (size, path) of files over min_big.
    older_than: only files last changed at least this many seconds ago. Returns (bytes, files, complete)."""
    path = Path(path)
    total = files = 0
    cutoff = time.time() - older_than
    try:
        if path.is_file():
            st = path.stat()
            return (st.st_size, 1, True) if st.st_mtime <= cutoff else (0, 0, True)
    except OSError:
        return 0, 0, True
    stack = [str(path)]
    while stack:
        if deadline and time.time() > deadline:
            return total, files, False
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink() or (hasattr(e, "is_junction") and e.is_junction()):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            if st.st_mtime > cutoff:
                                continue
                            total += st.st_size
                            files += 1
                            if big is not None and st.st_size >= min_big:
                                big.append((st.st_size, e.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return total, files, True


def _recycle_bin():
    """(bytes in the Recycle Bin, items), Windows only."""
    if sys.platform != "win32":
        return 0, 0
    ps = ("$i=(New-Object -ComObject Shell.Application).NameSpace(10).Items();"
          "$s=0;foreach($x in $i){$s+=$x.Size};\"$s $($i.Count)\"")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=30, creationflags=NO_WINDOW).stdout.split()
        return int(out[0]), int(out[1])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return 0, 0


def _browser_caches(local):
    out = []
    for prof_root in (local / "Microsoft/Edge/User Data", local / "Google/Chrome/User Data",
                      local / "BraveSoftware/Brave-Browser/User Data", Path(_env("APPDATA")) / "Opera Software/Opera Stable",
                      Path(_env("APPDATA")) / "Opera Software/Opera GX Stable", local / "Opera Software/Opera Stable",
                      local / "Opera Software/Opera GX Stable"):
        if not prof_root.is_dir():
            continue
        profiles = [prof_root] + [p for p in prof_root.iterdir() if p.is_dir() and (p.name == "Default" or p.name.startswith("Profile"))]
        for prof in profiles:
            for c in ("Cache", "Code Cache", "GPUCache", "Service Worker/CacheStorage"):
                if (prof / c).is_dir():
                    out.append(prof / c)
    return out


def categories():
    """What can be cleared safely: [(id, title, why, [paths], how, older_than_seconds)].
    how: 'delete' (contents removed), 'recycle' (files sent to the Recycle Bin), 'bin' (empty the Recycle Bin)."""
    home = Path.home()
    local = Path(_env("LOCALAPPDATA", str(home / "AppData/Local")))
    roaming = Path(_env("APPDATA", str(home / "AppData/Roaming")))
    windir = Path(_env("WINDIR", "C:/Windows"))
    progdata = Path(_env("PROGRAMDATA", "C:/ProgramData"))
    day, month = 86400, 30 * 86400
    cats = [
        ("temp", "Temporary files", "Left behind by installers and apps; safe to clear (files in use are skipped).",
         [Path(_env("TEMP", str(local / "Temp"))), windir / "Temp"], "delete", day),
        ("dumps", "Crash dumps and error reports", "Copies of memory from programs that crashed.",
         [local / "CrashDumps", progdata / "Microsoft/Windows/WER/ReportArchive",
          progdata / "Microsoft/Windows/WER/ReportQueue", windir / "Minidump", windir / "MEMORY.DMP"], "delete", 0),
        ("browser", "Browser caches", "Saved copies of web pages and pictures; browsers make them again as needed. "
                                      "Close the browser first for the most space.",
         _browser_caches(local), "delete", 0),
        ("shaders", "Graphics shader caches", "Rebuilt automatically by the graphics driver (the first game launch "
                                              "after can take a little longer).",
         [local / "NVIDIA/DXCache", local / "NVIDIA/GLCache", local / "D3DSCache", local / "AMD/DxCache",
          local / "AMD/GLCache", local / "Intel/ShaderCache"], "delete", 0),
        ("devcache", "Developer download caches", "pip, npm, yarn and NuGet keep copies of every package they "
                                                   "downloaded; they download again when needed.",
         [local / "pip/Cache", local / "npm-cache", roaming / "npm-cache", local / "Yarn/Cache",
          home / ".nuget/packages", home / ".cache/pip"], "delete", 0),
        ("updates", "Windows Update downloads", "Installers for updates that are already installed (needs Jarvis "
                                                "to be running as administrator; else it's skipped).",
         [windir / "SoftwareDistribution/Download"], "delete", 7 * day),
        ("installers", "Old installers in Downloads", "Setup files (.exe, .msi, .zip, .iso) over a month old. They go "
                                                      "to the Recycle Bin, so they can be restored.",
         [p for p in (home / "Downloads").glob("*") if p.is_file() and p.suffix.lower() in (".exe", ".msi", ".iso", ".zip", ".7z", ".rar")]
         if (home / "Downloads").is_dir() else [], "recycle", month),
        ("jarvis", "Jarvis's old pictures", "Screenshots, photos and image searches Jarvis saved, over a month old.",
         [HERE / "screens", HERE / "uploads", HERE / "images"], "delete", month),
        ("bin", "Recycle Bin", "Files you already deleted.", [], "bin", 0),
    ]
    return cats


def drives():
    out = []
    letters = [f"{c}:\\" for c in string.ascii_uppercase] if sys.platform == "win32" else ["/"]
    for d in letters:
        try:
            u = shutil.disk_usage(d)
        except OSError:
            continue
        out.append({"drive": d.rstrip("\\"), "total": u.total, "used": u.used, "free": u.free})
    return out


def scan(show=True):
    """Measure the drive and what's cleanable; shows the disk doctor panel. Returns a summary for Jarvis."""
    t0 = time.time()
    deadline = t0 + SCAN_SECONDS
    home = Path.home()
    folders = [p for p in home.iterdir() if p.is_dir() and not _is_link(p) and not p.name.startswith(".")] if home.is_dir() else []
    folders += [p for p in (home / "AppData/Local", home / "AppData/Roaming") if p.is_dir()]
    if sys.platform == "win32":
        folders += [Path(p) for p in (_env("ProgramFiles", "C:/Program Files"), _env("ProgramFiles(x86)", "C:/Program Files (x86)"),
                                      _env("PROGRAMDATA", "C:/ProgramData")) if Path(p).is_dir()]
    big, sizes, lock = [], {}, threading.Lock()

    def measure(p):
        found = []
        s, n, done = size_of(p, deadline, found)
        with lock:
            sizes[str(p)] = (s, done)
            big.extend(found)
    threads = [threading.Thread(target=measure, args=(p,), daemon=True) for p in folders]
    for t in threads:
        t.start()
    cats, items = categories(), []
    for cid, title, why, paths, how, older in cats:
        if how == "bin":
            b, n = _recycle_bin()
            if b:
                items.append({"id": cid, "title": title, "why": why, "bytes": b, "files": n, "how": how})
            continue
        total = files = 0
        for p in paths:
            s, n, _ = size_of(p, deadline + 10, older_than=older)
            total, files = total + s, files + n
        if total > 5 * 1024 ** 2:  # over 5 MB is worth showing
            items.append({"id": cid, "title": title, "why": why, "bytes": total, "files": files, "how": how})
    for t in threads:
        t.join(max(0.1, deadline + 2 - time.time()))
    with lock:
        top = sorted(((s, p, d) for p, (s, d) in sizes.items()), reverse=True)[:12]
        big_files = sorted(set(big), reverse=True)[:10]
    _save({"items": {i["id"]: i for i in items}, "at": time.time()})
    ev = {"type": "disk", "drives": drives(), "items": items,
          "folders": [{"path": p, "bytes": s, "complete": d} for s, p, d in top],
          "big_files": [{"path": p, "bytes": s} for s, p in big_files],
          "seconds": round(time.time() - t0, 1)}
    if show:
        try:
            features._panel(ev)
        except OSError:
            pass
    can = sum(i["bytes"] for i in items)
    return {"shown": show, "drives": [{**d, "free_gb": round(d["free"] / GB, 1), "used_pct": round(100 * d["used"] / max(1, d["total"]))}
                                      for d in ev["drives"]],
            "can_free_gb": round(can / GB, 1),
            "cleanable": [{"id": i["id"], "title": i["title"], "gb": round(i["bytes"] / GB, 2)} for i in items],
            "biggest_folders": [{"path": f["path"], "gb": round(f["bytes"] / GB, 1)} for f in ev["folders"][:6]],
            "note": ("The disk doctor panel is on the HUD. Tell him the headline (how full, how much can be freed, the "
                     "biggest space users) in two sentences. Only call disk_clean after he says which to clear (or yes).")}


def _save(st):
    try:
        STATE.write_text(json.dumps(st), encoding="utf-8")
    except OSError:
        pass


def _load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _delete_contents(path, older_than):
    """Delete the files inside path (or path itself, for a file) that are old enough; returns bytes freed.
    Files in use are skipped. Links are removed as links, never followed."""
    path = Path(path)
    cutoff = time.time() - older_than
    freed = 0
    if path.is_file() and not _is_link(path):
        try:
            if path.stat().st_mtime <= cutoff:
                s = path.stat().st_size
                path.unlink()
                freed += s
        except OSError:
            pass
        return freed
    if not path.is_dir() or _is_link(path):
        return 0
    for root, dirs, files in os.walk(path, topdown=False, followlinks=False):
        for f in files:
            fp = os.path.join(root, f)
            try:
                st = os.lstat(fp)
                if st.st_mtime <= cutoff:
                    os.remove(fp)
                    freed += st.st_size
            except OSError:
                continue
        for d in dirs:
            dp = os.path.join(root, d)
            try:
                if os.path.islink(dp) or (hasattr(os.path, "isjunction") and os.path.isjunction(dp)):
                    continue
                os.rmdir(dp)  # only if now empty
            except OSError:
                continue
    return freed


def _to_recycle_bin(paths):
    if sys.platform != "win32" or not paths:
        return 0
    freed = 0
    ps = ("Add-Type -AssemblyName Microsoft.VisualBasic; foreach($p in $input){ try { "
          "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p,'OnlyErrorDialogs','SendToRecycleBin') } catch {} }")
    sizes = {str(p): p.stat().st_size for p in paths if p.is_file()}
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], input="\n".join(sizes), text=True,
                       capture_output=True, timeout=300, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return 0
    for p, s in sizes.items():
        if not Path(p).exists():
            freed += s
    return freed


def _empty_bin():
    if sys.platform != "win32":
        return 0
    before, _ = _recycle_bin()
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
                       capture_output=True, timeout=300, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return 0
    after, _ = _recycle_bin()
    return max(0, before - after)


def clean(ids):
    """Clear the chosen items from the last scan (ids like 'temp', 'browser'). Returns what was freed."""
    st = _load()
    known = st.get("items") or {}
    if not known or time.time() - st.get("at", 0) > 3 * 3600:
        return {"error": "Run the disk doctor scan first (it's been a while), then pick what to clear."}
    ids = [i for i in (ids or []) if i in known]
    if not ids:
        return {"error": "Pick what to clear: " + ", ".join(f"{k} ({v['title']})" for k, v in known.items())}
    cats = {c[0]: c for c in categories()}
    done, total = [], 0
    for cid in ids:
        _, title, _, paths, how, older = cats[cid]
        if how == "bin":
            freed = _empty_bin()
        elif how == "recycle":
            cutoff = time.time() - older
            freed = _to_recycle_bin([p for p in paths if p.is_file() and p.stat().st_mtime <= cutoff])
        else:
            freed = sum(_delete_contents(p, older) for p in paths)
        total += freed
        done.append({"id": cid, "title": title, "freed_gb": round(freed / GB, 2)})
    try:
        features._panel({"type": "disk_cleaned", "done": done, "freed": total, "drives": drives()})
    except OSError:
        pass
    return {"freed_gb": round(total / GB, 2), "done": done,
            "note": "Tell him how much was freed. Anything in use was skipped; installers went to the Recycle Bin."}


FUNCS = {"disk_doctor": lambda: scan(), "disk_clean": clean}
TOOLS = [
    {"name": "disk_doctor", "description": (
        "Disk doctor ('what's filling my drive?', 'free up space', 'disk doctor'): measures every drive, the biggest "
        "folders and files, and what can be cleared safely (temp files, crash dumps, browser, shader and developer "
        "caches, Windows Update downloads, old installers, the Recycle Bin), and shows it on the HUD with tick boxes. "
        "Takes about half a minute."),
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "disk_clean", "description": (
        "Clear items from the last disk_doctor scan, by id (temp, dumps, browser, shaders, devcache, updates, "
        "installers, jarvis, bin). ONLY after he's said which to clear, or yes to your suggestion: it deletes them "
        "(old installers go to the Recycle Bin)."),
     "input_schema": {"type": "object", "required": ["ids"], "properties": {"ids": {"type": "array", "items": {"type": "string"}}}}},
]


def selftest():
    import tempfile
    global STATE
    real_state, real_panel = STATE, features._panel
    sent = []
    features._panel = sent.append
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        STATE = tmp / "state.json"
        temp = tmp / "Temp"
        (temp / "sub").mkdir(parents=True)
        old, new = temp / "old.tmp", temp / "sub" / "new.tmp"
        old.write_bytes(b"x" * 6_000_000)
        new.write_bytes(b"y" * 1000)
        os.utime(old, (time.time() - 5 * 86400,) * 2)
        keep = tmp / "keep"
        keep.mkdir()
        (keep / "mine.txt").write_text("his file")
        try:
            os.symlink(keep, temp / "link", target_is_directory=True)  # a link out of the cache: never followed
        except OSError:
            pass
        assert size_of(temp)[0] == 6_001_000 and size_of(temp, older_than=86400)[0] == 6_000_000
        os.environ["TEMP"] = str(temp)
        try:
            r = scan()
            assert sent[-1]["type"] == "disk" and any(i["id"] == "temp" for i in sent[-1]["items"]), sent[-1]["items"]
            assert "error" in clean(["nonsense"])
            out = clean(["temp"])
            assert not old.exists() and new.exists() and (keep / "mine.txt").exists(), out  # new and linked files kept
            assert out["done"][0]["freed_gb"] >= 0 and sent[-1]["type"] == "disk_cleaned"
            assert r["can_free_gb"] >= 0
        finally:
            STATE, features._panel = real_state, real_panel
    print("disk self-test passed")


if __name__ == "__main__":
    selftest()
