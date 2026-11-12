"""Self-repair: every night (and on "check yourself"), Jarvis looks after himself.

1. Reads his own log (jarvis.log) for the last 24 hours and groups the problems: each error's last line, with
   numbers and paths blanked so repeats count together. A browser tab closing mid-reply (connection reset,
   aborted, broken pipe) is normal and ignored.
2. Fixes what's safe to fix by himself: background jobs stuck "running" for over 3 hours are marked as
   interrupted (so the next can start), a log over 20 MB is rotated, and night-shift copies older than 14 days
   that he never kept or threw away are cleared.
3. Asks Claude Haiku once what the remaining problems mean: the likely cause and the fix (a setting he can change,
   something to reinstall, or a bug to report so the next update fixes it).
4. Shows a "Jarvis health" panel and tells him in the morning, only when there's something worth saying.
At Settings 'selfcare_time' (default 03:30), when the PC is on.
"""
import datetime
import json
import re
import shutil

import features

NOISE = re.compile(r"ConnectionResetError|ConnectionAbortedError|BrokenPipeError|WinError 1005[34]|client disconnected|"
                   r"Exception occurred during processing of request", re.I)
TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.\d+)?")


def _norm(line):
    line = re.sub(r"[A-Za-z]:\\[^\s'\"]+|/[\w./-]{6,}", "<path>", line)
    line = re.sub(r"\b0x[0-9a-f]+\b|\b\d+(?:\.\d+)?\b", "#", line)
    return re.sub(r"\s+", " ", line).strip()[:160]


def problems(lines, since):
    """[(problem, count, example)] from the log lines after `since` (a datetime), most frequent first."""
    groups, cur_time, in_tb = {}, None, False
    for raw in lines:
        m = TS.match(raw)
        if m:
            try:
                cur_time = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        if cur_time and cur_time < since:
            continue
        line = raw.rstrip()
        if line.startswith("Traceback"):
            in_tb = True
            continue
        is_err = (in_tb and re.match(r"^\w[\w.]*(Error|Exception|Exit|Interrupt)\b", line)) or \
            (not in_tb and re.search(r"\b(error|failed|exception|couldn'?t|could not)\b", line, re.I))
        if in_tb and line and not line.startswith((" ", "\t")) and not line.startswith("During handling"):
            in_tb = False
        if not is_err or NOISE.search(line):
            continue
        k = _norm(TS.sub("", line))
        g = groups.setdefault(k, [0, line.strip()[:300]])
        g[0] += 1
    return sorted(((k, n, ex) for k, (n, ex) in groups.items()), key=lambda x: -x[1])


