""" recording warnings during test function execution. """
import re
import warnings
from types import TracebackType
from typing import Any
from typing import Callable
from typing import Iterator
from typing import List
from typing import Optional
from typing import Pattern
from typing import Tuple
from typing import Union

from _pytest.compat import overload
from _pytest.compat import TYPE_CHECKING
from _pytest.fixtures import yield_fixture
from _pytest.outcomes import fail

if TYPE_CHECKING:
    from typing import Type


@yield_fixture
def recwarn():
    """Return a :class:`WarningsRecorder` instance that records all warnings emitted by test functions.

    See http://docs.python.org/library/warnings.html for information
    on warning categories.
    """
    wrec = WarningsRecorder()
    with wrec:
        warnings.simplefilter("default")
        yield wrec


def deprecated_call(func=None, *args, **kwargs):
    """context manager that can be used to ensure a block of code triggers a
    ``DeprecationWarning`` or ``PendingDeprecationWarning``::

        >>> import warnings
        >>> def api_call_v2():
        ...     warnings.warn('use v3 of this api', DeprecationWarning)
        ...     return 200

        >>> with deprecated_call():
        ...    assert api_call_v2() == 200

    ``deprecated_call`` can also be used by passing a function and ``*args`` and ``*kwargs``,
    in which case it will ensure calling ``func(*args, **kwargs)`` produces one of the warnings
    types above.
    """
    __tracebackhide__ = True
    if func is not None:
        args = (func,) + args
    return warns((DeprecationWarning, PendingDeprecationWarning), *args, **kwargs)


@overload
def warns(
    expected_warning: Optional[Union["Type[Warning]", Tuple["Type[Warning]", ...]]],
    *,
    match: "Optional[Union[str, Pattern]]" = ...
) -> "WarningsChecker":
    raise NotImplementedError()


@overload  # noqa: F811
def warns(  # noqa: F811
    expected_warning: Optional[Union["Type[Warning]", Tuple["Type[Warning]", ...]]],
    func: Callable,
    *args: Any,
    match: Optional[Union[str, "Pattern"]] = ...,
    **kwargs: Any
) -> Union[Any]:
    raise NotImplementedError()


def warns(  # noqa: F811
    expected_warning: Optional[Union["Type[Warning]", Tuple["Type[Warning]", ...]]],
    *args: Any,
    match: Optional[Union[str, "Pattern"]] = None,
    **kwargs: Any
) -> Union["WarningsChecker", Any]:
    r"""Assert that code raises a particular class of warning.

    ``expected_warning`` can be a warning class or sequence of warning classes,
    which are expected to be issued inside of the ``with`` block.

    This helper produces a list of :class:`warnings.WarningMessage` objects,
    one for each warning raised.

    This function can be used as a context manager, or any of the other ways
    ``pytest.raises`` can be used::

        >>> with warns(RuntimeWarning):
        ...    warnings.warn("my warning", RuntimeWarning)

    In the context manager form the keyword argument ``match`` can be used to
    assert that the warning message matches the given regular expression
    (using :func:`python:re.search`)::

        >>> with warns(UserWarning, match='must be 0 or None'):
        ...     warnings.warn("value must be 0 or None", UserWarning)

        >>> with warns(UserWarning, match=r'must be \d+$'):
        ...     warnings.warn("value must be 42", UserWarning)

        >>> with warns(UserWarning, match=r'must be \d+$'):
        ...     warnings.warn("this is not here", UserWarning)
        Traceback (most recent call last):
          ...
        _pytest.outcomes.Failed: DID NOT WARN. No warning of type ...UserWarning... was emitted...
    """
    __tracebackhide__ = True
    if not args:
        if kwargs:
            raise TypeError(
                "Unexpected keyword arguments passed to pytest.warns: {}."
                "  Did you mean to use the non-contextmanager form instead?".format(
                    ", ".join(kwargs)
                )
            )
        return WarningsChecker(expected_warning, match_expr=match)

    func = args[0]
    if not callable(func):
        raise TypeError(
            "{!r} object (type: {}) must be callable".format(func, type(func))
        )
    with WarningsChecker(expected_warning):
        return func(*args[1:], **kwargs)


