# Permission Policy

How the generated hooks decide allow, ask, defer, or deny, and the two
markers that change a decision. The guidance carries the rule; this page
carries the mechanism a denial sends you to.

## Sources of truth

Permissions come from the canonical semantic policies in `lup.policy` and the
application-owned `HookSet` in `harness/catalog.py`. Harness
generation compiles one hermetic dispatcher and runtime for each native
plugin. Never edit generated dispatcher or runtime files — change the
canonical source and regenerate.

## Shell classification

The policy classifies each shell command against
`lup.policy.vocabulary.default_vocabulary` as
`harness/content/shell_vocabulary.py` selects it, every URL scope,
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
lattice is not keyed on how a command is *spelled*: a rule naming an
executable and stating a verdict beside it gives two commands with one effect
different answers whenever two people write the two rules. `effects`
is the declaration instead — a list from the closed table in
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
| `allow_flags`, `read_verbs`, `frozen_flags`, `write_markers`, `bare_reads`, `guarded_keys` | the de-escalations: a pure read-only form, a verb that pins the query action, a flag that pins a dependency restore to what its lockfile already declares (`bun install --frozen-lockfile`, and `uv sync --frozen` or `--locked` by the same judgement), a marker whose absence means it only reads, the argument-less form, a setting that redirects neither execution nor the repository this checkout talks to |
| `setting_flags`, `guarded_settings` | the same absence test about a global that carries a setting — `git -c color.ui=false` turns off colour, `git -c core.pager=x` runs a program and `git -c remote.origin.url=x` aims the next push somewhere else, and only the last two are worth interrupting about |
| `ask_refspecs` | the effects an operand's *grammar* carries, for a push that spells force and delete twice |
| `ask_destinations` | the forms of repository named inline that the first non-flag operand may carry — a URL or a path reaches one the remote table never heard of, where a bare remote name is one somebody approved putting there |

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


<!-- passage: placement -->

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
/etc/hosts` settles as "the affected paths are captured and restorable",
which is a sentence about a file no snapshot has ever seen.

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
than merely quieter. The lattice asks about everything unjudged for an
*observability* reason, and a deferral is the one verdict that reaches nobody
— the runtime's own gate decides and the reason goes to no human. So every
deferral appends to `.lup/hooks/learned.jsonl`, one line per distinct command,
and `uv run lup-devtools dev hooks learn` reads it back as two lists:

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

That table also answers `uv run -m <root>.<module>`, on the root segment, and
one criterion settles every `uv run` form: an invocation is refused when it
leaves no reviewable artifact behind. `-c` leaves nothing to read and an
interpreter handed nothing runs no program at all, so those keep the refusal.
A path is judged as that path, spelled plainly, after `-s`, or after
`--script`. A module is judged by whether the project declares the root it
lives under, because a module is as openable, diffable and re-runnable as the
file it lives in — so one declaration admits every entry point beneath a root,
and an undeclared root is refused with the declaration to extend named. An
`-m` a declared target owns stays that target's: `uv run pytest -m slow`
selects a marker expression, not a module.

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
opened beside itself — and the machine's temporary root, the session
scratchpad (`$TMPDIR`, `/tmp/claude-*`) with the rest of `/tmp` around it,
which no review pass reads and no capture holds (reassigning `TMPDIR` asks,
and a suffix climbing clear of `/tmp` leaves the grant behind); discards and
fd dups strip.
Loops, conditionals, case
arms, subshells, and brace groups classify recursively over frozen bindings —
literal assignments instantiate, opaque ones (`read`, globs) gate
flag-guarded commands. `find -exec` payloads and `timeout`/`nice` wrappers
recurse, `sed`/`awk` pass read-only screens, quoted-delimiter heredocs are
literal data, and `curl` is read-screened within the declared fetch scopes.

### A write that carries its own content

A redirection is answered by its path, and the reason is that a command
produces its output by running: before the fact there is nothing for the
content gates to read. What the path settles is who gets asked. Into scratch
or beyond the checkout it is the ordinary work it was; into this repository's
own tree it **asks**, because the same bytes arriving through an `Edit` or an
`echo` would have been read by the content gates and these never will be. So
`dev render > docs/api.md` puts one question, and its recovery names the two
ways past it: redirect into a scratch path and move the result in once it has
been read, or carry the content in the command.

Asking rather than refusing is the whole concession to the premise. Nothing
can read this write in advance, and refusing on that ground would refuse the
only writes for which that is unavoidable — so a human is asked instead, and
`git apply`'s unreviewed route keeps being the one that denies. Measured
before this: `date +%s >> <a tracked module>` appended to reviewed source,
allowed and unprompted, while `echo x > <the same path>` was read by the
content gates — one file, one write, two answers, decided by which spelling
carried its bytes.

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

## Reaching another session

Two native calls address the population [coordination.md](coordination.md)
describes, and the policy answers both from the roster rather than from a
table. A send is denied when any string it carries names a live member of this
repository's roster, with `coordination_send` named as the surface reaching the
same peer and recording what it carried; every other target — a subagent this
session started, a teammate, a session in another repository — passes through
untouched. A listing is never refused: it answers for a wider, account-scoped
population a repository-scoped roster cannot hold, so the verdict is a deferral
and this repository's roster is attached beside the answer instead.

This is the one decision whose inputs are not declarative. The roster is live,
so the dispatcher's host half folds it — `peer_addresses` and `peer_listing` in
`lup.policy.assets.host` — and hands the kernel the spellings it found, exactly
the way an edit rule marked `resolution: required` is answered from a resolver
the dispatcher ran. The kernel still reads no filesystem and still decides from
its inputs alone. What is *declared* is only where to look: `HookSet.peer_policy`,
built by `lup.coordination.policy.peer_policy` from the store's own layout,
so renaming the coordination directory moves the compiled hook with it. A
project declaring none has both calls left entirely to the runtime's own
permissions, which is what a repository whose sessions never coordinate should
pay for them.

A deliberate send to a peer is not walled off. The `# lup: escalate:` marker in
any of the call's own inputs turns the refusal into the approval question the
sender asked for, carrying their stated reason — the valve every refusal has.
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

