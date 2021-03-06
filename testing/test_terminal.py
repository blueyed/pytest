"""
terminal reporting of the full testing process.
"""
import collections
import os
import sys
import textwrap
from io import StringIO
from typing import Dict
from typing import List
from typing import Tuple

import pluggy
import py.path

import _pytest.config
import pytest
from _pytest._code.code import ReprFileLocation
from _pytest.config import ExitCode
from _pytest.pytester import Testdir
from _pytest.reports import BaseReport
from _pytest.reports import TestReport
from _pytest.terminal import _folded_skips
from _pytest.terminal import _get_line_with_reprcrash_message
from _pytest.terminal import _get_pos
from _pytest.terminal import _plugin_nameversions
from _pytest.terminal import getreportopt
from _pytest.terminal import TerminalReporter

try:
    import pygments
except ImportError:
    pygments = None


DistInfo = collections.namedtuple("DistInfo", ["project_name", "version"])


TRANS_FNMATCH = str.maketrans({"[": "[[]", "]": "[]]"})


class Option:
    def __init__(self, verbosity=0):
        self.verbosity = verbosity

    @property
    def args(self):
        values = []
        values.append("--verbosity=%d" % self.verbosity)
        return values


@pytest.fixture(
    params=[Option(verbosity=0), Option(verbosity=1), Option(verbosity=-1)],
    ids=["default", "verbose", "quiet"],
)
def option(request):
    return request.param


@pytest.mark.parametrize(
    "input,expected",
    [
        ([DistInfo(project_name="test", version=1)], ["test-1"]),
        ([DistInfo(project_name="pytest-test", version=1)], ["test-1"]),
        (
            [
                DistInfo(project_name="test", version=1),
                DistInfo(project_name="test", version=1),
            ],
            ["test-1"],
        ),
    ],
    ids=["normal", "prefix-strip", "deduplicate"],
)
def test_plugin_nameversion(input, expected):
    pluginlist = [(None, x) for x in input]
    result = _plugin_nameversions(pluginlist)
    assert result == expected


class TestTerminal:
    def test_pass_skip_fail(self, testdir, option):
        testdir.makepyfile(
            """
            import pytest
            def test_ok():
                pass
            def test_skip():
                pytest.skip("xx")
            def test_func():
                assert 0
        """
        )
        result = testdir.runpytest(*option.args)
        if option.verbosity > 0:
            result.stdout.fnmatch_lines(
                [
                    "*test_pass_skip_fail.py::test_ok PASS*",
                    "*test_pass_skip_fail.py::test_skip SKIP*",
                    "*test_pass_skip_fail.py::test_func FAIL*",
                ]
            )
        elif option.verbosity == 0:
            result.stdout.fnmatch_lines(["*test_pass_skip_fail.py .sF*"])
        else:
            result.stdout.fnmatch_lines([".sF*"])
        result.stdout.fnmatch_lines(
            ["    def test_func():", ">       assert 0", "E       assert 0"]
        )

    def test_internalerror(self, testdir, linecomp):
        modcol = testdir.getmodulecol("def test_one(): pass")
        rep = TerminalReporter(modcol.config, file=linecomp.stringio)
        with pytest.raises(ValueError) as excinfo:
            raise ValueError("hello")
        rep.pytest_internalerror(excinfo.getrepr())
        linecomp.assert_contains_lines(["INTERNALERROR> *ValueError*hello*"])

    def test_writeline(self, testdir, linecomp):
        modcol = testdir.getmodulecol("def test_one(): pass")
        rep = TerminalReporter(modcol.config, file=linecomp.stringio)
        rep.write_fspath_result(modcol.nodeid, ".")
        rep.write_line("hello world")
        lines = linecomp.stringio.getvalue().split("\n")
        assert not lines[0]
        assert lines[1].endswith(modcol.name + " .")
        assert lines[2] == "hello world"

    def test_show_runtest_logstart(self, testdir, linecomp):
        item = testdir.getitem("def test_func(): pass")
        tr = TerminalReporter(item.config, file=linecomp.stringio)
        item.config.pluginmanager.register(tr)
        location = item.reportinfo()
        tr.config.hook.pytest_runtest_logstart(
            nodeid=item.nodeid, location=location, fspath=str(item.fspath)
        )
        linecomp.assert_contains_lines(["*test_show_runtest_logstart.py*"])

    def test_runtest_location_shown_before_test_starts(self, testdir):
        testdir.makepyfile(
            """
            def test_1():
                import time
                time.sleep(20)
        """
        )
        child = testdir.spawn_pytest("")
        child.expect(".*test_runtest_location.*py")
        child.sendeof()
        child.kill(15)

    def test_report_collect_after_half_a_second(self, testdir):
        """Test for "collecting" being updated after 0.5s"""

        testdir.makepyfile(
            **{
                "test1.py": """
                import _pytest.terminal

                _pytest.terminal.REPORT_COLLECTING_RESOLUTION = 0

                def test_1():
                    pass
                    """,
                "test2.py": "def test_2(): pass",
            }
        )
        # Explicitly test colored output.
        testdir.monkeypatch.setenv("PY_COLORS", "1")

        child = testdir.spawn_pytest("-v test1.py test2.py")
        child.expect(r"collecting \.\.\.")
        child.expect(r"collecting 1 item")
        child.expect(r"collecting 2 items")
        child.expect(r"collected 2 items")
        rest = child.read().decode("utf8")
        assert "= \x1b[32m\x1b[1m2 passed\x1b[0m\x1b[32m in" in rest

    def test_itemreport_subclasses_show_subclassed_file(self, testdir):
        testdir.makepyfile(
            **{
                "tests/test_p1": """
            class BaseTests(object):
                fail = False

                def test_p1(self):
                    if self.fail: assert 0
                """,
                "tests/test_p2": """
            from test_p1 import BaseTests

            class TestMore(BaseTests): pass
                """,
                "tests/test_p3.py": """
            from test_p1 import BaseTests

            BaseTests.fail = True

            class TestMore(BaseTests): pass
        """,
            }
        )
        result = testdir.runpytest("tests/test_p2.py", "--rootdir=tests")
        result.stdout.fnmatch_lines(["tests/test_p2.py .*", "=* 1 passed in *"])

        result = testdir.runpytest("-vv", "-rA", "tests/test_p2.py", "--rootdir=tests")
        result.stdout.fnmatch_lines(
            [
                "tests/test_p2.py::TestMore::test_p1 <- test_p1.py PASSED *",
                "*= short test summary info =*",
                "PASSED tests/test_p2.py::TestMore::test_p1",
            ]
        )
        result = testdir.runpytest("-vv", "-rA", "tests/test_p3.py", "--rootdir=tests")
        result.stdout.fnmatch_lines(
            [
                "tests/test_p3.py::TestMore::test_p1 <- test_p1.py FAILED *",
                "*_ TestMore.test_p1 _*",
                "    def test_p1(self):",
                ">       if self.fail: assert 0",
                "E       assert 0",
                "",
                "tests/test_p1.py:5: assert 0",
                "*= short test summary info =*",
                "FAILED tests/test_p3.py::TestMore::test_p1 (tests/test_p1.py:5) - assert 0",
                "*= 1 failed in *",
            ]
        )

    def test_itemreport_directclasses_not_shown_as_subclasses(self, testdir):
        a = testdir.mkpydir("a123")
        a.join("test_hello123.py").write(
            textwrap.dedent(
                """\
                class TestClass(object):
                    def test_method(self):
                        pass
                """
            )
        )
        result = testdir.runpytest("-vv")
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*a123/test_hello123.py*PASS*"])
        result.stdout.no_fnmatch_line("* <- *")

    @pytest.mark.parametrize(
        "args", ((), ("--fulltrace",), ("--fulltrace", "--tb=short"))
    )
    def test_keyboard_interrupt(self, args: Tuple[str, ...], testdir: Testdir) -> None:
        testdir.makepyfile(
            """
            def test_foobar():
                assert 0
            def test_interrupt_me():
                raise KeyboardInterrupt   # simulating the user
        """
        )

        fulltrace_note = (
            "(to show a full traceback on KeyboardInterrupt use --full-trace)"
        )
        result = testdir.runpytest(*args, no_reraise_ctrlc=True)
        if args == ():
            result.stdout.fnmatch_lines(
                [
                    "    def test_foobar():",
                    ">       assert 0",
                    "E       assert 0",
                    "*= short test summary info =*",
                    "*! KeyboardInterrupt !*",
                    "*_keyboard_interrupt.py:4: KeyboardInterrupt",
                    fulltrace_note,
                ]
            )
            return

        assert fulltrace_note not in result.stdout.str()
        if args == ("--fulltrace",):
            result.stdout.fnmatch_lines(
                [
                    "test_keyboard_interrupt.py F",
                    "",
                    "*= FAILURES =*",
                    "*_ test_foobar _*",
                    "    def test_foobar():",
                    ">       assert 0",
                    "E       assert 0",
                    "",
                    "test_keyboard_interrupt.py:2: assert 0",
                    "*= short test summary info =*",
                    "FAILED test_keyboard_interrupt.py:2::test_foobar - assert 0",
                    "*! KeyboardInterrupt !*",
                    "    def test_interrupt_me():",
                    ">       raise KeyboardInterrupt   # simulating the user",
                    "E       KeyboardInterrupt",
                    "",
                    "test_keyboard_interrupt.py:4: KeyboardInterrupt",
                    "*= 1 failed in *",
                ]
            )
        elif args == ("--fulltrace", "--tb=short"):
            result.stdout.fnmatch_lines(
                [
                    "test_keyboard_interrupt.py F",
                    "",
                    "*= FAILURES =*",
                    "*_ test_foobar _*",
                    "test_keyboard_interrupt.py:2: in test_foobar",
                    "    assert 0",
                    "E   assert 0",
                    "*= short test summary info =*",
                    "FAILED test_keyboard_interrupt.py:2::test_foobar - assert 0",
                    "*! KeyboardInterrupt !*",
                    "test_keyboard_interrupt.py:4: in test_interrupt_me",
                    "    raise KeyboardInterrupt   # simulating the user",
                    "E   KeyboardInterrupt",
                    "*= 1 failed in *",
                ]
            )
        else:
            assert False, args

    def test_keyboard_in_sessionstart(self, testdir):
        testdir.makeconftest(
            """
            def pytest_sessionstart():
                raise KeyboardInterrupt
        """
        )
        testdir.makepyfile(
            """
            def test_foobar():
                pass
        """
        )

        result = testdir.runpytest(no_reraise_ctrlc=True)
        assert result.ret == 2
        result.stdout.fnmatch_lines(["*KeyboardInterrupt*"])

    def test_collect_single_item(self, testdir):
        """Use singular 'item' when reporting a single test item"""
        testdir.makepyfile(
            """
            def test_foobar():
                pass
        """
        )
        result = testdir.runpytest()
        result.stdout.fnmatch_lines(["collected 1 item"])

    def test_rewrite(self, testdir, monkeypatch):
        config = testdir.parseconfig()
        f = StringIO()
        monkeypatch.setattr(f, "isatty", lambda *args: True)
        tr = TerminalReporter(config, f)
        tr._tw.fullwidth = 10
        tr.write("hello")
        tr.rewrite("hey", erase=True)
        assert f.getvalue() == "hello" + "\r" + "hey" + (6 * " ")


