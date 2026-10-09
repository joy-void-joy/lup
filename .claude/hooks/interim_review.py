# /// script
# requires-python = ">=3.14"
# dependencies = ["pydantic>=2.12", "pydantic-settings>=2.11", "sh>=2"]
# ///
"""Queue what needs the operator in the first lup's review dashboard: every prompt, and writes that show design.

An interim carrier for the bridge, until lup's own review flow and dashboard land
(`docs/judging-writes.md`); then this file and its hooks go. Claude Code runs it
for these events, named by the payload's `hook_event_name`:
- `PermissionRequest`, whenever Claude Code is about to show a permission prompt,
  for any tool, the judge's asks included. The prompt is queued for review
  instead, saying what Claude Code asks permission for; nothing it asks is
  allowed without the operator, but for a Write or Edit landing only in
  scratch: `tmp/` in a worktree of the session's repository, or the session's
  own scratchpad. A tool whose prompt is a question rather than a permission
  (`AskUserQuestion`) stays in the terminal: the dashboard can only approve or
  decline.
- `PostToolBatch`, after each batch of tool calls, to pass on what the operator
  wrote when approving a prompt (below).
- `PreToolUse`, before each Write or Edit, only in a session started before the
  judge (`lup-dev hook claude`) took this event over in `.claude/settings.json`:
  such a session still sends it here, and a hook that stopped answering would
  block every write there. It goes once none runs. It judges by the agreed table
  (*What each change gets*): tests, scratch, docs, data and ordinary production
  edits are allowed, and these are queued for the operator's review:
  - a new production file, or a Write over a whole existing one;
  - a protected path: manifests, lockfiles, git's and the runtimes' own
    directories, CI, editor configs, secrets, the project declaration, lup's catalog;
  - one of the operator's documents, `DESIGN.md` and `AGENTS.md` at a worktree's root;
  - an edit that adds a `# lup: ignore` suppression to a Python file.
  A write outside the session's repository isn't judged here: Claude Code's own
  mode decides it, and a prompt it shows is queued like any other.

A call that needs review is parked in the first lup's queue and refused at once,
saying how to hear the answer, so the agent carries on with other work while the
operator reviews at their own pace. `wait <id>`, a subcommand of this script,
polls until the review is answered and prints the answer, so a run in the
background wakes the agent; it never carries out the call. Repeating the exact
call then reaches the same review through its fingerprint:
- approved: the call goes through. For a write, the operator's note and line
  comments reach the agent's context at once. A PermissionRequest's answer can't
  carry context, so they wait under `.lup/approval-notes/` and reach the agent
  when the batch holding the call ends. An approval covers that one call: it
  never adds a permission rule.
- declined: refused, with the note and comments; a refused Write or Edit leaves
  the agent's version under `.lup/saved/<review>/`.
- still waiting: refused again, with the same message.

The review is parked and read back by the first lup's own host half
(`policy/assets/host.py`), which uses only the standard library, so the dashboard
sees exactly the records it writes itself. Each queued call is also kept under
`.lup/interim-queue/` in the session's checkout, which is how `wait` finds it.
Serve the dashboard with:

    uv run --directory <lup-legacy checkout> lup-devtools dashboard serve --root <this checkout>

The first lup's dashboard expires a review an hour after it's parked when its
requester isn't on the first lup's roster, which these sessions never are. `wait`
parks an expired review again under a new id and waits on that one, so the queue
still holds it; a repeat of the call reaches the newest.
"""

import importlib.util
import io
import json
import shutil
import sys
import time
import tokenize
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Literal

import sh
from pydantic import BaseModel, JsonValue, RootModel, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings, CliApp, CliPositionalArg, CliSubCommand


