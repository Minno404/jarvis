"""A company of agents: one goal, a team that plans, builds and checks its own work, and reports at checkpoints.

start_company("gun bros", "ship the Gun Bros demo") copies the project to drafts/ (his project isn't touched) and
runs a chain of background jobs there:
1. The planner reads the project and writes the plan: 3 to 6 tasks, each with what "done" means.
2. For each task, the coder does it; then the critic reviews the coder's changes against the task and either
   approves or sends back a list of problems. One round of fixes per task, then it moves on with the problems noted.
3. Every `checkpoint_every` tasks (default 2) Jarvis tells him where it's up to. He can say "stop the company".
4. At the end he gets the night-shift style panel: a summary and the changed files, to keep (old files backed up)
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


def start_company(project, goal, checkpoint_every=2):
    """Put a team of agents on one goal for a project, working on a copy."""
    import devhelper
    import nightshift
    key, path = devhelper._project(project)
    if not key:
        return {"error": f"No project called '{project}'", "projects": list(devhelper.list_projects())}
    cid = f"{key.replace(' ', '-')}-co-{datetime.datetime.now():%Y%m%d-%H%M}"
    draft = nightshift._drafts() / cid
    try:
        nightshift._copy(path, draft)
    except Exception as e:
        return {"error": str(e)}
    st = _state()
    c = st[cid] = {"id": cid, "project": key, "original": path, "draft": str(draft), "goal": goal, "tasks": [], "task": 0,
                   "retries": 0, "status": "planning", "every": max(1, int(checkpoint_every)), "log": []}
    features._save(FILE, st)
    _queue(c, "planner", f"You are the planner of a small team working on this project for {{USER}}. The goal: {goal}\n"
           "Read the project, then write COMPANY_PLAN.json in this folder: {\"tasks\": [{\"title\": \"...\", \"do\": "
           "\"exactly what to change, with file names\", \"done_when\": \"how a reviewer can tell from the code\"}]}. "
           "3 to 6 tasks, in order, each small enough for one sitting. Change nothing else.")
    return {"company": cid, "note": "The planner is on it; you'll hear at each checkpoint and get the result to keep or throw away."}


def _code(c, extra=""):
    t = c["tasks"][c["task"]]
    _queue(c, "coder", f"You are the coder on a team working toward: {c['goal']}\nTask {c['task'] + 1} of {len(c['tasks'])}: "
           f"{t['title']}\n{t['do']}\nDone when: {t.get('done_when', '')}\n{extra}Do this task only.")


def after_job(job, summary, say):
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


def company_status():
    st = _state()
    if not st:
        return {"error": "No team has been started."}
    c = st[sorted(st)[-1]]
    features._panel({"type": "panel", "kind": "list", "title": f"Team: {c['goal'][:40]}", "stay": True,
                     "items": [{"text": f"{'✓' if i < c['task'] else '▶' if i == c['task'] else '·'} {t['title']}",
                                "sub": t.get("done_when", "")[:120]} for i, t in enumerate(c["tasks"])] or [{"text": "Planning...", "sub": ""}],
                     "note": c["status"]})
    return {"goal": c["goal"], "status": c["status"], "task": c["task"], "of": len(c["tasks"])}


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
     "checkpoints, and he keeps or throws away the result. For big multi-step goals; one-off changes use dev_task.",
     "input_schema": {"type": "object", "required": ["project", "goal"],
                      "properties": {"project": S, "goal": S, "checkpoint_every": {"type": "integer"}}}},
    {"name": "company_status", "description": "Where the team is up to.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "stop_company", "description": "Stop the team.", "input_schema": {"type": "object", "properties": {}}},
]
COMMANDS = {"Projects": ["Get the team to ship my demo", "How's the team going?"]}


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
    after_job(j, "planned", said.append)
    assert last()["role"] == "coder" and "Add menu" in last()["request"] and not (draft / "COMPANY_PLAN.json").exists()
    (draft / "menu.lua").write_text("menu\n")
    after_job(last(), "added menu", said.append)
    assert last()["role"] == "critic" and "menu.lua" in last()["request"]
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
    assert shown[-1]["actions"][0][1].startswith("keep night shift game-co-")
    print("company self-test passed")
