"""A company of agents: one goal, a team that plans, builds and checks its own work, and reports at checkpoints.

"Make a Roblox game with the team" / "make that with the team": the brain passes what was said in the conversation
as the brief, and for something that doesn't exist yet (new=True) a project folder is made in Documents/Jarvis
Projects and added to his projects.
start_company("gun bros", "ship the Gun Bros demo") copies the project to drafts/ (his project isn't touched) and
runs a chain of background jobs there:
1. The planner reads the project and writes the plan: 3 to 6 tasks, each with what "done" means.
2. For each task, the coder does it; then the critic reviews the coder's changes against the task and either
   approves or sends back a list of problems. One round of fixes per task, then it moves on with the problems noted.
3. Every `checkpoint_every` tasks (default 2) Jarvis tells him where it's up to. He can say "stop the company".
4. The team panel ("show the team") shows what the planner, coder and critic are each doing, with a rough completion
   bar each and one for the whole goal. It updates itself while open, as jobs start and finish.
5. At the end he gets the night-shift style panel: a summary and the changed files, to keep (old files backed up)
   or throw away.
The agents read and write code but can't run it, so the critic checks by reading. The PC must stay on.
"""
import datetime
import json
from pathlib import Path

import features

FILE = "company.json"


def _state():
    return features._load(FILE, {})


