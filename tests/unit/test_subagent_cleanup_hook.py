"""A subagent's report waits for the background work it started, as measured.

The fixtures under ``fixtures/subagent_cleanup/`` are recordings, not
inventions: every hook payload Claude Code 2.1.278 handed a probe hook in a
throwaway project — once interactively with permissions skipped, once in
print mode from inside a sandboxed session — and the subagent's own
transcript from the print-mode run, cut to its ``user`` and ``assistant``
lines. The interactive run's transcript sat under a home directory the
recording session could not read, so its stop is judged against the
print-mode transcript, whose armed command is the same.

What is asserted is the rendered guard run as the runtime runs it, over
those payloads: the first stop is refused naming the monitor and not the
subagent's own entry, the stop that follows the refusal goes through, a task
the subagent did not arm is not its to stop, and the start event carries the
one sentence. The registration is asserted per event, and a project that
declined carries nothing.

``payloads-codex.jsonl`` is the same kind of recording from Codex 0.155.1,
where the two halves of the leak came apart: the work outlives the report and
its output resumes nobody. So that tree is asserted to register the start
alone, and its sentence to promise no refusal — the negative is asserted
rather than left to whoever reads the rendered text, because a promise that
never comes true is what teaches a subagent to discount the next one.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import NotRequired, TypedDict

import pytest
import sh

from lup.devtools.harness.generate import NativeHarnessComposition
from lup.harness.models import Artifact
from lup.policy.bundle import policy_kernel_modules
from lup.providers.codex.harness import CODEX_SUBAGENT_START_EVENT
from lup.providers.claude.harness import (
    CLAUDE_SUBAGENT_START_EVENT,
    CLAUDE_SUBAGENT_STOP_EVENT,
)
from lup.providers.roster_prompt import store_modules
from lup.providers.subagent_cleanup import GUARD_SCRIPT, RUNTIME_ENTRY, cleanup_hooks
from lup_template.harness.catalog import declared_hook_set
from lup_template.harness.composition import claude_target, codex_target


class ListedTask(TypedDict, total=False):
    """One entry of a recorded task list, as far as the tests rewrite it."""

    id: str
    type: str
    command: str


class Payload(TypedDict):
    """One recorded hook payload, as far as the tests read it."""

    hook_event_name: str
    agent_transcript_path: NotRequired[str]
    background_tasks: NotRequired[list[ListedTask]]


class Recorded(TypedDict):
    """One line of a recording: when it fired, and what the hook was handed."""

    at: float
    payload: Payload


RECORDINGS = pytest.mark.parametrize(
    ("recording", "task_id", "own_id"),
    [
        pytest.param(
            "payloads-claude-interactive.jsonl",
            "bextuezys",
            "a89db2100fd8133cd",
            id="interactive",
        ),
        pytest.param(
            "payloads-claude-print.jsonl", "bf0g39eun", "a320c99e18b0ff176", id="print"
        ),
    ],
)


CLAUDE_PLUGIN = Path(".claude/plugins/lup")
CODEX_PLUGIN = Path(".codex/plugins/lup")
"""Where each runtime's plugin sits, which is what picks the tree to read."""


def fixtures() -> Path:
    """Where the recordings sit, beside this test."""
    return Path(__file__).parent / "fixtures" / "subagent_cleanup"


def recorded(recording: str, event: str) -> list[Payload]:
    """Every payload of one event in one recording, in the order it fired."""
    lines: list[Recorded] = [
        json.loads(line)
        for line in (fixtures() / recording).read_text("utf-8").splitlines()
    ]
    return [
        entry["payload"]
        for entry in lines
        if entry["payload"]["hook_event_name"] == event
    ]


def shipped(
    target: Callable[[Path], NativeHarnessComposition],
) -> dict[Path, Artifact]:
    """Every artifact the plugin carries, by the path it carries it at."""
    return {
        artifact.path: artifact
        for artifact in target(Path.cwd()).recipe.desired.artifacts
    }


