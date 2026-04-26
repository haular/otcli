"""CLI package: Typer application + prompt helpers.

Avoid eagerly importing ``app`` here so that submodules of the service
layer can use ``otcli.cli.prompts`` without dragging the entire CLI
graph through a circular import.
"""
