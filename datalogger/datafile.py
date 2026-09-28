"""
Reader/writer for the ASCII data files Datalyse produces.

Format recovered by inspecting the twelve sample files shipped in
``datalyse.zip`` together with the strings the program uses when saving
(``DATALYSE``, ``DATATO``, ``DATATOMAL``).

Single device -- what "Save data" writes::

    DATALYSE<sep>Carl Hemmingsen<sep> A comment<sep>1
    DMI multimeter<sep>0<sep>3<sep>0<sep>1
    t /s<sep>t /°C
    <sp>0.25<sep><sp>72.1
    ...
    "f(t)=t
    "a1=0
    "a2=0
    "a3=0
    "a4=0

Several devices at once -- what "Save data" writes for `More Devices`::

    DATATO<sep>Carl Hemmingsen
    MI Multiinterface<sep>DMI multimeter
    time/s<sep>U /mV<sep>U / V
    0.5<sep>1.23<sep>2.34

Rules that are easy to get wrong.  Every one of these was confirmed against a
shipped sample and is covered by a test:

* The file is ANSI/cp1252, never UTF-16, and every line ends CRLF.
* The separator is whatever ``SEPARATOR`` says in Datalyse.ini; the shipped
  files use both TAB (0x09) and comma, so the reader sniffs it.
* Line 2 of a DATALYSE file carries four opaque configuration integers, kept
  verbatim on round-trip.
* The comment in line 1 can carry significant leading whitespace -- ``TEMP.DAT``
  holds ``DATALYSE,Carl Hemmingsen, Cooling graph for boiling water,1`` -- so it
  is not stripped.
* Values put a space in the sign column, but only for *non-negative* numbers:
  ``UNDERCOO.DAT`` really does contain ``<sp>31\\t-0.1``.
* Values carry up to seven significant digits, which is what a Delphi ``Single``
  prints: ``0.0895996``, ``4.85473``.
* A file may end with a quoted trailer block, in exactly one of four forms:
  ``"Mean value <x>``, ``"Dispersion <x>``, ``"f(t)=<expr>`` and ``"aN=<x>``.
  The trailer is kept verbatim *and* parsed through the properties below, so a
  round-trip stays byte-exact while the statistics remain readable.

Per-row raw text is retained, so re-writing a file that was only read
reproduces it byte for byte; rows a caller has modified are re-formatted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAGIC_SINGLE = "DATALYSE"
MAGIC_MULTI = "DATATO"
MAGIC_MULTI_ALT = "DATATOMAL"
LINE_END = "\r\n"

#: significant digits a saved value carries
SIG_DIGITS = 7


def sniff_separator(text: str) -> str:
    """Pick the field separator the way the original would have written it."""
    first = text.splitlines()[0] if text.splitlines() else ""
    for cand in ("\t", ",", ";"):
        if cand in first:
            return cand
    return "\t"


def _to_float(tok: str):
    """Parse one data field; None for blanks and non-numeric markers."""
    tok = tok.strip().replace(",", ".")
    if tok == "":
        return None
    try:
        return float(tok)
    except ValueError:
        # the original tolerated stray markers (e.g. '*' for "no reading")
        m = re.match(r"^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", tok)
        return float(m.group()) if m else None


def _fmt(v) -> str:
    """
    Format a data value the way the original does.

    The leading space occupies the sign column, but only for non-negative
    values -- negative numbers use that column for their minus sign.
    """
    if v is None:
        return " "
    f = float(v)
    if f == int(f) and abs(f) < 1e15:
        body = str(int(f))
    else:
        body = f"{f:.{SIG_DIGITS}g}"
    return (" " + body) if f >= 0 else body


def _num(v) -> str:
    """Format a model parameter the way the original does: ``0``, ``1.75``."""
    if v is None:
        return "0"
    f = float(v)
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return f"{f:g}"


def _parse_quoted(line: str) -> tuple[str, str]:
    """Split ``"Mean value 10.36`` into ``('Mean value', '10.36')``."""
    body = line[1:].strip()
    m = re.match(r"^(Mean value|Dispersion)\s+(.*)$", body)
    if m:
        return m.group(1), m.group(2).strip()
    key, _, val = body.partition("=")
    return key.strip(), val.strip()


@dataclass
class SeriesStats:
    """One ``"Mean value`` / ``"Dispersion`` pair from the trailer."""

    mean: float | None = None
    dispersion: float | None = None


