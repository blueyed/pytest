""" terminal reporting of the full testing process.

This is a good source for looking at the various reporting hooks.
"""
import argparse
import collections
import datetime
import linecache
import os
import platform
import sys
import time
import warnings
from functools import partial
from typing import Any
from typing import Callable
from typing import Dict
from typing import Generator
from typing import List
from typing import Mapping
from typing import Optional
from typing import Tuple
from typing import Union

import attr
import pluggy
import py
from more_itertools import collapse
from wcwidth import wcswidth

import pytest
from _pytest import nodes
from _pytest._code.code import ExceptionInfo
from _pytest._code.code import ReprFileLocation
from _pytest.assertion.util import _running_on_ci
from _pytest.compat import shell_quote
from _pytest.compat import TYPE_CHECKING
from _pytest.config import Config
from _pytest.config import ExitCode
from _pytest.main import Session
from _pytest.pathlib import _shorten_path
from _pytest.reports import CollectReport
from _pytest.reports import TestReport

if TYPE_CHECKING:
    from _pytest._code.code import _TracebackStyle

REPORT_COLLECTING_RESOLUTION = 0.5

KNOWN_TYPES = (
    "failed",
    "passed",
    "skipped",
    "deselected",
    "xfailed",
    "xpassed",
    "warnings",
    "error",
)

_REPORTCHARS_DEFAULT = "fE"


def _getdimensions():
    # Improved version of shutil.get_terminal_size that looks at stdin,
    # stderr, stdout.  Ref: https://bugs.python.org/issue14841.
    fallback = (80, 24)
    # columns, lines are the working values
    try:
        columns = int(os.environ["COLUMNS"])
    except (KeyError, ValueError):
        columns = 0
    try:
        lines = int(os.environ["LINES"])
    except (KeyError, ValueError):
        lines = 0
    # only query if necessary
    if columns <= 0 or lines <= 0:
        for check in [sys.__stdin__, sys.__stderr__, sys.__stdout__]:
            try:
                size = os.get_terminal_size(check.fileno())
            except (AttributeError, ValueError, OSError):
                # fd is None, closed, detached, or not a terminal.
                continue
            if columns == 0 and size.columns > 0:
                columns = size.columns
            if lines == 0 and size.lines > 0:
                lines = size.lines
            if columns == 0 or lines == 0:
                # Might happen on Sourcehut's CI (both are 0, isatty() is True).
                continue
            break
        else:
            size = os.terminal_size(fallback)

        if columns <= 0:
            columns = size.columns
        if lines <= 0:
            lines = size.lines
    return columns, lines


_cached_terminal_width = None
_cached_terminal_width_sighandler = None


def get_terminal_width():
    global _cached_terminal_width
    global _cached_terminal_width_sighandler

    if _cached_terminal_width_sighandler is None:
        import signal

        _prev_sig_handler = None
        _in_sighandler = False

        def _clear_cache_on_sigwinch(signum, frame):
            global _cached_terminal_width
            nonlocal _in_sighandler

            assert not _in_sighandler
            _in_sighandler = True

            try:
                _cached_terminal_width = None
                if _prev_sig_handler and _prev_sig_handler is not signal.SIG_DFL:
                    _prev_sig_handler(signum, frame)
            finally:
                _in_sighandler = False

        try:
            _prev_sig_handler = signal.signal(signal.SIGWINCH, _clear_cache_on_sigwinch)
            _cached_terminal_width_sighandler = _clear_cache_on_sigwinch
        except (AttributeError, ValueError):  # e.g. "signal only works in main thread"
            _cached_terminal_width_sighandler = False

    if _cached_terminal_width_sighandler is False:
        return _getdimensions()[0]

    if _cached_terminal_width is None:
        _cached_terminal_width, _ = _getdimensions()
    return _cached_terminal_width


class MoreQuietAction(argparse.Action):
    """
    a modified copy of the argparse count action which counts down and updates
    the legacy quiet attribute at the same time

    used to unify verbosity handling
    """

    def __init__(self, option_strings, dest, default=None, required=False, help=None):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            nargs=0,
            default=default,
            required=required,
            help=help,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        new_count = getattr(namespace, self.dest, 0) - 1
        setattr(namespace, self.dest, new_count)
        # todo Deprecate config.quiet
        namespace.quiet = getattr(namespace, "quiet", 0) + 1


