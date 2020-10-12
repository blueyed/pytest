# "\u2514\u2500\u2500 …" in logs on Windows builds?! (GHA)
# Ref: https://github.com/blueyed/pytest/pull/393/checks?check_run_id=1242349041#step:11:383
# Ref: https://github.com/blueyed/pytest/pull/441/checks?check_run_id=1242784524#step:11:1444
# Fine with Linux builds: https://github.com/blueyed/pytest/pull/441/checks?check_run_id=1242784403#step:11:163
def test_unicode_docstring(testdir):
    "└── test_this_outer"
    p1 = testdir.makepyfile(
        """
        def test_this():
            "└── test_this_inner"
            assert 0
        """
    )
    result = testdir.runpytest(p1)
    result.stdout.fnmatch_lines(
        [
            "    def test_this():",
            '        "└── test_this_inner"',
            ">       assert 0",
            "E       assert 0",
        ],
        consecutive=True,
    )
    assert 0
