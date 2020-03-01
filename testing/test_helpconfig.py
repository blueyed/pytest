import pytest
from _pytest.config import ExitCode
from _pytest.pytester import Testdir


def test_version(testdir, pytestconfig):
    testdir.monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD")
    result = testdir.runpytest("--version")
    assert result.ret == 0
    # p = py.path.local(py.__file__).dirpath()
    result.stderr.fnmatch_lines(
        ["*pytest*{}*imported from*".format(pytest.__version__)]
    )
    if pytestconfig.pluginmanager.list_plugin_distinfo():
        result.stderr.fnmatch_lines(["*setuptools registered plugins:", "*at*"])


def test_help(testdir: Testdir) -> None:
    result = testdir.runpytest("--help", "-p", "no:[defaults]")
    assert result.ret == 0
    result.stdout.fnmatch_lines(
        """
        usage: * [[]options[]] [[]file_or_dir[]] [[]file_or_dir[]] [[]...[]]

        positional arguments:
          file_or_dir

          -m MARKEXPR           only run tests matching given mark expression.
                                For example: -m 'mark1 and not mark2'.
        reporting:
          --durations=N *

        collection:
          --[[]no-[]]collect-only, --[[]no-[]]co

        test session debugging and configuration:
          -V, --version         display pytest version and information about plugins.
          -h, --help            show help message and configuration info

        *setup.cfg*
        *minversion*
        *to see*markers*pytest --markers*
        *to see*fixtures*pytest --fixtures*
    """
    )
    result.stdout.no_fnmatch_line("logging:")


def test_hookvalidation_unknown(testdir):
    testdir.makeconftest(
        """
        def pytest_hello(xyz):
            pass
    """
    )
    result = testdir.runpytest()
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*unknown hook*pytest_hello*"])


def test_hookvalidation_optional(testdir):
    testdir.makeconftest(
        """
        import pytest
        @pytest.hookimpl(optionalhook=True)
        def pytest_hello(xyz):
            pass
    """
    )
    result = testdir.runpytest()
    assert result.ret == ExitCode.NO_TESTS_COLLECTED


def test_traceconfig(testdir):
    result = testdir.runpytest("--traceconfig")
    result.stdout.fnmatch_lines(["*using*pytest*py*", "*active plugins*"])


def test_debug(testdir):
    result = testdir.runpytest_subprocess("--debug")
    assert result.ret == ExitCode.NO_TESTS_COLLECTED
    p = testdir.tmpdir.join("pytestdebug.log")
    assert "pytest_sessionstart" in p.read()


def test_PYTEST_DEBUG(testdir, monkeypatch):
    monkeypatch.setenv("PYTEST_DEBUG", "1")
    result = testdir.runpytest_subprocess()
    assert result.ret == ExitCode.NO_TESTS_COLLECTED
    result.stderr.fnmatch_lines(
        ["*pytest_plugin_registered*", "*manager*PluginManager*"]
    )
