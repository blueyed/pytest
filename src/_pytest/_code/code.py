import inspect
import re
import sys
import traceback
from inspect import CO_VARARGS
from inspect import CO_VARKEYWORDS
from io import StringIO
from traceback import format_exception_only
from types import CodeType
from types import FrameType
from types import TracebackType
from typing import Any
from typing import Callable
from typing import Dict
from typing import Generic
from typing import Iterable
from typing import List
from typing import Optional
from typing import Pattern
from typing import Sequence
from typing import Set
from typing import Tuple
from typing import TypeVar
from typing import Union
from weakref import ref

import attr
import pluggy
import py.path

import _pytest
from _pytest._io import TerminalWriter
from _pytest._io.saferepr import safeformat
from _pytest._io.saferepr import saferepr
from _pytest.compat import overload
from _pytest.compat import TYPE_CHECKING
from _pytest.outcomes import OutcomeException

if TYPE_CHECKING:
    from typing import Type
    from typing_extensions import Literal
    from weakref import ReferenceType  # noqa: F401

    from _pytest._code import Source

    _TracebackStyle = Literal["long", "short", "line", "no", "native"]


class Code:
    """ wrapper around Python code objects """

    def __init__(self, rawcode) -> None:
        if not hasattr(rawcode, "co_filename"):
            rawcode = getrawcode(rawcode)
        if not isinstance(rawcode, CodeType):
            raise TypeError("not a code object: {!r}".format(rawcode))
        self.filename = rawcode.co_filename
        self.firstlineno = rawcode.co_firstlineno - 1
        self.name = rawcode.co_name
        self.raw = rawcode

    def __eq__(self, other):
        return self.raw == other.raw

    # Ignore type because of https://github.com/python/mypy/issues/4266.
    __hash__ = None  # type: ignore

    def __ne__(self, other):
        return not self == other

    @property
    def path(self) -> Union[py.path.local, str]:
        """ return a path object pointing to source code (or a str in case
        of OSError / non-existing file).
        """
        if not self.raw.co_filename:
            return ""
        try:
            p = py.path.local(self.raw.co_filename)
            # maybe don't try this checking
            if not p.check():
                raise OSError("py.path check failed.")
            return p
        except OSError:
            # XXX maybe try harder like the weird logic
            # in the standard lib [linecache.updatecache] does?
            return self.raw.co_filename

    @property
    def fullsource(self) -> Optional["Source"]:
        """ return a _pytest._code.Source object for the full source file of the code
        """
        from _pytest._code import source

        full, _ = source.findsource(self.raw)
        return full

    def source(self) -> "Source":
        """ return a _pytest._code.Source object for the code object's source only
        """
        # return source only for that part of code
        import _pytest._code

        return _pytest._code.Source(self.raw)

    def getargs(self, var: bool = False) -> Tuple[str, ...]:
        """ return a tuple with the argument names for the code object

            if 'var' is set True also return the names of the variable and
            keyword arguments when present
        """
        # handfull shortcut for getting args
        raw = self.raw
        argcount = raw.co_argcount
        if var:
            argcount += raw.co_flags & CO_VARARGS
            argcount += raw.co_flags & CO_VARKEYWORDS
        return raw.co_varnames[:argcount]


class Frame:
    """Wrapper around a Python frame holding f_locals and f_globals
    in which expressions can be evaluated."""

    def __init__(self, frame: FrameType) -> None:
        self.lineno = frame.f_lineno - 1
        self.f_globals = frame.f_globals
        self.f_locals = frame.f_locals
        self.raw = frame
        self.code = Code(frame.f_code)

    @property
    def statement(self) -> "Source":
        """ statement this frame is at """
        import _pytest._code

        if self.code.fullsource is None:
            return _pytest._code.Source("")
        return self.code.fullsource.getstatement(self.lineno)

    def eval(self, code, **vars):
        """ evaluate 'code' in the frame

            'vars' are optional additional local variables

            returns the result of the evaluation
        """
        f_locals = self.f_locals.copy()
        f_locals.update(vars)
        return eval(code, self.f_globals, f_locals)

    def exec_(self, code, **vars) -> None:
        """ exec 'code' in the frame

            'vars' are optional; additional local variables
        """
        f_locals = self.f_locals.copy()
        f_locals.update(vars)
        exec(code, self.f_globals, f_locals)

    def repr(self, object: object) -> str:
        """ return a 'safe' (non-recursive, one-line) string repr for 'object'
        """
        return saferepr(object)

    def is_true(self, object):
        return object

    def getargs(self, var: bool = False):
        """ return a list of tuples (name, value) for all arguments

            if 'var' is set True also include the variable and keyword
            arguments when present
        """
        retval = []
        for arg in self.code.getargs(var):
            try:
                retval.append((arg, self.f_locals[arg]))
            except KeyError:
                pass  # this can occur when using Psyco
        return retval


