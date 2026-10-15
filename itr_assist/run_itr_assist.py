"""CLI runner script for ITR Assist."""
import os
import sys

# Ensure project root is in sys.path when executed directly as script
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from itr_assist.cli import main

if __name__ == "__main__":
    sys.exit(main())
