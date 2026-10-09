"""The gate as one command: every step runs, and a failure exits non-zero."""

import os
import sys
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.catalog.gate import Gate, Step
from lup_dev.gate import Check, Outcome, Ran, Runner, Shell, failed, report

if TYPE_CHECKING:
    from pathlib import Path


class Scripted(Runner):
    """Answers each command as scripted by its first word, recording every run."""

    def __init__(self, answers: dict[str, Ran]) -> None:
        self.answers = answers
        self.ran: list[list[str]] = []

    def run(self, command: list[str], cwd: Path) -> Ran:
        self.ran.append(command)
        return self.answers.get(command[0], Ran(code=0, output=f"{command[0]} ok\n"))


GATE = Gate(
    steps=[
        Step(name="lint", command=["lint", "--strict"]),
        Step(name="types", command=["types"]),
        Step(name="tests", command=["tests", "-q"]),
    ]
)


def test_every_step_passes(tmp_path: Path) -> None:
    runner = Scripted({})
    outcomes = Check(root=tmp_path, runner=runner, gate=GATE).run()
    assert [(o.step, o.result, o.code) for o in outcomes] == [
        ("lint", "passed", 0),
        ("types", "passed", 0),
        ("tests", "passed", 0),
    ]
    assert failed(outcomes) == []
    assert report(outcomes).endswith("The gate passed.")


def test_every_step_runs_after_one_fails(tmp_path: Path) -> None:
    runner = Scripted({"lint": Ran(code=1, output="a.py:1:1 - E501 too long\n")})
    outcomes = Check(root=tmp_path, runner=runner, gate=GATE).run()
    assert runner.ran == [["lint", "--strict"], ["types"], ["tests", "-q"]]
    assert [o.result for o in outcomes] == ["failed", "passed", "passed"]
    assert failed(outcomes) == ["lint"]


def test_the_report_gives_each_failures_output_in_full(tmp_path: Path) -> None:
    long = "".join(f"finding {n}\n" for n in range(500))
    runner = Scripted(
        {"types": Ran(code=1, output=long), "tests": Ran(code=2, output="1 failed\n")}
    )
    text = report(Check(root=tmp_path, runner=runner, gate=GATE).run())
    assert text.startswith(
        "passed   lint\nfailed   types (exit 1)\nfailed   tests (exit 2)\n"
    )
    assert f"--- types (exit 1) ---\n{long.rstrip()}" in text
    assert "--- tests (exit 2) ---\n1 failed" in text
    assert "lint ok" not in text
    assert text.endswith("The gate failed: types, tests.")


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
    runner = Scripted({})
    [outcome] = Check(root=root, runner=runner, gate=Gate(steps=[ENGINE])).run()
    return outcome, runner


def test_a_build_newer_than_its_sources_is_skipped(tmp_path: Path) -> None:
    touch(tmp_path / "src" / "deep" / "rule.ts", 1_000)
    touch(tmp_path / "table.ts", 1_000)
    touch(tmp_path / "bundle" / "engine.js", 2_000)
    outcome, runner = check_engine(tmp_path)
    assert outcome.result == "skipped"
    assert outcome.why == "bundle/engine.js is newer than its sources"
    assert runner.ran == []
    assert report([outcome]).startswith(
        "skipped  engine (bundle/engine.js is newer than its sources)"
    )


def test_a_build_older_than_a_source_runs(tmp_path: Path) -> None:
    touch(tmp_path / "bundle" / "engine.js", 2_000)
    touch(tmp_path / "src" / "deep" / "rule.ts", 3_000)
    outcome, runner = check_engine(tmp_path)
    assert outcome.result == "passed"
    assert runner.ran == [["build"]]


def test_a_missing_build_runs(tmp_path: Path) -> None:
    touch(tmp_path / "table.ts", 1_000)
    outcome, _ = check_engine(tmp_path)
    assert outcome.result == "passed"


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


def test_the_catalogs_gate_runs_the_engine_then_the_tools() -> None:
    assert [step.name for step in Gate().steps] == [
        "engine",
        "ruff",
        "format",
        "pyright",
        "pytest",
        "lint-imports",
    ]
    assert Gate().steps[1].command == ["uv", "run", "ruff", "check", "--ignore-noqa"]


@pytest.mark.parametrize(("code", "exit_code"), [(0, 0), (1, 1)])
def test_lup_dev_check_exits_non_zero_when_a_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, exit_code: int
) -> None:
    runner = Scripted({"types": Ran(code=code, output="types said so\n")})

    def shell() -> Runner:
        return runner

    monkeypatch.setattr(cli, "Shell", shell)
    monkeypatch.setattr(cli, "Gate", lambda: GATE)

    def toplevel(_: Path) -> Path:
        return tmp_path

    monkeypatch.setattr(cli, "toplevel", toplevel)
    result = CliRunner().invoke(cli.app, ["check"])
    assert result.exit_code == exit_code
    assert [command[0] for command in runner.ran] == ["lint", "types", "tests"]
    last = result.output.strip().splitlines()[-1]
    assert last == ("The gate passed." if code == 0 else "The gate failed: types.")
