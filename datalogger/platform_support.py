"""
Platform differences that the Tk front end has to respect.

Datalyse was a Windows program, so several things in the port were written the
Windows way by default.  Running the GUI on macOS needs all of them to move:

* **Modifier keys.**  ``Ctrl+O`` is wrong on macOS -- it is ``Command+O``, and
  a ``<Control-o>`` binding never fires.  Both the accelerator text and the
  binding have to follow the platform.
* **Serial port names.**  ``/dev/ttyUSB0`` does not exist on macOS, where the
  devices are ``/dev/cu.usbserial-*`` / ``/dev/cu.usbmodem-*``.  Hardcoding the
  Linux name means the port field is pre-filled with something that cannot
  work.  On macOS the ``cu.*`` (call-out) nodes are the right ones to open, not
  the ``tty.*`` (dial-in) nodes, which block waiting for carrier.
* **File-type filters.**  Tk's ``-filetypes`` takes a list of patterns.  A
  single space-separated string such as ``"*.DAT *.dat"`` works on Windows and
  X11 but is misread by the aqua file dialog, so the patterns are passed as
  Tcl lists.
* **Application menu.**  On macOS ``Quit`` belongs in the application menu, and
  Tk provides ``::tk::mac::Quit`` for it.  An "Exit" item buried in the File
  menu is the Windows convention.
* **Window focus.**  A Tk window launched from a terminal on macOS commonly
  opens behind the terminal, so it is raised explicitly.

Nothing here needs to be imported to run the CLI; it is only used by ``gui.py``.
"""
from __future__ import annotations

import glob
import os
import sys

__all__ = [
    "IS_MACOS", "IS_WINDOWS", "IS_LINUX",
    "MOD_LABEL", "MOD_SYMBOL", "accelerator", "bind_mod",
    "default_serial_port", "list_serial_ports", "preferred_ports",
    "data_filetypes", "csv_filetypes", "all_filetypes",
    "install_macos_app_menu", "raise_window", "platform_notes",
]

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = not IS_MACOS and not IS_WINDOWS

#: Tk modifier name, for ``bind()``.
MOD_LABEL = "Command" if IS_MACOS else "Control"
#: How the modifier is written in a menu accelerator.
MOD_SYMBOL = "\u2318" if IS_MACOS else "Ctrl+"   # ⌘


def accelerator(key: str) -> str:
    """``accelerator("O")`` -> ``'⌘O'`` on macOS, ``'Ctrl+O'`` elsewhere."""
    return f"{MOD_SYMBOL}{key}"


def bind_mod(widget, key: str, func) -> str:
    """
    Bind ``<Command-o>`` on macOS, ``<Control-o>`` elsewhere.

    Returns the sequence that was bound, which is what the tests assert on.
    """
    seq = f"<{MOD_LABEL}-{key}>"
    widget.bind(seq, lambda _e: func())
    return seq


# ----------------------------------------------------------------- serial ports
def _sort_key(device: str) -> tuple:
    """
    Order ports so the likely ones come first.

    On macOS ``cu.*`` is preferred over ``tty.*`` because the ``tty.*`` nodes
    wait for DCD and appear to hang with instruments that do not assert it.
    """
    base = os.path.basename(device)
    if IS_MACOS:
        rank = 0 if base.startswith("cu.") else 1
    elif IS_WINDOWS:
        rank = 0
    else:
        # /dev/ttyUSB*, /dev/ttyACM* are real converters; /dev/ttyS* are the
        # motherboard ports that are almost never what you want.
        rank = 0 if (base.startswith("ttyUSB") or base.startswith("ttyACM")
                     or base.startswith("cu.")) else 1
    return (rank, device)


def _glob_ports() -> list[tuple[str, str]]:
    """
    Fallback enumeration by globbing device nodes.

    Used when pyserial is not installed.  On Windows there are no nodes to
    glob, so this returns nothing rather than inventing COM names.
    """
    if IS_WINDOWS:
        return []
    # Derived from the import-time IS_* flags rather than re-reading
    # sys.platform, so the module cannot disagree with itself.
    if IS_MACOS:
        patterns = ["/dev/cu.*"]
    else:
        patterns = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyS*"]
    out: list[tuple[str, str]] = []
    for pat in patterns:
        for dev in glob.glob(pat):
            if not dev.endswith((".init", ".lock")):
                out.append((dev, ""))
    return sorted(set(out), key=lambda t: _sort_key(t[0]))


