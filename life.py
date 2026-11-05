"""Everyday helpers: meal ideas and recipes, bills and renewals, habits, a PC clean-up, game mode and finding files.

recipe:      a recipe as a panel that stays up while you cook (missing ingredients marked).
bills:       rego, insurance, subscriptions... Jarvis warns a week before and the day before each is due.
habits:      log them by voice; streaks and how you're tracking against a weekly goal.
clean-up:    scan first (temp files, Recycle Bin, old downloads), then clean only what he says yes to.
             Old downloads go to the Recycle Bin, so they can be got back.
game mode:   when a game starts, close the apps he picked; reopen them when it ends.
find files:  search his own folders by name, then open the file or show it in its folder.
"""
import calendar
import datetime
import os
import shutil
import subprocess
import time
from pathlib import Path

import features
from features import _load, _save

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
S, I = {"type": "string"}, {"type": "integer"}


def _today():
    return datetime.date.today()


def _match(items, name):
    """The key in items that best matches what he said ('gym' finds 'go to the gym')."""
    q = name.lower().strip()
    return q if q in items else next((k for k in items if q in k or k in q), None)


# ---------- Meal ideas ----------
def recipe(title, ingredients, steps, minutes=None, serves=None, missing=None):
    """Show a recipe on the HUD; it stays up until he closes it. Saved so it can be shown again later."""
    r = {"title": title, "ingredients": [str(i) for i in ingredients][:30], "steps": [str(s) for s in steps][:20],
         "minutes": minutes, "serves": serves, "missing": [str(m) for m in (missing or [])][:20],
         "saved": time.strftime("%Y-%m-%d %H:%M")}
    _save("recipes.json", ([x for x in _load("recipes.json", []) if x["title"].lower() != title.lower()] + [r])[-20:])
    try:
        features._panel({"type": "panel", "kind": "recipe", "stay": True, **r})
    except OSError:
        pass
    return {"shown": title, "missing": r["missing"]}


def show_recipe(title=None):
    """Show a recipe from before again (the last one, or by name)."""
    saved = _load("recipes.json", [])
    r = next((x for x in reversed(saved) if not title or title.lower() in x["title"].lower()), None)
    if not r:
        return {"error": "No saved recipe like that.", "saved": [x["title"] for x in saved]}
    return recipe(r["title"], r["ingredients"], r["steps"], r["minutes"], r["serves"], r["missing"])


# ---------- Shopping list with Woolworths and Coles prices ----------
import re  # noqa: E402

UNITS = r"(?:\d+[\d./]*\s*(?:g|kg|ml|l|cups?|tbsp|tsp|tablespoons?|teaspoons?|cloves?|cans?|tins?|packets?|bunch(?:es)?|x)?\b\s*(?:of\s+)?)"


def _term(item):
    """'2 tbsp soy sauce' -> 'soy sauce' (what to search the supermarket for)."""
    t = re.sub(r"\(.*?\)|,.*$", "", str(item).lower())
    return re.sub(rf"^\s*{UNITS}+", "", t).strip() or str(item).strip()


def _shop(terms):
    import json
    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:8765/api/shop", data=json.dumps({"items": terms}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=150) as r:
        return json.loads(r.read())


def _pick(found):
    """The best buy from a store's results: the cheapest of its top few available matches."""
    ok = [p for p in (found if isinstance(found, list) else [])[:4] if p.get("available") and p.get("price")]
    return min(ok, key=lambda p: p["price"]) if ok else None


def price_check(items):
    """Today's Woolworths and Coles prices for grocery items (top matches at each)."""
    terms = [_term(i) for i in items]
    try:
        return _shop(terms)
    except OSError as e:
        return {"error": f"Couldn't check prices: {e}"}


