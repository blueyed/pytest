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
