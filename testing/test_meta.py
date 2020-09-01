"""
Test importing of all internal packages and modules.

This ensures all internal packages can be imported without needing the pytest
namespace being set, which is critical for the initialization of xdist.
"""
import pkgutil
import subprocess
import sys
from typing import List

import _pytest
import pytest
from _pytest.pytester import Testdir

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _modules() -> List[str]:
    pytest_pkg = _pytest.__path__  # type: str  # type: ignore
    return sorted(
        n
        for _, n, _ in pkgutil.walk_packages(pytest_pkg, prefix=_pytest.__name__ + ".")
    )


@pytest.mark.parametrize("module", _modules())
def test_no_warnings(module: str) -> None:
    # fmt: off
    subprocess.check_call((
        sys.executable,
        "-W", "error",
        # https://github.com/pytest-dev/pytest/issues/5901
        "-W", "ignore:The usage of `cmp` is deprecated and will be removed on or after 2021-06-01.  Please use `eq` and `order` instead.:DeprecationWarning",  # noqa: E501
        "-c", "__import__({!r})".format(module),
    ))
    # fmt: on


@pytest.mark.filterwarnings(
    "ignore:pytest.collect.Item was moved to pytest.Item:pytest.PytestDeprecationWarning",
)
def test_pytest_collect_attribute(_sys_snapshot) -> None:
    from types import ModuleType

    del sys.modules["pytest"]

    import pytest

    assert isinstance(pytest.collect, ModuleType)
    assert pytest.collect.Item is pytest.Item  # type: ignore[attr-defined]

    with pytest.raises(ImportError):
        import pytest.collect

    from pytest import collect

    with pytest.raises(AttributeError):
        collect.doesnotexist  # type: ignore[attr-defined]


def test_pytest___get_attr__(_sys_snapshot) -> None:
    if sys.version_info >= (3, 7):
        with pytest.raises(AttributeError, match=r"^doesnotexist$"):
            pytest.doesnotexist
    else:
        with pytest.raises(AttributeError, match=r"doesnotexist"):
            pytest.doesnotexist  # type: ignore[attr-defined]


def test_pytest_circular_import(testdir: Testdir, symlink_or_skip) -> None:
    """Importing pytest should not import pytest itself."""
    import pytest
    import os.path

    symlink_or_skip(os.path.dirname(pytest.__file__), "another")

    del sys.modules["pytest"]

    testdir.syspathinsert()
    import another  # noqa: F401

    assert "pytest" not in sys.modules
