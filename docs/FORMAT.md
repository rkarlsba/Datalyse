# The Datalyse data file format

Everything below was derived from the twelve sample files shipped inside
`datalyse.zip` and from the literals `Datalyse.exe` writes when saving
(`DATALYSE`, `DATATO`, `DATATOMAL`). Each rule is enforced by a test in
`tests/test_datafile.py`, and the whole format is pinned by
`test_round_trip_is_byte_exact`, which requires all twelve samples to survive a
read/write cycle unchanged.

## Encoding and line endings

* ANSI / cp1252, never UTF-16.
* Every line ends `CRLF` (`\r\n`).
* The separator is a single character, chosen by `SEPARATOR` in `Datalyse.ini`
  (default `#9` = TAB). The shipped samples use both TAB and comma, so
  `sniff_separator()` picks whichever appears in line 1.

## Single device — `DATALYSE`

```
DATALYSE<sep>Carl Hemmingsen<sep> A comment<sep>1
DMI multimeter<sep>0<sep>3<sep>0<sep>1
t /s<sep>t /°C
<space>0.25<sep><space>72.1
...
"f(t)=t
"a1=0
"a2=0
"a3=0
"a4=0
```

Line 1:

| field | meaning |
|---|---|
| 1 | magic, literally `DATALYSE` |
| 2 | author, always `Carl Hemmingsen` (older files `carl`) |
| 3 | free-text comment — **not stripped**, may begin with a space |
| 4 | number of graphs/series the file was saved with |

Line 2:

| field | meaning |
|---|---|
| 1 | device name, as written in `Datalyse.ini` |
| 2–5 | four configuration integers, meaning not established |

The four integers are kept verbatim. Observations from the samples:

| file | value | comment |
|---|---|---|
| `FIXING.DAT` | `0,3,0,1` | field 4 tracks the y-axis decimal places (72.1) |
| `CAPACI.DAT` | `0,1,0,2` | y written with 2 decimals |
| `Poisson.DAT` | `0,2,0,0` | integer counts |
| `BA137.DAT` | `0,1,0,0` | integer counts |
| `EM1LOG.TXT` | `0,0,0,2` | 7 y-channels |

Fields 1 and 3 are `0` in every sample. Nothing in the program depends on these
values when reading, so a port can treat them as opaque.

Line 3: the x-axis label followed by one label per channel.

Data lines: one value per column, in the same order.

## Several devices — `DATATO`

Written when more than one device is logged at once:

```
DATATO,carl
MI Multiinterface,DMI multimeter
time/s,U /mV,U / V
0.5,0.334,1.23
```

Line 1 is `DATATO` plus the author (no comment, no count). Line 2 is the list of
device names, one field per device. Line 3 onwards matches the single-device
form. `DATATOMAL` appears in the save routine's strings and is accepted on read.

## Value formatting

Three rules, all confirmed against the samples:

1. **Sign column.** A non-negative value is written with a leading space; a
   negative value is not. `UNDERCOO.DAT` genuinely contains `<space>31\t-0.1`,
   not `<space>31\t<space>-0.1` and not `<space>31\t -0.1`.
2. **Precision.** Up to seven significant digits — `0.0895996`, `4.85473`.
   That is what a Delphi `Single` prints, and several samples carry exactly that
   signature.
3. **Integers.** A value with no fractional part is written without a decimal
   point: ` 4`, not ` 4.0`.

`datalogger.datafile._fmt()` implements these; `_num()` handles the trailer's
parameters, which use `0` rather than ` 0`.

## Trailer block

A file may end with a block of quoted lines. Exactly four forms occur across the
twelve samples:

| form | meaning | seen in |
|---|---|---|
| `"Mean value 10.36` | mean of a channel | Poisson, REFRIGER, UNDERCOO |
| `"Dispersion 3.31` | variance/dispersion of a channel | as above |
| `"f(t)=t` | the active model function | FIXING, CAPACI, Poisson, … |
| `"aN=<number>` | that model's parameters, a1…a4 | as above |

Mean/dispersion pairs repeat when the file holds several channels
(`REFRIGER.DAT` has two pairs). The block is stored verbatim in
`DataFile.trailer` so re-writing stays byte-exact, and exposed through
`DataFile.model`, `DataFile.model_params` and `DataFile.stats`.

## Compatibility notes for a port

* Never hard-code TAB. Read `SEPARATOR` from the ini, or sniff.
* Never strip the comment.
* Never normalise `-0.1` to ` -0.1`.
* Keep seven significant digits; truncating to four silently corrupts
  `CAPACI.DAT` and `UNDERCOO.DAT`.
* Preserve the trailer. It holds the user's statistics and the last model fit,
  and the original rewrites them on every save.