Edits in an explicitly mounted destination repository use that checkout's
generated policy. The caller keeps its session identity, measured execution
boundary, approval channel, and whole-shell restrictions. A writable parent
directory alone grants no policy authority over unrelated nested repositories.
Read-only mounts, including nested read-only paths, still withhold writes;
canonical Git common-directory identities distinguish unrelated repositories
and bind linked worktrees, separate Git directories, and submodules correctly.
Autonomous edit grants require the same agent identity to be authorized by
both policies. Claude's native agent type is carried to the owner; other calls
use the declared session identity.

At launch, `.lup/preflight/<nonce>.json` records exact destination grants and
the digest of the generated evaluator and runtime source accepted for each.
`LUP_BOUNDARY_ROOT` pins that ledger to the launch checkout when a command
changes its working directory; changing directories never changes its grants.
The evaluator runs from `.lup/policy-snapshots/<digest>`, with both source and
snapshot checked before execution. Missing, malformed, incompatible, changed,
or failing evaluators block the edit with a recovery diagnostic. Both native
runtimes share this routing and aggregate every file, including both sides of
a move; a denial wins over an approval request.

Destination evaluation never starts an external resolver from the checkout.
Rules requiring unavailable resolution retain their conservative review verdict.

After regenerating a destination policy, an independent operator can accept
its bytes without restarting the session. From the caller checkout, run
`uv run lup-devtools harness policy-refresh --nonce <nonce> --repository <checkout>`.
The same command can accept a newly created worktree only beneath an original
explicit writable bare-repository mount, with the same Git common directory
and a writable measured boundary. It never discovers unrelated nested
repositories or extends the launch's filesystem grants. The requester cannot
run this operator action, and the authority ledger and accepted snapshots are
protected edit paths. These records prevent accidental inheritance and stale
policy execution; they are mutable local bookkeeping, not authentication
against a hostile process with the same filesystem authority.

Edit decisions cover protected paths, marker changes, size, the canonical
anti-pattern audit, and declared import ownership. An edit over the size gate alone is deferred — the hook
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

