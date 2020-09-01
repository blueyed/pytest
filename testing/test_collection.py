import os
import pprint
import sys
import textwrap

import py.path

import pytest
from _pytest.config import ExitCode
from _pytest.main import _in_venv
from _pytest.main import Session
from _pytest.pytester import Testdir


class TestCollector:
    def test_collect_versus_item(self):
        from pytest import Collector, Item

        assert not issubclass(Collector, Item)
        assert not issubclass(Item, Collector)

    def test_check_equality(self, testdir: Testdir) -> None:
        modcol = testdir.getmodulecol(
            """
            def test_pass(): pass
            def test_fail(): assert 0
        """
        )
        fn1 = testdir.collect_by_name(modcol, "test_pass")
        assert isinstance(fn1, pytest.Function)
        fn2 = testdir.collect_by_name(modcol, "test_pass")
        assert isinstance(fn2, pytest.Function)

        assert fn1 == fn2
        assert fn1 != modcol
        assert hash(fn1) == hash(fn2)

        fn3 = testdir.collect_by_name(modcol, "test_fail")
        assert isinstance(fn3, pytest.Function)
        assert not (fn1 == fn3)
        assert fn1 != fn3

        for fn in fn1, fn2, fn3:
            assert isinstance(fn, pytest.Function)
            assert fn != 3  # type: ignore[comparison-overlap]
            assert fn != modcol
            assert fn != [1, 2, 3]  # type: ignore[comparison-overlap]
            assert [1, 2, 3] != fn  # type: ignore[comparison-overlap]
            assert modcol != fn

        assert testdir.collect_by_name(modcol, "doesnotexist") is None

    def test_getparent(self, testdir):
        modcol = testdir.getmodulecol(
            """
            class TestClass:
                 def test_foo(self):
                     pass
        """
        )
        cls = testdir.collect_by_name(modcol, "TestClass")
        fn = testdir.collect_by_name(testdir.collect_by_name(cls, "()"), "test_foo")

        parent = fn.getparent(pytest.Module)
        assert parent is modcol

        parent = fn.getparent(pytest.Function)
        assert parent is fn

        parent = fn.getparent(pytest.Class)
        assert parent is cls

    def test_getcustomfile_roundtrip(self, testdir):
        hello = testdir.makefile(".xxx", hello="world")
        testdir.makepyfile(
            conftest="""
            import pytest
            class CustomFile(pytest.File):
                pass
            def pytest_collect_file(path, parent):
                if path.ext == ".xxx":
                    return CustomFile(path, parent=parent)
        """
        )
        node = testdir.getpathnode(hello)
        assert isinstance(node, pytest.File)
        assert node.name == "hello.xxx"
        nodes = node.session.perform_collect([node.nodeid], genitems=False)
        assert len(nodes) == 1
        assert isinstance(nodes[0], pytest.File)

    def test_can_skip_class_with_test_attr(self, testdir):
        """Assure test class is skipped when using `__test__=False` (See #2007)."""
        testdir.makepyfile(
            """
            class TestFoo(object):
                __test__ = False
                def __init__(self):
                    pass
                def test_foo():
                    assert True
        """
        )
        result = testdir.runpytest()
        result.stdout.fnmatch_lines(["collected 0 items", "*no tests ran in*"])


class TestCollectFS:
    def test_ignored_certain_directories(self, testdir):
        tmpdir = testdir.tmpdir
        tmpdir.ensure("build", "test_notfound.py")
        tmpdir.ensure("dist", "test_notfound.py")
        tmpdir.ensure("_darcs", "test_notfound.py")
        tmpdir.ensure("CVS", "test_notfound.py")
        tmpdir.ensure("{arch}", "test_notfound.py")
        tmpdir.ensure(".whatever", "test_notfound.py")
        tmpdir.ensure(".bzr", "test_notfound.py")
        tmpdir.ensure("normal", "test_found.py")
        for x in tmpdir.visit("test_*.py"):
            x.write("def test_hello(): pass")

        result = testdir.runpytest("--collect-only")
        s = result.stdout.str()
        assert "test_notfound" not in s
        assert "test_found" in s

    @pytest.mark.parametrize(
        "fname",
        (
            "activate",
            "activate.csh",
            "activate.fish",
            "Activate",
            "Activate.bat",
            "Activate.ps1",
        ),
    )
    def test_ignored_virtualenvs(self, testdir, fname):
        bindir = "Scripts" if sys.platform.startswith("win") else "bin"
        testdir.tmpdir.ensure("virtual", bindir, fname)
        testfile = testdir.tmpdir.ensure("virtual", "test_invenv.py")
        testfile.write("def test_hello(): pass")

        # by default, ignore tests inside a virtualenv
        result = testdir.runpytest("-v", tty=True)
        result.stdout.no_fnmatch_line("*test_invenv*")
        result.stdout.fnmatch_lines(
            [
                "collected 0 items (1 path ignored) *",
                "ignored 1 path (via --collect-in-virtualenv)",
            ]
        )
        # allow test collection if user insists
        # NOTE: does not report ignored ".pytest_cache".
        result = testdir.runpytest("--collect-in-virtualenv")
        result.stdout.fnmatch_lines(
            ["collected 1 item", "", "virtual/test_invenv.py .*"]
        )
        assert "test_invenv" in result.stdout.str()
        # allow test collection if user directly passes in the directory
        result = testdir.runpytest("virtual")
        result.stdout.fnmatch_lines(["collected 1 item", "virtual/test_invenv.py . *"])

    @pytest.mark.parametrize(
        "fname",
        (
            "activate",
            "activate.csh",
            "activate.fish",
            "Activate",
            "Activate.bat",
            "Activate.ps1",
        ),
    )
    def test_ignored_virtualenvs_norecursedirs_precedence(self, testdir, fname):
        bindir = "Scripts" if sys.platform.startswith("win") else "bin"
        # norecursedirs takes priority
        testdir.tmpdir.ensure(".virtual", bindir, fname)
        testfile = testdir.tmpdir.ensure(".virtual", "test_invenv.py")
        testfile.write("def test_hello(): pass")
        result = testdir.runpytest("--collect-in-virtualenv")
        result.stdout.no_fnmatch_line("*test_invenv*")
        # ...unless the virtualenv is explicitly given on the CLI
        result = testdir.runpytest("--collect-in-virtualenv", ".virtual")
        assert "test_invenv" in result.stdout.str()

    @pytest.mark.parametrize(
        "fname",
        (
            "activate",
            "activate.csh",
            "activate.fish",
            "Activate",
            "Activate.bat",
            "Activate.ps1",
        ),
    )
    def test__in_venv(self, testdir, fname):
        """Directly test the virtual env detection function"""
        bindir = "Scripts" if sys.platform.startswith("win") else "bin"
        # no bin/activate, not a virtualenv
        base_path = testdir.tmpdir.mkdir("venv")
        assert _in_venv(base_path) is False
        # with bin/activate, totally a virtualenv
        base_path.ensure(bindir, fname)
        assert _in_venv(base_path) is True

    def test_custom_norecursedirs(self, testdir):
        testdir.makeini(
            """
            [pytest]
            norecursedirs = mydir xyz*
        """
        )
        tmpdir = testdir.tmpdir
        tmpdir.ensure("mydir", "test_hello.py").write("def test_1(): pass")
        tmpdir.ensure("xyz123", "test_2.py").write("def test_2(): 0/0")
        tmpdir.ensure("xy", "test_ok.py").write("def test_3(): pass")
        rec = testdir.inline_run()
        rec.assertoutcome(passed=1)
        rec = testdir.inline_run("xyz123/test_2.py")
        rec.assertoutcome(failed=1)

    def test_testpaths_ini(self, testdir, monkeypatch):
        testdir.makeini(
            """
            [pytest]
            testpaths = gui uts
        """
        )
        tmpdir = testdir.tmpdir
        tmpdir.ensure("env", "test_1.py").write("def test_env(): pass")
        tmpdir.ensure("gui", "test_2.py").write("def test_gui(): pass")
        tmpdir.ensure("uts", "test_3.py").write("def test_uts(): pass")

        # executing from rootdir only tests from `testpaths` directories
        # are collected
        items, reprec = testdir.inline_genitems("-v")
        assert [x.name for x in items] == ["test_gui", "test_uts"]

        # check that explicitly passing directories in the command-line
        # collects the tests
        for dirname in ("env", "gui", "uts"):
            items, reprec = testdir.inline_genitems(tmpdir.join(dirname))
            assert [x.name for x in items] == ["test_%s" % dirname]

        # changing cwd to each subdirectory and running pytest without
        # arguments collects the tests in that directory normally
        for dirname in ("env", "gui", "uts"):
            monkeypatch.chdir(testdir.tmpdir.join(dirname))
            items, reprec = testdir.inline_genitems()
            assert [x.name for x in items] == ["test_%s" % dirname]


