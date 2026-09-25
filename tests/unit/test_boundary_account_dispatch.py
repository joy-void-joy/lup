"""A refused git write reaches the agent named as the boundary, from either runtime.

Run through each generated dispatcher, because the sentence exists only if
the PostToolUse half of the compiled script calls it: the reading was
present in both scripts and called by neither, so a contained session met a
read-only `config` as a bare `Read-only file system`. Each runtime carries a
post-tool finding its own way -- a blocking decision on stdout, or stderr
behind exit 2 -- so what is read is everything the script said.
"""

import json
from pathlib import Path

import pytest
import sh

from lup.types import JsonObject

DISPATCHERS = [
    Path(".claude/plugins/lup/hooks/scripts/policy.py"),
    Path(".codex/plugins/lup/hooks/scripts/policy.py"),
]

REFUSED = (
    "error: could not lock config file /repo.git/config: Read-only file system\n"
    "error: unable to write upstream branch configuration"
)


def observed(dispatcher: Path, payload: JsonObject) -> str:
    """Everything one PostToolUse through a generated dispatcher said."""
    ran = sh.Command("python3")(
        "-I",
        "-S",
        str(dispatcher),
        _in=json.dumps(
            {"session_id": "s", "hook_event_name": "PostToolUse", **payload}
        ),
        _env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
        _ok_code=[0, 2],
        _return_cmd=True,
    )
    return ran.stdout.decode() + ran.stderr.decode()


def pushed(root: Path) -> JsonObject:
    """A `push -u` that landed and could not record its upstream."""
    return {
        "tool_name": "Bash",
        "tool_input": {"command": "git push -u origin feat"},
        "tool_response": {"stdout": "", "stderr": REFUSED, "exit_code": 0},
        "cwd": str(root),
    }


@pytest.mark.parametrize("dispatcher", DISPATCHERS, ids=["claude", "codex"])
def test_a_refused_upstream_record_is_explained_after_the_push(
    dispatcher: Path, tmp_path: Path
) -> None:
    (tmp_path / ".lup").mkdir()
    (tmp_path / ".lup" / "boundary.json").write_text(
        json.dumps(
            {
                "read_only": ["/repo.git"],
                "writable": ["/repo.git/refs"],
                "git_shared": ["/repo.git"],
                "write_refusals": ["Read-only file system"],
            }
        )
    )

    assert "host terminal" in observed(dispatcher.resolve(), pushed(tmp_path))


@pytest.mark.parametrize("dispatcher", DISPATCHERS, ids=["claude", "codex"])
def test_an_uncontained_session_hears_nothing(dispatcher: Path, tmp_path: Path) -> None:
    assert "host terminal" not in observed(dispatcher.resolve(), pushed(tmp_path))
