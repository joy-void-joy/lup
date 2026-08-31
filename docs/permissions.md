<!-- Generated from lup.devtools.harness.content.docs.permissions by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# Permission Policy

How the generated hooks decide allow, ask, defer, or deny, and the two
markers that change a decision. The guidance carries the rule; this page
carries the mechanism a denial sends you to.

## Sources of truth

Permissions come from the canonical semantic policies in `lup.policy` and the
application-owned `HookSet` in `devtools/harness/catalog.py`. Harness
generation compiles one hermetic dispatcher and runtime for each native
plugin. Never edit generated dispatcher or runtime files — change the
canonical source and regenerate.

## Shell classification

The policy classifies each shell command against
`lup.policy.vocabulary.default_vocabulary` as
`devtools/harness/content/shell_vocabulary.py` selects it, every URL scope,
and each edit in a batch. `lup.policy.shell_rules` owns the shape that table
takes and its erasure into the rows the kernel reads, never the words; the
project states only where it differs from what the library offers — a
downstream toolchain to add, a command it judges differently, one it drops —
so declaring `lake` costs one entry rather than a copy of every command the
library already judged. The shell
lattice reserves ask for judged risk; unjudged work denies, hinting the
escalation recipe. Under a launcher-verified OS sandbox
(`LUP_SANDBOX_ACTIVE`), unjudged work defers to that boundary, and a
`dangerouslyDisableSandbox` escape re-enters the deny lattice; the sandbox
block derives from the same `HookSet` declaration. A command the sandbox's
`excluded_commands` takes out of isolation re-enters it too, without the
escape: the boundary was told to leave that command alone, so there is
nothing for unjudged work to defer to.

Segments join deny > ask > defer > allow — unjudged rides into a judged
prompt, a judged deny wins the batch. Malformed input fails conservatively.

What the classified verdict then becomes is a second, ordered pass, declared
as an order rather than written as a branch. `policy/kernel/settlement.py`
holds one row per rule, read the way `.gitignore` reads patterns: every row is
offered the running verdict, a row that rewrites hands its result to the next,
and the first row that settles ends the pass. So a statement about precedence
— *a stated reason never leaves a refusal standing*, *a judged deny is not
rescued by a boundary*, *a question nobody can answer is no judgment* — is one
row that says it, and changing the policy is moving, adding, or dropping one.
The rows, in order, each stating its own claim:

| row | what it says |
| --- | --- |
| `ContainedPlacement` | A container is the place every placement was asking for. |
| `StatedReason` | A marker turns anything not already permitted into a question. |
| `TrappedPlacement` | A call declared ``outside`` on a host that cannot place it there. |
| `RestoredBySession` | An approval question about a loss this session can already put back. |
| `UnanswerableQuestion` | A question on a host with nobody to put it to is not a question. |
| `ConfinedElsewhere` | No judgment, and a boundary beneath it: the boundary carries it. |
| `Unjudged` | No judgment and no boundary: whoever can answer it, answers it. |
| `JudgedRefusal` | A rule refused this, and no sandbox rescues a judged deny. |
| `Standing` | Whatever reached here stands: a permission, or an answerable question. |

Where a command runs is a second axis beside that verdict, declared per rule
rather than inferred: `git` states its placement once and every verb beneath
it runs outside the sandbox, because one confined away from its transport or
from the repository's own locks fails however freely it was allowed. An
allow placed outside runs there unprompted; an ask placed outside says so in
the question it asks; a deny short-circuits the axis entirely, and so does a
defer, which hands the sandbox status over with the rest of the decision.
Confinement wins a join, so one segment that must stay inside keeps the whole
line inside. A runtime with no per-call sandbox renders the plain effect. A
container answers the axis rather than trapping on it: `outside` names the
native per-call sandbox, a container runs none, and the paths that placement
was about — the runtime's configuration home, the repository's locks, a route
to a remote — are all the container's own.

**Recovery** is the third axis, and the one that makes the effect a function
of the session rather than of the command. The vocabulary guards *the
direction that removes something no second attempt restores*, and what a
second attempt restores depends on what is running beneath it — so each rule
names the restorer its question was about:

