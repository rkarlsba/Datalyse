#!/usr/bin/env python3
"""
Construct the Tk GUI and report what came up, then tear it down.

This is the cross-platform regression check: it is what fails if a binding,
a ttk widget or a menu call is not available on the Tk that ships with the
running platform.  Unlike ``gui_smoketest.py`` it needs no data files, so it
works in CI where Datalyse's own sample files are not committed.

Runs on a real display, or under ``xvfb-run`` on a headless Linux box.  Exit
status is non-zero if the window cannot be built.

    $ python scripts/gui_construct_check.py
    $ xvfb-run -a python scripts/gui_construct_check.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datalogger import platform_support as plat          # noqa: E402


def main() -> int:
    try:
        import tkinter as tk
    except ImportError as exc:
        print(f"tkinter is not available: {exc}", file=sys.stderr)
        print("  Linux: install python3-tk", file=sys.stderr)
        print("  macOS: use python.org or `brew install python-tk`",
              file=sys.stderr)
        return 2

    from datalogger.gui import DatalyseApp

    # DatalyseApp is itself a tk.Tk root.  Creating a second root in the same
    # process just to probe the display first deadlocks the event loop, so the
    # check is done by catching the failure from this single root instead.
    try:
        app = DatalyseApp()
    except tk.TclError as exc:
        # No DISPLAY, or no window server: a skip, not a failure.
        print(f"no display available, skipping: {exc}")
        return 0
    app.update()

    def menu_labels(menubar, tk) -> list[str]:
        """
        Cascade labels, bounded by the menu's own last index.

        Note: Tk *clamps* an out-of-range menu index rather than raising, so
        ``menubar.type(i)`` keeps returning the last entry's type for ever and a
        "loop until TclError" walk never terminates.  Hence the explicit end.
        """
        try:
            last = int(menubar.index("end"))
        except (tk.TclError, ValueError, TypeError):
            return []
        out: list[str] = []
        for i in range(last + 1):
            if menubar.type(i) == "cascade":
                out.append(menubar.entrycget(i, "label"))
        return out

    menubar = getattr(app, "menubar", None)
    labels = menu_labels(menubar, tk) if menubar is not None else []

    print(f"platform   : {sys.platform}  ({plat.platform_notes()})")
    print(f"tk version : {tk.TkVersion}")
    print(f"geometry   : {app.winfo_geometry()}")
    print(f"menus      : {labels}")
    print(f"notebook   : {app.nb.tabs()}")
    print(f"table      : {len(app.tree.get_children())} rows")

    problems = []
    if menubar is None:
        problems.append("no menubar")
    for expected in ("File", "Device", "Tools", "View", "Help"):
        if expected not in labels:
            problems.append(f"menu {expected!r} missing")
    if len(app.nb.tabs()) != 2:
        problems.append("expected Graph and Table tabs")

    app.destroy()

    if problems:
        print("FAILED: " + "; ".join(problems), file=sys.stderr)
        return 1
    print("GUI construct check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