class TestCollectPluginHookRelay:
    def test_pytest_collect_file(self, testdir):
        wascalled = []

        class Plugin:
            def pytest_collect_file(self, path):
                if not path.basename.startswith("."):
                    # Ignore hidden files, e.g. .testmondata.
                    wascalled.append(path)

        testdir.makefile(".abc", "xyz")
        pytest.main([testdir.tmpdir], plugins=[Plugin()])
        assert len(wascalled) == 1
        assert wascalled[0].ext == ".abc"

    def test_pytest_collect_directory(self, testdir):
        wascalled = []

        class Plugin:
            def pytest_collect_directory(self, path):
                wascalled.append(path.basename)

        testdir.mkdir("hello")
        testdir.mkdir("world")
        pytest.main(testdir.tmpdir, plugins=[Plugin()])
        assert "hello" in wascalled
        assert "world" in wascalled


class TestPrunetraceback:
    def test_custom_repr_failure(self, testdir):
        p = testdir.makepyfile(
            """
            import not_exists
        """
        )
        testdir.makeconftest(
            """
            import pytest
            def pytest_collect_file(path, parent):
                return MyFile(path, parent)
            class MyError(Exception):
                pass
            class MyFile(pytest.File):
                def collect(self):
                    raise MyError()
                def repr_failure(self, excinfo):
                    if excinfo.errisinstance(MyError):
                        return "hello world"
                    return pytest.File.repr_failure(self, excinfo)
        """
        )

        result = testdir.runpytest(p)
        result.stdout.fnmatch_lines(["*ERROR collecting*", "*hello world*"])


