"""Jarvis's third brain: a free AI that runs on this PC (no account, no tokens, works offline).

Ollama runs an open model on the graphics card, and Jarvis talks to it through OpenAI's Codex CLI in its local
mode (codex --oss), the same way his ChatGPT brain works: his tools, coding jobs and PC jobs all work. It's less
capable than Claude, so by default it's the last fallback (Claude, then ChatGPT, then this); "switch to local"
makes it the only brain.

install() sets up whatever is missing: Ollama, Node.js and the Codex CLI (both through winget), then downloads the
model that suits this PC's graphics memory. Progress goes to the HUD's Activity panel.
"""
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import features

API = "http://127.0.0.1:11434"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CONTEXT = "32768"  # Codex needs a long context window; Ollama's default is much shorter
# (graphics memory needed in GB, Ollama model, what to call it)
MODELS = [(14, "gpt-oss:20b", "gpt-oss 20B (OpenAI's open model): the best fit for Codex"),
          (7, "qwen3:8b", "Qwen3 8B: good for mid-range graphics cards"),
          (0, "qwen3:4b", "Qwen3 4B: small and quick, for modest PCs")]
progress = {"step": "", "pct": None, "error": None, "running": False}


def _run(cmd, timeout=900):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)


def vram_gb():
    """The graphics card's own memory in GB (NVIDIA, AMD or Intel), or None if it can't be told."""
    try:
        r = _run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], 10)
        if r.returncode == 0 and r.stdout.strip():
            return round(max(float(x) for x in r.stdout.split()) / 1024, 1)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    if os.name != "nt":
        return None
    ps = (r"Get-ItemProperty 'HKLM:\SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0*' "
          r"-Name HardwareInformation.qwMemorySize -ErrorAction SilentlyContinue | "
          r"ForEach-Object { $_.'HardwareInformation.qwMemorySize' }")
    try:
        sizes = [int(x) for x in _run(["powershell", "-NoProfile", "-Command", ps], 20).stdout.split() if x.isdigit()]
        return round(max(sizes) / 1024 ** 3, 1) if sizes else None
    except (OSError, subprocess.SubprocessError):
        return None


def recommend(vram=None):
    v = vram if vram is not None else (vram_gb() or 0)
    need, model, label = next(m for m in MODELS if v >= m[0])
    return {"model": model, "label": label, "vram_gb": v or None}


