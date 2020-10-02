from .compat import TYPE_CHECKING

# from more_itertools import collapse

if TYPE_CHECKING:
    from typing import Optional
    from typing import Tuple
    from typing import TypeVar
    from typing import Union

    _T = TypeVar("_T", bound="type")


def collapse_tuples(obj) -> "Tuple":
    def walk(node):
        if isinstance(node, tuple):
            for child in node:
                yield from walk(child)
        else:
            yield node

    return tuple(x for x in walk(obj))


def validate_tup_type(
    type_or_types: "Union[_T, Tuple[_T, ...]]", base_type: "_T"
) -> "Tuple[_T, ...]":
    types = collapse_tuples(type_or_types)
    for exc in types:
        if not isinstance(exc, type) or not issubclass(exc, base_type):
            raise TypeError(
                "exceptions must be derived from {}, not {}".format(
                    base_type.__name__,
                    exc.__name__ if isinstance(exc, type) else type(exc).__name__,
                )
            )
    return types