class TracebackEntry:
    """ a single entry in a traceback """

    _repr_style = None  # type: Optional[Literal["short", "long"]]
    exprinfo = None

    def __init__(self, rawentry: TracebackType, excinfo=None) -> None:
        self._excinfo = excinfo
        self._rawentry = rawentry
        self.lineno = rawentry.tb_lineno - 1

    def set_repr_style(self, mode: "Literal['short', 'long']") -> None:
        assert mode in ("short", "long")
        self._repr_style = mode

    @property
    def frame(self) -> Frame:
        return Frame(self._rawentry.tb_frame)

    @property
    def relline(self) -> int:
        return self.lineno - self.frame.code.firstlineno

    def __repr__(self) -> str:
        return "<TracebackEntry %s:%d>" % (self.frame.code.path, self.lineno + 1)

    @property
    def statement(self) -> "Source":
        """ _pytest._code.Source object for the current statement """
        source = self.frame.code.fullsource
        if source is None:
            raise AttributeError
        return source.getstatement(self.lineno)

    @property
    def path(self) -> Union[py.path.local, str]:
        """ path to the source code """
        return self.frame.code.path

    @property
    def locals(self) -> Dict[str, Any]:
        """ locals of underlying frame """
        return self.frame.f_locals

    def getfirstlinesource(self) -> int:
        return self.frame.code.firstlineno

    def getsource(self, astcache=None) -> Optional["Source"]:
        """ return failing source code. """
        # we use the passed in astcache to not reparse asttrees
        # within exception info printing
        from _pytest._code.source import getstatementrange_ast

        source = self.frame.code.fullsource
        if source is None:
            return None
        key = astnode = None
        if astcache is not None:
            key = self.frame.code.path
            if key is not None:
                astnode = astcache.get(key, None)
        start = self.getfirstlinesource()
        try:
            astnode, _, end = getstatementrange_ast(
                self.lineno, source, astnode=astnode
            )
        except SyntaxError:
            end = self.lineno + 1
        else:
            if key is not None:
                astcache[key] = astnode
        return source[start:end]

    source = property(getsource)

    def ishidden(self):
        """ return True if the current frame has a var __tracebackhide__
            resolving to True.

            If __tracebackhide__ is a callable, it gets called with the
            ExceptionInfo instance and can decide whether to hide the traceback.

            mostly for internal use
        """
        f = self.frame
        tbh = f.f_locals.get(
            "__tracebackhide__", f.f_globals.get("__tracebackhide__", False)
        )
        if tbh and callable(tbh):
            return tbh(None if self._excinfo is None else self._excinfo())
        return tbh

    def __str__(self) -> str:
        try:
            fn = str(self.path)
        except py.error.Error:
            fn = "???"
        name = self.frame.code.name
        try:
            code = str(self.statement)
        except AttributeError:
            lines = "    ???"
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            lines = "    ??? ({!r})".format(exc)
        else:
            if "\n" in code:
                import textwrap

                lines = "\n".join(
                    "    " + line for line in textwrap.dedent(code).splitlines()
                )
            else:
                lines = "    " + code.lstrip()
        return '  File "{}", line {}, in {}\n{}'.format(
            fn, self.lineno + 1, name, lines
        )

    @property
    def name(self) -> str:
        """ co_name of underlying code """
        return self.frame.code.raw.co_name


