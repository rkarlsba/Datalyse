#!/usr/bin/env python3
"""Extract Delphi DFM (form) resources + every other resource from a PE file."""
import os
import sys

import pefile

RT_NAMES = {
    1: "RT_CURSOR", 2: "RT_BITMAP", 3: "RT_ICON", 4: "RT_MENU",
    5: "RT_DIALOG", 6: "RT_STRING", 7: "RT_FONTDIR", 8: "RT_FONT",
    9: "RT_ACCELERATOR", 10: "RT_RCDATA", 11: "RT_MESSAGETABLE",
    12: "RT_GROUP_CURSOR", 14: "RT_GROUP_ICON", 16: "RT_VERSION",
    17: "RT_DLGINCLUDE", 19: "RT_PLUGPLAY", 20: "RT_VXD", 21: "RT_ANICURSOR",
    22: "RT_ANIICON", 23: "RT_HTML", 24: "RT_MANIFEST",
}


def main(exe_path, outdir):
    os.makedirs(outdir, exist_ok=True)
    pe = pefile.PE(exe_path, fast_load=True)
    pe.parse_data_directories()
    manifest = []
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.name is not None:
            tname = str(entry.name)
        elif entry.id in RT_NAMES:
            tname = RT_NAMES[entry.id]
        else:
            tname = f"TYPE_{entry.id}"
        for r in entry.directory.entries:
            rname = r.name.decode("utf-8", "replace") if r.name else str(r.id)
            for lang in r.directory.entries:
                d = lang.data.struct
                blob = pe.get_data(d.OffsetToData, d.Size)
                safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(rname))
                fn = os.path.join(outdir, f"{tname}__{safe}__{lang.id}.bin")
                with open(fn, "wb") as fh:
                    fh.write(blob)
                manifest.append((tname, str(rname), lang.id, d.Size, blob[:8].hex()))
    return manifest


if __name__ == "__main__":
    exe = sys.argv[1]
    dest = sys.argv[2]
    rows = main(exe, dest)
    print(f"extracted {len(rows)} resource entries -> {dest}")
    for t, n, lang, size, head in rows:
        if t == "RT_RCDATA":
            print(f"  {t:12s} {n:26s} lang={lang:5d} size={size:6d} head={head}")
