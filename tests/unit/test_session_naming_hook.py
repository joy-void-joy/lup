"""A session named for its work, registered under each runtime's prompt event, and run.

One rendering, two plugins, and the difference between them is the point: the
runtime that takes a name only from the hook's own answer waits on the ask,
and the one that names a thread through its app-server does not. What is
asserted per runtime is the registration and the compiled declaration, and —
by running the rendered guard over a store the typed writers produced, from
inside a repository, with a stand-in CLI on the path the way the runtime's own
would be — what the session is told, what its roster row answers to, and what
the runtime was asked.
"""

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

import pytest
import sh

from lup.coordination.bare.naming import Naming, recalled
from lup.coordination.bare.store import current_name, member_of, session_actor
from lup.coordination.identity import MEMBER_ENV, mint_member_id
from lup.coordination.repository import RepositoryPeers
from lup.devtools.harness.generate import NativeHarnessComposition
from lup.harness.models import Artifact, HookSet
from lup.providers.claude.harness import CLAUDE_PROMPT_EVENT, CLAUDE_SESSION_NAMING
from lup.providers.codex.harness import CODEX_PROMPT_EVENT, CODEX_SESSION_NAMING
from lup.providers.roster_prompt import store_modules
from lup.providers.session_naming import GUARD_SCRIPT, RUNTIME_ENTRY, naming_hook
from lup_template.harness.catalog import declared_hook_set
from lup_template.harness.composition import claude_target, codex_target

RUNTIMES = pytest.mark.parametrize(
    ("target", "tree", "event", "host", "model", "timeout"),
    [
        pytest.param(
            claude_target,
            ".claude",
            CLAUDE_PROMPT_EVENT,
            CLAUDE_SESSION_NAMING,
            "sonnet",
            30,
            id="claude",
        ),
        pytest.param(
            codex_target,
            ".codex",
            CODEX_PROMPT_EVENT,
            CODEX_SESSION_NAMING,
            "gpt-5.6-terra",
            10,
            id="codex",
        ),
    ],
)

STAND_IN = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

record = Path(__file__).with_name("asked.jsonl")
answer = json.loads(Path(__file__).with_name("answer.json").read_text())
arguments = sys.argv[1:]
if arguments[:1] == ["app-server"]:
    for line in sys.stdin:
        message = json.loads(line)
        if message.get("method") == "thread/name/set":
            with record.open("a") as log:
                log.write(json.dumps({"named": message["params"]}) + "\\n")
        if "id" in message:
            print(json.dumps({"id": message["id"], "result": {}}), flush=True)
    sys.exit(0)
prompt = sys.stdin.read()
with record.open("a") as log:
    log.write(json.dumps({"arguments": arguments, "prompt": prompt}) + "\\n")
if arguments[:1] == ["exec"]:
    Path(arguments[arguments.index("-o") + 1]).write_text(json.dumps(answer))
else:
    print(json.dumps({"is_error": False, "structured_output": answer}))
"""
"""One program standing in for both runtimes' CLIs, answering *answer.json*.

Records every ask with the prompt it was handed, and every thread it was
asked to name, beside itself: what the runtime would have been asked is what
these tests assert, since no model is reached from a unit test."""


class Named(TypedDict):
    threadId: str
    name: str


class Asked(TypedDict, total=False):
    """One line of the stand-in's record: an ask and its prompt, or a thread named."""

    arguments: list[str]
    prompt: str
    named: Named


def rendered(tree: str) -> Path:
    """The plugin root one runtime's tree renders the hook under."""
    return Path(f"{tree}/plugins/lup")


def shipped(
    target: Callable[[Path], NativeHarnessComposition],
) -> dict[Path, Artifact]:
    """Every artifact one runtime's plugin carries, by the path it carries it at."""
    return {
        artifact.path: artifact
        for artifact in target(Path.cwd()).recipe.desired.artifacts
    }