| value | what puts the loss back | what carries it |
|---|---|---|
| `snapshot` | the whole loss is working-tree content in this checkout | the undo layer, container or not — `git reset --hard`, `git restore`, `git rm` |
| `container` | the loss can also land on this machine | a container *and* the snapshot beneath it, because the bind-mounted checkout survives the container — `rm`, `tar`, `apt install`, `systemctl` |
| `nothing` | neither reaches it | nothing, so the question stands — a remote ref, a published artifact, a command whose argument is another command, and the parts of this checkout no snapshot holds |

`nothing` is the default and the whole safety of the axis: a rule nobody
annotated keeps asking. `git clean -fdx` carries it deliberately rather than
by omission — it destroys ignored files, which is exactly what the snapshot
leaves out.

Where the named restorer is present, `RestoredBySession` settles the question
as a **deferral, not a permission**. Nothing decides the call may run: the
policy decides it has no reason left to interrupt, and the call goes to the
runtime's own gate, where an operator's configuration lives. A session run
with everything approved runs it; one at the runtime's defaults is still
asked, in the runtime's own words. A `# lup: escalate:` marker keeps its
question either way — it is the agent asking to be judged, and a boundary
does not overrule it.

That makes `defer` two things reaching one word, which the rows below it have
to keep apart: an unjudged deferral means *nobody looked*, and this one means
*somebody looked and the boundary answers*. `Unjudged` refuses the first for
want of anybody having looked, so the second settles rather than rewrites and
never reaches it.

**And it is written down**, which is what makes the relaxation honest rather
than merely quieter. The lattice asked about everything unjudged for an
*observability* reason, and a deferral is the one verdict that reaches nobody
— the runtime's own gate decides and the reason goes to no human. So every
deferral appends to `.lup/hooks/learned.jsonl`, one line per distinct command,
and `uv run lup-devtools hooks learn` reads it back as two lists:

- **gaps** — commands nobody has judged, which a boundary carried rather than
  a rule. Each is a candidate for a row in the shell vocabulary, and this list
  is the reason the corpus exists.
- **settled** — commands a rule judged and the boundary answered for. The
  audit trail: read it to check the relaxation is letting through what you
  meant.

Nothing writes a rule automatically, and the refusal is the design. From one
deferred `ruff check .`, a row of `ruff` → allow permits `ruff format --write`
forever and a row of `ruff check` → allow permits `ruff check --fix`; the same
mechanism over `rm tmp/scratch` → `rm` → allow permits `rm -rf`. What separates
the safe generalisation from the catastrophic one is exactly the judgement a
person is there to make.

Recorded when the verdict is reached rather than after the command has run. The
later event was the first proposal — learning from what a human approved — and
it cannot carry that: a runtime offers both *yes* and *yes, don't ask again*
and the event cannot tell them apart, and a human may answer by editing the
command, so it fires for something other than what was judged. None of that
touches a deferral, which is nobody's approval and is exactly known here.

`uv run <target>` is parsed rather than matched against that table, so its
targets carry the same three answers on a table of their own: each declares
its effect, its placement, and its reason. Blessing is the default and the
common case, and a project that means to stop a target — one that spends
money, runs for an hour, or publishes something — says so there. Leaving it
off is not the same answer: an undeclared target reaches no judgment, which
denies unsandboxed and defers under the boundary, where the policy has
stated nothing and the runtime's own permissions decide.

A target may also carry subcommands, because a toolchain reached through
`uv run` is one target and many commands — a devtools CLI that mostly reads
a repository may have one verb beneath it that opens a paid agent session,
and without this the choice is blessing that verb or refusing the toolchain.
The shape and the walk are the command table's own, so a target with verbs
is judged exactly as the command spelled directly would be, with the
target's own effect as the default beneath them.

Both axes cascade down a table's nesting, and absence means one thing
everywhere: a subcommand or operation omitting `effect` or `sandbox` inherits
the level above it, and one stating either overrides what it inherited in
either direction. `default_effect` is the exception, being required — a
command that never said who decides is a gap a reader sees rather than a
silent allow, and the fallback beneath every table denies.

