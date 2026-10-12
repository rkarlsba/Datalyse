# How Datalyse.exe was decompiled

Record of the reverse-engineering work behind the Python port: what the binary
turned out to be, which tools recovered what, and — importantly — the limits of
each method used.

## 1. The target

```
$ file original/Datalyse.exe
original/Datalyse.exe: PE32 executable for MS Windows 4.00 (GUI), Intel i386, 8 sections
```

| property | value |
|---|---|
| file size | 1 948 160 bytes |
| timestamp | 2012-07-15 07:36 |
| subsystem | 2 (GUI) |
| sections | `CODE DATA BSS .idata .tls .rdata .reloc .rsrc` |
| linker | Borland (Delphi `CODE`/`DATA`/`BSS` naming) |

Strings identify the toolchain precisely:

```
D:\Borland\Delphi 3\Datalyse\Datalyse.hlp
Portions Copyright (c) 1983,97 Borland
SOFTWARE\Borland\Delphi\RTL
```

So: **Borland Delphi 3**, a 32-bit VCL application. That matters because it
decides the whole approach — the GUI is declaratively stored as resources, and
string literals are *not* NUL-terminated, so `strings(1)` is the wrong tool.

## 2. Recovering the user interface (90 forms)

A Delphi GUI lives in the executable. Type 10 resources (`RT_RCDATA`) hold one
binary form definition per form: 92 entries, two of which are not forms
(`DVCLAL`, `PACKAGEINFO`).

Every form resource begins `54 50 46 30` — ASCII `TPF0`, the Delphi 3+ binary
DFM signature:

```
$ xxd the first bytes of TPCSkopMenuForm
00000000: 5450 4630 0f54 5043 536b 6f70 4d65 6e75  TPF0.TPCSkopMenu
00000010: 466f 726d 0e50 4353 6b6f 704d 656e 7546  Form.PCSkopMenuF
00000020: 6f72 6d04 4c65 6674 03a4 0203 546f 70     orm.Left....Top
```

`scripts/dfm2text.py` implements the stream format:

* names are Delphi **shortstrings**: a one-byte length then that many bytes;
* properties are `name, value` pairs terminated by an empty name;
* children follow, terminated by a `0x00` byte;
* values carry a `TValueType` tag — `vaInt8`, `vaInt16`, `vaInt32`,
  `vaExtended` (80-bit!), `vaString`, `vaBinary`, `vaSet`, `vaCollection` and
  so on, 22 variants in all.

**Validation.** A parser of a binary format is only trustworthy if it can prove
it consumed exactly the right bytes. The script reports the number of bytes left
after the root object:

```
parsed clean: 90   problems: 0
```

All 90 forms parse with **zero leftover bytes**. That result is what makes the
extracted structure (component names, captions, geometry, event-handler names,
menu items) trustworthy rather than plausible.

What that yielded: 90 forms in readable text (`decompiled/dfm/`), and **483
distinct event-handler names** — the method names of the original source, e.g.
`TitrerKurverClick`, `HalvtidButtonClick`, `Regres1ButtonClick`. Combined with
the menu captions this gives the feature set without needing the Pascal.

The largest form, `TDataForm`, is the main window and holds the whole menu tree
(`File`/`Edit`/`Device`/`Device Menu`/`Tools`/`View`/`Help` plus five popup
menus). `gui.py` in this repository mirrors those menu points.

## 3. Recovering string literals

Delphi 3 stores string constants as inline shortstrings in `CODE`. Running
`strings(1)` over the binary returns fragments: it cannot see length prefixes and
will happily merge adjacent literals.

`scripts/delphi_strings.py` instead walks the sections and accepts a position
only if the length byte is consistent **and** the byte after the string is not
printable (otherwise the candidate is in the middle of a longer run). That found
**4 956 literals**.

A second, more revealing format also exists. Some data is stored as a table of
`u32 length | bytes | pad to 4 | 0xFFFFFFFF` entries. A naive forward scan finds
one overlapping "table" per entry, because every terminator is also a legal
start; `scripts/delphi_strtable.py` builds a linked map of entry starts and
reports only *maximal chains*. Result: **548 tables, 2 317 entries**.

## 4. Recovering the code (Ghidra)

Ghidra 12.1.4 headless on the PE32 binary:

```console
$ ./ghidra_12.1.4_PUBLIC/support/analyzeHeadless ghidra_proj Datalyse \
      -import original/Datalyse.exe -analysisTimeoutPerFile 7200
```

`scripts/ghidra/ExportDecomp.java` then exports decompiled C. The binary has
**3 328 functions**, most of them statically linked VCL.

