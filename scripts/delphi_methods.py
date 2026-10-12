#!/usr/bin/env python3
"""
Recover a Delphi class's published-method table (name -> code address).

Datalyse's GUI logic lives in form methods that are referenced only from data:
each form class carries a length-prefixed table of its DFM-resolvable methods,

    u16 entry size | u32 method address | u8 name length | name

and the DFM event handler names (``OnClick = LasStatusButtonClick``) are exactly
the names in it.  ``ExportDecomp.java`` never decompiles these methods, because
nothing in *code* references them -- the only references come from this table.

Usage::

    scripts/delphi_methods.py TTESlogForm
    scripts/delphi_methods.py --near 004E8A20 --walk        # parse a raw block
    scripts/delphi_methods.py TSoundLMmenuform --follow      # resolve stubs

``--follow`` decodes the one-instruction forwarding stub Delphi emits for a
published method (``mov eax, [global]; mov eax, [eax]; call real``) and prints
the address of the real implementation.
"""
from __future__ import annotations

import argparse
import struct
import sys

import pefile

IMAGE = "original/Datalyse.exe"


class Binary:
    def __init__(self, path: str = IMAGE) -> None:
        self.pe = pefile.PE(path, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.data = open(path, "rb").read()
        self.sections = []
        for s in self.pe.sections:
            self.sections.append((s.Name.rstrip(b"\x00").decode(errors="replace"),
                                  self.base + s.VirtualAddress,
                                  s.PointerToRawData,
                                  s.SizeOfRawData))

    def offset(self, va: int) -> int | None:
        for _name, base, raw, size in self.sections:
            if base <= va < base + size:
                return raw + (va - base)
        return None

    def read(self, va: int, n: int) -> bytes:
        off = self.offset(va)
        if off is None:
            raise ValueError(f"0x{va:08X} is not in any section")
        return self.data[off:off + n]

    def u16(self, va: int) -> int:
        return struct.unpack("<H", self.read(va, 2))[0]

    def u32(self, va: int) -> int:
        return struct.unpack("<I", self.read(va, 4))[0]

    def find_shortstring(self, text: str) -> list[int]:
        """All VAs holding a Delphi shortstring with this exact value."""
        needle = bytes([len(text)]) + text.encode("latin-1")
        out = []
        start = 0
        while True:
            i = self.data.find(needle, start)
            if i < 0:
                return out
            start = i + 1
            for _n, base, raw, size in self.sections:
                if raw <= i < raw + size:
                    out.append(base + (i - raw))


def parse_entries(b: Binary, va: int, limit: int = 400):
    """Parse the length-prefixed method table starting at ``va``."""
    entries = []
    p = va
    for _ in range(limit):
        try:
            size = b.u16(p)
        except ValueError:
            break
        if size < 7 or size > 300:
            break
        addr = b.u32(p + 2)
        nlen = b.read(p + 6, 1)[0]
        if 2 + 4 + 1 + nlen != size:
            break
        raw = b.read(p + 7, nlen)
        if not all(0x20 <= c < 0x7F for c in raw):
            break
        entries.append((raw.decode("latin-1"), addr, p))
        p += size
    return entries, p


def table_for_class(b: Binary, class_name: str):
    """
    Find the method table that ends where a class's name shortstring begins.

    The table sits immediately before the name string, so walk backwards
    entry-by-entry (each entry is length-prefixed with its own size).
    """
    names = b.find_shortstring(class_name)
    if not names:
        raise SystemExit(f"no shortstring '{class_name}' found")
    for name_va in names:
        cur = name_va
        while True:
            found = None
            for size in range(7, 301):
                start = cur - size
                if start < 0:
                    break
                try:
                    if b.u16(start) != size:
                        continue
                except ValueError:
                    continue
                got, end = parse_entries(b, start, limit=1)
                if end == cur and got:
                    found = start
                    break
            if found is None:
                break
            cur = found
        entries, end = parse_entries(b, cur)
        if entries and end == name_va:
            return entries, name_va
    return [], None


def follow_stub(b: Binary, va: int) -> int | None:
    """
    Decode the published-method forwarding stub.

        mov eax, [global]      A1 imm32
        mov eax, [eax]         8B 00
        call target            E8 rel32
        ret                    C3

    Returns the call target, or None when the bytes are not that stub.
    """
    try:
        code = b.read(va, 16)
    except ValueError:
        return None
    i = 0
    if code[i:i + 2] == b"\x8b\xc0":          # alignment nop (mov eax, eax)
        i += 2
    if code[i] != 0xA1:
        return None
    i += 5 + 2                                 # A1 imm32 + mov eax,[eax]
    if code[i] != 0xE8:
        return None
    rel = struct.unpack("<i", code[i + 1:i + 5])[0]
    next_insn = va + i + 5
    if code[i + 5] != 0xC3:                    # ret
        return None
    return next_insn + rel


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("class_name", nargs="?", help="Delphi class name, e.g. TTESlogForm")
    ap.add_argument("--image", default=IMAGE)
    ap.add_argument("--follow", action="store_true",
                    help="resolve the forwarding stub to the real method")
    ap.add_argument("--at", help="parse a raw table at this VA instead of a class")
    ap.add_argument("--classes", help="comma-separated class names, all their tables")
    ap.add_argument("--addresses", action="store_true",
                    help="print only addresses (for scripts/ghidra/DecompileAt.java)")
    args = ap.parse_args()

    b = Binary(args.image)
    targets = []
    if args.at:
        targets.append((None, parse_entries(b, int(args.at, 16))[0], None))
    elif args.classes:
        for name in args.classes.split(","):
            name = name.strip()
            if not name:
                continue
            entries, class_va = table_for_class(b, name)
            targets.append((name, entries, class_va))
    elif args.class_name:
        entries, class_va = table_for_class(b, args.class_name)
        targets.append((args.class_name, entries, class_va))
    else:
        ap.error("give a class name, --classes or --at")

    if not any(entries for _n, entries, _v in targets):
        print("no method table found", file=sys.stderr)
        return 1

    if args.addresses:
        seen = set()
        for _name, entries, _va in targets:
            for _entry, addr, _at in entries:
                for candidate in ([addr, follow_stub(b, addr)] if args.follow else [addr]):
                    if candidate and candidate not in seen:
                        seen.add(candidate)
                        print(f"{candidate:08X}")
        return 0

    for name, entries, class_va in targets:
        if class_va:
            print(f"# {name} method table ends at 0x{class_va:08X}")
        for entry, addr, at in entries:
            line = f"{addr:08X}  {entry}  (entry @ {at:08X})"
            if args.follow:
                real = follow_stub(b, addr)
                line += f"  -> {real:08X}" if real else "  -> (not a stub)"
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
