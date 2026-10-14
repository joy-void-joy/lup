"""Rendering a session's guidance from the modules' sections, with a stub runner."""

import importlib
import shlex
import sys
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup_dev import (
    Core,
    Guidance,
    Module,
    Modules,
    Project,
    RoomNeeds,
    Runner,
    Section,
)
from lup_dev.declaration.resolve import Resolved, resolve
from lup_dev.launch.guidance import OPENING, GuidanceError, render

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lup_dev import Tools

PACKAGE = "guidance_fixture_stages"


class Stub(Runner):
    """Runs a tool as `stub exec <tool>`, so a test sees the runner's spelling."""

    @override
    def command(self, tool: list[str]) -> list[str]:
        return ["stub", "exec", *tool]

    @override
    def judging(self, tool: list[str]) -> list[str]:
        return ["stub", "judge", *tool]

    @override
    def environment(self) -> list[str]:
        return []

    @override
    def room(self, root: Path, tools: Tools) -> RoomNeeds:
        return RoomNeeds()


class Pipeline(Module):
    """A project's own module: a section from its root, one from a package."""

    name = "pipeline"

    runner: Runner = Stub()
    guidance: Guidance = Guidance.of(
        Section(name="pipeline", path=Path("guidance/pipeline.md")),
        Section(name="stages", package=PACKAGE, path=Path("docs/stages.md")),
    )


