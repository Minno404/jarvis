"""ChatGPT as Jarvis's backup brain, through OpenAI's Codex CLI signed in with a ChatGPT plan.

Setup, once: install Node.js, then run  npm install -g @openai/codex  and  codex login  (choose
"Sign in with ChatGPT"). Jarvis then switches to it by himself when the Claude plan's limit is used up,
and back to Claude about an hour later. Memory, journals, reminders, settings and the recent conversation
all live in Jarvis's own files, so ChatGPT picks up where Claude left off.
"""
import json
import os
import shutil
import subprocess
import re
import threading
import time
from pathlib import Path

import features
import usage

HERE = Path(__file__).resolve().parent


def find_codex():
    global CODEX
    # Node.js installed while Jarvis was running isn't on his PATH yet, and codex.cmd needs it ("node" not found)
    node = Path(os.environ.get("ProgramFiles", "")) / "nodejs"
    if os.name == "nt" and (node / "node.exe").exists() and str(node).lower() not in os.environ["PATH"].lower():
        os.environ["PATH"] = str(node) + os.pathsep + os.environ["PATH"]
    CODEX = shutil.which("codex") or shutil.which("codex.cmd") or shutil.which("codex", path=str(
        Path(os.environ.get("APPDATA", Path.home())) / "npm"))  # npm's global folder on Windows
    return CODEX


CODEX = None
find_codex()
# Codex's own sandbox runs read-only on Windows, which blocks Jarvis's tools (MT5, the TV, files). Jarvis's
# instructions limit it to his own tool commands instead. Set JARVIS_CODEX_SANDBOX=workspace-write to keep it.
SANDBOX = os.environ.get("JARVIS_CODEX_SANDBOX", "danger-full-access")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
thread = {"id": None, "last": 0.0, "turns": 0}        # the ChatGPT conversation
local_thread = {"id": None, "last": 0.0, "turns": 0}  # the local AI's (local_brain.py)

HOW_TO_USE_TOOLS = """
You are running inside OpenAI's Codex CLI as Jarvis's brain for now (instead of Claude).
You CAN do things on his PC, through Jarvis's tools. They're shell commands, run in this folder; pass arguments as
key=value pairs:
  python server.py tool <name> key=value key2="value with spaces"
Lists can be comma-separated (symbols=XAUUSD,EURUSD). For anything nested, pipe JSON in instead:
  echo '{"limits": {"Eating Out": 300}}' | python server.py tool set_spending_plan -
Each prints JSON. Never tell him you're restricted, sandboxed or can't do something on his PC. Instead:
- Jobs on his PC (clear temp files, free up space, install or uninstall software, fix a problem, sort files,
  change a setting, research something): use the specific tool if there is one (for space: cleanup_scan, then
  cleanup_run with what he agrees to), otherwise hand it to pc_task with the whole request. pc_task runs it in
  the background with full access and reports back; tell him it's on it.
- Coding on his projects, or changes to you (new panels, features, fixes): dev_task (project=jarvis for you; it
  reads CUSTOM.md and builds in custom/, kept through updates).
- Questions about your own docs and code: read them (type, dir, findstr on README.md, CUSTOM.md, *.py, custom/...).
In this chat itself don't edit files or run commands other than those: the jobs above do the real work.
Reply in plain spoken sentences: no markdown, lists or code; he hears your reply aloud.
"""


def available():
    """ChatGPT is set up: Codex installed and signed in (Codex installed only for the local AI doesn't count)."""
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return bool(CODEX) and ((home / "auth.json").exists() or bool(os.environ.get("OPENAI_API_KEY")))


SILENT_LIMIT = 300  # seconds with no word from Codex before it counts as stuck (the local AI's first load is slow)


LOCAL_NOTE = ("You are running on this PC as Jarvis's local brain (a free open model, no internet account): be "
              "brief and careful, and use your tools rather than guessing. For anything on the web use the "
              "web_search and read_page tools.")


def recent_context(n=6):
    """The last few exchanges from Jarvis's conversation log, so a switch of brain doesn't lose the thread."""
    d = HERE / "conversations"
    rows = []
    for f in sorted(d.glob("*.jsonl"))[-2:] if d.exists() else []:
        rows += [json.loads(r) for r in f.read_text(encoding="utf-8").splitlines() if r.strip()]
    if not rows:
        return ""
    who = features.settings()["name"] or "User"
    lines = [f"{who}: {r.get('user', r.get('halen'))}\nJarvis: {r['jarvis']}" for r in rows[-n:]]
    return "Your conversation just before this (with your other brain):\n" + "\n".join(lines) + "\n\n"


def command(resume_id=None, images=(), local=False, cwd=HERE):
    cmd = [CODEX, "exec", "--json", "--skip-git-repo-check", "-C", str(cwd), "-s", SANDBOX,
           "-c", "sandbox_workspace_write.network_access=true", "-c", 'approval_policy="never"']
    if local:  # the AI on this PC, through Ollama (it can't see pictures)
        import local_brain
        local_brain.ensure_running()
        cmd += ["--oss", "-c", 'oss_provider="ollama"', "-c", 'model_provider="ollama"', "-m", local_brain.model()]  # newer Codex needs the provider
        images = ()
    elif os.environ.get("JARVIS_GPT_MODEL"):
        cmd += ["-m", os.environ["JARVIS_GPT_MODEL"]]
    pics = [a for img in images for a in ("-i", str(img))]  # photos he sent, attached to the message
    return cmd + (["resume", resume_id, *pics, "-"] if resume_id else [*pics, "-"])


