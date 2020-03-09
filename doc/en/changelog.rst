.. toctree::
  :hidden:

  archive/changelog

.. _`changelog`:

=========
Changelog
=========

Versions follow `Semantic Versioning <https://semver.org/>`_ (``<major>.<minor>.<patch>``).

Backward incompatible (breaking) changes will only be introduced in major versions
with advance notice in the **Deprecations** section of releases.


..
    You should *NOT* be adding new change log entries to this file, this
    file is managed by towncrier. You *may* edit previous change logs to
    fix problems like typo corrections or such.
    To add a new change log entry, please see
    https://pip.pypa.io/en/latest/development/contributing/#news-entries
    we named the news folder changelog


.. only:: changelog_towncrier_draft

    .. The 'changelog_towncrier_draft' tag is included by our 'tox -e docs',
       but not on readthedocs.

    ----

    Changelog draft
    ===============

    .. include:: _changelog_towncrier_draft.rst

    ----

pytest 5.3.5 (2020-01-29)
=========================

Bug Fixes
---------

- `#6517 <https://github.com/pytest-dev/pytest/issues/6517>`_: Fix regression in pytest 5.3.4 causing an INTERNALERROR due to a wrong assertion.


pytest 5.3.4 (2020-01-20)
=========================

Bug Fixes
---------

- `#6496 <https://github.com/pytest-dev/pytest/issues/6496>`_: Revert `#6436 <https://github.com/pytest-dev/pytest/issues/6436>`__: unfortunately this change has caused a number of regressions in many suites,
  so the team decided to revert this change and make a new release while we continue to look for a solution.


pytest 5.3.3 (2020-01-16)
=========================

Bug Fixes
---------

- `#2780 <https://github.com/pytest-dev/pytest/issues/2780>`_: Captured output during teardown is shown with ``-rP``.


- `#5971 <https://github.com/pytest-dev/pytest/issues/5971>`_: Fix a ``pytest-xdist`` crash when dealing with exceptions raised in subprocesses created by the
  ``multiprocessing`` module.


- `#6436 <https://github.com/pytest-dev/pytest/issues/6436>`_: :class:`FixtureDef <_pytest.fixtures.FixtureDef>` objects now properly register their finalizers with autouse and
  parameterized fixtures that execute before them in the fixture stack so they are torn
  down at the right times, and in the right order.


- `#6532 <https://github.com/pytest-dev/pytest/issues/6532>`_: Fix parsing of outcomes containing multiple errors with ``testdir`` results (regression in 5.3.0).



Trivial/Internal Changes
------------------------

- `#6350 <https://github.com/pytest-dev/pytest/issues/6350>`_: Optimized automatic renaming of test parameter IDs.


pytest 5.3.2 (2019-12-13)
=========================

Improvements
------------

- `#4639 <https://github.com/pytest-dev/pytest/issues/4639>`_: Revert "A warning is now issued when assertions are made for ``None``".

  The warning proved to be less useful than initially expected and had quite a
  few false positive cases.



Bug Fixes
---------

- `#5430 <https://github.com/pytest-dev/pytest/issues/5430>`_: junitxml: Logs for failed test are now passed to junit report in case the test fails during call phase.


- `#6290 <https://github.com/pytest-dev/pytest/issues/6290>`_: The supporting files in the ``.pytest_cache`` directory are kept with ``--cache-clear``, which only clears cached values now.


- `#6301 <https://github.com/pytest-dev/pytest/issues/6301>`_: Fix assertion rewriting for egg-based distributions and ``editable`` installs (``pip install --editable``).


pytest 5.3.1 (2019-11-25)
=========================

Improvements
------------

- `#6231 <https://github.com/pytest-dev/pytest/issues/6231>`_: Improve check for misspelling of :ref:`pytest.mark.parametrize ref`.


- `#6257 <https://github.com/pytest-dev/pytest/issues/6257>`_: Handle :py:func:`_pytest.outcomes.exit` being used via :py:func:`~_pytest.hookspec.pytest_internalerror`, e.g. when quitting pdb from post mortem.



Bug Fixes
---------

- `#5914 <https://github.com/pytest-dev/pytest/issues/5914>`_: pytester: fix :py:func:`~_pytest.pytester.LineMatcher.no_fnmatch_line` when used after positive matching.


- `#6082 <https://github.com/pytest-dev/pytest/issues/6082>`_: Fix line detection for doctest samples inside :py:class:`python:property` docstrings, as a workaround to `bpo-17446 <https://bugs.python.org/issue17446>`__.


- `#6254 <https://github.com/pytest-dev/pytest/issues/6254>`_: Fix compatibility with pytest-parallel (regression in pytest 5.3.0).


- `#6255 <https://github.com/pytest-dev/pytest/issues/6255>`_: Clear the :py:data:`sys.last_traceback`, :py:data:`sys.last_type`
  and :py:data:`sys.last_value` attributes by deleting them instead
  of setting them to ``None``. This better matches the behaviour of
  the Python standard library.


pytest 5.3.0 (2019-11-19)
=========================

Deprecations
------------

- `#6179 <https://github.com/pytest-dev/pytest/issues/6179>`_: The default value of :confval:`junit_family` option will change to ``"xunit2"`` in pytest 6.0, given
  that this is the version supported by default in modern tools that manipulate this type of file.

  In order to smooth the transition, pytest will issue a warning in case the ``--junitxml`` option
  is given in the command line but :confval:`junit_family` is not explicitly configured in ``pytest.ini``.

  For more information, `see the docs <https://docs.pytest.org/en/latest/deprecations.html#junit-family-default-value-change-to-xunit2>`__.



Features
--------

