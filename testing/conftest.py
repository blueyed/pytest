import os
import re
import sys
from typing import List

import pytest
from _pytest.compat import TYPE_CHECKING
from _pytest.mark.legacy import matchmark
from _pytest.pytester import RunResult

if TYPE_CHECKING:
    from _pytest.config import Config


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration-tests", action="store_true", help=("Run integration tests.")
    )


if sys.gettrace():

    @pytest.fixture(autouse=True)
    def restore_tracing():
        """Restore tracing function (when run with Coverage.py).

        https://bugs.python.org/issue37011
        """
        orig_trace = sys.gettrace()
        yield
        if sys.gettrace() != orig_trace:
            sys.settrace(orig_trace)


@pytest.hookimpl
def pytest_runtest_setup(item):
    mark = "integration"
    option = "--run-integration-tests"
    if mark not in item.keywords or item.config.getoption(option):
        return

    # Run the test anyway if it was provided via its nodeid as arg.
    # NOTE: do not use startswith: should skip
    # "tests/test_foo.py::test_bar" with
    # "tests/test_foo.py" in invocation args.
    if any(item.nodeid == arg for arg in item.config.invocation_params.args):
        return

    # Run the test if selected by mark explicitly.
    markexpr = item.config.option.markexpr
    if markexpr and matchmark(item, markexpr):
        return

    pytest.skip("Not running {} test (use {})".format(mark, option))


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_collection_modifyitems(items):
    """Prefer faster tests.

    Use a hookwrapper to do this in the beginning, so e.g. --ff still works
    correctly.
    """
    fast_items = []
    slow_items = []
    slowest_items = []
    neutral_items = []

    yield


@pytest.fixture
def tw_mock():
    """Returns a mock terminal writer"""

    class TWMock:
        WRITE = object()

        def __init__(self):
            self.lines = []
            self.is_writing = False

        def sep(self, sep, line=None):
            self.lines.append((sep, line))

        def write(self, msg, **kw):
            self.lines.append((TWMock.WRITE, msg))

        def _write_source(self, lines, indents=()):
            if not indents:
                indents = [""] * len(lines)
            for indent, line in zip(indents, lines):
                self.line(indent + line)

        def line(self, line, **kw):
            self.lines.append(line)

        def markup(self, text, **kw):
            return text

        def get_write_msg(self, idx):
            flag, msg = self.lines[idx]
            assert flag == TWMock.WRITE
            return msg

        fullwidth = 80

    return TWMock()


@pytest.fixture
def dummy_yaml_custom_test(testdir):
    """Writes a conftest file that collects and executes a dummy yaml test.

    Taken from the docs, but stripped down to the bare minimum, useful for
    tests which needs custom items collected.
    """
    testdir.makeconftest(
        """
        import pytest

        def pytest_collect_file(parent, path):
            if path.ext == ".yaml" and path.basename.startswith("test"):
                return YamlFile(path, parent)

        class YamlFile(pytest.File):
            def collect(self):
                yield YamlItem(self.fspath.basename, self)

        class YamlItem(pytest.Item):
            def runtest(self):
                pass
    """
    )
    testdir.makefile(".yaml", test1="")


@pytest.fixture(scope="session", autouse=True)
def set_env(monkeypatch_session, pytestconfig: "Config") -> None:
    try:
        import coverage
    except ImportError:
        pass
    else:
        if coverage.Coverage.current():
            coveragerc = os.path.join(str(pytestconfig.rootdir), ".coveragerc")
            assert os.path.exists(coveragerc)
            monkeypatch_session.setenv("COVERAGE_PROCESS_START", coveragerc)

    monkeypatch_session.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch_session.delenv("PYTEST_ADDOPTS", raising=False)


@pytest.fixture
def symlink_or_skip():
    """Return a function that creates a symlink or raises ``Skip``.

    On Windows `os.symlink` is available, but normal users require special
    admin privileges to create symlinks.
    """

    def wrap_os_symlink(src, dst, *args, **kwargs):
        if os.path.islink(dst):
            return

        try:
            os.symlink(src, dst, *args, **kwargs)
        except OSError as e:
            pytest.skip("os.symlink({!r}) failed: {!r}".format((src, dst), e))
        assert os.path.islink(dst)

    return wrap_os_symlink


@pytest.fixture(scope="session")
def color_mapping():
    """Returns a utility class which can replace keys in strings in the form "{NAME}"
    by their equivalent ASCII codes in the terminal.

    Used by tests which check the actual colors output by pytest.
    """

    class ColorMapping:
        COLORS = {
            "red": "\x1b[31m",
            "green": "\x1b[32m",
            "yellow": "\x1b[33m",
            "bold": "\x1b[1m",
            "reset": "\x1b[0m",
            "kw": "\x1b[94m",
            "hl-reset": "\x1b[39;49;00m",
            "function": "\x1b[92m",
            "number": "\x1b[94m",
            "str": "\x1b[33m",
            "print": "\x1b[96m",
        }
        RE_COLORS = {k: re.escape(v) for k, v in COLORS.items()}

        @classmethod
        def format(cls, lines: List[str]) -> List[str]:
            """Straightforward replacement of color names to their ASCII codes."""
            return [line.format(**cls.COLORS) for line in lines]

        @classmethod
        def format_for_fnmatch(cls, lines: List[str]) -> List[str]:
            """Replace color names for use with LineMatcher.fnmatch_lines"""
            return [line.format(**cls.COLORS).replace("[", "[[]") for line in lines]

        @classmethod
        def format_for_rematch(cls, lines: List[str]) -> List[str]:
            """Replace color names for use with LineMatcher.re_match_lines"""
            return [line.format(**cls.RE_COLORS) for line in lines]

        @classmethod
        def requires_ordered_markup(cls, result: RunResult):
            """Should be called if a test expects markup to appear in the output
            in the order they were passed, for example:

                tw.write(line, bold=True, red=True)

            In Python 3.5 there's no guarantee that the generated markup will appear
            in the order called, so we do some limited color testing and skip the rest of
            the test.
            """
            if sys.version_info < (3, 6):
                # terminal writer.write accepts keyword arguments, so
                # py36+ is required so the markup appears in the expected order
                output = result.stdout.str()
                assert "test session starts" in output
                assert "\x1b[1m" in output
                pytest.skip("doing limited testing because lacking ordered markup")

    return ColorMapping
