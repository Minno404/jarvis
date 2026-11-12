"""Panels built by describing them: "make a panel that shows fuel prices near me".

make_panel(description): Claude Sonnet writes one small web page (HTML, CSS, JavaScript) for the panel, in about half
a minute; it appears on the HUD and stays (live_panels.json). "Change the fuel panel to ..." rewrites it;
"remove the fuel panel" deletes it.
Safety: the page runs in a sandboxed frame. It can't reach Jarvis, his files, cookies or the rest of the HUD. Its
only way out is two helpers the HUD answers for it:
- jarvis.tool(name, args): a short list of read-only tools (TOOLS_OK below: shifts, pay, account, prices, weather,
  web search...). Nothing that changes, sends, trades or deletes.
- jarvis.get(url): fetch a public https page or API as text, through Jarvis (no addresses on his home network, GET
  only, 500 KB at most).
"""
import datetime
import ipaddress
import json
import re
import socket
import threading
import urllib.parse
import urllib.request

import features

FILE = "live_panels.json"
TOOLS_OK = {"week_shifts": {"show": False}, "my_shifts": {"show": False}, "pay_estimate": {}, "account_status": {},
            "market_snapshot": {}, "mt5_report": {}, "mt5_trades": {}, "weather": {}, "web_search": {},
            "upcoming_news": {}, "list_reminders": {}, "experiment_report": {"show": False}}

WRITE = """Write a small live panel for {USER}'s Jarvis HUD: {description}
{previous}
It's one HTML fragment (no <html> or <body>): a <style> block, the markup, and a <script>. It runs alone in a
sandboxed frame about 300 px wide on a dark, see-through background: use color: var(--text), accents var(--cyan),
muted var(--mute), font inherit, compact rows, no external libraries, images or fonts.
Data comes only from these two helpers (both return promises):
- jarvis.tool(name, args) -> the tool's JSON result. Tools: week_shifts() {{days:[{{date,shifts:[{{start,end,hours}}],off,note}}]}},
  my_shifts({{days}}), pay_estimate({{weeks_ahead,weeks}}), account_status() (MT5 balance, equity, open positions),
  market_snapshot({{symbols:["XAUUSD"]}}) (bid/ask, ranges), mt5_report({{since}}), mt5_trades({{limit}}),
  weather({{place}}), web_search({{query}}) (search results with snippets), upcoming_news({{hours}}), list_reminders().
- jarvis.get(url) -> the text of a public https URL (parse JSON yourself). Use real, keyless public APIs you are
  sure exist; if the data needs a key or you're unsure of an API, use web_search and show the top results instead.
Refresh itself on a sensible timer (not faster than every 60 s; prices may use 15 s). Show "Loading..." first and a
short plain message if something fails. What he knows about him, if a location or preference is needed: {about}
Reply with JSON only: {{"title": "2-4 words", "html": "..."}}"""


def _load():
    return features._load(FILE, {})


def _id(title):
    return "live-" + (re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:30] or "panel")


def _write(description, previous=None):
    import council
    q = features.personal(WRITE).format(
        description=description, about=features.memory_prompt().strip()[:1200] or "(nothing)",
        previous=f"This replaces the current version; keep what works and apply the change. Current code:\n{previous}\n" if previous else "")
    out = council._json(council._claude(q, "sonnet")) or {}
    if not out.get("html"):
        raise RuntimeError("no panel came back")
    return str(out.get("title") or "Panel")[:40], out["html"]


def _build(description, pid=None):
    import server_bridge
    try:
        d = _load()
        old = d.get(pid) if pid else None
        title, html = _write(description if not old else f"{old['description']}. Change: {description}", old and old["html"])
        pid = pid or _id(title)
        d[pid] = {"id": pid, "title": old["title"] if old else title, "html": html,
                  "description": description if not old else f"{old['description']}. {description}",
                  "made": datetime.datetime.now().isoformat(timespec="minutes")}
        features._save(FILE, d)
        features._panel({"type": "live_panel", **d[pid]})
        server_bridge.say(f"Your {d[pid]['title']} panel is {'updated' if old else 'up'}, {{TITLE}}.")
    except Exception as e:
        server_bridge.say(f"I couldn't build that panel, {{TITLE}}: {str(e)[:100]}")


def make_panel(description):
    """Build a new live panel from a description (appears on the HUD in about half a minute)."""
    threading.Thread(target=_build, args=(description,), daemon=True).start()
    return {"building": True, "note": "Writing it now; it appears on the HUD in about half a minute."}


def _find(name):
    d = _load()
    n = _id(name)
    return next((k for k in d if k == n or n[5:] in k or name.lower() in d[k]["title"].lower()), None)


