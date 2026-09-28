"""
Shared test configuration.

The tests that assert against Datalyse's own shipped files (the twelve sample
``.DAT``/``.TXT`` files and ``DATALYSE.INI``) read them from ``original/``.
Those files are committed: they are third-party material under Carl
Hemmingsen's terms rather than the AGPL -- see ``original/COPYRIGHT.md`` -- and
being present is what makes the byte-exact format tests run at all.

If the directory has been removed, those tests skip with an explanation instead
of failing.  Restore it with::

    scripts/reverse.sh
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
    "Datalyse's own files are missing from original/ -- they are committed, so "
    "this means the directory was removed; run scripts/reverse.sh to restore it"
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "needs_original: requires the files downloaded into original/")


def skip_without_original(reason=MISSING_MSG):
    pytest.skip(reason)