def list_serial_ports() -> list[tuple[str, str]]:
    """
    Available serial ports as ``(device, description)``.

    Uses pyserial when it is installed, because it knows the USB
    vendor/product descriptions.  Otherwise falls back to globbing the device
    nodes, so the GUI still offers a usable list with no dependency.
    """
    try:
        from serial.tools import list_ports          # type: ignore
    except Exception:                                 # noqa: BLE001 - optional
        return _glob_ports()
    found = [(p.device, p.description or "") for p in list_ports.comports()]
    return sorted(found, key=lambda t: _sort_key(t[0]))


def preferred_ports() -> list[str]:
    """Just the device names, preferred first."""
    return [dev for dev, _ in list_serial_ports()]


def default_serial_port() -> str:
    """
    A sensible starting value for the port field.

    Returns the first real port if one is present, otherwise a platform-correct
    placeholder -- never a Linux path on macOS.
    """
    ports = preferred_ports()
    if ports:
        return ports[0]
    if IS_MACOS:
        return "/dev/cu.usbserial"
    if IS_WINDOWS:
        return "COM1"
    return "/dev/ttyUSB0"


# --------------------------------------------------------------- file dialogs
def data_filetypes() -> list[tuple[str, tuple[str, ...]]]:
    """
    Filter for Datalyse's own files.

    Patterns are tuples, which tkinter turns into the Tcl list the aqua dialog
    needs; a single space-separated string works on X11/Windows but is misread
    on macOS.
    """
    return [
        ("Datalyse data", ("*.DAT", "*.dat", "*.TXT", "*.txt")),
        ("All files", ("*",)),
    ]


def csv_filetypes() -> list[tuple[str, tuple[str, ...]]]:
    return [("CSV", ("*.csv",)), ("All files", ("*",))]


def all_filetypes() -> list[tuple[str, tuple[str, ...]]]:
    return [("All files", ("*",))]


# ------------------------------------------------------------------ mac extras
def install_macos_app_menu(root, on_about=None, on_quit=None) -> bool:
    """
    Wire up the macOS application menu entries.

    macOS routes Cmd+Q and the About item through Tcl commands rather than
    through a cascade in the menu bar, so they are registered here.  Returns
    True when the commands were installed (i.e. on macOS).
    """
    if not IS_MACOS:
        return False
    try:
        if on_quit is not None:
            root.createcommand("::tk::mac::Quit", on_quit)
        if on_about is not None:
            # Shown under "About <app>" in the application menu.
            root.createcommand("tk::mac::ShowHelp", on_about)
        # Keep the app usable after all windows are closed: clicking the Dock
        # icon should bring it back rather than leave a dead process.
        app = root
        root.createcommand("tk::mac::ReopenApplication",
                           lambda: (app.deiconify(), raise_window(app)))
        return True
    except Exception:                                 # noqa: BLE001 - not fatal
        return False


def raise_window(window) -> None:
    """
    Bring a Tk window to the front.

    On macOS a window started from a terminal usually opens behind it, so it is
    lifted, briefly made topmost, then released.
    """
    try:
        window.deiconify()
        window.lift()
        window.focus_force()
        if IS_MACOS:
            window.attributes("-topmost", True)
            window.after(300, lambda: window.attributes("-topmost", False))
    except Exception:                                 # noqa: BLE001 - cosmetic
        pass


def platform_notes() -> str:
    """One-line description used by the About box and the status bar."""
    if IS_MACOS:
        return f"macOS  (modifier: {MOD_SYMBOL}, ports: /dev/cu.*)"
    if IS_WINDOWS:
        return "Windows  (modifier: Ctrl+, ports: COM*)"
    return "Linux  (modifier: Ctrl+, ports: /dev/ttyUSB*)"
