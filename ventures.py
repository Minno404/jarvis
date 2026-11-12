"""Ventures: Jarvis researches ways for {USER} to make money online, gives his honest view, and then works on the
one {USER} picks.

1. "Find me ways to make money online" (optionally a focus: "with Roblox games", a budget, hours a week): a
   background research job (web search and reading, no shell) studies real options against what Jarvis knows about
   him (his memories: skills, job, time), and writes ventures/<id>/report.json: each option's realistic monthly
   income (low / typical / high, with sources), start-up cost, hours, time to the first dollar, risks, what Jarvis
   can do and what only he can do, and a score. Scams, gambling, get-rich-quick schemes and anything against a
   platform's rules are left out. A panel shows the options and Jarvis's pick, with a "Start this" button each.
2. "Start this" makes a step-by-step plan (another research job: e.g. for a Roblox game, study the best-performing
   games in the genre first, then design, build, test, publish, promote) and works through it: research steps
   and build steps (code in ventures/<id>/build, the way his dev jobs work) run in the background one after
   another; steps only he can do (accounts, money, publishing, posting) stop and wait for him: "done with that
   step" carries on. "Venture status" shows where it's up to.
Jarvis never spends money, signs up for anything or publishes in his name. Earnings figures are estimates from
public sources, not promises.
"""
import datetime
import json
import re

import features

ROOT = "ventures"
STATE = "ventures.json"

FIND = """Research the best ways for {USER} to make money online{focus}.{extra}
What Jarvis knows about him (fit the options to this: his skills, his job and free time, where he lives):
{about}

Find 6 to 8 real options, then pick the best one for him. Leave out scams, MLM, gambling, "passive income" hype,
anything against a platform's rules, and anything needing a big up-front spend. For each option, use real numbers
from real sources (platform payout rules like Roblox's DevEx rate, earnings reports, marketplace data, creator
interviews) and give the typical result, not the best case.
Write report.json in this folder, exactly this shape:
{{"options": [{{"id": "short-slug", "name": "...", "what": "one sentence", "why_him": "why it fits him",
  "startup_cost_aud": number, "hours_per_week": number, "time_to_first_dollar": "e.g. 2-3 months",
  "monthly_aud": {{"low": n, "typical": n, "high": n}}, "evidence": [{{"claim": "...", "source": "url"}}],
  "risks": ["..."], "jarvis_can_do": ["research, code, art briefs..."], "he_must_do": ["accounts, publishing..."],
  "score": 0-100}}],
 "pick": "id of the best option", "thoughts": "Jarvis's honest view in 3-5 sentences: the pick, why, the catch"}}"""

PLAN = """{USER} chose this way to make money: {name}: {what}
Option details: {option}
What Jarvis knows about him: {about}

Make a practical step-by-step launch plan. Start with market research where it matters (for a game: study the
best-performing games in the genre, what makes them earn, what players complain about, then pick an angle).
Each step is done by one of:
- "research": Jarvis researches on the web and writes findings to a file in this folder
- "build": Jarvis writes code or content in the build folder (no running programs; e.g. a Roblox game as Rojo
  project files with Luau scripts, a website, a design document)
- "you": only {USER} can do it (make accounts, spend money, publish, upload, post, test in Roblox Studio)
Write plan.json in this folder: {{"steps": [{{"title": "...", "who": "research|build|you", "do": "exactly what to
do, detailed enough to act on", "done_when": "how to tell it's done"}}], "first_money": "when and how the first
dollar should come"}}. 6 to 14 steps."""


def _dir(vid):
    d = features.HERE / ROOT / vid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state():
    return features._load(STATE, {"searches": {}, "ventures": {}})


def _queue(kind, path, request, **tag):
    import devhelper
    jobs = devhelper._load("dev_jobs.json", [])
    job = {"id": devhelper._next_id(jobs), "kind": kind, "project": tag.get("label", "venture"), "path": str(path),
           "request": request, "status": "queued", "asked": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), **tag}
    devhelper._save("dev_jobs.json", jobs + [job])
    return job["id"]