- `#4488 <https://github.com/pytest-dev/pytest/issues/4488>`_: The pytest team has created the `pytest-reportlog <https://github.com/pytest-dev/pytest-reportlog>`__
  plugin, which provides a new ``--report-log=FILE`` option that writes *report logs* into a file as the test session executes.

  Each line of the report log contains a self contained JSON object corresponding to a testing event,
  such as a collection or a test result report. The file is guaranteed to be flushed after writing
  each line, so systems can read and process events in real-time.

  The plugin is meant to replace the ``--resultlog`` option, which is deprecated and meant to be removed
  in a future release. If you use ``--resultlog``, please try out ``pytest-reportlog`` and
  provide feedback.


- `#4730 <https://github.com/pytest-dev/pytest/issues/4730>`_: When :py:data:`sys.pycache_prefix` (Python 3.8+) is set, it will be used by pytest to cache test files changed by the assertion rewriting mechanism.

  This makes it easier to benefit of cached ``.pyc`` files even on file systems without permissions.


- `#5515 <https://github.com/pytest-dev/pytest/issues/5515>`_: Allow selective auto-indentation of multiline log messages.

  Adds command line option ``--log-auto-indent``, config option
  :confval:`log_auto_indent` and support for per-entry configuration of
  indentation behavior on calls to :py:func:`python:logging.log()`.

  Alters the default for auto-indention from ``"on"`` to ``"off"``. This
  restores the older behavior that existed prior to v4.6.0. This
  reversion to earlier behavior was done because it is better to
  activate new features that may lead to broken tests explicitly
  rather than implicitly.


- `#5914 <https://github.com/pytest-dev/pytest/issues/5914>`_: :fixture:`testdir` learned two new functions, :py:func:`~_pytest.pytester.LineMatcher.no_fnmatch_line` and
  :py:func:`~_pytest.pytester.LineMatcher.no_re_match_line`.

  The functions are used to ensure the captured text *does not* match the given
  pattern.

  The previous idiom was to use :py:func:`python:re.match`:

  .. code-block:: python

      result = testdir.runpytest()
      assert re.match(pat, result.stdout.str()) is None

  Or the ``in`` operator:

  .. code-block:: python

      result = testdir.runpytest()
      assert text in result.stdout.str()

  But the new functions produce best output on failure.


- `#6057 <https://github.com/pytest-dev/pytest/issues/6057>`_: Added tolerances to complex values when printing ``pytest.approx``.

  For example, ``repr(pytest.approx(3+4j))`` returns ``(3+4j) ± 5e-06 ∠ ±180°``. This is polar notation indicating a circle around the expected value, with a radius of 5e-06. For ``approx`` comparisons to return ``True``, the actual value should fall within this circle.


- `#6061 <https://github.com/pytest-dev/pytest/issues/6061>`_: Added the pluginmanager as an argument to ``pytest_addoption``
  so that hooks can be invoked when setting up command line options. This is
  useful for having one plugin communicate things to another plugin,
  such as default values or which set of command line options to add.



Improvements
------------

- `#5061 <https://github.com/pytest-dev/pytest/issues/5061>`_: Use multiple colors with terminal summary statistics.


- `#5630 <https://github.com/pytest-dev/pytest/issues/5630>`_: Quitting from debuggers is now properly handled in ``doctest`` items.


- `#5924 <https://github.com/pytest-dev/pytest/issues/5924>`_: Improved verbose diff output with sequences.

  Before:

  ::

      E   AssertionError: assert ['version', '...version_info'] == ['version', '...version', ...]
      E     Right contains 3 more items, first extra item: ' '
      E     Full diff:
      E     - ['version', 'version_info', 'sys.version', 'sys.version_info']
      E     + ['version',
      E     +  'version_info',
      E     +  'sys.version',
      E     +  'sys.version_info',
      E     +  ' ',
      E     +  'sys.version',
      E     +  'sys.version_info']

  After:

  ::

      E   AssertionError: assert ['version', '...version_info'] == ['version', '...version', ...]
      E     Right contains 3 more items, first extra item: ' '
      E     Full diff:
      E       [
      E        'version',
      E        'version_info',
      E        'sys.version',
      E        'sys.version_info',
      E     +  ' ',
      E     +  'sys.version',
      E     +  'sys.version_info',
      E       ]


- `#5934 <https://github.com/pytest-dev/pytest/issues/5934>`_: ``repr`` of ``ExceptionInfo`` objects has been improved to honor the ``__repr__`` method of the underlying exception.

- `#5936 <https://github.com/pytest-dev/pytest/issues/5936>`_: Display untruncated assertion message with ``-vv``.


- `#5990 <https://github.com/pytest-dev/pytest/issues/5990>`_: Fixed plurality mismatch in test summary (e.g. display "1 error" instead of "1 errors").


- `#6008 <https://github.com/pytest-dev/pytest/issues/6008>`_: ``Config.InvocationParams.args`` is now always a ``tuple`` to better convey that it should be
  immutable and avoid accidental modifications.


- `#6023 <https://github.com/pytest-dev/pytest/issues/6023>`_: ``pytest.main`` returns a ``pytest.ExitCode`` instance now, except for when custom exit codes are used (where it returns ``int`` then still).


- `#6026 <https://github.com/pytest-dev/pytest/issues/6026>`_: Align prefixes in output of pytester's ``LineMatcher``.


- `#6059 <https://github.com/pytest-dev/pytest/issues/6059>`_: Collection errors are reported as errors (and not failures like before) in the terminal's short test summary.


- `#6069 <https://github.com/pytest-dev/pytest/issues/6069>`_: ``pytester.spawn`` does not skip/xfail tests on FreeBSD anymore unconditionally.


