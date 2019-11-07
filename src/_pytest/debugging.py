""" interactive debugging with PDB, the Python Debugger. """
import argparse
import functools
import sys
from typing import Generic
from typing import Optional
from typing import Tuple
from typing import TypeVar

from _pytest import outcomes
from _pytest.config import Config
from _pytest.config import hookimpl
from _pytest.config.exceptions import UsageError

if False:  # TYPE_CHECKING
    from typing import Type

    import pdb as pdb_for_typing  # noqa: F401

    from _pytest.capture import CaptureManager

_P = TypeVar("_P", bound="pdb_for_typing.Pdb")


def _validate_usepdb_cls(value) -> Tuple[str, str]:
    """Validate syntax of --pdbcls option."""
    try:
        modname, classname = value.split(":")
    except ValueError:
        raise argparse.ArgumentTypeError(
            "{!r} is not in the format 'modname:classname'".format(value)
        )
    return (modname, classname)


def pytest_addoption(parser):
    group = parser.getgroup("general")
    group._addoption(
        "--pdb",
        dest="usepdb",
        action="store_true",
        help="start the interactive Python debugger on errors or KeyboardInterrupt.",
    )
    group._addoption(
        "--pdbcls",
        dest="usepdb_cls",
        metavar="modulename:classname",
        type=_validate_usepdb_cls,
        help="start a custom interactive Python debugger on errors. "
        "For example: --pdbcls=IPython.terminal.debugger:TerminalPdb",
    )
    group._addoption(
        "--trace",
        dest="trace",
        action="store_true",
        help="Immediately break when running each test.",
    )


def pytest_configure(config: Config):
    import pytest

    main_plugin = pytestPDB(config)
    config.pluginmanager.register(main_plugin, "pdbsettrace")
    pytest.set_trace = main_plugin.set_trace

    if config.getvalue("trace"):
        config.pluginmanager.register(PdbTrace(config), "pdbtrace")
    if config.getvalue("usepdb"):
        config.pluginmanager.register(PdbInvoke(config), "pdbinvoke")


class PdbBase(Generic[_P]):
    def __init__(self, config: Config) -> None:
        self.config = config
        self._recursive_debug = 0
        self._wrapped_pdb_cls = None  # type: Optional[Tuple[Tuple[str, str], Type[_P]]]

    @classmethod
    def _is_capturing(cls, capman):
        if capman:
            return capman.is_capturing()
        return False

    def _import_pdb_cls(self) -> "Type[_P]":
        usepdb_cls = self.config.getvalue("usepdb_cls")  # type: Tuple[str, str]

        if self._wrapped_pdb_cls and self._wrapped_pdb_cls[0] == usepdb_cls:
            return self._wrapped_pdb_cls[1]

        if usepdb_cls:
            modname, classname = usepdb_cls

            try:
                __import__(modname)
                mod = sys.modules[modname]

                # Handle --pdbcls=pdb:pdb.Pdb (useful e.g. with pdbpp).
                parts = classname.split(".")
                pdb_cls = getattr(mod, parts[0])
                for part in parts[1:]:
                    pdb_cls = getattr(pdb_cls, part)
            except Exception as exc:
                value = ":".join((modname, classname))
                raise UsageError(
                    "--pdbcls: could not import {!r}: {}".format(value, exc)
                )
        else:
            import pdb

            pdb_cls = pdb.Pdb

        wrapped_cls = self._get_pdb_wrapper_class(pdb_cls)
        self._wrapped_pdb_cls = (usepdb_cls, wrapped_cls)
        return wrapped_cls

    def _get_pdb_wrapper_class(self, pdb_cls: "Type[_P]") -> "Type[_P]":
        import _pytest.config

        pytestPDB_obj = self
        capman = self.config.pluginmanager.getplugin(
            "capturemanager"
        )  # type: Optional[CaptureManager]

        class PytestPdbWrapper(pdb_cls):  # type: ignore
            _pytest_capman = capman
            _continued = False

            def do_debug(self, arg):
                pytestPDB_obj._recursive_debug += 1
                ret = super().do_debug(arg)
                pytestPDB_obj._recursive_debug -= 1
                return ret

            def do_continue(self, arg):
                ret = super().do_continue(arg)
                if pytestPDB_obj._recursive_debug == 0:
                    tw = _pytest.config.create_terminal_writer(pytestPDB_obj.config)
                    tw.line()

                    capman = self._pytest_capman
                    capturing = pytestPDB._is_capturing(capman)
                    if capturing:
                        if capturing == "global":
                            tw.sep(">", "PDB continue (IO-capturing resumed)")
                        else:
                            tw.sep(
                                ">",
                                "PDB continue (IO-capturing resumed for %s)"
                                % capturing,
                            )
                        assert capman
                        capman.resume()
                    else:
                        tw.sep(">", "PDB continue")
                pytestPDB_obj.config.pluginmanager.hook.pytest_leave_pdb(
                    config=pytestPDB_obj.config, pdb=self
                )
                self._continued = True
                return ret

            do_c = do_cont = do_continue

            def do_quit(self, arg):
                """Raise Exit outcome when quit command is used in pdb.

                This is a bit of a hack - it would be better if BdbQuit
                could be handled, but this would require to wrap the
                whole pytest run, and adjust the report etc.
                """
                ret = super().do_quit(arg)

                if pytestPDB_obj._recursive_debug == 0:
                    outcomes.exit("Quitting debugger")

                return ret

            do_q = do_quit
            do_exit = do_quit

            def setup(self, f, tb):
                """Suspend on setup().

                Needed after do_continue resumed, and entering another
                breakpoint again.
                """
                ret = super().setup(f, tb)
                if not ret and self._continued:
                    # pdb.setup() returns True if the command wants to exit
                    # from the interaction: do not suspend capturing then.
                    if self._pytest_capman:
                        self._pytest_capman.suspend_global_capture(in_=True)
                return ret

            def get_stack(self, f, t):
                stack, i = super().get_stack(f, t)
                if f is None:
                    # Find last non-hidden frame.
                    i = max(0, len(stack) - 1)
                    while i and stack[i][0].f_locals.get("__tracebackhide__", False):
                        i -= 1
                return stack, i

        return PytestPdbWrapper

    def _init_pdb(self, method, *args, **kwargs):
        """ Initialize PDB debugging, dropping any IO capturing. """
        import _pytest.config

        capman = self.config.pluginmanager.getplugin("capturemanager")
        if capman:
            capman.suspend(in_=True)

        tw = _pytest.config.create_terminal_writer(self.config)
        tw.line()

        if self._recursive_debug == 0:
            # Handle header similar to pdb.set_trace in py37+.
            header = kwargs.pop("header", None)
            if header is not None:
                tw.sep(">", header)
            else:
                capturing = self._is_capturing(capman)
                if capturing == "global":
                    tw.sep(">", "PDB {} (IO-capturing turned off)".format(method))
                elif capturing:
                    tw.sep(
                        ">",
                        "PDB %s (IO-capturing turned off for %s)" % (method, capturing),
                    )
                else:
                    tw.sep(">", "PDB {}".format(method))

        _pdb = self._import_pdb_cls()(**kwargs)

        self.config.pluginmanager.hook.pytest_enter_pdb(config=self.config, pdb=_pdb)
        return _pdb

    def post_mortem(self, t):
        p = self._init_pdb("post_mortem")
        p.reset()
        p.interaction(None, t)
        if getattr(p, "quitting", False):
            outcomes.exit("Quitting debugger")


