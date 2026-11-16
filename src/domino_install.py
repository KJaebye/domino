"""Installation entry point used by the source installer and offline bootstrap."""
import domino_cli
from domino_cli import main as cli_main


def main(argv=None):
    return cli_main(argv, installing=True)


def package_cli(argv=None, *, installing=False):
    """Package managers own their launchers, including during local initialization."""
    previous = domino_cli.PACKAGE_MANAGED
    domino_cli.PACKAGE_MANAGED = True
    try:
        return cli_main(argv, installing=installing)
    finally:
        domino_cli.PACKAGE_MANAGED = previous


def package_install(argv=None):
    return package_cli(argv, installing=True)


if __name__ == '__main__':
    import sys
    if sys.argv[1:2] == ['--package-cli']:
        raise SystemExit(package_cli(sys.argv[2:]))
    raise SystemExit(main())
