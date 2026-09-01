"""`ow` command-line interface: serve / import / export-site."""

from __future__ import annotations

import errno
import os
import socket
import sys
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import structlog
import typer
import uvicorn

from ontoworkbench.config import Settings, ensure_env_file
from ontoworkbench.observability.logging import setup_logging
from ontoworkbench.observability.middleware import request_id_ctx

app = typer.Typer(help="Ontology Workbench — self-hosted ontology workbench.")

_imports_log = structlog.get_logger("ow.imports")
_serve_log = structlog.get_logger("ow.serve")

PACKAGE_ROOT = Path(__file__).parent
BACKEND_ROOT = PACKAGE_ROOT.parent

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_PORT_ATTEMPTS = 10


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
    # Keep alembic from applying alembic.ini's plain-text logging over the
    # app's JSON sinks (env.py honors this switch); records still flow to
    # the root handlers set up by setup_logging, wrapped as JSON.
    cfg.attributes["no_logger"] = True
    alembic_command.upgrade(cfg, "head")


def _probe_port(host: str, port: int) -> None:
    """Bind (host, port) momentarily; raise OSError when it is taken or unusable.

    SO_REUSEADDR is set to match what asyncio/uvicorn will do at bind time, so a
    port left in TIME_WAIT still counts as free.
    """
    addrinfo = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]
    with socket.socket(addrinfo[0], socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(addrinfo[4])


def _warn_stderr(message: str) -> None:
    """Emit a serve-time warning to stderr (injectable for tests)."""
    typer.echo(message, err=True)


def warn_non_loopback(host: str) -> None:
    """Warn that binding is exposed beyond loopback — as a JSON log event.

    A typer.echo here would drop one plain-text line into the JSON stream
    and break log ingestion; the event keeps every sink uniformly parseable.
    """
    _serve_log.warning(
        "serve.non_loopback",
        host=host,
        hint="place this instance behind a reverse proxy with HTTPS before exposing it",
    )


def _serve_cli(
    host: str | None, port: int | None, data_dir: str | None, log_dir: str | None
) -> dict:
    """Collect only the flags actually passed; absent ones stay absent.

    Precedence is CLI > env (.env) > defaults: a flag default riding along
    here would land as an init kwarg and pin the field, silently overriding
    OW_HOST/OW_PORT from .env — which is exactly how they once stopped
    working. `is not None` keeps --port 0 (random port) meaningful.
    """
    cli: dict = {}
    if host is not None:
        cli["host"] = host
    if port is not None:
        cli["port"] = port
    if data_dir:
        cli["data_dir"] = Path(data_dir)
    if log_dir:
        cli["log_dir"] = Path(log_dir)
    return cli


def resolve_serve_port(
    host: str,
    port: int,
    probe: Callable[[str, int], None] = _probe_port,
    warn: Callable[[str], None] = _warn_stderr,
) -> int:
    """Return the first port at or after `port` that can be bound (spec §6/§10).

    On EADDRINUSE the candidate bumps +1 (up to MAX_PORT_ATTEMPTS tries, each
    bump logged); any other OSError (e.g. unknown host) propagates immediately.
    """
    for attempt in range(MAX_PORT_ATTEMPTS):
        candidate = port + attempt
        try:
            probe(host, candidate)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            if attempt + 1 < MAX_PORT_ATTEMPTS:
                warn(f"port {candidate} is in use — trying {candidate + 1}")
                continue
            break
        return candidate
    raise OSError(
        f"ports {port}-{port + MAX_PORT_ATTEMPTS - 1} are all in use; "
        "pass a different --port or free one and retry"
    )


@app.command()
def serve(
    host: Annotated[str | None, typer.Option()] = None,
    port: Annotated[int | None, typer.Option()] = None,
    data_dir: Annotated[str | None, typer.Option()] = None,
    log_dir: Annotated[str | None, typer.Option()] = None,
    no_browser: Annotated[bool, typer.Option()] = False,
) -> None:
    """Run the workbench server (migrates the DB, serves API + SPA)."""
    from ontoworkbench.db.session import init_engine
    from ontoworkbench.server.app import create_app, default_spa_dist

    settings = _settings(_serve_cli(host, port, data_dir, log_dir))

    # JSON sinks must exist before migrations run, or alembic's INFO lines
    # hit a handler-less root logger and vanish (lastResort shows WARNING+).
    setup_logging(settings.log_dir, settings.log_level)
    _migrate(settings.db_url, settings.data_dir)
    init_engine(settings.db_url)

    try:
        serve_port = resolve_serve_port(settings.host, settings.port)
    except OSError as exc:
        typer.echo(f"cannot serve on {settings.host}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if settings.host not in LOOPBACK_HOSTS:
        warn_non_loopback(settings.host)

    if not no_browser and host in {"127.0.0.1", "localhost"} and sys.stdout.isatty():
        webbrowser.open(f"http://{host}:{serve_port}/")
    uvicorn.run(
        create_app(settings, spa_dist=default_spa_dist()),
        host=settings.host,
        port=serve_port,
        log_config=None,
    )


@app.command("import")
def import_ontology(
    path: Annotated[str, typer.Argument(help="Ontology file to import")],
    data_dir: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Import an ontology server-side through the same path as uploads."""
    from uuid import uuid4

    from ontoworkbench.core.indexes import build_indexes
    from ontoworkbench.core.ir import build_ir
    from ontoworkbench.core.parsing import sniff_format, timed_parse
    from ontoworkbench.core.store import LocalUserDirStore
    from ontoworkbench.db.repositories import OntologyRepository, UserRepository
    from ontoworkbench.db.session import init_engine, sessionmaker_or_fail

    cli: dict = {}
    if data_dir:
        cli["data_dir"] = Path(data_dir)
    settings = _settings(cli)
    setup_logging(settings.log_dir, settings.log_level)
    _migrate(settings.db_url, settings.data_dir)
    init_engine(settings.db_url)

    src = Path(path)
    if not src.is_file():
        typer.echo(f"no such file: {src}", err=True)
        raise typer.Exit(code=2)
    started = time.perf_counter()
    t_read = time.perf_counter()
    data = src.read_bytes()
    read_ms = (time.perf_counter() - t_read) * 1000
    filename = src.name

    with sessionmaker_or_fail()() as session:
        users = UserRepository(session)
        admin = users.first()
        if admin is None:
            typer.echo("no user yet — run `ow serve` and complete /setup first", err=True)
            raise typer.Exit(code=2)
        repos = OntologyRepository(session)
        t_dup = time.perf_counter()
        if repos.find_by_filename(admin.id, filename):
            typer.echo(f"'{filename}' already imported — id kept", err=True)
            raise typer.Exit(code=0)
        dup_ms = time.perf_counter() - t_dup
        fmt = sniff_format(filename, data[:2048])
        graph, parse_ms = timed_parse(data, fmt)
        t_ir = time.perf_counter()
        ir = build_ir(graph)
        ir_ms = (time.perf_counter() - t_ir) * 1000
        store = LocalUserDirStore(settings.data_dir)
        oid = uuid4()
        t_store = time.perf_counter()
        store.save(admin.id, oid, filename, data)
        store_ms = (time.perf_counter() - t_store) * 1000
        t_create = time.perf_counter()
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
            instance_count=ir.counts.individual_count,
            stats_json={"prefixes": ir.prefixes, "parse_ms": round(parse_ms, 1)},
            file_size_bytes=len(data),
            file_hash=LocalUserDirStore.file_hash(data),
        )
        db_ms = (dup_ms + (time.perf_counter() - t_create)) * 1000
        t_index = time.perf_counter()
        build_indexes(ir)  # warm parse validation only; server rebuilds on demand
        index_ms = (time.perf_counter() - t_index) * 1000
        # Same ops event and field set as the API path (ow.imports, spec §3)
        # so grepping one name covers both; request_id "-" marks the CLI source.
        _imports_log.info(
            "ontology.import",
            source="cli",
            filename=filename,
            format=fmt,
            size_bytes=len(data),
            read_ms=round(read_ms, 1),
            parse_ms=round(parse_ms, 1),
            ir_ms=round(ir_ms, 1),
            store_ms=round(store_ms, 1),
            db_ms=round(db_ms, 1),
            index_ms=round(index_ms, 1),
            class_count=ir.counts.class_count,
            property_count=ir.counts.property_count,
            instance_count=ir.counts.individual_count,
            axiom_count=ir.counts.axiom_count,
            ontology_id=str(row.id),
            user_id=str(admin.id),
            request_id=request_id_ctx.get(),
            total_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        typer.echo(f"imported {filename} as {row.id} ({ir.counts.class_count} classes)")


@app.command("export-site")
def export_site_cmd(
    ontology_id: Annotated[str, typer.Argument(help="Ontology UUID")],
    out: Annotated[
        str | None, typer.Option(help="Output dir (default {data_dir}/exports/{id}-{timestamp})")
    ] = None,
    force: Annotated[bool, typer.Option()] = False,
    data_dir: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Export a stored ontology as a static docs site (same path as the API)."""
    from uuid import UUID

    from ontoworkbench.core.errors import CoreError
    from ontoworkbench.core.indexes import build_indexes
    from ontoworkbench.core.ir import build_ir
    from ontoworkbench.core.parsing import parse_graph
    from ontoworkbench.db.repositories import OntologyRepository, UserRepository
    from ontoworkbench.db.session import init_engine, sessionmaker_or_fail
    from ontoworkbench.exporter.site import default_out_dir, export_site

    cli: dict = {}
    if data_dir:
        cli["data_dir"] = Path(data_dir)
    settings = _settings(cli)
    setup_logging(settings.log_dir, settings.log_level)
    _migrate(settings.db_url, settings.data_dir)
    init_engine(settings.db_url)

    try:
        oid = UUID(ontology_id)
    except ValueError:
        typer.echo(f"not a UUID: {ontology_id}", err=True)
        raise typer.Exit(code=2) from None

    with sessionmaker_or_fail()() as session:
        admin = UserRepository(session).first()
        if admin is None:
            typer.echo("no user yet — run `ow serve` and complete /setup first", err=True)
            raise typer.Exit(code=2)
        row = OntologyRepository(session).get_owned(admin.id, oid)
        if row is None:
            typer.echo(f"no such ontology: {ontology_id}", err=True)
            raise typer.Exit(code=2)
        data = Path(row.storage_path).read_bytes()
        ir = build_ir(parse_graph(data, row.format))
        target = Path(out) if out else default_out_dir(settings.data_dir, oid)
        try:
            result = export_site(ir, build_indexes(ir), target, row.title or row.filename, force)
        except CoreError as exc:
            typer.echo(f"{exc.code}: {exc.message} ({exc.hint})", err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"exported {row.filename} -> {result.output_dir} ({result.page_count} pages)")


if __name__ == "__main__":  # pragma: no cover
    app()
