"""Concrete semantic fetch, shell, and edit policies."""

import shlex
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from lup.codescan.antipatterns import audit_text, patterns_for_suffix
from lup.codescan.common import IGNORE_RE, PythonContext
from lup.codescan.markers import marker_count
from lup.policy.contracts import DecisionPolicy
from lup.policy.models import Decision, EditBatch, EditChange, FetchUrl, ShellCommand


class UrlScope(BaseModel):
    """One normalized scheme/host/port and path-prefix rule."""

    model_config = ConfigDict(frozen=True)

    origin: AnyHttpUrl
    path_prefix: str = "/"
    reason: str = ""


def url_in_scope(url: AnyHttpUrl, scope: UrlScope) -> bool:
    """Compare parsed URL components without textual pattern matching."""
    candidate = urlsplit(str(url))
    expected = urlsplit(str(scope.origin))
    return (
        candidate.scheme == expected.scheme
        and candidate.hostname == expected.hostname
        and candidate.port == expected.port
        and candidate.path.startswith(scope.path_prefix)
    )


class FetchPolicy(DecisionPolicy[FetchUrl]):
    """Evaluate deny scopes before allow scopes and ask on everything else."""

    def __init__(self, allowed: list[UrlScope], denied: list[UrlScope]) -> None:
        self.allowed = list(allowed)
        self.denied = list(denied)

    def decide(self, event: FetchUrl) -> Decision:
        denied = next(
            (scope for scope in self.denied if url_in_scope(event.url, scope)), None
        )
        if denied is not None:
            return Decision(effect="deny", reason=denied.reason or "URL is denied")
        allowed = next(
            (scope for scope in self.allowed if url_in_scope(event.url, scope)), None
        )
        if allowed is not None:
            return Decision(effect="allow", reason=allowed.reason)
        return Decision(
            effect="ask", reason="URL is outside the declared documentation scopes"
        )


class ShellSegment(BaseModel):
    """One parsed command segment with its ordered shell words."""

    model_config = ConfigDict(frozen=True)

    words: list[str] = Field(min_length=1)


SHELL_SEPARATORS = {
    ";": True,
    "&": True,
    "&&": True,
    "|": True,
    "||": True,
    "\n": True,
}
SHELL_PUNCTUATION = ";&|<>\n"
PASS_THROUGH_WORDS = {
    "sudo": True,
    "env": True,
    "command": True,
    "exec": True,
    "time": True,
    "nohup": True,
    "setsid": True,
    "stdbuf": True,
}
READ_ONLY_COMMANDS = {
    "ls": True,
    "tree": True,
    "grep": True,
    "cat": True,
    "echo": True,
    "test": True,
    "file": True,
    "wc": True,
    "head": True,
    "tail": True,
    "find": True,
}
INTERPRETERS = {
    "python": True,
    "python3": True,
    "perl": True,
    "ruby": True,
    "node": True,
    "deno": True,
    "bun": True,
    "php": True,
}


def parse_shell_segments(command: str) -> list[ShellSegment] | None:
    """Parse quoted shell words and unquoted compound separators with ``shlex``."""
    if any(marker in command for marker in ["$(`", "$(", "<(", ">(", "`"]):
        return None
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SHELL_PUNCTUATION)
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[ShellSegment] = []  # lup: ignore[empty-collection]
    current: list[str] = []  # lup: ignore[empty-collection]
    for token in tokens:
        if token and all(character in SHELL_PUNCTUATION for character in token):
            if "<" in token or ">" in token:
                return None
            if current:
                segments.append(ShellSegment(words=current))
            current = []
        else:
            current.append(token)
    if current:
        segments.append(ShellSegment(words=current))
    return segments or None


def command_words(words: list[str]) -> list[str]:
    """Skip assignments and transparent wrappers to the effective command."""
    position = 0
    while position < len(words):
        word = words[position]
        name, separator, _value = (
            word.partition(  # lup: ignore[string-split] — shell assignment token
                "="
            )
        )
        if separator and name.isidentifier():
            position += 1
            continue
        executable = PurePosixPath(word).name
        if executable in PASS_THROUGH_WORDS:
            position += 1
            continue
        return words[position:]
    return []


