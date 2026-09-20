from pathlib import Path

import psycopg
import typer

from src.agent.loop import ClaudeClient, run_agent
from src.agent.tools import AgentContext
from src.indexer.embedder import VoyageEmbeddingClient
from src.indexer.pipeline import index_repo
from src.storage import db, graph_store

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
        f"({summary.functions} functions, {summary.methods} methods, {summary.classes} classes). "
        f"Graph: {summary.graph_nodes} nodes, {summary.graph_edges} edges."
    )


@app.command()
def ask(question: str) -> None:
    """Ask a grounded question about the indexed repo.

    Operates on the repo rooted at the current directory — run
    `codeintel index .` from that repo first.
    """
    repo_root = Path.cwd().resolve()
    repo_id = str(repo_root)

    if not graph_store.has_graph(repo_id):
        typer.secho(
            f"No index found for {repo_id}. Run `codeintel index .` from this directory first.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        embedding_client = VoyageEmbeddingClient()
    except Exception as exc:
        typer.secho(
            f"Could not create the Voyage embedding client (is VOYAGE_API_KEY set?): {exc}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    try:
        llm = ClaudeClient()
    except Exception as exc:
        typer.secho(
            f"Could not create the Claude client (is ANTHROPIC_API_KEY set?): {exc}",
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
        ctx = AgentContext(
            repo_root=repo_root,
            repo_id=repo_id,
            conn=conn,
            embedding_client=embedding_client,
            graph=graph_store.load_graph(repo_id),
        )
        answer = run_agent(question, ctx, llm)
    finally:
        conn.close()

    typer.echo(answer.text)


@app.command()
def impact(symbol: str) -> None:
    """Show call sites affected by changing a function/class/file."""
    raise NotImplementedError("impact: implemented in Phase 5")


@app.command()
def graph(symbol: str) -> None:
    """Debug/demo: print callers and callees of a symbol.

    Operates on the repo rooted at the current directory — run
    `codeintel index .` from that repo first.
    """
    repo_id = str(Path.cwd().resolve())
    if not graph_store.has_graph(repo_id):
        typer.secho(
            f"No graph found for {repo_id}. Run `codeintel index .` from this directory first.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    g = graph_store.load_graph(repo_id)

    matches = [
        (node, data)
        for node, data in g.nodes(data=True)
        if data.get("type") in ("function", "class")
        and symbol in (data.get("qualified_name"), data.get("name"))
    ]
    if not matches:
        typer.secho(f"No function or class named '{symbol}' found in the graph.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    for node, data in matches:
        typer.echo(f"{data['qualified_name']} ({data['file']}:{data['start_line']})")

        callers = sorted(
            g.nodes[u]["qualified_name"] for u, _, edata in g.in_edges(node, data=True) if edata.get("type") == "CALLS"
        )
        callees = sorted(
            g.nodes[v]["qualified_name"]
            for _, v, edata in g.out_edges(node, data=True)
            if edata.get("type") == "CALLS"
        )

        typer.echo(f"  Callers ({len(callers)}):" if callers else "  Callers: (none)")
        for name in callers:
            typer.echo(f"    - {name}")
        typer.echo(f"  Callees ({len(callees)}):" if callees else "  Callees: (none)")
        for name in callees:
            typer.echo(f"    - {name}")


if __name__ == "__main__":
    app()
