# flake8: noqa
# disable flake check on this file because some constructs are strange
# or redundant on purpose and can't be disable on a line-by-line basis
import ast
import inspect
import sys
from types import CodeType
from typing import Any
from typing import Dict
from typing import Optional

import py.path

import _pytest._code
import pytest
from _pytest._code import getfslineno
from _pytest._code import Source
from _pytest._code.source import get_statement_startend2


def test_source_str_function() -> None:
    x = Source("3")
    assert str(x) == "3"

    x = Source("   3")
    assert str(x) == "3"

    x = Source(
        """
        3
        """
    )
    assert str(x) == "\n3"


def test_unicode() -> None:
    x = Source("4")
    assert str(x) == "4"
    co = _pytest._code.compile('"å"', mode="eval")
    val = eval(co)
    assert isinstance(val, str)


def test_source_from_function() -> None:
    source = _pytest._code.Source(test_source_str_function)
    assert str(source).startswith("def test_source_str_function() -> None:")


def test_source_from_method() -> None:
    class TestClass:
        def test_method(self):
            pass

    source = _pytest._code.Source(TestClass().test_method)
    assert source.lines == ["def test_method(self):", "    pass"]


def test_source_from_lines() -> None:
    lines = ["a \n", "b\n", "c"]
    source = _pytest._code.Source(lines)
    assert source.lines == ["a ", "b", "c"]


def test_source_from_inner_function() -> None:
    def f():
        pass

    source = _pytest._code.Source(f, deindent=False)
    assert str(source).startswith("    def f():")
    source = _pytest._code.Source(f)
    assert str(source).startswith("def f():")


def test_source_putaround_simple() -> None:
    source = Source("raise ValueError")
    source = source.putaround(
        "try:",
        """\
        except ValueError:
            x = 42
        else:
            x = 23""",
    )
    assert (
        str(source)
        == """\
try:
    raise ValueError
except ValueError:
    x = 42
else:
    x = 23"""
    )


def test_source_putaround() -> None:
    source = Source()
    source = source.putaround(
        """
        if 1:
            x=1
    """
    )
    assert str(source).strip() == "if 1:\n    x=1"


def test_source_strips() -> None:
    source = Source("")
    assert source == Source()
    assert str(source) == ""
    assert source.strip() == source


def test_source_strip_multiline() -> None:
    source = Source()
    source.lines = ["", " hello", "  "]
    source2 = source.strip()
    assert source2.lines == [" hello"]


def test_syntaxerror_rerepresentation() -> None:
    ex = pytest.raises(SyntaxError, _pytest._code.compile, "xyz xyz")
    assert ex is not None
    assert ex.value.lineno == 1
    if hasattr(sys, "pypy_version_info") or sys.version_info >= (3, 8):
        assert ex.value.offset == 5
    else:
        assert ex.value.offset == 7
    assert ex.value.text == "xyz xyz\n"


def test_isparseable() -> None:
    assert Source("hello").isparseable()
    assert Source("if 1:\n  pass").isparseable()
    assert Source(" \nif 1:\n  pass").isparseable()
    assert not Source("if 1:\n").isparseable()
    assert not Source(" \nif 1:\npass").isparseable()
    assert not Source(chr(0)).isparseable()


class TestAccesses:
    def setup_class(self) -> None:
        self.source = Source(
            """\
            def f(x):
                pass
            def g(x):
                pass
        """
        )

    def test_getrange(self) -> None:
        x = self.source[0:2]
        assert x.isparseable()
        assert len(x.lines) == 2
        assert str(x) == "def f(x):\n    pass"

    def test_getrange_step_not_supported(self) -> None:
        with pytest.raises(IndexError, match=r"step"):
            self.source[::2]

    def test_getline(self) -> None:
        x = self.source[0]
        assert x == "def f(x):"

    def test_len(self) -> None:
        assert len(self.source) == 4

    def test_iter(self) -> None:
        values = [x for x in self.source]
        assert len(values) == 4