def pytest_addoption(parser):
    group = parser.getgroup("terminal reporting", "reporting", after="general")
    group._addoption(
        "-v",
        "--verbose",
        action="count",
        default=0,
        dest="verbose",
        help="increase verbosity.",
    )
    group._addoption(
        "-q",
        "--quiet",
        action=MoreQuietAction,
        default=0,
        dest="verbose",
        help="decrease verbosity.",
    )
    group._addoption(
        "--verbosity",
        dest="verbose",
        type=int,
        default=0,
        help="set verbosity. Default is 0.",
    )
    group._addoption(
        "-r",
        action="store",
        dest="reportchars",
        default=_REPORTCHARS_DEFAULT,
        metavar="chars",
        help="show extra test summary info as specified by chars: (f)ailed, "
        "(E)rror, (s)kipped, (x)failed, (X)passed, "
        "(p)assed, (P)assed with output, (a)ll except passed (p/P), or (A)ll. "
        "(w)arnings are enabled by default (see --disable-warnings), "
        "'N' can be used to reset the list. (default: 'fE').",
    )
    group._addoption(
        "--disable-warnings",
        "--disable-pytest-warnings",
        default=False,
        dest="disable_warnings",
        action="store_true",
        help="disable warnings summary",
    )
    group._addoption(
        "-l",
        "--showlocals",
        action="store_true",
        dest="showlocals",
        default=False,
        help="show locals in tracebacks (disabled by default).",
    )
    group._addoption(
        "--tb",
        metavar="style",
        action="store",
        dest="tbstyle",
        default="auto",
        choices=["auto", "long", "short", "no", "line", "native"],
        help=(
            "traceback print mode (auto/long/short/line/native/no):\n"
            " - auto (default): 'long' tracebacks for the first and last entry,"
            " but 'short' style for the other entries\n"
            " - long: exhaustive, informative traceback formatting\n"
            " - short: shorter traceback format\n"
            " - line: only one line per failure\n"
            " - native: Python standard library formatting\n"
            " - no: no traceback at all\n"
        ),
    )
    group._addoption(
        "--show-capture",
        action="store",
        dest="showcapture",
        choices=["no", "stdout", "stderr", "log", "all"],
        default="all",
        help="Controls how captured stdout/stderr/log is shown on failed tests. "
        "Default is 'all'.",
    )
    group._addoption(
        "--fulltrace",
        "--full-trace",
        action="store_true",
        default=False,
        help=(
            "don't cut any tracebacks (default is to cut). "
            "When used `-tb` defaults to 'long'."
        ),
    )
    group._addoption(
        "--color",
        metavar="color",
        action="store",
        dest="color",
        default="auto",
        choices=["yes", "no", "auto"],
        help="color terminal output (yes/no/auto).",
    )

    parser.addini(
        "console_output_style",
        help='console output: "classic", or with additional progress information ("progress" (percentage) | "count").',
        default="progress",
    )

    # Experimental.
    parser.addini(
        "assert_truncate_level",
        help=(
            "Truncate explanations of assertion failures?  "
            '("auto" (when verbosity < 2, and not running on CI), '
            "or minimum verbosity level to trigger it (i.e. 0 for no truncation)."
        ),
        default="auto",
    )


def pytest_configure(config: Config) -> None:
    reporter = TerminalReporter(config, sys.stdout)
    config.pluginmanager.register(reporter, "terminalreporter")
    if config.option.debug or config.option.traceconfig:

        def mywriter(tags, args):
            msg = " ".join(map(str, args))
            reporter.write_line("[traceconfig] " + msg)

        config.trace.root.setprocessor("pytest:config", mywriter)


def getreportopt(config: Config) -> str:
    reportchars = config.option.reportchars

    old_aliases = {"F", "S"}
    reportopts = ""
    for char in reportchars:
        if char in old_aliases:
            char = char.lower()
        if char == "a":
            reportopts = "sxXEf"
        elif char == "A":
            reportopts = "PpsxXEf"
        elif char == "N":
            reportopts = ""
        elif char not in reportopts:
            reportopts += char

    if not config.option.disable_warnings and "w" not in reportopts:
        reportopts = "w" + reportopts
    elif config.option.disable_warnings and "w" in reportopts:
        reportopts = reportopts.replace("w", "")

    return reportopts


@pytest.hookimpl(trylast=True)  # after _pytest.runner
def pytest_report_teststatus(report: TestReport) -> Tuple[str, str, str]:
    letter = "F"
    if report.passed:
        letter = "."
    elif report.skipped:
        letter = "s"

    outcome = report.outcome
    if report.when in ("collect", "setup", "teardown") and outcome == "failed":
        outcome = "error"
        letter = "E"

    return outcome, letter, outcome.upper()


@attr.s
class WarningReport:
    """Holds information for warnings captured by
    :func:`TerminalReporter.pytest_warning_captured`."""

    warning = attr.ib(type=warnings.WarningMessage)  # type: ignore
    """The original warning."""
    when = attr.ib(type=str)
    """When the warning was captured, e.g. "config", "collect", or
    "runtest" (see :func:`_pytest.hookspec.pytest_warning_captured`)."""
    fslocation = attr.ib(type=Tuple[str, int])
    """Source of the warning (file system location, see :func:`get_location`)."""
    nodeid = attr.ib(type=Optional[str], default=None)
    """Node id that generated the warning (see :func:`get_location`)."""
    count_towards_summary = True

    @property
    def message(self) -> str:
        """Formatted warning (the standard way, without trailing newline)."""
        wm = self.warning
        return warnings.formatwarning(
            str(wm.message), wm.category, wm.filename, wm.lineno, wm.line,
        ).rstrip()

    @property
    def source_line(self) -> str:
        line = self.warning.line
        if line is None:
            line = linecache.getline(self.warning.filename, self.warning.lineno)
        return line

    def get_location(self, config: Config) -> str:
        """
        Returns the more user-friendly information about the location
        of a warning.
        """
        filename, linenum = self.fslocation[:2]
        relpath = config.invocation_dir.bestrelpath(py.path.local(filename))
        if not self.nodeid:
            return "{}:{}".format(relpath, linenum)
        if self.nodeid.startswith(relpath):
            names = self.nodeid[len(relpath) :]
            if names.startswith("::"):
                return "{}:{}{}".format(relpath, linenum, names)
        return "{} ({}:{})".format(self.nodeid, relpath, linenum)


