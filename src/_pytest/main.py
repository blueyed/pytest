""" core implementation of testing process: init, session, runtest loop. """
import fnmatch
import functools
import importlib
import os
import re
import sys
from typing import Callable
from typing import Dict
from typing import FrozenSet
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Union

import attr
import py

import _pytest._code
from _pytest import nodes
from _pytest.compat import TYPE_CHECKING
from _pytest.config import Config
from _pytest.config import directory_arg
from _pytest.config import ExitCode
from _pytest.config import hookimpl
from _pytest.config import UsageError
from _pytest.fixtures import FixtureManager
from _pytest.outcomes import exit
from _pytest.reports import CollectReport
from _pytest.runner import collect_one_node
from _pytest.runner import SetupState

RE_FNAME_LINENO = re.compile(r"^([^:].[^:]*):(\d+)?(-?)(\d+)?:?$")


if TYPE_CHECKING:
    from typing import Type
    from typing_extensions import Literal

    from _pytest.python import Package


def pytest_addoption(parser):
    parser.addini(
        "norecursedirs",
        "directory patterns to avoid for recursion",
        type="args",
        default=[".*", "build", "dist", "CVS", "_darcs", "{arch}", "*.egg", "venv"],
    )
    parser.addini(
        "testpaths",
        "directories to search for tests when no files or directories are given in the "
        "command line.",
        type="args",
        default=[],
    )
    group = parser.getgroup("general", "running and selection options")
    group._addoption(
        "-x",
        "--exitfirst",
        action="store_const",
        dest="maxfail",
        const=1,
        help="exit instantly on first error or failed test.",
    )
    group._addoption(
        "--maxfail",
        metavar="num",
        action="store",
        type=int,
        dest="maxfail",
        default=0,
        help="exit after first num failures or errors.",
    )
    group._addoption(
        "--strict-markers",
        "--strict",
        action="store_true",
        help="markers not registered in the `markers` section of the configuration file raise errors.",
    )
    group._addoption(
        "-c",
        metavar="file",
        type=str,
        dest="inifilename",
        help="load configuration from `file` instead of trying to locate one of the implicit "
        "configuration files.",
    )
    group._addoption(
        "--continue-on-collection-errors",
        action="store_true",
        default=False,
        dest="continue_on_collection_errors",
        help="Force test execution even if collection errors occur.",
    )
    group._addoption(
        "--rootdir",
        action="store",
        dest="rootdir",
        help="Define root directory for tests. Can be relative path: 'root_dir', './root_dir', "
        "'root_dir/another_dir/'; absolute path: '/home/user/root_dir'; path with variables: "
        "'$HOME/root_dir'.",
    )

    group = parser.getgroup("collect", "collection")
    group.addoption(
        "--collectonly",
        "--collect-only",
        "--co",
        action="store_true",
        help="only collect tests, don't execute them.",
    )
    group.addoption(
        "--pyargs",
        action="store_true",
        help="try to interpret all arguments as python packages.",
    )
    group.addoption(
        "--ignore",
        action="append",
        metavar="path",
        help="ignore path during collection (multi-allowed).",
    )
    group.addoption(
        "--ignore-glob",
        action="append",
        metavar="path",
        help="ignore path pattern during collection (multi-allowed).",
    )
    group.addoption(
        "--deselect",
        action="append",
        metavar="nodeid_prefix",
        help="deselect item (via node id prefix) during collection (multi-allowed).",
    )
    group.addoption(
        "--confcutdir",
        dest="confcutdir",
        default=None,
        metavar="dir",
        type=functools.partial(directory_arg, optname="--confcutdir"),
        help="only load conftest.py's relative to specified dir.",
    )
    group.addoption(
        "--noconftest",
        action="store_true",
        dest="noconftest",
        default=False,
        help="Don't load any conftest.py files.",
    )
    group.addoption(
        "--keepduplicates",
        "--keep-duplicates",
        action="store_true",
        dest="keepduplicates",
        default=False,
        help="Keep duplicate tests.",
    )
    group.addoption(
        "--collect-in-virtualenv",
        action="store_true",
        dest="collect_in_virtualenv",
        default=False,
        help="Don't ignore tests in a local virtualenv directory",
    )

    group = parser.getgroup("debugconfig", "test session debugging and configuration")
    group.addoption(
        "--basetemp",
        dest="basetemp",
        default=None,
        metavar="dir",
        help=(
            "base temporary directory for this test run."
            "(warning: this directory is removed if it exists)"
        ),
    )


