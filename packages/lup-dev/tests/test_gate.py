"""The gate as one command: its requirements first, then every step runs, each
through the project's runner, and a failure exits non-zero. Every process and
probe is stubbed."""

import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from filelock import FileLock
from pydantic import TypeAdapter
from typer.testing import CliRunner

from lup_dev import Requirement, cli
from lup_dev.catalog.gate import Gate, Step
from lup_dev.declaration.package_managers.uv import Uv
from lup_dev.declaration.requirements import (
    Needed,
    Printed,
    RequirementError,
    Tools,
)
from lup_dev.declaration.runner import Plain
from lup_dev.gate import (
    Amended,
    Check,
    Fixes,
    Gated,
    GateError,
    Outcome,
    Passed,
    Passes,
    Processes,
    Ran,
    Shell,
    Standing,
    at_commit,
    failed,
    report,
    standing,
)
from lup_dev.merging import Merged, Merging

if TYPE_CHECKING:
    from conftest import FakeClock, Kit
    from conftest import Shell as Git


class Scripted(Processes):
    """Answers each command as scripted by its first word, recording every run."""

    def __init__(self, answers: dict[str, Ran]) -> None:
        self.answers = answers
        self.ran: list[list[str]] = []

    @override
    def run(self, command: list[str], cwd: Path) -> Ran:
        self.ran.append(command)
        return self.answers.get(command[0], Ran(code=0, output=f"{command[0]} ok\n"))


class Stubbed(Tools):
    """The programs a test says are on the `PATH`, each probe printing as told."""

    def __init__(
        self, programs: list[str], printed: dict[str, Printed] | None = None
    ) -> None:
        self.programs = programs
        self.printed = printed or {}

    @override
    def found(self, program: str) -> bool:
        return program in self.programs

    @override
    def run(self, command: list[str]) -> Printed:
        return self.printed.get(command[0], Printed(code=127, output=""))


NODE = Stubbed(["node", "uv"], {"node": Printed(code=0, output="26.10.0\n")})
"""lup's default requirements, met."""

STEPS = [
    Step(name="lint", command=["lint", "--strict"]),
    Step(name="types", command=["types"]),
    Step(name="tests", command=["tests", "-q"]),
]


def gate(
    root: Path,
    processes: Processes,
    steps: list[Step] = STEPS,
    *,
    fixes: list[Step] | None = None,
) -> Gated:
    """Run `steps` over `root` as written, with no requirements."""
    return Check(
        root=root,
        processes=processes,
        tools=Stubbed([]),
        runner=Plain(),
        steps=steps,
        fixes=fixes or [],
    ).run()


def test_every_step_passes(tmp_path: Path) -> None:
    gated = gate(tmp_path, Scripted({}))
    assert [(o.step, o.result, o.code) for o in gated.outcomes] == [
        ("lint", "passed", 0),
        ("types", "passed", 0),
        ("tests", "passed", 0),
    ]
    assert failed(gated.outcomes) == []
    assert report(gated).endswith("The gate passed.")


def test_every_step_runs_after_one_fails(tmp_path: Path) -> None:
    processes = Scripted({"lint": Ran(code=1, output="a.py:1:1 - E501 too long\n")})
    gated = gate(tmp_path, processes)
    assert processes.ran == [["lint", "--strict"], ["types"], ["tests", "-q"]]
    assert [o.result for o in gated.outcomes] == ["failed", "passed", "passed"]
    assert failed(gated.outcomes) == ["lint"]


def test_the_report_gives_each_failures_output_in_full(tmp_path: Path) -> None:
    long = "".join(f"finding {n}\n" for n in range(500))
    processes = Scripted(
        {"types": Ran(code=1, output=long), "tests": Ran(code=2, output="1 failed\n")}
    )
    text = report(gate(tmp_path, processes))
    assert text.startswith(
        "passed   lint\nfailed   types (exit 1)\nfailed   tests (exit 2)\n"
    )
    assert f"--- types (exit 1) ---\n{long.rstrip()}" in text
    assert "--- tests (exit 2) ---\n1 failed" in text
    assert "lint ok" not in text
    assert text.endswith("The gate failed: types, tests.")


def test_the_fixes_run_before_the_gate_and_count_like_its_steps(
    tmp_path: Path,
) -> None:
    processes = Scripted({"format": Ran(code=2, output="a.py: invalid syntax\n")})
    fixes = [
        Step(name="fix", command=["fix"]),
        Step(name="reformat", command=["format"]),
    ]
    gated = gate(tmp_path, processes, fixes=fixes)
    assert processes.ran == [
        ["fix"],
        ["format"],
        ["lint", "--strict"],
        ["types"],
        ["tests", "-q"],
    ]
    assert failed(gated.outcomes) == ["reformat"]


def test_each_step_runs_through_the_runner_unless_it_says_not(tmp_path: Path) -> None:
    processes = Scripted({})
    Check(
        root=tmp_path,
        processes=processes,
        tools=Stubbed([]),
        runner=Uv(),
        steps=[
            Step(name="lint", command=["ruff", "check"]),
            Step(name="build", command=["make", "all"], in_environment=False),
        ],
        fixes=Fixes().steps,
    ).run()
    assert processes.ran == [
        ["uv", "run", "ruff", "check", "--fix-only", "--ignore-noqa"],
        ["uv", "run", "lup-dev", "rules", "fix"],
        ["uv", "run", "ruff", "format"],
        ["uv", "run", "ruff", "check"],
        ["make", "all"],
    ]


