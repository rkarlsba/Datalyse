"""Round-trip and semantic tests for the Datalyse .DAT format."""
import glob
import os

import pytest

from datalogger.datafile import DataFile, MAGIC_MULTI, MAGIC_SINGLE, sniff_separator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = sorted(glob.glob(os.path.join(ROOT, "original", "*.DAT"))) + \
          sorted(glob.glob(os.path.join(ROOT, "original", "*.TXT")))
SAMPLES = [p for p in SAMPLES if "README" not in p]

# Datalyse's own sample files live in original/ and are committed: they are
# third-party material rather than AGPL, and they are the ground truth for the
# format.  See original/COPYRIGHT.md.  If the directory has been removed there
# is nothing to round-trip, so skip rather than fail.
pytestmark = pytest.mark.skipif(
    len(SAMPLES) < 10,
    reason="Datalyse's sample .DAT/.TXT files are missing from original/ -- "
           "run scripts/reverse.sh to restore them",
)


def test_samples_present():
    assert len(SAMPLES) >= 10


@pytest.mark.parametrize("path", SAMPLES, ids=[os.path.basename(p) for p in SAMPLES])
def test_round_trip_is_byte_exact(path):
    """
    Reading a shipped file and writing it back must reproduce it exactly.

    This is the strongest available check on the format: it pins the separator,
    the CRLF line ends, cp1252 encoding, the sign-column space rule, the
    significant-digit rule, the unstripped comment and the quoted trailer block.
    """
    original = open(path, "rb").read()
    rewritten = DataFile.load(path).to_text().encode("cp1252")
    assert rewritten == original


def test_comment_leading_space_is_preserved():
    """TEMP.DAT really has ", Cooling graph ..." -- the space is data."""
    df = DataFile.load(os.path.join(ROOT, "original", "TEMP.DAT"))
    assert df.comment.startswith(" Cooling")


def test_negative_values_get_no_sign_column_space():
    """UNDERCOO.DAT contains "<sp>31\\t-0.1"."""
    df = DataFile.load(os.path.join(ROOT, "original", "UNDERCOO.DAT"))
    text = df.to_text()
    assert "\t-0.1\r\n" in text
    assert "\t -0.1" not in text


def test_trailer_stats_are_parsed():
    df = DataFile.load(os.path.join(ROOT, "original", "Poisson.DAT"))
    assert df.trailer[0].startswith('"Mean value')
    s = df.stats
    assert s and s[0].mean == pytest.approx(10.36)
    assert s[0].dispersion == pytest.approx(3.31)


def test_trailer_model_is_parsed():
    df = DataFile.load(os.path.join(ROOT, "original", "FIXING.DAT"))
    assert df.model == "t"
    assert df.model_params == [0.0, 0.0, 0.0, 0.0]


def test_trailer_survives_a_new_row(tmp_path):
    """Adding measured data must not lose the statistics/model block."""
    df = DataFile.load(os.path.join(ROOT, "original", "FIXING.DAT"))
    before = list(df.trailer)
    df.add_row([9999.0, 1.0])
    text = df.to_text()
    for line in before:
        assert line in text
    assert len(DataFile.parse(text).rows) == len(df.rows)


def test_repeated_mean_dispersion_pairs_are_kept_in_order():
    df = DataFile.load(os.path.join(ROOT, "original", "REFRIGER.DAT"))
    assert len(df.stats) >= 2
    assert all(s.mean is not None and s.dispersion is not None for s in df.stats)


def test_value_formatting_rules():
    """Seven significant digits, and a space only in place of a missing sign."""
    from datalogger.datafile import _fmt
    assert _fmt(0.0895996) == " 0.0895996"     # as in CAPACI.DAT
    assert _fmt(4.85473) == " 4.85473"
    assert _fmt(-0.1) == "-0.1"                # as in UNDERCOO.DAT
    assert _fmt(-3.25) == "-3.25"
    assert _fmt(4.0) == " 4"
    assert _fmt(218.3) == " 218.3"
    assert _fmt(None) == " "


