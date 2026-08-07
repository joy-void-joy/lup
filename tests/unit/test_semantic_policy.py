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
from pathlib import Path
from types import ModuleType
from typing import Literal

import pytest
import sh
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from lup.adapters.claude.native import (
    ClaudeBeforeToolEvent,
    ClaudeEditBatchOperation,
    ClaudeEventDecoder,
    ClaudeHookPayload,
    ClaudeUnknownOperation,
    ClaudeDecisionRenderer,
    parse_claude_before_tool,
)
from lup.adapters.codex.native import (
    CodexBeforeToolEvent,
    CodexEventDecoder,
    CodexFileChange,
    CodexFileChangeOperation,
    CodexUnknownOperation,
    CodexDecisionRenderer,
)
from lup.harness.enforcement import declared_path_rules
from lup.policy.chain import UnknownToolPolicy
from lup.policy.bundle import (
    bundled_antipattern_rows,
    policy_kernel_modules,
    render_policy_data,
    runtime_path_rules,
    runtime_url_scope,
)
from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.edit import decide_edit
from lup.policy.kernel.rows import PathRoleRow
from lup.policy.kernel.lex import shell_write_targets
from lup.policy.models import (
    Decision,
    EditBatch,
    EditChange,
    FetchUrl,
    ShellCommand,
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

from lup_template.devtools.harness.catalog import portable_harness
from lup_template.devtools.harness.content.shell_vocabulary import SHELL_RULES


class DecisionCase(BaseModel):
    """One primitive input and its expected policy effect."""

    model_config = ConfigDict(frozen=True)

    input: str
    effect: Literal["allow", "ask", "deny", "defer"]
    sandboxed: bool = False
    interactive: bool = True
    existing: list[str] = Field(default_factory=list)
    """Repository-relative files that already exist when the case is judged."""


class EditDecisionCase(BaseModel):
    """One edit fixture shared by canonical and assembled policy forms."""

    model_config = ConfigDict(frozen=True)

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
    PathRoleRow(root="tmp", role="scratch"),
]

FIXTURE_RECOVERABLE_LIMIT = 5
FIXTURE_RUNNER_TARGETS = ["pyright", "pytest", "ruff", "lup-devtools"]
"""What this project declares `uv run <target>` may reach, which is what the
shell fixtures below are written against."""
"""How many restorable files one command may destroy before it asks."""

