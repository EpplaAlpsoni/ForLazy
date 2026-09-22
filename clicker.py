"""Unprivileged X11 input via the server's XTEST extension."""

import os

from Xlib import X, XK, display
from Xlib.ext import xtest


class X11Clicker:
    global_keys = True
    ready = True

    def __init__(self):
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
            raise RuntimeError("ForLazy requires an X11 desktop session. Switch to SteamOS Desktop Mode with X11; native Wayland and Gaming Mode are not supported.")
        try:
            self.connection = display.Display()
        except Exception as exc:
            raise RuntimeError("Cannot connect to X11. Open ForLazy from your Desktop Mode session.") from exc
        if not self.connection.has_extension("XTEST"):
            self.connection.close()
            raise RuntimeError("This X11 session does not provide the XTEST extension.")
        self.set_hotkeys("F6", True)

    def _key_codes(self, name):
        aliases = {
            "Ctrl": ("Control_L", "Control_R"), "Alt": ("Alt_L", "Alt_R"),
            "Shift": ("Shift_L", "Shift_R"), "Meta": ("Super_L", "Super_R"),
            "Esc": ("Escape",), "Return": ("Return", "KP_Enter"),
        }
        return tuple(
            code for key_name in aliases.get(name, (name,))
            if (code := self.connection.keysym_to_keycode(XK.string_to_keysym(key_name)))
        )

    def set_hotkeys(self, toggle_key, escape_enabled):
        parts = [part.strip() for part in toggle_key.split("+") if part.strip()]
        chord = [self._key_codes(part) for part in parts]
        if not chord or any(not alternatives for alternatives in chord):
            raise ValueError(f"Unsupported X11 hotkey: {toggle_key}")
        self.bindings = {"toggle": chord}
        if escape_enabled and toggle_key not in ("Esc", "Escape"):
            self.bindings["escape"] = [self._key_codes("Escape")]

    def pressed_keys(self):
        state = self.connection.query_keymap()
        def down(code):
            return bool(state[code // 8] & (1 << (code % 8)))

        return {
            action for action, chord in self.bindings.items()
            if all(any(down(code) for code in alternatives) for alternatives in chord)
        }

    def click(self, button, count=1):
        pointer = self.connection.screen().root.query_pointer()
        if pointer.root_x <= 0 and pointer.root_y <= 0:
            return False
        for _ in range(count):
            xtest.fake_input(self.connection, X.ButtonPress, button)
            xtest.fake_input(self.connection, X.ButtonRelease, button)
        self.connection.sync()
        return True

    def close(self):
        self.connection.close()