def laid_out(
    root: Path,
    target: Callable[[Path], NativeHarnessComposition] = claude_target,
    plugin: Path = CLAUDE_PLUGIN,
) -> Path:
    """The guard, the host half, and the packages it imports, as a plugin lays them out."""
    artifacts = shipped(target)
    carried = [
        (
            Path("hooks") / "scripts" / GUARD_SCRIPT,
            artifacts[plugin / "hooks" / "scripts" / GUARD_SCRIPT].content,
        ),
        (
            Path("hooks") / "runtime" / RUNTIME_ENTRY,
            artifacts[plugin / "hooks" / "runtime" / RUNTIME_ENTRY].content,
        ),
        # The entry reads this project's own gate spellings out of it, the way
        # the compiled dispatcher beside it reads every other declared value.
        (
            Path("hooks") / "runtime" / "policy_data.py",
            artifacts[plugin / "hooks" / "runtime" / "policy_data.py"].content,
        ),
        *[
            (Path("hooks") / "runtime" / "kernel" / module.name, module.source)
            for module in policy_kernel_modules()
        ],
        *[
            (Path("hooks") / "runtime" / module.path, module.content)
            for module in store_modules()
        ],
    ]
    for relative, content in carried:
        landed = root / relative
        landed.parent.mkdir(parents=True, exist_ok=True)
        landed.write_text(content)
    return root / "hooks" / "scripts" / GUARD_SCRIPT


def judged(guard: Path, payload: Payload) -> str:
    """The guard's stdout for one payload, run as the runtime runs it."""
    return str(sh.sh(str(guard), _in=json.dumps(payload)))


def at_stop(recording: str, index: int) -> Payload:
    """One recorded stop, its transcript pointed at the fixture copy."""
    stop = recorded(recording, CLAUDE_SUBAGENT_STOP_EVENT)[index]
    stop["agent_transcript_path"] = str(fixtures() / "transcript-claude-print.jsonl")
    return stop


@RECORDINGS
def test_the_first_stop_refuses_the_report_naming_the_task_it_armed(
    recording: str, task_id: str, own_id: str, tmp_path: Path
) -> None:
    """The monitor is named, the subagent's own entry is not, and the ending call is."""
    guard = laid_out(tmp_path / "plugin")

    answer = json.loads(judged(guard, at_stop(recording, 0)))

    assert answer["decision"] == "block"
    assert task_id in answer["reason"]
    assert own_id not in answer["reason"]
    assert "TaskStop" in answer["reason"]


@RECORDINGS
def test_the_stop_that_follows_a_refusal_goes_through(
    recording: str, task_id: str, own_id: str, tmp_path: Path
) -> None:
    """Once: the runtime flags the second pass, and the task is gone from it anyway."""
    guard = laid_out(tmp_path / "plugin")

    assert judged(guard, at_stop(recording, 1)) == ""


def test_a_task_the_subagent_did_not_arm_is_not_its_to_stop(tmp_path: Path) -> None:
    """A watch the parent armed is in the same list and must not be named."""
    guard = laid_out(tmp_path / "plugin")
    stop = at_stop("payloads-claude-print.jsonl", 0)
    for task in stop.get("background_tasks", []):
        task["command"] = "tail -f somebody-elses.log"

    assert judged(guard, stop) == ""


def test_the_start_event_tells_the_subagent_what_is_its_to_stop(
    tmp_path: Path,
) -> None:
    """One sentence as context, naming the call that ends a task, refusing nothing."""
    guard = laid_out(tmp_path / "plugin")
    [start] = recorded("payloads-claude-print.jsonl", CLAUDE_SUBAGENT_START_EVENT)

    answer = json.loads(judged(guard, start))

    pushed = answer["hookSpecificOutput"]
    assert pushed["hookEventName"] == CLAUDE_SUBAGENT_START_EVENT
    assert "TaskStop" in pushed["additionalContext"]
    assert "decision" not in answer


def test_the_entry_reaches_the_kernel_under_an_isolated_interpreter(
    tmp_path: Path,
) -> None:
    """The host half names its own search path, so no interpreter flag takes it away."""
    laid_out(tmp_path / "plugin")

    isolated = str(
        sh.Command("python3")(
            "-I",
            "-S",
            str(tmp_path / "plugin" / "hooks" / "runtime" / RUNTIME_ENTRY),
            _in=json.dumps(at_stop("payloads-claude-print.jsonl", 0)),
        )
    )

    assert json.loads(isolated)["decision"] == "block"


@pytest.mark.parametrize(
    "event", [CLAUDE_SUBAGENT_START_EVENT, CLAUDE_SUBAGENT_STOP_EVENT]
)
def test_each_subagent_event_registers_the_fold_and_refuses_nothing(
    event: str,
) -> None:
    """Under its own event, with no matcher, and with no `exit 2` beside it."""
    artifacts = shipped(claude_target)
    plugin = CLAUDE_PLUGIN
    hooks = json.loads(artifacts[plugin / "hooks" / "hooks.json"].content)["hooks"]

    [group] = [
        group
        for group in hooks[event]
        if any(GUARD_SCRIPT in entry["command"] for entry in group["hooks"])
    ]
    [entry] = group["hooks"]

    assert "matcher" not in group
    assert "exit 2" not in entry["command"]
    assert artifacts[plugin / "hooks" / "scripts" / GUARD_SCRIPT].executable
    assert plugin / "hooks" / "runtime" / RUNTIME_ENTRY in artifacts


