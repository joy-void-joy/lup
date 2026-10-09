"""The contract with the engine: a file report as the engine sends it, as JSON."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lup_dev.codescan.contract import FileReport
from lup_dev.codescan.directives import Defer, Ignore, Malformed, Note

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
        "signatures": [
            {
                "name": "Claude.ask",
                "returns": "TurnResult[T]",
                "parameters": [
                    {
                        "name": "self",
                        "kind": "positional-or-keyword",
                        "annotation": "Self",
                        "has_default": False,
                    },
                    {
                        "name": "prompt",
                        "kind": "positional-or-keyword",
                        "annotation": "str",
                        "has_default": False,
                    },
                ],
            }
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
    assert report.surface.signatures[0].parameters[1].annotation == "str"
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
