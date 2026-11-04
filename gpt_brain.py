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
import time
from pathlib import Path

import features

HERE = Path(__file__).resolve().parent
CODEX = shutil.which("codex") or shutil.which("codex.cmd") or shutil.which("codex", path=str(
    Path(os.environ.get("APPDATA", Path.home())) / "npm"))  # npm's global folder on Windows
SANDBOX = os.environ.get("JARVIS_CODEX_SANDBOX", "workspace-write")  # danger-full-access if tools get blocked
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
thread = {"id": None, "last": 0.0, "turns": 0}

HOW_TO_USE_TOOLS = """
You are running inside OpenAI's Codex CLI as Jarvis's backup brain (the Claude plan is used up for now).
Your tools are shell commands, run in this folder. Pass arguments as key=value pairs:
  python server.py tool <name> key=value key2="value with spaces"
Lists can be comma-separated (symbols=XAUUSD,EURUSD). For anything nested, pipe JSON in instead:
  echo '{"limits": {"Eating Out": 300}}' | python server.py tool set_spending_plan -
Each prints JSON. Run no other commands and don't read or edit files (except viewing the screenshot image the
screenshot tool saves). Reply in plain spoken sentences: no markdown, lists or code; he hears your reply aloud.
"""


def available():
    return bool(CODEX)


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


def command(resume_id=None):
    cmd = [CODEX, "exec", "--json", "--skip-git-repo-check", "-C", str(HERE), "-s", SANDBOX,
           "-c", "sandbox_workspace_write.network_access=true", "-c", 'approval_policy="never"']
    if os.environ.get("JARVIS_GPT_MODEL"):
        cmd += ["-m", os.environ["JARVIS_GPT_MODEL"]]
    return cmd + (["resume", resume_id, "-"] if resume_id else ["-"])


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


def chat(system_prompt, message):
    """Yield Jarvis's reply from ChatGPT (each message whole; None marks the end of one). Raises on failure."""
    if time.time() - thread["last"] > 1200 or thread["turns"] >= 15:  # same fresh-start rule as Claude
        thread.update(id=None, turns=0)
    thread["last"], thread["turns"] = time.time(), thread["turns"] + 1
    text = message if thread["id"] else f"{system_prompt}\n{HOW_TO_USE_TOOLS}\n{recent_context()}{message}"
    proc = subprocess.Popen(command(thread["id"]), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", cwd=HERE, creationflags=NO_WINDOW)
    try:
        proc.stdin.write(text)
        proc.stdin.close()
        out = []
        for line in proc.stdout:
            out.append(line)
            tid, texts, err = parse([line])
            if tid:
                thread["id"] = tid
            for t in texts:
                if t.strip():
                    yield t
                    yield None
        proc.wait(timeout=30)
        _, texts, err = parse(out)
        if err or not texts:
            thread["id"] = None
            raise RuntimeError(err or "ChatGPT gave no answer: " + "".join(out)[-300:])
    finally:
        if proc.poll() is None:
            proc.kill()


def selftest():
    sample = ['{"type":"thread.started","thread_id":"abc-123"}', '{"type":"turn.started"}',
              '{"type":"item.completed","item":{"id":"1","type":"command_execution","command":"python server.py tool quote"}}',
              '{"type":"item.completed","item":{"id":"2","type":"agent_message","text":"Gold is at 3,950, sir."}}',
              '{"type":"turn.completed","usage":{"input_tokens":10}}']
    assert parse(sample) == ("abc-123", ["Gold is at 3,950, sir."], None)
    assert parse(['{"type":"turn.failed","error":{"message":"usage limit"}}'])[2] == "usage limit"
    c = command("abc-123")
    assert c[-3:] == ["resume", "abc-123", "-"] and "--json" in c and c.index("-s") < c.index("resume")
    print("gpt brain self-test passed")


if __name__ == "__main__":
    selftest()
