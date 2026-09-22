"""Wayland pointer control and global shortcuts through desktop portals."""

import asyncio
import os
import threading
import uuid
from queue import Empty, SimpleQueue

from Xlib import XK
from pathlib import Path

from dbus_next import Message, MessageType, Variant
from dbus_next.aio import MessageBus


class PortalClicker:
    global_keys = False

    def __init__(self):
        self.ready = False
        self.error = None
        self.token_path = Path(__file__).resolve().parent / ".tools" / "portal-restore-token"
        self.restore_token = self._load_restore_token()
        self.permission_required = not bool(self.restore_token)
        self.permission_requested = threading.Event()
        if self.restore_token:
            self.permission_requested.set()
        self.session = None
        self.shortcut_session = None
        self.shortcut_config = None
        self.shortcut_bindings = {}
        self.shortcut_status = "Waiting for global shortcuts…"
        self.shortcut_pending = False
        self.shortcut_events = SimpleQueue()
        self.shortcut_held = set()
        self.pending = {}
        self.inflight = None
        self.loop = None
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _load_restore_token(self):
        try:
            return self.token_path.read_text(encoding="utf-8").strip() or None
        except (FileNotFoundError, OSError):
            return None

    def _save_restore_token(self, token):
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.token_path.with_suffix(".tmp")
        temporary.write_text(token, encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.token_path)
        self.restore_token = token

    def request_persistent_permission(self):
        """Ask the portal to grant persistent pointer control."""
        if not self.ready:
            self.permission_required = False
            self.permission_requested.set()

    def _run(self):
        try:
            asyncio.run(self._serve())
        except Exception as exc:
            self.error = f"Desktop permission unavailable: {exc}. Reopen ForLazy to retry."

    async def _call(self, member, signature, body, *, path="/org/freedesktop/portal/desktop", interface="org.freedesktop.portal.RemoteDesktop"):
        reply = await self.bus.call(Message(
            destination="org.freedesktop.portal.Desktop", path=path,
            interface=interface, member=member, signature=signature, body=body,
        ))
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(reply.body[0] if reply.body else reply.error_name)
        return reply

    def _signal(self, message):
        if message.message_type != MessageType.SIGNAL:
            return
        if message.interface == "org.freedesktop.portal.Request" and message.member == "Response":
            future = self.pending.get(message.path)
            if future is not None and not future.done():
                future.set_result(message.body)
        elif message.interface == "org.freedesktop.portal.GlobalShortcuts":
            if not message.body or message.body[0] != self.shortcut_session:
                return
            if message.member == "ShortcutsChanged":
                self._update_shortcut_bindings(message.body[1])
            elif message.member in ("Activated", "Deactivated"):
                action = message.body[1]
                if message.member == "Deactivated":
                    self.shortcut_held.discard(action)
                elif action in self.shortcut_bindings and action not in self.shortcut_held:
                    self.shortcut_held.add(action)
                    self.shortcut_events.put((self.shortcut_session, action))
        elif (message.interface == "org.freedesktop.portal.Session"
              and message.member == "Closed" and message.path == self.shortcut_session):
            self.shortcut_session = None
            self.shortcut_bindings = {}
            self.shortcut_status = "Global shortcuts were revoked. Apply hotkey to retry."
        elif message.interface == "org.freedesktop.portal.Session" and message.member == "Closed" and message.path == self.session:
            self.ready = False
            self.error = "Desktop permission was revoked. Reopen ForLazy to reconnect."

    async def _request(self, member, signature, body, options=None, *, interface="org.freedesktop.portal.RemoteDesktop"):
        token = "forlazy" + uuid.uuid4().hex
        sender = self.bus.unique_name[1:].replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        future = self.loop.create_future()
        self.pending[path] = future
        options = dict(options or {}, handle_token=Variant("s", token))
        try:
            await self._call(member, signature, [*body, options], interface=interface)
            response, results = await future
            if response != 0:
                raise RuntimeError("permission request cancelled or denied")
            return results
        except asyncio.CancelledError:
            await self._call("Close", "", [], path=path, interface="org.freedesktop.portal.Request")
            raise
        finally:
            self.pending.pop(path, None)

    async def _serve(self):
        self.loop = asyncio.get_running_loop()
        self.bus = await MessageBus().connect()
        self.bus.add_message_handler(self._signal)
        try:
            for interface in ("Request", "Session", "GlobalShortcuts"):
                reply = await self.bus.call(Message(
                    destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus", member="AddMatch", signature="s",
                    body=[f"type='signal',sender='org.freedesktop.portal.Desktop',interface='org.freedesktop.portal.{interface}'"],
                ))
                if reply.message_type == MessageType.ERROR:
                    raise RuntimeError("Cannot subscribe to desktop permission responses")
            # Wait for the UI to request access unless a saved grant can be restored.
            setup = None
            shortcuts = None
            applied_config = None
            try:
                while not self.closed.is_set():
                    if self.shortcut_config != applied_config:
                        applied_config = self.shortcut_config
                        if shortcuts is not None:
                            shortcuts.cancel()
                            await asyncio.gather(shortcuts, return_exceptions=True)
                        shortcuts = asyncio.create_task(self._setup_shortcuts(applied_config))
                    if setup is None and self.permission_requested.is_set():
                        setup = asyncio.create_task(self._setup())
                    if setup is not None and setup.done():
                        await setup
                    if not self.bus.connected:
                        raise RuntimeError("Desktop session disconnected")
                    await asyncio.sleep(0.05)
            finally:
                if shortcuts is not None:
                    shortcuts.cancel()
                    await asyncio.gather(shortcuts, return_exceptions=True)
                # A revoked shortcut session must not interrupt pointer cleanup.
                await asyncio.gather(self._close_shortcuts(), return_exceptions=True)
                if setup is not None:
                    setup.cancel()
                    await asyncio.gather(setup, return_exceptions=True)
                if self.inflight is not None:
                    await asyncio.gather(asyncio.wrap_future(self.inflight), return_exceptions=True)
                if self.session:
                    await self._call("Close", "", [], path=self.session, interface="org.freedesktop.portal.Session")
        finally:
            self.ready = False
            self.bus.disconnect()

    async def _setup(self):
        result = await self._request("CreateSession", "a{sv}", [], {
            "session_handle_token": Variant("s", "forlazy" + uuid.uuid4().hex),
        })
        self.session = result["session_handle"].value
        options = {
            "types": Variant("u", 2),
            "persist_mode": Variant("u", 2),
        }
        restore_token = getattr(self, "restore_token", None)
        if restore_token:
            options["restore_token"] = Variant("s", restore_token)
        await self._request("SelectDevices", "oa{sv}", [self.session], options)
        result = await self._request("Start", "osa{sv}", [self.session, ""])
        if not result.get("devices", Variant("u", 0)).value & 2:
            raise RuntimeError("Pointer control was not granted")
        returned_token = result.get("restore_token")
        if returned_token:
            self._save_restore_token(returned_token.value)
            self.permission_required = False
        else:
            self.permission_required = True
        self.ready = True

    @staticmethod
    def shortcut_trigger(hotkey):
        """Translate Qt portable text to the XDG shortcut syntax."""
        modifiers = []
        names = {"Ctrl": "CTRL", "Alt": "ALT", "Shift": "SHIFT", "Meta": "LOGO", "Num": "NUM"}
        while "+" in hotkey and hotkey.split("+", 1)[0] in names:
            modifier, hotkey = hotkey.split("+", 1)
            modifiers.append(names[modifier])
        aliases = {"Esc": "Escape", "Del": "Delete", "Ins": "Insert",
                   "PgUp": "Prior", "PgDown": "Next", "Space": "space",
                   "Backtab": "ISO_Left_Tab", "Enter": "KP_Enter"}
        key = aliases.get(hotkey, hotkey)
        if len(key) == 1:
            # XDG uses keysym names (e.g. plus), never punctuation.
            import ctypes
            import ctypes.util
            library = ctypes.util.find_library("xkbcommon")
            if library:
                xkb = ctypes.CDLL(library)
                xkb.xkb_utf32_to_keysym.argtypes = [ctypes.c_uint32]
                xkb.xkb_utf32_to_keysym.restype = ctypes.c_uint32
                xkb.xkb_keysym_get_name.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t]
                buffer = ctypes.create_string_buffer(64)
                symbol = xkb.xkb_utf32_to_keysym(ord(key.lower()))
                if xkb.xkb_keysym_get_name(symbol, buffer, len(buffer)) > 0:
                    key = buffer.value.decode("ascii")
            elif key.isalpha():
                key = key.lower()
        if not key or not all(c.isalnum() or c == "_" for c in key):
            raise ValueError(f"Unsupported Wayland hotkey: {hotkey}")
        if not XK.string_to_keysym(key) and not (key.startswith("U") or key == "ISO_Left_Tab"):
            raise ValueError(f"Unsupported Wayland hotkey: {hotkey}")
        return "+".join([*modifiers, key])

    def set_hotkeys(self, hotkey, escape_enabled):
        trigger = self.shortcut_trigger(hotkey)
        self.shortcut_pending = True
        self.shortcut_status = "Approve global shortcuts in the desktop permission dialog…"
        # A generation also permits retrying a denied request with the same keys.
        self.shortcut_config = (trigger, escape_enabled, uuid.uuid4().hex)

    def take_shortcut_events(self):
        events = []
        while True:
            try:
                session, action = self.shortcut_events.get_nowait()
            except Empty:
                return events
            if session == self.shortcut_session and action in self.shortcut_bindings:
                events.append(action)

    def _update_shortcut_bindings(self, shortcuts):
        self.shortcut_bindings = {
            action: properties.get("trigger_description", Variant("s", action)).value
            for action, properties in shortcuts if action in ("toggle", "escape")
        }
        descriptions = [f"{'Start/stop' if action == 'toggle' else 'Stop'}: {trigger}"
                        for action, trigger in self.shortcut_bindings.items()]
        self.shortcut_status = ("Global shortcuts • " + " • ".join(descriptions)
                                if descriptions else "No global shortcuts granted. Apply hotkey to retry.")
        if "toggle" not in self.shortcut_bindings and descriptions:
            self.shortcut_status += " • Global start/stop was not granted."

    async def _close_shortcuts(self):
        session = self.shortcut_session
        self.shortcut_session = None
        self.shortcut_bindings = {}
        self.shortcut_held.clear()
        if session:
            await self._call("Close", "", [], path=session, interface="org.freedesktop.portal.Session")

    async def _setup_shortcuts(self, config):
        try:
            await self._close_shortcuts()
            trigger, escape_enabled, generation = config
            interface = "org.freedesktop.portal.GlobalShortcuts"
            result = await self._request("CreateSession", "a{sv}", [], {
                "session_handle_token": Variant("s", "forlazy" + uuid.uuid4().hex),
            }, interface=interface)
            self.shortcut_session = result["session_handle"].value
            shortcuts = [["toggle", {"description": Variant("s", "Start / stop ForLazy"),
                                      "preferred_trigger": Variant("s", trigger)}]]
            if escape_enabled and trigger != "Escape":
                shortcuts.append(["escape", {"description": Variant("s", "Stop ForLazy"),
                                               "preferred_trigger": Variant("s", "Escape")}])
            result = await self._request("BindShortcuts", "oa(sa{sv})sa{sv}",
                                         [self.shortcut_session, shortcuts, ""], interface=interface)
            self._update_shortcut_bindings(result.get("shortcuts", Variant("a(sa{sv})", [])).value)
        except Exception as exc:
            self.shortcut_bindings = {}
            self.shortcut_status = f"Global shortcuts unavailable: {exc}. Apply hotkey to retry."
        finally:
            if config == self.shortcut_config:
                self.shortcut_pending = False

    def pressed_keys(self):
        if self.error:
            raise RuntimeError(self.error)
        if self.inflight is not None and self.inflight.done():
            self.inflight.result()
        return set()

    async def _click(self, button):
        code = {1: 272, 3: 273, 2: 274}[button]
        try:
            await self._call("NotifyPointerButton", "oa{sv}iu", [self.session, {}, code, 1])
        finally:
            await self._call("NotifyPointerButton", "oa{sv}iu", [self.session, {}, code, 0])

    async def _click_many(self, button, count):
        for _ in range(count):
            await self._click(button)

    def click(self, button, count=1):
        self.pressed_keys()
        if not self.ready or (self.inflight is not None and not self.inflight.done()):
            return None
        self.inflight = asyncio.run_coroutine_threadsafe(self._click_many(button, count), self.loop)
        return True

    def close(self):
        self.closed.set()
        self.thread.join(timeout=2)
