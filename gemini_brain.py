"""Gemini as a brain: Google's Gemini through its API, with a free key from aistudio.google.com (Get API key).

- Chat: Settings > Brain > Gemini (or "switch to Gemini"). It uses all of Jarvis's tools through one function,
  jarvis_tool(name, args); the tools' names and one-line descriptions are in its instructions, and tool_help gives
  the full arguments. It can see photos. The conversation is kept in memory (cleared on restart or a new persona).
- Trading: the autopilot can ask it as one of its brains (see mt5trade.brains).
The key is kept in gemini_key.txt here, never sent to the HUD or the phone. Model: Settings 'gemini_model'
(default gemini-flash-latest; gemini-pro-latest thinks harder but the free tier allows fewer messages a day).
"""
import base64
import json
import mimetypes
import re
import urllib.error
import urllib.request

import features

KEY_FILE = features.HERE / "gemini_key.txt"
API = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT = "gemini-flash-latest"
history = []  # the chat so far, Gemini's own format


def key():
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def available():
    return bool(key())


def model():
    return features.settings().get("gemini_model") or DEFAULT


def set_key(k):
    """Save (or with "" remove) the Gemini API key, after checking it works."""
    k = (k or "").strip()
    if not k:
        KEY_FILE.unlink(missing_ok=True)
        return {"ready": False}
    if not re.fullmatch(r"[A-Za-z0-9_\-]{30,60}", k):
        return {"error": "That doesn't look like a Gemini API key (from aistudio.google.com, they start with AIza)."}
    try:
        urllib.request.urlopen(urllib.request.Request(f"{API}/models", headers={"x-goog-api-key": k}), timeout=15).close()
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            return {"error": "Google didn't accept that key."}
    except OSError:
        pass  # offline right now: save it anyway
    KEY_FILE.write_text(k, encoding="utf-8")
    return {"ready": True}


def _post(body, timeout=180):
    req = urllib.request.Request(f"{API}/models/{model()}:generateContent", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "ignore")
        try:
            msg = json.loads(msg)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            pass
        raise RuntimeError(f"Gemini {e.code}: {msg[:300]}") from None  # 429 = its limit (quota): the next brain takes over


def _parts(r):
    c = (r.get("candidates") or [{}])[0]
    return (c.get("content") or {}).get("parts") or [], c.get("finishReason")


def ask(prompt, system=None):
    """One answer, no tools (the trading autopilot)."""
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    parts, why = _parts(_post(body))
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text:
        raise RuntimeError(f"Gemini gave no answer ({why or 'empty'})")
    return text


TOOL = {"functionDeclarations": [{
    "name": "jarvis_tool", "description": "Use one of your tools (listed in your instructions) by name.",
    "parameters": {"type": "object", "required": ["name"], "properties": {
        "name": {"type": "string", "description": "the tool's name"},
        "args": {"type": "object", "description": "its arguments as an object (tool_help gives them)"}}}}]}


def tool_list(tools, short):
    return "\n".join(f"- {t['name']}: {short(t['description'])}" for t in tools)


def chat(system, text, funcs, photo=None, rounds=10):
    """Yield Jarvis's reply (one piece per model turn), running his tools as Gemini asks."""
    while len(history) > 40:  # drop the oldest, but never split a tool call from its answer
        del history[0]
        while history and (history[0]["role"] != "user" or any("functionResponse" in p for p in history[0]["parts"])):
            del history[0]
    parts = [{"text": text}]
    if photo:
        mime = mimetypes.guess_type(str(photo))[0] or "image/jpeg"
        parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(open(photo, "rb").read()).decode()}})
    history.append({"role": "user", "parts": parts})
    for _ in range(rounds):
        r = _post({"systemInstruction": {"parts": [{"text": system}]}, "contents": history, "tools": [TOOL]})
        out, why = _parts(r)
        if not out:
            history.pop()
            raise RuntimeError(f"Gemini gave no answer ({why or 'empty'})")
        history.append({"role": "model", "parts": out})
        said = "".join(p.get("text", "") for p in out if not p.get("thought")).strip()
        if said:
            yield said
        calls = [p["functionCall"] for p in out if "functionCall" in p]
        if not calls:
            return
        answers = []
        for c in calls:
            a = c.get("args") or {}
            name, args = a.get("name", ""), a.get("args") or {}
            try:
                res = funcs[name](**args) if name in funcs else {"error": f"No tool called {name}"}
            except Exception as e:
                res = {"error": f"{type(e).__name__}: {e}"}
            try:
                res = json.loads(json.dumps(res, default=str))
            except (TypeError, ValueError):
                res = {"result": str(res)}
            answers.append({"functionResponse": {"name": "jarvis_tool",
                                                 "response": res if isinstance(res, dict) else {"result": res}}})
        history.append({"role": "user", "parts": answers})
    yield "That took more steps than I allow in one go, sir. Ask me to carry on if you want me to keep going."


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    KEY_FILE = features.HERE / "gemini_key.txt"
    assert not available() and set_key("nope").get("error")
    replies = iter([
        {"candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"name": "jarvis_tool", "args": {"name": "add", "args": {"a": 2, "b": 3}}}}]}}]},
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "It's 5, sir."}]}}]}])
    sent = []
    _post = lambda body, timeout=180: (sent.append(body), next(replies))[1]
    out = list(chat("sys", "what's 2+3", {"add": lambda a, b: {"sum": a + b}}))
    assert out == ["It's 5, sir."], out
    assert sent[1]["contents"][-2]["parts"][0]["functionResponse"]["response"] == {"sum": 5}
    assert tool_list([{"name": "x", "description": "Does x. More."}], lambda d: d.split(".")[0] + ".") == "- x: Does x."
    print("gemini self-test passed")