def shopping_list_add(items, recipe=None):
    """Add groceries to his shopping list, priced at Woolworths and Coles, and show the list."""
    terms = [_term(i) for i in items]
    try:
        prices = _shop(terms)
    except OSError:
        prices = {}
    lst = _load("shopping.json", [])
    have = {e["term"] for e in lst}
    for item, t in zip(items, terms):
        e = {"item": str(item), "term": t, "for": recipe or "", "picks": {}}
        for store, res in (prices or {}).items():
            p = _pick(res.get(t)) if isinstance(res, dict) else None
            if p:
                e["picks"][store] = {k: p.get(k) for k in ("name", "price", "size", "unit", "special")}
        if t in have:
            lst = [x if x["term"] != t else {**e, "for": x.get("for") or e["for"]} for x in lst]
        else:
            lst.append(e)
    _save("shopping.json", lst)
    out = shopping_list()
    errors = {s: r["error"] for s, r in (prices or {}).items() if isinstance(r, dict) and "error" in r}
    if errors or not prices:
        out["price_problems"] = errors or "Couldn't reach the supermarkets."
    return out


def _totals(lst):
    stores = sorted({s for e in lst for s in e["picks"]})
    tot = {s: round(sum(e["picks"][s]["price"] for e in lst if s in e["picks"]), 2) for s in stores}
    best = [min(e["picks"].items(), key=lambda kv: kv[1]["price"]) for e in lst if e["picks"]]
    return tot, round(sum(p["price"] for _, p in best), 2)


def shopping_list():
    """His shopping list, the best price for each item and the totals, shown on the HUD."""
    lst = _load("shopping.json", [])
    tot, cheapest = _totals(lst)
    rows = []
    for e in lst:
        best = min(e["picks"].items(), key=lambda kv: kv[1]["price"]) if e["picks"] else None
        rows.append({"item": e["item"], "for": e.get("for", ""),
                     "best": {"store": best[0], **best[1]} if best else None,
                     "other": [{"store": s, "price": p["price"]} for s, p in e["picks"].items() if best and s != best[0]]})
    try:
        features._panel({"type": "panel", "kind": "shopping", "title": "Shopping list", "stay": True, "rows": rows,
                         "totals": tot, "cheapest": cheapest})
    except OSError:
        pass
    return {"items": rows, "totals_if_all_at_one_store": tot, "cheapest_mix": cheapest,
            "note": "Online prices; in-store prices are usually the same but can differ."}


def shopping_list_remove(item=None, everything=False):
    """Tick off or remove an item (or clear the whole list)."""
    lst = _load("shopping.json", [])
    if everything:
        _save("shopping.json", [])
        return {"cleared": len(lst)}
    q = (item or "").lower().strip()
    keep = [e for e in lst if not (q and (q in e["item"].lower() or q in e["term"]))]
    if len(keep) == len(lst):
        return {"error": f"'{item}' isn't on the list", "list": [e["item"] for e in lst]}
    _save("shopping.json", keep)
    return {"removed": len(lst) - len(keep), "left": [e["item"] for e in keep]}


# ---------- Bills and renewals ----------
EVERY = {"week": 7, "fortnight": 14, "month": 1, "quarter": 3, "year": 12, "once": 0}  # days for week/fortnight
PER_MONTH = {"week": 52 / 12, "fortnight": 26 / 12, "month": 1, "quarter": 1 / 3, "year": 1 / 12, "once": 0}


def _add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def _next(due, every):
    return due + datetime.timedelta(days=EVERY[every]) if every in ("week", "fortnight") else _add_months(due, EVERY[every])


def add_bill(name, due, amount=None, every="month"):
    """A bill or renewal. due: YYYY-MM-DD (the next time it's due). every: week, fortnight, month, quarter, year, once."""
    every = every.lower().strip()
    every = {"weekly": "week", "fortnightly": "fortnight", "monthly": "month", "quarterly": "quarter",
             "yearly": "year", "annually": "year", "annual": "year", "one-off": "once", "one off": "once"}.get(every, every)
    if every not in EVERY:
        return {"error": "every must be week, fortnight, month, quarter, year or once"}
    try:
        d = datetime.date.fromisoformat(due)
    except ValueError:
        return {"error": "due must be a date like 2026-12-01"}
    bills = _load("bills.json", {})
    bills[name.lower().strip()] = {"name": name, "due": d.isoformat(), "amount": amount, "every": every}
    _save("bills.json", bills)
    return {"added": name, "due": d.isoformat(), "every": every}


