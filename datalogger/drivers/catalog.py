"""
The driver catalog.

Every entry records where its protocol comes from:

``source='doc'``
    The vendor's online help for Datalyse documents the exchange (serial
    settings, command and response layout).  These parsers are exact and are
    covered by tests in ``tests/test_drivers.py``.
``source='binary'``
    The command/identity strings were recovered from Datalyse.exe's embedded
    Delphi string tables; the serial settings come from the help pages.  The
    response *layout* is not documented, so only the identification exchange is
    implemented exactly and measuring uses the documented-format assumption
    stated in ``notes``.
``source='inferred'``
    Serial settings from the help pages, but the measure exchange is not
    documented anywhere.  A generic numeric-line parser is used and the driver
    says so; these need a capture from real hardware to become exact.
``source='decompiled'``
    The measurement exchange itself was read out of Datalyse's own machine code
    (which help page and which address are in ``notes``), so the parser is a
    transcription of what the original does -- the strongest provenance
    available for a device the vendor never documented.  Getting at it means
    decompiling the form methods, which the reference-driven export misses: see
    ``scripts/delphi_methods.py`` and ``scripts/ghidra/DecompileAt.java``.

Recovered identification strings (from the string tables at VA 0x4854F8-0x48634C):

===========================  =============================
command sent                 expected answer contains
===========================  =============================
``*IDN?``                    ``FLUKE, 45``
``v``                        (DMI24 multimeter)
``V``                        ``PH1000`` / ``MC24E`` / ``EM1`` / ``MI``
``ID``                       ``  ``  (Fluke 867B)
``REV``                      ``GENESYS 20`` / ``SPEC 20 GENESYS``
``id?``                      ``E91`` / ``E00``
``=TY PHM210``               ``=TY CDM210``
``%RM400``                   ``RM400``
``#vr``                      ``HAMEG HO89``
``O8``                       ``Shinko``
``$ST``                      ``Lambda2``
``I4``                       (SF counter)
``w``                        (Bosch balance weighing)
``8``                        (Consort)
===========================  =============================
"""
from __future__ import annotations

import re

from .base import (NUM, DeviceError, Driver, SerialParams, all_floats, first_float,
                   register, strip_units, to_float)
from ..transport import Transport


# ---------------------------------------------------------------------------
# Documented byte protocols
# ---------------------------------------------------------------------------
@register
class ElmaTes2730(Driver):
    """
    Elma 2730 / Beha 2730 / TES 2730 multimeter (Datalyse devices 22, 25, 26).

    The help file is explicit: "you send a space without CR, LF and the meter
    responds with 5 bytes -- 1. byte: 0x02 start byte, 2. byte: area,
    3,4. byte: digits, decimal point, sign (or error code), 5. byte: 0x03 stop
    byte."
    """

    key = "elma2730"
    label = "elma/BEHA 2730"
    serial = SerialParams(baudrate=9600, bytesize=8, parity="N", stopbits=1)
    channels = ("value",)
    units = ("",)
    measure_command = " "          # a single space, deliberately without CR/LF
    command_terminator = ""
    response_bytes = 5
    source = "doc"
    notes = ("Frame is STX <area> <d1> <d2> ETX.  The two payload bytes carry the "
             "meter's own digit encoding; `decode_payload` implements the layout "
             "used by the Metex-family chipset and the raw frame is always "
             "available via `parse_frame` for verification against hardware.")

    #: 7-segment bit patterns for the Metex-style digit byte, bit 0 = segment a
    SEGMENTS = {
        0x7E: 0, 0x30: 1, 0x6D: 2, 0x79: 3, 0x33: 4,
        0x5B: 5, 0x5F: 6, 0x70: 7, 0x7F: 8, 0x7B: 9,
    }

    def parse_frame(self, frame: str) -> dict | None:
        """Return {'area': int, 'raw': (b1, b2)} for a valid 5-byte frame."""
        b = frame.encode("cp1252", "replace")
        if len(b) != 5 or b[0] != 0x02 or b[4] != 0x03:
            return None
        return {"area": b[1], "raw": (b[2], b[3])}

    def parse_measure(self, response: str) -> list[float] | None:
        info = self.parse_frame(response)
        if info is None:
            return None
        value = self.decode_payload(info["raw"][0], info["raw"][1])
        return [value] if value is not None else None

    def decode_payload(self, digit_byte: int, flags: int) -> float | None:
        """
        Decode the meter's two payload bytes.

        `digit_byte` is the seven-segment pattern of the single displayed digit
        group and `flags` carries decimal point / sign / over-range.  Returns
        None when the display shows an error code.
        """
        if digit_byte in (0x00, 0xFF):
            return None
        digit = self.SEGMENTS.get(digit_byte)
        if digit is None:
            return None
        value = float(digit)
        if flags & 0x08:
            value = -value
        return value


