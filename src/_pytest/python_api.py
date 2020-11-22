import inspect
import math
import pprint
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sized
from decimal import Decimal
from itertools import filterfalse
from numbers import Number
from types import TracebackType
from typing import Any
from typing import Callable
from typing import cast
from typing import Generic
from typing import Optional
from typing import Pattern
from typing import Tuple
from typing import TypeVar
from typing import Union

from more_itertools.more import always_iterable

import _pytest._code
from _pytest.compat import STRING_TYPES
from _pytest.compat import TYPE_CHECKING
from _pytest.outcomes import fail

if TYPE_CHECKING:
    from typing import overload
    from typing import Type  # noqa: F401 (used in type string)


BASE_TYPE = (type, STRING_TYPES)


def _non_numeric_type_error(value, at):
    at_str = " at {}".format(at) if at else ""
    return TypeError(
        "cannot make approximate comparisons to non-numeric values: {!r} {}".format(
            value, at_str
        )
    )


# builtin pytest.approx helper


class ApproxBase:
    """
    Provide shared utilities for making approximate comparisons between numbers
    or sequences of numbers.
    """

    # Tell numpy to use our `__eq__` operator instead of its.
    __array_ufunc__ = None
    __array_priority__ = 100

    def __init__(self, expected, rel=None, abs=None, nan_ok=False):
        __tracebackhide__ = True
        self.expected = expected
        self.abs = abs
        self.rel = rel
        self.nan_ok = nan_ok
        self._check_type()

    def __repr__(self):
        raise NotImplementedError

    def __eq__(self, actual):
        return all(
            a == self._approx_scalar(x) for a, x in self._yield_comparisons(actual)
        )

    # Ignore type because of https://github.com/python/mypy/issues/4266.
    __hash__ = None  # type: ignore

    def __ne__(self, actual):
        return not (actual == self)

    def _approx_scalar(self, x):
        return ApproxScalar(x, rel=self.rel, abs=self.abs, nan_ok=self.nan_ok)

    def _yield_comparisons(self, actual):
        """
        Yield all the pairs of numbers to be compared.  This is used to
        implement the `__eq__` method.
        """
        raise NotImplementedError

    def _check_type(self):
        """
        Raise a TypeError if the expected value is not a valid type.
        """
        # This is only a concern if the expected value is a sequence.  In every
        # other case, the approx() function ensures that the expected value has
        # a numeric type.  For this reason, the default is to do nothing.  The
        # classes that deal with sequences should reimplement this method to
        # raise if there are any non-numeric elements in the sequence.
        pass


def _recursive_list_map(f, x):
    if isinstance(x, list):
        return list(_recursive_list_map(f, xi) for xi in x)
    else:
        return f(x)


class ApproxNumpy(ApproxBase):
    """
    Perform approximate comparisons where the expected value is numpy array.
    """

    def __repr__(self):
        list_scalars = _recursive_list_map(self._approx_scalar, self.expected.tolist())
        return "approx({!r})".format(list_scalars)

    def __eq__(self, actual):
        import numpy as np

        # self.expected is supposed to always be an array here

        if not np.isscalar(actual):
            try:
                actual = np.asarray(actual)
            except:  # noqa
                raise TypeError("cannot compare '{}' to numpy.ndarray".format(actual))

        if not np.isscalar(actual) and actual.shape != self.expected.shape:
            return False

        return ApproxBase.__eq__(self, actual)

    def _yield_comparisons(self, actual):
        import numpy as np

        # `actual` can either be a numpy array or a scalar, it is treated in
        # `__eq__` before being passed to `ApproxBase.__eq__`, which is the
        # only method that calls this one.

        if np.isscalar(actual):
            for i in np.ndindex(self.expected.shape):
                yield actual, self.expected[i].item()
        else:
            for i in np.ndindex(self.expected.shape):
                yield actual[i].item(), self.expected[i].item()


