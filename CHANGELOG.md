# Changelog

## Unreleased

### Migrating personal Claude profile callers

Two earlier public API changes have explicit migration records for adopters
updating from before those changes:

- `ClaudeProfileStore` split at `fcb61ade6`. Import `AccountFile`,
  `ClaudeProfileNames`, and `ClaudeProfileRegistrar` from
  `lup.providers.claude.profile_store`. Construct one
  `accounts = AccountFile(registry_path)` and share it between
  `ClaudeProfileNames(accounts)` and `ClaudeProfileRegistrar(accounts)`.
  Registry reads, writes, home resolution, and `resolver_registry()` belong to
  `accounts`; `names()`, `config_dir_for()`, and `active_profile()` belong to
  the names reader; `add_profile()`, `set_active()`, and `remove_profile()`
  belong to the registrar. A CLI composes these with
  `ProfileDirectory(names, registrar, CLAUDE_LOGIN)` from
  `lup.providers.profiles`. The existing registry and account homes remain valid.
- `CLAUDE_CONFIG_DIR` moved at `da46c6bb2`. Import it from
  `lup.providers.claude.login`, which also declares `CLAUDE_LOGIN`; use
  `CLAUDE_LOGIN.environment(config_home)` when constructing a launch environment.
  The former `lup.adapters` namespace is `lup.providers` in the current API.

`dev update` reports these migration steps when the previous pin predates the
corresponding change. Run `uv run lup-devtools dev check` after adapting callers
to catch remaining imports and capability mismatches.

### A session an application opens can be walled

`SessionRequest` could say how much a session may do and nothing about what
confined it, so an application composing `Client` reached neither boundary
the launcher already knew how to open: the sandbox settings each adapter
carried were reachable only by building that adapter's configuration by
hand, and the wrapper that runs a CLI inside a container was reachable only
as a resolver actor's.

`containment` is that axis, in the launcher's own three words. `inner`
establishes the runtime's own sandbox, `outer` starts the runtime as the
program named in `contained_program` and stands its own sandbox down inside
the container, and `none` is the default — what every request meant before
the field existed, so nothing an adopter holds changes until it asks.

The two runtimes render it into what each has. Claude keeps autonomy and
containment in two fields that decide nothing about each other. Codex has
one field for both, and takes the narrower of what the wall asks and what
the autonomy implies, so neither can widen what the other narrowed.
`contained_cli` writes the program an `outer` request names, for either
runtime, defaulting to the mounts that hold a session to the tree it was
given.

## 0.3.0 — 2026-09-19

Breaking reorganisation of the library's top level. Thirty-four entries became
twenty by asking of each one which of four kinds it is: a foundation that
imports nothing else here, a subject, the one vendor boundary, or tooling.
Every import path an adopter holds is affected, and the migration is derived
rather than written. Both ends of the range are read out of git, so one command
prints the exact `dev relocate` invocation that repoints a checkout from
whichever commit it stands at:

```sh
uv run lup-devtools dev migrate map c564bc01a..
```

Derived rather than pasted here for the reason the reorganisation itself gives:
a hundred pairs written down go stale the next time one module moves, and a
list confidently wrong is worse than one that had to be looked up.

| Was | Is | Why |
| --- | --- | --- |
| `lup.adapters` | `lup.providers` | the boundary named for what sits behind it, not for the pattern |
| `lup.runtime` | `lup.sessions` | one of four modules called `runtime`; the engine is about a session's turns |
| `lup.runtime.contracts` / `.models` / `.wrappers` | `lup.sessions.capabilities` / `.events` / `.middleware` | each named for what it holds |
| `lup.runtime.profiles`, `.profile_tree`, `.login`, `.session_home`, `.selection`, `.routing`, `.config` | `lup.providers.*` | which runtime answers is the provider's question, not the turn engine's |
| `lup.mcp`, `lup.tool_policy`, `lup.tool_routes`, `lup.codeintel` | `lup.tools.mcp`, `.policy`, `.routing`, `.lsp` | one entry for what an agent acts with; `codeintel` shared eight characters with `codescan` on the opposite side of the system |
| `lup.journal`, `lup.telemetry.*`, `lup.replay.journal`, `lup.usage`, `lup.runtime.usage` | `lup.observability.journal`, `.audit`, `.trace`, `.display`, `.metrics`, `.blocks`, `.native`, `.replay`, `.usage`, `.cost` | four entries answered "what happened", and `journal` named four different things |
| `lup.actors`, `lup.jobs.runtime`, `lup.realtime`, `lup.subagents`, `lup.reflect`, `lup.runtime.background` | `lup.orchestration.*`, with `reflect` → `reflection` and `jobs.runtime` → `jobs` | five entries answered "run work concurrently" |
| `lup.resilience`, `lup.runtime.threads`, `lup.gitlocks` | `lup.execution.resilience`, `.threads`, `.writability` | what carrying work out runs into; `gitlocks` asks a filesystem question that git's `config.lock` is only the first caller of |
| `lup.hooks` | `lup.policy.hooks` | the hook seam is part of the permission subject |
| `lup.codescan` | `lup.harness.codescan` | the rule engine reads the harness declaration models it judges |
| `lup.selection` | `lup.tables` | it is about narrowing a library table, not selecting a runtime |
| `lup.gitguard` | `lup.devtools.gitguard` | catching a test suite writing outside its fixtures is development tooling |
| `lup.harness.banner` | `lup.banner` | a foundation both the harness and the policy bundle write |
| `lup.client` | `lup.sessions.client`, `lup.providers.routing`, `lup` | one module was the type every consumer holds *and* the router that reaches both vendors |
| `lup.gitlocks` → `lup.execution.writability`, and `lup.devtools.utils.git` | `lup.execution.shell` | a configured `git` the mount rail and the harness both reach, moved below both |