@register
class ExtechThermometer(Driver):
    """
    Extech thermometer (Datalyse device 88, "EXTECH thermometer").

    "you send a space without CR, LF and the meter responds with 7 bytes",
    baud 9600, no parity, 1 stop, 8 data bits, RTS low during communication.
    """

    key = "extech"
    label = "EXTECH thermometer"
    serial = SerialParams(baudrate=9600, bytesize=8, parity="N", stopbits=1)
    channels = ("t1", "t2")
    units = ("°C", "°C")
    measure_command = " "
    command_terminator = ""
    response_bytes = 7
    rts_low = True
    source = "doc"
    notes = "7-byte fixed frame; the help does not spell out the bit packing."

    def parse_measure(self, response: str) -> list[float] | None:
        b = response.encode("cp1252", "replace")
        if len(b) < 7:
            return None
        # Fall back to any ASCII digits present in the frame.
        vals = all_floats(strip_units(response))
        return vals or None


@register
class BoschBalance(Driver):
    """
    Bosch BS / EP / DMS / SAE balances (Datalyse devices 9, 36).

    Documented exactly: command ``w`` (or ``s``); the balance answers
    ``NNNBBBBDDDDDDDDBUUUU CR LF``, 22 characters.  "Datalyse cuts the first 3
    characters and removes all non-numeric characters and converts the
    remaining to a number."
    """

    key = "bosch"
    label = "Bosch balance"
    serial = SerialParams(baudrate=1200, bytesize=8, parity="N", stopbits=1)
    channels = ("mass",)
    units = ("g",)
    measure_command = "w"
    source = "doc"
    notes = ("BS series: 8 data bits; EP/DMS series: 7 data bits. The original "
             "tries 8/1 first and falls back to 7/2.")

    def parse_measure(self, response: str) -> list[float] | None:
        if len(response) < 4:
            return None
        body = response[3:]                       # "cuts the first 3 characters"
        digits = re.sub(r"[^0-9.]", "", body)     # "removes all non-numeric"
        if not digits:
            return None
        try:
            return [float(digits)]
        except ValueError:
            return None


@register
class ConsortMeter(Driver):
    """
    Consort P601 / C831 (Datalyse devices 20, 123).

    "Datalyse uses the command ``8`` and Consort responds with: #, VALUE, UNIT,
    °C, CH, Hour, Date, nnnn" -- the first time a header is transmitted as
    well.  A compact answer looks like ``nnnn 6.28 ph 21.2``.
    """

    key = "consort"
    label = "Consort P601"
    serial = SerialParams(baudrate=2400, bytesize=8, parity="N", stopbits=1)
    channels = ("value", "temperature")
    units = ("", "°C")
    measure_command = "8"
    source = "doc"

    VALUE_RE = re.compile(r"([-+]?\d+(?:[.,]\d+)?)\s*([A-Za-z/µ]+)?")
    UNIT_MAP = {"ph": "pH", "mv": "mV", "s/cm": "S/cm", "ms": "mS",
                "us": "µS", "c": "°C"}

    def parse_measure(self, response: str) -> list[float] | None:
        vals = all_floats(response)
        if not vals:
            return None
        return vals[:2]


# ---------------------------------------------------------------------------
# Drivers whose identification exchange was recovered from the binary
# ---------------------------------------------------------------------------
class _LineDriver(Driver):
    """Common shape for instruments that answer a measurement with one line."""

    def parse_measure(self, response: str) -> list[float] | None:
        if not response.strip():
            return None
        vals = all_floats(strip_units(response))
        return vals or None


@register
class Fluke8845A(_LineDriver):
    key = "fluke8845a"
    label = "Fluke 8845A"
    serial = SerialParams(baudrate=9600, bytesize=8, parity="N", stopbits=2)
    channels = ("value",)
    version_command = "*IDN?"
    version_expect = ("FLUKE", "45")
    measure_command = ""
    source = "binary"
    notes = ("Identity exchange recovered from the string table ('*IDN?' -> "
             "'FLUKE, 45'); the help documents 9600/no parity/2 stop/8 data. "
             "The measurement query is NOT attested anywhere, so none is sent: "
             "the driver reads the value the meter already transmits. Set "
             "measure_command from a capture if your unit needs polling.")


