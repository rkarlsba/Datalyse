#!/usr/bin/env python3
"""
Smoke-test the Tk front end for real: build it, load a shipped data file,
render the graph, screenshot the window, and tear down.

Run with a display available (DISPLAY set).  Writes:
  docs/gui_screenshot.png  -- the live window
  docs/gui_graph.png       -- the matplotlib figure as drawn in the GUI
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datalogger.datafile import DataFile            # noqa: E402
from datalogger.gui import DatalyseApp              # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs")
os.makedirs(OUT, exist_ok=True)

app = DatalyseApp(os.path.join(ROOT, "original", "DATALYSE.INI"))

# exercise the real code paths the menus use
app.data = DataFile.load(os.path.join(ROOT, "original", "FIXING.DAT"))
app.refresh_all()
app.nb.select(0)
app.update_idletasks()
app.update()
app.status(f"loaded FIXING.DAT: {len(app.data.rows)} rows")

# give the window manager a moment, then screenshot the live window
time.sleep(1.5)
app.update()
wid = app.winfo_id()
shot = os.path.join(OUT, "gui_screenshot.png")
for cmd in (["import", "-window", str(wid), shot],
            ["import", "-window", "root", shot]):
    try:
        subprocess.run(cmd, check=True, timeout=30)
        break
    except Exception as exc:                          # noqa: BLE001
        print("screenshot attempt failed:", exc, file=sys.stderr)

app.fig.savefig(os.path.join(OUT, "gui_graph.png"), dpi=110)
print("window id      :", wid)
print("geometry       :", app.winfo_geometry())
print("notebook tabs  :", [app.nb.tab(i, "text") for i in range(app.nb.index("end"))])
print("table rows     :", len(app.tree.get_children()))
print("menubar        :", app.cget("menu") != "")
print("screenshot     :", shot, os.path.getsize(shot) if os.path.exists(shot) else "MISSING")
app.destroy()
print("GUI smoke test OK")
