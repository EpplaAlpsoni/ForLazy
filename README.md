# ForLazy
I made this out of pure hatred and spite. Sure, _clicker_ in the discovery could work but I didn't like it. I'm so petty.

A simple Linux autoclicker made with PySide6. Choose an interval, mouse button,
single or double clicks, and whether to run continuously or for a fixed count.
Press Start, then move the cursor where you want to click.

> **Platform:** ForLazy is Linux-only. It uses Linux input interfaces for X11
> and Wayland and does not support Windows or macOS.

## Install

1. Download **install-forlazy.sh** from the latest release.
2. Open a terminal and run:

```bash
bash ~/Downloads/install-forlazy.sh
```

3. Open **ForLazy** from your app menu.

That's it. No root, `sudo`, distro package manager, or SteamOS read-only changes are needed.

The first install needs an internet connection and roughly 1 GB of free space. After installation, ForLazy can launch offline. To update, download the newest installer and run it again.

On SteamOS, install and use ForLazy from Desktop Mode.

### Portable / development use

If you cloned the repository and don't want to install ForLazy, run:

```bash
bash run.sh
```

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

| Desktop session | Start/stop controls |
| --- | --- |
| X11 | The configured hotkey toggles globally; optional Escape stops globally. Moving to the top-left corner also stops. |
| Wayland | The configured hotkey toggles globally. Portal permission may be required for pointer control. |

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

- **Download fails:** check your internet connection and make sure `curl` is installed, then run the installer again.
- **ForLazy command not found after installation:** launch it from your app menu or run `~/.local/bin/forlazy` directly. Your shell may not include `~/.local/bin` in `PATH`.
- **Permission denied/cancelled on Wayland:** close ForLazy and reopen it to retry the permission request.
- **Portal unavailable on Wayland:** your desktop/compositor must provide the Remote Desktop portal. Make sure `xdg-desktop-portal` and the appropriate portal backend for your desktop are available and running.
- **Cannot connect to X11:** launch ForLazy from a terminal inside your graphical desktop session rather than SSH or a non-graphical session.
- **Qt cannot load a platform plugin:** remove custom `QT_PLUGIN_PATH` / `QT_QPA_PLATFORM_PLUGIN_PATH` overrides and try again from your normal desktop session.
- **Clicks do not work in a particular application:** some applications, games, compositors, or security configurations may reject synthetic input even when ForLazy itself is working.
- **SteamOS or another immutable distro:** use the rootless installer normally. ForLazy does not require changing the read-only system partition. If the desktop portal itself is missing or broken, repair it using the method recommended by your distribution rather than modifying the system specifically for ForLazy.

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