class Traceback(List[TracebackEntry]):
    """ Traceback objects encapsulate and offer higher level
        access to Traceback entries.
    """

    def __init__(
        self,
        tb: Union[TracebackType, Iterable[TracebackEntry]],
        excinfo: Optional["ReferenceType[ExceptionInfo]"] = None,
    ) -> None:
        """ initialize from given python traceback object and ExceptionInfo """
        self._excinfo = excinfo
        if isinstance(tb, TracebackType):

            def f(cur: TracebackType) -> Iterable[TracebackEntry]:
                cur_ = cur  # type: Optional[TracebackType]
                while cur_ is not None:
                    yield TracebackEntry(cur_, excinfo=excinfo)
                    cur_ = cur_.tb_next

            super().__init__(f(tb))
        else:
            super().__init__(tb)

    def cut(
        self,
        path=None,
        lineno: Optional[int] = None,
        firstlineno: Optional[int] = None,
        excludepath=None,
    ) -> "Traceback":
        """ return a Traceback instance wrapping part of this Traceback

            by providing any combination of path, lineno and firstlineno, the
            first frame to start the to-be-returned traceback is determined

            this allows cutting the first part of a Traceback instance e.g.
            for formatting reasons (removing some uninteresting bits that deal
            with handling of the exception/traceback)
        """
        for x in self:
            code = x.frame.code
            codepath = code.path
            if (
                (path is None or codepath == path)
                and (
                    excludepath is None
                    or not isinstance(codepath, py.path.local)
                    or not codepath.relto(excludepath)
                )
                and (lineno is None or x.lineno == lineno)
                and (firstlineno is None or x.frame.code.firstlineno == firstlineno)
            ):
                return Traceback(x._rawentry, self._excinfo)
        return self

    @overload
    def __getitem__(self, key: int) -> TracebackEntry:
        raise NotImplementedError()

    @overload  # noqa: F811
    def __getitem__(self, key: slice) -> "Traceback":  # noqa: F811
        raise NotImplementedError()

    def __getitem__(  # noqa: F811
        self, key: Union[int, slice]
    ) -> Union[TracebackEntry, "Traceback"]:
        if isinstance(key, slice):
            return self.__class__(super().__getitem__(key))
        else:
            return super().__getitem__(key)

    def filter(
        self, fn: Callable[[TracebackEntry], bool] = lambda x: not x.ishidden()
    ) -> "Traceback":
        """ return a Traceback instance with certain items removed

            fn is a function that gets a single argument, a TracebackEntry
            instance, and should return True when the item should be added
            to the Traceback, False when not

            by default this removes all the TracebackEntries which are hidden
            (see ishidden() above)
        """
        return Traceback(filter(fn, self), self._excinfo)

    def getcrashentry(self) -> TracebackEntry:
        """ return last non-hidden traceback entry that lead
        to the exception of a traceback.
        """
        for i in range(-1, -len(self) - 1, -1):
            entry = self[i]
            if not entry.ishidden():
                return entry
        return self[-1]

    def recursionindex(self) -> Optional[int]:
        """ return the index of the frame/TracebackEntry where recursion
            originates if appropriate, None if no recursion occurred
        """
        cache = {}  # type: Dict[Tuple[Any, int, int], List[Dict[str, Any]]]
        for i, entry in enumerate(self):
            # id for the code.raw is needed to work around
            # the strange metaprogramming in the decorator lib from pypi
            # which generates code objects that have hash/value equality
            # XXX needs a test
            key = entry.frame.code.path, id(entry.frame.code.raw), entry.lineno
            # print "checking for recursion at", key
            values = cache.setdefault(key, [])
            if values:
                f = entry.frame
                loc = f.f_locals
                for otherloc in values:
                    if f.is_true(
                        f.eval(
                            co_equal,
                            __recursioncache_locals_1=loc,
                            __recursioncache_locals_2=otherloc,
                        )
                    ):
                        return i
            values.append(entry.frame.f_locals)
        return None

    def __str__(self):
        return "\n".join(str(x) for x in self)


co_equal = compile(
    "__recursioncache_locals_1 == __recursioncache_locals_2", "?", "eval"
)


_E = TypeVar("_E", bound=BaseException)