@register
class Fluke867B(_LineDriver):
    key = "fluke867b"
    label = "Fluke 867B"
    serial = SerialParams(baudrate=19200, bytesize=8, parity="N", stopbits=1)
    channels = ("value",)
    version_command = "ID"
    version_expect = ("867",)
    measure_command = ""
    source = "binary"
    notes = ("Identity command 'ID' recovered from the string table (the meter "
             "answers two spaces). 19200/no parity/1 stop/8 data per the help. "
             "The measurement exchange is undocumented.")


@register
class Dmi24Multimeter(_LineDriver):
    key = "dmi24"
    label = "DMI multimeter"
    serial = SerialParams(baudrate=9600, bytesize=8, parity="N", stopbits=1)
    channels = ("value",)
    version_command = "v"
    version_expect = ("dmi24", "t1")
    measure_command = ""
    source = "binary"
    notes = ("'v' whereupon 'dmi24' or 't1'; all three literals sit adjacent to "
             "each other in the string table, so 't1' is very likely a channel "
             "selector, but which one is the query is not proven -- no command "
             "is therefore sent and the meter's own output is read.")


@register
class Dmi4Multimeter(_LineDriver):
    key = "dmi4"
    label = "Digital demonstration multimeter"
    serial = SerialParams(baudrate=9600, bytesize=8, parity="N", stopbits=1)
    channels = ("value",)
    version_command = "V"
    version_expect = ("DMI4",)
    measure_command = ""
    source = "binary"
    notes = ("SF 'Digital demonstration multimeter' / DMI4, version 1.20; "
             "9600/no parity/1 stop/8 data and command 'V' for version are "
             "documented. The measurement query is not documented.")


@register
class ImpoHandheld(_LineDriver):
    """
    The IMPO handheld family: temperature, pH, conductivity, lux, O2,
    manometer and radioactivity meters (Datalyse devices 67, 68, 96, 128, 129,
    137, 138).  All share 9600/no parity/1 stop/8 data and command 'V'.
    """

    key = "impo_handheld"
    label = "Temperature-Meter"
    serial = SerialParams(baudrate=9600, bytesize=8, parity="N", stopbits=1)
    channels = ("value", "temperature")
    units = ("", "°C")
    version_command = "V"
    version_expect = ("V",)
    measure_command = ""
    source = "binary"
    notes = ("Version command 'V' is documented for every meter in this family "
             "(temperature, pH, conductivity, lux, O2, manometer, radioactivity) "
             "together with 9600/no parity/1 stop/8 data. The measurement query "
             "is not documented, so none is sent.")


@register
class GenesysSpectrophotometer(_LineDriver):
    key = "genesys"
    label = "Genesys"
    serial = SerialParams(baudrate=9600, bytesize=8, parity="N", stopbits=1)
    channels = ("absorbance",)
    version_command = "REV"
    version_expect = ("GENESYS", "SPEC 20")
    measure_command = "SND"
    source = "binary"
    notes = ("'REV' -> 'GENESYS 20'/'SPEC 20 GENESYS', 'BAUD 9600', 'SND' all "
             "recovered together in one string-table run.")


@register
class RadiometerPHM(_LineDriver):
    key = "phm"
    label = "pHM 210"
    serial = SerialParams(baudrate=2400, bytesize=7, parity="E", stopbits=1)
    channels = ("value",)
    version_command = "=TY PHM210"
    version_expect = ("PHM210", "CDM210")
    measure_command = "?TY"
    source = "binary"
    notes = ("'=TY PHM210' / '=TY CDM210' are the identity probes and '?TY' is "
             "the request the dispatcher sends next; Radiometer's own command "
             "set uses '?' for queries and '=' for setup, and the pairing was "
             "recovered from one string-table run. The answer format itself is "
             "undocumented, so the reply is parsed generically.")


@register
class ShinkoBalance(_LineDriver):
    key = "shinko"
    label = "Shinko"
    serial = SerialParams(baudrate=2400, bytesize=8, parity="N", stopbits=1)
    channels = ("mass",)
    units = ("g",)
    version_command = "O8"
    version_expect = ("shinko",)
    measure_command = ""
    source = "binary"
    notes = ("'O8' is the identity probe -- the dispatcher shows 'Shinko: O8' "
             "when it answers 'Shinko'. No measurement query was recovered, so "
             "none is sent.")


