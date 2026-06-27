import pytest

from grid_scope.cli import main


def test_cli_help_exits_cleanly(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "daily snapshot" in capsys.readouterr().out.lower()
