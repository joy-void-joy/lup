"""The file tools are refused every path a command is refused.

`HookSet.refused_paths` is the one declaration a shell word is refused by, on
both runtimes. Claude's Read, Grep and Glob run in the session's own process
and never reach the policy hook, so its settings carry the same set as `Read`
deny rules -- which the runtime also merges into its sandbox's read
restrictions -- compiled from that declaration rather than from a second list
that named two paths of it. Codex has no file-reading tool: every read it
makes is a command, so the dispatcher's own copy of the declaration is its
whole layer, and its sandbox has no read restriction to carry.
"""

import ast
import json
from pathlib import Path

import pytest

from lup.devtools.harness.settings import credential_read_denials
from lup_template.harness.catalog import declared_hook_set


def generated_refusals(runtime: str) -> object:
    """The refusal rows a runtime's generated dispatcher was compiled with."""
    data = Path(f".{runtime}/plugins/lup/hooks/runtime/policy_data.py")
    for node in ast.parse(data.read_text(encoding="utf-8")).body:
        match node:
            case ast.AnnAssign(target=ast.Name(id="REFUSED_PATHS"), value=value) if (
                value is not None
            ):
                return ast.literal_eval(value)
    raise AssertionError(f"{data} carries no REFUSED_PATHS")


def test_claude_s_file_tools_are_denied_every_withheld_path() -> None:
    settings = json.loads(Path(".claude/settings.json").read_text(encoding="utf-8"))
    denied = settings["permissions"]["deny"]
    compiled = credential_read_denials(declared_hook_set())
    declared = [
        pattern
        for refused in declared_hook_set().refused_paths
        for pattern in refused.paths
    ]

    assert set(compiled) <= set(denied)
    assert len(compiled) >= len(declared)
    for rule in [
        "Read(~/.ssh/**)",
        "Read(~/.ssh)",
        "Read(~/.aws/credentials)",
        "Read(~/.netrc)",
        "Read(~/.git-credentials)",
        "Read(~/.claude/.credentials.json)",
        "Read(//**/claude-config/.credentials.json)",
        "Read(~/.codex/auth.json)",
        "Read(//proc/*/environ)",
    ]:
        assert rule in denied
    assert "credentials" not in settings["sandbox"]


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_each_dispatcher_withholds_the_whole_declared_set(runtime: str) -> None:
    assert generated_refusals(runtime) == [
        refused.erased() for refused in declared_hook_set().refused_paths
    ]