def laid_out(artifacts: dict[Path, Artifact], plugin: Path, root: Path) -> Path:
    """The guard, the host half, its settings and the shipped package, as a plugin lays them out."""
    runtime = Path("hooks") / "runtime" / RUNTIME_ENTRY
    compiled = Path("hooks") / runtime.with_suffix(".json").name
    carried = [
        (
            Path("hooks") / "scripts" / GUARD_SCRIPT,
            artifacts[plugin / "hooks" / "scripts" / GUARD_SCRIPT],
        ),
        (runtime, artifacts[plugin / runtime]),
        (compiled, artifacts[plugin / compiled]),
        *[
            (Path("hooks") / "runtime" / module.path, module)
            for module in store_modules()
        ],
    ]
    for relative, artifact in carried:
        landed = root / relative
        landed.parent.mkdir(parents=True, exist_ok=True)
        landed.write_text(artifact.content)
    return root / "hooks" / "scripts" / GUARD_SCRIPT


class Session:
    """One session on a real roster, prompted through the rendered guard."""

    def __init__(
        self,
        target: Callable[[Path], NativeHarnessComposition],
        tree: str,
        event: str,
        tmp_path: Path,
        answer: str | None,
    ) -> None:
        self.guard = laid_out(shipped(target), rendered(tree), tmp_path / "plugin")
        self.event = event
        self.repository = tmp_path / "repository"
        self.repository.mkdir()
        sh.git("init", "-q", str(self.repository))
        self.peers = RepositoryPeers(self.repository)
        self.member = mint_member_id()
        self.peers.join(self.member, self.repository, cli_name="dev")
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        (self.bin / "answer.json").write_text(json.dumps({"name": answer}))
        for program in ("claude", "codex"):
            stand_in = self.bin / program
            stand_in.write_text(STAND_IN)
            stand_in.chmod(0o755)

    def prompted(self, prompt: str, title: str | None = None) -> str:
        """What the hook prints for one prompt, with *title* where the chrome reports one."""
        payload = {
            "session_id": "root-session",
            "cwd": str(self.repository),
            "hook_event_name": self.event,
            "prompt": prompt,
            **({"session_title": title} if title is not None else {}),
        }
        return str(
            sh.sh(
                str(self.guard),
                _in=json.dumps(payload),
                _cwd=str(self.repository),
                _env={
                    **os.environ,
                    MEMBER_ENV: self.member,
                    "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                },
            )
        )

    def called(self) -> str:
        """What the roster calls this session now."""
        found = member_of(self.peers.root, session_actor(self.member))
        assert found is not None
        return current_name(found)

    def asked(self) -> list[Asked]:
        """Everything the stand-in CLI was asked, oldest first."""
        record = self.bin / "asked.jsonl"
        return (
            [json.loads(line) for line in record.read_text().splitlines()]
            if record.exists()
            else []
        )

    def concluded(self, count: int) -> list[Asked]:
        """The record once a detached ask has made *count* entries and concluded.

        Waited on rather than slept past, for at most fifteen seconds: the
        work is a process of the hook's own that outlives it.
        """
        for _ in range(300):
            titling = recalled(self.peers.root, self.member)
            if len(self.asked()) >= count and titling and not titling["asked"]:
                break
            time.sleep(0.05)
        return self.asked()


@RUNTIMES
def test_the_prompt_event_registers_the_naming_hook_and_refuses_nothing(
    target: Callable[[Path], NativeHarnessComposition],
    tree: str,
    event: str,
    host: str,
    model: str,
    timeout: int,
) -> None:
    """Under the prompt event, never refusing, with the declaration in the runtime's words."""
    artifacts = shipped(target)
    plugin = rendered(tree)
    hooks = json.loads(artifacts[plugin / "hooks" / "hooks.json"].content)["hooks"]
    [entry] = [
        entry
        for group in hooks[event]
        for entry in group["hooks"]
        if GUARD_SCRIPT in entry["command"]
    ]
    settings: Naming = json.loads(
        artifacts[plugin / "hooks" / "session_naming.json"].content
    )

    assert "exit 2" not in entry["command"]
    assert entry["timeout"] == timeout
    assert artifacts[plugin / "hooks" / "scripts" / GUARD_SCRIPT].executable
    assert artifacts[plugin / "hooks" / "runtime" / RUNTIME_ENTRY].content == host
    assert settings["model"] == model
    assert settings["effort"] == "low"


@pytest.mark.parametrize("declined", ["peer_policy", "session_naming"])
def test_no_roster_or_no_naming_registers_nothing(declined: str) -> None:
    """A name is what a roster addresses, so either absence carries nothing."""
    source: HookSet = declared_hook_set().model_copy(update={declined: None})
    hook = naming_hook(
        rendered(".claude"),
        "CLAUDE_PLUGIN_ROOT",
        source,
        CLAUDE_PROMPT_EVENT,
        CLAUDE_SESSION_NAMING,
        "lup.providers.claude.assets.session_naming",
        lambda _tier: "sonnet",
        {"low": "low"},
        waits=True,
    )

    assert hook.registered == {}
    assert hook.artifacts == []


@pytest.mark.parametrize(
    ("target", "tree", "event"),
    [pytest.param(claude_target, ".claude", CLAUDE_PROMPT_EVENT, id="claude")],
)
def test_claude_names_the_session_while_its_first_prompt_waits(
    target: Callable[[Path], NativeHarnessComposition],
    tree: str,
    event: str,
    tmp_path: Path,
) -> None:
    """The title comes back in the answer; the roster answers to the same name."""
    session = Session(target, tree, event, tmp_path, "session-naming-hook")

    first = session.prompted("Name each session after its work", title="dev")

    assert json.loads(first) == {
        "hookSpecificOutput": {
            "hookEventName": event,
            "sessionTitle": "session-naming-hook",
        }
    }
    assert session.called() == "session-naming-hook"
    [ask] = session.asked()
    assert ask.get("prompt") == "Name each session after its work"
    assert ask.get("arguments", [])[:8] == [
        "--safe-mode",
        "-p",
        "--model",
        "sonnet",
        "--effort",
        "low",
        "--no-session-persistence",
        "--tools",
    ]
    assert session.prompted("And test it", title="session-naming-hook") == ""
    assert len(session.asked()) == 1


@pytest.mark.parametrize(
    ("target", "tree", "event"),
    [pytest.param(claude_target, ".claude", CLAUDE_PROMPT_EVENT, id="claude")],
)
def test_claude_carries_a_roster_rename_to_the_title_once(
    target: Callable[[Path], NativeHarnessComposition],
    tree: str,
    event: str,
    tmp_path: Path,
) -> None:
    """A peer's rename reaches the chrome at the next prompt, and only then."""
    session = Session(target, tree, event, tmp_path, "session-naming-hook")
    session.prompted("Name each session after its work", title="dev")
    session.peers.rename(session.member, "chosen")

    pushed = session.prompted("Carry on", title="session-naming-hook")

    assert json.loads(pushed)["hookSpecificOutput"]["sessionTitle"] == "chosen"
    assert session.prompted("Carry on", title="somebody-renamed-it") == ""
    assert len(session.asked()) == 1


@pytest.mark.parametrize(
    ("target", "tree", "event"),
    [pytest.param(claude_target, ".claude", CLAUDE_PROMPT_EVENT, id="claude")],
)
def test_claude_leaves_a_title_somebody_set_and_asks_no_more_than_declared(
    target: Callable[[Path], NativeHarnessComposition],
    tree: str,
    event: str,
    tmp_path: Path,
) -> None:
    """A greeting names nothing and is asked again; a chosen title is never asked over."""
    session = Session(target, tree, event, tmp_path, None)

    assert session.prompted("hi", title="somebody-chose-this") == ""
    assert session.asked() == []
    assert [session.prompted("hi", title="dev") for _ in range(4)] == [""] * 4
    assert len(session.asked()) == 3
    assert session.called() == "dev"


@pytest.mark.parametrize(
    ("target", "tree", "event"),
    [pytest.param(codex_target, ".codex", CODEX_PROMPT_EVENT, id="codex")],
)
def test_codex_names_the_session_and_its_thread_without_holding_the_prompt(
    target: Callable[[Path], NativeHarnessComposition],
    tree: str,
    event: str,
    tmp_path: Path,
) -> None:
    """The hook answers nothing and returns; a process of its own names roster and thread."""
    session = Session(target, tree, event, tmp_path, "session-naming-hook")

    assert session.prompted("Name each session after its work") == ""
    ask, named = session.concluded(2)

    assert ask.get("prompt") == "Name each session after its work"
    assert ask.get("arguments", [])[:2] == ["exec", "--ephemeral"]
    assert "--disable" in ask.get("arguments", [])
    assert named == Asked(
        named=Named(threadId="root-session", name="session-naming-hook")
    )
    assert session.called() == "session-naming-hook"

    session.peers.rename(session.member, "chosen")
    assert session.prompted("Carry on") == ""
    assert session.concluded(3)[2:] == [
        Asked(named=Named(threadId="root-session", name="chosen"))
    ]
