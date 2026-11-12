"""Phone alerts: short notifications on his phone through the free ntfy app (ntfy.sh), even with the HUD closed.
Settings > Phone alerts switches them on and shows the private topic name to subscribe to in the app. Sent for:
autopilot trades opening and closing, a new roster loading, shift reminders, and the weekly trade review.
The text goes through ntfy.sh's server; the topic is a long random name nobody else knows."""
import json
import secrets
import threading
import urllib.request

import features


def topic():
    s = features.settings()
    if not s.get("ntfy_topic"):
        s = {**s, "ntfy_topic": "jarvis-" + secrets.token_hex(10)}
        features._save("settings.json", s)
    return s["ntfy_topic"]


def on():
    return bool(features.settings().get("phone_alerts"))


def notify(text, title="Jarvis", force=False, tags=""):
    """Send one alert (in the background; never blocks or raises). force: even with alerts off (the Test button)."""
    if not (force or on()):
        return False
    url = (features.settings().get("ntfy_server") or "https://ntfy.sh").rstrip("/") + "/" + topic()

    def go():
        try:
            req = urllib.request.Request(url, data=str(text)[:2000].encode("utf-8"), method="POST",
                                         headers={"Title": title.encode("ascii", "ignore").decode(), "Tags": tags})
            urllib.request.urlopen(req, timeout=15).close()
        except OSError as e:
            print("phone alert:", repr(e)[:160])
    threading.Thread(target=go, daemon=True).start()
    return True


# ---------- Talking to Jarvis from the Apple Watch (or anywhere) ----------
# A watch can't join Tailscale, but it can reach ntfy.sh. A Shortcut on the watch dictates what he says and posts it
# to a second private topic (the "inbox"); Jarvis checks it every few seconds, answers like a typed message, and the
# answer comes back as a phone alert, which the watch shows. The inbox name is the password: anyone who knew it
# could talk to Jarvis, so it's long, random, and shown only on this PC.
def inbox():
    s = features.settings()
    if not s.get("ntfy_inbox"):
        s = {**s, "ntfy_inbox": "jarvis-in-" + secrets.token_hex(12)}
        features._save("settings.json", s)
    return s["ntfy_inbox"]


def watch_on():
    return bool(features.settings().get("watch_chat"))


def check_inbox(answer, since="10s"):
    """New messages in the inbox -> answer(text) each, its reply sent back as an alert. Returns the last message id
    (pass it as `since` next time)."""
    url = f"{(features.settings().get('ntfy_server') or 'https://ntfy.sh').rstrip('/')}/{inbox()}/json?poll=1&since={since}"
    last = since
    with urllib.request.urlopen(url, timeout=20) as r:
        for line in r.read().decode("utf-8", "ignore").splitlines():
            try:
                m = json.loads(line)
            except ValueError:
                continue
            last = m.get("id", last)
            text = (m.get("message") or "").strip()
            if m.get("event") == "message" and text:
                reply = answer(text[:1000])
                notify(reply, "Jarvis", force=True, tags="speech_balloon")
    return last


def start_inbox(answer):
    """Check the inbox every 5 seconds while watch chat is on (Settings > Phone alerts)."""
    import time

    def loop():
        since = "10s"
        while True:
            if watch_on():
                try:
                    since = check_inbox(answer, since)
                except OSError as e:
                    print("watch inbox:", repr(e)[:120])
                    time.sleep(25)
            else:
                since = "10s"  # nothing sent while it was off gets answered later
            time.sleep(5)
    threading.Thread(target=loop, daemon=True).start()


def settings_info():
    return {"on": on(), "topic": topic(), "server": features.settings().get("ntfy_server") or "https://ntfy.sh",
            "watch": watch_on(), "inbox": inbox()}


def set_alerts(on=None, test=False, watch=None):
    if watch is not None:
        features._save("settings.json", {**features.settings(), "watch_chat": bool(watch)})
    if on is not None:
        features._save("settings.json", {**features.settings(), "phone_alerts": bool(on)})
    if test:
        notify("Phone alerts are working. Trades, rosters and shift reminders will show up here.", force=True,
               tags="white_check_mark")
    return settings_info()


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    t = topic()
    assert t.startswith("jarvis-") and len(t) == 27 and topic() == t
    assert not notify("x") and set_alerts(on=True)["on"]
    i = inbox()
    assert i.startswith("jarvis-in-") and len(i) == 34 and i != t and set_alerts(watch=True)["watch"]
    import io
    sent = []
    notify = lambda text, title="Jarvis", force=False, tags="": sent.append(text)
    body = '{"id":"a1","event":"open"}\n{"id":"a2","event":"message","message":"what time is it"}\n'
    urllib.request.urlopen = lambda url, timeout=0: io.BytesIO(body.encode())
    assert check_inbox(lambda q: "It's 9, sir." if q == "what time is it" else "?") == "a2" and sent == ["It's 9, sir."]
    print("alerts self-test passed")
