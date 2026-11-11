"""Phone alerts: short notifications on his phone through the free ntfy app (ntfy.sh), even with the HUD closed.
Settings > Phone alerts switches them on and shows the private topic name to subscribe to in the app. Sent for:
autopilot trades opening and closing, a new roster loading, shift reminders, and the weekly trade review.
The text goes through ntfy.sh's server; the topic is a long random name nobody else knows."""
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


def settings_info():
    return {"on": on(), "topic": topic(), "server": features.settings().get("ntfy_server") or "https://ntfy.sh"}


def set_alerts(on=None, test=False):
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
    print("alerts self-test passed")