class TestCollectonly:
    def test_collectonly_basic(self, testdir):
        testdir.makepyfile(
            """
            def test_func():
                pass
        """
        )
        result = testdir.runpytest("--collect-only")
        result.stdout.fnmatch_lines(
            ["<Module test_collectonly_basic.py>", "  <Function test_func>"]
        )

    def test_collectonly_skipped_module(self, testdir):
        testdir.makepyfile(
            """
            import pytest
            pytest.skip("hello")
        """
        )
        result = testdir.runpytest("--collect-only", "-rs")
        result.stdout.fnmatch_lines(["*ERROR collecting*"])

    def test_collectonly_displays_test_description(
        self, testdir: Testdir, dummy_yaml_custom_test
    ) -> None:
        """Used dummy_yaml_custom_test for an Item without ``obj``."""
        testdir.makepyfile(
            """
            def test_with_description():
                '''  This test has a description.

                  more1.
                    more2.'''
            """
        )
        result = testdir.runpytest("--collect-only", "--verbose")
        result.stdout.fnmatch_lines(
            [
                "<YamlFile test1.yaml>",
                "  <YamlItem test1.yaml>",
                "<Module test_collectonly_displays_test_description.py>",
                "  <Function test_with_description>",
                "    This test has a description.",
                "    ",
                "    more1.",
                "      more2.",
            ],
            consecutive=True,
        )

    def test_collectonly_failed_module(self, testdir):
        testdir.makepyfile("""raise ValueError(0)""")
        result = testdir.runpytest("--collect-only")
        result.stdout.fnmatch_lines(["*raise ValueError*", "*1 error*"])

    def test_collectonly_fatal(self, testdir: Testdir, color_mapping) -> None:
        testdir.makeconftest(
            """
            def pytest_collectstart(collector):
                assert 0, "urgs"
        """
        )
        testdir.monkeypatch.setenv("PY_COLORS", "1")
        result = testdir.runpytest("--collect-only")
        result.stdout.fnmatch_lines(
            color_mapping.format_for_fnmatch(
                [
                    "*INTERNAL*args*",
                    "{red}=*= {yellow}no tests ran{reset}{red} in *{reset}{red} =*={reset}",
                ]
            )
        )
        assert result.ret == 3

    def test_collectonly_simple(self, testdir):
        p = testdir.makepyfile(
            """
            def test_func1():
                pass
            class TestClass(object):
                def test_method(self):
                    pass
        """
        )
        result = testdir.runpytest("--collect-only", p)
        # assert stderr.startswith("inserting into sys.path")
        assert result.ret == 0
        result.stdout.fnmatch_lines(
            [
                "*<Module *.py>",
                "* <Function test_func1>",
                "* <Class TestClass>",
                "*   <Function test_method>",
            ]
        )

    def test_collectonly_error(self, testdir):
        p = testdir.makepyfile("import Errlkjqweqwe")
        result = testdir.runpytest("--collect-only", p)
        assert result.ret == 2
        result.stdout.fnmatch_lines(
            textwrap.dedent(
                """\
                *ERROR*
                *ImportError*
                *No module named *Errlk*
                *1 error*
                """
            ).strip()
        )

    def test_collectonly_missing_path(self, testdir):
        """this checks issue 115,
            failure in parseargs will cause session
            not to have the items attribute
        """
        result = testdir.runpytest("--collect-only", "uhm_missing_path")
        assert result.ret == 4
        result.stderr.fnmatch_lines(["*ERROR: file not found*"])

    def test_collectonly_quiet(self, testdir):
        testdir.makepyfile("def test_foo(): pass")
        result = testdir.runpytest("--collect-only", "-q")
        result.stdout.fnmatch_lines(["*test_foo*"])

    def test_collectonly_more_quiet(self, testdir):
        testdir.makepyfile(test_fun="def test_foo(): pass")
        result = testdir.runpytest("--collect-only", "-qq")
        result.stdout.fnmatch_lines(["*test_fun.py: 1*"])


class TestFixtureReporting:
    def test_setup_fixture_error(self, testdir):
        testdir.makepyfile(
            """
            def setup_function(function):
                print("setup func")
                assert 0
            def test_nada():
                pass
        """
        )
        result = testdir.runpytest()
        result.stdout.fnmatch_lines(
            [
                "*ERROR at setup of test_nada*",
                "*setup_function(function):*",
                "*setup func*",
                "*assert 0*",
                "*1 error*",
            ]
        )
        assert result.ret != 0

    def test_teardown_fixture_error(self, testdir):
        testdir.makepyfile(
            """
            def test_nada():
                pass
            def teardown_function(function):
                print("teardown func")
                assert 0
        """
        )
        result = testdir.runpytest()
        result.stdout.fnmatch_lines(
            [
                "*ERROR at teardown*",
                "*teardown_function(function):*",
                "*assert 0*",
                "*Captured stdout*",
                "*teardown func*",
                "*1 passed*1 error*",
            ]
        )

    def test_teardown_fixture_error_and_test_failure(self, testdir):
        testdir.makepyfile(
            """
            def test_fail():
                assert 0, "failingfunc"

            def teardown_function(function):
                print("teardown func")
                assert False
        """
        )
        result = testdir.runpytest()
        result.stdout.fnmatch_lines(
            [
                "*ERROR at teardown of test_fail*",
                "*teardown_function(function):*",
                "*assert False*",
                "*Captured stdout*",
                "*teardown func*",
                "*test_fail*",
                "*def test_fail():",
                "*failingfunc*",
                "*1 failed*1 error*",
            ]
        )

    def test_setup_teardown_output_and_test_failure(self, testdir):
        """ Test for issue #442 """
        testdir.makepyfile(
            """
            def setup_function(function):
                print("setup func")

            def test_fail():
                assert 0, "failingfunc"

            def teardown_function(function):
                print("teardown func")
        """
        )
        result = testdir.runpytest()
        result.stdout.fnmatch_lines(
            [
                "*test_fail*",
                "*def test_fail():",
                "*failingfunc*",
                "*Captured stdout setup*",
                "*setup func*",
                "*Captured stdout teardown*",
                "*teardown func*",
                "*1 failed*",
            ]
        )


