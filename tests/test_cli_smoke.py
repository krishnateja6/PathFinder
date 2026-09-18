from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()


def test_cli_app_loads():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "codeintel" in result.output.lower() or "usage" in result.output.lower()