class TerminalReporter:
    def __init__(self, config: Config, file=None) -> None:
        import _pytest.config

        self.config = config
        self._numcollected = 0
        self._session = None  # type: Session  # type: ignore[assignment]
        self._showfspath = None

        self.stats = {}  # type: Dict[str, List[Any]]
        self._main_color = None  # type: Optional[str]
        self._known_types = None  # type: Optional[List]
        self.startdir = config.invocation_dir
        if file is None:
            file = sys.stdout
        self.writer = self._tw = _pytest.config.create_terminal_writer(config, file)
        self.currentfspath = None  # type: Any
        self.reportchars = getreportopt(config)
        self.hasmarkup = self._tw.hasmarkup
        self.isatty = file.isatty()
        self._progress_items_reported = 0
        self._show_progress_info = self._determine_show_progress_info()
        self._collect_report_last_write = None  # type: Optional[float]

        self._collect_ignored = {}  # type: Dict[str, List[py.path.local]]
        """Information about ignored paths (for reporting)."""

    def _determine_show_progress_info(self):
        """Return True if we should display progress information based on the current config"""
        # do not show progress if we are not capturing output (#3038)
        if self.config.getoption("capture", "no") == "no":
            return False
        # do not show progress if we are showing fixture setup/teardown
        if self.config.getoption("setupshow", False):
            return False
        cfg = self.config.getini("console_output_style")
        if cfg in ("progress", "count"):
            return cfg
        return False

    @property
    def verbosity(self):
        return self.config.option.verbose

    @property
    def showheader(self):
        return self.verbosity >= 0

    @property
    def showfspath(self):
        if self._showfspath is None:
            return self.verbosity >= 0
        return self._showfspath

    @showfspath.setter
    def showfspath(self, value):
        self._showfspath = value

    @property
    def showlongtestinfo(self):
        return self.verbosity > 0

    def hasopt(self, char):
        char = {"xfailed": "x", "skipped": "s"}.get(char, char)
        return char in self.reportchars

    def write_fspath_result(self, nodeid, res, **markup):
        fspath = self.config.rootdir.join(nodeid.split("::")[0])
        # NOTE: explicitly check for None to work around py bug, and for less
        # overhead in general (https://github.com/pytest-dev/py/pull/207).
        if self.currentfspath is None or fspath != self.currentfspath:
            if self.currentfspath is not None and self._show_progress_info:
                self._write_progress_information_filling_space()
            self.currentfspath = fspath
            fspath = self.startdir.bestrelpath(fspath)
            self._tw.line()
            self._tw.write(fspath + " ")
        self._tw.write(res, **markup)

    def write_ensure_prefix(self, prefix, extra="", **kwargs):
        if self.currentfspath != prefix:
            self._tw.line()
            self.currentfspath = prefix
            self._tw.write(prefix)
        if extra:
            self._tw.write(extra, **kwargs)
            self.currentfspath = -2

    def ensure_newline(self):
        if self.currentfspath:
            self._tw.line()
            self.currentfspath = None

    def write(self, content, **markup):
        self._tw.write(content, **markup)

    def write_line(self, line, **markup):
        if not isinstance(line, str):
            line = str(line, errors="replace")
        self.ensure_newline()
        self._tw.line(line, **markup)

    def rewrite(self, line, **markup):
        """
        Rewinds the terminal cursor to the beginning and writes the given line.

        :kwarg erase: if True, will also add spaces until the full terminal width to ensure
            previous lines are properly erased.

        The rest of the keyword arguments are markup instructions.
        """
        erase = markup.pop("erase", False)
        if erase:
            fill_count = self._tw.fullwidth - len(line) - 1
            fill = " " * fill_count
        else:
            fill = ""
        line = str(line)
        self._tw.write("\r" + line + fill, **markup)

    def write_sep(self, sep, title=None, **markup):
        self.ensure_newline()
        self._tw.sep(sep, title, **markup)

    def section(self, title, sep="=", **kw):
        kw.setdefault("bold", True)
        self._tw.sep(sep, title, **kw)

    def line(self, msg, **kw):
        self._tw.line(msg, **kw)

    def _add_stats(self, category: str, items: List) -> None:
        set_main_color = category not in self.stats
        self.stats.setdefault(category, []).extend(items[:])
        if set_main_color:
            self._set_main_color()

    def pytest_internalerror(self, excrepr):
        for line in str(excrepr).split("\n"):
            self.write_line("INTERNALERROR> " + line)
        return 1

    def pytest_warning_captured(
        self, when: str, warning_message: warnings.WarningMessage, item  # type: ignore[name-defined]
    ) -> None:
        fslocation = warning_message.filename, warning_message.lineno
        nodeid = item.nodeid if item is not None else ""
        warning_report = WarningReport(
            warning=warning_message, fslocation=fslocation, nodeid=nodeid, when=when
        )
        self._add_stats("warnings", [warning_report])

    def pytest_plugin_registered(self, plugin):
        if self.config.option.traceconfig:
            msg = "PLUGIN registered: {}".format(plugin)
            # XXX this event may happen during setup/teardown time
            #     which unfortunately captures our output here
            #     which garbles our output if we use self.write_line
            self.write_line(msg)

    def pytest_deselected(self, items):
        self._add_stats("deselected", items)

    def pytest_runtest_logstart(self, nodeid, location):
        # ensure that the path is printed before the
        # 1st test of a module starts running
        if self.showlongtestinfo:
            line = self._locationline(nodeid, *location)
            self.write_ensure_prefix(line, "")
        elif self.showfspath:
            fsid = nodeid.split("::")[0]
            self.write_fspath_result(fsid, "")

    def pytest_runtest_logreport(self, report: TestReport) -> None:
        self._tests_ran = True
        rep = report
        res = self.config.hook.pytest_report_teststatus(report=rep, config=self.config)
        category, letter, word = res
        if isinstance(word, tuple):
            word, markup = word
        else:
            markup = None
        self._add_stats(category, [rep])
        if rep.when == "call" or (rep.when == "setup" and rep.failed):
            self._progress_items_reported += 1
        if not letter and not word:
            # probably passed setup/teardown
            return
        running_xdist = hasattr(rep, "node")
        if markup is None:
            was_xfail = hasattr(report, "wasxfail")
            if rep.passed and not was_xfail:
                markup = {"green": True}
            elif rep.passed and was_xfail:
                markup = {"yellow": True}
            elif rep.failed:
                markup = {"red": True}
            elif rep.skipped:
                markup = {"yellow": True}
            else:
                markup = {}
        if self.verbosity <= 0:
            if not running_xdist and self.showfspath:
                self.write_fspath_result(rep.nodeid, letter, **markup)
            else:
                self._tw.write(letter, **markup)
        else:
            line = self._locationline(rep.nodeid, *rep.location)
            if not running_xdist:
                self.write_ensure_prefix(line, word, **markup)
                if self._show_progress_info:
                    self._write_progress_information_filling_space()
            else:
                self.ensure_newline()
                self._tw.write("[%s]" % rep.node.gateway.id)
                if self._show_progress_info:
                    self._tw.write(
                        self._get_progress_information_message() + " ", cyan=True
                    )
                else:
                    self._tw.write(" ")
                self._tw.write(word, **markup)
                self._tw.write(" " + line)
                self.currentfspath = -2

    @property
    def _is_last_item(self) -> bool:
        return self._progress_items_reported == self._session.testscollected

    def pytest_runtest_logfinish(self) -> None:
        """Write progress if past edge."""
        if self.verbosity > 0 or not self._show_progress_info:
            return

        if self._show_progress_info == "count":
            num_tests = self._session.testscollected
            progress_length = len(" [{0}/{0}]".format(num_tests))
        else:
            progress_length = len(" [100%]")

        w = self._width_of_current_line
        past_edge = w + progress_length + 1 >= self._tw.fullwidth
        if past_edge:
            msg = self._get_progress_information_message()
            main_color, _ = self._get_main_color()
            self._tw.write(msg + "\n", **{main_color: True})

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtestloop(self) -> Generator[None, None, None]:
        """Write final progress indicator."""
        outcome = yield  # type: pluggy.callers._Result
        if (
            getattr(self, "_tests_ran", False)
            and self.verbosity <= 0
            and self._show_progress_info
            and not outcome.excinfo
        ):
            self._write_progress_information_filling_space()

    def _get_progress_information_message(self) -> str:
        collected = self._session.testscollected
        if self._show_progress_info == "count":
            if collected:
                counter_format = "{{:{}d}}".format(len(str(collected)))
                format_string = " [{}/{{}}]".format(counter_format)
                return format_string.format(self._progress_items_reported, collected)
            return " [ {} / {} ]".format(collected, collected)
        else:
            if collected:
                return " [{:3d}%]".format(
                    self._progress_items_reported * 100 // collected
                )
            return " [100%]"

    def _write_progress_information_filling_space(self):
        color, _ = self._get_main_color()
        msg = self._get_progress_information_message()
        w = self._width_of_current_line
        fill = self._tw.fullwidth - w - 1
        self.write(msg.rjust(fill), **{color: True})

    @property
    def _width_of_current_line(self):
        """Return the width of current line, using the superior implementation of py-1.6 when available"""
        try:
            return self._tw.width_of_current_line
        except AttributeError:
            # py < 1.6.0
            return self._tw.chars_on_current_line

    def pytest_collection(self) -> None:
        if self.isatty:
            if self.config.option.verbose >= 0:
                self.write("collecting ... ", bold=True)
                self._collect_report_last_write = time.time()
        elif self.config.option.verbose >= 1:
            self.write("collecting ... ", bold=True)

    def pytest_collectreport(self, report: CollectReport) -> None:
        if report.failed:
            self._add_stats("error", [report])
        elif report.skipped:
            self._add_stats("skipped", [report])
        items = [x for x in report.result if isinstance(x, pytest.Item)]
        self._numcollected += len(items)
        if self.isatty:
            self.report_collect()

    def report_collect(self, final: bool = False) -> None:
        if self.config.option.verbose < 0:
            return

        if not final:
            # Only write "collecting" report every 0.5s.
            t = time.time()
            if (
                self._collect_report_last_write is not None
                and self._collect_report_last_write > t - REPORT_COLLECTING_RESOLUTION
            ):
                return
            self._collect_report_last_write = t

        errors = len(self.stats.get("error", []))
        skipped = len(self.stats.get("skipped", []))
        deselected = len(self.stats.get("deselected", []))
        selected = self._numcollected - errors - skipped - deselected
        if final:
            line = "collected "
        else:
            line = "collecting "
        line += (
            str(self._numcollected) + " item" + ("" if self._numcollected == 1 else "s")
        )
        if errors:
            line += " / %d error%s" % (errors, "s" if errors != 1 else "")
        if deselected:
            line += " / %d deselected" % deselected
        if skipped:
            line += " / %d skipped" % skipped
        if self._numcollected > selected > 0:
            line += " / %d selected" % selected
        if self._collect_ignored:
            ignored_count = sum(len(x) for x in self._collect_ignored.values())
            line += " ({} {} ignored)".format(
                ignored_count, "path" if ignored_count == 1 else "paths"
            )
        if self.isatty:
            self.rewrite(line, bold=True, erase=True)
            if final:
                self.write("\n")
        else:
            self.write_line(line)

    def _verbose_collect_ignored(self) -> Optional[List[str]]:
        """Get information about ignored files during collection."""
        verbosity = self.config.option.verbose
        if not self._collect_ignored or verbosity < 1:
            return []

        total = 0
        desc = []
        ret = []
        for via, paths in self._collect_ignored.items():
            count = len(paths)
            total += count
            if len(self._collect_ignored) > 1:
                desc.append("{} ({})".format(via, count))
            else:
                desc.append("via {}".format(via))

        ret = [
            "ignored {} {} ({})".format(
                total, "path" if total == 1 else "paths", ", ".join(desc)
            )
        ]
        if verbosity > 1:
            ret[-1] += ":"
            indent = "  " if len(self._collect_ignored) > 1 else ""
            for via, paths in self._collect_ignored.items():
                if indent:
                    ret.append("  via {}:".format(via))
                for path in paths:
                    ret.append(
                        "{} - {}".format(
                            indent, self.config.invocation_dir.bestrelpath(path)
                        )
                    )
        return ret

    @pytest.hookimpl(trylast=True)
    def pytest_sessionstart(self, session: Session) -> None:
        self._session = session
        self._sessionstarttime = time.time()
        if not self.showheader:
            return
        self.write_sep("=", "test session starts", bold=True)
        verinfo = platform.python_version()
        msg = "platform {} -- Python {}".format(sys.platform, verinfo)
        pypy_version_info = getattr(sys, "pypy_version_info", None)
        if pypy_version_info:
            verinfo = ".".join(map(str, pypy_version_info[:3]))
            msg += "[pypy-{}-{}]".format(verinfo, pypy_version_info[3])
        msg += ", pytest-{}, py-{}, pluggy-{}".format(
            pytest.__version__, py.__version__, pluggy.__version__
        )
        if (
            self.verbosity > 0
            or self.config.option.debug
            or getattr(self.config.option, "pastebin", None)
        ):
            msg += " -- {}".format(_shorten_path(sys.executable))
        self.write_line(msg)
        lines = self.config.hook.pytest_report_header(
            config=self.config, startdir=self.startdir
        )
        self._write_report_lines_from_hooks(lines)

    def _write_report_lines_from_hooks(self, lines):
        lines.reverse()
        for line in collapse(lines):
            self.write_line(line)

    @pytest.hookimpl(trylast=True)
    def pytest_report_header(self, config: Config) -> List[str]:
        rootdir = _shorten_path(str(config.rootdir))
        if rootdir == "~":
            # Typical with tests, use the full path then.
            line = "rootdir: ~ ({})".format(config.rootdir)
        else:
            line = "rootdir: {}".format(rootdir)

        if config.inifile:
            line += ", inifile: {}".format(
                _shorten_path(config.rootdir.bestrelpath(config.inifile))  # type: ignore  # (currently wrong)
            )
        cwd = _shorten_path(os.getcwd())
        if rootdir != cwd:
            line += ", cwd: {}".format(cwd)

        testpaths = config.getini("testpaths")
        if testpaths and config.args == testpaths:
            rel_paths = [_shorten_path(x) for x in testpaths]
            line += ", testpaths: {}".format(", ".join(rel_paths))
        result = [line]

        plugininfo = config.pluginmanager.list_plugin_distinfo()
        if plugininfo:
            result.append("plugins: %s" % ", ".join(_plugin_nameversions(plugininfo)))

        if config._implicit_args:
            result.append(
                "implicit args: %s"
                % ", ".join(
                    "{!r} ({})".format(" ".join([shell_quote(x) for x in values]), desc)
                    for desc, values in config._implicit_args
                )
            )
        if config.option.verbose > 1 and config.invocation_params.args:
            result.append(
                "explicit args: %s"
                % " ".join([shell_quote(str(x)) for x in config.invocation_params.args])
            )

        return result

    @pytest.hookimpl(hookwrapper=True)
    def pytest_ignore_collect(
        self, path: py.path.local
    ) -> Generator[
        None, pluggy.callers._Result, None,
    ]:
        """Register ignored files during collection for reporting."""
        outcome = yield
        ret = (
            outcome.get_result()
        )  # type: Optional[Union[bool, Tuple[bool, Optional[str]]]]
        if isinstance(ret, tuple):
            ignored, desc = ret[:2]
            if ignored and desc:
                self._collect_ignored.setdefault(desc, []).append(path)

    def pytest_collection_finish(self, session):
        self.report_collect(True)

        for line in self._verbose_collect_ignored():
            self._tw.line(line)

        lines = self.config.hook.pytest_report_collectionfinish(
            config=self.config, startdir=self.startdir, items=session.items
        )
        self._write_report_lines_from_hooks(lines)

        if self.config.getoption("collectonly"):
            if session.items:
                if self.config.option.verbose > -1:
                    self._tw.line("")
                self._printcollecteditems(session.items)

            failed = self.stats.get("failed")
            if failed:
                self.section("collection failures", "!")
                for rep in failed:
                    rep.toterminal(self._tw)

    def _printcollecteditems(self, items):
        # to print out items and their parent collectors
        # we take care to leave out Instances aka ()
        # because later versions are going to get rid of them anyway
        if self.config.option.verbose < 0:
            if self.config.option.verbose < -1:
                counts = {}  # type: Dict[str, int]
                for item in items:
                    name = item.nodeid.split("::", 1)[0]
                    counts[name] = counts.get(name, 0) + 1
                for name, count in sorted(counts.items()):
                    self._tw.line("%s: %d" % (name, count))
            else:
                for item in items:
                    self._tw.line(item.nodeid)
            return
        stack = []
        indent = ""
        for item in items:
            needed_collectors = item.listchain()[1:]  # strip root node
            while stack:
                if stack == needed_collectors[: len(stack)]:
                    break
                stack.pop()
            for col in needed_collectors[len(stack) :]:
                stack.append(col)
                if col.name == "()":  # Skip Instances.
                    continue
                indent = (len(stack) - 1) * "  "
                self._tw.line("{}{}".format(indent, col))
                if self.config.option.verbose >= 1:
                    if hasattr(col, "_obj") and col._obj.__doc__:
                        for line in col._obj.__doc__.strip().splitlines():
                            self._tw.line("{}{}".format(indent + "  ", line.strip()))

    @pytest.hookimpl(hookwrapper=True)
    def pytest_sessionfinish(self, session: Session, exitstatus: ExitCode):
        outcome = yield
        outcome.get_result()
        self._tw.line("")
        summary_exit_codes = (
            ExitCode.OK,
            ExitCode.TESTS_FAILED,
            ExitCode.INTERRUPTED,
            ExitCode.USAGE_ERROR,
            ExitCode.NO_TESTS_COLLECTED,
        )
        if exitstatus in summary_exit_codes:
            self.config.hook.pytest_terminal_summary(
                terminalreporter=self, exitstatus=exitstatus, config=self.config
            )
        if exitstatus == ExitCode.INTERRUPTED:
            self._report_keyboardinterrupt()
            del self._keyboardinterrupt_memo
        elif session.shouldstop:
            self.write_sep("!", session.shouldstop, red=True)
        if self.verbosity < -1:
            if session.shouldfail:
                self.write_line("!! {} !!".format(session.shouldfail), red=True)
        else:
            self.summary_stats()

    @pytest.hookimpl(hookwrapper=True)
    def pytest_terminal_summary(self):
        self.summary_errors()
        self.summary_failures()
        self.summary_warnings()
        self.summary_passes()
        yield
        self.short_test_summary()
        # Display any extra warnings from teardown here (if any).
        self.summary_warnings()

    def pytest_keyboard_interrupt(self, excinfo: ExceptionInfo) -> None:
        tbstyle = self.config.getoption("tbstyle", "auto")
        style = "long" if tbstyle == "auto" else tbstyle  # type: _TracebackStyle
        self._keyboardinterrupt_memo = excinfo.getrepr(funcargs=True, style=style)

    def pytest_unconfigure(self):
        if hasattr(self, "_keyboardinterrupt_memo"):
            self._report_keyboardinterrupt()

    def _report_keyboardinterrupt(self):
        excrepr = self._keyboardinterrupt_memo
        msg = excrepr.reprcrash.message
        self.write_sep("!", msg, red=True)
        if "KeyboardInterrupt" in msg:
            if self.config.option.fulltrace:
                excrepr.toterminal(self._tw)
            else:
                excrepr.reprcrash.toterminal(self._tw)
                self._tw.line(
                    "(to show a full traceback on KeyboardInterrupt use --full-trace)",
                    yellow=True,
                )

    def _locationline(self, nodeid, fspath, lineno, domain):
        if fspath:
            res = self.config.cwd_relative_nodeid(nodeid)
            # collect_fspath comes from testid which has a "/"-normalized path
            if self.verbosity >= 2 and nodeid.split("::")[0] != fspath.replace(
                "\\", nodes.SEP
            ):
                res += " <- " + self.startdir.bestrelpath(fspath)
        else:
            res = "[location]"
        return res + " "

    def _getfailureheadline(self, rep):
        head_line = rep.head_line
        if head_line:
            return head_line
        return "test session"  # XXX?

    def _getcrashline(self, rep):
        try:
            return str(rep.longrepr.reprcrash)
        except AttributeError:
            try:
                return str(rep.longrepr)[:50]
            except AttributeError:
                return ""

    #
    # summaries for sessionfinish
    #
    def getreports(self, name):
        values = []
        for x in self.stats.get(name, []):
            if not hasattr(x, "_pdbshown"):
                values.append(x)
        return values

    def summary_warnings(self):
        if not self.hasopt("w"):
            return

        all_warnings = self.stats.get("warnings")  # type: Optional[List[WarningReport]]
        if not all_warnings:
            return

        final = hasattr(self, "_already_displayed_warnings")
        if final:
            warning_reports = all_warnings[self._already_displayed_warnings :]
        else:
            warning_reports = all_warnings
        self._already_displayed_warnings = len(warning_reports)
        if not warning_reports:
            return

        grouped = (
            collections.OrderedDict()
        )  # type: collections.OrderedDict[str, collections.OrderedDict[str, List[WarningReport]]]
        for wr in warning_reports:
            if wr.when not in grouped:
                grouped[wr.when] = collections.OrderedDict()
            wmsg = "{}: {}".format(wr.warning.category.__name__, wr.warning.message)
            grouped[wr.when].setdefault(wmsg, []).append(wr)

        for when, grouped_by_message in grouped.items():
            title = (
                "warnings summary (final)" if final else "warnings summary"
            ) + " [{}]".format(when)
            self.write_sep("=", title, yellow=True, bold=False)
            for message, warning_reports in grouped_by_message.items():
                locations = []
                source_locs = []
                for w in warning_reports:
                    location = w.get_location(self.config)
                    if location in locations:
                        continue
                    self._tw.line(location)
                    locations.append(location)

                    source_loc = w.warning.filename, w.warning.lineno
                    if source_loc in source_locs:
                        continue
                    source_locs.append(source_loc)
                    line = w.source_line
                    if line:
                        self._tw.line("    {}".format(line.strip()))

                lines = message.splitlines()
                indented = "\n".join("  " + x for x in lines)
                message = indented.rstrip()
                self._tw.line(message)
                self._tw.line()
        self._tw.line("-- Docs: https://docs.pytest.org/en/latest/warnings.html")

    def summary_passes(self):
        if self.config.option.tbstyle != "no":
            if self.hasopt("P"):
                reports = self.getreports("passed")
                if not reports:
                    return
                self.write_sep("=", "PASSES")
                for rep in reports:
                    if rep.sections:
                        msg = self._getfailureheadline(rep)
                        self.write_sep("_", msg, green=True, bold=True)
                        self._outrep_summary(rep)
                    self._handle_teardown_sections(rep.nodeid)

    def _get_teardown_reports(self, nodeid: str) -> List[TestReport]:
        return [
            report
            for report in self.getreports("")
            if report.when == "teardown" and report.nodeid == nodeid
        ]

    def _handle_teardown_sections(self, nodeid: str) -> None:
        for report in self._get_teardown_reports(nodeid):
            self.print_teardown_sections(report)

    def print_teardown_sections(self, rep: TestReport) -> None:
        showcapture = self.config.option.showcapture
        if showcapture == "no":
            return
        for secname, content in rep.sections:
            if showcapture != "all" and showcapture not in secname:
                continue
            if "teardown" in secname:
                self.section(secname, "-")
                if content[-1:] == "\n":
                    content = content[:-1]
                self._tw.line(content)

    def summary_failures(self):
        if self.config.option.tbstyle != "no":
            reports = self.getreports("failed")
            if not reports:
                return
            self.write_sep("=", "FAILURES")
            if self.config.option.tbstyle == "line":
                for rep in reports:
                    line = self._getcrashline(rep)
                    self.write_line(line)
            else:
                for rep in reports:
                    msg = self._getfailureheadline(rep)
                    self.write_sep("_", msg, red=True, bold=True)
                    self._outrep_summary(rep)
                    self._handle_teardown_sections(rep.nodeid)

    def summary_errors(self):
        if self.config.option.tbstyle != "no":
            reports = self.getreports("error")
            if not reports:
                return
            self.write_sep("=", "ERRORS")
            for rep in self.stats["error"]:
                msg = self._getfailureheadline(rep)
                if rep.when == "collect":
                    msg = "ERROR collecting " + msg
                else:
                    msg = "ERROR at {} of {}".format(rep.when, msg)
                self.write_sep("_", msg, red=True, bold=True)
                self._outrep_summary(rep)

    def _outrep_summary(self, rep):
        rep.toterminal(self._tw)
        showcapture = self.config.option.showcapture
        if showcapture == "no":
            return
        for secname, content in rep.sections:
            if showcapture != "all" and showcapture not in secname:
                continue
            self.section(secname, "-")
            if content[-1:] == "\n":
                content = content[:-1]
            self._tw.line(content)

    def summary_stats(self) -> None:
        session_duration = time.time() - self._sessionstarttime
        (parts, main_color) = self.build_summary_stats_line()
        if self._session.exitstatus == ExitCode.INTERNAL_ERROR:
            main_color = "red"
        line_parts = []

        display_sep = self.verbosity >= 0
        if display_sep:
            fullwidth = self._tw.fullwidth
        for text, markup in parts:
            with_markup = self._tw.markup(text, **markup)
            if display_sep:
                fullwidth += len(with_markup) - len(text)
            line_parts.append(with_markup)
        msg = ", ".join(line_parts)

        main_markup = {main_color: True}
        duration = " in {}".format(format_session_duration(session_duration))
        duration_with_markup = self._tw.markup(duration, **main_markup)
        if display_sep:
            fullwidth += len(duration_with_markup) - len(duration)
        msg += duration_with_markup

        if display_sep:
            markup_for_end_sep = self._tw.markup("", **main_markup)
            if markup_for_end_sep.endswith("\x1b[0m"):
                markup_for_end_sep = markup_for_end_sep[:-4]
            fullwidth += len(markup_for_end_sep)
            msg += markup_for_end_sep

        if self._session.shouldfail:
            msg += " ({})".format(self._session.shouldfail)

        if display_sep:
            self.write_sep("=", msg, fullwidth=fullwidth, **main_markup)
        else:
            self.write_line(msg, **main_markup)

    def short_test_summary(self) -> None:
        if not self.reportchars:
            return

        if not self.isatty or _running_on_ci():
            termwidth = None
        else:
            termwidth = self._tw.fullwidth

        def show_simple(stat, lines: List[str]) -> None:
            failed = self.stats.get(stat, [])
            if not failed:
                return
            config = self.config
            for rep in failed:
                line = _get_line_with_reprcrash_message(config, rep, termwidth)
                lines.append(line)

        def show_xfailed(lines: List[str]) -> None:
            xfailed = self.stats.get("xfailed", [])
            for rep in xfailed:
                verbose_word = rep._get_verbose_word(self.config)
                pos = _get_pos(self.config, rep)
                lines.append("{} {}".format(verbose_word, pos))
                reason = rep.wasxfail
                if reason:
                    lines.append("  " + str(reason))

        def show_xpassed(lines: List[str]) -> None:
            xpassed = self.stats.get("xpassed", [])
            for rep in xpassed:
                verbose_word = rep._get_verbose_word(self.config)
                pos = _get_pos(self.config, rep)
                reason = rep.wasxfail
                lines.append("{} {} {}".format(verbose_word, pos, reason))

        def show_skipped(lines: List[str]) -> None:
            skipped = self.stats.get("skipped", [])
            fskips = _folded_skips(skipped) if skipped else []
            if not fskips:
                return
            verbose_word = skipped[0]._get_verbose_word(self.config)
            for num, fspath, lineno, reason in fskips:
                if reason.startswith("Skipped: "):
                    reason = reason[9:]
                if lineno is not None:
                    lines.append(
                        "%s [%d] %s:%d: %s"
                        % (verbose_word, num, fspath, lineno, reason)
                    )
                else:
                    lines.append("%s [%d] %s: %s" % (verbose_word, num, fspath, reason))

        REPORTCHAR_ACTIONS = {
            "x": show_xfailed,
            "X": show_xpassed,
            "f": partial(show_simple, "failed"),
            "s": show_skipped,
            "p": partial(show_simple, "passed"),
            "E": partial(show_simple, "error"),
        }  # type: Mapping[str, Callable[[List[str]], None]]

        lines = []  # type: List[str]
        for char in self.reportchars:
            action = REPORTCHAR_ACTIONS.get(char)
            if action:  # skipping e.g. "P" (passed with output) here.
                action(lines)

        if lines:
            self.section("short test summary info", "=")
            for line in lines:
                self.write_line(line)

    def _get_main_color(self) -> Tuple[str, List[str]]:
        if self._main_color is None or self._known_types is None or self._is_last_item:
            self._set_main_color()
            assert self._main_color
            assert self._known_types
        return self._main_color, self._known_types

    def _determine_main_color(self, unknown_type_seen: bool) -> str:
        stats = self.stats
        if "failed" in stats or "error" in stats:
            main_color = "red"
        elif "warnings" in stats or "xpassed" in stats or unknown_type_seen:
            main_color = "yellow"
        elif "passed" in stats or not self._is_last_item:
            main_color = "green"
        else:
            main_color = "yellow"
        return main_color

    def _set_main_color(self) -> None:
        unknown_types = []  # type: List[str]
        for found_type in self.stats.keys():
            if found_type:  # setup/teardown reports have an empty key, ignore them
                if found_type not in KNOWN_TYPES and found_type not in unknown_types:
                    unknown_types.append(found_type)
        self._known_types = list(KNOWN_TYPES) + unknown_types
        self._main_color = self._determine_main_color(bool(unknown_types))

    def build_summary_stats_line(self) -> Tuple[List[Tuple[str, Dict[str, bool]]], str]:
        main_color, known_types = self._get_main_color()

        parts = []
        for key in known_types:
            reports = self.stats.get(key, None)
            if reports:
                count = sum(
                    1 for rep in reports if getattr(rep, "count_towards_summary", True)
                )
                color = _color_for_type.get(key, _color_for_type_default)
                markup = {color: True, "bold": color == main_color}
                parts.append(("%d %s" % _make_plural(count, key), markup))

        if not parts:
            parts = [("no tests ran", {_color_for_type_default: True})]

        return parts, main_color