class TestCustomConftests:
    def test_ignore_collect_path(self, testdir):
        testdir.makeconftest(
            """
            def pytest_ignore_collect(path, config):
                return path.basename.startswith("x") or \
                       path.basename == "test_one.py"
        """
        )
        sub = testdir.mkdir("xy123")
        sub.ensure("test_hello.py").write("syntax error")
        sub.join("conftest.py").write("syntax error")
        testdir.makepyfile("def test_hello(): pass")
        testdir.makepyfile(test_one="syntax error")
        result = testdir.runpytest("--fulltrace")
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*1 passed*"])

    def test_ignore_collect_not_called_on_argument(self, testdir):
        testdir.makeconftest(
            """
            def pytest_ignore_collect(path, config):
                return True
        """
        )
        p = testdir.makepyfile("def test_hello(): pass")
        result = testdir.runpytest(p)
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*1 passed*"])
        result = testdir.runpytest()
        assert result.ret == ExitCode.NO_TESTS_COLLECTED
        result.stdout.fnmatch_lines(["*collected 0 items*"])

    def test_collectignore_exclude_on_option(self, testdir):
        testdir.makeconftest(
            """
            collect_ignore = ['hello', 'test_world.py']
            def pytest_addoption(parser):
                parser.addoption("--XX", action="store_true", default=False)
            def pytest_configure(config):
                if config.getvalue("XX"):
                    collect_ignore[:] = []
        """
        )
        testdir.mkdir("hello")
        testdir.makepyfile(test_world="def test_hello(): pass")
        result = testdir.runpytest("-v", tty=True)
        result.stdout.fnmatch_lines(
            [
                "collected 0 items (2 paths ignored) *",
                "ignored 2 paths (via collect_ignore)",
            ]
        )
        assert result.ret == ExitCode.NO_TESTS_COLLECTED
        result.stdout.no_fnmatch_line("*passed*")
        result = testdir.runpytest("--XX")
        assert result.ret == 0
        assert "passed" in result.stdout.str()

        # collect_ignore and --ignore.
        testdir.makepyfile(test_ignore="")
        result = testdir.runpytest("-vv", "--ignore", "test_ignore.py")
        result.stdout.fnmatch_lines(
            [
                "collecting ... collected 0 items (3 paths ignored)",
                (
                    sys.version_info < (3, 6)
                    and "ignored 3 paths (*):"
                    or "ignored 3 paths (collect_ignore (2), --ignore (1)):"
                ),
                "*= no tests ran in *",
            ]
        )
        if sys.version_info >= (3, 6):
            result.stdout.fnmatch_lines(
                [
                    "  via collect_ignore:",
                    "   - hello",
                    "   - test_world.py",
                    "  via --ignore:",
                    "   - test_ignore.py",
                ]
            )
        assert result.ret == ExitCode.NO_TESTS_COLLECTED

    def test_collectignoreglob_exclude_on_option(self, testdir):
        testdir.makeconftest(
            """
            collect_ignore_glob = ['*w*l[dt]*']
            def pytest_addoption(parser):
                parser.addoption("--XX", action="store_true", default=False)
            def pytest_configure(config):
                if config.getvalue("XX"):
                    collect_ignore_glob[:] = []
        """
        )
        testdir.makepyfile(test_world="def test_hello(): pass")
        testdir.makepyfile(test_welt="def test_hallo(): pass")
        result = testdir.runpytest()
        result.stdout.fnmatch_lines(
            ["collected 0 items (2 paths ignored)", "", "*= no tests ran in *"],
            consecutive=True,
        )
        assert result.ret == ExitCode.NO_TESTS_COLLECTED
        result.stdout.fnmatch_lines(["*collected 0 items*"])
        result = testdir.runpytest("--XX")
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*2 passed*"])

    def test_pytest_fs_collect_hooks_are_seen(self, testdir):
        testdir.makeconftest(
            """
            import pytest
            class MyModule(pytest.Module):
                pass
            def pytest_collect_file(path, parent):
                if path.ext == ".py":
                    return MyModule(path, parent)
        """
        )
        testdir.mkdir("sub")
        testdir.makepyfile("def test_x(): pass")
        result = testdir.runpytest("--co")
        result.stdout.fnmatch_lines(["*MyModule*", "*test_x*"])

    def test_pytest_collect_file_from_sister_dir(self, testdir):
        sub1 = testdir.mkpydir("sub1")
        sub2 = testdir.mkpydir("sub2")
        conf1 = testdir.makeconftest(
            """
            import pytest
            class MyModule1(pytest.Module):
                pass
            def pytest_collect_file(path, parent):
                if path.ext == ".py":
                    return MyModule1(path, parent)
        """
        )
        conf1.move(sub1.join(conf1.basename))
        conf2 = testdir.makeconftest(
            """
            import pytest
            class MyModule2(pytest.Module):
                pass
            def pytest_collect_file(path, parent):
                if path.ext == ".py":
                    return MyModule2(path, parent)
        """
        )
        conf2.move(sub2.join(conf2.basename))
        p = testdir.makepyfile("def test_x(): pass")
        p.copy(sub1.join(p.basename))
        p.copy(sub2.join(p.basename))
        result = testdir.runpytest("--co")
        result.stdout.fnmatch_lines(["*MyModule1*", "*MyModule2*", "*test_x*"])