def wrap_session(
    config: Config, doit: Callable[[Config, "Session"], Optional[Union[int, ExitCode]]]
) -> Union[int, ExitCode]:
    """Skeleton command line program"""
    session = Session.from_config(config)
    session.exitstatus = ExitCode.OK
    initstate = 0
    try:
        try:
            config._do_configure()
            initstate = 1
            config.hook.pytest_sessionstart(session=session)
            initstate = 2
            session.exitstatus = doit(config, session) or 0
        except UsageError:
            session.exitstatus = ExitCode.USAGE_ERROR
            raise
        except Failed as exc:
            if not session.shouldfail:
                # Typically Failed is raised when session.shouldfail has been
                # set.  This sets it for when the exception was raised only.
                session.shouldfail = exc.args[0]
            session.exitstatus = ExitCode.TESTS_FAILED
        except (KeyboardInterrupt, exit.Exception):
            excinfo = _pytest._code.ExceptionInfo.from_current()
            exitstatus = ExitCode.INTERRUPTED  # type: Union[int, ExitCode]
            if isinstance(excinfo.value, exit.Exception):
                if excinfo.value.returncode is not None:
                    exitstatus = excinfo.value.returncode
                if initstate < 2:
                    sys.stderr.write(
                        "{}: {}\n".format(excinfo.typename, excinfo.value.msg)
                    )
            config.hook.pytest_keyboard_interrupt(excinfo=excinfo)
            session.exitstatus = exitstatus
        except:  # noqa
            session.exitstatus = ExitCode.INTERNAL_ERROR
            excinfo = _pytest._code.ExceptionInfo.from_current()
            try:
                config.notify_exception(excinfo, config.option)
            except exit.Exception as exc:
                if exc.returncode is not None:
                    session.exitstatus = exc.returncode
                sys.stderr.write("{}: {}\n".format(type(exc).__name__, exc))
            else:
                if excinfo.errisinstance(SystemExit):
                    sys.stderr.write("mainloop: caught unexpected SystemExit!\n")

    finally:
        # Explicitly break reference cycle.
        excinfo = None  # type: ignore
        session.startdir.chdir()
        if initstate >= 2:
            try:
                config.hook.pytest_sessionfinish(
                    session=session, exitstatus=session.exitstatus
                )
            except exit.Exception as exc:
                if exc.returncode is not None:
                    session.exitstatus = exc.returncode
                sys.stderr.write("{}: {}\n".format(type(exc).__name__, exc))
        config._ensure_unconfigure()
    return session.exitstatus


def pytest_cmdline_main(config):
    return wrap_session(config, _main)


def _main(config: Config, session: "Session") -> Optional[Union[int, ExitCode]]:
    """ default command line protocol for initialization, session,
    running tests and reporting. """
    config.hook.pytest_collection(session=session)
    config.hook.pytest_runtestloop(session=session)

    if session.testsfailed:
        return ExitCode.TESTS_FAILED
    elif session.testscollected == 0:
        return ExitCode.NO_TESTS_COLLECTED
    return None


def pytest_collection(session):
    return session.perform_collect()


def pytest_runtestloop(session):
    if session.testsfailed and not session.config.option.continue_on_collection_errors:
        raise session.Interrupted(
            "%d error%s during collection"
            % (session.testsfailed, "s" if session.testsfailed != 1 else "")
        )

    if session.config.option.collectonly:
        return True

    for i, item in enumerate(session.items):
        nextitem = session.items[i + 1] if i + 1 < len(session.items) else None
        item.config.hook.pytest_runtest_protocol(item=item, nextitem=nextitem)
        if session.shouldfail:
            raise session.Failed(session.shouldfail)
        if session.shouldstop:
            raise session.Interrupted(session.shouldstop)
    return True


