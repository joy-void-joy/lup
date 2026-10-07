# /// script
# requires-python = ">=3.14"
# dependencies = ["pydantic>=2.12", "pydantic-settings>=2.11", "sh>=2"]
# ///
"""Ask the operator in the first lup's dashboard: before writes that show design, and wherever Claude Code prompts.

An interim review for the bridge, until lup's own review flow and dashboard land
(`docs/judging-writes.md`); then this file and its hooks go. Claude Code runs it
for three events, named by the payload's `hook_event_name`:
- `PreToolUse`, before each Write or Edit. Most writes pass untouched, left to
  Claude Code's own permission mode. A write the operator wants to see first is
  parked as a review:
  - a new production file, or a Write over a whole existing one;
  - a protected path: manifests, lockfiles, runtime settings and hooks, CI, editor configs;
  - one of the operator's documents, `DESIGN.md` and `AGENTS.md` at a worktree's root;
  - an edit that adds a `# lup: ignore` suppression to a Python file.
- `PermissionRequest`, whenever Claude Code is about to show a permission prompt,
  for any tool. The prompt is parked as a review instead, saying what Claude Code
  asks permission for. A tool whose prompt is a question rather than a permission
  (`AskUserQuestion`) stays in the terminal: the dashboard can only approve or decline.
- `PostToolBatch`, after each batch of tool calls, to pass on what the operator
  wrote when approving a prompt (below).

Either way the call waits here until the review is answered in the first lup's
dashboard. An approval lets the call through. For a write, the operator's note
and line comments reach the agent's context at once. A PermissionRequest's answer
can't carry context, so they wait under `.lup/approval-notes/` and reach the agent
when the batch holding the call ends. A decline refuses the call and passes the
note and comments on; a refused Write or Edit leaves the agent's version under
`.lup/saved/<review>/`. A call nobody answers within `patience` is refused the
same way, with the review left waiting: retrying the same call waits on the same
review. An approval covers that one call: it never adds a permission rule.

The review is parked and read back by the first lup's own host half
(`policy/assets/host.py`), which uses only the standard library, so the dashboard
sees exactly the records it writes itself. Serve the dashboard with:

    uv run --directory <lup-legacy checkout> lup-devtools dashboard serve --root <this checkout>

The first lup's dashboard expires a review after an hour when its requester isn't
on the first lup's roster, which these sessions never are. The waiting call then
parks the same review again under a new id, so the dashboard's history shows the
expired one beside the one still waiting.
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
from pydantic_settings import BaseSettings


class Settings(BaseSettings, env_prefix="LUP_INTERIM_REVIEW_"):
    """What this review assumes about the machine, the first lup and this repository."""

    legacy_checkout: Path = Path("lup-legacy.git/tree/dev")
    """The first lup's checkout, relative to the directory holding `lup.git`."""
    production: list[str] = ["packages/*/src/**"]
    """Where production code lives, as patterns relative to the worktree."""
    protected: list[str] = [
        "**/pyproject.toml",
        "**/uv.lock",
        "**/package.json",
        "**/bun.lock",
        ".claude/**",
        ".codex/**",
        ".github/**",
        ".pre-commit-config.yaml",
        ".vscode/**",
        ".devcontainer/**",
        ".gitignore",
        ".env*",
        "**/lup_dev/catalog/**",
    ]
    """Paths every write to asks, as patterns relative to the worktree.

    Manifests and lockfiles choose what runs; runtime settings and hooks, CI,
    pre-commit and editor configs run outside the agent's own calls;
    `.gitignore` decides what review can see; `.env*` holds secrets;
    `lup_dev/catalog/` is the data that sets lup's policy (its rules, its path
    roles), which the operator reviews before it changes.
    """
    operator_documents: list[str] = ["DESIGN.md", "AGENTS.md"]
    """The operator's documents, as patterns relative to the worktree.

    Changing one is a design decision, so every write to one asks.
    """
    terminal_tools: list[str] = ["AskUserQuestion"]
    """Tools whose prompt asks the operator a question rather than for permission.

    The dashboard can only approve or decline, so their prompts stay in the terminal.
    """
    python_suffixes: list[str] = [".py", ".pyi"]
    answers_variable: str = "LUP_REVIEW_ANSWERS"
    """The variable a first-lup launch names the answers store with; unset here, so the host's default applies."""
    poll: timedelta = timedelta(seconds=2)
    """How often a waiting call looks for the operator's answer."""
    patience: timedelta = timedelta(days=20)
    """How long a call waits before it's refused: effectively as long as it takes, since waiting never re-prompts the agent.

    It's bounded only because Claude Code lets a call continue through the normal
    permission flow when a hook times out ("don't count on a stalled hook to act as
    a gate", its hooks docs), so the hook must decide before its timeout, which
    `.claude/settings.json` sets just above this. Twenty days stays under the
    longest timer Node, which runs Claude Code, can hold: about 24.8 days.
    """
    notify: bool = True
    """Whether a review that starts waiting raises a desktop notice through `notify-send`, where it's installed."""


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
    """What this hook makes of one write: a review to wait on, if any, and anything the agent should hear."""

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