def ollama_exe():
    return shutil.which("ollama") or next((str(p) for p in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe") if p.exists()), None)


def _api(path, data=None, timeout=5):
    req = urllib.request.Request(API + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def models():
    try:
        with _api("/api/tags") as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except (OSError, ValueError):
        return None  # Ollama isn't running


def model():
    """The model to use. Settings > Brain > "runs on: RAM" uses a copy set to run on the processor and system memory
    (num_gpu 0): much slower, but leaves the graphics card free for games."""
    s = features.settings()
    base = s.get("local_model") or recommend(0)["model"]
    if s.get("local_on") != "ram":
        return base
    name = "jarvis-ram-" + base.replace(":", "-").replace("/", "-")
    have = models()
    if have is not None and not any(m.split(":")[0] == name for m in have):
        with _api("/api/create", {"model": name, "from": base, "parameters": {"num_gpu": 0}, "stream": False},
                  timeout=120):
            pass
    return name


def unload_all():
    """Free the graphics card / memory now (Ollama otherwise keeps the model loaded a few minutes)."""
    for m in models() or []:
        try:
            with _api("/api/generate", {"model": m, "keep_alive": 0}, timeout=10):
                pass
        except OSError:
            pass


def ensure_running():
    """Start Ollama in the background (with the long context Codex needs) if it isn't running."""
    if models() is not None:
        return True
    exe = ollama_exe()
    if not exe:
        return False
    subprocess.Popen([exe, "serve"], env={**os.environ, "OLLAMA_CONTEXT_LENGTH": CONTEXT},
                     creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(1)
        if models() is not None:
            return True
    return False


def ready():
    """Can Jarvis think with the local AI right now? (Ollama installed, model downloaded, Codex installed.)"""
    import gpt_brain
    # no call to Ollama here: this runs on every reply, and on Windows asking a port nobody's on takes ~2 s
    return bool(gpt_brain.CODEX and ollama_exe() and features.settings().get("local_model"))


def status():
    import gpt_brain
    have = models()
    return {"installed": bool(ollama_exe()), "running": have is not None, "codex": bool(gpt_brain.CODEX),
            "model": features.settings().get("local_model"), "ready": ready(), "progress": progress,
            "recommended": recommend()}


def _winget(pkg):
    if not shutil.which("winget"):
        raise RuntimeError("winget isn't on this PC (it comes with the App Installer from the Microsoft Store)")
    r = _run(["winget", "install", "-e", "--id", pkg, "--silent", "--accept-package-agreements",
              "--accept-source-agreements"], 1800)
    if r.returncode not in (0, -1978335189):  # 0x8A15002B: already installed
        raise RuntimeError(f"winget couldn't install {pkg}: {(r.stdout or r.stderr)[-300:].strip()}")


def install(want=None):
    """Set the local AI up (whatever's missing). Runs for a while: call it in a thread; watch progress."""
    import gpt_brain
    if progress["running"]:
        return {"error": "Already installing."}
    progress.update(running=True, error=None, pct=None)
    try:
        want = want or recommend()["model"]
        if not ollama_exe():
            progress["step"] = "Installing Ollama (runs the AI)"
            _winget("Ollama.Ollama")
        # the long context Codex needs, for this and future starts of Ollama
        _run(["powershell", "-NoProfile", "-Command",
              f"[Environment]::SetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH','{CONTEXT}','User')"], 30)
        os.environ["OLLAMA_CONTEXT_LENGTH"] = CONTEXT
        for name in ("ollama app.exe", "ollama.exe"):  # restart it so the setting applies
            _run(["taskkill", "/IM", name, "/F"], 30)
        if not gpt_brain.CODEX:
            npm = shutil.which("npm") or shutil.which("npm.cmd")
            if not npm:
                progress["step"] = "Installing Node.js (Windows may ask for permission)"
                _winget("OpenJS.NodeJS.LTS")
                npm = next((str(p) for p in (Path(os.environ.get("ProgramFiles", "")) / "nodejs" / "npm.cmd",)
                            if p.exists()), None)
            if not npm:
                raise RuntimeError("Node.js installed, but Jarvis needs a restart to find it. Restart him and "
                                   "press Install again.")
            progress["step"] = "Installing the Codex CLI (how Jarvis talks to the AI)"
            r = _run([npm, "install", "-g", "@openai/codex"], 900)
            if r.returncode != 0:
                raise RuntimeError("npm couldn't install Codex: " + (r.stderr or r.stdout)[-300:].strip())
            gpt_brain.find_codex()
        progress["step"] = "Starting Ollama"
        if not ensure_running():
            raise RuntimeError("Ollama didn't start. Restart the PC and press Install again.")
        progress["step"] = f"Downloading {want} (several GB, one time)"
        with _api("/api/pull", {"model": want, "stream": True}, timeout=7200) as r:
            for line in r:
                ev = json.loads(line or b"{}")
                if ev.get("error"):
                    raise RuntimeError(ev["error"])
                if ev.get("total"):
                    progress["pct"] = round(100 * ev.get("completed", 0) / ev["total"])
        features._save("settings.json", {**features.settings(), "local_model": want})
        progress.update(step="Ready", pct=100)
        return {"ready": True, "model": want}
    except Exception as e:
        progress.update(error=str(e)[:300], step="Couldn't finish")
        return {"error": str(e)}
    finally:
        progress["running"] = False


def selftest():
    assert recommend(16)["model"] == "gpt-oss:20b" and recommend(8)["model"] == "qwen3:8b"
    assert recommend(4)["model"] == "qwen3:4b" and recommend(0)["model"] == "qwen3:4b"
    assert CONTEXT.isdigit() and models() is None  # nothing running here
    print("local brain self-test passed")


if __name__ == "__main__":
    selftest()
