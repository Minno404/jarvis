"""Jarvis teaching himself new skills: "Jarvis, learn to check my car rego".

1. learn_skill(request) queues a coding job (devhelper's background jobs) that writes ONE add-on file, the way
   CUSTOM.md describes: custom/_staging/<name>/<name>.py with FUNCS, TOOLS and a self-test. The job can only read
   and write in that folder; it can't run anything.
2. When the job finishes, Jarvis checks the file without loading it into himself: it must compile, and its
   self-test (run in a separate Python with a 60-second limit) must pass. Anything risky in it (deleting files,
   running programs, sending things over the internet) is listed as a warning.
3. A panel shows what it does, its tools, the check results, the warnings and the code, with Install and Discard.
4. Install (only when he presses it, or says "install the skill <name>") moves it into custom/, where it loads
   now and on every start. Skills he no longer wants: "remove the skill <name>" moves it back out.
"""
import ast
import datetime
import re
import shutil
import subprocess
import sys

import features

STAGING = "custom/_staging"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REGISTER = None  # set by server.py: REGISTER(module) adds its tools to Jarvis now

PROMPT = """Write ONE new Jarvis add-on skill in this folder, in a single file named {name}.py, so Jarvis can do this:
{request}

Rules (CUSTOM.md in this folder has the full guide):
- The file defines FUNCS (a dict of name -> function) and TOOLS (a list of tool definitions: name, description,
  input_schema), exactly like Jarvis's built-in modules. Tool names start with "{name}_". Functions take keyword
  arguments and return a dict (an "error" key when something's wrong). Optional: COMMANDS = {{"Skills": ["example phrase"]}}.
- Python standard library only (urllib for the web), plus "import features" for features.settings(),
  features._load(name, default) / features._save(name, data) for small JSON files, and features._panel({{...}})
  to show a panel (kind "list" with items [{{"text", "sub"}}], or kind "stats" with rows [[label, value]]).
- Never delete files, never run other programs, never touch anything outside this add-on's own JSON files, no
  passwords or keys in the code (if a website needs a key, read it from features.settings()["{name}_key"] and say so
  in the tool's description).
- End with: if __name__ == "__main__": a short self-test with asserts that needs no internet (fake the web part).
  Start it with: import tempfile, pathlib; features.HERE = pathlib.Path(tempfile.mkdtemp())  (so it never touches his
  real files). Finish it with print("{name} self-test passed").
- You can't run anything: write it carefully. Finish with 2 plain sentences on what the skill does and how to use it.
"""
RISKY = {"os.remove": "deletes files", "os.unlink": "deletes files", "unlink(": "deletes files", "rmtree": "deletes folders",
         "subprocess": "runs programs", "os.system": "runs programs", "Popen": "runs programs", "eval(": "runs code it builds",
         "exec(": "runs code it builds", "smtplib": "sends email", "socket": "opens network connections",
         "ctypes": "calls Windows directly", "winreg": "changes the Windows registry", "__import__": "imports by name"}


