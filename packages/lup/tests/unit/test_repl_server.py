"""Behavior tests for the in-container REPL server's wire protocol.

``serve`` is importable host-side by design (it only runs under
``__main__`` in the container), so the protocol loop can be driven with
in-memory streams: feed JSON lines, read JSON responses.
"""

import json
import sys
from io import StringIO

from lup.sandbox.models import ExecuteCodeResult
from lup.sandbox.repl_server import serve


def run_server_raw(lines: list[str]) -> list[str]:
    originals = sys.stdin, sys.stdout, sys.stderr
    out = StringIO()
    sys.stdin = StringIO("".join(f"{line}\n" for line in lines))
    sys.stdout = out
    try:
        serve()
    finally:
        hijacked = [sys.stdin, sys.stdout, sys.stderr]
        sys.stdin, sys.stdout, sys.stderr = originals
        for handle in hijacked:
            if handle is not out and handle not in originals:
                handle.close()
    return out.getvalue().splitlines()


def run_server(lines: list[str]) -> list[ExecuteCodeResult]:
    return [
        ExecuteCodeResult.model_validate_json(line) for line in run_server_raw(lines)
    ]


def test_malformed_requests_error_without_killing_the_server() -> None:
    responses = run_server(
        [
            "not json",
            "[1, 2]",
            '{"timeout": 5}',
            '{"code": "x = 1 + 1"}',
            '{"code": "print(x + 1)"}',
        ]
    )
    assert [r.exit_code for r in responses] == [1, 1, 1, 0, 0]
    for rejected in responses[:3]:
        assert rejected.stderr.startswith("Malformed request")
        assert rejected.stdout == ""
    assert responses[4].stdout == "3\n"


def test_failing_cell_reports_traceback_and_later_cells_run() -> None:
    responses = run_server(['{"code": "1 / 0"}', '{"code": "print(\'alive\')"}'])
    assert responses[0].exit_code == 1
    assert "ZeroDivisionError" in responses[0].stderr
    assert responses[1] == ExecuteCodeResult(
        exit_code=0,
        stdout="alive\n",
        stderr="",
        duration_ms=responses[1].duration_ms,
    )


def test_server_emits_exactly_the_models_fields() -> None:
    """The in-container script is the one copy of the shape it cannot import.

    It runs on pure stdlib, so it hand-writes the response dict. Parsing
    alone would not catch a drift — the model's fields all carry defaults,
    so a dropped key would validate into a silent default. Compare the
    emitted keys against the model directly.
    """
    (line,) = run_server_raw(['{"code": "x = 1"}'])

    assert set(json.loads(line)) == set(ExecuteCodeResult.model_fields)