`lup.channels`, `lup.types`, `lup.markdown`, `lup.workspace`, `lup.web`,
`lup.sandbox`, `lup.policy`, `lup.harness`, `lup.resolver` and `lup.devtools`
keep their names. `channels` in particular stays a top-level foundation: it
imports nothing but `lup.types`, and folding it in with `workspace`
manufactured a cycle between storage and observability.

`from lup import Client, create_client, Provider` is unchanged — the package
root still exports the whole front door, and `create_client` is declared there
now rather than one module down. What moved is where a consumer that bypassed
the root has to look: `Client` is `lup.sessions.client`, and the model-id
routing is `lup.providers.routing`, which is the vendor edge that was already
keeping a matcher vocabulary of its own.

**One capability is gone rather than moved.** `PROVIDER_PREFIXES`, a
`dict[str, Provider]` matched longest-prefix-first, is replaced by
`PROVIDER_ROUTES`, a `list[ProviderRoute]` matched in declaration order and
carrying a `ModelMatcher` rather than a bare prefix — so an adopter can name a
model exactly, or write a matcher of its own, where a prefix says the wrong
thing. A caller passing `prefixes=` passes `routes=` instead, and writes the
narrower entry above the broader one rather than relying on a sort nothing on
the page mentioned. Every other export in the ledger resolved to its new home.

- Modelled the payloads a literal dictionary key was reading by hand: a Codex
  `turn/completed` notification, the two spellings a delegation names its role
  under, what a retrieval call names as its source, Claude's project section,
  and the REPL wire protocol, now declared once in the half that runs in the
  container. `PayloadText` in `lup.types` carries the fact three of them
  share.
- Named the shapes that replace an open string map in the `dict-str-payload`
  and `dict-str-object` diagnostics, so a denial points at a frozen id model,
  a declared route list, or `EnvVars`/`StringMap` rather than at a
  suppression.
- Derived the permissions page's settlement order from the kernel that reads
  it, and the supersession gate now reads its answer from the domain it
  publishes rather than from a constant pair declared beside it.
- Version directory names parse with `semver`, so an experiment arm's
  `+build` suffix orders with the release it came from, and `resolve_version`
  takes the counter and the word for what it counts as overridable defaults.

### The coordination store is state

Four append-only logs folded whole by every reader on every call became one
file per member, written by that member's own processes under its own lock,
with every relation between members derived at the read: presence is the
file's modification time, a claim carries the modification time of the path it
was taken over and is settled by a stat, and a contest is two live members'
files meeting on one path. Mail is one file per message in one inbox, consumed
by deletion, so no reader keeps a position.

Broadcast splits into the two acts it always was. A message has one recipient,
so a sender that means everyone resolves it against the roster; a standing
fact is state — read at the head of a turn for as long as it holds, retracted
by deleting it, and reaching a session that starts tomorrow.

Eight migrations are declared over the hundred and fifty-three names this
moves; `uv run lup-devtools dev migrate map` prints what to call instead.

### A module's prose is one file

Prose a content module composes is authored as Markdown beside it. A module
composing several passages marks them off inside that one file with
`<!-- passage: name -->` and names which it is placing, so a subject is one
file rather than eleven and a passage is named for what it holds rather than
for its position in a list.

`passage_path` takes the module alone — which passage is `Passage.name`, read
off the section markers rather than off a second filename. How many newlines a
rendered document ends on moved from `sectioned` to the renderer, which is the
one reader that sees a whole document whatever kinds of part composed it.

### A peer that is idle can be woken

`wake()` finishes the job itself on both runtimes rather than handing the
caller an instruction on one of them. Every Claude session runs a private
inbox socket, and lup passes `--messaging-socket-path` for every session it
launches, so a member declares the handle that wakes it when it joins and a
sender writes a frame there carrying that member's session id. A session lup
did not launch is still reached through the runtime's own default paths.

The handle is declared by the adapter for the runtime that would use it,
because what a handle *is* differs by runtime: on Codex it is the thread
`codex queue` takes, which nothing hands a server Codex starts, so that
adapter declares nothing and the outcome is reported rather than skipped.

A wake is always *on top of* the mail and never instead of it, so the record
is identical on both and only the latency differs. The agent never touches the
channel: `coordination_send` remains the one habit.

### The rest

- `ledger migrate` copies a kind's journal lines and blobs into the placement
  its mapping now declares, for a kind moved after records already exist. The
  source lines stay: the committed journal is merged by git's union driver, so
  a deletion there would not even be durable, and the fold already reads each
  record once.
- `ledger index-notes` records a closed session per directory under an
  existing `notes/` tree, and one output per result, through the same writers
  a live run uses — so a backfilled record is the same two records a live run
  leaves. Idempotent by `(checkout, path)`.
- Every parsed command carries the directory it runs in, and a segment's path
  words resolve by position rather than by value, so a relative operand after
  a `cd` is judged against the file it would reach.
- An in-place rewrite nothing produced says which reading stopped it: a path
  naming no file, a target that is not a regular file, a script `sed` would
  not run, and text that could not be read each carry their own recovery.
- A global in front of a subcommand is consumed before the subcommand is read.
- A contained session reads the clock in the operator's zone, filled from the
  file the machine keeps it in rather than from a `TZ` a Linux host exports
  for nobody.
- Every workflow job names the pinned runner image, held to it by a sweep over
  `.github/workflows` rather than by whoever remembers.

### What this release carries no migration for

A repository declares which of its subtrees it publishes nothing out of, in
`DevProject.internal_modules`, and the preservation gate walks what is left.
Two are declared here, and what went from them is not a break an adopter can
meet:

- **`lup_template`**, the scaffold. `dev init` copies this half into the
  adopting repository and renames it, so its names arrive there as that
  project's own source rather than as an import. Thirteen went, among them
  `build_session_toolset`, the five `*_GROUP` toolsets, and the `library_*`
  commands.
