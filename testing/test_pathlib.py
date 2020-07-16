import os.path
import sys

import py

import pytest
from _pytest.pathlib import _shorten_path
from _pytest.pathlib import fnmatch_ex
from _pytest.pathlib import get_lock_path
from _pytest.pathlib import maybe_delete_a_numbered_dir
from _pytest.pathlib import Path
from _pytest.pathlib import rm_rf


class TestPort:
    """Test that our port of py.common.FNMatcher (fnmatch_ex) produces the same results as the
    original py.path.local.fnmatch method.
    """

    @pytest.fixture(params=["pathlib", "py.path"])
    def match(self, request):
        if request.param == "py.path":

            def match_(pattern, path):
                return py.path.local(path).fnmatch(pattern)

        else:
            assert request.param == "pathlib"

            def match_(pattern, path):
                return fnmatch_ex(pattern, path)

        return match_

    if sys.platform == "win32":
        drv1 = "c:"
        drv2 = "d:"
    else:
        drv1 = "/c"
        drv2 = "/d"

    @pytest.mark.parametrize(
        "pattern, path",
        [
            ("*.py", "foo.py"),
            ("*.py", "bar/foo.py"),
            ("test_*.py", "foo/test_foo.py"),
            ("tests/*.py", "tests/foo.py"),
            (drv1 + "/*.py", drv1 + "/foo.py"),
            (drv1 + "/foo/*.py", drv1 + "/foo/foo.py"),
            ("tests/**/test*.py", "tests/foo/test_foo.py"),
            ("tests/**/doc/test*.py", "tests/foo/bar/doc/test_foo.py"),
            ("tests/**/doc/**/test*.py", "tests/foo/doc/bar/test_foo.py"),
        ],
    )
    def test_matching(self, match, pattern, path):
        assert match(pattern, path)

    def test_matching_abspath(self, match):
        abspath = os.path.abspath(os.path.join("tests/foo.py"))
        assert match("tests/foo.py", abspath)

    @pytest.mark.parametrize(
        "pattern, path",
        [
            ("*.py", "foo.pyc"),
            ("*.py", "foo/foo.pyc"),
            ("tests/*.py", "foo/foo.py"),
            (drv1 + "/*.py", drv2 + "/foo.py"),
            (drv1 + "/foo/*.py", drv2 + "/foo/foo.py"),
            ("tests/**/test*.py", "tests/foo.py"),
            ("tests/**/test*.py", "foo/test_foo.py"),
            ("tests/**/doc/test*.py", "tests/foo/bar/doc/foo.py"),
            ("tests/**/doc/test*.py", "tests/foo/bar/test_foo.py"),
        ],
    )
    def test_not_matching(self, match, pattern, path):
        assert not match(pattern, path)


def test_access_denied_during_cleanup(tmp_path, monkeypatch):
    """Ensure that deleting a numbered dir does not fail because of OSErrors (#4262)."""
    path = tmp_path / "temp-1"
    path.mkdir()

    def renamed_failed(*args):
        raise OSError("access denied")

    monkeypatch.setattr(Path, "rename", renamed_failed)

    lock_path = get_lock_path(path)
    maybe_delete_a_numbered_dir(path)
    assert not lock_path.is_file()


def test_shorten_path(testdir) -> None:
    home = str(Path.home())
    assert os.getcwd() == str(home)
    assert _shorten_path(home) == "~"
    assert _shorten_path(os.path.join(home, "foo")) == "~{}foo".format(os.path.sep)

    assert _shorten_path("foo") == "foo"
    abs_foo = os.path.abspath("foo")
    assert _shorten_path(abs_foo) == "~{}foo".format(os.path.sep)
    assert _shorten_path(os.path.join(abs_foo, "..")) == "~"


def test_rm_rf_chmod0(tmp_path: "Path") -> None:
    noperm = tmp_path / "noperm"
    noperm.touch(mode=0)
    rm_rf(tmp_path)
    assert not os.path.exists(tmp_path)