# Requirements, checked before any step.

NEEDED = [
    Needed(
        module="code-rules",
        requirement=Requirement(
            tool="node",
            why="runs the rule engine",
            install="https://nodejs.org/en/download",
        ),
    ),
    Needed(
        module="python",
        requirement=Requirement(tool="uv", why="runs the project's tools"),
    ),
]
CLIPBOARD = Needed(
    module="review",
    requirement=Requirement(
        any_of=["wl-copy", "xclip"], optional=True, why="copies a review"
    ),
)


def test_a_missing_requirement_stops_the_gate_naming_every_one(
    tmp_path: Path,
) -> None:
    processes = Scripted({})
    check = Check(
        root=tmp_path,
        processes=processes,
        tools=Stubbed([]),
        runner=Plain(),
        steps=STEPS,
        requirements=NEEDED,
        fixes=Fixes().steps,
    )
    with pytest.raises(RequirementError) as refused:
        check.run()
    assert processes.ran == []
    assert str(refused.value).splitlines() == [
        "Requirements not met, so nothing ran:",
        (
            "- `node`, for `code-rules` (runs the rule engine): not on the `PATH`. "
            "Install: https://nodejs.org/en/download."
        ),
        "- `uv`, for `python` (runs the project's tools): not on the `PATH`.",
    ]


def test_a_missing_optional_requirement_is_said_once_and_the_gate_runs(
    tmp_path: Path,
) -> None:
    processes = Scripted({})
    gated = Check(
        root=tmp_path,
        processes=processes,
        tools=Stubbed(["node", "uv"]),
        runner=Plain(),
        steps=STEPS,
        requirements=[*NEEDED, CLIPBOARD],
    ).run()
    assert len(processes.ran) == len(STEPS)
    text = report(gated)
    assert text.startswith(
        "off      `wl-copy or xclip`, for `review` (copies a review): "
        "not on the `PATH`.\npassed   lint\n"
    )
    assert text.count("wl-copy") == 1
    assert text.endswith("The gate passed.")


# A step that builds a file.

ENGINE = Step(
    name="engine",
    command=["build"],
    builds="bundle/engine.js",
    sources=["src/**/*", "table.ts"],
)


