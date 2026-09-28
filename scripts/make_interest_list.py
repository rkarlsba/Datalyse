#!/usr/bin/env python3
"""
Build the address list handed to the Ghidra export script.

Feeds in every literal found by delphi_strings.py and every entry of every
Delphi string table, so the decompiler is pointed at the functions that
actually implement the application logic rather than the whole linked VCL.
"""
import glob
import re
import struct
import sys

import pefile


def va_of(pe, off):
    ib = pe.OPTIONAL_HEADER.ImageBase
    for s in pe.sections:
        st, en = s.PointerToRawData, s.PointerToRawData + s.SizeOfRawData
        if st <= off < en:
            return ib + s.VirtualAddress + (off - st)
    return None


def main():
    pe = pefile.PE("original/Datalyse.exe", fast_load=True)
    pe.parse_data_directories()
    data = open("original/Datalyse.exe", "rb").read()
    addrs = set()

    # 1. literals recovered by the Pascal string scanner
    for line in open("decompiled/strings_pascal.txt"):
        m = re.match(r"^([0-9A-F]{8}) ", line)
        if m:
            addrs.add(int(m.group(1), 16))

    # 2. every string-table entry start
    SEP = struct.pack("<I", 0xFFFFFFFF)
    p = 0
    while p + 8 <= len(data):
        n = struct.unpack_from("<I", data, p)[0]
        if 0 < n <= 4096 and p + 4 + n <= len(data):
            body = data[p + 4:p + 4 + n]
            if body and not any(b == 0 or b == 0xFF for b in body):
                try:
                    text = body.decode("cp1252")
                except UnicodeDecodeError:
                    text = ""
                if text and all(0x20 <= ord(c) < 0x100 for c in text):
                    nxt = p + 4 + n + ((-(4 + n)) % 4)
                    if data[nxt:nxt + 4] == SEP:
                        v = va_of(pe, p)
                        if v:
                            addrs.add(v)
        p += 1

    out = sys.argv[1] if len(sys.argv) > 1 else "decompiled/interesting.txt"
    with open(out, "w") as fh:
        for a in sorted(addrs):
            fh.write(f"{a:08X}\n")
    print(f"{len(addrs)} addresses -> {out}")


if __name__ == "__main__":
    main()
