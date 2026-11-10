"""Things that only the running Jarvis (server.py) can do, reachable from tool calls too (each tool call is its own
process): IN_SERVER is True inside Jarvis; elsewhere post() asks the running Jarvis over its local API."""
import json
import urllib.request

IN_SERVER = False
_say = None  # set by server.py: Jarvis speaks up (or holds it while he's away or gaming)


def say(text):
    if _say:
        _say(text)


def post(path, body, timeout=60):
    req = urllib.request.Request("http://127.0.0.1:8765" + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())
