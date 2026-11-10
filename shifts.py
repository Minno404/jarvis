"""Work shifts: "bring up my work shifts" shows what's coming up; sending a photo or screenshot of the roster ("here's
my roster") has the brain read it and save every shift (save_shifts). Kept in shifts.json on this PC."""
import datetime

import features

FILE = "shifts.json"


def _load():
    return features._load(FILE, [])


def _hours(s):
    if s.get("paid") is not None:  # the roster's paid hours, when it gives them
        return float(s["paid"])
    a, b = (datetime.datetime.strptime(x, "%H:%M") for x in (s["start"], s["end"]))
    h = (b - a).total_seconds() / 3600
    return h + 24 if h <= 0 else h  # past midnight


def save_shifts(shifts, replace=True):
    """shifts: [{date YYYY-MM-DD, start HH:MM, end HH:MM, where, note}]. replace: the roster's dates replace what was
    saved for those dates (a new roster overrides the old one)."""
    clean = []
    for s in shifts or []:
        try:
            d = datetime.date.fromisoformat(str(s["date"]))
            st, en = (datetime.datetime.strptime(str(s[k]).strip().zfill(5), "%H:%M").strftime("%H:%M") for k in ("start", "end"))
        except (KeyError, ValueError):
            return {"error": f"Every shift needs date (YYYY-MM-DD), start and end (24-hour HH:MM); this one didn't: {s}"}
        clean.append({"date": d.isoformat(), "start": st, "end": en, "where": str(s.get("where", ""))[:60],
                      "note": str(s.get("note", ""))[:120],
                      **({"paid": round(float(s["paid"]), 2)} if s.get("paid") not in (None, "") else {})})
    if not clean:
        return {"error": "No shifts given."}
    dates = {s["date"] for s in clean}
    old = [s for s in _load() if not (replace and s["date"] in dates)]
    allx = sorted(old + clean, key=lambda s: (s["date"], s["start"]))
    cutoff = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    features._save(FILE, [s for s in allx if s["date"] >= cutoff])  # keep two months of past shifts
    first, last = min(dates), max(dates)
    return {"saved": len(clean), "from": first, "to": last, "hours": round(sum(_hours(s) for s in clean), 1)}


def my_shifts(days=14, show=True):
    """His upcoming shifts (today onward, the next `days` days), shown as a panel."""
    today = datetime.date.today()
    end = (today + datetime.timedelta(days=int(days))).isoformat()
    now = datetime.datetime.now().strftime("%H:%M")
    up = [s for s in _load() if today.isoformat() <= s["date"] <= end
          and not (s["date"] == today.isoformat() and s["end"] < now and s["end"] > s["start"])]
    hours = round(sum(_hours(s) for s in up), 1)
    if show:
        def line(s):
            d = datetime.date.fromisoformat(s["date"])
            day = "Today" if d == today else "Tomorrow" if d == today + datetime.timedelta(days=1) else d.strftime("%a %d %b")
            return {"text": f"{day}  {s['start']} to {s['end']}",
                    "sub": " · ".join(x for x in (s["where"], f"{_hours(s):g} h", s["note"]) if x)}
        features._panel({"type": "panel", "title": "Work shifts", "kind": "list", "stay": True,
                         "items": [line(s) for s in up[:12]] or [{"text": "No shifts saved for the next two weeks",
                                                                  "sub": "Send a photo or screenshot of your roster"}],
                         "note": f"{len(up)} shifts, {hours:g} hours in the next {days} days" if up else ""})
    nxt = up[0] if up else None
    return {"shifts": up, "count": len(up), "hours": hours,
            "next": nxt and f"{nxt['date']} {nxt['start']} to {nxt['end']}" + (f" at {nxt['where']}" if nxt["where"] else "")}


def delete_shifts(date=None, everything=False):
    """Remove the shifts on one date (YYYY-MM-DD), or everything=True for all."""
    keep = [] if everything else [s for s in _load() if s["date"] != str(date)]
    features._save(FILE, keep)
    return {"left": len(keep)}


FUNCS = {"save_shifts": save_shifts, "my_shifts": my_shifts, "delete_shifts": delete_shifts}
S = {"type": "string"}
TOOLS = [
    {"name": "save_shifts", "description": (
        "Save his work shifts from his roster. When he sends a photo, screenshot or text of his roster ('here's my "
        "roster'), read every shift that's his (only his name's row if it lists several people) and save them all in "
        "one call: date YYYY-MM-DD (work out the year and the dates from the roster's week), start and end in 24-hour "
        "HH:MM, where (store/role/location if shown), note. A new roster replaces what was saved for its dates. Then "
        "call my_shifts to show them, and say how many shifts and hours you saved."),
     "input_schema": {"type": "object", "required": ["shifts"], "properties": {
         "shifts": {"type": "array", "items": {"type": "object", "required": ["date", "start", "end"], "properties": {
             "date": S, "start": S, "end": S, "where": S, "note": S}}},
         "replace": {"type": "boolean"}}}},
    {"name": "my_shifts", "description": "His upcoming work shifts ('when do I work next?', 'bring up my work shifts', "
     "'how many hours this week?'): shows them as a panel and returns them. days: how far ahead (default 14).",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}, "show": {"type": "boolean"}}}},
    {"name": "delete_shifts", "description": "Remove his saved shifts on a date (YYYY-MM-DD), or everything=true for all.",
     "input_schema": {"type": "object", "properties": {"date": S, "everything": {"type": "boolean"}}}},
]
COMMANDS = {"Work": ["*Bring up my work shifts", "*When do I work next?", "Here's my roster (with a photo)"]}


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
        assert m["count"] == 2 and m["hours"] == 12 and shown[-1]["stay"] and "Tomorrow" in shown[-1]["items"][0]["text"], m
        assert save_shifts([{"date": "nope", "start": "9", "end": "5"}]).get("error")
        assert delete_shifts(everything=True)["left"] == 0
        print("shifts self-test passed")
    finally:
        features.HERE, features._panel = real, real_panel


if __name__ == "__main__":
    selftest()
