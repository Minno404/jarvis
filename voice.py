"""Voice control: "Hey Jarvis" wake word, then speech-to-text, all on this PC.

openWakeWord listens for "hey jarvis"; after it fires (or the mic button is pressed) we record until you
stop talking, transcribe with Whisper (faster-whisper) and hand the text to Jarvis like a typed message.
Needs: pip install openwakeword faster-whisper sounddevice  (models download once on first start)
"""
import os
import re
import threading
import time

import numpy as np

RATE, FRAME = 16000, 1280  # 80 ms frames, what openWakeWord expects
WAKE_THRESHOLD = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.5"))
# "Jarvis" on its own: the "hey jarvis" model only half-fires on it, so a half-fire gets a second opinion
# from Whisper on the last ~1.5 s. Lower = catches more, checks more often.
LOOSE_THRESHOLD = float(os.environ.get("JARVIS_LOOSE_WAKE", "0.12"))
NAME = re.compile(r"\bjarvis\b", re.I)
# Speech recognition quality (Settings > Voice recognition): bigger Whisper models hear far better, a bit slower
STT_MODELS = {"fast": "base.en", "accurate": "small.en", "best": "medium.en"}
SURE_LOGPROB = -0.6  # Whisper's average confidence below this: he checks "did you say...?" before acting


STT = {}  # the loaded Whisper model


def transcribe_audio(data, suffix=".m4a"):
    """A recording from the phone's microphone (any format a browser records: mp4/aac, webm/opus) -> (text, sure)."""
    import tempfile
    if not STT.get("model"):
        from faster_whisper import WhisperModel
        STT["model"] = WhisperModel(stt_model(), device="cpu", compute_type="int8")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
    try:
        segments, _ = STT["model"].transcribe(f.name, language="en", beam_size=5, initial_prompt=vocab(), vad_filter=True)
        segments = list(segments)
    finally:
        os.unlink(f.name)
    return " ".join(s.text.strip() for s in segments).strip(), sure(segments)


def stt_model():
    if os.environ.get("JARVIS_STT_MODEL"):
        return os.environ["JARVIS_STT_MODEL"]
    try:
        import features
        return STT_MODELS.get(features.settings().get("stt_quality") or "accurate", "small.en")
    except Exception:
        return "small.en"


def vocab():
    """Words Whisper should expect: his name, Jarvis's own words, and trading terms if he trades."""
    words = ["Jarvis", "Hey Jarvis", "Spotify", "Discord", "Netflix", "YouTube", "TV", "HUD", "Spend Breakdown",
             "Claude", "ChatGPT", "split", "merge", "protocol", "Kokoro"]
    try:
        import features
        s = features.settings()
        words[:0] = [x for x in (s.get("name"), s.get("title")) if x]
        if features.feature("trading"):
            words += ["XAUUSD", "gold", "GBPJPY", "MT5", "MetaTrader", "long", "short", "stop loss", "take profit",
                      "London open", "New York session"]
    except Exception:
        pass
    return ", ".join(dict.fromkeys(words)) + "."

INTERRUPT_THRESHOLD = 0.6   # a bit stricter while he's talking, so his own voice can't set it off
FOLLOW_UP_S = 8             # after he answers you by voice, keep listening this long for a reply
# After "Hey Jarvis": how long to wait for you to start talking, and how long a pause ends what you're saying.
# Longer = more time to think mid-sentence, but a slightly slower reply after you finish.
START_WAIT_S = float(os.environ.get("JARVIS_START_WAIT", "8"))
PAUSE_S = float(os.environ.get("JARVIS_PAUSE", "1.6"))

speaking = threading.Event()  # set while Jarvis is talking
_push = threading.Event()     # mic button: listen now, no wake word needed
_follow = {"until": 0.0}
paused = speaking             # older name
ptt_held = threading.Event()  # set while the push-to-talk key is held down (see hotkey.py)
mode = {"wake": True}         # False in push-to-talk-only mode: no wake word and no open-mic follow-ups


def set_mode(listen_mode):
    """'wake' (say "Hey Jarvis"), 'ptt' (push-to-talk key only) or 'both'."""
    mode["wake"] = listen_mode != "ptt"
    if not mode["wake"]:
        _follow["until"] = 0


