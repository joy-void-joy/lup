
## Authoring

### Add a skill

Create two files beneath `content/skills/` — the library's half when the
skill automates work inside a project, this repository's when its subject is
standing one up. The declaration is typed Python; the prose is Markdown
beside it, named for the module and read as its passage:

```python
"""The project-triage skill."""

from lup.harness.models import Argument, ArgumentsRef, Passage, PromptDocument, Skill

SKILL = Skill(
    id="skill.triage",
    name="triage",
    description="Classify one reported problem and identify the next investigation",
    arguments=[
        Argument(
            name="report",
            description="Problem report or error text to classify",
            required=True,
        )
    ],
    prompt=PromptDocument(
        parts=[Passage(module=__name__, values={"report": ArgumentsRef()})]
    ),
)
```

Beside it, `triage.passage.md`:

```markdown
Read the report, inspect the relevant boundary, and return the
most likely failure class with one concrete next check.

Report:
{{ '{{' }} report }}
```

A passage names values and nothing else. A statement tag ({{ statement_tag }})
or a comment tag ({{ comment_tag }}) is refused where the file is read, so
prose varying by more than a value is two passages, or a declaration in
Python that says which one is read. Every value is a part — an
`ArgumentsRef`, a `SkillInvocation`, a path through `code()` or `plain()` —
so it enters escaped, and a description carrying a backtick cannot close the
span it lands in. A name the values never carried fails generation rather
than rendering as a blank.

Import it into the module whose subject it serves, under `content/modules/`,
and name it in that module's `ContentRoster`. That is the whole registration:
a skill reaches a project because its module does, and there is no second
roster to add it to as well. Explicit imports make a misspelled or missing
module a type-checking error; there is no dynamic registry and no barrel file.
A declaration file no module claims fails `dev check`'s module-coverage sweep
rather than shipping unnoticed — and where no existing module is about the
skill's subject, that is a new module rather than a stretched one.

Then run the authoring loop:

```bash
uv run lup-devtools harness generate all
uv run lup-devtools harness check all
uv run ruff check packages/lup/src/lup {{ project_directory }}
uv run pyright
uv run pytest tests/unit/test_harness_compilation.py -q
```

A declaration must not branch on a provider name. Argument declarations and
`ArgumentsRef` must occur together — model validation rejects either alone.
Use semantic prompt parts such as `ArgumentsRef` or `SkillInvocation` and let
each renderer choose its spelling;
[platform-differentiation.md](platform-differentiation.md) records what prose
may and may not name.

### Add a document

Documentation is generated the same way. Add a module under `content/docs/`
in the half whose subject it is, list it in that half's
`content/docs/catalog.py`, and regenerate. The banner is applied from the
roster, so a document module holds prose only. The index builds its rows from
the documents both halves declare, so a page appears there by being declared
— and a page it lists that stops being published fails generation rather than
leaving a link that resolves to nothing.

### Change the fetch allowlist

The application-owned `HookSet` is constructed by `portable_harness()` in
`{{ harness_catalog_py }}`. Add the narrowest origin and
path prefix that supports the workflow:

```python
allowed_fetch=[
    HookUrlScope.model_validate(
        {
            "origin": "https://docs.example.com",
            "path_prefix": "/agent-api/",
        }
    ),
]
```

Origins normalize into scheme, host, port, and path-prefix rows. Put an
explicit exclusion in `denied_fetch` when a permitted host has a sensitive
subtree; deny rows win over allow rows. Never add provider-specific fetch
logic to the kernel or a generated dispatcher.

Regenerate and run the policy fixtures:

```bash
uv run lup-devtools harness generate all
uv run pytest tests/unit/test_semantic_policy.py -q
uv run lup-devtools harness check all
```

Inspect `hooks/runtime/policy_data.py` in both generated trees. The rows should
change while `hooks/runtime/kernel.py` stays identical: configuration is
generated data, policy control flow is one copied module.

### Change the shell classification

The shell auto-allow vocabulary is data too. The baseline lives in
`lup.policy.vocabulary` (`default_vocabulary()`) as a readable table, and every
rule in it states what the command *does* rather than what that earns: a
subcommand command falls off its own enumeration into
`unclassified_operation`, and each verb it lists declares its own effects. To
teach the fleet a downstream toolchain, append rules through the `HookSet` in
`catalog.py` — never edit the kernel:

```python
shell_rules=[
    ShellCommandRule(
        name="cargo",
        effects=[declare("unclassified_operation", scope="cargo")],
        subcommands=[
            ShellSubcommandRule(
                name="check", effects=[declare("reads_path", scope="project")]
            ),
            ShellSubcommandRule(
                name="build",
                effects=[declare("writes_path", scope="scratch", write="create")],
            ),
            ShellSubcommandRule(
                name="test", effects=[declare("runs_declared_target")]
            ),
        ],
    ),
]
```

The extension is concatenated onto the baseline and erased into the same
`SHELL_RULES` rows the kernel interprets. A universal command every repository
should trust belongs in a `lup.policy.vocabulary` group instead. Regenerate and run the
policy fixtures exactly as above.

`effects` is required, so a rule that forgot to say is a type error rather
than a grant nobody wrote down, and a verb that genuinely does nothing this
table guards says `changes_nothing`. Nothing here states a verdict: the two
ways to reach one are declaring an effect that asks —
`installs_dependency`, `external_mutation`, `mutates_environment` — or, where
the objection is to the *spelling* rather than to the operation, setting
`refuses` with the route to take instead. A destructive form under an
allowing verb is guarded by naming the flag in `ask_flags` and what it adds
in `flag_effects`, so the question names the operation somebody is actually
being asked about.

Every axis cascades, so each subcommand above states its own `effects` rather
than leaving them out — omitting a field means "inherit from the level above",
never "allow". The same cascade is what lets `sandbox="outside"` be declared
once on a command and reach every verb beneath it. Run
`uv run lup-devtools dev vocabulary --provenance` to see which level supplied
each half of every rule, and `dev vocabulary --json --output <path>` before and
after a reshaping to confirm no verdict moved that you did not move.

Then sweep what an ordinary session runs. `uv run lup-devtools dev hooks sweep`
classifies the everyday corpus this project declared in
`HookSet.everyday_commands` and exits non-zero on anything that is not a plain
allow — the one measurement that reads the direction a *tightening* shows up
in, since a provenance diff and a verdict census both go on agreeing when a
de-escalation quietly stops firing. Each command is swept once per posture a
session runs in, so a rule that only asks where nobody can answer is caught
too. `dev check` runs the same sweep, so a rule that stopped `git status`
fails there rather than in somebody's session.

### Put a program in the image

A package reaches the container through one of three doors, and picking the
wrong one is how a tool ends up absent with nothing having said so.

`Image.baseline` is the library's answer to what any shell session needs to be
usable at all — `git`, `curl`, `jq`, the registry managers. It is not a place
for a project's own tools, and overriding it means restating every name in it
to add one.

A `Requirement` in the manifest is what a declared *capability* asked for. It
takes a purpose, an exercise that proves a machine has the thing, and a policy
for going without — so it is the right door exactly when the absence deserves
a diagnostic. It is the wrong one otherwise: a manifest that invents
prerequisites refuses machines that were fine, which is why ripgrep was
declared here once and taken back out.

`Image.tooling` is the third, and the one for a program this project's work
simply needs present. Declared where the image is composed:

```python
return Image(
    egress=SessionEgress(mode="host"),
    tooling=[
        Package(name="poppler"),
        Package(name="prettier", manager="bun", version="3.4.2"),
    ],
)
```

Whole packages rather than bare names, so a registry package is pinned and
reached through the manager that obtains it. Nothing exercises these: a name
the manager cannot resolve fails the build and names itself, which beats a
probe. `dev seams` reports what this project declared and where.

## Resolving a conflict

`harness reconcile` compares the current files, the desired render, and the
ownership manifest. It mutates nothing. A conflict means one of these:

| Category | Meaning | Action |
|---|---|---|
| `backpropagation_candidate` | A previously generated file differs from its owned digest. | Reproduce the intended change in the typed content or policy source, then regenerate. |
| `unknown_conflict` | Lup has no ownership proof for the existing bytes. | Decide whether the file belongs in typed generation or should stay local-only. |
| `local_only` | The recipe deliberately leaves the path to the user. | Keep it outside generation. |
| `sensitive_local_only` | The path may hold credentials or trust state. | Never import or commit it through the harness. |

The ordinary path is short:

```bash
uv run lup-devtools harness reconcile all
# edit the corresponding module under harness/content/ or harness/catalog.py
uv run lup-devtools harness generate all
uv run lup-devtools harness check all
```

Do not resolve a conflict by deleting an unknown file. Classify its ownership,
or leave the conflict explicit.

### Applying a source-patch proposal

