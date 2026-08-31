"""CLI import emits the same staged ops event as the API path (spec §3)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ontoworkbench.auth.password import hash_password
from ontoworkbench.cli import app
from ontoworkbench.db.models import Base
from ontoworkbench.db.repositories import UserRepository
from ontoworkbench.db.session import init_engine, sessionmaker_or_fail

TTL = "@prefix : <http://ex.org/o#> .\n:C a <http://www.w3.org/2002/07/owl#Class> .\n"


def test_cli_import_event_fields(tmp_path: Path) -> None:
    """CLI import emits the same staged event as the API path.

    source=cli, request_id "-" (no HTTP context) and the staged timings —
    one field set across both entry points (spec §3).
    """
    runner = CliRunner()
    src = tmp_path / "mini.ttl"
    src.write_text(TTL)

    # First run migrates the fresh DB and stops at "no user yet".
    r1 = runner.invoke(app, ["import", str(src), "--data-dir", str(tmp_path)])
    assert r1.exit_code == 2

    engine = init_engine(f"sqlite:///{tmp_path}/ow.db")
    Base.metadata.create_all(engine)
    with sessionmaker_or_fail()() as s:
        UserRepository(s).create("admin", hash_password("admin123!"))

    # The CLI re-runs setup_logging against CliRunner's captured stdout, so
    # the event line lands in r2.output (not capsys).
    r2 = runner.invoke(app, ["import", str(src), "--data-dir", str(tmp_path)])
    assert r2.exit_code == 0, r2.output

    line = next(line for line in r2.output.splitlines() if '"event": "ontology.import"' in line)
    rec = json.loads(line)
    assert rec["source"] == "cli"
    assert rec["request_id"] == "-"
    for stage in ("read_ms", "parse_ms", "ir_ms", "store_ms", "db_ms", "index_ms", "total_ms"):
        assert rec[stage] >= 0