def _about():
    try:
        return features.memory_prompt().strip()[:3000] or "(nothing remembered yet)"
    except Exception:
        return "(nothing remembered yet)"


def find_ventures(focus="", budget="", hours=""):
    """Research ways for him to make money online (background, about 5-15 minutes)."""
    sid = datetime.datetime.now().strftime("find-%Y%m%d-%H%M")
    extra = "".join(x for x in (f" Budget to start: {budget}." if budget else "",
                                f" Time he has: {hours} hours a week." if hours else ""))
    req = features.personal(FIND).format(focus=f", focused on {focus}" if focus else "", extra=extra, about=_about())
    st = _state()
    st["searches"][sid] = {"focus": focus, "asked": datetime.datetime.now().isoformat(timespec="minutes")}
    features._save(STATE, st)
    _queue("research", _dir(sid), req, venture_find=sid, label="money research")
    return {"researching": sid, "note": "Researching in the background; I'll show you the options and my pick when done."}


def show_options(sid=None):
    """The last money research: options, numbers and Jarvis's pick, with a Start button each."""
    st = _state()
    sid = sid or (sorted(st["searches"]) or [None])[-1]
    if not sid:
        return {"error": "I haven't researched any yet: say 'find me ways to make money online'."}
    try:
        rep = json.loads((_dir(sid) / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": "That research didn't produce a report (it may still be running)."}
    opts = sorted(rep.get("options", []), key=lambda o: -float(o.get("score") or 0))
    features._panel({"type": "panel", "kind": "ventures", "title": "Ways to make money", "stay": True, "search": sid,
                     "options": opts, "pick": rep.get("pick"), "thoughts": rep.get("thoughts", ""),
                     "actions": [[f"Start: {o['name'][:28]}", f"start venture {sid} {o['id']}"] for o in opts[:3]]})
    return {"pick": rep.get("pick"), "thoughts": rep.get("thoughts"), "options": [o["name"] for o in opts]}


def start_venture(search, option):
    """He picked an option: plan it (background research), then work through the plan."""
    try:
        rep = json.loads((_dir(search) / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": "I can't find that research."}
    opt = next((o for o in rep.get("options", []) if o.get("id") == option), None)
    if not opt:
        return {"error": "That option isn't in the research.", "options": [o.get("id") for o in rep.get("options", [])]}
    vid = re.sub(r"[^a-z0-9-]", "", option.lower())[:30] or "venture"
    st = _state()
    st["ventures"][vid] = {"name": opt["name"], "option": opt, "status": "planning", "steps": [], "step": 0,
                           "started": datetime.datetime.now().isoformat(timespec="minutes")}
    features._save(STATE, st)
    req = features.personal(PLAN).format(name=opt["name"], what=opt.get("what", ""), option=json.dumps(opt)[:4000],
                                         about=_about())
    _queue("research", _dir(vid), req, venture=vid, venture_step="plan", label=f"{opt['name']} plan")
    return {"started": vid, "note": "Planning it now; I'll show you the plan and start on my steps."}


def _next(vid, say):
    """Run the venture's next step: queue Jarvis's, or stop and ask him for his."""
    st = _state()
    v = st["ventures"][vid]
    if v["step"] >= len(v["steps"]):
        v["status"] = "plan done"
        features._save(STATE, st)
        say(f"Every step of {v['name']} is done, {{TITLE}}. {v.get('first_money', '')}")
        return
    s = v["steps"][v["step"]]
    if s["who"] == "you":
        v["status"] = "waiting for you"
        features._save(STATE, st)
        say(f"{v['name']}: your turn, {{TITLE}}. {s['title']}: {s['do']} Say 'done with that step' when it's done.")
        try:
            import alerts
            alerts.notify(f"{s['title']}: {s['do']}", f"{v['name']}: your step", tags="point_right")
        except Exception:
            pass
        return
    v["status"] = f"working: {s['title']}"
    features._save(STATE, st)
    build = _dir(vid) / "build"
    build.mkdir(exist_ok=True)
    notes = "\n".join(f"- {p.name}" for p in sorted(_dir(vid).glob("*.md")))
    req = (f"Venture: {v['name']}. Step {v['step'] + 1} of {len(v['steps'])}: {s['title']}.\n{s['do']}\nDone when: "
           f"{s.get('done_when', '')}\nEarlier findings are in the venture folder ({_dir(vid)}): {notes or 'none yet'}. "
           + ("Write your findings to a .md file there." if s["who"] == "research" else
              "Read the findings you need there, and write the work in this build folder."))
    if s["who"] == "build":
        _queue("dev", build, req, venture=vid, venture_step=v["step"], label=f"{v['name']} build")
    else:
        _queue("research", _dir(vid), req, venture=vid, venture_step=v["step"], label=f"{v['name']} research")


def after_job(job, summary, say):
    """A venture job finished (called by the job runner)."""
    if job.get("venture_find"):
        say(f"I've finished researching ways to make money, {{TITLE}}. {summary.split('. ', 1)[0]}.")
        show_options(job["venture_find"])
        return
    vid = job["venture"]
    st = _state()
    v = st["ventures"].get(vid)
    if not v or v["status"] == "stopped":
        return
    if job.get("venture_step") == "plan":
        try:
            plan = json.loads((_dir(vid) / "plan.json").read_text(encoding="utf-8"))
            v["steps"] = [s for s in plan["steps"] if s.get("who") in ("research", "build", "you")]
            v["first_money"] = plan.get("first_money", "")
        except (OSError, ValueError, KeyError):
            v["status"] = "planning failed"
            features._save(STATE, st)
            say(f"I couldn't make a plan for {v['name']}, {{TITLE}}: {summary}")
            return
        features._save(STATE, st)
        venture_status(vid)
        say(f"The plan for {v['name']} is ready, {{TITLE}}: {len(v['steps'])} steps. Starting on the first.")
    else:
        v["steps"][v["step"]]["result"] = summary[:400]
        v["step"] += 1
        features._save(STATE, st)
        say(f"{v['name']}: done {v['steps'][v['step'] - 1]['title']}. {summary.split('. ', 1)[0]}.")
    _next(vid, say)


def step_done(venture=None, note=""):
    """He finished his step: carry on with the plan."""
    import server_bridge
    st = _state()
    vid = venture or next((k for k, v in st["ventures"].items() if v["status"] == "waiting for you"), None)
    v = st["ventures"].get(vid or "")
    if not v or v["status"] != "waiting for you":
        return {"error": "No venture is waiting on you."}
    v["steps"][v["step"]]["result"] = note or "done"
    v["step"] += 1
    features._save(STATE, st)
    _next(vid, server_bridge.say)
    return {"next": v["steps"][v["step"]]["title"] if v["step"] < len(v["steps"]) else "finished"}


def venture_status(venture=None):
    """Where his ventures are up to (a panel of the steps)."""
    st = _state()
    vs = st["ventures"]
    if not vs:
        return {"error": "No ventures yet: say 'find me ways to make money online'."}
    vid = venture if venture in vs else sorted(vs, key=lambda k: vs[k]["started"])[-1]
    v = vs[vid]
    icon = lambda i, s: "✓" if i < v["step"] else "▶" if i == v["step"] else "·"
    features._panel({"type": "panel", "kind": "list", "title": f"Venture: {v['name']}", "stay": True,
                     "items": [{"text": f"{icon(i, s)} {s['title']}", "sub": ("YOU · " if s["who"] == "you" else "")
                                + (s.get("result") or s.get("done_when", ""))[:140]} for i, s in enumerate(v["steps"])],
                     "note": f"{v['status']} · {v.get('first_money', '')}"})
    return {"venture": v["name"], "status": v["status"], "step": v["step"], "of": len(v["steps"])}


def stop_venture(venture):
    st = _state()
    if venture not in st["ventures"]:
        return {"error": "No such venture.", "ventures": list(st["ventures"])}
    st["ventures"][venture]["status"] = "stopped"
    features._save(STATE, st)
    return {"stopped": venture}


FUNCS = {"find_ventures": find_ventures, "money_options": show_options, "start_venture": start_venture,
         "venture_step_done": step_done, "venture_status": venture_status, "stop_venture": stop_venture}
S = {"type": "string"}
TOOLS = [
    {"name": "find_ventures", "description": "Research ways for him to make money online ('find me ways to make money "
     "online', 'how could I make money with Roblox games'): a background job studies real options with real numbers and "
     "sources, fitted to him, then shows them with your pick. focus / budget / hours: only if he says.",
     "input_schema": {"type": "object", "properties": {"focus": S, "budget": S, "hours": S}}},
    {"name": "money_options", "description": "Show the last money research's options and your pick again.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "start_venture", "description": "He picked an option to go for: plan it and start working through the "
     "plan. search and option are the ids from the money options panel.", "input_schema": {"type": "object",
     "required": ["search", "option"], "properties": {"search": S, "option": S}}},
    {"name": "venture_step_done", "description": "He finished the step a venture was waiting on him for: carry on.",
     "input_schema": {"type": "object", "properties": {"venture": S, "note": S}}},
    {"name": "venture_status", "description": "Where his money ventures are up to.",
     "input_schema": {"type": "object", "properties": {"venture": S}}},
    {"name": "stop_venture", "description": "Stop working on a venture.",
     "input_schema": {"type": "object", "required": ["venture"], "properties": {"venture": S}}},
]
COMMANDS = {"Make money": ["Find me ways to make money online", "Venture status", "Done with that step"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    import devhelper
    features.HERE = Path(tempfile.mkdtemp())
    devhelper._load = lambda n, d: json.loads((features.HERE / n).read_text()) if (features.HERE / n).exists() else d
    devhelper._save = lambda n, data: (features.HERE / n).write_text(json.dumps(data))
    jobs = lambda: devhelper._load("dev_jobs.json", [])
    shown, said = [], []
    features._panel = shown.append
    r = find_ventures("Roblox games")
    j = jobs()[-1]
    assert j["kind"] == "research" and "Roblox games" in j["request"] and j["venture_find"] == r["researching"]
    (_dir(r["researching"]) / "report.json").write_text(json.dumps({"options": [
        {"id": "roblox-obby", "name": "Roblox obby game", "what": "x", "score": 80},
        {"id": "fiverr", "name": "Fiverr gigs", "what": "y", "score": 60}], "pick": "roblox-obby", "thoughts": "Go Roblox."}))
    after_job(j, "Found 2 options. More.", said.append)
    assert shown[-1]["kind"] == "ventures" and shown[-1]["actions"][0][1] == f"start venture {r['researching']} roblox-obby"
    assert start_venture(r["researching"], "roblox-obby")["started"] == "roblox-obby"
    pj = jobs()[-1]
    assert pj["venture_step"] == "plan" and "Roblox obby game" in pj["request"]
    (_dir("roblox-obby") / "plan.json").write_text(json.dumps({"steps": [
        {"title": "Study top obbies", "who": "research", "do": "look", "done_when": "notes"},
        {"title": "Build the obby", "who": "build", "do": "code it", "done_when": "files"},
        {"title": "Publish it", "who": "you", "do": "upload in Studio", "done_when": "live"}], "first_money": "In a month."}))
    after_job(pj, "Planned.", said.append)
    assert jobs()[-1]["kind"] == "research" and jobs()[-1]["venture_step"] == 0
    after_job(jobs()[-1], "Top obbies earn from passes.", said.append)
    bj = jobs()[-1]
    assert bj["kind"] == "dev" and bj["path"].endswith("build") and "Study top obbies" not in bj["request"]
    import alerts
    alerts.notify = lambda *a, **k: None
    after_job(bj, "Built it.", said.append)
    assert "your turn" in said[-1] and _state()["ventures"]["roblox-obby"]["status"] == "waiting for you"
    import server_bridge
    server_bridge.say = said.append
    assert step_done()["next"] == "finished" and "Every step" in said[-1]
    assert venture_status()["status"] == "plan done"
    print("ventures self-test passed")