class TestSession:
    def test_parsearg(self, testdir) -> None:
        p = testdir.makepyfile("def test_func(): pass")
        subdir = testdir.mkdir("sub")
        subdir.ensure("__init__.py")
        target = subdir.join(p.basename)
        p.move(target)
        subdir.chdir()
        config = testdir.parseconfig(p.basename)
        rcol = Session(config=config)
        assert rcol.fspath == subdir
        fspath, parts = rcol._parsearg(p.basename)

        assert fspath == target
        assert len(parts) == 0
        fspath, parts = rcol._parsearg(p.basename + "::test_func")
        assert fspath == target
        assert parts[0] == "test_func"
        assert len(parts) == 1

    def test_collect_topdir(self, testdir):
        p = testdir.makepyfile("def test_func(): pass")
        id = "::".join([p.basename, "test_func"])
        # XXX migrate to collectonly? (see below)
        config = testdir.parseconfig(id)
        topdir = testdir.tmpdir
        rcol = Session(config)
        assert topdir == rcol.fspath
        # rootid = rcol.nodeid
        # root2 = rcol.perform_collect([rcol.nodeid], genitems=False)[0]
        # assert root2 == rcol, rootid
        colitems = rcol.perform_collect([rcol.nodeid], genitems=False)
        assert len(colitems) == 1
        assert colitems[0].fspath == p

    def get_reported_items(self, hookrec):
        """Return pytest.Item instances reported by the pytest_collectreport hook"""
        calls = hookrec.getcalls("pytest_collectreport")
        return [
            x
            for call in calls
            for x in call.report.result
            if isinstance(x, pytest.Item)
        ]

    def test_collect_protocol_single_function(self, testdir):
        p = testdir.makepyfile("def test_func(): pass")
        id = "::".join([p.basename, "test_func"])
        items, hookrec = testdir.inline_genitems(id)
        (item,) = items
        assert item.name == "test_func"
        newid = item.nodeid
        assert newid == id
        pprint.pprint(hookrec.calls)
        topdir = testdir.tmpdir  # noqa
        hookrec.assert_contains(
            [
                ("pytest_collectstart", "collector.fspath == topdir"),
                ("pytest_make_collect_report", "collector.fspath == topdir"),
                ("pytest_collectstart", "collector.fspath == p"),
                ("pytest_make_collect_report", "collector.fspath == p"),
                ("pytest_pycollect_makeitem", "name == 'test_func'"),
                ("pytest_collectreport", "report.result[0].name == 'test_func'"),
            ]
        )
        # ensure we are reporting the collection of the single test item (#2464)
        assert [x.name for x in self.get_reported_items(hookrec)] == ["test_func"]

    def test_collect_protocol_method(self, testdir):
        p = testdir.makepyfile(
            """
            class TestClass(object):
                def test_method(self):
                    pass
        """
        )
        normid = p.basename + "::TestClass::test_method"
        for id in [p.basename, p.basename + "::TestClass", normid]:
            items, hookrec = testdir.inline_genitems(id)
            assert len(items) == 1
            assert items[0].name == "test_method"
            newid = items[0].nodeid
            assert newid == normid
            # ensure we are reporting the collection of the single test item (#2464)
            assert [x.name for x in self.get_reported_items(hookrec)] == ["test_method"]

    def test_collect_custom_nodes_multi_id(self, testdir):
        p = testdir.makepyfile("def test_func(): pass")
        testdir.makeconftest(
            """
            import pytest
            class SpecialItem(pytest.Item):
                def runtest(self):
                    return # ok
            class SpecialFile(pytest.File):
                def collect(self):
                    return [SpecialItem(name="check", parent=self)]
            def pytest_collect_file(path, parent):
                if path.basename == %r:
                    return SpecialFile(fspath=path, parent=parent)
        """
            % p.basename
        )
        id = p.basename

        items, hookrec = testdir.inline_genitems(id)
        pprint.pprint(hookrec.calls)
        assert len(items) == 2
        hookrec.assert_contains(
            [
                ("pytest_collectstart", "collector.fspath == collector.session.fspath"),
                (
                    "pytest_collectstart",
                    "collector.__class__.__name__ == 'SpecialFile'",
                ),
                ("pytest_collectstart", "collector.__class__.__name__ == 'Module'"),
                ("pytest_pycollect_makeitem", "name == 'test_func'"),
                ("pytest_collectreport", "report.nodeid.startswith(p.basename)"),
            ]
        )
        assert len(self.get_reported_items(hookrec)) == 2

    def test_collect_subdir_event_ordering(self, testdir):
        p = testdir.makepyfile("def test_func(): pass")
        aaa = testdir.mkpydir("aaa")
        test_aaa = aaa.join("test_aaa.py")
        p.move(test_aaa)

        items, hookrec = testdir.inline_genitems()
        assert len(items) == 1
        pprint.pprint(hookrec.calls)
        hookrec.assert_contains(
            [
                ("pytest_collectstart", "collector.fspath == test_aaa"),
                ("pytest_pycollect_makeitem", "name == 'test_func'"),
                ("pytest_collectreport", "report.nodeid.startswith('aaa/test_aaa.py')"),
            ]
        )

    def test_collect_two_commandline_args(self, testdir):
        p = testdir.makepyfile("def test_func(): pass")
        aaa = testdir.mkpydir("aaa")
        bbb = testdir.mkpydir("bbb")
        test_aaa = aaa.join("test_aaa.py")
        p.copy(test_aaa)
        test_bbb = bbb.join("test_bbb.py")
        p.move(test_bbb)

        id = "."

        items, hookrec = testdir.inline_genitems(id)
        assert len(items) == 2
        pprint.pprint(hookrec.calls)
        hookrec.assert_contains(
            [
                ("pytest_collectstart", "collector.fspath == test_aaa"),
                ("pytest_pycollect_makeitem", "name == 'test_func'"),
                ("pytest_collectreport", "report.nodeid == 'aaa/test_aaa.py'"),
                ("pytest_collectstart", "collector.fspath == test_bbb"),
                ("pytest_pycollect_makeitem", "name == 'test_func'"),
                ("pytest_collectreport", "report.nodeid == 'bbb/test_bbb.py'"),
            ]
        )

    def test_serialization_byid(self, testdir):
        testdir.makepyfile("def test_func(): pass")
        items, hookrec = testdir.inline_genitems()
        assert len(items) == 1
        (item,) = items
        items2, hookrec = testdir.inline_genitems(item.nodeid)
        (item2,) = items2
        assert item2.name == item.name
        assert item2.fspath == item.fspath

    def test_find_byid_without_instance_parents(self, testdir):
        p = testdir.makepyfile(
            """
            class TestClass(object):
                def test_method(self):
                    pass
        """
        )
        arg = p.basename + "::TestClass::test_method"
        items, hookrec = testdir.inline_genitems(arg)
        assert len(items) == 1
        (item,) = items
        assert item.nodeid.endswith("TestClass::test_method")
        # ensure we are reporting the collection of the single test item (#2464)
        assert [x.name for x in self.get_reported_items(hookrec)] == ["test_method"]


class Test_getinitialnodes:
    def test_global_file(self, testdir, tmpdir):
        x = tmpdir.ensure("x.py")
        with tmpdir.as_cwd():
            config = testdir.parseconfigure(x)
        col = testdir.getnode(config, x)
        assert isinstance(col, pytest.Module)
        assert col.name == "x.py"
        assert col.parent.parent is None
        for col in col.listchain():
            assert col.config is config

    def test_pkgfile(self, testdir):
        """Verify nesting when a module is within a package.
        The parent chain should match: Module<x.py> -> Package<subdir> -> Session.
            Session's parent should always be None.
        """
        tmpdir = testdir.tmpdir
        subdir = tmpdir.join("subdir")
        x = subdir.ensure("x.py")
        subdir.ensure("__init__.py")
        with subdir.as_cwd():
            config = testdir.parseconfigure(x)
        col = testdir.getnode(config, x)
        assert col.name == "x.py"
        assert isinstance(col, pytest.Module)
        assert isinstance(col.parent, pytest.Package)
        assert isinstance(col.parent.parent, pytest.Session)
        # session is batman (has no parents)
        assert col.parent.parent.parent is None
        for col in col.listchain():
            assert col.config is config


