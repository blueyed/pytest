""" version info, help messages, tracing configuration.  """
import os
import sys
import types
from argparse import Action
from typing import Generator
from typing import List
from typing import Optional
from typing import Tuple

import py.path

import pytest
from _pytest.compat import TYPE_CHECKING
from _pytest.config import Config
from _pytest.config import PrintHelp
from _pytest.pathlib import _shorten_path

if TYPE_CHECKING:
    from typing_extensions import Literal  # noqa: F401


class HelpAction(Action):
    """This is an argparse Action that will raise an exception in
    order to skip the rest of the argument parsing when --help is passed.
    This prevents argparse from quitting due to missing required arguments
    when any are defined, for example by ``pytest_addoption``.
    This is similar to the way that the builtin argparse --help option is
    implemented by raising SystemExit.
    """

    def __init__(self, option_strings, dest=None, default=False, help=None):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            const=True,
            default=default,
            nargs=0,
            help=help,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, self.const)

        # We should only skip the rest of the parsing after preparse is done
        if getattr(parser._parser, "after_preparse", False):
            raise PrintHelp


def pytest_addoption(parser):
    group = parser.getgroup("debugconfig")
    group.addoption(
        "--version",
        "-V",
        action="store_const",
        const=True,
        help="display pytest version and information about plugins.",
    )
    group._addoption(
        "-h",
        "--help",
        action=HelpAction,
        dest="help",
        help="show help message and configuration info",
    )
    group._addoption(
        "-p",
        action="append",
        dest="plugins",
        default=[],
        metavar="name",
        help="early-load given plugin module name or entry point (multi-allowed).\n"
        "To avoid loading of plugins, use the `no:` prefix, e.g. "
        "`no:doctest`.  "
        "`no:[defaults]` disables all non-essential default plugins.",
    )
    group.addoption(
        "--traceconfig",
        "--trace-config",
        action="store_true",
        default=False,
        help="trace considerations of conftest.py files.",
    )
    group.addoption(
        "--debug",
        action="store_true",
        dest="debug",
        default=False,
        help="store internal tracing debug information in 'pytestdebug.log'.",
    )
    group._addoption(
        "-o",
        "--override-ini",
        dest="override_ini",
        action="append",
        help='override ini option with "option=value" style, e.g. `-o xfail_strict=True -o cache_dir=cache`.',
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_cmdline_parse() -> Generator:
    outcome = yield
    config = outcome.get_result()  # type: Config
    if config.option.debug:
        path = os.path.abspath("pytestdebug.log")
        debugfile = open(path, "w")
        debugfile.write(
            "versions pytest-%s, py-%s, "
            "python-%s\ncwd=%s\nargs=%s\n\n"
            % (
                pytest.__version__,
                py.__version__,
                ".".join(map(str, sys.version_info)),
                os.getcwd(),
                config.invocation_params.args,
            )
        )
        config.trace.root.setwriter(debugfile.write)
        undo_tracing = config.pluginmanager.enable_tracing()
        sys.stderr.write("writing pytestdebug information to %s\n" % path)

        def unset_tracing():
            debugfile.close()
            sys.stderr.write("wrote pytestdebug information to %s\n" % debugfile.name)
            config.trace.root.setwriter(None)
            undo_tracing()

        config.add_cleanup(unset_tracing)


def showversion(config: Config) -> None:
    sys.stderr.write(
        "This is pytest version {}, imported from {}\n".format(
            pytest.__version__, pytest.__file__
        )
    )
    for line in getpluginversioninfo(config):
        sys.stderr.write(line + "\n")


def pytest_cmdline_main(config: Config) -> Optional["Literal[0]"]:
    if config.option.version:
        config._do_configure()
        showversion(config)
    elif config.option.help:
        config._do_configure()
        showhelp(config)
    else:
        return None

    _show_warnings(config)
    return 0


def showhelp(config: Config) -> None:
    import textwrap
    from _pytest.terminal import get_terminal_width

    config._parser.optparser.print_help()
    print()
    print("[pytest] ini-options in the first pytest.ini|tox.ini|setup.cfg file found:")
    print()

    columns = max(40, get_terminal_width())
    indent_len = 24  # based on argparse's max_help_position=24
    wrap_width = columns - indent_len
    indent = " " * indent_len
    for name in config._parser._ininames:
        help, type, default = config._parser._inidict[name]
        if type is None:
            type = "string"
        spec = "{} ({}):".format(name, type)
        print("  %s" % spec, end="")
        spec_len = len(spec)
        if spec_len > (indent_len - 3):
            # Display help starting at a new line.
            print()
            helplines = textwrap.wrap(
                help,
                columns,
                initial_indent=indent,
                subsequent_indent=indent,
                break_on_hyphens=False,
            )

            for line in helplines:
                print(line)
        else:
            # Display help starting after the spec, following lines indented.
            print(" " * (indent_len - spec_len - 2), end="")
            wrapped = textwrap.wrap(help, wrap_width, break_on_hyphens=False)

            print(wrapped[0])
            for line in wrapped[1:]:
                print(indent + line)

    print()
    print("environment variables:")
    vars = [
        ("PYTEST_ADDOPTS", "extra command line options"),
        ("PYTEST_PLUGINS", "comma-separated plugins to load during startup"),
        ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "set to disable plugin auto-loading"),
        ("PYTEST_DEBUG", "set to enable debug tracing of pytest's internals"),
    ]
    for name, help in vars:
        print("  {:<24} {}".format(name, help))
    print()
    print()

    print("to see available markers type: pytest --markers")
    print("to see available fixtures type: pytest --fixtures")
    print(
        "(shown according to specified file_or_dir or current dir "
        "if not specified; fixtures with leading '_' are only shown "
        "with the '-v' option"
    )

    _show_warnings(config)


