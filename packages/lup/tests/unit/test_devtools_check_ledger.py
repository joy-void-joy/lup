"""What the pre-flight gate says about where a repository keeps its log.

`run_checks` takes the layout a project declares and hands every sweep to
`scan_reports` through one partial. A parameter that partial leaves out is no
error: `scan_reports` declares a default for it, so the gate runs, reports,
and answers about a log with no committed half for a repository whose
committed journal is in the tree — the one half with something to check. The
first two tests drive the gate over a throwaway repository and read the row
it prints; the third holds the partial to the signature, so a parameter added
to `scan_reports` and left out of the gate fails here rather than in the
project that declared it.
"""

import inspect
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

import pytest
import typer

import lup.devtools.dev.check as check
from lup.devtools.project import DevProject
from lup.harness.models import HookSet
from lup.ledger.store import InTree, LedgerLayout
from tests.unit.test_ledger_placement import committed, repository

UNION = "ledger/journal.jsonl merge=union\n"


def quiet(name: str) -> Callable[..., check.CheckReport]:
    """A tool the gate forks, answering ok without forking anything."""

    def tool(*args: object, **kwargs: object) -> check.CheckReport:
        return check.CheckReport(name=name, lines=[f"{name}: ok"])

    return tool


def weightless(compositions: object) -> int:
    """No compiled tree to weigh, which the real reading refuses to guess at."""
    return 0


@pytest.fixture
def gate(tmp_lup_project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway repository the sweeps read, with the tools that answer
    about files or compiled trees stubbed: neither is what is under test."""
    root = repository(tmp_lup_project)
    (root / "README.md").write_text("# probe\n", encoding="utf-8")
    committed(root, "base")
    monkeypatch.chdir(root)
    for tool in ("ruff_format_check", "ruff_lint_check", "pyright_check"):
        monkeypatch.setattr(check, tool, quiet(tool))
    monkeypatch.setattr(check, "guidance_bytes", weightless)
    return root


def checked(ledger: LedgerLayout) -> None:
    check.run_checks(
        fix=False,
        no_test=True,
        project=DevProject(package="app"),
        test_roots=[],
        compositions=[],
        repository_writers=[],
        git_guards=[],
        hooks_declaration=HookSet(id="probe", policy_ids=[]),
        ledger=ledger,
    )


def printed(ledger: LedgerLayout, capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Every line the gate echoed, whether or not it went on to refuse: a
    throwaway repository has no merge driver registered, so the exit says
    nothing about the row under test."""
    with suppress(typer.Exit):
        checked(ledger)
    return capsys.readouterr().out.splitlines()


def placement_row(lines: list[str]) -> str:
    [row] = [line for line in lines if line.startswith("ledger placement:")]
    return row


def test_a_committed_half_fails_the_gate_until_it_merges_by_union(
    gate: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout = LedgerLayout(committed=InTree())

    lines = printed(layout, capsys)

    assert placement_row(lines) == f"ledger placement: FAIL ({layout.describe()})"
    assert any('"ledger/journal.jsonl merge=union"' in line for line in lines)
    assert lines[-1].startswith("Failed:") and "ledger placement" in lines[-1]


def test_a_committed_half_declared_to_merge_by_union_passes_naming_both_halves(
    gate: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (gate / ".gitattributes").write_text(UNION, encoding="utf-8")
    layout = LedgerLayout(committed=InTree())

    lines = printed(layout, capsys)

    assert placement_row(lines) == (
        "ledger placement: ok (committed kinds in the tree at ledger/, merged by"
        " union; local kinds shared under the git directory)"
    )
    assert "ledger placement" not in lines[-1]


def test_a_log_with_no_committed_half_has_nothing_to_ask_git(
    gate: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = printed(LedgerLayout(), capsys)

    assert placement_row(lines) == (
        "ledger placement: ok (every kind shared under the git directory)"
    )


def test_the_gate_binds_every_parameter_scan_reports_declares(
    gate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bound against the real signature, so a positional slot that shifted
    # fails as loudly as a keyword that went missing.
    declared = inspect.signature(check.scan_reports)
    calls: list[inspect.BoundArguments] = []

    def recording(*args: object, **kwargs: object) -> list[check.CheckReport]:
        calls.append(declared.bind(*args, **kwargs))
        return []

    monkeypatch.setattr(check, "scan_reports", recording)
    layout = LedgerLayout(committed=InTree())

    checked(layout)

    [call] = calls
    assert set(call.arguments) == set(declared.parameters)
    assert call.arguments["ledger"] is layout
