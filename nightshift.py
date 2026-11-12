"""Night shift: "work on the Gun Bros reload system tonight". Jarvis codes while {USER} sleeps, on a copy.

1. tonight(project, request): copies the project to drafts/<project>-<date> (skipping .git, node_modules, build
   output and files over 50 MB) and queues a coding job there that starts at Settings 'night_start' (default
   00:30; "now" starts it straight away). His real project is never touched.
2. When it's done, Jarvis compares the copy with his project: the files it changed or added, with a line count.
   The morning panel shows the summary and the files, with "Keep tonight's work" and "Throw it away".
3. Keep copies just those files into his project, after backing up the ones it replaces to
   drafts/<project>-<date>-backup. Throw it away deletes the copy.
The PC has to be on overnight (Jarvis keeps it awake while a job runs).
"""
import datetime
import filecmp
import hashlib
import shutil
from pathlib import Path

import features

SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", "Library", "Temp", "obj", "bin", ".vs"}
MAX_FILE, MAX_TOTAL = 50_000_000, 1_000_000_000


def _drafts():
    d = features.HERE / "drafts"
    d.mkdir(exist_ok=True)
    return d


def _copy(src, dst):
    total = 0

    def ignore(folder, names):
        nonlocal total
        out = []
        for n in names:
            p = Path(folder) / n
            if n in SKIP or (p.is_file() and p.stat().st_size > MAX_FILE):
                out.append(n)
            elif p.is_file():
                total += p.stat().st_size
                if total > MAX_TOTAL:
                    raise RuntimeError("The project is over 1 GB without its build folders: too big to copy overnight.")
        return out
    shutil.copytree(src, dst, ignore=ignore)


def _start_time(now=None):
    now = now or datetime.datetime.now()
    t = features.settings().get("night_start", "00:30")
    h, m = map(int, t.split(":"))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if at <= now and (now - at).total_seconds() > 4 * 3600:  # it's daytime: tonight
        at += datetime.timedelta(days=1)
    return at if at > now else now


