"""ForLazy: a small PySide6 autoclicker for Linux desktops."""

import os
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QKeySequenceEdit, QMainWindow, QMessageBox, QPushButton, QRadioButton, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)

from clicker import X11Clicker
from portal import PortalClicker


class HotkeyEdit(QKeySequenceEdit):
    """A shortcut editor that replaces its value when clicked."""

    def mousePressEvent(self, event):
        self.clear()
        super().mousePressEvent(event)


class ForLazyWindow(QMainWindow):
    def __init__(self, backend, settings_path=None):
        super().__init__()
        self.backend = backend
        self.settings_path = Path(settings_path or Path(__file__).resolve().parent / ".tools" / "settings.json")
        self.saved_settings = self._read_settings()
        self.active = False
        self.deadline = None
        self.previous_keys = set()
        self.click_count = 0
        self.restart_not_before = 0.0
        self.setWindowTitle("ForLazy — Auto Clicker")
        self.setFixedWidth(520)

        body = QWidget(objectName="body")
        self.setCentralWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("ForLazy", objectName="title")
        subtitle = QLabel("AUTO CLICKER", objectName="subtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()
        self.state_badge = QLabel("READY", objectName="badge")
        header.addWidget(self.state_badge)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        main_tab = QWidget()
        main_layout = QVBoxLayout(main_tab)
        main_layout.setContentsMargins(0, 10, 0, 0)
        main_layout.setSpacing(12)
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setContentsMargins(4, 18, 4, 4)
        settings_layout.setSpacing(12)
        self.tabs.addTab(main_tab, "Clicker")
        self.tabs.addTab(settings_tab, "Settings")
        layout.addWidget(self.tabs)
        layout = main_layout

        interval_group = QGroupBox("Click interval")
        interval_layout = QGridLayout(interval_group)
        interval_layout.setHorizontalSpacing(8)
        interval_layout.setVerticalSpacing(3)
        self.hours = self._time_field(self.saved_settings.get("hours", 0), 23)
        self.minutes = self._time_field(self.saved_settings.get("minutes", 0), 59)
        self.seconds = self._time_field(self.saved_settings.get("seconds", 0), 59)
        self.interval = self._time_field(self.saved_settings.get("milliseconds", 100), 999)
        for column, (field, label) in enumerate((
            (self.hours, "hours"), (self.minutes, "minutes"),
            (self.seconds, "seconds"), (self.interval, "milliseconds"),
        )):
            interval_layout.addWidget(field, 0, column)
            caption = QLabel(label, objectName="fieldLabel")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            interval_layout.addWidget(caption, 1, column)
        layout.addWidget(interval_group)

        options_row = QHBoxLayout()
        options_group = QGroupBox("Click options")
        options_layout = QGridLayout(options_group)
        options_layout.addWidget(QLabel("Mouse button"), 0, 0)
        self.button = QComboBox()
        for name, number in (("Left", 1), ("Right", 3), ("Middle", 2)):
            self.button.addItem(name, number)
        self.button.setCurrentIndex(max(0, self.button.findData(self.saved_settings.get("button", 1))))
        options_layout.addWidget(self.button, 1, 0)
        options_layout.addWidget(QLabel("Click type"), 0, 1)
        self.click_type = QComboBox()
        self.click_type.addItem("Single", 1)
        self.click_type.addItem("Double", 2)
        self.click_type.setCurrentIndex(max(0, self.click_type.findData(self.saved_settings.get("click_type", 1))))
        options_layout.addWidget(self.click_type, 1, 1)
        options_row.addWidget(options_group, 1)

        repeat_group = QGroupBox("Click repeat")
        repeat_layout = QGridLayout(repeat_group)
        self.repeat_forever = QRadioButton("Until stopped")
        self.repeat_forever.setChecked(not self.saved_settings.get("repeat_limited", False))
        self.repeat_limited = QRadioButton("Repeat")
        self.repeat_limited.setChecked(self.saved_settings.get("repeat_limited", False))
        self.repeat_count = QSpinBox()
        self.repeat_count.setRange(1, 999_999_999)
        self.repeat_count.setValue(self.saved_settings.get("repeat_count", 10))
        self.repeat_count.setEnabled(self.repeat_limited.isChecked())
        self.repeat_limited.toggled.connect(self.repeat_count.setEnabled)
        self.repeat_count.valueChanged.connect(lambda: self.repeat_limited.setChecked(True))
        self.repeat_count.editingFinished.connect(lambda: self.repeat_limited.setChecked(True))
        repeat_layout.addWidget(self.repeat_forever, 0, 0, 1, 3)
        repeat_layout.addWidget(self.repeat_limited, 1, 0)
        repeat_layout.addWidget(self.repeat_count, 1, 1)
        repeat_layout.addWidget(QLabel("times"), 1, 2)
        options_row.addWidget(repeat_group, 1)
        layout.addLayout(options_row)

        self.permission_panel = QGroupBox("Wayland permission")
        self.permission_panel.setObjectName("permissionPanel")
        permission_layout = QHBoxLayout(self.permission_panel)
        self.permission_text = QLabel(
            "Persistent pointer access has not been granted. Without it, KDE asks again every launch."
        )
        self.permission_text.setWordWrap(True)
        permission_layout.addWidget(self.permission_text, 1)
        self.permission_button = QPushButton("Grant persistent access")
        self.permission_button.setObjectName("permissionButton")
        self.permission_button.clicked.connect(self.request_persistent_permission)
        permission_layout.addWidget(self.permission_button)
        self.permission_panel.setVisible(
            not backend.global_keys and getattr(backend, "permission_required", False)
        )
        layout.addWidget(self.permission_panel)

        actions = QHBoxLayout()
        self.toggle_button = QPushButton("Start (F6)", objectName="startButton")
        self.toggle_button.setMinimumHeight(46)
        self.toggle_button.clicked.connect(self.toggle)
        actions.addWidget(self.toggle_button, 2)
        self.stop_button = QPushButton("Stop (Esc)", objectName="stopButton")
        self.stop_button.setMinimumHeight(46)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        actions.addWidget(self.stop_button, 1)
        layout.addLayout(actions)

        self.status = QLabel("Ready to click", objectName="status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        if backend.global_keys:
            help_message = "Configured hotkey works globally • Top-left screen corner stops"
        else:
            help_message = "On Wayland, keyboard shortcuts work while this window has focus"
        help_text = QLabel(help_message, objectName="helpText")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        baby_group = QGroupBox("Safety")
        baby_layout = QVBoxLayout(baby_group)
        self.baby_mode = QCheckBox("Baby Mode")
        self.baby_mode.setChecked(self.saved_settings.get("baby_mode", False))
        baby_layout.addWidget(self.baby_mode)
        baby_time_row = QHBoxLayout()
        baby_time_row.addWidget(QLabel("Countdown"))
        self.baby_delay = QSpinBox()
        self.baby_delay.setRange(1, 60)
        self.baby_delay.setValue(self.saved_settings.get("baby_delay", 3))
        self.baby_delay.setSuffix(" seconds")
        self.baby_delay.setEnabled(self.baby_mode.isChecked())
        self.baby_mode.toggled.connect(self.baby_delay.setEnabled)
        baby_time_row.addWidget(self.baby_delay)
        baby_time_row.addStretch()
        baby_layout.addLayout(baby_time_row)
        baby_description = QLabel(
            "Wait after Start before clicking, giving you time to move the cursor into position."
        )
        baby_description.setObjectName("settingsDescription")
        baby_description.setWordWrap(True)
        baby_layout.addWidget(baby_description)
        settings_layout.addWidget(baby_group)

        hotkey_group = QGroupBox("Keyboard shortcuts")
        hotkey_layout = QGridLayout(hotkey_group)
        hotkey_layout.addWidget(QLabel("Start / stop hotkey"), 0, 0)
        self.hotkey_edit = HotkeyEdit(QKeySequence(self.saved_settings.get("hotkey", "F6")))
        self.hotkey_edit.setObjectName("hotkeyInput")
        self.hotkey_edit.setMinimumHeight(38)
        self.hotkey_edit.setToolTip("Click here, then press the new keyboard shortcut")
        self.hotkey_edit.setMaximumSequenceLength(1)
        self.hotkey_edit.setClearButtonEnabled(False)
        hotkey_frame = QFrame(objectName="hotkeyInputFrame")
        hotkey_frame_layout = QHBoxLayout(hotkey_frame)
        hotkey_frame_layout.setContentsMargins(8, 2, 5, 2)
        hotkey_frame_layout.addWidget(self.hotkey_edit)
        hotkey_layout.addWidget(hotkey_frame, 0, 1)
        self.apply_hotkey_button = QPushButton("Apply hotkey")
        self.apply_hotkey_button.setObjectName("applyHotkeyButton")
        self.apply_hotkey_button.setMinimumWidth(108)
        self.apply_hotkey_button.clicked.connect(self.apply_hotkey)
        hotkey_layout.addWidget(self.apply_hotkey_button, 0, 2)
        self.escape_stop = QCheckBox("Escape also stops the autoclicker")
        self.escape_stop.setChecked(self.saved_settings.get("escape_stop", True))
        hotkey_layout.addWidget(self.escape_stop, 1, 0, 1, 3)
        hotkey_note = QLabel(
            "The main hotkey toggles Start and Stop. Escape is an optional secondary stop key."
        )
        hotkey_note.setObjectName("settingsDescription")
        hotkey_note.setWordWrap(True)
        hotkey_layout.addWidget(hotkey_note, 2, 0, 1, 3)
        settings_layout.addWidget(hotkey_group)
        settings_layout.addStretch()

        self.local_shortcuts = []
        self.applied_hotkey = self.hotkey_text()
        self.hotkey_edit.keySequenceChanged.connect(self.hotkey_changed)
        self.escape_stop.toggled.connect(self.update_hotkeys)
        self.update_hotkeys()
        self._connect_settings_autosave()

        self.setStyleSheet(self._stylesheet())
        self.click_timer = QTimer(self)
        self.click_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.click_timer.timeout.connect(self.perform_click)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start(20)
        if not backend.ready:
            self.toggle_button.setEnabled(False)
            if getattr(backend, "permission_required", False):
                self.state_badge.setText("ACCESS NEEDED")
                self.status.setText("Grant persistent access before starting")
            else:
                self.state_badge.setText("CONNECTING")
                self.status.setText("Restoring pointer access…")

    @staticmethod
    def _time_field(value, maximum):
        field = QSpinBox()
        field.setRange(0, maximum)
        field.setValue(value)
        return field

    def _read_settings(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return {}

    def _connect_settings_autosave(self):
        for spinbox in (
            self.hours, self.minutes, self.seconds, self.interval,
            self.repeat_count, self.baby_delay,
        ):
            spinbox.valueChanged.connect(self.save_settings)
        for combo in (self.button, self.click_type):
            combo.currentIndexChanged.connect(self.save_settings)
        for toggle in (self.repeat_forever, self.repeat_limited, self.baby_mode, self.escape_stop):
            toggle.toggled.connect(self.save_settings)

    def save_settings(self):
        data = {
            "hours": self.hours.value(),
            "minutes": self.minutes.value(),
            "seconds": self.seconds.value(),
            "milliseconds": self.interval.value(),
            "button": self.button.currentData(),
            "click_type": self.click_type.currentData(),
            "repeat_limited": self.repeat_limited.isChecked(),
            "repeat_count": self.repeat_count.value(),
            "baby_mode": self.baby_mode.isChecked(),
            "baby_delay": self.baby_delay.value(),
            "hotkey": getattr(self, "applied_hotkey", self.hotkey_text()),
            "escape_stop": self.escape_stop.isChecked(),
        }
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(self.settings_path)
        except OSError as exc:
            self.status.setText(f"Could not save settings: {exc}")

    @staticmethod
    def _stylesheet():
        return """
            QWidget#body { background: #181a1f; color: #e8eaf0; }
            QWidget#body QLabel { color: #e1e4ea; }
            QLabel#title { font-size: 25px; font-weight: 750; color: #f7f8fb; }
            QLabel#subtitle { color: #7d8ba3; font-size: 10px; font-weight: 700; padding-top: 7px; }
            QLabel#badge { color: #83d6a0; background: #20362a; border: 1px solid #31523d;
                           border-radius: 10px; padding: 4px 10px; font-size: 10px; font-weight: 700; }
            QGroupBox { background: #20232a; border: 1px solid #343842; border-radius: 7px;
                        margin-top: 10px; padding: 14px 10px 10px; font-weight: 650; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #cdd2dc; }
            QSpinBox, QComboBox, QKeySequenceEdit { background: #16181d; border: 1px solid #414651; border-radius: 5px;
                                 padding: 6px 8px; min-height: 22px; color: #f2f3f7; }
            QKeySequenceEdit QLineEdit { background: transparent; border: 0; color: #f2f3f7; }
            QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus { border-color: #5b8def; }
            QFrame#hotkeyInputFrame { background: #101319; border: 2px solid #65728a;
                                      border-radius: 6px; }
            QFrame#hotkeyInputFrame:hover { border-color: #72a0f3; background: #151b27; }
            QKeySequenceEdit#hotkeyInput { background: transparent; border: 0; padding: 0;
                                           color: #ffffff; }
            QKeySequenceEdit#hotkeyInput:disabled { color: #747c89; }
            QLabel#fieldLabel, QLabel#muted, QLabel#helpText { color: #8e96a6; font-size: 11px; }
            QLabel#settingsDescription { color: #9ca4b3; padding: 2px 22px 4px 22px; }
            QLabel#status { color: #b9c0cc; padding: 2px 4px; }
            QTabWidget::pane { border: 0; }
            QTabBar::tab { color: #929aa9; background: transparent; padding: 8px 18px;
                           border-bottom: 2px solid transparent; }
            QTabBar::tab:selected { color: #f0f2f6; border-bottom-color: #4e82e8; }
            QPushButton { border-radius: 6px; font-weight: 700; padding: 8px 14px; }
            QPushButton#startButton { background: #3977e8; border: 1px solid #5590f4; color: white; }
            QPushButton#startButton:hover { background: #4785f1; }
            QPushButton#stopButton { background: #2a2d34; border: 1px solid #444954; color: #e4e7ed; }
            QPushButton#stopButton:enabled:hover { background: #713d43; border-color: #a34e59; }
            QGroupBox#permissionPanel { background: #332b1d; border-color: #735b2e; }
            QPushButton#permissionButton { background: #6f5423; border: 1px solid #a17a35; color: #fff2d5; }
            QPushButton#permissionButton:hover { background: #806229; }
            QPushButton#applyHotkeyButton { background: #3977e8; border: 1px solid #5590f4; color: white; }
            QPushButton#applyHotkeyButton:hover { background: #4785f1; }
            QPushButton#applyHotkeyButton:pressed { background: #2f67ca; }
            QPushButton#applyHotkeyButton:disabled { color: #7f8794; background: #292d35; border-color: #3b404b; }
            QPushButton:disabled { color: #656b76; background: #24272d; border-color: #343840; }
            QRadioButton { color: #dce0e7; spacing: 7px; }
            QCheckBox { color: #e1e4ea; spacing: 8px; }
            QCheckBox::indicator { width: 15px; height: 15px; }
            QCheckBox::indicator:checked { background: #4e82e8; border: 1px solid #72a0f3; }
            QRadioButton::indicator:checked { background: #4e82e8; border: 3px solid #20232a; }
            QRadioButton::indicator { width: 13px; height: 13px; border-radius: 8px; border: 1px solid #626977; }
        """

    def request_persistent_permission(self):
        self.permission_button.setEnabled(False)
        self.permission_button.setText("Waiting for KDE…")
        self.status.setText("Approve persistent pointer control in the KDE dialog")
        self.backend.request_persistent_permission()

    def interval_ms(self):
        total = (
            self.hours.value() * 3_600_000 + self.minutes.value() * 60_000
            + self.seconds.value() * 1_000 + self.interval.value()
        )
        return total

    def settings_widgets(self):
        return (
            self.hours, self.minutes, self.seconds, self.interval, self.button,
            self.click_type, self.repeat_forever, self.repeat_limited, self.repeat_count,
            self.baby_mode, self.baby_delay, self.hotkey_edit, self.escape_stop,
        )

    def hotkey_text(self):
        text = self.hotkey_edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        return text or "F6"

    def hotkey_changed(self):
        self.apply_hotkey_button.setText("Apply hotkey")

    def apply_hotkey(self):
        if not self.update_hotkeys():
            return
        self.applied_hotkey = self.hotkey_text()
        self.save_settings()
        self.apply_hotkey_button.setText("Applied ✓")
        self.tabs.setCurrentIndex(0)
        self.toggle_button.setFocus(Qt.FocusReason.OtherFocusReason)
        self.status.setText(f"Hotkey changed to {self.hotkey_text()}")

    def update_hotkeys(self):
        hotkey = self.hotkey_text()
        if not self.hotkey_edit.keySequence().toString():
            self.hotkey_edit.setKeySequence(QKeySequence(hotkey))
        if hasattr(self.backend, "set_hotkeys"):
            try:
                self.backend.set_hotkeys(hotkey, self.escape_stop.isChecked())
            except ValueError as exc:
                self.status.setText(str(exc))
                return False
        for shortcut in self.local_shortcuts:
            shortcut.setParent(None)
            shortcut.deleteLater()
        self.local_shortcuts.clear()
        if not self.backend.global_keys:
            bindings = [(hotkey, self.toggle)]
            if self.escape_stop.isChecked() and hotkey not in ("Esc", "Escape"):
                bindings.append(("Escape", self.stop))
            for key, callback in bindings:
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setAutoRepeat(False)
                shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
                shortcut.activated.connect(callback)
                self.local_shortcuts.append(shortcut)
        self.update_action_labels()
        return True

    def update_action_labels(self):
        hotkey = self.hotkey_text()
        self.toggle_button.setText(f"Running… ({hotkey})" if self.active else f"Start ({hotkey})")
        stop_keys = hotkey
        if self.escape_stop.isChecked() and hotkey not in ("Esc", "Escape"):
            stop_keys = f"Esc / {hotkey}"
        self.stop_button.setText(f"Stop ({stop_keys})")

    def toggle(self):
        if not self.active and time.monotonic() < self.restart_not_before:
            return
        if not self.backend.ready or (not self.toggle_button.isEnabled() and not self.active):
            return
        if self.active:
            self.stop()
            return
        self.active = True
        self.click_count = 0
        self.repeat_progress = 0
        for widget in self.settings_widgets():
            widget.setEnabled(False)
        self.update_action_labels()
        self.toggle_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        if self.baby_mode.isChecked():
            delay = self.baby_delay.value()
            self.deadline = time.monotonic() + delay
            self.state_badge.setText("STARTING")
            self.status.setText(f"Baby Mode • starting in {delay} seconds…")
        else:
            self.begin_clicking()

    def begin_clicking(self):
        self.deadline = None
        self.click_timer.start(self.interval_ms())
        self.state_badge.setText("CLICKING")
        self.perform_click()

    def stop(self, message=None):
        self.active = False
        self.deadline = None
        self.click_timer.stop()
        for widget in self.settings_widgets():
            widget.setEnabled(True)
        self.repeat_count.setEnabled(self.repeat_limited.isChecked())
        self.baby_delay.setEnabled(self.baby_mode.isChecked())
        self.update_action_labels()
        self.toggle_button.setEnabled(self.backend.ready)
        self.stop_button.setEnabled(False)
        self.state_badge.setText("READY")
        self.status.setText(message or f"Stopped • {self.click_count} clicks")

    def poll(self):
        try:
            keys = self.backend.pressed_keys()
            if not self.backend.global_keys:
                permission_required = getattr(self.backend, "permission_required", False)
                self.permission_panel.setVisible(permission_required)
                if self.backend.ready:
                    self.permission_button.setText("Grant persistent access")
                    self.permission_button.setEnabled(permission_required)
                    if not self.active:
                        self.state_badge.setText("READY")
            if self.backend.ready and not self.toggle_button.isEnabled() and not self.active:
                self.toggle_button.setEnabled(True)
                self.status.setText("Ready to click")
            if "escape" in keys:
                if self.active:
                    self.stop()
            elif "toggle" in keys - self.previous_keys:
                self.toggle()
            self.previous_keys = keys
            if self.deadline is not None:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    self.begin_clicking()
                else:
                    self.status.setText(f"Baby Mode • starting in {int(remaining) + 1} seconds…")
        except Exception as exc:
            self.fail(exc)

    def perform_click(self):
        if not self.active:
            return
        try:
            if "escape" in self.backend.pressed_keys():
                self.stop()
                return
            click_total = self.click_type.currentData()
            result = self.backend.click(self.button.currentData(), click_total)
            if result is False:
                self.stop("Stopped • cursor reached the top-left corner")
                return
            if result is True:
                self.click_count += click_total
                self.repeat_progress += 1
            if self.repeat_limited.isChecked() and self.repeat_progress >= self.repeat_count.value():
                # Ignore a duplicate/held hotkey event from the activation that
                # started this short finite run. Without this latch, fast runs
                # can stop and immediately begin again at click 1.
                self.restart_not_before = time.monotonic() + 0.75
                self.stop(f"Complete • {self.click_count} clicks")
            else:
                self.status.setText(f"Clicking at current cursor • {self.click_count} clicks")
        except Exception as exc:
            self.fail(exc)

    def fail(self, exc):
        self.stop(f"Input connection failed: {exc}")
        self.poll_timer.stop()
        self.toggle_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.state_badge.setText("ERROR")

    def closeEvent(self, event):
        self.stop()
        self.poll_timer.stop()
        self.backend.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ForLazy")
    try:
        wayland = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY")
        backend = PortalClicker() if wayland else X11Clicker()
    except RuntimeError as exc:
        QMessageBox.critical(None, "ForLazy cannot start", str(exc))
        return 1
    window = ForLazyWindow(backend)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
