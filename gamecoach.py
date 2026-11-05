"""Game coach: Jarvis watches your gameplay and helps you find the mistakes in how you play.

"Coach me" / "watch my gameplay": while the game runs, a screenshot every ~20 s (kept on this PC only, in
screens/coach/). Every few minutes the AI looks at the latest few and, only if it sees a clear mistake, Jarvis says
one short tip (live tips can be turned off). When the game ends (or "stop coaching"), it looks over the whole
session and gives a review: what you did well, the mistakes that kept coming up, and what to practise. "How did I
play?" brings the last review back. Exclusive-fullscreen games can screenshot as black: use borderless windowed.
"""
import datetime
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import features

DIR = features.HERE / "screens" / "coach"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CLAUDE = None  # set by server.py (the Claude Code command)
S, I = {"type": "string"}, {"type": "integer"}

LIVE_PROMPT = """You are a sharp, friendly coach watching {USER} play {game} live. These are screenshots from the
last couple of minutes, oldest first: {files}
Read each with the Read tool. If you can see a clear, specific mistake in how he's playing (positioning, decisions,
resources, map awareness, aim habits, economy, cooldowns, build, settings...), reply with ONE tip of at most 20
words, said like a coach in his ear, e.g. "You keep fighting in the open; hug cover before you reload." Don't repeat
these tips you already gave: {given}. If nothing clearly wrong is visible, or you can't tell what's happening,
reply exactly NOTHING. No preamble."""

REVIEW_PROMPT = """You are an expert coach for {game}. Below are screenshots from {USER}'s session ({minutes} minutes),
oldest first: {files}
Read each with the Read tool. Live tips already given during the session: {given}.
Give him a spoken review, about 150 words, plain sentences, no lists or markdown: one or two things he did well, the
two or three mistakes that kept coming up (be specific about what you saw and when), and one concrete thing to
practise next session. If the screenshots don't show enough to judge, say what you could see and what would help
(e.g. borderless windowed so captures aren't black)."""


def _cfg():
    return features.settings().get("game_coach") or {}


def _set(**kw):
    s = features.settings()
    features._save("settings.json", {**s, "game_coach": {**(s.get("game_coach") or {}), **kw}})


def coach_on(game=None, live_tips=True, every_seconds=20, tip_minutes=3, auto=None):
    """Start coaching: Jarvis watches the gameplay and gives tips. game: which game (else whatever's running).
    auto: coach every game automatically from now on."""
    kw = {"on": True, "game": game or "", "live": bool(live_tips), "every": max(8, min(120, int(every_seconds or 20))),
          "tip_every": max(1, min(15, float(tip_minutes or 3))) * 60}
    if auto is not None:
        kw["auto"] = bool(auto)
    _set(**kw)
    return {"coaching": game or "the next game that's running", **kw,
            "note": "Screenshots stay on this PC. Live tips use a little of the AI allowance each time."}


def coach_off():
    """Stop coaching now; the session review follows."""
    _set(on=False, auto=False)
    return {"stopped": True, "note": "The review of this session is on its way (if there was one)."}


def last_review():
    """The latest gameplay review ('how did I play?')."""
    d = features.HERE / "reviews" / "games"
    f = max(d.glob("*.md"), default=None) if d.is_dir() else None
    if not f:
        return {"error": "No gameplay reviews yet. Say 'coach me' before your next game."}
    return {"review": f.read_text(encoding="utf-8"), "file": f.name}


def coach_now():
    """Look at the last minute of gameplay right now ('what am I doing wrong?')."""
    sess = Coach.current
    frames = sess.frames[-3:] if sess else []
    if not frames:
        return {"error": "I'm not watching a game right now. Say 'coach me' first."}
    tip = analyse(LIVE_PROMPT.replace("If nothing clearly wrong is visible", "If nothing is clearly wrong")
                  .replace("ONE tip of at most 20", "the most useful tip, at most 40"), frames, sess.game, sess.tips)
    return {"tip": tip if tip and tip.strip().upper() != "NOTHING" else "Nothing obviously wrong in the last minute."}