def ptt_down():
    """The push-to-talk key went down: listen until it comes back up (and cut in if he's talking)."""
    ptt_held.set()
    listen_now()


def ptt_up():
    ptt_held.clear()


def ptt_done(held_frames, max_s=30):
    """While recording with the push-to-talk key: stop once it's released (plus a moment's tail) or at max_s."""
    return not ptt_held.is_set() or held_frames * FRAME / RATE >= max_s


on_hold = threading.Event()  # "hold on Jarvis": ignore everything until "Hey Jarvis" or the mic button
muted = threading.Event()    # muted (the mini core's mic button, tray, Settings): ignore everything, even "Hey Jarvis"
STATUS = {"fn": None}


def set_muted(on):
    (muted.set if on else muted.clear)()
    _push.clear()
    _follow["until"] = 0
    if STATUS["fn"]:
        STATUS["fn"]("Muted: not listening" if on else 'Say "Hey Jarvis"')

HOLD = re.compile(r"(?:^|\b)(hold on|hang on|hold up|wait|stop|shush|be quiet|quiet|shut up|pause|not now|"
                  r"never ?mind|cancel|that'?s enough)[\s,.!]*(?:jarvis)?[\s,.!]*$", re.I)


def is_hold(text):
    """'Hold on Jarvis', 'stop', 'Jarvis, not now.' ... said as a whole, or at the end of the last few seconds."""
    last = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]  # his own voice may come before it
    t = re.sub(r"^\W*(hey\s+)?jarvis\W*", "", last[-1] if last else "", flags=re.I)
    return bool(t) and bool(HOLD.search(t)) and len(t.split()) <= 6


def hold():
    on_hold.set()
    _follow["until"] = 0


def listen_now():
    on_hold.clear()
    _push.set()


def follow_up(seconds=FOLLOW_UP_S):
    """Listen for a reply without the wake word, for a few seconds (not while on hold or in push-to-talk mode)."""
    if not on_hold.is_set() and mode["wake"]:
        _follow["until"] = time.time() + seconds


def start(on_status, on_heard, on_text, on_interrupt=lambda: None, on_follow=lambda on: None,
          on_hold_cmd=lambda: None):
    """on_status(str) for the HUD, on_heard() when listening starts, on_text(str) with what you said,
    on_interrupt() when you cut in while he's talking, on_follow(bool) when the reply window opens/closes,
    on_hold_cmd() when you say "hold on Jarvis"."""
    cb = dict(on_heard=on_heard, on_text=on_text, on_interrupt=on_interrupt, on_follow=on_follow,
              on_hold_cmd=on_hold_cmd)
    threading.Thread(target=_run, args=(on_status, cb), daemon=True).start()


def end_of_speech(levels, noise, frame_s=FRAME / RATE, quiet_s=None, wait_s=None):
    """Given loudness per frame since listening began, decide: 'wait', 'done' or 'nothing' (no speech)."""
    quiet_s, wait_s = quiet_s or PAUSE_S, wait_s or START_WAIT_S
    talk = max(noise * 3, 300)
    spoke = [i for i, v in enumerate(levels) if v > talk]
    if not spoke:
        return "nothing" if len(levels) * frame_s >= wait_s else "wait"
    quiet = len(levels) - 1 - spoke[-1]
    if quiet * frame_s >= quiet_s or len(levels) * frame_s >= 30:
        return "done"
    return "wait"


class _MicQueue:
    """The microphone feeds a queue from its own audio thread, so slow work here (speech recognition)
    never makes it drop what you're saying."""

    def __init__(self, sd):
        import queue
        self.q = queue.Queue()
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME,
                                     callback=lambda data, frames, t, status: self.q.put(data.copy()))
        self.stream.start()

    def read(self, n=FRAME):
        import queue
        try:
            return self.q.get(timeout=3), False
        except queue.Empty:
            raise RuntimeError("the microphone stopped sending audio")

    @property
    def read_available(self):
        return self.q.qsize() * FRAME


def _open_mic(sd):
    """Open the default microphone, resetting the audio system first if it was lost (headset unplugged...)."""
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass
    return _MicQueue(sd)