`HookSet.import_boundaries` carries the same `seam-boundary` ownership that
the repository audit reads. Concrete adapter imports belong in providers or
declared composition roots; provider SDK imports belong in implementations
and explicitly named fixtures, not application composition roots. The shared
AST scanner understands direct, parent-package, wildcard, and relative
imports, including multiline statements. Provider names in prose and canonical
tool grants such as `Read` and `WebSearch` remain valid: vocabulary is not a
dependency. Computed import names and arbitrary executed code are outside this
static guard, not claims of runtime isolation.

An unsuppressed dependency breach denies before size allowances or a batch's
approval request can admit it. A typed suppression uses the existing reviewed
suppression allowance; removing one exposes the import again. Retiring
`seam-boundary` through `HookSet.rules` retires the hook and audit together.
Both native dispatchers carry the same scanner and ownership rows.

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

## Where a native ask is put

A policy ask goes to the person through whatever channel the runtime has.
Claude renders it as a native permission request carrying the reason that
earned it, and parks nothing. Codex has no ask effect at its pre-tool
boundary, so it parks the call in `.lup/questions.jsonl` and refuses execution
until an explicit answer is recorded, at both pre-tool and permission-request
events; the refusal names the review id and the commands to inspect, approve
or reject it, and a pending or rejected review returns an explicit denial.

What a rendered ask rests on is the session answering to a person. An autonomy
mode answers on the session's behalf, including for the operations the
`human_only` reviewer reserves, and no field in the hook payload separates a
prompt somebody saw from one a mode settled. Observed execution is evidence of
neither: it records that a call ran and confers no authority over the next.

Codex delivers that denial as a supported structured `deny` carrying
`systemMessage`, so its app-server raises an operator-visible warning in
`hook/completed` beside the agent's refusal. `codex exec --json` omits those
hook events; its agent still receives the same refusal and review commands.
Neither surface turns a policy question into an implicit approval.

The operator can keep one browser inbox open by running this from a terminal
outside the agent session:

```bash
uv run lup-devtools dev questions serve
```

It listens on `127.0.0.1:8766` and opens the browser. Without `--root`, it
follows the launch repository's worktrees. Each `--root <checkout>` selects a
repository to watch; when supplied, only those repositories and their worktrees
are included. Repeat `--root` to watch several repositories, use `--no-open` to
open the printed address manually, and choose another port with `--port`. Leave
the terminal command running while reviewing; Ctrl-C stops its server.

The inbox titles requests from captured evidence: a file's action and path,
the number of files, or the command to run. The exact operation, requester,
rule, reason, command or captured file diff, and recorded answer remain visible.
The default view includes files that require review and highlights newly
introduced rule exceptions. Files the policy allows automatically and existing
exceptions remain available in the full-operation view. Approval still applies
to the exact complete submission. Where recorded evidence cannot establish a
file's status, it remains visible rather than being treated as automatically allowed.
The file navigator shows change counts and supports searching paths. Select
one file to inspect its colored, numbered diff or complete Before, After and
Raw views; `[` and `]` move between files. A shared directory appears once,
with complete paths available for inspection. The queue, navigator and evidence
panels scroll independently; smaller screens offer panel switches.
Typed `lup: ignore[...]` comments are highlighted in the code and grouped by
rule; existing exceptions appear only in the full-operation view. Expand a
group for written reasons and occurrence links, or use `n` and `p` to jump
between exceptions.

Approve or reject one question with an optional note. Auto-advance opens the
next pending request after a successful decision; turn it off to stay on the
answered request. New arrivals do not move a selection already under review.
Use `j` / `k` for next / previous request, `Shift+A` to approve, `Shift+R` to
reject, `c` to open and focus the collapsed comment, and `?` for shortcut help.
Decision buttons stay visible beneath the selected evidence. Shortcuts pause
in text fields, and holding a decision key cannot answer another request.

Use **Copy link** to share a request without sharing a credential. Links use
`#review=<question-id>`; copied links also name the checkout to distinguish
identical IDs. They open the exact pending or historical request,
including in another tab of an already authorized browser. Back, forward, and
changed links select the corresponding request. A missing ID stays selected
while the inbox watches for it; it never silently opens a different request.