def touch(path: Path, when: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    os.utime(path, (when, when))


def check_engine(root: Path) -> tuple[Outcome, Scripted]:
    processes = Scripted({})
    [outcome] = gate(root, processes, [ENGINE]).outcomes
    return outcome, processes


def test_a_build_newer_than_its_sources_is_skipped(tmp_path: Path) -> None:
    touch(tmp_path / "src" / "deep" / "rule.ts", 1_000)
    touch(tmp_path / "table.ts", 1_000)
    touch(tmp_path / "bundle" / "engine.js", 2_000)
    outcome, processes = check_engine(tmp_path)
    assert outcome.result == "skipped"
    assert outcome.why == "bundle/engine.js is newer than its sources"
    assert processes.ran == []
    assert report(Gated(outcomes=[outcome])).startswith(
        "skipped  engine (bundle/engine.js is newer than its sources)"
    )


class Building(Processes):
    """Passes every command, `build` writing the engine's bundle as it runs."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.ran: list[list[str]] = []

    @override
    def run(self, command: list[str], cwd: Path) -> Ran:
        self.ran.append(command)
        if command == ["build"]:
            touch(self.root / "bundle" / "engine.js", 9_000)
        return Ran(code=0, output="")


def test_with_fixes_a_stale_build_runs_before_them_and_once(tmp_path: Path) -> None:
    touch(tmp_path / "table.ts", 1_000)
    processes = Building(tmp_path)
    gated = gate(
        tmp_path,
        processes,
        [ENGINE, *STEPS],
        fixes=[Step(name="fix", command=["fix"])],
    )
    assert processes.ran[:2] == [["build"], ["fix"]]
    assert processes.ran.count(["build"]) == 1
    assert [(each.step, each.result) for each in gated.outcomes][:3] == [
        ("engine", "passed"),
        ("fix", "passed"),
        ("engine", "skipped"),
    ]


def test_without_fixes_a_build_runs_once_in_its_place(tmp_path: Path) -> None:
    touch(tmp_path / "table.ts", 1_000)
    processes = Building(tmp_path)
    gate(tmp_path, processes, [*STEPS[:1], ENGINE])
    assert processes.ran == [["lint", "--strict"], ["build"]]


def test_a_build_older_than_a_source_runs(tmp_path: Path) -> None:
    touch(tmp_path / "bundle" / "engine.js", 2_000)
    touch(tmp_path / "src" / "deep" / "rule.ts", 3_000)
    outcome, processes = check_engine(tmp_path)
    assert outcome.result == "passed"
    assert processes.ran == [["build"]]


def test_a_missing_build_runs(tmp_path: Path) -> None:
    touch(tmp_path / "table.ts", 1_000)
    outcome, _ = check_engine(tmp_path)
    assert outcome.result == "passed"


# The shell.


def test_the_shell_runs_a_command_and_keeps_its_output(tmp_path: Path) -> None:
    script = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
    ran = Shell().run([sys.executable, "-c", script], tmp_path)
    assert ran.code == 3
    assert "out" in ran.output
    assert "err" in ran.output


def test_a_command_not_installed_fails_its_step(tmp_path: Path) -> None:
    ran = Shell().run(["lup-no-such-command"], tmp_path)
    assert ran.code == 127
    assert "isn't installed" in ran.output


# The catalog's gate.


def test_the_catalogs_gate_runs_lups_rules_then_the_tools() -> None:
    commands = {step.name: step.command for step in Gate().steps}
    assert list(commands) == ["rules", "format", "pytest", "lint-imports"]
    assert commands["rules"] == ["lup-dev", "rules", "check"]


def test_the_fixes_are_ruffs_then_unused_ignores_removed_then_the_formatter() -> None:
    assert [step.command for step in Fixes().steps] == [
        ["ruff", "check", "--fix-only", "--ignore-noqa"],
        ["lup-dev", "rules", "fix"],
        ["ruff", "format"],
    ]


class InProcess(Processes):
    """Runs `uv run lup-dev …` in this process, on the fakes; the rest pass."""

    def __init__(self) -> None:
        self.ran: list[list[str]] = []

    @override
    def run(self, command: list[str], cwd: Path) -> Ran:
        self.ran.append(command)
        match command:
            case ["uv", "run", "lup-dev", *arguments]:
                with pytest.MonkeyPatch.context() as patch:
                    patch.chdir(cwd)
                    result = CliRunner().invoke(cli.app, arguments)
                if result.exception is not None and not isinstance(
                    result.exception, SystemExit
                ):
                    raise result.exception
                return Ran(code=result.exit_code, output=result.output)
            case _:
                return Ran(code=0, output="")


def rules_step(root: Path) -> tuple[Outcome, list[Outcome]]:
    """Run the catalog's whole gate over `root`; its `rules` step, and every step."""
    outcomes = Check(
        root=root,
        processes=InProcess(),
        tools=NODE,
        runner=Uv(),
        steps=Gate().steps,
    ).run()
    [rules] = [outcome for outcome in outcomes.outcomes if outcome.step == "rules"]
    return rules, outcomes.outcomes


def test_the_gate_fails_on_lups_findings_listing_each_with_its_steer(
    fakes: Kit, repo: Path
) -> None:
    (repo / "src" / "pkg" / "core.py").write_text(
        "x = 1  # BAD regex\ny = (1, 2)  # BAD tuple-shape\n"
    )
    rules, outcomes = rules_step(repo)
    assert rules.result == "failed"
    assert rules.code == 1
    assert rules.output.splitlines() == [
        "src/pkg/core.py:1:8 - regex: regex fires here",
        "    steer: do it the other way",
        "src/pkg/core.py:2:13 - tuple-shape: tuple-shape fires here",
        "    steer: do it the other way",
        "lup checked 3 files: 2 findings.",
    ]
    assert failed(outcomes) == ["rules"]
    assert report(Gated(outcomes=outcomes)).endswith("The gate failed: rules.")


def test_the_gate_passes_a_worktree_without_findings(fakes: Kit, repo: Path) -> None:
    rules, outcomes = rules_step(repo)
    assert rules.result == "passed"
    assert rules.output == "lup checked 3 files: 0 findings.\n"
    assert failed(outcomes) == []


def test_the_gates_rules_leave_tests_scratch_and_excluded_paths_out(
    fakes: Kit, repo: Path
) -> None:
    (repo / "lup_project.py").write_text(
        "from lup_dev import Core, Modules, Paths, Project\n"
        "excluding = Core(paths=Paths().add(excluded=['vendor/**']))\n"
        "project = Project(modules=Modules.default().edit(excluding))\n"
    )
    for written in ["vendor/lib.py", "tmp/try.py", "tests/test_core.py"]:
        (repo / written).parent.mkdir(exist_ok=True)
        (repo / written).write_text("x = 1  # BAD regex\n")
    rules, _ = rules_step(repo)
    assert rules.result == "passed"
    sent = {source.path for batch in fakes.engine.checked for source in batch}
    assert Path("tests/test_core.py") in sent
    assert Path("vendor/lib.py") not in sent
    assert Path("tmp/try.py") not in sent


# Passes, recorded by the files they passed on.


def kept(root: Path, processes: Processes, clock: FakeClock, **fields: object) -> Check:
    """The gate over `root` with lup's three scripted steps, its passes kept in its repository."""
    return Check.model_validate(
        {
            "root": root,
            "processes": processes,
            "tools": Stubbed([]),
            "runner": Plain(),
            "steps": STEPS,
            "passes": Passes.of(root, clock),
            **fields,
        }
    )


class Writing(Processes):
    """Passes every command, the one named `at` writing `text` into `path` as it runs."""

    def __init__(self, at: str, path: Path, text: str) -> None:
        self.at = at
        self.path = path
        self.text = text
        self.ran: list[list[str]] = []

    @override
    def run(self, command: list[str], cwd: Path) -> Ran:
        self.ran.append(command)
        if command[0] == self.at:
            self.path.write_text(self.text)
        return Ran(code=0, output="")


def test_a_pass_is_recorded_for_the_files_and_answers_the_next_run(
    repo: Path, clock: FakeClock
) -> None:
    processes = Scripted({})
    first = kept(repo, processes, clock).run()
    second = kept(repo, processes, clock).run()

    files = standing(repo)
    assert first.recorded == Passed(
        files=files, at=clock.now(), steps=["lint", "types", "tests"]
    )
    assert len(processes.ran) == len(STEPS)
    assert second.outcomes == []
    assert second.found == first.recorded
    assert report(second) == (
        "The gate passed on these files already, at 2026-10-01 12:00 UTC (tree "
        f"`{files.tree}`): nothing ran. `--again` runs it anyway."
    )
    assert report(first).endswith(
        f"The gate passed. It's recorded for these files (tree `{files.tree}`), so "
        "running it again on them, or pushing them, runs nothing."
    )


def test_a_file_changed_or_added_runs_the_gate_again_and_one_ignored_doesnt(
    repo: Path, clock: FakeClock
) -> None:
    processes = Scripted({})
    kept(repo, processes, clock).run()
    (repo / ".venv").mkdir()
    (repo / ".venv" / "ignored.py").write_text("x = 1\n")
    ignored = kept(repo, processes, clock).run()
    (repo / "src" / "pkg" / "new.py").write_text("y = 2\n")
    added = kept(repo, processes, clock).run()
    (repo / "README.md").write_text("# Changed\n")
    changed = kept(repo, processes, clock).run()

    assert ignored.found is not None
    assert added.found is None
    assert changed.found is None
    assert len(processes.ran) == 3 * len(STEPS)


def test_again_runs_every_step_where_a_pass_is_recorded(
    repo: Path, clock: FakeClock
) -> None:
    processes = Scripted({})
    kept(repo, processes, clock).run()
    again = kept(repo, processes, clock).run(again=True)
    assert again.found is None
    assert again.recorded is not None
    assert len(processes.ran) == 2 * len(STEPS)


def test_a_failing_run_records_nothing(repo: Path, clock: FakeClock) -> None:
    processes = Scripted({"types": Ran(code=1, output="no\n")})
    failing = kept(repo, processes, clock).run()
    assert failing.recorded is None
    assert Passes.of(repo, clock).found(standing(repo)) is None


def test_files_a_step_changes_leave_the_pass_unrecorded(
    repo: Path, clock: FakeClock
) -> None:
    processes = Writing("types", repo / "README.md", "# Written by a step\n")
    moved = kept(repo, processes, clock).run()
    assert moved.moved
    assert moved.recorded is None
    assert report(moved).endswith(
        "The gate passed. The worktree's files changed while it ran, so it isn't "
        "recorded."
    )
    assert Passes.of(repo, clock).found(standing(repo)) is None


def test_the_pass_is_recorded_for_the_files_after_the_fixes(
    repo: Path, clock: FakeClock
) -> None:
    processes = Writing("fix", repo / "README.md", "# Fixed\n")
    fixed = kept(
        repo, processes, clock, fixes=[Step(name="fix", command=["fix"])]
    ).run()
    assert fixed.recorded is not None
    assert fixed.recorded.files == standing(repo)
    assert fixed.recorded.steps == ["lint", "types", "tests"]
    assert kept(repo, processes, clock).run().found == fixed.recorded


def test_the_person_s_layer_is_part_of_the_files(repo: Path, clock: FakeClock) -> None:
    (repo / ".gitignore").write_text(".venv/\n.lup/\nlup_project.local.py\n")
    processes = Scripted({})
    without = kept(repo, processes, clock).run().recorded
    (repo / "lup_project.local.py").write_text("project = None\n")
    layered = kept(repo, processes, clock).run()

    assert without is not None
    assert without.files.layer is None
    assert layered.found is None
    assert layered.recorded is not None
    assert layered.recorded.files.tree == without.files.tree
    assert layered.recorded.files.layer is not None
    assert layered.recorded.files.name == (
        f"{without.files.tree}-{layered.recorded.files.layer}"
    )


def test_reading_the_files_leaves_the_worktree_s_index_as_it_was(
    repo: Path, shell: Git
) -> None:
    (repo / "README.md").write_text("# Changed\n")
    (repo / "new.py").write_text("x = 1\n")
    before = shell.git(repo, "status", "--porcelain")
    standing(repo)
    assert shell.git(repo, "status", "--porcelain") == before
    assert shell.git(repo, "diff", "--cached", "--name-only") == ""


def test_every_worktree_of_a_repository_finds_its_passes(
    repo: Path, linked: Path, clock: FakeClock
) -> None:
    processes = Scripted({})
    recorded = kept(repo, processes, clock).run().recorded
    found = kept(linked, processes, clock).run().found
    assert recorded is not None
    assert found == recorded


# A pass found, beside the builds a worktree lacks.

BUILT = [ENGINE.model_copy(update={"sources": ["table.ts"]}), *STEPS]
"""The engine built from its table alone, then lup's three scripted steps: the
repository's own `src/` is newer than any bundle `Building` writes."""


def ignoring_the_bundle(root: Path) -> None:
    """Give `root` the engine's table, git ignoring the bundle built from it, as lup's repository does."""
    (root / ".gitignore").write_text(".venv/\n.lup/\nbundle/\n")
    touch(root / "table.ts", 1_000)


def test_a_pass_found_in_a_fresh_worktree_still_builds_what_it_lacks(
    repo: Path, shell: Git, clock: FakeClock, tmp_path: Path
) -> None:
    ignoring_the_bundle(repo)
    shell.commit(repo, "the engine's table, its bundle ignored")
    recorded = kept(repo, Building(repo), clock, steps=BUILT).run().recorded
    fresh = tmp_path / "fresh"
    shell.git(repo, "worktree", "add", "-q", "-b", "fresh", str(fresh))
    processes = Building(fresh)

    gated = kept(fresh, processes, clock, steps=BUILT).run()

    assert recorded is not None
    assert gated.found == recorded
    assert processes.ran == [["build"]]
    assert (fresh / "bundle" / "engine.js").is_file()
    assert report(gated) == (
        "passed   engine\n\nThe gate passed. These files passed already, at "
        f"2026-10-01 12:00 UTC (tree `{recorded.files.tree}`), so only the builds "
        "stale in this worktree ran. `--again` runs every step."
    )


def test_a_pass_found_where_each_build_is_up_to_date_runs_nothing(
    repo: Path, clock: FakeClock
) -> None:
    ignoring_the_bundle(repo)
    processes = Building(repo)
    kept(repo, processes, clock, steps=BUILT).run()
    again = kept(repo, processes, clock, steps=BUILT).run()

    assert again.found is not None
    assert again.outcomes == []
    assert processes.ran == [
        ["build"],
        ["lint", "--strict"],
        ["types"],
        ["tests", "-q"],
    ]
    assert report(again) == again.found.said()


def test_a_build_failing_beside_a_pass_found_fails_the_gate(
    repo: Path, clock: FakeClock
) -> None:
    ignoring_the_bundle(repo)
    kept(repo, Building(repo), clock, steps=BUILT).run()
    touch(repo / "table.ts", 20_000)
    processes = Scripted({"build": Ran(code=2, output="no bundler\n")})

    gated = kept(repo, processes, clock, steps=BUILT).run()

    assert gated.found is not None
    assert processes.ran == [["build"]]
    assert failed(gated.outcomes) == ["engine"]
    text = report(gated)
    assert text.startswith(
        "failed   engine (exit 2)\n\n--- engine (exit 2) ---\nno bundler\n\n"
    )
    assert text.endswith(
        "The gate failed: engine. These files passed already, at 2026-10-01 12:00 "
        f"UTC (tree `{gated.found.files.tree}`), so only the builds stale in this "
        "worktree ran. `--again` runs every step."
    )


def test_a_build_beside_a_pass_found_checks_the_requirements_first(
    repo: Path, clock: FakeClock
) -> None:
    ignoring_the_bundle(repo)
    kept(repo, Building(repo), clock, steps=BUILT).run()
    (repo / "bundle" / "engine.js").unlink()
    processes = Scripted({})
    check = kept(repo, processes, clock, steps=BUILT, requirements=NEEDED)
    with pytest.raises(RequirementError):
        check.run()
    assert processes.ran == []


# The gate on a commit, in a worktree made at it.


class Witness(Processes):
    """Answers the gate run on a commit as told, seeing where it ran and what was there."""

    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.ran: list[tuple[list[str], Path]] = []
        self.readme: list[str] = []

    @override
    def run(self, command: list[str], cwd: Path) -> Ran:
        self.ran.append((command, cwd))
        self.readme.append((cwd / "README.md").read_text())
        return Ran(code=self.code, output=f"the report, ending {self.code}\n")


def gated_at(
    repo: Path,
    revision: str,
    processes: Processes,
    clock: FakeClock,
    *,
    again: bool = False,
    fix: bool = False,
) -> tuple[Passed | Ran | Amended, list[str], list[Path]]:
    """Run the gate at `revision` from `repo`: what it gave, what it said, and each worktree it stopped."""
    said: list[str] = []
    stopped: list[Path] = []
    outcome = at_commit(
        repo,
        revision,
        processes,
        Passes.of(repo, clock),
        Uv(),
        say=said.append,
        stop=stopped.append,
        again=again,
        fix=fix,
    )
    return outcome, said, stopped


def test_at_a_commit_the_gate_runs_in_a_worktree_made_at_it_and_removed_after(
    repo: Path, shell: Git, clock: FakeClock
) -> None:
    first = shell.git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("# Second\n")
    shell.commit(repo, "second")
    (repo / "README.md").write_text("# Not committed\n")
    processes = Witness()

    outcome, said, stopped = gated_at(repo, "HEAD~1", processes, clock)

    [(command, made)] = processes.ran
    assert command == Uv().judging(["lup-dev", "check"])
    assert made != repo
    assert processes.readme == ["# Work\n"]
    assert outcome == Ran(code=0, output="the report, ending 0\n")
    assert said == [f"The gate runs on {first}, in a worktree made for it at {made}."]
    assert stopped == [made]
    assert not made.exists()
    assert str(made) not in shell.git(repo, "worktree", "list")
    tree = shell.git(repo, "rev-parse", f"{first}^{{tree}}")
    found = Passes.of(repo, clock).found(Standing(tree=tree))
    assert found == Passed(files=Standing(tree=tree), at=clock.now(), steps=[])


def test_at_a_commit_whose_files_passed_nothing_runs(
    repo: Path, clock: FakeClock
) -> None:
    recorded = kept(repo, Scripted({}), clock).run().recorded
    processes = Witness()

    outcome, said, stopped = gated_at(repo, "HEAD", processes, clock)

    assert outcome == recorded
    assert processes.ran == []
    assert said == []
    assert stopped == []


def test_at_a_commit_again_runs_the_gate_where_its_files_passed(
    repo: Path, clock: FakeClock
) -> None:
    kept(repo, Scripted({}), clock).run()
    processes = Witness()
    gated_at(repo, "HEAD", processes, clock, again=True)
    [(command, _)] = processes.ran
    assert command == Uv().judging(["lup-dev", "check", "--again"])


class Fixing(Processes):
    """Answers the gate run on a commit as `lup-dev check --fix` would on the files it's given: rewriting the README, as told, then passing."""

    def __init__(self, readme: str | None) -> None:
        self.written = readme
        self.ran: list[list[str]] = []

    @override
    def run(self, command: list[str], cwd: Path) -> Ran:
        self.ran.append(command)
        if self.written is not None:
            (cwd / "README.md").write_text(self.written)
        return Ran(code=0, output="the report, ending 0\n")


def test_at_a_commit_with_fix_what_the_fixes_change_is_amended_into_a_commit_of_its_own(
    repo: Path, shell: Git, clock: FakeClock
) -> None:
    (repo / "README.md").write_text("# Second\n")
    shell.commit(repo, "second:\n\n  kept `as` written  \n")
    first = shell.git(repo, "rev-parse", "HEAD")
    processes = Fixing("# Second, formatted\n")

    outcome, said, _ = gated_at(repo, "HEAD", processes, clock, fix=True)

    assert processes.ran == [Uv().judging(["lup-dev", "check", "--fix"])]
    assert isinstance(outcome, Amended)
    assert (outcome.amends, outcome.ran) == (
        first,
        Ran(code=0, output="the report, ending 0\n"),
    )
    amended = outcome.commit
    assert shell.git(repo, "rev-parse", "HEAD") == first
    assert shell.git(repo, "show", f"{amended}:README.md") == "# Second, formatted"
    assert shell.git(repo, "rev-parse", f"{amended}^@") == shell.git(
        repo, "rev-parse", f"{first}^@"
    )
    message = ["cat-file", "commit"]
    assert (
        shell.git(repo, *message, amended).partition("\n\n")[2]
        == shell.git(repo, *message, first).partition("\n\n")[2]
    )
    tree = shell.git(repo, "rev-parse", f"{amended}^{{tree}}")
    assert Passes.of(repo, clock).found(Standing(tree=tree)) is not None
    assert outcome.said() == (
        f"The fixes changed files: they're in {amended}, a commit with {first}'s "
        "parents and message, which no branch names."
    )
    assert len(said) == 1


def test_at_a_commit_with_fix_that_changes_nothing_the_commit_itself_passes(
    repo: Path, shell: Git, clock: FakeClock
) -> None:
    processes = Fixing(None)

    outcome, _, _ = gated_at(repo, "HEAD", processes, clock, fix=True)

    assert outcome == Ran(code=0, output="the report, ending 0\n")
    tree = shell.git(repo, "rev-parse", "HEAD^{tree}")
    assert Passes.of(repo, clock).found(Standing(tree=tree)) is not None


def test_at_a_commit_whose_gate_fails_nothing_is_recorded(
    repo: Path, shell: Git, clock: FakeClock
) -> None:
    processes = Witness(code=1)

    outcome, _, stopped = gated_at(repo, "HEAD", processes, clock)

    assert outcome == Ran(code=1, output="the report, ending 1\n")
    assert not stopped[0].exists()
    tree = shell.git(repo, "rev-parse", "HEAD^{tree}")
    assert Passes.of(repo, clock).found(Standing(tree=tree)) is None


def test_at_a_commit_the_person_s_layer_joins_its_files(
    repo: Path, linked: Path, clock: FakeClock, shell: Git
) -> None:
    (repo / ".gitignore").write_text(".venv/\n.lup/\nlup_project.local.py\n")
    shell.commit(repo, "ignore the person's layer")
    (repo / "lup_project.local.py").write_text("project = None\n")
    recorded = kept(repo, Scripted({}), clock).run().recorded
    processes = Witness()

    outcome, _, _ = gated_at(linked, "main", processes, clock)

    assert recorded is not None
    assert recorded.files.layer is not None
    assert outcome == recorded
    assert processes.ran == []


def test_the_gate_in_any_worktree_reads_the_person_s_layer_in_the_main_one(
    repo: Path, linked: Path
) -> None:
    (repo / "lup_project.local.py").write_text(BUILDING)
    processes = Scripted({})
    Check.declared(linked, processes, NODE).run()
    assert processes.ran[0] == ["uv", "run", "build", "it"]


def test_a_worktree_a_gone_run_left_is_removed_and_a_running_one_s_kept(
    repo: Path, shell: Git, clock: FakeClock
) -> None:
    left = Path(tempfile.mkdtemp(prefix="lup-gate-"))
    live = Path(tempfile.mkdtemp(prefix="lup-gate-"))
    for each in [left, live]:
        shell.git(repo, "worktree", "add", "--detach", "--quiet", str(each), "HEAD")
    locks = repo / ".git" / "lup" / "gates"
    locks.mkdir(parents=True)
    holding = FileLock(locks / f"{live.name}.lock")
    holding.acquire()
    try:
        _, said, _ = gated_at(repo, "HEAD", Witness(), clock)
        listed = shell.git(repo, "worktree", "list")
    finally:
        holding.release()
        shell.git(repo, "worktree", "remove", "--force", str(live))

    assert said[0] == (
        f"Removed {left}, a worktree a run of the gate on a commit left behind."
    )
    assert not left.exists()
    assert str(left) not in listed
    assert str(live) in listed


def test_at_a_revision_naming_no_commit_is_refused(
    repo: Path, clock: FakeClock
) -> None:
    with pytest.raises(GateError, match="`nowhere` names no commit in"):
        gated_at(repo, "nowhere", Witness(), clock)


# `lup-dev check`, reading the worktree's declaration.

DECLARED = """\
from lup_dev import Gate, Modules, Plain, Project, Python, Step

project = Project(
    modules=Modules.default().drop("private", why="these read Python's steps alone").edit(
        Python(
            runner=Plain(),
            gate=Gate.of(
                Step(name="lint", command=["lint", "--strict"]),
                Step(name="types", command=["types"]),
                Step(name="tests", command=["tests", "-q"]),
            ),
        )
    )
)
"""
"""A declaration whose `Python` runs three steps of its own, each as the `PATH`
finds it, and without `Private`, whose step would run beside them."""

BUILDING = '''
from lup_dev import Gate, Module, Modules, Project, Step


class Building(Module):
    """A module of the project's own, building something first."""

    name = "building"

    gate: Gate = Gate.of(Step(name="build", command=["build", "it"]), before="rules")


project = Project(modules=Modules.default().add(Building()))
'''
"""lup's defaults, and a module of the project's own adding a step before them."""


@pytest.fixture
def scripted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scripted:
    """`lup-dev check` run in `tmp_path`, by scripted processes, node on the `PATH`.

    The steps are the declaration's a test writes in `tmp_path`'s `lup_project.py`,
    or lup's defaults where it writes none.
    """
    processes = Scripted({"types": Ran(code=0, output="types said so\n")})

    def shell() -> Processes:
        return processes

    def toplevel(_: Path) -> Path:
        return tmp_path

    def machine() -> Tools:
        return NODE

    def scrapped(worktree: Path, runner: object) -> None:
        processes.ran.append(["scrapped", str(worktree)])

    git = ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test"]
    for arguments in [["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "one"]]:
        Shell().run([*git, *arguments], tmp_path)
    monkeypatch.setattr(cli, "Shell", shell)
    monkeypatch.setattr(cli, "scrapped", scrapped)
    monkeypatch.setattr(cli, "Machine", machine)
    monkeypatch.setattr(cli, "toplevel", toplevel)
    return processes


def test_lup_dev_check_runs_lups_default_gate_through_uv(scripted: Scripted) -> None:
    result = CliRunner().invoke(cli.app, ["check", "--fix"])
    assert result.exit_code == 0
    assert scripted.ran == [
        *(["uv", "run", *step.command] for step in Fixes().steps),
        *(["uv", "run", *step.command] for step in Gate().steps),
        ["uv", "run", "lup-dev", "private", "check"],
    ]


def test_lup_dev_check_runs_the_steps_a_module_of_the_projects_own_adds(
    scripted: Scripted, tmp_path: Path
) -> None:
    (tmp_path / "lup_project.py").write_text(BUILDING)
    result = CliRunner().invoke(cli.app, ["check"])
    assert result.exit_code == 0
    assert scripted.ran == [
        ["uv", "run", "build", "it"],
        *(["uv", "run", *step.command] for step in Gate().steps),
        ["uv", "run", "lup-dev", "private", "check"],
    ]


@pytest.mark.parametrize(("code", "exit_code"), [(0, 0), (1, 1)])
def test_lup_dev_check_exits_non_zero_when_a_step_fails(
    scripted: Scripted, tmp_path: Path, code: int, exit_code: int
) -> None:
    (tmp_path / "lup_project.py").write_text(DECLARED)
    scripted.answers = {"types": Ran(code=code, output="types said so\n")}
    result = CliRunner().invoke(cli.app, ["check"])
    assert result.exit_code == exit_code
    assert scripted.ran == [["lint", "--strict"], ["types"], ["tests", "-q"]]
    last = result.output.strip().splitlines()[-1]
    assert last.startswith(
        "The gate passed. It's recorded" if code == 0 else "The gate failed: types."
    )


def test_lup_dev_check_fix_rewrites_first(scripted: Scripted, tmp_path: Path) -> None:
    (tmp_path / "lup_project.py").write_text(DECLARED)
    result = CliRunner().invoke(cli.app, ["check", "--fix"])
    assert result.exit_code == 0
    fixes = [step.command for step in Fixes().steps]
    assert scripted.ran[: len(fixes)] == fixes
    assert [command[0] for command in scripted.ran[len(fixes) :]] == [
        "lint",
        "types",
        "tests",
    ]
    assert result.output.startswith(
        "passed   fix\npassed   ignores\npassed   reformat\npassed   lint\n"
    )


def test_lup_dev_check_runs_nothing_without_a_required_tool(
    scripted: Scripted, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "lup_project.py").write_text(DECLARED)

    def bare() -> Tools:
        return Stubbed([])

    monkeypatch.setattr(cli, "Machine", bare)
    result = CliRunner().invoke(cli.app, ["check"])
    assert isinstance(result.exception, RequirementError)
    assert "`node`, for `code-rules` (runs the rule engine)" in str(result.exception)
    assert scripted.ran == []


def test_lup_dev_check_fails_on_a_declaration_that_doesnt_load(
    scripted: Scripted, tmp_path: Path
) -> None:
    (tmp_path / "lup_project.py").write_text("project = 3\n")
    result = CliRunner().invoke(cli.app, ["check"])
    assert "is a `builtins.int`, not a `lup_dev.declaration.project.Project`" in str(
        result.exception
    )
    assert scripted.ran == []


def test_lup_dev_check_twice_on_the_same_files_runs_the_steps_once(
    scripted: Scripted, tmp_path: Path
) -> None:
    (tmp_path / "lup_project.py").write_text(DECLARED)
    first = CliRunner().invoke(cli.app, ["check"])
    second = CliRunner().invoke(cli.app, ["check", "--fix"])
    again = CliRunner().invoke(cli.app, ["check", "--again"])
    assert [result.exit_code for result in [first, second, again]] == [0, 0, 0]
    assert second.output.startswith("The gate passed on these files already, at ")
    assert [command[0] for command in scripted.ran] == 2 * ["lint", "types", "tests"]


BUILDS = """\
from lup_dev import Gate, Modules, Plain, Project, Python, Step

project = Project(
    modules=Modules.default().drop("private", why="these read Python's steps alone").edit(
        Python(
            runner=Plain(),
            gate=Gate.of(
                Step(name="engine", command=["build"], builds="bundle/engine.js"),
                Step(name="tests", command=["tests", "-q"]),
            ),
        )
    )
)
"""
"""A declaration whose `Python` builds a file its scripted step never writes,
then tests, each as the `PATH` finds it."""


def test_lup_dev_check_exits_non_zero_when_a_build_beside_a_pass_found_fails(
    scripted: Scripted, tmp_path: Path
) -> None:
    (tmp_path / "lup_project.py").write_text(BUILDS)
    first = CliRunner().invoke(cli.app, ["check"])
    scripted.answers = {"build": Ran(code=1, output="no bundler\n")}
    second = CliRunner().invoke(cli.app, ["check"])
    assert [result.exit_code for result in [first, second]] == [0, 1]
    assert second.output.startswith("failed   engine (exit 1)\n")
    assert [command[0] for command in scripted.ran] == ["build", "tests", "build"]


def test_lup_dev_check_at_a_commit_runs_its_gate_in_a_worktree_made_at_it(
    scripted: Scripted, tmp_path: Path
) -> None:
    result = CliRunner().invoke(cli.app, ["check", "--at", "HEAD"])
    assert result.exit_code == 0, result.output
    [ran, scrapped] = scripted.ran
    assert ran == Uv().judging(["lup-dev", "check"])
    assert scrapped[0] == "scrapped"
    assert result.output.startswith("The gate runs on ")
    assert result.output.endswith("env ok\n")
    repeated = CliRunner().invoke(cli.app, ["check", "--at", "HEAD"])
    assert repeated.output.startswith("The gate passed on these files already, at ")
    assert len(scripted.ran) == 2


def test_lup_dev_merge_merges_apart_gates_the_merge_and_prints_what_came_of_it(
    scripted: Scripted, tmp_path: Path
) -> None:
    git = ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test"]
    base = Shell().run(["git", "rev-parse", "HEAD"], tmp_path).output.strip()
    for arguments in [
        ["switch", "-q", "-c", "feat"],
        ["commit", "-q", "--allow-empty", "-m", "feat"],
    ]:
        Shell().run([*git, *arguments], tmp_path)
    tip = Shell().run(["git", "rev-parse", "HEAD"], tmp_path).output.strip()
    result = CliRunner().invoke(
        cli.app,
        ["merge", base, tip],
        input="merge: feat\n",
        env={"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.com"}
        | {"GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.com"},
    )
    assert result.exit_code == 0, result.output
    merging = TypeAdapter[Merging](Merging).validate_json(result.stdout)
    assert isinstance(merging, Merged)
    assert merging.ran
    parents = Shell().run(["git", "rev-parse", f"{merging.commit}^@"], tmp_path)
    assert parents.output.split() == [base, tip]
    assert "The gate runs on " in result.stderr
    assert scripted.ran[0] == Uv().judging(["lup-dev", "check", "--fix"])


def test_lup_dev_check_at_a_commit_exits_as_its_gate_did(
    scripted: Scripted,
) -> None:
    scripted.answers = {"env": Ran(code=1, output="The gate failed: tests.\n")}
    result = CliRunner().invoke(cli.app, ["check", "--at", "HEAD"])
    assert result.exit_code == 1
    assert result.output.endswith("The gate failed: tests.\n")


def test_lup_dev_check_at_a_commit_with_fix_runs_its_gate_with_the_fixes(
    scripted: Scripted,
) -> None:
    result = CliRunner().invoke(cli.app, ["check", "--at", "HEAD", "--fix"])
    assert result.exit_code == 0, result.output
    [ran, _] = scripted.ran
    assert ran == Uv().judging(["lup-dev", "check", "--fix"])
    assert result.output.endswith("env ok\n")
