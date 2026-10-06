"""Command-line entry point: python -m paddock <command> ..."""

import argparse
import sys

from paddock import bundle

MODULES = (bundle,)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="paddock", description="PadDock CI helpers")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")
    for module in MODULES:
        module.add_commands(sub)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