class Test_genitems:
    def test_check_collect_hashes(self, testdir):
        p = testdir.makepyfile(
            """
            def test_1():
                pass

            def test_2():
                pass
        """
        )
        p.copy(p.dirpath(p.purebasename + "2" + ".py"))
        items, reprec = testdir.inline_genitems(p.dirpath())
        assert len(items) == 4
        for numi, i in enumerate(items):
            for numj, j in enumerate(items):
                if numj != numi:
                    assert hash(i) != hash(j)
                    assert i != j

    def test_example_items1(self, testdir):
        p = testdir.makepyfile(
            """
            import pytest

            def testone():
                pass

            class TestX(object):
                def testmethod_one(self):
                    pass

            class TestY(TestX):
                @pytest.mark.parametrize("arg0", [".["])
                def testmethod_two(self, arg0):
                    pass
        """
        )
        items, reprec = testdir.inline_genitems(p)
        assert len(items) == 4
        assert items[0].name == "testone"
        assert items[1].name == "testmethod_one"
        assert items[2].name == "testmethod_one"
        assert items[3].name == "testmethod_two[.[]"

        # let's also test getmodpath here
        assert items[0].getmodpath() == "testone"
        assert items[1].getmodpath() == "TestX.testmethod_one"
        assert items[2].getmodpath() == "TestY.testmethod_one"
        # PR #6202: Fix incorrect result of getmodpath method. (Resolves issue #6189)
        assert items[3].getmodpath() == "TestY.testmethod_two[.[]"

        s = items[0].getmodpath(stopatmodule=False)
        assert s.endswith("test_example_items1.testone")
        print(s)

    def test_class_and_functions_discovery_using_glob(self, testdir):
        """
        tests that python_classes and python_functions config options work
        as prefixes and glob-like patterns (issue #600).
        """
        testdir.makeini(
            """
            [pytest]
            python_classes = *Suite Test
            python_functions = *_test test
        """
        )
        p = testdir.makepyfile(
            """
            class MyTestSuite(object):
                def x_test(self):
                    pass

            class TestCase(object):
                def test_y(self):
                    pass
        """
        )
        items, reprec = testdir.inline_genitems(p)
        ids = [x.getmodpath() for x in items]
        assert ids == ["MyTestSuite.x_test", "TestCase.test_y"]


def test_matchnodes_two_collections_same_file(testdir):
    testdir.makeconftest(
        """
        import pytest
        def pytest_configure(config):
            config.pluginmanager.register(Plugin2())

        class Plugin2(object):
            def pytest_collect_file(self, path, parent):
                if path.ext == ".abc":
                    return MyFile2(path, parent)

        def pytest_collect_file(path, parent):
            if path.ext == ".abc":
                return MyFile1(path, parent)

        class MyFile1(pytest.Item, pytest.File):
            def runtest(self):
                pass
        class MyFile2(pytest.File):
            def collect(self):
                return [Item2("hello", parent=self)]

        class Item2(pytest.Item):
            def runtest(self):
                pass
    """
    )
    p = testdir.makefile(".abc", "")
    result = testdir.runpytest()
    assert result.ret == 0
    result.stdout.fnmatch_lines(["*2 passed*"])
    res = testdir.runpytest("%s::hello" % p.basename)
    res.stdout.fnmatch_lines(["*1 passed*"])


class TestNodekeywords:
    def test_no_under(self, testdir):
        modcol = testdir.getmodulecol(
            """
            def test_pass(): pass
            def test_fail(): assert 0
        """
        )
        values = list(modcol.keywords)
        assert modcol.name in values
        for x in values:
            assert not x.startswith("_")
        assert modcol.name in repr(modcol.keywords)

    def test_issue345(self, testdir):
        testdir.makepyfile(
            """
            def test_should_not_be_selected():
                assert False, 'I should not have been selected to run'

            def test___repr__():
                pass
        """
        )
        reprec = testdir.inline_run("-k repr")
        reprec.assertoutcome(passed=1, failed=0)

    def test_keyword_matching_is_case_insensitive_by_default(self, testdir):
        """Check that selection via -k EXPRESSION is case-insensitive.

        Since markers are also added to the node keywords, they too can
        be matched without having to think about case sensitivity.

        """
        testdir.makepyfile(
            """
            import pytest

            def test_sPeCiFiCToPiC_1():
                assert True

            class TestSpecificTopic_2:
                def test(self):
                    assert True

            @pytest.mark.sPeCiFiCToPic_3
            def test():
                assert True

            @pytest.mark.sPeCiFiCToPic_4
            class Test:
                def test(self):
                    assert True

            def test_failing_5():
                assert False, "This should not match"

        """
        )
        num_matching_tests = 4
        for expression in ("specifictopic", "SPECIFICTOPIC", "SpecificTopic"):
            reprec = testdir.inline_run("-k " + expression)
            reprec.assertoutcome(passed=num_matching_tests, failed=0)


COLLECTION_ERROR_PY_FILES = dict(
    test_01_failure="""
        def test_1():
            assert False
        """,
    test_02_import_error="""
        import asdfasdfasdf
        def test_2():
            assert True
        """,
    test_03_import_error="""
        import asdfasdfasdf
        def test_3():
            assert True
    """,
    test_04_success="""
        def test_4():
            assert True
    """,
)


def test_exit_on_collection_error(testdir):
    """Verify that all collection errors are collected and no tests executed"""
    testdir.makepyfile(**COLLECTION_ERROR_PY_FILES)

    res = testdir.runpytest()
    assert res.ret == 2

    res.stdout.fnmatch_lines(
        [
            "collected 2 items / 2 errors",
            "*ERROR collecting test_02_import_error.py*",
            "*No module named *asdfa*",
            "*ERROR collecting test_03_import_error.py*",
            "*No module named *asdfa*",
        ]
    )


def test_exit_on_collection_with_maxfail_smaller_than_n_errors(testdir):
    """
    Verify collection is aborted once maxfail errors are encountered ignoring
    further modules which would cause more collection errors.
    """
    testdir.makepyfile(**COLLECTION_ERROR_PY_FILES)

    res = testdir.runpytest("--maxfail=1")
    assert res.ret == 1
    res.stdout.fnmatch_lines(
        [
            "collected 1 item / 1 error",
            "*ERROR collecting test_02_import_error.py*",
            "*No module named *asdfa*",
            "*= 1 error in *s (stopping after 1 failure) =*",
        ]
    )
    res.stdout.no_fnmatch_line("*test_03*")