class TestSourceParsingAndCompiling:
    def setup_class(self) -> None:
        self.source = Source(
            """\
            def f(x):
                assert (x ==
                        3 +
                        4)
        """
        ).strip()

    def test_compile(self) -> None:
        co = _pytest._code.compile("x=3")
        d = {}  # type: Dict[str, Any]
        exec(co, d)
        assert d["x"] == 3

    def test_compile_and_getsource_simple(self) -> None:
        co = _pytest._code.compile("x=3")
        exec(co)
        source = _pytest._code.Source(co)
        assert str(source) == "x=3"

    def test_compile_and_getsource_through_same_function(self) -> None:
        def gensource(source):
            return _pytest._code.compile(source)

        co1 = gensource(
            """
            def f():
                raise KeyError()
        """
        )
        co2 = gensource(
            """
            def f():
                raise ValueError()
        """
        )
        source1 = inspect.getsource(co1)
        assert "KeyError" in source1
        source2 = inspect.getsource(co2)
        assert "ValueError" in source2

    def test_getstatement(self) -> None:
        # print str(self.source)
        ass = str(self.source[1:])
        for i in range(1, 4):
            # print "trying start in line %r" % self.source[i]
            s = self.source.getstatement(i)
            # x = s.deindent()
            assert str(s) == ass

    def test_getstatementrange_triple_quoted(self) -> None:
        # print str(self.source)
        source = Source(
            """hello('''
        ''')"""
        )
        s = source.getstatement(0)
        assert s == str(source)
        s = source.getstatement(1)
        assert s == str(source)

    def test_getstatementrange_within_constructs(self) -> None:
        source = Source(
            """\
            try:
                try:
                    raise ValueError
                except SomeThing:
                    pass
            finally:
                42
        """
        )
        assert len(source) == 7
        # check all lineno's that could occur in a traceback
        # assert source.getstatementrange(0) == (0, 7)
        # assert source.getstatementrange(1) == (1, 5)
        assert source.getstatementrange(2) == (2, 3)
        assert source.getstatementrange(3) == (3, 4)
        assert source.getstatementrange(4) == (4, 5)
        # assert source.getstatementrange(5) == (0, 7)
        assert source.getstatementrange(6) == (6, 7)

    def test_getstatementrange_bug(self) -> None:
        source = Source(
            """\
            try:
                x = (
                   y +
                   z)
            except:
                pass
        """
        )
        assert len(source) == 6
        assert source.getstatementrange(2) == (1, 4)

    def test_getstatementrange_bug2(self) -> None:
        source = Source(
            """\
            assert (
                33
                ==
                [
                  X(3,
                      b=1, c=2
                   ),
                ]
              )
        """
        )
        assert len(source) == 9
        assert source.getstatementrange(5) == (0, 9)

    def test_getstatementrange_ast_issue58(self) -> None:
        source = Source(
            """\

            def test_some():
                for a in [a for a in
                    CAUSE_ERROR]: pass

            x = 3
        """
        )
        assert getstatement(2, source).lines == source.lines[2:3]
        assert getstatement(3, source).lines == source.lines[3:4]

    def test_getstatementrange_out_of_bounds_py3(self) -> None:
        source = Source("if xxx:\n   from .collections import something")
        r = source.getstatementrange(1)
        assert r == (1, 2)

    def test_getstatementrange_with_syntaxerror_issue7(self) -> None:
        source = Source(":")
        pytest.raises(SyntaxError, lambda: source.getstatementrange(0))

    def test_compile_to_ast(self) -> None:
        source = Source("x = 4")
        mod = source.compile(flag=ast.PyCF_ONLY_AST)
        assert isinstance(mod, ast.Module)
        compile(mod, "<filename>", "exec")

    def test_compile_and_getsource(self) -> None:
        co = self.source.compile()
        exec(co, globals())
        f(7)  # type: ignore
        excinfo = pytest.raises(AssertionError, f, 6)  # type: ignore
        assert excinfo is not None
        frame = excinfo.traceback[-1].frame
        assert isinstance(frame.code.fullsource, Source)
        stmt = frame.code.fullsource.getstatement(frame.lineno)
        assert str(stmt).strip().startswith("assert")

    @pytest.mark.parametrize("name", ["", None, "my"])
    def test_compilefuncs_and_path_sanity(self, name: Optional[str]) -> None:
        def check(comp, name) -> None:
            co = comp(self.source, name)
            if not name:
                expected = "codegen %s:%d>" % (mypath, mylineno + 2 + 2)  # type: ignore
            else:
                expected = "codegen %r %s:%d>" % (name, mypath, mylineno + 2 + 2)  # type: ignore
            fn = co.co_filename
            assert fn.endswith(expected)

        mycode = _pytest._code.Code(self.test_compilefuncs_and_path_sanity)
        mylineno = mycode.firstlineno
        mypath = mycode.path

        for comp in _pytest._code.compile, _pytest._code.Source.compile:
            check(comp, name)

    def test_offsetless_synerr(self):
        pytest.raises(SyntaxError, _pytest._code.compile, "lambda a,a: 0", mode="eval")