class WarningsRecorder(warnings.catch_warnings):
    """A context manager to record raised warnings.

    Adapted from `warnings.catch_warnings`.
    """

    def __init__(self):
        super().__init__(record=True)
        self._entered = False
        self._list = []  # type: List[warnings.WarningMessage]

    def __repr__(self):
        return "<{} len(_list)={}>".format(self.__class__.__name__, len(self._list))

    @property
    def list(self) -> List["warnings.WarningMessage"]:
        """The list of recorded warnings."""
        return self._list

    def __getitem__(self, i: int) -> "warnings.WarningMessage":
        """Get a recorded warning by index."""
        return self._list[i]

    def __iter__(self) -> Iterator["warnings.WarningMessage"]:
        """Iterate through the recorded warnings."""
        return iter(self._list)

    def __len__(self) -> int:
        """The number of recorded warnings."""
        return len(self._list)

    def pop(self, cls: "Type[Warning]" = Warning) -> "warnings.WarningMessage":
        """Pop the first recorded warning, raise exception if not exists."""
        for i, w in enumerate(self._list):
            if issubclass(w.category, cls):
                return self._list.pop(i)
        __tracebackhide__ = True
        raise AssertionError("%r not found in warning list" % cls)

    def clear(self) -> None:
        """Clear the list of recorded warnings."""
        self._list[:] = []

    # Type ignored because it doesn't exactly warnings.catch_warnings.__enter__
    # -- it returns a List but we only emulate one.
    def __enter__(self) -> "WarningsRecorder":  # type: ignore
        if self._entered:
            __tracebackhide__ = True
            raise RuntimeError("Cannot enter %r twice" % self)
        _list = super().__enter__()
        # record=True means it's None.
        assert _list is not None
        self._list = _list
        warnings.simplefilter("always")
        return self

    def __exit__(
        self,
        exc_type: Optional["Type[BaseException]"],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if not self._entered:
            __tracebackhide__ = True
            raise RuntimeError("Cannot exit %r without entering first" % self)

        super().__exit__(exc_type, exc_val, exc_tb)

        # Built-in catch_warnings does not reset entered state so we do it
        # manually here for this context manager to become reusable.
        self._entered = False


class WarningsChecker(WarningsRecorder):
    def __init__(
        self,
        expected_warning: Optional[
            Union["Type[Warning]", Tuple["Type[Warning]", ...]]
        ] = None,
        match_expr: Optional[Union[str, "Pattern"]] = None,
    ) -> None:
        super().__init__()

        msg = "exceptions must be derived from Warning, not %s"
        if expected_warning is None:
            expected_warning_tup = None
        elif isinstance(expected_warning, tuple):
            for exc in expected_warning:
                if not issubclass(exc, Warning):
                    raise TypeError(msg % type(exc))
            expected_warning_tup = expected_warning
        elif issubclass(expected_warning, Warning):
            expected_warning_tup = (expected_warning,)
        else:
            raise TypeError(msg % type(expected_warning))

        self.expected_warning = expected_warning_tup
        self.match_expr = match_expr

    def __exit__(
        self,
        exc_type: Optional["Type[BaseException]"],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        super().__exit__(exc_type, exc_val, exc_tb)

        __tracebackhide__ = True

        if self.expected_warning is None:
            return
        if exc_type is not None:
            # Only check if we're not currently handling an exception.
            return

        if not any(issubclass(r.category, self.expected_warning) for r in self):
            fail(
                "DID NOT WARN. No warning of type {} was emitted. "
                "The list of emitted warnings is: {}.".format(
                    self.expected_warning, [each.message for each in self]
                )
            )
        elif self.match_expr is not None:
            match_pat = re.compile(self.match_expr)
            for r in self:
                if issubclass(r.category, self.expected_warning):
                    if match_pat.search(str(r.message)):
                        break
            else:
                fail(
                    "DID NOT WARN. No warning of type {} matching"
                    " the regex pattern {!r} was emitted."
                    " The list of emitted warnings is: {}.".format(
                        self.expected_warning,
                        match_pat.pattern,
                        [each.message for each in self],
                    )
                )
