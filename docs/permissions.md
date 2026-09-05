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

### What a rule states, and what it earns

**A rule says what an operation does. It never says what that earns.** The
lattice was once keyed on how a command was *spelled*: a rule named an
executable and stated a verdict beside it, so two commands with one effect
reached different answers whenever two people wrote the two rules. `effects`
is the declaration now — a list from the closed table in
`policy/kernel/effects.py`, each member deciding its own verdict from the
scope it was given, what the host measured, and where the session sits — and
`declared_verdict` derives the answer wherever it is used. Two spellings of
one effect cannot diverge, because there is one row for the effect and every
spelling reaches it.

`ShellCommandRule.effects` and `RunnerTargetRule.effects` are **required**. A
declaration stating none derives an allow, so an omission would be a grant
nobody wrote down rather than a gap a reader sees; a command that genuinely
does nothing this table guards says `changes_nothing`, which exists to be
sayable.

Two things a rule states that are not effects:

- `refuses` — where the agent goes instead, when this project declines the
  *spelling*. Set, the row denies whatever its effects would have earned, and
  the text is the whole of what the agent is told, so it names the route
  rather than the objection: `uv add` for `pip install`, writing the command
  out for `eval`. A refusal is about the route, and the route is not what an
  operation does — which is why it sits outside the effects instead of being
  spelled as one.
- `sandbox` — where an invocation has to run, whatever it earns. The axis
  below.

And the columns that say what a *word* adds or removes, each answering one
question the row alone cannot:

| column | what it states |
|---|---|
| `ask_flags` | the spellings that escalate this row |
| `flag_effects` | what the escalation is *about* — `git reset --hard` discards working-tree content, which the bare verb never did |
| `write_flags` | options whose value is a path this command writes, so the path is resolved and judged by the write row every other spelling reaches |
| `allow_flags`, `read_verbs`, `write_markers`, `bare_reads`, `guarded_keys` | the de-escalations: a pure read-only form, a verb that pins the query action, a marker whose absence means it only reads, the argument-less form, a setting that does not redirect execution |
| `setting_flags`, `guarded_settings` | the same absence test about a global that carries a setting — `git -c color.ui=false` turns off colour, `git -c core.pager=x` runs a program, and only the second is worth interrupting about |
| `ask_refspecs` | the effects an operand's *grammar* carries, for a push that spells force and delete twice |

A rule declaring `reviewed` on a write says the route it takes has gates that
read what it wrote. It is declared rather than measured: which gates a
spelling passes through is fixed by the spelling, so it is known where the
rule is written and not at the path. That axis is what keeps the write row's
refusal aimed at *bypassing the content gates* rather than at editing a file.

What the classified verdict then becomes is a second, ordered pass, declared
as an order rather than written as a branch. `policy/kernel/settlement.py`
holds one row per rule, read the way `.gitignore` reads patterns: every row is
offered the running verdict, a row that rewrites hands its result to the next,
and the first row that settles ends the pass. So a statement about precedence
— *a stated reason never leaves a refusal standing*, *a judged deny is not
rescued by a boundary*, *a question nobody can answer is no judgment* — is one
row that says it, and changing the policy is moving, adding, or dropping one.
The rows, in order, each stating its own claim:

| id | row | what it says |
| --- | --- | --- |
| `hard-prohibition` | `HardProhibition` | A policy invariant, which asking about does not move. |
| `missing-capability` | `MissingCapability` | A guarantee the runtime cannot deliver, which approval cannot create. |
| `decision-escalation` | `DecisionEscalation` | A stated reason turns anything not already permitted into a question. |
| `sandbox-escalation` | `SandboxEscalation` | The agent asked for the launcher&#x27;s host, which is always reviewed. |
| `trapped-placement` | `TrappedPlacement` | An operation that has to reach the host where nothing can carry it. |
| `unleased-write` | `UnleasedWrite` | A write the measured boundary does not cover, wherever the session sits. |
| `provider-native` | `ProviderNative` | A rule looked and handed the decision to the provider&#x27;s own mode. |
| `recovered-loss` | `RecoveredLoss` | A question about a loss a proven capture already put somewhere safe. |
| `unreachable-reviewer` | `UnreachableReviewer` | A question in a session no eligible reviewer can be reached from. |
| `contained-effects` | `ContainedEffects` | Nobody judged it, and everything it can do is confined: run it inside. |
| `unjudged-ambient` | `UnjudgedAmbientPolicy` | Nobody judged it and no boundary confines it: the profile answers. |
| `unreadable` | `Unreadable` | Nothing judged it, nothing confines it, and nobody can read it. |
| `judged-refusal` | `JudgedRefusal` | A rule refused this, and no boundary rescues a judged deny. |
| `standing` | `Standing` | Whatever reached here stands: a permission, or an answerable question. |

