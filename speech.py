"""Jarvis's voice: Microsoft's online neural voices (edge-tts), or Kokoro, a more natural voice that runs on
this PC (free, no limits, works offline once downloaded).

Kokoro installs itself the first time it's picked in Settings: pip install kokoro-onnx, then the voice model
(about 350 MB) from its GitHub releases into the voices/ folder. Until it's ready, the online voice is used.
"""
import io
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
import wave
from pathlib import Path

import features

HERE = Path(__file__).resolve().parent
VOICES_DIR = HERE / "voices"
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"
FILES = {"kokoro-v1.0.onnx": 300_000_000, "voices-v1.0.bin": 25_000_000}  # rough sizes, for progress
KOKORO_VOICES = {  # name -> (Kokoro voice, language)
    "George (British man)": ("bm_george", "en-gb"), "Fable (British man)": ("bm_fable", "en-gb"),
    "Lewis (British man)": ("bm_lewis", "en-gb"), "Daniel (British man)": ("bm_daniel", "en-gb"),
    "Emma (British woman)": ("bf_emma", "en-gb"), "Isabella (British woman)": ("bf_isabella", "en-gb"),
    "Alice (British woman)": ("bf_alice", "en-gb"), "Lily (British woman)": ("bf_lily", "en-gb"),
    "Michael (American man)": ("am_michael", "en-us"), "Adam (American man)": ("am_adam", "en-us"),
    "Heart (American woman)": ("af_heart", "en-us"), "Bella (American woman)": ("af_bella", "en-us")}
PERSONA_KOKORO = {"jarvis": "George (British man)", "friday": "Emma (British woman)",
                  "edith": "Heart (American woman)", "mate": "Michael (American man)"}
status = {"kokoro": "not installed", "progress": 0}
_lock, _kokoro = threading.Lock(), {}

# ---------- Words written for reading, turned into words for speaking ----------
SAY = {"XAUUSD": "gold", "XAGUSD": "silver", "GBPJPY": "pound yen", "EURUSD": "euro dollar", "GBPUSD": "cable",
       "USDJPY": "dollar yen", "US100": "the Nasdaq", "NAS100": "the Nasdaq", "US30": "the Dow", "BTCUSD": "bitcoin",
       "MT5": "M T 5", "HUD": "H U D", "PnL": "P and L", "P&L": "P and L", "e.g.": "for example", "i.e.": "that is",
       "vs": "versus", "approx.": "about"}


def _money(m):
    sign, whole, cents = m.group(1), m.group(2).replace(",", ""), m.group(3)
    words = f"{int(whole):,} dollar{'s' if whole != '1' else ''}" + (f" {int(cents)}" if cents and int(cents) else "")
    return ("minus " if sign == "-" else "plus " if sign == "+" else "") + words


def speakable(text):
    """Text as it should be said: no markdown, links or emoji; symbols, tickers and money in words."""
    t = re.sub(r"https?://\S+", "a link", text)
    t = re.sub(r"[*_#`>|]+", "", t)
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", t)
    t = re.sub(r"([+-]?)\$(\d[\d,]*)(?:\.(\d{1,2}))?", _money, t)
    t = re.sub(r"([+-])(\d+(?:\.\d+)?)R\b", lambda m: ("plus " if m.group(1) == "+" else "minus ") + m.group(2) + " R", t)
    t = re.sub(r"(\d)%", r"\1 percent", t)
    t = re.sub(r"\s[-–—]\s", ", ", t)
    for k, v in SAY.items():
        t = re.sub(rf"(?<![A-Za-z]){re.escape(k)}(?:\.\w+)?(?![A-Za-z])", v, t)
    return re.sub(r"\s+", " ", t).strip()


# ---------- Engines ----------
def edge(text, voice, rate):
    import asyncio
    import edge_tts

    async def run():
        audio = b""
        async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        return audio
    return asyncio.run(run())


def _wav(samples, rate):
    import numpy as np
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def kokoro_ready():
    return all((VOICES_DIR / f).exists() for f in FILES) and _importable()


def _importable():
    try:
        import kokoro_onnx  # noqa: F401
        return True
    except ImportError:
        return False


