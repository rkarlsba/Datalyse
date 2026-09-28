# datalogger — a Python port of Datalyse

`Datalyse.exe` is a 32-bit Windows data-acquisition program for ~130 laboratory
instruments, written in Borland Delphi 3 by **Carl Hemmingsen**, published as
freeware at [datalyse.dk](https://datalyse.dk/datauk/index.htm) and last built
2012-07-15. It is no longer maintained, it only runs on Windows, and it talks to
instruments over COM1–COM8.

This is a Python re-implementation. It was produced by downloading the original,
decompiling it, and rebuilding its observable behaviour — the file format, the
configuration semantics, the per-instrument serial protocols and the analysis
tools — as a native Python program.

```console
$ datalogger devices                 # the device list from Datalyse.ini
$ datalogger info 3                  # the recovered protocol for device 3
$ datalogger measure /dev/ttyUSB0 --device 3 --interval 1 --out run.DAT
$ datalogger show run.DAT
$ datalogger analyze run.DAT --regress --integral --extrema
$ datalogger plot run.DAT --out graph.png
$ datalogger gui                     # the Tk front end
```

## Verified fidelity

The strongest claim in this repository is that **all twelve data files shipped
inside `datalyse.zip` round-trip byte-for-byte**:

| check | result |
|---|---|
| shipped `.DAT`/`.TXT` files parsed | 12 / 12 |
| re-written byte-identically | **12 / 12** (incl. TAB *and* comma files) |
| Delphi forms (DFM) decompiled | 90 / 90, zero bytes left unconsumed |
| `Datalyse.ini` devices recognised | 138 / 138 |
| test suite | 94 passing |

Byte-exact round-tripping pins every detail at once: cp1252 encoding, CRLF line
ends, the sniffed separator, the sign-column space rule, seven-significant-digit
values, the unstripped comment field and the quoted trailer block.

## How the port was built

Reproduce it end to end with `scripts/`:

1. **Download** — the site is a FrontPage frameset; the real link is
   `https://datalyse.dk/datauk/original/datalyse.zip`.
2. **Identify** — `Datalyse.exe` is `PE32 GUI i386`, Borland Delphi 3, 8 sections,
   1.9 MB, with 92 `RCDATA` entries.
3. **Decompile the UI** — 90 Delphi forms are stored as binary DFM. Every one
   starts with the `TPF0` signature; `scripts/dfm2text.py` parses the
   `TValueType`-tagged stream back into text and validates by consuming exactly
   to end-of-stream on all 90.
4. **Decompile the code** — Ghidra headless analysis, then
   `scripts/ghidra/ExportDecomp.java` exports C for every function.
5. **Recover the protocol data** — Delphi stores string literals as
   length-prefixed shortstrings (which `strings(1)` mangles), plus a
   `u32 len | bytes | 0xFFFFFFFF` string-table format. `scripts/delphi_strings.py`
   and `scripts/delphi_strtable.py` recover 4 956 literals and 548 tables.
6. **Collect vendor documentation** — the online help documents serial settings
   and response layouts per instrument; `scripts/parse_help.py` turns it into
   structured data.
7. **Write the Python** — `datalogger/`.

Full write-up: [`docs/REVERSE_ENGINEERING.md`](docs/REVERSE_ENGINEERING.md).

## Layout

```
datalogger/
├── config.py         Datalyse.ini parsing (SEPARATOR, COMPANYNUMBER, DEVICE, PATH)
├── datafile.py       the .DAT ASCII format, read + write
├── transport.py      serial layer: pyserial, plus pty and loopback back ends
├── drivers/
│   ├── base.py       Driver / SerialParams / registry
│   ├── catalog.py    per-instrument protocols
│   └── devices.py    all 138 devices from Datalyse.ini, with id commands
├── engine.py         the measurement loop behind "Measure (t,f(t))"
├── analysis.py       the Tools windows: fit, integral, tangent, regression,
│                     half life, Poisson, titration curves, Fourier, autoscale
├── cli.py            command line front end
└── gui.py            Tk front end mirroring the original menus
```

Supporting material:

```
original/              Datalyse.exe, DATALYSE.INI and the 12 sample data files
decompiled/dfm/        the 89 forms, converted to readable text
decompiled/ghidra*/    decompiled C for every function
decompiled/strings*    every recovered string literal and string table
site/help/             the vendor's per-instrument protocol documentation
docs/                  format spec, device table, reverse-engineering notes
scripts/               the tools that produced all of the above
tests/                 94 tests
```

## The data format

Documented in full in [`docs/FORMAT.md`](docs/FORMAT.md). The short version:

```
DATALYSE<sep>Carl Hemmingsen<sep> A comment<sep>1
DMI multimeter<sep>0<sep>3<sep>0<sep>1
t /s<sep>t /°C
<space>0.25<sep><space>72.1
"f(t)=t
"a1=0
```

Two things that are easy to get wrong and that the tests pin down: the leading
space occupies the *sign* column and is therefore absent on negative numbers
(` 31` but `-0.1`), and the comment field is not stripped — `TEMP.DAT` really
contains `, Cooling graph for boiling water` with a leading space.

## Instrument support — what is and is not faithful

Be careful here; this is the honest boundary of the port.

**Exact** (`source='doc'`) — the vendor help documents the exchange, so the
parser is a direct transcription:

| driver | devices | protocol |
|---|---|---|
| `elma2730` | 22, 25, 26, 75 | send one space, no CR/LF; 5-byte STX/area/data/ETX frame |
| `extech` | 88 | send one space, no CR/LF; 7-byte frame, RTS low |
| `bosch` | 9, 36 | `w`; 22-char `NNNBBBBDDDDDDDDBUUUU`; cut 3, strip non-numerics |
| `consort` | 20, 123 | `8`; `nnnn 6.28 ph 21.2` |

**Identification exact, measurement inferred** (`source='binary'`) — the
identify command and its expected answer were recovered from the dispatch
function's string table and are exact; the measurement query follows the
instrument's own manual, not the Datalyse help, and says so in `driver.notes`:

`fluke8845a`, `fluke867b`, `dmi24`, `dmi4`, `genesys`, `phm`, `shinko`, `hameg`,
`sf`, `impo_handheld`.

**Serial settings only** (`source='inferred'`) — 100+ further devices have their
baud/parity/stop/data and identification strings recorded, but no published
response layout. They fall back to `generic`, which reads one line and extracts
every number. Use `datalogger monitor` to capture real traffic and then write a
proper driver.

The dispatcher's own messages are preserved in the device table, so the port
tells you which instruments Datalyse itself could not identify — e.g. device 12
carries the original's *"Metex has no version code, a measurement will be made:"*
and device 31 *"Oxygen Meter has no version code."*.

Nothing here was reverse-engineered by guessing: every protocol claim is
attributed in `driver.source` and `driver.notes`, either to a vendor help page or
to a specific string-table address in `Datalyse.exe`.

## Instrument-free testing

The measurement path is fully exercised without hardware via `PtyTransport`,
which drives a **real pyserial handle over a pseudo-terminal** with an
auto-responder thread emulating an instrument — so request/response ordering,
the flush-before-command and the version check are all really tested.

```python
from datalogger.engine import Measurement, resolve
from datalogger.transport import PtyTransport

binding = resolve(driver_key="fluke8845a")
t = PtyTransport(baudrate=9600, stopbits=2).open().serve(
        {"*IDN?": "FLUKE, 45, 1.0\r\n", "VAL1?": "+1.2345E+00\r\n"})
m = Measurement(binding, t, interval=0.05)
m.identify()          # raises DeviceError if the wrong instrument is attached
m.run(rows=5)
```

## Install

```console
$ python3 -m venv .venv && . .venv/bin/activate
$ pip install -e ".[all]"          # or ".[serial]", ".[analysis]", ".[dev]"
$ datalogger devices
```

Or without installing, from the repository root: `python -m datalogger devices`.

`pyserial` is only needed to talk to real hardware; `numpy`/`matplotlib` only for
the analysis and plotting paths. The configuration and file layers are stdlib
only, so `pip install -e .` with no extras still gives you `devices`, `info`,
`show` and the `selftest` runner. The GUI needs `tkinter` from the system Python.
The reverse-engineering scripts additionally need `.[reverse]`.

The GUI runs on Linux, macOS and Windows from the same `gui.py`; the
platform-specific parts (modifier keys, serial port names, file dialog filters,
the macOS application menu) live in `datalogger/platform_support.py`. On macOS,
read **[docs/MACOS.md](docs/MACOS.md)** first — it covers which Python to use
(Apple's system Python ships a broken Tk 8.5), why you must use `/dev/cu.*`
rather than `/dev/tty.*`, and adapter driver notes.

## Licence

**This port is free software under the GNU Affero General Public License,
version 3 or later** — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

The original Datalyse is a **separate work**: 32-bit Windows freeware written in
Borland Delphi 3 by **Carl Hemmingsen**, published at
[datalyse.dk](https://datalyse.dk/), last built 2012-07-15 and no longer
maintained. Its own readme states only *"Datalyse is freeware"* — which is not a
free-software licence, and it is **not** covered by the AGPL above.

Datalyse itself is **not covered by the AGPL**. Its own files — the program, its
configuration and the sample data — are committed under
[`original/`](original/COPYRIGHT.md) as third-party material under the author's
terms. See [original/COPYRIGHT.md](original/COPYRIGHT.md) for the provenance of
every file and the pending request to relicense. AGPL §5 allows a covered work to
sit in an aggregate alongside separate independent works, so being in the same
repository does not put those files under the AGPL, and nothing here relicenses
them.

Still excluded, because they are derivatives of the original rather than the
original itself, and because `scripts/reverse.sh` regenerates them: the
decompiled output, and the mirrored vendor help pages.

Because Datalyse's authorship notices are embedded in the data files it writes,
this port reproduces them literally when saving — a file written by the original
round-trips byte-identically, author field and all. That is a claim about format
fidelity, not about authorship.