class ApproxMapping(ApproxBase):
    """
    Perform approximate comparisons where the expected value is a mapping with
    numeric values (the keys can be anything).
    """

    def __repr__(self):
        return "approx({!r})".format(
            {k: self._approx_scalar(v) for k, v in self.expected.items()}
        )

    def __eq__(self, actual):
        if set(actual.keys()) != set(self.expected.keys()):
            return False

        return ApproxBase.__eq__(self, actual)

    def _yield_comparisons(self, actual):
        for k in self.expected.keys():
            yield actual[k], self.expected[k]

    def _check_type(self):
        __tracebackhide__ = True
        for key, value in self.expected.items():
            if isinstance(value, type(self.expected)):
                msg = "pytest.approx() does not support nested dictionaries: key={!r} value={!r}\n  full mapping={}"
                raise TypeError(msg.format(key, value, pprint.pformat(self.expected)))
            elif not isinstance(value, Number):
                raise _non_numeric_type_error(self.expected, at="key={!r}".format(key))


class ApproxSequencelike(ApproxBase):
    """
    Perform approximate comparisons where the expected value is a sequence of
    numbers.
    """

    def __repr__(self):
        seq_type = type(self.expected)
        if seq_type not in (tuple, list, set):
            seq_type = list
        return "approx({!r})".format(
            seq_type(self._approx_scalar(x) for x in self.expected)
        )

    def __eq__(self, actual):
        if len(actual) != len(self.expected):
            return False
        return ApproxBase.__eq__(self, actual)

    def _yield_comparisons(self, actual):
        return zip(actual, self.expected)

    def _check_type(self):
        __tracebackhide__ = True
        for index, x in enumerate(self.expected):
            if isinstance(x, type(self.expected)):
                msg = "pytest.approx() does not support nested data structures: {!r} at index {}\n  full sequence: {}"
                raise TypeError(msg.format(x, index, pprint.pformat(self.expected)))
            elif not isinstance(x, Number):
                raise _non_numeric_type_error(
                    self.expected, at="index {}".format(index)
                )


class ApproxScalar(ApproxBase):
    """
    Perform approximate comparisons where the expected value is a single number.
    """

    # Using Real should be better than this Union, but not possible yet:
    # https://github.com/python/typeshed/pull/3108
    DEFAULT_ABSOLUTE_TOLERANCE = 1e-12  # type: Union[float, Decimal]
    DEFAULT_RELATIVE_TOLERANCE = 1e-6  # type: Union[float, Decimal]

    def __repr__(self):
        """
        Return a string communicating both the expected value and the tolerance
        for the comparison being made, e.g. '1.0 ± 1e-6', '(3+4j) ± 5e-6 ∠ ±180°'.
        """

        # Infinities aren't compared using tolerances, so don't show a
        # tolerance. Need to call abs to handle complex numbers, e.g. (inf + 1j)
        if math.isinf(abs(self.expected)):
            return str(self.expected)

        # If a sensible tolerance can't be calculated, self.tolerance will
        # raise a ValueError.  In this case, display '???'.
        try:
            vetted_tolerance = "{:.1e}".format(self.tolerance)
            if isinstance(self.expected, complex) and not math.isinf(self.tolerance):
                vetted_tolerance += " ∠ ±180°"
        except ValueError:
            vetted_tolerance = "???"

        return "{} ± {}".format(self.expected, vetted_tolerance)

    def __eq__(self, actual):
        """
        Return true if the given value is equal to the expected value within
        the pre-specified tolerance.
        """
        if _is_numpy_array(actual):
            # Call ``__eq__()`` manually to prevent infinite-recursion with
            # numpy<1.13.  See #3748.
            return all(self.__eq__(a) for a in actual.flat)

        # Short-circuit exact equality.
        if actual == self.expected:
            return True

        # Allow the user to control whether NaNs are considered equal to each
        # other or not.  The abs() calls are for compatibility with complex
        # numbers.
        if math.isnan(abs(self.expected)):
            return self.nan_ok and math.isnan(abs(actual))

        # Infinity shouldn't be approximately equal to anything but itself, but
        # if there's a relative tolerance, it will be infinite and infinity
        # will seem approximately equal to everything.  The equal-to-itself
        # case would have been short circuited above, so here we can just
        # return false if the expected value is infinite.  The abs() call is
        # for compatibility with complex numbers.
        if math.isinf(abs(self.expected)):
            return False

        # Return true if the two numbers are within the tolerance.
        return abs(self.expected - actual) <= self.tolerance

    # Ignore type because of https://github.com/python/mypy/issues/4266.
    __hash__ = None  # type: ignore

    @property
    def tolerance(self):
        """
        Return the tolerance for the comparison.  This could be either an
        absolute tolerance or a relative tolerance, depending on what the user
        specified or which would be larger.
        """

        def set_default(x, default):
            return x if x is not None else default

        # Figure out what the absolute tolerance should be.  ``self.abs`` is
        # either None or a value specified by the user.
        absolute_tolerance = set_default(self.abs, self.DEFAULT_ABSOLUTE_TOLERANCE)

        if absolute_tolerance < 0:
            raise ValueError(
                "absolute tolerance can't be negative: {}".format(absolute_tolerance)
            )
        if math.isnan(absolute_tolerance):
            raise ValueError("absolute tolerance can't be NaN.")

        # If the user specified an absolute tolerance but not a relative one,
        # just return the absolute tolerance.
        if self.rel is None:
            if self.abs is not None:
                return absolute_tolerance

        # Figure out what the relative tolerance should be.  ``self.rel`` is
        # either None or a value specified by the user.  This is done after
        # we've made sure the user didn't ask for an absolute tolerance only,
        # because we don't want to raise errors about the relative tolerance if
        # we aren't even going to use it.
        relative_tolerance = set_default(
            self.rel, self.DEFAULT_RELATIVE_TOLERANCE
        ) * abs(self.expected)

        if relative_tolerance < 0:
            raise ValueError(
                "relative tolerance can't be negative: {}".format(absolute_tolerance)
            )
        if math.isnan(relative_tolerance):
            raise ValueError("relative tolerance can't be NaN.")

        # Return the larger of the relative and absolute tolerances.
        return max(relative_tolerance, absolute_tolerance)