The decision is recorded in the
same durable relay that the terminal commands use, so a browser and terminal
answering concurrently cannot replace each other's answer. Session notification
is best effort after the answer is saved. The browser can advance while the
server completes delivery; a missing route or failed delivery does not erase
the answer. Each browser answer retains a separate notification outcome
in `.lup/review-notifications/`, bound to its question, fingerprint and answer
timestamp. Answered requests show a compact status with expandable details:
mail queued, native queue accepted, failed or unconfirmed. Interrupted attempts
remain unconfirmed; diagnostics failures never undo the recorded approval.
Native retries notify only a unique registered requester whose bound native
session matches the request. Queue acceptance does not prove the agent read
the message. A native-hook approval still requires the agent to retry the exact
tool call. The inbox never executes a reconstructed command.

The server mints a capability for that invocation and puts it in the printed
browser URL's fragment, which HTTP requests do not send to the server. The
page removes the credential from the address and keeps it in local storage for
that exact origin: scheme, hostname, and port. Tabs at that origin authenticate
queue API requests with its bearer credential, so shared request links carry
only review identity. The credential is never a cookie or read from stale
session storage. A fresh launch link updates other open tabs through storage
events; opening it in the same tab keeps the selected review and draft comment.
If browser storage is blocked, the page explains that access is limited to the
tab that opened the launch link. The page and its assets contain no credential.
Restarting the server replaces the capability; reopen its printed launch link.
Treat the full address as an operator credential and keep it out of agent
messages. The server binds loopback, checks Host against DNS rebinding, and
checks the origin of answer submissions. These controls protect the browser
surface; they are not isolation against arbitrary processes running as the
operator's user. The session's filesystem and process boundary remains part
of the authority boundary.

The terminal surface remains available: run `uv run lup-devtools dev questions
show <id>` from the indicated checkout, then `uv run lup-devtools dev questions
answer <id> --as operator` or `uv run lup-devtools dev questions reject <id>
--as operator` outside the agent session. Queue answers and the server that
mints browser review credentials are declared `operator_only` in the shell
vocabulary; an escalation cannot grant the requester authority to answer
itself. Nested command paths are declared with `ShellOperationRule.parents`,
and the deepest matching path decides.

Approval releases one exact retry in the same session and directory.
The hook re-runs policy, compares the payload, captured file preimages,
resolved paths, originating dispatcher and policy bytes, and accepted
destination policy bindings, then claims the approval exclusively before
allowing execution. A changed file, payload or policy requires another
review. The receipt binds both the original request and the exact approved
runtime input rewrite; observing a different executed input marks the receipt
`in_doubt`. Rejection leaves the operation stopped and delivers the
operator's note.
A crash after claiming approval does not make it reusable. Native sandbox
restrictions still apply; queue approval does not change execution placement.
Post-tool evidence marks a dispatched review completed, without claiming that
the operation's effects succeeded. Execution against an unresolved review is
recorded as `in_doubt` and diagnosed. A missing matching event leaves dispatch
unresolved; it never makes the answer reusable.

A Codex pre-tool receipt can advance once to the permission event when both
events carry the same nonempty native invocation ID and exact operation.
The handoff takes a separate exclusive claim, so repeated permission events
cannot reuse it. The native permission-event contract does not promise that
ID; when absent, the pre-tool receipt cannot establish the handoff. The call
stays blocked pending fresh review or execution from an operator terminal.

Native patches are decoded into file transitions before review. A standalone
shell `apply_patch` with a single-quoted argument or a quoted heredoc reaches
the same edit gates. Relative paths resolve against the hook payload's
working directory. Add-file operations replacing existing files are judged
as overwrites. Compound shell commands are never reduced to only their patch.
Plain two-path `cp` commands capture both source and destination; changes to
either invalidate approval. Every statically known shell write target also
contributes its preimage, including redirections, authored content and in-place
rewrites. The review diff uses the captured documents for
patches and copies, so it remains the proposal submitted even if another writer
changes the files before the operator opens it. Recognized `sed -i` commands
also show a diff from their captured input. The preview preserves supported
options and transforms that input through sed's sandbox mode; it never runs
the submitted shell command. A caption identifies the inbox environment as
the source of this simulation. The exact command stays visible beside its diff.
Because the request does not capture its execution locale, only ASCII input
and scripts without numeric byte escapes, locale-sensitive ranges, classes, case conversion or
case-insensitive flags are previewed. Unsupported forms explain that a file
preview is unavailable and display the complete command for review.


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

  The question says which *there* it buys, from the placement the launch
  measured rather than from the marker: on a host, that the call leaves for
  the host, outside the only boundary there is; inside a container, that it
  runs with the per-call sandbox off and still inside the container's
  mounts, where a path mounted read-only stays read-only. A contained launch
  never arms the per-call sandbox, so the escape lifts no mount, and a
  write the mount table refuses fails approved exactly as it fails unmarked
  — the exact command is then the user's to run from a host terminal.

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