def test_getstartingblock_singleline() -> None:
    class A:
        def __init__(self, *args) -> None:
            frame = sys._getframe(1)
            self.source = _pytest._code.Frame(frame).statement

    x = A("x", "y")

    values = [i for i in x.source.lines if i.strip()]
    assert len(values) == 1


def test_getline_finally() -> None:
    def c() -> None:
        pass

    with pytest.raises(TypeError) as excinfo:
        teardown = None
        try:
            c(1)  # type: ignore
        finally:
            if teardown:
                teardown()
    source = excinfo.traceback[-1].statement
    assert str(source).strip() == "c(1)  # type: ignore"


def test_getfuncsource_dynamic() -> None:
    source = """
        def f():
            raise ValueError

        def g(): pass
    """
    co = _pytest._code.compile(source)
    exec(co, globals())
    f_source = _pytest._code.Source(f)  # type: ignore
    g_source = _pytest._code.Source(g)  # type: ignore
    assert str(f_source).strip() == "def f():\n    raise ValueError"
    assert str(g_source).strip() == "def g(): pass"


def test_getfuncsource_with_multine_string() -> None:
    def f():
        c = """while True:
    pass
"""

    expected = '''\
    def f():
        c = """while True:
    pass
"""
'''
    assert str(_pytest._code.Source(f)) == expected.rstrip()


def test_deindent() -> None:
    from _pytest._code.source import deindent as deindent

    assert deindent(["\tfoo", "\tbar"]) == ["foo", "bar"]

    source = """\
        def f():
            def g():
                pass
    """
    lines = deindent(source.splitlines())
    assert lines == ["def f():", "    def g():", "        pass"]


def test_source_of_class_at_eof_without_newline(tmpdir, _sys_snapshot) -> None:
    # this test fails because the implicit inspect.getsource(A) below
    # does not return the "x = 1" last line.
    source = _pytest._code.Source(
        """
        class A(object):
            def method(self):
                x = 1
    """
    )
    path = tmpdir.join("a.py")
    path.write(source)
    s2 = _pytest._code.Source(tmpdir.join("a.py").pyimport().A)
    assert str(source).strip() == str(s2).strip()


if True:

    def x():
        pass


def test_getsource_fallback() -> None:
    from _pytest._code.source import getsource

    expected = """def x():
    pass"""
    src = getsource(x)
    assert src == expected


def test_idem_compile_and_getsource() -> None:
    from _pytest._code.source import getsource

    expected = "def x(): pass"
    co = _pytest._code.compile(expected)
    src = getsource(co)
    assert src == expected


def test_compile_ast() -> None:
    # We don't necessarily want to support this.
    # This test was added just for coverage.
    stmt = ast.parse("def x(): pass")
    co = _pytest._code.compile(stmt, filename="foo.py")
    assert isinstance(co, CodeType)


def test_findsource_fallback() -> None:
    from _pytest._code.source import findsource

    src, lineno = findsource(x)
    assert src is not None
    assert "test_findsource_simple" in str(src)
    assert src[lineno] == "    def x():"


