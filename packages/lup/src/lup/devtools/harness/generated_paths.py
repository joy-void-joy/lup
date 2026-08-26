"""Which file each typed declaration compiles to, walked from the compiled trees.

The page describing generated output used to carry this as a table somebody
maintained. It drifts one way only: an artifact added to a recipe is invisible
until whoever added it remembers the page, so the rows that go missing are
always the newest — and a map with a family missing reads exactly like a
complete one.

Nothing here is authored. Every artifact already knows where it came from,
because a reader who opens the generated file has to be told where to edit
instead; this reads that same attribution and inverts it, so the map is the
artifacts' own answer rather than a second description of them. An artifact
whose format cannot print the line still carries it — a skill's command file,
a verbatim kernel copy, a JSON manifest — which is why the map is complete
where a walk over rendered banners alone would leave three families out.

One row per artifact rather than a folded shape. A folded row reads better and
answers worse: what a reader brings to this page is one generated path they
are looking at, and the answer to that is exact or it is nothing. The page is
long because the tree is, which is the container growing to fit what it holds.
"""

from collections.abc import Iterator
from pathlib import Path

import lup.harness.models as models
from lup.providers.harness import claude_prompt_renderer
from lup.devtools.harness.composition import NativeTargets
from lup.banner import GeneratedBanner
from lup.harness.materialization import write_generated_file
from lup.harness.models import Artifact, PromptDocument, TextPart
from lup.markdown import CodeCell, PlainCell, TableCell
from lup.workspace.paths import project_root

# lup: ignore[constant-declaration] — one generated artifact's identity: the
# writer, the docs index that links it, and the banner must all name one file
GENERATED_PATHS = Path("docs/generated-paths.md")
"""Where this page lands, relative to a checkout."""

# lup: ignore[constant-declaration] — the command a reader types, whose words
# are the CLI's own rather than a preference this module holds
GENERATED_PATHS_COMMAND = "uv run lup-devtools harness generate all"
"""What rebuilds this page, as its banner tells a reader to run."""

# lup: ignore[constant-declaration] — this page's own opening prose, which is
# the document the module renders rather than an input a caller supplies
INTRODUCTION = (
    "# Every generated path, and what it is compiled from\n\n"
    "Walked from the trees the recipes compile, so a path reaches this page "
    "by being generated rather than by being remembered. The right column is "
    "each artifact's own attribution — for most of them the line a reader "
    "meets on opening the file, naming where to edit instead — so nothing "
    "here can name a source the artifact does not.\n\n"
    "A source spelled as a dotted module is a module to open. One spelled as "
    "an identifier is a typed declaration, composed in the catalog that names "
    "it. One spelled as a path is copied from that file byte for byte.\n\n"
    "The repository-wide artifacts written outside every runtime tree — the "
    "rule and command references, this page, and the CI workflow — belong to "
    "no recipe and are described in [harness.md](harness.md) instead.\n\n"
)


def compiled_rows(artifacts: list[Artifact]) -> Iterator[list[TableCell]]:
    """One row per artifact: the path it lands at, and what compiled it."""
    for artifact in sorted(artifacts, key=lambda one: one.path.as_posix()):
        attribution = artifact.banner.attribution() if artifact.banner else ""
        yield [
            CodeCell(text=artifact.path.as_posix()),
            PlainCell(text=attribution or "declared nowhere — a defect, not a row"),
        ]


def target_section(
    label: str, artifacts: list[Artifact], first: bool
) -> list[models.PromptPart]:
    """One runtime's heading, and the table of everything its recipe writes.

    The blank line between sections rides on the *next* heading rather than
    trailing its table, because a table already ends in its own newline and
    the document has to end in exactly one.
    """
    spacing = "" if first else "\n"
    return [
        TextPart(text=f"{spacing}## `{label}` — {len(artifacts)} artifacts\n\n"),
        models.MarkdownTable(
            headers=["Generated path", "Compiled from"],
            rows=list(compiled_rows(artifacts)),
        ),
    ]


def generated_paths_document(targets: NativeTargets, root: Path) -> PromptDocument:
    """The map, walked from every runtime this project compiles a tree for."""
    return PromptDocument(
        source=__name__,
        parts=[
            TextPart(text=INTRODUCTION),
            *(
                part
                for index, (label, build) in enumerate(sorted(targets.builders.items()))
                for part in target_section(
                    label, build(root).recipe.desired.artifacts, first=index == 0
                )
            ),
        ],
    )


def generated_paths_artifact(targets: NativeTargets, root: Path) -> Artifact:
    """The map as one artifact, gated like any other generated file."""
    document = generated_paths_document(targets, root)
    return Artifact.generated(
        path=GENERATED_PATHS,
        body=claude_prompt_renderer().render(document),
        semantic_id="docs.generated-paths",
        banner=GeneratedBanner(
            source=document.declared_source(), command=GENERATED_PATHS_COMMAND
        ),
    )


def write_generated_paths(
    targets: NativeTargets, root: Path | None = None, *, check: bool = False
) -> Path:
    """Write or verify the generated-path map."""
    checkout = root or project_root()
    return write_generated_file(
        generated_paths_artifact(targets, checkout),
        checkout,
        GENERATED_PATHS_COMMAND,
        check=check,
    )