SHELL_POLICY_CASES = [
    DecisionCase(input="env MODE=test python script.py", effect="deny"),
    DecisionCase(input="uv run --with requests python -c 'x'", effect="deny"),
    # A scratch root is gitignored, so a script there reaches no reviewer and
    # no diff; the escalation ladder routes one-off work to devtools instead.
    DecisionCase(input="uv run pytest | uv run python tmp/oneoff.py", effect="deny"),
    DecisionCase(input="uv run python tmp/oneoff.py", effect="deny"),
    DecisionCase(input="find . -name '*.py' | xargs grep TODO", effect="allow"),
    DecisionCase(input="echo x | xargs rm -rf", effect="ask"),
    DecisionCase(input="cd /tmp/worktree && uv run pytest", effect="allow"),
    DecisionCase(input="git status\ncurl https://example.com", effect="ask"),
    DecisionCase(input="find . -name '*.tmp' -delete", effect="ask"),
    DecisionCase(input="cat x |& rm -rf ~", effect="ask"),
    DecisionCase(input="cat x ;& rm -rf ~", effect="deny"),
    DecisionCase(
        input="echo payload > pyproject.toml",
        effect="ask",
        existing=["pyproject.toml"],
    ),
    DecisionCase(
        input="echo payload >> src/generated.py",
        effect="ask",
        existing=["src/generated.py"],
    ),
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
    # Overwriting an existing file is the destructive case and asks; creating
    # one destroys nothing, and a target that cannot be resolved to a literal
    # path keeps the strict verdict rather than guessing it is new.
    DecisionCase(input="echo x > out.txt", effect="ask", existing=["out.txt"]),
    DecisionCase(input="echo x > out.txt", effect="allow"),
    DecisionCase(input="echo x > nested/new.txt", effect="allow"),
    DecisionCase(input="echo x >> notes.log", effect="allow"),
    DecisionCase(input="echo x > $UNSET_DIR/out.txt", effect="ask"),
    DecisionCase(input="echo x > ~/out.txt", effect="ask"),
    DecisionCase(input="cat <<EOF", effect="deny"),
    # The session scratchpad is a write-allowed root like repo-relative tmp/;
    # reassigning TMPDIR is a security-sensitive assignment, and a suffix that
    # climbs out of the root falls back to the ordinary redirection rule —
    # which still asks whenever the target cannot be resolved to a literal.
    DecisionCase(input="echo x > $TMPDIR/out.txt", effect="allow"),
    DecisionCase(input='sort f > "${TMPDIR}/sorted.txt"', effect="allow"),
    DecisionCase(input="echo x > /tmp/claude-1000/scratch/out.txt", effect="allow"),
    DecisionCase(input="cat <<'EOF' > $TMPDIR/notes.md\nbody\nEOF", effect="allow"),
    DecisionCase(input="echo x > $TMPDIR/../etc/crontab", effect="ask"),
    DecisionCase(input="echo x > /tmp/claude-1000/../shadow", effect="allow"),
    # A /tmp path outside the session root is not scratch, so it follows the
    # ordinary create-versus-overwrite rule rather than being written freely.
    DecisionCase(input="echo x > /tmp/other/file", effect="allow"),
    DecisionCase(input="TMPDIR=/etc; echo x > $TMPDIR/passwd", effect="ask"),
    DecisionCase(input="for TMPDIR in /etc; do echo x > $TMPDIR/f; done", effect="ask"),
    # Housekeeping confined to the disposable roots is as safe as writing
    # them; any long flag, opaque word, or outside target keeps the verb's ask.
    DecisionCase(input="rm tmp/oneoff.py", effect="allow"),
    DecisionCase(input="rm -rf tmp/scratch", effect="allow"),
    DecisionCase(input="rm -f $TMPDIR/out.txt", effect="allow"),
    DecisionCase(input="rm /tmp/claude-1000/scratch/f", effect="allow"),
    DecisionCase(input="rm tmp/x src/y", effect="ask"),
    DecisionCase(input="rm tmp/../src/x.py", effect="ask"),
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
    # An empty directory anywhere, unlike the file beside it: `mkdir` cannot
    # overwrite and leaves nothing to run, so what lands inside is judged on
    # its own path rather than the directory being refused up front.
    DecisionCase(input="mkdir src/newpkg", effect="allow"),
    DecisionCase(input="touch src/newfile.py", effect="ask"),
    DecisionCase(input="cp --archive tmp/a tmp/b", effect="ask"),
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
    DecisionCase(input="echo $(git push)", effect="ask"),
    DecisionCase(input="echo $(rm -rf /)", effect="ask"),
    DecisionCase(input="git log $(cat names.txt)", effect="deny"),
    DecisionCase(input="F=$(ls); sed $F 's/a/b/' f", effect="deny"),
    DecisionCase(input="$(which ls) -la", effect="deny"),
    DecisionCase(input="echo $(echo $(echo $(ls)))", effect="deny"),
    DecisionCase(input="echo $(ls", effect="deny"),
    DecisionCase(input="echo `id`", effect="deny"),
    # Read-side process substitution classifies its inner command recursively;
    # the write side still asks and a substituting inner command is denied.
    DecisionCase(input="diff <(git status) <(git log)", effect="allow"),
    DecisionCase(input="diff <(sudo id) f", effect="ask"),
    DecisionCase(input="diff <(cat $(x)) f", effect="deny"),
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
    DecisionCase(input="for x in -i; do sed \"$x\" 's/a/b/' f; done", effect="deny"),
    DecisionCase(input='for f in *.txt; do sort "$f"; done', effect="deny"),
    DecisionCase(input='for f in a; do python "$f"; done', effect="deny"),
    DecisionCase(input='for f in a; do wc "$f"', effect="deny"),
    DecisionCase(input="while do done", effect="deny"),
    DecisionCase(input='for f a; do wc "$f"; done', effect="deny"),
    # Expanded read-only vocabulary with writer-flag guards.
    DecisionCase(input="sort f", effect="allow"),
    DecisionCase(input="sort -o out f", effect="ask"),
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
    DecisionCase(input="yq -i '.a = 1' f", effect="ask"),
    DecisionCase(input="xmllint --noout f", effect="allow"),
    DecisionCase(input="xmllint -output out f", effect="ask"),
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
    DecisionCase(input="git push --force", effect="ask"),
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
    # Read verbs pin git config to its query action; writes, scoped writes,
    # and opaque words keep the row's ask.
    DecisionCase(input="git config --get user.name", effect="allow"),
    DecisionCase(input="git config --get-regexp 'branch\\..*'", effect="allow"),
    DecisionCase(input="git config --list", effect="allow"),
    DecisionCase(input="git config -l", effect="allow"),
    DecisionCase(input="git config user.name me", effect="ask"),
    DecisionCase(input="git config --unset user.name", effect="ask"),
    DecisionCase(input="git config --global user.name me", effect="ask"),
    DecisionCase(input="git config --get $KEY", effect="ask"),
    # Global value flags are consumed, never read as the subcommand; globals
    # that change execution behavior ask.
    DecisionCase(input="git -C /other status", effect="allow"),
    DecisionCase(input="git -C status push", effect="ask"),
    DecisionCase(input="git -c core.pager=touch log", effect="ask"),
    DecisionCase(input="git --exec-path=/tmp/x status", effect="ask"),
    # Exec-bearing and file-writing flags on allowed subcommands ask.
    DecisionCase(input="git rebase --exec 'touch x' HEAD~2", effect="ask"),
    DecisionCase(input="git fetch --upload-pack=/tmp/x origin", effect="ask"),
    DecisionCase(input="git grep -Ovim pattern", effect="ask"),
    DecisionCase(input="git log --output=/tmp/f", effect="ask"),
    DecisionCase(input="git reflog", effect="allow"),
    DecisionCase(input="git reflog expire --expire=now --all", effect="ask"),
    DecisionCase(input="git push", effect="ask"),
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
    DecisionCase(input="git bisect start", effect="deny"),
    DecisionCase(input="sort --compress-program=/tmp/x f", effect="ask"),
    # gh: read-only operations allow; mutating forms ask.
    DecisionCase(input="gh run view 1", effect="allow"),
    DecisionCase(input="gh repo view", effect="allow"),
    DecisionCase(input="gh pr close 1", effect="ask"),
    DecisionCase(input="gh api -X POST /repos", effect="ask"),
    DecisionCase(input="gh pr create --title x", effect="ask"),
    DecisionCase(input="gh pr checkout 123", effect="allow"),
    DecisionCase(input="gh auth status", effect="allow"),
    DecisionCase(input="gh secret list", effect="deny"),
    # Adversarial hardening: no auto-allowed code execution or injection.
    DecisionCase(input="sudo cat /etc/shadow", effect="ask"),
    DecisionCase(input="LD_PRELOAD=./x.so ls", effect="ask"),
    DecisionCase(input="GIT_SSH_COMMAND=./x git fetch origin", effect="ask"),
    DecisionCase(input="git fetch ext::sh -c id", effect="ask"),
    DecisionCase(input="uv run --with evil pytest", effect="ask"),
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
    # The decision lattice: unjudged commands deny and bounce to the agent,
    # judged-risky rows ask, and a leading escalation marker promotes a deny
    # or ask to an approval question carrying the agent's stated reason.
    DecisionCase(input="cargo build", effect="deny"),
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
    DecisionCase(input="rm -rf build", effect="ask"),
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
    # A heredoc rewriting an existing file is shell file authoring over work
    # the edit gate already saw: deny toward the Edit tool and tmp/*.py in
    # both operator orders, even sandboxed. Authoring a file that is not
    # there yet overwrites nothing and passes.
    DecisionCase(
        input="cat > out.py <<'EOF'\nbody\nEOF", effect="deny", existing=["out.py"]
    ),
    DecisionCase(
        input="cat <<'EOF' > out.py\nbody\nEOF", effect="deny", existing=["out.py"]
    ),
    DecisionCase(
        input="cat > out.py <<'EOF'\nbody\nEOF",
        effect="deny",
        sandboxed=True,
        existing=["out.py"],
    ),
    DecisionCase(input="cat > fresh.py <<'EOF'\nbody\nEOF", effect="allow"),
    DecisionCase(input="cat > tmp/oneoff.py <<'EOF'\nbody\nEOF", effect="allow"),
    # Frozen variable bindings: assignments and read rebind for the segments
    # that follow; literal values instantiate references, opaque ones gate
    # guarded rows, and unresolved expansions deny toward explicit binding.
    DecisionCase(input="x=5", effect="allow"),
    DecisionCase(input="f=notes.txt; sort $f", effect="allow"),
    DecisionCase(input="f=-o; sort $f x", effect="ask"),
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
    # Sandboxed executions: machinery bail-outs defer to the OS boundary,
    # judged decisions hold, and escalation still promotes to a question.
    DecisionCase(input="frobnicate --weird", effect="deny"),
    DecisionCase(input="frobnicate --weird", effect="defer", sandboxed=True),
    DecisionCase(input="sed --frob 's/a/b/' f", effect="defer", sandboxed=True),
    DecisionCase(input="sort $UNBOUND f", effect="defer", sandboxed=True),
    DecisionCase(input="foo() { cat x; }", effect="defer", sandboxed=True),
    DecisionCase(input="case $m in a) echo a;;", effect="defer", sandboxed=True),
    DecisionCase(input="git push --force", effect="ask", sandboxed=True),
    DecisionCase(input="sed -i 's/a/b/' f", effect="deny", sandboxed=True),
    DecisionCase(input="ssh-add -D", effect="deny", sandboxed=True),
    DecisionCase(input="frobnicate; ssh host", effect="ask", sandboxed=True),
    DecisionCase(input="python -c 'x'", effect="deny", sandboxed=True),
    # A help probe only prints usage, so it reads an unclassified command
    # without judging it. Bare -h counts alone; carrying a value it is an
    # ordinary argument (mysql -h host) and classifies normally.
    DecisionCase(input="frobnicate --help", effect="allow"),
    DecisionCase(input="codex plugin marketplace --help", effect="allow"),
    DecisionCase(input="git push --help", effect="allow"),
    DecisionCase(input="frobnicate -h", effect="allow"),
    DecisionCase(input="mysql -h db.example.com", effect="deny"),
    # A non-interactive host cannot put a question to a human: sandboxed, an
    # ask rides the OS boundary; unsandboxed it fails closed. A judged deny
    # is never rescued, and unjudged work defers exactly as it always did.
    DecisionCase(input="git push --force", effect="deny", interactive=False),
    DecisionCase(
        input="git push --force", effect="defer", sandboxed=True, interactive=False
    ),
    DecisionCase(input="PYTHONPATH=src uv run pytest", effect="ask"),
    DecisionCase(
        input="PYTHONPATH=src uv run pytest",
        effect="defer",
        sandboxed=True,
        interactive=False,
    ),
    DecisionCase(
        input="sed -i 's/a/b/' f", effect="deny", sandboxed=True, interactive=False
    ),
    DecisionCase(
        input="frobnicate --weird", effect="defer", sandboxed=True, interactive=False
    ),
    # The classic sourcing bypasses stay outside the vocabulary: deny
    # unsandboxed, defer to the OS boundary inside it; a deferring segment
    # among allows keeps the batch deferred.
    DecisionCase(input="eval echo x", effect="deny"),
    DecisionCase(input="source setup.sh", effect="deny"),
    DecisionCase(input=". ./env.sh", effect="deny"),
    DecisionCase(input="eval echo x", effect="defer", sandboxed=True),
    DecisionCase(input="source setup.sh", effect="defer", sandboxed=True),
    DecisionCase(input="frobnicate; ls", effect="defer", sandboxed=True),
    DecisionCase(input="echo $(whoami)", effect="allow", sandboxed=True),
    DecisionCase(input="echo $(frobnicate)", effect="deny"),
    DecisionCase(input="echo $(frobnicate)", effect="defer", sandboxed=True),
    DecisionCase(input="git log $(cat names.txt)", effect="defer", sandboxed=True),
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
        path="downstream.json",
        before='{"projects": []}',
        after='{"projects": [{"name": "fleet-app"}]}',
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
                "downstream.json",
            ],
            human_owned_files=["README.md"],
            autonomous_agent_identities=["resolver-worker"],
            path_roles=FIXTURE_PATH_ROLES,
            shell_rules=SHELL_RULES,
            recoverable_target_limit=FIXTURE_RECOVERABLE_LIMIT,
            runner_targets=FIXTURE_RUNNER_TARGETS,
        ),
        encoding="utf-8",
    )
    fixtures = runtime / "fixtures.json"
    fixtures.write_text(
        json.dumps(
            {
                "shell": [item.model_dump() for item in SHELL_POLICY_CASES],
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
        "    MAXIMUM_ADDED_LINES, PATH_ROLES, PATH_RULES, RUNNER_TARGETS,\n"
        "    SHELL_RULES,\n"
        ")\n"
        "fixtures = json.loads(\n"
        "    (Path(__file__).parent / 'fixtures.json').read_text(encoding='utf-8')\n"
        ")\n"
        "for case in fixtures['shell']:\n"
        "    result = decide_shell(\n"
        "        case['input'], SHELL_RULES, sandboxed=case['sandboxed'],\n"
        "        interactive=case['interactive'],\n"
        "        path_roles=PATH_ROLES,\n"
        "        existing_targets=case['existing'],\n"
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
        "    )\n"
        "    assert decision.effect == case['effect'], case\n",
        encoding="utf-8",
    )

    sh.Command("python3")("-I", "-S", str(probe))


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


def test_malformed_native_fetch_urls_become_conservative_unknown_tools() -> None:
    from lup.adapters.claude.native import ClaudeFetchOperation
    from lup.adapters.codex.native import CodexFetchOperation

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
    assert effect("curl -sI https://docs.example.com/") == "deny"
    assert effect("curl -s -I https://docs.example.com/") == "allow"
    assert effect("curl -s https://internal.example.com/x") == "deny"
    assert effect("curl -s https://elsewhere.example.com/") == "ask"
    assert effect("curl -X DELETE https://docs.example.com/api") == "ask"
    assert effect("curl -d a=b https://docs.example.com/api") == "deny"


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
    assert policy.decide(ShellCommand(command="echo $(dangerous)")).effect == "deny"


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
        runner_targets=FIXTURE_RUNNER_TARGETS,
    )
    sandboxed_policy = ShellPolicy(
        SHELL_RULES,
        sandbox_active=True,
        path_roles=FIXTURE_PATH_ROLES,
        runner_targets=FIXTURE_RUNNER_TARGETS,
    )

    for index, case in enumerate(SHELL_POLICY_CASES):
        if case.interactive:
            active = sandboxed_policy if case.sandboxed else policy
        else:
            active = ShellPolicy(
                SHELL_RULES,
                sandbox_active=case.sandboxed,
                interactive=False,
                path_roles=FIXTURE_PATH_ROLES,
                runner_targets=FIXTURE_RUNNER_TARGETS,
            )
        # Each case judges a tree of its own, so a file one case declares
        # present never leaks into the next case's create-versus-overwrite.
        root = tmp_path / f"case{index}"
        root.mkdir()
        for name in case.existing:
            present = root / name
            present.parent.mkdir(parents=True, exist_ok=True)
            present.write_text("already here", encoding="utf-8")
        decided = active.decide(ShellCommand(command=case.input, cwd=root))
        assert decided.effect == case.effect, case.input
        bundled_effect = bundled.decide_shell(
            case.input,
            policy.rules,
            sandboxed=case.sandboxed,
            interactive=case.interactive,
            path_roles=FIXTURE_PATH_ROLES,
            existing_targets=case.existing,
            runner_targets=FIXTURE_RUNNER_TARGETS,
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


def test_creating_a_file_passes_where_overwriting_one_still_asks(
    tmp_path: Path,
) -> None:
    policy = ShellPolicy(SHELL_RULES)
    existing = tmp_path / "kept.txt"
    existing.write_text("prior work", encoding="utf-8")
    command = "echo x > kept.txt"

    assert policy.decide(ShellCommand(command=command, cwd=tmp_path)).effect == "ask"
    existing.unlink()
    assert policy.decide(ShellCommand(command=command, cwd=tmp_path)).effect == "allow"


def test_sandbox_escape_reenters_the_deny_lattice() -> None:
    policy = ShellPolicy(SHELL_RULES, sandbox_active=True)
    confined = policy.decide(ShellCommand(command="frobnicate --weird"))
    assert confined.effect == "defer"
    escaped = policy.decide(
        ShellCommand(command="frobnicate --weird", unsandboxed=True)
    )
    assert escaped.effect == "deny"
    assert "escalate" in escaped.reason


def test_non_interactive_denials_do_not_prescribe_escalation() -> None:
    """Codex hooks cannot complete the approval flow, so they never name it."""
    interactive = ShellPolicy(SHELL_RULES).decide(
        ShellCommand(command="git push --force")
    )
    assert interactive.effect == "ask"

    blocked = ShellPolicy(SHELL_RULES, interactive=False).decide(
        ShellCommand(command="git push --force")
    )
    assert blocked.effect == "deny"
    assert "escalate" not in blocked.reason
    assert "allowed vocabulary" in blocked.reason


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


def test_only_the_review_pass_retires_a_claim() -> None:
    """A claim is checked by someone other than whoever made it."""
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
        == "allow"
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

    A route decorator trips the `dict-get` regex and nothing else, so before
    the refiner the audit called the marker spurious while the kernel denied
    every edit that removed it — a change one gate required and the other
    forbade, with no operation in between.
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
    """A prompt carries the reason and nothing else, so it has to locate the line."""
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
    assert "line 2: first: Any = 1  # lup: ignore[any-type]" in decision.reason
    assert "line 3: second: Any = 2  # lup: ignore[any-type]" in decision.reason


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
            value="downstream.json",
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
                value="downstream.json",
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
            [".claude", "pyproject.toml", "sync.json", "downstream.json"],
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
    path = Path("src/lup_template/devtools/harness/content/skills/commit.py")
    before = path.read_text(encoding="utf-8")
    after = before + (
        '\nPROSE_GATE_EXAMPLE = """Any and # lup: examples remain prose."""\n'
    )

    decision = EditPolicy(protected=[]).decide(
        EditBatch(changes=[EditChange(path=path, before=before, after=after)])
    )

    assert decision.effect == "allow"