def uv_run_words(words: list[str]) -> list[str]:
    """Return the executable portion of a ``uv run`` invocation."""
    position = 2
    value_options = {
        "--directory",
        "--package",
        "--project",
        "--with",
        "--with-editable",
    }
    while position < len(words) and words[position].startswith("-"):
        option = words[position]
        if option in {"-c", "-m", "--script"}:
            return words[position:]
        position += 2 if option in value_options else 1
    return words[position:]


def is_repository_tmp_script(word: str) -> bool:
    """Recognize only a script beneath the repository-relative ``tmp`` root."""
    path = PurePosixPath(word)
    return not path.is_absolute() and bool(path.parts) and path.parts[0] == "tmp"


class ShellPolicy(DecisionPolicy[ShellCommand]):
    """Conservatively combine parsed command segments without a regex rule table."""

    def decide(self, event: ShellCommand) -> Decision:
        segments = parse_shell_segments(event.command)
        if segments is None:
            return Decision(
                effect="ask",
                reason="command is malformed or contains command/process substitution",
            )
        decisions = [self.decide_segment(segment) for segment in segments]
        denied = next((item for item in decisions if item.effect == "deny"), None)
        if denied is not None:
            return denied
        asked = next((item for item in decisions if item.effect == "ask"), None)
        if asked is not None:
            return asked
        return Decision(effect="allow", reason="every shell segment is declared safe")

    def decide_segment(self, segment: ShellSegment) -> Decision:
        words = command_words(segment.words)
        if not words:
            return Decision(effect="ask", reason="shell segment has no command")
        executable = PurePosixPath(words[0]).name
        if executable in INTERPRETERS:
            return Decision(
                effect="deny",
                reason="bare interpreters and inline code are not allowed",
            )
        if executable in READ_ONLY_COMMANDS:
            if executable == "find" and any(
                word in {"-exec", "-ok", "-delete"} for word in words
            ):
                return Decision(effect="ask", reason="find requests a mutating action")
            return Decision(effect="allow")
        if executable == "cd":
            return Decision(effect="allow", reason="directory navigation")
        if executable == "xargs":
            payload = [word for word in words[1:] if not word.startswith("-")]
            if not payload:
                return Decision(effect="ask", reason="xargs payload is not classified")
            return self.decide_segment(ShellSegment(words=payload))
        if executable == "git" and len(words) > 1:
            if words[1] in {
                "status",
                "log",
                "diff",
                "show",
                "branch",
                "worktree",
                "stash",
                "remote",
                "fetch",
                "tag",
                "add",
                "commit",
                "mv",
            }:
                return Decision(effect="allow")
        if executable == "gh" and len(words) > 2:
            if words[1] in {"pr", "issue"} and words[2] in {
                "list",
                "view",
                "diff",
                "status",
            }:
                return Decision(effect="allow")
        if executable == "uvx":
            if len(words) > 1 and PurePosixPath(words[1]).name in INTERPRETERS:
                return Decision(effect="deny", reason="inline code is not allowed")
            return Decision(effect="ask", reason="uvx command is not classified")
        if executable == "uv" and len(words) > 1:
            if words[1] in {"add", "sync"}:
                return Decision(
                    effect="ask",
                    reason="dependency changes fetch and execute external code",
                )
            if words[1] in {"remove", "lock"}:
                return Decision(effect="allow")
            if words[1] == "run" and len(words) > 2:
                run_words = uv_run_words(words)
                if not run_words:
                    return Decision(effect="ask", reason="uv run has no command")
                run_command = PurePosixPath(run_words[0]).name
                script = (
                    run_words[1]
                    if run_command in INTERPRETERS and len(run_words) > 1
                    else run_words[0]
                )
                if is_repository_tmp_script(script):
                    return Decision(effect="allow", reason="declared temporary script")
                if run_command in {"pyright", "pytest", "ruff", "lup-devtools"}:
                    return Decision(effect="allow")
                if len(run_words) == 2 and run_words[1] == "--help":
                    return Decision(effect="allow", reason="command help is read-only")
                if run_command in INTERPRETERS or run_command in {
                    "-c",
                    "-m",
                    "--script",
                }:
                    return Decision(effect="deny", reason="inline code is not allowed")
        return Decision(
            effect="ask", reason=f"command {executable!r} is not classified"
        )