## What a question says

A verdict carries two texts for two readers, and the contract is that
neither borrows from the other. The `reason` is read by whoever approves,
who answers yes or no and can act on nothing else, so it is one sentence of
at most two hundred characters that leads with the operands the decision
turns on — the packages a `--with` installs, the path a write lands on, the
host a fetch reaches — and states the one fact that stopped it. A compound
command that trips several rules lists each survivor after the first, one
per line, because the answer is one decision over the whole operation. The
`recovery` is read by the agent, on a refusal or a question nobody can be
shown, and says what to change; it is where every instruction goes, and an
instruction found in a reason is a defect
`packages/lup/tests/unit/test_reason_voice.py` refuses. Neither carries
reference. A scope table, a rule index, the marker grammar: each is the same
on every occurrence and read on none, so a question names where it is
pulled from — `dev policy`, this page — rather than repeating it.

## Execution does not grant authority

`.lup/hooks/approvals.jsonl` contains execution observations. Historical records
labelled `approved` carry no explicit reusable grant and are never read as
authority. `dev hooks approvals` shows these observations with that limitation;
`dev hooks forget <prefix or exact call>` retires an observation without
changing authorization. Explicit native review answers remain single-use in
`dev questions`; an execution event cannot turn one into a permanent grant.

The `uv` command reader resolves global options before the subcommand, including
`--directory`, so relocating an operator-only queue command cannot make it an
unclassified command that a contained session runs freely.

## Asking before spending a turn on it

A denial is the ordinary way to learn a verdict, and it costs a turn. These
commands answer the same question up front, against the declared policy
rather than a reading of this page:

```bash
uv run lup-devtools dev policy '<the command as you would run it>'
uv run lup-devtools dev policy --kind fetch '<the URL>'
uv run lup-devtools dev policy --kind edit '<the path>'
uv run lup-devtools dev policy --kind edit-batch proposed-edits.json
uv run lup-devtools dev vocabulary --provenance
uv run lup-devtools dev hooks sweep
```

`dev policy` prints the decision and the sentence explaining it — the same
sentence the hook would have shown — for a shell command, and takes the same
lattice through the same segments, so a pipeline or a `$(...)` answers as it
actually would. With `--kind fetch` it reads a URL against the declared
scopes and lists every one of them beneath the verdict, which is where the
question a fetch outside them raises sends its reader. `dev vocabulary` prints every shell form the vocabulary
judges and where each rule came from, which is the one to reach for when the
question is "what *would* be allowed here" rather than "is this".

An edit path is a path-only preview over unchanged content. Its output labels
the proposed content and operation as unavailable; it is not approval of an
unspecified edit. For a concrete verdict, `edit-batch` reads a JSON
`EditBatch`: `{"changes": [{"path": "src/example.py", "before": "old\n",
"after": "new\n", "operation": "modify"}]}`. Paths resolve against the
calling checkout, and every preimage must match disk. Creations use null
preimages and deletions null postimages. Both forms use the hook's destination
authority and accepted policy snapshots, retaining the caller's write boundary.

`dev edit-prepare proposed-edits.json --output tmp/prepared.patch` audits the
complete proposed documents before a write is attempted. It collects every
source-rule finding together, including project-wide rules and canonical type
resolution, and reports the declared edit gates. The command writes only a
fresh patch artifact beneath a declared scratch root; it never edits the
targets, submits a review, or grants approval. Submit the emitted patch once
through the native edit tool. An `ask` in this preview means review may be
required when submitted; it does not mean a question has already been queued.