Decompiling all of them would bury the application logic in library code, so the
first pass selected only the functions that reference recovered string data:
`scripts/make_interest_list.py` emits the VA of every literal and every string
table entry (**7 685 addresses**), and the Ghidra script uses the reference
manager to find which functions touch them. **199 functions** referenced them.

## 5. Where the instrument protocols live

Those 199 functions are dominated by one enormous procedure at **`0x0047FB84`**
— 3 198 lines of exported C. Its string references start at VA `0x00485458` and
run through `0x00486F24`, and they are the driver dispatch table. Sample of the
recovered probe/answer pairs:

| command sent | expected answer | device |
|---|---|---|
| `*IDN?` | `FLUKE, 45` | Fluke 8845A |
| `v` | `dmi24`, `t1` | DMI24 multimeter |
| `V` | `PH1000`, `MC24E`, `EM1`, `MI` | IMPO handheld family |
| `ID` | (two spaces) | Fluke 867B |
| `=TY PHM210` | `?TY`, `=TY CDM210` | Radiometer pHM/CDM |
| `REV` | `GENESYS 20`, `SPEC 20 GENESYS` | Genesys spectrophotometers |
| `%RM400` | `RM400` | Elcanic RM400 counter |
| `*idn?` | `F.W.BELL,MODEL 5080` | Bell 5080 teslameter |
| `#vr` | `HAMEG HO89` | Hameg scopes |
| `id?` | `E91`, `E00` | Jenway 6405 |
| `:SYSTem:VERSion?` | `1991.0`, `Keithley Multimeter` | Keithley 2000 |
| `w` | 22-char weight frame | Bosch balances |

The same table also carries the program's own diagnostics, which tell us exactly
which instruments it *could not* identify — *"Metex has no version code, a
measurement will be made:"*, *"Oxygen Meter has no version code."*, *"MC24 2.3
has no version code!"*, *"A&D balances have no version code,"*. Those are
preserved verbatim in `datalogger/drivers/devices.py` so the port does not
pretend to more accuracy than the original had.

A second string table at VA `0x00479B10` holds the model fit templates that the
"Model function" dialog offers:

```
'a1*t+a2'   'a1*ln(t)+a2'   '*exp('   '*10^('
'a2*t^a1'   '*t^'           '0.5*a1*t^2+a2*t'   't^2'
```

and VA `0x00477974` holds the acid/base table separators (`*` marks the titrated
proton), which is how `Aciddata.ini` lines are interpreted.

## 6. The form methods the reference-driven pass misses

The selection in §4 has a blind spot: a form's own methods are reached from
*data*, not from code. Delphi emits for every class a length-prefixed table of
its published methods,

```
u16 entry size | u32 method address | u8 name length | name
```

whose names are exactly the DFM's `OnClick = ...` handler names. The table ends
where the class-name shortstring begins, which is what makes it findable:
`scripts/delphi_methods.py TTESlogForm` walks backwards from `'TTESlogForm'`
and prints

```
004EB1D8  LasStatusButtonClick   ("Read state")
004EAA14  LasSerieButtonClick    ("Read record")
004EB5BC  LasSingleLogClick      ("Read single values")
...
```

None of those 18 addresses was in the exported set. `scripts/ghidra/DecompileAt.java`
takes explicit addresses, defines a function where Ghidra has not and decompiles
only those.

## 7. Worked example: the TES 1380 (device 110) protocol

The vendor's page for the TES family (`tes.htm`, referenced by `appaemne.htm`)
documents the instrument's serial settings, its menu and its memory sizes — but
no bytes. The port therefore carried device 110 as `generic`, a text parser that
can never read a binary frame. The handlers say what it really is:

* `0x00551CB0` case `0x6e` — the measurement branch of the shared dispatcher:
  send a single space, read the answer, decode with
* `0x0050DD54` — the value decoder, and
* `0x0047FB84` case `0x6e` — the settings installed for this device before any
  of that runs: 9600/8/N/1, an **empty** command terminator (the shortstring at
  record offset 0 is written as `0x0000`), a 1 s read window (offset `0x34`) and
  `0x03` as the byte that ends a reply (offset `0xb`, compared against the last
  byte received in the reader at `0x00455EA0`).

So one command, one ETX-terminated binary frame. Datalyse never checks a start
byte and never counts the frame — it reads whatever arrives within the window
and hands the buffer to the decoder, which reads only these bytes:

| byte | meaning |
|---|---|
| 1, 2 | value digits, two per byte: `d1.d2d3d4` (this is where the 0.001 pH resolution survives) |
| 3, 4 | temperature digits, two per byte: `d1d2.d3d4` |
| 6 | bit 0 pH / mV, bit 2 °C / °F, bit 4 sign |
| 7 | bit 0 value sits one decade higher (+10), bit 4 logging in progress |

