"""Config, driver, transport, engine and analysis tests."""
import math
import os

import pytest

from datalogger.config import COMPANIES, DatalyseConfig
from datalogger.drivers import registry
from datalogger.drivers.base import find_for, Driver
from datalogger.drivers.devices import DEVICE_PROFILES, find_by_name, profile
from datalogger.engine import Measurement, resolve
from datalogger.transport import LoopbackTransport, PtyTransport
from datalogger import analysis as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INI = os.path.join(ROOT, "original", "DATALYSE.INI")


# ------------------------------------------------------------------- the config
@pytest.fixture(scope="module")
def cfg():
    if not os.path.isfile(INI):
        pytest.skip("Datalyse's DATALYSE.INI is missing from original/ -- "
                    "run scripts/reverse.sh to restore it")
    return DatalyseConfig.load(INI)


def test_separator_and_company(cfg):
    assert cfg.separator == "\t"
    assert cfg.company_number == 1
    assert COMPANIES[cfg.company_number] == "all"


def test_device_count_and_states(cfg):
    assert len(cfg.devices) >= 130
    assert cfg.devices[1].enabled and cfg.devices[1].name.startswith("pt200")
    # OFF devices must not be reported as ON
    assert not cfg.devices[33].enabled
    assert not cfg.devices[117].enabled
    # "OFF" contains "ON": the naive substring check would get this wrong
    assert "OFF" in cfg.raw_lines[[i for i, l in enumerate(cfg.raw_lines)
                                   if l.startswith("DEVICE,33")][0]]


def test_comments_after_blank_line_ignored(cfg):
    assert not any(l.strip().upper().startswith("DEVICE,") for l in cfg.raw_lines
                   if l.strip().startswith("Everything") or
                   l.strip().startswith("Note,"))


def test_enabled_subset_of_all(cfg):
    assert len(cfg.enabled_devices()) < len(cfg.devices)
    assert all(d.enabled for d in cfg.enabled_devices())


def test_hash_separator_means_tab():
    c = DatalyseConfig.parse("SEPARATOR,#9\nDEVICE,1,ON : x\n")
    assert c.separator == "\t"
    c = DatalyseConfig.parse("SEPARATOR,;\nDEVICE,1,ON : x\n")
    assert c.separator == ";"


def test_invalid_device_number_ignored():
    c = DatalyseConfig.parse("DEVICE,notanumber,ON : x\nDEVICE,5,ON : ok\n")
    assert set(c.devices) == {5}


# ------------------------------------------------------------------- the drivers
def test_registry_populated():
    reg = registry()
    assert len(reg) >= 10
    assert "generic" in reg
    for key, d in reg.items():
        assert d.key == key
        assert d.source in ("doc", "binary", "inferred", "decompiled")


def test_elma_frame_validation():
    d = registry()["elma2730"]
    good = bytes([0x02, 0x05, 0x7E, 0x00, 0x03]).decode("cp1252")
    assert d.parse_frame(good) == {"area": 0x05, "raw": (0x7E, 0x00)}
    assert d.parse_frame("junk") is None
    assert d.parse_frame(bytes([0x01, 0x02, 0x03, 0x04, 0x05]).decode("cp1252")) is None
    assert d.parse_measure(good) == [0.0]


def test_bosch_parse_matches_documented_recipe():
    """"cuts the first 3 characters and removes all non-numeric characters"."""
    d = registry()["bosch"]
    assert d.parse_measure("NNNBBBB00012345BUUUU\r\n") == [12345.0]
    assert d.parse_measure("abc") is None


def test_consort_parses_value_and_temperature():
    d = registry()["consort"]
    vals = d.parse_measure("nnnn 6.28 ph 21.2")
    assert vals[0] == pytest.approx(6.28)
    assert vals[1] == pytest.approx(21.2)


def test_fluke_identity_expectation():
    d = registry()["fluke8845a"]
    assert d.version_ok("FLUKE, 45, 1.0")
    assert not d.version_ok("KEITHLEY,2000")


