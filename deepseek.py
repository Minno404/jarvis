"""DeepSeek as a brain: Claude Code pointed at DeepSeek's servers with your own API key (platform.deepseek.com).

Everything Claude does in Jarvis works the same (his tools, coding and PC jobs), for a fraction of a cent a message,
and nothing runs on this PC. Its top model (V4-Pro) can't see pictures. The key is kept in deepseek_key.txt here,
never sent to the HUD or your phone.
"""
import os
import re
import urllib.request

import features

KEY_FILE = features.HERE / "deepseek_key.txt"
BASE = "https://api.deepseek.com/anthropic"
MODEL = "deepseek-v4-pro"  # the best; "deepseek-flash" is cheaper and quicker


def key():
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def available():
    return bool(key())


def env():
    """The environment that makes Claude Code use DeepSeek (DeepSeek's own Claude Code setup)."""
    e = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY",)}
    model = os.environ.get("JARVIS_DEEPSEEK_MODEL", MODEL)
    e.update(ANTHROPIC_BASE_URL=BASE, ANTHROPIC_AUTH_TOKEN=key(), ANTHROPIC_MODEL=model,
             ANTHROPIC_DEFAULT_OPUS_MODEL=model, ANTHROPIC_DEFAULT_SONNET_MODEL=model,
             ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-flash", CLAUDE_CODE_SUBAGENT_MODEL="deepseek-flash")
    return e


def set_key(k):
    """Save (or with "" remove) the DeepSeek API key, after checking it works."""
    k = (k or "").strip()
    if not k:
        KEY_FILE.unlink(missing_ok=True)
        return {"ready": False}
    if not re.fullmatch(r"[A-Za-z0-9_\-]{20,200}", k):
        return {"error": "That doesn't look like a DeepSeek API key (they start with sk-)."}
    req = urllib.request.Request("https://api.deepseek.com/user/balance",
                                 headers={"Authorization": f"Bearer {k}", "Accept": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).close()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"error": "DeepSeek didn't accept that key."}
    except OSError:
        pass  # offline right now: save it anyway
    KEY_FILE.write_text(k, encoding="utf-8")
    return {"ready": True}


def selftest():
    assert "error" in set_key("not a key!")
    e = env()
    assert e["ANTHROPIC_BASE_URL"] == BASE and "ANTHROPIC_API_KEY" not in e
    print("deepseek self-test passed")


if __name__ == "__main__":
    selftest()