def _roll(bills, today):
    """Recurring bills more than 3 days past due move on to their next date (assumed paid)."""
    changed = False
    for b in bills.values():
        d = datetime.date.fromisoformat(b["due"])
        while b["every"] != "once" and (today - d).days > 3:
            d, changed = _next(d, b["every"]), True
        b["due"] = d.isoformat()
    return changed


def bills():
    """All bills and renewals, soonest first, with days left and the monthly total."""
    all_ = _load("bills.json", {})
    if _roll(all_, _today()):
        _save("bills.json", all_)
    out = sorted(({**b, "days_left": (datetime.date.fromisoformat(b["due"]) - _today()).days} for b in all_.values()),
                 key=lambda b: b["due"])
    total = sum(float(b["amount"] or 0) * PER_MONTH[b["every"]] for b in out)
    return {"bills": out, "monthly_total": round(total, 2)}


def bill_paid(name):
    """Mark a bill paid: a recurring one moves to its next due date, a one-off is removed."""
    all_ = _load("bills.json", {})
    k = _match(all_, name)
    if not k:
        return {"error": f"No bill called '{name}'", "bills": [b["name"] for b in all_.values()]}
    b = all_[k]
    if b["every"] == "once":
        del all_[k]
        _save("bills.json", all_)
        return {"paid": b["name"], "removed": True}
    b["due"] = _next(datetime.date.fromisoformat(b["due"]), b["every"]).isoformat()
    _save("bills.json", all_)
    return {"paid": b["name"], "next_due": b["due"]}


def remove_bill(name):
    all_ = _load("bills.json", {})
    k = _match(all_, name)
    if not k:
        return {"error": f"No bill called '{name}'"}
    del all_[k]
    _save("bills.json", all_)
    return {"removed": name}


def bill_warnings(today=None):
    """What to tell him today: bills due within a week (once) and tomorrow/today (once)."""
    today = today or _today()
    all_, state = _load("bills.json", {}), _load("state.json", {})
    warned = set(state.get("bills_warned", []))
    out = []
    for b in sorted(all_.values(), key=lambda b: b["due"]):
        left = (datetime.date.fromisoformat(b["due"]) - today).days
        amt = f" (${float(b['amount']):,.2f})" if b.get("amount") else ""
        for mark, when, ok in (("1", "is due tomorrow" if left == 1 else "is due today", 0 <= left <= 1),
                               ("7", f"is due in {left} days", 2 <= left <= 7)):
            key = f"{b['name']}|{b['due']}|{mark}"
            if ok and key not in warned and not (mark == "7" and f"{b['name']}|{b['due']}|1" in warned):
                warned.add(key)
                out.append(f"{b['name']}{amt} {when}")
    if out:
        state["bills_warned"] = sorted(warned)[-100:]
        _save("state.json", state)
    return out


# ---------- Habits ----------
def add_habit(name, per_week=7):
    """A habit to track, with how many days a week he's aiming for (7 = every day)."""
    h = _load("habits.json", {"habits": {}, "log": []})
    h["habits"][name.lower().strip()] = {"name": name, "per_week": max(1, min(7, int(per_week)))}
    _save("habits.json", h)
    return {"tracking": name, "per_week": h["habits"][name.lower().strip()]["per_week"]}


def log_habit(name, date=None, undo=False):
    """He did it (today, or date YYYY-MM-DD). New habits start being tracked automatically. undo removes a log."""
    h = _load("habits.json", {"habits": {}, "log": []})
    k = _match(h["habits"], name)
    if not k:
        k = name.lower().strip()
        h["habits"][k] = {"name": name, "per_week": 7}
    day = date or _today().isoformat()
    entry = {"habit": k, "date": day}
    if undo:
        h["log"] = [e for e in h["log"] if e != entry]
    elif entry not in h["log"]:
        h["log"].append(entry)
    h["log"] = h["log"][-3000:]
    _save("habits.json", h)
    return _status(h, k)


