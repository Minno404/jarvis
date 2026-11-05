"""Screen awareness, the dev helper, PC jobs and reading Windows errors.

screenshot: saves what's on your screen to screens/screen.png for Jarvis to look at.
dev_task:   hands a coding job on one of your projects to a separate Claude Code run in that project's
            folder. It works in the background (Jarvis's server picks the job up) and Jarvis tells you
            when it's done. It can read and edit files in that folder only, and can't run commands.
pc_task:    anything else, done by a full Claude Code run (shell, files, web) in Claude Code's auto mode,
            where a safety check reviews each action and blocks risky ones.
pc_errors:  recent errors from Windows' own logs, grouped.
"""
import datetime
import json
import re
import os
import shutil
import subprocess
from pathlib import Path

import features
from features import _load, _save, _next_id

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------- Screen ----------
def screenshot(all_screens=False):
    from PIL import ImageGrab  # pip install pillow
    img = ImageGrab.grab(all_screens=bool(all_screens))
    img.thumbnail((1920, 1920))  # plenty to read text, and keeps it quick
    d = features.HERE / "screens"
    d.mkdir(exist_ok=True)
    path = d / "screen.png"
    img.save(path)
    return {"saved": str(path), "size": list(img.size), "next": "Read this file with the Read tool to see the screen."}


# ---------- Projects ----------
DEFAULT_PROJECTS = {}  # add your own: "add my project X at C:\\..."


def list_projects():
    # Jarvis himself is always a project: changes to him go into custom/ (see CUSTOM.md) and survive updates
    return {**_load("projects.json", DEFAULT_PROJECTS), "jarvis": str(Path(__file__).resolve().parent)}


def add_project(name, path):
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.is_dir():
        return {"error": f"No folder at {p}"}
    projects = list_projects()
    projects[name.lower().strip()] = str(p)
    _save("projects.json", projects)
    return {"added": name, "path": str(p)}


def _project(name):
    projects, q = list_projects(), name.lower().strip()
    key = q if q in projects else next((k for k in projects if q in k or k in q), None)
    return key, projects.get(key)


