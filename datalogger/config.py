"""
Reading of the Datalyse configuration files.

Reverse-engineered from Datalyse.exe (Delphi 3) and the shipped INI files.
`Datalyse.ini` is read from the program directory first, then from C:\\, exactly
as the original does.  Everything after the first empty line is ignored, the
keyword list is comma separated, and matching is case insensitive.

The structures here are also what DATALYSE.INI documents for itself:

    DATALYSE.INI,,{ control line }
    SEPARATOR,#9,{ ,:comma, #9:tab, ;:semicolon, other chars: no separator }
    COMPANYNUMBER,1,{ 1:all, 2:Atimco, 3:Buch&Holm, 4:IMPO, 5:Muller+Sørensen,
                      6:Radiometer, 7:SF, 8:Sagitta, 9:Other devices }
    DEVICE,1,ON : pt200 thermometer, impo, pt2, pt1
    PATH,C:\\DATALYSE\\
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

#: Shown wherever Datalyse's own configuration is required but absent.  The file
#: ships in the repository's ``original/`` directory, so this really means the
#: directory has gone missing -- say how to get it back.
MISSING_INI_HELP = (
    "Datalyse's own configuration was not found.  It ships in this repository's\n"
    "original/ directory, which is third-party material rather than AGPL -- see\n"
    "original/COPYRIGHT.md.\n\n"
    "If that directory is missing, restore it with\n\n"
    "    scripts/reverse.sh\n\n"
    "or point at a copy you already have: --ini /path/to/Datalyse.ini"
)

# Manufacturer codes, from the comment on the COMPANYNUMBER line.
COMPANIES = {
    1: "all",
    2: "Atimco",
    3: "Buch&Holm",
    4: "IMPO",
    5: "Muller+Sørensen",
    6: "Radiometer",
    7: "SF",
    8: "Sagitta",
    9: "Other devices",
}

DEFAULT_SEPARATOR = "\t"


def find_file(directory: str, *names: str) -> str | None:
    """
    Locate a file inside `directory` ignoring case.

    The shipped archive mixes cases (``DATALYSE.INI`` vs ``aciddata.ini``), and
    the original ran on a case-insensitive filesystem, so a Linux port has to
    match names the same forgiving way.
    """
    if not directory or not os.path.isdir(directory):
        return None
    try:
        entries = {e.lower(): e for e in os.listdir(directory)}
    except OSError:
        return None
    for name in names:
        hit = entries.get(name.lower())
        if hit:
            full = os.path.join(directory, hit)
            if os.path.isfile(full):
                return full
    return None



def _decode_separator(tok: str) -> str:
    """`#9` means tab; `,` and `;` are literal; anything else means 'none'."""
    tok = tok.strip()
    if not tok:
        return DEFAULT_SEPARATOR
    if tok.startswith("#"):
        try:
            return chr(int(tok[1:]))
        except ValueError:
            return DEFAULT_SEPARATOR
    if tok in (",", ";"):
        return tok
    return DEFAULT_SEPARATOR


@dataclass
class DeviceEntry:
    """One `DEVICE,<n>,<ON|OFF> : <description>` line from Datalyse.ini."""

    number: int
    enabled: bool
    description: str
    fields: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        """The human readable device name (first comma-separated field)."""
        return self.fields[0].strip() if self.fields else self.description.strip()

    @property
    def vendor(self) -> str:
        for f in self.fields[1:]:
            f = f.strip().lower()
            if f in ("impo", "atimco", "sf", "radiometer", "muller",
                     "buch&holm", "sagitta", "elcanic", "m+s"):
                return f
        return ""


class DatalyseConfig:
    """Parsed DATALYSE.INI."""

    def __init__(self) -> None:
        self.separator: str = DEFAULT_SEPARATOR
        self.company_number: int = 1
        self.path: str | None = None
        self.default_device: int | None = None
        self.default_device_name: str | None = None
        self.devices: dict[int, DeviceEntry] = {}
        self.raw_lines: list[str] = []
        self.source: str | None = None

    # ------------------------------------------------------------------ parse
    @classmethod
    def parse(cls, text: str, source: str | None = None) -> "DatalyseConfig":
        cfg = cls()
        cfg.source = source
        stopped = False
        for raw in text.splitlines():
            line = raw.rstrip("\r\n")
            cfg.raw_lines.append(line)
            if stopped:
                continue
            if not line.strip():
                stopped = True          # "Everything below the first empty line is skipped"
                continue
            parts = [p.strip() for p in line.split(",")]
            keyword = parts[0].strip().upper()
            value = parts[1] if len(parts) > 1 else ""

            if keyword == "SEPARATOR":
                cfg.separator = _decode_separator(value)
            elif keyword == "COMPANYNUMBER":
                try:
                    cfg.company_number = int(value)
                except ValueError:
                    cfg.company_number = 1
            elif keyword == "PATH":
                cfg.path = value or None
            elif keyword == "DEFAULTDEVICE":
                try:
                    cfg.default_device = int(value)
                except ValueError:
                    pass
                if len(parts) > 2:
                    cfg.default_device_name = parts[2].strip()
            elif keyword == "DEVICE":
                try:
                    number = int(value)
                except ValueError:
                    continue          # "If the selection is empty or invalid, it is ignored"
                rest = ",".join(parts[2:])
                # DEVICE,<n>,ON : description  OR  DEVICE,<n>,OFF: description
                upper = rest.upper()
                if ":" in rest:
                    state, desc = rest.split(":", 1)
                else:
                    state, desc = rest, ""
                enabled = "OFF" not in state.upper()
                fields = [f.strip() for f in desc.split(",") if f.strip()]
                cfg.devices[number] = DeviceEntry(number, enabled, desc.strip(), fields)
        return cfg

    @classmethod
    def load(cls, path: str) -> "DatalyseConfig":
        with open(path, "rb") as fh:
            raw = fh.read()
        for enc in ("cp1252", "utf-8", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:                                    # pragma: no cover
            text = raw.decode("cp1252", "replace")
        return cls.parse(text, source=os.path.abspath(path))

    @classmethod
    def find_and_load(cls, progdir: str | None = None) -> "DatalyseConfig":
        """Mirror the original search order: program dir, then C:\\."""
        candidates = []
        for d in (progdir, os.getcwd()):
            if d:
                hit = find_file(d, "Datalyse.ini")
                if hit:
                    candidates.append(hit)
        candidates += ["C:\\Datalyse.ini", "C:/Datalyse.ini"]
        for c in candidates:
            if os.path.isfile(c):
                return cls.load(c)
        raise FileNotFoundError("datalyse.ini not found")     # the app's own message

    # ------------------------------------------------------------------ query
    def enabled_devices(self) -> list[DeviceEntry]:
        return [d for d in self.devices.values() if d.enabled]

    def filtered_devices(self) -> list[DeviceEntry]:
        """Devices visible in the device menu, honouring COMPANYNUMBER."""
        out = self.enabled_devices()
        if self.company_number in (1, None) or self.company_number not in COMPANIES:
            return out
        want = COMPANIES[self.company_number].lower()
        kept = []
        for d in out:
            blob = (d.description + " " + " ".join(d.fields)).lower()
            if want in blob or d.vendor == want.split("&")[0]:
                kept.append(d)
        return kept or out

    def describe(self) -> str:
        lines = [
            f"source        : {self.source}",
            f"separator     : {self.separator!r} (0x{ord(self.separator):02X})",
            f"companynumber : {self.company_number} ({COMPANIES.get(self.company_number, '?')})",
            f"path          : {self.path}",
            f"defaultdevice : {self.default_device} {self.default_device_name or ''}",
            f"devices       : {len(self.devices)} defined, "
            f"{len(self.enabled_devices())} ON",
        ]
        return "\n".join(lines)
