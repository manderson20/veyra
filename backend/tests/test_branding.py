# SPDX-License-Identifier: AGPL-3.0-or-later
import io

from veyra.cli.branding import _logo, banner, color_depth
from veyra.cli.main import main


class FakeTTY(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


def test_no_color_when_not_a_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert color_depth(io.StringIO()) == 0


def test_no_color_env(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert color_depth(FakeTTY()) == 0
    assert "\033[" not in banner(FakeTTY())


def test_truecolor_and_ascii(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setenv("TERM", "xterm-256color")
    assert "\033[38;2;" in banner(FakeTTY())
    ascii_out = banner(io.StringIO(), ascii_only=True)
    assert ascii_out.isascii()
    assert "Open Communications Platform" in ascii_out


def test_logos_are_consistent():
    for name in ("logo-unicode.txt", "logo-ascii.txt"):
        assert len(_logo(name)) >= 5


def test_cli_version(capsys):
    assert main(["version", "--json"]) == 0
    assert '"version"' in capsys.readouterr().out
