"""Work shifts: "bring up my work shifts" shows a month calendar up to the end of his latest roster, and a tap on a
day edits it (a shift, a day off, a note). "What am I doing this week?" shows this week in one row. Sending a photo,
screenshot or PDF of the roster has the brain save every shift (save_shifts). Kept in shifts.json (shifts) and
days.json (days off and notes) on this PC. Days inside a roster's dates with no shift count as days off."""
import datetime

import features

FILE = "shifts.json"
DAYS = "days.json"  # {date: {"off": bool, "note": str}}: what he marked himself


def _load():
    return features._load(FILE, [])


def _hours(s):
    if s.get("paid") is not None:  # the roster's paid hours, when it gives them
        return float(s["paid"])
    a, b = (datetime.datetime.strptime(x, "%H:%M") for x in (s["start"], s["end"]))
    h = (b - a).total_seconds() / 3600
    return h + 24 if h <= 0 else h  # past midnight


def save_shifts(shifts, replace=True):
    """shifts: [{date YYYY-MM-DD, start HH:MM, end HH:MM, where, note}], or {date, off: true, note} for a day off on
    the roster (note: what it says, like BOD or 58 Hours Rest). replace: the roster's dates replace what was saved
    for those dates (a new roster overrides the old one)."""
    clean, offs = [], {}
    for s in shifts or []:
        if s.get("off"):
            try:
                offs[datetime.date.fromisoformat(str(s["date"])).isoformat()] = str(s.get("note") or "")[:40]
            except (KeyError, ValueError):
                return {"error": f"A day off needs its date (YYYY-MM-DD): {s}"}
            continue
        try:
            d = datetime.date.fromisoformat(str(s["date"]))
            st, en = (datetime.datetime.strptime(str(s[k]).strip().zfill(5), "%H:%M").strftime("%H:%M") for k in ("start", "end"))
        except (KeyError, ValueError):
            return {"error": f"Every shift needs date (YYYY-MM-DD), start and end (24-hour HH:MM); this one didn't: {s}"}
        clean.append({"date": d.isoformat(), "start": st, "end": en, "where": str(s.get("where", ""))[:60],
                      "note": str(s.get("note", ""))[:120],
                      **({"paid": round(float(s["paid"]), 2)} if s.get("paid") not in (None, "") else {})})
    if not clean and not offs:
        return {"error": "No shifts given."}
    dates = {s["date"] for s in clean} | set(offs)
    old = [s for s in _load() if not (replace and s["date"] in dates)]
    allx = sorted(old + clean, key=lambda s: (s["date"], s["start"]))
    cutoff = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    features._save(FILE, [s for s in allx if s["date"] >= cutoff])  # keep two months of past shifts
    days = features._load(DAYS, {})
    if replace:  # the new roster decides which of its days are off
        days = {d: v for d, v in days.items() if not (d in dates and v.get("off"))}
    for d, note in offs.items():
        days[d] = {"off": True, "note": note}
    features._save(DAYS, days)
    covered = sorted({*features._load("roster_dates.json", []), *(  # every day a roster has covered, for "off" days
        (datetime.date.fromisoformat(min(dates)) + datetime.timedelta(days=i)).isoformat()
        for i in range((datetime.date.fromisoformat(max(dates)) - datetime.date.fromisoformat(min(dates))).days + 1))})
    features._save("roster_dates.json", [d for d in covered if d >= cutoff])
    first, last = min(dates), max(dates)
    return {"saved": len(clean), "days_off": len(offs), "from": first, "to": last,
            "hours": round(sum(_hours(s) for s in clean), 1)}


def my_shifts(days=14, show=True):
    """His upcoming shifts (today onward, the next `days` days), shown as a panel."""
    today = datetime.date.today()
    end = (today + datetime.timedelta(days=int(days))).isoformat()
    now = datetime.datetime.now().strftime("%H:%M")
    up = [s for s in _load() if today.isoformat() <= s["date"] <= end
          and not (s["date"] == today.isoformat() and s["end"] < now and s["end"] > s["start"])]
    hours = round(sum(_hours(s) for s in up), 1)
    if show:
        shift_calendar()
    nxt = up[0] if up else None
    return {"shifts": up, "count": len(up), "hours": hours,
            "next": nxt and f"{nxt['date']} {nxt['start']} to {nxt['end']}" + (f" at {nxt['where']}" if nxt["where"] else "")}


