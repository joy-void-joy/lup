# /// script
# requires-python = ">=3.14"
# dependencies = ["pydantic>=2.12", "pydantic-settings>=2.11", "sh>=2"]
# ///
"""Ask the operator in the first lup's dashboard before a write that shows design lands.

An interim review for the bridge, until lup's own review flow and dashboard land
(`docs/after-call-diff.md`); then this file and its hook go. It runs before each
Write or Edit. Most writes pass untouched, left to Claude Code's own permission
mode. A write the operator wants to see first is parked as a review in the first
lup's format, and the call waits here until it's answered in the first lup's
dashboard:
- a new production file, or a Write over a whole existing one;
- a protected path: manifests, lockfiles, runtime settings and hooks, CI, editor configs;
- an edit that adds a `# lup: ignore` suppression to a Python file.

An approval lets the call through, with the operator's note and line comments
added to the agent's context. A decline refuses it, saves the agent's version
under `.lup/saved/<review>/`, and passes the note and comments on. A call nobody
answers within `patience` is refused the same way, with the review left waiting:
retrying the same call waits on the same review.

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
from pydantic import BaseModel, RootModel, TypeAdapter, ValidationError
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
    ]
    """Paths every write to asks, as patterns relative to the worktree.

    Manifests and lockfiles choose what runs; runtime settings and hooks, CI,
    pre-commit and editor configs run outside the agent's own calls;
    `.gitignore` decides what review can see; `.env*` holds secrets.
    """
    python_suffixes: list[str] = [".py", ".pyi"]
    answers_variable: str = "LUP_REVIEW_ANSWERS"
    """The variable a first-lup launch names the answers store with; unset here, so the host's default applies."""
    poll: timedelta = timedelta(seconds=2)
    """How often a waiting call looks for the operator's answer."""
    patience: timedelta = timedelta(hours=4)
    """How long a call waits before it's refused; the hook's timeout in `.claude/settings.json` sits just above it."""
    notify: bool = True
    """Whether a review that starts waiting raises a desktop notice through `notify-send`, where it's installed."""


class ToolInput(BaseModel):
    """A Write or Edit call's input, as Claude Code sends it."""

    file_path: Path
    content: str | None = None
    old_string: str | None = None
    new_string: str | None = None
    replace_all: bool | None = None


class HookPayload(BaseModel):
    """What Claude Code sends a PreToolUse hook on stdin."""

    session_id: str
    cwd: Path
    tool_name: str
    tool_input: ToolInput


class Review(BaseModel, frozen=True):
    """Why a write waits for the operator, in the first lup's terms."""

    rule: str
    reason: str
    purpose: Literal["quality_review", "policy_override"]


class Verdict(BaseModel, frozen=True):
    """What this hook makes of one write: a review to wait on, if any, and anything the agent should hear."""

    review: Review | None = None
    note: str = ""


class Preconditions(RootModel[dict[Path, str | None]]):
    """Each file the call changes, with its content before the call, or none where it's new."""


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


class Decision(BaseModel, frozen=True, alias_generator=to_camel, populate_by_name=True):
    """The PreToolUse decision Claude Code reads back."""

    hook_event_name: Literal["PreToolUse"] = "PreToolUse"
    permission_decision: Literal["allow", "deny"] | None = None
    permission_decision_reason: str | None = None
    additional_context: str | None = None


class HookOutput(BaseModel, frozen=True, alias_generator=to_camel, populate_by_name=True):
    """What this hook prints for Claude Code."""

    hook_specific_output: Decision


