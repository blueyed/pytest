import os

import pytest


def test_symlink_or_skip(monkeypatch, tmpdir, symlink_or_skip):
    symlink_or_skip("src", "dst")
    assert os.path.islink("dst")

    def oserror(src, dst):
        raise OSError("foo")

    monkeypatch.setattr("os.symlink", oserror)

    # Works with existing symlinks.
    symlink_or_skip("src", "dst")

    with pytest.raises(
        pytest.skip.Exception,
        match=r"os\.symlink\(\('src', 'dst2'\)\) failed: OSError\('foo',?\)",
    ):
        symlink_or_skip("src", "dst2")