- **`lup.policy.kernel`**, compiled into the hermetic dispatcher each
  generated plugin runs and reached there as bare `kernel.*`. Forty-seven
  went, nearly all of them the hand-rolled shell tokenizer — `ShellToken`,
  `Lexeme`, `Scan`, `tokenize_shell`, `read_heredoc_bodies` — and the
  control-flow readers beside it, replaced in place.

A project that imported either subtree was reaching past what this repository
publishes. The declaration sits in the catalog with its reasoning, so the
judgement can be read and argued with rather than inferred from a gate that
quietly stopped firing.


### What this release asks of a caller

- agent_roster_text, topic_bullets, UpstreamReport.section — a roster and a report section are a list and a document rather than joined text: each is parts now, so a name or a description carrying a newline cannot end the bullet or the heading it was written into
-   Compose the parts instead of the string: `agent_roster_bullets(agents)` from `lup.harness.content.catalog` answers with a `BulletList`, and a report's section is `section(report)` from `lup.harness.content.docs.upstream_reports`, a `Passage`. Where the text itself was wanted, `part.text_payload` reads it back. `topic_bullets` has no replacement: its one caller builds a `BulletList` from `REPORT_TOPICS`.
- WorkflowSpec.body, WorkflowSpec.install_step, PublishSpec.body — a generated workflow is a declared document rather than a formatted string: the steps are `WorkflowStep` declarations and the file is a `YamlDocument`, which is emitted and parsed back before it is written, so a runner label or a command carrying a colon can no longer end the mapping it lands in
-   Read the YAML off `spec.document().text()` where `spec.body()` was read, or take the whole artifact from `spec.artifact()` as the generator does. A project that appended its own step by formatting text around `body()` declares a `WorkflowStep` instead and overrides `steps()`; `install_step` is `install_steps()`, which answers with a list rather than a block of YAML.
- MarkdownCell, MarkdownCell.text, MarkdownCell.render — the base every generated Markdown leaf answers through is an inline node rather than a table cell: the same escaping is what a heading compiled from a catalog and a value inside a sentence need, and a name saying `cell` said the table was the only container there could be
-   Import `InlineNode` from `lup.formats.markdown` where `MarkdownCell` was imported; `text` and `render` are unchanged, and every concrete kind — `PlainCell`, `CodeCell`, `HtmlCodeCell`, `LinkCell` — keeps its name and its behaviour.
- PYTHON_SUFFIXES, MARKDOWN_SUFFIXES, JS_SUFFIXES, JSON_SUFFIXES — the marker scanner routes a file by one dict from suffix to scan mode, where four parallel tuples each guarded an arm of a match that decided on nothing the subject carried
-   Read `SCAN_MODES` from `lup.harness.codescan.markers` where one of the suffix tuples was read: its keys are the suffixes and its values the `ScanMode` each routes to, so the suffixes of one mode are the keys whose value is that mode.
- AntiPatternSet, AntiPatternSet.python, AntiPatternSet.typescript, AntiPatternSet.for_suffix, AntiPatternSet.selected, antipattern_set_for — the set holds every rule a project is judged by — the line rules, the project rules the sweep runs, and the composition rule generation runs — so it is named for what it holds
-   Import `RuleSet` from `lup.harness.codescan.antipatterns` where `AntiPatternSet` was imported, and `rule_set_for` where `antipattern_set_for` was; the fields and methods keep their names, and `project` and `composition` stand beside `python` and `typescript`.
- AntiPattern.id, AntiPattern.examples, AntiPattern.message, AntiPattern.refinement, AntiPattern.strength, AntiPattern.examples_bound_the_rule, STRUCTURAL_RULES, anti_pattern_rules — every rule is one declaration: what every rule states moved to the `Rule` base that `AntiPattern`, `ProjectRule` and `CompositionRule` share, and the reference derives every card from the set instead of keeping the structural ones by hand
-   A caller constructing or reading an `AntiPattern` changes nothing: the fields are inherited. One that read `STRUCTURAL_RULES` or `anti_pattern_rules()` reads `all_rules()`, which derives every card. A project declaring a rule the sweep decides declares a `ProjectRule` from `lup.harness.codescan.project` beside its audit and adds it to its set's `project` list.
- member_environment — a launcher mints a session's name beside its id, numbered against the live sessions of the repository so two sessions in one worktree are reachable apart, and exports the two together
-   Where `member_environment(member_id)` was exported, call `launched_member(root)` from `lup.coordination.repository` and export its `.environment()`; a caller holding an id and a name of its own builds a `LaunchedMember` and exports that.
- NATIVE_SPELLING_RULE_ID, KERNEL_IMPORT_RULE_ID, LIBRARY_DEFAULT_RULE_ID, CONSTANT_DECLARATION_RULE_ID — the boundary scanner's rule ids are one enumeration: several audits share that module, and a constant apiece said the same thing as many times as there were suppression comments naming it, so `RuleId` says it once
-   Read the id off `RuleId` instead: `RuleId.NATIVE_SPELLING`, `RuleId.KERNEL_IMPORTS`, `RuleId.LIBRARY_DEFAULT` and `RuleId.CONSTANT_DECLARATION`, all from `lup.harness.codescan.boundaries`. Note the plural in the second, whose constant was singular. Each carries the same string it always did and the type is a `StrEnum`, so a comparison against a rule id read from anywhere else -- a directive, a deny message, the generated reference -- holds without being converted.
- changes_runtime_source, prompt_command, prompt_entry, prompt_artifacts — the roster's prompt hook became one guard serving the arriving and the departing event alike, so none of these names a thing that is only about the prompt any more, and each has to be told which script and which runtime module it is building for
-   Call `runtime_source(module)` for `changes_runtime_source()`, `guard_command(plugin_root_env, guard_script)` for `prompt_command(plugin_root_env)`, and `hook_entry(plugin_root_env, guard_script)` for `prompt_entry(plugin_root_env)`. The added argument is which guard the entry points at, and a caller that had one hook passes the script it was already generating.
-   Call `roster_artifacts` for `prompt_artifacts`. It keeps `plugin_root`, `semantic_id` and `event` and adds `guard_script`, `runtime_module`, `source_file` and `origin` -- what the one prompt guard used to hold as its own constants, passed now that two events render it.
- CallToolResultWithAlias, CallToolResultWithAlias.is_error — in-process MCP servers are built on the mcp 2.x server API, whose result already answers to `is_error`; the subclass existed only to alias `isError` onto the snake-case spelling an SDK query runner looked for, and it has nothing left to translate
-   Drop the subclass and let the server's own result stand. A caller that built one to get the alias reads `is_error` off the response envelope instead -- which is what a `@lup_tool` handler's failure already crosses as, and what `mcp_response(text, is_error=True)` sets.
- refuse_a_blocked_registration — a merge-driver registration a contained session cannot make no longer refuses the worktree: the registration is the host's once-per-clone act, and the checkout is usable without it, so the pre-flight reports the gap and answers whether it is blocked instead of stopping
-   Call `report_a_blocked_registration` where the refusal was called; it returns whether the registration is blocked, which a caller that made the worktree conditional on it reads instead of catching the exit.
- repository_worktrees, WriteFacts.worktrees, ShellContext.repository_worktrees, redirected_verb_only_reads, redirect_stays_in_this_repository — a git directory redirect is a value flag and nothing more: the verb behind `-C`, `--git-dir` and `--work-tree` is judged by its own row in the other tree, as `cd there && git <verb>` always was, so the guard that asked about the redirect and the worktree list it was measured against have nothing left to decide
-   Drop the `repository_worktrees` argument from any call into `decide_shell`, `classify_shell` or `shell_context`, and the `worktrees` key from a `WriteFacts` a project builds by hand; a project's own shell vocabulary needs no change, and a git rule that listed the directory flags under `ask_flags` keeps them under `value_flags` alone.
- approval_fingerprint, approval_receipt_root, record_approval, spend_approval, uncorrelated — a queue approval is bound to the exact call, session, checkout and file preimages and spent once on retry, so the receipts that stood in for that correlation — written per pending prompt, and matched by nothing narrower than a prompt — have nothing left to answer
-   Nothing outside the dispatcher called these. A project that carried its own copy of the Codex dispatcher asset takes the library's again by regenerating: the receipts directory it wrote under the session root is no longer read and can be removed.
    uv run lup-devtools harness generate all