class ParkedCall(BaseModel, frozen=True):
    """One call as the first lup's host half parks it and recognizes it again."""

    worktree: Path
    session: str
    tool: str
    arguments: str
    preconditions: str
    review: Review
    answers: Path

    def park(self, host: ModuleType) -> ParkedState:
        """Park this call, or read back the state of the review it already waits on."""
        return ParkedState.model_validate(
            host.review_hook_call(
                self.worktree,
                self.session,
                self.tool,
                self.arguments,
                self.preconditions,
                self.review.reason,
                self.review.rule,
                self.review.purpose,
                "human_only",
                answers=str(self.answers),
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


def notify(review: Review, settings: Settings) -> None:
    """Tell the operator a review is waiting, where the desktop can show it."""
    if not settings.notify or shutil.which("notify-send") is None:
        return
    try:
        sh.Command("notify-send")("--app-name=lup", "A write waits for your review", review.reason)
    except sh.ErrorReturnCode as failed:
        print(f"interim review: notify-send failed: {failed.stderr.decode()}", file=sys.stderr)


def looks(
    host: ModuleType,
    call: ParkedCall,
    settings: Settings,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Iterator[ParkedState]:
    """Each look at the call's review, one per poll, until it's settled or the patience runs out.

    The first look parks it. A review the dashboard expired is parked again by
    the next look, under a new id, and the operator is told once more. A
    settled review is the last look: looking again would park the call anew.
    """
    deadline = monotonic() + settings.patience.total_seconds()
    announced = ""
    while monotonic() < deadline:
        state = call.park(host)
        if state.state == "pending" and state.id != announced:
            notify(call.review, settings)
            announced = state.id
        yield state
        if state.state != "pending":
            return
        sleep(settings.poll.total_seconds())


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


def saved(worktree: Path, review_id: str, relative: Path, content: str) -> Path:
    """Keep the agent's version of a refused write where it can revise it, and say where."""
    target = worktree / ".lup/saved" / review_id / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def decide(payload: HookPayload, settings: Settings) -> Decision | None:
    """Decide one Write or Edit: no decision for most, a held review for the rest."""
    file = payload.cwd / payload.tool_input.file_path
    start = next(directory for directory in file.parents if directory.is_dir())
    worktree_text = git(start, "rev-parse", "--show-toplevel")
    common = git(start, "rev-parse", "--path-format=absolute", "--git-common-dir")
    session_common = git(payload.cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if worktree_text is None or common is None or common != session_common:
        return None
    worktree = Path(worktree_text)
    relative = file.relative_to(worktree)
    before = file.read_text() if file.is_file() else None
    after = payload.tool_input.content if payload.tool_name == "Write" else edited(before or "", payload.tool_input)
    if after is None:
        return None
    judged = verdict(relative, payload.tool_name, before, after, settings)
    if judged.review is None:
        return Decision(additional_context=judged.note) if judged.note else None
    try:
        host = legacy_host(Path(common).parent / settings.legacy_checkout)
    except FileNotFoundError as missing:
        reason = (
            f"{judged.review.reason}, so the operator reviews it first, "
            f"but the review can't be asked: {missing}. Tell the operator."
        )
        return Decision(permission_decision="deny", permission_decision_reason=reason)
    relay = host.review_home(worktree) / ".lup/questions.jsonl"
    call = ParkedCall(
        worktree=worktree,
        session=payload.session_id,
        tool=payload.tool_name,
        arguments=payload.tool_input.model_dump_json(exclude_none=True),
        preconditions=Preconditions({file: before}).model_dump_json(),
        review=judged.review,
        answers=host.review_answers(relay, host.review_answers_home(settings.answers_variable)),
    )
    settled = next((state for state in looks(host, call, settings) if state.state != "pending"), None)
    match settled:
        case ParkedState(state="approved", id=review_id):
            approval = f"The operator approved this {payload.tool_name} of {relative} in the review dashboard."
            context = "\n".join(part for part in [approval, said(host, call, review_id)] if part)
            return Decision(permission_decision="allow", additional_context=context)
        case ParkedState(state="rejected", id=review_id):
            kept = saved(worktree, review_id, relative, after)
            reason = "\n".join(
                part
                for part in [
                    f"The operator declined this {payload.tool_name} ({judged.review.reason}).",
                    said(host, call, review_id),
                    f"Your version is saved at {kept}. Revise it there and write it back, which asks again.",
                ]
                if part
            )
            return Decision(permission_decision="deny", permission_decision_reason=reason)
        case ParkedState(state="unavailable", reason=why):
            reason = f"{judged.review.reason}, but the review can't be asked: {why}."
            return Decision(permission_decision="deny", permission_decision_reason=reason)
        case _:
            kept = saved(worktree, call.park(host).id, relative, after)
            reason = (
                f"No answer within {settings.patience} ({judged.review.reason}). The review is still waiting in the dashboard. "
                f"Your version is saved at {kept}. Retrying the same call waits on the same review."
            )
            return Decision(permission_decision="deny", permission_decision_reason=reason)


def main() -> None:
    """Read the hook's payload, decide, and print the decision where there is one.

    Any failure refuses the call, naming the failure: a hook that crashes is a
    non-blocking error to Claude Code, which would let a write meant for review
    through unseen.
    """
    try:
        decision = decide(HookPayload.model_validate_json(sys.stdin.read()), Settings())
    except Exception as failure:
        reason = f"The interim review failed, so this write is refused until it's fixed: {failure!r}. Tell the operator."
        decision = Decision(permission_decision="deny", permission_decision_reason=reason)
    if decision is not None:
        print(HookOutput(hook_specific_output=decision).model_dump_json(by_alias=True, exclude_none=True))


if __name__ == "__main__":
    main()