class Settings(BaseSettings, env_prefix="LUP_INTERIM_REVIEW_"):
    """What this review assumes about the machine, the first lup and this repository."""

    legacy_checkout: Path = Path("lup-legacy.git/tree/dev")
    """The first lup's checkout, relative to the directory holding `lup.git`."""
    production: list[str] = ["packages/**/src/**"]
    """Where production code lives, as patterns relative to the worktree: the source trees under the packages."""
    protected: list[str] = [
        "**/pyproject.toml",
        "**/uv.lock",
        "**/package.json",
        "**/bun.lock",
        ".github/**",
        ".git/**",
        ".githooks/**",
        ".husky/**",
        ".pre-commit-config.yaml",
        ".vscode/**",
        ".devcontainer/**",
        ".claude/**",
        ".codex/**",
        "**/sync.json",
        "**/sync.json.local",
        "**/.env*",
        "**/.gitignore",
        "lup_project.py",
        "**/lup_dev/catalog/**",
    ]
    """Paths every write to asks, as patterns relative to the worktree.

    The defaults in `lup_dev/catalog/paths.py`, and what lup's declaration adds:
    - manifests and lockfiles, which choose what runs;
    - what runs outside the agent's own calls: CI, git's own directory and
      hooks, pre-commit, editor and container configs, the runtimes' settings and hooks;
    - what widens a later launch, `sync.json` and `sync.json.local`;
    - secrets, `.env*`;
    - `.gitignore`, which decides what review can see;
    - the project declaration, `lup_project.py`;
    - `lup_dev/catalog/`, the data that sets lup's policy (its rules, its path
      roles), which the operator reviews before it changes.
    """
    operator_documents: list[str] = ["DESIGN.md", "AGENTS.md"]
    """The operator's documents, as patterns relative to the worktree.

    Changing one is a design decision, so every write to one asks.
    """
    scratch: list[str] = ["tmp/**"]
    """Scratch in a worktree, as patterns relative to it: gitignored, so nothing in it lands."""
    scratchpad: str = "/tmp/claude-*/*/{session}/scratchpad/**"
    """Claude Code's scratchpad for one session, as a pattern with the session's id in place of `{session}`."""
    terminal_tools: list[str] = ["AskUserQuestion"]
    """Tools whose prompt asks the operator a question rather than for permission.

    The dashboard can only approve or decline, so their prompts stay in the terminal.
    """
    python_suffixes: list[str] = [".py", ".pyi"]
    answers_variable: str = "LUP_REVIEW_ANSWERS"
    """The variable a first-lup launch names the answers store with; unset here, so the host's default applies."""
    poll: timedelta = timedelta(seconds=2)
    """How often `wait` looks for the operator's answer."""
    notify: bool = True
    """Whether a review newly queued raises a desktop notice through `notify-send`, where it's installed."""


class ToolInput(BaseModel):
    """A Write or Edit call's input, as Claude Code sends it."""

    file_path: Path
    content: str | None = None
    old_string: str | None = None
    new_string: str | None = None
    replace_all: bool | None = None


class CommandInput(BaseModel):
    """The part of a Bash call's input a review shows."""

    command: str
    description: str = ""


class PathInput(BaseModel):
    """The part of a file tool's input a review shows."""

    file_path: Path


class PlanInput(BaseModel):
    """The part of an ExitPlanMode call's input a review shows: the plan Claude Code injects into it."""

    plan: str = ""


class WritePayload(BaseModel):
    """What Claude Code sends a PreToolUse hook for a Write or Edit on stdin."""

    session_id: str
    cwd: Path
    tool_name: str
    tool_input: ToolInput
    agent_id: str = ""
    """The subagent making the call, blank for the session's own conversation."""


class PermissionPayload(BaseModel):
    """What Claude Code sends a PermissionRequest hook on stdin: the call, of any tool, it would prompt for."""

    session_id: str
    cwd: Path
    tool_name: str
    tool_input: dict[str, JsonValue]
    agent_id: str = ""
    """The subagent making the call, blank for the session's own conversation."""


class BatchPayload(BaseModel):
    """The part of what Claude Code sends a PostToolBatch hook that says whose batch of calls just ended."""

    session_id: str
    cwd: Path
    agent_id: str = ""
    """The subagent whose batch it was, blank for the session's own conversation."""


class Review(BaseModel, frozen=True):
    """Why a call waits for the operator, in the first lup's terms."""

    rule: str
    reason: str
    purpose: Literal["quality_review", "policy_override"]


class Verdict(BaseModel, frozen=True):
    """What this hook makes of one write: a review to queue, if any, and anything the agent should hear."""

    review: Review | None = None
    note: str = ""


class Preconditions(RootModel[dict[Path, str | None]]):
    """Each file the call changes, with its content before the call, or none where it's new."""


class Draft(BaseModel, frozen=True):
    """The agent's version of a file, kept where it can revise it when the call writing it is refused."""

    home: Path
    """The checkout whose `.lup/saved/` keeps it."""
    relative: Path
    content: str

    def save(self, review_id: str) -> Path:
        """Keep this version under the review that refused it, and say where."""
        target = self.home / ".lup/saved" / review_id / self.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.content)
        return target


class Change(BaseModel, frozen=True):
    """What a Write or Edit does to one file: its content before, none where it's new, and after."""

    file: Path
    before: str | None
    after: str

    def preconditions(self) -> Preconditions:
        """The file as the review binds it: its content before the call."""
        return Preconditions({self.file: self.before})

    def draft(self, home: Path) -> Draft:
        """The content after, kept in `home`: by its path in that checkout, or its whole path where it lies outside."""
        relative = (
            self.file.relative_to(home) if self.file.is_relative_to(home) else self.file.relative_to(self.file.anchor)
        )
        return Draft(home=home, relative=relative, content=self.after)


def wait_command(review_id: str, checkout: Path) -> str:
    """The command that waits for one queued review's answer, as the agent runs it from the session's checkout."""
    script = Path(__file__).resolve()
    shown = script.relative_to(checkout) if script.is_relative_to(checkout) else script
    return f"uv run --script {shown} wait {review_id}"


