import pytest
from _pytest import nodes
from _pytest.pytester import Testdir


@pytest.mark.parametrize(
    "baseid, nodeid, expected",
    (
        ("", "", True),
        ("", "foo", True),
        ("", "foo/bar", True),
        ("", "foo/bar::TestBaz", True),
        ("foo", "food", False),
        ("foo/bar::TestBaz", "foo/bar", False),
        ("foo/bar::TestBaz", "foo/bar::TestBop", False),
        ("foo/bar", "foo/bar::TestBop", True),
    ),
)
def test_ischildnode(baseid, nodeid, expected):
    result = nodes.ischildnode(baseid, nodeid)
    assert result is expected


def test_node_from_parent_disallowed_arguments() -> None:
    with pytest.raises(TypeError, match="session is"):
        nodes.Node.from_parent(None, session=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="config is"):
        nodes.Node.from_parent(None, config=None)  # type: ignore[arg-type]


def test_std_warn_not_pytestwarning(testdir):
    items = testdir.getitems(
        """
        def test():
            pass
    """
    )
    with pytest.raises(ValueError, match=".*instance of PytestWarning.*"):
        items[0].warn(UserWarning("some warning"))


def test_fulltrace_with_tb_native(testdir: Testdir) -> None:
    p1 = testdir.makepyfile("def test(): assert 0")
    result = testdir.runpytest(str(p1), "--fulltrace", "--tb=native")
    result.stdout.fnmatch_lines(
        [
            "*= FAILURES =*",
            "*_ test _*",
            "Traceback (most recent call last):",
            "  File *, in runtest",
            "    def test(): assert 0",
            "AssertionError: assert 0",
        ]
    )


def test_tbstyle_with_non_python(testdir: Testdir) -> None:
    testdir.makeconftest(
        """
        import pytest

        class MyItem(pytest.Item):
            nodeid = 'foo'

            def runtest(self):
                assert 0, "failure"

        def pytest_collect_file(path, parent):
            return MyItem("foo", parent)
    """
    )

    # Defaults to "--tb=long".
    result = testdir.runpytest()
    result.stdout.fnmatch_lines(
        [
            "_ _ _ _ _ *",
            "",
            "    def runtest(self):",
            '>       assert 0, "failure"',
            "E       AssertionError: failure",
            "E       assert 0",
            "",
            "conftest.py:7: AssertionError: failure...",
        ]
    )

    # Honors "--tb=short".
    result = testdir.runpytest("--tb=short")
    result.stdout.fnmatch_lines(
        [
            "conftest.py:7: in runtest",
            '    assert 0, "failure"',
            "E   AssertionError: failure",
            "E   assert 0",
        ]
    )
