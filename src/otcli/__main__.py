"""Console-script entry point.

Imports the Typer ``app`` lazily through ``otcli.cli.app`` so that the
``otcli.cli`` package itself stays import-cheap (it is also imported by
service modules that just need the prompt helpers).
"""

from otcli.cli.app import app


def main() -> None:
    app()


if __name__ == '__main__':
    main()
