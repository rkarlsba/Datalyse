# Running the GUI on macOS

The Tk front end is not Windows- or Linux-specific; the same `gui.py` runs on
macOS. This document covers what had to change for that to be true, how to
install it, and the serial-adapter specifics that catch people out.

## Install

```console
$ git clone git@github.com:rkarlsba/Datalyse.git
$ cd Datalyse
$ python3 -m venv .venv && . .venv/bin/activate
$ pip install -e ".[all]"          # pyserial + numpy + matplotlib
$ python -m datalogger gui
```

## Tkinter, and which Python you use

`tkinter` is not a pip package — it ships with Python, or it doesn't. Which one
you get matters on macOS:

| Python from | Tk version | Verdict |
|---|---|---|
| **python.org** installer | 8.6.x / 9.0 | works, recommended |
| **Homebrew** (`brew install python` + `brew install python-tk`) | 8.6.x / 9.0 | works |
| Apple's `/usr/bin/python3` (Command Line Tools) | **8.5.9**, deprecated | avoid |

The system Python links against Apple's long-deprecated Tk 8.5.9. It is known to
misrender `ttk` widgets and to crash on some dialog interactions. Check yours:

```console
$ python3 -c "import tkinter; print(tkinter.TkVersion)"
8.6.12      # good
9.0         # good
8.5         # install a different Python
```

Homebrew splits Tk out of the Python formula, so `import tkinter` fails until
you add it. Install the variant matching your Python:

```console
$ brew install python-tk@3.12        # or: brew install python-tk
```

## What changed for macOS

The original was a Windows program, so several things were Windows-shaped by
default. All of it now lives in `datalogger/platform_support.py`, with tests in
`tests/test_platform.py` that load that module under each platform in turn.

**Modifier keys.** The File menu said `Ctrl+O` and bound `<Control-o>`. On macOS
that accelerator is wrong and the binding never fires — it is `Command+O`
(`<Command-o>`). Both the label and the binding now follow the platform, and
`Cmd+S` saves. Quit moved to the application menu with `Cmd+Q`, wired through
`::tk::mac::Quit`, because an "Exit" item in the File menu is the Windows
convention.

**Serial port names.** The port field was pre-filled with `/dev/ttyUSB0`, which
does not exist on macOS — so the field started out filled with something that
could never work. It is now a dropdown of the ports actually attached, and the
fallback placeholder is platform-correct.

**File dialogs.** Tk's `-filetypes` takes a list of patterns, and a
space-separated string like `"*.DAT *.dat"` works on Windows and X11 but is
misread by the aqua file dialog. Patterns are now tuples, which tkinter converts
into the Tcl list macOS expects.

**Window focus.** A Tk window launched from Terminal on macOS normally opens
*behind* it, which reads as "nothing happened". The window is now raised and
briefly made topmost.

## Serial adapters

Instruments here are RS-232, so you need a USB-to-serial adapter.

| Chip | macOS support |
|---|---|
| **FTDI** FT232R/FT232RL | driver built into macOS 10.9+ — usually just works |
| **Silicon Labs** CP2102/CP2104 | driver built into macOS 10.9+ |
| **WCH** CH340/CH341 | driver needed on some versions; WCH publishes one |
| **Prolific** PL2303 | avoid — newer macOS removed support for many revisions |

### Port names: use `cu.*`, not `tty.*`

macOS exposes each adapter twice, and the two are not interchangeable:

```
/dev/tty.usbserial-1420     dial-in node -- blocks waiting for DCD
/dev/cu.usbserial-1420      call-out node -- opens immediately
```

Some instruments never assert DCD, so opening the `tty.*` node appears to hang
for the full timeout and then fails with nothing useful. **Always use `cu.*`.**

List what is attached:

```console
$ python -m datalogger ports
$ ls /dev/cu.*
```

The GUI's port dropdown already sorts `cu.*` first for this reason, and
`tests/test_platform.py` asserts that ordering.

## Permissions

No `sudo` needed — `/dev/cu.*` nodes are world read/write. If yours are not:

```console
$ ls -l /dev/cu.usbserial-1420
crw-rw-rw-  1 root  wheel   ...   /dev/cu.usbserial-1420
```

If it shows something narrower, a leftover kernel extension or a stale driver
install is the usual cause; reinstalling the vendor driver restores the default
ownership.

## Verifying it works without hardware

There is no macOS-specific CI job that fakes an instrument, but the test suite is
exercised on real macOS runners in CI, including constructing the GUI itself:

```console
$ python -m pytest tests -q
$ python -c "import datalogger.gui as g; a=g.DatalyseApp(); a.update(); a.destroy()"
```

Hardware-free end-to-end testing uses a pseudo-terminal, so the serial path is
genuinely exercised without a device:

```console
$ python -m pytest tests/test_core.py -q -k pty
```

## Making a real `.app`

Optional. `py2app` bundles the venv into a double-clickable application:

```console
$ pip install py2app
$ python setup.py py2app        # needs a setup.py naming datalogger.gui:main
```

Not set up here, because the GUI is usually run from a terminal where the
project's `original/` data files and the CLI are also at hand. A bundle would
also need its own copy of `Datalyse.ini`; see `scripts/reverse.sh`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `ModuleNotFoundError: No module named 'tkinter'` | Homebrew Python without `python-tk` |
| Window never appears | it opened behind Terminal — check the Dock; it is also raised on start |
| `could not open port /dev/tty.usbserial-*` | you used the `tty.*` node; use `/dev/cu.*` |
| No ports in the dropdown | adapter driver not loaded — check `ls /dev/cu.*` first |
| Garbled readings | wrong line settings for that device; check `datalogger info <n>` |
| Menu items look wrong / blank dialogs | you are on Tk 8.5.9 — use a different Python |