def queue_file(checkout: Path, review_id: str) -> Path:
    """Where a queued call is kept under its review's id, in the session's checkout, for `wait` to find."""
    return checkout / ".lup/interim-queue" / f"{review_id}.json"


class Request(BaseModel, frozen=True):
    """One call to put before the operator, as either event hands it over."""

    repository: Path
    """The repository's shared git directory; the first lup's checkout sits beside the directory holding it."""
    root: Path
    """Where the call runs, which the review records and binds."""
    checkout: Path
    """The session's checkout, where the queued call is kept and its wait command runs."""
    session: str
    agent: str
    """The subagent that asked, blank for the session's own conversation."""
    tool: str
    arguments: str
    """The call's input as JSON, as the review shows and binds it."""
    preconditions: Preconditions
    review: Review
    draft: Draft | None = None
    """What the call would write, kept for the agent when it's refused; none where it writes no file."""

    def kept(self, review_id: str) -> str:
        """Save the agent's version once this call is refused, and say where and what it can do with it.

        Nothing where the call writes no file.
        """
        if self.draft is None:
            return ""
        kept = self.draft.save(review_id)
        return f"Your version is saved at {kept}. Revise it there and write it back, which asks again."

    def waiting(self, review_id: str) -> str:
        """What the agent hears while the call waits for review: where it is, how to hear the answer, and what then."""
        return (
            f"Queued for the operator's review in the dashboard ({review_id}): {self.review.reason}. "
            "Carry on with other work, or end your turn. "
            f"To hear when it's answered, run `{wait_command(review_id, self.checkout)}` in the background; "
            "once it's approved, repeat this exact call."
        )


class ParkedState(BaseModel, frozen=True):
    """What the first lup's host half answers for one parked call."""

    state: Literal["pending", "approved", "rejected", "unavailable"]
    id: str
    reason: str


class LineComment(BaseModel, frozen=True):
    """One comment the operator anchored to lines of a file the review showed."""

    path: Path
    start: int
    end: int
    side: Literal["before", "after"] = "after"
    note: str

    def render(self) -> str:
        """The comment as the agent reads it: where it points, then what it says."""
        lines = str(self.start) if self.start == self.end else f"{self.start}-{self.end}"
        return f"{self.path}:{lines} ({self.side}): {self.note}"


class Said(BaseModel, frozen=True):
    """What the operator wrote on a review: a note, and comments on lines."""

    note: str = ""
    comments: list[LineComment] = []


class Answer(Said, frozen=True):
    """The operator's decision on a review, with what they said about it."""

    approved: bool


class RecordedAnswer(BaseModel, frozen=True):
    """An answer as the host keeps it, naming the review it settles."""

    question: str
    answer: Answer

    def words(self) -> Said:
        """What the operator wrote with the decision."""
        return self.answer

    def decision(self) -> Answer | None:
        """The operator's decision."""
        return self.answer


class RecordedRemark(BaseModel, frozen=True):
    """A remark the operator sent without deciding, as the host keeps it beside the answers."""

    question: str
    remark: Said

    def words(self) -> Said:
        """What the operator wrote."""
        return self.remark

    def decision(self) -> Answer | None:
        """None: a remark decides nothing."""
        return None


class RelayEntry(BaseModel, frozen=True):
    """A review as the first lup's relay keeps it: the part a wait reads."""

    id: str
    fingerprint: str
    """The digest of the call it reviews, which a repeat of the call hashes to again."""
    state: str


class Outcome(BaseModel, frozen=True):
    """What a call put before the operator comes to, in the words the agent hears, before either event spells it."""

    allowed: bool
    headline: str
    said: str = ""
    """The operator's note and line comments; empty where they wrote nothing."""
    after: str = ""
    """What the agent can do next, such as where its version is saved."""

    def message(self) -> str:
        """Everything the agent hears about the outcome, one part per line."""
        return "\n".join(part for part in [self.headline, self.said, self.after] if part)


class PreToolUseAnswer(BaseModel, frozen=True, alias_generator=to_camel, populate_by_name=True):
    """The PreToolUse decision Claude Code reads back."""

    hook_event_name: Literal["PreToolUse"] = "PreToolUse"
    permission_decision: Literal["allow", "deny"] | None = None
    permission_decision_reason: str | None = None
    additional_context: str | None = None

    @classmethod
    def of(cls, outcome: Outcome) -> PreToolUseAnswer:
        """The decision for an outcome: an approval lets the call through and says why; anything else refuses it."""
        if outcome.allowed:
            return cls(permission_decision="allow", additional_context=outcome.message())
        return cls(permission_decision="deny", permission_decision_reason=outcome.message())