A source-aware tool may produce a Git-format patch against canonical Python
without applying it. Keep the source tree at the patch's preimage, then persist
the proposal:

```bash
uv run lup-devtools harness propose-reconciliation tmp/source.patch
```

The command prints a proposal id and writes immutable `source.patch` and
`metadata.json` under `.lup/reconcile/<id>/`. Review both files and the named
preimages, then apply only the reviewed proposal:

```bash
uv run lup-devtools harness apply-reconciliation <proposal-id>
```

Apply verifies the patch digest, proposal identity, and current preimage digest
before showing the patch and asking for confirmation. It then runs
`git apply --check`, applies the canonical-source patch, regenerates both
targets, and removes the consumed proposal. A changed preimage, malformed
path, digest mismatch, or non-applying patch stops before any mutation.

This is a patch transport, not a native-body importer. A rendered artifact is
never parsed heuristically back into Python.

## Launch and trust

Generated plugins carry their own policy runtime and dispatcher; hook execution
imports neither `lup-devtools`, this checkout, nor its virtual environment.
Both decoders convert native tool payloads into the same semantic
edit/shell/fetch/search vocabulary, shared policy evaluates it, and each
adapter renders the decision back — Codex `ask` being a documented fail-closed
exit-code-2 approximation.

Codex packages install through the native plugin CLI only when a separately
installed, content-addressed cache revision is absent. Installed revisions are
immutable and retained so concurrent sessions keep valid hook paths; the source
plugin is never mistaken for the cache. Personal trust state, credentials,
active run state, and cache contents are never generated or committed. Review
hook trust with the native hooks surface after generation.

### Opening a session the anti-pattern gate leaves alone

`--ignore-antipatterns`, on both launchers, for the sessions where the rules
are not the point: exploring, spiking, or working over code these conventions
were never written for.

It reaches the gate rather than the command line, which is the only thing that
would make it work. The anti-pattern table is projected into each plugin's
hermetic edit policy at generation time, and `ready_to_open` regenerates before
it opens — so the flag compiles the tree the session actually runs against.
What it sets is `RuleSelection` with every id retired, spelled as the ids
rather than as a flag meaning "all of them", because the selection is
subtractive and a rule added later should be one the selection has visibly not
answered for.

Three things it deliberately does not do, each announced at launch because each
bites later and none announces itself:

- **The sweep does not follow.** `dev check --antipatterns` reads the
  repository's own declaration, so a session that edited freely under the flag
  will fail it. That is the point rather than an oversight: a transient switch
  must not quietly become the repository's answer.
- **The committed tree is rewritten.** Regenerate before committing, or the
  commit carries a plugin nothing declares.
- **It is not how a project drops the rules.** `dev seams --retire-all` is,
  because that writes the decision where a review sees it and `--keep` takes it
  back.

### Reopening a session, and why a launcher owns it

Both launchers reopen an earlier session, from one declaration and in each
runtime's own words:

| request | flag | Claude | Codex |
|---|---|---|---|
| the most recent session here | `--continue` / `-c` | `--continue` | `resume --last` |
| choose from a picker | `--resume` | `--resume` | `resume` |
| one session by id | `--session <id>` | `--resume <id>` | `resume <id>` |

The shapes are genuinely different rather than differently named — a
subcommand has to lead the argument vector where a flag does not — which is
why `Resumption` carries the request and each adapter's function carries the
words. Naming two at once is refused rather than ranked, before anything is
generated.

This exists for more than convenience. The policy a session enforces is
compiled into the plugin tree its runtime loads **at startup**, so widening
that policy takes effect only in a new process. Without reopening, the price
of every widening is the conversation that established what it was for — which
is what pushes an agent toward a per-call escape that helps once and
evaporates. With it the durable path is also the cheap one:

1. The agent proposes the declaration edit. The policy source is a protected
   path, so the edit surfaces as an approval with the diff in it.
2. Approve it — what is approved is the rule, not one command.
3. `harness generate all`, or just relaunch — the same thing: a launcher
   regenerates every declared tree on the way in, not only the one it opens.
4. `harness claude --continue` / `harness codex --continue`. The reopened
   session is already running against the tree the approval produced.

### Where a profile comes from