def _in_venv(path):
    """Attempts to detect if ``path`` is the root of a Virtual Environment by
    checking for the existence of the appropriate activate script"""
    bindir = path.join("Scripts" if sys.platform.startswith("win") else "bin")
    if not bindir.isdir():
        return False
    activates = (
        "activate",
        "activate.csh",
        "activate.fish",
        "Activate",
        "Activate.bat",
        "Activate.ps1",
    )
    return any([fname.basename in activates for fname in bindir.listdir()])


def pytest_collection_modifyitems(items, config):
    deselect_prefixes = tuple(config.getoption("deselect") or [])
    if not deselect_prefixes:
        return

    remaining = []
    deselected = []
    for colitem in items:
        if colitem.nodeid.startswith(deselect_prefixes):
            deselected.append(colitem)
        else:
            remaining.append(colitem)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = remaining


class NoMatch(Exception):
    """ raised if matching cannot locate a matching names. """


class Interrupted(KeyboardInterrupt):
    """ signals an interrupted test run. """

    __module__ = "builtins"  # for py3


class Failed(Exception):
    """ signals a stop as failed test run. """


@attr.s
class _bestrelpath_cache(dict):
    path = attr.ib(type=py.path.local)

    def __missing__(self, path: py.path.local) -> str:
        r = self.path.bestrelpath(path)  # type: str
        self[path] = r
        return r


