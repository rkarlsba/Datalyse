"""
Tests for the platform differences the GUI depends on.

The module decides macOS-vs-elsewhere at import time, so each test loads it
fresh from source with ``sys.platform`` patched.  Loading it into a throwaway
module object keeps the shared import untouched, which matters because the rest
of the suite must keep seeing the real platform.
"""
import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "datalogger", "platform_support.py")

_counter = 0


def load_for(platform: str):
    """Import platform_support.py as if running on ``platform``."""
    global _counter
    _counter += 1
    spec = importlib.util.spec_from_file_location(f"_ps_{platform}_{_counter}",
                                                  SOURCE)
    mod = importlib.util.module_from_spec(spec)
    real = sys.platform
    sys.platform = platform
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.platform = real
    return mod


class FakeWidget:
    """Records what a real Tk widget would have been asked to bind."""

    def __init__(self):
        self.bound = {}

    def bind(self, sequence, func):
        self.bound[sequence] = func


# ------------------------------------------------------------------ modifiers
@pytest.mark.parametrize("platform,expected_mod,expected_accel", [
    ("darwin", "Command", "\u2318O"),
    ("linux", "Control", "Ctrl+O"),
    ("win32", "Control", "Ctrl+O"),
])
def test_modifier_follows_platform(platform, expected_mod, expected_accel):
    m = load_for(platform)
    assert m.MOD_LABEL == expected_mod
    assert m.accelerator("O") == expected_accel


def test_bind_uses_command_on_macos_not_control():
    """
    A <Control-o> binding never fires on macOS, so this is the difference
    between a working shortcut and one that silently does nothing.
    """
    w = FakeWidget()
    m = load_for("darwin")
    seq = m.bind_mod(w, "o", lambda: None)
    assert seq == "<Command-o>"
    assert "<Command-o>" in w.bound
    assert "<Control-o>" not in w.bound


def test_bind_uses_control_elsewhere():
    w = FakeWidget()
    m = load_for("linux")
    seq = m.bind_mod(w, "o", lambda: None)
    assert seq == "<Control-o>"
    assert "<Control-o>" in w.bound


# ---------------------------------------------------------------- serial ports
def test_macos_sorts_callout_ports_first():
    """
    On macOS the tty.* nodes wait for DCD and hang on instruments that do not
    assert it, so cu.* must come first.
    """
    m = load_for("darwin")
    ports = ["/dev/tty.usbserial-1420", "/dev/cu.usbserial-1420",
             "/dev/cu.usbmodem-1101"]
    order = sorted(ports, key=m._sort_key)
    assert order[0].startswith("/dev/cu."), order
    assert order[-1].startswith("/dev/tty."), order


def test_linux_sorts_usb_before_motherboard_ports():
    m = load_for("linux")
    ports = ["/dev/ttyS0", "/dev/ttyUSB0", "/dev/ttyACM0"]
    order = sorted(ports, key=m._sort_key)
    assert order[0] == "/dev/ttyACM0" or order[0] == "/dev/ttyUSB0"
    assert order[-1] == "/dev/ttyS0"


def test_default_port_is_never_a_linux_path_on_macos(monkeypatch):
    m = load_for("darwin")
    monkeypatch.setattr(m, "preferred_ports", lambda: [])
    port = m.default_serial_port()
    assert port.startswith("/dev/cu."), port
    assert "ttyUSB" not in port


def test_default_port_offers_a_real_port_when_one_exists(monkeypatch):
    m = load_for("darwin")
    monkeypatch.setattr(m, "preferred_ports", lambda: ["/dev/cu.usbserial-1420"])
    assert m.default_serial_port() == "/dev/cu.usbserial-1420"


def test_default_port_falls_back_per_platform(monkeypatch):
    for platform, prefix in (("linux", "/dev/tty"), ("win32", "COM")):
        m = load_for(platform)
        monkeypatch.setattr(m, "preferred_ports", lambda: [])
        assert m.default_serial_port().startswith(prefix)


def test_list_serial_ports_returns_pairs():
    m = load_for(sys.platform)
    for dev, desc in m.list_serial_ports():
        assert isinstance(dev, str) and dev
        assert isinstance(desc, str)


def test_windows_glob_fallback_returns_nothing_rather_than_guessing():
    """There are no COM* nodes to glob, so an empty list beats an invention."""
    m = load_for("win32")
    assert m._glob_ports() == []


def test_macos_glob_fallback_finds_cu_nodes():
    m = load_for("darwin")
    for dev, _ in m._glob_ports():
        assert os.path.basename(dev).startswith("cu."), dev


# -------------------------------------------------------------------- dialogs
@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_filetype_patterns_are_tcl_lists(platform):
    """
    tkinter turns a tuple into the Tcl list the aqua dialog requires.  A single
    space-separated string like "*.DAT *.dat" works on X11/Windows but is
    misread on macOS, so patterns must never contain spaces.
    """
    m = load_for(platform)
    for label, patterns in m.data_filetypes():
        assert isinstance(patterns, tuple)
        for pat in patterns:
            assert " " not in pat, (label, pat)


def test_filetypes_cover_datalyse_extensions():
    m = load_for("darwin")
    pats = m.data_filetypes()[0][1]
    for ext in ("*.DAT", "*.dat", "*.TXT", "*.txt"):
        assert ext in pats


# ------------------------------------------------------------------ mac extras
def test_app_menu_is_a_noop_off_macos():
    m = load_for("linux")

    class R:
        def createcommand(self, *a):        # pragma: no cover - must not run
            raise AssertionError("createcommand called off macOS")

    assert m.install_macos_app_menu(R(), on_about=lambda: None) is False


def test_app_menu_installs_on_macos():
    m = load_for("darwin")

    class R:
        def __init__(self):
            self.commands = {}

        def createcommand(self, name, fn):
            self.commands[name] = fn

    r = R()
    assert m.install_macos_app_menu(r, on_about=lambda: None,
                                    on_quit=lambda: None) is True
    assert "::tk::mac::Quit" in r.commands


def test_platform_notes_describe_the_host():
    assert "macOS" in load_for("darwin").platform_notes()
    assert "Linux" in load_for("linux").platform_notes()
    assert "Windows" in load_for("win32").platform_notes()