def test_exit_on_collection_with_maxfail_bigger_than_n_errors(testdir):
    """
    Verify the test run aborts due to collection errors even if maxfail count of
    errors was not reached.
    """
    testdir.makepyfile(**COLLECTION_ERROR_PY_FILES)

    res = testdir.runpytest("--maxfail=4")
    assert res.ret == 2
    res.stdout.fnmatch_lines(
        [
            "collected 2 items / 2 errors",
            "*ERROR collecting test_02_import_error.py*",
            "*No module named *asdfa*",
            "*ERROR collecting test_03_import_error.py*",
            "*No module named *asdfa*",
            "*! Interrupted: 2 errors during collection !*",
            "*= 2 errors in *",
        ]
    )


def test_continue_on_collection_errors(testdir):
    """
    Verify tests are executed even when collection errors occur when the
    --continue-on-collection-errors flag is set
    """
    testdir.makepyfile(**COLLECTION_ERROR_PY_FILES)

    res = testdir.runpytest("--continue-on-collection-errors")
    assert res.ret == 1

    res.stdout.fnmatch_lines(
        ["collected 2 items / 2 errors", "*1 failed, 1 passed, 2 errors*"]
    )


def test_continue_on_collection_errors_maxfail(testdir):
    """
    Verify tests are executed even when collection errors occur and that maxfail
    is honoured (including the collection error count).
    4 tests: 2 collection errors + 1 failure + 1 success
    test_4 is never executed because the test run is with --maxfail=3 which
    means it is interrupted after the 2 collection errors + 1 failure.
    """
    testdir.makepyfile(**COLLECTION_ERROR_PY_FILES)

    res = testdir.runpytest("--continue-on-collection-errors", "--maxfail=3")
    assert res.ret == 1

    res.stdout.fnmatch_lines(["collected 2 items / 2 errors", "*1 failed, 2 errors*"])


def test_fixture_scope_sibling_conftests(testdir):
    """Regression test case for https://github.com/pytest-dev/pytest/issues/2836"""
    foo_path = testdir.mkdir("foo")
    foo_path.join("conftest.py").write(
        textwrap.dedent(
            """\
            import pytest
            @pytest.fixture
            def fix():
                return 1
            """
        )
    )
    foo_path.join("test_foo.py").write("def test_foo(fix): assert fix == 1")

    # Tests in `food/` should not see the conftest fixture from `foo/`
    food_path = testdir.mkpydir("food")
    food_path.join("test_food.py").write("def test_food(fix): assert fix == 1")

    res = testdir.runpytest()
    assert res.ret == 1

    res.stdout.fnmatch_lines(
        [
            "*ERROR at setup of test_food*",
            "E*fixture 'fix' not found",
            "*1 passed, 1 error*",
        ]
    )


def test_collect_init_tests(testdir: "Testdir") -> None:
    """Check that we collect files from __init__.py files when they patch the 'python_files' (#3773)"""
    p = testdir.copy_example("collect/collect_init_tests")
    package_line = "<Package {}>".format(testdir.tmpdir.join("tests"))
    result = testdir.runpytest(p, "--collect-only")
    result.stdout.fnmatch_lines(
        [
            "collected 2 items",
            "",
            package_line,
            "  <Module __init__.py>",
            "    <Function test_init>",
            "  <Module test_foo.py>",
            "    <Function test_foo>",
            "",
        ],
        consecutive=True,
    )
    result = testdir.runpytest("./tests", "--collect-only")
    result.stdout.fnmatch_lines(
        [
            "collected 2 items",
            "",
            package_line,
            "  <Module __init__.py>",
            "    <Function test_init>",
            "  <Module test_foo.py>",
            "    <Function test_foo>",
            "",
        ],
        consecutive=True,
    )
    # Ignores duplicates with "." and pkginit (#4310).
    result = testdir.runpytest("./tests", ".", "--collect-only")
    result.stdout.fnmatch_lines(
        [
            "collected 2 items",
            "",
            package_line,
            "  <Module __init__.py>",
            "    <Function test_init>",
            "  <Module test_foo.py>",
            "    <Function test_foo>",
            "",
        ],
        consecutive=True,
    )
    # Same as before, but different order.
    result = testdir.runpytest(".", "tests", "--collect-only")
    result.stdout.fnmatch_lines(
        [
            "collected 2 items",
            "",
            package_line,
            "  <Module __init__.py>",
            "    <Function test_init>",
            "  <Module test_foo.py>",
            "    <Function test_foo>",
            "",
        ],
        consecutive=True,
    )
    result = testdir.runpytest("./tests/test_foo.py", "--collect-only")
    result.stdout.fnmatch_lines(
        [
            "collected 1 item",
            "",
            package_line,
            "  <Module test_foo.py>",
            "    <Function test_foo>",
            "",
        ],
        consecutive=True,
    )
    result = testdir.runpytest("./tests/__init__.py", "--collect-only")
    result.stdout.fnmatch_lines(
        [
            "collected 1 item",
            "",
            package_line,
            "  <Module __init__.py>",
            "    <Function test_init>",
            "",
        ],
        consecutive=True,
    )


def test_collect_invalid_signature_message(testdir):
    """Check that we issue a proper message when we can't determine the signature of a test
    function (#4026).
    """
    testdir.makepyfile(
        """
        import pytest

        class TestCase:
            @pytest.fixture
            def fix():
                pass
    """
    )
    result = testdir.runpytest()
    result.stdout.fnmatch_lines(
        ["Could not determine arguments of *.fix *: invalid method signature"]
    )


def test_collect_handles_raising_on_dunder_class(testdir):
    """Handle proxy classes like Django's LazySettings that might raise on
    ``isinstance`` (#4266).
    """
    testdir.makepyfile(
        """
        class ImproperlyConfigured(Exception):
            pass

        class RaisesOnGetAttr(object):
            def raises(self):
                raise ImproperlyConfigured

            __class__ = property(raises)

        raises = RaisesOnGetAttr()


        def test_1():
            pass
    """
    )
    result = testdir.runpytest()
    result.stdout.fnmatch_lines(["*1 passed in*"])
    assert result.ret == 0