`$(...)` classifies recursively — the inner command joins the batch and its
opaque result rides only argument-safe commands; command position, deep
nesting, and backticks stay conservative. File writes (redirection, `rm`)
auto-allow only into a repo `tmp/` — the one at the top or any a package
opened beside itself — and the scratchpad (`$TMPDIR`,
`/tmp/claude-*`; reassigning `TMPDIR` asks); discards and fd dups strip;
heredoc-fed writes deny toward Edit/tmp scripts. Loops, conditionals, case
arms, subshells, and brace groups classify recursively over frozen bindings —
literal assignments instantiate, opaque ones (`read`, globs) gate
flag-guarded commands. `find -exec` payloads and `timeout`/`nice` wrappers
recurse, `sed`/`awk` pass read-only screens, quoted-delimiter heredocs are
literal data, and `curl` is read-screened within the declared fetch scopes.

Codex's native prefix evaluator deliberately leaves an assignment-bearing
script opaque. Its permission-request hook still passes literal assignments
through this same classifier, so `ENV_VAR=constant git status` is approved
without a prompt. Security-sensitive assignments preserve the prompt, and a
malformed assignment is refused as an unknown command.

## Fetch scopes

One declared origin table feeds both `WebFetch` and the `curl` screen. A
scope may opt into its subdomains, which also contributes the `*.host`
wildcard to the OS sandbox network allowlist, so both boundaries admit the
same set. Declare any origin an agent should be able to read as a fetch
scope; reserve the sandbox's `extra_domains` for hosts that need egress
without being readable sources. Egress the proxy cannot carry at all — SSH
under a git remote, a daemon socket — is not a scope question: the sandbox's
only lever there is `excluded_commands`, which drops the command out of
isolation rather than widening anything.

## Forge credentials

A contained session reaches its forge on something the operator lent it,
selected at launch from a ladder ordered by what each rung leaves behind: a
forwarded ssh agent, then an ephemeral copy of the host's usable ssh keys,
then a token over HTTPS, then nothing and public reads. `GitAccess.source`
pins one rung; `auto` walks them and takes the first that is *verified*
usable — an agent holding an identity, a key that opens with no passphrase,
a `known_hosts` entry that lets a non-interactive ssh verify the forge. A
pinned rung that turns out unusable degrades to public reads with the reason
said, rather than refusing a launch over a preference.

Both ssh rungs are gated on the egress carrying ssh at all. ssh reads none of
the proxy variables, so under `filtered` a forwarded socket would be a
credential the session holds and cannot use — which reads as ready and is
not. The selected rung also decides which way remotes are rewritten: toward
`https://host/` for a token, toward `git@host:` for a key or an agent, so one
session speaks one transport rather than half its remotes working.

**What the credential-path denials do and do not buy.** `~/.ssh` and
`~/.aws/credentials` are declared in `HookSandbox.credential_paths`, which
compiles into an OS-level read denial for sandboxed shell and into `Read`
deny rules for the in-process file tools. That stops an agent *reading* key
material and is worth keeping. It is not isolation from `ssh` and `git`
*using* it: `ssh git@github.com` contains no credential path, and ssh reads
the key or the agent socket itself. On Claude the denial is additionally
enforced by the native per-path credential sandbox; Codex has no per-path
equivalent, so there it is the semantic policy alone, and neither is a
syscall boundary. An operator granting an ssh rung is granting the contained
session the use of that identity, and this is the honest description of that
grant rather than a claim of a stronger boundary.

Nothing lent is written where it could outlive the session: the ephemeral
home is made under the system temporary directory at mode `0700`, holds
copies at `0600`, is mounted read-only, and is removed when the launcher
exits. The host's own `~/.ssh/config` is never copied — the configuration is
compiled from what was actually lent, so it cannot name an `IdentityFile`,
an `Include` or a `Match exec` that does not exist inside. Host-key
verification is left at ssh's default: `known_hosts` is carried in, and a
forge it cannot verify is a reason to decline the rung rather than to accept
an unknown host.

Nothing lent reaches the argv that starts the container either. The token
crosses as a bare `-e NAME`, which both engines read as "take this one from
my own environment", and the forge client's own variable is derived inside
the image from it — a value in argv is a value in `ps` for every process on
the host, for as long as the session runs.

Signing is a separate claim from authorship and stays off by default: an
agent commit is not a human vouching for it, and signing it with the
operator's key would make the signature assert something untrue. What that
costs is a branch protection rule requiring signed commits, which fails on
agent branches as a visible check at push time rather than as `gpg: signing
failed` mid-commit.

## Edit decisions