@attr.s(repr=False)
class ExceptionInfo(Generic[_E]):
    """ wraps sys.exc_info() objects and offers
        help for navigating the traceback.
    """

    _assert_start_repr = "AssertionError('assert "

    _excinfo = attr.ib(type=Optional[Tuple["Type[_E]", "_E", TracebackType]])
    _striptext = attr.ib(type=str, default="")
    _traceback = attr.ib(type=Optional[Traceback], default=None)

    @classmethod
    def from_exc_info(
        cls,
        exc_info: Tuple["Type[_E]", "_E", TracebackType],
        exprinfo: Optional[str] = None,
    ) -> "ExceptionInfo[_E]":
        """returns an ExceptionInfo for an existing exc_info tuple.

        .. warning::

            Experimental API


        :param exprinfo: a text string helping to determine if we should
                         strip ``AssertionError`` from the output, defaults
                         to the exception message/``__str__()``
        """
        _striptext = ""
        if exprinfo is None and isinstance(exc_info[1], AssertionError):
            exprinfo = getattr(exc_info[1], "msg", None)
            if exprinfo is None:
                exprinfo = saferepr(exc_info[1])
            if exprinfo and exprinfo.startswith(cls._assert_start_repr):
                _striptext = "AssertionError: "

        return cls(exc_info, _striptext)

    @classmethod
    def from_current(
        cls, exprinfo: Optional[str] = None
    ) -> "ExceptionInfo[BaseException]":
        """returns an ExceptionInfo matching the current traceback

        .. warning::

            Experimental API


        :param exprinfo: a text string helping to determine if we should
                         strip ``AssertionError`` from the output, defaults
                         to the exception message/``__str__()``
        """
        tup = sys.exc_info()
        assert tup[0] is not None, "no current exception"
        assert tup[1] is not None, "no current exception"
        assert tup[2] is not None, "no current exception"
        exc_info = (tup[0], tup[1], tup[2])
        return ExceptionInfo.from_exc_info(exc_info, exprinfo)

    @classmethod
    def for_later(cls) -> "ExceptionInfo[_E]":
        """return an unfilled ExceptionInfo
        """
        return cls(None)

    def fill_unfilled(self, exc_info: Tuple["Type[_E]", _E, TracebackType]) -> None:
        """fill an unfilled ExceptionInfo created with for_later()"""
        assert self._excinfo is None, "ExceptionInfo was already filled"
        self._excinfo = exc_info

    @property
    def type(self) -> "Type[_E]":
        """the exception class"""
        assert (
            self._excinfo is not None
        ), ".type can only be used after the context manager exits"
        return self._excinfo[0]

    @property
    def value(self) -> _E:
        """the exception value"""
        assert (
            self._excinfo is not None
        ), ".value can only be used after the context manager exits"
        return self._excinfo[1]

    @property
    def tb(self) -> TracebackType:
        """the exception raw traceback"""
        assert (
            self._excinfo is not None
        ), ".tb can only be used after the context manager exits"
        return self._excinfo[2]

    @property
    def typename(self) -> str:
        """the type name of the exception"""
        assert (
            self._excinfo is not None
        ), ".typename can only be used after the context manager exits"
        return self.type.__name__

    @property
    def traceback(self) -> Traceback:
        """the traceback"""
        if self._traceback is None:
            self._traceback = Traceback(self.tb, excinfo=ref(self))
        return self._traceback

    @traceback.setter
    def traceback(self, value: Traceback) -> None:
        self._traceback = value

    def __repr__(self) -> str:
        if self._excinfo is None:
            return "<ExceptionInfo for raises contextmanager>"
        return "<{} {} tblen={}>".format(
            self.__class__.__name__, saferepr(self._excinfo[1]), len(self.traceback)
        )

    def exconly(self, tryshort: bool = False) -> str:
        """ return the exception as a string

            when 'tryshort' resolves to True, and the exception is a
            _pytest._code._AssertionError, only the actual exception part of
            the exception representation is returned (so 'AssertionError: ' is
            removed from the beginning)
        """
        lines = format_exception_only(self.type, self.value)
        if isinstance(self.value, OutcomeException):
            # Remove module prefix.
            assert lines[0].startswith(self.type.__module__), (lines[0], self.type)
            lines[0] = lines[0][len(self.type.__module__) + 1 :]
        text = "".join(lines)
        text = text.rstrip()
        if tryshort:
            if text.startswith(self._striptext):
                text = text[len(self._striptext) :]
        return text

    def errisinstance(
        self, exc: Union["Type[BaseException]", Tuple["Type[BaseException]", ...]]
    ) -> bool:
        """ return True if the exception is an instance of exc """
        return isinstance(self.value, exc)

    def _getreprcrash(self) -> "ReprFileLocation":
        exconly = self.exconly(tryshort=True)
        entry = self.traceback.getcrashentry()
        path, lineno = entry.frame.code.raw.co_filename, entry.lineno
        return ReprFileLocation(path, lineno + 1, exconly)

    def getrepr(
        self,
        showlocals: bool = False,
        style: "_TracebackStyle" = "long",
        abspath: bool = False,
        tbfilter: bool = True,
        funcargs: bool = False,
        truncate_locals: bool = True,
        chain: bool = True,
    ) -> Union["ReprExceptionInfo", "ExceptionChainRepr"]:
        """
        Return str()able representation of this exception info.

        :param bool showlocals:
            Show locals per traceback entry.
            Ignored if ``style=="native"``.

        :param str style: long|short|no|native traceback style

        :param bool abspath:
            If paths should be changed to absolute or left unchanged.

        :param bool tbfilter:
            Hide entries that contain a local variable ``__tracebackhide__==True``.
            Ignored if ``style=="native"``.

        :param bool funcargs:
            Show fixtures ("funcargs" for legacy purposes) per traceback entry.

        :param bool truncate_locals:
            With ``showlocals==True``, make sure locals can be safely represented as strings.

        :param bool chain: if chained exceptions in Python 3 should be shown.

        .. versionchanged:: 3.9

            Added the ``chain`` parameter.
        """
        if style == "native":
            return ReprExceptionInfo(
                ReprTracebackNative(
                    traceback.format_exception(
                        self.type, self.value, self.traceback[0]._rawentry
                    )
                ),
                self._getreprcrash(),
            )

        fmt = FormattedExcinfo(
            showlocals=showlocals,
            style=style,
            abspath=abspath,
            tbfilter=tbfilter,
            funcargs=funcargs,
            truncate_locals=truncate_locals,
            chain=chain,
        )
        return fmt.repr_excinfo(self)

    def match(self, regexp: "Union[str, Pattern]") -> "Literal[True]":
        """
        Check whether the regular expression `regexp` matches the string
        representation of the exception using :func:`python:re.search`.
        If it matches `True` is returned.
        If it doesn't match an `AssertionError` is raised.
        """
        __tracebackhide__ = True
        str_val = str(self.value)
        if re.search(regexp, str_val):
            # Return True to allow for "assert excinfo.match()".
            return True
        raise AssertionError(
            "Regex pattern {!r} does not match {!r}.{}".format(
                regexp,
                str_val,
                " Did you mean to `re.escape()` the regex?"
                if regexp == str_val else "",
            )
        )