- LibraryMode.LINKED, read_linked_path, link_library — an editable install of a lup checkout moved the library with no command run in the project and nothing written down, so the pin, the copied half and the generated trees had nothing to be held at one commit against
-   A project resolving lup from a path pins the branch carrying its changes instead, which moves under a command and records the commit it moved to.
    uv run lup-devtools dev library git --branch <branch>
- build_session_toolset, tool_group_names, ServerGroup — assembling a session's tool groups was the same work in every project built on lup and went stale in each of them separately; what a project decides is which groups it carries, so the assembly is the library's and the list is the project's
-   Replace the copied `build_session_toolset` with a list of `ToolGroup`s: name `coordination_group()`, `ledger_group(...)`, `sandbox_group()`, `codeintel_group()` and `realtime_group()` from `lup.tools.toolsets` rather than rebuilding them, and write a builder for each group of your own. A builder that has nothing to build for a session returns nothing, which replaces every `if` that asked whether the session had a sandbox or an identity.
-   `tool_group_names(realtime=...)` is derived now: `served_names(groups, needs)` for one session, `startup_names(groups)` for the servers a runtime starts when a session opens.
-   A `--server` option typed as the `ServerGroup` literal takes a plain string and is checked against the declared names, since a project's groups are its own.
- capture, operations, CAPTURE_FILE, CapabilityKind, CapabilityKind.COMMAND, CapabilityKind.EXPORT, Capability.kind, SurfaceCapture.commands, SurfaceCapture.read, SurfaceCapture.write — a surface stored in the tree ages against the walker that reads it — the checked-in one had already stopped seeing type aliases — while git holds every revision, so both ends of a range are read rather than remembered
-   `dev preserve capture` and its fixture are gone: nothing is stored. `dev migrate map <base>..<head>` derives the relocation, `dev migrate check` refuses a capability that went undeclared, and both read the surface out of git.
    uv run lup-devtools dev migrate map <base>..