Use `--suppressions exceptions.json` to request specific Python exceptions in
the candidate, as a JSON list:

```json
[{"path": "src/example.py", "line": 8, "rule_id": "import-re",
  "reason": "This module implements the grammar itself."}]
```

Line numbers refer to the proposed document before insertion. Each request
must name a proven, suppressible missing directive and state a reason; strong,
refuted, unresolved and nonmatching sites are refused. The helper merges typed
directives, keeps their reasons, verifies that Python semantics are unchanged,
and audits the resulting candidate again. Other source families are audited
but their exception comments remain explicit edits in the proposal. Missing
type evidence is reported, never converted into an automatic suppression.

The emitted native patch is decoded again and compared with every intended
before/after document and operation. Content that the native patch grammar
cannot preserve exactly, including an empty creation or a missing final
newline, is refused with an explanation. Stale preimages, duplicate targets,
foreign paths and contradictory operations are refused before preparation.
`--json` exposes the complete candidate, findings and readings for tools.

A native hook reporting a pending review has already submitted the request.
Wait for that answer, then retry the exact call. Adding an escalation or
changing the payload creates a different review; an approved request cannot
acquire additional code under its existing receipt. Reviews also bind to the
policy that judged the call: regenerating that policy before retrying can
require a fresh review even when the proposal and its preimages are unchanged.

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

Claude reports post-edit diagnostics through its
[structured post-edit feedback](https://code.claude.com/docs/en/hooks#posttooluse-decision-control):
exit 0 with `decision: "block"` and a `reason`. This gives the agent the findings
beside the completed edit. It does not undo the edit or report a crashed hook.
Diagnostics name the file, line, severity, and message. Codex delivers its
post-tool findings through stderr and exit 2. Its patch parser reads every
touched path without replaying the old file contents, so both runtimes run
the same per-file repairs and type checks after an edit, including moves.

Both plugins register a short command invoking the generated
`hooks/scripts/policy.sh`. That guard runs `policy.py`, preserves its output
and deliberate refusals, and refuses if the dispatcher cannot start or crashes.
Missing Python calls for installing Python or fixing PATH. Missing or broken
generated files call for `uv run lup-devtools harness generate all` from a
terminal outside the affected session. If a merge left conflict markers in
generated files, settle or abort that merge before regenerating; do not repair
the generated dispatcher by hand. Recovery instructions live in the guard,
so the native runtime does not echo them with every diagnostic.

Plugin hooks receive a writable data directory: `PLUGIN_DATA` under Codex and
`CLAUDE_PLUGIN_DATA` under Claude Code. Each dispatcher appends
`hook-events.jsonl` there as it runs: a `started` record after input parsing,
then `completed` with the final policy outcome or `failed` with the exact
dispatcher exception. Records carry the event, session, turn, tool, tool-use
id, and UTC timestamp. They deliberately omit tool input and output, which may
contain commands, patches, or credentials — with one exception. A call whose
input names a URL also records `fetch_origin`: the scheme, host, and port of
that URL, and nothing else. That is the coarse half a scope is written
against and the half the verdict turned on, so without it a refusal says a
URL was outside the declared scopes without saying which origin asked, and
the host has to be inferred from what the session did next. The path and
query stay omitted because they are where a document id, a search phrase, or
a token spelled into the URL ride; userinfo goes with them, since the host is
read from the parse rather than from the authority that would carry it.

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

1. **Canonical sources** — the `HookSet` in `harness/catalog.py`
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
   `hooks/hooks.json`, the guard `hooks/scripts/policy.sh`, the dispatcher
   `hooks/scripts/policy.py`, and
   `hooks/runtime/{kernel.py,policy_data.py}` into each plugin tree.
4. **Equivalence** — the shared fixture suite runs the same cases through the
   library policies and the assembled runtime and requires identical verdicts.

Every rule id a denial cites is indexed in [rules.md](rules.md).
[harness.md](harness.md) covers changing the declarations above, and
[platform-differentiation.md](platform-differentiation.md) records where the
two dispatchers deliberately differ.