def test_the_other_runtime_tells_a_subagent_what_it_opened_is_its_to_close(
    tmp_path: Path,
) -> None:
    """Over its own recorded start, naming the call that ends what a session runs."""
    guard = laid_out(tmp_path / "plugin", codex_target, CODEX_PLUGIN)
    [start] = recorded("payloads-codex.jsonl", CODEX_SUBAGENT_START_EVENT)

    answer = json.loads(judged(guard, start))

    pushed = answer["hookSpecificOutput"]
    assert pushed["hookEventName"] == CODEX_SUBAGENT_START_EVENT
    assert "write_stdin" in pushed["additionalContext"]
    assert "decision" not in answer


def test_the_sentence_promises_no_refusal_where_none_is_registered(
    tmp_path: Path,
) -> None:
    """Measured: leftovers there resume nobody, so nothing refuses a report there.

    A sentence promising a refusal that never comes is what teaches a
    subagent to discount the next one, so the negative is asserted rather
    than left to the reader of the rendered text.
    """
    guard = laid_out(tmp_path / "plugin", codex_target, CODEX_PLUGIN)
    [start] = recorded("payloads-codex.jsonl", CODEX_SUBAGENT_START_EVENT)

    said = json.loads(judged(guard, start))["hookSpecificOutput"]["additionalContext"]

    assert "refused" not in said
    assert "resumes you" not in said


def test_the_other_runtime_registers_the_start_and_no_stop() -> None:
    """The whole difference between the two trees, read off the registration."""
    artifacts = shipped(codex_target)
    hooks = json.loads(artifacts[CODEX_PLUGIN / "hooks" / "hooks.json"].content)[
        "hooks"
    ]

    folded = {
        event: groups
        for event, groups in hooks.items()
        if any(
            GUARD_SCRIPT in entry["command"]
            for group in groups
            for entry in group["hooks"]
        )
    }

    assert list(folded) == [CODEX_SUBAGENT_START_EVENT]


def test_a_runtime_that_resumes_nobody_takes_the_sentence_alone() -> None:
    """No stop event is how a host half says its leftovers wake no one."""
    quiet = cleanup_hooks(
        Path("plugin"),
        "PLUGIN_ROOT",
        declared_hook_set(),
        "print()",
        "nowhere",
        CODEX_SUBAGENT_START_EVENT,
        None,
    )

    assert list(quiet.registered) == [CODEX_SUBAGENT_START_EVENT]


def test_a_project_that_declined_registers_nothing_and_carries_nothing() -> None:
    """The declaration is the hook set's own field, so None declines both events."""
    declined = declared_hook_set().model_copy(update={"subagent_cleanup": None})

    quiet = cleanup_hooks(
        Path("plugin"),
        "PLUGIN_ROOT",
        declined,
        "print()",
        "nowhere",
        CLAUDE_SUBAGENT_START_EVENT,
        CLAUDE_SUBAGENT_STOP_EVENT,
    )

    assert quiet.registered == {}
    assert quiet.artifacts == []


def test_the_start_event_tells_the_subagent_what_it_verifies(tmp_path: Path) -> None:
    """The other half of what is true at that moment, and the costlier half.

    A delegated agent inherits the repository's guidance and reads, correctly,
    that the full gate is what has to be green — and nothing there says it is
    not the one to run it. Several agents dispatched into one working tree
    each start the whole suite over a tree the others are still editing, so
    the answer is about a state that never existed and a failure in it cannot
    be attributed to whoever caused it.

    Said at the start rather than refused at the call, because a refusal lands
    after the agent has planned around running it.
    """
    guard = laid_out(tmp_path / "plugin")
    [start] = recorded("payloads-claude-print.jsonl", CLAUDE_SUBAGENT_START_EVENT)

    said = json.loads(judged(guard, start))["hookSpecificOutput"]["additionalContext"]

    assert "--changed" in said
    assert "dev check" in said
    # Both halves arrive together or a subagent reads neither.
    assert "TaskStop" in said