class TestTerminalFunctional:
    def test_deselected(self, testdir):
        testpath = testdir.makepyfile(
            """
                def test_one():
                    pass
                def test_two():
                    pass
                def test_three():
                    pass
           """
        )
        result = testdir.runpytest("-k", "test_two:", testpath)
        result.stdout.fnmatch_lines(
            ["collected 3 items / 1 deselected / 2 selected", "*test_deselected.py ..*"]
        )
        assert result.ret == 0

    def test_deselected_with_hookwrapper(self, testdir):
        testpath = testdir.makeconftest(
            """
            import pytest

            @pytest.hookimpl(hookwrapper=True)
            def pytest_collection_modifyitems(config, items):
                yield
                deselected = items.pop()
                config.hook.pytest_deselected(items=[deselected])
            """
        )
        testpath = testdir.makepyfile(
            """
                def test_one():
                    pass
                def test_two():
                    pass
                def test_three():
                    pass
           """
        )
        result = testdir.runpytest(testpath)
        result.stdout.fnmatch_lines(
            [
                "collected 3 items / 1 deselected / 2 selected",
                "*= 2 passed, 1 deselected in*",
            ]
        )
        assert result.ret == 0

    def test_show_deselected_items_using_markexpr_before_test_execution(self, testdir):
        testdir.makepyfile(
            test_show_deselected="""
            import pytest

            @pytest.mark.foo
            def test_foobar():
                pass

            @pytest.mark.bar
            def test_bar():
                pass

            def test_pass():
                pass
        """
        )
        result = testdir.runpytest("-m", "not foo")
        result.stdout.fnmatch_lines(
            [
                "collected 3 items / 1 deselected / 2 selected",
                "*test_show_deselected.py ..*",
                "*= 2 passed, 1 deselected in * =*",
            ]
        )
        result.stdout.no_fnmatch_line("*= 1 deselected =*")
        assert result.ret == 0

    def test_no_skip_summary_if_failure(self, testdir):
        testdir.makepyfile(
            """
            import pytest
            def test_ok():
                pass
            def test_fail():
                assert 0
            def test_skip():
                pytest.skip("dontshow")
        """
        )
        result = testdir.runpytest()
        assert result.stdout.str().find("skip test summary") == -1
        assert result.ret == 1

    def test_passes(self, testdir):
        p1 = testdir.makepyfile(
            """
            def test_passes():
                pass
            class TestClass(object):
                def test_method(self):
                    pass
        """
        )
        old = p1.dirpath().chdir()
        try:
            result = testdir.runpytest()
        finally:
            old.chdir()
        result.stdout.fnmatch_lines(["test_passes.py ..*", "* 2 pass*"])
        assert result.ret == 0

    @pytest.mark.xdist_specific  # to have some entrypoint plugin.
    def test_header_trailer_info(self, testdir: "Testdir", request) -> None:
        testdir.makepyfile("def test_pass(): pass")
        has_xdist = request.config.pluginmanager.get_plugin("xdist")
        if has_xdist:
            result = testdir.runpytest("-pxdist")
        else:
            result = testdir.runpytest()
        verinfo = ".".join(map(str, sys.version_info[:3]))
        result.stdout.fnmatch_lines(
            [
                "*===== test session starts ====*",
                "platform %s -- Python %s*pytest-%s*py-%s*pluggy-%s"
                % (
                    sys.platform,
                    verinfo,
                    pytest.__version__,
                    py.__version__,
                    pluggy.__version__,
                ),
                "*test_header_trailer_info.py .*",
                "=* 1 passed*in *.[0-9][0-9]s *=",
            ]
        )
        if has_xdist:
            result.stdout.fnmatch_lines(["plugins: *"])

    def test_header(self, testdir: Testdir) -> None:
        root = testdir.tmpdir.join("root")
        root.join("tests").ensure_dir()
        root.join("gui").ensure_dir()

        # Hack to get decent/typical display for rootdir (not only "~" directly).
        testdir.tmpdir = root
        testdir.chdir()

        # no ini file
        result = testdir.runpytest()
        result.stdout.fnmatch_lines(["rootdir: ~/root"])

        # with inifile
        testdir.makeini("""[pytest]""")
        result = testdir.runpytest()
        result.stdout.fnmatch_lines(["rootdir: ~/root, inifile: tox.ini"])

        # with testpaths option, and not passing anything in the command-line
        testdir.makeini(
            """
            [pytest]
            testpaths = tests gui
        """
        )
        result = testdir.runpytest()
        result.stdout.fnmatch_lines(
            ["rootdir: ~/root, inifile: tox.ini, testpaths: tests, gui"]
        )

        # with testpaths option, passing directory in command-line: do not show testpaths then
        result = testdir.runpytest("tests")
        result.stdout.fnmatch_lines(["rootdir: ~/root, inifile: tox.ini"])

        # Reports cwd if != rootdir.
        testdir.makefile("ini", **{"tests/pytest": ""})
        result = testdir.runpytest("tests")
        result.stdout.fnmatch_lines(
            ["rootdir: ~/root/tests, inifile: pytest.ini, cwd: ~/root"]
        )

    def test_header_full_rootdir_and_cachedir(self, testdir: Testdir) -> None:
        testdir.makeini(
            """
            [pytest]
            cache_dir = /tmp/elsewhere
        """
        )
        result = testdir.runpytest("-v")
        result.stdout.fnmatch_lines(
            [
                "rootdir: ~ ({}), inifile: tox.ini".format(testdir.tmpdir),
                "cachedir: /tmp/elsewhere",
            ]
        )

    def test_showlocals(self, testdir):
        p1 = testdir.makepyfile(
            """
            def test_showlocals():
                x = 3
                y = "x" * 5000
                assert 0
        """
        )
        result = testdir.runpytest(p1, "-l")
        result.stdout.fnmatch_lines(
            [
                # "_ _ * Locals *",
                "x* = 3",
                "y* = 'xxxxxx*",
            ]
        )

    def test_showlocals_short(self, testdir):
        p1 = testdir.makepyfile(
            """
            def test_showlocals_short():
                x = 3
                y = "xxxx"
                assert 0
        """
        )
        result = testdir.runpytest(p1, "-l", "--tb=short")
        result.stdout.fnmatch_lines(
            [
                "test_showlocals_short.py:*",
                "    assert 0",
                "E   assert 0",
                "        x          = 3",
                "        y          = 'xxxx'",
            ]
        )

    @pytest.fixture
    def verbose_testfile(self, testdir):
        return testdir.makepyfile(
            """
            import pytest
            def test_fail():
                raise ValueError()
            def test_pass():
                pass
            class TestClass(object):
                def test_skip(self):
                    pytest.skip("hello")
            def test_gen():
                def check(x):
                    assert x == 1
                yield check, 0
        """
        )

    def test_verbose_reporting(self, verbose_testfile, testdir):
        result = testdir.runpytest(
            verbose_testfile, "-v", "-Walways::pytest.PytestWarning"
        )
        result.stdout.fnmatch_lines(
            [
                "*test_verbose_reporting.py::test_fail *FAIL*",
                "*test_verbose_reporting.py::test_pass *PASS*",
                "*test_verbose_reporting.py::TestClass::test_skip *SKIP*",
                "*test_verbose_reporting.py::test_gen *XFAIL*",
            ]
        )
        assert result.ret == 1

    @pytest.mark.xdist_specific
    def test_verbose_reporting_xdist(
        self, verbose_testfile: "py.path.local", testdir: "Testdir"
    ) -> None:
        pytest.importorskip("xdist")
        result = testdir.runpytest(
            verbose_testfile, "-v", "-pxdist", "-n1", "-Walways::pytest.PytestWarning"
        )
        result.stdout.fnmatch_lines(
            ["*FAIL*test_verbose_reporting_xdist.py::test_fail*"]
        )
        assert result.ret == 1

    def test_quiet_reporting(self, testdir):
        p1 = testdir.makepyfile("def test_pass(): pass")
        result = testdir.runpytest(p1, "-q")
        s = result.stdout.str()
        assert "test session starts" not in s
        assert p1.basename not in s
        assert "===" not in s
        assert "passed" in s

    def test_more_quiet_reporting(self, testdir):
        p1 = testdir.makepyfile("def test_pass(): pass")
        result = testdir.runpytest(p1, "-qq")
        s = result.stdout.str()
        assert "test session starts" not in s
        assert p1.basename not in s
        assert "===" not in s
        assert "passed" not in s

    @pytest.mark.parametrize(
        "params", [(), ("--collect-only",)], ids=["no-params", "collect-only"]
    )
    def test_report_collectionfinish_hook(self, testdir, params):
        testdir.makeconftest(
            """
            def pytest_report_collectionfinish(config, startdir, items):
                return ['hello from hook: {0} items'.format(len(items))]
        """
        )
        testdir.makepyfile(
            """
            import pytest
            @pytest.mark.parametrize('i', range(3))
            def test(i):
                pass
        """
        )
        result = testdir.runpytest(*params)
        result.stdout.fnmatch_lines(["collected 3 items", "hello from hook: 3 items"])

    def test_summary_f_alias(self, testdir):
        """Test that 'f' and 'F' report chars are aliases and don't show up twice in the summary (#6334)"""
        testdir.makepyfile(
            """
            def test():
                assert False
            """
        )
        result = testdir.runpytest("-rfF")
        expected = "FAILED test_summary_f_alias.py:2::test - assert False"
        result.stdout.fnmatch_lines([expected])
        assert result.stdout.lines.count(expected) == 1

    def test_summary_s_alias(self, testdir):
        """Test that 's' and 'S' report chars are aliases and don't show up twice in the summary"""
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.skip
            def test():
                pass
            """
        )
        result = testdir.runpytest("-rsS")
        expected = "SKIPPED [1] test_summary_s_alias.py:3: unconditional skip"
        result.stdout.fnmatch_lines([expected])
        assert result.stdout.lines.count(expected) == 1


@pytest.mark.parametrize("tty", (True, False))
@pytest.mark.parametrize("use_CI", (True, False))
def test_fail_extra_reporting(tty: bool, use_CI: bool, testdir: Testdir):
    monkeypatch = testdir.monkeypatch
    if use_CI:
        monkeypatch.setenv("CI", "true")
    else:
        monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("PY_COLORS", "0")

    testdir.makepyfile(
        """
        def test_this(request):
            tr = request.config.pluginmanager.getplugin("terminalreporter")
            assert tr.isatty is {tty}
            assert 0, 'this_failed' * 8

        def test_linematcher():
            from _pytest.pytester import LineMatcher

            LineMatcher(["1", "2", "3"]).fnmatch_lines(["2", "last_unmatched"])
    """.format(
            tty=tty
        )
    )

    if tty:
        from _pytest.pytester import LineMatcher

        child = testdir.spawn_pytest("")
        lm = LineMatcher(child.read().decode().splitlines())
    else:
        result = testdir.runpytest("-rN")
        result.stdout.no_fnmatch_line("*short test summary*")
        result = testdir.runpytest()
        lm = result.stdout

    if use_CI or not tty:
        msgs = [
            "FAILED test_fail_extra_reporting.py:4::test_this - AssertionError: "
            + ("this_failed" * 8)
            + "\\nassert 0",
            # TODO: no Log here?  (via tryshort?)
            "FAILED test_fail_extra_reporting.py:9::test_linematcher"
            " - LineMatcherFailed: unmatched: 'last_unmatched'"
            r"\nLog:\nnomatch: '2'\n    and: '1'\nexact match: '2'\nnomatch: 'last_unmatched'\n    and: '3'"
            r"\nremains unmatched: 'last_unmatched'",
        ]
    else:
        msgs = [
            "FAILED test_fail_extra_reporting.py:4::test_this - AssertionError: this_faile...",
            "FAILED test_fail_extra_reporting.py:9::test_linematcher - LineMatcherFailed: ...",
        ]

    lm.fnmatch_lines(
        [
            '>       LineMatcher(["1", "2", "3"]).fnmatch_lines(["2", "last_unmatched"])',
            "E       LineMatcherFailed: unmatched: 'last_unmatched'",
            "E       Log:",
            "E       nomatch: '2'",
            "E           and: '1'",
            "E       exact match: '2'",
            "E       nomatch: 'last_unmatched'",
            "E           and: '3'",
            "E       remains unmatched: 'last_unmatched'",
            "*test summary*",
        ]
        + msgs
        + ["*= 2 failed in *"]
    )


def test_fail_reporting_with_tb_no(testdir):
    testdir.makepyfile("def test_this(): assert 0")
    result = testdir.runpytest("-rf", "--tb=no")
    result.stdout.fnmatch_lines("*short test summary*")


def test_fail_reporting_on_pass(testdir):
    testdir.makepyfile("def test_this(): assert 1")
    result = testdir.runpytest("-rf")
    result.stdout.no_fnmatch_line("*short test summary*")


def test_pass_extra_reporting(testdir):
    testdir.makepyfile("def test_this(): assert 1")
    result = testdir.runpytest()
    result.stdout.no_fnmatch_line("*short test summary*")
    result = testdir.runpytest("-rp")
    result.stdout.fnmatch_lines(["*test summary*", "PASS*test_pass_extra_reporting*"])


def test_pass_reporting_on_fail(testdir):
    testdir.makepyfile("def test_this(): assert 0")
    result = testdir.runpytest("-rp")
    result.stdout.no_fnmatch_line("*short test summary*")


def test_pass_output_reporting(testdir):
    testdir.makepyfile(
        """
        def setup_module():
            print("setup_module")

        def teardown_module():
            print("teardown_module")

        def test_pass_has_output():
            print("Four score and seven years ago...")

        def test_pass_no_output():
            pass
    """
    )
    result = testdir.runpytest()
    s = result.stdout.str()
    assert "test_pass_has_output" not in s
    assert "Four score and seven years ago..." not in s
    assert "test_pass_no_output" not in s
    result = testdir.runpytest("-rPp")
    result.stdout.fnmatch_lines(
        [
            "*= PASSES =*",
            "*_ test_pass_has_output _*",
            "*- Captured stdout setup -*",
            "setup_module",
            "*- Captured stdout call -*",
            "Four score and seven years ago...",
            "*- Captured stdout teardown -*",
            "teardown_module",
            "*= short test summary info =*",
            "PASSED test_pass_output_reporting.py::test_pass_has_output",
            "PASSED test_pass_output_reporting.py::test_pass_no_output",
            "*= 2 passed in *",
        ]
    )


def test_color_yes(testdir: Testdir, color_mapping) -> None:
    p1 = testdir.makepyfile(
        """
        def fail():
            assert 0, "multi-\\nline error"

        def test_this():
            fail()
        """
    )
    result = testdir.runpytest("--color=yes", str(p1))
    color_mapping.requires_ordered_markup(result)

    if pygments:
        exp_tb_lines = [
            "    {kw}def{hl-reset} {function}test_this{hl-reset}():",
            ">       fail()",
            "{bold}test_color_yes.py{reset}:5: ",
            "_ _ * _ _*",
            "",
            "    {kw}def{hl-reset} {function}fail{hl-reset}():",
            ">       {kw}assert{hl-reset} {number}0{hl-reset}, *{hl-reset}",
            "{bold}{red}E       AssertionError: multi-{reset}",
            "{bold}{red}E   {reset}      line error",
            "{bold}{red}E   {reset}    assert 0",
        ]
    else:
        exp_tb_lines = [
            "    def test_this():",
            ">       fail()",
            "",
            "{bold}test_color_yes.py{reset}:5: ",
            "_ _ * _ _*",
            "",
            "    def fail():",
            '>       assert 0, "multi-\\nline error"',
            "{bold}{red}E       AssertionError: multi-{reset}",
            "{bold}{red}E   {reset}      line error",
            "{bold}{red}E   {reset}    assert 0",
        ]
    result.stdout.fnmatch_lines(
        color_mapping.format_for_fnmatch(
            [
                "{bold}=*= test session starts =*={reset}",
                "collected 1 item",
                "",
                "test_color_yes.py {red}F{reset}{red} * [100%]{reset}",
                "",
                "=*= FAILURES =*=",
                "{red}{bold}_*_ test_this _*_{reset}",
                "",
            ]
            + exp_tb_lines
            + [
                "",
                "{bold}test_color_yes.py{reset}:2: AssertionError: multi-...",
                "{red}=*= {red}{bold}1 failed{reset}{red} in *s{reset}{red} =*={reset}",
            ]
        )
    )

    if pygments:
        exp_tb_lines = [
            "    {kw}assert{hl-reset} {number}0{hl-reset}, *",
            "{bold}{red}E   AssertionError: multi-{reset}",
            "{bold}{red}E   {reset}  line error",
            "{bold}{red}E   {reset}assert 0",
        ]
    else:
        exp_tb_lines = [
            "    assert 0, *",
            "{bold}{red}E   AssertionError: multi-{reset}",
            "{bold}{red}E   {reset}  line error",
            "{bold}{red}E   {reset}assert 0",
        ]

    result = testdir.runpytest("--color=yes", "--tb=short", str(p1))
    result.stdout.fnmatch_lines(
        color_mapping.format_for_fnmatch(
            [
                "{bold}=*= test session starts =*={reset}",
                "collected 1 item",
                "",
                "test_color_yes.py {red}F{reset}{red} * [100%]{reset}",
                "",
                "=*= FAILURES =*=",
                "{red}{bold}_*_ test_this _*_{reset}",
                "test_color_yes.py:5: in test_this",
                "    fail()",
                "test_color_yes.py:2: in fail",
            ]
            + exp_tb_lines
            + ["{red}=*= {red}{bold}1 failed{reset}{red} in *s{reset}{red} =*={reset}"]
        )
    )


def test_color_no(testdir):
    testdir.makepyfile("def test_this(): assert 1")
    result = testdir.runpytest("--color=no")
    assert "test session starts" in result.stdout.str()
    result.stdout.no_fnmatch_line("*\x1b[1m*")


@pytest.mark.parametrize("verbose", [True, False])
def test_color_yes_collection_on_non_atty(testdir, verbose):
    """skip collect progress report when working on non-terminals.
    #1397
    """
    testdir.makepyfile(
        """
        import pytest
        @pytest.mark.parametrize('i', range(10))
        def test_this(i):
            assert 1
    """
    )
    args = ["--color=yes"]
    if verbose:
        args.append("-vv")
    result = testdir.runpytest(*args)
    assert "test session starts" in result.stdout.str()
    assert "\x1b[1m" in result.stdout.str()
    result.stdout.no_fnmatch_line("*collecting 10 items*")
    if verbose:
        assert "collecting ..." in result.stdout.str()
    assert "collected 10 items" in result.stdout.str()


def test_getreportopt():
    from _pytest.terminal import _REPORTCHARS_DEFAULT

    class Config:
        class Option:
            reportchars = _REPORTCHARS_DEFAULT
            disable_warnings = False

        option = Option()

    config = Config()

    assert _REPORTCHARS_DEFAULT == "fE"

    # Default.
    assert getreportopt(config) == "wfE"

    config.option.reportchars = "sf"
    assert getreportopt(config) == "wsf"

    config.option.reportchars = "sfxw"
    assert getreportopt(config) == "sfxw"

    config.option.reportchars = "a"
    assert getreportopt(config) == "wsxXEf"

    config.option.reportchars = "N"
    assert getreportopt(config) == "w"

    config.option.reportchars = "NwfE"
    assert getreportopt(config) == "wfE"

    config.option.reportchars = "NfENx"
    assert getreportopt(config) == "wx"

    # Now with --disable-warnings.
    config.option.disable_warnings = True
    config.option.reportchars = "a"
    assert getreportopt(config) == "sxXEf"

    config.option.reportchars = "sfx"
    assert getreportopt(config) == "sfx"

    config.option.reportchars = "sfxw"
    assert getreportopt(config) == "sfx"

    config.option.reportchars = "a"
    assert getreportopt(config) == "sxXEf"

    config.option.reportchars = "A"
    assert getreportopt(config) == "PpsxXEf"

    config.option.reportchars = "AN"
    assert getreportopt(config) == ""

    config.option.reportchars = "NwfE"
    assert getreportopt(config) == "fE"


def test_terminalreporter_reportopt_addopts(testdir):
    testdir.makeini("[pytest]\naddopts=-rs")
    testdir.makepyfile(
        """
        import pytest

        @pytest.fixture
        def tr(request):
            tr = request.config.pluginmanager.getplugin("terminalreporter")
            return tr
        def test_opt(tr):
            assert tr.hasopt('skipped')
            assert not tr.hasopt('qwe')
    """
    )
    result = testdir.runpytest()
    result.stdout.fnmatch_lines(["*1 passed*"])


def test_tbstyle_short(testdir):
    p = testdir.makepyfile(
        """
        import pytest

        @pytest.fixture
        def arg(request):
            return 42
        def test_opt(arg):
            x = 0
            assert x
    """
    )
    result = testdir.runpytest("--tb=short")
    s = result.stdout.str()
    assert "arg = 42" not in s
    assert "x = 0" not in s
    result.stdout.fnmatch_lines(["*%s:8*" % p.basename, "    assert x", "E   assert*"])
    result = testdir.runpytest()
    s = result.stdout.str()
    assert "x = 0" in s
    assert "assert x" in s


def test_traceconfig(testdir):
    result = testdir.runpytest("--traceconfig")
    result.stdout.fnmatch_lines(["*active plugins*"])
    assert result.ret == ExitCode.NO_TESTS_COLLECTED


class TestGenericReporting:
    """ this test class can be subclassed with a different option
        provider to run e.g. distributed tests.
    """

    def test_collect_fail(self, testdir, option):
        testdir.makepyfile("import xyz\n")
        result = testdir.runpytest(*option.args)
        result.stdout.fnmatch_lines(
            ["ImportError while importing*", "*No module named *xyz*", "*1 error*"]
        )

    def test_maxfailures(self, testdir, option):
        testdir.makepyfile(
            """
            def test_1():
                assert 0
            def test_2():
                assert 0
            def test_3():
                assert 0
        """
        )
        result = testdir.runpytest("--maxfail=2", *option.args)
        if option.verbosity <= -1:
            result.stdout.fnmatch_lines(
                [
                    "*def test_1():*",
                    "*def test_2():*",
                    "2 failed in *s (stopping after 2 failures)",
                ]
            )
        else:
            result.stdout.fnmatch_lines(
                [
                    "*def test_1():*",
                    "*def test_2():*",
                    "*= 2 failed in *s (stopping after 2 failures) =*",
                ]
            )

    def test_maxfailures_veryquiet(self, testdir):
        testdir.makepyfile(
            """
            def test_1(): assert 0
            def test_2(): assert 0
        """
        )
        result = testdir.runpytest("-x", "-qq")
        result.stdout.fnmatch_lines(
            [
                "*def test_1():*",
                "test_maxfailures_veryquiet.py:1: assert 0",
                "!! stopping after 1 failure !!",
            ]
        )

    def test_maxfailures_with_interrupted(self, testdir):
        testdir.makepyfile(
            """
            def test(request):
                request.session.shouldstop = "session_interrupted"
                assert 0
        """
        )
        result = testdir.runpytest("--maxfail=1", "-ra")
        result.stdout.fnmatch_lines(
            [
                "*= short test summary info =*",
                "FAILED *",
                "*! session_interrupted !*",
                "*= 1 failed in *s (stopping after 1 failure) =*",
            ]
        )

    def test_tb_option(self, testdir, option):
        testdir.makepyfile(
            """
            import pytest
            def g():
                raise IndexError
            def test_func():
                print(6*7)
                g()  # --calling--
        """
        )
        for tbopt in ["long", "short", "no"]:
            print("testing --tb=%s..." % tbopt)
            result = testdir.runpytest("-rN", "--tb=%s" % tbopt)
            s = result.stdout.str()
            if tbopt == "long":
                assert "print(6*7)" in s
            else:
                assert "print(6*7)" not in s
            if tbopt != "no":
                assert "--calling--" in s
                assert "IndexError" in s
            else:
                assert "FAILURES" not in s
                assert "--calling--" not in s
                assert "IndexError" not in s

    def test_tb_crashline(self, testdir, option):
        p = testdir.makepyfile(
            """
            import pytest
            def g():
                raise IndexError
            def test_func1():
                print(6*7)
                g()  # --calling--
            def test_func2():
                assert 0, "hello"
        """
        )
        result = testdir.runpytest("--tb=line")
        bn = p.basename
        result.stdout.fnmatch_lines(
            ["*%s:3: IndexError*" % bn, "*%s:8: AssertionError: hello*" % bn]
        )
        s = result.stdout.str()
        assert "def test_func2" not in s

    def test_pytest_report_header(self, testdir, option):
        testdir.makeconftest(
            """
            def pytest_sessionstart(session):
                session.config._somevalue = 42
            def pytest_report_header(config):
                return "hello: %s" % config._somevalue
        """
        )
        testdir.mkdir("a").join("conftest.py").write(
            """