def test_findsource() -> None:
    from _pytest._code.source import findsource

    co = _pytest._code.compile(
        """if 1:
    def x():
        pass
"""
    )

    src, lineno = findsource(co)
    assert src is not None
    assert "if 1:" in str(src)

    d = {}  # type: Dict[str, Any]
    eval(co, d)
    src, lineno = findsource(d["x"])
    assert src is not None
    assert "if 1:" in str(src)
    assert src[lineno] == "    def x():"


@pytest.mark.pypy_specific
def test_getfslineno() -> None:
    def f(x) -> None:
        raise NotImplementedError()

    fspath, lineno = getfslineno(f)

    assert isinstance(fspath, py.path.local)
    assert fspath.basename == "test_source.py"
    assert lineno == f.__code__.co_firstlineno - 1  # see findsource

    class A:
        pass

    fspath, lineno = getfslineno(A)

    _, A_lineno = inspect.findsource(A)
    assert isinstance(fspath, py.path.local)
    assert fspath.basename == "test_source.py"
    assert lineno == A_lineno

    assert getfslineno(3) == ("", -1)

    class B:
        pass

    B.__name__ = B.__qualname__ = "do_not_find_me"
    assert getfslineno(B)[1] == -1

    co = compile("...", "", "eval")
    assert co.co_filename == ""

    if hasattr(sys, "pypy_version_info"):
        assert getfslineno(co) == ("", -1)
    else:
        assert getfslineno(co) == ("", 0)


def test_code_of_object_instance_with_call() -> None:
    class A:
        pass

    pytest.raises(TypeError, lambda: _pytest._code.Source(A()))

    class WithCall:
        def __call__(self) -> None:
            pass

    code = _pytest._code.Code(WithCall())
    assert "pass" in str(code.source())

    class Hello:
        def __call__(self) -> None:
            pass

    pytest.raises(TypeError, lambda: _pytest._code.Code(Hello))


def getstatement(lineno: int, source) -> Source:
    from _pytest._code.source import getstatementrange_ast

    src = _pytest._code.Source(source, deindent=False)
    ast, start, end = getstatementrange_ast(lineno, src)
    return src[start:end]


def test_oneline() -> None:
    source = getstatement(0, "raise ValueError")
    assert str(source) == "raise ValueError"


def test_comment_and_no_newline_at_end() -> None:
    from _pytest._code.source import getstatementrange_ast

    source = Source(
        [
            "def test_basic_complex():",
            "    assert 1 == 2",
            "# vim: filetype=pyopencl:fdm=marker",
        ]
    )
    ast, start, end = getstatementrange_ast(1, source)
    assert end == 2


def test_oneline_and_comment() -> None:
    source = getstatement(0, "raise ValueError\n#hello")
    assert str(source) == "raise ValueError"


@pytest.mark.pypy_specific
def test_comments() -> None:
    source = '''def test():
    "comment 1"
    x = 1
      # comment 2
    # comment 3

    assert False

"""
comment 4
"""
'''
    for line in range(2, 6):
        assert str(getstatement(line, source)) == "    x = 1"
    if sys.version_info >= (3, 8) or hasattr(sys, "pypy_version_info"):
        tqs_start = 8
    else:
        tqs_start = 10
        assert str(getstatement(10, source)) == '"""'
    for line in range(6, tqs_start):
        assert str(getstatement(line, source)) == "    assert False"
    for line in range(tqs_start, 10):
        assert str(getstatement(line, source)) == '"""\ncomment 4\n"""'


def test_comment_in_statement() -> None:
    source = """test(foo=1,
    # comment 1
    bar=2)
"""
    for line in range(1, 3):
        assert (
            str(getstatement(line, source))
            == "test(foo=1,\n    # comment 1\n    bar=2)"
        )


def test_source_with_decorator() -> None:
    """Test behavior with Source / Code().source with regard to decorators."""
    from _pytest.compat import get_real_func

    @pytest.mark.foo
    def deco_mark():
        assert False

    src = inspect.getsource(deco_mark)
    assert str(Source(deco_mark, deindent=False)) == src
    assert src.startswith("    @pytest.mark.foo")

    @pytest.fixture
    def deco_fixture():
        assert False

    src = inspect.getsource(deco_fixture)
    assert src == "    @pytest.fixture\n    def deco_fixture():\n        assert False\n"
    assert str(Source(deco_fixture)).startswith("@functools.wraps(function)")
    assert str(Source(get_real_func(deco_fixture), deindent=False)) == src


