# Copyright and provenance — `original/`

**These files are not part of the Python port and are NOT covered by the GNU
Affero General Public License that governs the rest of this repository.**

They are the work of a third party, included here as third-party material under
the terms set by their author. AGPL §5 permits a covered work to sit in an
"aggregate" alongside separate independent works, which is what this directory
is; being in the same repository does not place them under the AGPL, and nothing
here should be read as relicensing them.

## Copyright

**Copyright © Carl Hemmingsen. All rights reserved.**

The author's own words, verbatim from `README.TXT` in this directory — this is
the entire licence statement that accompanies the original distribution:

```
Datalyse for Windows

Licence:
Datalyse is freeware
```

"Freeware" describes how the program is distributed; it is not a free-software
licence and grants no explicit right to modify, redistribute, or relicense.
None of the `.ini` or `.DAT` files carry a notice of their own.

## Provenance

Every file here was downloaded from the author's own public distribution:

```
https://datalyse.dk/datauk/original/datalyse.zip
```

Nothing was obtained from a third-party mirror, and no file has been modified.

## Contents

| File | What it is |
|---|---|
| `Datalyse.exe` | the original 32-bit Windows program (Borland Delphi 3, PE32, last built 2012-07-15) |
| `README.TXT` | the author's readme, containing the licence statement quoted above |
| `DATALYSE.INI` | main configuration: device list, separator, company number, path |
| `aciddata.ini` | acid titration data (called `Syredata.ini` in the readme) |
| `basedata.ini` | base titration data |
| `vernier.ini` | Vernier probe data |
| `multilog.ini` | MultiLog device data |
| `Diva.ini` | DiVA spectrometer calibration |
| `OOOHH.WAV` | an alert sound |
| 12 × `.DAT` / `.TXT` | sample data files: `BA137`, `CAPACI`, `DRINK`, `EM1LOG`, `FIXING`, `Poisson`, `REFRIGER`, `TEMP`, `TITRAT`, `TRANSIST`, `UNDERCOO`, `USE_EFF` |

## Why they are here

1. **Verification.** The twelve sample data files are the ground truth for the
   `.DAT` format. The strongest test in this repository reads each one and
   writes it back, asserting the result is byte-identical. Datalyse's format is
   idiosyncratic enough — a space in the sign column, seven significant digits,
   an unstripped comment field, a quoted trailer block — that no amount of
   reading the code would have pinned it. Without these files those tests skip.
2. **Reference.** `DATALYSE.INI` is the authoritative device list the port
   follows, and the vendor `.ini` files document the calibration data formats.

This repository is **private**. These files are here so the project can be
verified and audited, not to redistribute the program.

## Pending permission

The maintainers of this port are seeking Carl Hemmingsen's permission to
relicense this material, with the intention of moving it to the AGPL once — and
only once — that permission is granted in writing.

Until that happens, treat everything in this directory as the author's
copyrighted work under the terms above. Do not copy it out of this repository,
and do not assume the AGPL applies to it.

**Takedown.** If you are the copyright holder and would prefer these files not
be here, please open an issue and they will be removed promptly, as will the
original binary in particular.

## Related

* `../NOTICE` — the licence position for the port itself
* `../LICENSE` — the AGPL, which covers the port and not this directory
* `../scripts/reverse.sh` — re-downloads this directory from the publisher, so
  it is reproducible for anyone who does not have it