- `#6097 <https://github.com/pytest-dev/pytest/issues/6097>`_: The "[...%]" indicator in the test summary is now colored according to the final (new) multi-colored line's main color.


- `#6116 <https://github.com/pytest-dev/pytest/issues/6116>`_: Added ``--co`` as a synonym to ``--collect-only``.


- `#6148 <https://github.com/pytest-dev/pytest/issues/6148>`_: ``atomicwrites`` is now only used on Windows, fixing a performance regression with assertion rewriting on Unix.


- `#6152 <https://github.com/pytest-dev/pytest/issues/6152>`_: Now parametrization will use the ``__name__`` attribute of any object for the id, if present. Previously it would only use ``__name__`` for functions and classes.


- `#6176 <https://github.com/pytest-dev/pytest/issues/6176>`_: Improved failure reporting with pytester's ``Hookrecorder.assertoutcome``.


- `#6181 <https://github.com/pytest-dev/pytest/issues/6181>`_: The reason for a stopped session, e.g. with ``--maxfail`` / ``-x``, now gets reported in the test summary.


- `#6206 <https://github.com/pytest-dev/pytest/issues/6206>`_: Improved ``cache.set`` robustness and performance.



Bug Fixes
---------

- `#2049 <https://github.com/pytest-dev/pytest/issues/2049>`_: Fixed ``--setup-plan`` showing inaccurate information about fixture lifetimes.


- `#2548 <https://github.com/pytest-dev/pytest/issues/2548>`_: Fixed line offset mismatch of skipped tests in terminal summary.


- `#6039 <https://github.com/pytest-dev/pytest/issues/6039>`_: The ``PytestDoctestRunner`` is now properly invalidated when unconfiguring the doctest plugin.

  This is important when used with ``pytester``'s ``runpytest_inprocess``.


- `#6047 <https://github.com/pytest-dev/pytest/issues/6047>`_: BaseExceptions are now handled in ``saferepr``, which includes ``pytest.fail.Exception`` etc.


- `#6074 <https://github.com/pytest-dev/pytest/issues/6074>`_: pytester: fixed order of arguments in ``rm_rf`` warning when cleaning up temporary directories, and do not emit warnings for errors with ``os.open``.


- `#6189 <https://github.com/pytest-dev/pytest/issues/6189>`_: Fixed result of ``getmodpath`` method.



Trivial/Internal Changes
------------------------

- `#4901 <https://github.com/pytest-dev/pytest/issues/4901>`_: ``RunResult`` from ``pytester`` now displays the mnemonic of the ``ret`` attribute when it is a
  valid ``pytest.ExitCode`` value.


pytest 5.2.4 (2019-11-15)
=========================

Bug Fixes
---------

- `#6194 <https://github.com/pytest-dev/pytest/issues/6194>`_: Fix incorrect discovery of non-test ``__init__.py`` files.


- `#6197 <https://github.com/pytest-dev/pytest/issues/6197>`_: Revert "The first test in a package (``__init__.py``) marked with ``@pytest.mark.skip`` is now correctly skipped.".


pytest 5.2.3 (2019-11-14)
=========================

Bug Fixes
---------

- `#5830 <https://github.com/pytest-dev/pytest/issues/5830>`_: The first test in a package (``__init__.py``) marked with ``@pytest.mark.skip`` is now correctly skipped.


- `#6099 <https://github.com/pytest-dev/pytest/issues/6099>`_: Fix ``--trace`` when used with parametrized functions.


- `#6183 <https://github.com/pytest-dev/pytest/issues/6183>`_: Using ``request`` as a parameter name in ``@pytest.mark.parametrize`` now produces a more
  user-friendly error.


pytest 5.2.2 (2019-10-24)
=========================

Bug Fixes
---------

- `#5206 <https://github.com/pytest-dev/pytest/issues/5206>`_: Fix ``--nf`` to not forget about known nodeids with partial test selection.


- `#5906 <https://github.com/pytest-dev/pytest/issues/5906>`_: Fix crash with ``KeyboardInterrupt`` during ``--setup-show``.


- `#5946 <https://github.com/pytest-dev/pytest/issues/5946>`_: Fixed issue when parametrizing fixtures with numpy arrays (and possibly other sequence-like types).


- `#6044 <https://github.com/pytest-dev/pytest/issues/6044>`_: Properly ignore ``FileNotFoundError`` exceptions when trying to remove old temporary directories,
  for instance when multiple processes try to remove the same directory (common with ``pytest-xdist``
  for example).


pytest 5.2.1 (2019-10-06)
=========================

Bug Fixes
---------

- `#5902 <https://github.com/pytest-dev/pytest/issues/5902>`_: Fix warnings about deprecated ``cmp`` attribute in ``attrs>=19.2``.


pytest 5.2.0 (2019-09-28)
=========================

Deprecations
------------

- `#1682 <https://github.com/pytest-dev/pytest/issues/1682>`_: Passing arguments to pytest.fixture() as positional arguments is deprecated - pass them
  as a keyword argument instead.



Features
--------

- `#1682 <https://github.com/pytest-dev/pytest/issues/1682>`_: The ``scope`` parameter of ``@pytest.fixture`` can now be a callable that receives
  the fixture name and the ``config`` object as keyword-only parameters.
  See `the docs <https://docs.pytest.org/en/latest/fixture.html#dynamic-scope>`__ for more information.


- `#5764 <https://github.com/pytest-dev/pytest/issues/5764>`_: New behavior of the ``--pastebin`` option: failures to connect to the pastebin server are reported, without failing the pytest run



Bug Fixes
---------

