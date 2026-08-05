"""The continuous-integration workflow that runs this project's own gate.

A generated tree goes stale the moment the library that compiles it moves, and
nothing in a checkout says so until something asks. ``dev check`` asks, so what
CI owes the project is to run it — one job, not a second list of gates that
drifts from the first. Generated rather than scaffolded for the same reason:
a copy handed over once is a list nobody updates.
"""

from pathlib import Path

from lup.harness.banner import GeneratedBanner
from lup.harness.materialization import write_generated_file
from lup.harness.models import Artifact
from lup.workspace.paths import project_root

WORKFLOW_PATH = Path(".github/workflows/quality.yml")
WORKFLOW_COMMAND = "uv run lup-devtools harness generate all"
CHECK_COMMAND = "uv run lup-devtools dev check"

WORKFLOW_BODY = f"""name: Quality

on:
  pull_request:
  push:
    branches: [main, dev]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --all-extras
      - name: Quality gate
        run: {CHECK_COMMAND}
"""


def workflow_artifact() -> Artifact:
    """The workflow as one artifact, gated like any other generated file."""
    return Artifact.generated(
        path=WORKFLOW_PATH,
        body=WORKFLOW_BODY,
        semantic_id="ci.quality",
        banner=GeneratedBanner(source=__name__, command=WORKFLOW_COMMAND),
    )


def write_workflow(root: Path | None = None, *, check: bool = False) -> Path:
    """Write or verify the generated continuous-integration workflow."""
    return write_generated_file(
        workflow_artifact(),
        root or project_root(),
        WORKFLOW_COMMAND,
        check=check,
    )