@dataclass
class DataFile:
    """A parsed Datalyse data file."""

    magic: str = MAGIC_SINGLE
    author: str = "Carl Hemmingsen"
    comment: str = ""
    series_count: int = 1
    device_names: list[str] = field(default_factory=list)
    settings: list[int] = field(default_factory=list)
    x_label: str = "t /s"
    y_labels: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    separator: str = "\t"
    #: quoted trailer lines, verbatim, in file order
    trailer: list[str] = field(default_factory=list)
    # internal: raw field text per row as read, plus the parsed snapshot used
    # to tell whether a caller has actually modified a row
    _raw_rows: list[list[str]] = field(default_factory=list, repr=False)
    _parsed_rows: list[list] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------ access
    @property
    def columns(self) -> int:
        return 1 + len(self.y_labels)

    @property
    def model(self) -> str | None:
        """The saved f(t) expression, e.g. ``'t'``."""
        for line in self.trailer:
            key, val = _parse_quoted(line)
            if key == "f(t)":
                return val
        return None

    @property
    def model_params(self) -> list[float]:
        """a1..aN of the saved model, in the order they appear."""
        out: list[float] = []
        for line in self.trailer:
            key, val = _parse_quoted(line)
            if re.fullmatch(r"a\d+", key):
                try:
                    out.append(float(val))
                except ValueError:
                    out.append(0.0)
        return out

    @property
    def stats(self) -> list[SeriesStats]:
        """Mean/dispersion pairs recorded in the trailer, in file order."""
        out: list[SeriesStats] = []
        for line in self.trailer:
            key, val = _parse_quoted(line)
            if key not in ("Mean value", "Dispersion"):
                continue
            try:
                num = float(val)
            except ValueError:
                continue
            if key == "Mean value" or not out:
                out.append(SeriesStats())
            if key == "Mean value":
                out[-1].mean = num
            else:
                out[-1].dispersion = num
        return out

    def x_values(self) -> list:
        return [r[0] for r in self.rows if r]

    def y_values(self, index: int = 0) -> list:
        return [r[1 + index] if len(r) > 1 + index else None for r in self.rows]

    def add_row(self, values: list) -> None:
        """Append a freshly measured row (re-formatted when written)."""
        self.rows.append(list(values))

    # ------------------------------------------------------------------- write
    def to_text(self) -> str:
        sep = self.separator
        out = []
        if self.magic == MAGIC_SINGLE:
            out.append(sep.join([MAGIC_SINGLE, self.author, self.comment,
                                 str(self.series_count)]))
            dev = self.device_names[0] if self.device_names else ""
            nums = list(self.settings) + [0] * (4 - len(self.settings))
            out.append(sep.join([dev] + [str(n) for n in nums[:4]]))
        else:
            out.append(sep.join([self.magic, self.author]))
            out.append(sep.join(self.device_names))
        out.append(sep.join([self.x_label] + self.y_labels))
        for i, row in enumerate(self.rows):
            if (i < len(self._raw_rows) and i < len(self._parsed_rows)
                    and list(row) == list(self._parsed_rows[i])):
                out.append(sep.join(self._raw_rows[i]))
            else:
                out.append(sep.join(_fmt(v) for v in row))
        out.extend(self.trailer)
        return LINE_END.join(out) + LINE_END

    def write(self, path: str) -> None:
        with open(path, "wb") as fh:
            fh.write(self.to_text().encode("cp1252", "replace"))

    # ------------------------------------------------------------------- parse
    @classmethod
    def parse(cls, text: str) -> "DataFile":
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        if not lines:
            raise ValueError("empty data file")

        sep = sniff_separator(text)
        head = lines[0].split(sep)
        magic = head[0].strip().upper()
        if magic not in (MAGIC_SINGLE, MAGIC_MULTI, MAGIC_MULTI_ALT):
            raise ValueError(f"not a Datalyse data file (magic={head[0]!r})")

        df = cls(magic=magic, separator=sep)
        if magic == MAGIC_SINGLE:
            df.author = head[1].strip() if len(head) > 1 else ""
            # the comment is deliberately NOT stripped: leading spaces are data
            df.comment = head[2] if len(head) > 2 else ""
            if len(head) > 3:
                try:
                    df.series_count = int(head[3].strip())
                except ValueError:
                    df.series_count = 1
            if len(lines) > 1:
                d = lines[1].split(sep)
                df.device_names = [d[0].strip()] if d and d[0].strip() else []
                df.settings = []
                for tok in d[1:5]:
                    try:
                        df.settings.append(int(tok.strip()))
                    except ValueError:
                        df.settings.append(0)
            label_line, data_lines = (lines[2] if len(lines) > 2 else ""), lines[3:]
        else:
            df.author = head[1].strip() if len(head) > 1 else ""
            df.device_names = [t.strip() for t in lines[1].split(sep) if t.strip()]
            label_line, data_lines = (lines[2] if len(lines) > 2 else ""), lines[3:]

        labels = [t.strip() for t in label_line.split(sep)]
        df.x_label = labels[0] if labels else ""
        df.y_labels = labels[1:]

        for ln in data_lines:
            if ln.startswith('"'):
                df.trailer.append(ln)          # kept verbatim, see _parse_quoted
                continue
            toks = ln.split(sep)
            vals = [_to_float(t) for t in toks]
            if any(v is not None for v in vals):
                df.rows.append(vals)
                df._raw_rows.append(toks)
                df._parsed_rows.append(list(vals))
        return df

    @classmethod
    def load(cls, path: str) -> "DataFile":
        with open(path, "rb") as fh:
            raw = fh.read()
        for enc in ("cp1252", "utf-8"):
            try:
                return cls.parse(raw.decode(enc))
            except UnicodeDecodeError:
                continue
        return cls.parse(raw.decode("cp1252", "replace"))
