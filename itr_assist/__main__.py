"""Module entry point for itr_assist package.

Usage:
    python -m itr_assist          (Launches GUI)
    python -m itr_assist --cli    (Runs CLI pipeline)
"""
import sys

from itr_assist.cli import main as cli_main
from itr_assist.gui import launch_gui


def main() -> int:
    """Run package entry point."""
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        return cli_main()
    launch_gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
