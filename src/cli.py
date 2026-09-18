import typer

app = typer.Typer(help="codeintel — agentic codebase intelligence over a real call/import graph.")


@app.command()
def index(repo_path: str) -> None:
    """Build the semantic + structural index for a repo."""
    raise NotImplementedError("index: implemented in Phase 1/2")


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
