"""
Serial transport abstraction.

The original talks to COM1..COM8 through the Win16/Win32 comm API.  Behaviour
that matters for faithful emulation:

* The port is configured with the device's own baud/parity/stop/data settings
  before any command is sent (`SetCommState` equivalent).
* Reads are line oriented and the device is expected to answer within a
  timeout; on timeout the original shows "no data" and keeps the series going.
* The port is opened *before* the instrument is switched on, which is why the
  help file insists on "turn on the PC first" -- opening a port toggles DTR and
  can wedge an attached instrument.

`LoopbackTransport` and `PtyTransport` exist so the driver logic is testable
without hardware; `PtyTransport` drives a real `pyserial` handle over a
pseudo-terminal, so the code path under test is the same one used on a PC.
"""
from __future__ import annotations

import abc
import os
import select
import time

DEFAULT_TIMEOUT = 2.0


class TransportError(RuntimeError):
    pass


class Transport(abc.ABC):
    """Minimal duck-type over the operations the drivers need."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self.is_open = False

    @abc.abstractmethod
    def open(self) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    @abc.abstractmethod
    def write(self, data: bytes) -> int: ...

    @abc.abstractmethod
    def _read_some(self, n: int, timeout: float) -> bytes: ...

    # ---------------------------------------------------------------- helpers
    def read_bytes(self, n: int, timeout: float | None = None) -> bytes:
        timeout = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        buf = b""
        while len(buf) < n:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            chunk = self._read_some(n - len(buf), left)
            if not chunk:
                break
            buf += chunk
        return buf

    def read_until(self, terminator: bytes = b"\r", timeout: float | None = None,
                   max_bytes: int = 4096) -> bytes:
        """Read until `terminator` (inclusive) or timeout, whichever first."""
        timeout = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        buf = b""
        while len(buf) < max_bytes:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            chunk = self._read_some(1, left)
            if not chunk:
                continue
            buf += chunk
            if buf.endswith(terminator):
                break
        return buf

    def read_line(self, timeout: float | None = None) -> str:
        """Read one \\r- or \\n-terminated line and decode it as cp1252."""
        raw = self.read_until(b"\n", timeout)
        if not raw:
            raw = self.read_until(b"\r", timeout)
        return raw.decode("cp1252", "replace").strip("\r\n")

    def flush_input(self) -> None:
        while self._read_some(256, 0.01):
            pass

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()


class SerialTransport(Transport):
    """Real hardware, via pyserial."""

    def __init__(self, port: str, baudrate: int = 9600, bytesize: int = 8,
                 parity: str = "N", stopbits: float = 1,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        super().__init__(timeout)
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self._ser = None

    def open(self):
        """Open the port.  Returns self so callers can chain (see PtyTransport.serve)."""
        import serial                       # imported lazily: optional dep
        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=self.bytesize,
            parity=self.parity,
            stopbits=self.stopbits,
            timeout=0.05,
            write_timeout=self.timeout,
        )
        self.is_open = True
        return self

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None
        self.is_open = False

    def write(self, data: bytes) -> int:
        if self._ser is None:
            raise TransportError("port not open")
        return self._ser.write(data) or len(data)

    def _read_some(self, n: int, timeout: float) -> bytes:
        if self._ser is None:
            raise TransportError("port not open")
        self._ser.timeout = max(0.01, min(timeout, 0.25))
        return self._ser.read(n) or b""


class PtyTransport(SerialTransport):
    """
    A real pyserial handle wired to a pseudo-terminal.

    `peer` is a file object for the other end of the pty: write to it to feed
    the transport data, read from it to see what the driver sent.  This lets
    the full driver path (baud/parity/line handling included) run in tests.

    `serve()` additionally emulates an instrument: a background thread watches
    what the driver writes and answers from a ``{command: response}`` script,
    which is the only way to test the real request/response ordering -- a test
    that pre-loads the answer would have it eaten by the driver's own
    flush-before-command.
    """

    def __init__(self, **kw) -> None:
        super().__init__(port="", **kw)
        self.peer = None
        self.peer_path = None
        self.sent_history: list[str] = []
        self._thread = None
        self._serving = False

    def open(self) -> None:
        import pty
        master, slave = pty.openpty()
        self.peer_path = os.ttyname(slave)
        self.port = self.peer_path
        # keep `slave` open: closing it would make the master see EOF
        self._slave_fd = slave
        self._master_fd = master
        self.peer = os.fdopen(os.dup(master), "r+b", buffering=0)
        return super().open()

    def close(self) -> None:
        self.stop_serving()
        super().close()
        try:
            if self.peer:
                self.peer.close()
        finally:
            for fd in (getattr(self, "_master_fd", None), getattr(self, "_slave_fd", None)):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            self._master_fd = self._slave_fd = None

    def feed(self, data: bytes) -> None:
        """Simulate the instrument sending `data`."""
        self.peer.write(data)
        self.peer.flush()

    # ----------------------------------------------------------- auto-responder
    def serve(self, script: dict[str, str]) -> "PtyTransport":
        """Answer the driver from `script` (longest command match wins)."""
        import threading
        self._script = sorted(script.items(), key=lambda kv: -len(kv[0]))
        self._serving = True
        self.sent_history = []
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self._thread.start()
        return self

    def _serve_loop(self) -> None:
        buf = b""
        while self._serving and self._master_fd is not None:
            try:
                r, _, _ = select.select([self._master_fd], [], [], 0.05)
            except (OSError, ValueError):
                break
            if not r:
                continue
            try:
                data = os.read(self._master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            for cmd, resp in self._script:
                if cmd.encode("cp1252") in buf:
                    self.sent_history.append(cmd)
                    buf = buf.split(cmd.encode("cp1252"), 1)[1]
                    if resp:
                        try:
                            self.feed(resp.encode("cp1252"))
                        except (OSError, ValueError):
                            return
                    break

    def stop_serving(self) -> None:
        self._serving = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def sent(self, timeout: float = 0.2) -> bytes:
        """Bytes the driver has written to the instrument."""
        if self._thread is not None:
            # the responder already drained the master side
            return "".join(self.sent_history).encode("cp1252")
        if self._master_fd is None:
            return b""
        out = b""
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            r, _, _ = select.select([self._master_fd], [], [], left)
            if not r:
                break
            out += os.read(self._master_fd, 4096)
        return out


class LoopbackTransport(Transport):
    """
    Fully in-memory instrument for unit tests.

    `script` maps a command prefix the driver writes to the response the
    instrument should return.  Every exchange is recorded in `history`.
    """

    def __init__(self, script: dict[str, str] | None = None,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        super().__init__(timeout)
        self.script = dict(script or {})
        self.history: list[tuple[str, str]] = []
        self._pending = b""
        self._out = b""

    def open(self):
        self.is_open = True
        return self

    def close(self) -> None:
        self.is_open = False

    def write(self, data: bytes) -> int:
        self._out += data
        text = self._out.decode("cp1252", "replace")
        for cmd, resp in self.script.items():
            if cmd and cmd in text:
                self.history.append((cmd, resp))
                self._pending = resp.encode("cp1252")
                self._out = b""
                break
        return len(data)

    def _read_some(self, n: int, timeout: float) -> bytes:
        chunk, self._pending = self._pending[:n], self._pending[n:]
        return chunk