def test_single_line_else() -> None:
    source = getstatement(1, "if False: 2\nelse: 3")
    assert str(source) == "else: 3"


def test_single_line_finally() -> None:
    source = getstatement(1, "try: 1\nfinally: 3")
    assert str(source) == "finally: 3"


def test_issue55() -> None:
    source = (
        "def round_trip(dinp):\n  assert 1 == dinp\n"
        'def test_rt():\n  round_trip("""\n""")\n'
    )
    s = getstatement(3, source)
    assert str(s) == '  round_trip("""\n""")'


def test_multiline() -> None:
    source = getstatement(
        0,
        """\
raise ValueError(
    23
)
x = 3
""",
    )
    assert str(source) == "raise ValueError(\n    23\n)"


class TestTry:
    def setup_class(self) -> None:
        self.source = """\
try:
    raise ValueError
except Something:
    raise IndexError(1)
else:
    raise KeyError()
"""

    def test_body(self) -> None:
        source = getstatement(1, self.source)
        assert str(source) == "    raise ValueError"

    def test_except_line(self) -> None:
        source = getstatement(2, self.source)
        assert str(source) == "except Something:"

    def test_except_body(self) -> None:
        source = getstatement(3, self.source)
        assert str(source) == "    raise IndexError(1)"

    def test_else(self) -> None:
        source = getstatement(5, self.source)
        assert str(source) == "    raise KeyError()"


class TestTryFinally:
    def setup_class(self) -> None:
        self.source = """\
try:
    raise ValueError
finally:
    raise IndexError(1)
"""

    def test_body(self) -> None:
        source = getstatement(1, self.source)
        assert str(source) == "    raise ValueError"

    def test_finally(self) -> None:
        source = getstatement(3, self.source)
        assert str(source) == "    raise IndexError(1)"


class TestIf:
    def setup_class(self) -> None:
        self.source = """\
if 1:
    y = 3
elif False:
    y = 5
else:
    y = 7
"""

    def test_body(self) -> None:
        source = getstatement(1, self.source)
        assert str(source) == "    y = 3"

    def test_elif_clause(self) -> None:
        source = getstatement(2, self.source)
        assert str(source) == "elif False:"

    def test_elif(self) -> None:
        source = getstatement(3, self.source)
        assert str(source) == "    y = 5"

    def test_else(self) -> None:
        source = getstatement(5, self.source)
        assert str(source) == "    y = 7"


def test_semicolon() -> None:
    s = """\
hello ; pytest.skip()
"""
    source = getstatement(0, s)
    assert str(source) == s.strip()


def test_def_online() -> None:
    s = """\
def func(): raise ValueError(42)

def something():
    pass
"""
    source = getstatement(0, s)
    assert str(source) == "def func(): raise ValueError(42)"


def XXX_test_expression_multiline() -> None:
    source = """\
something
'''
'''"""
    result = getstatement(1, source)
    assert str(result) == "'''\n'''"


def test_getstartingblock_multiline() -> None:
    class A:
        def __init__(self, *args):
            frame = sys._getframe(1)
            self.source = _pytest._code.Frame(frame).statement

    # fmt: off
    x = A('x',
          'y'
          ,
          'z')
    # fmt: on
    values = [i for i in x.source.lines if i.strip()]
    assert len(values) == 4


def test_deco_statements() -> None:
    """Ref: https://github.com/pytest-dev/pytest/issues/4984"""
    code = "\n".join(
        [
            "@deco",
            "def test(): pass",
            "",
            "last_line = 1",
        ]
    )
    astnode = ast.parse(code, "source", "exec")
    assert get_statement_startend2(0, astnode) == (0, 1)

    assert getstatement(0, code).lines == ["@deco"]
    assert getstatement(1, code).lines == ["def test(): pass"]
    assert getstatement(2, code).lines == ["def test(): pass"]
    assert getstatement(3, code).lines == ["last_line = 1"]
