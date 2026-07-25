"""Library-side validated policies that erase into kernel rows to decide.

Each policy (shell, fetch, edit) validates its configuration as pydantic
surfaces — URL scopes, path rules, the canonical anti-pattern set — then
flattens them into primitive rows and delegates every verdict to
:mod:`lup.policy.kernel`. :mod:`lup.policy.bundle` performs the same erasure
at generation time, which is how this layer and the generated dispatchers
stay decision-identical; the shared fixture suite asserts exactly that.
"""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from lup.codescan.antipatterns import patterns_for_suffix
from lup.policy.contracts import DecisionPolicy
from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.edit import (
    decide_edit,
    path_rule_matches as kernel_path_rule_matches,
)
from lup.policy.kernel.fetch import decide_fetch
from lup.policy.kernel.lex import parse_shell_words, shell_write_targets
from lup.policy.kernel.rows import AntiPatternRow, PathRuleRow, UrlScopeRow
from lup.policy.kernel.shell import decide_shell, decide_shell_segment
from lup.policy.kernel.words import command_words as kernel_command_words
from lup.policy.shell_rules import (
    BASE_SHELL_RULES,
    ShellCommandRule,
    erase_shell_rules,
)
from lup.policy.models import (
    Decision,
    EditBatch,
    EditChange,
    FetchUrl,
    ShellCommand,
    UrlPathPrefix,
)


def pydantic_decision(decision: KernelDecision) -> Decision:
    """Restore the validated public decision at the kernel boundary."""
    return Decision(effect=decision.effect, reason=decision.reason)


class UrlScope(BaseModel):
    """One normalized scheme/host/port and path-prefix rule."""

    model_config = ConfigDict(frozen=True)

    origin: AnyHttpUrl
    path_prefix: UrlPathPrefix = "/"
    reason: str = ""
    include_subdomains: bool = False


def url_scope_row(scope: UrlScope) -> UrlScopeRow:
    """Erase a validated URL scope into the kernel's primitive row."""
    parsed = urlsplit(str(scope.origin))
    if parsed.hostname is None:
        raise ValueError("validated URL scope has no hostname")
    return UrlScopeRow(
        scheme=parsed.scheme,
        host=parsed.hostname,
        port=parsed.port,
        path_prefix=scope.path_prefix,
        reason=scope.reason,
        include_subdomains=scope.include_subdomains,
    )


class FetchPolicy(DecisionPolicy[FetchUrl]):
    """Evaluate deny scopes before allow scopes and ask on everything else."""

    def __init__(self, allowed: list[UrlScope], denied: list[UrlScope]) -> None:
        self.allowed = list(allowed)
        self.denied = list(denied)

    def decide(self, event: FetchUrl) -> Decision:
        return pydantic_decision(
            decide_fetch(
                str(event.url),
                [url_scope_row(scope) for scope in self.allowed],
                [url_scope_row(scope) for scope in self.denied],
            )
        )


class ShellSegment(BaseModel):
    """One parsed command segment with its ordered shell words."""

    model_config = ConfigDict(frozen=True)

    words: list[str] = Field(min_length=1)


def command_words(words: list[str]) -> list[str]:
    """Expose effective-command parsing for compatibility consumers."""
    return kernel_command_words(words)


def parse_shell_segments(command: str) -> list[ShellSegment] | None:
    """Expose validated segment models for compatibility consumers."""
    segments = parse_shell_words(command)
    if isinstance(segments, KernelDecision):
        return None
    return [ShellSegment(words=words) for words in segments]


class ShellPolicy(DecisionPolicy[ShellCommand]):
    """Delegate shell classification to the shared hermetic kernel.

    URL scopes feed the kernel's curl screen, so shell reads and WebFetch
    consult one declared origin table.
    """

    def __init__(
        self,
        rules: list[ShellCommandRule] | None = None,
        allowed_urls: list[UrlScope] | None = None,
        denied_urls: list[UrlScope] | None = None,
        sandbox_active: bool = False,
        trusted_script_roots: list[str] | None = None,
        interactive: bool = True,
    ) -> None:
        self.rules = erase_shell_rules(BASE_SHELL_RULES if rules is None else rules)
        self.allowed_scopes = [url_scope_row(scope) for scope in allowed_urls or []]
        self.denied_scopes = [url_scope_row(scope) for scope in denied_urls or []]
        self.sandbox_active = sandbox_active
        self.trusted_script_roots = trusted_script_roots or []
        self.interactive = interactive

    def decide(self, event: ShellCommand) -> Decision:
        root = event.cwd or Path.cwd()
        return pydantic_decision(
            decide_shell(
                event.command,
                self.rules,
                self.allowed_scopes,
                self.denied_scopes,
                sandboxed=self.sandbox_active and not event.unsandboxed,
                trusted_script_roots=self.trusted_script_roots,
                interactive=self.interactive,
                existing_targets=[
                    target
                    for target in shell_write_targets(event.command)
                    if (root / target).exists()
                ],
            )
        )

    def decide_segment(self, segment: ShellSegment) -> Decision:
        return pydantic_decision(
            decide_shell_segment(
                segment.words,
                self.rules,
                self.allowed_scopes,
                self.denied_scopes,
                self.trusted_script_roots,
            )
        )


class PathRule(BaseModel):
    """One semantic protected-path match supplied by a composition root."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["exact", "subtree", "name_prefix", "new_subtree"]
    value: str
    reason: str
    allow_autonomous: bool = False


def path_rule_row(rule: PathRule) -> PathRuleRow:
    """Erase one validated path rule into the kernel's primitive row."""
    return PathRuleRow(
        kind=rule.kind,
        value=rule.value,
        reason=rule.reason,
        allow_autonomous=rule.allow_autonomous,
    )


def human_owned_path_rule(path: str) -> PathRule:
    """Declare one human-owned file whose edits always require approval."""
    return PathRule(
        kind="exact",
        value=path,
        reason=(
            f"{path} is human-authored; propose changes via AskUserQuestion"
            " instead of editing"
        ),
    )


def path_rule_matches(path: Path, rule: PathRule) -> bool:
    """Compare a path with one rule through the canonical kernel matcher."""
    return kernel_path_rule_matches(path.as_posix(), path.exists(), path_rule_row(rule))


def antipattern_rows(change: EditChange) -> list[AntiPatternRow]:
    """Compile rules selected by one edit path into primitive kernel rows."""
    patterns = patterns_for_suffix(change.path.suffix.lower())
    if patterns is None:
        return []
    return [
        AntiPatternRow(
            id=rule.id,
            pattern=rule.pattern.pattern,
            message=rule.message,
            context=rule.context,
        )
        for rule in patterns
    ]


class EditPolicy(DecisionPolicy[EditBatch]):
    """Apply the shared marker, anti-pattern, path, deletion, and size gates."""

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
        deferred = next((item for item in decisions if item.effect == "defer"), None)
        if deferred is not None:
            return deferred
        return Decision(effect="allow", reason="every edit in the batch is safe")

    def decide_change(self, change: EditChange) -> Decision:
        suffix = change.path.suffix.lower()
        return pydantic_decision(
            decide_edit(
                change.path.as_posix(),
                change.before,
                change.after,
                path_exists=change.path.exists(),
                path_rules=[path_rule_row(rule) for rule in self.protected],
                antipattern_rows=antipattern_rows(change),
                maximum_added_lines=self.maximum_added_lines,
                autonomous=self.autonomous,
                python_source=suffix in (".py", ".pyi"),
            )
        )