def kokoro(text, name, speed=1.0):
    with _lock:  # one at a time: the model is shared
        if "k" not in _kokoro:
            from kokoro_onnx import Kokoro
            _kokoro["k"] = Kokoro(str(VOICES_DIR / "kokoro-v1.0.onnx"), str(VOICES_DIR / "voices-v1.0.bin"))
        voice, lang = KOKORO_VOICES.get(name, KOKORO_VOICES["George (British man)"])
        samples, rate = _kokoro["k"].create(text, voice=voice, speed=speed, lang=lang)
    return _wav(samples, rate)


def install_kokoro():
    """Install Kokoro and download its voice model in the background (once). Progress is in status."""
    if status["kokoro"] in ("installing", "downloading", "ready"):
        return status

    def run():
        try:
            if not _importable():
                status.update(kokoro="installing", progress=0)
                py = Path(sys.executable)  # pip wants a console python (not pythonw, nor Jarvis.exe)
                py = py.with_name("python.exe") if py.name.lower() == "pythonw.exe" else py
                py = Path(shutil.which("python") or "python") if py.name.lower() == "jarvis.exe" else py
                subprocess.run([str(py), "-m", "pip", "install", "--quiet", "kokoro-onnx"], check=True, timeout=900,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            VOICES_DIR.mkdir(exist_ok=True)
            total, done = sum(FILES.values()), 0
            for name, size in FILES.items():
                dest = VOICES_DIR / name
                if not dest.exists():
                    status.update(kokoro="downloading")
                    tmp = dest.with_suffix(".part")
                    with urllib.request.urlopen(MODEL_URL + name, timeout=60) as r, open(tmp, "wb") as f:
                        while chunk := r.read(1 << 20):
                            f.write(chunk)
                            done += len(chunk)
                            status["progress"] = min(99, round(done / total * 100))
                    tmp.replace(dest)
                else:
                    done += size
            status.update(kokoro="ready" if kokoro_ready() else "failed", progress=100)
        except Exception as e:
            status.update(kokoro="failed", error=f"{type(e).__name__}: {e}")
            print("Kokoro voice setup failed:", repr(e))
    threading.Thread(target=run, daemon=True).start()
    status.update(kokoro="installing", progress=0)
    return status


def say(text, persona, kokoro_voice=None):
    """Audio for one piece of speech: (bytes, mime type). persona: the personas.py entry in use.
    kokoro_voice: use this Kokoro voice instead of the one in Settings (split mode's second avatar)."""
    s = features.settings()
    words = speakable(text)
    if s.get("voice_engine") == "kokoro" and kokoro_ready():
        try:
            name = kokoro_voice or s.get("kokoro_voice") or PERSONA_KOKORO.get(persona.get("key"), "George (British man)")
            return kokoro(words, name, float(s.get("voice_speed") or 1.0)), "audio/wav"
        except Exception as e:  # fall back to the online voice rather than go silent
            print("Kokoro voice failed, using the online voice:", repr(e))
    voice = os.environ.get("JARVIS_VOICE") or persona["voice"]
    return edge(words, voice, persona["rate"]), "audio/mpeg"


if VOICES_DIR.exists() and kokoro_ready():
    status.update(kokoro="ready", progress=100)


def selftest():
    cases = {"Gold (XAUUSD) is down -$41.40 today, sir.": "Gold (gold) is down minus 41 dollars 40 today, sir.",
             "Net +2.1R on GBPJPY, win rate 67%.": "Net plus 2.1 R on pound yen, win rate 67 percent.",
             "**Done** - see https://x.com/a": "Done, see a link",
             "Balance $1,196.00 on MT5": "Balance 1,196 dollars on M T 5",
             "XAUUSD.n short closed": "gold short closed"}
    for a, b in cases.items():
        assert speakable(a) == b, (speakable(a), b)
    import numpy as np
    w = _wav(np.zeros(2400, dtype=np.float32), 24000)
    assert w[:4] == b"RIFF" and len(w) == 44 + 4800
    print("speech self-test passed")


if __name__ == "__main__":
    selftest()