A profile names one account and the configuration home it runs under, and which
origin holds them is the project's to choose. A project that keeps accounts of
its own keeps one directory per name — `.lup/profiles/<name>/`, with each
runtime's home in the subdirectory that runtime's login names (`claude-config/`
for Claude Code, `codex-home/` for Codex) — so a name resolves inside the
checkout
rather than against anything under the operator's home, and `.lup` already being
ignored is what keeps a login out of a commit. A project that keeps none falls
back to the personal registry at `~/.lup/profiles.json`, whose names are
registered by hand and each carry wherever its home already lives.

`harness profile` and `setup profile` curate whichever origin the project
supplied — `list`, `add`, `use`, `remove` — and `harness claude --profile`
selects one for a single launch. Naming none selects the active profile; naming
none with none active leaves whatever home the surrounding environment already
selected, so a session launched from inside another stays on the account it was
started under. A name no origin answers to is refused with the roster that would
have answered, at the launcher as well as at the command tree.

A directory profile's home is derived from its name, so `add --config-dir`
pointing elsewhere is refused, and `remove` says to remove the directory rather
than forgetting it: the directory is the profile and it holds the login. To
point one at a home that already exists, symlink that subdirectory at it.

### Workspace trust, and the profile it is recorded against

Claude Code keeps workspace trust in its user-level configuration document,
and offers nowhere else to put it — so an untrusted workspace is not a
project-level fact a repository can declare for itself. An untrusted one does
not fail: the session drops every `permissions.allow` entry
`.claude/settings.json` declares, warns into its own stderr, and runs on under
a permission posture the repository never declared.

A headless run cannot accept a dialog, so it establishes trust itself. Each
workspace's sessions are pointed at a private configuration home derived under
the selected profile, and trust is recorded there — never in the operator's own
document — for the repository the run was invoked against and the checkouts the
run made of it, and nothing else a session happens to open in. Pointing a run at
a repository is the act of trust; a workspace outside that stops the run rather
than degrading it.

`CLAUDE_CONFIG_DIR` selects which profile all of this reads and writes. Where it
is set, the document is `.config.json` inside the named directory; where it is
unset, the document is `~/.claude.json` beside the home rather than in it, and
the derived homes still land under `~/.claude`. Both spellings matter for an
interactive fix: accepting a trust dialog in a shell that does not export the
same variable writes to a different profile and appears to do nothing.
### Reviewing a session's edits in an editor

Reviewing a whole-file write in a terminal is reading a wall of text and
deciding. An editor renders the same approval as a side-by-side diff you can
edit before accepting it, and a contained session can reach one on the host.
Nothing had to be built for this — the pieces were already here — so the recipe
is the whole of it:

1. Install the editor's Claude Code extension.
2. Open the editor on the checkout the session runs in.
3. Set `diffTool` to `auto` in your own Claude Code settings. It is global
   configuration rather than anything this repository declares, and the entry
   appears in `/config` only while an editor is connected.
4. Launch the session as usual, then `/ide` inside it.

`--profile` is not a reason to avoid any of this. The bridge binds the
lockfile directory the *editor* uses — resolved from `CLAUDE_CONFIG_DIR` as the
editor's own process reads it — so which account the session runs under and
which editor it talks to are independent. Each launch says which directory it
bound, so a bridge that will not connect is visible at the top of the session
rather than as an editor that never appears.

`/ide` is spelled out because a container is neither case the vendor documents:
a CLI started from the editor's own terminal attaches on its own, and one
started from an external terminal attaches when `autoConnectIde` is set. A
contained session is documented as neither, so it asks.

Two checkers will otherwise disagree over the same files. This repository
already refuses Claude Code's own `pyright-lsp` plugin, because the per-edit
check in the policy's host half is the one wired to the gates. The editor's own
Python checker is a third opinion and is not this repository's to turn off:
set `python.analysis.typeCheckingMode` to `off` in your editor if its
diagnostics start contradicting the ones the gate produces.

**Codex has no equivalent, and this is not an omission.** Its extension drives
the app-server and spawns its own core, so there is no lockfile rendezvous to
bridge; `ProviderLogin.editor_lockfiles` records that as a declaration rather
than as prose. The only attachment point the vendor exposes is a setting
naming the executable to run, which its own description marks as for
development only, warns may break the extension, and scopes to the whole editor
install — so it cannot differ per worktree, and it is user-level configuration
this repository does not write. A Codex editor session would need the extension
host inside the image, or a host posture with a prepared home. Neither is
built, and neither is needed for the review problem: what a Codex session's
reviewer reads is `dev questions show`.


Commit generated artifacts together with the catalog changes that produced
them. [contributing.md](contributing.md) covers what review looks for.
