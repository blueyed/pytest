import os

import pytest
from _pytest.config import ExitCode
from _pytest.pytester import FdChecker
from _pytest.pytester import Testdir


@pytest.mark.skipif(not os.path.exists(FdChecker.procfspath), reason="no procfs")
@pytest.mark.parametrize("verbosity", (0, 1))
def test_fdchecker(verbosity: int, testdir: Testdir) -> None:
    p1 = testdir.makepyfile(
        r"""
        import os

        def log_leak(fd):
            with open("leaked", "a") as f:
                f.write("{}\n".format(fd))

        def test_leak1():
            log_leak(os.dup(0))

        def test_leak2():
            log_leak(os.dup(0))
            log_leak(os.dup(0))
        """
    )
    result = testdir.runpytest(
        "-p", "pytester", "--check-fds", "--verbosity={}".format(verbosity), str(p1)
    )

    with open("leaked", "r") as f:
        leaks = f.read().splitlines()
        for leaked in leaks:
            os.close(int(leaked))

    if verbosity == 0:
        leak_msg_1 = "1 FD leakage detected: {} (c)".format(leaks[0])
        leak_msg_2 = "2 FD leakages detected: {} (c), {} (c)".format(*leaks[1:3])

        result.stdout.fnmatch_lines(
            [
                "test_fdchecker.py .E.E *",
                "",
                "*= ERRORS =*",
                "*_ ERROR at teardown of test_leak1 _*",
                "test_fdchecker.py:6: {}".format(leak_msg_1),
                "*_ ERROR at teardown of test_leak2 _*",
                "test_fdchecker.py:9: {}".format(leak_msg_2),
                "*= short test summary info =*",
                "ERROR test_fdchecker.py:6::test_leak1 - {}".format(leak_msg_1),
                "ERROR test_fdchecker.py:9::test_leak2 - {}".format(leak_msg_2),
                "*= 2 passed, 2 errors in *=",
            ],
            consecutive=True,
        )
    else:
        result.stdout.fnmatch_lines(
            [
                r"test_fdchecker.py::test_leak1 PASSED * [[] 50%[]]",
                r"test_fdchecker.py::test_leak1 ERROR  * [[] 50%[]]",
                r"test_fdchecker.py::test_leak2 PASSED * [[]100%[]]",
                r"test_fdchecker.py::test_leak2 ERROR  * [[]100%[]]",
                r"",
                r"*= ERRORS =*",
                r"*_ ERROR at teardown of test_leak1 _*",
                r"test_fdchecker.py:6: 1 FD leakage detected: {} (c)".format(leaks[0]),
                r" - fd {}: c, os.stat_result(*)".format(leaks[0]),
                r"*_ ERROR at teardown of test_leak2 _*",
                r"test_fdchecker.py:9: 2 FD leakages detected: {} (c), {} (c)".format(
                    *leaks[1:3]
                ),
                r" - fd {}: c, os.stat_result(*)".format(leaks[1]),
                r" - fd {}: c, os.stat_result(*)".format(leaks[2]),
                r"*= short test summary info =*",
                r"ERROR test_fdchecker.py:6::test_leak1 - 1 FD leakage detected: {0} (c)\n - fd {0}: c, *".format(
                    leaks[0]
                ),
                r"ERROR test_fdchecker.py:9::test_leak2 - 2 FD leakages detected: {} (c), {} (c)\n - *".format(
                    *leaks[1:3]
                ),
                r"*= 2 passed, 2 errors in *",
            ]
        )


@pytest.mark.skipif(not os.path.exists(FdChecker.procfspath), reason="no procfs")
def test_fdchecker_section_with_existing_error(testdir: Testdir) -> None:
    p1 = testdir.makepyfile(
        r"""
        import os
        import pytest

        def log_leak(fd):
            with open("leaked", "a") as f:
                f.write("{}\n".format(fd))

        @pytest.fixture
        def fix():
            yield
            assert 0, "teardown_error"

        def test_leak(fix):
            log_leak(os.dup(0))
        """
    )
    result = testdir.runpytest("-p", "pytester", "--check-fds", str(p1))

    with open("leaked", "r") as f:
        leaks = f.read().splitlines()
        for leaked in leaks:
            os.close(int(leaked))

    result.stdout.fnmatch_lines(
        [
            "test_fdchecker_section_with_existing_error.py .E *",
            "*= ERRORS =*",
            "*_ ERROR at teardown of test_leak _*",
            ">       assert 0*",
            "*- FD check failure(s) -*",
            "1 FD leakage detected: * (c)",
            "*= short test summary info =*",
            "ERROR * - AssertionError*",
            "*= 1 passed, 1 error in *",
        ]
    )


def test_fdchecker_option(testdir: Testdir) -> None:
    testdir.monkeypatch.setattr(FdChecker, "procfspath", "/does/not/exist")
    result = testdir.runpytest("-p", "pytester", "--check-fds")
    result.stderr.fnmatch_lines(
        [
            "ERROR: --check-fds: not supported on this platform (missing /does/not/exist)",
        ]
    )
    assert result.ret == ExitCode.USAGE_ERROR

    # Can be disabled via `--no-` prefix.
    result = testdir.runpytest("-p", "pytester", "--check-fds", "--no-check-fds")
    result.stdout.fnmatch_lines(["*= no tests ran in *"])
    assert result.ret == ExitCode.NO_TESTS_COLLECTED

    # Silently do not enable it (backward compatibility).
    result = testdir.runpytest("-p", "pytester", "--lsof")
    result.stdout.fnmatch_lines(["*= no tests ran in *"])
    assert result.ret == ExitCode.NO_TESTS_COLLECTED