def calendar(start, end):
    """Each day from start to end (dates): its shifts, and whether it's a day off (he marked it, or a roster covered
    it with no shift for him)."""
    by = {}
    for x in _load():
        by.setdefault(x["date"], []).append(x)
    days, covered = features._load(DAYS, {}), set(features._load("roster_dates.json", []))
    out, d = {}, start
    while d <= end:
        k = d.isoformat()
        sh = [{**x, "hours": round(_hours(x), 2)} for x in by.get(k, [])]
        mark = days.get(k, {})
        out[k] = {"shifts": sh, "off": bool(mark.get("off") or (not sh and k in covered)), "note": mark.get("note", "")}
        d += datetime.timedelta(days=1)
    return out


def shift_calendar(show=True):
    """The month calendar: this month up to the end of the month his latest shift is in."""
    today = datetime.date.today()
    last = max([datetime.date.fromisoformat(x["date"]) for x in _load()] + [today])
    start = today.replace(day=1)
    end = (last.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    days = calendar(start, end)
    up = [x for k, v in days.items() if k >= today.isoformat() for x in v["shifts"]]
    note = f"{len(up)} shifts, {sum(x['hours'] for x in up):g} paid hours from today. Tap a day to change it."
    if show:
        features._panel({"type": "panel", "title": "Work shifts", "kind": "calendar", "stay": True, "days": days,
                         "today": today.isoformat(), "note": note, "actions": [["Check my roster email", "check rosters"]]})
    return {"from": start.isoformat(), "to": end.isoformat(), "upcoming": len(up), "note": note}


def week_shifts(show=True):
    """This week, Monday to Sunday, in one row: 'what am I doing this week?'."""
    today = datetime.date.today()
    mon = today - datetime.timedelta(days=today.weekday())
    days = calendar(mon, mon + datetime.timedelta(days=6))
    if show:
        hrs = sum(x["hours"] for v in days.values() for x in v["shifts"])
        features._panel({"type": "panel", "title": "This week", "kind": "calendar", "week": True, "stay": True,
                         "days": days, "today": today.isoformat(), "note": f"{hrs:g} paid hours this week"})
    return {"days": [{"date": k, **v} for k, v in days.items()]}


def set_day(date, start=None, end=None, off=False, note=None, clear=False, where=""):
    """Change one day by hand: a shift (start and end HH:MM, replacing that day's shifts), off=True for a day off,
    note (any text, "" removes it), or clear=True to empty the day."""
    try:
        d = datetime.date.fromisoformat(str(date)).isoformat()
    except ValueError:
        return {"error": "date must be YYYY-MM-DD"}
    days = features._load(DAYS, {})
    mark = days.get(d, {})
    if clear or off or (start and end):
        features._save(FILE, [x for x in _load() if x["date"] != d])
        mark.pop("off", None)
    if start and end:
        r = save_shifts([{"date": d, "start": start, "end": end, "where": where}])
        if r.get("error"):
            return r
    if off:
        mark["off"] = True
    elif clear:
        covered = features._load("roster_dates.json", [])
        if d in covered:  # empty means empty, not "off" from the roster
            features._save("roster_dates.json", [x for x in covered if x != d])
    if note is not None:
        mark["note"] = str(note)[:80]
    if clear:
        mark = {}
    days = {**days, d: mark} if any(mark.values()) else {k: v for k, v in days.items() if k != d}
    features._save(DAYS, days)
    return {"date": d, **calendar(*(datetime.date.fromisoformat(d),) * 2)[d]}


def delete_shifts(date=None, everything=False):
    """Remove the shifts on one date (YYYY-MM-DD), or everything=True for all."""
    keep = [] if everything else [s for s in _load() if s["date"] != str(date)]
    features._save(FILE, keep)
    if everything:
        features._save(DAYS, {})
        features._save("roster_dates.json", [])
    return {"left": len(keep)}


FUNCS = {"save_shifts": save_shifts, "my_shifts": my_shifts, "delete_shifts": delete_shifts,
         "shift_calendar": shift_calendar, "week_shifts": week_shifts, "set_day": set_day}
S = {"type": "string"}
TOOLS = [
    {"name": "save_shifts", "description": (
        "Save his work shifts from his roster. When he sends a photo, screenshot or text of his roster ('here's my "
        "roster'), read every shift that's his (only his name's row if it lists several people) and save them all in "
        "one call: date YYYY-MM-DD (work out the year and the dates from the roster's week), start and end in 24-hour "
        "HH:MM, where (store/role/location if shown), note. Days off on the roster (BOD, rest, leave) go in too as "
        "{date, off: true, note: what it says}. A new roster replaces what was saved for its dates. Then "
        "call my_shifts to show them, and say how many shifts and hours you saved."),
     "input_schema": {"type": "object", "required": ["shifts"], "properties": {
         "shifts": {"type": "array", "items": {"type": "object", "required": ["date", "start", "end"], "properties": {
             "date": S, "start": S, "end": S, "where": S, "note": S, "off": {"type": "boolean"}}}},
         "replace": {"type": "boolean"}}}},
    {"name": "my_shifts", "description": "His upcoming work shifts ('when do I work next?', 'how many hours this fortnight?'): shows the shift "
     "calendar and returns them. days: how far ahead (default 14).",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}, "show": {"type": "boolean"}}}},
    {"name": "shift_calendar", "description": "His work shifts as a month calendar, up to the end of his latest roster "
     "('bring up my work shifts', 'show my roster').", "input_schema": {"type": "object", "properties": {}}},
    {"name": "week_shifts", "description": "This week's shifts, Monday to Sunday, in one row ('what am I doing this "
     "week?'). Returns each day.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "set_day", "description": "Change one day on his shift calendar: a shift (start, end HH:MM, replacing that "
     "day's), off=true for a day off, a note (e.g. 'dentist 2pm'; '' removes it), or clear=true to empty it.",
     "input_schema": {"type": "object", "required": ["date"], "properties": {
         "date": S, "start": S, "end": S, "off": {"type": "boolean"}, "note": S, "clear": {"type": "boolean"}, "where": S}}},
    {"name": "delete_shifts", "description": "Remove his saved shifts on a date (YYYY-MM-DD), or everything=true for all.",
     "input_schema": {"type": "object", "properties": {"date": S, "everything": {"type": "boolean"}}}},
]
COMMANDS = {"Work": ["*Bring up my work shifts", "*What am I doing this week?", "*When do I work next?",
                     "Here's my roster (with a photo)"]}


