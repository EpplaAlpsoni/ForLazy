# ForLazy

A simple Linux autoclicker made with PySide6. Choose an interval, mouse button,
single or double clicks, and whether to run continuously or for a fixed count.
Press Start, then move the cursor where you want to click.

> **Platform:** ForLazy is Linux-only. It uses Linux input interfaces for X11
> and Wayland and does not support Windows or macOS.

## Install on Linux

ForLazy installs for your user account and does not need root access or a distro
package manager. Download or clone the project, open a terminal in its folder,
and run:

```bash
./install.sh
```

The installer places the app in `~/.local/share/forlazy`, adds the user-wide
command `~/.local/bin/forlazy`, and creates an application-menu entry. Launch
**ForLazy** from your desktop's app menu or run:

```bash
forlazy
```

If your shell does not include `~/.local/bin` in `PATH`, use
`~/.local/bin/forlazy` directly. The source folder can be moved or deleted after
installation. Run `./install.sh` again to update an existing installation.

The first installation needs `curl`, standard Linux desktop libraries, internet
access, and roughly 1 GB of free space. It downloads a private Python 3.12,
[uv](https://docs.astral.sh/uv/), and Python dependencies into the installed app
directory. It does not modify system Python or use `apt`, `dnf`, `pacman`,
`sudo`, or root access. Later launches work offline.

For a portable checkout without installing a command or menu entry, run
`bash run.sh` from the project folder.

On SteamOS, perform installation and use from Desktop Mode. The rootless install
works without disabling the read-only system partition.

## Use

1. On Wayland, select **Grant persistent access** and approve KDE's permission
   dialog. ForLazy saves the grant and normally reconnects silently next time.
2. Set the interval using hours, minutes, seconds, and milliseconds. Choose the
   mouse button, single or double clicks, and continuous or fixed-count repeat.
3. Press **Start**. Clicking begins immediately unless Baby Mode is enabled.
4. Press **Stop** to finish. Closing ForLazy also stops clicking.

The **Settings** tab contains **Baby Mode**, which is disabled by default. Turn
it on to add a configurable 1–60 second safety countdown after pressing Start.
With Baby Mode off, clicking begins immediately.

Settings also lets you replace the default **F6** start/stop hotkey and choose
whether **Escape** acts as a secondary stop key. The custom hotkey is global on
X11; Wayland shortcuts work while ForLazy has focus. Enter a shortcut and select
**Apply**. The Stop button shows every key that can stop the clicker.

Entering or changing the repeat count automatically selects **Repeat**. The
count represents click actions, so repeating a double-click three times sends
six individual clicks.

All clicker and app settings are saved automatically in `.tools/settings.json`
and restored on the next launch. The file is created with user-only permissions.

Clicks follow the cursor. Intervals range from 10 ms to one hour; timing is
best effort, not a real-time guarantee. Settings are locked while running.

| Desktop session | Start/stop controls |
| --- | --- |
| X11 | The configured hotkey toggles globally; optional Escape stops globally. Moving to the top-left corner also stops. |
| Wayland | Configured shortcuts work **only while ForLazy has focus**. Alt+Tab back to ForLazy to stop, or end sharing through the desktop's sharing indicator. No corner stop. |

Wayland uses the desktop's
[Remote Desktop portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html)
for local pointer control. No network server or screen recording is started.
The first grant always requires KDE's confirmation. ForLazy stores the portal's
single-use restore token in `.tools/portal-restore-token` with user-only file
permissions and replaces it after every successful restoration. KDE can prompt
again if permission is denied, revoked, or cannot be restored.
The desktop must provide this portal (as KDE Plasma does). Gaming Mode and
applications that block synthetic input are not supported.

## Troubleshooting

- **Download fails:** check your internet connection, then rerun `bash run.sh`.
- **Permission denied/cancelled on Wayland:** close ForLazy and reopen it to retry.
- **Portal unavailable:** launch from your KDE Desktop Mode session. A Wayland
  compositor without a Remote Desktop portal cannot provide this input method.
- **Cannot connect to X11:** run from a terminal in your desktop session, not SSH.
- **Qt cannot load a platform plugin:** use the regular SteamOS desktop session
  and remove custom `QT_PLUGIN_PATH` / `QT_QPA_PLATFORM_PLUGIN_PATH` overrides.

To uninstall the user-wide installation, remove `~/.local/share/forlazy`,
`~/.local/bin/forlazy`, and `~/.local/share/applications/forlazy.desktop`.
No system packages or shell profiles are changed.

## Development

```bash
bash run.sh --install-only
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

Tests use fake input backends and mocked portal calls; they do not click your
desktop. Actual Wayland input requires an interactive permission grant.
