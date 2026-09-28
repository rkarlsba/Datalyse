"""
Driver model.

A driver bundles the four things the original hard-codes per instrument:

1. the serial line settings,
2. an identification/version exchange used to check the right device is on the
   port (the "Vers. no. must be: ... or better" dialogues),
3. the measurement exchange -- command out, response in,
4. a pure function turning the response into floating point channel values.

Keeping (4) as a pure string -> numbers function means every parser is testable
without a serial port, which is how the drivers here are verified.
"""
from __future__ import annotations

import abc
import re
from dataclasses import dataclass, field
from typing import Callable

from ..transport import Transport

# ---------------------------------------------------------------- serial setup
PARITY_NAMES = {"N": "none", "E": "even", "O": "odd", "M": "mark", "S": "space"}


@dataclass(frozen=True)
class SerialParams:
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1

    def describe(self) -> str:
        return (f"{self.baudrate}, {PARITY_NAMES.get(self.parity, self.parity)} parity, "
                f"{self.stopbits:g} stop, {self.bytesize} data bits")

    def pyserial_kwargs(self) -> dict:
        return dict(baudrate=self.baudrate, bytesize=self.bytesize,
                    parity=self.parity, stopbits=self.stopbits)


# ---------------------------------------------------------------------- values
class DeviceError(RuntimeError):
    """Raised when an instrument answers in a way we cannot interpret."""


# Widely used float pattern: optional sign, digits, optional decimal part.
NUM = r"[-+]?\d+(?:[.,]\d+)?"


def to_float(tok: str) -> float:
    return float(tok.replace(",", "."))


def first_float(text: str) -> float | None:
    m = re.search(NUM, text)
    return to_float(m.group()) if m else None


def all_floats(text: str) -> list[float]:
    return [to_float(m) for m in re.findall(NUM, text)]


def strip_units(text: str) -> str:
    """Remove the unit suffixes the instruments append to readings."""
    return re.sub(r"[A-Za-zµΩ%/°]+", " ", text)


# ---------------------------------------------------------------------- driver
class Driver(abc.ABC):
    """
    Base class for an instrument driver.

    Subclasses normally only set the class attributes and implement
    `parse_measure`; `identify` and `measure` do the I/O.
    """

    key: str = ""
    label: str = ""
    serial: SerialParams = SerialParams()
    channels: tuple[str, ...] = ("y",)
    units: tuple[str, ...] = ("",)
    #: command sent to ask the instrument its identity, if it has one
    version_command: str | None = None
    #: substring(s) that a correct answer must contain
    version_expect: tuple[str, ...] = ()
    #: command sent for each measurement
    measure_command: str = ""
    #: terminator appended to commands ("" for the byte-protocol devices)
    command_terminator: str = "\r"
    #: bytes to wait for, for fixed-length binary protocols (0 = read a line)
    response_bytes: int = 0
    #: how long to wait for the answer
    timeout: float = 2.0
    #: free-text provenance: where the protocol is documented
    source: str = ""
    notes: str = ""

    # ------------------------------------------------------------------ io
    def encode(self, command: str) -> bytes:
        return (command + self.command_terminator).encode("cp1252")

    def identify(self, transport: Transport) -> str | None:
        """Return the instrument's identity string, or None if it has none."""
        if not self.version_command:
            return None
        transport.flush_input()
        transport.write(self.encode(self.version_command))
        raw = transport.read_bytes(self.response_bytes) if self.response_bytes \
            else transport.read_line(self.timeout)
        if isinstance(raw, bytes):
            raw = raw.decode("cp1252", "replace")
        return raw.strip()

    def version_ok(self, identity: str | None) -> bool:
        if not self.version_expect:
            return True
        if identity is None:
            return False
        up = identity.upper()
        return any(e.upper() in up for e in self.version_expect)

    def raw_exchange(self, transport: Transport) -> str:
        transport.flush_input()
        # An empty measure_command means the protocol is unknown: read whatever
        # the instrument sends rather than inventing a query for it.
        if self.measure_command:
            transport.write(self.encode(self.measure_command))
        if self.response_bytes:
            data = transport.read_bytes(self.response_bytes, self.timeout)
            return data.decode("cp1252", "replace")
        return transport.read_line(self.timeout)

    def measure(self, transport: Transport) -> list[float]:
        raw = self.raw_exchange(transport)
        vals = self.parse_measure(raw)
        if vals is None:
            raise DeviceError(f"{self.key}: could not interpret {raw!r}")
        return vals

    # -------------------------------------------------------------- parsing
    @abc.abstractmethod
    def parse_measure(self, response: str) -> list[float] | None:
        """Turn a raw instrument response into channel values (None = no data)."""

    def __str__(self) -> str:
        return f"{self.key} ({self.label})"


# -------------------------------------------------------------------- registry
_REGISTRY: dict[str, Driver] = {}


def register(driver_cls: type[Driver]) -> type[Driver]:
    """Class decorator adding a driver to the registry."""
    inst = driver_cls()
    if not inst.key:
        raise ValueError(f"{driver_cls.__name__} must define a key")
    _REGISTRY[inst.key] = inst
    return driver_cls


def get(key: str) -> Driver:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(f"unknown driver {key!r}; known: {sorted(_REGISTRY)}") from None


def registry() -> dict[str, Driver]:
    return dict(_REGISTRY)


def find_for(device_name: str) -> Driver | None:
    """
    Best-effort match of a `DEVICE,...` name from Datalyse.ini to a driver.

    Consults the recovered device profile table first (which is how the
    original resolves a device), then falls back to the driver keys and labels.
    """
    name = (device_name or "").strip().lower()
    if not name:
        return None

    from .devices import find_by_name
    prof = find_by_name(device_name)
    if prof and prof.driver and prof.driver in _REGISTRY:
        return _REGISTRY[prof.driver]

    if name in _REGISTRY:
        return _REGISTRY[name]
    for d in _REGISTRY.values():
        if d.label and d.label.lower() in name:
            return d
    for d in _REGISTRY.values():
        if not d.label:
            continue
        words = [w for w in re.split(r"[^a-z0-9]+", d.label.lower()) if len(w) > 2]
        if words and all(w in name for w in words):
            return d
    return None
