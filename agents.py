"""Agents: a Jarvis for each project ("Gun Bros Jarvis", "Trading Jarvis"), each with its own memory, all aware
of each other, all working in the background so the main Jarvis stays free to talk.

- make_agent(name, project, brief): an agent tied to one of his projects (devhelper's list). Its first job reads
  the whole project and writes its second brain: brain/<agent>.md, an overview of the structure, the main systems
  and where things are. Re-read on "refresh the Gun Bros brain".
- ask_agent(agent, request): queues the request as a background job in that project (code changes or questions);
  it runs alongside anything else, and the answer is said with the agent's name when it's done. Several agents can
  work at once.
- Each job gets: the agent's brief, its second brain, its own notes (the last 20 things it learned, from the
  "NOTE:" lines it ends its answers with), and the board: what every other agent is doing or last did.
- The main Jarvis sees the board in his instructions too, so "what's Gun Bros Jarvis up to?" or "tell the trading
  agent what the Gun Bros one found" just work.
- project_lookup(project, query): the instant part of the second brain, no AI: files, functions and lines in the
  project that match ("where's the damage code?").
"""
import datetime
import json
import re
from pathlib import Path

import features

FILE = "agents.json"
CODE = {".py", ".js", ".ts", ".tsx", ".jsx", ".lua", ".luau", ".cs", ".cpp", ".c", ".h", ".hpp", ".gd", ".java", ".kt",
        ".rs", ".go", ".html", ".css", ".json", ".md", ".txt", ".toml", ".yaml", ".yml", ".rbxmx", ".shader"}
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", "Library", "Temp", "obj", "bin", ".vs",
        "Packages", "Logs"}
SYMBOL = re.compile(r"^\s*(?:(?:local\s+)?function\s+([\w.:]+)|def\s+(\w+)|class\s+(\w+)|(?:export\s+)?(?:async\s+)?"
                    r"function\s+(\w+)|(?:public|private|protected|internal)\s+[\w<>\[\],\s]+?\s(\w+)\s*\()", re.M)


def _load():
    return features._load(FILE, {"agents": {}})


def _save(d):
    features._save(FILE, d)


def _key(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower().replace("jarvis", "").replace("agent", "")).strip("-") or "agent"


def _brain(key):
    p = features.HERE / "brain" / f"{key}.md"
    p.parent.mkdir(exist_ok=True)
    return p


def board(exclude=None):
    """What every agent is doing or last did, one line each."""
    out = []
    for k, a in _load()["agents"].items():
        if k == exclude:
            continue
        doing = f"working on: {a['doing']} (since {a['since'][11:16]})" if a.get("doing") else \
            f"idle; last: {a['last'][:160]}" if a.get("last") else "idle"
        out.append(f"- {a['name']} (project {a['project']}): {doing}")
    return "\n".join(out)


def prompt():
    """For the main Jarvis's instructions."""
    b = board()
    return ("\nYour agents (each works in the background on one project; use ask_agent to give one a task):\n" + b
            if b else "")


# ---------- The project second brain: instant lookups, no AI ----------
def _files(root):
    for f in Path(root).rglob("*"):
        if f.is_file() and f.suffix.lower() in CODE and not any(p in SKIP for p in f.relative_to(root).parts) \
                and f.stat().st_size < 2_000_000:
            yield f


def project_lookup(project, query, limit=25):
    """Where things are in a project: matching file names, functions/classes and lines (no AI, instant)."""
    import devhelper
    key, path = devhelper._project(project)
    if not key:
        return {"error": f"No project called '{project}'", "projects": list(devhelper.list_projects())}
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2 and w not in {"the", "where", "what", "code",
                                                                                     "how", "does", "find", "for", "and"}]
    if not words:
        return {"error": "What should I look for?"}
    files, symbols, lines = [], [], []
    for f in _files(path):
        rel = str(f.relative_to(path)).replace("\\", "/")
        if any(w in rel.lower() for w in words):
            files.append(rel)
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in SYMBOL.finditer(text):
            name = next(g for g in m.groups() if g)
            if any(w in name.lower() for w in words):
                symbols.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1} {name}")
        if len(lines) < limit:
            for i, line in enumerate(text.splitlines(), 1):
                if any(w in line.lower() for w in words):
                    lines.append(f"{rel}:{i}: {line.strip()[:120]}")
                    if len(lines) >= limit:
                        break
    brain = next((_brain(k) for k, a in _load()["agents"].items() if a["project"] == key and _brain(k).exists()), None)
    return {"project": key, "files": files[:limit], "functions": symbols[:limit], "lines": lines[:limit],
            **({"overview": brain.read_text(encoding="utf-8")[:3000]} if brain else {})}


# ---------- Agents ----------
OVERVIEW = """Read this whole project and write its second brain: a file named SECOND_BRAIN.md in this folder, so a
helper can find anything fast later. Include: what the project is, how it's laid out (folders and the important
files), each main system (what it does, which files and functions), how they connect, where the settings and
data are, and anything unfinished or broken you notice. Be concrete: file paths and function names. Up to about
300 lines."""