def pytest_report_header(config, startdir):
    return ["line1", str(startdir)]
"""
        )
        result = testdir.runpytest("a")
        result.stdout.fnmatch_lines(["*hello: 42*", "line1", str(testdir.tmpdir)])

    def test_show_capture(self, testdir):
        testdir.makepyfile(
            """
            import sys
            import logging
            def test_one():
                sys.stdout.write('!This is stdout!')
                sys.stderr.write('!This is stderr!')
                logging.warning('!This is a warning log msg!')
                assert False, 'Something failed'
        """
        )

        result = testdir.runpytest("--tb=short")
        result.stdout.fnmatch_lines(
            [
                "!This is stdout!",
                "!This is stderr!",
                "*WARNING*!This is a warning log msg!",
            ]
        )

        result = testdir.runpytest("--show-capture=all", "--tb=short")
        result.stdout.fnmatch_lines(
            [
                "!This is stdout!",
                "!This is stderr!",
                "*WARNING*!This is a warning log msg!",
            ]
        )

        stdout = testdir.runpytest("--show-capture=stdout", "--tb=short").stdout.str()
        assert "!This is stderr!" not in stdout
        assert "!This is stdout!" in stdout
        assert "!This is a warning log msg!" not in stdout

        stdout = testdir.runpytest("--show-capture=stderr", "--tb=short").stdout.str()
        assert "!This is stdout!" not in stdout
        assert "!This is stderr!" in stdout
        assert "!This is a warning log msg!" not in stdout

        stdout = testdir.runpytest("--show-capture=log", "--tb=short").stdout.str()
        assert "!This is stdout!" not in stdout
        assert "!This is stderr!" not in stdout
        assert "!This is a warning log msg!" in stdout

        stdout = testdir.runpytest("--show-capture=no", "--tb=short").stdout.str()
        assert "!This is stdout!" not in stdout
        assert "!This is stderr!" not in stdout
        assert "!This is a warning log msg!" not in stdout

    def test_show_capture_with_teardown_logs(self, testdir):
        """Ensure that the capturing of teardown logs honor --show-capture setting"""
        testdir.makepyfile(
            """
            import logging
            import sys
            import pytest

            @pytest.fixture(scope="function", autouse="True")
            def hook_each_test(request):
                yield
                sys.stdout.write("!stdout!")
                sys.stderr.write("!stderr!")
                logging.warning("!log!")

            def test_func():
                assert False
        """
        )

        result = testdir.runpytest("--show-capture=stdout", "--tb=short").stdout.str()
        assert "!stdout!" in result
        assert "!stderr!" not in result
        assert "!log!" not in result

        result = testdir.runpytest("--show-capture=stderr", "--tb=short").stdout.str()
        assert "!stdout!" not in result
        assert "!stderr!" in result
        assert "!log!" not in result

        result = testdir.runpytest("--show-capture=log", "--tb=short").stdout.str()
        assert "!stdout!" not in result
        assert "!stderr!" not in result
        assert "!log!" in result

        result = testdir.runpytest("--show-capture=no", "--tb=short").stdout.str()
        assert "!stdout!" not in result
        assert "!stderr!" not in result
        assert "!log!" not in result


@pytest.mark.xfail("not hasattr(os, 'dup')")
def test_fdopen_kept_alive_issue124(testdir):
    testdir.makepyfile(
        """
        import os, sys
        k = []
        def test_open_file_and_keep_alive(capfd):
            stdout = os.fdopen(1, 'w', 1)
            k.append(stdout)

        def test_close_kept_alive_file():
            stdout = k.pop()
            stdout.close()
    """
    )
    result = testdir.runpytest()
    result.stdout.fnmatch_lines(["*2 passed*"])


def test_tbstyle_native_setup_error(testdir):
    testdir.makepyfile(
        """
        import pytest
        @pytest.fixture
        def setup_error_fixture():
            raise Exception("error in exception")

        def test_error_fixture(setup_error_fixture):
            pass
    """
    )
    result = testdir.runpytest("--tb=native")
    result.stdout.fnmatch_lines(
        ['*File *test_tbstyle_native_setup_error.py", line *, in setup_error_fixture*']
    )


def test_terminal_summary(testdir):
    testdir.makeconftest(
        """
        def pytest_terminal_summary(terminalreporter, exitstatus):
            w = terminalreporter
            w.section("hello")
            w.line("world")
            w.line("exitstatus: {0}".format(exitstatus))
    """
    )
    result = testdir.runpytest()
    result.stdout.fnmatch_lines(
        """
        *==== hello ====*
        world
        exitstatus: 5
    """
    )


@pytest.mark.filterwarnings("default")
def test_terminal_summary_warnings_are_displayed(testdir):
    """Test that warnings emitted during pytest_terminal_summary are displayed.
    (#1305).
    """
    testdir.makeconftest(
        """
        import warnings
        def pytest_terminal_summary(terminalreporter):
            warnings.warn(UserWarning('internal warning'))
    """
    )
    testdir.makepyfile(
        """
        def test_failure():
            import warnings
            warnings.warn("warning_from_" + "test")
            assert 0
    """
    )
    result = testdir.runpytest("-ra")
    result.stdout.fnmatch_lines(
        [
            "*= warnings summary [[]runtest[]] =*",
            "*warning_from_test*",
            "-- Docs: *",
            "*= short test summary info =*",
            "*= warnings summary (final) [[]config[]] =*",
            "conftest.py:3",
            "    warnings.warn(UserWarning('internal warning'))",
            "  UserWarning: internal warning",
            "-- Docs: *",
            "*== 1 failed, 2 warnings in *",
        ]
    )
    result.stdout.no_fnmatch_line("*None*")
    stdout = result.stdout.str()
    assert stdout.count("warning_from_test") == 1
    assert stdout.count("=== warnings summary ") == 2
    assert stdout.count(" 1 failed, 2 warnings ") == 1
    assert result.ret == 1

    result = testdir.runpytest("--disable-warnings")
    stdout = result.stdout.str()
    assert stdout.count("warning_from_test") == 0
    assert stdout.count("=== warnings summary ") == 0
    assert stdout.count(" 1 failed, 2 warnings ") == 1
    assert result.ret == 1


@pytest.mark.filterwarnings("default")
def test_terminal_summary_warnings_header_once(testdir):
    testdir.makepyfile(
        """
        def test_failure():
            import warnings
            warnings.warn("warning_from_" + "test")
            assert 0
    """
    )
    result = testdir.runpytest("-ra")
    result.stdout.fnmatch_lines(
        [
            "*= warnings summary [[]runtest[]] =*",
            "*warning_from_test*",
            "*= short test summary info =*",
            "*== 1 failed, 1 warning in *",
        ]
    )
    result.stdout.no_fnmatch_line("*None*")
    stdout = result.stdout.str()
    assert stdout.count("warning_from_test") == 1
    assert stdout.count("=== warnings summary ") == 1


@pytest.fixture(scope="session")
def tr() -> TerminalReporter:
    config = _pytest.config._prepareconfig([])
    return TerminalReporter(config)


@pytest.mark.parametrize(
    "exp_color, exp_line, stats_arg",
    [
        # The method under test only cares about the length of each
        # dict value, not the actual contents, so tuples of anything
        # suffice
        # Important statuses -- the highest priority of these always wins
        ("red", [("1 failed", {"bold": True, "red": True})], {"failed": (1,)}),
        (
            "red",
            [
                ("1 failed", {"bold": True, "red": True}),
                ("1 passed", {"bold": False, "green": True}),
            ],
            {"failed": (1,), "passed": (1,)},
        ),
        ("red", [("1 error", {"bold": True, "red": True})], {"error": (1,)}),
        ("red", [("2 errors", {"bold": True, "red": True})], {"error": (1, 2)}),
        (
            "red",
            [
                ("1 passed", {"bold": False, "green": True}),
                ("1 error", {"bold": True, "red": True}),
            ],
            {"error": (1,), "passed": (1,)},
        ),
        # (a status that's not known to the code)
        ("yellow", [("1 weird", {"bold": True, "yellow": True})], {"weird": (1,)}),
        (
            "yellow",
            [
                ("1 passed", {"bold": False, "green": True}),
                ("1 weird", {"bold": True, "yellow": True}),
            ],
            {"weird": (1,), "passed": (1,)},
        ),
        ("yellow", [("1 warning", {"bold": True, "yellow": True})], {"warnings": (1,)}),
        (
            "yellow",
            [
                ("1 passed", {"bold": False, "green": True}),
                ("1 warning", {"bold": True, "yellow": True}),
            ],
            {"warnings": (1,), "passed": (1,)},
        ),
        (
            "green",
            [("5 passed", {"bold": True, "green": True})],
            {"passed": (1, 2, 3, 4, 5)},
        ),
        # "Boring" statuses.  These have no effect on the color of the summary
        # line.  Thus, if *every* test has a boring status, the summary line stays
        # at its default color, i.e. yellow, to warn the user that the test run
        # produced no useful information
        ("yellow", [("1 skipped", {"bold": True, "yellow": True})], {"skipped": (1,)}),
        (
            "green",
            [
                ("1 passed", {"bold": True, "green": True}),
                ("1 skipped", {"bold": False, "yellow": True}),
            ],
            {"skipped": (1,), "passed": (1,)},
        ),
        (
            "yellow",
            [("1 deselected", {"bold": True, "yellow": True})],
            {"deselected": (1,)},
        ),
        (
            "green",
            [
                ("1 passed", {"bold": True, "green": True}),
                ("1 deselected", {"bold": False, "yellow": True}),
            ],
            {"deselected": (1,), "passed": (1,)},
        ),
        ("yellow", [("1 xfailed", {"bold": True, "yellow": True})], {"xfailed": (1,)}),
        (
            "green",
            [
                ("1 passed", {"bold": True, "green": True}),
                ("1 xfailed", {"bold": False, "yellow": True}),
            ],
            {"xfailed": (1,), "passed": (1,)},
        ),
        ("yellow", [("1 xpassed", {"bold": True, "yellow": True})], {"xpassed": (1,)}),
        (
            "yellow",
            [
                ("1 passed", {"bold": False, "green": True}),
                ("1 xpassed", {"bold": True, "yellow": True}),
            ],
            {"xpassed": (1,), "passed": (1,)},
        ),
        # Likewise if no tests were found at all
        ("yellow", [("no tests ran", {"yellow": True})], {}),
        # Test the empty-key special case
        ("yellow", [("no tests ran", {"yellow": True})], {"": (1,)}),
        (
            "green",
            [("1 passed", {"bold": True, "green": True})],
            {"": (1,), "passed": (1,)},
        ),
        # A couple more complex combinations
        (
            "red",
            [
                ("1 failed", {"bold": True, "red": True}),
                ("2 passed", {"bold": False, "green": True}),
                ("3 xfailed", {"bold": False, "yellow": True}),
            ],
            {"passed": (1, 2), "failed": (1,), "xfailed": (1, 2, 3)},
        ),
        (
            "green",
            [
                ("1 passed", {"bold": True, "green": True}),
                ("2 skipped", {"bold": False, "yellow": True}),
                ("3 deselected", {"bold": False, "yellow": True}),
                ("2 xfailed", {"bold": False, "yellow": True}),
            ],
            {
                "passed": (1,),
                "skipped": (1, 2),
                "deselected": (1, 2, 3),
                "xfailed": (1, 2),
            },
        ),
    ],
)
def test_summary_stats(
    tr: TerminalReporter,
    exp_line: List[Tuple[str, Dict[str, bool]]],
    exp_color: str,
    stats_arg: Dict[str, List],
) -> None:
    tr.stats = stats_arg

    # Fake "_is_last_item" to be True.
    class fake_session:
        testscollected = 0

    tr._session = fake_session  # type: ignore[assignment]
    assert tr._is_last_item

    # Reset cache.
    tr._main_color = None

    print("Based on stats: %s" % stats_arg)
    print('Expect summary: "{}"; with color "{}"'.format(exp_line, exp_color))
    (line, color) = tr.build_summary_stats_line()
    print('Actually got:   "{}"; with color "{}"'.format(line, color))
    assert line == exp_line
    assert color == exp_color


def test_skip_counting_towards_summary(tr):
    class DummyReport(BaseReport):
        count_towards_summary = True

    r1 = DummyReport()
    r2 = DummyReport()
    tr.stats = {"failed": (r1, r2)}
    tr._main_color = None
    res = tr.build_summary_stats_line()
    assert res == ([("2 failed", {"bold": True, "red": True})], "red")

    r1.count_towards_summary = False
    tr.stats = {"failed": (r1, r2)}
    tr._main_color = None
    res = tr.build_summary_stats_line()
    assert res == ([("1 failed", {"bold": True, "red": True})], "red")


class TestClassicOutputStyle:
    """Ensure classic output style works as expected (#3883)"""

    @pytest.fixture
    def test_files(self, testdir):
        testdir.makepyfile(
            **{
                "test_one.py": "def test_one(): pass",
                "test_two.py": "def test_two(): assert 0",
                "sub/test_three.py": """
                    def test_three_1(): pass
                    def test_three_2(): assert 0
                    def test_three_3(): pass
                """,
            }
        )

    def test_normal_verbosity(self, testdir, test_files):
        result = testdir.runpytest("-o", "console_output_style=classic")
        result.stdout.fnmatch_lines(
            [
                "test_one.py .",
                "test_two.py F",
                "sub{}test_three.py .F.".format(os.sep),
                "*2 failed, 3 passed in*",
            ]
        )

    def test_verbose(self, testdir, test_files):
        result = testdir.runpytest("-o", "console_output_style=classic", "-v")
        result.stdout.fnmatch_lines(
            [
                "test_one.py::test_one PASSED",
                "test_two.py::test_two FAILED",
                "sub{}test_three.py::test_three_1 PASSED".format(os.sep),
                "sub{}test_three.py::test_three_2 FAILED".format(os.sep),
                "sub{}test_three.py::test_three_3 PASSED".format(os.sep),
                "*2 failed, 3 passed in*",
            ]
        )

    def test_quiet(self, testdir, test_files):
        result = testdir.runpytest("-o", "console_output_style=classic", "-q")
        result.stdout.fnmatch_lines([".F.F.", "*2 failed, 3 passed in*"])


class TestProgressOutputStyle:
    @pytest.fixture
    def many_tests_files(self, testdir):
        testdir.makepyfile(
            test_bar="""
                import pytest
                @pytest.mark.parametrize('i', range(10))
                def test_bar(i): pass
            """,
            test_foo="""
                import pytest
                @pytest.mark.parametrize('i', range(5))
                def test_foo(i): pass
            """,
            test_foobar="""
                import pytest
                @pytest.mark.parametrize('i', range(5))
                def test_foobar(i): pass
            """,
        )

    @pytest.fixture
    def progress_files_non_verbose(self, testdir: Testdir) -> None:
        testdir.makepyfile(
            test_more_than_width="""
                import pytest
                @pytest.mark.parametrize('i', range(100))
                def test_more_than_width(i): pass
            """,
        )

    def test_zero_tests_collected(self, testdir):
        """Some plugins (testmon for example) might issue pytest_runtest_logreport without any tests being
        actually collected (#2971)."""
        testdir.makeconftest(
            """
        def pytest_collection_modifyitems(items, config):
            from _pytest.runner import CollectReport
            for node_id in ('nodeid1', 'nodeid2'):
                rep = CollectReport(node_id, 'passed', None, None)
                rep.when = 'passed'
                rep.duration = 0.1
                config.hook.pytest_runtest_logreport(report=rep)
        """
        )
        output = testdir.runpytest()
        output.stdout.no_fnmatch_line("*ZeroDivisionError*")
        output.stdout.fnmatch_lines(["=* 2 passed in *="])

    def test_normal(self, many_tests_files, progress_files_non_verbose, testdir):
        output = testdir.runpytest()
        output.stdout.fnmatch_lines(
            [
                "test_bar.py ..........                                                   [[]  8%[]]",
                "test_foo.py .....                                                        [[] 12%[]]",
                "test_foobar.py .....                                                     [[] 16%[]]",
                "test_more_than_width.py ................................................ [[] 56%[]]",
                "....................................................                     [[]100%[]]",
                "*= 120 passed in *",
            ]
        )

    def test_same_nodeids(self, testdir: Testdir, color_mapping) -> None:
        p1 = testdir.makeconftest(
            """
            def pytest_collection_modifyitems(items):
                for item in items[1:]:
                    item._nodeid = items[0].nodeid
            """
        )
        p1 = testdir.makepyfile(
            """
            import pytest

            @pytest.fixture
            def err_setup():
                assert 0, "setup-error"

            @pytest.fixture
            def err_teardown():
                yield
                assert 0, "teardown-error"

            def test1(err_setup): pass
            def test2(err_teardown): pass
            def test3(): pass
            def test4(): pass
            """
        )
        result = testdir.runpytest("-v", str(p1))
        result.stdout.fnmatch_lines(
            color_mapping.format_for_fnmatch(
                [
                    "test_same_nodeids.py::test1 ERROR  * [ 25%]",
                    "test_same_nodeids.py::test1 PASSED * [ 50%]",
                    "test_same_nodeids.py::test1 ERROR  * [ 50%]",
                    "test_same_nodeids.py::test1 PASSED * [ 75%]",
                    "test_same_nodeids.py::test1 PASSED * [100%]",
                ]
            )
        )

    def test_skipped(self, testdir: Testdir) -> None:
        p1 = testdir.makepyfile(
            """
            import pytest

            n = 0

            @pytest.fixture
            def skip_in_setup():
                global n
                n += 1
                if n % 2:
                    pytest.skip("...")
                yield


            @pytest.mark.parametrize("n", range(5))
            def test(n, skip_in_setup):
                pass
            """
        )

        result = testdir.runpytest(p1)
        assert result.ret == 0
        result.stdout.fnmatch_lines(
            [
                "test_skipped.py s.s.s * [[]100%[]]",
                "*= 2 passed, 3 skipped in*",
            ]
        )

    def test_colored_progress(self, testdir, monkeypatch, color_mapping):
        monkeypatch.setenv("PY_COLORS", "1")
        testdir.makepyfile(
            test_axfail="""
                import pytest
                @pytest.mark.xfail
                def test_axfail(): assert 0
            """,
            test_bar="""
                import pytest
                @pytest.mark.parametrize('i', range(10))
                def test_bar(i): pass
            """,
            test_foo="""
                import pytest
                import warnings
                @pytest.mark.parametrize('i', range(5))
                def test_foo(i):
                    warnings.warn(DeprecationWarning("collection"))
                    pass
            """,
            test_foobar="""
                import pytest
                @pytest.mark.parametrize('i', range(5))
                def test_foobar(i): raise ValueError()
            """,
        )
        result = testdir.runpytest()
        result.stdout.re_match_lines(
            color_mapping.format_for_rematch(
                [
                    r"test_axfail.py {yellow}x{reset}{green} \s+ \[  4%\]{reset}",
                    r"test_bar.py ({green}\.{reset}){{10}}{green} \s+ \[ 52%\]{reset}",
                    r"test_foo.py ({green}\.{reset}){{5}}{yellow} \s+ \[ 76%\]{reset}",
                    r"test_foobar.py ({red}F{reset}){{5}}{red} \s+ \[100%\]{reset}",
                ]
            )
        )

        # Only xfail should have yellow progress indicator.
        result = testdir.runpytest("test_axfail.py")
        result.stdout.re_match_lines(
            color_mapping.format_for_rematch(
                [
                    r"test_axfail.py {yellow}x{reset}{yellow} \s+ \[100%\]{reset}",
                    r"^{yellow}=+ ({yellow}{bold}|{bold}{yellow})1 xfailed{reset}{yellow} in ",
                ]
            )
        )

    def test_count(self, many_tests_files, progress_files_non_verbose, testdir):
        testdir.makeini(
            """
            [pytest]
            console_output_style = count
        """
        )
        output = testdir.runpytest()
        output.stdout.fnmatch_lines(
            [
                "test_bar.py ..........                                                [[] 10/120[]]",
                "test_foo.py .....                                                     [[] 15/120[]]",
                "test_foobar.py .....                                                  [[] 20/120[]]",
                "test_more_than_width.py ............................................. [[] 65/120[]]",
                ".......................................................               [[]120/120[]]",
                "*= 120 passed in *",
            ]
        )

    def test_verbose(self, many_tests_files, testdir):
        output = testdir.runpytest("-v")
        output.stdout.re_match_lines(
            [
                r"test_bar.py::test_bar\[0\] PASSED \s+ \[  5%\]",
                r"test_foo.py::test_foo\[4\] PASSED \s+ \[ 75%\]",
                r"test_foobar.py::test_foobar\[4\] PASSED \s+ \[100%\]",
            ]
        )

    def test_verbose_count(self, many_tests_files, testdir):
        testdir.makeini(
            """
            [pytest]
            console_output_style = count
        """
        )
        output = testdir.runpytest("-v")
        output.stdout.re_match_lines(
            [
                r"test_bar.py::test_bar\[0\] PASSED \s+ \[ 1/20\]",
                r"test_foo.py::test_foo\[4\] PASSED \s+ \[15/20\]",
                r"test_foobar.py::test_foobar\[4\] PASSED \s+ \[20/20\]",
            ]
        )

    @pytest.mark.xdist_specific
    def test_xdist_normal(self, many_tests_files, testdir: "Testdir") -> None:
        pytest.importorskip("xdist")
        output = testdir.runpytest("-pxdist", "-n2")
        output.stdout.re_match_lines([r"\.{20} \s+ \[100%\]"])

    @pytest.mark.xdist_specific
    def test_xdist_normal_count(self, many_tests_files, testdir: "Testdir") -> None:
        pytest.importorskip("xdist")
        testdir.makeini(
            """
            [pytest]
            console_output_style = count
        """
        )
        output = testdir.runpytest("-pxdist", "-n2")
        output.stdout.re_match_lines([r"\.{20} \s+ \[20/20\]"])

    @pytest.mark.xdist_specific
    def test_xdist_verbose(self, many_tests_files, testdir: "Testdir") -> None:
        pytest.importorskip("xdist")
        output = testdir.runpytest("-pxdist", "-n2", "-v")
        output.stdout.re_match_lines_random(
            [
                r"\[gw\d\] \[\s*\d+%\] PASSED test_bar.py::test_bar\[1\]",
                r"\[gw\d\] \[\s*\d+%\] PASSED test_foo.py::test_foo\[1\]",
                r"\[gw\d\] \[\s*\d+%\] PASSED test_foobar.py::test_foobar\[1\]",
            ]
        )
        output.stdout.fnmatch_lines_random(
            [
                line.translate(TRANS_FNMATCH)
                for line in [
                    "test_bar.py::test_bar[0] ",
                    "test_foo.py::test_foo[0] ",
                    "test_foobar.py::test_foobar[0] ",
                    "[gw?] [  5%] PASSED test_*[?] ",
                    "[gw?] [ 10%] PASSED test_*[?] ",
                    "[gw?] [ 55%] PASSED test_*[?] ",
                    "[gw?] [ 60%] PASSED test_*[?] ",
                    "[gw?] [ 95%] PASSED test_*[?] ",
                    "[gw?] [100%] PASSED test_*[?] ",
                ]
            ]
        )

    def test_capture_no(self, many_tests_files, testdir):
        output = testdir.runpytest("-s")
        output.stdout.re_match_lines(
            [r"test_bar.py \.{10}", r"test_foo.py \.{5}", r"test_foobar.py \.{5}"]
        )

        output = testdir.runpytest("--capture=no")
        output.stdout.no_fnmatch_line("*%]*")


class TestProgressWithTeardown:
    """Ensure we show the correct percentages for tests that fail during teardown (#3088)"""

    @pytest.fixture
    def contest_with_teardown_fixture(self, testdir):
        testdir.makeconftest(
            """
            import pytest

            @pytest.fixture
            def fail_teardown():
                yield
                assert False
        """
        )

    @pytest.fixture
    def many_files(self, testdir, contest_with_teardown_fixture):
        testdir.makepyfile(
            test_bar="""
                import pytest
                @pytest.mark.parametrize('i', range(5))
                def test_bar(fail_teardown, i):
                    pass
            """,
            test_foo="""
                import pytest
                @pytest.mark.parametrize('i', range(15))
                def test_foo(fail_teardown, i):
                    pass
            """,
        )

    def test_teardown_simple(self, testdir, contest_with_teardown_fixture):
        testdir.makepyfile(
            """
            def test_foo(fail_teardown):
                pass
        """
        )
        output = testdir.runpytest()
        output.stdout.re_match_lines([r"test_teardown_simple.py \.E\s+\[100%\]"])

    @pytest.mark.pypy_specific
    def test_teardown_with_test_also_failing(
        self, testdir, contest_with_teardown_fixture
    ):
        testdir.makepyfile(
            """
            def test_foo(fail_teardown):
                assert 0
        """
        )
        output = testdir.runpytest("-rfE")
        output.stdout.fnmatch_lines(
            [
                "test_teardown_with_test_also_failing.py FE * [[]100%[]]",
                "FAILED test_teardown_with_test_also_failing.py:2::test_foo - assert 0",
                # TODO: fix location for/with PyPy
                "ERROR test_teardown_with_test_also_failing.py::test_foo ({}) - assert False".format(
                    "*/lib_pypy/_functools.py:*"
                    if hasattr(sys, "pypy_version_info")
                    else "conftest.py:6"
                ),
            ]
        )

    def test_teardown_many(self, testdir, many_files):
        output = testdir.runpytest()
        output.stdout.re_match_lines(
            [r"test_bar.py (\.E){5}\s+\[ 25%\]", r"test_foo.py (\.E){15}\s+\[100%\]"]
        )

    def test_teardown_many_verbose(
        self, testdir: Testdir, many_files, color_mapping
    ) -> None:
        result = testdir.runpytest("-v")
        result.stdout.fnmatch_lines(
            color_mapping.format_for_fnmatch(
                [
                    "test_bar.py::test_bar[0] PASSED  * [  5%]",
                    "test_bar.py::test_bar[0] ERROR   * [  5%]",
                    "test_bar.py::test_bar[4] PASSED  * [ 25%]",
                    "test_foo.py::test_foo[14] PASSED * [100%]",
                    "test_foo.py::test_foo[14] ERROR  * [100%]",
                    "=* 20 passed, 20 errors in *",
                ]
            )
        )

    @pytest.mark.xdist_specific
    def test_xdist_normal(self, many_files, testdir: "Testdir") -> None:
        pytest.importorskip("xdist")
        output = testdir.runpytest("-pxdist", "-n2")
        output.stdout.re_match_lines([r"[\.E]{40} \s+ \[100%\]"])


def test_skip_reasons_folding():
    path = "xyz"
    lineno = 3
    message = "justso"
    longrepr = (path, lineno, message)

    class X:
        pass

    ev1 = X()
    ev1.when = "execute"
    ev1.skipped = True
    ev1.longrepr = longrepr

    ev2 = X()
    ev2.when = "execute"
    ev2.longrepr = longrepr
    ev2.skipped = True

    # ev3 might be a collection report
    ev3 = X()
    ev3.when = "collect"
    ev3.longrepr = longrepr
    ev3.skipped = True

    values = _folded_skips([ev1, ev2, ev3])
    assert len(values) == 1
    num, fspath, lineno, reason = values[0]
    assert num == 3
    assert fspath == path
    assert lineno == lineno
    assert reason == message


def test_line_with_reprcrash(monkeypatch):
    from wcwidth import wcswidth

    import _pytest.terminal

    mocked_verbose_word = "FAILED"

    mocked_pos = "some::nodeid"

    def mock_get_pos(*args):
        return mocked_pos

    monkeypatch.setattr(_pytest.terminal, "_get_pos", mock_get_pos)

    class config:
        pass

    class rep:
        def _get_verbose_word(self, *args):
            return mocked_verbose_word

        class longrepr:
            class reprcrash:
                pass

    def check(msg, width, expected):
        __tracebackhide__ = True
        if msg:
            rep.longrepr.reprcrash = ReprFileLocation("path", "lineno", msg)
        actual = _get_line_with_reprcrash_message(config, rep(), width)

        assert actual == expected
        if actual != "{} {}".format(mocked_verbose_word, mocked_pos):
            assert wcswidth(actual) <= width

    # AttributeError with message
    check(None, 80, "FAILED some::nodeid")

    check("msg", 80, "FAILED some::nodeid - msg")
    check("msg", 3, "FAILED some::nodeid")

    check("msg", 24, "FAILED some::nodeid")
    check("msg", 25, "FAILED some::nodeid - msg")

    check("some longer msg", 24, "FAILED some::nodeid")
    check("some longer msg", 25, "FAILED some::nodeid - ...")
    check("some longer msg", 26, "FAILED some::nodeid - s...")

    check("some\nmessage", 25, "FAILED some::nodeid - ...")
    check("some\nmessage", 26, "FAILED some::nodeid - s...")
    check("some\nmessage", 80, "FAILED some::nodeid - some\\nmessage")
    check("some\r\nmessage", 80, "FAILED some::nodeid - some\\r\\nmessage")
    check("\r\nsome\r\nmessage", 80, "FAILED some::nodeid - \\r\\nsome\\r\\nmessage")
    check("\nsome\r\nmessage", 80, "FAILED some::nodeid - \\nsome\\r\\nmessage")

    # Test unicode safety.
    check("😄😄😄😄😄\n2nd line", 25, "FAILED some::nodeid - ...")
    check("😄😄😄😄😄\n2nd line", 26, "FAILED some::nodeid - ...")
    check("😄😄😄😄😄\n2nd line", 27, "FAILED some::nodeid - 😄...")
    check("😄😄😄😄😄\n2nd line", 28, "FAILED some::nodeid - 😄...")
    check("😄😄😄😄😄\n2nd line", 29, "FAILED some::nodeid - 😄😄...")

    # Color escape codes.
    check("with some truncated \x1b[31mcolor", 29, "FAILED some::nodeid - 'wit...")
    check("with \x1b[31mcolor", 30, "FAILED some::nodeid - 'with...")
    check("with \x1b[31mcolor", 50, "FAILED some::nodeid - 'with \\x1b[31mcolor'")
    # Non-printable (kept).
    check("with \0NULL", 29, "FAILED some::nodeid - with...")
    check("with \0NULL", 30, "FAILED some::nodeid - with ...")
    check("with \0NULL", 31, "FAILED some::nodeid - with \0NULL")
    # Non-printable (via repr).
    check("with \bBS", 25, "FAILED some::nodeid - ...")
    check("with \bBS", 50, "FAILED some::nodeid - 'with \\x08BS'")

    # NOTE: constructed, not sure if this is supported.
    mocked_pos = "nodeid::😄::withunicode"
    check("😄😄😄😄😄\n2nd line", 29, "FAILED nodeid::😄::withunicode")
    check("😄😄😄😄😄\n2nd line", 40, "FAILED nodeid::😄::withunicode - 😄😄...")
    check("😄😄😄😄😄\n2nd line", 41, "FAILED nodeid::😄::withunicode - 😄😄...")
    check("😄😄😄😄😄\n2nd line", 42, "FAILED nodeid::😄::withunicode - 😄😄😄...")
    check("😄😄😄😄😄\n2nd line", 80, "FAILED nodeid::😄::withunicode - 😄😄😄😄😄\\n2nd line")


def test__get_pos() -> None:
    rep = TestReport(
        "nodeid_without_testname",
        location=("loc", 1, ""),
        keywords=(),
        outcome="failed",
        longrepr=None,
        when="call",
    )

    class config:
        class option:
            fulltrace = False

        def cwd_relative_nodeid(nodeid):
            assert nodeid == rep.nodeid
            return nodeid

    def check(config: object, rep: object) -> str:
        return _get_pos(config, rep)  # type: ignore[arg-type]

    assert check(config, rep) == "nodeid_without_testname"
    rep.nodeid = "path::testname"
    assert not rep.longrepr
    assert check(config, rep) == "path::testname"

    class longrepr:
        reprcrash = ReprFileLocation(path="path", lineno=2, message="msg")

    rep.longrepr = longrepr  # type: ignore[assignment]
    config.invocation_dir = py.path.local()  # type: ignore[attr-defined]
    assert check(config, rep) == "path:2::testname"

    # Windows path with different path as in nodeid.
    assert rep.longrepr
    rep.longrepr.reprcrash.path = r"windows\path.py"
    assert check(config, rep) == r"path::testname (windows\path.py:2)"
    # lineno=None
    rep.longrepr.reprcrash.lineno = None
    assert check(config, rep) == r"path::testname (windows\path.py)"
    # lineno=0
    rep.longrepr.reprcrash.lineno = 0
    assert check(config, rep) == r"path::testname (windows\path.py:0)"

    # Windows path with same path as in nodeid.
    rep.longrepr.reprcrash.lineno = 2
    rep.nodeid = "windows/path.py::testname"
    rep.longrepr.reprcrash.path = r"windows\path.py"
    assert check(config, rep) == "windows/path.py:2::testname"
    # lineno=None
    rep.longrepr.reprcrash.lineno = None
    assert check(config, rep) == "windows/path.py::testname"
    # lineno=0
    rep.longrepr.reprcrash.lineno = 0
    assert check(config, rep) == "windows/path.py:0::testname"


def test_crash_during_collection(testdir, monkeypatch) -> None:
    from pluggy import hooks

    def crash(obj):
        raise Exception("crash")

    monkeypatch.setattr("_pytest.python.safe_isclass", crash)

    p1 = testdir.makepyfile("def test_pass(): pass")
    result = testdir.runpytest(str(p1))
    result.stdout.fnmatch_lines(
        [
            "collected 0 items / 1 error",
            "",
            "*= ERRORS =*",
            "*_ ERROR collecting test_crash_during_collection.py _*",
            # XXX: shouldn't be cut off here.
            "{}:*: in __call__".format(hooks.__file__),
            "    return self._hookexec(self, self.get_hookimpls(), kwargs)",
        ],
        consecutive=True,
    )

    lnum = crash.__code__.co_firstlineno + 1
    result.stdout.fnmatch_lines(
        [
            "{}:{}: in crash".format(__file__, lnum),
            '    raise Exception("crash")',
            "E   Exception: crash",
            "*= short test summary info =*",
            "ERROR collecting test_crash_during_collection.py ({}:{}) - Exception: crash".format(
                __file__, lnum
            ),
            "*! Interrupted: 1 error during collection !*",
            "*= 1 error in *",
        ]
    )


@pytest.mark.parametrize("ci", (None, "true"))
def test_summary_with_nonprintable(ci, testdir: Testdir) -> None:
    testdir.monkeypatch.setattr("_pytest.terminal.get_terminal_width", lambda: 99)
    if ci:
        testdir.monkeypatch.setenv("CI", ci)
        expected = r"'AssertionError: \x1b[31mred\x00\x08!!\nassert 0'"
    else:
        testdir.monkeypatch.delenv("CI", raising=False)
        expected = r"'AssertionError: \x1b[31mred\x00\x08!!\nasser..."
    p1 = testdir.makepyfile(r"def test(): assert 0, '\x1b[31mred\0\b!!'")
    result = testdir.runpytest("-rf", str(p1), tty=True)
    result.stdout.fnmatch_lines(
        [
            "test_summary_with_nonprintable.py:1: AssertionError: \x1b[31mred\0\b!!...",
            "*= short test summary info =*",
            "FAILED test_summary_with_nonprintable.py:1::test - " + expected,
            "*= 1 failed in *=",
        ]
    )


@pytest.mark.parametrize("arg", (None, "--tb=native", "--full-trace"))
def test_failed_pos(arg, testdir):
    p1 = testdir.makepyfile("def test(): assert 0")
    args = ("-ra", str(p1))
    if arg:
        args += (arg,)
    result = testdir.runpytest(*args)
    if arg == "--tb=native":
        result.stdout.fnmatch_lines(
            [
                "*= FAILURES =*",
                "*_ test _*",
                "    def test(): assert 0",
                "AssertionError: assert 0",
                "*= short test summary info =*",
                "FAILED test_failed_pos.py:1::test - assert 0",
                "*= 1 failed in *",
            ]
        )
    else:
        result.stdout.fnmatch_lines(
            [
                "*= FAILURES =*",
                "*_ test _*",
                ">   def test(): assert 0",
                "E   assert 0",
                "test_failed_pos.py:1: assert 0",
                "*= short test summary info =*",
                "FAILED test_failed_pos.py:1::test - assert 0",
                "*= 1 failed in *",
            ]
        )


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (10.0, "10.00s"),
        (10.34, "10.34s"),
        (59.99, "59.99s"),
        (60.55, "60.55s (0:01:00)"),
        (123.55, "123.55s (0:02:03)"),
        (60 * 60 + 0.5, "3600.50s (1:00:00)"),
    ],
)
def test_format_session_duration(seconds, expected):
    from _pytest.terminal import format_session_duration

    assert format_session_duration(seconds) == expected


