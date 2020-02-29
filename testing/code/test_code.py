import sys
from types import FrameType
from unittest import mock

import pytest
from _pytest._code import Code
from _pytest._code import ExceptionInfo
from _pytest._code import Frame
from _pytest._code.code import ReprFuncArgs


def test_ne() -> None:
    code1 = Code(compile('foo = "bar"', "", "exec"))
    assert code1 == code1
    code2 = Code(compile('foo = "baz"', "", "exec"))
    assert code2 != code1


def test_code_gives_back_name_for_not_existing_file() -> None:
    name = "abc-123"
    co_code = compile("pass\n", name, "exec")
    assert co_code.co_filename == name
    code = Code(co_code)
    assert str(code.path) == name
    assert code.fullsource is None


def test_code_with_class() -> None:
    class A:
        pass

    pytest.raises(TypeError, Code, A)


def x() -> None:
    raise NotImplementedError()


def test_code_fullsource() -> None:
    code = Code(x)
    full = code.fullsource
    assert "test_code_fullsource()" in str(full)


def test_code_source() -> None:
    code = Code(x)
    src = code.source()
    expected = """def x() -> None:
    raise NotImplementedError()"""
    assert str(src) == expected


def test_frame_getsourcelineno_myself() -> None:
    def func() -> FrameType:
        return sys._getframe(0)

    f = Frame(func())
    source, lineno = f.code.fullsource, f.lineno
    assert source is not None
    assert source[lineno].startswith("        return sys._getframe(0)")


def test_getstatement_empty_fullsource() -> None:
    def func() -> FrameType:
        return sys._getframe(0)

    f = Frame(func())
    with mock.patch.object(f.code.__class__, "fullsource", None):
        assert f.statement == ""


def test_code_from_func() -> None:
    co = Code(test_frame_getsourcelineno_myself)
    assert co.firstlineno
    assert co.path


def test_unicode_handling() -> None:
    value = "ąć".encode()

    def f() -> None:
        raise Exception(value)

    excinfo = pytest.raises(Exception, f)
    str(excinfo)


def test_code_getargs() -> None:
    def f1(x):
        raise NotImplementedError()

    c1 = Code(f1)
    assert c1.getargs(var=True) == ("x",)

    def f2(x, *y):
        raise NotImplementedError()

    c2 = Code(f2)
    assert c2.getargs(var=True) == ("x", "y")

    def f3(x, **z):
        raise NotImplementedError()

    c3 = Code(f3)
    assert c3.getargs(var=True) == ("x", "z")

    def f4(x, *y, **z):
        raise NotImplementedError()

    c4 = Code(f4)
    assert c4.getargs(var=True) == ("x", "y", "z")


def test_frame_getargs() -> None:
    def f1(x) -> FrameType:
        return sys._getframe(0)

    fr1 = Frame(f1("a"))
    assert fr1.getargs(var=True) == [("x", "a")]

    def f2(x, *y) -> FrameType:
        return sys._getframe(0)

    fr2 = Frame(f2("a", "b", "c"))
    assert fr2.getargs(var=True) == [("x", "a"), ("y", ("b", "c"))]

    def f3(x, **z) -> FrameType:
        return sys._getframe(0)

    fr3 = Frame(f3("a", b="c"))
    assert fr3.getargs(var=True) == [("x", "a"), ("z", {"b": "c"})]

    def f4(x, *y, **z) -> FrameType:
        return sys._getframe(0)

    fr4 = Frame(f4("a", "b", c="d"))
    assert fr4.getargs(var=True) == [("x", "a"), ("y", ("b",)), ("z", {"c": "d"})]


class TestExceptionInfo:
    def test_bad_getsource(self) -> None:
        try:
            if False:
                pass
            else:
                assert False
        except AssertionError:
            exci = ExceptionInfo.from_current()
        assert exci.getrepr()

    def test_from_current_with_missing(self) -> None:
        with pytest.raises(AssertionError, match="no current exception"):
            ExceptionInfo.from_current()


class TestTracebackEntry:
    def test_getsource(self) -> None:
        try:
            if False:
                pass
            else:
                assert False
        except AssertionError:
            exci = ExceptionInfo.from_current()
        entry = exci.traceback[0]
        source = entry.getsource()
        assert source is not None
        assert len(source) == 6
        assert "assert False" in source[5]


class TestTraceback:
    def test_getsource(self):
        try:
            raise AssertionError(sys._getframe().f_lineno)
        except AssertionError:
            exci = ExceptionInfo.from_current()

        tb = exci.traceback
        assert str(tb) == "\n".join(
            [
                '  File "{}", line {}, in test_getsource'.format(
                    __file__, exci.value.args[0]
                ),
                "    raise AssertionError(sys._getframe().f_lineno)",
            ]
        )

        # Same, but multiple source lines, and entries.
        # fmt: off
        def inner():
            raise AssertionError(  # some comment
                sys._getframe().f_lineno
            )
        # fmt: on

        try:
            inner()
        except AssertionError:
            exci = ExceptionInfo.from_current()
        tb = exci.traceback
        baselnum = exci.value.args[0]
        if sys.version_info >= (3, 8):
            expected_inner_lnum = baselnum - 1
        else:
            expected_inner_lnum = baselnum
        assert str(tb) == "\n".join(
            [
                '  File "{}", line {}, in test_getsource'.format(
                    __file__, baselnum + 5
                ),
                "    inner()",
                '  File "{}", line {}, in inner'.format(__file__, expected_inner_lnum),
                "    raise AssertionError(  # some comment",
                "        sys._getframe().f_lineno",
                "    )",
            ]
        )

    def test_filter_keeps_crash_entry(self, testdir):
        p1 = testdir.makepyfile(
            """
            def test(request):
                capman = request.config.pluginmanager.getplugin("capturemanager")
                capman.read_global_capture = None
            """
        )
        result = testdir.runpytest_subprocess(str(p1))
        result.stdout.fnmatch_lines(
            [
                "collected 1 item",
                "",
                "test_filter_keeps_crash_entry.py FE *",
                "_* ERROR at teardown of test *_",
                ">       out, err = self.read_global_capture()",
                "E       TypeError: 'NoneType' object is not callable",
                "=* FAILURES *=",
                ">       out, err = self.read_global_capture()",
                "E       TypeError: 'NoneType' object is not callable",
                "FAILED test_filter_keeps_crash_entry.py::test (*_pytest*capture.py:*)"
                " - TypeError: *",
                "ERROR test_filter_keeps_crash_entry.py::test (*_pytest*capture.py:*)"
                " - TypeError: *",
            ]
        )


class TestReprFuncArgs:
    def test_not_raise_exception_with_mixed_encoding(self, tw_mock) -> None:
        args = [("unicode_string", "São Paulo"), ("utf8_string", b"S\xc3\xa3o Paulo")]

        r = ReprFuncArgs(args)
        r.toterminal(tw_mock)

        assert (
            tw_mock.lines[0]
            == r"unicode_string = São Paulo, utf8_string = b'S\xc3\xa3o Paulo'"
        )
