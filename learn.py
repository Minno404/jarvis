"""Jarvis learning about you from conversation.

Every exchange is logged to conversations/<date>.jsonl. Every so often (when you've been away for a
while, or at night protocol) a separate Claude run reads what's new and picks out lasting things you
said about yourself, which go into his memory marked "learned". Ask "what have you learned about me?"
to see them, and "forget ..." to remove any.
"""
import datetime
import json
import os
import subprocess

import features
from features import _load, _save

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CLAUDE = None  # set by server.py


def log_exchange(said, reply):
    d = features.HERE / "conversations"
    d.mkdir(exist_ok=True)
    now = datetime.datetime.now()
    with (d / f"{now:%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": f"{now:%H:%M}", "user": said, "jarvis": reply}) + "\n")


def unlearned():
    """Exchanges not yet read by a learning pass, and where each day's file is up to."""
    d, done = features.HERE / "conversations", _load("state.json", {}).get("learned_lines", {})
    lines, marks = [], {}
    for f in sorted(d.glob("*.jsonl")) if d.exists() else []:
        rows = f.read_text(encoding="utf-8").splitlines()
        new = rows[done.get(f.stem, 0):]
        lines += [dict(json.loads(r), day=f.stem) for r in new if r.strip()]
        marks[f.stem] = len(rows)
    return lines[-200:], marks


LEARN_PROMPT = """Below are recent conversations between {USER} and his assistant Jarvis, and what Jarvis already
remembers about him. List new, lasting facts that {USER} HIMSELF stated: his life, routines, preferences,
people he mentions, goals, projects, gear, how he likes things done. Rules:
- Only what he said, never your guesses or Jarvis's suggestions. One short sentence each.
- Skip one-off requests, moods, anything already remembered, and anything only true today.
- Skip health, money amounts and other sensitive details unless he explicitly asked Jarvis to remember them.
- At most 8. An empty list is fine.

Already remembered:
{known}

Conversations:
{convo}"""

SCHEMA = {"type": "object", "properties": {"facts": {"type": "array", "items": {"type": "string"}}},
          "required": ["facts"]}


def learn_now():
    lines, marks = unlearned()
    if not lines:
        return {"learned": [], "note": "Nothing new to learn from."}
    known = "\n".join(f"- {m['fact']}" for m in features.memories()) or "(nothing yet)"
    who = features.settings()["name"] or "User"
    convo = "\n".join(f"[{l['day']} {l['t']}] {who}: {l.get('user', l.get('halen'))}\nJarvis: {l['jarvis']}" for l in lines)
    r = subprocess.run([CLAUDE or "claude", "-p", "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
                        # background job: the small, cheap model with no Claude Code coding prompt
                        "--model", os.environ.get("JARVIS_LEARN_MODEL", "haiku"), "--tools", "",
                        "--system-prompt", "You pick out lasting facts from conversations.",
                        "--setting-sources", "project", "--strict-mcp-config", "--disable-slash-commands"],
                       input=features.personal(LEARN_PROMPT).format(known=known, convo=convo), capture_output=True, text=True,
                       encoding="utf-8", timeout=300, creationflags=NO_WINDOW)
    facts = (json.loads(r.stdout).get("structured_output") or {}).get("facts", [])
    for fact in facts[:8]:
        features.remember(fact, source="learned")
    state = _load("state.json", {})
    state["learned_lines"] = {**state.get("learned_lines", {}), **marks}
    _save("state.json", state)
    return {"learned": facts[:8]}


def learn_due(idle_s):
    """Worth a pass: at least 6 new exchanges and he's been away from the PC for 20 minutes."""
    return idle_s >= 1200 and len(unlearned()[0]) >= 6


FUNCS = {"learn": learn_now}
TOOLS = [{"name": "learn", "description": "Read recent conversations now and remember lasting things he's told you. "
          "(Also happens by itself when he's away, and at night protocol.)",
          "input_schema": {"type": "object", "properties": {}}}]


def selftest():
    import shutil
    import tempfile
    from pathlib import Path
    global CLAUDE
    real, features.HERE = features.HERE, Path(tempfile.mkdtemp())
    try:
        for i in range(7):
            log_exchange(f"question {i}", f"answer {i}")
        assert learn_due(1300) and not learn_due(60)
        if os.name != "nt":  # stand-in for Claude Code that returns two facts
            fake = features.HERE / "fakeclaude"
            fake.write_text('#!/bin/sh\ncat >/dev/null\necho \'{"structured_output": {"facts": '
                            '["Plays League with friends on weekends", "Trades gold mostly"]}}\'\n')
            fake.chmod(0o755)
            CLAUDE = str(fake)
            assert learn_now()["learned"] == ["Plays League with friends on weekends", "Trades gold mostly"]
            assert [m.get("source") for m in features.memories()] == ["learned", "learned"]
            assert unlearned()[0] == [] and not learn_due(5000)
            log_exchange("one more", "ok")
            assert len(unlearned()[0]) == 1
    finally:
        shutil.rmtree(features.HERE)
        features.HERE = real
        CLAUDE = None
    print("learn self-test passed")


if __name__ == "__main__":
    selftest()