**Placement** is the second axis, and the boundary it names is the profile's
own — whatever delivers containment — never a provider's per-call sandbox,
which is one adapter's mechanism for spelling `inside`. Three values:
`inside` runs within the containment boundary whatever mode the session is
in, `ambient` runs wherever the session already lives, and `outside` runs on
the launcher's host through the trusted host executor. An allow placed
outside runs there unprompted; an ask placed outside says so in the question
it asks; a deny short-circuits the axis, and so does a defer, which hands the
whole decision over rather than half of it. Confinement wins a join, so one
segment that must stay inside keeps the whole line inside, and a runtime with
no channel renders the plain effect rather than an intent it would drop.

The offered table declares no placement at all. What `git`, `gh` and a
session-opening toolchain need is a boundary that grants a route to the
remote, the repository's own locks, and the runtime's configuration home —
which is a fact about the profile, declared with the boundary and *measured*
at launch, where a profile that cannot meet it says so once. Declared as a
placement it was unmeasurable: the profile that grants those and the profile
that does not both read as `outside`, and the second finds out at its first
shell call, on an error that reads like a broken repository.

**Checkpoint** is the third axis, and the one that makes the effect a
function of the session rather than of the command. The vocabulary guards
*the direction that removes something no second attempt restores*, so each
rule names the capture that would cover its loss:

| value | what the capture holds | when a rule declares it |
|---|---|---|
| `targeted` | exactly the paths the operation names | every path resolves statically — `rm build/out`, `git restore`, a redirect into a named file |
| `boundary_wide` | every precious writable root | a variable, a glob, a substitution or a directory walk prevents an exact footprint, so the wider capture is what the opacity costs |
| `unrecoverable` | nothing reaches it | a remote ref, a published artifact, an issue somebody read, a command whose argument is another command |

`unrecoverable` is the default and the whole safety of the axis: a rule
nobody annotated keeps asking. `git clean -fdx` carries it deliberately
rather than by omission — it destroys ignored files, which is exactly what a
capture leaves out.

**A declared value is a claim about a path, so it is checked against the
paths.** A row carries one value for every path it might touch, which stops
being true the moment an operand leaves the checkout: the capture these name
is a snapshot of the checkout, and a loss beyond it is held by nothing. So a
redirection reads its scope off the target, and a path verb reads its
strongest operand — only the ones it *writes*, since a source `cp` merely
reads is an ordinary read however far out it sits. Without that, `rm
/etc/hosts` was settled as "the affected paths are captured and restorable",
which is a sentence about a file no snapshot had ever seen.

Where the capture was actually *taken*, `RecoveredLoss` settles the question
as a **permission**. Not a deferral: deferring would make the outcome depend
on which mode the session happened to be started in, for a fact that has
nothing to do with the session's mode. This policy has positively established
that the loss it was protecting against did not happen, so it authorizes.

Taken, and not merely requested. A snapshot reference is not recovery —
coverage, restoration, metadata, completion and post-state are the guarantee
— so the row reads *measured* evidence and distinguishes three answers:
nothing required, capture proven, and capture attempted and short. The third
keeps the question and says which it was, because "nobody captured this" and
"the capture did not work" are different things to tell somebody.

It discharges local loss and nothing travelling beside it. An operation that
also rewrites a production file, touches a protected path, reads a credential
or reaches a remote keeps its question in full, which the row reads over the
findings that composed the verdict rather than over their join — a join
reports the strongest effect and says nothing about how many reasons reached
it. And a `# lup: escalate[decision]:` marker keeps its question either way:
the agent asked to be judged, and evidence does not overrule the request.

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
targets carry a table of their own — and they carry it in the same vocabulary:
each declares its `effects`, its `refuses`, its placement, and its reason.
Blessing a toolchain is the common case and it is one word,
`runs_declared_target`. A project that means to stop a target — one that
spends money, runs for an hour, or publishes something — refuses it there.
Leaving it off is not the same answer: an undeclared target reaches no
judgment, which denies unsandboxed and defers under the boundary, where the
policy has stated nothing and the runtime's own permissions decide.

A target may also carry subcommands, because a toolchain reached through
`uv run` is one target and many commands — a devtools CLI that mostly reads
a repository may have one verb beneath it that opens a paid agent session,
and without this the choice is blessing that verb or refusing the toolchain.
The shape and the walk are the command table's own, so a target with verbs
is judged exactly as the command spelled directly would be, with the target's
own effects as the default beneath them. One statement serves both halves:
while the runner row stated a verdict of its own, a target could bless itself
and refuse its own verbs with nothing noticing.

Every axis cascades down a table's nesting, and absence means one thing
everywhere: a subcommand or operation omitting `effects`, `refuses` or
`sandbox` inherits the level above it, and one stating any of them overrides
what it inherited in either direction — widening a restrictive parent is as
ordinary as narrowing a permissive one. So `git` says once where its
subcommands run, and each of them says only what differs; a toolchain refused
at the command keeps its one documented entry point by clearing `refuses` on
the subcommand that has one.

