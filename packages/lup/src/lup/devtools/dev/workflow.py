"""The continuous-integration workflow that runs a project's own gate.

A generated tree goes stale the moment the library that compiles it moves, and
nothing in a checkout says so until something asks. ``dev check`` asks, so what
CI owes the project is to run it — one job, not a second list of gates that
drifts from the first. Generated rather than scaffolded for the same reason:
a copy handed over once is a list nobody updates.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lup.harness.banner import GeneratedBanner
from lup.harness.materialization import write_generated_file
from lup.harness.models import Artifact
from lup.workspace.paths import project_root

WORKFLOW_PATH = Path(".github/workflows/quality.yml")
WORKFLOW_COMMAND = "uv run lup-devtools harness generate all"
CHECK_COMMAND = "uv run lup-devtools dev check"


class WorkflowSpec(BaseModel):
    """The choices a project makes about running its own gate.

    Every field is a judgement rather than a fact, which is why each is a
    default a project replaces rather than a constant it would have to fork
    the generator to change. What the job *runs* is not among them: the whole
    argument for generating this file is that CI owes the project one gate,
    and a second list to keep in step is the thing being avoided.
    """

    model_config = ConfigDict(frozen=True)

    branches: list[str] = ["main"]
    """Which pushed branches run the gate, beyond every pull request."""

    runner: str = "ubuntu-latest"
    """The label the job asks for."""

    sync_flags: list[str] = ["--all-extras"]
    """What `uv sync` is given before the gate runs."""

    def body(self) -> str:
        """Render the workflow YAML from these declared choices."""
        return f"""name: Quality

on:
  pull_request:
  push:
    branches: [{", ".join(self.branches)}]

jobs:
  check:
    runs-on: {self.runner}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync {" ".join(self.sync_flags)}
      - name: Quality gate
        run: {CHECK_COMMAND}
"""

    def artifact(self) -> Artifact:
        """This workflow as one artifact, gated like any other generated file."""
        return Artifact.generated(
            path=WORKFLOW_PATH,
            body=self.body(),
            semantic_id="ci.quality",
            banner=GeneratedBanner(source=__name__, command=WORKFLOW_COMMAND),
        )


# lup: ignore[model-free-function] — driver writing the artifact into a tree
def write_workflow(
    spec: WorkflowSpec, root: Path | None = None, *, check: bool = False
) -> Path:
    """Write or verify the generated continuous-integration workflow."""
    return write_generated_file(
        spec.artifact(),
        root or project_root(),
        WORKFLOW_COMMAND,
        check=check,
    )