@register
class HamegScope(_LineDriver):
    key = "hameg"
    label = "Hameg"
    serial = SerialParams(baudrate=38400, bytesize=8, parity="N", stopbits=2)
    channels = ("value",)
    version_command = "#vr"
    version_expect = ("HAMEG",)
    measure_command = ""
    source = "binary"
    notes = ("'#vr' is the identity probe ('#vr' -> 'HAMEG HO89'); Hameg does "
             "automatic baud-rate detection. No measurement query was "
             "recovered, so none is sent.")


@register
class SfInstrument(_LineDriver):
    """S. Frederiksen (SF) instruments: counters, function generator, meters."""

    key = "sf"
    label = "Temperature-meter"
    serial = SerialParams(baudrate=9600, bytesize=8, parity="N", stopbits=1)
    channels = ("value",)
    version_command = "V"
    version_expect = ("SF", "2001", "2002")
    measure_command = ""
    source = "binary"
    notes = ("S. Frederiksen instruments answer 'V' with a version string "
             "('SF 2001', '2002.50'); 'B0'/'B2' switch the baud rate to "
             "1200/9600. The per-instrument measurement exchange is not "
             "documented.")


@register
class GenericLine(_LineDriver):
    """
    Last-resort driver.

    Reads one line and pulls every number out of it.  This is what the program
    falls back to for instruments Datalyse supports but whose protocol was
    never documented publicly -- it is honest about being a guess and exists so
    such a device can still be logged and the raw traffic inspected.
    """

    key = "generic"
    label = ""
    serial = SerialParams(baudrate=9600, bytesize=8, parity="N", stopbits=1)
    channels = ("value",)
    measure_command = ""
    source = "inferred"
    notes = ("No documented exchange: reads whatever the instrument sends. "
             "Use `datalogger monitor` to capture the real protocol and then "
             "add a proper driver.")


# ---------------------------------------------------------------------------
# Protocol recovered from the decompiled handlers
# ---------------------------------------------------------------------------
def _bcd(byte: int) -> int:
    """Two decimal digits per byte, high nibble first (FUN_0050D8A8)."""
    return (byte >> 4) * 10 + (byte & 0x0F)