@attr.s
class FormattedExcinfo:
    """ presenting information about failing Functions and Generators. """

    # for traceback entries
    flow_marker = ">"
    fail_marker = "E"

    showlocals = attr.ib(type=bool, default=False)
    style = attr.ib(type="_TracebackStyle", default="long")
    abspath = attr.ib(type=bool, default=True)
    tbfilter = attr.ib(type=bool, default=True)
    funcargs = attr.ib(type=bool, default=False)
    truncate_locals = attr.ib(type=bool, default=True)
    chain = attr.ib(type=bool, default=True)
    astcache = attr.ib(default=attr.Factory(dict), init=False, repr=False)

    def _getindent(self, source: "Source") -> int:
        # figure out indent for given source
        try:
            s = str(source.getstatement(len(source) - 1))
        except KeyboardInterrupt:
            raise
        except:  # noqa
            try:
                s = str(source[-1])
            except KeyboardInterrupt:
                raise
            except:  # noqa
                return 0
        return 4 + (len(s) - len(s.lstrip()))

    def _getentrysource(self, entry: TracebackEntry) -> Optional["Source"]:
        source = entry.getsource(self.astcache)
        if source is not None:
            source = source.deindent()
        return source

    def repr_args(self, entry: TracebackEntry) -> Optional["ReprFuncArgs"]:
        if self.funcargs:
            args = []
            for argname, argvalue in entry.frame.getargs(var=True):
                args.append((argname, saferepr(argvalue)))
            return ReprFuncArgs(args)
        return None

    def get_source(
        self,
        source: "Source",
        line_index: int = -1,
        excinfo: Optional[ExceptionInfo] = None,
        short: bool = False,
    ) -> List[str]:
        """ return formatted and marked up source lines. """
        import _pytest._code

        lines = []
        if source is None or line_index >= len(source.lines):
            source = _pytest._code.Source("???")
            line_index = 0
        if line_index < 0:
            line_index += len(source)
        space_prefix = "    "
        if short:
            lines.append(space_prefix + source.lines[line_index].strip())
        else:
            for line in source.lines[:line_index]:
                lines.append(space_prefix + line)
            lines.append(self.flow_marker + "   " + source.lines[line_index])
            for line in source.lines[line_index + 1 :]:
                lines.append(space_prefix + line)
        if excinfo is not None:
            indent = 4 if short else self._getindent(source)
            lines.extend(self.get_exconly(excinfo, indent=indent, markall=True))
        return lines

    def get_exconly(
        self, excinfo: ExceptionInfo, indent: int = 4, markall: bool = False
    ) -> List[str]:
        lines = []
        indentstr = " " * indent
        # get the real exception information out
        exlines = excinfo.exconly(tryshort=True).split("\n")
        failindent = self.fail_marker + indentstr[1:]
        for line in exlines:
            lines.append(failindent + line)
            if not markall:
                failindent = indentstr
        return lines

    def repr_locals(self, locals: Dict[str, object]) -> Optional["ReprLocals"]:
        if self.showlocals:
            lines = []
            keys = [loc for loc in locals if loc[0] != "@"]
            keys.sort()
            for name in keys:
                value = locals[name]
                if name == "__builtins__":
                    lines.append("__builtins__ = <builtins>")
                else:
                    # This formatting could all be handled by the
                    # _repr() function, which is only reprlib.Repr in
                    # disguise, so is very configurable.
                    if self.truncate_locals:
                        str_repr = saferepr(value)
                    else:
                        str_repr = safeformat(value)
                    # if len(str_repr) < 70 or not isinstance(value,
                    #                            (list, tuple, dict)):
                    lines.append("{:<10} = {}".format(name, str_repr))
                    # else:
                    #    self._line("%-10s =\\" % (name,))
                    #    # XXX
                    #    pprint.pprint(value, stream=self.excinfowriter)
            return ReprLocals(lines)
        return None

    def repr_traceback_entry(
        self, entry: TracebackEntry, excinfo: Optional[ExceptionInfo] = None
    ) -> "ReprEntry":
        import _pytest._code

        source = self._getentrysource(entry)
        if source is None:
            source = _pytest._code.Source("???")
            line_index = 0
        else:
            line_index = entry.lineno - entry.getfirstlinesource()

        lines = []  # type: List[str]
        style = entry._repr_style if entry._repr_style is not None else self.style
        if style in ("short", "long"):
            short = style == "short"
            reprargs = self.repr_args(entry) if not short else None
            s = self.get_source(source, line_index, excinfo, short=short)
            lines.extend(s)
            if short:
                message = "in %s" % (entry.name)
            elif excinfo:
                message = excinfo.exconly(tryshort=True)
            else:
                message = ""
            path = self._makepath(entry.path)
            filelocrepr = ReprFileLocation(path, entry.lineno + 1, message)
            localsrepr = self.repr_locals(entry.locals)
            return ReprEntry(lines, reprargs, localsrepr, filelocrepr, style)
        if excinfo:
            lines.extend(self.get_exconly(excinfo, indent=4))
        return ReprEntry(lines, None, None, None, style)

    def _makepath(self, path):
        if not self.abspath:
            try:
                np = py.path.local().bestrelpath(path)
            except OSError:
                return path
            if len(np) < len(str(path)):
                path = np
        return path

    def repr_traceback(self, excinfo: ExceptionInfo) -> "ReprTraceback":
        traceback = excinfo.traceback
        if self.tbfilter:
            traceback = traceback.filter()

        if excinfo.errisinstance(RecursionError):
            traceback, extraline = self._truncate_recursive_traceback(traceback)
        else:
            extraline = None

        last = traceback[-1]
        entries = []
        for index, entry in enumerate(traceback):
            einfo = (last == entry) and excinfo or None
            reprentry = self.repr_traceback_entry(entry, einfo)
            entries.append(reprentry)
        return ReprTraceback(entries, extraline, style=self.style)

    def _truncate_recursive_traceback(
        self, traceback: Traceback
    ) -> Tuple[Traceback, Optional[str]]:
        """
        Truncate the given recursive traceback trying to find the starting point
        of the recursion.

        The detection is done by going through each traceback entry and finding the
        point in which the locals of the frame are equal to the locals of a previous frame (see ``recursionindex()``.

        Handle the situation where the recursion process might raise an exception (for example
        comparing numpy arrays using equality raises a TypeError), in which case we do our best to
        warn the user of the error and show a limited traceback.
        """
        try:
            recursionindex = traceback.recursionindex()
        except Exception as e:
            max_frames = 10
            extraline = (
                "!!! Recursion error detected, but an error occurred locating the origin of recursion.\n"
                "  The following exception happened when comparing locals in the stack frame:\n"
                "    {exc_type}: {exc_msg}\n"
                "  Displaying first and last {max_frames} stack frames out of {total}."
            ).format(
                exc_type=type(e).__name__,
                exc_msg=str(e),
                max_frames=max_frames,
                total=len(traceback),
            )  # type: Optional[str]
            # Type ignored because adding two instaces of a List subtype
            # currently incorrectly has type List instead of the subtype.
            traceback = traceback[:max_frames] + traceback[-max_frames:]  # type: ignore
        else:
            if recursionindex is not None:
                extraline = "!!! Recursion detected (same locals & position)"
                traceback = traceback[: recursionindex + 1]
            else:
                extraline = None

        return traceback, extraline

    def repr_excinfo(self, excinfo: ExceptionInfo) -> "ExceptionChainRepr":
        repr_chain = (
            []
        )  # type: List[Tuple[ReprTraceback, Optional[ReprFileLocation], Optional[str]]]
        e = excinfo.value
        excinfo_ = excinfo  # type: Optional[ExceptionInfo]
        descr = None
        seen = set()  # type: Set[int]
        while e is not None and id(e) not in seen:
            seen.add(id(e))
            if excinfo_:
                reprtraceback = self.repr_traceback(excinfo_)
                reprcrash = excinfo_._getreprcrash()  # type: Optional[ReprFileLocation]
            else:
                # fallback to native repr if the exception doesn't have a traceback:
                # ExceptionInfo objects require a full traceback to work
                reprtraceback = ReprTracebackNative(
                    traceback.format_exception(type(e), e, None)
                )
                reprcrash = None

            repr_chain += [(reprtraceback, reprcrash, descr)]
            if e.__cause__ is not None and self.chain:
                e = e.__cause__
                excinfo_ = (
                    ExceptionInfo((type(e), e, e.__traceback__))
                    if e.__traceback__
                    else None
                )
                descr = "The above exception was the direct cause of the following exception:"
            elif (
                e.__context__ is not None and not e.__suppress_context__ and self.chain
            ):
                e = e.__context__
                excinfo_ = (
                    ExceptionInfo((type(e), e, e.__traceback__))
                    if e.__traceback__
                    else None
                )
                descr = "During handling of the above exception, another exception occurred:"
            else:
                e = None
        repr_chain.reverse()
        return ExceptionChainRepr(repr_chain)