def _status(h, k):
    days = {datetime.date.fromisoformat(e["date"]) for e in h["log"] if e["habit"] == k}
    today, goal = _today(), h["habits"][k]["per_week"]
    week_start = today - datetime.timedelta(days=today.weekday())
    this_week = sum(week_start <= d <= today for d in days)
    if goal >= 7:  # daily: days in a row, still alive if yesterday counts
        d, streak = (today if today in days else today - datetime.timedelta(days=1)), 0
        while d in days:
            streak, d = streak + 1, d - datetime.timedelta(days=1)
        unit = "days"
    else:  # weekly goal: weeks in a row that hit it (this week counts once it's hit)
        streak, ws = 0, week_start if this_week >= goal else week_start - datetime.timedelta(days=7)
        while sum(ws <= d < ws + datetime.timedelta(days=7) for d in days) >= goal:
            streak, ws = streak + 1, ws - datetime.timedelta(days=7)
        unit = "weeks"
    last14 = "".join("x" if today - datetime.timedelta(days=i) in days else "." for i in range(13, -1, -1))
    return {"habit": h["habits"][k]["name"], "this_week": this_week, "goal_per_week": goal, "streak": streak,
            "streak_unit": unit, "last_14_days": last14, "done_today": today in days}


def habits(name=None):
    """How his habits are going: this week vs the goal, the streak, and the last 14 days (x = done)."""
    h = _load("habits.json", {"habits": {}, "log": []})
    if name:
        k = _match(h["habits"], name)
        return _status(h, k) if k else {"error": f"Not tracking '{name}'", "habits": list(h["habits"])}
    return {"habits": [_status(h, k) for k in h["habits"]]}


def remove_habit(name):
    h = _load("habits.json", {"habits": {}, "log": []})
    k = _match(h["habits"], name)
    if not k:
        return {"error": f"Not tracking '{name}'"}
    del h["habits"][k]
    _save("habits.json", h)  # the log is kept, so adding it back brings its history back
    return {"stopped_tracking": name}


# ---------- Clean-up crew ----------
def _size(p):
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _recycle_bin():
    import ctypes

    class Info(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]
    info = Info(ctypes.sizeof(Info), 0, 0)
    ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    return info.i64Size, info.i64NumItems


def _temp_dirs():
    return [Path(p) for p in {os.environ.get("TEMP", ""), os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Temp")}
            if p and Path(p).is_dir()]


def _old_downloads(days):
    cut, out = time.time() - days * 86400, []
    d = Path.home() / "Downloads"
    for f in (d.iterdir() if d.is_dir() else []):
        try:
            st = f.stat()
            if st.st_mtime < cut and st.st_atime < cut:
                out.append((f, st.st_size if f.is_file() else _size(f)))
        except OSError:
            pass
    return sorted(out, key=lambda x: -x[1])


MB = 1024 * 1024


def cleanup_scan(old_download_days=90):
    """What a clean-up would free, without deleting anything. Tell him, and only clean what he says yes to."""
    temp = sum(_size(p) for p in _temp_dirs())
    try:
        rb, rb_items = _recycle_bin()
    except Exception:
        rb, rb_items = 0, 0
    old = _old_downloads(old_download_days)
    _save("cleanup_scan.json", {"at": time.time(), "days": old_download_days})
    return {"temp_files_mb": round(temp / MB), "recycle_bin_mb": round(rb / MB), "recycle_bin_items": rb_items,
            "old_downloads_mb": round(sum(s for _, s in old) / MB), "old_downloads_count": len(old),
            "old_download_days": old_download_days,
            "biggest_old_downloads": [{"name": f.name, "mb": round(s / MB, 1)} for f, s in old[:8]],
            "next": "Ask which to clean: temp, recycle_bin, old_downloads. Old downloads go to the Recycle Bin."}


def cleanup_run(what):
    """Clean what he agreed to after a scan: any of temp, recycle_bin, old_downloads."""
    scan = _load("cleanup_scan.json", {})
    if time.time() - scan.get("at", 0) > 1800:
        return {"error": "Scan first (cleanup_scan) and tell him what it found before cleaning."}
    what = {w.lower().replace(" ", "_") for w in (what if isinstance(what, list) else [what])}
    freed, done = 0, {}
    if "recycle_bin" in what:  # emptied before old downloads go into it, so those can still be got back
        import ctypes
        size, _ = _recycle_bin()
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7)  # no confirm, no progress, no sound
        freed += size
        done["recycle_bin_mb"] = round(size / MB)
    if "temp" in what:
        n = 0
        for d in _temp_dirs():
            for p in d.iterdir():
                try:
                    if time.time() - p.stat().st_mtime < 86400:
                        continue  # in use by something running now, probably
                    s = p.stat().st_size if p.is_file() else _size(p)
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
                    freed, n = freed + s, n + s
                except OSError:
                    pass  # locked or needs admin: skip it
        done["temp_mb"] = round(n / MB)
    if "old_downloads" in what:
        old = _old_downloads(scan.get("days", 90))
        if old:
            paths = "','".join(str(f).replace("'", "''") for f, _ in old)
            ps = ("Add-Type -AssemblyName Microsoft.VisualBasic; foreach($p in @('" + paths + "')){ if(Test-Path "
                  "-LiteralPath $p -PathType Container){[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p,"
                  "'OnlyErrorDialogs','SendToRecycleBin')} else {[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
                  "$p,'OnlyErrorDialogs','SendToRecycleBin')} }")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=300,
                           creationflags=NO_WINDOW)
        moved = [(f, s) for f, s in old if not f.exists()]
        done["old_downloads_to_recycle_bin"] = len(moved)
        done["old_downloads_mb"] = round(sum(s for _, s in moved) / MB)
    _save("cleanup_scan.json", {})
    return {"cleaned": done, "freed_mb": round(freed / MB)}


