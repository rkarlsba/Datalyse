#!/usr/bin/env python3
"""Locate child-object framing in a binary DFM by finding known VCL class names."""
import sys

path = sys.argv[1]
data = open(path, "rb").read()
needles = [b"TButton", b"TLabel", b"TEdit", b"TPanel", b"TGroupBox", b"TMainMenu",
           b"TTimer", b"TComboBox", b"TStringGrid", b"TImage", b"TPageControl"]
for n in needles:
    start = 0
    while True:
        i = data.find(n, start)
        if i < 0:
            break
        print(f"{n.decode():14s} @0x{i:06x}  prev8={data[max(0,i-8):i].hex(' ')}")
        start = i + 1
        break