-   A command is no longer walked as a capability of its own. It is declared by a function whose name is in the surface already, so a command that goes takes its declaration with it.
- standing, unsaid, gone, member_of, RepositoryPeers.pulsed, RepositoryPeers.rewound, RosterRecord.applied, ActorSpawned.applied, ActorJoined.applied, ActorDescribed.applied, ActorFinished.applied, TouchRecord.claim, TouchRecord.applied, PathTouched.claim, PathTouched.applied, PathContested.claim, PathContested.applied, PrefixLocked.claim, PrefixLocked.applied, PrefixReleased.claim, PrefixReleased.applied, PathVacated.claim, PathVacated.applied, stream_records, peer_members, peer_heard, peer_present, peer_name_claims, peer_addresses, peer_listing, claim_covers, peer_claims — the coordination store was folded by three hand-kept readers that shared no import — the typed library, the prompt-time hook and the compiled permission dispatcher — so every record the store gained had to be taught to each separately, and one that missed a record went on answering confidently about a store it no longer understood; there is now one fold, `lup.coordination.bare.store`, which every reader imports and each plugin ships
-   Fold the roster with `store.members(roster_path)`, and read it as the pulses and resets leave it with `store.present(root)`, which applies both. What a record makes of a member is `store.applied` and is no longer a method on the record: `ActorJoined` and its siblings are writers now, and the fold takes them off disk without importing them.
-   `RepositoryPeers.pulsed` and `.rewound` are `store.pulsed` and `store.rewound`; `RepositoryPeers.present()` applies both already and is what a caller wanted from either.
-   Claims fold with `store.claims(root)`, narrow to live holders with `store.held(root, live)`, and answer a path with `store.covering(root, path, live)`. `Claim.covers`, `.subject` and `.vacant` still answer for a typed caller, over that same fold.
-   The dispatcher's half is gone from `lup.policy.assets.host`: `peer_addresses` and `peer_listing` are `store.addresses` and `store.listing`, `claim_holders` is `store.claim_holders`, `record_claims` is `store.record_claims`, and each takes the coordination directory `peer_store` still resolves rather than a project root and a list of file names.
- PeerPolicy.roster_file, PeerPolicy.names_file, PeerPolicy.touches_file, PeerPolicy.member_kind, PeerPolicy.heartbeats_dir, PeerPolicy.stale_after_seconds — the compiled dispatcher imports the shipped fold, which owns every file name the store is made of, so a policy restating them was the second spelling that could drift
-   Drop those six from any `PeerPolicy(...)` you build. What is left is what the fold cannot know: `store`, the path parts beneath the shared git directory; `windows_dir`, the dispatcher's own snapshots; `member_env`; and the five lines a stopped caller reads. A project that moved its store still says so with `store`.
- roster_artifacts, DEPARTURE_ORIGIN, DEPARTURE_SOURCE — a plugin carries the coordination half as one package rather than a loose file per hook, because the two hooks and the dispatcher all stand on the same fold
-   `roster_artifacts` is gone. `store_artifacts(plugin_root, semantic_id)` places the package under `hooks/runtime/coordination/`, and is called unconditionally: it takes no hook set, because the dispatcher imports the package whatever a project declared about rosters. `hook_artifacts(...)` places one event's guard and the entry beside the package that it runs.
- HOOKS_MANIFEST, CodexHookEvent, CODEX_HOOK_EVENTS, declared_hook_records, untrusted_hooks — which hooks a Codex home would run is the runtime's verdict over its own records and the plugin cache those records name, so it is asked rather than reconstructed — the hand-kept event table knew three events while the generated manifest declares five, and the one call that decides whether a session carries the policy raised on the two it had never heard of
-   Ask the home instead of naming its records. `read_hooks(home, cwd)` in `lup.providers.codex.trust` returns a `CodexHookReport`, and each `CodexHook` in it carries the `key` the record is kept under, its `current_hash`, `trust_status` and `is_managed` — so nothing composes a record name from `HOOKS_MANIFEST` and `CODEX_HOOK_EVENTS`, and no table has to be kept level with the manifest.
-   Replace `untrusted_hooks(home, marketplace)` with `policy_hooks_skipped(home, project, marketplace)` from `lup.providers.codex.home`, which answers the same question for the working directory a session opens on. It returns the `CodexHook`s themselves rather than record names, and covers a hook whose recorded digest has gone stale — the `modified` verdict a table of names could not see, and the one a regenerated plugin meets constantly.
-   `CodexHookEvent` named the three events the table knew. Nothing narrows an event any more: `CodexHook.event_name` is whatever the runtime reports, so an event added to the manifest needs no change here.
- schema_digest_drift — one regeneration of the app-server schemas answers two questions — whether the shapes the typed models were read from have moved, and whether the reply hook trust is seeded from still carries the fields it is read by — and a second invocation for the second question could answer about a different version
-   Call `schema_reading(contracts)` from `lup.devtools.harness.doctor` where `schema_digest_drift()` was called. It takes the `WireContract`s the composition declares — `NativeHarnessComposition.wire_contracts`, empty for a runtime that depends on no reply by field name — and returns a `SchemaReading` carrying `digests` and `contracts`. The digests are what the old call returned; `findings()` renders both as the messages to print, and `drifted()` answers whether anything moved.
- Woken.instruction, Handover.instruction, Delegation.instruction — a wake is finished by the library on both runtimes now that a Claude session is reached by writing to its own inbox socket, so the outcome where the caller had to finish the job with a tool this library does not hold no longer happens
-   Drop the field from anything that read it. A wake now either reached the peer or did not: read `reached` for which, and `reason` for why not. Code that printed `instruction` beside `note` should print `note` alone, and code that branched on `instruction` being set has one branch fewer.
- Finished, Finished.actor, Finished.at, Finished.error, Finished.summary, Finished.type, HEARTBEATS_DIR, Held.digest, Look.conversation, NAMES_FILE, NameRecord, NameRecord.at, NameRecord.cli_name, NameRecord.id, Named.id, RESETS_DIR, ROSTER_FILE, RosterRecord, RosterRecord.actor, RosterRecord.at, RosterRecord.delivery, RosterRecord.description, RosterRecord.error, RosterRecord.liveness, RosterRecord.summary, RosterRecord.task, RosterRecord.type, RosterRecord.wake, RosterRecord.worktree, TOUCHES_FILE, TouchRecord, TouchRecord.actor, TouchRecord.at, TouchRecord.digest, TouchRecord.path, TouchRecord.prefix, TouchRecord.rivals, TouchRecord.type, Touched, Touched.actor, Touched.at, Touched.digest, Touched.path, Touched.rivals, Touched.type, appended, applied, arrival, beat_path, claims, heard, heard_at, name_holders, named, narrowed, reset, reset_at, reset_path, stamp, stamped_at, touch_prefix, touched_claim, vacant — the coordination store is one file per member and every relation between members is derived at the read, so the four append-only logs and the stamp directories beside them are gone: presence is the member file's modification time, a claim is settled against the path it names, a contest is two live members' files meeting, and a name is on the member that answers to it
-   Read the store through `lup.coordination.bare.store`: `present(root)` for who is here, `held(root, live)` for what they hold, `called(root)` and `naming(root)` for what each is called, `member_of(root, id)` for one. Nothing folds a record any more, so `appended`, `applied`, `arrival`, `heard`, `named`, `narrowed` and the record types they folded (`RosterRecord`, `NameRecord`, `TouchRecord`, `Finished`, `Touched`) have no replacement and need none.
-   Write through the typed verbs, never a record: `Roster.joined`/`describes`/`finished`/`beat` for a member, and `store.revised(root, id, revise)` for a bare writer that must read before it writes. A member file is revised under its own lock, so a caller appending to a shared log now revises one member's file instead.
-   Presence is the file's modification time. `beat(root, id)` touches it and creates nothing, so `heard_at`, `beat_path`, `stamp`, `stamped_at` and `HEARTBEATS_DIR` are gone; read `heard` off the member instead, which `present` fills in from the stat it already takes.
-   A rewind clears the member's own `description` and records the conversation it now belongs to, in one revision, so `reset`, `reset_at`, `reset_path` and `RESETS_DIR` are gone and so is `Look.conversation` — which conversation a row describes is on the row. The prompt fold does it; a caller doing it itself writes `conversation` and an empty `description` through `store.revised`.
-   A claim carries the modification time of the path it was taken over rather than a digest of it, so `Held.digest` and `claims(root)` are gone: `standing(claim)` asks the filesystem, and `held(root, live)` reports only what still holds. `vacant`, `touch_prefix` and `touched_claim` have no replacement — there is nothing to vacate and no record to build.
- MemberNamed, MemberNamed.at, MemberNamed.cli_name, MemberNamed.id, MemberNames, MemberNames.__init__, MemberNames.called, MemberNames.current, MemberNames.latest, MemberNames.named, MemberNames.rename, MemberNames.resolve, NAME_ADAPTER — a name is on the member that answers to it, with the names it answered to before beside it, because the two were only ever read together and a separate log made a rename an event about a member rather than the member changing
-   Call `RepositoryPeers.rename(member_id, cli_name)` for `MemberNames.rename`, `.called(member_id)` for `.current`, `.answering(cli_name)` for `.resolve`, and `.names_taken(except_id)` for `.called` — which now answers with the names live sessions hold, keyed by name. `store.naming(root)` is every claim any member ever made on a name, oldest first, for a caller that wants the history `MemberNames.named` gave.
-   A rename takes the store's `ROSTER_LOCK`, because a name is the one decision made against every other member's file. A caller writing one itself takes that lock around reading what is taken and writing what it chose.
- Claim.digest, Claim.vacant, PathContested, PathContested.digest, PathContested.rivals, PathContested.type, PathTouched, PathTouched.digest, PathTouched.type, PathVacated, PathVacated.prefix, PathVacated.type, PrefixLocked, PrefixLocked.type, PrefixReleased, PrefixReleased.type, TOUCH_ADAPTER, TouchEntry, TouchRecord, TouchRecord.actor, TouchRecord.at, TouchRecord.path, Touches, Touches.__init__, Touches.claims, Touches.contested, Touches.covering, Touches.held, Touches.locked, Touches.record, Touches.released, Touches.touched, Touches.vacated — a claim is evidence rather than an assertion: it records the modification time of the path it was taken over, so a reader settles it with a stat instead of waiting for a record to retire it, and a contest is derived from two members' files rather than guessed at by whichever of them wrote
-   Call `RepositoryPeers.touched(member_id, *paths)` for `Touches.touched`, `.lock`/`.release` for `Touches.locked`/`.released`, and `.held()`/`.holding()` for `Touches.held`/`.covering`. Each writes the claim onto that member's own file under its own lock; there is no `Touches` to open and no record to append.
-   Nothing records a contest: `Touches.contested` and `PathContested` are gone, and a reader derives it from two live members claiming one path. A caller that named rivals records its own claim and lets the reader meet the other.
-   Nothing ends a claim either: `Touches.vacated`, `PathVacated`, `Claim.vacant` and `Claim.digest` are gone, because a path that is no longer there — or that somebody has written since — answers for itself at the read.
- ActorCohort.say_all, ActorDelivery.through, ActorMessage.run_id, DELIVERY_DIR, EVERYONE, MESSAGE_FILE, QuestionMailbox.delivered, QuestionMailbox.send, QuestionMailbox.waiting — mail is one file per message in one member's inbox, consumed by deletion, and the token meaning everyone is resolved by the sender rather than matched by every reader — which is what forced a delivery position per member, and what made a redirect stop workers spawned after the stop
-   Call `ActorMail.send(to, text, door=..., sender=..., in_reply_to=..., redirect=...)` with the member rather than building an `ActorMessage`: resolving what an operator typed is the roster's, through `ActorCohort.post(address, ...)` or `RepositoryPeers.send(address, ...)`. `ActorMessage` keeps every field but `run_id`, which is `sender`.
-   Commit a delivery with the delivery: `ActorMail.delivered(actor, delivery)` deletes exactly the files it was handed, so `ActorDelivery.through` and every offset beside it are gone, and a message posted between the read and the commit is no longer consumed unseen.
-   Say what you mean by everyone. `ActorCohort.notify(text)` posts a standing notice — state, read at the head of every turn, reaching members spawned afterwards — and also sends it to whoever is live; `ActorCohort.redirect_all(text)` stops whoever is working and nobody else. `EVERYONE` is gone from the store, so nothing matches it at read.
-   Reach a member's inbox through the cohort rather than the question mailbox: `QuestionMailbox.send`, `.waiting` and `.delivered` are gone, because addressing needs a roster the mailbox does not hold. `run_cohort(mailbox, run_id)` from `lup.resolver.mailbox` builds the cohort over that run's own mail and journal.
- ActorDescribed, ActorDescribed.description, ActorDescribed.type, ActorFinished, ActorFinished.error, ActorFinished.summary, ActorFinished.type, ActorJoined, ActorJoined.delivery, ActorJoined.liveness, ActorJoined.task, ActorJoined.type, ActorJoined.wake, ActorJoined.worktree, ActorSpawned, ActorSpawned.task, ActorSpawned.type, RosterRecord, RosterRecord.actor, RosterRecord.at — a member is a file rather than a fold of arrival, description and departure records, so the records have nothing left to be: announcing twice finds the first file standing and leaves it, which is what the fold's idempotence was for
-   Construct `Roster(directory)` rather than `Roster(root / ROSTER_FILE)`: it holds the store's directory now, not one file inside it. `joined`, `spawned`, `describes`, `finished` and `beat` keep their signatures; `Roster.stream` and the record types it carried are gone.
- RepositoryPeers.heard, RepositoryPeers.standing, RepositoryPeers.touches, RepositoryPeers.vacant — what a repository's peers answer is read from the files rather than from a record beside them, so the methods that reconciled the two have nothing to reconcile
-   Read `RosterMember.heard` for `RepositoryPeers.heard`, which the fold fills from the member file's own stat. `standing()` is gone, because there is no reading of the record apart from the pulse; `present()` is the one answer, and `lapsed()` is what a sweep would retire.
-   Use `RepositoryPeers.touched`/`lock`/`release`/`held` for what `.touches` gave, and drop `.vacant()`: a claim over a path that has gone stops standing at the read, so nothing collects them to end.
- Arrived.consumed, Arrived.messages, DELIVERY_DIR, EVERYONE, MESSAGE_FILE, Message.to_actor, committed_offset, framed, reaches, reader_name — the peer delivery reader stands on the shipped store package instead of restating the format it reads, so it moved beside the compiled dispatcher — the other file type-checked against the generated tree it is shipped into — and the maildir left it with no position to keep and no address to match
-   Import `lup.providers.claude.assets.peer_delivery_runtime` for `lup.providers.claude.peer_delivery_runtime`, and run the emitted copy under `hooks/runtime/` rather than the module: it names its own directory as a search path and imports `coordination.mail` as a sibling, which resolves only there.
-   The inbox is the position, so `committed_offset`, `framed`, `Arrived` and `reader_name` are gone, and `reaches` with them — one directory per member means there is no address left to match. `deliver(root, member_id)` keeps its signature and its fail-open contract.
- stale_window — a claim window is this session's own before-and-after and nobody else's reader, because a change it cannot attribute is one each session records for itself and a reader derives the contest from
-   `close_claim_window(root, store, windows_dir, mine)` answers `{"paths": [...]}` and takes no `stale_after_seconds`: it no longer reads anybody else's window, so `stale_window` has nothing to judge. `store.record_claims(root, mine, paths)` takes the three arguments that are left.
- rewritten_files — one function had two names on the two sides of the boundary it answers across, and the row type beside it said `File` where the field it fills says `documents` — what a rewrite leaves behind is the document, the file being the path it lands at
-   Call `rewritten_documents` where `rewritten_files` was called; the arguments and the reading are unchanged. `RewrittenFileRow` is `RewrittenDocumentRow` and `UnreadFileRow` is `UnproducedDocumentRow`, whose field on `RewriteReading` is `unproduced` rather than `unread` — the word `unread` stays with the shell write nobody read the content of, which is a different question.
- SpawnedActor, SpawnedActor.actor, SpawnedActor.address, SpawnedActor.arrived, SpawnedActor.delivery, SpawnedActor.description, SpawnedActor.error, SpawnedActor.heard, SpawnedActor.kind, SpawnedActor.liveness, SpawnedActor.running, SpawnedActor.summary, SpawnedActor.task, SpawnedActor.wake, SpawnedActor.worktree — a repository peer is a session somebody started in a checkout, which nothing here spawned: the word belonged to a cohort's workers and read as false on the roster that carries most of these rows, where the fold's own source is a member file
-   Import `RosterMember` from `lup.coordination.roster` where `SpawnedActor` was imported. Every field keeps its name and its meaning; only the type is spelled for what it folds, which is `store.Member`.
- Claim, Claim.at, Claim.covers, Claim.held, Claim.holders, Claim.path, Claim.prefix, Claim.subject, folded_claim — `Claim` named two shapes one import apart: a member's own record of a path it holds, and the cross-member row derived from every member claiming one path. The first is `store.Holding` and the second is this, so each says which it is
-   Import `HeldPath` from `lup.coordination.touches` where `Claim` was imported, and `folded_held_path` where `folded_claim` was. The fields are unchanged: a path, whether it is a prefix, and the members holding it. A caller that meant one member's own record wants `lup.coordination.bare.store.Holding` instead.
## 0.2.0 — 2026-07-23