# ---------- Game mode ----------
def memory_hogs(n=8):
    """The apps using the most memory right now, to help him pick what game mode should close."""
    import psutil
    use = {}
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            use[p.info["name"]] = use.get(p.info["name"], 0) + p.info["memory_info"].rss
        except (psutil.Error, TypeError, AttributeError):
            pass
    return [{"app": k, "mb": round(v / MB)} for k, v in sorted(use.items(), key=lambda x: -x[1])[:n]]


def game_mode(on=None, close=None):
    """Game mode: when a game starts, close the apps in close (e.g. ['chrome', 'spotify']), reopen them after.
    on: turn it on or off. close: the apps to close (replaces the list)."""
    s = features.settings()
    g = dict(s.get("game_mode") or {"on": False, "close": []})
    if close is not None:
        g["close"] = [c.lower().strip().removesuffix(".exe") + ".exe" for c in close if c.strip()]
        g["on"] = True if on is None else g["on"]
    if on is not None:
        g["on"] = bool(on)
    features._save("settings.json", {**s, "game_mode": g})
    return {**g, "note": "Closes them when a game starts and reopens them when it ends."}


class GameMode:
    """Called from the watcher with the current game (or None)."""
    def __init__(self):
        self.closed = None  # exe paths closed for the current game

    def tick(self, game):
        g = features.settings().get("game_mode") or {}
        if game and self.closed is None and g.get("on") and g.get("close"):
            import psutil
            paths, want = {}, set(g["close"])
            for p in psutil.process_iter(["name", "exe"]):
                n = (p.info["name"] or "").lower()
                if n in want and n not in paths and p.info["exe"]:
                    paths[n] = p.info["exe"]
            for n in paths:
                subprocess.run(["taskkill", "/IM", n], capture_output=True, creationflags=NO_WINDOW)  # like clicking X
            self.closed = list(paths.values())
            print(datetime.datetime.now(), "game mode closed:", list(paths))
        elif not game and self.closed is not None:
            for path in self.closed:
                try:
                    os.startfile(path)
                except OSError as e:
                    print(datetime.datetime.now(), "game mode couldn't reopen", path, repr(e))
            self.closed = None