def declared(*modules: Module) -> Resolved:
    """Resolve `Core` with the project's own section, then `modules`."""
    project = Section(name="project", path=Path("AGENTS.md"))
    core = Core(guidance=Guidance.of(project))
    return resolve(Project(modules=Modules.only(core, *modules)))


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A project's root holding its sections, and a package shipping one.

    The package is imported from this test's directory, and forgotten after.
    """
    project = tmp_path / "project"
    (project / "guidance").mkdir(parents=True)
    (project / "AGENTS.md").write_text("# The project\n\nIts own.\n")
    (project / "guidance" / "pipeline.md").write_text("Pipeline: {{ run('make') }}.")
    shipped = tmp_path / "site" / PACKAGE
    (shipped / "docs").mkdir(parents=True)
    (shipped / "__init__.py").write_text('"""Ships a section."""\n')
    (shipped / "docs" / "stages.md").write_text("\nStages.\n\n")
    sys.modules.pop(PACKAGE, None)
    monkeypatch.setattr(sys, "path", [str(tmp_path / "site"), *sys.path])
    importlib.invalidate_caches()
    yield project
    sys.modules.pop(PACKAGE, None)


def test_sections_render_in_module_order_from_a_path_and_a_package(root: Path) -> None:
    rendered = render(declared(Pipeline()), root, root, [])
    assert rendered == (
        f"{OPENING}\n\n# The project\n\nIts own.\n\nPipeline: stub exec make.\n\n"
        "Stages.\n"
    )


def test_a_section_placed_before_another_renders_there(root: Path) -> None:
    placed = Pipeline(
        guidance=Guidance()
        .drop("stages")
        .add(
            Section(name="stages", package=PACKAGE, path=Path("docs/stages.md")),
            before="project",
        )
    )
    rendered = render(declared(placed), root, root, [])
    assert rendered.index("Stages.") < rendered.index("Its own.")
    assert rendered.index("Its own.") < rendered.index("Pipeline:")


def test_the_person_s_own_section_comes_after_the_project_s(root: Path) -> None:
    (root / "AGENTS.local.md").write_text("Mine: {{ run('pytest -x') }}.\n")
    rendered = render(declared(Pipeline()), root, root, [])
    assert rendered.endswith("Stages.\n\nMine: stub exec pytest -x.\n")


def test_the_person_s_own_section_is_read_in_the_worktree_launched(
    root: Path, tmp_path: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "AGENTS.local.md").write_text("Mine.\n")
    (root / "AGENTS.local.md").write_text("The commit's, never read.\n")
    rendered = render(declared(Pipeline()), root, worktree, [])
    assert rendered.endswith("Stages.\n\nMine.\n")
    assert "never read" not in rendered


def test_without_a_local_section_the_document_ends_with_the_declared(
    root: Path,
) -> None:
    rendered = render(declared(Pipeline()), root, root, [])
    assert rendered.endswith("Stages.\n")
    assert "Mine" not in rendered


def test_run_spells_a_command_as_the_runner_runs_it(root: Path) -> None:
    (root / "AGENTS.md").write_text(
        '`{{ run("lup-dev check --fix") }}`, `{{ run("pytest -k \'a b\'") }}`'
    )
    rendered = render(declared(Pipeline()), root, root, [])
    assert "`stub exec lup-dev check --fix`" in rendered
    assert f"`stub exec pytest -k {shlex.quote('a b')}`" in rendered


def test_a_malformed_command_is_refused_naming_the_section(root: Path) -> None:
    (root / "AGENTS.md").write_text('{{ run("pytest -k \'a") }}')
    with pytest.raises(
        GuidanceError, match=r"`project` \(`AGENTS.md`\).*isn't a command"
    ):
        render(declared(Pipeline()), root, root, [])


def test_an_undefined_name_is_refused_naming_the_section(root: Path) -> None:
    (root / "guidance" / "pipeline.md").write_text("Run {{ gate }} first.")
    with pytest.raises(
        GuidanceError,
        match=r"the section `pipeline` \(`guidance/pipeline.md`\) doesn't render: "
        r"'gate' is undefined",
    ):
        render(declared(Pipeline()), root, root, [])


def test_an_undefined_name_in_the_person_s_section_is_refused_naming_it(
    root: Path,
) -> None:
    (root / "AGENTS.local.md").write_text("{% if mine %}Mine.{% endif %}")
    with pytest.raises(
        GuidanceError, match=r"the person's own section .*AGENTS.local.md"
    ):
        render(declared(Pipeline()), root, root, [])


def test_a_section_can_t_reach_past_the_sandbox(root: Path) -> None:
    (root / "AGENTS.md").write_text("{{ run.__globals__ }}")
    with pytest.raises(GuidanceError, match=r"unsafe"):
        render(declared(Pipeline()), root, root, [])


def test_a_missing_section_file_is_refused_naming_it(root: Path) -> None:
    (root / "guidance" / "pipeline.md").unlink()
    with pytest.raises(
        GuidanceError,
        match=r"the section `pipeline` \(`guidance/pipeline.md`\) has no file",
    ):
        render(declared(Pipeline()), root, root, [])


def test_a_missing_package_resource_is_refused_naming_it(root: Path) -> None:
    missing = Pipeline(
        guidance=Guidance().replace(
            "stages",
            Section(name="stages", package=PACKAGE, path=Path("docs/gone.md")),
        )
    )
    with pytest.raises(
        GuidanceError,
        match=rf"the section `stages` \(`docs/gone.md` in `{PACKAGE}`\) has no file",
    ):
        render(declared(missing), root, root, [])


def test_a_missing_package_is_refused_naming_it(root: Path) -> None:
    missing = Pipeline(
        guidance=Guidance().replace(
            "stages",
            Section(name="stages", package="no_such_package", path=Path("a.md")),
        )
    )
    with pytest.raises(GuidanceError, match=r"`a.md` in `no_such_package`"):
        render(declared(missing), root, root, [])


def test_lup_s_own_sections_render_through_the_project_s_runner(
    tmp_path: Path,
) -> None:
    rendered = render(resolve(Project()), tmp_path, tmp_path, [])
    assert rendered.startswith(f"{OPENING}\n\n# The room\n")
    assert "`uv run lup-dev check`" in rendered
    assert "{{" not in rendered
    assert rendered.index("# The room") < rendered.index("# Running the project's")
    assert rendered.index("# Running the project's") < rendered.index(
        "# lup's code rules"
    )


def test_no_section_of_lup_s_spells_the_runner() -> None:
    texts = [
        files(section.package or "").joinpath(*section.path.parts).read_text()
        for section in resolve(Project()).guidance
    ]
    assert len(texts) == 3
    assert all("uv run" not in text for text in texts)