def _run(on_status, cb):
    STATUS["fn"] = on_status
    try:
        on_status("Loading…")
        import sounddevice as sd
        import openwakeword
        from openwakeword.model import Model
        from faster_whisper import WhisperModel
        try:
            openwakeword.utils.download_models(model_names=["hey_jarvis"])  # once; quick when present
        except Exception as e:
            print("voice: wake word model download:", repr(e))
        wake = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        stt = WhisperModel(stt_model(), device="cpu", compute_type="int8")
        STT["model"] = stt  # shared with the phone's microphone (transcribe_audio)
        # the quick "did he just say Jarvis?" check runs often, so it always uses the small fast model
        name_stt = stt if stt_model() == "base.en" else WhisperModel("base.en", device="cpu", compute_type="int8")
    except Exception as e:
        print("voice: can't start:", repr(e))
        on_status("Off (see log)")
        return
    failures = 0
    while threading.main_thread().is_alive():
        try:
            stream = _open_mic(sd)
            on_status("Muted: not listening" if muted.is_set() else 'Say "Hey Jarvis"')
            failures = 0
            _listen(stream, wake, stt, name_stt=name_stt, **cb)
        except Exception as e:
            if not threading.main_thread().is_alive():
                return  # Jarvis is closing; nothing to report
            failures += 1
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "voice: microphone problem, reconnecting:", repr(e))
            on_status("No microphone, retrying…" if failures > 2 else "Reconnecting mic…")
            time.sleep(min(30, 2 * failures))


def starts_talking(levels, noise):
    """In the reply window: two loud frames in a row means he's started talking."""
    talk = max(noise * 3, 300)
    return len(levels) >= 2 and levels[-1] > talk and levels[-2] > talk


def _transcribe(stt, frames, careful=False):
    """What was said. careful (a whole request): a wider search, and also whether Whisper is sure of it."""
    pcm = np.concatenate(frames).astype(np.float32) / 32768
    segments, _ = stt.transcribe(pcm, language="en", beam_size=5 if careful else 1, initial_prompt=vocab(),
                                 vad_filter=True)
    segments = list(segments)
    text = " ".join(s.text.strip() for s in segments).strip()
    if not careful:
        return text
    return text, sure(segments)


def sure(segments):
    """Is Whisper confident? Its average log-probability (weighted by length), how sure it is that it was speech
    at all, and whether the text came out repetitive (a sign it's making things up)."""
    if not segments:
        return True
    n = sum(max(1, len(s.text)) for s in segments)
    lp = sum(s.avg_logprob * max(1, len(s.text)) for s in segments) / n
    return lp >= SURE_LOGPROB and max(s.no_speech_prob for s in segments) < 0.6 \
        and max(s.compression_ratio for s in segments) < 2.4


def after_name(text):
    """'Hey Jarvis, turn on the TV.' -> 'turn on the TV.' (also drops anything said before his name)."""
    parts = re.split(r"\bjarvis\b[\s,.!?]*", text, flags=re.I)
    return parts[-1].strip() if len(parts) > 1 else text.strip()


def _drain(stream):
    while getattr(stream, "read_available", 0):
        stream.read(FRAME)