Breaking capability-composition and semantic-policy release. A clean break:
remove legacy imports rather than wrapping them, because no runtime
compatibility facade exists.

| Removed surface | Replacement |
|---|---|
| `Engine.client()` / `Client.session()` | adapter `create_*_session_factory(config)`, then `SessionFactory.open()` |
| `Client.query()` / broad `query(**options)` | `SessionFactory.query(prompt, OutputModel)`, or the free `query(factory, prompt, OutputModel)` alias |
| `Client.stream()` / `ReplayStream` | optional `TurnHandle.events`; completed `TurnResult.blocks` |
| old `Session.send(text)` | `handle = await Session.start(turn_request(text))`, then `await handle.turn.result()` |
| `Session.interrupt()` | optional `TurnHandle.interrupt.interrupt()` |
| `LupResponse.output(Model)` | strict `TurnResult[Model].output` |
| `output_schema` / `output_format` | `TurnRequest(output_type=Model)` and turn-bound `submit_output` |
| `Engine.profiles()` / `Profile.select()` | adapter `ProfileSelector.session_factory(base, name)`, or `transform(name)` plus immutable `ConfigTransform.apply()` |
| `Engine.background()` / `BackgroundDriver` | `runtime.background.BackgroundAgent(factory, state_to_request, …)` |
| `Engine.builtin_tools()` / provider tables | adapter `NativeEventDecoder` plus semantic events |
| `claude-compat` / `openai-compat` engines | `ClaudeCompatibilityTransform` / `CodexCompatibilityTransform` |
| `LupAgentOptions` | component-owned `ClaudeSessionConfig`, `CodexSessionConfig`, wrapper configs, `TurnRequest` |
| `ConsumeTracker`, `INTENT_KNOBS`, `refuse_unconsumed()` | Pydantic validation on the component owning each setting |
| global `ENGINES` / mutable `MODEL_ROUTES` | immutable `ModelRoute` values and explicit recipes |
| `adapters.tools.names` | semantic policy models; native names stay private to decoders and renderers |
| `lup-devtools claude` | `lup-devtools harness claude` |
| `lup-devtools claude usage` | `lup-devtools usage` |