def test_newly_measured_rows_are_formatted():
    df = DataFile(comment="c", device_names=["D"], settings=[0, 1, 0, 1],
                  x_label="t /s", y_labels=["y"])
    df.add_row([12.0, -3.25])
    df.add_row([13.5, 4.0])
    body = df.to_text().split("\r\n")
    assert body[3] == " 12\t-3.25"
    assert body[4] == " 13.5\t 4"


@pytest.mark.parametrize("path", SAMPLES, ids=[os.path.basename(p) for p in SAMPLES])
def test_parse_every_shipped_sample(path):
    df = DataFile.load(path)
    assert df.magic in (MAGIC_SINGLE, MAGIC_MULTI)
    assert df.rows, "no data rows"
    assert len(df.y_labels) >= 1
    assert all(len(r) >= 1 for r in df.rows)


@pytest.mark.parametrize("path", SAMPLES, ids=[os.path.basename(p) for p in SAMPLES])
def test_round_trip_preserves_structure(path):
    a = DataFile.load(path)
    b = DataFile.parse(a.to_text())
    assert b.magic == a.magic
    assert b.author == a.author
    assert b.comment == a.comment
    assert b.device_names == a.device_names
    assert b.settings == a.settings
    assert b.x_label == a.x_label
    assert b.y_labels == a.y_labels
    assert len(b.rows) == len(a.rows)


def test_values_survive_round_trip():
    path = os.path.join(ROOT, "original", "FIXING.DAT")
    a = DataFile.load(path)
    b = DataFile.parse(a.to_text())
    for ra, rb in zip(a.rows, b.rows):
        assert ra[0] == pytest.approx(rb[0], abs=1e-6)
        assert ra[1] == pytest.approx(rb[1], abs=1e-4)


def test_single_device_header_fields():
    df = DataFile.load(os.path.join(ROOT, "original", "FIXING.DAT"))
    assert df.magic == MAGIC_SINGLE
    assert df.separator == "\t"
    assert df.device_names == ["DMI multimeter"]
    assert df.settings == [0, 3, 0, 1]
    assert df.x_label == "t /s"
    assert df.y_labels == ["t /°C"]


def test_multi_device_header_fields():
    df = DataFile.load(os.path.join(ROOT, "original", "TRANSIST.TXT"))
    assert df.magic == MAGIC_MULTI
    assert df.device_names == ["MI Multiinterface", "DMI multimeter"]
    assert df.x_label == "time/s"
    assert df.y_labels == ["U /mV", "U / V"]
    assert len(df.rows[0]) == 3


def test_comma_separated_file():
    df = DataFile.load(os.path.join(ROOT, "original", "BA137.DAT"))
    assert df.separator == ","
    assert df.device_names == ["MC24E counter"]
    assert df.y_labels == ["A/Bq"]


def test_eight_channel_file():
    df = DataFile.load(os.path.join(ROOT, "original", "EM1LOG.TXT"))
    assert len(df.y_labels) == 7
    assert df.columns == 8
    assert len(df.rows[0]) == 8


def test_sniff_separator():
    assert sniff_separator("a\tb\n") == "\t"
    assert sniff_separator("a,b\n") == ","
    assert sniff_separator("a;b\n") == ";"
    assert sniff_separator("plain\n") == "\t"


def test_writer_uses_crlf_and_cp1252(tmp_path):
    df = DataFile(comment="Troom=24°C", device_names=["DMI multimeter"],
                  settings=[0, 3, 0, 1], x_label="t /s", y_labels=["t /°C"],
                  rows=[[0.25, 72.1]])
    out = tmp_path / "x.DAT"
    df.write(str(out))
    raw = out.read_bytes()
    assert b"\r\n" in raw
    assert "°C".encode("cp1252") in raw
    assert raw.startswith(b"DATALYSE\t")


def test_malformed_file_rejected():
    with pytest.raises(ValueError):
        DataFile.parse("NOTDATALYSE,foo\n")
