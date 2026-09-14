import json

import typer

from vera import __version__

app = typer.Typer(
    name="vera",
    help="CI-native automated test reporting and regression intelligence.",
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    """Print Vera's installed version and exit."""

    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show the installed version and exit.",
    ),
) -> None:
    """Run Vera commands."""


@app.command()
def health() -> None:
    """Confirm that the local Vera CLI is operational."""

    typer.echo(json.dumps({"status": "ok", "version": __version__}))