`$(...)` classifies recursively — the inner command joins the batch and its
opaque result rides only argument-safe commands; command position, deep
nesting, and backticks stay conservative. File writes (redirection, `rm`)
auto-allow only into a repo `tmp/` — the one at the top or any a package
opened beside itself — and the scratchpad (`$TMPDIR`,
`/tmp/claude-*`; reassigning `TMPDIR` asks); discards and fd dups strip.
Loops, conditionals, case
arms, subshells, and brace groups classify recursively over frozen bindings —
literal assignments instantiate, opaque ones (`read`, globs) gate
flag-guarded commands. `find -exec` payloads and `timeout`/`nice` wrappers
recurse, `sed`/`awk` pass read-only screens, quoted-delimiter heredocs are
literal data, and `curl` is read-screened within the declared fetch scopes.

### A write that carries its own content

A redirection is answered by its path, and the reason is that a command
produces its output by running: before the fact there is nothing for the
content gates to read, so `dev render > docs/api.md` is judged on where it
lands and reviewed against the file *afterwards*.

That premise is false for `cat > f <<'EOF'` and `echo x > f`, where the bytes
are sitting in the command. Those go to the same gates an `Edit` goes to —
the anti-pattern audit, the review-note gate, the size budget, the full-write
gate — with the file about to be replaced as the preimage, and the strongest
verdict wins. So a heredoc that drops a `# lup:` note is denied exactly as
the edit would be, and one that replaces a tracked module asks; a write into
scratch stays the ordinary work it was.

Two shapes are read and no others: `cat` handed nothing but a
quoted-delimiter heredoc, and `echo` handed literal words. `printf` is
absent because its first argument is a format, and an unquoted heredoc
because the shell substitutes into the body — a reading that was wrong would
put a document in front of the gates that the command never writes, which is
worse than putting nothing there. Everything unread keeps the answer it had.

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

- The escalation marker, as the leading comment line of a shell command,
  names which axis it asks to move — `lup: escalate[decision]: <why>` for a
  reviewer over a verdict a rule reached alone, `lup: escalate[sandbox]:
  <why>` for the launcher's host, and `lup: escalate[decision,sandbox]:
  <why>` for both. Two different requests were sharing one spelling, and they
  promote a verdict differently: decision escalation turns an overrideable
  refusal or an abstention into a question at the placement it already had,
  while sandbox escalation moves the placement and is *always* reviewed —
  what the person is being asked is not "may this run" but "may this run
  *there*", which has an answer of its own. Composed, the combined form is
  the only route from an overrideable refusal to the host, because the
  decision half has already made it a question by the time the placement
  moves.

  The bare `lup: escalate: <why>` keeps working as decision escalation and
  says it is an alias, because a migration that breaks every marker at once
  is one nobody can act on mid-run.

  A reason is mandatory in every spelling: the whole content of the request
  is what it says to whoever answers, and a request that says nothing asks
  them to approve a rule id. Three refusals it does not reach, each being a
  statement that the operation cannot happen rather than that nobody
  approved it: a marker stating no reason, a policy invariant, and an
  operation whose placement no channel can carry — where no approval creates
  the channel, so no reviewer is shown the question.
- The typed suppression marker, `lup: ignore[<rule-id>]` as a comment on the
  offending line, silences exactly the anti-pattern it names and no other, so
  the site still trips every rule it left unnamed. [contributing.md](contributing.md)
  carries the scoping — where the marker must sit, comma-separated ids, the
  flagged bare form, and the file-wide placement.

Each rule id is shown in the deny message that cites it, and indexed in
[rules.md](rules.md).

## Asking before spending a turn on it

A denial is the ordinary way to learn a verdict, and it costs a turn. Three
commands answer the same question up front, against the declared policy
rather than a reading of this page:

```bash
uv run lup-devtools dev policy '<the command as you would run it>'
uv run lup-devtools dev vocabulary --provenance
uv run lup-devtools hooks sweep
```

`dev policy` prints the decision and the sentence explaining it — the same
sentence the hook would have shown — for a shell command, and takes the same
lattice through the same segments, so a pipeline or a `$(...)` answers as it
actually would. `dev vocabulary` prints every shell form the vocabulary
judges and where each rule came from, which is the one to reach for when the
question is "what *would* be allowed here" rather than "is this".

`hooks sweep` classifies a whole list at once and exits non-zero if any line
is not a plain allow. With no file it reads the everyday corpus this project
declared in `HookSet.everyday_commands` — the commands an ordinary session
runs, which this table must keep allowing — and `dev check` runs the same
sweep, so a rule that tightened something it did not mean to fails at the
gate rather than in somebody's session. That is the one measurement of the
vocabulary that reads a *tightening*: the recorded questions list what a
session was interrupted about, and a verdict census lists what each row
earns, so both go on agreeing when a de-escalation quietly stops firing.

The corpus is swept once per posture a session runs in — interactive, worker,
contained, and contained worker — because a verdict is only ever reached for
somebody, and a rule that starts asking where nobody is there to answer stops
a session rather than interrupting one. `--autonomous`, `--headless` and
`--trapped` name one posture and ask about that one instead. Pass a file for
a question this project has not settled — a candidate corpus, or the commands
a recorded session was actually stopped for — asked from the posture those
same flags name.

Only what must keep allowing belongs in that corpus. A command that asks
today is either a defect to fix or a question somebody meant, and neither is
settled by adding it to a list that asserts allow.

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