# ---------- Find my file ----------
KINDS = {"pdf": {".pdf"}, "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp"},
         "video": {".mp4", ".mov", ".mkv", ".avi", ".webm"}, "audio": {".mp3", ".wav", ".m4a", ".flac"},
         "document": {".doc", ".docx", ".pdf", ".txt", ".odt", ".rtf", ".pages"},
         "spreadsheet": {".xls", ".xlsx", ".csv", ".ods"}, "slides": {".ppt", ".pptx", ".key"},
         "zip": {".zip", ".rar", ".7z"}, "program": {".exe", ".msi"}}
SKIP = {"appdata", "node_modules", ".git", "__pycache__", "$recycle.bin", "site-packages", ".venv", "venv"}


def _roots():
    home = Path.home()
    roots = [home / n for n in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")]
    roots += [p for p in home.glob("OneDrive*") if p.is_dir()]
    return [r for r in roots if r.is_dir()]


def find_files(query, kind=None, days=None, limit=8):
    """Search his folders (Desktop, Documents, Downloads, Pictures, Videos, Music, OneDrive) by file name.
    kind: pdf, image, video, audio, document, spreadsheet, slides, zip, program. days: changed in the last N days."""
    words = [w for w in query.lower().replace("_", " ").replace("-", " ").split() if w not in ("the", "a", "my", "file")]
    exts = KINDS.get((kind or "").lower().rstrip("s")) or KINDS.get((kind or "").lower())
    since = time.time() - days * 86400 if days else 0
    found, seen, start = [], set(), time.time()
    for root in _roots():
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP and not d.startswith(".")]
            for f in files:
                low = f.lower().replace("_", " ").replace("-", " ")
                if (exts and os.path.splitext(low)[1] not in exts) or not all(w in low for w in words):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if st.st_mtime >= since and p not in seen:
                    seen.add(p)
                    found.append((st.st_mtime, p, st.st_size))
            if time.time() - start > 8:
                break
    found.sort(reverse=True)
    return {"files": [{"name": os.path.basename(p), "folder": os.path.dirname(p), "path": p,
                       "modified": time.strftime("%Y-%m-%d", time.localtime(m)), "kb": round(s / 1024)}
                      for m, p, s in found[:limit]], "count": len(found)}


def open_file(path, show_in_folder=False):
    """Open a file he found (or show it selected in File Explorer)."""
    p = Path(path)
    if not p.exists():
        return {"error": f"There's no file at {path}"}
    if show_in_folder:
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        os.startfile(str(p))
    return {"opened": p.name}


# ---------- For the watcher ----------
_game = GameMode()


def tick(game):
    """Every 10 s from Jarvis's watcher: game mode, and bill warnings (returns lines to say)."""
    _game.tick(game)
    return [f"Heads up, {{TITLE}}: {w}." for w in bill_warnings()]


FUNCS = {f.__name__: f for f in (recipe, show_recipe, price_check, shopping_list_add, shopping_list,
                                 shopping_list_remove, add_bill, bills, bill_paid, remove_bill, add_habit, log_habit,
                                 habits, remove_habit, cleanup_scan, cleanup_run, memory_hogs, game_mode, find_files,
                                 open_file)}