class Session(nodes.FSCollector):
    Interrupted = Interrupted
    Failed = Failed
    # Set on the session by runner.pytest_sessionstart.
    _setupstate = None  # type: SetupState
    # Set on the session by fixtures.pytest_sessionstart.
    _fixturemanager = None  # type: FixtureManager
    exitstatus = None  # type: Union[int, ExitCode]

    def __init__(self, config: Config) -> None:
        nodes.FSCollector.__init__(
            self, config.rootdir, parent=None, config=config, session=self, nodeid=""
        )
        self.testsfailed = 0
        self.testscollected = 0
        self.shouldstop = False
        self.shouldfail = False
        self.trace = config.trace.root.get("collection")
        self.startdir = config.invocation_dir
        self._initialpaths = frozenset()  # type: FrozenSet[py.path.local]

        # Keep track of any collected nodes in here, so we don't duplicate fixtures
        self._collection_node_cache1 = (
            {}
        )  # type: Dict[py.path.local, Sequence[nodes.Collector]]
        self._collection_node_cache2 = (
            {}
        )  # type: Dict[Tuple[Type[nodes.Collector], py.path.local], nodes.Collector]
        self._collection_node_cache3 = (
            {}
        )  # type: Dict[Tuple[Type[nodes.Collector], str], CollectReport]

        # Dirnames of pkgs with dunder-init files.
        self._collection_pkg_roots = {}  # type: Dict[py.path.local, Package]

        self._bestrelpathcache = _bestrelpath_cache(
            config.rootdir
        )  # type: Dict[py.path.local, str]

        self.config.pluginmanager.register(self, name="session")

        self._deselected = []  # type: List[nodes.Item]

        #: Count of ignored paths (for reporting).
        self._collect_ignored = {}  # type: Dict[str, int]

    @classmethod
    def from_config(cls, config):
        return cls._create(config)

    def __repr__(self):
        return "<%s %s exitstatus=%r testsfailed=%d testscollected=%d>" % (
            self.__class__.__name__,
            self.name,
            getattr(self, "exitstatus", "<UNSET>"),
            self.testsfailed,
            self.testscollected,
        )

    def _node_location_to_relpath(self, node_path: py.path.local) -> str:
        # bestrelpath is a quite slow function
        return self._bestrelpathcache[node_path]

    @hookimpl(tryfirst=True)
    def pytest_collectstart(self):
        if self.shouldfail:
            raise self.Failed(self.shouldfail)
        if self.shouldstop:
            raise self.Interrupted(self.shouldstop)

    def _register_collect_ignored(self, when: str) -> None:
        self._collect_ignored.setdefault(when, 0)
        self._collect_ignored[when] += 1

    def pytest_ignore_collect(
        self, path: py.path.local, config: Config
    ) -> "Optional[Literal[True]]":
        if path.basename[:1] == ".":
            return True

        collect_ignore = config._getconftest_pathlist(
            "collect_ignore", path=path.dirpath()
        )
        if collect_ignore and py.path.local(path) in collect_ignore:
            self._register_collect_ignored("collect_ignore")
            return True
        excludeopt = config.getoption("ignore")
        if excludeopt:
            ignore_paths = [py.path.local(x) for x in excludeopt]
            if py.path.local(path) in ignore_paths:
                self._register_collect_ignored("--ignore")
                return True

        collect_ignore_glob = config._getconftest_pathlist(
            "collect_ignore_glob", path=path.dirpath()
        )
        if collect_ignore_glob and any(
            fnmatch.fnmatch(str(path), str(glob)) for glob in collect_ignore_glob
        ):
            self._register_collect_ignored("collect_ignore_glob")
            return True
        excludeglobopt = config.getoption("ignore_glob")
        if excludeglobopt:
            ignore_globs = [py.path.local(x) for x in excludeglobopt]
            if any(fnmatch.fnmatch(str(path), str(glob)) for glob in ignore_globs):
                self._register_collect_ignored("--ignore_glob")
                return True

        allow_in_venv = config.getoption("collect_in_virtualenv")
        if not allow_in_venv and _in_venv(path):
            self._register_collect_ignored("--collect-in-virtualenv")
            return True
        return None

    def pytest_report_collectionfinish(self) -> Optional[str]:
        if not self._collect_ignored:
            return None

        total = 0
        desc = []
        for via, count in self._collect_ignored.items():
            total += count
            if len(self._collect_ignored) > 1:
                desc.append("{} ({})".format(via, count))
            else:
                desc.append("via {}".format(via))
        return "ignored {} {} ({})".format(
            total, "path" if total == 1 else "paths", ", ".join(desc)
        )

    @hookimpl(tryfirst=True)
    def pytest_runtest_logreport(self, report):
        if report.failed and not hasattr(report, "wasxfail"):
            self.testsfailed += 1
            maxfail = self.config.getvalue("maxfail")
            if maxfail and self.testsfailed >= maxfail:
                self.shouldfail = "stopping after {} failure{}".format(
                    self.testsfailed, "s" if self.testsfailed > 1 else ""
                )

    pytest_collectreport = pytest_runtest_logreport

    def isinitpath(self, path):
        return path in self._initialpaths

    def gethookproxy(self, fspath: py.path.local):
        return super()._gethookproxy(fspath)

    def pytest_deselected(self, items):
        """Keep track of explicitly deselected items."""
        self._deselected.extend(items)

    def perform_collect(self, args=None, genitems=True):
        hook = self.config.hook
        try:
            items = self._perform_collect(args, genitems)
            self.config.pluginmanager.check_pending()

            items_before = set(items)
            hook.pytest_collection_modifyitems(
                session=self, config=self.config, items=items
            )
            ignore = set(self._deselected + items)
            removed_items = items_before.difference(ignore)
            if removed_items:
                # Explicitly deselect them.
                # Calls the own hook again, but that is OK.
                self.config.hook.pytest_deselected(items=list(removed_items))
        finally:
            hook.pytest_collection_finish(session=self)
        self.testscollected = len(items)
        return items

    def _perform_collect(self, args, genitems):
        if args is None:
            args = self.config.args
        self.trace("perform_collect", self, args)
        self.trace.root.indent += 1
        self._notfound = []
        initialpaths = []  # type: List[py.path.local]
        self._initial_parts = []  # type: List[Tuple[py.path.local, List[str]]]
        self.items = items = []  # type: List[nodes.Item]
        for arg in args:
            fspath, parts = self._parsearg(arg)
            self._initial_parts.append((fspath, parts))
            initialpaths.append(fspath)
        self._initialpaths = frozenset(initialpaths)
        rep = collect_one_node(self)
        self.ihook.pytest_collectreport(report=rep)
        self.trace.root.indent -= 1
        if self._notfound:
            errors = []
            for arg, exc in self._notfound:
                line = "(no name {!r} in any of {!r})".format(arg, exc.args[0])
                errors.append("not found: {}\n{}".format(arg, line))
            raise UsageError(*errors)
        if not genitems:
            return rep.result
        else:
            if rep.passed:
                for node in rep.result:
                    self.items.extend(self.genitems(node))
            return items

    def collect(self):
        for fspath, parts in self._initial_parts:
            self.trace("processing argument", (fspath, parts))
            self.trace.root.indent += 1
            try:
                yield from self._collect(fspath, parts)
            except NoMatch:
                report_arg = "::".join((str(fspath), *parts))
                # we are inside a make_report hook so
                # we cannot directly pass through the exception
                self._notfound.append((report_arg, sys.exc_info()[1]))

            self.trace.root.indent -= 1
        self._collection_node_cache1.clear()
        self._collection_node_cache2.clear()
        self._collection_node_cache3.clear()
        self._collection_pkg_roots.clear()

    def _collect(self, argpath, names):
        from _pytest.python import Package

        # Start with a Session root, and delve to argpath item (dir or file)
        # and stack all Packages found on the way.
        # No point in finding packages when collecting doctests
        if not self.config.getoption("doctestmodules", False):
            pm = self.config.pluginmanager
            for parent in reversed(argpath.parts()):
                if pm._confcutdir and pm._confcutdir.relto(parent):
                    break

                if parent.isdir():
                    pkginit = parent.join("__init__.py")
                    if pkginit.isfile():
                        if pkginit not in self._collection_node_cache1:
                            col = self._collectfile(pkginit, handle_dupes=False)
                            if col:
                                if isinstance(col[0], Package):
                                    self._collection_pkg_roots[parent] = col[0]
                                # always store a list in the cache, matchnodes expects it
                                self._collection_node_cache1[col[0].fspath] = [col[0]]

        # If it's a directory argument, recurse and look for any Subpackages.
        # Let the Package collector deal with subnodes, don't collect here.
        if argpath.check(dir=1):
            assert not names, "invalid arg {!r}".format((argpath, names))

            seen_dirs = set()
            for path in argpath.visit(
                fil=self._visit_filter, rec=self._recurse, bf=True, sort=True
            ):
                dirpath = path.dirpath()
                if dirpath not in seen_dirs:
                    # Collect packages first.
                    seen_dirs.add(dirpath)
                    pkginit = dirpath.join("__init__.py")
                    if pkginit.exists():
                        for x in self._collectfile(pkginit):
                            yield x
                            if isinstance(x, Package):
                                self._collection_pkg_roots[dirpath] = x
                if dirpath in self._collection_pkg_roots:
                    # Do not collect packages here.
                    continue

                for x in self._collectfile(path):
                    key = (type(x), x.fspath)
                    if key in self._collection_node_cache2:
                        yield self._collection_node_cache2[key]
                    else:
                        self._collection_node_cache2[key] = x
                        yield x
        else:
            assert argpath.check(file=1)

            if argpath in self._collection_node_cache1:
                col = self._collection_node_cache1[argpath]
            else:
                collect_root = self._collection_pkg_roots.get(argpath.dirname, self)
                col = collect_root._collectfile(argpath, handle_dupes=False)
                if col:
                    self._collection_node_cache1[argpath] = col
            m = self.matchnodes(col, names)
            # If __init__.py was the only file requested, then the matched node will be
            # the corresponding Package, and the first yielded item will be the __init__
            # Module itself, so just use that. If this special case isn't taken, then all
            # the files in the package will be yielded.
            if argpath.basename == "__init__.py":
                try:
                    yield next(m[0].collect())
                except StopIteration:
                    # The package collects nothing with only an __init__.py
                    # file in it, which gets ignored by the default
                    # "python_files" option.
                    pass
                return
            yield from m

    @staticmethod
    def _visit_filter(f):
        return f.check(file=1)

    def _tryconvertpyarg(self, x):
        """Convert a dotted module name to path."""
        try:
            spec = importlib.util.find_spec(x)
        # AttributeError: looks like package module, but actually filename
        # ImportError: module does not exist
        # ValueError: not a module name
        except (AttributeError, ImportError, ValueError):
            return x
        if spec is None or spec.origin in {None, "namespace"}:
            return x
        elif spec.submodule_search_locations:
            return os.path.dirname(spec.origin)
        else:
            return spec.origin

    @staticmethod
    def _parse_fname_lineno(
        arg: str,
    ) -> Tuple[str, Tuple[Optional[int], Optional[int]]]:
        fname = arg
        start, end = None, None
        if ":" in arg:
            m = RE_FNAME_LINENO.match(arg)
            if m:
                fname = m.group(1)
                is_range = m.group(3)
                start_ = m.group(2)
                if start_:
                    start = int(start_)
                end_ = m.group(4)
                if end_:
                    end = int(end_)
                elif not is_range:
                    end = start
        return fname, (start, end)

    def _parsearg(self, arg):
        """ return (fspath, names) tuple after checking the file exists. """
        strpath, *parts = str(arg).split("::")
        if self.config.option.pyargs:
            strpath = self._tryconvertpyarg(strpath)

        fname, lineno = self._parse_fname_lineno(strpath)

        relpath = fname.replace("/", os.sep)
        fspath = self.config.invocation_dir.join(relpath, abs=True)
        if not fspath.check():
            if self.config.option.pyargs:
                raise UsageError(
                    "file or package not found: " + arg + " (missing __init__.py?)"
                )
            raise UsageError("file not found: " + arg)
        fspath = fspath.realpath()
        fspath.lineno = lineno
        return (fspath, parts)

    def matchnodes(self, matching, names):
        self.trace("matchnodes", matching, names)
        self.trace.root.indent += 1
        nodes = self._matchnodes(matching, names)
        num = len(nodes)
        self.trace("matchnodes finished -> ", num, "nodes")
        self.trace.root.indent -= 1
        if num == 0:
            raise NoMatch(matching, names[:1])
        return nodes

    def _matchnodes(self, matching, names):
        if not matching or not names:
            return matching
        name = names[0]
        assert name
        nextnames = names[1:]
        resultnodes = []
        for node in matching:
            if isinstance(node, nodes.Item):
                if not names:
                    resultnodes.append(node)
                continue
            assert isinstance(node, nodes.Collector)
            key = (type(node), node.nodeid)
            if key in self._collection_node_cache3:
                rep = self._collection_node_cache3[key]
            else:
                rep = collect_one_node(node)
                self._collection_node_cache3[key] = rep
            if rep.passed:
                has_matched = False
                for x in rep.result:
                    # TODO: remove parametrized workaround once collection structure contains parametrization
                    if x.name == name or x.name.split("[")[0] == name:
                        resultnodes.extend(self.matchnodes([x], nextnames))
                        has_matched = True
                # XXX accept IDs that don't have "()" for class instances
                if not has_matched and len(rep.result) == 1 and x.name == "()":
                    nextnames.insert(0, name)
                    resultnodes.extend(self.matchnodes([x], nextnames))
            else:
                # report collection failures here to avoid failing to run some test
                # specified in the command line because the module could not be
                # imported (#134)
                node.ihook.pytest_collectreport(report=rep)
        return resultnodes

    def genitems(self, node):
        self.trace("genitems", node)
        if isinstance(node, nodes.Item):
            node.ihook.pytest_itemcollected(item=node)
            yield node
        else:
            assert isinstance(node, nodes.Collector)
            rep = collect_one_node(node)
            if rep.passed:
                for subnode in rep.result:
                    try:
                        collect_lnum = node.fspath.lineno
                    except AttributeError:
                        collect_lnum = None

                    if collect_lnum and (collect_lnum[0] or collect_lnum[1]):
                        import inspect

                        start, end = collect_lnum

                        for item in self.genitems(subnode):
                            lines, lnum = inspect.getsourcelines(item.obj)
                            if (end is None or end >= lnum) and (
                                start is None or start <= lnum + len(lines)
                            ):
                                yield item
                            else:
                                node.ihook.pytest_deselected(items=[item])
                    else:
                        yield from self.genitems(subnode)
            node.ihook.pytest_collectreport(report=rep)