def analyse(prompt, frames, game, given=()):
    """Ask the AI to look at the screenshots. Claude Code (its Read tool views images) or ChatGPT (attached)."""
    files = ", ".join(str(f) for f in frames)
    text = features.personal(prompt.format(game=game or "this game", files=files, minutes="{minutes}",
                                           given="; ".join(given) or "none", USER="{USER}"))
    use_gpt = features.settings().get("brain") == "chatgpt" or not CLAUDE
    if not use_gpt:
        r = subprocess.run([CLAUDE, "-p", "--model", "sonnet", "--tools", "Read", "--setting-sources", "project",
                            "--strict-mcp-config", "--disable-slash-commands", "--permission-mode", "dontAsk",
                            "--output-format", "text"], input=text, capture_output=True, text=True, encoding="utf-8",
                           cwd=features.HERE, timeout=240, creationflags=NO_WINDOW)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        import gpt_brain
        if not gpt_brain.available():
            raise RuntimeError((r.stdout or r.stderr or "no answer")[-200:])
    import gpt_brain
    p = subprocess.run(gpt_brain.command(None, frames), input=text.replace("Read each with the Read tool. ", ""),
                       capture_output=True, text=True, encoding="utf-8", cwd=features.HERE, timeout=240,
                       creationflags=NO_WINDOW)
    _, texts, err = gpt_brain.parse(p.stdout.splitlines())
    if err or not texts:
        raise RuntimeError(err or "no answer")
    return texts[-1].strip()


class Coach:
    """One game session being watched. tick() is called every few seconds from Jarvis's watcher."""
    current = None

    def __init__(self, game, say):
        self.game, self.say, self.start = game, say, time.time()
        self.dir = DIR / time.strftime("%Y-%m-%d_%H%M")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.frames, self.tips, self.last_shot, self.last_tip, self.busy = [], [], 0.0, time.time(), False
        for old in sorted(p for p in DIR.iterdir() if p.is_dir() and p != self.dir)[:-2]:
            shutil.rmtree(old, ignore_errors=True)  # keep the last couple of sessions only

    def shot(self):
        from PIL import ImageGrab
        img = ImageGrab.grab().convert("RGB")
        img.thumbnail((1280, 1280))
        f = self.dir / f"{len(self.frames):04d}.jpg"
        img.save(f, quality=70)
        self.frames.append(f)

    def tick(self, cfg):
        now = time.time()
        if now - self.last_shot >= cfg.get("every", 20):
            self.last_shot = now
            try:
                self.shot()
            except Exception as e:
                print(datetime.datetime.now(), "coach screenshot:", repr(e))
        if cfg.get("live", True) and not self.busy and now - self.last_tip >= cfg.get("tip_every", 180) \
                and len(self.frames) >= 3:
            self.last_tip, self.busy = now, True
            threading.Thread(target=self._tip, daemon=True).start()

    def _tip(self):
        try:
            tip = analyse(LIVE_PROMPT, self.frames[-3:], self.game, self.tips[-6:])
            if tip and tip.strip().strip(".").upper() != "NOTHING" and len(tip) < 220:
                self.tips.append(tip)
                self.say(f"Coach: {tip}", urgent=True)
        except Exception as e:
            print(datetime.datetime.now(), "coach tip:", repr(e)[:200])
        finally:
            self.busy = False

    def finish(self):
        """The session review, saved to reviews/games and said (held if he's away)."""
        minutes = round((time.time() - self.start) / 60)
        if len(self.frames) < 4 or minutes < 2:
            return
        step = max(1, len(self.frames) // 8)
        sample = self.frames[::step][:8]
        try:
            text = analyse(REVIEW_PROMPT.replace("{minutes}", str(minutes)), sample, self.game, self.tips)
        except Exception as e:
            print(datetime.datetime.now(), "coach review:", repr(e)[:200])
            return
        d = features.HERE / "reviews" / "games"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{time.strftime('%Y-%m-%d_%H%M')}.md").write_text(
            f"# {self.game}: {time.strftime('%d %b %Y %H:%M')} ({minutes} min)\n\n{text}\n\nLive tips: "
            + ("; ".join(self.tips) or "none") + "\n", encoding="utf-8")
        try:
            features._panel({"type": "panel", "kind": "text", "title": f"Coach review: {self.game}", "text": text,
                             "stay": True})
        except OSError:
            pass
        self.say(f"Your {self.game} review is ready. {text}")