TOOLS = [
    {"name": "recipe", "description": "Show a recipe on his HUD (it stays up while he cooks). For 'what can I make "
     "with...' / meal ideas: first suggest 2-3 quick ideas out loud, then show the one he picks, then straight away "
     "shopping_list_add the missing ingredients so he gets a priced shopping list. ingredients with amounts, short "
     "steps, and missing = the ingredients he didn't say he has.",
     "input_schema": {"type": "object", "required": ["title", "ingredients", "steps"], "properties": {
         "title": S, "ingredients": {"type": "array", "items": S}, "steps": {"type": "array", "items": S},
         "minutes": I, "serves": I, "missing": {"type": "array", "items": S}}}},
    {"name": "shopping_list_add", "description": "Add groceries to his shopping list, with today's Woolworths and "
     "Coles prices (cheapest store per item and the totals), shown on his HUD. items: plain grocery names "
     "('soy sauce', 'spring onions'); recipe: what they're for. Tell him the cheapest total and where; takes a few "
     "seconds.", "input_schema": {"type": "object", "required": ["items"], "properties": {
         "items": {"type": "array", "items": S}, "recipe": S}}},
    {"name": "shopping_list", "description": "Show his shopping list with prices and totals.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "shopping_list_remove", "description": "Tick off / remove an item from the shopping list, or "
     "everything=true to clear it.", "input_schema": {"type": "object", "properties": {
         "item": S, "everything": {"type": "boolean"}}}},
    {"name": "price_check", "description": "How much groceries cost right now at Woolworths and Coles.",
     "input_schema": {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": S}}}},
    {"name": "show_recipe", "description": "Show a recipe from before again (the last one, or by name).",
     "input_schema": {"type": "object", "properties": {"title": S}}},
    {"name": "add_bill", "description": "Track a bill or renewal (rego, insurance, phone, subscriptions). Jarvis warns "
     "a week before and the day before. due = next due date YYYY-MM-DD; every = week, fortnight, month, quarter, "
     "year or once; amount in dollars if known.",
     "input_schema": {"type": "object", "required": ["name", "due"], "properties": {
         "name": S, "due": S, "amount": {"type": "number"}, "every": S}}},
    {"name": "bills", "description": "His bills and renewals, soonest first, and the monthly total.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "bill_paid", "description": "He paid a bill: moves it to its next due date.",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S}}},
    {"name": "remove_bill", "description": "Stop tracking a bill.",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S}}},
    {"name": "add_habit", "description": "Start tracking a habit with a weekly goal (per_week 1-7, 7 = daily).",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S, "per_week": I}}},
    {"name": "log_habit", "description": "He did a habit ('I went to the gym', 'drank my water'). Today unless date "
     "(YYYY-MM-DD) is given; undo removes a log. Tell him the streak / this week vs the goal.",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S, "date": S,
                                                                            "undo": {"type": "boolean"}}}},
    {"name": "habits", "description": "How his habits are going: this week vs the goal, streaks, last 14 days. A "
     "progress panel suits it.", "input_schema": {"type": "object", "properties": {"name": S}}},
    {"name": "remove_habit", "description": "Stop tracking a habit.",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S}}},
    {"name": "cleanup_scan", "description": "'Clean up my PC': see how much space temp files, the Recycle Bin and "
     "old downloads (untouched for old_download_days, default 90) take, deleting nothing. Tell him, mention the "
     "biggest old downloads, and ask which to clean.",
     "input_schema": {"type": "object", "properties": {"old_download_days": I}}},
    {"name": "cleanup_run", "description": "Clean ONLY what he said yes to after cleanup_scan: what = any of temp, "
     "recycle_bin, old_downloads. Old downloads go to the Recycle Bin; emptying the Recycle Bin is permanent, so "
     "only with his clear yes.",
     "input_schema": {"type": "object", "required": ["what"], "properties": {"what": {"type": "array", "items": S}}}},
    {"name": "memory_hogs", "description": "The apps using the most memory right now (to pick what game mode closes).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "game_mode", "description": "Game mode: when a game starts, close the apps he picked (close: names like "
     "chrome, spotify, onedrive) and reopen them when it ends. on turns it on/off.",
     "input_schema": {"type": "object", "properties": {"on": {"type": "boolean"},
                                                       "close": {"type": "array", "items": S}}}},
    {"name": "find_files", "description": "Find a file on his PC by name words ('the bank PDF from last month' -> "
     "query 'bank', kind pdf, days 45). Searches Desktop, Documents, Downloads, Pictures, Videos, Music and OneDrive. "
     "If nothing matches, try fewer or different words.",
     "input_schema": {"type": "object", "required": ["query"], "properties": {"query": S, "kind": S, "days": I}}},
    {"name": "open_file", "description": "Open a file (path from find_files), or show_in_folder to show it in File "
     "Explorer.", "input_schema": {"type": "object", "required": ["path"], "properties": {
         "path": S, "show_in_folder": {"type": "boolean"}}}},
]