def test_collecterror(testdir):
    p1 = testdir.makepyfile("raise SyntaxError()")
    result = testdir.runpytest("-ra", str(p1))
    result.stdout.fnmatch_lines(
        [
            "collected 0 items / 1 error",
            "*= ERRORS =*",
            "*_ ERROR collecting test_collecterror.py _*",
            "E   SyntaxError: *",
            "*= short test summary info =*",
            "ERROR collecting test_collecterror.py",
            "*! Interrupted: 1 error during collection !*",
            "*= 1 error in *",
        ]
    )


def test_getdimensions(monkeypatch):
    import _pytest.terminal
    from _pytest.terminal import _getdimensions
    from _pytest.terminal import get_terminal_width

    monkeypatch.setattr(_pytest.terminal, "_cached_terminal_width", None)
    monkeypatch.setenv("COLUMNS", "30")
    monkeypatch.setenv("LINES", "25")

    assert _getdimensions() == (30, 25)
    assert get_terminal_width() == 30

    calls = []

    def mocked_get_terminal_size(*args):
        calls.append(args)
        raise OSError()

    monkeypatch.setattr(os, "get_terminal_size", mocked_get_terminal_size)

    monkeypatch.delenv("COLUMNS")
    monkeypatch.delenv("LINES")
    assert _getdimensions() == (80, 24)
    assert calls == [(0,), (2,), (1,)]

    def mocked_get_terminal_size(fileno):
        calls.append(fileno)
        if fileno == 2:
            return os.terminal_size((12, 34))
        raise OSError()

    monkeypatch.setattr(os, "get_terminal_size", mocked_get_terminal_size)

    # Ignores sizes with columns or lines being 0.
    calls = []
    assert _getdimensions() == (12, 34)
    assert calls == [0, 2]

    def mocked_get_terminal_size(fileno):
        calls.append(fileno)
        return os.terminal_size((0, 0))
        raise OSError()

    monkeypatch.setattr(os, "get_terminal_size", mocked_get_terminal_size)

    calls = []
    assert _getdimensions() == (80, 24)
    assert calls == [0, 2, 1]

    # Simulate SIGWINCH not being available.
    calls = []
    monkeypatch.setattr("_pytest.terminal._cached_terminal_width_sighandler", False)
    assert get_terminal_width() == 80
    assert calls == [0, 2, 1]

    # Do not mess with the terminal plugin.
    monkeypatch.undo()