- Replaced engine/client/options service locators with narrow `SessionFactory`,
  `Session`, `Turn`, event, interrupt, steer, fork, binding, render, launch, and
  policy capabilities.
- Added strict typed turn-bound `submit_output`, whole-logical-turn wrappers,
  debounced background scheduling, immutable routing, profile transforms, and
  Claude/Codex concrete factories.
- Added `SessionRequest.effort`, so reasoning effort is asked for in portable
  words and rendered by `CLAUDE_EFFORT`/`CODEX_EFFORT` the way autonomy already
  was. Both adapters already carried an effort field and passed it to their
  provider, but no request could reach either, so an application that set one
  silently ran at whatever the runtime's own configuration file said. The two
  ladders meet on `low`–`xhigh`; `minimal` opens at Claude's floor and `max` at
  Codex's ceiling, and Codex's `none` is withheld because Claude would render
  it as `low`.
- Moved Codex execution to typed live app-server JSON-RPC and records the
  current dynamic-tool rebinding limitation explicitly.
- Added a single Pydantic harness catalog, deterministic Claude/Codex artifact
  compilation, validation, safe reconciliation, ownership manifests, hermetic
  semantic policy dispatchers, Codex cache verification, and named launchers.
- Added the persisted DAG resolver with question brokering, isolated leases and
  worktrees, semantic multi-parent joins, bounded review, integration,
  verification, final review, and cleanup records. Native entries scan and
  organize inline notes through the shared Python core without modifying the
  user's checkout.
