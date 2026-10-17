"""The gate as one command: its requirements first, then every step runs, each
through the project's runner, and a failure exits non-zero. Every process and
probe is stubbed."""

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from typer.testing import CliRunner

from lup_dev import Requirement, cli
from lup_dev.catalog.gate import Gate, Step
from lup_dev.declaration.requirements import (
    Needed,
    Printed,
    RequirementError,
    Tools,
)
from lup_dev.declaration.runner import Plain, Uv
from lup_dev.gate import (
    Check,
    Fixes,
    Gated,
    Outcome,
    Processes,
    Ran,
    Shell,
    failed,
    report,
)

if TYPE_CHECKING:
    from conftest import Kit


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


# `lup-dev check`, reading the worktree's declaration.

DECLARED = """\
from lup_dev import Gate, Modules, Plain, Project, Python, Step

project = Project(
    modules=Modules.default().edit(
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
finds it."""

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

    monkeypatch.setattr(cli, "Shell", shell)
    monkeypatch.setattr(cli, "Machine", machine)
    monkeypatch.setattr(cli, "toplevel", toplevel)
    return processes


def test_lup_dev_check_runs_lups_default_gate_through_uv(scripted: Scripted) -> None:
    result = CliRunner().invoke(cli.app, ["check", "--fix"])
    assert result.exit_code == 0
    assert scripted.ran == [
        *(["uv", "run", *step.command] for step in Fixes().steps),
        *(["uv", "run", *step.command] for step in Gate().steps),
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
    assert last == ("The gate passed." if code == 0 else "The gate failed: types.")


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