def parse(lines):
    """Codex's JSON events -> (thread id, reply texts, error)."""
    tid, texts, err = None, [], None
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "thread.started":
            tid = ev.get("thread_id")
        elif ev.get("type") == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
            texts.append(ev["item"].get("text", ""))
        elif ev.get("type") in ("turn.failed", "error"):
            e = ev.get("error") or ev
            err = e.get("message") if isinstance(e, dict) else str(e)
    return tid, texts, err


BUSY = set()  # conversations Codex is answering right now: a second message can't resume one (it's locked)
CONFLICT = re.compile(r"active writer|thread-store conflict|thread/resume", re.I)


def chat(system_prompt, message, images=(), local=False, _retry=True):
    """Yield Jarvis's reply from ChatGPT, or from the local AI (each message whole; None marks the end of one).
    Raises on failure."""
    thread = local_thread if local else globals()["thread"]
    if time.time() - thread["last"] > 1200 or thread["turns"] >= 15:  # same fresh-start rule as Claude
        thread.update(id=None, turns=0)
    thread["last"], thread["turns"] = time.time(), thread["turns"] + 1
    how = HOW_TO_USE_TOOLS + (LOCAL_NOTE if local else "")
    resume = thread["id"] if thread["id"] not in BUSY else None  # still busy with the last message: start a new one
    text = message if resume else f"{system_prompt}\n{how}\n{recent_context()}{message}"
    mine = resume
    if mine:
        BUSY.add(mine)
    proc = subprocess.Popen(command(resume, images, local), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", cwd=HERE, creationflags=NO_WINDOW)
    seen = {"at": time.time()}

    def feed():  # in its own thread, so a long prompt can never deadlock against Codex's output
        try:
            proc.stdin.write(text)
            proc.stdin.close()
        except OSError:
            pass

    def watchdog():  # Codex silent this long: it's stuck; stop it so Jarvis says so instead of hanging
        while proc.poll() is None:
            if time.time() - seen["at"] > SILENT_LIMIT:
                print(time.strftime("%Y-%m-%d %H:%M:%S"), "codex silent for", SILENT_LIMIT, "s, stopping it")
                proc.kill()
            time.sleep(2)

    threading.Thread(target=feed, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    said = False
    try:
        out = []
        for line in proc.stdout:
            seen["at"] = time.time()
            out.append(line)
            tid, texts, err = parse([line])
            if tid:
                thread["id"] = mine = tid
                BUSY.add(tid)
            for t in texts:
                if t.strip():
                    said = True
                    yield t
                    yield None
        proc.wait(timeout=30)
        usage.codex(out, "chat", local)
        _, texts, err = parse(out)
        if err or not texts:
            thread["id"] = None
            detail = err or "".join(out)[-300:]
            if _retry and not said and CONFLICT.search(detail):  # that conversation was locked: once more, fresh
                BUSY.discard(mine)
                yield from chat(system_prompt, message, images, local, _retry=False)
                return
            raise RuntimeError(err or ("The local AI" if local else "ChatGPT") + " gave no answer: " + "".join(out)[-300:])
    finally:
        BUSY.discard(mine)
        if proc.poll() is None:
            proc.kill()


def run_task(prompt, cwd, timeout=1800, local=False, pc=True):
    """A background job (coding or PC work) done by ChatGPT, or the local AI, through Codex.
    Returns (spoken summary, ok). pc: a PC job (shell and files anywhere); else a project job (that folder only)."""
    prompt = (("You have full access to this PC through the shell (PowerShell or cmd): you are not sandboxed and "
               "may run commands and change files to do this job.\n\n") if pc else
              "Work only inside this project folder. You read and edit its files with shell commands (that's allowed "
              "and expected here).\n\n") + prompt
    r = subprocess.run(command(None, (), local, cwd), input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=cwd,
                       timeout=timeout, creationflags=NO_WINDOW)
    usage.codex(r.stdout.splitlines(), "job", local)
    _, texts, err = parse(r.stdout.splitlines())
    if err or not texts:
        return f"It didn't work: {err or (r.stderr or r.stdout)[-200:].strip() or 'no answer'}", False
    return texts[-1].strip(), True


def selftest():
    sample = ['{"type":"thread.started","thread_id":"abc-123"}', '{"type":"turn.started"}',
              '{"type":"item.completed","item":{"id":"1","type":"command_execution","command":"python server.py tool quote"}}',
              '{"type":"item.completed","item":{"id":"2","type":"agent_message","text":"Gold is at 3,950, sir."}}',
              '{"type":"turn.completed","usage":{"input_tokens":10}}']
    assert parse(sample) == ("abc-123", ["Gold is at 3,950, sir."], None)
    assert parse(['{"type":"turn.failed","error":{"message":"usage limit"}}'])[2] == "usage limit"
    c = command("abc-123")
    assert c[-3:] == ["resume", "abc-123", "-"] and "--json" in c and c.index("-s") < c.index("resume")
    assert command(None, ["uploads/a.jpg"])[-3:] == ["-i", "uploads/a.jpg", "-"]
    assert command("t1", ["p.jpg"])[-5:] == ["resume", "t1", "-i", "p.jpg", "-"]
    print("gpt brain self-test passed")


if __name__ == "__main__":
    selftest()
