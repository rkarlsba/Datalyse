"""
Shared test configuration.

The tests that assert against Datalyse's own shipped files (the twelve sample
``.DAT``/``.TXT`` files and ``DATALYSE.INI``) need ``original/`` to be present.
That directory is deliberately **not** committed -- it holds the original
proprietary binary and its data, which are not ours to redistribute -- so when
it is missing those tests skip with an explanation instead of failing.

Get it back at any time with::

    scripts/reverse.sh

which re-downloads and regenerates ``original/`` along with everything else.
"""
import glob
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGINAL = os.path.join(ROOT, "original")

SAMPLES = sorted(glob.glob(os.path.join(ORIGINAL, "*.DAT"))) + \
          sorted(glob.glob(os.path.join(ORIGINAL, "*.TXT")))
SAMPLES = [p for p in SAMPLES if "README" not in p]

HAVE_SAMPLES = len(SAMPLES) >= 10
HAVE_INI = os.path.isfile(os.path.join(ORIGINAL, "DATALYSE.INI"))

MISSING_MSG = (
    "the original Datalyse files are not in original/ -- they are intentionally "
    "not committed; run scripts/reverse.sh to download and regenerate them"
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "needs_original: requires the files downloaded into original/")


def skip_without_original(reason=MISSING_MSG):
    pytest.skip(reason)
