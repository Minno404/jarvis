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
STT_MODEL = os.environ.get("JARVIS_STT_MODEL", "base.en")  # small.en is more accurate but slower
VOCAB = ("Jarvis, XAUUSD, gold, GBPJPY, MT5, MetaTrader, long, short, stop loss, take profit, R, "
         "London open, New York session, Spotify, League of Legends.")

INTERRUPT_THRESHOLD = 0.6   # a bit stricter while he's talking, so his own voice can't set it off
FOLLOW_UP_S = 6             # after he answers you by voice, keep listening this long for a reply

speaking = threading.Event()  # set while Jarvis is talking
_push = threading.Event()     # mic button: listen now, no wake word needed
_follow = {"until": 0.0}
paused = speaking             # older name


on_hold = threading.Event()  # "hold on Jarvis": ignore everything until "Hey Jarvis" or the mic button

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
    """Listen for a reply without the wake word, for a few seconds (not while on hold)."""
    if not on_hold.is_set():
        _follow["until"] = time.time() + seconds


def start(on_status, on_heard, on_text, on_interrupt=lambda: None, on_follow=lambda on: None,
          on_hold_cmd=lambda: None):
    """on_status(str) for the HUD, on_heard() when listening starts, on_text(str) with what you said,
    on_interrupt() when you cut in while he's talking, on_follow(bool) when the reply window opens/closes,
    on_hold_cmd() when you say "hold on Jarvis"."""
    cb = dict(on_heard=on_heard, on_text=on_text, on_interrupt=on_interrupt, on_follow=on_follow,
              on_hold_cmd=on_hold_cmd)
    threading.Thread(target=_run, args=(on_status, cb), daemon=True).start()


def end_of_speech(levels, noise, frame_s=FRAME / RATE, quiet_s=0.8, wait_s=4.0):
    """Given loudness per frame since listening began, decide: 'wait', 'done' or 'nothing' (no speech)."""
    talk = max(noise * 3, 300)
    spoke = [i for i, v in enumerate(levels) if v > talk]
    if not spoke:
        return "nothing" if len(levels) * frame_s >= wait_s else "wait"
    quiet = len(levels) - 1 - spoke[-1]
    if quiet * frame_s >= quiet_s or len(levels) * frame_s >= 15:
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
        stt = WhisperModel(STT_MODEL, device="cpu", compute_type="int8")
    except Exception as e:
        print("voice: can't start:", repr(e))
        on_status("Off (see log)")
        return
    failures = 0
    while threading.main_thread().is_alive():
        try:
            stream = _open_mic(sd)
            on_status('Say "Hey Jarvis"')
            failures = 0
            _listen(stream, wake, stt, **cb)
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


def _transcribe(stt, frames):
    pcm = np.concatenate(frames).astype(np.float32) / 32768
    segments, _ = stt.transcribe(pcm, language="en", beam_size=1, initial_prompt=VOCAB, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


def after_name(text):
    """'Hey Jarvis, turn on the TV.' -> 'turn on the TV.' (also drops anything said before his name)."""
    parts = re.split(r"\bjarvis\b[\s,.!?]*", text, flags=re.I)
    return parts[-1].strip() if len(parts) > 1 else text.strip()


def _drain(stream):
    while getattr(stream, "read_available", 0):
        stream.read(FRAME)


def _listen(stream, wake, stt, on_heard, on_text, on_interrupt, on_follow, on_hold_cmd):
    recent, pre, last2s = [], [], []  # room loudness over ~10 s, the last few frames, the last 2 seconds
    following, checked_until = False, 0.0
    while True:
        frame = stream.read(FRAME)[0][:, 0]
        level = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
        recent = (recent + [level])[-125:]
        pre = (pre + [frame])[-4:]
        last2s = (last2s + [frame])[-25:]
        noise = float(np.percentile(recent, 20))
        in_window = time.time() < _follow["until"] and not speaking.is_set() and not on_hold.is_set()
        if following != in_window:
            following = in_window
            on_follow(in_window)
        by_name = False
        if _push.is_set():
            woke = True
        elif in_window:
            woke = starts_talking(recent[-2:], noise)
        else:
            score = max(wake.predict(frame).values())
            woke = score >= (INTERRUPT_THRESHOLD if speaking.is_set() else WAKE_THRESHOLD)
            if (not woke and not speaking.is_set() and score >= LOOSE_THRESHOLD
                    and time.time() >= checked_until):  # maybe just "Jarvis"
                checked_until = time.time() + 1.5  # one check per utterance, not one per frame
                woke = bool(NAME.search(_transcribe(stt, last2s[-20:])))
            by_name = woke
            if woke and speaking.is_set():
                on_interrupt()
                speaking.clear()
        if not woke:
            continue
        _push.clear()
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
            state = end_of_speech(levels, noise)
            if state != "wait":
                break
        text = _transcribe(stt, audio) if (state == "done" or by_name) else ""
        said = after_name(text) if by_name else text
        if is_hold(text) and (not said or is_hold(said)):
            hold()
            on_hold_cmd()
        else:
            on_hold.clear()  # "Hey Jarvis" or the mic button ends a hold
            on_text(said)
        wake.reset()
        last2s = []
        _drain(stream)  # drop audio that piled up while transcribing
        time.sleep(0.3)


if __name__ == "__main__":  # quick check of the end-of-speech rule
    q, loud = 50.0, 2000.0
    assert end_of_speech([q] * 10, q) == "wait"
    assert end_of_speech([q] * 50, q) == "nothing"
    assert end_of_speech([q] * 3 + [loud] * 10 + [q] * 5, q) == "wait"
    assert end_of_speech([q] * 3 + [loud] * 10 + [q] * 10, q) == "done"
    assert end_of_speech([loud] * 190, q) == "done"  # 15 s cap
    assert starts_talking([q, loud, loud], q) and not starts_talking([loud, q], q) and not starts_talking([loud], q)
    for said in ("Hold on Jarvis", "hold on, Jarvis.", "Jarvis, stop!", "Hey Jarvis, not now.", "never mind",
                 "and that is why gold went up, sir. Hold on Jarvis", "Hang on.", "Okay, that's enough Jarvis"):
        assert is_hold(said), said
    assert after_name("Hey Jarvis, turn on the TV.") == "turn on the TV." and after_name("Jarvis.") == ""
    assert after_name("and gold is up, sir. Hey Jarvis what's on") == "what's on" and after_name("open MT5") == "open MT5"
    for said in ("Hey Jarvis, what's gold doing?", "wait until gold hits 3,950 then tell me", "", "Jarvis",
                 "set a timer to stop the oven", "how do I stop losing on shorts"):
        assert not is_hold(said), said
    print("voice self-test passed")
