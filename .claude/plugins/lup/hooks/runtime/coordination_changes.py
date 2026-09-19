# Generated from lup.providers.roster_prompt by `uv run lup-devtools harness generate all` — edit the source, not this file.
# See docs/harness.md.

"""Entry point for coordination.changes, run as a bare script."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from coordination.changes import main

main()
