"""The AI council: for a big decision, every AI Jarvis can reach argues it out.

Round 1: Claude, ChatGPT, Gemini and the local AI (whichever are set up) each answer on their own: a stance, how sure
they are, three reasons and the biggest risk. Round 2: each sees the others' answers and keeps or changes its stance,
with one line of rebuttal. Then Claude (Haiku) sums up where they agree, where they split, and a verdict. The council
panel shows each AI's card and the summary; Jarvis says the verdict. Never in incognito (it uses online AIs).
Costs: about two questions per AI plus one for the summary.
"""
import datetime
import json
import re
import subprocess
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import features

CLAUDE = None  # set by server.py
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOG = "council_log.json"
RUN = {"on": False}


def _claude(prompt, model="sonnet"):
    r = subprocess.run([CLAUDE or "claude", "-p", "--output-format", "json", "--model", model, "--tools", "",
                        "--setting-sources", "project", "--strict-mcp-config", "--disable-slash-commands",
                        "--system-prompt", "You are one member of an AI council advising a person. Reply with one "
                        "JSON object only."], input=prompt, capture_output=True, text=True, encoding="utf-8",
                       timeout=300, creationflags=NO_WINDOW)
    out = json.loads(r.stdout or "{}")
    if out.get("is_error") or not out.get("result"):
        raise RuntimeError(str(out.get("result") or r.stderr)[-200:])
    return out["result"]


