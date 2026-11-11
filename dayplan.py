"""Shift-aware reminders from his saved shifts (shifts.py), checked every minute by the server's watcher:
- Night shifts (starting 6 pm to 5 am): a reminder to get some sleep, 7 hours before the start.
- Every shift: a heads-up when it's time to leave (Settings 'shift_commute_min', default 30, plus 10 minutes),
  with a short brief: the shift's times and paid hours, the roster label, and how the autopilot is doing.
Shifts that only continue one already running (a multi-day trip's next day) get no reminders. Each reminder is
said by Jarvis and sent to his phone (alerts.py); each fires once (dayplan_state.json)."""
import datetime

import features
import shifts

STATE = "dayplan_state.json"


def _dt(date, hm):
    return datetime.datetime.combine(datetime.date.fromisoformat(date), datetime.time.fromisoformat(hm))


def starts(rows):
    """The shifts that really start (not the next day of one already running), with their start datetime."""
    ends = []
    for s in rows:
        st, en = _dt(s["date"], s["start"]), _dt(s["date"], s["end"])
        if en <= st:
            en += datetime.timedelta(days=1)  # past midnight
        ends.append((st, en))
    out = []
    for s, (st, en) in zip(rows, ends):
        if any(o_st < st <= o_en for o_st, o_en in ends if o_st < st):
            continue  # inside a shift that's already on
        out.append((st, en, s))
    return out


def ended_recently(hours=4, now=None):
    """Did one of his shifts end in the last `hours` hours?"""
    now = now or datetime.datetime.now()
    rows = [s for s in shifts._load() if abs((datetime.date.fromisoformat(s["date"]) - now.date()).days) <= 2]
    return any(now - datetime.timedelta(hours=hours) <= en <= now for _, en, _ in starts(rows))


def due(now=None):
    """[(key, text)] reminders due now."""
    now = now or datetime.datetime.now()
    rows = [s for s in shifts._load() if now.date() - datetime.timedelta(days=2) <= datetime.date.fromisoformat(s["date"])
            <= now.date() + datetime.timedelta(days=2)]
    commute = int(features.settings().get("shift_commute_min") or 30) + 10
    out = []
    for st, en, s in starts(rows):
        when = f"{st:%I:%M %p}".lstrip("0").lower().replace(":00 ", " ").replace(" ", "")
        hours = shifts._hours(s)
        if st.hour >= 18 or st.hour < 5:
            rest = st - datetime.timedelta(hours=7)
            if rest <= now < rest + datetime.timedelta(minutes=30):
                out.append((f"rest {s['date']} {s['start']}",
                            f"Night shift at {when}{' tonight' if st.date() == now.date() and st.hour >= 18 else ''}. "
                            "Good time to get some sleep, {TITLE}."))
        leave = st - datetime.timedelta(minutes=commute)
        if leave <= now < leave + datetime.timedelta(minutes=20):
            length = (en - st).total_seconds() / 3600
            brief = f"Time to head off, {{TITLE}}. Shift at {when}, {length:g} hours"
            brief += f" ({hours:g} paid)" if abs(hours - length) > 0.01 else ""
            brief += f", {s['note']}." if s.get("note") else "."
            try:
                import mt5trade
                if mt5trade.AUTO.on:
                    t = mt5trade._load(mt5trade.AUTO_STATE, {}).get("trades", 0)
                    brief += f" The autopilot is on, {t} trade{'s' if t != 1 else ''} today; it keeps going while you work."
            except Exception:
                pass
            out.append((f"leave {s['date']} {s['start']}", brief))
    return out


def tick(say, now=None):
    """Say and send each reminder that's due and hasn't been yet."""
    st = features._load(STATE, [])
    new = [(k, t) for k, t in due(now) if k not in st]
    if not new:
        return []
    import alerts
    for k, text in new:
        text = features.address(text.replace("{TITLE}", "sir"))
        say(text)
        alerts.notify(text, "Work shift", tags="briefcase")
    features._save(STATE, (st + [k for k, _ in new])[-60:])
    return [t for _, t in new]


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    shifts.save_shifts([{"date": "2026-11-16", "start": "09:00", "end": "01:00"},
                        {"date": "2026-11-17", "start": "01:00", "end": "01:00"},  # the trip continues
                        {"date": "2026-11-18", "start": "20:00", "end": "04:00"}])
    assert [s["date"] for _, _, s in starts(shifts._load())] == ["2026-11-16", "2026-11-18"]
    said = []
    assert tick(said.append, datetime.datetime(2026, 11, 16, 8, 25))[0].startswith("Time to head off")
    assert not tick(said.append, datetime.datetime(2026, 11, 16, 8, 30))  # once only
    assert not due(datetime.datetime(2026, 11, 17, 0, 25))  # the next day of the trip: nothing
    assert "sleep" in due(datetime.datetime(2026, 11, 18, 13, 5))[0][1]
    assert "8pm" in due(datetime.datetime(2026, 11, 18, 19, 25))[0][1], due(datetime.datetime(2026, 11, 18, 19, 25))
    print("dayplan self-test passed")