Edit decisions cover protected paths, marker changes, size, and the canonical
anti-pattern audit. An edit over the size gate alone is deferred — the hook
emits no decision, so auto-accept applies while hard gates stay explicit.

Size is counted in *real* changed lines per change block, and an edit of
three or fewer auto-allows. Imports, comments, whitespace, blank lines,
docstrings, string literals, type annotations, and TypedDict/BaseModel bodies
are not real lines. Pure deletions and single-line `replace_all` renames
auto-allow outright; a multi-line `replace_all` falls through to the size
gate, and a full-file write asks for everything but a package marker — an
`__init__.py` arriving empty or holding nothing but its docstring, where the
question the gate exists to raise has no content to answer it. One carrying
anything else is the module it became, and asks. The anti-pattern audit runs
before any auto-allow, so keeping an edit small cannot outrun it.

Every verdict above is what the kernel reaches when a project says nothing,
and every one of them is nameable. `HookSet.edit_rules` is a `Selection` of
`EditRule`, each naming the axes an edit has — the gate it speaks about, the
file suffixes, the path roles, and whether the change creates, overwrites,
modifies, or deletes — plus the effect it hands that class and the size
threshold it counts by. The two move independently: a rule may widen how much
counts as small for one suffix without restating who decides when it trips.

Overlapping rules resolve **last-match-wins**, the way `.gitignore` reads, so
a project writes the broad statement first and carves its exceptions after
it. A repository whose conventions are Python conventions says so in two
entries — the content gates allow, then `.py`/`.pyi` ask — and leaves prose,
data, and other toolchains to be reviewed in the diff rather than at the
hook. Most-specific-wins was rejected: it makes a table's meaning depend on a
specificity ordering nobody wrote down, and has no answer at all for two
rules of equal reach.

The gate ids include the two that deny removing review feedback. A gate a
project cannot reach is one whose rightness this library asserted on that
project's behalf, and an escape hatch stated in a declaration somebody
reviews is better than the fork it would otherwise take. Moving one gate
moves nothing adjacent: softening `feedback-removed` leaves `claim-removed`
denying, because the two are about different things.

A project that declares an **acceptance guard** adds one gate ahead of all
of those, over every root it gave the `test` role. An ordinary session is
asked before it edits a test, because a test that encodes the wrong
behaviour has to be fixable by someone who can weigh that; a session
declared autonomous is refused, because for it these tests are the
specification it is implementing against, and rewriting a specification to
match an implementation is the failure the guard exists to catch. It answers
before the gates below rather than through them — including pure deletion,
which would otherwise wave through removing the test outright, and the
protected-path rules, whose autonomous release must not survive a refusal
aimed at exactly that caller. This is the one place autonomy costs a caller
more rather than less. Declaring no guard leaves tests judged by the
ordinary lattice, which is right for a project that does not implement
against fixed acceptance tests.

The
resolver's worker receives only its declared autonomous edit exceptions;
temporary paths, human-owned files like `README.md`, marker changes, and
anti-pattern violations retain their guardrails in every mode.

A few of those guardrails open only for a gate a human granted — creating a
devtools module, adding an anti-pattern suppression. What a lease holds is
written in one document per lease, and every judge reads it at the moment it
judges: the canonical policy in the composing process and the deployed
dispatcher in the session's own. The session environment names that document
and never carries its contents, so a gate granted while the session runs
reaches it and one taken back stops applying, with no restart either way. A
narrowed document parks the run rather than silently reducing what a worker
may do. Nothing else grants: a name outside the declared vocabulary is
dropped, and an unreadable document is no grant at all.

Autonomy follows the identity a launcher declares for the session it starts,
carried in the environment and matched against the resolver's own
`worker_identity`, so it reaches a top-level worker session on either runtime
rather than only a natively dispatched subagent. A session that is not
autonomous declares the empty identity rather than staying silent: runtimes
merge a session's environment over the launching process's, so silence would
inherit whatever the operator had exported. A hook script is spawned by the
runtime with the runtime's environment, so an agent exporting the variable
inside a shell tool call never reaches the dispatcher that judges it.

## Two markers change a decision

The guidance spells both; this is what each one does.