def tick(game, say):
    """From Jarvis's watcher every 10 s: start, run and finish coaching sessions."""
    cfg = _cfg()
    want = cfg.get("on") or cfg.get("auto")
    playing = game or (cfg.get("on") and cfg.get("game") and cfg["game"]) or None
    sess = Coach.current
    if sess and (not want or not playing):
        Coach.current = None
        if cfg.get("on") and not cfg.get("auto") and not playing:
            _set(on=False)  # one-off coaching ends with the game
        threading.Thread(target=sess.finish, daemon=True).start()
        return
    if want and playing and not sess:
        Coach.current = sess = Coach(cfg.get("game") or playing, say)
        print(datetime.datetime.now(), "coaching", sess.game)
    if sess:
        sess.tick(cfg)


FUNCS = {f.__name__: f for f in (coach_on, coach_off, coach_now, last_review)}
TOOLS = [
    {"name": "coach_on", "description": "Watch his gameplay and coach him ('coach me', 'watch my gameplay', 'help me "
     "get better at Valorant'): screenshots while he plays, a short live tip when there's a clear mistake, and a review "
     "when the game ends. live_tips false = only the review. auto true = coach every game from now on. tip_minutes = "
     "how often to check for tips (default 3).",
     "input_schema": {"type": "object", "properties": {"game": S, "live_tips": {"type": "boolean"},
                                                       "every_seconds": I, "tip_minutes": {"type": "number"},
                                                       "auto": {"type": "boolean"}}}},
    {"name": "coach_off", "description": "Stop coaching now ('stop coaching'); the session review follows.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "coach_now", "description": "Look at the last minute of his gameplay now ('what am I doing wrong?', "
     "'how's my positioning?') and give a tip. Only while coaching.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "last_review", "description": "His latest gameplay review ('how did I play?').",
     "input_schema": {"type": "object", "properties": {}}},
]


def selftest():
    import tempfile
    global DIR
    real_here, real_dir = features.HERE, DIR
    features.HERE = Path(tempfile.mkdtemp())
    DIR = features.HERE / "screens" / "coach"
    said, real_analyse = [], globals()["analyse"]
    try:
        globals()["analyse"] = lambda prompt, frames, game, given=(): (
            "Hug cover before you reload." if "live" in prompt else "Good aim. You peek too much. Practise holding angles.")
        Coach.shot = lambda self: self.frames.append(self.dir / f"{len(self.frames):04d}.jpg")
        assert coach_on(every_seconds=8, tip_minutes=1)["coaching"] == "the next game that's running"
        tick("Valorant", lambda t, urgent=False: said.append(t))
        sess = Coach.current
        assert sess and sess.game == "Valorant" and len(sess.frames) == 1
        for _ in range(3):
            sess.last_shot -= 60
            sess.tick(_cfg())
        sess.last_tip -= 120
        sess.tick(_cfg())
        time.sleep(0.2)
        assert said == ["Coach: Hug cover before you reload."] and sess.tips
        sess.start -= 600
        tick(None, lambda t, urgent=False: said.append(t))  # game over: review
        time.sleep(0.3)
        assert Coach.current is None and said[-1].startswith("Your Valorant review is ready.")
        assert "You peek too much" in last_review()["review"] and _cfg()["on"] is False
        assert "error" in coach_now()
        coach_on("Minecraft")  # a game Jarvis can't spot itself: watched until 'stop coaching'
        tick(None, lambda t, urgent=False: said.append(t))
        assert Coach.current.game == "Minecraft"
        coach_off()
        tick(None, lambda t, urgent=False: said.append(t))
        assert Coach.current is None
    finally:
        features.HERE, DIR = real_here, real_dir
        globals()["analyse"] = real_analyse
    print("game coach self-test passed")


if __name__ == "__main__":
    selftest()
