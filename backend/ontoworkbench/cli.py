"""`ow` command-line interface: serve / import / export-site."""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from ontoworkbench.config import Settings, ensure_env_file

app = typer.Typer(help="Ontology Workbench — self-hosted ontology workbench.")

PACKAGE_ROOT = Path(__file__).parent
BACKEND_ROOT = PACKAGE_ROOT.parent


def _settings(cli: dict) -> Settings:
    """Resolve settings with .env bootstrap (CLI > env > defaults)."""
    ensure_env_file(BACKEND_ROOT / ".env")
    return Settings.load(cli)


def _migrate(db_url: str, data_dir: Path) -> None:
    """Ensure the data dir exists and the schema is at head."""
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["OW_DB_URL"] = db_url
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    alembic_command.upgrade(cfg, "head")


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8734,
    data_dir: Annotated[str | None, typer.Option()] = None,
    log_dir: Annotated[str | None, typer.Option()] = None,
    no_browser: Annotated[bool, typer.Option()] = False,
) -> None:
    """Run the workbench server (migrates the DB, serves API + SPA)."""
    from ontoworkbench.db.session import init_engine
    from ontoworkbench.server.app import create_app

    cli: dict = {"host": host, "port": port}
    if data_dir:
        cli["data_dir"] = Path(data_dir)
    if log_dir:
        cli["log_dir"] = Path(log_dir)
    settings = _settings(cli)

    _migrate(settings.db_url, settings.data_dir)
    init_engine(settings.db_url)

    if not no_browser and host in {"127.0.0.1", "localhost"} and sys.stdout.isatty():
        webbrowser.open(f"http://{host}:{settings.port}/")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_config=None)


@app.command("import")
def import_ontology(
    path: Annotated[str, typer.Argument(help="Ontology file to import")],
    data_dir: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Import an ontology server-side through the same path as uploads."""
    from uuid import uuid4

    from ontoworkbench.core.indexes import build_indexes
    from ontoworkbench.core.ir import build_ir
    from ontoworkbench.core.parsing import parse_graph, sniff_format
    from ontoworkbench.core.store import LocalUserDirStore
    from ontoworkbench.db.repositories import OntologyRepository, UserRepository
    from ontoworkbench.db.session import init_engine, sessionmaker_or_fail

    cli: dict = {}
    if data_dir:
        cli["data_dir"] = Path(data_dir)
    settings = _settings(cli)
    _migrate(settings.db_url, settings.data_dir)
    init_engine(settings.db_url)

    src = Path(path)
    if not src.is_file():
        typer.echo(f"no such file: {src}", err=True)
        raise typer.Exit(code=2)
    data = src.read_bytes()
    filename = src.name

    with sessionmaker_or_fail()() as session:
        users = UserRepository(session)
        admin = users.first()
        if admin is None:
            typer.echo("no user yet — run `ow serve` and complete /setup first", err=True)
            raise typer.Exit(code=2)
        repos = OntologyRepository(session)
        if repos.find_by_filename(admin.id, filename):
            typer.echo(f"'{filename}' already imported — id kept", err=True)
            raise typer.Exit(code=0)
        fmt = sniff_format(filename, data[:2048])
        ir = build_ir(parse_graph(data, fmt))
        store = LocalUserDirStore(settings.data_dir)
        oid = uuid4()
        store.save(admin.id, oid, filename, data)
        row = repos.create(
            admin.id,
            id=oid,
            title=filename.rsplit(".", 1)[0],
            filename=filename,
            storage_path=str(
                settings.data_dir / "users" / str(admin.id) / "ontologies" / str(oid) / filename
            ),
            format=fmt,
            class_count=ir.counts.class_count,
            property_count=ir.counts.property_count,
            axiom_count=ir.counts.axiom_count,
            stats_json={"prefixes": ir.prefixes},
            file_size_bytes=len(data),
            file_hash=LocalUserDirStore.file_hash(data),
        )
        build_indexes(ir)  # warm parse validation only; server rebuilds on demand
        typer.echo(f"imported {filename} as {row.id} ({ir.counts.class_count} classes)")


@app.command("export-site")
def export_site(
    ontology_id: Annotated[str, typer.Argument(help="Ontology UUID")],
    out: Annotated[str, typer.Option()] = "site",
    force: Annotated[bool, typer.Option()] = False,
) -> None:
    """Export an ontology as a static docs site (implemented in M4)."""
    typer.echo("not implemented: export-site lands in M4", err=True)
    raise typer.Exit(code=2)


if __name__ == "__main__":  # pragma: no cover
    app()
