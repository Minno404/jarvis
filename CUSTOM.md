# Building your own additions to Jarvis

Everything in the `custom/` folder is yours. Updates never change or delete it, so anything built there
(new panels, extra stats, new tools, a different look) carries over to every new version.

**Never edit Jarvis's core files** (`*.py` in the main folder, `web/index.html`, `updater.py`, `README.md`):
every update replaces them, and edited ones can stop updates working. Put everything in `custom/` instead.
A broken add-on is skipped (and noted in the browser console / jarvis.log); Jarvis still starts.

## Files you can add to `custom/`

| File | What it does |
|---|---|
| `something.js` | Runs in the HUD after it loads (PC and phone). Add panels, rows, behaviour. |
| `something.css` | Extra styles for the HUD. Loaded after the built-in ones, so they can override them. |
| `something.py` | Python add-on: extra live stats for the HUD, and/or new tools Jarvis can use. |

Restart Jarvis after adding or changing a `.py` file. `.js` and `.css` changes show on the next page load.

## HUD helpers (in `custom/*.js`)

```js
// A new side panel: movable, resizable, closable, and remembered like the built-in ones.
// "show the <title>" / "close the <title>" work by voice straight away.
const p = JarvisHUD.addPanel({id: 'taskmgr', title: 'Task manager', side: 'right', html: '<div id="tmRows"></div>'});

// Live PC stats every 2 seconds. d has cpu_percent, ram_percent, gpu_percent, gpu_temp_c... plus anything
// your custom/*.py STATS() returns.
JarvisHUD.onStats(d => { document.getElementById('tmRows').textContent = d.cpu_percent + '%'; });

// Add rows to a built-in panel: 'time', 'systems', 'protocols', 'mt5', 'journal', 'report'
JarvisHUD.panel('systems').append(JarvisHUD.row('Uptime', 'upVal'));   // then set #upVal's text in onStats

JarvisHUD.esc(text)   // escape text before putting it in HTML
```

Use the HUD's own classes so it matches: `.row` (label / value line), `.bar > i` (a progress bar; set the
`i`'s width in %), `h2` (panel title). Colours: `var(--cyan)` (the theme colour), `var(--mute)`,
`var(--text)`, `var(--amber)`, `var(--red)`.

## Python add-ons (`custom/*.py`)

```python
import psutil

def STATS():
    """Merged into the stats the HUD gets every 2 seconds. Keep it fast (well under 100 ms)."""
    return {"uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1)}

# New tools Jarvis can use, the same shape as the built-in ones
def battery():
    b = psutil.sensors_battery()
    return {"percent": b.percent if b else None}

FUNCS = {"battery": battery}
TOOLS = [{"name": "battery", "description": "The laptop battery level.",
          "input_schema": {"type": "object", "properties": {}}}]
```

`import features` gives you Jarvis's helpers (settings, memory, `features.HERE` for the folder).