# ------------------------------------------------------- the TES 1380 protocol
def tes_frame(value_digits, temp_digits, flags6=0x00, flags7=0x00):
    """
    Build a TES-1380 reply frame the way the meter packs it.

    ``value_digits``/``temp_digits`` are the four decimal digits each field
    carries, most significant first: the value is ``d1.d2d3d4`` and the
    temperature ``d1d2.d3d4``.  Layout recovered from 0x0050DD54: byte 0 is not
    read, bytes 1,2 hold the value (low pair first), 3,4 the temperature, byte 5
    is not read, 6 and 7 are flags, and the frame ends with ETX.
    """
    v_hi, v_lo = int("".join(map(str, value_digits[:2]))), int("".join(map(str, value_digits[2:])))
    t_hi, t_lo = int("".join(map(str, temp_digits[:2]))), int("".join(map(str, temp_digits[2:])))
    packed = lambda pair: (pair // 10) << 4 | (pair % 10)   # noqa: E731
    return bytes([0x02, packed(v_lo), packed(v_hi), packed(t_lo), packed(t_hi),
                  0x00, flags6, flags7, 0x03])


def test_tes1380_decodes_ph_and_temperature():
    """Datalyse's own example scale: 7.006 pH at 25.40 degC (case 0x6e)."""
    d = registry()["tes1380"]
    frame = tes_frame((7, 0, 0, 6), (2, 5, 4, 0), flags6=0x05)
    info = d.decode_frame(frame)
    assert info["unit"] == "pH" and info["temp_unit"] == "°C"
    assert info["value"] == pytest.approx(7.006)
    assert info["temperature"] == pytest.approx(25.40)
    assert info["logging"] is False
    assert d.parse_measure(frame.decode("cp1252")) == pytest.approx([7.006, 25.4])


def test_tes1380_decodes_mv_with_the_decade_bit():
    """
    mV readings arrive two decades low with the +10 status bit set, which is
    how 1999 mV fits the same four digits (0x0050DD54): 9.99 + 10 = 19.99,
    shifted back by 100.
    """
    m = registry()["tes1380"]
    frame = tes_frame((9, 9, 9, 0), (2, 5, 4, 0), flags6=0x04, flags7=0x11)
    info = m.decode_frame(frame)
    assert info["unit"] == "mV" and info["temp_unit"] == "°C"
    assert info["decade"] is True
    assert info["value"] == pytest.approx(1999.0)
    assert info["logging"] is True                      # bit 0x10 of byte 7

    neg = tes_frame((6, 4, 5, 0), (2, 0, 0, 0), flags6=0x14)
    assert m.decode_frame(neg)["value"] == pytest.approx(-645.0)


def test_tes1380_blank_and_short_frames_are_not_readings():
    d = registry()["tes1380"]
    blank = bytes([0x02, 0xFF, 0xFF, 0x40, 0x25, 0x00, 0x05, 0x00, 0x03])
    assert d.decode_frame(blank)["blank"] is True
    assert d.parse_measure(blank.decode("cp1252")) is None
    assert d.parse_measure("junk") is None


def test_tes1380_serial_settings_match_the_dispatcher():
    """0x0047FB84 case 0x6e: 9600/8/N/1, no terminator, ETX ends the frame."""
    d = registry()["tes1380"]
    assert d.serial.baudrate == 9600 and d.serial.bytesize == 8
    assert d.serial.parity == "N" and d.serial.stopbits == 1
    assert d.command_terminator == ""
    assert d.measure_command == " "
    assert registry()["tes1380"].notes.lower().count("0x6e") == 2


def test_tes1380_pty_measure_sends_a_bare_space():
    d = registry()["tes1380"]
    frame = tes_frame((7, 0, 0, 6), (2, 5, 4, 0), flags6=0x05)
    t = PtyTransport(baudrate=9600, timeout=2.0)
    t.open().serve({" ": frame.decode("cp1252")})
    try:
        vals = d.measure(t)
        assert vals[0] == pytest.approx(7.006)
        assert vals[1] == pytest.approx(25.4)
        assert t.sent() == b" ", "the device needs no CR/LF"
    finally:
        t.close()


def test_tes1380_pty_read_state_sequence():
    """The control panel's RP/RQ/RR exchange, ending on the 1-byte answer."""
    d = registry()["tes1380"]
    live = tes_frame((7, 0, 0, 6), (2, 5, 4, 0), flags6=0x05)
    script = {" ": live.decode("cp1252"),
              "RP": "\x01\x03",
              "RQ": "\x02\x03",
              "RR": "\x03"}
    t = PtyTransport(baudrate=9600, timeout=1.0)
    t.open().serve(script)
    try:
        state = d.read_state(t)
    finally:
        t.close()
    assert list(state) == [" ", "RP", "RQ", "RR"]
    assert state["RR"] == b"\x03"
    assert state["RP"].startswith(b"\x01")


def test_tes1380_is_device_110_not_the_generic_fallback():
    from datalogger.drivers.devices import profile
    assert profile(110).driver == "tes1380"
    assert find_for("TES 1380 pH/ORP/temperature").key == "tes1380"


def test_drivers_do_not_invent_measurement_commands():
    """
    Provenance discipline: a driver may only claim a measurement command it can
    back up.  Anything that is not a direct transcription of the vendor help
    ('doc') must say in its notes where the command came from, or send none.
    """
    for key, d in registry().items():
        if d.measure_command and d.source != "doc":
            assert d.notes, (
                f"{key}: measure_command={d.measure_command!r} is not documented "
                f"but the driver gives no provenance in notes"
            )


def test_undocumented_drivers_send_nothing():
    """Where the measurement query is unknown, no query is invented."""
    for key in ("impo_handheld", "sf", "dmi24", "fluke8845a", "fluke867b",
                "shinko", "hameg"):
        assert registry()[key].measure_command == "", key


def test_generic_driver_never_raises_on_junk():
    d = registry()["generic"]
    assert d.parse_measure("") is None
    assert d.parse_measure("no digits here") is None
    assert d.parse_measure(" 1.5 mV ") == [1.5]


def test_find_for_by_label():
    assert find_for("dmi24 multimeter") is not None
    assert find_for("Fluke 8845A") is not None


# -------------------------------------------------------------- the device table
def test_every_ini_device_has_a_profile(cfg):
    for number, dev in cfg.devices.items():
        assert profile(number) is not None, f"device {number} ({dev.name}) unprofiled"


def test_profiles_are_wellformed():
    for number, p in DEVICE_PROFILES.items():
        assert p.name
        if p.driver:
            assert p.driver in registry(), f"device {number}: unknown driver {p.driver}"
        if p.id_command is None:
            assert p.note or p.driver == "generic", \
                f"device {number} has no id command and no explanation"


def test_profile_lookup():
    assert DEVICE_PROFILES[3].id_command == "*IDN?"
    assert DEVICE_PROFILES[20].serial.baudrate == 2400
    assert find_by_name("Fluke 8845A").name.startswith("Fluke")


# ------------------------------------------------------------------- transport
def test_loopback_scripted_exchange():
    t = LoopbackTransport({"V": "PH1000 v1.7\r\n"})
    t.open()
    t.write(b"V\r")
    line = t.read_line(0.2)
    assert "PH1000" in line
    assert t.history == [("V", "PH1000 v1.7\r\n")]


def test_pty_transport_real_serial_path():
    """The driver path driving an actual pyserial handle over a pty."""
    d = registry()["fluke8845a"]
    t = PtyTransport(baudrate=9600, bytesize=8, parity="N", stopbits=2, timeout=2.0)
    t.open().serve({"*IDN?": "FLUKE, 45, 1.0\r\n"})
    try:
        ident = d.identify(t)
        assert ident is not None and "FLUKE, 45" in ident
        assert "*IDN?" in t.sent().decode()
        assert d.version_ok(ident)
    finally:
        t.close()


def test_pty_measure_loop():
    d = registry()["consort"]
    t = PtyTransport(baudrate=2400, timeout=2.0)
    t.open().serve({"8": "nnnn 6.28 ph 21.2\r\n"})
    try:
        vals = d.measure(t)
        assert vals[0] == pytest.approx(6.28)
        assert t.sent().decode().startswith("8")
    finally:
        t.close()


def test_pty_autoresponder_rejects_wrong_device():
    """A wrong instrument on the port must fail the version check."""
    d = registry()["fluke8845a"]
    t = PtyTransport(baudrate=9600, timeout=1.0)
    t.open().serve({"*IDN?": "KEITHLEY,2000,1203\r\n"})
    try:
        ident = d.identify(t)
        assert ident is not None
        assert not d.version_ok(ident)
    finally:
        t.close()


# ---------------------------------------------------------------------- engine
def test_measurement_writes_rows(tmp_path):
    binding = resolve(driver_key="consort")
    t = PtyTransport(baudrate=2400, timeout=1.0)
    t.open().serve({"8": "nnnn 7.01 ph 22.0\r\n"})
    try:
        m = Measurement(binding, t, interval=0.0, comment="unit test")
        m.run(rows=3)
        assert len(m.data.rows) == 3
        assert m.data.rows[0][0] == pytest.approx(0.0, abs=0.5)
        out = tmp_path / "u.DAT"
        m.save(str(out))
        back = type(m.data).load(str(out))
        assert len(back.rows) == 3
        assert back.comment == "unit test"
        assert back.device_names == ["Consort P601"]
    finally:
        t.close()


def test_measurement_identify_then_measure():
    """The identification exchange has to succeed before the loop starts."""
    # Genesys has both a recovered identity exchange ('REV') and a recovered
    # measurement command ('SND'), so it exercises the whole sequence.
    binding = resolve(driver_key="genesys")
    t = PtyTransport(baudrate=9600, timeout=1.0)
    t.open().serve({"REV": "GENESYS 20\r\n", "SND": "0.1234\r\n"})
    try:
        m = Measurement(binding, t, interval=0.0)
        ident = m.identify()
        assert "GENESYS" in ident
        m.run(rows=2)
        assert len(m.data.rows) == 2
        assert m.data.rows[0][1] == pytest.approx(0.1234)
    finally:
        t.close()


def test_measurement_rejects_wrong_instrument():
    from datalogger.drivers.base import DeviceError
    binding = resolve(driver_key="fluke8845a")
    t = PtyTransport(baudrate=9600, timeout=1.0)
    t.open().serve({"*IDN?": "KEITHLEY,2000\r\n"})
    try:
        m = Measurement(binding, t)
        with pytest.raises(DeviceError):
            m.identify()
    finally:
        t.close()


def test_measurement_records_errors_without_dying():
    binding = resolve(driver_key="generic")
    t = LoopbackTransport({})          # never answers
    t.open()
    m = Measurement(binding, t, interval=0.0)
    m.run(rows=2)
    assert len(m.errors) == 2
    assert m.data.rows == []


def test_resolve_prefers_profile_over_driver_default():
    b = resolve(device_number=20)
    assert b.driver.key == "consort"
    assert b.serial.baudrate == 2400
    assert b.name == "Consort P601"
    b2 = resolve(device_number=3)
    assert b2.serial.stopbits == 2


# -------------------------------------------------------------------- analysis
def test_linear_regression_exact():
    x = [0, 1, 2, 3, 4]
    y = [1.0, 3.0, 5.0, 7.0, 9.0]
    r = A.linear_regression(x, y)
    assert r["slope"] == pytest.approx(2.0)
    assert r["intercept"] == pytest.approx(1.0)
    assert r["r2"] == pytest.approx(1.0)


def test_log_regression_recovers_power_law():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [3 * xi ** 2 for xi in x]
    r = A.linear_regression(x, y, log_x=True, log_y=True)
    assert r["slope"] == pytest.approx(2.0)
    assert r["intercept"] == pytest.approx(math.log10(3.0))   # a2*t^a1 -> log10 a2


def test_integral_of_line_is_area():
    x = [0.0, 1.0, 2.0, 3.0]
    y = [2.0, 2.0, 2.0, 2.0]
    assert A.integrate(x, y) == pytest.approx(6.0)
    assert A.integrate(x, y, 1.0, 2.0) == pytest.approx(2.0)


def test_model_fit_recovers_parameters():
    x = [float(i) for i in range(1, 21)]
    y = [2.5 * xi + 1.25 for xi in x]
    r = A.fit_model(x, y, "linear")
    assert r["params"][0] == pytest.approx(2.5, rel=1e-3)
    assert r["params"][1] == pytest.approx(1.25, rel=1e-3)
    assert r["r2"] == pytest.approx(1.0, abs=1e-6)
    assert r["template"] == "a1*t+a2"


def test_exponential_model_fit():
    x = [float(i) for i in range(1, 15)]
    y = [3.0 * 1.15 ** xi for xi in x]
    r = A.fit_model(x, y, "exp")
    # a1*exp(a2*t) fitted to 3*1.15**t  =>  a1 = 3, a2 = ln(1.15)
    assert r["params"][0] == pytest.approx(3.0, rel=1e-2)
    assert r["params"][1] == pytest.approx(math.log(1.15), rel=1e-3)
    assert r["template"] == "a1*exp(a2*t)"


def test_half_life_of_exponential_decay():
    lam = 0.1
    x = [float(i) for i in range(0, 50)]
    y = [100.0 * pow(2.718281828459045, -lam * xi) for xi in x]
    hl = A.half_life(x, y)
    assert hl == pytest.approx(0.693147 / lam, rel=1e-3)


def test_half_life_none_for_growing_data():
    assert A.half_life([0, 1, 2, 3], [1, 2, 3, 4]) is None


def test_extrema_and_zero_crossing():
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [-1.0, 0.5, 2.0, 0.5, -1.0]
    e = A.extrema(x, y)
    assert e["maximum"] == (2.0, 2.0)
    assert e["minimum"] == (0.0, -1.0)
    assert len(e["zeros"]) == 2
    assert e["zeros"][0] == pytest.approx(2.0 / 3.0, abs=1e-6)


def test_tangent_on_parabola():
    x = [float(i) for i in range(-10, 11)]
    y = [xi * xi for xi in x]
    slope, intercept = A.tangent(x, y, 3.0)
    assert slope == pytest.approx(6.0, abs=1e-9)
    assert intercept == pytest.approx(-9.0, abs=1e-9)


def test_autoscale_includes_all_points():
    lo, hi = A.autoscale([1.0, 2.5, 9.9])
    assert lo <= 1.0 and hi >= 9.9


def test_poisson_matches_theory():
    p = A.poisson_expected([5] * 1000)
    assert p["mean"] == pytest.approx(5.0)
    assert p["n"] == 1000


def test_acid_line_parsing():
    a = A.parse_acid_line("Sulfuric acid/*-3.0/1.99")
    assert a.name == "Sulfuric acid"
    assert a.pka == [-3.0, 1.99]
    assert a.marked == 0
    b = A.parse_acid_line("L-Arginine/2.02/8.99/*12.47")
    assert b.z == 3 and b.marked == 2
    c = A.parse_acid_line("Garbage without slashes")
    assert c is None


def test_titration_curve_shape():
    acid = A.parse_acid_line("Acetic acid/*4.76")
    v, ph = A.titration_curve(acid, conc_acid=0.1, conc_base=0.1, v_acid=25.0)
    assert len(v) == len(ph)
    assert ph[0] < 4.0                       # weak acid start
    # equivalence at 25 mL of 0.1 M base, pH should rise steeply there
    idx = int(abs(v - 25.0).argmin())
    assert ph[idx] > ph[0]
    assert ph[idx + 40] > ph[idx]            # still rising past equivalence
    assert ph.max() > 11.0
    assert ph.min() > 1.0


def test_titration_strong_acid_starts_low():
    a = A.parse_acid_line("Hydrochloric acid/*-7.0")
    v, ph = A.titration_curve(a, 0.1, 0.1, 25.0)
    assert ph[0] == pytest.approx(1.0, abs=0.05)


def test_fourier_finds_tone():
    import math
    n = 1024
    fs = 1000.0
    y = [math.sin(2 * math.pi * 50.0 * i / fs) for i in range(n)]
    r = A.fourier_spectrum(y, 1.0 / fs)
    assert r["peak_frequency"] == pytest.approx(50.0, abs=1.0)


def test_differentiate_log_axis():
    x = [1.0, 2.0, 4.0, 8.0]
    y = [0.0, 1.0, 2.0, 3.0]
    lx, d = A.differentiate(x, y, log_x=True)
    # y = log2(x) so dy/dlog10(x) = log10(2)*? -- monotone increasing anyway
    assert all(v > 0 for v in d[1:-1])
