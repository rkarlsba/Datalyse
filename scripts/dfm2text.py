#!/usr/bin/env python3
"""
Delphi binary DFM (TPF0) -> text DFM converter.

Implements the stream produced by Delphi's TWriter/ObjectBinaryToText:
  'TPF0' signature, then a tree of objects:
     <class name: shortstring> <instance name: shortstring>
     <property>* terminated by an empty name (0x00)
     <child object>* terminated by a 0x00 byte
  Property values are tagged with TValueType:
     vaNull vaList vaInt8 vaInt16 vaInt32 vaExtended vaString vaIdent
     vaFalse vaTrue vaBinary vaSet vaLString vaNil vaCollection vaSingle
     vaCurrency vaDate vaWString vaInt64 vaUTF8String vaDouble
"""
import struct
import sys

SIG = b"TPF0"

(vaNull, vaList, vaInt8, vaInt16, vaInt32, vaExtended, vaString, vaIdent,
 vaFalse, vaTrue, vaBinary, vaSet, vaLString, vaNil, vaCollection, vaSingle,
 vaCurrency, vaDate, vaWString, vaInt64, vaUTF8String, vaDouble) = range(22)

VALUE_NAMES = {
    vaNull: "vaNull", vaList: "vaList", vaInt8: "vaInt8", vaInt16: "vaInt16",
    vaInt32: "vaInt32", vaExtended: "vaExtended", vaString: "vaString",
    vaIdent: "vaIdent", vaFalse: "vaFalse", vaTrue: "vaTrue",
    vaBinary: "vaBinary", vaSet: "vaSet", vaLString: "vaLString",
    vaNil: "vaNil", vaCollection: "vaCollection", vaSingle: "vaSingle",
    vaCurrency: "vaCurrency", vaDate: "vaDate", vaWString: "vaWString",
    vaInt64: "vaInt64", vaUTF8String: "vaUTF8String", vaDouble: "vaDouble",
}

ffInherited = 0xF0
ffChildPos = 0xF1


class DfmError(Exception):
    pass


def _unpack_extended(b):
    """Decode an 80-bit IEEE 754 extended (Delphi Real48/Extended)."""
    if len(b) != 10:
        raise DfmError("extended needs 10 bytes")
    mant = int.from_bytes(b[:8], "little")
    se = int.from_bytes(b[8:10], "little")
    sign = -1.0 if se & 0x8000 else 1.0
    exp = se & 0x7FFF
    if exp == 0 and mant == 0:
        return 0.0
    if exp == 0x7FFF:
        return sign * float("inf") if mant == 0x8000000000000000 else float("nan")
    # integer bit is explicit
    return sign * mant * 2.0 ** (exp - 16383 - 63)


class Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0
        self.inherited = False

    def eof(self):
        return self.p >= len(self.d)

    def byte(self):
        if self.p >= len(self.d):
            raise DfmError("unexpected end of stream")
        v = self.d[self.p]
        self.p += 1
        return v

    def peek(self):
        return self.d[self.p] if self.p < len(self.d) else None

    def take(self, n):
        if self.p + n > len(self.d):
            raise DfmError("unexpected end of stream")
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def i8(self):
        return struct.unpack("<b", self.take(1))[0]

    def i16(self):
        return struct.unpack("<h", self.take(2))[0]

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def shortstr(self):
        """Delphi 3+ ANSI shortstring: length byte + characters."""
        n = self.byte()
        return self.take(n).decode("cp1252", "replace")

    def longstr(self):
        n = self.i32()
        return self.take(n).decode("cp1252", "replace")


def escape(s):
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "'":
            out.append("\\'")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 32:
            out.append("#%d" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def q(s):
    return "'" + escape(s) + "'"


def read_value(r):
    """Return (text, kind) for one tagged property value."""
    t = r.byte()
    if t == vaNull:
        return "NULL", t
    if t == vaList:
        items = []
        while True:
            if r.peek() == 0:
                r.byte()
                break
            items.append(read_value(r)[0])
        return "(" + " ".join(items) + ")", t
    if t == vaInt8:
        return str(r.i8()), t
    if t == vaInt16:
        return str(r.i16()), t
    if t == vaInt32:
        return str(r.i32()), t
    if t == vaInt64:
        return str(struct.unpack("<q", r.take(8))[0]), t
    if t == vaExtended:
        return repr(_unpack_extended(r.take(10))), t
    if t == vaSingle:
        return repr(struct.unpack("<f", r.take(4))[0]), t
    if t == vaDouble:
        return repr(struct.unpack("<d", r.take(8))[0]), t
    if t == vaCurrency:
        return repr(struct.unpack("<q", r.take(8))[0] / 10000.0), t
    if t == vaDate:
        return repr(struct.unpack("<d", r.take(8))[0]), t
    if t in (vaString, vaLString):
        s = r.shortstr() if t == vaString else r.longstr()
        return q(s), t
    if t == vaUTF8String:
        n = r.i32()
        return q(r.take(n).decode("utf-8", "replace")), t
    if t == vaWString:
        n = r.i32()
        return q(r.take(n).decode("utf-16-le", "replace")), t
    if t == vaIdent:
        return r.shortstr(), t
    if t == vaFalse:
        return "False", t
    if t == vaTrue:
        return "True", t
    if t == vaBinary:
        n = r.i32()
        blob = r.take(n)
        hexs = " ".join(f"{b:02X}" for b in blob[:64])
        if n > 64:
            hexs += f" ... ({n} bytes)"
        return "{ " + hexs + " }", t
    if t == vaSet:
        items = []
        while True:
            if r.peek() == 0:
                r.byte()
                break
            items.append(r.shortstr())
        return "[" + ", ".join(items) + "]", t
    if t == vaNil:
        return "nil", t
    if t == vaCollection:
        items = []
        while True:
            if r.peek() == 0:
                r.byte()
                break
            items.append(read_object(r, is_collection=True))
        return "\n".join(items), t
    raise DfmError(f"unknown value type {t} at offset {r.p - 1}")


def read_object(r, is_collection=False):
    """Read one component/collection-item, return indented text lines."""
    if is_collection:
        cls = ""
    else:
        cls = r.shortstr()
    name = r.shortstr()
    lines = []
    header = (cls + " " + name).strip()
    # properties
    while True:
        prop = r.shortstr()
        if prop == "":
            break
        val, _ = read_value(r)
        lines.append(f"{prop} = {val}")
    body = "\n".join(lines)
    # children
    kids = []
    while True:
        if r.eof():
            break
        nb = r.peek()
        if nb == 0:
            r.byte()
            break
        kids.append(read_object(r))
    out = header
    if body:
        out += "\n" + body
    for k in kids:
        out += "\n" + indent(k)
    return out


def indent(text, pad="  "):
    return "\n".join(pad + ln if ln else ln for ln in text.split("\n"))


def convert(data):
    if not data.startswith(SIG):
        raise DfmError("not a TPF0 binary DFM")
    r = Reader(data)
    r.p = 4
    root = read_object(r)
    leftover = len(data) - r.p
    return root, leftover


if __name__ == "__main__":
    for path in sys.argv[1:]:
        blob = open(path, "rb").read()
        try:
            txt, left = convert(blob)
        except DfmError as exc:
            print(f"!! {path}: {exc}")
            continue
        flag = "OK " if left == 0 else f"LEFT={left}"
        print(f"--- {path} [{flag}]")
        print(txt)