class PathRule(BaseModel):
    """One semantic protected-path match supplied by a concrete composition root."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["exact", "subtree", "name_prefix", "new_subtree"]
    value: str
    reason: str
    allow_autonomous: bool = False


def path_rule_matches(path: Path, rule: PathRule) -> bool:
    portable = PurePosixPath(path.as_posix())
    match rule.kind, rule.value:
        case "exact", str(expected):
            return portable == PurePosixPath(expected)
        case "subtree", str(expected):
            root = PurePosixPath(expected)
            return portable == root or portable.is_relative_to(root)
        case "name_prefix", str(prefix):
            return portable.name.startswith(prefix)
        case "new_subtree", str(expected):
            root = PurePosixPath(expected)
            in_subtree = portable == root or portable.is_relative_to(root)
            return in_subtree and not path.exists()
        case _:
            raise ValueError(f"invalid value for path rule kind {rule.kind!r}")


def added_lines(change: EditChange) -> list[str]:
    """Return new lines that did not appear in the before block."""
    before = change.before.splitlines() if change.before is not None else []
    after = change.after.splitlines() if change.after is not None else []
    remaining = list(before)
    added: list[str] = []  # lup: ignore[empty-collection]
    for line in after:
        if line in remaining:
            remaining.remove(line)
        else:
            added.append(line)
    return added


def added_line_numbers(change: EditChange) -> dict[int, bool]:
    """Identify added line positions while preserving full-file syntax context."""
    before = change.before.splitlines() if change.before is not None else []
    remaining = list(before)
    added: dict[int, bool] = {}  # lup: ignore[empty-collection] — ordered positions
    for number, line in enumerate((change.after or "").splitlines(), start=1):
        if line in remaining:
            remaining.remove(line)
        else:
            added[number] = True
    return added


class EditPolicy(DecisionPolicy[EditBatch]):
    """Apply protected-path, marker, antipattern, deletion, and size gates."""

    def __init__(
        self,
        protected: list[PathRule],
        maximum_added_lines: int = 3,
        autonomous: bool = False,
    ) -> None:
        self.protected = list(protected)
        self.maximum_added_lines = maximum_added_lines
        self.autonomous = autonomous

    def decide(self, event: EditBatch) -> Decision:
        decisions = [self.decide_change(change) for change in event.changes]
        denied = next((item for item in decisions if item.effect == "deny"), None)
        if denied is not None:
            return denied
        asked = next((item for item in decisions if item.effect == "ask"), None)
        if asked is not None:
            return asked
        return Decision(effect="allow", reason="every edit in the batch is safe")

    def decide_change(self, change: EditChange) -> Decision:
        before = change.before or ""
        after = change.after or ""
        if marker_count(before) != marker_count(after):
            return Decision(effect="ask", reason="edit changes inline review markers")
        lines = added_lines(change)
        patterns = patterns_for_suffix(change.path.suffix.lower())
        if patterns is not None:
            added_numbers = added_line_numbers(change)
            missing = next(
                (
                    finding
                    for finding in audit_text(after, patterns)
                    if finding.line in added_numbers and finding.kind == "missing"
                ),
                None,
            )
            if missing is not None:
                return Decision(effect="deny", reason=missing.message)
            context = PythonContext.parse(after)
            after_lines = after.splitlines()
            for number in added_numbers:
                line = after_lines[number - 1]
                directive = IGNORE_RE.search(line)
                if directive is not None and context.comment_at(
                    number, directive.start()
                ):
                    return Decision(
                        effect="ask",
                        reason="edit introduces an antipattern suppression",
                    )
        protected = next(
            (rule for rule in self.protected if path_rule_matches(change.path, rule)),
            None,
        )
        if protected is not None and not (
            self.autonomous and protected.allow_autonomous
        ):
            return Decision(effect="ask", reason=protected.reason)
        if change.before is None:
            if self.autonomous:
                return Decision(effect="allow", reason="reviewed autonomous full write")
            return Decision(effect="ask", reason="full-file writes require approval")
        if change.after is None or change.after == "":
            return Decision(effect="allow", reason="pure deletion")
        if len(lines) > self.maximum_added_lines:
            if self.autonomous:
                return Decision(effect="allow", reason="reviewed autonomous edit")
            return Decision(effect="ask", reason="edit exceeds the small-change gate")
        return Decision(effect="allow", reason="small safe edit")
