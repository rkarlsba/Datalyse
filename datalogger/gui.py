"""
Tk front end, mirroring the original's form and menu structure.

The menu points are the ones recovered from ``TDataForm`` in the resources of
``Datalyse.exe``:

    File    Open / Save data / Save data as / Font for graph / Exit
    Device  Choose Device / Terminal / Math / Two Devices / More Devices /
            Simulation (Titration curves, Data collection without devices,
                        Half life, Poisson)
    Device Menu  Measure (t,f(t)) / View (t,f(t)) / Multitable / (t,y) Graph /
                 (x,y) Graph / Terminal
    Tools   Autoscale / Scaling of axis / Formatting / Fit function /
            Linear regression / Numerical integration / Differentiation /
            Maximum / Minimum / Zero / Tangent
    View    View Table / View Memo
    Help    About Datalyse / www.datalyse.dk

Measurement runs in a worker thread so the UI stays responsive and the graph
redraws while data arrives, which is what "auto scale the on-screen graph while
the program is measuring" describes.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, analysis
from .config import DatalyseConfig, find_file
from .datafile import DataFile
from .drivers import registry
from .drivers.devices import DEVICE_PROFILES
from .engine import Measurement, resolve

APP_TITLE = "Datalyse (Python port)"


class DatalyseApp(tk.Tk):
    def __init__(self, ini_path: str | None = None) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1000x680")

        self.cfg: DatalyseConfig | None = None
        for cand in (ini_path, os.path.join(os.getcwd(), "Datalyse.ini")):
            if cand and os.path.isfile(cand):
                self.cfg = DatalyseConfig.load(cand)
                break
        if self.cfg is None:
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            hit = find_file(os.path.join(here, "original"), "Datalyse.ini")
            if hit:
                self.cfg = DatalyseConfig.load(hit)

        self.data: DataFile = DataFile()
        self.device_number: int | None = None
        self.measurement: Measurement | None = None
        self._stop_flag = threading.Event()
        self._events: queue.Queue = queue.Queue()

        self._build_menu()
        self._build_body()
        self._build_status()
        if self.cfg:
            self.status(f"Datalyse.ini: {self.cfg.source}  "
                        f"({len(self.cfg.enabled_devices())} devices ON)")
        else:
            self.status("datalyse.ini not found -- device list unavailable")

    # ------------------------------------------------------------------ menus
    def _build_menu(self) -> None:
        m = tk.Menu(self)

        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Open ...", accelerator="Ctrl+O", command=self.open_file)
        f.add_command(label="Save data", command=self.save_data)
        f.add_command(label="Save data as ...", command=self.save_data_as)
        f.add_separator()
        f.add_command(label="Export table as CSV ...", command=self.export_csv)
        f.add_separator()
        f.add_command(label="E&xit Datalyse", command=self.destroy)
        m.add_cascade(label="File", menu=f)

        e = tk.Menu(m, tearoff=0)
        e.add_command(label="Copy data", command=self.copy_data)
        e.add_separator()
        e.add_command(label="Delete graph", command=self.clear_data)
        m.add_cascade(label="Edit", menu=e)

        d = tk.Menu(m, tearoff=0)
        d.add_command(label="Choose Device ...", command=self.choose_device)
        d.add_command(label="Terminal ...", command=self.show_terminal_help)
        d.add_separator()
        sim = tk.Menu(d, tearoff=0)
        sim.add_command(label="Titration curves", command=self.sim_titration)
        sim.add_command(label="Data collection without devices",
                        command=self.sim_offline)
        sim.add_command(label="Half life", command=self.sim_halflife)
        sim.add_command(label="Poisson", command=self.sim_poisson)
        d.add_cascade(label="Simulation", menu=sim)
        m.add_cascade(label="Device", menu=d)

        dm = tk.Menu(m, tearoff=0)
        dm.add_command(label="Measure ( t,f(t) ) ...", command=self.start_measure)
        dm.add_command(label="Stop measuring", command=self.stop_measure)
        dm.add_separator()
        dm.add_command(label="View (t,f(t))", command=self.show_graph)
        dm.add_command(label="Multitable ...", command=self.show_table)
        m.add_cascade(label="Device Menu", menu=dm)

        t = tk.Menu(m, tearoff=0)
        t.add_command(label="Autoscale", command=self.auto_scale)
        t.add_separator()
        for key in sorted(analysis.MODELS):
            t.add_command(label=f"Fit: {analysis.MODELS[key].template}",
                          command=lambda k=key: self.fit(k))
        t.add_command(label="Linear regression", command=self.regress)
        t.add_command(label="Numerical integration ...", command=self.integrate)
        t.add_separator()
        t.add_command(label="Maximum", command=lambda: self.extrema("maximum"))
        t.add_command(label="Minimum", command=lambda: self.extrema("minimum"))
        t.add_command(label="Zero", command=lambda: self.extrema("zeros"))
        t.add_command(label="Half life", command=self.half_life)
        m.add_cascade(label="Tools", menu=t)

        v = tk.Menu(m, tearoff=0)
        v.add_command(label="View Table", command=self.show_table)
        v.add_command(label="View Graph", command=self.show_graph)
        m.add_cascade(label="View", menu=v)

        h = tk.Menu(m, tearoff=0)
        h.add_command(label="About Datalyse", command=self.about)
        h.add_command(label="www.datalyse.dk",
                      command=lambda: self.status("http://www.datalyse.dk"))
        m.add_cascade(label="Help", menu=h)

        self.config(menu=m)
        self.bind("<Control-o>", lambda _e: self.open_file())

    # ------------------------------------------------------------------- body
    def _build_body(self) -> None:
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self._make_graph_tab()
        self._make_table_tab()

    def _make_graph_tab(self) -> None:
        frame = ttk.Frame(self.nb)
        self.nb.add(frame, text="Graph")
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        self.fig = Figure(figsize=(8, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.grid(True, alpha=0.3)
        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _make_table_tab(self) -> None:
        frame = ttk.Frame(self.nb)
        self.nb.add(frame, text="Table")
        self.tree = ttk.Treeview(frame, show="headings")
        vs = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

    def _build_status(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        self.status_var = tk.StringVar(value="ready")
        ttk.Label(bar, textvariable=self.status_var, anchor="w").pack(
            fill="x", padx=6, pady=3)

    # ---------------------------------------------------------------- helpers
    def status(self, text: str) -> None:
        self.status_var.set(text)

    def require_device(self) -> bool:
        if self.device_number is None:
            messagebox.showinfo(APP_TITLE, "Choose a device first (Device menu).")
            return False
        return True

    # ------------------------------------------------------------------ device
    def choose_device(self) -> None:
        if not self.cfg:
            messagebox.showwarning(APP_TITLE, "datalyse.ini not found")
            return
        win = tk.Toplevel(self)
        win.title("Choose Device")
        win.transient(self)
        cols = ("num", "driver", "serial", "name")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=18)
        for c, w in zip(cols, (50, 110, 260, 420)):
            tree.heading(c, text=c)
            tree.column(c, width=w)
        for d in self.cfg.enabled_devices():
            p = DEVICE_PROFILES.get(d.number)
            drv = (p.driver if p else None) or "-"
            ser = p.serial.describe() if p and p.serial else "-"
            tree.insert("", "end", values=(d.number, drv, ser, d.description))
        tree.pack(fill="both", expand=True, padx=6, pady=6)

        def use(_e=None):
            sel = tree.selection()
            if not sel:
                return
            self.device_number = int(tree.item(sel[0], "values")[0])
            p = DEVICE_PROFILES.get(self.device_number)
            self.status(f"device {self.device_number}: "
                        f"{p.name if p else '?'}  driver="
                        f"{(p.driver if p else None) or '-'}  "
                        f"{p.serial.describe() if p and p.serial else ''}")
            win.destroy()

        tree.bind("<Double-1>", use)
        ttk.Button(win, text="Choose", command=use).pack(pady=(0, 6))
        tree.focus_set()

    # --------------------------------------------------------------- measuring
    def start_measure(self) -> None:
        if not self.require_device():
            return
        p = DEVICE_PROFILES.get(self.device_number)
        defaults = p.serial if p and p.serial else None
        win = tk.Toplevel(self)
        win.title("Measure (t,f(t))")
        win.transient(self)
        rows = [
            ("Serial port", tk.StringVar(value="/dev/ttyUSB0")),
            ("Interval (s)", tk.StringVar(value="1.0")),
            ("Duration (s, blank = until Stop)", tk.StringVar(value="")),
            ("Comment", tk.StringVar(value="")),
        ]
        for i, (label, var) in enumerate(rows):
            ttk.Label(win, text=label).grid(row=i, column=0, sticky="w", padx=6, pady=3)
            ttk.Entry(win, textvariable=var, width=34).grid(row=i, column=1, padx=6, pady=3)
        if defaults:
            ttk.Label(win, text=f"line settings: {defaults.describe()}").grid(
                row=len(rows), column=0, columnspan=2, sticky="w", padx=6)

        def go():
            port = rows[0][1].get().strip()
            try:
                interval = float(rows[1][1].get() or 1.0)
                dur = rows[2][1].get().strip()
                duration = float(dur) if dur else None
            except ValueError:
                messagebox.showerror(APP_TITLE, "interval/duration must be numbers")
                return
            comment = rows[3][1].get()
            win.destroy()
            self._run_measure(port, interval, duration, comment)

        ttk.Button(win, text="Start", command=go).grid(
            row=len(rows) + 1, column=1, sticky="e", padx=6, pady=8)

    def _run_measure(self, port: str, interval: float, duration, comment: str) -> None:
        binding = resolve(device_number=self.device_number)
        try:
            transport = binding.open(port)
        except Exception as exc:                      # noqa: BLE001 - surface anything
            messagebox.showerror(APP_TITLE, f"cannot open {port}:\n{exc}")
            return
        self.data = DataFile(comment=comment, device_names=[binding.name],
                             settings=[0, 0, 0, 0], x_label="t /s",
                             y_labels=list(binding.driver.channels))
        m = Measurement(binding, transport, interval=interval, comment=comment)

        def on_sample(t: float, vals: list[float]) -> None:
            self._events.put(("row", t, vals))

        m.on_sample = on_sample
        self.measurement = m
        self._stop_flag.clear()
        self.status(f"measuring {binding.name} on {port} ...")

        def worker():
            try:
                m.identify()
            except Exception as exc:                  # noqa: BLE001
                self._events.put(("error", str(exc)))
            m.run(duration=duration)
            try:
                transport.close()
            finally:
                self._events.put(("done",))

        threading.Thread(target=worker, daemon=True).start()
        self.after(120, self._drain)

    def stop_measure(self) -> None:
        if self.measurement:
            self.measurement.stop()
            self._stop_flag.set()
            self.status("stopping ...")

    def _drain(self) -> None:
        drained = 0
        while drained < 400:
            try:
                ev = self._events.get_nowait()
            except queue.Empty:
                break
            drained += 1
            if ev[0] == "row":
                self.data.add_row([ev[1]] + list(ev[2]))
            elif ev[0] == "error":
                self.status(f"device error: {ev[1]}")
            elif ev[0] == "done":
                self.status(f"stopped -- {len(self.data.rows)} readings")
                self.refresh_all()
                return
        if drained:
            self.refresh_graph()
        if self.measurement is not None:
            self.after(150, self._drain)

    # -------------------------------------------------------------------- view
    def refresh_all(self) -> None:
        self.refresh_graph()
        self.refresh_table()

    def refresh_graph(self) -> None:
        self.ax.clear()
        x = self.data.x_values()
        for i, label in enumerate(self.data.y_labels):
            y = self.data.y_values(i)
            pairs = [(a, b) for a, b in zip(x, y) if b is not None]
            if pairs:
                self.ax.plot([p[0] for p in pairs], [p[1] for p in pairs],
                             lw=1.0, marker="." if len(pairs) < 200 else None,
                             label=label)
        self.ax.set_xlabel(self.data.x_label)
        if self.data.y_labels:
            self.ax.set_ylabel(self.data.y_labels[0])
        self.ax.grid(True, alpha=0.3)
        if len(self.data.y_labels) > 1:
            self.ax.legend(fontsize=8)
        self.ax.set_title(self.data.comment or "Datalyse")
        self.canvas.draw_idle()

    def refresh_table(self) -> None:
        cols = [self.data.x_label] + list(self.data.y_labels)
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = cols
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=110)
        for row in self.data.rows:
            self.tree.insert("", "end", values=[
                f"{v:.7g}" if isinstance(v, float) else v for v in row])

    def show_graph(self) -> None:
        self.refresh_graph()
        self.nb.select(0)

    def show_table(self) -> None:
        self.refresh_table()
        self.nb.select(1)

    # -------------------------------------------------------------------- file
    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open", filetypes=[("Datalyse data", "*.DAT *.dat *.TXT *.txt"),
                                     ("All files", "*.*")])
        if not path:
            return
        try:
            self.data = DataFile.load(path)
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.refresh_all()
        self.status(f"{path}: {len(self.data.rows)} rows, "
                    f"{len(self.data.y_labels)} channel(s)")

    def _write(self, path: str) -> None:
        self.data.write(path)
        self.status(f"saved {path}")

    def save_data(self) -> None:
        if not self.data.rows:
            messagebox.showinfo(APP_TITLE, "no data to save")
            return
        self.save_data_as()

    def save_data_as(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".DAT",
                                            filetypes=[("Datalyse data", "*.DAT")])
        if path:
            self._write(path)

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(",".join([self.data.x_label] + self.data.y_labels) + "\n")
            for row in self.data.rows:
                fh.write(",".join("" if v is None else f"{v:.10g}" for v in row) + "\n")
        self.status(f"exported {path}")

    def copy_data(self) -> None:
        self.clipboard_clear()
        sep = "\t"
        lines = [sep.join([self.data.x_label] + self.data.y_labels)]
        for row in self.data.rows:
            lines.append(sep.join("" if v is None else f"{v:.10g}" for v in row))
        self.clipboard_append("\n".join(lines))
        self.status(f"{len(self.data.rows)} rows copied to the clipboard")

    def clear_data(self) -> None:
        self.data = DataFile()
        self.refresh_all()
        self.status("graph deleted")

    # ------------------------------------------------------------------- tools
    def auto_scale(self) -> None:
        y = [v for v in self.data.y_values(0) if v is not None]
        if not y:
            return
        lo, hi = analysis.autoscale(y)
        self.ax.set_ylim(lo, hi)
        self.canvas.draw_idle()
        self.status(f"autoscale: {lo:g} .. {hi:g}")

    def _result(self, title: str, text: str) -> None:
        messagebox.showinfo(title, text)
        self.status(text)

    def fit(self, key: str) -> None:
        try:
            r = analysis.fit_model(self.data.x_values(), self.data.y_values(0), key)
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self._result("Fit function",
                     f"f(t) = {r['template']}\n"
                     f"a1 = {r['params'][0]:.8g}\na2 = {r['params'][1]:.8g}\n"
                     f"R² = {r['r2']:.6f}")

    def regress(self) -> None:
        try:
            r = analysis.linear_regression(self.data.x_values(), self.data.y_values(0))
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self._result("Linear regression",
                     f"y = {r['slope']:.8g} * x + {r['intercept']:.8g}\n"
                     f"R² = {r['r2']:.6f}   (n = {r['n']})")

    def integrate(self) -> None:
        val = analysis.integrate(self.data.x_values(), self.data.y_values(0))
        self._result("Numerical integration", f"integral = {val:.8g}")

    def extrema(self, which: str) -> None:
        e = analysis.extrema(self.data.x_values(), self.data.y_values(0))
        if which == "maximum":
            self._result("Maximum", f"maximum at {e['maximum']}")
        elif which == "minimum":
            self._result("Minimum", f"minimum at {e['minimum']}")
        else:
            self._result("Zero", ", ".join(f"{z:.6g}" for z in e["zeros"]) or "none")

    def half_life(self) -> None:
        hl = analysis.half_life(self.data.x_values(), self.data.y_values(0))
        self._result("Half life", "no decay found" if hl is None else f"T½ = {hl:.6g}")

    # ------------------------------------------------------------- simulations
    def sim_offline(self) -> None:
        self.status("Data collection without devices: pick any device and press "
                    "Measure -- no hardware is required for the menus.")

    def sim_halflife(self) -> None:
        import random
        random.seed(137)
        x, y, v = [], [], 1000.0
        for i in range(0, 120, 5):
            x.append(float(i))
            y.append(v)
            v *= 0.5 ** (5 / 30.0)
        self.data = DataFile(comment="Half life simulation", device_names=["simulation"],
                             settings=[0, 1, 0, 0], x_label="t /s", y_labels=["A/Bq"])
        for a, b in zip(x, y):
            self.data.add_row([a, round(b)])
        self.refresh_all()
        self._result("Half life", f"T½ = {analysis.half_life(x, y):.6g} s")

    def sim_poisson(self) -> None:
        import random
        random.seed(137)
        counts = [sum(1 for _ in range(100) if random.random() < 0.05)
                  for _ in range(400)]
        p = analysis.poisson_expected(counts)
        lines = [f"mean = {p['mean']:.3f}   variance = {p['variance']:.3f}"]
        for k, o, e in list(zip(p["bins"], p["observed"], p["expected"]))[:12]:
            lines.append(f"{k:3d}  observed {o:5d}   expected {e:9.2f}")
        self._result("Poisson", "\n".join(lines))

    def sim_titration(self) -> None:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        acids = []
        for name in ("aciddata.ini", "basedata.ini"):
            hit = find_file(os.path.join(here, "original"), name)
            if hit:
                acids.extend(analysis.load_acids(hit))
        if not acids:
            messagebox.showinfo(APP_TITLE, "no acid data files found")
            return
        win = tk.Toplevel(self)
        win.title("Simulation of titration curves")
        win.transient(self)
        names = [a.name for a in acids]
        var = tk.StringVar(value=names[0])
        ttk.Label(win, text="Acid").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        cb = ttk.Combobox(win, textvariable=var, values=names, width=34)
        cb.grid(row=0, column=1, padx=6, pady=6)

        def plot():
            acid = next(a for a in acids if a.name == var.get())
            v, ph = analysis.titration_curve(acid)
            self.data = DataFile(comment=f"Titration of {acid.name}",
                                 device_names=["simulation"], settings=[0, 1, 0, 2],
                                 x_label="V /mL", y_labels=["pH"])
            for a, b in zip(v, ph):
                self.data.add_row([round(float(a), 3), round(float(b), 4)])
            self.refresh_all()
            self.nb.select(0)
            win.destroy()
            self.status(f"titration of {acid.name}: pKa "
                        f"{', '.join(f'{p:g}' for p in acid.pka)}")

        ttk.Button(win, text="Simulate", command=plot).grid(
            row=1, column=1, sticky="e", padx=6, pady=6)

    def show_terminal_help(self) -> None:
        self._result("Terminal",
                     "Use the CLI for the raw terminal:\n\n"
                     "    datalogger monitor /dev/ttyUSB0 --baud 9600")

    def about(self) -> None:
        self._result("About Datalyse",
                     f"Datalyse (Python port) {__version__}\n\n"
                     "Original: Datalyse 3.7, (c) Carl Hemmingsen, freeware,\n"
                     "Borland Delphi 3, last built 2012-07-15.\n"
                     "Protocols recovered from Datalyse.exe and datalyse.dk.")


def main(ini_path: str | None = None) -> int:
    app = DatalyseApp(ini_path)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