class Request(BaseModel, frozen=True):
    """One call to put before the operator, as either event hands it over."""

    repository: Path
    """The repository's shared git directory; the first lup's checkout sits beside the directory holding it."""
    root: Path
    """Where the call runs, which the review records and binds."""
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


class RecordedRemark(BaseModel, frozen=True):
    """A remark the operator sent without deciding, as the host keeps it beside the answers."""

    question: str
    remark: Said

    def words(self) -> Said:
        """What the operator wrote."""
        return self.remark


class Outcome(BaseModel, frozen=True):
    """How a call put before the operator ended, in the words the agent hears, before either event spells it."""

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
        """Park this call, or read back the state of the review it already waits on."""
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
    """What the hook reaches beyond its payload: the first lup's host half, and the clock a waiting call keeps."""

    load: Callable[[Path], ModuleType] = legacy_host
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic


def notify(review: Review, settings: Settings) -> None:
    """Tell the operator a review is waiting, where the desktop can show it."""
    if not settings.notify or shutil.which("notify-send") is None:
        return
    try:
        sh.Command("notify-send")("--app-name=lup", "A call waits for your review", review.reason)
    except sh.ErrorReturnCode as failed:
        print(f"interim review: notify-send failed: {failed.stderr.decode()}", file=sys.stderr)


def looks(host: ModuleType, call: ParkedCall, settings: Settings, outside: Outside) -> Iterator[ParkedState]:
    """Each look at the call's review, one per poll, until it's settled or the patience runs out.

    The first look parks it. A review the dashboard expired is parked again by
    the next look, under a new id, and the operator is told once more. A
    settled review is the last look: looking again would park the call anew.
    The last look is taken when the patience runs out, so there is always one.
    """
    deadline = outside.monotonic() + settings.patience.total_seconds()
    announced = ""
    while True:
        state = call.park(host)
        if state.state == "pending" and state.id != announced:
            notify(call.request.review, settings)
            announced = state.id
        yield state
        if state.state != "pending" or outside.monotonic() >= deadline:
            return
        outside.sleep(settings.poll.total_seconds())


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


def ask(request: Request, settings: Settings, outside: Outside) -> Outcome:
    """Put one call before the operator in the first lup's dashboard and wait for the answer.

    The one waiting path both events share; each spells the outcome its own way.
    """
    reason = request.review.reason
    try:
        host = outside.load(request.repository.parent / settings.legacy_checkout)
    except FileNotFoundError as missing:
        headline = (
            f"{reason}, so the operator reviews it first, but the review can't be asked: {missing}. Tell the operator."
        )
        return Outcome(allowed=False, headline=headline)
    relay = host.review_home(request.root) / ".lup/questions.jsonl"
    call = ParkedCall(
        request=request,
        answers=host.review_answers(relay, host.review_answers_home(settings.answers_variable)),
    )
    *_, last = looks(host, call, settings, outside)
    match last:
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
            headline = (
                f"No answer within {settings.patience} ({reason}). The review is still waiting in the dashboard, "
                "and retrying the same call waits on the same review."
            )
            return Outcome(allowed=False, headline=headline, after=request.kept(review_id))


def reviewed_write(payload: WritePayload, settings: Settings, outside: Outside) -> PreToolUseAnswer | None:
    """Decide one Write or Edit: no decision for most, a held review for the rest."""
    file = payload.cwd / payload.tool_input.file_path
    start = next(directory for directory in file.parents if directory.is_dir())
    worktree_text = git(start, "rev-parse", "--show-toplevel")
    common = git(start, "rev-parse", "--path-format=absolute", "--git-common-dir")
    session_common = git(payload.cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if worktree_text is None or common is None or common != session_common:
        return None
    worktree = Path(worktree_text)
    change = changed(file, payload.tool_name, payload.tool_input)
    if change is None:
        return None
    judged = verdict(file.relative_to(worktree), payload.tool_name, change.before, change.after, settings)
    if judged.review is None:
        return PreToolUseAnswer(additional_context=judged.note) if judged.note else None
    request = Request(
        repository=Path(common),
        root=worktree,
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


def permission(payload: PermissionPayload, settings: Settings, outside: Outside) -> PermissionAnswer | None:
    """Carry one permission prompt to the dashboard instead of the terminal, and answer it from there.

    An approval allows this call only. What the operator wrote with it waits
    in the notes file until the batch holding the call ends (`delivered`),
    since a PermissionRequest's answer can't carry context.
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
    checkout = Path(checkout_text)
    change = prompted_write(payload)
    request = Request(
        repository=Path(common),
        root=payload.cwd,
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


def main() -> None:
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


if __name__ == "__main__":
    main()