def tonight(project, request, now=False):
    """Queue a coding job on a copy of his project, to run tonight (or now)."""
    import devhelper
    key, path = devhelper._project(project)
    if not key:
        return {"error": f"No project called '{project}'", "projects": list(devhelper.list_projects())}
    if Path(path).resolve() == features.HERE.resolve():
        return {"error": "Not Jarvis himself: use a normal job for changes to Jarvis (they go in custom/)."}
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    draft = _drafts() / f"{key.replace(' ', '-')}-{stamp}"
    try:
        _copy(path, draft)
    except Exception as e:
        shutil.rmtree(draft, ignore_errors=True)
        return {"error": str(e)}
    start = datetime.datetime.now() if now else _start_time()
    jobs = devhelper._load("dev_jobs.json", [])
    job = {"id": devhelper._next_id(jobs), "project": key, "path": str(draft), "original": path, "night": True,
           "request": request + "\n\n(You're working overnight on a copy of the project while he sleeps: take your "
           "time, do it thoroughly, and keep the change focused on what he asked.)",
           "status": "queued", "after": start.isoformat(timespec="minutes"),
           "asked": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    devhelper._save("dev_jobs.json", jobs + [job])
    return {"queued": job["id"], "starts": start.strftime("%H:%M"), "copy": str(draft),
            "note": f"Working on a copy from {start:%H:%M}; your project isn't touched until you say keep it."}


def changes(original, draft):
    """Files the job changed or added in the copy -> [(relative path, 'changed'|'new', lines)]."""
    out = []
    o, d = Path(original), Path(draft)
    for f in sorted(d.rglob("*")):
        if not f.is_file() or any(part in SKIP for part in f.relative_to(d).parts):
            continue
        rel = f.relative_to(d)
        src = o / rel
        if not src.exists():
            kind = "new"
        elif filecmp.cmp(src, f, shallow=False):
            continue
        else:
            kind = "changed"
        try:
            lines = f.read_text(encoding="utf-8").count("\n") + 1
        except (UnicodeDecodeError, OSError):
            lines = 0
        out.append((str(rel).replace("\\", "/"), kind, lines))
    return out


def after_job(job, summary, say):
    """The night's job finished: the panel for the morning, and the spoken summary (held until he's back)."""
    ch = changes(job["original"], job["path"])
    name = Path(job["path"]).name
    features._save("nightshift.json", {**features._load("nightshift.json", {}), name: {
        "original": job["original"], "draft": job["path"], "summary": summary, "files": ch,
        "finished": datetime.datetime.now().isoformat(timespec="minutes")}})
    features._panel({"type": "panel", "kind": "list", "title": f"Night shift: {job['project']}", "stay": True,
                     "items": [{"text": summary[:300], "sub": ""}] + [{"text": f"{k.upper()} {p}", "sub": f"{n} lines"}
                                                                      for p, k, n in ch[:15]],
                     "note": f"{len(ch)} files changed in the copy; your project is untouched until you keep it.",
                     "actions": ([["Keep tonight's work", f"keep night shift {name}"]] if ch else [])
                     + [["Throw it away", f"discard night shift {name}"]]})
    say(f"Morning report from the night shift on {job['project']}, {{TITLE}}: {summary} "
        + (f"{len(ch)} files changed in the copy; say keep it to bring them into your project." if ch else "Nothing changed."))


def _find(name=None):
    d = features._load("nightshift.json", {})
    if name and name in d:
        return name, d[name]
    if not name and d:
        k = sorted(d, key=lambda k: d[k]["finished"])[-1]
        return k, d[k]
    return None, None


def keep_night(name=None):
    """Bring the night's changed files into his project (the replaced ones are backed up first)."""
    name, n = _find(name)
    if not n:
        return {"error": "No night shift work waiting."}
    ch = changes(n["original"], n["draft"])
    backup = _drafts() / f"{name}-backup"
    for rel, kind, _ in ch:
        src, dst = Path(n["draft"]) / rel, Path(n["original"]) / rel
        if kind == "changed":
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup / rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    shutil.rmtree(n["draft"], ignore_errors=True)
    d = features._load("nightshift.json", {})
    d.pop(name, None)
    features._save("nightshift.json", d)
    return {"kept": len(ch), "backup": str(backup) if any(k == "changed" for _, k, _ in ch) else None}


def discard_night(name=None):
    name, n = _find(name)
    if not n:
        return {"error": "No night shift work waiting."}
    shutil.rmtree(n["draft"], ignore_errors=True)
    d = features._load("nightshift.json", {})
    d.pop(name, None)
    features._save("nightshift.json", d)
    return {"discarded": name}


FUNCS = {"night_shift": tonight, "keep_night_shift": keep_night, "discard_night_shift": discard_night}
S = {"type": "string"}
TOOLS = [
    {"name": "night_shift", "description": "Code on one of his projects overnight, on a copy ('work on the Gun Bros "
     "reload system tonight'): it starts at night, and in the morning he gets a summary and the changed files to keep "
     "or throw away. now=true starts straight away. project: a name from list_projects.",
     "input_schema": {"type": "object", "required": ["project", "request"],
                      "properties": {"project": S, "request": S, "now": {"type": "boolean"}}}},
    {"name": "keep_night_shift", "description": "Bring the night shift's changes into his project (only when he says).",
     "input_schema": {"type": "object", "properties": {"name": S}}},
    {"name": "discard_night_shift", "description": "Throw away the night shift's work.",
     "input_schema": {"type": "object", "properties": {"name": S}}},
]
COMMANDS = {"Projects": ["Work on my game tonight: …", "Keep tonight's work"]}


if __name__ == "__main__":
    import json
    import tempfile
    features.HERE = Path(tempfile.mkdtemp())
    proj = Path(tempfile.mkdtemp()) / "game"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "gun.lua").write_text("ammo = 6\n")
    (proj / "node_modules").mkdir()
    (proj / "node_modules" / "big.js").write_text("x")
    import devhelper
    devhelper._load = lambda n, d: json.loads((features.HERE / n).read_text()) if (features.HERE / n).exists() else d
    devhelper._save = lambda n, data: (features.HERE / n).write_text(json.dumps(data))
    devhelper.list_projects = lambda: {"gun bros": str(proj)}
    r = tonight("gun bros", "add a reload")
    job = devhelper._load("dev_jobs.json", [])[-1]
    draft = Path(job["path"])
    assert job["night"] and job["after"] and (draft / "src" / "gun.lua").exists() and not (draft / "node_modules").exists()
    assert _start_time(datetime.datetime(2026, 11, 13, 14, 0)) == datetime.datetime(2026, 11, 14, 0, 30)
    assert _start_time(datetime.datetime(2026, 11, 13, 1, 0)) == datetime.datetime(2026, 11, 13, 1, 0)  # past 00:30: now
    (draft / "src" / "gun.lua").write_text("ammo = 6\nfunction reload() ammo = 6 end\n")
    (draft / "src" / "reload.lua").write_text("-- new\n")
    assert changes(proj, draft) == [("src/gun.lua", "changed", 3), ("src/reload.lua", "new", 2)]
    shown, said = [], []
    features._panel = shown.append
    after_job(job, "Added reloading.", said.append)
    assert "2 files changed" in said[-1] and shown[-1]["actions"][0][0] == "Keep tonight's work"
    k = keep_night()
    assert k["kept"] == 2 and "reload" in (proj / "src" / "gun.lua").read_text() and (proj / "src" / "reload.lua").exists()
    assert Path(k["backup"], "src", "gun.lua").read_text() == "ammo = 6\n" and not draft.exists()
    print("nightshift self-test passed")
