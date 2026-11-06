"""The floating mini Jarvis: a see-through, always-on-top reactor core drawn with Tk.

Everything that isn't a ring is a hole in the window, so you see and click the app underneath.
Drag the core to move it, scroll over it to resize, click it to type to Jarvis, double-click to
open the full window. All Tk calls stay on the Tk thread; other threads talk to it through `send`.
"""
import math
import queue
import random
import threading
import time

KEY = "#010203"  # this exact colour is see-through and click-through
CYAN, DIM, AMBER, AMBER_DIM = "#5fe3ff", "#2a8fb0", "#ffb347", "#a8742c"
GLOW = ["#0b3a4a", "#145f75", "#1f8aa6", "#3bbfe0"]  # inner glow, outside in
GLOW_AMBER = ["#4a320b", "#755014", "#a6721f", "#e0a03b"]


def palette(hexc):
    """(bright, dim, glow steps) for the HUD's accent colour, so the mini core matches the main window."""
    h = hexc.lstrip("#")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    mix = lambda k: "#" + "".join(f"{max(4, round(v * k)):02x}" for v in rgb)  # never the see-through key colour
    return "#" + h.lower(), mix(.5), [mix(k) for k in (.19, .33, .55, .78)]
RINGS = [(110, 10, 6, 1, .7), (170, 3, 3, -.6, .85), (230, 14, 24, .35, .5),
         (300, 2, 2, -.25, .9), (350, 6, 60, .15, .35), (395, 1.5, 1, 0, 1)]  # radius, width, arcs, speed, fill

_q = queue.Queue()
pin_events = {"moved": None, "close": None}  # set by server.py: moved(pid, x, y, w, h), close(pid)


def send(cmd, *args):
    """Thread-safe: 'show', 'hide', 'mode' <idle|thinking|speaking|listening>, 'quit'."""
    _q.put((cmd, args))


def start(on_ask, on_open, size=170, on_mute=None):
    """on_mute(): the mic button was clicked (toggle mute); send('muted', on) shows the result."""
    threading.Thread(target=_run, args=(on_ask, on_open, size, on_mute), daemon=True).start()