def test_collect_with_chdir_during_import(testdir):
    subdir = testdir.tmpdir.mkdir("sub")
    testdir.tmpdir.join("conftest.py").write(
        textwrap.dedent(
            """
            import os
            os.chdir(%r)
            """
            % (str(subdir),)
        )
    )
    testdir.makepyfile(
        """
        def test_1():
            import os
            assert os.getcwd() == %r
        """
        % (str(subdir),)
    )
    with testdir.tmpdir.as_cwd():
        result = testdir.runpytest()
    result.stdout.fnmatch_lines(["*1 passed in*"])
    assert result.ret == 0

    # Handles relative testpaths.
    testdir.makeini(
        """
        [pytest]
        testpaths = .
    """
    )
    with testdir.tmpdir.as_cwd():
        result = testdir.runpytest("--collect-only")
    result.stdout.fnmatch_lines(["collected 1 item"])


def test_collect_pyargs_with_testpaths(testdir, monkeypatch):
    testmod = testdir.mkdir("testmod")
    # NOTE: __init__.py is not collected since it does not match python_files.
    testmod.ensure("__init__.py").write("def test_func(): pass")
    testmod.ensure("test_file.py").write("def test_func(): pass")

    root = testdir.mkdir("root")
    root.ensure("pytest.ini").write(
        textwrap.dedent(
            """
        [pytest]
        addopts = --pyargs
        testpaths = testmod
    """
        )
    )
    monkeypatch.setenv("PYTHONPATH", str(testdir.tmpdir), prepend=os.pathsep)
    with root.as_cwd():
        result = testdir.runpytest_subprocess()
    result.stdout.fnmatch_lines(["*1 passed in*"])


@pytest.mark.skipif(
    not hasattr(py.path.local, "mksymlinkto"),
    reason="symlink not available on this platform",
)
def test_collect_symlink_file_arg(testdir):
    """Test that collecting a direct symlink, where the target does not match python_files works (#4325)."""
    real = testdir.makepyfile(
        real="""
        def test_nodeid(request):
            assert request.node.nodeid == "real.py::test_nodeid"
        """
    )
    symlink = testdir.tmpdir.join("symlink.py")
    symlink.mksymlinkto(real)
    result = testdir.runpytest("-v", symlink)
    result.stdout.fnmatch_lines(["real.py::test_nodeid PASSED*", "*1 passed in*"])
    assert result.ret == 0


@pytest.mark.skipif(
    not hasattr(py.path.local, "mksymlinkto"),
    reason="symlink not available on this platform",
)
def test_collect_symlink_out_of_tree(testdir):
    """Test collection of symlink via out-of-tree rootdir."""
    sub = testdir.tmpdir.join("sub")
    real = sub.join("test_real.py")
    real.write(
        textwrap.dedent(
            """
        def test_nodeid(request):
            # Should not contain sub/ prefix.
            assert request.node.nodeid == "test_real.py::test_nodeid"
        """
        ),
        ensure=True,
    )

    out_of_tree = testdir.tmpdir.join("out_of_tree").ensure(dir=True)
    symlink_to_sub = out_of_tree.join("symlink_to_sub")
    symlink_to_sub.mksymlinkto(sub)
    sub.chdir()
    result = testdir.runpytest("-vs", "--rootdir=%s" % sub, symlink_to_sub)
    result.stdout.fnmatch_lines(
        [
            # Should not contain "sub/"!
            "test_real.py::test_nodeid PASSED"
        ]
    )
    assert result.ret == 0


def test_collectignore_via_conftest(testdir):
    """collect_ignore in parent conftest skips importing child (issue #4592)."""
    tests = testdir.mkpydir("tests")
    tests.ensure("conftest.py").write("collect_ignore = ['ignore_me']")

    ignore_me = tests.mkdir("ignore_me")
    ignore_me.ensure("__init__.py")
    ignore_me.ensure("conftest.py").write("assert 0, 'should_not_be_called'")

    result = testdir.runpytest()
    assert result.ret == ExitCode.NO_TESTS_COLLECTED


def test_collect_pkg_init_and_file_in_args(testdir):
    subdir = testdir.mkdir("sub")
    init = subdir.ensure("__init__.py")
    init.write("def test_init(): pass")
    p = subdir.ensure("test_file.py")
    p.write("def test_file(): pass")

    # NOTE: without "-o python_files=*.py" this collects test_file.py twice.
    # This changed/broke with "Add package scoped fixtures #2283" (2b1410895)
    # initially (causing a RecursionError).
    result = testdir.runpytest("-v", str(init), str(p))
    result.stdout.fnmatch_lines(
        [
            "sub/test_file.py::test_file PASSED*",
            "sub/test_file.py::test_file PASSED*",
            "*2 passed in*",
        ]
    )

    result = testdir.runpytest("-v", "-o", "python_files=*.py", str(init), str(p))
    result.stdout.fnmatch_lines(
        [
            "sub/__init__.py::test_init PASSED*",
            "sub/test_file.py::test_file PASSED*",
            "*2 passed in*",
        ]
    )


def test_collect_pkg_init_only(testdir):
    subdir = testdir.mkdir("sub")
    init = subdir.ensure("__init__.py")
    init.write("def test_init(): pass")

    result = testdir.runpytest(str(init))
    result.stdout.fnmatch_lines(["*no tests ran in*"])

    result = testdir.runpytest("-v", "-o", "python_files=*.py", str(init))
    result.stdout.fnmatch_lines(["sub/__init__.py::test_init PASSED*", "*1 passed in*"])


@pytest.mark.skipif(
    not hasattr(py.path.local, "mksymlinkto"),
    reason="symlink not available on this platform",
)
@pytest.mark.parametrize("use_pkg", (True, False))
def test_collect_sub_with_symlinks(use_pkg, testdir):
    sub = testdir.mkdir("sub")
    if use_pkg:
        sub.ensure("__init__.py")
    sub.ensure("test_file.py").write("def test_file(): pass")

    # Create a broken symlink.
    sub.join("test_broken.py").mksymlinkto("test_doesnotexist.py")

    # Symlink that gets collected.
    sub.join("test_symlink.py").mksymlinkto("test_file.py")

    result = testdir.runpytest("-v", str(sub))
    result.stdout.fnmatch_lines(
        [
            "sub/test_file.py::test_file PASSED*",
            "sub/test_symlink.py::test_file PASSED*",
            "*2 passed in*",
        ]
    )


