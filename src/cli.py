from pathlib import Path

import psycopg
import typer

from src.indexer.embedder import VoyageEmbeddingClient
from src.indexer.pipeline import index_repo
from src.storage import db

app = typer.Typer(help="codeintel — agentic codebase intelligence over a real call/import graph.")


@app.command()
def index(repo_path: str) -> None:
    """Build the semantic + structural index for a repo."""
    repo = Path(repo_path)
    if not repo.is_dir():
        typer.secho(f"Not a directory: {repo}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    try:
        client = VoyageEmbeddingClient()
    except Exception as exc:
        typer.secho(
            f"Could not create the Voyage embedding client (is VOYAGE_API_KEY set?): {exc}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    try:
        conn = db.connect()
    except psycopg.OperationalError as exc:
        typer.secho(
            f"Could not connect to Postgres at {db.get_dsn()} (is `docker compose up -d` running?): {exc}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    try:
        summary = index_repo(repo, client, conn)
    finally:
        conn.close()

    typer.echo(
        f"Indexed {summary.total_chunks} chunks from {summary.repo} "
        f"({summary.functions} functions, {summary.methods} methods, {summary.classes} classes)."
    )


@app.command()
def ask(question: str) -> None:
    """Ask a grounded question about the indexed repo."""
    raise NotImplementedError("ask: implemented in Phase 3")


@app.command()
def impact(symbol: str) -> None:
    """Show call sites affected by changing a function/class/file."""
    raise NotImplementedError("impact: implemented in Phase 5")


@app.command()
def graph(symbol: str) -> None:
    """Debug/demo: print callers and callees of a symbol."""
    raise NotImplementedError("graph: implemented in Phase 2")


if __name__ == "__main__":
    app()