def _local(prompt):
    import local_brain
    body = {"model": local_brain.model(), "stream": False, "think": False, "format": "json",
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["message"]["content"]


def members():
    """[(name, ask)] for every AI that's set up and not out of its limit."""
    import gemini_brain
    import gpt_brain
    import local_brain
    import mt5trade
    out = []
    if CLAUDE and not mt5trade.IS_OUT("Claude"):
        out.append(("Claude", _claude))
    if gpt_brain.available() and not mt5trade.IS_OUT("ChatGPT"):
        out.append(("ChatGPT", mt5trade.ask_chatgpt))
    if gemini_brain.available() and not mt5trade.IS_OUT("Gemini"):
        out.append(("Gemini", gemini_brain.ask))
    try:
        if local_brain.ready():
            out.append(("Local AI", _local))
    except Exception:
        pass
    return out


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


R1 = ("{USER} asks the council: {q}\n\nAnswer independently and honestly; disagree with the obvious answer if you "
      "think it's wrong. Reply with JSON only: {{\"stance\": \"your answer in at most 12 words\", \"confidence\": 0-100, "
      "\"reasons\": [\"three short reasons\"], \"risk\": \"the biggest risk or downside, one line\"}}")
R2 = ("{USER} asked the council: {q}\n\nYour first answer: {mine}\n\nThe other members said:\n{others}\n\nThink about "
      "their points. Keep your stance or change it. Reply with JSON only: {{\"stance\": \"at most 12 words\", "
      "\"confidence\": 0-100, \"changed\": true/false, \"rebuttal\": \"one sentence answering the strongest point "
      "against you\"}}")
SUM = ("An AI council answered {USER}'s question: {q}\n\nFinal positions:\n{all}\n\nReply with JSON only: "
       "{{\"agree\": [\"what they agree on, up to 3\"], \"split\": [\"where they disagree, up to 3\"], \"verdict\": "
       "\"the council's overall answer in one or two plain sentences, saying how split it was\"}}")


def _round(members_, prompts):
    with ThreadPoolExecutor(len(members_)) as pool:
        futs = {n: pool.submit(ask, prompts[n]) for n, ask in members_}
    out = {}
    for n, f in futs.items():
        try:
            out[n] = _json(f.result()) or {"error": "no clear answer"}
        except Exception as e:
            out[n] = {"error": str(e)[:120]}
    return out


def deliberate(q, members_=None, rounds=2):
    """The whole debate -> {question, members: {name: {round1, round2}}, summary}."""
    members_ = members_ or members()
    p = features.personal
    r1 = _round(members_, {n: p(R1).format(q=q) for n, _ in members_})
    ok = [(n, a) for n, a in members_ if "error" not in r1[n]]
    r2 = {}
    if rounds > 1 and len(ok) > 1:
        line = lambda n, a: f"- {n}: {a.get('stance')} ({a.get('confidence')}% sure). Reasons: {'; '.join(map(str, a.get('reasons') or []))}"
        r2 = _round(ok, {n: p(R2).format(q=q, mine=json.dumps(r1[n]),
                                         others="\n".join(line(m, r1[m]) for m, _ in ok if m != n)) for n, _ in ok})
    final = {n: {**r1[n], **{k: v for k, v in r2.get(n, {}).items() if k != "error"}} for n, _ in members_}
    summary = {}
    try:
        everyone = "\n".join(f"- {n}: {a.get('stance')} ({a.get('confidence')}%)" for n, a in final.items() if a.get("stance"))
        summary = _json(_claude(p(SUM).format(q=q, all=everyone), "haiku")) or {}
    except Exception as e:
        print("council summary:", repr(e)[:120])
    if not summary.get("verdict"):
        stances = [a.get("stance") for a in final.values() if a.get("stance")]
        summary = {"agree": [], "split": [], "verdict": " / ".join(stances) or "The council couldn't answer."}
    return {"question": q, "at": datetime.datetime.now().isoformat(timespec="minutes"),
            "members": {n: {"round1": r1[n], "round2": r2.get(n), "final": final[n]} for n, _ in members_},
            "summary": summary}


def _show(res):
    features._panel({"type": "panel", "kind": "council", "title": "The council", "stay": True, "question": res["question"],
                     "members": [{"name": n, **m["final"], "round1": m["round1"], "changed": bool((m["round2"] or {}).get("changed"))}
                                 for n, m in res["members"].items()],
                     "summary": res["summary"]})


def ask_council(question):
    """Start a council debate in the background; the panel and the verdict come when it's done (a minute or two)."""
    if features.incognito():
        return {"error": "Not in incognito: the council uses online AIs."}
    if RUN["on"]:
        return {"error": "The council is already sitting on another question."}
    ms = members()
    if len(ms) < 2:
        return {"error": "The council needs at least two AIs set up (Claude, ChatGPT, Gemini or the local AI)."}
    RUN["on"] = True

    def go():
        import server_bridge
        try:
            res = deliberate(question, ms)
            features._save(LOG, (features._load(LOG, []) + [res])[-20:])
            _show(res)
            server_bridge.say(f"The council has spoken, {{TITLE}}. {res['summary']['verdict']}")
        except Exception as e:
            server_bridge.say(f"The council couldn't finish: {str(e)[:100]}")
        finally:
            RUN["on"] = False
    threading.Thread(target=go, daemon=True).start()
    return {"started": True, "members": [n for n, _ in ms],
            "note": f"{', '.join(n for n, _ in ms)} are debating it now; the verdict comes in a minute or two."}


def last_council():
    """Show the last council's debate again."""
    log = features._load(LOG, [])
    if not log:
        return {"error": "The council hasn't sat yet."}
    _show(log[-1])
    return {"question": log[-1]["question"], "verdict": log[-1]["summary"].get("verdict")}


FUNCS = {"ask_council": ask_council, "last_council": last_council}
TOOLS = [
    {"name": "ask_council", "description": "Put a big decision or hard question to the AI council ('ask the council "
     "whether...', 'what does the council think'): Claude, ChatGPT, Gemini and the local AI each answer, see each other's "
     "answers, then a verdict. Runs in the background (a minute or two); the panel and the verdict come by themselves.",
     "input_schema": {"type": "object", "required": ["question"], "properties": {"question": {"type": "string"}}}},
    {"name": "last_council", "description": "Show the council's last debate again.",
     "input_schema": {"type": "object", "properties": {}}},
]
COMMANDS = {"Council": ["Ask the council: should I sell my car?", "Show the last council"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    a = lambda p: ('{"stance": "Yes, do it", "confidence": 70, "reasons": ["a", "b", "c"], "risk": "x"}' if "first answer"
                   not in p else '{"stance": "Yes, carefully", "confidence": 65, "changed": true, "rebuttal": "fair"}')
    b = lambda p: 'Sure! {"stance": "No", "confidence": 60, "reasons": ["d"], "risk": "y"}' if "first answer" not in p \
        else '{"stance": "No", "confidence": 62, "changed": false, "rebuttal": "still no"}'
    bad = lambda p: (_ for _ in ()).throw(RuntimeError("limit"))
    _claude = lambda prompt, model="sonnet": '{"agree": ["it matters"], "split": ["whether to"], "verdict": "Split 1-1."}'
    res = deliberate("Should I?", [("Claude", a), ("ChatGPT", b), ("Gemini", bad)])
    m = res["members"]
    assert m["Claude"]["final"]["stance"] == "Yes, carefully" and m["Claude"]["round2"]["changed"]
    assert m["ChatGPT"]["final"]["stance"] == "No" and "error" in m["Gemini"]["round1"] and m["Gemini"]["round2"] is None
    assert res["summary"]["verdict"] == "Split 1-1."
    shown = []
    features._panel = shown.append
    _show(res)
    assert shown[0]["kind"] == "council" and len(shown[0]["members"]) == 3 and shown[0]["members"][0]["changed"]
    print("council self-test passed")
