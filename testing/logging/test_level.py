import logging

import pytest
from _pytest.logging import validate_log_level
from _pytest.pytester import Testdir


def test_validate_log_level() -> None:
    with pytest.raises(
        pytest.UsageError,
        match="'foo' is not recognized as a logging level name for 'setting_name'",
    ):
        validate_log_level("foo", "setting_name")

    with pytest.raises(
        pytest.UsageError,
        match="'FOO' is not recognized as a logging level name for 'setting_name'",
    ):
        validate_log_level("FOO", "setting_name")

    assert validate_log_level("debug", "setting_name") == logging.DEBUG
    assert validate_log_level("0", "setting_name") == logging.NOTSET
    assert validate_log_level("123", "setting_name") == 123


def test_invalid_log_level(testdir: Testdir) -> None:
    result = testdir.runpytest("--log-cli-level", "foo")
    result.stderr.fnmatch_lines(
        [
            "ERROR: 'foo' is not recognized as a logging level name for 'log_cli_level'."
            " Please consider passing the logging level num instead.",
        ]
    )


def test_custom_log_level(testdir: Testdir) -> None:
    testdir.makeconftest(
        """
        import logging
        logging.addLevelName(42, "mylevel")
        """
    )
    testdir.makepyfile(
        """
        import logging

        def test():
            logging.log(42, "mytestmsg")
        """
    )
    result = testdir.runpytest("--log-cli-level", "mylevel")
    result.stdout.fnmatch_lines(
        [
            "collected 1 item",
            "",
            "test_custom_log_level.py::test ",
            "*- live log call -*",
            "mylevel  root:test_custom_log_level.py:4 mytestmsg",
            "PASSED * [[]100%[]]",
            "*= 1 passed in *",
        ]
    )
