"""
Command line front-end.

Mirrors the original's menu points as subcommands:

    devices                     Device -> Choose Device ...
    info N                      the device's own help page in text form
    monitor PORT                Terminal ...
    measure PORT ...            Device Menu -> Measure (t,f(t)) ...
    show FILE                   File -> Open ...
    analyze FILE                Tools -> Fit / Integral / Regress / ...
    titration                   Device -> Simulation -> Titration curves
    poisson / halflife          Device -> Simulation -> Half life / Poisson
    selftest                    exercises every driver without hardware
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from . import __version__
from .analysis import (MODELS, extrema, fit_model, half_life, integrate,
                       linear_regression, load_acids, parse_acid_line,
                       poisson_expected, titration_curve)
from .config import COMPANIES, MISSING_INI_HELP, DatalyseConfig
from .datafile import DataFile
from .drivers import registry
from .drivers.base import find_for
from .drivers.devices import DEVICE_PROFILES
from .engine import resolve
from .transport import SerialTransport

DEFAULT_INI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_config(args) -> DatalyseConfig | None:
    from .config import find_file
    explicit = getattr(args, "ini", None)
    if explicit:
        return DatalyseConfig.load(explicit) if os.path.isfile(explicit) else None
    for d in (os.path.join(DEFAULT_INI_DIR, "original"), DEFAULT_INI_DIR,
              os.getcwd()):
        hit = find_file(d, "Datalyse.ini")
        if hit:
            return DatalyseConfig.load(hit)
    return None


def _ini_dir() -> str | None:
    from .config import find_file
    for d in (os.path.join(DEFAULT_INI_DIR, "original"), DEFAULT_INI_DIR):
        hit = find_file(d, "Datalyse.ini")
        if hit:
            return os.path.dirname(hit)
    return None


# --------------------------------------------------------------------- devices
def cmd_devices(args) -> int:
    cfg = _load_config(args)
    if cfg is None:
        print("datalyse.ini not found", file=sys.stderr)
        print(file=sys.stderr)
        print(MISSING_INI_HELP, file=sys.stderr)
        return 2
    print(cfg.describe())
    print()
    print(f"{'#':>4}  {'driver':<10} {'serial':<32} name")
    print("-" * 100)
    shown = 0
    for d in cfg.filtered_devices() if args.filtered else cfg.devices.values():
        if not d.enabled and not args.all:
            continue
        prof = DEVICE_PROFILES.get(d.number)
        drv = (prof.driver if prof else None) or "-"
        ser = prof.serial.describe() if prof and prof.serial else "-"
        print(f"{d.number:>4}  {drv:<10} {ser:<32} {d.description}")
        shown += 1
    print(f"\n{shown} devices")
    return 0


def cmd_info(args) -> int:
    prof = DEVICE_PROFILES.get(args.number)
    if prof is None:
        print(f"no profile for device {args.number}", file=sys.stderr)
        return 1
    print(f"device {args.number}: {prof.name}")
    print(f"  driver          : {prof.driver or '(none)'}")
    print(f"  serial          : {prof.serial.describe() if prof.serial else 'n/a'}")
    print(f"  id command      : {prof.id_command!r}")
    print(f"  id expects      : {prof.id_expect or '(no version code)'}")
    print(f"  measure command : {prof.measure_command!r}")
    print(f"  channels        : {', '.join(prof.channels)}")
    print(f"  documented in   : {prof.docs}")
    if prof.note:
        print(f"  notes           : {prof.note}")
    if prof.driver and prof.driver in registry():
        d = registry()[prof.driver]
        print(f"  driver source   : {d.source}")
        if d.notes:
            print(f"  driver notes    : {d.notes}")
    return 0


def cmd_drivers(args) -> int:
    for key, d in sorted(registry().items()):
        print(f"{key:<12} {d.source:<9} {d.serial.describe():<34} {d.label}")
    return 0


def cmd_ports(args) -> int:
    try:
        from serial.tools import list_ports
    except ImportError:
        print("pyserial not installed", file=sys.stderr)
        return 2
    found = list(list_ports.comports())
    if not found:
        print("no serial ports found")
    for p in found:
        print(f"{p.device:<20} {p.description}  [{p.hwid}]")
    return 0


# --------------------------------------------------------------------- monitor
def cmd_monitor(args) -> int:
    """Raw terminal: show every byte in both directions, like Device->Terminal."""
    t = SerialTransport(port=args.port, baudrate=args.baud,
                        bytesize=args.bits, parity=args.parity, stopbits=args.stop,
                        timeout=0.2)
    t.open()
    print(f"# {args.port} at {args.baud} {args.bits}{args.parity}{args.stop:g} "
          f"-- Ctrl-C to stop", file=sys.stderr)
    if args.send:
        for cmd in args.send:
            payload = (cmd.replace("\\r", "\r").replace("\\n", "\n")
                          .replace("\\t", "\t")).encode("cp1252")
            t.write(payload)
            print(f">>> {payload!r}")
    deadline = None if args.seconds is None else time.monotonic() + args.seconds
    try:
        while True:
            if deadline and time.monotonic() > deadline:
                break
            data = t.read_bytes(256, 0.3)
            if data:
                sys.stdout.write(data.decode("cp1252", "replace"))
                sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        t.close()
    return 0


# --------------------------------------------------------------------- measure
def cmd_measure(args) -> int:
    binding = resolve(device_number=args.device, driver_key=args.driver)
    print(f"device  : {binding.name} (driver {binding.driver.key})")
    print(f"serial  : {binding.serial.describe()}")
    if args.identify:
        t = binding.open(args.port)
        try:
            ident = binding.driver.identify(t)
            print(f"identity: {ident!r}")
            if not binding.driver.version_ok(ident):
                print(f"warning : expected one of {binding.driver.version_expect}",
                      file=sys.stderr)
        finally:
            t.close()
        if args.identify_only:
            return 0
    t = binding.open(args.port)
    from .engine import Measurement
    m = Measurement(binding, t, interval=args.interval, comment=args.comment or "")
    n = 0

    def show(t_s: float, vals: list[float]) -> None:
        nonlocal n
        n += 1
        body = "  ".join(f"{v:12.5g}" for v in vals)
        print(f"{t_s:9.3f}  {body}")

    m.on_sample = show
    try:
        m.run(duration=args.duration, rows=args.rows)
    except KeyboardInterrupt:
        print("\n# stopped")
    finally:
        t.close()
    if args.out:
        # the original always writes the device's own name into the header
        m.data.settings = ([0, 0, 0, 0] if len(m.data.y_labels) > 1 else [0, 1, 0, 1])
        m.save(args.out)
        print(f"# {n} readings -> {args.out}")
    return 0


# ------------------------------------------------------------------------ show
def cmd_show(args) -> int:
    df = DataFile.load(args.file)
    print(f"magic    : {df.magic}")
    print(f"author   : {df.author}")
    print(f"comment  : {df.comment}")
    print(f"separator: {df.separator!r}")
    print(f"devices  : {', '.join(df.device_names)}")
    print(f"settings : {df.settings}")
    print(f"columns  : {df.x_label} | {' | '.join(df.y_labels)}")
    print(f"rows     : {len(df.rows)}")
    if args.head:
        print()
        print(f"{df.x_label:>12}  " + "  ".join(f"{l:>12}" for l in df.y_labels))
        for row in df.rows[:args.head]:
            print(f"{row[0]:>12.7g}  " + "  ".join(
                f"{v:>12.7g}" if v is not None else f"{'-':>12}" for v in row[1:]))
    return 0


# --------------------------------------------------------------------- analyze
def cmd_analyze(args) -> int:
    df = DataFile.load(args.file)
    x = df.x_values()
    y = df.y_values(args.channel)
    y = [v for v in y if v is not None]
    if args.fit:
        print(f"model fit   : {fit_model(x, y, args.fit)}")
    if args.regress:
        print(f"regression  : {linear_regression(x, y)}")
    if args.integral:
        print(f"integral    : {integrate(x, y, args.from_x, args.to_x):.8g}")
    if args.slope:
        from .analysis import tangent
        s, i = tangent(x, y, args.at)
        print(f"tangent     : slope={s:.8g} intercept={i:.8g} at x={args.at}")
    if args.extrema:
        e = extrema(x, y)
        print(f"maximum     : {e['maximum']}")
        print(f"minimum     : {e['minimum']}")
        print(f"zeros       : {', '.join(f'{z:.6g}' for z in e['zeros']) or '(none)'}")
    if args.halflife:
        hl = half_life(x, y)
        print(f"half life   : {hl if hl is None else f'{hl:.6g}'}")
    if args.poisson:
        p = poisson_expected(y)
        print(f"poisson     : mean={p.get('mean'):.4g} var={p.get('variance'):.4g} n={p.get('n')}")
    return 0


def cmd_plot(args) -> int:
    import matplotlib
    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    df = DataFile.load(args.file)
    x = df.x_values()
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, label in enumerate(df.y_labels):
        y = df.y_values(i)
        ax.plot(x, [v for v in y], marker="." if len(x) < 200 else None,
                lw=1.0, label=label)
    ax.set_xlabel(df.x_label)
    ax.set_ylabel(df.y_labels[0] if df.y_labels else "")
    ax.grid(True, alpha=0.3)
    if len(df.y_labels) > 1:
        ax.legend()
    ax.set_title(df.comment or args.file)
    fig.tight_layout()
    if args.out:
        fig.savefig(args.out, dpi=120)
        print(f"wrote {args.out}")
    if args.show:
        plt.show()
    return 0


# ------------------------------------------------------------------ simulations
def cmd_titration(args) -> int:
    from .config import find_file
    acids = []
    ini_dir = _ini_dir()
    for name in ("aciddata.ini", "basedata.ini"):
        p = find_file(ini_dir, name) if ini_dir else None
        if p:
            acids.extend(load_acids(p))
    if args.list:
        for a in acids:
            mark = "*" if a.marked is not None else " "
            print(f"{mark} {a.name:<28} pKa={', '.join(f'{p:g}' for p in a.pka)}")
        return 0
    match = [a for a in acids if a.name.lower() == (args.acid or "").lower()]
    if not match:
        match = [a for a in acids if args.acid and args.acid.lower() in a.name.lower()]
    if not match:
        print(f"no acid matching {args.acid!r}; use --list", file=sys.stderr)
        return 1
    acid = match[0]
    v, ph = titration_curve(acid, args.conc, args.conc_base, args.volume)
    print(f"# {acid.name}  pKa={[f'{p:g}' for p in acid.pka]}  "
          f"c={args.conc} M, V0={args.volume} mL, titrant={args.conc_base} M")
    for vi, pi in zip(v, ph):
        print(f"{vi:8.3f}  {pi:7.4f}")
    return 0


def cmd_poisson(args) -> int:
    import random
    random.seed(args.seed)
    counts = [sum(1 for _ in range(args.n) if random.random() < 0.05)
              for _ in range(args.samples)]
    p = poisson_expected(counts)
    print(f"# {args.samples} samples, mean {p['mean']:.3f}")
    for k, o, e in zip(p["bins"], p["observed"], p["expected"]):
        print(f"{k:4d}  observed={o:6d}  expected={e:9.2f}")
    return 0


def cmd_selftest(args) -> int:
    """Exercise the whole stack with no hardware: pty-backed drivers + files."""
    import subprocess
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return subprocess.call([sys.executable, "-m", "pytest", "-q",
                            os.path.join(here, "tests")])


# ------------------------------------------------------------------------ main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="datalogger",
        description="Python re-implementation of Datalyse (datalogger.exe), "
                    "the serial-port data logger from datalyse.dk.")
    p.add_argument("--version", action="version", version=f"datalogger {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("devices", help="list the devices from Datalyse.ini")
    d.add_argument("--ini")
    d.add_argument("--all", action="store_true", help="include devices switched OFF")
    d.add_argument("--filtered", action="store_true",
                   help="apply COMPANYNUMBER filtering")
    d.set_defaults(func=cmd_devices)

    i = sub.add_parser("info", help="show a device's recovered protocol")
    i.add_argument("number", type=int)
    i.set_defaults(func=cmd_info)

    r = sub.add_parser("drivers", help="list implemented drivers")
    r.set_defaults(func=cmd_drivers)

    q = sub.add_parser("ports", help="list serial ports")
    q.set_defaults(func=cmd_ports)

    m = sub.add_parser("monitor", help="raw terminal on a port")
    m.add_argument("port")
    m.add_argument("--baud", type=int, default=9600)
    m.add_argument("--bits", type=int, default=8)
    m.add_argument("--parity", default="N")
    m.add_argument("--stop", type=float, default=1)
    m.add_argument("--send", action="append",
                   help="send this command first (\\\\r expands to CR)")
    m.add_argument("--seconds", type=float, default=10)
    m.set_defaults(func=cmd_monitor)

    a = sub.add_parser("measure", help="log a device to a .DAT file")
    a.add_argument("port")
    a.add_argument("--device", type=int, help="device number from Datalyse.ini")
    a.add_argument("--driver", help="force a driver key")
    a.add_argument("--interval", type=float, default=1.0)
    a.add_argument("--duration", type=float)
    a.add_argument("--rows", type=int)
    a.add_argument("--comment", default="")
    a.add_argument("--out")
    a.add_argument("--identify", action="store_true")
    a.add_argument("--identify-only", action="store_true")
    a.set_defaults(func=cmd_measure)

    s = sub.add_parser("show", help="print a data file")
    s.add_argument("file")
    s.add_argument("--head", type=int, default=10)
    s.set_defaults(func=cmd_show)

    n = sub.add_parser("analyze", help="run the Tools menu on a data file")
    n.add_argument("file")
    n.add_argument("--channel", type=int, default=0)
    n.add_argument("--fit", choices=sorted(MODELS))
    n.add_argument("--regress", action="store_true")
    n.add_argument("--integral", action="store_true")
    n.add_argument("--from", dest="from_x", type=float)
    n.add_argument("--to", dest="to_x", type=float)
    n.add_argument("--slope", action="store_true")
    n.add_argument("--at", type=float, default=0.0)
    n.add_argument("--extrema", action="store_true")
    n.add_argument("--halflife", action="store_true")
    n.add_argument("--poisson", action="store_true")
    n.set_defaults(func=cmd_analyze)

    pl = sub.add_parser("plot", help="plot a data file")
    pl.add_argument("file")
    pl.add_argument("--out")
    pl.add_argument("--show", action="store_true")
    pl.set_defaults(func=cmd_plot)

    ti = sub.add_parser("titration", help="simulate a titration curve")
    ti.add_argument("--acid")
    ti.add_argument("--list", action="store_true")
    ti.add_argument("--conc", type=float, default=0.1)
    ti.add_argument("--conc-base", type=float, default=0.1)
    ti.add_argument("--volume", type=float, default=25.0)
    ti.set_defaults(func=cmd_titration)

    po = sub.add_parser("poisson", help="Poisson simulation")
    po.add_argument("--n", type=int, default=100)
    po.add_argument("--samples", type=int, default=200)
    po.add_argument("--seed", type=int, default=137)
    po.set_defaults(func=cmd_poisson)

    st = sub.add_parser("selftest", help="run the test suite")
    st.set_defaults(func=cmd_selftest)

    g = sub.add_parser("gui", help="start the Tk front end")
    g.add_argument("--ini")
    g.add_argument("--data", help="a .DAT file to open at start-up")
    g.set_defaults(func=cmd_gui)
    return p


def cmd_gui(args) -> int:
    try:
        from .gui import main as gui_main
    except ImportError as exc:
        print(f"Tk is not available: {exc}", file=sys.stderr)
        return 2
    if args.data:
        os.environ["DATALOGGER_OPEN"] = os.path.abspath(args.data)
    return gui_main(getattr(args, "ini", None))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
