def test_unicode_docstring(testdir):
    p1 = testdir.makepyfile(
        """
        def test_this():
            "└── root"
            assert 0
        """
    )
    result = testdir.runpytest(p1)
    result.stdout.fnmatch_lines(
        [
            "    def test_this():",
            '        "└── root"',
            ">       assert 0",
            "E       assert 0",
        ],
        consecutive=True,
    )