def _listen(stream, wake, stt, on_heard, on_text, on_interrupt, on_follow, on_hold_cmd, name_stt=None):
    recent, pre, last2s = [], [], []  # room loudness over ~10 s, the last few frames, the last 2 seconds
    following, checked_until = False, 0.0
    while True:
        frame = stream.read(FRAME)[0][:, 0]
        level = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
        recent = (recent + [level])[-125:]
        pre = (pre + [frame])[-4:]
        last2s = (last2s + [frame])[-25:]
        noise = float(np.percentile(recent, 20))
        if muted.is_set():  # the microphone keeps running (so nothing piles up), but nothing is listened to
            _push.clear()
            continue
        in_window = time.time() < _follow["until"] and not speaking.is_set() and not on_hold.is_set()
        if following != in_window:
            following = in_window
            on_follow(in_window)
        by_name = False
        if _push.is_set():
            woke = True
            if speaking.is_set():  # mic button or push-to-talk while he's talking: cut in
                on_interrupt()
                speaking.clear()
        elif not mode["wake"]:
            continue  # push-to-talk only: nothing else wakes him (and no wake-word work at all)
        elif in_window:
            woke = starts_talking(recent[-2:], noise)
        else:
            score = max(wake.predict(frame).values())
            woke = score >= (INTERRUPT_THRESHOLD if speaking.is_set() else WAKE_THRESHOLD)
            if (not woke and not speaking.is_set() and score >= LOOSE_THRESHOLD
                    and time.time() >= checked_until):  # maybe just "Jarvis"
                checked_until = time.time() + 1.5  # one check per utterance, not one per frame
                woke = bool(NAME.search(_transcribe(name_stt or stt, last2s[-20:])))
            by_name = woke
            if woke and speaking.is_set():
                on_interrupt()
                speaking.clear()
        if not woke:
            continue
        _push.clear()
        by_key = ptt_held.is_set()  # push-to-talk: record exactly while the key is held
        _follow["until"] = 0
        following = False
        on_heard()
        # Woken by name: keep the last 2 s, so "Hey Jarvis turn on the TV" in one breath and "hold on, Jarvis"
        # are both heard whole. Mic button / talk-back: just the last few frames, for the start of the word.
        audio = list(last2s if by_name else pre)
        levels = []
        while True:
            f = stream.read(FRAME)[0][:, 0]
            audio.append(f)
            levels.append(float(np.sqrt(np.mean(f.astype(np.float32) ** 2))))
            if by_key:
                state = "done" if ptt_done(len(levels)) else "wait"
                if state == "done":
                    audio += [stream.read(FRAME)[0][:, 0] for _ in range(3)]  # the end of the last word
            else:
                state = end_of_speech(levels, noise)
            if state != "wait":
                break
        text, confident = _transcribe(stt, audio, careful=True) if (state == "done" or by_name) else ("", True)
        said = after_name(text) if by_name else text
        if is_hold(text) and (not said or is_hold(said)):
            hold()
            on_hold_cmd()
        else:
            on_hold.clear()  # "Hey Jarvis" or the mic button ends a hold
            try:
                on_text(said, confident)
            except TypeError:  # an older listener that takes just the text
                on_text(said)
        wake.reset()
        last2s = []
        _drain(stream)  # drop audio that piled up while transcribing
        time.sleep(0.3)


if __name__ == "__main__":  # quick check of the end-of-speech rule
    q, loud = 50.0, 2000.0
    fs = FRAME / RATE
    assert end_of_speech([q] * int(6 / fs), q) == "wait"  # 6 s to think before speaking is fine
    assert end_of_speech([q] * int(8.1 / fs), q) == "nothing"
    assert end_of_speech([q] * 3 + [loud] * 10 + [q] * int(1.2 / fs), q) == "wait"  # a 1.2 s pause mid-thought
    assert end_of_speech([q] * 3 + [loud] * 10 + [q] * int(1.7 / fs), q) == "done"
    assert end_of_speech([loud] * int(30.1 / fs), q) == "done"  # 30 s cap
    assert starts_talking([q, loud, loud], q) and not starts_talking([loud, q], q) and not starts_talking([loud], q)
    for said in ("Hold on Jarvis", "hold on, Jarvis.", "Jarvis, stop!", "Hey Jarvis, not now.", "never mind",
                 "and that is why gold went up, sir. Hold on Jarvis", "Hang on.", "Okay, that's enough Jarvis"):
        assert is_hold(said), said
    assert after_name("Hey Jarvis, turn on the TV.") == "turn on the TV." and after_name("Jarvis.") == ""
    assert after_name("and gold is up, sir. Hey Jarvis what's on") == "what's on" and after_name("open MT5") == "open MT5"
    for said in ("Hey Jarvis, what's gold doing?", "wait until gold hits 3,950 then tell me", "", "Jarvis",
                 "set a timer to stop the oven", "how do I stop losing on shorts"):
        assert not is_hold(said), said
    ptt_down()
    assert ptt_held.is_set() and _push.is_set() and not ptt_done(10)
    ptt_up()
    assert ptt_done(10) and ptt_done(10_000)
    _push.clear()
    set_mode("ptt")
    assert not mode["wake"]
    follow_up()
    assert _follow["until"] == 0  # no open-mic follow-ups in push-to-talk mode
    set_mode("both")
    assert mode["wake"]
    print("voice self-test passed")
