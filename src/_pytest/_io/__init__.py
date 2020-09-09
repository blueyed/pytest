import os
import sys
from typing import List
from typing import Sequence

import py.io

from _pytest.compat import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TextIO


def use_markup(file: "TextIO") -> bool:
    # Backward compatibility with pylib: handle PY_COLORS={0,1} only.
    val = os.getenv("PY_COLORS")
    if val in ("0", "1"):
        return val == "1"

    # TODO
    # # PYTEST_FORCE_COLOR: handled as boolean.
    # val = os.getenv("PYTEST_FORCE_COLOR")
    # if val is not None:
    #     from _pytest.config import _strtobool
    #
    #     return _strtobool(val)

    # NO_COLOR: disable markup with any value (https://no-color.org/).
    if "NO_COLOR" in os.environ:
        return False

    # TODO
    # if _running_on_ci():
    #     return True

    return file.isatty() if hasattr(file, "isatty") else False


class TerminalWriter(py.io.TerminalWriter):  # noqa: pygrep-py
    def __init__(self, file: "TextIO" = None) -> None:
        if file is None:
            file = sys.stdout
        if hasattr(file, "isatty") and file.isatty() and sys.platform == "win32":
            try:
                import colorama
            except ImportError:
                pass
            else:
                file = colorama.AnsiToWin32(file).stream
                assert file is not None
        self._file = file
        self._lastlen = 0
        self._chars_on_current_line = 0
        self._width_of_current_line = 0
        self.hasmarkup = use_markup(self._file)

    def write(self, msg: str, **markup: bool) -> int:  # type: ignore[override]
        if not msg:
            return 0
        self._update_chars_on_current_line(msg)  # type: ignore[attr-defined]
        if self.hasmarkup and markup:
            markupmsg = self.markup(msg, **markup)
        else:
            markupmsg = msg
        ret = self._file.write(markupmsg)
        self._file.flush()
        return ret

    @property
    def fullwidth(self):
        if hasattr(self, "_terminal_width"):
            return self._terminal_width

        from _pytest.terminal import get_terminal_width

        return get_terminal_width()

    @fullwidth.setter
    def fullwidth(self, value):
        self._terminal_width = value

    def _write_source(self, lines: List[str], indents: Sequence[str] = ()) -> None:
        """Write lines of source code possibly highlighted.

        Keeping this private for now because the API is clunky. We should discuss how
        to evolve the terminal writer so we can have more precise color support, for example
        being able to write part of a line in one color and the rest in another, and so on.
        """
        if indents and len(indents) != len(lines):
            raise ValueError(
                "indents size ({}) should have same size as lines ({})".format(
                    len(indents), len(lines)
                )
            )
        if not indents:
            indents = [""] * len(lines)
        source = "\n".join(lines)
        new_lines = self._highlight(source).splitlines()
        for indent, new_line in zip(indents, new_lines):
            self.line(indent + new_line)

    def _highlight(self, source):
        """Highlight the given source code according to the "code_highlight" option"""
        if not self.hasmarkup:
            return source
        try:
            from pygments.formatters.terminal import TerminalFormatter
            from pygments.lexers.python import PythonLexer
            from pygments import highlight
        except ImportError:
            return source
        else:
            return highlight(source, PythonLexer(), TerminalFormatter(bg="dark"))


def _running_on_ci():
    return os.environ.get("CI", "").lower() == "true" or "BUILD_NUMBER" in os.environ
