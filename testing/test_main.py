import pytest
from _pytest.main import Session


@pytest.mark.parametrize(
    "given,expected",
    {
        "empty": ("", ("", None)),
        "no_fname": (":12", (":12", None)),
        "base": ("fname:12", ("fname", 12)),
        "invalid_lnum": ("fname:12a", ("fname:12a", None)),
        "optional_colon": ("fname:12:", ("fname", 12)),
        "windows": (r"c:\foo", (r"c:\foo", None)),
        "windows_lnum": (r"c:\foo:12", (r"c:\foo", 12)),
    },
)
def test_parse_fname_lineno(given, expected):
    assert Session._parse_fname_lineno(given) == expected
