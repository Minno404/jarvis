"""The push-to-talk key: held anywhere in Windows (even in a game), Jarvis listens until it's released.

Keys are saved by the HUD's settings as browser key codes ("KeyV", "F13", "Backquote", "Mouse4"...) and mapped to
Windows virtual-key codes here. It polls the key state 40 times a second, which costs next to nothing.
"""
import threading
import time

VK = {"Mouse4": 0x05, "Mouse5": 0x06, "MouseMiddle": 0x04, "Backspace": 0x08, "Tab": 0x09, "Enter": 0x0D,
      "ShiftLeft": 0xA0, "ShiftRight": 0xA1, "ControlLeft": 0xA2, "ControlRight": 0xA3, "AltLeft": 0xA4,
      "AltRight": 0xA5, "Pause": 0x13, "CapsLock": 0x14, "Escape": 0x1B, "Space": 0x20, "PageUp": 0x21,
      "PageDown": 0x22, "End": 0x23, "Home": 0x24, "ArrowLeft": 0x25, "ArrowUp": 0x26, "ArrowRight": 0x27,
      "ArrowDown": 0x28, "Insert": 0x2D, "Delete": 0x2E, "MetaLeft": 0x5B, "MetaRight": 0x5C,
      "ContextMenu": 0x5D, "ScrollLock": 0x91, "NumLock": 0x90, "Backquote": 0xC0, "Minus": 0xBD, "Equal": 0xBB,
      "BracketLeft": 0xDB, "BracketRight": 0xDD, "Backslash": 0xDC, "Semicolon": 0xBA, "Quote": 0xDE,
      "Comma": 0xBC, "Period": 0xBE, "Slash": 0xBF, "NumpadMultiply": 0x6A, "NumpadAdd": 0x6B,
      "NumpadSubtract": 0x6D, "NumpadDecimal": 0x6E, "NumpadDivide": 0x6F}
VK.update({f"Key{c}": ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
VK.update({f"Digit{d}": 0x30 + d for d in range(10)})
VK.update({f"Numpad{d}": 0x60 + d for d in range(10)})
VK.update({f"F{n}": 0x70 + n - 1 for n in range(1, 25)})

NAMES = {"Mouse4": "Mouse back button", "Mouse5": "Mouse forward button", "MouseMiddle": "Middle mouse button",
         "Backquote": "` (backtick)", "CapsLock": "Caps Lock", "AltRight": "Right Alt", "ControlRight": "Right Ctrl"}
state = {"vk": None, "code": None}


def name(code):
    """A friendly name for a key code, for the HUD and Jarvis."""
    if not code:
        return "Not set"
    return NAMES.get(code) or code.replace("Key", "").replace("Digit", "").replace("Numpad", "Numpad ")


def set_key(code):
    state.update(code=code or None, vk=VK.get(code) if code else None)
    return state["vk"] is not None or not code


def start(down, up):
    """Watch the push-to-talk key in the background: down() when pressed, up() when released (Windows only)."""
    import ctypes
    user32 = ctypes.windll.user32

    def loop():
        held = False
        while True:
            vk = state["vk"]
            now = bool(vk and user32.GetAsyncKeyState(vk) & 0x8000)
            if now != held:
                held = now
                try:
                    (down if now else up)()
                except Exception as e:
                    print("push-to-talk:", repr(e))
            time.sleep(0.025)
    threading.Thread(target=loop, daemon=True).start()


def selftest():
    assert VK["KeyV"] == 0x56 and VK["F13"] == 0x7C and VK["Mouse4"] == 0x05 and VK["Digit0"] == 0x30
    assert set_key("Mouse4") and state["vk"] == 5 and name("Mouse4") == "Mouse back button" and name("KeyV") == "V"
    assert not set_key("SomethingWeird") and set_key("") and state["vk"] is None
    print("hotkey self-test passed")


if __name__ == "__main__":
    selftest()
