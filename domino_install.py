"""Installation entry point used by the source installer and offline bootstrap."""
from domino_cli import main as cli_main


def main(argv=None):
    return cli_main(argv, installing=True)


if __name__ == '__main__':
    raise SystemExit(main())