- `#5806 <https://github.com/pytest-dev/pytest/issues/5806>`_: Fix "lexer" being used when uploading to bpaste.net from ``--pastebin`` to "text".


- `#5884 <https://github.com/pytest-dev/pytest/issues/5884>`_: Fix ``--setup-only`` and ``--setup-show`` for custom pytest items.



Trivial/Internal Changes
------------------------

- `#5056 <https://github.com/pytest-dev/pytest/issues/5056>`_: The HelpFormatter uses ``py.io.get_terminal_width`` for better width detection.


pytest 5.1.3 (2019-09-18)
=========================

Bug Fixes
---------

- `#5807 <https://github.com/pytest-dev/pytest/issues/5807>`_: Fix pypy3.6 (nightly) on windows.


- `#5811 <https://github.com/pytest-dev/pytest/issues/5811>`_: Handle ``--fulltrace`` correctly with ``pytest.raises``.


- `#5819 <https://github.com/pytest-dev/pytest/issues/5819>`_: Windows: Fix regression with conftest whose qualified name contains uppercase
  characters (introduced by #5792).


pytest 5.1.2 (2019-08-30)
=========================

Bug Fixes
---------

- `#2270 <https://github.com/pytest-dev/pytest/issues/2270>`_: Fixed ``self`` reference in function-scoped fixtures defined plugin classes: previously ``self``
  would be a reference to a *test* class, not the *plugin* class.


- `#570 <https://github.com/pytest-dev/pytest/issues/570>`_: Fixed long standing issue where fixture scope was not respected when indirect fixtures were used during
  parametrization.


- `#5782 <https://github.com/pytest-dev/pytest/issues/5782>`_: Fix decoding error when printing an error response from ``--pastebin``.


- `#5786 <https://github.com/pytest-dev/pytest/issues/5786>`_: Chained exceptions in test and collection reports are now correctly serialized, allowing plugins like
  ``pytest-xdist`` to display them properly.


- `#5792 <https://github.com/pytest-dev/pytest/issues/5792>`_: Windows: Fix error that occurs in certain circumstances when loading
  ``conftest.py`` from a working directory that has casing other than the one stored
  in the filesystem (e.g., ``c:\test`` instead of ``C:\test``).


pytest 5.1.1 (2019-08-20)
=========================

Bug Fixes
---------

- `#5751 <https://github.com/pytest-dev/pytest/issues/5751>`_: Fixed ``TypeError`` when importing pytest on Python 3.5.0 and 3.5.1.


pytest 5.1.0 (2019-08-15)
=========================

Removals
--------

- `#5180 <https://github.com/pytest-dev/pytest/issues/5180>`_: As per our policy, the following features have been deprecated in the 4.X series and are now
  removed:

  * ``Request.getfuncargvalue``: use ``Request.getfixturevalue`` instead.

  * ``pytest.raises`` and ``pytest.warns`` no longer support strings as the second argument.

  * ``message`` parameter of ``pytest.raises``.

  * ``pytest.raises``, ``pytest.warns`` and ``ParameterSet.param`` now use native keyword-only
    syntax. This might change the exception message from previous versions, but they still raise
    ``TypeError`` on unknown keyword arguments as before.

  * ``pytest.config`` global variable.

  * ``tmpdir_factory.ensuretemp`` method.

  * ``pytest_logwarning`` hook.

  * ``RemovedInPytest4Warning`` warning type.

  * ``request`` is now a reserved name for fixtures.


  For more information consult
  `Deprecations and Removals <https://docs.pytest.org/en/latest/deprecations.html>`__ in the docs.


- `#5565 <https://github.com/pytest-dev/pytest/issues/5565>`_: Removed unused support code for `unittest2 <https://pypi.org/project/unittest2/>`__.

  The ``unittest2`` backport module is no longer
  necessary since Python 3.3+, and the small amount of code in pytest to support it also doesn't seem
  to be used: after removed, all tests still pass unchanged.

  Although our policy is to introduce a deprecation period before removing any features or support
  for third party libraries, because this code is apparently not used
  at all (even if ``unittest2`` is used by a test suite executed by pytest), it was decided to
  remove it in this release.

  If you experience a regression because of this, please
  `file an issue <https://github.com/pytest-dev/pytest/issues/new>`__.


- `#5615 <https://github.com/pytest-dev/pytest/issues/5615>`_: ``pytest.fail``, ``pytest.xfail`` and ``pytest.skip`` no longer support bytes for the message argument.

  This was supported for Python 2 where it was tempting to use ``"message"``
  instead of ``u"message"``.

  Python 3 code is unlikely to pass ``bytes`` to these functions. If you do,
  please decode it to an ``str`` beforehand.



Features
--------

- `#5564 <https://github.com/pytest-dev/pytest/issues/5564>`_: New ``Config.invocation_args`` attribute containing the unchanged arguments passed to ``pytest.main()``.


- `#5576 <https://github.com/pytest-dev/pytest/issues/5576>`_: New `NUMBER <https://docs.pytest.org/en/latest/doctest.html#using-doctest-options>`__
  option for doctests to ignore irrelevant differences in floating-point numbers.
  Inspired by Sébastien Boisgérault's `numtest <https://github.com/boisgera/numtest>`__
  extension for doctest.



Improvements
------------

- `#5471 <https://github.com/pytest-dev/pytest/issues/5471>`_: JUnit XML now includes a timestamp and hostname in the testsuite tag.


- `#5707 <https://github.com/pytest-dev/pytest/issues/5707>`_: Time taken to run the test suite now includes a human-readable representation when it takes over
  60 seconds, for example::

      ===== 2 failed in 102.70s (0:01:42) =====



Bug Fixes
---------

- `#4344 <https://github.com/pytest-dev/pytest/issues/4344>`_: Fix RuntimeError/StopIteration when trying to collect package with "__init__.py" only.


- `#5115 <https://github.com/pytest-dev/pytest/issues/5115>`_: Warnings issued during ``pytest_configure`` are explicitly not treated as errors, even if configured as such, because it otherwise completely breaks pytest.


- `#5477 <https://github.com/pytest-dev/pytest/issues/5477>`_: The XML file produced by ``--junitxml`` now correctly contain a ``<testsuites>`` root element.


- `#5524 <https://github.com/pytest-dev/pytest/issues/5524>`_: Fix issue where ``tmp_path`` and ``tmpdir`` would not remove directories containing files marked as read-only,
  which could lead to pytest crashing when executed a second time with the ``--basetemp`` option.


- `#5537 <https://github.com/pytest-dev/pytest/issues/5537>`_: Replace ``importlib_metadata`` backport with ``importlib.metadata`` from the
  standard library on Python 3.8+.


- `#5578 <https://github.com/pytest-dev/pytest/issues/5578>`_: Improve type checking for some exception-raising functions (``pytest.xfail``, ``pytest.skip``, etc)
  so they provide better error messages when users meant to use marks (for example ``@pytest.xfail``
  instead of ``@pytest.mark.xfail``).


- `#5606 <https://github.com/pytest-dev/pytest/issues/5606>`_: Fixed internal error when test functions were patched with objects that cannot be compared
  for truth values against others, like ``numpy`` arrays.


- `#5634 <https://github.com/pytest-dev/pytest/issues/5634>`_: ``pytest.exit`` is now correctly handled in ``unittest`` cases.
  This makes ``unittest`` cases handle ``quit`` from pytest's pdb correctly.


- `#5650 <https://github.com/pytest-dev/pytest/issues/5650>`_: Improved output when parsing an ini configuration file fails.


- `#5701 <https://github.com/pytest-dev/pytest/issues/5701>`_: Fix collection of ``staticmethod`` objects defined with ``functools.partial``.


- `#5734 <https://github.com/pytest-dev/pytest/issues/5734>`_: Skip async generator test functions, and update the warning message to refer to ``async def`` functions.



Improved Documentation
----------------------

- `#5669 <https://github.com/pytest-dev/pytest/issues/5669>`_: Add docstring for ``Testdir.copy_example``.



Trivial/Internal Changes
------------------------

- `#5095 <https://github.com/pytest-dev/pytest/issues/5095>`_: XML files of the ``xunit2`` family are now validated against the schema by pytest's own test suite
  to avoid future regressions.


- `#5516 <https://github.com/pytest-dev/pytest/issues/5516>`_: Cache node splitting function which can improve collection performance in very large test suites.


- `#5603 <https://github.com/pytest-dev/pytest/issues/5603>`_: Simplified internal ``SafeRepr`` class and removed some dead code.


- `#5664 <https://github.com/pytest-dev/pytest/issues/5664>`_: When invoking pytest's own testsuite with ``PYTHONDONTWRITEBYTECODE=1``,
  the ``test_xfail_handling`` test no longer fails.


- `#5684 <https://github.com/pytest-dev/pytest/issues/5684>`_: Replace manual handling of ``OSError.errno`` in the codebase by new ``OSError`` subclasses (``PermissionError``, ``FileNotFoundError``, etc.).


pytest 5.0.1 (2019-07-04)
=========================

Bug Fixes
---------

- `#5479 <https://github.com/pytest-dev/pytest/issues/5479>`_: Improve quoting in ``raises`` match failure message.


- `#5523 <https://github.com/pytest-dev/pytest/issues/5523>`_: Fixed using multiple short options together in the command-line (for example ``-vs``) in Python 3.8+.


- `#5547 <https://github.com/pytest-dev/pytest/issues/5547>`_: ``--step-wise`` now handles ``xfail(strict=True)`` markers properly.



Improved Documentation
----------------------

- `#5517 <https://github.com/pytest-dev/pytest/issues/5517>`_: Improve "Declaring new hooks" section in chapter "Writing Plugins"


pytest 5.0.0 (2019-06-28)
=========================

Important
---------

This release is a Python3.5+ only release.

For more details, see our `Python 2.7 and 3.4 support plan <https://docs.pytest.org/en/latest/py27-py34-deprecation.html>`__.

Removals
--------

- `#1149 <https://github.com/pytest-dev/pytest/issues/1149>`_: Pytest no longer accepts prefixes of command-line arguments, for example
  typing ``pytest --doctest-mod`` inplace of ``--doctest-modules``.
  This was previously allowed where the ``ArgumentParser`` thought it was unambiguous,
  but this could be incorrect due to delayed parsing of options for plugins.
  See for example issues `#1149 <https://github.com/pytest-dev/pytest/issues/1149>`__,
  `#3413 <https://github.com/pytest-dev/pytest/issues/3413>`__, and
  `#4009 <https://github.com/pytest-dev/pytest/issues/4009>`__.


- `#5402 <https://github.com/pytest-dev/pytest/issues/5402>`_: **PytestDeprecationWarning are now errors by default.**

  Following our plan to remove deprecated features with as little disruption as
  possible, all warnings of type ``PytestDeprecationWarning`` now generate errors
  instead of warning messages.

  **The affected features will be effectively removed in pytest 5.1**, so please consult the
  `Deprecations and Removals <https://docs.pytest.org/en/latest/deprecations.html>`__
  section in the docs for directions on how to update existing code.

  In the pytest ``5.0.X`` series, it is possible to change the errors back into warnings as a stop
  gap measure by adding this to your ``pytest.ini`` file:

  .. code-block:: ini

      [pytest]
      filterwarnings =
          ignore::pytest.PytestDeprecationWarning

  But this will stop working when pytest ``5.1`` is released.

  **If you have concerns** about the removal of a specific feature, please add a
  comment to `#5402 <https://github.com/pytest-dev/pytest/issues/5402>`__.


- `#5412 <https://github.com/pytest-dev/pytest/issues/5412>`_: ``ExceptionInfo`` objects (returned by ``pytest.raises``) now have the same ``str`` representation as ``repr``, which
  avoids some confusion when users use ``print(e)`` to inspect the object.

  This means code like:

  .. code-block:: python

        with pytest.raises(SomeException) as e:
            ...
        assert "some message" in str(e)


  Needs to be changed to:

  .. code-block:: python

        with pytest.raises(SomeException) as e:
            ...
        assert "some message" in str(e.value)




Deprecations
------------

- `#4488 <https://github.com/pytest-dev/pytest/issues/4488>`_: The removal of the ``--result-log`` option and module has been postponed to (tentatively) pytest 6.0 as
  the team has not yet got around to implement a good alternative for it.


- `#466 <https://github.com/pytest-dev/pytest/issues/466>`_: The ``funcargnames`` attribute has been an alias for ``fixturenames`` since
  pytest 2.3, and is now deprecated in code too.



Features
--------

- `#3457 <https://github.com/pytest-dev/pytest/issues/3457>`_: New `pytest_assertion_pass <https://docs.pytest.org/en/latest/reference.html#_pytest.hookspec.pytest_assertion_pass>`__
  hook, called with context information when an assertion *passes*.

  This hook is still **experimental** so use it with caution.


- `#5440 <https://github.com/pytest-dev/pytest/issues/5440>`_: The `faulthandler <https://docs.python.org/3/library/faulthandler.html>`__ standard library
  module is now enabled by default to help users diagnose crashes in C modules.

  This functionality was provided by integrating the external
  `pytest-faulthandler <https://github.com/pytest-dev/pytest-faulthandler>`__ plugin into the core,
  so users should remove that plugin from their requirements if used.

  For more information see the docs: https://docs.pytest.org/en/latest/usage.html#fault-handler


- `#5452 <https://github.com/pytest-dev/pytest/issues/5452>`_: When warnings are configured as errors, pytest warnings now appear as originating from ``pytest.`` instead of the internal ``_pytest.warning_types.`` module.


- `#5125 <https://github.com/pytest-dev/pytest/issues/5125>`_: ``Session.exitcode`` values are now coded in ``pytest.ExitCode``, an ``IntEnum``. This makes the exit code available for consumer code and are more explicit other than just documentation. User defined exit codes are still valid, but should be used with caution.

  The team doesn't expect this change to break test suites or plugins in general, except in esoteric/specific scenarios.

  **pytest-xdist** users should upgrade to ``1.29.0`` or later, as ``pytest-xdist`` required a compatibility fix because of this change.



Bug Fixes
---------

- `#1403 <https://github.com/pytest-dev/pytest/issues/1403>`_: Switch from ``imp`` to ``importlib``.


- `#1671 <https://github.com/pytest-dev/pytest/issues/1671>`_: The name of the ``.pyc`` files cached by the assertion writer now includes the pytest version
  to avoid stale caches.


- `#2761 <https://github.com/pytest-dev/pytest/issues/2761>`_: Honor PEP 235 on case-insensitive file systems.


- `#5078 <https://github.com/pytest-dev/pytest/issues/5078>`_: Test module is no longer double-imported when using ``--pyargs``.


- `#5260 <https://github.com/pytest-dev/pytest/issues/5260>`_: Improved comparison of byte strings.

  When comparing bytes, the assertion message used to show the byte numeric value when showing the differences::

          def test():
      >       assert b'spam' == b'eggs'
      E       AssertionError: assert b'spam' == b'eggs'
      E         At index 0 diff: 115 != 101
      E         Use -v to get the full diff

  It now shows the actual ascii representation instead, which is often more useful::

          def test():
      >       assert b'spam' == b'eggs'
      E       AssertionError: assert b'spam' == b'eggs'
      E         At index 0 diff: b's' != b'e'
      E         Use -v to get the full diff


- `#5335 <https://github.com/pytest-dev/pytest/issues/5335>`_: Colorize level names when the level in the logging format is formatted using
  '%(levelname).Xs' (truncated fixed width alignment), where X is an integer.


- `#5354 <https://github.com/pytest-dev/pytest/issues/5354>`_: Fix ``pytest.mark.parametrize`` when the argvalues is an iterator.


- `#5370 <https://github.com/pytest-dev/pytest/issues/5370>`_: Revert unrolling of ``all()`` to fix ``NameError`` on nested comprehensions.


- `#5371 <https://github.com/pytest-dev/pytest/issues/5371>`_: Revert unrolling of ``all()`` to fix incorrect handling of generators with ``if``.


- `#5372 <https://github.com/pytest-dev/pytest/issues/5372>`_: Revert unrolling of ``all()`` to fix incorrect assertion when using ``all()`` in an expression.


- `#5383 <https://github.com/pytest-dev/pytest/issues/5383>`_: ``-q`` has again an impact on the style of the collected items
  (``--collect-only``) when ``--log-cli-level`` is used.


- `#5389 <https://github.com/pytest-dev/pytest/issues/5389>`_: Fix regressions of `#5063 <https://github.com/pytest-dev/pytest/pull/5063>`__ for ``importlib_metadata.PathDistribution`` which have their ``files`` attribute being ``None``.


- `#5390 <https://github.com/pytest-dev/pytest/issues/5390>`_: Fix regression where the ``obj`` attribute of ``TestCase`` items was no longer bound to methods.


- `#5404 <https://github.com/pytest-dev/pytest/issues/5404>`_: Emit a warning when attempting to unwrap a broken object raises an exception,
  for easier debugging (`#5080 <https://github.com/pytest-dev/pytest/issues/5080>`__).


- `#5432 <https://github.com/pytest-dev/pytest/issues/5432>`_: Prevent "already imported" warnings from assertion rewriter when invoking pytest in-process multiple times.


- `#5433 <https://github.com/pytest-dev/pytest/issues/5433>`_: Fix assertion rewriting in packages (``__init__.py``).


- `#5444 <https://github.com/pytest-dev/pytest/issues/5444>`_: Fix ``--stepwise`` mode when the first file passed on the command-line fails to collect.


- `#5482 <https://github.com/pytest-dev/pytest/issues/5482>`_: Fix bug introduced in 4.6.0 causing collection errors when passing
  more than 2 positional arguments to ``pytest.mark.parametrize``.


- `#5505 <https://github.com/pytest-dev/pytest/issues/5505>`_: Fix crash when discovery fails while using ``-p no:terminal``.



Improved Documentation
----------------------

- `#5315 <https://github.com/pytest-dev/pytest/issues/5315>`_: Expand docs on mocking classes and dictionaries with ``monkeypatch``.


- `#5416 <https://github.com/pytest-dev/pytest/issues/5416>`_: Fix PytestUnknownMarkWarning in run/skip example.


pytest 4.6.9 (2020-01-04)
=========================

Bug Fixes
---------

- `#6301 <https://github.com/pytest-dev/pytest/issues/6301>`_: Fix assertion rewriting for egg-based distributions and ``editable`` installs (``pip install --editable``).


pytest 4.6.8 (2019-12-19)
=========================

Features
--------

- `#5471 <https://github.com/pytest-dev/pytest/issues/5471>`_: JUnit XML now includes a timestamp and hostname in the testsuite tag.



Bug Fixes
---------

- `#5430 <https://github.com/pytest-dev/pytest/issues/5430>`_: junitxml: Logs for failed test are now passed to junit report in case the test fails during call phase.



Trivial/Internal Changes
------------------------

- `#6345 <https://github.com/pytest-dev/pytest/issues/6345>`_: Pin ``colorama`` to ``0.4.1`` only for Python 3.4 so newer Python versions can still receive colorama updates.


pytest 4.6.7 (2019-12-05)
=========================

Bug Fixes
---------

- `#5477 <https://github.com/pytest-dev/pytest/issues/5477>`_: The XML file produced by ``--junitxml`` now correctly contain a ``<testsuites>`` root element.


- `#6044 <https://github.com/pytest-dev/pytest/issues/6044>`_: Properly ignore ``FileNotFoundError`` (``OSError.errno == NOENT`` in Python 2) exceptions when trying to remove old temporary directories,
  for instance when multiple processes try to remove the same directory (common with ``pytest-xdist``
  for example).


pytest 4.6.6 (2019-10-11)
=========================

Bug Fixes
---------

- `#5523 <https://github.com/pytest-dev/pytest/issues/5523>`_: Fixed using multiple short options together in the command-line (for example ``-vs``) in Python 3.8+.


- `#5537 <https://github.com/pytest-dev/pytest/issues/5537>`_: Replace ``importlib_metadata`` backport with ``importlib.metadata`` from the
  standard library on Python 3.8+.


- `#5806 <https://github.com/pytest-dev/pytest/issues/5806>`_: Fix "lexer" being used when uploading to bpaste.net from ``--pastebin`` to "text".


- `#5902 <https://github.com/pytest-dev/pytest/issues/5902>`_: Fix warnings about deprecated ``cmp`` attribute in ``attrs>=19.2``.



Trivial/Internal Changes
------------------------

- `#5801 <https://github.com/pytest-dev/pytest/issues/5801>`_: Fixes python version checks (detected by ``flake8-2020``) in case python4 becomes a thing.


pytest 4.6.5 (2019-08-05)
=========================

Bug Fixes
---------

- `#4344 <https://github.com/pytest-dev/pytest/issues/4344>`_: Fix RuntimeError/StopIteration when trying to collect package with "__init__.py" only.


- `#5478 <https://github.com/pytest-dev/pytest/issues/5478>`_: Fix encode error when using unicode strings in exceptions with ``pytest.raises``.


- `#5524 <https://github.com/pytest-dev/pytest/issues/5524>`_: Fix issue where ``tmp_path`` and ``tmpdir`` would not remove directories containing files marked as read-only,
  which could lead to pytest crashing when executed a second time with the ``--basetemp`` option.


- `#5547 <https://github.com/pytest-dev/pytest/issues/5547>`_: ``--step-wise`` now handles ``xfail(strict=True)`` markers properly.


- `#5650 <https://github.com/pytest-dev/pytest/issues/5650>`_: Improved output when parsing an ini configuration file fails.

pytest 4.6.4 (2019-06-28)
=========================

Bug Fixes
---------

- `#5404 <https://github.com/pytest-dev/pytest/issues/5404>`_: Emit a warning when attempting to unwrap a broken object raises an exception,
  for easier debugging (`#5080 <https://github.com/pytest-dev/pytest/issues/5080>`__).


- `#5444 <https://github.com/pytest-dev/pytest/issues/5444>`_: Fix ``--stepwise`` mode when the first file passed on the command-line fails to collect.


- `#5482 <https://github.com/pytest-dev/pytest/issues/5482>`_: Fix bug introduced in 4.6.0 causing collection errors when passing
  more than 2 positional arguments to ``pytest.mark.parametrize``.


- `#5505 <https://github.com/pytest-dev/pytest/issues/5505>`_: Fix crash when discovery fails while using ``-p no:terminal``.


pytest 4.6.3 (2019-06-11)
=========================

Bug Fixes
---------

- `#5383 <https://github.com/pytest-dev/pytest/issues/5383>`_: ``-q`` has again an impact on the style of the collected items
  (``--collect-only``) when ``--log-cli-level`` is used.


- `#5389 <https://github.com/pytest-dev/pytest/issues/5389>`_: Fix regressions of `#5063 <https://github.com/pytest-dev/pytest/pull/5063>`__ for ``importlib_metadata.PathDistribution`` which have their ``files`` attribute being ``None``.


- `#5390 <https://github.com/pytest-dev/pytest/issues/5390>`_: Fix regression where the ``obj`` attribute of ``TestCase`` items was no longer bound to methods.


pytest 4.6.2 (2019-06-03)
=========================

Bug Fixes
---------

- `#5370 <https://github.com/pytest-dev/pytest/issues/5370>`_: Revert unrolling of ``all()`` to fix ``NameError`` on nested comprehensions.


- `#5371 <https://github.com/pytest-dev/pytest/issues/5371>`_: Revert unrolling of ``all()`` to fix incorrect handling of generators with ``if``.


- `#5372 <https://github.com/pytest-dev/pytest/issues/5372>`_: Revert unrolling of ``all()`` to fix incorrect assertion when using ``all()`` in an expression.


pytest 4.6.1 (2019-06-02)
=========================

Bug Fixes
---------

- `#5354 <https://github.com/pytest-dev/pytest/issues/5354>`_: Fix ``pytest.mark.parametrize`` when the argvalues is an iterator.


- `#5358 <https://github.com/pytest-dev/pytest/issues/5358>`_: Fix assertion rewriting of ``all()`` calls to deal with non-generators.


pytest 4.6.0 (2019-05-31)
=========================

Important
---------

The ``4.6.X`` series will be the last series to support **Python 2 and Python 3.4**.

For more details, see our `Python 2.7 and 3.4 support plan <https://docs.pytest.org/en/latest/py27-py34-deprecation.html>`__.


Features
--------

- `#4559 <https://github.com/pytest-dev/pytest/issues/4559>`_: Added the ``junit_log_passing_tests`` ini value which can be used to enable or disable logging of passing test output in the Junit XML file.


- `#4956 <https://github.com/pytest-dev/pytest/issues/4956>`_: pytester's ``testdir.spawn`` uses ``tmpdir`` as HOME/USERPROFILE directory.


- `#5062 <https://github.com/pytest-dev/pytest/issues/5062>`_: Unroll calls to ``all`` to full for-loops with assertion rewriting for better failure messages, especially when using Generator Expressions.


- `#5063 <https://github.com/pytest-dev/pytest/issues/5063>`_: Switch from ``pkg_resources`` to ``importlib-metadata`` for entrypoint detection for improved performance and import time.


- `#5091 <https://github.com/pytest-dev/pytest/issues/5091>`_: The output for ini options in ``--help`` has been improved.


- `#5269 <https://github.com/pytest-dev/pytest/issues/5269>`_: ``pytest.importorskip`` includes the ``ImportError`` now in the default ``reason``.


- `#5311 <https://github.com/pytest-dev/pytest/issues/5311>`_: Captured logs that are output for each failing test are formatted using the
  ColoredLevelFormatter.


- `#5312 <https://github.com/pytest-dev/pytest/issues/5312>`_: Improved formatting of multiline log messages in Python 3.



Bug Fixes
---------

- `#2064 <https://github.com/pytest-dev/pytest/issues/2064>`_: The debugging plugin imports the wrapped ``Pdb`` class (``--pdbcls``) on-demand now.


- `#4908 <https://github.com/pytest-dev/pytest/issues/4908>`_: The ``pytest_enter_pdb`` hook gets called with post-mortem (``--pdb``).


- `#5036 <https://github.com/pytest-dev/pytest/issues/5036>`_: Fix issue where fixtures dependent on other parametrized fixtures would be erroneously parametrized.


- `#5256 <https://github.com/pytest-dev/pytest/issues/5256>`_: Handle internal error due to a lone surrogate unicode character not being representable in Jython.


- `#5257 <https://github.com/pytest-dev/pytest/issues/5257>`_: Ensure that ``sys.stdout.mode`` does not include ``'b'`` as it is a text stream.


- `#5278 <https://github.com/pytest-dev/pytest/issues/5278>`_: Pytest's internal python plugin can be disabled using ``-p no:python`` again.


- `#5286 <https://github.com/pytest-dev/pytest/issues/5286>`_: Fix issue with ``disable_test_id_escaping_and_forfeit_all_rights_to_community_support`` option not working when using a list of test IDs in parametrized tests.


- `#5330 <https://github.com/pytest-dev/pytest/issues/5330>`_: Show the test module being collected when emitting ``PytestCollectionWarning`` messages for
  test classes with ``__init__`` and ``__new__`` methods to make it easier to pin down the problem.


- `#5333 <https://github.com/pytest-dev/pytest/issues/5333>`_: Fix regression in 4.5.0 with ``--lf`` not re-running all tests with known failures from non-selected tests.



Improved Documentation
----------------------

- `#5250 <https://github.com/pytest-dev/pytest/issues/5250>`_: Expand docs on use of ``setenv`` and ``delenv`` with ``monkeypatch``.


Archive
=======

For older changelogs see the :ref:`changelog archive <changelog-archive>`.
