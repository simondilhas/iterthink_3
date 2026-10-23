"""``python -m iterthink`` opens the local web UI."""

from iterthink.web.__main__ import main


def cli() -> None:
    main()


if __name__ == "__main__":
    cli()