class PermissionDecision(BaseModel, frozen=True):
    """Allow or deny the one call a permission prompt is about.

    It never carries `updatedPermissions`: an approval covers one call, and a
    rule it added would let later calls through unseen.
    """

    behavior: Literal["allow", "deny"]
    message: str | None = None
    """Why it's denied, which the agent reads; Claude Code reads it on a deny only."""


class PermissionAnswer(BaseModel, frozen=True, alias_generator=to_camel, populate_by_name=True):
    """The PermissionRequest decision Claude Code reads back in place of the operator's answer at the prompt."""

    hook_event_name: Literal["PermissionRequest"] = "PermissionRequest"
    decision: PermissionDecision

    @classmethod
    def of(cls, outcome: Outcome) -> PermissionAnswer:
        """The decision for an outcome: an approval allows the call; anything else denies it and says why."""
        if outcome.allowed:
            return cls(decision=PermissionDecision(behavior="allow"))
        return cls.refusing(outcome.message())

    @classmethod
    def refusing(cls, message: str) -> PermissionAnswer:
        """A denial that tells the agent why."""
        return cls(decision=PermissionDecision(behavior="deny", message=message))


class BatchAnswer(BaseModel, frozen=True, alias_generator=to_camel, populate_by_name=True):
    """What a PostToolBatch hook adds to the agent's context before its next request."""

    hook_event_name: Literal["PostToolBatch"] = "PostToolBatch"
    additional_context: str


type HookAnswer = PreToolUseAnswer | PermissionAnswer | BatchAnswer


class HookOutput(BaseModel, frozen=True, alias_generator=to_camel, populate_by_name=True):
    """What this hook prints for Claude Code."""

    hook_specific_output: HookAnswer


class Note(BaseModel, frozen=True):
    """What the agent hears about an approved prompt, waiting for the batch holding the call to end."""

    message: str


class ParkedCall(BaseModel, frozen=True):
    """One call as the first lup's host half parks it and recognizes it again."""

    request: Request
    answers: Path
    """The host's file of the operator's answers to the relay the call is parked in."""

    def park(self, host: ModuleType) -> ParkedState:
        """Park this call, or read back the state of the review it already waits on.

        An approval read back here is spent: the host claims it, so it lets the
        call through once. Only a call about to run may park.
        """
        request = self.request
        return ParkedState.model_validate(
            host.review_hook_call(
                request.root,
                request.session,
                request.tool,
                request.arguments,
                request.preconditions.model_dump_json(),
                request.review.reason,
                request.review.rule,
                request.review.purpose,
                "human_only",
                answers=str(self.answers),
                agent=request.agent,
            )
        )

    def queue(self, review_id: str) -> bool:
        """Keep this call where `wait` finds it under this review, and say whether it's newly queued."""
        record = queue_file(self.request.checkout, review_id)
        if record.is_file():
            return False
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(self.model_dump_json())
        return True


class Look(BaseModel, frozen=True):
    """One look at a queued review that leaves it as it is: the newest review of the call, its state, and its answer."""

    review: str
    state: str
    """Its state in the relay, or why there is none to look at."""
    answer: Answer | None = None


class Heard(BaseModel, frozen=True):
    """What a wait on a queued review ends with: what it prints, and its exit status."""

    message: str
    status: int
    """0 approved; 1 declined, or gone from the queue unanswered; 2 nothing to wait on."""


def git(directory: Path, *arguments: str) -> str | None:
    """Ask git about the repository holding `directory`, or None where it holds none."""
    output = sh.git("-C", directory, *arguments, _ok_code=[0, 128], _return_cmd=True)
    return str(output).strip() if output.exit_code == 0 else None


def edited(before: str, tool_input: ToolInput) -> str | None:
    """The file after an Edit, applied as the Edit tool applies it; None where the tool would refuse the edit."""
    old = tool_input.old_string
    new = tool_input.new_string
    if not old or new is None:
        return None
    occurrences = before.count(old)
    if occurrences == 0 or (occurrences > 1 and not tool_input.replace_all):
        return None
    # lup: ignore[string-replace] — this is the Edit tool's own exact replacement, not parsing
    return before.replace(old, new) if tool_input.replace_all else before.replace(old, new, 1)


def changed(file: Path, tool: str, tool_input: ToolInput) -> Change | None:
    """What a Write or Edit would do to `file`; None where the Edit tool would refuse the edit."""
    before = file.read_text() if file.is_file() else None
    after = tool_input.content if tool == "Write" else edited(before or "", tool_input)
    if after is None:
        return None
    return Change(file=file, before=before, after=after)