def _get_rep_reprcrash(
    rep: Union[CollectReport, TestReport], fulltrace: bool
) -> Optional[ReprFileLocation]:
    if not rep.longrepr:
        return None

    if isinstance(rep, TestReport) and not fulltrace:
        # This uses the first traceback entry for the location in the test itself
        # (rather than reprcrash, which might be less relevant for going to
        # directly, e.g. pexpect failures in pytest itself).
        try:
            return rep.longrepr.reprtraceback.reprentries[0].reprfileloc
        except AttributeError:
            pass

    # Handle --tb=native, --tb=no.
    try:
        return rep.longrepr.reprcrash
    except AttributeError:
        return None


def _get_pos(config: Config, rep: Union[CollectReport, TestReport]) -> str:
    nodeid = config.cwd_relative_nodeid(rep.nodeid)
    path, _, testname = nodeid.partition("::")

    if isinstance(rep, CollectReport):
        desc = "collecting"
        if nodeid:
            desc += " " + nodeid
        path = rep.fspath
    else:
        desc = nodeid

    # Append location (line number).
    crashloc = _get_rep_reprcrash(rep, config.option.fulltrace)
    if not crashloc:
        return desc

    assert isinstance(crashloc.path, str), crashloc.path
    crash_path = crashloc.path
    if os.path.isabs(crash_path):
        crash_path = _shorten_path(crash_path, str(config.invocation_dir))

    if str(crash_path).replace("\\", nodes.SEP) == path:
        if not testname:
            return "%s:%d" % (path, crashloc.lineno)
        return "%s:%d::%s" % (path, crashloc.lineno, testname)
    return "%s (%s:%d)" % (desc, crash_path, crashloc.lineno)