def _queue(c, role, request):
    import devhelper
    jobs = devhelper._load("dev_jobs.json", [])
    job = {"id": devhelper._next_id(jobs), "project": c["project"], "path": c["draft"], "original": c["original"],
           "company": c["id"], "role": role, "request": features.personal(request), "status": "queued",
           "asked": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    devhelper._save("dev_jobs.json", jobs + [job])


ROBLOX = ("This is a Roblox game: build it as a Rojo project (default.project.json; src/server, src/client and src/shared "
          "with .luau scripts; a README.md saying how to sync it into Roblox Studio with Rojo). No .rbxl files.")


def _new_project(name):
    """A folder for something that doesn't exist yet, added to his projects. -> (key, path)"""
    import devhelper
    import re
    name = re.sub(r"[^\w -]", "", name).strip()[:40] or "New project"
    docs = Path.home() / "Documents"
    folder = (docs if docs.is_dir() else Path.home()) / "Jarvis Projects" / name
    folder.mkdir(parents=True, exist_ok=True)
    devhelper.add_project(name, str(folder))
    return name.lower(), str(folder)


def start_company(project, goal, checkpoint_every=2, brief="", new=False):
    """Put a team of agents on one goal for a project, working on a copy. brief: the details from the conversation."""
    import devhelper
    import nightshift
    key, path = devhelper._project(project)
    if not key and new:
        key, path = _new_project(project)
    if not key:
        return {"error": f"No project called '{project}'. For something new, call again with new=true.",
                "projects": list(devhelper.list_projects())}
    if Path(path).resolve() == features.HERE.resolve():
        return {"error": "Not Jarvis himself: changes to Jarvis are a dev_task with project 'jarvis'."}
    empty = not any(Path(path).iterdir())
    brief = (brief or "").strip()[:4000]
    if "roblox" in f"{project} {goal} {brief}".lower():
        brief = (brief + "\n" + ROBLOX).strip()
    cid = f"{key.replace(' ', '-')}-co-{datetime.datetime.now():%Y%m%d-%H%M}"
    draft = nightshift._drafts() / cid
    try:
        nightshift._copy(path, draft)
    except Exception as e:
        return {"error": str(e)}
    st = _state()
    c = st[cid] = {"id": cid, "project": key, "original": path, "draft": str(draft), "goal": goal, "brief": brief, "tasks": [], "task": 0,
                   "retries": 0, "status": "planning", "every": max(1, int(checkpoint_every)), "log": []}
    features._save(FILE, st)
    _queue(c, "planner", f"You are the planner of a small team working on this project for {{USER}}. The goal: {goal}\n"
           + (f"What he said he wants (from the conversation):\n{brief}\n" if brief else "")
           + ("The folder is empty: this is a brand new project, so the first task sets up its structure. " if empty else "")
           + "Read the project, then write COMPANY_PLAN.json in this folder: {\"tasks\": [{\"title\": \"...\", \"do\": "
           "\"exactly what to change, with file names\", \"done_when\": \"how a reviewer can tell from the code\"}]}. "
           "3 to 6 tasks, in order, each small enough for one sitting. Change nothing else.")
    try:
        features._panel(board(c))  # the team panel, which keeps itself up to date while open
    except Exception:
        pass
    return {"company": cid, "note": "The planner is on it; you'll hear at each checkpoint and get the result to keep or throw away."}


def _code(c, extra=""):
    t = c["tasks"][c["task"]]
    _queue(c, "coder", f"You are the coder on a team working toward: {c['goal']}\nTask {c['task'] + 1} of {len(c['tasks'])}: "
           f"{t['title']}\n{t['do']}\nDone when: {t.get('done_when', '')}\n"
           + (f"What he asked for overall:\n{c['brief']}\n" if c.get("brief") else "") + f"{extra}Do this task only.")


def after_job(job, summary, say):
    try:
        _after(job, summary, say)
    finally:
        refresh(job.get("company"))


def _after(job, summary, say):
    import nightshift
    st = _state()
    c = st.get(job["company"])
    if not c or c["status"] == "stopped":
        return
    draft = Path(c["draft"])
    role = job["role"]
    if role == "planner":
        try:
            c["tasks"] = json.loads((draft / "COMPANY_PLAN.json").read_text(encoding="utf-8"))["tasks"][:6]
            (draft / "COMPANY_PLAN.json").unlink()
            assert c["tasks"]
        except Exception:
            c["status"] = "failed"
            features._save(FILE, st)
            return say(f"The team couldn't plan {c['goal']}, {{TITLE}}: {summary}")
        c["status"] = "working"
        features._save(FILE, st)
        say(f"The team has a plan for {c['goal']}, {{TITLE}}: " + "; ".join(t["title"] for t in c["tasks"]) + ". Starting.")
        return _code(c)
    t = c["tasks"][c["task"]]
    if role == "coder":
        files = ", ".join(p for p, _, _ in nightshift.changes(c["original"], c["draft"]))[:1500]
        features._save(FILE, st)
        return _queue(c, "critic", f"You are the critic on a team working toward: {c['goal']}\nThe coder just did task "
                      f"{c['task'] + 1}: {t['title']}\n{t['do']}\nDone when: {t.get('done_when', '')}\nThe coder said: {summary[:600]}\n"
                      f"Files changed so far: {files}\nRead the changed code critically: bugs, missed cases, things that "
                      "would break the rest of the project, whether it's really done. Do NOT change any code. Write "
                      "COMPANY_REVIEW.json in this folder: {\"verdict\": \"approve\" or \"fix\", \"problems\": [\"...\"]}.")
    try:  # the critic's verdict
        rev = json.loads((draft / "COMPANY_REVIEW.json").read_text(encoding="utf-8"))
        (draft / "COMPANY_REVIEW.json").unlink()
    except Exception:
        rev = {"verdict": "approve", "problems": []}
    if rev.get("verdict") == "fix" and rev.get("problems") and c["retries"] < 1:
        c["retries"] += 1
        features._save(FILE, st)
        return _code(c, "The critic found these problems with your first attempt, fix them:\n- " + "\n- ".join(map(str, rev["problems"][:8])) + "\n")
    c["log"].append({"task": t["title"], "fixed_once": bool(c["retries"]),
                     "open_problems": rev.get("problems", []) if rev.get("verdict") == "fix" else []})
    c["task"] += 1
    c["retries"] = 0
    if c["task"] >= len(c["tasks"]):
        c["status"] = "done"
        features._save(FILE, st)
        left = [p for l in c["log"] for p in l["open_problems"]]
        text = (f"The team finished {c['goal']}: {len(c['tasks'])} tasks, {sum(l['fixed_once'] for l in c['log'])} sent back "
                f"by the critic and fixed." + (f" Still open: {'; '.join(map(str, left))[:300]}" if left else ""))
        return nightshift.after_job({"project": c["project"], "path": c["draft"], "original": c["original"]}, text, say)
    features._save(FILE, st)
    if c["task"] % c["every"] == 0:
        say(f"Checkpoint, {{TITLE}}: the team has done {c['task']} of {len(c['tasks'])} tasks toward {c['goal']}. "
            f"Next: {c['tasks'][c['task']]['title']}.")
    _code(c)


def board(c):
    """The team panel: each member's current work and a rough completion bar (from tasks done and who's on now)."""
    import devhelper
    jobs = [j for j in devhelper._load("dev_jobs.json", []) if j.get("company") == c["id"]]
    cur = jobs[-1] if jobs and jobs[-1]["status"] in ("queued", "running") else {}
    role, on = cur.get("role"), cur.get("status") == "running"
    n, k, tasks = len(c["tasks"]), c["task"], c["tasks"]
    done, title = c["status"] == "done", tasks[k]["title"] if k < n else ""
    wait = "" if on else " (queued)"
    if c["status"] == "planning":
        plan = ("Reading the project and writing the plan" + wait, 50 if on else 10)
    else:
        plan = (f"Planned {n} tasks" if n else "Couldn't make a plan", 100 if n else 0)
    if not n:
        code = crit = ("Waiting for the plan", 0)
    elif done:
        sent = sum(x["fixed_once"] for x in c["log"])
        code, crit = (f"Finished all {n} tasks", 100), (f"Reviewed all {n}, sent {sent} back", 100)
    else:
        part = {"coder": .5 if on else 0, "critic": .9}.get(role, 0)
        code = (f"Task {k + 1}/{n}: {title}" + (" (fixing the critic's notes)" if c["retries"] else "") + wait
                if role == "coder" else f"Waiting on the review of task {k + 1}" if role == "critic" else "Idle",
                (k + part) / n * 100)
        crit = (f"Reviewing task {k + 1}: {title}" + wait if role == "critic" else
                f"Waiting for the coder ({k} approved)", (k + (.5 if role == "critic" and on else 0)) / n * 100)
    steps = 1 + 2 * n
    fin = 100 if done else 5 if not n else (1 + 2 * k + (role == "critic")) / steps * 100
    return {"type": "panel", "kind": "team", "id": c["id"], "title": f"Team: {c['project']}", "goal": c["goal"],
            "status": c["status"], "overall": round(fin), "stay": True,
            "members": [{"name": name, "doing": d, "pct": round(pc), "active": role == r and on}
                        for name, r, (d, pc) in (("Planner", "planner", plan), ("Coder", "coder", code), ("Critic", "critic", crit))],
            "tasks": [{"title": t["title"], "state": "done" if i < k or done else "now" if i == k else "todo"}
                      for i, t in enumerate(tasks)]}


def refresh(cid):
    """Update the team panel if it's open (the HUD ignores it otherwise)."""
    c = _state().get(cid) if cid else None
    if c:
        try:
            features._panel({**board(c), "update": True})
        except Exception:
            pass  # Jarvis isn't running (self-test) or the HUD is closed


def company_status():
    st = _state()
    if not st:
        return {"error": "No team has been started."}
    c = st[sorted(st, key=lambda k: st[k]["id"].rsplit("-co-", 1)[-1])[-1]]
    b = board(c)
    features._panel(b)
    return {"goal": c["goal"], "status": c["status"], "task": c["task"], "of": len(c["tasks"]), "overall_pct": b["overall"],
            "members": [f"{m['name']}: {m['doing']} ({m['pct']}%)" for m in b["members"]]}


def stop_company():
    st = _state()
    for c in st.values():
        if c["status"] in ("planning", "working"):
            c["status"] = "stopped"
    features._save(FILE, st)
    return {"stopped": True, "note": "The job running now finishes, then the team stops. The copy stays in drafts."}


FUNCS = {"start_company": start_company, "company_status": company_status, "stop_company": stop_company}
S = {"type": "string"}
TOOLS = [
    {"name": "start_company", "description": "Put a team of agents (planner, coder, critic) on one big goal for a "
     "project ('get the team to ship the Gun Bros demo'): they plan, build and check each other on a copy, report at "
     "checkpoints, and he keeps or throws away the result. Use it whenever he says 'with the team' or 'get the team "
     "to' ('make a Roblox game with the team', 'make that with the team'). 'That' is what you've been talking about: "
     "put everything relevant from the conversation in brief (the idea, features, style, decisions made, in full "
     "sentences), since the team sees nothing else. project: one of his projects, or for something that doesn't "
     "exist yet a short name for it with new=true (a folder is made in Documents/Jarvis Projects). If it's unclear "
     "what he wants built, ask one question first. For big multi-step goals; one-off changes use dev_task.",
     "input_schema": {"type": "object", "required": ["project", "goal"],
                      "properties": {"project": S, "goal": S, "brief": S, "new": {"type": "boolean"},
                                     "checkpoint_every": {"type": "integer"}}}},
    {"name": "company_status", "description": "Show the team panel ('show the team', 'how's the team going'): what "
     "the planner, coder and critic are each doing, with a rough completion bar each.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "stop_company", "description": "Stop the team.", "input_schema": {"type": "object", "properties": {}}},
]
COMMANDS = {"Projects": ["Get the team to ship my demo", "Show the team"]}


if __name__ == "__main__":
    import tempfile
    import devhelper
    features.HERE = Path(tempfile.mkdtemp())
    proj = Path(tempfile.mkdtemp()) / "game"
    proj.mkdir()
    (proj / "main.lua").write_text("x = 1\n")
    devhelper._load = lambda n, d: json.loads((features.HERE / n).read_text()) if (features.HERE / n).exists() else d
    devhelper._save = lambda n, data: (features.HERE / n).write_text(json.dumps(data))
    devhelper.list_projects = lambda: {"game": str(proj)}
    last = lambda: devhelper._load("dev_jobs.json", [])[-1]
    said, shown = [], []
    features._panel = shown.append
    start_company("game", "ship the demo", 1)
    j = last()
    draft = Path(j["path"])
    assert j["role"] == "planner"
    (draft / "COMPANY_PLAN.json").write_text(json.dumps({"tasks": [{"title": "Add menu", "do": "a", "done_when": "b"},
                                                                    {"title": "Add sound", "do": "c", "done_when": "d"}]}))
    b = board(_state()[j["company"]])
    assert b["members"][0]["pct"] == 10 and b["members"][1]["doing"] == "Waiting for the plan" and b["overall"] == 5
    after_job(j, "planned", said.append)
    b = board(_state()[j["company"]])
    assert b["members"][0]["pct"] == 100 and b["members"][1]["doing"] == "Task 1/2: Add menu (queued)" and b["overall"] == 20
    assert shown[-1]["update"] and shown[-1]["kind"] == "team"  # the open panel was refreshed
    assert last()["role"] == "coder" and "Add menu" in last()["request"] and not (draft / "COMPANY_PLAN.json").exists()
    (draft / "menu.lua").write_text("menu\n")
    after_job(last(), "added menu", said.append)
    assert last()["role"] == "critic" and "menu.lua" in last()["request"]
    b = board(_state()[j["company"]])
    assert b["members"][1]["pct"] == 45 and b["members"][2]["doing"].startswith("Reviewing task 1") and b["overall"] == 40
    (draft / "COMPANY_REVIEW.json").write_text(json.dumps({"verdict": "fix", "problems": ["no back button"]}))
    after_job(last(), "reviewed", said.append)
    assert last()["role"] == "coder" and "no back button" in last()["request"]
    after_job(last(), "fixed", said.append)
    (draft / "COMPANY_REVIEW.json").write_text(json.dumps({"verdict": "approve", "problems": []}))
    after_job(last(), "ok", said.append)
    assert "Checkpoint" in said[-1] and last()["role"] == "coder" and "Add sound" in last()["request"]
    after_job(last(), "sound", said.append)
    after_job(last(), "no review file", said.append)  # critic wrote nothing: approved
    assert _state()[j["company"]]["status"] == "done" and "1 sent back" in said[-1] and "1 files changed" in said[-1]
    keep = [e for e in shown if e.get("actions")][-1]
    assert keep["actions"][0][1].startswith("keep night shift game-co-")
    b = board(_state()[j["company"]])
    assert b["overall"] == 100 and [m["pct"] for m in b["members"]] == [100, 100, 100] and "sent 1 back" in b["members"][2]["doing"]
    assert start_company("space miner", "make it").get("error")  # unknown and not new
    import pathlib
    pathlib.Path.home = staticmethod(lambda: features.HERE)
    added = {}
    devhelper.add_project = lambda n, p: added.update({n.lower(): p})
    devhelper.list_projects = lambda: {"game": str(proj), **added}
    r = start_company("Space Miner", "make a Roblox mining game", brief="Top-down, pets, 4 players.", new=True)
    assert r.get("company", "").startswith("space-miner-co-") and (features.HERE / "Jarvis Projects" / "Space Miner").is_dir()
    q = last()["request"]
    assert "pets, 4 players" in q and "Rojo project" in q and "brand new project" in q
    print("company self-test passed")
