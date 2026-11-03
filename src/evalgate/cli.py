"""Command-line interface (placeholder until M6)."""

import typer

from evalgate import __version__

app = typer.Typer(help="EvalGate: a regression gate for LLM features.")


@app.command()
def version() -> None:
    """Print the EvalGate version."""
    typer.echo(__version__)


def main() -> None:
    app()