class pytestPDB(PdbBase):
    def pytest_configure(self, config):
        import pdb

        self._recursive_debug = 0
        self._wrapped_pdb_cls = None
        self._saved_pdb_set_trace = (pdb, pdb.set_trace)
        pdb.set_trace = functools.partial(self.set_trace, self)

    def pytest_unconfigure(self, config):
        pdb, set_trace = self._saved_pdb_set_trace
        pdb.set_trace = set_trace  # type: ignore

    def set_trace(self, *args, **kwargs):
        """Invoke debugging via ``Pdb.set_trace``, dropping any IO capturing."""
        frame = sys._getframe().f_back
        _pdb = self._init_pdb("set_trace", *args, **kwargs)
        _pdb.set_trace(frame)


def set_trace(*, header=None):
    """Placeholder for when there is no config (yet)."""
    import pdb
    import sys

    pdb_ = pdb.Pdb()
    if header is not None:
        pdb_.message(header)  # type: ignore
    pdb_.set_trace(sys._getframe().f_back)


class PdbInvoke(PdbBase):
    def pytest_exception_interact(self, node, call, report):
        capman = node.config.pluginmanager.getplugin("capturemanager")
        if capman:
            capman.suspend_global_capture(in_=True)
            out, err = capman.read_global_capture()
            sys.stdout.write(out)
            sys.stdout.write(err)

        # XXX we re-use the TerminalReporter's terminalwriter
        # because this seems to avoid some encoding related troubles
        # for not completely clear reasons.
        tw = node.config.pluginmanager.getplugin("terminalreporter")._tw
        tw.line()

        showcapture = node.config.option.showcapture

        for sectionname, content in (
            ("stdout", report.capstdout),
            ("stderr", report.capstderr),
            ("log", report.caplog),
        ):
            if showcapture in (sectionname, "all") and content:
                tw.sep(">", "captured " + sectionname)
                if content[-1:] == "\n":
                    content = content[:-1]
                tw.line(content)

        tw.sep("!", "traceback for {}".format(call.excinfo.typename))
        report.toterminal(tw)
        tw.sep(">", "entering PDB")
        tb = _postmortem_traceback(call.excinfo)
        report._pdbshown = True
        self.post_mortem(tb)
        return report

    def pytest_internalerror(self, excrepr, excinfo):
        tb = _postmortem_traceback(excinfo)
        self.post_mortem(tb)


class PdbTrace(pytestPDB):
    @hookimpl(hookwrapper=True)
    def pytest_pyfunc_call(self, pyfuncitem):
        self._test_pytest_function(pyfuncitem)
        yield

    def _test_pytest_function(self, pyfuncitem):
        _pdb = self._init_pdb("runcall")
        testfunction = pyfuncitem.obj

        # we can't just return `partial(pdb.runcall, testfunction)` because (on
        # python < 3.7.4) runcall's first param is `func`, which means we'd get
        # an exception if one of the kwargs to testfunction was called `func`
        @functools.wraps(testfunction)
        def wrapper(*args, **kwargs):
            func = functools.partial(testfunction, *args, **kwargs)
            _pdb.runcall(func)

        pyfuncitem.obj = wrapper


def _postmortem_traceback(excinfo):
    from doctest import UnexpectedException

    # Save original exception, to be used with e.g. pdb.pm().
    sys.last_type, sys.last_value, sys.last_traceback = excinfo._excinfo

    if isinstance(excinfo.value, UnexpectedException):
        # A doctest.UnexpectedException is not useful for post_mortem.
        # Use the underlying exception instead:
        return excinfo.value.exc_info[2]
    else:
        tb = excinfo._excinfo[2]
        while tb:
            if tb is excinfo.traceback[0]._rawentry:
                break
            tb = tb.tb_next
        assert tb
        return tb