def _slug(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    stop = {"to", "my", "the", "a", "an", "and", "for", "of", "how", "learn", "check", "can", "you", "me", "i"}
    return ("_".join([w for w in words if w not in stop][:3]) or "skill")[:30]


def _dir(name):
    return features.HERE / STAGING / name


def learn_skill(request, name=None):
    """Teach Jarvis a new skill: a coding job writes it in the background; he reviews and installs it."""
    import devhelper
    name = _slug(name or request)
    d = _dir(name)
    d.mkdir(parents=True, exist_ok=True)
    guide = features.HERE / "CUSTOM.md"
    if guide.exists():
        shutil.copy(guide, d / "CUSTOM.md")
    jobs = devhelper._load("dev_jobs.json", [])
    job = {"id": devhelper._next_id(jobs), "project": f"skill {name}", "path": str(d), "skill": name,
           "request": features.personal(PROMPT).format(name=name, request=request), "status": "queued",
           "asked": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    devhelper._save("dev_jobs.json", jobs + [job])
    return {"learning": name, "note": "Writing it in the background; I'll show it to you to check before it's installed."}


def check(name):
    """Compile it, run its self-test in a separate Python, and list anything risky. Never imports it here."""
    f = _dir(name) / f"{name}.py"
    if not f.exists():
        return {"ok": False, "problems": ["The job didn't write the file."]}
    code = f.read_text(encoding="utf-8")
    out = {"code": code, "lines": code.count("\n") + 1, "warnings": sorted({v for k, v in RISKY.items() if k in code}),
           "problems": [], "tools": []}
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        out["problems"].append(f"It doesn't compile: {e}")
        out["ok"] = False
        return out
    for node in ast.walk(tree):  # the tool names, read from the code without running it
        if isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            if "name" in keys and "description" in keys:
                v = node.values[keys.index("name")]
                if isinstance(v, ast.Constant):
                    out["tools"].append(v.value)
    if "FUNCS" not in code or "TOOLS" not in code:
        out["problems"].append("It has no FUNCS / TOOLS, so Jarvis couldn't use it.")
    try:
        import os
        here = os.path.dirname(os.path.abspath(features.__file__))
        run = (f"import sys, runpy; sys.path[:0] = [{str(f.parent)!r}, {here!r}]; "  # (Jarvis's own Python ignores PYTHONPATH)
               f"runpy.run_path({f.name!r}, run_name='__main__')")
        r = subprocess.run([sys.executable, "-c", run], cwd=f.parent, capture_output=True, text=True, timeout=60,
                           creationflags=NO_WINDOW)
        out["test"] = (r.stdout + r.stderr).strip()[-600:]
        if r.returncode:
            out["problems"].append("Its self-test failed.")
    except subprocess.TimeoutExpired:
        out["problems"].append("Its self-test ran over 60 seconds.")
    out["ok"] = not out["problems"]
    return out


def after_job(job, summary, say):
    """Called when a skill's coding job finishes: check it and show it for his OK."""
    name = job["skill"]
    c = check(name)
    features._panel({"type": "panel", "kind": "skill", "title": f"New skill: {name.replace('_', ' ')}", "stay": True,
                     "name": name, "summary": summary, **{k: c.get(k) for k in ("ok", "tools", "warnings", "problems",
                                                                                 "test", "lines", "code")},
                     "actions": ([["Install", f"install the skill {name}"]] if c["ok"] else [])
                     + [["Discard", f"discard the skill {name}"]] + ([] if c["ok"] else [["Try again", f"retry the skill {name}"]])})
    say(f"I've learned a new skill, {{TITLE}}: {name.replace('_', ' ')}. Have a look before I install it." if c["ok"] else
        f"My new skill {name.replace('_', ' ')} didn't pass its checks, {{TITLE}}: {c['problems'][0]}")


def install_skill(name):
    """Install a checked skill: it moves into custom/ and works straight away."""
    name = _slug(name)
    c = check(name)
    if not c["ok"]:
        return {"error": "It hasn't passed its checks: " + "; ".join(c["problems"])}
    dest = features.HERE / "custom" / f"{name}.py"
    if dest.exists():
        return {"error": f"A custom add-on called {name}.py is already installed."}
    shutil.move(str(_dir(name) / f"{name}.py"), dest)
    shutil.rmtree(_dir(name), ignore_errors=True)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"custom_{name}", dest)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        if REGISTER:
            REGISTER(m)
    except Exception as e:
        return {"installed": name, "note": f"Installed, but it failed to load ({e}); it'll try again after a restart."}
    return {"installed": name, "tools": c["tools"], "note": "Ready to use now."}


def discard_skill(name):
    shutil.rmtree(_dir(_slug(name)), ignore_errors=True)
    return {"discarded": _slug(name)}


def retry_skill(name):
    import devhelper
    name = _slug(name)
    job = next((j for j in reversed(devhelper._load("dev_jobs.json", [])) if j.get("skill") == name), None)
    if not job:
        return {"error": "I don't have that skill's request any more: ask me to learn it again."}
    req = job["request"].split("so Jarvis can do this:\n", 1)[-1].split("\n\nRules", 1)[0]
    c = check(name)
    return learn_skill(req + ("\n\nThe last attempt had these problems, fix them: " + "; ".join(c.get("problems", []))
                              + "\nIts test output: " + str(c.get("test", ""))[-300:]), name)


def remove_skill(name):
    """Uninstall a learned skill (moved back to custom/_staging; gone from Jarvis after a restart)."""
    name = _slug(name)
    f = features.HERE / "custom" / f"{name}.py"
    if not f.exists():
        return {"error": f"No installed skill called {name}."}
    _dir(name).mkdir(parents=True, exist_ok=True)
    shutil.move(str(f), _dir(name) / f"{name}.py")
    return {"removed": name, "note": "Gone after the next restart."}


def skills():
    """Skills being learned or waiting for his OK, and the ones installed."""
    staged = sorted(p.name for p in (features.HERE / STAGING).glob("*") if p.is_dir()) if (features.HERE / STAGING).exists() else []
    return {"waiting": staged, "installed": sorted(p.stem for p in (features.HERE / "custom").glob("*.py"))
            if (features.HERE / "custom").exists() else []}


FUNCS = {"learn_skill": learn_skill, "install_skill": install_skill, "discard_skill": discard_skill,
         "retry_skill": retry_skill, "remove_skill": remove_skill, "list_skills": skills}
S = {"type": "string"}
TOOLS = [
    {"name": "learn_skill", "description": "Teach yourself a new skill he asks for that no tool covers ('learn to check "
     "my car rego', 'learn to track fuel prices'): a background job writes a small add-on; you'll show it to him to "
     "check and install. request: what the skill should do, in detail; name: optional short name.",
     "input_schema": {"type": "object", "required": ["request"], "properties": {"request": S, "name": S}}},
    {"name": "install_skill", "description": "Install a learned skill ONLY when he says so (or presses Install).",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S}}},
    {"name": "discard_skill", "description": "Throw away a learned skill waiting for his OK.",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S}}},
    {"name": "retry_skill", "description": "Have another go at a learned skill that failed its checks.",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S}}},
    {"name": "remove_skill", "description": "Uninstall a learned skill he no longer wants.",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S}}},
    {"name": "list_skills", "description": "The skills you've learned and any waiting for his OK.",
     "input_schema": {"type": "object", "properties": {}}},
]
COMMANDS = {"Skills": ["Learn to check my car rego", "What skills have you learned?"]}


