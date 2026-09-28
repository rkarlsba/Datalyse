#!/usr/bin/env python3
"""
Turn the vendor's online device help (the HTML rendering of Datalyse.hlp) into
structured protocol data.

Each page is split on its <h3><a name="..."> anchors, which is how the original
help file is organised; every section then gets its baud/parity/stop/data
settings, its version/identification command and its prose notes lifted out.
The result feeds `datalogger/drivers/catalog.py`.
"""
from __future__ import annotations

import glob
import html
import json
import os
import re
import sys

BAUD_RE = re.compile(
    r"Baud rate\s+(\d+)\s*(?:\((\d+)\))?\s*,?\s*"
    r"(no|even|odd|mark|space)?\s*parity\s*,?\s*"
    r"(\d)\s*stop\s*(?:bit)?s?\s*,?\s*(\d)\s*data\s*bits?",
    re.I,
)
CMD_RE = re.compile(
    r"(?:Version\s+)?[Cc]ommand\s*(?:for version\s*)?[:\s]*[&quot;\"]*([^\"<>\n]{1,24})",
)
H3_RE = re.compile(r'<h3>(.*?)</h3>', re.I | re.S)
NAME_RE = re.compile(r'<a\s+name="([^"]+)"', re.I)

PARITY = {"no": "N", "even": "E", "odd": "O", "mark": "M", "space": "S"}


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", s).strip()


def decode(path: str) -> str:
    raw = open(path, "rb").read()
    for enc in ("cp1252", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1252", "replace")


def parse_page(path: str) -> list[dict]:
    text = decode(path)
    page = os.path.basename(path)
    heads = list(H3_RE.finditer(text))
    out = []
    for i, m in enumerate(heads):
        start = m.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[start:end]
        rawname = NAME_RE.search(m.group(1))
        title = strip_tags(m.group(1))
        if not title or title.lower().startswith(("functions and operating",
                                                  "menu structure")):
            continue

        plain = strip_tags(body)
        rec = {
            "page": page,
            "anchor": rawname.group(1) if rawname else "",
            "title": title,
        }
        bm = BAUD_RE.search(plain)
        if bm:
            rec["baud"] = int(bm.group(1))
            rec["baud_forced"] = int(bm.group(2)) if bm.group(2) else None
            rec["parity"] = PARITY.get((bm.group(3) or "no").lower(), "N")
            rec["stopbits"] = int(bm.group(4))
            rec["bytesize"] = int(bm.group(5))
        cm = CMD_RE.search(plain)
        if cm:
            cmd = cm.group(1).strip().strip('".; ')
            cmd = re.sub(r"\s+", " ", cmd)
            if cmd and len(cmd) <= 24:
                rec["version_command"] = cmd
        # first couple of sentences about how the device answers are useful
        rec["notes"] = plain[:1200]
        if rec.get("baud") or rec.get("version_command"):
            out.append(rec)
    return out


def main(srcdir: str, outpath: str) -> None:
    devices = []
    for path in sorted(glob.glob(os.path.join(srcdir, "*.htm"))):
        devices.extend(parse_page(path))
    with open(outpath, "w") as fh:
        json.dump(devices, fh, indent=1, ensure_ascii=False)
    with_params = [d for d in devices if d.get("baud")]
    with_cmd = [d for d in devices if d.get("version_command")]
    print(f"{len(devices)} device sections from {len(glob.glob(srcdir+'/*.htm'))} pages")
    print(f"  {len(with_params)} with full serial settings")
    print(f"  {len(with_cmd)} with a version/ID command")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