- Added the project-wide `abc-capability` AST rule and typed suppression audit.
- Added the semantic shell decision lattice: erased rule tables judge every
  command, subcommand, and flag tier; unjudged work denies with a
  `# lup: escalate:` recipe; loops, conditionals, case arms, subshells, brace
  groups, and `$(...)` substitutions classify recursively over frozen variable
  bindings; `find -exec` payloads, `timeout`/`nice` wrappers, read-only
  `sed`/`awk`/`curl` screens, and quoted heredocs are judged in place; segments
  join deny > ask > defer > allow.
- Added launcher-verified OS-sandbox awareness: a `HookSet` sandbox declaration
  compiles into settings, launch, and doctor; unjudged work defers to the
  active sandbox boundary, a `dangerouslyDisableSandbox` escape re-enters the
  deny lattice, and Codex launches establish the interactive sandbox envelope.
- Added the Codex guidance flavor: shared template sections render both
  `TEMPLATE_CLAUDE.md` and a native `TEMPLATE_AGENTS.md`, with intentional
  differences recorded in docs/platform-differentiation.md.
- Added `# lup: defer[<wake condition>]:` parked-work notes with wake-gated
  clearing; tracking files are retired and `dev check` stays red while any
  deferred note exists.
- Renamed the downstream registry to `sync.json` with a documented contract
  (docs/template.md) and a legacy fallback.
- Added human-owned file protection compiled from the hook catalog: README.md
  edits always ask and never auto-allow.
- Added generated-artifact provenance banners with ownership documentation
  (docs/harness.md), and extracted the resolver entry and hook
  dispatchers into real source assets.
- Retyped the harness catalog around annotated domain types, decomposed the
  harness CLI into composition, drift, reconcile, doctor, resolve, and launch
  modules, and gave anti-pattern rules token-masked syntactic contexts shared
  by the auditor and the hook kernel.
- Hardened the resolver entry's argument normalization and pinned
  worker-crash, revision-exhaustion, and join-conflict recovery legs.
- Added the pre-commit generation gate and the native-nightly workflow
  (deterministic evidence checks plus secrets-gated live smokes), and audited
  the test suite for load-bearing coverage.
- Removed all legacy engine, client, broad options, profile, background-driver,
  replay-stream, and provider-wide tool-registry modules. There is no legacy
  facade.
- Fixed `LocalProcessLauncher` to capture through pipes so git output stays
  plain regardless of the host pager configuration, and made resolver resume
  treat the persisted phase as a monotonic high-water mark so hard-killed runs
  recover from every mid-phase kill window.
- Fixed a Claude launch to name every plugin directory the checkout carries
  rather than only the compiled one, so a project's hand-written plugin loads
  from its own tree instead of through a marketplace name — one global
  namespace whose winner is whichever checkout registered it last.

This was a clean breaking release with no compatibility facade: every removed
surface above has a replacement in the current API, which
[docs/library.md](docs/library.md) describes directly.
