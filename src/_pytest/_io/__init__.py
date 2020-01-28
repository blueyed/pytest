import py.io


class TerminalWriter(py.io.TerminalWriter):  # noqa: pygrep-py
    @property
    def fullwidth(self):
        if hasattr(self, "_terminal_width"):
            return self._terminal_width

        from _pytest.terminal import get_terminal_width

        return get_terminal_width()

    @fullwidth.setter
    def fullwidth(self, value):
        self._terminal_width = value
