import pytest
from pathlib import Path

from grid_scope.cli import main


def test_cli_help_exits_cleanly(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "daily snapshot" in capsys.readouterr().out.lower()


def test_cli_describes_wattlas() -> None:
    parser = __import__("grid_scope.cli", fromlist=["build_parser"]).build_parser()
    assert "Wattlas" in parser.description


def test_refresh_script_sets_pipeline_source_path() -> None:
    script = (Path(__file__).parents[2] / "scripts" / "refresh-snapshot.sh").read_text()
    assert 'PYTHONPATH="$ROOT/pipeline/src"' in script