def safe_fixes(now=None):
    """What's safe to fix without asking. -> [what was done]"""
    import devhelper
    now = now or datetime.datetime.now()
    done = []
    jobs = devhelper._load("dev_jobs.json", [])
    stuck = [j for j in jobs if j.get("status") == "running" and j.get("asked", "9") <
             (now - datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M") and not j.get("night")]
    for j in stuck:
        j.update(status="error", result="Interrupted (it was stuck for over 3 hours; Jarvis may have restarted).")
    if stuck:
        devhelper._save("dev_jobs.json", jobs)
        done.append(f"Cleared {len(stuck)} stuck background job{'s' if len(stuck) > 1 else ''}.")
    log = features.HERE / "jarvis.log"
    if log.exists() and log.stat().st_size > 20_000_000:
        shutil.move(str(log), str(log.with_suffix(".log.1")))
        done.append("Rotated a log file over 20 MB.")
    kept = features._load("nightshift.json", {})
    drafts = features.HERE / "drafts"
    if drafts.exists():
        old = [d for d in drafts.iterdir() if d.is_dir() and not d.name.endswith("-backup")
               and d.stat().st_mtime < (now - datetime.timedelta(days=14)).timestamp() and d.name not in kept]
        for d in old:
            shutil.rmtree(d, ignore_errors=True)
        if old:
            done.append(f"Cleared {len(old)} old night-shift copies.")
    return done


def diagnose(probs):
    """Claude Haiku's read on the problems -> [{problem, cause, fix, who}]"""
    if not probs:
        return []
    import council
    lines = "\n".join(f"- {n}x: {ex}" for _, n, ex in probs[:8])
    try:
        r = council._claude("You're Jarvis checking your own error log (a Python personal-assistant app on Windows: "
                            "MT5 trading, Claude/ChatGPT/Gemini brains, voice, a web HUD). For each problem below, give "
                            "the likely cause and the fix in plain words for a non-programmer. who: 'you' (he can fix it: a "
                            "setting, a sign-in, reinstalling something), 'update' (a bug in Jarvis to report: the next "
                            "update fixes it) or 'harmless' (nothing to do). Reply with JSON only: {\"items\": [{\"problem\": "
                            "\"short\", \"cause\": \"...\", \"fix\": \"...\", \"who\": \"you|update|harmless\"}]}\n\n" + lines,
                            "haiku")
        return (council._json(r) or {}).get("items", [])
    except Exception as e:
        print("selfcare diagnosis:", repr(e)[:120])
        return [{"problem": ex[:80], "cause": "", "fix": "", "who": "update"} for _, _, ex in probs[:5]]


def check_yourself(show=True, now=None):
    """Jarvis's health check: his errors in the last 24 hours, what he fixed, and what the rest mean."""
    now = now or datetime.datetime.now()
    log = features.HERE / "jarvis.log"
    try:
        lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()[-20000:]
    except OSError:
        lines = []
    probs = problems(lines, now - datetime.timedelta(hours=24))
    fixed = safe_fixes(now)
    diag = diagnose(probs)
    worth = [d for d in diag if d.get("who") != "harmless"]
    res = {"checked": now.isoformat(timespec="minutes"), "errors": sum(n for _, n, _ in probs),
           "kinds": len(probs), "fixed": fixed, "diagnosis": diag}
    features._save("selfcare.json", res)
    if show:
        features._panel({"type": "panel", "kind": "list", "title": "Jarvis health", "stay": True,
                         "items": [{"text": "Fixed: " + f, "sub": ""} for f in fixed]
                         + [{"text": f"{'YOU' if d.get('who') == 'you' else 'UPDATE'}: {d.get('problem', '')}",
                             "sub": f"{d.get('cause', '')} {d.get('fix', '')}".strip()} for d in worth]
                         or [{"text": "All good", "sub": "No problems in the last 24 hours."}],
                         "note": f"{res['errors']} errors of {res['kinds']} kinds in the last 24 hours."})
    return {**res, "worth_telling": bool(fixed or worth)}


def due(now=None):
    now = now or datetime.datetime.now()
    t = features.settings().get("selfcare_time", "03:30")
    st = features._load("state.json", {})
    if not t or now.strftime("%H:%M") < t or st.get("selfcare_day") == now.date().isoformat():
        return False
    features._save("state.json", {**st, "selfcare_day": now.date().isoformat()})
    return True


def nightly(say):
    r = check_yourself(show=False)
    if r["worth_telling"]:
        need = [d for d in r["diagnosis"] if d.get("who") == "you"]
        say(f"Overnight check-up, {{TITLE}}: "
            + (" ".join(r["fixed"]) + " " if r["fixed"] else "")
            + (f"{len(need)} thing{'s' if len(need) > 1 else ''} need you: {need[0].get('problem')}. {need[0].get('fix', '')} "
               if need else "")
            + "Say 'check yourself' for the details.")


FUNCS = {"check_yourself": check_yourself}
TOOLS = [{"name": "check_yourself", "description": "Your own health check ('check yourself', 'are you OK', 'any "
          "errors'): your errors in the last 24 hours, what you fixed by yourself, and what the rest mean.",
          "input_schema": {"type": "object", "properties": {}}}]
COMMANDS = {"Jarvis": ["Check yourself"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    log = ["2026-11-12 10:00:00.1 mt5: 2 new trades",
           "2026-11-12 10:01:00.5 proactive message failed: TimeoutError('timed out after 12')",
           "Traceback (most recent call last):", '  File "x.py", line 3, in f', "KeyError: 'price'",
           "2026-11-12 10:02:00.5 proactive message failed: TimeoutError('timed out after 30')",
           "ConnectionResetError: [WinError 10054] An existing connection was forcibly closed",
           "2026-11-10 09:00:00.0 old failed thing"]
    p = problems(log, datetime.datetime(2026, 11, 11, 12))
    assert [(n, ex[-18:]) for _, n, ex in p] == [(2, "('timed out after 12')"[-18:]), (1, "KeyError: 'price'"[-18:])], p
    import devhelper
    devhelper._load = lambda n, d: json.loads((features.HERE / n).read_text()) if (features.HERE / n).exists() else d
    devhelper._save = lambda n, data: (features.HERE / n).write_text(json.dumps(data))
    devhelper._save("dev_jobs.json", [{"id": 1, "status": "running", "asked": "2026-11-12 01:00"},
                                      {"id": 2, "status": "running", "asked": "2026-11-12 09:30"}])
    assert safe_fixes(datetime.datetime(2026, 11, 12, 10, 0)) == ["Cleared 1 stuck background job."]
    assert [j["status"] for j in devhelper._load("dev_jobs.json", [])] == ["error", "running"]
    import council
    council._claude = lambda p, model="": '{"items": [{"problem": "MT5 timeouts", "cause": "MT5 closed", "fix": "Open MT5", "who": "you"}]}'
    (features.HERE / "jarvis.log").write_text("\n".join(log))
    said = []
    nightly(said.append)
    assert "1 thing need" in said[0] or "need you: MT5 timeouts" in said[0], said
    assert due(datetime.datetime(2026, 11, 13, 3, 40)) and not due(datetime.datetime(2026, 11, 13, 4))
    print("selfcare self-test passed")
