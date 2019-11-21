import pytest
from _pytest.main import ExitCode
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


@pytest.mark.parametrize("returncode", (None, 42))
def test_wrap_session_notify_exception(returncode, testdir):
    c1 = testdir.makeconftest(
        """
        import pytest

        def pytest_sessionstart():
            raise ValueError("boom")

        def pytest_internalerror(excrepr, excinfo):
            pytest.exit("exiting after %s..." % excinfo.typename, returncode={returncode!r})
    """.format(
            returncode=returncode
        )
    )
    result = testdir.runpytest()
    if returncode:
        assert result.ret == returncode
    else:
        assert result.ret == ExitCode.INTERNAL_ERROR
    result.stdout.lines[0] == "INTERNALERROR> Traceback (most recent call last):"
    result.stdout.lines[-3:] == [
        'INTERNALERROR>   File "{}", line 2, in pytest_sessionstart'.format(c1),
        "INTERNALERROR>     raise ValueError",
        "INTERNALERROR> ValueError: boom",
    ]
    assert result.stderr.lines == ["Exit: exiting after ValueError..."]