def dev_task(project, request):
    key, path = _project(project)
    if not key:
        return {"error": f"No project called '{project}'", "projects": list(list_projects())}
    jobs = _load("dev_jobs.json", [])
    job = {"id": _next_id(jobs), "project": key, "path": path, "request": request, "status": "queued",
           "asked": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    _save("dev_jobs.json", jobs + [job])
    return {"queued": job["id"], "note": "It runs in the background; Jarvis will say when it's done."}


def dev_status(id=None):
    jobs = _load("dev_jobs.json", [])
    return [j for j in jobs if j["id"] == id] if id else jobs[-5:]


DEV_PROMPT = ("You are helping {USER} with his project in this folder. Do what he asks, keeping changes small and "
              "in the style of the existing code. You can read and edit files here but can't run commands, so "
              "don't claim anything was tested. Finish with 2-3 plain sentences (no markdown or backticks) he can hear read aloud: what you "
              "changed (file names) or found, and anything he should check.\n\nHis request: ")


def next_job():
    """Mark the oldest queued job as running and return it (or None)."""
    jobs = _load("dev_jobs.json", [])
    job = next((j for j in jobs if j["status"] == "queued"), None)
    if job:
        job["status"] = "running"
        _save("dev_jobs.json", jobs)
    return job


def finish_job(job, status, result):
    jobs = _load("dev_jobs.json", [])
    for j in jobs:
        if j["id"] == job["id"]:
            j.update(status=status, result=result, finished=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    _save("dev_jobs.json", jobs[-50:])


# ---------- Anything else on the PC ----------
def pc_task(request):
    """Hand a job to a full Claude Code run on his PC, the same way he'd ask Claude in chat."""
    jobs = _load("dev_jobs.json", [])
    job = {"id": _next_id(jobs), "kind": "pc", "project": "PC", "path": str(Path.home()), "request": request,
           "status": "queued", "asked": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    _save("dev_jobs.json", jobs + [job])
    return {"queued": job["id"], "note": "It runs in the background; Jarvis will say when it's done."}


PC_PROMPT = ("You are Jarvis's hands on {USER}'s Windows PC. He asked for the job below by voice, so do it properly "
             "and completely, like a careful senior engineer: look before you change anything, prefer reversible "
             "changes, back up a file before editing it, never delete his files or touch his trading account, and "
             "if a step needs Administrator rights and you don't have them, say exactly what to run. You can use "
             "the shell, files and the web. Finish with 2-4 plain sentences (no markdown or backticks) he can hear read aloud: what you did "
             "or found, and anything left for him to do.\n\nThe job: ")


SELF_RULE = ("\n\nIMPORTANT: Jarvis's own program lives in {HERE}. Its core files (*.py, web/index.html, updater, "
             "README) are replaced by every update, so NEVER edit them. To change or add to Jarvis (new panels, "
             "stats, tools, looks), write files only in {HERE}\\custom, following {HERE}\\CUSTOM.md: read it first. "
             "Things built there are kept through every update.\n\n")


def _self_rule(job):
    """Jobs that could touch Jarvis himself get the custom/ rule, so updates keep working."""
    here = str(Path(__file__).resolve().parent)
    touches = job.get("kind") == "pc" or Path(job["path"]).resolve() == Path(here)
    return SELF_RULE.replace("{HERE}", here) if touches else ""


def run_job(job, claude, brain="claude"):
    """Run one background job and return the spoken summary. brain: "claude" or "chatgpt" (whichever Jarvis is
    thinking with). A Claude job that hits the plan's limit is handed to ChatGPT when it's set up.

    Dev jobs: in the project folder, read and edit only. PC jobs: anywhere, with the shell and the web; with Claude,
    under Claude Code's auto mode, where a safety check reviews every action and blocks risky ones."""
    import gpt_brain
    prompt = features.personal(PC_PROMPT if job.get("kind") == "pc" else DEV_PROMPT) + _self_rule(job) + job["request"]
    text, status = "", "error"
    if brain != "chatgpt" and claude:
        base = [claude, "-p", "--output-format", "json", "--model", os.environ.get("JARVIS_DEV_MODEL", "sonnet"),
                "--strict-mcp-config"]
        if job.get("kind") == "pc":
            cmd = base + ["--permission-mode", "auto", "--permission-prompts", "none"]
        else:
            cmd = base + ["--permission-mode", "acceptEdits", "--allowedTools", "Read,Edit,Write,Glob,Grep",
                          "--disallowedTools", "Bash,PowerShell,WebFetch,WebSearch"]
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                               cwd=job["path"], timeout=1800, creationflags=NO_WINDOW)
            out = json.loads(r.stdout)
            text = out.get("result", "").strip() or "It finished but didn't say anything."
            status = "error" if out.get("is_error") else "done"
        except Exception as e:
            text, status = f"It didn't work: {type(e).__name__}.", "error"
        limited = status == "error" and re.search(r"limit|quota|usage|exceeded|429", text, re.I)
        if limited and gpt_brain.available():
            brain = "chatgpt"  # Claude's allowance ran out: let ChatGPT do the job instead
    if brain == "chatgpt" or not claude:
        if not gpt_brain.available():
            text, status = text or "Neither Claude nor ChatGPT is set up for jobs on this PC.", "error"
        else:
            try:
                text, ok = gpt_brain.run_task(prompt, job["path"])
                status = "done" if ok else "error"
            except Exception as e:
                text, status = f"It didn't work: {type(e).__name__}.", "error"
    finish_job(job, status, text)
    what = "that job" if job.get("kind") == "pc" else f"the {job['project']} job"
    return f"Sir, {what} is {'done' if status == 'done' else 'stuck'}. {text}"


# ---------- Errors on the PC ----------
EVENTS_PS = r"""[Console]::OutputEncoding=[Text.Encoding]::UTF8
Get-WinEvent -FilterHashtable @{LogName='System','Application'; Level=1,2; StartTime=(Get-Date).AddHours(-HOURS)} `
  -MaxEvents 400 -ErrorAction SilentlyContinue | ForEach-Object {
  $m = "$($_.Message)" -replace '\s+',' '; if ($m.Length -gt 300) { $m = $m.Substring(0,300) }
  [pscustomobject]@{time=$_.TimeCreated.ToString('yyyy-MM-dd HH:mm'); log=$_.LogName; source=$_.ProviderName;
                    id=$_.Id; message=$m} } | ConvertTo-Json -Depth 2"""
CRASH_SOURCES = {"Application Error": "app crash", "Application Hang": "app froze",
                 "Windows Error Reporting": "crash report", "Microsoft-Windows-WER-SystemErrorReporting": "blue screen",
                 "BugCheck": "blue screen", "Microsoft-Windows-Kernel-Power": "unexpected shutdown or restart",
                 "Display": "graphics driver", "nvlddmkm": "NVIDIA driver", "amdkmdag": "AMD driver"}


def summarize_events(events):
    """Group repeated errors so the same one firing 200 times is one line, worst and newest first."""
    groups = {}
    for e in events:
        g = groups.setdefault((e["source"], e["id"]), {"source": e["source"], "id": e["id"], "log": e["log"],
                                                       "count": 0, "first": e["time"], "last": e["time"],
                                                       "example": e["message"]})
        g["count"] += 1
        g["first"], g["last"] = min(g["first"], e["time"]), max(g["last"], e["time"])
        if e["time"] >= g["last"]:
            g["example"] = e["message"]
        if e["source"] in CRASH_SOURCES:
            g["kind"] = CRASH_SOURCES[e["source"]]
    newest = sorted(groups.values(), key=lambda g: g["last"], reverse=True)
    return sorted(newest, key=lambda g: "kind" not in g)[:20]  # crashes first, then newest


def pc_errors(hours=24):
    out = subprocess.run(["powershell", "-NoProfile", "-Command", EVENTS_PS.replace("HOURS", str(float(hours)))],
                         capture_output=True, timeout=60, creationflags=NO_WINDOW).stdout.decode("utf-8", "replace")
    events = json.loads(out) if out.strip() else []
    events = [events] if isinstance(events, dict) else events
    log = features.HERE / "jarvis.log"
    jarvis = [l.strip() for l in log.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
              if any(w in l for w in ("Error", "error", "Exception"))][-10:] if log.exists() else []
    return {"hours": hours, "windows_errors": len(events), "grouped": summarize_events(events),
            "jarvis_log_errors": jarvis}


FUNCS = {f.__name__: f for f in (screenshot, list_projects, add_project, dev_task, dev_status, pc_task, pc_errors)}
S = {"type": "string"}
TOOLS = [
    {"name": "screenshot", "description": "Capture his screen (main monitor, or all_screens) to an image file, then "
     "Read that file to see it. Use for 'what's on my screen', 'read this', 'what does this error mean'.",
     "input_schema": {"type": "object", "properties": {"all_screens": {"type": "boolean"}}}},
    {"name": "list_projects", "description": "His coding projects and their folders.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "add_project", "description": "Register a project folder by name so dev_task can work on it.",
     "input_schema": {"type": "object", "required": ["name", "path"], "properties": {"name": S, "path": S}}},
    {"name": "dev_task", "description": "Hand a coding job (look into, explain, fix or change something) on one of "
     "his projects to a separate coder that works in the background, often for several minutes. Tell him you've "
     "started it; you'll announce the result yourself.",
     "input_schema": {"type": "object", "required": ["project", "request"], "properties": {
         "project": S, "request": {"type": "string", "description": "What he wants, in full, in his words"}}}},
    {"name": "pc_task", "description": "Do anything on his PC that your other tools can't: install or set up "
     "software, find or organise files, fix a Windows problem, research something and write it up, build a small "
     "script... the things he'd ask Claude to do in chat. A full assistant does it in the background with the "
     "shell, files and the web (a safety check blocks risky actions) and you announce the result. Before "
     "repairs that change system settings, drivers or installed software, confirm with him first.",
     "input_schema": {"type": "object", "required": ["request"], "properties": {
         "request": {"type": "string", "description": "The full job, in his words, plus anything you already "
                                                      "know that helps (e.g. the error details from pc_errors)"}}}},
    {"name": "pc_errors", "description": "Recent Windows errors (System and Application logs, crashes, blue "
     "screens, driver resets, unexpected restarts), grouped, plus Jarvis's own recent errors.",
     "input_schema": {"type": "object", "properties": {"hours": {"type": "number", "description": "default 24"}}}},
    {"name": "dev_status", "description": "Recent background jobs (dev and PC) and their results.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}}},
]


def selftest():
    import tempfile
    real, features.HERE = features.HERE, Path(tempfile.mkdtemp())
    try:
        proj = features.HERE / "gunbros"
        proj.mkdir()
        assert "error" in add_project("nowhere", str(features.HERE / "missing"))
        add_project("Gun Bros", str(proj))
        assert "error" in dev_task("tavern", "add fog of war") and "gun bros" in list_projects()
        q = dev_task("gun", "make the shotgun spread wider")
        job = next_job()
        assert job["id"] == q["queued"] and job["status"] == "running" and next_job() is None
        if os.name != "nt":  # a stand-in for Claude Code that ignores its flags
            fake = features.HERE / "fakeclaude"
            fake.write_text('#!/bin/sh\ncat >/dev/null\necho \'{"result": "Widened the spread in weapons.js."}\'\n')
            fake.chmod(0o755)
            said = run_job(job, str(fake))
            assert said == "Sir, the gun bros job is done. Widened the spread in weapons.js.", said
            assert dev_status(job["id"])[0]["status"] == "done"
        ev = [{"time": f"2026-11-05 0{h}:00", "log": "System", "source": "Service Control Manager", "id": 7000,
               "message": f"The X service failed to start ({h})"} for h in range(1, 6)]
        ev += [{"time": "2026-11-05 02:30", "log": "Application", "source": "Application Error", "id": 1000,
                "message": "Faulting application name: League of Legends.exe"}]
        g = summarize_events(ev)
        assert g[0]["kind"] == "app crash" and g[1]["count"] == 5 and g[1]["last"] == "2026-11-05 05:00"
        assert g[1]["example"].endswith("(5)")
        pc = pc_task("install 7-Zip")
        assert next_job()["kind"] == "pc" and dev_status(pc["queued"])[0]["status"] == "running"
    finally:
        shutil.rmtree(features.HERE)
        features.HERE = real
    print("dev helper self-test passed")


if __name__ == "__main__":
    selftest()