def _show_warnings(config: Config) -> None:
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter:
        tw = reporter._tw
        for warningreport in reporter.stats.get("warnings", []):
            tw.line()
            tw.line("warning : " + warningreport.message, red=True)


conftest_options = [("pytest_plugins", "list of plugin names to load")]


def get_plugin_info(
    config: Config, include_non_eps: bool = False, verbose: bool = False
) -> Tuple[List[str], List[str]]:
    distnames = []  # type: List[str]
    othernames = []  # type: List[str]

    pm = config.pluginmanager
    distplugins = {plugin: dist for plugin, dist in pm.list_plugin_distinfo()}
    prev_dist = None
    for name, plugin in pm.list_name_plugin():
        if plugin in distplugins:
            dist = distplugins[plugin]
            if verbose:
                dist_name = "{}-{}".format(dist.project_name, dist.version)
                if dist_name != prev_dist:
                    distnames.append("{}:".format(dist_name))
                    prev_dist = dist_name

                if isinstance(plugin, types.ModuleType):
                    loc = getattr(plugin, "__file__", repr(plugin))
                    distnames.append("  {} at {}".format(name, loc))
                else:
                    mod = plugin.__module__
                    loc = getattr(sys.modules[mod], "__file__", repr(plugin))
                    distnames.append("  {} at {}:{}".format(name, loc, plugin.__name__))
                continue

            # gets us name and version!
            name = "{dist.project_name}-{dist.version}".format(dist=dist)
            # questionable convenience, but it keeps things short
            if name.startswith("pytest-"):
                name = name[7:]
            # we decided to print python package names
            # they can have more than one plugin
            if name not in distnames:
                distnames.append(name)
        elif include_non_eps:
            if isinstance(plugin, types.ModuleType):
                mod, modname = plugin, plugin.__name__
                if modname.startswith("_pytest."):
                    continue
                if verbose:
                    name = getattr(mod, "__file__", repr(plugin))
                elif modname == "conftest" and hasattr(mod, "__file__"):
                    # Use relative path for conftest plugins.
                    name = _shorten_path(
                        mod.__file__, relative_to=str(config.invocation_params.dir)
                    )
            else:
                modname = getattr(plugin, "__module__", None)
                if modname and modname.startswith("_pytest."):
                    continue
                if modname is not None and verbose:
                    loc = getattr(sys.modules[modname], "__file__", repr(plugin))
                    name += " at {}".format(loc)
            othernames.append(name)
    return distnames, othernames


def getpluginversioninfo(config: Config) -> List[str]:
    lines = []
    distplugins, otherplugins = get_plugin_info(
        config, include_non_eps=True, verbose=True
    )
    if distplugins:
        lines.append("setuptools registered plugins:")
        for distplugin in distplugins:
            lines.append("  " + distplugin)
    if otherplugins:
        lines.append("other plugins:")
        for otherplugin in otherplugins:
            lines.append("  " + otherplugin)
    return lines


def pytest_report_header(config: Config) -> List[str]:
    lines = []
    if config.option.debug or config.option.traceconfig:
        lines.append(
            "using: pytest-{} pylib-{}".format(pytest.__version__, py.__version__)
        )
        lines.extend(getpluginversioninfo(config))

    if config.option.traceconfig:
        lines.append("active plugins:")
        items = config.pluginmanager.list_name_plugin()
        for name, plugin in items:
            if hasattr(plugin, "__file__"):
                r = plugin.__file__
            else:
                r = repr(plugin)
            lines.append("    {:<20}: {}".format(name, r))
    return lines