class ApproxDecimal(ApproxScalar):
    """
    Perform approximate comparisons where the expected value is a decimal.
    """

    DEFAULT_ABSOLUTE_TOLERANCE = Decimal("1e-12")
    DEFAULT_RELATIVE_TOLERANCE = Decimal("1e-6")


def approx(expected, rel=None, abs=None, nan_ok=False):
    """
    Assert that two numbers (or two sets of numbers) are equal to each other
    within some tolerance.

    Due to the `intricacies of floating-point arithmetic`__, numbers that we
    would intuitively expect to be equal are not always so::

        >>> 0.1 + 0.2 == 0.3
        False

    __ https://docs.python.org/3/tutorial/floatingpoint.html

    This problem is commonly encountered when writing tests, e.g. when making
    sure that floating-point values are what you expect them to be.  One way to
    deal with this problem is to assert that two floating-point numbers are
    equal to within some appropriate tolerance::

        >>> abs((0.1 + 0.2) - 0.3) < 1e-6
        True

    However, comparisons like this are tedious to write and difficult to
    understand.  Furthermore, absolute comparisons like the one above are
    usually discouraged because there's no tolerance that works well for all
    situations.  ``1e-6`` is good for numbers around ``1``, but too small for
    very big numbers and too big for very small ones.  It's better to express
    the tolerance as a fraction of the expected value, but relative comparisons
    like that are even more difficult to write correctly and concisely.

    The ``approx`` class performs floating-point comparisons using a syntax
    that's as intuitive as possible::

        >>> from pytest import approx
        >>> 0.1 + 0.2 == approx(0.3)
        True

    The same syntax also works for sequences of numbers::

        >>> (0.1 + 0.2, 0.2 + 0.4) == approx((0.3, 0.6))
        True

    Dictionary *values*::

        >>> {'a': 0.1 + 0.2, 'b': 0.2 + 0.4} == approx({'a': 0.3, 'b': 0.6})
        True

    ``numpy`` arrays::

        >>> import numpy as np                                                          # doctest: +SKIP
        >>> np.array([0.1, 0.2]) + np.array([0.2, 0.4]) == approx(np.array([0.3, 0.6])) # doctest: +SKIP
        True

    And for a ``numpy`` array against a scalar::

        >>> import numpy as np                                         # doctest: +SKIP
        >>> np.array([0.1, 0.2]) + np.array([0.2, 0.1]) == approx(0.3) # doctest: +SKIP
        True

    By default, ``approx`` considers numbers within a relative tolerance of
    ``1e-6`` (i.e. one part in a million) of its expected value to be equal.
    This treatment would lead to surprising results if the expected value was
    ``0.0``, because nothing but ``0.0`` itself is relatively close to ``0.0``.
    To handle this case less surprisingly, ``approx`` also considers numbers
    within an absolute tolerance of ``1e-12`` of its expected value to be
    equal.  Infinity and NaN are special cases.  Infinity is only considered
    equal to itself, regardless of the relative tolerance.  NaN is not
    considered equal to anything by default, but you can make it be equal to
    itself by setting the ``nan_ok`` argument to True.  (This is meant to
    facilitate comparing arrays that use NaN to mean "no data".)

    Both the relative and absolute tolerances can be changed by passing
    arguments to the ``approx`` constructor::

        >>> 1.0001 == approx(1)
        False
        >>> 1.0001 == approx(1, rel=1e-3)
        True
        >>> 1.0001 == approx(1, abs=1e-3)
        True

    If you specify ``abs`` but not ``rel``, the comparison will not consider
    the relative tolerance at all.  In other words, two numbers that are within
    the default relative tolerance of ``1e-6`` will still be considered unequal
    if they exceed the specified absolute tolerance.  If you specify both
    ``abs`` and ``rel``, the numbers will be considered equal if either
    tolerance is met::

        >>> 1 + 1e-8 == approx(1)
        True
        >>> 1 + 1e-8 == approx(1, abs=1e-12)
        False
        >>> 1 + 1e-8 == approx(1, rel=1e-6, abs=1e-12)
        True

    If you're thinking about using ``approx``, then you might want to know how
    it compares to other good ways of comparing floating-point numbers.  All of
    these algorithms are based on relative and absolute tolerances and should
    agree for the most part, but they do have meaningful differences:

    - ``math.isclose(a, b, rel_tol=1e-9, abs_tol=0.0)``:  True if the relative
      tolerance is met w.r.t. either ``a`` or ``b`` or if the absolute
      tolerance is met.  Because the relative tolerance is calculated w.r.t.
      both ``a`` and ``b``, this test is symmetric (i.e.  neither ``a`` nor
      ``b`` is a "reference value").  You have to specify an absolute tolerance
      if you want to compare to ``0.0`` because there is no tolerance by
      default.  Only available in python>=3.5.  `More information...`__

      __ https://docs.python.org/3/library/math.html#math.isclose

    - ``numpy.isclose(a, b, rtol=1e-5, atol=1e-8)``: True if the difference
      between ``a`` and ``b`` is less that the sum of the relative tolerance
      w.r.t. ``b`` and the absolute tolerance.  Because the relative tolerance
      is only calculated w.r.t. ``b``, this test is asymmetric and you can
      think of ``b`` as the reference value.  Support for comparing sequences
      is provided by ``numpy.allclose``.  `More information...`__

      __ http://docs.scipy.org/doc/numpy-1.10.0/reference/generated/numpy.isclose.html

    - ``unittest.TestCase.assertAlmostEqual(a, b)``: True if ``a`` and ``b``
      are within an absolute tolerance of ``1e-7``.  No relative tolerance is
      considered and the absolute tolerance cannot be changed, so this function
      is not appropriate for very large or very small numbers.  Also, it's only
      available in subclasses of ``unittest.TestCase`` and it's ugly because it
      doesn't follow PEP8.  `More information...`__

      __ https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertAlmostEqual

    - ``a == pytest.approx(b, rel=1e-6, abs=1e-12)``: True if the relative
      tolerance is met w.r.t. ``b`` or if the absolute tolerance is met.
      Because the relative tolerance is only calculated w.r.t. ``b``, this test
      is asymmetric and you can think of ``b`` as the reference value.  In the
      special case that you explicitly specify an absolute tolerance but not a
      relative tolerance, only the absolute tolerance is considered.

    .. warning::

       .. versionchanged:: 3.2

       In order to avoid inconsistent behavior, ``TypeError`` is
       raised for ``>``, ``>=``, ``<`` and ``<=`` comparisons.
       The example below illustrates the problem::

           assert approx(0.1) > 0.1 + 1e-10  # calls approx(0.1).__gt__(0.1 + 1e-10)
           assert 0.1 + 1e-10 > approx(0.1)  # calls approx(0.1).__lt__(0.1 + 1e-10)

       In the second example one expects ``approx(0.1).__le__(0.1 + 1e-10)``
       to be called. But instead, ``approx(0.1).__lt__(0.1 + 1e-10)`` is used to
       comparison. This is because the call hierarchy of rich comparisons
       follows a fixed behavior. `More information...`__

       __ https://docs.python.org/3/reference/datamodel.html#object.__ge__
    """

    # Delegate the comparison to a class that knows how to deal with the type
    # of the expected value (e.g. int, float, list, dict, numpy.array, etc).
    #
    # The primary responsibility of these classes is to implement ``__eq__()``
    # and ``__repr__()``.  The former is used to actually check if some
    # "actual" value is equivalent to the given expected value within the
    # allowed tolerance.  The latter is used to show the user the expected
    # value and tolerance, in the case that a test failed.
    #
    # The actual logic for making approximate comparisons can be found in
    # ApproxScalar, which is used to compare individual numbers.  All of the
    # other Approx classes eventually delegate to this class.  The ApproxBase
    # class provides some convenient methods and overloads, but isn't really
    # essential.

    __tracebackhide__ = True

    if isinstance(expected, Decimal):
        cls = ApproxDecimal
    elif isinstance(expected, Number):
        cls = ApproxScalar
    elif isinstance(expected, Mapping):
        cls = ApproxMapping
    elif _is_numpy_array(expected):
        cls = ApproxNumpy
    elif (
        isinstance(expected, Iterable)
        and isinstance(expected, Sized)
        and not isinstance(expected, STRING_TYPES)
    ):
        cls = ApproxSequencelike
    else:
        raise _non_numeric_type_error(expected, at=None)

    return cls(expected, rel, abs, nan_ok)