Bytes 0 and 5 are never read, and no code path fixes the frame length, so the
read is inherently timeout-driven. The decode is literal arithmetic from the
disassembly — `fild`/`fdiv` by 100, 10, 1000, `fadd` 10, `fmul` 100 — with two
consequences worth stating plainly: the value arrives as `X.XXX` in pH mode but
two decades low in mV mode (1999 mV is sent as 9.99 with the decade bit set), and
the `> 80 → −80` branch is dead for pH, kept here only because it is in the code.

The same table yields the control panel (`TTESlogForm`): `RP`, `RQ` and up to
four `RR` answer one byte each — `RR` must be exactly one byte long to count as an
answer, which is the only length check in the whole TES support — while `L` is the
log-button command for this device and `s` is what the settings dialog probes it
with. The record dump's display decoder (`0x004EA614`) reads digits one per byte
with a flag nibble, a *different* packing from the live frame.

The neighbouring TES devices are near-misses of the same work: 107/108/109 have
their own decoders at `0x0050D8C0`, `0x0050DA84` and `0x0050DD54` and their own
dispatcher cases, so they can be recovered the same way.

## 8. Serial settings from the vendor's own documentation

The help file that shipped with the program (`Datalyse.hlp`) is also published
as HTML at `datalyse.dk/datauk/`. Those 26 pages document, per instrument, the
line settings and often the exact exchange. Examples quoted verbatim in the
driver sources:

* Elma/TES 2730 — *"you send a space without CR, LF and the meter responds with
  5 bytes … 3,4. byte: digits, decimal point, sign (or error code)"*.
* Bosch balances — *"NNNBBBBDDDDDDDDBUUUU CR LF, a total of 22 character.
  Datalyse cuts the first 3 characters and removes all non-numeric characters
  and converts the remaining to a number."*
* Extech thermometer — *"you send a space without CR, LF and the meter responds
  with 7 bytes"*, RTS low.
* Consort — *"Datalyse uses the command "8" and Consort responds with: #, VALUE,
  UNIT, °C, CH, Hour, Date"*, with the compact form `nnnn 6.28 ph 21.2`.

`scripts/parse_help.py` turns those pages into structured data: 29 device
sections, 27 with complete serial settings, 24 with a version command.

## 9. Limits of this work

Stated plainly, because they bound what the port can claim:

* **Five drivers are exact.** The vendor documentation specifies the complete
  measurement exchange for the Elma/TES 2730, Extech, Bosch and Consort families;
  the TES 1380's comes from the decompiled handlers instead. Ten more have exact
  *identification* but a measurement query taken from the instrument's own manual
  rather than from Datalyse. The remaining ~100 devices have serial settings and
  identification strings only.
* **The TES 1380 frame is decoded, not confirmed on hardware.** The bytes were
  read out of the machine code and the arithmetic is transcribed exactly, but no
  capture from a real TES 1380 has been compared against it: the frame *length*,
  byte 0 and byte 5 are still unknown, and the `> 80 → −80` branch is dead for pH.
  `read_state()` therefore returns the control panel's raw answers rather than
  pretending to interpret them.
* **The Elma payload decode is inferred.** The help documents the 5-byte frame
  but not the bit layout of the two payload bytes, so `decode_payload()` is
  flagged as inferred, the raw frame is always exposed via `parse_frame()` for
  comparison against hardware, and the driver is marked accordingly.
* **The four integers on line 2 are not explained.** Field 4 correlates with the
  y-axis decimal count in the samples, but that is a correlation across twelve
  files, not a recovered rule. They are preserved verbatim.
* **No Pascal source was recovered.** Delphi 3 binaries retain no usable RTTI for
  method bodies — but they do keep the published-method tables (§6), which is how
  the TES 1380 handlers were reached. What the decompilation otherwise gives you
  is machine code and string constants, which is why this port is written against
  *observed behaviour*: the file format is pinned byte-for-byte, the protocols are
  quoted from primary sources or from the code they were recovered from, and where
  a fact is uncertain the code says so.

## Reproducing all of it

```console
$ scripts/reverse.sh          # download -> resources -> DFM -> strings -> Ghidra -> docs
$ .venv/bin/python -m pytest tests -q
```

Artifacts land in `decompiled/`:

```
decompiled/dfm/                90 forms as text
decompiled/resources/          136 raw resources
decompiled/strings_pascal.txt  4 956 literals
decompiled/string_tables.txt   548 tables / 2 317 entries
decompiled/interesting.txt     7 685 addresses handed to Ghidra
decompiled/ghidra/decomp/      199 app-logic functions in C
decompiled/ghidra_all/decomp/  every function in C
decompiled/ghidra/functions.txt  function inventory
decompiled/ghidra_at/decomp/    the form methods the export missed (TES 1380)
```
