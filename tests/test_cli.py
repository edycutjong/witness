from witness import __version__
from witness.cli import main


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.startswith(f"witness {__version__} (relate-db 1.0.1)")