def selftest():
    import tempfile
    real = features.HERE
    features.HERE = Path(tempfile.mkdtemp())
    try:
        global _today
        today = datetime.date(2026, 11, 5)
        real_today, _today = _today, lambda: today
        assert _add_months(datetime.date(2026, 1, 31), 1) == datetime.date(2026, 2, 28)
        assert add_bill("Car rego", "2026-11-12", 420, "year")["every"] == "year"
        assert add_bill("Netflix", "2026-11-06", 18.99, "monthly")["every"] == "month"
        assert add_bill("Phone", "2026-10-20", 45, "month")["due"] == "2026-10-20"
        b = bills()
        assert [x["name"] for x in b["bills"]] == ["Netflix", "Car rego", "Phone"]  # phone rolled to 20 Nov
        assert b["bills"][2]["due"] == "2026-11-20" and b["monthly_total"] == round(420 / 12 + 18.99 + 45, 2)
        assert bill_warnings(today) == ["Netflix ($18.99) is due tomorrow", "Car rego ($420.00) is due in 7 days"]
        assert bill_warnings(today) == []  # once each
        assert bill_paid("netflix")["next_due"] == "2026-12-06"
        assert "error" in add_bill("x", "soon")
        log_habit("gym", "2026-11-03")
        log_habit("gym", "2026-11-04")
        s = log_habit("Gym")
        assert (s["streak"], s["this_week"], s["done_today"]) == (3, 3, True) and s["last_14_days"].endswith("xxx")
        add_habit("run", 3)
        for d in ("2026-10-27", "2026-10-28", "2026-10-29", "2026-11-03"):
            log_habit("run", d)
        r = habits("running")
        assert (r["streak"], r["streak_unit"], r["this_week"]) == (1, "weeks", 1)
        assert log_habit("gym", undo=True)["done_today"] is False
        assert recipe.__name__ and "error" in show_recipe("nothing")
        recipe("Fried rice", ["2 cups rice"], ["Fry it"], missing=["soy sauce"])
        assert show_recipe()["shown"] == "Fried rice"
        assert [_term(x) for x in ("2 tbsp soy sauce", "300 g chicken thigh, diced", "Spring onions", "1 can of coconut milk")] \
            == ["soy sauce", "chicken thigh", "spring onions", "coconut milk"]
        global _shop
        real_shop = _shop
        _shop = lambda terms: {"Woolworths": {t: [{"name": f"WW {t}", "price": 3.5, "available": True}] for t in terms},
                               "Coles": {"soy sauce": [{"name": "Coles soy", "price": 2.8, "available": True},
                                                       {"name": "Out of stock", "price": 1, "available": False}]}}
        r = shopping_list_add(["2 tbsp soy sauce", "spring onions"], recipe="Fried rice")
        assert r["totals_if_all_at_one_store"] == {"Coles": 2.8, "Woolworths": 7.0} and r["cheapest_mix"] == 6.3
        assert r["items"][0]["best"]["store"] == "Coles" and "price_problems" not in r
        assert shopping_list_remove("soy")["left"] == ["spring onions"]
        _shop = lambda terms: (_ for _ in ()).throw(OSError("down"))
        assert shopping_list_add(["milk"])["price_problems"] and len(shopping_list()["items"]) == 2  # listed anyway
        _shop = real_shop
        assert "error" in cleanup_run(["temp"])  # never without a scan first
        assert game_mode(close=["Chrome", "spotify.exe"])["close"] == ["chrome.exe", "spotify.exe"]
        home = Path(tempfile.mkdtemp())
        (home / "Documents" / "bank").mkdir(parents=True)
        (home / "Documents" / "bank" / "CommBank_Statement_Oct.pdf").write_text("x")
        (home / "Documents" / "notes.txt").write_text("x")
        (home / "AppData").mkdir()
        (home / "AppData" / "bank statement.pdf").write_text("x")
        real_home, Path.home = Path.home, lambda: home
        try:
            f = find_files("bank statement", kind="pdf")
            assert [x["name"] for x in f["files"]] == ["CommBank_Statement_Oct.pdf"]
            assert find_files("statement", kind="image")["count"] == 0
        finally:
            Path.home = real_home
        _today = real_today
    finally:
        features.HERE = real
    print("life self-test passed")


if __name__ == "__main__":
    selftest()
