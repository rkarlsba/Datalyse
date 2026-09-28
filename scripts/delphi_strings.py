#!/usr/bin/env python3
"""
Delphi Pascal string-literal recovery.

Old Delphi (D3-D7) stores string constants inside the code/data sections as
ANSI shortstrings: a one-byte length followed by that many characters, with no
terminating NUL. `strings(1)` therefore both misses short literals and merges
adjacent ones. This scanner walks the sections and validates the length prefix,
which is how you recover protocol commands, format strings and messages.
"""
import sys
from collections import Counter

import pefile

PRINTABLE = set(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}
# cp1252 extras seen in this program (Danish text, degree signs, unit symbols)
HIGH = {0x80, 0x91, 0x92, 0x93, 0x94, 0xA0, 0xB0, 0xB1, 0xB5, 0xE4, 0xF6,
        0xFC, 0xC4, 0xD6, 0xDC, 0xE6, 0xF8, 0xE5, 0xC6, 0xD8, 0xC5, 0xDF}


def scan(data, base, minlen=3):
    """Yield (offset, text) for every plausible Pascal shortstring."""
    out = []
    n = len(data)
    for i in range(n):
        L = data[i]
        if L < minlen or i + 1 + L > n:
            continue
        chunk = data[i + 1:i + 1 + L]
        if all(c in PRINTABLE or c in HIGH for c in chunk):
            # reject if the byte after the string is also printable (=> we are
            # in the middle of a longer run, so this length byte was spurious)
            nxt = data[i + 1 + L] if i + 1 + L < n else 0
            if nxt in PRINTABLE:
                continue
            out.append((base + i, chunk.decode("cp1252", "replace")))
    return out


def main(exe, minlen=3):
    pe = pefile.PE(exe, fast_load=True)
    pe.parse_data_directories()
    results = []
    for s in pe.sections:
        name = s.Name.decode(errors="replace").rstrip("\x00")
        if name not in (".text", "CODE", ".data", "DATA"):
            continue
        data = s.get_data()
        base = pe.OPTIONAL_HEADER.ImageBase + s.VirtualAddress
        for off, txt in scan(data, base, minlen):
            results.append((off, name, txt))
    return results


if __name__ == "__main__":
    exe = sys.argv[1]
    minlen = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    rows = main(exe, minlen)
    for off, sec, txt in rows:
        print(f"{off:08X} {sec:6s} {txt!r}")
    print(f"# {len(rows)} literals", file=sys.stderr)