def test_automatic_pytest_deselect(testdir):
    p1 = testdir.makepyfile(
        conftest="""
        import pytest

        deselect_calls = []

        def pytest_deselected(items):
            assert type(items) == list
            deselect_calls.append(items)

        def pytest_collection_modifyitems(items):
            items[:] = [item for item in items if item.name != "test_removed"]

        def test_removed():
            assert 0

        def test_check():
            assert len(deselect_calls) == 1
            assert [x.name for x in deselect_calls[0]] == ["test_removed"]
    """
    )
    result = testdir.runpytest(str(p1))
    assert result.ret == 0
    assert result.reprec.countoutcomes() == [1, 0, 0]


def test_collector_respects_tbstyle(testdir):
    p1 = testdir.makepyfile("assert 0")
    result = testdir.runpytest(p1, "--tb=native")
    assert result.ret == ExitCode.INTERRUPTED
    result.stdout.fnmatch_lines(
        [
            "*_ ERROR collecting test_collector_respects_tbstyle.py _*",
            "Traceback (most recent call last):",
            '  File "*/test_collector_respects_tbstyle.py", line 1, in <module>',
            "    assert 0",
            "AssertionError: assert 0",
            "*! Interrupted: 1 error during collection !*",
            "*= 1 error in *",
        ]
    )


def test_keyboardinterrupt_during_collection(testdir):
    sub = testdir.mkdir("sub")
    sub.ensure("__init__.py")
    sub.ensure("test_file.py").write("raise KeyboardInterrupt()")
    result = testdir.runpytest(no_reraise_ctrlc=True)
    assert result.ret == ExitCode.INTERRUPTED
    result.stdout.fnmatch_lines(
        [
            "*! KeyboardInterrupt !*",
            "*/sub/test_file.py:1: KeyboardInterrupt",
            "(to show a full traceback on KeyboardInterrupt use --full-trace)",
            "*= no tests ran in *=",
        ]
    )


def test_collect_by_file_and_lineno(testdir):
    p1 = testdir.makepyfile(
        """
        import pytest

        def test_one():
            pass

        @pytest.mark.parametrize("param", ["sel1", "desel"])
        def test_two(param):
            pass
    """
    )
    result = testdir.runpytest("--collect-only", "{}:1".format(p1))
    result.stdout.fnmatch_lines(
        ["collected 3 items / 3 deselected", "*= 3 deselected in *"]
    )
    assert result.ret == ExitCode.NO_TESTS_COLLECTED

    result = testdir.runpytest("--collect-only", "{}:3".format(p1))
    result.stdout.fnmatch_lines(
        [
            "collected 3 items / 2 deselected / 1 selected",
            "<Module test_collect_by_file_and_lineno.py>",
            "  <Function test_one>",
            "*= 2 deselected in *",
        ]
    )
    assert result.ret == 0

    result = testdir.runpytest("--collect-only", "-k", "not desel", "{}:6".format(p1))
    result.stdout.fnmatch_lines(
        [
            "collected 3 items / 2 deselected / 1 selected",
            "<Module test_collect_by_file_and_lineno.py>",
            "  <Function test_two[sel1]>",
            "*= 2 deselected in *",
        ]
    )
    assert result.ret == 0

    p2 = testdir.makepyfile(
        test_p2="""
        def test_three():
            pass
    """
    )
    result = testdir.runpytest("--collect-only", "{}:99".format(p1))
    assert result.ret == ExitCode.NO_TESTS_COLLECTED

    result = testdir.runpytest("--collect-only", "{}:99".format(p1), "{}:3".format(p2))
    result.stdout.fnmatch_lines(
        [
            "collected 4 items / 3 deselected / 1 selected",
            "<Module test_p2.py>",
            "  <Function test_three>",
            "*= 3 deselected in *",
        ]
    )
    assert result.ret == 0

    # Range: from
    result = testdir.runpytest("--collect-only", "{}:6-".format(p1))
    result.stdout.fnmatch_lines(
        [
            "collected 3 items / 1 deselected / 2 selected",
            "<Module test_collect_by_file_and_lineno.py>",
            "  <Function test_two[sel1]>",
            "  <Function test_two[desel]>",
            "*= 1 deselected in *",
        ]
    )
    assert result.ret == 0

    # Range: until
    result = testdir.runpytest("--collect-only", "{}:-99".format(p1))
    result.stdout.fnmatch_lines(
        [
            "collected 3 items",
            "<Module test_collect_by_file_and_lineno.py>",
            "  <Function test_one>",
            "  <Function test_two[sel1]>",
            "  <Function test_two[desel]>",
            "*= no tests ran in *",
        ]
    )
    assert result.ret == 0

    # Range: from-until
    result = testdir.runpytest("--collect-only", "{}:1-3".format(p1))
    result.stdout.fnmatch_lines(
        [
            "collected 3 items / 2 deselected / 1 selected",
            "<Module test_collect_by_file_and_lineno.py>",
            "  <Function test_one>",
            "*= 2 deselected in *",
        ]
    )
    assert result.ret == 0

    # Range: invalid / non-matching
    result = testdir.runpytest("--collect-only", "{}:3-1".format(p1))
    result.stdout.fnmatch_lines(
        ["collected 3 items / 3 deselected", "*= 3 deselected in *"]
    )
    assert result.ret == ExitCode.NO_TESTS_COLLECTED


def test_does_not_eagerly_collect_packages(testdir):
    testdir.makepyfile("def test(): pass")
    pydir = testdir.mkpydir("foopkg")
    pydir.join("__init__.py").write("assert False")
    result = testdir.runpytest()
    assert result.ret == ExitCode.OK


def test_does_not_put_src_on_path(testdir):
    # `src` is not on sys.path so it should not be importable
    testdir.tmpdir.join("src/nope/__init__.py").ensure()
    testdir.makepyfile(
        "import pytest\n"
        "def test():\n"
        "    with pytest.raises(ImportError):\n"
        "        import nope\n"
    )
    result = testdir.runpytest()
    assert result.ret == ExitCode.OK
