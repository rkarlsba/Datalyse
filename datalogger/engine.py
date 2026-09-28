"""
Measurement engine.

Emulates what the original does after you pick a device from the menu and hit
"Measure (t,f(t))":

* open the port with the device's own line settings,
* run the identification exchange and compare the answer with the version the
  driver expects ("Vers. no. must be: ... or better"),
* then loop: read the instrument, append (t, value...) to the data set, redraw.

Sampling is time based and uses a monotonic clock, so the time column stays
honest even when a reading is slow -- the original does the same and simply
writes the elapsed seconds, which is why its files contain non-uniform
timestamps.

`Measurement` is deliberately transport-agnostic: pass a `LoopbackTransport`
or `PtyTransport` and the whole loop runs without hardware.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .datafile import DataFile
from .drivers import registry as driver_registry
from .drivers.base import DeviceError, Driver, SerialParams
from .drivers.devices import DeviceProfile, profile as profile_for
from .transport import DEFAULT_TIMEOUT, SerialTransport, Transport, TransportError


@dataclass
class DeviceBinding:
    """A device chosen from Datalyse.ini, resolved to a driver."""

    number: int
    name: str
    driver: Driver
    serial: SerialParams
    profile: DeviceProfile | None = None
    port: str | None = None

    def open(self, port: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> Transport:
        use = port or self.port
        if not use:
            raise TransportError(f"no serial port given for {self.name}")
        t = SerialTransport(port=use, timeout=timeout, **self.serial.pyserial_kwargs())
        t.open()
        return t


def resolve(device_number: int | None = None, device_name: str | None = None,
            driver_key: str | None = None) -> DeviceBinding:
    """
    Turn a Datalyse.ini device entry (or an explicit driver key) into a binding.

    Resolution order: explicit driver key, then the device profile table
    (keyed by the number in Datalyse.ini), then a name match, then the generic
    line driver so that *something* still works.
    """
    from .drivers.devices import find_by_name

    prof = None
    if device_number is not None:
        prof = profile_for(device_number)
    if prof is None and device_name:
        prof = find_by_name(device_name)

    if driver_key:
        drv = driver_registry()[driver_key]
    elif prof and prof.driver and prof.driver in driver_registry():
        drv = driver_registry()[prof.driver]
    else:
        drv = driver_registry()["generic"]

    serial = (prof.serial if prof and prof.serial else drv.serial)
    name = (prof.name if prof else None) or device_name or drv.label or drv.key
    return DeviceBinding(number=device_number or 0, name=name, driver=drv,
                         serial=serial, profile=prof)


class Measurement:
    """A running acquisition."""

    def __init__(self, binding: DeviceBinding, transport: Transport,
                 interval: float = 1.0, comment: str = "",
                 max_rows: int | None = None) -> None:
        self.binding = binding
        self.transport = transport
        self.interval = interval
        self.driver = binding.driver
        self.data = DataFile(
            comment=comment,
            device_names=[binding.name],
            settings=[0, 0, 0, 0],
            x_label="t /s",
            y_labels=list(self.driver.channels),
        )
        #: the original records the physical unit under each channel
        if getattr(self.driver, "units", None):
            self.data.y_labels = [
                u or c for c, u in zip(self.driver.channels,
                                       list(self.driver.units) + [""] * len(self.driver.channels))
            ]
        self.max_rows = max_rows
        self.identity: str | None = None
        self.errors: list[tuple[float, str]] = []
        self.on_sample: Callable[[float, list[float]], None] | None = None
        self._t0 = time.monotonic()
        self._stop = False

    # ------------------------------------------------------------------ setup
    def identify(self) -> str | None:
        """Run the version exchange; raises DeviceError on a version mismatch."""
        if not getattr(self.driver, "version_command", None):
            return None
        self.identity = self.driver.identify(self.transport)
        if not self.driver.version_ok(self.identity):
            raise DeviceError(
                f"{self.binding.name}: unexpected identity {self.identity!r}; "
                f"expected one of {self.driver.version_expect}"
            )
        return self.identity

    def stop(self) -> None:
        self._stop = True

    # ------------------------------------------------------------------- loop
    def sample_once(self) -> list[float] | None:
        t = time.monotonic() - self._t0
        try:
            vals = self.driver.measure(self.transport)
        except (DeviceError, TransportError) as exc:
            self.errors.append((t, str(exc)))
            return None
        self.data.rows.append([round(t, 3)] + list(vals))
        if self.on_sample:
            self.on_sample(t, vals)
        return vals

    def run(self, duration: float | None = None, rows: int | None = None,
            callbacks: Iterable[Callable[[float, list[float]], None]] = ()) -> DataFile:
        """
        Sample until stopped, until `duration` seconds elapse, or until `rows`
        readings have been taken (whichever comes first).
        """
        self._t0 = time.monotonic()
        self._stop = False
        limit = rows if rows is not None else self.max_rows
        deadline = None if duration is None else self._t0 + duration
        n = 0
        while not self._stop:
            next_at = self._t0 + (n + 1) * self.interval
            self.sample_once()
            n += 1
            if limit is not None and n >= limit:
                break
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                break
            sleep_for = next_at - now
            if sleep_for > 0:
                time.sleep(sleep_for)
        return self.data

    def save(self, path: str) -> None:
        self.data.write(path)
