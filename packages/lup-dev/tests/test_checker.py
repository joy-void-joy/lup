"""The contract with the engine, as JSON: a check request as the client sends it, and
a file report as the engine sends it."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lup_dev import CodeRules, Modules, Plain, Project, Rules, Uv, environments
from lup_dev.catalog.rules import DefaultRules
from lup_dev.codescan.contract import FileReport
from lup_dev.codescan.directives import Defer, Ignore, Malformed, Note
from lup_dev.codescan.engine import CheckRequest, EngineChecker, EngineEnvironment
from lup_dev.declaration.resolve import resolve
from lup_dev.environments import environment
from lup_dev.policy import importers
from lup_dev.policy.importers import BackgroundSpawner
from lup_dev.settings import LupDevSettings

PATH = "packages/lup/src/lup/claude.py"
REPORT = {
    "path": PATH,
    "findings": [
        {
            "path": PATH,
            "owner": "lup",
            "rule": "tuple-shape",
            "message": "a tuple[str, int] hides what each position means",
            "steer": "name the fields with a model, or use list[X]",
            "span": {
                "start": {"line": 41, "column": 12},
                "end": {"line": 41, "column": 27},
            },
        },
        {
            "path": PATH,
            "owner": "pyright",
            "rule": "reportOptionalMemberAccess",
            "message": '"split" is not a known attribute of "None"',
            "span": {
                "start": {"line": 50, "column": 9},
                "end": {"line": 50, "column": 14},
            },
        },
    ],
    "directives": [
        {
            "kind": "ignore",
            "line": 12,
            "covers": 13,
            "rule": "tuple-shape",
            "why": "sh takes positional tuples",
        },
        {
            "kind": "defer",
            "line": 20,
            "issue": 7,
            "why": "retries ignore the reset time",
        },
        {"kind": "defer", "line": 21, "when": "sdk_reports_ttl", "why": "read the TTL"},
        {"kind": "note", "line": 30, "text": "the retry count is the provider's limit"},
        {
            "kind": "malformed",
            "line": 40,
            "text": 'ignore("tuple-shape")',
            "problem": "an ignore needs its why",
        },
    ],
    "surface": {
        "exported": [],
        "classes": ["Claude"],
        "functions": ["Claude.ask"],
        "places": [
            {"kind": "class", "name": "Claude", "line": 8},
            {"kind": "function", "name": "Claude.ask", "line": 11},
        ],
    },
    "imports": ["claude_agent_sdk", "lup.sessions.results"],
}


def directives(*entries: dict[str, object]) -> str:
    return json.dumps({"path": "a.py", "directives": list(entries)})


def test_a_report_reads_every_part() -> None:
    report = FileReport.model_validate_json(json.dumps(REPORT))
    assert report.path == Path(PATH)
    assert [finding.owner for finding in report.findings] == ["lup", "pyright"]
    assert [type(directive) for directive in report.directives] == [
        Ignore,
        Defer,
        Defer,
        Note,
        Malformed,
    ]
    assert report.surface.functions == ["Claude.ask"]
    assert report.surface.place("function", "Claude.ask") == 11
    assert report.imports == ["claude_agent_sdk", "lup.sessions.results"]


def test_a_defer_needs_an_issue_or_a_condition() -> None:
    with pytest.raises(ValidationError):
        FileReport.model_validate_json(
            directives({"kind": "defer", "line": 1, "why": "x"})
        )


def test_a_defer_needs_its_reason() -> None:
    with pytest.raises(ValidationError):
        FileReport.model_validate_json(
            directives({"kind": "defer", "line": 1, "issue": 7})
        )


def test_an_unknown_directive_kind_is_refused() -> None:
    with pytest.raises(ValidationError):
        FileReport.model_validate_json(directives({"kind": "todo", "line": 1}))


def test_a_check_request_carries_each_modules_selection_as_recorded() -> None:
    project = Project(
        modules=Modules.default().edit(
            CodeRules(rules=Rules().drop("regex", why="a grammar").add("elif"))
        )
    )
    request = CheckRequest(
        build="1-2",
        environment=EngineEnvironment(venv=None, files=[]),
        root="/work",
        rules=resolve(project).rules,
        sources=[],
    )
    [selected] = json.loads(request.model_dump_json())["rules"]
    left_out = {
        "verb": "drop",
        "names": ["runtime-mention"],
        "why": DefaultRules().left_out[0].why,
    }
    assert selected == {
        "module": "code-rules",
        "rules": {
            "start": {"kind": "all"},
            "operations": [
                left_out,
                {"verb": "drop", "names": ["regex"], "why": "a grammar"},
                {"verb": "add", "entries": ["elif"], "before": None, "after": None},
            ],
        },
        "default": {"start": {"kind": "all"}, "operations": [left_out]},
    }


def test_a_rooms_worktree_is_read_in_its_launchs_environment_as_the_room_places_it() -> (
    None
):
    launch = Path("/rooms/lup/environments/0f3a")
    root = Path("/srv/lup.git/tree/dev")
    assert EngineEnvironment.of(Uv(), root) == EngineEnvironment(
        venv=".venv", files=Uv().environment()
    )
    assert EngineEnvironment.of(Uv(), root, launch) == EngineEnvironment(
        venv=str(environment(launch, root)), files=Uv().environment()
    )
    # A runner naming no environment reads none, wherever the room keeps them.
    assert EngineEnvironment.of(Plain(), root, launch).venv is None


def test_the_engine_reads_the_launchs_environments_given_else_those_the_room_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    given = tmp_path / "given"
    named = tmp_path / "named"
    assert EngineChecker.configured(LupDevSettings()).environments is None
    monkeypatch.setenv(environments.ENVIRONMENTS, str(named))
    assert EngineChecker.configured(LupDevSettings()).environments == named
    assert EngineChecker.configured(LupDevSettings(), given).environments == given


def test_the_importers_pass_is_started_reading_the_launchs_environments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[list[str]] = []

    def detached(program: str, *arguments: str, log: Path) -> None:
        started.append(list(arguments))

    monkeypatch.setattr(importers, "detached", detached)
    worktree = tmp_path / "tree"
    log = tmp_path / "log"
    BackgroundSpawner().spawn(worktree, log)
    BackgroundSpawner(environments=tmp_path / "launch").spawn(worktree, log)
    assert started == [
        ["-m", "lup_dev.cli", "importers", str(worktree)],
        [
            "-m",
            "lup_dev.cli",
            "importers",
            str(worktree),
            "--environments",
            str(tmp_path / "launch"),
        ],
    ]