def test_sigwinch(testdir, monkeypatch):
    import signal

    monkeypatch.setenv("LINES", "30")
    monkeypatch.setenv("COLUMNS", "50")

    p1 = testdir.makepyfile(
        """
        from _pytest._io import TerminalWriter

        def test(monkeypatch):
            import os
            import signal
            import _pytest.terminal

            assert signal.getsignal(signal.SIGWINCH) is not signal.SIG_DFL

            def prev_handler(signal, frame):
                print("prev_handler" + "_was_called", signal, frame)

            signal.signal(signal.SIGWINCH, prev_handler)

            _pytest.terminal._cached_terminal_width = None
            _pytest.terminal._cached_terminal_width_sighandler = None

            # Outer monkeypatch is respected.
            assert os.getenv("COLUMNS") == "50"

            tw = TerminalWriter()
            assert tw.fullwidth == 50

            assert input() == "step_1"
            monkeypatch.setenv("COLUMNS", "51")
            # Uses cache, without SIGWINCH.
            assert tw.fullwidth == 50

            print("waiting_for_sigwinch")
            assert input() == "sent_sigwinch"
            assert tw.fullwidth == 51

            signal.signal(signal.SIGWINCH, signal.SIG_DFL)
            print("waiting_for_sigwinch")
            assert input() == "sent_sigwinch"
            assert tw.fullwidth == 51
    """
    )
    cmdargs = [sys.executable, "-m", "pytest", "-s", "--full-trace", str(p1)]
    child = testdir.spawn(" ".join(cmdargs))
    child.sendline("step_1")

    child.expect_exact("waiting_for_sigwinch")
    child.kill(signal.SIGWINCH)
    child.sendline("sent_sigwinch")
    child.expect_exact("prev_handler_was_called")

    child.expect_exact("waiting_for_sigwinch")
    child.kill(signal.SIGWINCH)
    child.sendline("sent_sigwinch")

    rest = child.read().decode()
    assert child.wait() == 0, rest
    assert "prev_handler_was_called" not in rest
    assert child.wait() == 0, rest