def selftest():
    import tempfile
    from pathlib import Path
    real = features.HERE
    features.HERE = Path(tempfile.mkdtemp())
    shown = []
    real_panel, features._panel = features._panel, shown.append
    try:
        d = lambda n: (datetime.date.today() + datetime.timedelta(days=n)).isoformat()
        r = save_shifts([{"date": d(1), "start": "9:00", "end": "17:30", "where": "Store"},
                         {"date": d(3), "start": "22:00", "end": "06:00"}])
        assert r["saved"] == 2 and r["hours"] == 16.5, r
        assert save_shifts([{"date": d(1), "start": "10:00", "end": "14:00"}])["saved"] == 1  # new roster replaces that day
        m = my_shifts()
        assert m["count"] == 2 and m["hours"] == 12 and shown[-1]["kind"] == "calendar", m
        assert save_shifts([{"date": "nope", "start": "9", "end": "5"}]).get("error")
        r = save_shifts([{"date": d(5), "off": True, "note": "BOD"}, {"date": d(6), "start": "08:00", "end": "16:00"}])
        assert r["days_off"] == 1 and calendar(*(datetime.date.fromisoformat(d(5)),) * 2)[d(5)] == {"shifts": [], "off": True, "note": "BOD"}
        delete_shifts(d(6))
        c = calendar(datetime.date.fromisoformat(d(0)), datetime.date.fromisoformat(d(3)))
        assert c[d(2)]["off"] and not c[d(0)]["off"] and c[d(3)]["shifts"][0]["hours"] == 8, c  # inside the roster: off
        assert set_day(d(2), "08:00", "12:00")["shifts"][0]["start"] == "08:00"
        r = set_day(d(1), off=True, note="dentist")
        assert r["off"] and not r["shifts"] and r["note"] == "dentist", r
        assert set_day(d(1), clear=True) == {"date": d(1), "shifts": [], "off": False, "note": ""}
        assert len(week_shifts()["days"]) == 7 and shown[-1]["kind"] == "calendar" and shown[-1]["week"]
        assert shift_calendar()["upcoming"] == 2 and d(3) in shown[-1]["days"]
        assert delete_shifts(everything=True)["left"] == 0
        print("shifts self-test passed")
    finally:
        features.HERE, features._panel = real, real_panel


if __name__ == "__main__":
    selftest()
