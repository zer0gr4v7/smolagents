from pathlib import Path

import pytest

from smolagents.openclaw.cli import main


def test_init_writes_starter_yaml(tmp_path: Path, capsys):
    target = tmp_path / "openclaw.yaml"
    rc = main(["init", str(target)])
    assert rc == 0
    text = target.read_text()
    assert "memory_path:" in text
    assert "model:" in text


def test_init_refuses_to_overwrite(tmp_path: Path, capsys):
    target = tmp_path / "openclaw.yaml"
    target.write_text("existing")
    rc = main(["init", str(target)])
    assert rc == 1
    assert target.read_text() == "existing"


def test_init_force_overwrites(tmp_path: Path):
    target = tmp_path / "openclaw.yaml"
    target.write_text("existing")
    rc = main(["init", str(target), "--force"])
    assert rc == 0
    assert "memory_path:" in target.read_text()


def test_run_day_subcommand_executes(tmp_path: Path, capsys):
    db = tmp_path / "oc.db"
    rc = main(["--db", str(db), "run-day"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "day=1" in out
    assert db.exists()


def test_run_subcommand_prints_formula(tmp_path: Path, capsys):
    db = tmp_path / "oc.db"
    rc = main(["--db", str(db), "run", "--days", "3"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Revenue =" in out
    assert "R_outdoor_gear" in out


def test_status_after_run(tmp_path: Path, capsys):
    db = tmp_path / "oc.db"
    main(["--db", str(db), "run", "--days", "2"])
    capsys.readouterr()  # drain
    rc = main(["--db", str(db), "status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Day" in out


def test_config_path_overrides_db(tmp_path: Path):
    cfg_path = tmp_path / "c.yaml"
    cfg_db = tmp_path / "from_config.db"
    cli_db = tmp_path / "from_cli.db"
    cfg_path.write_text(f"memory_path: {cfg_db}\nseed: 5\n")
    main(["--config", str(cfg_path), "--db", str(cli_db), "run-day"])
    # --db wins, so the cli_db is the one that gets created.
    assert cli_db.exists()
