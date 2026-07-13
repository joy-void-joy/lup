"""Behavior tests for the in-container REPL server's wire protocol.

``serve`` is importable host-side by design (it only runs under
``__main__`` in the container), so the protocol loop can be driven with
in-memory streams: feed JSON lines, read JSON responses.
"""

import sys
from io import StringIO
from typing import TypedDict

from pydantic import TypeAdapter

from lup.sandbox.repl_server import serve


class ReplResponse(TypedDict):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


RESPONSE = TypeAdapter(ReplResponse)


def run_server(lines: list[str]) -> list[ReplResponse]:
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
    return [RESPONSE.validate_json(line) for line in out.getvalue().splitlines()]


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
    assert [r["exit_code"] for r in responses] == [1, 1, 1, 0, 0]
    for rejected in responses[:3]:
        assert rejected["stderr"].startswith("Malformed request")
        assert rejected["stdout"] == ""
    assert responses[4]["stdout"] == "3\n"


def test_failing_cell_reports_traceback_and_later_cells_run() -> None:
    responses = run_server(['{"code": "1 / 0"}', '{"code": "print(\'alive\')"}'])
    assert responses[0]["exit_code"] == 1
    assert "ZeroDivisionError" in responses[0]["stderr"]
    assert responses[1] == {
        "exit_code": 0,
        "stdout": "alive\n",
        "stderr": "",
        "duration_ms": responses[1]["duration_ms"],
    }