def suppressions(source: str) -> int | None:
    """How many `# lup: ignore` comments a Python source holds, read by Python's tokenizer; None where it can't read it."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return None
    return sum(1 for token in tokens if token.type == tokenize.COMMENT and "lup: ignore" in token.string)


def verdict(relative: Path, tool: str, before: str | None, after: str, settings: Settings) -> Verdict:
    """Whether the operator sees this write before it lands, and why."""
    protected = next((pattern for pattern in settings.protected if relative.full_match(pattern)), None)
    if protected is not None:
        reason = f"{relative} is a protected path ({protected})"
        return Verdict(review=Review(rule="interim-protected-path", reason=reason, purpose="policy_override"))
    if any(relative.full_match(pattern) for pattern in settings.operator_documents):
        reason = f"{relative} is one of the operator's documents"
        return Verdict(review=Review(rule="interim-operator-document", reason=reason, purpose="policy_override"))
    if not any(relative.full_match(pattern) for pattern in settings.production):
        return Verdict()
    if before is None:
        reason = f"{relative} is a new production file"
        return Verdict(review=Review(rule="interim-new-file", reason=reason, purpose="quality_review"))
    if tool == "Write":
        reason = f"the Write replaces all of {relative}"
        return Verdict(review=Review(rule="interim-whole-file", reason=reason, purpose="quality_review"))
    if relative.suffix not in settings.python_suffixes:
        return Verdict()
    added = suppressions(after)
    if added is None:
        note = (
            f"The interim review couldn't read {relative} as Python after this edit, "
            "so it didn't check it for added suppressions."
        )
        return Verdict(note=note)
    if added > (suppressions(before) or 0):
        reason = f"the edit adds a `# lup: ignore` to {relative}"
        return Verdict(review=Review(rule="interim-suppression", reason=reason, purpose="policy_override"))
    return Verdict()


def asked_for(payload: PermissionPayload, checkout: Path) -> str:
    """What Claude Code asks permission for, as the review's reason: the command, the path, or the tool and input."""
    whole = f"Claude Code asks permission to use {payload.tool_name} with {json.dumps(payload.tool_input)}"
    match payload.tool_name:
        case "Bash":
            call = CommandInput.model_validate(payload.tool_input)
            purpose = f" ({call.description})" if call.description else ""
            return f"Claude Code asks permission to run{purpose}: {call.command}"
        case "Read" | "Write" | "Edit":
            path = PathInput.model_validate(payload.tool_input).file_path
            shown = path.relative_to(checkout) if path.is_relative_to(checkout) else path
            return f"Claude Code asks permission to use {payload.tool_name} on {shown}"
        case "ExitPlanMode":
            plan = PlanInput.model_validate(payload.tool_input).plan
            return f"Claude Code asks permission to leave plan mode with this plan:\n\n{plan}" if plan else whole
        case _:
            return whole


def prompted_write(payload: PermissionPayload) -> Change | None:
    """The file a prompted Write or Edit would leave, so the review shows its diff; None for every other tool."""
    match payload.tool_name:
        case "Write" | "Edit":
            tool_input = ToolInput.model_validate(payload.tool_input)
            return changed(payload.cwd / tool_input.file_path, payload.tool_name, tool_input)
        case _:
            return None