def _is_numpy_array(obj):
    """
    Return true if the given object is a numpy array.  Make a special effort to
    avoid importing numpy unless it's really necessary.
    """
    import sys

    np = sys.modules.get("numpy")
    if np is not None:
        return isinstance(obj, np.ndarray)
    return False


# builtin pytest.raises helper

_E = TypeVar("_E", bound=BaseException)


if TYPE_CHECKING:
    @overload
    def raises(
        expected_exception: Union["Type[_E]", Tuple["Type[_E]", ...]],
        *,
        match: "Optional[Union[str, Pattern]]" = ...
    ) -> "RaisesContext[_E]":
        ...


    @overload
    def raises(
        expected_exception: Union["Type[_E]", Tuple["Type[_E]", ...]],
        func: Callable,
        *args: Any,
        **kwargs: Any
    ) -> _pytest._code.ExceptionInfo[_E]:
        ...


def raises(
    expected_exception: Union["Type[_E]", Tuple["Type[_E]", ...]],
    *args: Any,
    **kwargs: Any
) -> Union["RaisesContext[_E]", _pytest._code.ExceptionInfo[_E]]:
    r"""
    Assert that a code block/function call raises ``expected_exception``
    or raise a failure exception otherwise.

    :kwparam match: if specified, a string containing a regular expression,
        or a regular expression object, that is tested against the string
        representation of the exception using ``re.search``. To match a literal
        string that may contain `special characters`__, the pattern can
        first be escaped with ``re.escape``.

        (This is only used when ``pytest.raises`` is used as a context manager,
        and passed through to the function otherwise.
        When using ``pytest.raises`` as a function, you can use:
        ``pytest.raises(Exc, func, match="passed on").match("my pattern")``.)

        __ https://docs.python.org/3/library/re.html#regular-expression-syntax

    .. currentmodule:: _pytest._code

    Use ``pytest.raises`` as a context manager, which will capture the exception of the given
    type::

        >>> with raises(ZeroDivisionError):
        ...    1/0

    If the code block does not raise the expected exception (``ZeroDivisionError`` in the example
    above), or no exception at all, the check will fail instead.

    You can also use the keyword argument ``match`` to assert that the
    exception matches a text or regex::

        >>> with raises(ValueError, match='must be 0 or None'):
        ...     raise ValueError("value must be 0 or None")

        >>> with raises(ValueError, match=r'must be \d+$'):
        ...     raise ValueError("value must be 42")

    The context manager produces an :class:`ExceptionInfo` object which can be used to inspect the
    details of the captured exception::

        >>> with raises(ValueError) as exc_info:
        ...     raise ValueError("value must be 42")
        >>> assert exc_info.type is ValueError
        >>> assert exc_info.value.args[0] == "value must be 42"

    .. note::

       When using ``pytest.raises`` as a context manager, it's worthwhile to
       note that normal context manager rules apply and that the exception
       raised *must* be the final line in the scope of the context manager.
       Lines of code after that, within the scope of the context manager will
       not be executed. For example::

           >>> value = 15
           >>> with raises(ValueError) as exc_info:
           ...     if value > 10:
           ...         raise ValueError("value must be <= 10")
           ...     assert exc_info.type is ValueError  # this will not execute

       Instead, the following approach must be taken (note the difference in
       scope)::

           >>> with raises(ValueError) as exc_info:
           ...     if value > 10:
           ...         raise ValueError("value must be <= 10")
           ...
           >>> assert exc_info.type is ValueError

    **Using with** ``pytest.mark.parametrize``

    When using :ref:`pytest.mark.parametrize ref`
    it is possible to parametrize tests such that
    some runs raise an exception and others do not.

    See :ref:`parametrizing_conditional_raising` for an example.

    **Legacy form**

    It is possible to specify a callable by passing a to-be-called lambda::

        >>> raises(ZeroDivisionError, lambda: 1/0)
        <ExceptionInfo ...>

    or you can specify an arbitrary callable with arguments::

        >>> def f(x): return 1/x
        ...
        >>> raises(ZeroDivisionError, f, 0)
        <ExceptionInfo ...>
        >>> raises(ZeroDivisionError, f, x=0)
        <ExceptionInfo ...>

    The form above is fully supported but discouraged for new code because the
    context manager form is regarded as more readable and less error-prone.

    .. note::
        Similar to caught exception objects in Python, explicitly clearing
        local references to returned ``ExceptionInfo`` objects can
        help the Python interpreter speed up its garbage collection.

        Clearing those references breaks a reference cycle
        (``ExceptionInfo`` --> caught exception --> frame stack raising
        the exception --> current frame stack --> local variables -->
        ``ExceptionInfo``) which makes Python keep all objects referenced
        from that cycle (including all local variables in the current
        frame) alive until the next cyclic garbage collection run.
        More detailed information can be found in the official Python
        documentation for :ref:`the try statement <python:try>`.
    """
    __tracebackhide__ = True
    for exc in filterfalse(
        inspect.isclass, always_iterable(expected_exception, BASE_TYPE)
    ):
        msg = "exceptions must be derived from BaseException, not %s"
        raise TypeError(msg % type(exc))

    message = "DID NOT RAISE {}".format(expected_exception)

    if not args:
        match = kwargs.pop("match", None)
        if kwargs:
            msg = "Unexpected keyword arguments passed to pytest.raises: "
            msg += ", ".join(sorted(kwargs))
            msg += "\nUse context-manager form instead?"
            raise TypeError(msg)
        return RaisesContext(expected_exception, message, match)
    else:
        func = args[0]
        if not callable(func):
            raise TypeError(
                "{!r} object (type: {}) must be callable".format(func, type(func))
            )
        try:
            func(*args[1:], **kwargs)
        except expected_exception as e:
            # We just caught the exception - there is a traceback.
            assert e.__traceback__ is not None
            return _pytest._code.ExceptionInfo.from_exc_info(
                (type(e), e, e.__traceback__)
            )
    fail(message)


raises.Exception = fail.Exception  # type: ignore


class RaisesContext(Generic[_E]):
    def __init__(
        self,
        expected_exception: Union["Type[_E]", Tuple["Type[_E]", ...]],
        message: str,
        match_expr: Optional[Union[str, "Pattern"]] = None,
    ) -> None:
        self.expected_exception = expected_exception
        self.message = message
        self.match_expr = match_expr
        self.excinfo = None  # type: Optional[_pytest._code.ExceptionInfo[_E]]

    def __enter__(self) -> _pytest._code.ExceptionInfo[_E]:
        self.excinfo = _pytest._code.ExceptionInfo.for_later()
        return self.excinfo

    def __exit__(
        self,
        exc_type: Optional["Type[BaseException]"],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> bool:
        __tracebackhide__ = True
        if exc_type is None:
            fail(self.message)
        assert self.excinfo is not None
        if not issubclass(exc_type, self.expected_exception):
            return False
        # Cast to narrow the exception type now that it's verified.
        exc_info = cast(
            Tuple["Type[_E]", _E, TracebackType], (exc_type, exc_val, exc_tb)
        )
        self.excinfo.fill_unfilled(exc_info)
        if self.match_expr is not None:
            self.excinfo.match(self.match_expr)
        return True
