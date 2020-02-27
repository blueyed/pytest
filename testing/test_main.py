from typing import Optional
from typing import Tuple

import pytest
from _pytest.config import ExitCode
from _pytest.main import Session
from _pytest.pytester import Testdir


@pytest.mark.parametrize(
    "given,expected",
    {
        "empty": ("", ("", (None, None))),
        "no_fname": (":12", (":12", (None, None))),
        "base": ("fname:12", ("fname", (12, 12))),
        "invalid_lnum": ("fname:12a", ("fname:12a", (None, None))),
        "optional_colon": ("fname:12:", ("fname", (12, 12))),
        "windows": (r"c:\foo", (r"c:\foo", (None, None))),
        "windows_lnum": (r"c:\foo:12", (r"c:\foo", (12, 12))),
        # Ranges.
        "range": ("fname:1-2", ("fname", (1, 2))),
        "range-nostart": ("fname:-2", ("fname", (None, 2))),
        "range-noend": ("fname:1-", ("fname", (1, None))),
        "range-nostart-noend": ("fname:-", ("fname", (None, None))),
        "range-optional-colon": ("fname:1-2:", ("fname", (1, 2))),
        "range-invalid": ("fname:2-1:", ("fname", (2, 1))),
    },
)
def test_parse_fname_lnum_range(
    given: str, expected: Tuple[str, Tuple[Optional[int], Optional[int]]]
):
    assert Session._parse_fname_lnum_range(given) == expected


@pytest.mark.parametrize(
    "ret_exc",
    (
        pytest.param((None, ValueError)),
        pytest.param((42, SystemExit)),
        pytest.param((False, SystemExit)),
    ),
)
def test_wrap_session_notify_exception(ret_exc, testdir):
    returncode, exc = ret_exc
    c1 = testdir.makeconftest(
        """
        import pytest

        def pytest_sessionstart():
            raise {exc}("boom")

        def pytest_internalerror(excrepr, excinfo):
            returncode = {returncode!r}
            if returncode is not False:
                pytest.exit("exiting after %s..." % excinfo.typename, returncode={returncode!r})
    """.format(
            returncode=returncode, exc=exc.__name__
        )
    )
    result = testdir.runpytest()
    if returncode:
        assert result.ret == returncode
    else:
        assert result.ret == ExitCode.INTERNAL_ERROR
    assert result.stdout.lines[0] == "INTERNALERROR> Traceback (most recent call last):"

    if exc == SystemExit:
        assert result.stdout.lines[-3:] == [
            'INTERNALERROR>   File "{}", line 4, in pytest_sessionstart'.format(c1),
            'INTERNALERROR>     raise SystemExit("boom")',
            "INTERNALERROR> SystemExit: boom",
        ]
    else:
        assert result.stdout.lines[-3:] == [
            'INTERNALERROR>   File "{}", line 4, in pytest_sessionstart'.format(c1),
            'INTERNALERROR>     raise ValueError("boom")',
            "INTERNALERROR> ValueError: boom",
        ]
    if returncode is False:
        assert result.stderr.lines == ["mainloop: caught unexpected SystemExit!"]
    else:
        assert result.stderr.lines == ["Exit: exiting after {}...".format(exc.__name__)]


@pytest.mark.parametrize("returncode", (None, 42))
def test_wrap_session_exit_sessionfinish(
    returncode: Optional[int], testdir: Testdir
) -> None:
    testdir.makeconftest(
        """
        import pytest
        def pytest_sessionfinish():
            pytest.exit(msg="exit_pytest_sessionfinish", returncode={returncode})
    """.format(
            returncode=returncode
        )
    )
    result = testdir.runpytest()
    if returncode:
        assert result.ret == returncode
    else:
        assert result.ret == ExitCode.NO_TESTS_COLLECTED
    assert result.stdout.lines[-1] == "collected 0 items"
    assert result.stderr.lines == ["Exit: exit_pytest_sessionfinish"]


def test_session_shouldfail_from_failed(testdir: Testdir) -> None:
    testdir.makeconftest(
        """
        import pytest
        def pytest_runtestloop(session):
            raise session.Failed("session_failed")
    """
    )
    result = testdir.runpytest()
    assert result.ret == 1
    result.stdout.fnmatch_lines(["*= no tests ran in *s (session_failed) =*"])


def test_session_shouldfail_with_different_failed(testdir: Testdir) -> None:
    testdir.makeconftest(
        """
        import pytest
        def pytest_runtestloop(session):
            session.shouldfail = "session_shouldfail"
            raise session.Failed("session_failed")
    """
    )
    result = testdir.runpytest()
    assert result.ret == 1
    result.stdout.fnmatch_lines(["*= no tests ran in *s (session_shouldfail) =*"])