def make_agent(name, project, brief=""):
    """A Jarvis for one of his projects, with its own memory; it starts by reading the project."""
    import devhelper
    key_p, path = devhelper._project(project)
    if not key_p:
        return {"error": f"No project called '{project}'", "projects": list(devhelper.list_projects())}
    d = _load()
    k = _key(name)
    d["agents"][k] = {"name": f"{name.replace('Jarvis', '').strip()} Jarvis", "project": key_p, "path": path,
                      "brief": brief[:600], "notes": [], "doing": "reading the project", "last": "",
                      "since": datetime.datetime.now().isoformat(timespec="minutes"), "made": datetime.date.today().isoformat()}
    _save(d)
    _queue(k, OVERVIEW, overview=True)
    return {"agent": d["agents"][k]["name"], "note": "It's reading the project now and writing its second brain; give "
            "it tasks any time (they queue up)."}


def _queue(key, request, overview=False):
    import devhelper
    a = _load()["agents"][key]
    brain = _brain(key)
    context = (f"You are {a['name']}, {{USER}}'s helper for the {a['project']} project. "
               + (f"Your brief: {a['brief']}\n" if a["brief"] else "")
               + (f"\nYour second brain (your overview of this project):\n{brain.read_text(encoding='utf-8')[:6000]}\n" if brain.exists() else "")
               + ("\nThings you've learned before:\n" + "\n".join(f"- {n}" for n in a["notes"][-20:]) + "\n" if a["notes"] else "")
               + ("\nWhat the other agents are doing (you may mention it if it matters):\n" + board(key) + "\n" if board(key) else "")
               + "\nEnd your answer with up to 3 lines starting NOTE: for anything worth remembering next time "
               "(decisions, where things are, what's left to do).\n\nThe task: ")
    jobs = devhelper._load("dev_jobs.json", [])
    job = {"id": devhelper._next_id(jobs), "project": a["project"], "path": a["path"], "agent": key, "overview": overview,
           "request": features.personal(context) + request, "status": "queued",
           "asked": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    devhelper._save("dev_jobs.json", jobs + [job])
    return job["id"]


def ask_agent(agent, request):
    """Give an agent a task or a question; it works in the background and answers when done."""
    d = _load()
    k = _key(agent)
    k = k if k in d["agents"] else next((x for x in d["agents"] if k in x or x in k), None)
    if not k:
        return {"error": f"No agent called {agent}.", "agents": [a["name"] for a in d["agents"].values()]}
    a = d["agents"][k]
    a["doing"], a["since"] = request[:120], datetime.datetime.now().isoformat(timespec="minutes")
    _save(d)
    _queue(k, request)
    return {"agent": a["name"], "note": "On it in the background; it'll answer when it's done."}


def after_job(job, summary, say):
    """An agent's job finished: its notes, the board, and the answer said in its name."""
    d = _load()
    a = d["agents"].get(job["agent"])
    if not a:
        return say(summary)
    notes = re.findall(r"^\s*NOTE:\s*(.+)$", summary, re.M)
    text = re.sub(r"^\s*NOTE:.*$", "", summary, flags=re.M).strip()
    a["notes"] = (a["notes"] + [n.strip()[:200] for n in notes])[-40:]
    a["last"], a["doing"] = f"{a.get('doing') or 'a task'}: {text[:200]}", ""
    if job.get("overview"):
        f = Path(job["path"]) / "SECOND_BRAIN.md"
        if f.exists():
            _brain(job["agent"]).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
            f.unlink()  # kept with Jarvis, out of his project
            a["last"] = "read the project and wrote its second brain"
    _save(d)
    say(f"{a['name']}: {text}" if not job.get("overview") else
        f"{a['name']} has read the {a['project']} project and is ready, {{TITLE}}.")


def agents_status():
    """Every agent and what it's doing (a panel)."""
    d = _load()["agents"]
    if not d:
        return {"error": "No agents yet: say 'make a Gun Bros agent for my Gun Bros project'."}
    features._panel({"type": "panel", "kind": "list", "title": "Agents", "stay": True,
                     "items": [{"text": f"{'▶' if a.get('doing') else '·'} {a['name']}",
                                "sub": (f"Working on {a['doing']}" if a.get("doing") else f"Last: {a['last'][:120]}" if a.get("last") else "Idle")
                                + f" · {len(a['notes'])} notes"} for a in d.values()]})
    return {"agents": [{"name": a["name"], "project": a["project"], "doing": a.get("doing"), "last": a.get("last")}
                       for a in d.values()]}


def refresh_brain(agent):
    """Have an agent re-read its project and rewrite its second brain."""
    d = _load()
    k = _key(agent)
    if k not in d["agents"]:
        return {"error": f"No agent called {agent}."}
    d["agents"][k]["doing"] = "re-reading the project"
    _save(d)
    _queue(k, OVERVIEW, overview=True)
    return {"refreshing": d["agents"][k]["name"]}


def remove_agent(agent):
    d = _load()
    k = _key(agent)
    if d["agents"].pop(k, None) is None:
        return {"error": f"No agent called {agent}."}
    _save(d)
    return {"removed": k}


def find_agent(name):
    """The agent's key for a spoken name, or None (quick commands: "Gun Bros Jarvis, ...")."""
    d, k = _load()["agents"], _key(name)
    return k if k in d else None


FUNCS = {f.__name__: f for f in (make_agent, ask_agent, agents_status, refresh_brain, remove_agent, project_lookup,
                                 find_agent)}
S = {"type": "string"}
TOOLS = [
    {"name": "make_agent", "description": "Make a project agent ('make a Gun Bros agent'): a Jarvis for one of his "
     "projects with its own memory; it reads the whole project first. project: from list_projects (add_project first "
     "if it's new). brief: what it should focus on, if he says.", "input_schema": {"type": "object",
     "required": ["name", "project"], "properties": {"name": S, "project": S, "brief": S}}},
    {"name": "ask_agent", "description": "Give a project agent a task or question ('Gun Bros Jarvis, add a reload "
     "system', 'ask the trading agent ...'). It runs in the background; you stay free, and its answer is said in its "
     "name when done.", "input_schema": {"type": "object", "required": ["agent", "request"],
                                         "properties": {"agent": S, "request": S}}},
    {"name": "agents_status", "description": "What every agent is doing ('what are my agents up to').",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "refresh_brain", "description": "Have an agent re-read its project (after big changes).",
     "input_schema": {"type": "object", "required": ["agent"], "properties": {"agent": S}}},
    {"name": "remove_agent", "description": "Remove an agent (only when he asks).",
     "input_schema": {"type": "object", "required": ["agent"], "properties": {"agent": S}}},
    {"name": "project_lookup", "description": "Instantly find where something is in one of his projects ('where's the "
     "damage code in Gun Bros?'): matching files, functions and lines, plus its agent's overview. No AI, no waiting.",
     "input_schema": {"type": "object", "required": ["project", "query"], "properties": {"project": S, "query": S}}},
]
COMMANDS = {"Agents": ["Make a Gun Bros agent", "Gun Bros Jarvis, add a reload system", "What are my agents up to?"]}


if __name__ == "__main__":
    import tempfile
    import devhelper
    features.HERE = Path(tempfile.mkdtemp())
    proj = Path(tempfile.mkdtemp()) / "gunbros"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "combat.lua").write_text("local function applyDamage(target, amount)\n  target.hp -= amount\nend\n")
    (proj / "src" / "ui.js").write_text("function drawHud() {}\n")
    (proj / "node_modules").mkdir()
    (proj / "node_modules" / "x.js").write_text("function applyDamage(){}")
    devhelper._load = lambda n, d: json.loads((features.HERE / n).read_text()) if (features.HERE / n).exists() else d
    devhelper._save = lambda n, data: (features.HERE / n).write_text(json.dumps(data))
    devhelper.list_projects = lambda: {"gun bros": str(proj), "trading": str(proj)}
    r = project_lookup("gun bros", "where's the damage code?")
    assert r["files"] == [] and r["functions"] == ["src/combat.lua:1 applyDamage"] and len(r["lines"]) == 1, r
    assert make_agent("Gun Bros", "gun bros")["agent"] == "Gun Bros Jarvis"
    make_agent("Trading Jarvis", "trading", "watch my strategy")
    jobs = devhelper._load("dev_jobs.json", [])
    assert jobs[0]["overview"] and jobs[0]["agent"] == "gun-bros" and "SECOND_BRAIN.md" in jobs[0]["request"]
    (proj / "SECOND_BRAIN.md").write_text("Combat lives in src/combat.lua.")
    said = []
    after_job(jobs[0], "Done reading.", said.append)
    assert "is ready" in said[-1] and _brain("gun-bros").read_text().startswith("Combat")
    assert not (proj / "SECOND_BRAIN.md").exists()
    assert ask_agent("gun bros jarvis", "add a reload system")["agent"] == "Gun Bros Jarvis"
    job = devhelper._load("dev_jobs.json", [])[-1]
    assert "Combat lives" in job["request"] and "Trading Jarvis" in job["request"] and "add a reload" in job["request"]
    assert "working on: add a reload system" in prompt()
    after_job(job, "Added reload in src/combat.lua.\nNOTE: reload is in combat.lua\nNOTE: ammo UI still todo", said.append)
    a = _load()["agents"]["gun-bros"]
    assert said[-1] == "Gun Bros Jarvis: Added reload in src/combat.lua." and a["notes"] == ["reload is in combat.lua", "ammo UI still todo"]
    assert "idle; last: add a reload system" in board()
    assert project_lookup("gun bros", "combat")["overview"].startswith("Combat")
    print("agents self-test passed")
