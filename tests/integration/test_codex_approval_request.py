"""Whether a Codex session can be *asked* rather than only refused.

This is the last structural difference between the two runtimes' review
experience, and it is one unmeasured question.

A policy verdict of `ask` has nowhere to go on Codex's `PreToolUse`: the
compiled dispatcher runs as a command hook, and that boundary carries no
portable ask effect — so `queued_review` denies the call and sends the
operator to another terminal. Issue #180 is that dead end reported from a real
session, where an explicitly authorized whole-file rewrite could not be
installed because "nobody who could approve it is reachable from this
session".

Codex has a second hook event that is meant to be the interactive channel.
`docs/native-capabilities.md` already records that it never fires under
`codex exec`, which reports `approval: never` — so what is open is the
*app-server* path, the one an IDE and every Lup Codex session drive. The
generated dispatcher is already written for it: on `PermissionRequest` an
`allow` becomes a native allow decision, and an `ask` **returns saying
nothing**, which is the dispatcher deliberately declining to decide so the
runtime's own approval flow can proceed. Whether anything is listening is what
has never been measured.

Two arms, and neither alone settles it:

* The first asks whether the event fires here at all. A policy-allowed command
  is put to a live session and the plugin's own evidence journal is read for a
  `PermissionRequest` record. The journal rather than the behaviour, because a
  command that simply ran proves nothing about which hook let it.

* The second asks the question that matters. A command the policy classifies
  `ask` is put to the same session, the dispatcher declines to decide, and the
  arm observes whether an approval request reaches the client that opened the
  thread. If one does, a Codex session can be asked, #180 stops being a dead
  end, and `dev questions` becomes a fallback rather than the only surface. If
  none does, the queue is permanently that surface and its diff rendering is
  load-bearing.

Neither arm can run without a Codex login, which a contained session does not
reach — a nested `codex exec` there answers 401, the credential sitting
outside what a session is granted. So they carry the integration marker this
repository deselects by default, exactly as `test_codex_hook_firing.py` does,
and the run that settles them is the operator's to start from a host terminal
where Codex is signed in:

    uv run pytest tests/integration/test_codex_approval_request.py \
        -m integration -v

Deselected rather than failed, which is what keeps an unmeasured question out
of everybody else's gate. Until that run happens both arms are built and
neither is evidence.
"""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from lup.policy.hooks import (
    LupHookInput,
    LupHookMatcher,
    LupHookOutput,
    LupHooksConfig,
    deny_hook,
)
from lup.providers.codex.home import CodexWorktreeHomeStore
from lup.providers.codex.runtime import CodexSessionConfig, create_codex
from lup.sessions.client import Client
from lup.sessions.events import turn_request
from lup.workspace.paths import find_project_root

pytestmark = pytest.mark.integration

PROBE_MODEL = "gpt-5.5"

ALLOWED = "echo lup-approval-control"
"""Classified `allow`, so the dispatcher answers with a native allow decision."""

ASKED = "chmod +x tmp/lup-approval-probe.sh"
"""Classified `ask` — "changing permissions requires approval".

Inert by construction: the file it names is never created, so the worst a
granted approval buys is a `chmod` that fails on a missing path. A probe whose
asked-about command mattered if it ran would make a positive result expensive,
and the answer is wanted either way.
"""

INSTRUCTIONS = (
    "You are a shell assistant. Run exactly the command you are given with "
    "the shell tool, once. Never work around a refusal and never rewrite the "
    "command. Then report what happened by calling the submission tool — "
    "always finish by submitting, whether the command ran, was refused, or "
    "was left waiting on an approval nobody answered."
)


class ShellAttempt(BaseModel):
    """What one session observed when it tried to run one command."""

    ran: bool = Field(description="True if the command executed and produced output")
    output: str = Field(description="What was printed, the refusal, or the wait")


class ApprovalWatch(BaseModel):
    """Every approval request one turn caused the server to send its client.

    Recorded rather than judged. What this arm measures is whether a request
    *arrives*, and a watcher that decided on its merits would be measuring its
    own decision instead — so every arrival is noted and every one is refused,
    which leaves the session exactly where a denial leaves it and runs nothing.
    """

    tools: list[str] = []

    def hooks(self) -> LupHooksConfig:
        """The session hooks an arriving approval is routed through.

        `resolve_approval` answers an app-server approval request from the
        session's own declared hooks, so registering one is how a client
        observes that a request reached it at all. A session declaring none
        declines every request — which is the safe answer, and also an answer
        indistinguishable from nothing having arrived.
        """

        async def note(event: LupHookInput) -> LupHookOutput:
            self.tools.append(event.tool_name)
            return deny_hook("the approval probe records and grants nothing")

        return LupHooksConfig(pre_tool_use=[LupHookMatcher(hook=note, tag="probe")])

    def arrived(self) -> bool:
        """Whether anything at all was routed here during the turn."""
        return bool(self.tools)