def _run(on_ask, on_open, size, on_mute=None):
    import ctypes
    import tkinter as tk

    root = tk.Tk()
    root.attributes("-alpha", 0.0)  # invisible until hidden properly below (no flash at startup)
    root.overrideredirect(True)  # no frame
    root.wm_attributes("-topmost", True)
    root.wm_attributes("-transparentcolor", KEY)
    root.configure(bg=KEY)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    st = {"size": size, "mode": "idle", "t": 0.0, "level": 0.0, "target": 0.0, "next": 0.0,
          "colours": (CYAN, DIM, GLOW), "x": sw - size - 40, "y": sh - size - 110, "drag": None, "moved": False,
          "muted": False}
    cv = tk.Canvas(root, bg=KEY, highlightthickness=0, bd=0)
    cv.pack(fill="both", expand=True)
    entry = tk.Entry(root, bg="#03070c", fg="#cdeefb", insertbackground="#5fe3ff", relief="flat",
                     highlightthickness=1, highlightbackground="#1c5a78", highlightcolor="#5fe3ff",
                     font=("Consolas", 10))

    def place():
        s = st["size"]
        root.geometry(f"{s}x{s}+{int(st['x'])}+{int(st['y'])}")

    place()
    root.update()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    ctypes.windll.user32.ShowWindow(hwnd, 0)  # start hidden
    root.attributes("-alpha", 1.0)

    def show(on):
        if on:
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x13)  # topmost, no move/size/focus
        ctypes.windll.user32.ShowWindow(hwnd, 4 if on else 0)  # SW_SHOWNOACTIVATE / SW_HIDE
        if not on:
            entry.place_forget()

    # --- input ---
    def buttons():
        """The two little buttons above the core: (centre x, centre y, radius) for '-' (hide) and the mic (mute)."""
        s = st["size"]
        r = max(9, s * .075)
        return (s * .12, s * .12, r), (s * .88, s * .12, r)

    def hit(b, e):
        return (e.x - b[0]) ** 2 + (e.y - b[1]) ** 2 <= (b[2] + 3) ** 2

    def press(e):
        hide_b, mic_b = buttons()
        if hit(hide_b, e):
            st["drag"] = "hide"
            return
        if hit(mic_b, e):
            st["drag"] = "mic"
            return
        st["drag"], st["moved"] = (e.x_root - st["x"], e.y_root - st["y"]), False

    def motion(e):
        if isinstance(st["drag"], tuple):
            st["x"], st["y"], st["moved"] = e.x_root - st["drag"][0], e.y_root - st["drag"][1], True
            place()

    def release(e):
        d, st["drag"] = st["drag"], None
        if d == "hide":  # tucked away until Jarvis is minimised again (or "Mini core" in the tray)
            show(False)
            return
        if d == "mic":
            if on_mute:
                threading.Thread(target=on_mute, daemon=True).start()
            return
        if not st["moved"]:  # a click, not a drag: open the input box
            s = st["size"]
            entry.place(x=s * .15, y=s * .72, width=s * .7, height=max(20, s * .13))
            entry.focus_force()

    def wheel(e):
        old = st["size"]
        st["size"] = max(110, min(520, round(old * (1.1 if e.delta > 0 else 0.9))))
        st["x"] -= (st["size"] - old) / 2  # grow around the centre
        st["y"] -= (st["size"] - old) / 2
        place()

    def submit(e):
        text = entry.get().strip()
        entry.delete(0, "end")
        entry.place_forget()
        if text:
            threading.Thread(target=on_ask, args=(text,), daemon=True).start()

    cv.bind("<ButtonPress-1>", press)
    cv.bind("<B1-Motion>", motion)
    cv.bind("<ButtonRelease-1>", release)
    cv.bind("<Double-Button-1>", lambda e: threading.Thread(target=on_open, daemon=True).start())
    cv.bind("<MouseWheel>", wheel)
    entry.bind("<Return>", submit)
    entry.bind("<Escape>", lambda e: entry.place_forget())

    # --- drawing (same rings as the main window's core) ---
    def draw():
        s, mode = st["size"], st["mode"]
        st["t"] += 0.04 if mode == "thinking" else 0.012
        now = time.time()
        if mode == "listening":  # a steady breathing pulse while he listens to you
            st["target"] = .25 + .15 * math.sin(now * 6)
        elif mode == "speaking":  # syllable-like pulses while Jarvis talks
            if now > st["next"]:
                st["target"] = 0 if random.random() < .15 else .35 + random.random() * .65
                st["next"] = now + .07 + random.random() * .11
        else:
            st["target"] = 0
        st["level"] += (st["target"] - st["level"]) * .25
        lv, t, k, c = st["level"], st["t"], s / 840, s / 2
        bright, dim, glow = (AMBER, AMBER_DIM, GLOW_AMBER) if mode == "thinking" else st["colours"]
        pulse = lv * 70 + math.sin(t * 2) * 6
        cv.delete("all")
        for i, col in enumerate(glow):  # soft centre, as stepped discs
            r = (90 + pulse) * k * (1 - i * .2)
            cv.create_oval(c - r, c - r, c + r, c + r, fill=col, outline="")
        r = (36 + pulse * .5) * k
        cv.create_oval(c - r, c - r, c + r, c + r, fill=bright, outline="")
        for i, (rad, w, n, spd, f) in enumerate(RINGS):
            R = rad * (1 + lv * (.15 if i < 3 else .04)) * k
            col = bright if i % 2 else dim
            for j in range(n):
                a = math.degrees(t * spd) + j * 360 / n
                cv.create_arc(c - R, c - R, c + R, c + R, start=-a, extent=-(360 / n) * f,
                              style="arc", outline=col, width=max(1, w * k * 1.6))
        hide_b, mic_b = buttons()  # the "-" and the mic, drawn on solid discs so they can be clicked
        red = "#ff5c6c"
        for (x, y, r), col in ((hide_b, dim), (mic_b, red if st["muted"] else dim)):
            cv.create_oval(x - r, y - r, x + r, y + r, fill="#06121a", outline=col, width=1)
        x, y, r = hide_b
        cv.create_line(x - r * .45, y, x + r * .45, y, fill=bright, width=max(1, r * .16))
        x, y, r = mic_b  # a microphone: capsule, cradle and stand; struck through when muted
        mc = red if st["muted"] else bright
        cv.create_rectangle(x - r * .18, y - r * .55, x + r * .18, y + r * .08, fill=mc, outline="")
        cv.create_arc(x - r * .38, y - r * .45, x + r * .38, y + r * .3, start=200, extent=140, style="arc", outline=mc,
                      width=max(1, r * .1))
        cv.create_line(x, y + r * .3, x, y + r * .55, fill=mc, width=max(1, r * .1))
        if st["muted"]:
            cv.create_line(x - r * .55, y + r * .55, x + r * .55, y - r * .55, fill=red, width=max(1, r * .14))
        if st["muted"]:
            cv.create_text(c, s * .93, text="MUTED", fill="#ff5c6c", font=("Bahnschrift SemiBold", max(7, int(s * .055))))
        for j in range(72):
            a = j / 72 * math.tau - t * .1
            r1, r2 = 410 * k, (410 - (8 if j % 6 else 20)) * k
            cv.create_line(c + math.cos(a) * r1, c + math.sin(a) * r1, c + math.cos(a) * r2,
                           c + math.sin(a) * r2, fill=dim, width=1)

    # --- pinned panels: see-through floating copies of HUD panels (drawn here so they can fade) ---
    pins, pin_st = {}, {"visible": False, "alpha": 0.6}
    MUTE, TEXT, BG = "#6f9fb4", "#cdeefb", "#08151d"

    def pin_add(pid, title, x=None, y=None, w=300, h=260):
        if pid in pins:
            return
        top = tk.Toplevel(root)
        top.overrideredirect(True)
        top.wm_attributes("-topmost", True)
        top.attributes("-alpha", pin_st["alpha"])
        top.configure(bg=BG)
        x = sw - w - 40 - 320 * len(pins) if x is None else x
        y = 60 if y is None else y
        top.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        c = tk.Canvas(top, bg=BG, highlightthickness=0, bd=0)
        c.pack(fill="both", expand=True)
        top.update()
        p = {"top": top, "cv": c, "title": title, "rows": [], "hwnd": ctypes.windll.user32.GetParent(top.winfo_id()),
             "drag": None}
        pins[pid] = p

        def press(e):
            w_, h_ = top.winfo_width(), top.winfo_height()
            if e.x > w_ - 26 and e.y < 24:  # the x: unpin
                p["drag"] = ("close",)
            elif e.x > w_ - 18 and e.y > h_ - 18:  # the corner grip: resize
                p["drag"] = ("size", e.x_root, e.y_root, w_, h_)
            else:
                p["drag"] = ("move", e.x_root - top.winfo_x(), e.y_root - top.winfo_y())

        def motion(e):
            d = p["drag"]
            if d and d[0] == "move":
                top.geometry(f"+{e.x_root - d[1]}+{e.y_root - d[2]}")
            elif d and d[0] == "size":
                top.geometry(f"{max(180, d[3] + e.x_root - d[1])}x{max(110, d[4] + e.y_root - d[2])}")
                pin_draw(pid)

        def release(e):
            d, p["drag"] = p["drag"], None
            if d and d[0] == "close":
                if pin_events["close"]:
                    threading.Thread(target=pin_events["close"], args=(pid,), daemon=True).start()
            elif d and pin_events["moved"]:
                pin_events["moved"](pid, top.winfo_x(), top.winfo_y(), top.winfo_width(), top.winfo_height())
        c.bind("<ButtonPress-1>", press)
        c.bind("<B1-Motion>", motion)
        c.bind("<ButtonRelease-1>", release)
        ctypes.windll.user32.ShowWindow(p["hwnd"], 4 if pin_st["visible"] else 0)
        pin_draw(pid)

    def pin_draw(pid):
        p = pins.get(pid)
        if not p:
            return
        c, bright, dim = p["cv"], st["colours"][0], st["colours"][1]
        w, h = p["top"].winfo_width(), p["top"].winfo_height()
        c.delete("all")
        c.create_rectangle(0, 0, w - 1, h - 1, outline=dim)
        c.create_line(12, 0, 52, 0, fill=bright, width=2)
        c.create_text(12, 14, text=p["title"].upper(), fill=bright, anchor="w", font=("Bahnschrift SemiBold", 9))
        c.create_text(w - 12, 13, text="\u00d7", fill=MUTE, anchor="e", font=("Consolas", 11))
        y, inner = 32, w - 24
        for r in p["rows"]:
            if y > h - 14:
                break
            if "h" in r:
                y += 4
                c.create_text(12, y, text=str(r["h"]).upper(), fill=bright, anchor="w", font=("Bahnschrift SemiBold", 8))
                y += 16
            elif "bar" in r:
                c.create_rectangle(12, y - 6, 12 + inner, y - 3, fill="#12303e", outline="")
                c.create_rectangle(12, y - 6, 12 + inner * max(0, min(100, float(r["bar"]))) / 100, y - 3,
                                   fill=bright, outline="")
                y += 6
            elif "l" in r:
                c.create_text(12, y, text=str(r["l"])[:40], fill=MUTE, anchor="w", font=("Consolas", 9))
                c.create_text(w - 12, y, text=str(r.get("v", ""))[:30], fill=r.get("vc") or TEXT, anchor="e",
                              font=("Consolas", 9))
                y += 18
            elif "t" in r:
                c.create_text(12, y, text=str(r["t"]), fill=r.get("c") or MUTE, anchor="nw", width=inner,
                              font=("Consolas", 9))
                y += 18 * max(1, min(3, len(str(r["t"])) * 7 // max(60, inner) + 1))
        for k in (6, 11, 16):  # resize grip
            c.create_line(w - k, h - 2, w - 2, h - k, fill=dim)

    def pins_show(on):
        pin_st["visible"] = bool(on)
        for p in pins.values():
            if on:
                ctypes.windll.user32.SetWindowPos(p["hwnd"], -1, 0, 0, 0, 0, 0x13)
            ctypes.windll.user32.ShowWindow(p["hwnd"], 4 if on else 0)

    def tick():
        try:
            while True:
                cmd, args = _q.get_nowait()
                if cmd == "show":
                    show(True)
                elif cmd == "hide":
                    show(False)
                elif cmd == "muted":
                    st["muted"] = bool(args[0])
                elif cmd == "mode":
                    st["mode"] = args[0] if args[0] in ("thinking", "speaking", "listening") else "idle"
                elif cmd == "colour":
                    try:
                        st["colours"] = palette(args[0])
                        entry.configure(insertbackground=st["colours"][0], highlightcolor=st["colours"][0])
                        for pid in pins:
                            pin_draw(pid)
                    except (ValueError, IndexError, AttributeError):
                        pass  # not a colour: keep the current one
                elif cmd == "pin_add":
                    pin_add(*args)
                elif cmd == "pin_remove":
                    p = pins.pop(args[0], None)
                    if p:
                        p["top"].destroy()
                elif cmd == "pin_frame":
                    if args[0] in pins:
                        pins[args[0]]["rows"] = args[1] or []
                        pin_draw(args[0])
                elif cmd == "pins_show":
                    pins_show(args[0])
                elif cmd == "pin_alpha":
                    pin_st["alpha"] = max(0.2, min(1.0, float(args[0])))
                    for p in pins.values():
                        p["top"].attributes("-alpha", pin_st["alpha"])
                elif cmd == "quit":
                    root.destroy()
                    return
        except queue.Empty:
            pass
        draw()
        root.after(33, tick)

    tick()
    root.mainloop()
