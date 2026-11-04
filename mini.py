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


def send(cmd, *args):
    """Thread-safe: 'show', 'hide', 'mode' <idle|thinking|speaking|listening>, 'quit'."""
    _q.put((cmd, args))


def start(on_ask, on_open, size=170):
    threading.Thread(target=_run, args=(on_ask, on_open, size), daemon=True).start()


def _run(on_ask, on_open, size):
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
          "colours": (CYAN, DIM, GLOW), "x": sw - size - 40, "y": sh - size - 110, "drag": None, "moved": False}
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
    def press(e):
        st["drag"], st["moved"] = (e.x_root - st["x"], e.y_root - st["y"]), False

    def motion(e):
        if st["drag"]:
            st["x"], st["y"], st["moved"] = e.x_root - st["drag"][0], e.y_root - st["drag"][1], True
            place()

    def release(e):
        st["drag"] = None
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
        for j in range(72):
            a = j / 72 * math.tau - t * .1
            r1, r2 = 410 * k, (410 - (8 if j % 6 else 20)) * k
            cv.create_line(c + math.cos(a) * r1, c + math.sin(a) * r1, c + math.cos(a) * r2,
                           c + math.sin(a) * r2, fill=dim, width=1)

    def tick():
        try:
            while True:
                cmd, args = _q.get_nowait()
                if cmd == "show":
                    show(True)
                elif cmd == "hide":
                    show(False)
                elif cmd == "mode":
                    st["mode"] = args[0] if args[0] in ("thinking", "speaking", "listening") else "idle"
                elif cmd == "colour":
                    try:
                        st["colours"] = palette(args[0])
                        entry.configure(insertbackground=st["colours"][0], highlightcolor=st["colours"][0])
                    except (ValueError, IndexError, AttributeError):
                        pass  # not a colour: keep the current one
                elif cmd == "quit":
                    root.destroy()
                    return
        except queue.Empty:
            pass
        draw()
        root.after(33, tick)

    tick()
    root.mainloop()