- The escalation marker, `lup: escalate: <why>` as the leading comment line
  of a shell command, promotes anything not already permitted into an approval
  question carrying that reason. It is the recovery path when work is denied
  as unjudged: reshape the command into the allowed vocabulary, or escalate
  with a reason. It is an **effect**-axis marker and says nothing about
  placement — it asks whether the call may happen, not where. Two refusals it
  does not reach, both being statements that the call cannot happen rather
  than that nobody approved it: a marker stating no reason, which would be
  authorising itself, and a call declared `outside` on a host with no channel
  to put it there.
- The typed suppression marker, `lup: ignore[<rule-id>]` as a comment on the
  offending line, silences exactly the anti-pattern it names and no other, so
  the site still trips every rule it left unnamed. [contributing.md](contributing.md)
  carries the scoping — where the marker must sit, comma-separated ids, the
  flagged bare form, and the file-wide placement.

Each rule id is shown in the deny message that cites it, and indexed in
[rules.md](rules.md).

## Asking before spending a turn on it

A denial is the ordinary way to learn a verdict, and it costs a turn. Two
commands answer the same question up front, against the declared policy
rather than a reading of this page:

```bash
uv run lup-devtools dev policy '<the command as you would run it>'
uv run lup-devtools dev vocabulary --provenance
```

`dev policy` prints the decision and the sentence explaining it — the same
sentence the hook would have shown — for a shell command, and takes the same
lattice through the same segments, so a pipeline or a `$(...)` answers as it
actually would. `dev vocabulary` prints every shell form the vocabulary
judges and where each rule came from, which is the one to reach for when the
question is "what *would* be allowed here" rather than "is this".

## Hook execution evidence

Plugin hooks receive a writable data directory: `PLUGIN_DATA` under Codex and
`CLAUDE_PLUGIN_DATA` under Claude Code. Each dispatcher appends
`hook-events.jsonl` there as it runs: a `started` record after input parsing,
then `completed` with the final policy outcome or `failed` with the exact
dispatcher exception. Records carry the event, session, turn, tool, tool-use
id, and UTC timestamp. They deliberately omit tool input and output, which may
contain commands, patches, or credentials.

This journal distinguishes failures whose UI is otherwise identical. A
`failed` record is a dispatcher failure; `completed` with `deny` is an
intentional policy refusal; `started` without a terminal record is an
interrupted dispatcher. If the native runtime reports a hook event but no
correlated `started` record exists, the plugin command never began, so the
investigation belongs at its trust, hook-definition, or process-launch
boundary rather than in policy logic. An unwritable journal reports its own
diagnostic but does not change the decision the hook reached.

## How one decision reaches two runtimes

The generated plugins enforce permissions without importing lup, yet decide
identically to the library.

1. **Canonical sources** — the `HookSet` in `devtools/harness/catalog.py`
   (protected edit roots, allowed fetch scopes, policy ids, and the shell and
   edit selections), the anti-pattern rule set in `lup.harness.codescan.antipatterns`,
   and the offered shell vocabulary in `lup.policy.vocabulary`. Each selection
   is resolved by `HookSet.resolved_shell_rules` and
   `HookSet.resolved_edit_rules` and nowhere else: a second place that knew
   which defaults a selection layers over is how a session comes to decide
   differently from the plugin its own declaration generated.
2. **Library layer** — `lup.policy.rules` validates those inputs as Pydantic
   surfaces and erases them into primitive rows; `lup.policy.kernel` — the
   hermetic, stdlib-only decision core — interprets those rows to reach every
   shell, fetch, and edit verdict; `lup.policy.chain` composes policies
   deny-before-ask; the adapters' `native` modules decode wire payloads into
   `lup.policy.models` events and render decisions back.
3. **Assembly** — `lup.policy.bundle` reads the kernel source verbatim and
   renders the erased rows as data files; the adapter hook renderers emit
   `hooks/hooks.json`, the dispatcher `hooks/scripts/policy.py`, and
   `hooks/runtime/{kernel.py,policy_data.py}` into each plugin tree.
4. **Equivalence** — the shared fixture suite runs the same cases through the
   library policies and the assembled runtime and requires identical verdicts.

Every rule id a denial cites is indexed in [rules.md](rules.md).
[harness.md](harness.md) covers changing the declarations above, and
[platform-differentiation.md](platform-differentiation.md) records where the
two dispatchers deliberately differ.
