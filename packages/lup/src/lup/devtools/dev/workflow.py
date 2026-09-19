"""The continuous-integration workflow that runs a project's own gate.

A generated tree goes stale the moment the library that compiles it moves, and
nothing in a checkout says so until something asks. ``dev check`` asks, so what
CI owes the project is to run it — one job, not a second list of gates that
drifts from the first. Generated rather than scaffolded for the same reason:
a copy handed over once is a list nobody updates.

Both steps are spelled with the same constants the git guards install, so a
contributor who never armed the hooks is refused here by the identical
commands rather than by a second rule about them.
"""

from pathlib import Path

from pydantic import BaseModel

from lup.devtools.dev.git_guards import CHECK_COMMAND, DRIFT_COMMAND
from lup.formats.banner import GeneratedBanner
from lup.harness.materialization import write_generated_file
from lup.formats.banner import REGENERATE_COMMAND
from lup.harness.models import Artifact
from lup.workspace.paths import project_root

# lup: ignore[constant-declaration] — the directory GitHub Actions itself reads
WORKFLOW_PATH = Path(".github/workflows/quality.yml")
WORKFLOW_COMMAND = REGENERATE_COMMAND
"""What the gate runs to rebuild every tree, taken from the command the banners
already tell a reader to type so the two cannot name different things."""


class FrontendSpec(BaseModel, frozen=True):
    """A bun workspace the gate has to install before it can check bundles.

    Declared rather than assumed because most projects have none, and the
    one that does needs two steps on the runner — bun itself, and the
    workspace's dependencies from its lockfile — before `dev check` can
    rebuild the bundles it compares against what is committed.
    """

    workspace: str
    """Where `package.json` and `bun.lock` live, relative to the repository."""

    bun_version: str = "latest"
    """Which bun the runner installs; pin it to what the lockfile was made with."""


class WorkflowSpec(BaseModel, frozen=True):
    """The choices a project makes about running its own gate.

    Every field is a judgement rather than a fact, which is why each is a
    default a project replaces rather than a constant it would have to fork
    the generator to change. What the job *runs* is not among them: the whole
    argument for generating this file is that CI owes the project one gate,
    and a second list to keep in step is the thing being avoided.
    """

    branches: list[str] = ["main"]
    """Which pushed branches run the gate, beyond every pull request."""

    runner: str = "ubuntu-latest"
    """The label the job asks for."""

    sync_flags: list[str] = ["--all-extras"]
    """What `uv sync` is given before the gate runs."""

    frontend: FrontendSpec | None = None
    """The bun workspace to install first, for a project that builds bundles."""

    system_packages: list[str] = []
    """Distribution packages the gate needs that `uv sync` cannot install.

    A project whose code shells out to a binary — poppler for a page count,
    a renderer, a compiler — needs it on the runner too, and no lock file
    reaches it. Without this the failure lands as a test asserting the thing
    the missing binary would have produced, several steps from the cause.

    Empty is the common case and renders no step at all, so a project that
    needs nothing carries no apt call it would have to read past.
    """

    def install_step(self) -> str:
        """The apt step, or nothing where the project declares no package."""
        if not self.system_packages:
            return ""
        return f"""      - name: System packages
        run: sudo apt-get update && sudo apt-get install -y {
            " ".join(self.system_packages)
        }
"""

    def frontend_steps(self) -> str:
        """The bun steps, or nothing where the project declares no workspace."""
        if self.frontend is None:
            return ""
        return f"""      - uses: oven-sh/setup-bun@v2
        with:
          bun-version: {self.frontend.bun_version}
      - name: Frontend dependencies
        run: bun install --frozen-lockfile
        working-directory: {self.frontend.workspace}
"""

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
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
{self.install_step()}{self.frontend_steps()}      - run: uv sync {" ".join(self.sync_flags)}
      - name: Merge driver
        run: uv run lup-devtools git merge-driver
      - name: Generated artifact drift
        run: {DRIFT_COMMAND}
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


# lup: ignore[constant-declaration] — the directory GitHub Actions itself reads
PUBLISH_PATH = Path(".github/workflows/publish.yml")


class PublishSpec(BaseModel, frozen=True):
    """What a project publishes when a release tag arrives, and from where.

    Declared rather than assumed, because publishing is the one thing in this
    module a repository can be wrong about silently: a workflow that builds
    the wrong distribution still passes, and what it uploads is what everyone
    installs.

    Nothing here carries a credential and nothing has to. Publication is by
    the forge's own OIDC token, exchanged for a short-lived upload token by a
    publisher the index has been told to trust — so the secret that would
    otherwise sit in the repository does not exist to leak, and a fork running
    this workflow cannot publish because the trust names this repository.
    """

    package: str = ""
    """Which workspace member to build, empty where the project is the package.

    A repository whose distribution sits in a subdirectory names it, and
    ``uv build`` is told which member to build rather than building the
    workspace root — which is a different distribution with a different name
    and, in the case this exists for, one nobody publishes.
    """

    environment: str = "pypi"
    """The deployment environment the publishing job runs in.

    Named because the index's trusted publisher is declared against it, and
    because an environment is where a forge can be told to hold a release for
    review before it uploads. A project wanting neither still names one; it
    costs a line and gives it somewhere to put the pause later.
    """

    tags: str = "v*"
    """Which pushed tags publish, as the forge matches them."""

    runner: str = "ubuntu-latest"
    """The label the job asks for."""

    def body(self) -> str:
        """Render the publishing workflow from these declared choices."""
        member = f" --package {self.package}" if self.package else ""
        return f"""name: Publish

on:
  push:
    tags: ["{self.tags}"]

jobs:
  publish:
    runs-on: {self.runner}
    environment: {self.environment}
    # What stands in for a stored token: the forge mints an identity for this
    # run, and the index trusts it for this repository and this workflow.
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - name: Build the distribution
        run: uv build{member}
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
"""

    def artifact(self) -> Artifact:
        """This workflow as one artifact, gated like any other generated file."""
        return Artifact.generated(
            path=PUBLISH_PATH,
            body=self.body(),
            semantic_id="ci.publish",
            banner=GeneratedBanner(source=__name__, command=WORKFLOW_COMMAND),
        )


def write_publish(
    spec: PublishSpec, root: Path | None = None, *, check: bool = False
) -> Path:
    """Write or verify the generated publishing workflow."""
    return write_generated_file(
        spec.artifact(),
        root or project_root(),
        WORKFLOW_COMMAND,
        check=check,
    )