class TerminalRepr:
    def __str__(self) -> str:
        # FYI this is called from pytest-xdist's serialization of exception
        # information.
        io = StringIO()
        tw = TerminalWriter(file=io)
        self.toterminal(tw)
        return io.getvalue().strip()

    def __repr__(self) -> str:
        return "<{} instance at {:0x}>".format(self.__class__, id(self))

    def toterminal(self, tw: TerminalWriter) -> None:
        raise NotImplementedError()


class ExceptionRepr(TerminalRepr):
    def __init__(self) -> None:
        self.sections = []  # type: List[Tuple[str, str, str]]

    def addsection(self, name: str, content: str, sep: str = "-") -> None:
        self.sections.append((name, content, sep))

    def toterminal(self, tw: TerminalWriter) -> None:
        for name, content, sep in self.sections:
            tw.sep(sep, name)
            tw.line(content)


class ExceptionChainRepr(ExceptionRepr):
    def __init__(
        self,
        chain: Sequence[
            Tuple["ReprTraceback", Optional["ReprFileLocation"], Optional[str]]
        ],
    ) -> None:
        super().__init__()
        self.chain = chain
        # reprcrash and reprtraceback of the outermost (the newest) exception
        # in the chain
        self.reprtraceback = chain[-1][0]
        self.reprcrash = chain[-1][1]

    def toterminal(self, tw: TerminalWriter) -> None:
        for element in self.chain:
            element[0].toterminal(tw)
            if element[2] is not None:
                tw.line("")
                tw.line(element[2], yellow=True)
        super().toterminal(tw)