def _get_line_with_reprcrash_message(config, rep, termwidth):
    """Get summary line for a report, trying to add reprcrash message."""
    verbose_word = rep._get_verbose_word(config)
    pos = _get_pos(config, rep)

    line = "{} {}".format(verbose_word, pos)

    if termwidth is not None:
        len_line = wcswidth(line)
        assert len_line != -1, repr(line)
        ellipsis, len_ellipsis = "...", 3
        if len_line > termwidth - len_ellipsis:
            # No space for an additional message.
            return line

    try:
        msg = rep.longrepr.reprcrash.message
    except AttributeError:
        msg = None

    if msg is not None:
        # Remove duplicate prefix, e.g. "Failed:" from pytest.fail.
        implicit_prefix = verbose_word.lower() + ":"
        if msg[: len(implicit_prefix)].lower() == implicit_prefix:
            msg = msg[len(implicit_prefix) + 1 :]

        sep = " - "
        trans_nls = str.maketrans({"\r": "\\r", "\n": "\\n"})
        if termwidth is None:
            msg_trans = msg.translate(trans_nls)
            if wcswidth(msg_trans) == -1:
                msg_trans = repr(msg)
            return line + sep + msg_trans

        max_len_msg = termwidth - len_line - len(sep)
        orig_msg = msg
        msg = msg.translate(trans_nls)
        len_msg = wcswidth(msg)
        if len_msg == -1:
            # Non-printable/escape characters (except for newlines).
            msg = repr(orig_msg)
            len_msg = wcswidth(msg)
            assert len_msg != -1, repr(msg, orig_msg)

        if max_len_msg >= len_ellipsis:
            if len_msg > max_len_msg:
                max_len_msg -= len_ellipsis
                msg = msg[:max_len_msg]
                while wcswidth(msg) > max_len_msg:
                    msg = msg[:-1]
                msg += ellipsis
            line += sep + msg
    return line


