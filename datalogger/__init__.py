"""
datalogger -- a Python re-implementation of Datalyse (``Datalyse.exe``).

The original is a Borland Delphi 3 program (c) Carl Hemmingsen, last built
2012-07-15, that logs data from ~130 laboratory instruments over a serial port.
This package reproduces its observable behaviour:

* ``datalogger.config``   -- Datalyse.ini parsing, exactly as documented
* ``datalogger.datafile`` -- the ASCII ``.DAT`` format the program reads/writes
* ``datalogger.transport``-- serial layer, plus pty and loopback back ends
* ``datalogger.drivers``  -- per-instrument protocols, recovered from the binary
* ``datalogger.engine``   -- the measurement loop behind "Measure (t,f(t))"
* ``datalogger.analysis`` -- the Tools/analysis windows
* ``datalogger.cli``      -- command line front end
* ``datalogger.gui``      -- Tk front end mirroring the original forms
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
