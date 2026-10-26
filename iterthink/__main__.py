"""``iterthink`` opens the desktop window.

``--browser`` serves the UI and prints a link instead; ``mcp`` serves the MCP
tools over stdio, so a packaged app can be an agent's MCP server too.
"""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version


def _version() -> str:
    try:
        return version("iterthink")
    except PackageNotFoundError:
        return "unknown"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="iterthink", description="Local-first project workspace.")
    parser.add_argument("--version", action="version", version=f"iterthink {_version()}")
    parser.add_argument(
        "--browser", action="store_true", help="serve the UI and print a link, no window"
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("mcp", help="serve the MCP tools over stdio")
    return parser


def cli(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "mcp":
        from iterthink.mcp import server

        server.main()
    elif args.browser:
        from iterthink.web import __main__ as browser

        browser.main()
    else:
        from iterthink import desktop

        desktop.main()


if __name__ == "__main__":
    cli()