def legacy_host(checkout: Path) -> ModuleType:
    """The first lup's host half, loaded from its checkout: it parks reviews and reads their answers."""
    source = checkout / "packages/lup/src/lup/policy/assets/host.py"
    if not source.is_file():
        raise FileNotFoundError(f"no first-lup host half at {source}")
    spec = importlib.util.spec_from_file_location("lup_legacy_host", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Python can't load {source} as a module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Outside(BaseModel, frozen=True):
    """What the hook reaches beyond its payload: the first lup's host half, and the clock `wait` polls by."""

    load: Callable[[Path], ModuleType] = legacy_host
    sleep: Callable[[float], None] = time.sleep


def notify(review: Review, settings: Settings) -> None:
    """Tell the operator a review is queued, where the desktop can show it."""
    if not settings.notify or shutil.which("notify-send") is None:
        return
    try:
        sh.Command("notify-send")("--app-name=lup", "A call waits for your review", review.reason)
    except sh.ErrorReturnCode as failed:
        print(f"interim review: notify-send failed: {failed.stderr.decode()}", file=sys.stderr)


def said(host: ModuleType, call: ParkedCall, review_id: str) -> str:
    """Everything the operator wrote on one review, answer and remarks alike.

    The decision never depends on this: a record that can't be read is said so
    in the message, beside the decision already taken.
    """
    try:
        records = TypeAdapter(list[RecordedAnswer | RecordedRemark]).validate_python(
            host.review_records(call.answers)
        )
    except ValidationError as unreadable:
        return f"The operator's note and comments couldn't be read from {call.answers}: {unreadable}"
    written = [record.words() for record in records if record.question == review_id]
    notes = [entry.note for entry in written if entry.note]
    comments = [comment.render() for entry in written for comment in entry.comments]
    parts = [*(f"The operator's note: {note}" for note in notes), *(["Line comments:", *comments] if comments else [])]
    return "\n".join(parts)


def answered(host: ModuleType, call: ParkedCall, state: ParkedState) -> Outcome:
    """What a review's state means for its call, in the words the agent hears."""
    request = call.request
    reason = request.review.reason
    match state:
        case ParkedState(state="approved", id=review_id):
            headline = f"The operator approved this {request.tool} call in the review dashboard ({reason})."
            return Outcome(allowed=True, headline=headline, said=said(host, call, review_id))
        case ParkedState(state="rejected", id=review_id):
            headline = f"The operator declined this {request.tool} call ({reason})."
            words = said(host, call, review_id)
            return Outcome(allowed=False, headline=headline, said=words, after=request.kept(review_id))
        case ParkedState(state="unavailable", reason=why):
            return Outcome(allowed=False, headline=f"{reason}, but the review can't be asked: {why}.")
        case ParkedState(id=review_id):
            return Outcome(allowed=False, headline=request.waiting(review_id))


def ask(request: Request, settings: Settings, outside: Outside) -> Outcome:
    """Queue one call for the operator's review in the first lup's dashboard, or read back the answer it already has.

    The one path both events share. It never waits: a call the relay already
    holds reaches the same review through its fingerprint, and is let through
    once approved, refused with what the operator wrote once declined, and
    refused with the same message while the review waits.
    """
    try:
        host = outside.load(request.repository.parent / settings.legacy_checkout)
    except FileNotFoundError as missing:
        headline = (
            f"{request.review.reason}, so the operator reviews it first, but the review can't be asked: {missing}. "
            "Tell the operator."
        )
        return Outcome(allowed=False, headline=headline)
    relay = host.review_home(request.root) / ".lup/questions.jsonl"
    call = ParkedCall(
        request=request,
        answers=host.review_answers(relay, host.review_answers_home(settings.answers_variable)),
    )
    state = call.park(host)
    match state.state:
        case "pending":
            if call.queue(state.id):
                notify(request.review, settings)
        case "approved" | "rejected":
            queue_file(request.checkout, state.id).unlink(missing_ok=True)
        case "unavailable":
            pass
    return answered(host, call, state)


def reviewed_write(payload: WritePayload, settings: Settings, outside: Outside) -> PreToolUseAnswer | None:
    """Judge one Write or Edit by the agreed table: allow most, queue the rest for the operator's review.

    A write outside the session's repository gets no answer, leaving it to
    Claude Code's own mode. An Edit the tool would refuse is allowed, and fails
    on its own.
    """
    file = payload.cwd / payload.tool_input.file_path
    start = next(directory for directory in file.parents if directory.is_dir())
    worktree_text = git(start, "rev-parse", "--show-toplevel")
    common = git(start, "rev-parse", "--path-format=absolute", "--git-common-dir")
    session_common = git(payload.cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    checkout_text = git(payload.cwd, "rev-parse", "--show-toplevel")
    if worktree_text is None or common is None or common != session_common or checkout_text is None:
        return None
    worktree = Path(worktree_text)
    change = changed(file, payload.tool_name, payload.tool_input)
    if change is None:
        return PreToolUseAnswer(permission_decision="allow")
    judged = verdict(file.relative_to(worktree), payload.tool_name, change.before, change.after, settings)
    if judged.review is None:
        return PreToolUseAnswer(permission_decision="allow", additional_context=judged.note or None)
    request = Request(
        repository=Path(common),
        root=worktree,
        checkout=Path(checkout_text),
        session=payload.session_id,
        agent=payload.agent_id,
        tool=payload.tool_name,
        arguments=payload.tool_input.model_dump_json(exclude_none=True),
        preconditions=change.preconditions(),
        review=judged.review,
        draft=change.draft(worktree),
    )
    return PreToolUseAnswer.of(ask(request, settings, outside))


def notes_file(checkout: Path, session: str, agent: str) -> Path:
    """Where approved prompts' notes wait for the conversation that asked: the session's, or a subagent's."""
    return checkout / ".lup/approval-notes" / session / f"{agent or 'session'}.jsonl"


def scratch_write(payload: PermissionPayload, common: Path, settings: Settings) -> bool:
    """Whether a prompted Write or Edit lands only in scratch, which the operator doesn't review.

    Scratch is `settings.scratch` in any worktree of the session's repository, or
    the session's own scratchpad. The path is resolved first, so a `..` or a
    symlink can't lead out of either.
    """
    if payload.tool_name not in ["Write", "Edit"]:
        return False
    path = (payload.cwd / PathInput.model_validate(payload.tool_input).file_path).resolve()
    if path.full_match(settings.scratchpad.format(session=payload.session_id)):
        return True
    directory = next(parent for parent in path.parents if parent.is_dir())
    toplevel = git(directory, "rev-parse", "--show-toplevel")
    shared = git(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if toplevel is None or shared is None or Path(shared) != common:
        return False
    return any(path.full_match(str(Path(toplevel) / pattern)) for pattern in settings.scratch)


def permission(payload: PermissionPayload, settings: Settings, outside: Outside) -> PermissionAnswer | None:
    """Queue one permission prompt in the dashboard instead of the terminal, and answer it from there.

    A Write or Edit landing only in scratch is allowed without asking
    (`scratch_write`). An approval allows this call only. What the operator
    wrote with it waits in the notes file until the batch holding the call
    ends (`delivered`), since a PermissionRequest's answer can't carry context.
    """
    if payload.tool_name in settings.terminal_tools:
        return None
    checkout_text = git(payload.cwd, "rev-parse", "--show-toplevel")
    common = git(payload.cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if checkout_text is None or common is None:
        return PermissionAnswer.refusing(
            f"Claude Code asks permission for this {payload.tool_name} call, but {payload.cwd} is in no git checkout, "
            "so the review dashboard can't be reached. Tell the operator."
        )
    if scratch_write(payload, Path(common), settings):
        return PermissionAnswer(decision=PermissionDecision(behavior="allow"))
    checkout = Path(checkout_text)
    change = prompted_write(payload)
    request = Request(
        repository=Path(common),
        root=payload.cwd,
        checkout=checkout,
        session=payload.session_id,
        agent=payload.agent_id,
        tool=payload.tool_name,
        arguments=json.dumps(payload.tool_input),
        preconditions=change.preconditions() if change else Preconditions({}),
        review=Review(rule="interim-permission-prompt", reason=asked_for(payload, checkout), purpose="policy_override"),
        draft=change.draft(checkout) if change else None,
    )
    outcome = ask(request, settings, outside)
    if outcome.allowed and outcome.said:
        notes = notes_file(checkout, payload.session_id, payload.agent_id)
        notes.parent.mkdir(parents=True, exist_ok=True)
        with notes.open("a") as waiting:
            waiting.write(Note(message=outcome.message()).model_dump_json() + "\n")
    return PermissionAnswer.of(outcome)


def delivered(payload: BatchPayload) -> BatchAnswer | None:
    """Pass on the notes waiting for the conversation whose batch of calls just ended, once."""
    checkout_text = git(payload.cwd, "rev-parse", "--show-toplevel")
    if checkout_text is None:
        return None
    notes = notes_file(Path(checkout_text), payload.session_id, payload.agent_id)
    if not notes.is_file():
        return None
    waiting = [Note.model_validate_json(line) for line in notes.read_text().splitlines() if line]
    notes.unlink()
    return BatchAnswer(additional_context="\n\n".join(note.message for note in waiting))


def looked(host: ModuleType, call: ParkedCall, review_id: str) -> Look:
    """The newest review of this call in the relay, its state and its answer, read without touching any of them.

    The newest, since a repeat of the call or an earlier wait may have parked
    it again under a new id once the dashboard expired it: they share its
    fingerprint.
    """
    relay = host.review_home(call.request.root) / ".lup/questions.jsonl"
    entries = TypeAdapter(dict[str, RelayEntry]).validate_python(host.native_review_records(relay))
    if review_id not in entries:
        return Look(review=review_id, state=f"not in {relay}")
    fingerprint = entries[review_id].fingerprint
    newest = [entry for entry in entries.values() if entry.fingerprint == fingerprint][-1]
    records = TypeAdapter(list[RecordedAnswer | RecordedRemark]).validate_python(host.review_records(call.answers))
    decisions = [record.decision() for record in records if record.question == newest.id]
    answer = next((decision for decision in decisions if decision is not None), None)
    return Look(review=newest.id, state=newest.state, answer=answer)


def watched(host: ModuleType, call: ParkedCall, review_id: str, settings: Settings, outside: Outside) -> Iterator[Look]:
    """Each look at a queued review, one per poll, until the operator answers it or it leaves the queue unanswered.

    A look never claims an approval: only a repeat of the call does. A review
    the dashboard expired unanswered is parked again under a new id, which can't
    spend an answer since nothing newer stands for the call, and the operator
    is told once more.
    """
    current = review_id
    while True:
        look = looked(host, call, current)
        yield look
        current = look.review
        if look.answer is not None:
            return
        match look.state:
            case "pending":
                outside.sleep(settings.poll.total_seconds())
            case "expired":
                parked = call.park(host)
                if parked.state != "pending":
                    yield Look(review=current, state=f"expired, and parking it again failed: {parked.reason}")
                    return
                if call.queue(parked.id):
                    notify(call.request.review, settings)
                current = parked.id
            case _:
                return


def waited(review_id: str, cwd: Path, settings: Settings, outside: Outside) -> Heard:
    """Wait until the operator answers one queued review, and say what came of it."""
    checkout_text = git(cwd, "rev-parse", "--show-toplevel")
    if checkout_text is None:
        return Heard(message=f"{cwd} is in no git checkout, so no queued review can be found from here.", status=2)
    record = queue_file(Path(checkout_text), review_id)
    if not record.is_file():
        message = (
            f"No review {review_id} is queued from {checkout_text}: "
            "a repeat of its call settled it already, or it was queued from another checkout."
        )
        return Heard(message=message, status=2)
    call = ParkedCall.model_validate_json(record.read_text())
    host = outside.load(call.request.repository.parent / settings.legacy_checkout)
    *_, last = watched(host, call, review_id, settings, outside)
    match last:
        case Look(review=review, answer=Answer(approved=True)):
            outcome = answered(host, call, ParkedState(state="approved", id=review, reason=""))
            repeat = "Repeat this exact call to carry it out; the approval covers that one call."
            return Heard(message=f"{outcome.message()}\n{repeat}", status=0)
        case Look(review=review, answer=Answer()):
            outcome = answered(host, call, ParkedState(state="rejected", id=review, reason=""))
            return Heard(message=outcome.message(), status=1)
        case Look(review=review, state=state):
            message = (
                f"Review {review} left the queue unanswered: {state}. "
                "Repeat the exact call to queue it again if it's still needed."
            )
            return Heard(message=message, status=1)


class HookEvent(BaseModel):
    """The event Claude Code runs this hook for, read before the rest so a failure is answered in that event's terms."""

    hook_event_name: Literal["PreToolUse", "PermissionRequest", "PostToolBatch"]

    def answer(self, raw: str, settings: Settings, outside: Outside) -> HookAnswer | None:
        """Read the event's whole payload and answer it, or give no answer where Claude Code's own flow applies."""
        match self.hook_event_name:
            case "PreToolUse":
                return reviewed_write(WritePayload.model_validate_json(raw), settings, outside)
            case "PermissionRequest":
                return permission(PermissionPayload.model_validate_json(raw), settings, outside)
            case "PostToolBatch":
                return delivered(BatchPayload.model_validate_json(raw))

    def refusal(self, failure: Exception) -> HookAnswer:
        """The answer when the hook itself fails: refuse the call and name the failure.

        A crashing hook is a non-blocking error to Claude Code, which would let a
        write meant for review through unseen. After a batch there is nothing to
        refuse, so the agent is told the operator's notes may not have reached it.
        """
        match self.hook_event_name:
            case "PreToolUse":
                reason = f"The interim review failed, so this write is refused until it's fixed: {failure!r}."
                told = f"{reason} Tell the operator."
                return PreToolUseAnswer(permission_decision="deny", permission_decision_reason=told)
            case "PermissionRequest":
                reason = f"The interim review failed, so this call is refused until it's fixed: {failure!r}."
                return PermissionAnswer.refusing(f"{reason} Tell the operator.")
            case "PostToolBatch":
                context = f"The interim review couldn't pass on the operator's notes on approved calls: {failure!r}."
                return BatchAnswer(additional_context=f"{context} Tell the operator.")


def hook() -> None:
    """Read the hook's payload, answer it, and print the answer where there is one.

    Any failure refuses the call, naming the failure. A payload naming no event
    this hook answers can't be answered in its own terms, so it exits 2 with
    the error: that blocks a PreToolUse call, and leaves a PermissionRequest
    to the terminal prompt.
    """
    raw = sys.stdin.read()
    try:
        event = HookEvent.model_validate_json(raw)
    except ValidationError as unreadable:
        print(f"The interim review can't tell which hook event called it: {unreadable}", file=sys.stderr)
        sys.exit(2)
    try:
        answer = event.answer(raw, Settings(), Outside())
    except Exception as failure:
        answer = event.refusal(failure)
    if answer is not None:
        print(HookOutput(hook_specific_output=answer).model_dump_json(by_alias=True, exclude_none=True))


class Wait(BaseModel):
    """Wait until the operator answers a queued review, print the answer, and exit: run it in the background.

    Exits 0 once approved, 1 once declined or gone from the queue unanswered,
    and 2 where there's nothing to wait on. It never carries out the call:
    repeat the call once it's approved.
    """

    review: CliPositionalArg[str]
    """The review's id, as the refusal that queued it gives it."""

    def cli_cmd(self) -> None:
        """Wait from the current directory, which is in the session's checkout."""
        heard = waited(self.review, Path.cwd(), Settings(), Outside())
        print(heard.message)
        sys.exit(heard.status)


class Command(BaseModel):
    """The interim review: with no arguments, answer the Claude Code hook whose payload is on stdin."""

    wait: CliSubCommand[Wait]

    def cli_cmd(self) -> None:
        """Answer the hook, or run the subcommand given."""
        if self.wait is None:
            hook()
            return
        CliApp.run_subcommand(self)


if __name__ == "__main__":
    CliApp.run(Command)
