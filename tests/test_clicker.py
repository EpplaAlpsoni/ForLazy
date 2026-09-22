import os
from queue import SimpleQueue
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from dbus_next import Message, MessageType, Variant
from main import ForLazyWindow
from clicker import X11Clicker
from portal import PortalClicker


class FakeBackend:
    global_keys = True
    ready = True

    def __init__(self):
        self.keys = set()
        self.clicks = []
        self.safe = True
        self.closed = False
        self.permission_required = False
        self.permission_requests = 0
        self.hotkeys = None

    def pressed_keys(self):
        return self.keys

    def click(self, button, count=1):
        if self.safe:
            self.clicks.extend([button] * count)
        return self.safe

    def close(self):
        self.closed = True

    def request_persistent_permission(self):
        self.permission_requests += 1

    def set_hotkeys(self, hotkey, escape_enabled):
        self.hotkeys = (hotkey, escape_enabled)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.settings_directory = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.settings_directory.name) / "settings.json"
        self.backend = FakeBackend()
        self.window = ForLazyWindow(self.backend, self.settings_path)
        self.window.poll_timer.stop()

    def tearDown(self):
        self.window.close()
        self.settings_directory.cleanup()

    def start_clicking(self):
        self.window.toggle()

    def test_countdown_and_selected_button(self):
        self.window.button.setCurrentIndex(1)
        self.window.baby_mode.setChecked(True)
        self.window.toggle()
        self.window.poll()
        self.assertEqual(self.backend.clicks, [])
        self.assertFalse(self.window.interval.isEnabled())
        self.window.deadline = 0
        self.window.poll()
        self.assertEqual(self.backend.clicks, [3])
        self.assertTrue(self.window.click_timer.isActive())

    def test_baby_mode_is_off_and_clicks_immediately(self):
        self.assertFalse(self.window.baby_mode.isChecked())
        self.window.toggle()
        self.assertIsNone(self.window.deadline)
        self.assertEqual(self.backend.clicks, [1])

    def test_baby_mode_adds_three_second_countdown(self):
        self.window.baby_mode.setChecked(True)
        self.window.toggle()
        self.assertIsNotNone(self.window.deadline)
        self.assertEqual(self.backend.clicks, [])
        self.assertIn("Baby Mode", self.window.status.text())

    def test_baby_mode_countdown_is_configurable(self):
        self.window.baby_mode.setChecked(True)
        self.window.baby_delay.setValue(7)
        with patch("main.time.monotonic", return_value=100):
            self.window.toggle()
        self.assertEqual(self.window.deadline, 107)
        self.assertIn("7 seconds", self.window.status.text())

    def test_hotkey_and_secondary_escape_are_configurable(self):
        self.window.hotkey_edit.setKeySequence(QKeySequence("Ctrl+F8"))
        self.assertTrue(self.window.apply_hotkey_button.isEnabled())
        self.window.apply_hotkey_button.click()
        self.assertEqual(self.backend.hotkeys, ("Ctrl+F8", True))
        self.assertEqual(self.window.stop_button.text(), "Stop (Esc / Ctrl+F8)")
        self.assertTrue(self.window.apply_hotkey_button.isEnabled())
        self.window.escape_stop.setChecked(False)
        self.assertEqual(self.backend.hotkeys, ("Ctrl+F8", False))
        self.assertIn("Ctrl+F8", self.window.toggle_button.text())
        self.assertEqual(self.window.stop_button.text(), "Stop (Ctrl+F8)")
        self.window.toggle()
        self.window.stop()
        self.assertTrue(self.window.apply_hotkey_button.isEnabled())

    def test_clicking_hotkey_field_clears_old_binding_for_capture(self):
        self.window.show()
        self.assertEqual(self.window.hotkey_text(), "F6")
        QTest.mouseClick(self.window.hotkey_edit, Qt.MouseButton.LeftButton)
        self.assertTrue(self.window.hotkey_edit.keySequence().isEmpty())
        self.assertTrue(self.window.apply_hotkey_button.isEnabled())

    def test_empty_hotkey_apply_restores_f6(self):
        self.window.hotkey_edit.setKeySequence(QKeySequence("F8"))
        self.window.apply_hotkey_button.click()
        self.window.hotkey_edit.clear()
        self.window.apply_hotkey_button.click()
        self.assertEqual(self.window.hotkey_text(), "F6")
        self.assertEqual(self.backend.hotkeys, ("F6", True))

    def test_applied_local_hotkey_toggles_clicking(self):
        self.backend.global_keys = False
        self.window.hotkey_edit.setKeySequence(QKeySequence("Ctrl+F8"))
        self.window.apply_hotkey_button.click()
        self.window.show()
        self.app.processEvents()
        QTest.keyClick(self.window, Qt.Key.Key_F8, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.window.active)

    def test_mouse_applied_hotkey_releases_button_focus_and_works(self):
        self.backend.global_keys = False
        self.window.show()
        self.window.tabs.setCurrentIndex(1)
        self.window.hotkey_edit.setFocus()
        QTest.keyClick(
            self.window.hotkey_edit, Qt.Key.Key_F8, Qt.KeyboardModifier.ControlModifier
        )
        QTest.mouseClick(self.window.apply_hotkey_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertIs(self.window.focusWidget(), self.window.toggle_button)
        QTest.keyClick(self.window, Qt.Key.Key_F8, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.window.active)

    def test_wayland_portal_events_toggle_without_focus_and_disable_local_duplicates(self):
        self.backend.global_keys = False
        self.backend.shortcut_bindings = {"toggle": "F9", "escape": "Esc"}
        self.backend.shortcut_pending = False
        self.backend.shortcut_status = "Global shortcuts active"
        events = []
        def take_events():
            result = events[:]
            events.clear()
            return result
        self.backend.take_shortcut_events = take_events
        self.window.update_hotkeys()
        self.assertTrue(all(not key.isEnabled() for key in self.window.local_shortcuts))
        self.assertFalse(self.window.isActiveWindow())
        events.append("toggle")
        self.window.poll()
        self.assertTrue(self.window.active)
        events.append("toggle")
        self.window.poll()
        self.assertFalse(self.window.active)
        self.assertIn("F9", self.window.toggle_button.text())
        self.backend.shortcut_bindings = {}
        self.window.poll()
        self.assertTrue(all(key.isEnabled() for key in self.window.local_shortcuts))
        self.assertIn("focused", self.window.help_text.text())

    def test_editing_repeat_count_selects_finite_repeat(self):
        self.assertTrue(self.window.repeat_forever.isChecked())
        self.window.repeat_count.setEnabled(True)
        self.window.repeat_count.setValue(12)
        self.assertTrue(self.window.repeat_limited.isChecked())

    def test_held_f6_does_not_toggle_repeatedly(self):
        self.backend.keys = {"toggle"}
        self.window.poll()
        self.window.poll()
        self.assertTrue(self.window.active)
        self.backend.keys = set()
        self.window.poll()
        self.backend.keys = {"toggle"}
        self.window.poll()
        self.assertFalse(self.window.active)

    def test_escape_stops_before_next_click(self):
        self.start_clicking()
        self.backend.keys = {"escape"}
        self.window.perform_click()
        self.assertFalse(self.window.active)
        self.assertEqual(len(self.backend.clicks), 1)

    def test_corner_and_close_stop(self):
        self.start_clicking()
        self.backend.safe = False
        self.window.perform_click()
        self.assertFalse(self.window.click_timer.isActive())
        self.window.close()
        self.assertTrue(self.backend.closed)

    def test_error_disables_clicking(self):
        self.start_clicking()
        with patch.object(self.backend, "pressed_keys", side_effect=RuntimeError("Disconnected")):
            self.window.poll()
        self.assertFalse(self.window.active)
        self.assertFalse(self.window.toggle_button.isEnabled())

    def test_wayland_waits_for_permission(self):
        self.window.close()
        self.backend.global_keys = False
        self.backend.ready = False
        self.window = ForLazyWindow(self.backend, self.settings_path)
        self.window.poll_timer.stop()
        self.window.toggle()
        self.assertFalse(self.window.active)
        self.backend.ready = True
        self.window.poll()
        self.assertTrue(self.window.toggle_button.isEnabled())

    def test_missing_persistent_permission_shows_grant_action(self):
        self.window.close()
        self.backend.global_keys = False
        self.backend.ready = False
        self.backend.permission_required = True
        self.window = ForLazyWindow(self.backend, self.settings_path)
        self.window.poll_timer.stop()
        self.assertFalse(self.window.permission_panel.isHidden())
        self.window.permission_button.click()
        self.assertEqual(self.backend.permission_requests, 1)
        self.assertFalse(self.window.permission_button.isEnabled())

    def test_interval_fields_are_combined(self):
        self.window.hours.setValue(1)
        self.window.minutes.setValue(2)
        self.window.seconds.setValue(3)
        self.window.interval.setValue(4)
        self.assertEqual(self.window.interval_ms(), 3_723_004)

    def test_all_settings_are_restored_in_a_new_window(self):
        self.window.hours.setValue(2)
        self.window.minutes.setValue(3)
        self.window.seconds.setValue(4)
        self.window.interval.setValue(567)
        self.window.button.setCurrentIndex(1)
        self.window.click_type.setCurrentIndex(1)
        self.window.repeat_limited.setChecked(True)
        self.window.repeat_count.setValue(42)
        self.window.baby_mode.setChecked(True)
        self.window.baby_delay.setValue(9)
        self.window.escape_stop.setChecked(False)
        self.window.hotkey_edit.setKeySequence(QKeySequence("Ctrl+F9"))
        self.window.apply_hotkey_button.click()
        self.assertEqual(stat.S_IMODE(self.settings_path.stat().st_mode), 0o600)
        self.window.close()

        backend = FakeBackend()
        self.window = ForLazyWindow(backend, self.settings_path)
        self.window.poll_timer.stop()
        self.assertEqual(
            (self.window.hours.value(), self.window.minutes.value(),
             self.window.seconds.value(), self.window.interval.value()),
            (2, 3, 4, 567),
        )
        self.assertEqual(self.window.button.currentData(), 3)
        self.assertEqual(self.window.click_type.currentData(), 2)
        self.assertTrue(self.window.repeat_limited.isChecked())
        self.assertEqual(self.window.repeat_count.value(), 42)
        self.assertTrue(self.window.baby_mode.isChecked())
        self.assertEqual(self.window.baby_delay.value(), 9)
        self.assertFalse(self.window.escape_stop.isChecked())
        self.assertEqual(self.window.hotkey_text(), "Ctrl+F9")
        self.assertEqual(backend.hotkeys, ("Ctrl+F9", False))

    def test_finite_repeat_stops_at_exact_count(self):
        self.window.repeat_limited.setChecked(True)
        self.window.repeat_count.setValue(3)
        self.window.click_type.setCurrentIndex(1)
        self.start_clicking()
        self.assertEqual(len(self.backend.clicks), 2)
        self.window.perform_click()
        self.window.perform_click()
        self.assertEqual(len(self.backend.clicks), 6)
        self.assertFalse(self.window.active)
        self.assertIn("Complete", self.window.status.text())
        self.window.toggle()
        self.assertFalse(self.window.active)
        self.assertEqual(len(self.backend.clicks), 6)

    def test_finite_repeat_can_be_started_again_after_completion_latch(self):
        self.window.repeat_limited.setChecked(True)
        self.window.repeat_count.setValue(1)
        self.start_clicking()
        self.assertFalse(self.window.active)
        self.window.restart_not_before = 0
        self.window.toggle()
        self.assertFalse(self.window.active)
        self.assertEqual(len(self.backend.clicks), 2)


class PortalTests(unittest.IsolatedAsyncioTestCase):
    async def test_restore_token_is_stored_with_user_only_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = PortalClicker.__new__(PortalClicker)
            backend.token_path = Path(directory) / "nested" / "token"
            backend._save_restore_token("private-token")
            self.assertEqual(backend.token_path.read_text(), "private-token")
            self.assertEqual(stat.S_IMODE(backend.token_path.stat().st_mode), 0o600)

    async def test_setup_requests_only_pointer(self):
        backend = PortalClicker.__new__(PortalClicker)
        backend.restore_token = None
        backend._save_restore_token = unittest.mock.Mock()
        backend._request = AsyncMock(side_effect=[
            {"session_handle": Variant("s", "/session/test")}, {},
            {"devices": Variant("u", 2), "restore_token": Variant("s", "next-token")},
        ])
        await backend._setup()
        self.assertTrue(backend.ready)
        calls = backend._request.call_args_list
        self.assertEqual(calls[1].args[3]["types"].value, 2)
        self.assertEqual(calls[1].args[3]["persist_mode"].value, 2)
        self.assertEqual(calls[2].args[2], ["/session/test", ""])
        backend._save_restore_token.assert_called_once_with("next-token")

    async def test_setup_uses_saved_restore_token(self):
        backend = PortalClicker.__new__(PortalClicker)
        backend.restore_token = "saved-token"
        backend._save_restore_token = unittest.mock.Mock()
        backend._request = AsyncMock(side_effect=[
            {"session_handle": Variant("s", "/session/test")}, {},
            {"devices": Variant("u", 2), "restore_token": Variant("s", "rotated-token")},
        ])
        await backend._setup()
        options = backend._request.call_args_list[1].args[3]
        self.assertEqual(options["restore_token"].value, "saved-token")
        backend._save_restore_token.assert_called_once_with("rotated-token")

    async def test_missing_pointer_permission_is_rejected(self):
        backend = PortalClicker.__new__(PortalClicker)
        backend.restore_token = None
        backend._request = AsyncMock(side_effect=[
            {"session_handle": Variant("s", "/session/test")}, {},
            {"devices": Variant("u", 1)},
        ])
        with self.assertRaisesRegex(RuntimeError, "not granted"):
            await backend._setup()

    async def test_buttons_are_paired_and_use_evdev_codes(self):
        backend = PortalClicker.__new__(PortalClicker)
        backend.session = "/session/test"
        for button, code in ((1, 272), (3, 273), (2, 274)):
            backend._call = AsyncMock()
            await backend._click(button)
            self.assertEqual([call.args[2] for call in backend._call.call_args_list], [
                [backend.session, {}, code, 1], [backend.session, {}, code, 0],
            ])

    async def test_release_attempted_after_press_error(self):
        backend = PortalClicker.__new__(PortalClicker)
        backend.session = "/session/test"
        backend._call = AsyncMock(side_effect=[RuntimeError("lost reply"), None])
        with self.assertRaises(RuntimeError):
            await backend._click(1)
        self.assertEqual(backend._call.call_args.args[2][-1], 0)


class GlobalShortcutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = PortalClicker.__new__(PortalClicker)
        self.backend.session = "/pointer/session"
        self.backend.pending = {}
        self.backend.shortcut_session = None
        self.backend.shortcut_bindings = {}
        self.backend.shortcut_events = SimpleQueue()
        self.backend.shortcut_held = set()
        self.backend.shortcut_config = None
        self.backend._call = AsyncMock()

    async def bind(self, hotkey="Ctrl+F8", escape=True):
        self.backend.set_hotkeys(hotkey, escape)
        bindings = [["toggle", {"trigger_description": Variant("s", "Ctrl+F9")}]]
        if escape and hotkey != "Esc":
            bindings.append(["escape", {"trigger_description": Variant("s", "Escape")}])
        self.backend._request = AsyncMock(side_effect=[
            {"session_handle": Variant("s", "/shortcuts/session")},
            {"shortcuts": Variant("a(sa{sv})", bindings)},
        ])
        await self.backend._setup_shortcuts(self.backend.shortcut_config)

    def signal(self, member, action="toggle", session="/shortcuts/session"):
        self.backend._signal(Message(
            message_type=MessageType.SIGNAL, path="/org/freedesktop/portal/desktop",
            interface="org.freedesktop.portal.GlobalShortcuts", member=member,
            signature="osta{sv}", body=[session, action, 1, {}],
        ))

    async def test_binding_uses_global_portal_and_desktop_assigned_keys(self):
        await self.bind()
        call = self.backend._request.call_args
        self.assertEqual(call.kwargs["interface"], "org.freedesktop.portal.GlobalShortcuts")
        self.assertEqual(call.args[1], "oa(sa{sv})sa{sv}")
        self.assertEqual(call.args[2][1][0][1]["preferred_trigger"].value, "CTRL+F8")
        self.assertEqual(self.backend.shortcut_bindings["toggle"], "Ctrl+F9")
        self.assertFalse(self.backend.shortcut_pending)
        self.assertEqual(self.backend.session, "/pointer/session")

    async def test_quick_taps_survive_release_before_poll_and_repeat_is_ignored(self):
        await self.bind()
        self.signal("Activated")
        self.signal("Activated")
        self.signal("Deactivated")
        self.assertEqual(self.backend.take_shortcut_events(), ["toggle"])
        self.signal("Activated")
        self.assertEqual(self.backend.take_shortcut_events(), ["toggle"])
        self.assertEqual(self.backend.take_shortcut_events(), [])

    async def test_foreign_sessions_and_disabled_escape_are_ignored(self):
        await self.bind(escape=False)
        self.signal("Activated", session="/other/session")
        self.signal("Activated", action="escape")
        self.assertEqual(self.backend.take_shortcut_events(), [])
        self.assertEqual(len(self.backend._request.call_args.args[2][1]), 1)

    async def test_escape_toggle_does_not_register_conflicting_stop(self):
        await self.bind("Esc")
        self.assertEqual(len(self.backend._request.call_args.args[2][1]), 1)

    async def test_rebinding_closes_old_session_and_discards_queued_events(self):
        await self.bind()
        self.signal("Activated")
        await self.backend._close_shortcuts()
        self.backend._call.assert_awaited_with(
            "Close", "", [], path="/shortcuts/session", interface="org.freedesktop.portal.Session")
        self.assertEqual(self.backend.take_shortcut_events(), [])
        self.assertFalse(self.backend.shortcut_held)

    async def test_denial_keeps_pointer_access_and_allows_retry(self):
        self.backend.ready = True
        self.backend.set_hotkeys("F6", True)
        original = self.backend.shortcut_config
        self.backend._request = AsyncMock(side_effect=RuntimeError("denied"))
        await self.backend._setup_shortcuts(original)
        self.assertTrue(self.backend.ready)
        self.assertFalse(self.backend.shortcut_pending)
        self.assertEqual(self.backend.shortcut_bindings, {})
        self.assertIn("denied", self.backend.shortcut_status)
        self.backend.set_hotkeys("F6", True)
        self.assertNotEqual(original, self.backend.shortcut_config)

    async def test_session_revocation_removes_global_bindings(self):
        await self.bind()
        self.backend._signal(Message(
            message_type=MessageType.SIGNAL, path="/shortcuts/session",
            interface="org.freedesktop.portal.Session", member="Closed",
        ))
        self.assertEqual(self.backend.shortcut_bindings, {})
        self.assertIn("revoked", self.backend.shortcut_status)

    def test_qt_to_xdg_shortcut_conversion(self):
        for source, expected in (("F6", "F6"), ("Ctrl+Shift+A", "CTRL+SHIFT+a"),
                                 ("Meta+PgDown", "LOGO+Next"), ("Ctrl++", "CTRL+plus"),
                                 ("Space", "space"), ("Esc", "Escape")):
            self.assertEqual(PortalClicker.shortcut_trigger(source), expected)


class X11HotkeyTests(unittest.TestCase):
    def test_escape_main_bind_does_not_create_conflicting_stop_action(self):
        backend = X11Clicker.__new__(X11Clicker)
        backend.connection = unittest.mock.Mock()
        backend.connection.keysym_to_keycode.return_value = 9
        backend.set_hotkeys("Escape", True)
        self.assertEqual(set(backend.bindings), {"toggle"})


if __name__ == "__main__":
    unittest.main()