if __name__ == "__main__":
    import json
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    (features.HERE / "custom").mkdir()
    assert _slug("Learn to check my car rego") == "car_rego"
    import devhelper
    devhelper._load = lambda n, d: json.loads((features.HERE / n).read_text()) if (features.HERE / n).exists() else d
    devhelper._save = lambda n, data: (features.HERE / n).write_text(json.dumps(data))
    r = learn_skill("check my car rego")
    job = devhelper._load("dev_jobs.json", [])[-1]
    assert r["learning"] == "car_rego" and job["skill"] == "car_rego" and "car_rego_" in job["request"]
    assert not check("car_rego")["ok"]  # nothing written yet
    good = ('import features\nFUNCS = {"car_rego_days": lambda: {"days": 30}}\nTOOLS = [{"name": "car_rego_days", "description": "Days '
            'left.", "input_schema": {"type": "object", "properties": {}}}]\nif __name__ == "__main__":\n'
            '    assert FUNCS["car_rego_days"]()["days"] == 30\n    print("car_rego self-test passed")\n')
    (_dir("car_rego") / "car_rego.py").write_text(good)
    c = check("car_rego")
    assert c["ok"] and c["tools"] == ["car_rego_days"] and not c["warnings"], c
    (_dir("car_rego") / "car_rego.py").write_text(good.replace("== 30", "== 31") + "import subprocess\n")
    c = check("car_rego")
    assert not c["ok"] and "runs programs" in c["warnings"] and "self-test failed" in c["problems"][0]
    shown, said = [], []
    features._panel = shown.append
    after_job(job, "Done.", said.append)
    assert shown[-1]["kind"] == "skill" and ["Try again", "retry the skill car_rego"] in shown[-1]["actions"]
    (_dir("car_rego") / "car_rego.py").write_text(good)
    added = []
    REGISTER = added.append
    r = install_skill("car_rego")
    assert r["installed"] == "car_rego" and added and added[0].FUNCS["car_rego_days"]()["days"] == 30, r
    assert skills() == {"waiting": [], "installed": ["car_rego"]}
    assert remove_skill("car_rego")["removed"] and skills()["waiting"] == ["car_rego"]
    print("skills self-test passed")
