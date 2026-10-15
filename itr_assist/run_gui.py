"""Launch script for ITR Assist GUI."""
import os
import sys

# Ensure project root is in sys.path when executed directly as script
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from itr_assist.gui import launch_gui


def main() -> int:
    """Run GUI entry point."""
    launch_gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