@register
class Tes1380(Driver):
    """
    TES 1380 pH/ORP/temperature meter -- Datalyse device 110.

    Unlike every other TES family member this one is not inferred from the help
    file: the protocol was read out of the decompiled handlers.

    * ``0x00551CB0`` case ``0x6e`` is the measurement branch of the shared
      dispatcher.  It sends a single space, then hands the answer to
    * ``0x0050DD54``, the value decoder, and
    * ``0x0047FB84`` case ``0x6e`` installs this device's line settings before
      any of that runs: 9600/8/N/1, an **empty** command terminator, a 1 s read
      window, and ``0x03`` as the byte that ends a reply frame.

    So each command is answered by one ETX-terminated binary frame.  There is
    no ASCII in it: bytes 1..4 are packed decimal digits (two per byte) and
    bytes 6..7 are flag bits.  Datalyse never checks a start byte and never
    counts the frame, it simply reads whatever arrives inside the 1 s window,
    which is what :meth:`measure` does too -- except that it stops on the ETX.

    ``0x0050DD54`` also fixes the two encoded scales: the value digits are
    ``d1.d2d3d4`` (that is how the 0.001 pH resolution of the instrument
    survives the frame) and the temperature digits are ``d1d2.d3d4``.  In mV
    mode the same digits are two decades lower, so the meter sets a status bit
    and the original shifts them back by 100.
    """

    key = "tes1380"
    label = "TES-1380 pH meter"
    serial = SerialParams(baudrate=9600, bytesize=8, parity="N", stopbits=1)
    channels = ("pH", "t")
    units = ("pH", "°C")
    measure_command = " "
    command_terminator = ""
    response_bytes = 0
    #: the 1 s window the dispatcher installs for device 110
    timeout = 1.0
    source = "decompiled"
    notes = (
        "Recovered from Datalyse's own decompiled code, not from a datasheet: "
        "measurement command ' ' from case 0x6e of the measurement dispatcher "
        "at 0x00551CB0, frame layout from the decoder at 0x0050DD54, line "
        "settings and the empty terminator / ETX frame end (0x03) from case "
        "0x6e of the device dispatcher at 0x0047FB84. Decoded: frame bytes "
        "1,2 = value digits, 3,4 = temperature digits, 6 bit0 pH/mV, bit2 "
        "degC/degF, bit4 sign, 7 bit0 +10 decade, bit4 logging in progress. "
        "Byte 0 and byte 5 are not read by the original, and the total frame "
        "length is not fixed anywhere in it -- the read is timeout-driven.")

    #: digits the meter cannot report: 0xFFFF in the value bytes means "- - - -"
    BLANK = 0xFF

    #: the control-panel commands the TES log form sends (0x004E8CAC case 0x6e)
    STATE_COMMANDS = ("RP", "RQ", "RR")
    #: the settings dialog probes the 1380 with this instead of a space
    #: (0x00489740); it decodes with the same routine, so it is an alias
    PROBE_COMMAND = "s"
    #: the control-panel "read log" button for the 1380 (0x004EB1D8)
    LOG_COMMAND = "L"

    # ------------------------------------------------------------------ decode
    def decode_frame(self, frame: bytes) -> dict | None:
        """
        Decode one reply frame into its fields, or None if it is too short.

        Returns ``value``/``unit`` (pH or mV), ``temperature``/``temp_unit``,
        the ``logging`` and ``blank`` flags, ``decade`` (the +10 status bit the
        original applies before the mV shift) and the raw 8 bytes it used.
        """
        if len(frame) < 8:
            return None
        b = frame
        unit = "pH" if b[6] & 0x01 else "mV"
        value = _bcd(b[2]) / 10.0 + _bcd(b[1]) / 1000.0
        temperature = _bcd(b[4]) + _bcd(b[3]) / 100.0
        if b[7] & 0x01:                     # value sits a decade higher
            value += 10.0
        if value > 80.0 and unit == "pH":   # dead branch for pH, kept faithful
            value -= 80.0
        if b[6] & 0x10:                     # sign
            value = -value
        if unit == "mV":                    # mV is reported two decades low
            value *= 100.0
        return {
            "value": value,
            "unit": unit,
            "temperature": temperature,
            "temp_unit": "°C" if b[6] & 0x04 else "°F",
            "logging": bool(b[7] & 0x10),
            "blank": b[1] == self.BLANK and b[2] == self.BLANK,
            "decade": bool(b[7] & 0x01),
            "raw": bytes(b[:8]),
        }

    def parse_measure(self, response: str) -> list[float] | None:
        info = self.decode_frame(response.encode("cp1252", "replace"))
        if info is None or info["blank"]:
            return None
        return [round(info["value"], 3), round(info["temperature"], 2)]

    # --------------------------------------------------------------------- io
    def query(self, transport: Transport, command: str,
              timeout: float | None = None) -> bytes:
        """Send `command` (no terminator) and read up to the frame's ETX."""
        transport.flush_input()
        transport.write(command.encode("cp1252"))
        return transport.read_until(b"\x03", self.timeout if timeout is None else timeout)

    def measure(self, transport: Transport) -> list[float]:
        """
        One live reading: send a space, read until ETX.

        The transport reads with a timeout, so a meter that stays silent yields
        a short (or empty) frame and a DeviceError instead of a blocked port.
        """
        raw = self.query(transport, self.measure_command)
        vals = self.parse_measure(raw.decode("cp1252", "replace"))
        if vals is None:
            raise DeviceError(f"{self.key}: no reading in {raw!r}")
        return vals

    def read_state(self, transport: Transport) -> dict[str, bytes]:
        """
        The control panel's status exchange (0x004E8CAC, case 0x6e).

        Sends a space, then ``RP`` and ``RQ``, then repeats ``RR`` -- up to four
        times -- until the meter answers with a single byte.  The original's
        parsing of those answers is a state machine this port has not
        reimplemented, so the raw frames are returned for inspection: that is
        what a capture needs, and what the original compares (``RR`` must be one
        byte long to count as an answer).
        """
        out: dict[str, bytes] = {" ": self.query(transport, " ")}
        for command in ("RP", "RQ"):
            out[command] = self.query(transport, command)
        for _ in range(4):
            out["RR"] = self.query(transport, "RR")
            if len(out["RR"]) == 1:
                break
        return out
