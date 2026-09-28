#!/usr/bin/env python3
"""
Decode the Delphi string-table blobs embedded in Datalyse.exe.

Layout, confirmed by inspection:
    u32 length | string bytes | pad to 4-byte boundary | 0xFFFFFFFF terminator

Entries are laid out contiguously, so the useful unit is the *maximal chain*
of consecutive entries: every entry terminator is also a legal entry start,
which makes naive forward parsing produce one overlapping "table" per entry.
This builds a linked structure of entry starts and reports only chain heads.
"""
import struct
import sys

import pefile

SEP = struct.pack("<I", 0xFFFFFFFF)


def va_of(pe, off):
    ib = pe.OPTIONAL_HEADER.ImageBase
    for s in pe.sections:
        st, en = s.PointerToRawData, s.PointerToRawData + s.SizeOfRawData
        if st <= off < en:
            return ib + s.VirtualAddress + (off - st)
    return None


def entry_at(data, p):
    """Return (text, next_offset) if a valid entry starts at p, else None."""
    if p + 8 > len(data):
        return None
    n = struct.unpack_from("<I", data, p)[0]
    if n == 0 or n > 4096 or p + 4 + n > len(data):
        return None
    body = data[p + 4:p + 4 + n]
    if any(b == 0 or b == 0xFF for b in body):
        return None
    try:
        text = body.decode("cp1252")
    except UnicodeDecodeError:
        return None
    if not all(0x20 <= ord(c) < 0x100 for c in text):
        return None
    nxt = p + 4 + n + ((-(4 + n)) % 4)
    if data[nxt:nxt + 4] != SEP:
        return None
    return text, nxt + 4


def main(exe):
    pe = pefile.PE(exe, fast_load=True)
    pe.parse_data_directories()
    data = open(exe, "rb").read()

    entries = {}          # start -> (text, next)
    for p in range(0, len(data) - 8):
        r = entry_at(data, p)
        if r:
            entries[p] = r

    has_pred = {nxt: p for p, (_t, nxt) in entries.items() if nxt in entries}
    heads = [p for p in entries if p not in has_pred]

    runs = []
    for h in sorted(heads):
        chain = []
        p = h
        while p in entries:
            text, nxt = entries[p]
            chain.append(text)
            p = nxt
        if len(chain) >= 2:
            runs.append((h, chain))
    runs.sort()
    return pe, runs


if __name__ == "__main__":
    exe = sys.argv[1]
    pe, runs = main(exe)
    total = sum(len(c) for _h, c in runs)
    print(f"# {len(runs)} maximal string tables, {total} entries total\n")
    for start, strs in runs:
        print(f"### table @ raw 0x{start:06X}  VA 0x{va_of(pe, start) or 0:08X}  ({len(strs)} entries)")
        for k, s in enumerate(strs):
            print(f"   [{k:3d}] {s!r}")
        print()