def probe_session(cwd: Path, watch: ApprovalWatch) -> CodexSessionConfig:
    """A session whose approvals are live, which is what makes the arm possible.

    ``approval_policy`` is `on-request` rather than the `never` the hook-firing
    probe uses, and that is the whole difference between the two files: `never`
    is the setting under which `PermissionRequest` is already known not to
    fire, so a probe that kept it would re-measure the answer we have.

    The sandbox stays at `workspace-write` rather than being opened, because an
    approval request is what a boundary *produces*: a session granted full
    access has nothing left to ask about.
    """
    return CodexSessionConfig(
        model=PROBE_MODEL,
        developer_instructions=INSTRUCTIONS,
        cwd=cwd,
        sandbox="workspace-write",
        approval_policy="on-request",
        hooks=watch.hooks(),
    )


def hook_records(cwd: Path) -> list[dict[str, str]]:
    """Every hook invocation this checkout's plugin has journalled.

    Read from the scoped home's plugin data directory, which is where the
    generated dispatcher writes `record_hook_evidence` — metadata only, so
    nothing here carries a command or a patch.
    """
    journal = CodexWorktreeHomeStore().home_for(cwd) / "hook-events.jsonl"
    if not journal.is_file():
        return []
    return [
        json.loads(line)
        for line in journal.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def fired(cwd: Path, event: str) -> list[dict[str, str]]:
    """Which journalled invocations were of one event."""
    return [record for record in hook_records(cwd) if record.get("event_name") == event]


async def ask(factory: Client, command: str) -> ShellAttempt:
    """Put one command to one already-configured session."""
    async with factory.open() as handle:
        accepted = await handle.session.start(
            turn_request(
                f"Run this command with the shell tool: {command}\n"
                "Then call the submission tool with `ran` set to whether it "
                "executed, and `output` set to what it printed, the refusal "
                "you were given, or the approval you were left waiting on.",
                ShellAttempt,
            )
        )
        return (await accepted.turn.result()).output


async def test_the_probe_prompt_reaches_the_shell() -> None:
    """The control. Without it, a refusal and a reluctance look the same."""
    root = find_project_root()

    observed = await ask(create_codex(probe_session(root, ApprovalWatch())), ALLOWED)

    assert observed.ran, observed.output
    assert "lup-approval-control" in observed.output


async def test_whether_permission_request_fires_in_an_app_server_session() -> None:
    """Arm one: does the interactive hook event reach the plugin here at all?

    The journal rather than the command's fate, because a command that ran
    proves nothing about which hook let it run: `PreToolUse` allowing it and
    `PermissionRequest` never firing looks exactly like both firing.
    """
    root = find_project_root()
    before = len(fired(root, "PermissionRequest"))

    await ask(create_codex(probe_session(root, ApprovalWatch())), ALLOWED)

    assert len(fired(root, "PermissionRequest")) > before, (
        "No PermissionRequest reached the plugin's dispatcher during a live "
        "app-server turn, so the interactive half of the boundary does not "
        "fire here either — and a Codex `ask` can only ever be spent as a "
        "denial. `dev questions` is then the permanent review surface."
    )


async def test_whether_a_declined_decision_reaches_the_client_as_an_approval() -> None:
    """Arm two, and the one that decides whether #180 has a way out.

    On `ask` the generated dispatcher returns saying nothing, which is it
    declining to decide so the runtime's own approval flow can proceed. This
    asks whether that flow then reaches whoever opened the thread.

    A failure here is not a defect in Lup. It is the finding that the
    dispatcher's deliberate silence has nobody listening on the other side,
    which is worth recording as a vendor surface gap rather than worked
    around — the fail-closed denial is the correct behaviour under it.
    """
    root = find_project_root()
    watch = ApprovalWatch()

    observed = await ask(create_codex(probe_session(root, watch)), ASKED)

    assert not observed.ran, (
        "A command this project's policy classifies `ask` ran without any "
        f"approval being recorded: {observed.output}"
    )
    assert watch.arrived(), (
        "The dispatcher declined to decide and no approval request reached "
        "the client, so nothing was listening: a Codex session cannot be "
        "asked, only refused. Record this against the app-server's approval "
        f"surface rather than treating it as a Lup defect. Saw: {watch.tools}"
    )
