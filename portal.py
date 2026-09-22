"""Wayland input through the user-approved RemoteDesktop portal."""

import asyncio
import os
import threading
import uuid
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
        elif message.interface == "org.freedesktop.portal.Session" and message.member == "Closed" and message.path == self.session:
            self.ready = False
            self.error = "Desktop permission was revoked. Reopen ForLazy to reconnect."

    async def _request(self, member, signature, body, options=None):
        token = "forlazy" + uuid.uuid4().hex
        sender = self.bus.unique_name[1:].replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        future = self.loop.create_future()
        self.pending[path] = future
        options = dict(options or {}, handle_token=Variant("s", token))
        try:
            await self._call(member, signature, [*body, options])
            response, results = await future
            if response != 0:
                raise RuntimeError("permission request cancelled or denied")
            return results
        finally:
            self.pending.pop(path, None)

    async def _serve(self):
        self.loop = asyncio.get_running_loop()
        self.bus = await MessageBus().connect()
        self.bus.add_message_handler(self._signal)
        try:
            for interface in ("Request", "Session"):
                reply = await self.bus.call(Message(
                    destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus", member="AddMatch", signature="s",
                    body=[f"type='signal',sender='org.freedesktop.portal.Desktop',interface='org.freedesktop.portal.{interface}'"],
                ))
                if reply.message_type == MessageType.ERROR:
                    raise RuntimeError("Cannot subscribe to desktop permission responses")
            # Wait for the UI to request access unless a saved grant can be restored.
            setup = None
            try:
                while not self.closed.is_set():
                    if setup is None and self.permission_requested.is_set():
                        setup = asyncio.create_task(self._setup())
                    if setup is not None and setup.done():
                        await setup
                    if not self.bus.connected:
                        raise RuntimeError("Desktop session disconnected")
                    await asyncio.sleep(0.05)
            finally:
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
