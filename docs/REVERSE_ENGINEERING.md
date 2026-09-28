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

## 6. Serial settings from the vendor's own documentation

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

## 7. Limits of this work

Stated plainly, because they bound what the port can claim:

* **Only 4 drivers are exact.** The vendor documentation specifies the complete
  measurement exchange for the Elma/TES 2730, Extech, Bosch and Consort families.
  Ten more have exact *identification* but a measurement query taken from the
  instrument's own manual rather than from Datalyse. The remaining ~100 devices
  have serial settings and identification strings only.
* **The Elma payload decode is inferred.** The help documents the 5-byte frame
  but not the bit layout of the two payload bytes, so `decode_payload()` is
  flagged as inferred, the raw frame is always exposed via `parse_frame()` for
  comparison against hardware, and the driver is marked accordingly.
* **The four integers on line 2 are not explained.** Field 4 correlates with the
  y-axis decimal count in the samples, but that is a correlation across twelve
  files, not a recovered rule. They are preserved verbatim.
* **No Pascal source was recovered.** Delphi 3 binaries retain no usable RTTI for
  method bodies. What the decompilation gives you is machine code and string
  constants, which is why this port is written against *observed behaviour*: the
  file format is pinned byte-for-byte, the protocols are quoted from primary
  sources, and where a fact is uncertain the code says so.

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
```
