import os
import re

import pytest
from _pytest.config import ExitCode
from _pytest.pytester import Testdir


def test_version(testdir: Testdir) -> None:
    """Test --version output, especially with regard to (entrypoint) plugins."""
    testdir.monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD")
    testdir.makefiles(
        {
            "PKG-INFO": """
                Name: myproject
                Version: 1.0.0
                """,
            "entry_points.txt": """
                [pytest11]
                EP MyPlugin = ep_plugin:MyPlugin
                EP module = ep_plugin
                """,
        },
        base_path="myproject.egg-info",
    )

    # Only load our entrypoint plugin.
    def is_blocked_ep(self, ep):
        return not ep.name.startswith("EP ")

    testdir.monkeypatch.setattr(
        "_pytest.config.PytestPluginManager.is_blocked_ep", is_blocked_ep
    )

    ep_plugin = testdir.makepyfile(ep_plugin="class MyPlugin: pass")
    other_plugin = testdir.makepyfile(
        other_plugin="""
        class MyPlugin:
            pass
        def pytest_configure(config):
            config.pluginmanager.register("MyPluginAsString()", "plugin name")
            config.pluginmanager.register(MyPlugin(), "plugin name 2")
            config.pluginmanager.register(MyPlugin())
    """
    )
    conftest = testdir.makeconftest("")
    tests_conftest = testdir.makepyfile(
        **{
            "tests/conftest.py": """
                class MyConftestPlugin():
                    pass
                def pytest_configure(config):
                    config.pluginmanager.register(object(), "conftest-name-object")
                    config.pluginmanager.register(MyConftestPlugin())
        """,
        }
    )

    testdir.syspathinsert()
    result = testdir.runpytest("--version", "-p", "other_plugin")
    expected_stderr = [
        "*pytest*{}*imported from*".format(pytest.__version__),
        "setuptools registered plugins:",
        "  myproject-1.0.0:",
        "    EP MyPlugin at {}:MyPlugin".format(ep_plugin),
        "    EP module at {}".format(ep_plugin),
        "other plugins:",
        "  {}".format(other_plugin),
        "  {}".format(conftest),
        "  {}".format(tests_conftest),
        "  conftest-name-object",
        "  [0-9]*[0-9] at {}".format(tests_conftest),
        "  plugin name",
        "  plugin name 2 at {}".format(other_plugin),
        "  [0-9]*[0-9] at {}".format(other_plugin),
    ]
    result.stderr.fnmatch_lines(expected_stderr, consecutive=True)
    assert len(result.stderr.lines) == len(expected_stderr)
    assert result.ret == 0

    # Cover/test terminal's pytest_report_header.
    result = testdir.runpytest("-p", "other_plugin", "--co")
    result.stdout.fnmatch_lines(["plugins: myproject-1.0.0"])
    result = testdir.runpytest("-p", "other_plugin", "--co", "-v")
    result.stdout.re_match_lines(
        [
            r"plugins: myproject-1.0.0; other_plugin, conftest.py,"
            r" tests{}conftest.py, conftest-name-object, \d+, plugin name,"
            r" plugin name 2, \d+".format(re.escape(os.path.sep)),
        ]
    )

    # Does report blocked plugins.
    result = testdir.runpytest("--version", "-p", "no:EP MyPlugin")
    expected_stderr = [
        "*pytest*{}*imported from*".format(pytest.__version__),
        "setuptools registered plugins:",
        "  myproject-1.0.0:",
        "    EP module at {}".format(ep_plugin),
        "other plugins:",
        "  {}".format(conftest),
        "  {}".format(tests_conftest),
        "  conftest-name-object",
        "  [0-9]*[0-9] at {}".format(tests_conftest),
        'blocked plugins (NOTE: "pytest_" prefix gets added automatically):',
        "  EP MyPlugin",
        "  pytest_EP MyPlugin",
    ]
    result.stderr.fnmatch_lines(expected_stderr, consecutive=True)
    assert len(result.stderr.lines) == len(expected_stderr)
    assert result.ret == 0

    # Does not add note unnecessarily.
    result = testdir.runpytest("--version", "-p", "no:pytest_foo")
    assert result.stderr.lines[-2:] == [
        "blocked plugins:",
        "  pytest_foo",
    ]
    assert result.ret == 0


def test_help(testdir: Testdir) -> None:
    result = testdir.runpytest("--help", "-p", "no:[defaults]")
    assert result.ret == 0
    trans_escape = str.maketrans({"[": "[[]", "]": "[]]"})
    result.stdout.fnmatch_lines(
        """
        usage: * [options] [file_or_dir] [file_or_dir] [...]

        positional arguments:
          file_or_dir

          -m MARKEXPR           only run tests matching given mark expression.
                                For example: -m 'mark1 and not mark2'.
        reporting:
          --durations=N *

        collection:
          --[no-]collect-only, --[no-]co
          --[no-]conftest       Don't load any conftest.py files.

        test session debugging and configuration:
          -V, --version         display pytest version and information about plugins.
          -h, --help            show help message and configuration info

        *setup.cfg*
        *minversion*
        *to see*markers*pytest --markers*
        *to see*fixtures*pytest --fixtures*
    """.translate(
            trans_escape
        )
    )
    result.stdout.no_fnmatch_line("logging:")


@pytest.mark.parametrize("method", ("runpytest_inprocess", "runpytest_subprocess"))
def test_help_unconfigures_always(method: str, testdir: Testdir) -> None:
    testdir.makeconftest(
        """
        def pytest_addoption(parser):
            parser._usage = "%(crash_help)s"
        """
    )
    testdir.makepyfile(
        myplugin="""
        def pytest_configure():
            print("plugin pytest_configure")

        def pytest_unconfigure():
            print("plugin pytest_unconfigure")
        """
    )
    testdir.syspathinsert()
    result = getattr(testdir, method)("--help", "-p", "no:[defaults]", "-p", "myplugin")
    assert result.stdout.lines == [
        "plugin pytest_configure",
        "plugin pytest_unconfigure",
    ]
    assert "KeyError: 'crash_help'" in result.stderr.lines

    # XXX: should have the same exitcode?!
    if method == "runpytest_inprocess":
        assert result.ret == ExitCode.INTERNAL_ERROR
    else:
        assert result.ret == ExitCode.TESTS_FAILED


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