def test_via_exec(testdir: Testdir) -> None:
    p1 = testdir.makepyfile("exec('def test_via_exec(): pass')")
    result = testdir.runpytest(str(p1), "-vv")
    result.stdout.fnmatch_lines(
        ["test_via_exec.py::test_via_exec <- <string> PASSED*", "*= 1 passed in *"]
    )


class TestCodeHighlight:
    def test_code_highlight_simple(self, testdir: Testdir, color_mapping) -> None:
        pytest.importorskip("pygments")

        testdir.makepyfile(
            """
            def test_foo():
                assert 1 == 10
        """
        )
        result = testdir.runpytest("--color=yes")
        color_mapping.requires_ordered_markup(result)
        result.stdout.fnmatch_lines(
            color_mapping.format_for_fnmatch(
                [
                    "    {kw}def{hl-reset} {function}test_foo{hl-reset}():",
                    ">       {kw}assert{hl-reset} {number}1{hl-reset} == {number}10{hl-reset}",
                    "{bold}{red}E       assert 1 == 10{reset}",
                ]
            )
        )

    def test_code_highlight_continuation(self, testdir: Testdir, color_mapping) -> None:
        pytest.importorskip("pygments")

        testdir.makepyfile(
            """
            def test_foo():
                print('''
                '''); assert 0
        """
        )
        result = testdir.runpytest("--color=yes")
        color_mapping.requires_ordered_markup(result)

        result.stdout.fnmatch_lines(
            color_mapping.format_for_fnmatch(
                [
                    "    {kw}def{hl-reset} {function}test_foo{hl-reset}():",
                    "        {print}print{hl-reset}({str}'''{hl-reset}{str}{hl-reset}",
                    ">   {str}    {hl-reset}{str}'''{hl-reset}); {kw}assert{hl-reset} {number}0{hl-reset}",
                    "{bold}{red}E       assert 0{reset}",
                ]
            )
        )
