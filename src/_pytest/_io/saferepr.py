import pprint
import reprlib
import types
from typing import Any
from typing import Callable
from typing import Tuple


def _try_repr_or_str(obj):
    try:
        return repr(obj)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return '{}("{}")'.format(type(obj).__name__, obj)


def _format_repr_exception(exc: BaseException, obj: Any) -> str:
    try:
        exc_info = _try_repr_or_str(exc)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        exc_info = "unpresentable exception ({})".format(_try_repr_or_str(exc))
    return "<[{} raised in repr()] {} object at 0x{:x}>".format(
        exc_info, obj.__class__.__name__, id(obj)
    )


def _ellipsize(s: str, maxsize: int) -> str:
    if len(s) > maxsize:
        i = max(0, (maxsize - 3) // 2)
        j = max(0, maxsize - 3 - i)
        return s[:i] + "..." + s[len(s) - j :]
    return s


class SafeRepr(reprlib.Repr):
    """subclass of repr.Repr that limits the resulting size of repr()
    and includes information on exceptions raised during the call.
    """

    def __init__(self, maxsize: int) -> None:
        super().__init__()
        self.maxstring = maxsize
        self.maxsize = maxsize

    def repr(self, x: Any) -> str:
        try:
            s = super().repr(x)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            s = _format_repr_exception(exc, x)
        return _ellipsize(s, self.maxsize)

    def repr_instance(self, x: Any, level: int) -> str:
        try:
            s = repr(x)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            s = _format_repr_exception(exc, x)
        return _ellipsize(s, self.maxsize)

    def repr_str(self, x: str, level: int) -> str:
        # Copied from reprlib.Repr to use _consistent_str_repr.
        s = _consistent_str_repr(x[: self.maxstring])
        if len(s) > self.maxstring:
            i = max(0, (self.maxstring - 3) // 2)
            j = max(0, self.maxstring - 3 - i)
            s = _consistent_str_repr(x[:i] + x[len(x) - j :])
            s = s[:i] + "..." + s[len(s) - j :]
        return s


def safeformat(obj: Any) -> str:
    """return a pretty printed string for the given object.
    Failing __repr__ functions of user instances will be represented
    with a short exception info.
    """
    try:
        return _pformat_consistent(obj)
    except Exception as exc:
        return _format_repr_exception(exc, obj)


def saferepr(obj: Any, maxsize: int = 240) -> str:
    """return a size-limited safe repr-string for the given object.
    Failing __repr__ functions of user instances will be represented
    with a short exception info and 'saferepr' generally takes
    care to never raise exceptions itself.  This function is a wrapper
    around the Repr/reprlib functionality of the standard 2.6 lib.
    """
    return SafeRepr(maxsize).repr(obj)


def _consistent_str_repr(obj: object) -> str:
    if isinstance(obj, str):
        return '"' + repr("'" + obj)[2:]
    return repr(obj)


def rebind_globals(func, newglobals):

    newfunc = types.FunctionType(
        func.__code__, newglobals, func.__name__, func.__defaults__, func.__closure__
    )
    newfunc.__annotations__ = func.__annotations__
    newfunc.__kwdefaults__ = func.__kwdefaults__
    return newfunc


def _wrapped_safe_repr(obj: object, *args, **kwargs) -> Tuple[str, bool, bool]:
    if isinstance(obj, str):
        return '"' + repr("'" + obj)[2:], True, False
    return _new_safe_repr(obj, *args, **kwargs)


newglobals = pprint._safe_repr.__globals__.copy()  # type: ignore[attr-defined]  # noqa: F821
newglobals["_safe_repr"] = _wrapped_safe_repr
_new_safe_repr = rebind_globals(
    pprint._safe_repr, newglobals  # type: ignore[attr-defined]  # noqa: F821
)  # type: Callable[..., Tuple[str, bool, bool]]


class ConsistentPrettyPrinter(pprint.PrettyPrinter):
    def format(self, object, context, maxlevels, level):
        """Wraps pprint._safe_repr for consistent quotes with string reprs."""
        return _wrapped_safe_repr(object, context, maxlevels, level, self._sort_dicts)


def _pformat_consistent(
    object, indent=1, width=80, depth=None, *, compact=False
) -> str:
    return ConsistentPrettyPrinter(
        indent=indent, width=width, depth=depth, compact=compact
    ).pformat(object)


class AlwaysDispatchingPrettyPrinter(pprint.PrettyPrinter):
    """PrettyPrinter that always dispatches (regardless of width)."""

    def _format(self, object, stream, indent, allowance, context, level):
        p = self._dispatch.get(type(object).__repr__, None)

        objid = id(object)
        if objid in context or p is None:
            return super()._format(object, stream, indent, allowance, context, level)

        context[objid] = 1
        p(self, object, stream, indent, allowance, context, level + 1)
        del context[objid]


def _pformat_dispatch(object, indent=1, width=80, depth=None, *, compact=False):
    return AlwaysDispatchingPrettyPrinter(
        indent=1, width=80, depth=None, compact=False
    ).pformat(object)