def change_panel(name, change):
    """Rewrite one of his live panels with a change."""
    pid = _find(name)
    if not pid:
        return {"error": f"No live panel called {name}.", "panels": [p["title"] for p in _load().values()]}
    threading.Thread(target=_build, args=(change, pid), daemon=True).start()
    return {"rebuilding": _load()[pid]["title"]}


def remove_panel(name):
    pid = _find(name)
    if not pid:
        return {"error": f"No live panel called {name}.", "panels": [p["title"] for p in _load().values()]}
    d = _load()
    d.pop(pid)
    features._save(FILE, d)
    features._panel({"type": "live_panel", "id": pid, "remove": True})
    return {"removed": pid}


def live_panels():
    return {"panels": list(_load().values())}


# ---------- What a panel's frame may ask for ----------
def _public(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or not u.hostname:
        raise ValueError("https addresses only")
    for info in socket.getaddrinfo(u.hostname, 443):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("that address isn't on the public internet")
    return url


def panel_call(panel, kind, name="", args=None, url=""):
    """One request from a live panel's frame: a read-only tool, or a public web page."""
    if panel not in _load():
        return {"error": "unknown panel"}
    try:
        if kind == "tool":
            if name not in TOOLS_OK or name not in features.REGISTRY:
                return {"error": f"panels can't use {name}"}
            ok = {k: v for k, v in (args or {}).items() if isinstance(v, (str, int, float, bool, list))}
            return {"result": json.loads(json.dumps(features.REGISTRY[name](**{**ok, **TOOLS_OK[name]}), default=str))}
        if kind == "get":
            req = urllib.request.Request(_public(url), headers={"User-Agent": "Jarvis/1.0 (personal assistant panel)"})

            class NoRedirect(urllib.request.HTTPRedirectHandler):  # a redirect could point back inside his network
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    _public(newurl)
                    return super().redirect_request(req, fp, code, msg, headers, newurl)
            with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as r:
                return {"result": r.read(500_000).decode("utf-8", "ignore")}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:200]}
    return {"error": "unknown request"}


FUNCS = {"make_panel": make_panel, "change_panel": change_panel, "remove_panel": remove_panel, "live_panels": live_panels}
S = {"type": "string"}
TOOLS = [
    {"name": "make_panel", "description": "Build a new live panel on his HUD from a description ('make a panel that "
     "shows fuel prices near me', 'a panel with gold's price and my open trades'). It writes itself in about half a "
     "minute and stays. description: everything he said he wants on it.",
     "input_schema": {"type": "object", "required": ["description"], "properties": {"description": S}}},
    {"name": "change_panel", "description": "Change a live panel he had built ('make the fuel panel show only diesel').",
     "input_schema": {"type": "object", "required": ["name", "change"], "properties": {"name": S, "change": S}}},
    {"name": "remove_panel", "description": "Delete a live panel he had built.",
     "input_schema": {"type": "object", "required": ["name"], "properties": {"name": S}}},
]
COMMANDS = {"Panels": ["Make a panel that shows gold's price and my open trades", "Remove the fuel panel"]}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    features.HERE = Path(tempfile.mkdtemp())
    import council
    import server_bridge
    said, shown = [], []
    server_bridge.say = said.append
    features._panel = shown.append
    council._claude = lambda q, model="": json.dumps({"title": "Fuel prices", "html": "<div id=f>Loading...</div>" + ("<b>diesel</b>" if "Change:" in q else "")})
    _build("fuel prices near me")
    assert shown[-1]["type"] == "live_panel" and shown[-1]["id"] == "live-fuel-prices" and "is up" in said[-1]
    _build("only diesel", _find("fuel"))
    assert "diesel" in _load()["live-fuel-prices"]["html"] and "updated" in said[-1] and len(_load()) == 1
    features.REGISTRY.update(week_shifts=lambda show=True: {"show": show}, set_day=lambda **k: {"bad": 1})
    assert panel_call("live-fuel-prices", "tool", "week_shifts", {"show": True}) == {"result": {"show": False}}
    assert "can't use" in panel_call("live-fuel-prices", "tool", "set_day", {})["error"]
    assert panel_call("nope", "tool", "week_shifts")["error"] == "unknown panel"
    for bad in ("http://example.com", "https://127.0.0.1/x", "https://192.168.1.1/", "https://localhost/"):
        assert "error" in panel_call("live-fuel-prices", "get", url=bad), bad
    assert remove_panel("fuel")["removed"] and shown[-1]["remove"] and not _load()
    print("panelsmith self-test passed")
