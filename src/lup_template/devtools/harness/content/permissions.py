"""Canonical permission-policy mechanism reference.

Rendered to ``docs/permissions.md`` rather than the always-loaded guidance:
the dispatcher denies at the moment of violation and its message already
names the recovery, so the full lattice is reference material. The two
markers an agent needs *before* it can open this file — ``# lup: escalate``
and ``# lup: ignore`` — stay in the guidance itself.
"""

import lup.harness.models as models

DOCUMENT = models.PromptDocument(
    parts=[
        models.TextPart(
            text=r"""<!-- Generated from src/lup_template/devtools/harness/content/permissions.py via `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/generated-artifacts.md. -->

# Permission Policy

How the generated hooks decide allow, ask, defer, or deny. For the daily
summary and the escalation syntax, see
[.claude/CLAUDE.md](../.claude/CLAUDE.md) § Permission Hooks; for the
decision flow, see [architecture.md](architecture.md) § Permission policy flow.

## Sources of truth

Permissions come from the canonical semantic policies in `lup.policy` and the
application-owned `HookSet` in `devtools/harness/catalog.py`. Harness
generation compiles one hermetic dispatcher and runtime for each native
plugin. Never edit generated dispatcher or runtime files — change the
canonical source and regenerate.

## Shell classification

The policy classifies each shell command against the vocabulary in
`devtools/harness/content/shell_vocabulary.py`, every URL scope, and each edit
in a batch. `lup.policy.shell_rules` owns the shape that table takes and its
erasure into the rows the kernel reads, never the words. The shell
lattice reserves ask for judged risk; unjudged work denies, hinting the
escalation recipe. Under a launcher-verified OS sandbox
(`LUP_SANDBOX_ACTIVE`), unjudged work defers to that boundary, and a
`dangerouslyDisableSandbox` escape re-enters the deny lattice; the sandbox
block derives from the same `HookSet` declaration.

Segments join deny > ask > defer > allow — unjudged rides into a judged
prompt, a judged deny wins the batch. Malformed input fails conservatively.

`$(...)` classifies recursively — the inner command joins the batch and its
opaque result rides only argument-safe commands; command position, deep
nesting, and backticks stay conservative. File writes (redirection, `rm`)
auto-allow only into repo `tmp/` and the scratchpad (`$TMPDIR`,
`/tmp/claude-*`; reassigning `TMPDIR` asks); discards and fd dups strip;
heredoc-fed writes deny toward Edit/tmp scripts. Loops, conditionals, case
arms, subshells, and brace groups classify recursively over frozen bindings —
literal assignments instantiate, opaque ones (`read`, globs) gate
flag-guarded commands. `find -exec` payloads and `timeout`/`nice` wrappers
recurse, `sed`/`awk` pass read-only screens, quoted-delimiter heredocs are
literal data, and `curl` is read-screened within the declared fetch scopes.

## Fetch scopes

One declared origin table feeds both `WebFetch` and the `curl` screen. A
scope may opt into its subdomains, which also contributes the `*.host`
wildcard to the OS sandbox network allowlist, so both boundaries admit the
same set. Declare any origin an agent should be able to read as a fetch
scope; reserve the sandbox's `extra_domains` for hosts that need egress
without being readable sources.

## Edit decisions

Edit decisions cover protected paths, marker changes, size, and the canonical
anti-pattern audit. An edit over the size gate alone is deferred — the hook
emits no decision, so auto-accept applies while hard gates stay explicit. The
resolver's worker receives only its declared autonomous edit exceptions;
temporary paths, human-owned files like `README.md`, marker changes, and
anti-pattern violations retain their guardrails in every mode.

Autonomy follows the identity a launcher declares for the session it starts,
carried in the environment and matched against the resolver's own
`worker_identity`, so it reaches a top-level worker session on either runtime
rather than only a natively dispatched subagent. A session that is not
autonomous declares the empty identity rather than staying silent: runtimes
merge a session's environment over the launching process's, so silence would
inherit whatever the operator had exported. A hook script is spawned by the
runtime with the runtime's environment, so an agent exporting the variable
inside a shell tool call never reaches the dispatcher that judges it.
"""
        ),
    ]
)