class ReprExceptionInfo(ExceptionRepr):
    def __init__(
        self, reprtraceback: "ReprTraceback", reprcrash: "ReprFileLocation"
    ) -> None:
        super().__init__()
        self.reprtraceback = reprtraceback
        self.reprcrash = reprcrash

    def toterminal(self, tw: TerminalWriter) -> None:
        self.reprtraceback.toterminal(tw)
        super().toterminal(tw)


@attr.s
class ReprTraceback(TerminalRepr):
    reprentries = attr.ib(type=Sequence[Union["ReprEntry", "ReprEntryNative"]])
    extraline = attr.ib(type=Optional[str])
    style = attr.ib(type="_TracebackStyle")

    entrysep = "_ "

    def toterminal(self, tw: TerminalWriter) -> None:
        # the entries might have different styles
        for i, entry in enumerate(self.reprentries):
            if entry.style == "long":
                tw.line("")
            entry.toterminal(tw)
            if i < len(self.reprentries) - 1:
                next_entry = self.reprentries[i + 1]
                if (
                    entry.style == "long"
                    or entry.style == "short"
                    and next_entry.style == "long"
                ):
                    tw.sep(self.entrysep)

        if self.extraline:
            tw.line(self.extraline)


class ReprTracebackNative(ReprTraceback):
    def __init__(self, tblines: Sequence[str]) -> None:
        self.style = "native"
        self.reprentries = [ReprEntryNative(tblines)]
        self.extraline = None


class ReprEntryNative(TerminalRepr):
    style = "native"  # type: _TracebackStyle

    def __init__(self, tblines: Sequence[str]) -> None:
        self.lines = tblines

    def toterminal(self, tw: TerminalWriter) -> None:
        tw.write("".join(self.lines))


class ReprEntry(TerminalRepr):
    def __init__(
        self,
        lines: Sequence[str],
        reprfuncargs: Optional["ReprFuncArgs"],
        reprlocals: Optional["ReprLocals"],
        filelocrepr: Optional["ReprFileLocation"],
        style: "_TracebackStyle",
    ) -> None:
        self.lines = lines
        self.reprfuncargs = reprfuncargs
        self.reprlocals = reprlocals
        self.reprfileloc = filelocrepr
        self.style = style

    @staticmethod
    def _color_error_lines(tw: TerminalWriter, lines: Sequence[str]) -> None:
        bold_before = False
        seen_indent_lines = []  # type: List[str]
        seen_source_lines = []  # type: List[str]
        for line in lines:
            if line.startswith("E   "):
                if seen_source_lines:
                    tw._write_source(seen_source_lines, seen_indent_lines)
                    seen_indent_lines = []
                    seen_source_lines = []

                if bold_before:
                    markup = tw.markup("E   ", bold=True, red=True)
                    markup += tw.markup(line[4:])
                else:
                    markup = tw.markup(line, bold=True, red=True)
                    bold_before = True
                tw.line(markup)
            else:
                bold_before = False
                seen_indent_lines.append(line[:4])
                seen_source_lines.append(line[4:])

        if seen_source_lines:
            tw._write_source(seen_source_lines, seen_indent_lines)
            seen_indent_lines = []
            seen_source_lines = []

    def toterminal(self, tw: TerminalWriter) -> None:
        if self.style == "short":
            assert self.reprfileloc is not None
            self.reprfileloc.toterminal(tw, style="short")
            self._color_error_lines(tw, self.lines)
            if self.reprlocals:
                self.reprlocals.toterminal(tw, indent=" " * 8)
            return

        if self.reprfuncargs:
            self.reprfuncargs.toterminal(tw)
        self._color_error_lines(tw, self.lines)
        if self.reprlocals:
            tw.line("")
            self.reprlocals.toterminal(tw)
        if self.reprfileloc:
            if self.lines:
                tw.line("")
            self.reprfileloc.toterminal(tw)

    def __str__(self) -> str:
        return "{}\n{}\n{}".format(
            "\n".join(self.lines), self.reprlocals, self.reprfileloc
        )


