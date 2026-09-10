"""The roster's changes registered under each runtime's prompt event, and run.

One rendering, two plugins. What is asserted per runtime is that the event
is registered with the guard and the verbatim fold, that the entry cannot
refuse, and — by running the rendered guard over a store the typed writers
produced, from inside a repository, the way the runtime would — that its
stdout is the envelope both vendors document: the pointer on the first
prompt, nothing on a quiet one, and a line for what changed after that.
"""

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest
import sh

from lup.coordination.changes import envelope, pointer
from lup.coordination.identity import MEMBER_ENV, mint_member_id
from lup.coordination.repository import RepositoryPeers
from lup.devtools.harness.generate import NativeHarnessComposition
from lup.providers.claude.harness import CLAUDE_PROMPT_EVENT
from lup.providers.codex.harness import CODEX_PROMPT_EVENT
from lup.providers.roster_prompt import (
    GUARD_SCRIPT,
    RUNTIME_MODULE,
    changes_runtime_source,
    prompt_hook,
)
from lup_template.harness.catalog import portable_harness
from lup_template.harness.composition import claude_target, codex_target

RUNTIMES = pytest.mark.parametrize(
    ("target", "tree", "event"),
    [
        pytest.param(claude_target, ".claude", CLAUDE_PROMPT_EVENT, id="claude"),
        pytest.param(codex_target, ".codex", CODEX_PROMPT_EVENT, id="codex"),
    ],
)


def rendered(tree: str) -> Path:
    """The plugin root one runtime's tree renders the hook under."""
    return Path(f"{tree}/plugins/lup")


@RUNTIMES
def test_the_prompt_event_registers_the_fold_and_refuses_nothing(
    target: Callable[[Path], NativeHarnessComposition], tree: str, event: str
) -> None:
    """Under its own event, with no matcher, and with no `exit 2` beside it."""
    artifacts = {
        artifact.path: artifact
        for artifact in target(Path.cwd()).recipe.desired.artifacts
    }
    plugin = rendered(tree)
    hooks = json.loads(artifacts[plugin / "hooks" / "hooks.json"].content)["hooks"]

    [group] = hooks[event]
    [entry] = group["hooks"]

    assert "matcher" not in group
    assert GUARD_SCRIPT in entry["command"]
    assert "exit 2" not in entry["command"]
    assert artifacts[plugin / "hooks" / "scripts" / GUARD_SCRIPT].executable
    runtime = artifacts[plugin / "hooks" / "runtime" / RUNTIME_MODULE]
    assert runtime.content == changes_runtime_source()


def test_a_project_without_a_roster_registers_nothing_and_carries_nothing() -> None:
    """The declaration is the peer policy, so declining it declines this too."""
    undeclared = portable_harness().declared_hooks.model_copy(
        update={"peer_policy": None}
    )

    quiet = prompt_hook(Path("plugin"), "PLUGIN_ROOT", undeclared, "UserPromptSubmit")

    assert quiet.registered == {}
    assert quiet.artifacts == []


@RUNTIMES
def test_the_rendered_guard_prints_the_changes_as_additional_context(
    target: Callable[[Path], NativeHarnessComposition],
    tree: str,
    event: str,
    tmp_path: Path,
) -> None:
    """The measurement: the guard run as the runtime runs it, over a real store.

    No launcher-proven id in the environment, so the reader falls back to the
    id the runtime hands the hook — the bare session's own case.
    """
    artifacts = {
        artifact.path: artifact
        for artifact in target(Path.cwd()).recipe.desired.artifacts
    }
    plugin = rendered(tree)
    for kind, name in (("scripts", GUARD_SCRIPT), ("runtime", RUNTIME_MODULE)):
        shipped = tmp_path / "plugin" / "hooks" / kind / name
        shipped.parent.mkdir(parents=True, exist_ok=True)
        shipped.write_text(artifacts[plugin / "hooks" / kind / name].content)
    repository = tmp_path / "repository"
    repository.mkdir()
    sh.git("init", "-q", str(repository))
    peers = RepositoryPeers(repository)
    peers.join(mint_member_id(), repository, cli_name="reviewer")
    prompt = {"session_id": "abc123", "cwd": str(repository), "hook_event_name": event}
    environment = {**os.environ, MEMBER_ENV: ""}

    def submitted() -> str:
        return str(
            sh.sh(
                str(tmp_path / "plugin" / "hooks" / "scripts" / GUARD_SCRIPT),
                _in=json.dumps(prompt),
                _cwd=str(repository),
                _env=environment,
            )
        )

    first = submitted()
    quiet = submitted()
    peers.join(mint_member_id(), repository, cli_name="third")
    arrived = submitted()

    assert json.loads(first) == envelope(event, [pointer(1)])
    assert quiet == ""
    assert json.loads(arrived) == envelope(
        event, [f"third arrived — repository — working in {repository}"]
    )