def _folded_skips(skipped):
    d = {}
    for event in skipped:
        key = event.longrepr
        assert len(key) == 3, (event, key)
        keywords = getattr(event, "keywords", {})
        # folding reports with global pytestmark variable
        # this is workaround, because for now we cannot identify the scope of a skip marker
        # TODO: revisit after marks scope would be fixed
        if (
            event.when == "setup"
            and "skip" in keywords
            and "pytestmark" not in keywords
        ):
            key = (key[0], None, key[2])
        d.setdefault(key, []).append(event)
    values = []
    for key, events in d.items():
        values.append((len(events),) + key)
    return values


_color_for_type = {
    "failed": "red",
    "error": "red",
    "warnings": "yellow",
    "passed": "green",
}
_color_for_type_default = "yellow"


def _make_plural(count, noun):
    # No need to pluralize words such as `failed` or `passed`.
    if noun not in ["error", "warnings"]:
        return count, noun

    # The `warnings` key is plural. To avoid API breakage, we keep it that way but
    # set it to singular here so we can determine plurality in the same way as we do
    # for `error`.
    noun = noun.replace("warnings", "warning")

    return count, noun + "s" if count != 1 else noun


def _plugin_nameversions(plugininfo) -> List[str]:
    values = []  # type: List[str]
    for plugin, dist in plugininfo:
        # gets us name and version!
        name = "{dist.project_name}-{dist.version}".format(dist=dist)
        # questionable convenience, but it keeps things short
        if name.startswith("pytest-"):
            name = name[7:]
        # we decided to print python package names
        # they can have more than one plugin
        if name not in values:
            values.append(name)
    return values


def format_session_duration(seconds: float) -> str:
    """Format the given seconds in a human readable manner to show in the final summary"""
    if seconds < 60:
        return "{:.2f}s".format(seconds)
    else:
        dt = datetime.timedelta(seconds=int(seconds))
        return "{:.2f}s ({})".format(seconds, dt)