@attr.s
class ReprFileLocation(TerminalRepr):
    path = attr.ib(type=str, converter=str)
    lineno = attr.ib(type="Optional[int]")
    message = attr.ib(type=str)

    def _get_short_msg(self) -> str:
        msg = self.message
        i = msg.find("\n")
        if i != -1:
            if msg[i - 1] == "\r":
                i -= 1
            msg = msg[:i] + "..."
        return msg

    def toterminal(self, tw: TerminalWriter, style: "_TracebackStyle" = None) -> None:
        # filename and lineno output for each entry,
        # using an output format that most editors understand
        bold = style != "short"
        tw.write("%s" % self.path, bold=bold)
        if self.lineno:
            tw.line(":{}: {}".format(self.lineno, self._get_short_msg()))
        else:
            tw.line(": {}".format(self._get_short_msg()))


class ReprLocals(TerminalRepr):
    def __init__(self, lines: Sequence[str]) -> None:
        self.lines = lines

    def toterminal(self, tw: TerminalWriter, indent="") -> None:
        for line in self.lines:
            tw.line(indent + line)


class ReprFuncArgs(TerminalRepr):
    def __init__(self, args: Sequence[Tuple[str, object]]) -> None:
        self.args = args

    def toterminal(self, tw: TerminalWriter) -> None:
        if self.args:
            linesofar = ""
            for name, value in self.args:
                ns = "{} = {}".format(name, value)
                if len(ns) + len(linesofar) + 2 > tw.fullwidth:
                    if linesofar:
                        tw.line(linesofar)
                    linesofar = ns
                else:
                    if linesofar:
                        linesofar += ", " + ns
                    else:
                        linesofar = ns
            if linesofar:
                tw.line(linesofar)
            tw.line("")


def getrawcode(obj, trycall: bool = True):
    """ return code object for given function. """
    try:
        return obj.__code__
    except AttributeError:
        obj = getattr(obj, "f_code", obj)
        obj = getattr(obj, "__code__", obj)
        if trycall and not hasattr(obj, "co_firstlineno"):
            if hasattr(obj, "__call__") and not inspect.isclass(obj):
                x = getrawcode(obj.__call__, trycall=False)
                if hasattr(x, "co_firstlineno"):
                    return x
        return obj


# relative paths that we use to filter traceback entries from appearing to the user;
# see filter_traceback
# note: if we need to add more paths than what we have now we should probably use a list
# for better maintenance

_PLUGGY_DIR = py.path.local(pluggy.__file__.rstrip("oc"))
# pluggy is either a package or a single module depending on the version
if _PLUGGY_DIR.basename == "__init__.py":
    _PLUGGY_DIR = _PLUGGY_DIR.dirpath()
_PYTEST_DIR = py.path.local(_pytest.__file__).dirpath()
_PY_DIR = py.path.local(py.__file__).dirpath()


def filter_traceback(entry: TracebackEntry) -> bool:
    """Return True if a TracebackEntry instance should be removed from tracebacks:
    * dynamically generated code (no code to show up for it);
    * internal traceback from pytest or its internal libraries, py and pluggy.
    """
    # entry.path might sometimes return a str object when the entry
    # points to dynamically generated code
    # see https://bitbucket.org/pytest-dev/py/issues/71
    raw_filename = entry.frame.code.raw.co_filename
    is_generated = "<" in raw_filename and ">" in raw_filename
    if is_generated:
        return False
    # entry.path might point to a non-existing file, in which case it will
    # also return a str object. see #1133
    p = py.path.local(entry.path)
    return (
        not p.relto(_PLUGGY_DIR) and not p.relto(_PYTEST_DIR) and not p.relto(_PY_DIR)
    )
