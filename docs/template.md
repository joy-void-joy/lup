<!-- Generated from lup_template.devtools.harness.content.docs.template by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# The application template

`src/lup_template` is the half you fork. It is a complete working agent — an
`lup` application, a development CLI, and the harness declarations that
generate the native plugin trees — arranged so that adapting it to a new
domain is a series of small, obvious edits rather than a rewrite.

Three packages, split by what changes and how often.

| Package | Owns | Changes |
| --- | --- | --- |
| `agent/` | Reasoning. Prompts, output schema, tools, subagents, tool policy. No I/O. | Every time the domain does |
| `environment/` | I/O. The CLI that starts a run, the session lifecycle, what happens to a result. | When the surface changes |
| `devtools/` | Development. What this project adds to the inherited `lup-devtools` CLI, and the typed harness declarations. | When the workflow changes |

Keeping the agent free of I/O is what makes it improvable: the self-improvement
loop reads traces and changes prompts, tools, and models, and it never has to
reason about where a session came from.

```
src/lup_template/
├── agent/                   # Agent module for the self-improving loop.
│   ├── config.py            # Configuration management using pydantic-settings.
│   ├── core.py              # Application composition roots over Lup's provider-neutral runtime.
│   ├── models.py            # Output models for the agent.
│   ├── prompts.py           # The standing prose the agent is told: its task, its guidelines, and how to deliver a result.
│   ├── subagents.py         # Subagent definitions.
│   ├── tool_policy.py       # Decide which tools the agent is allowed to use this session.
│   ├── tools/               # Tools package - MCP tools and domain-specific utilities.
│   │   ├── example.py       # Example MCP tools showing the tool pattern and Data Augmentation.
│   │   ├── nested.py        # Nested Agent pattern (template).
│   │   ├── realtime.py      # Real-time MCP tools for persistent agents.
│   │   └── reflect.py       # Reflection tool — forced self-assessment before output finalization.
│   └── toolsets.py          # Single source of truth for the agent's MCP tool groups.
├── devtools/                # Development and analysis CLI tools for lup.
│   ├── agent/               # Agent introspection and interactive debugging tools.
│   │   ├── inspect_agent.py # Agent configuration inspection: tools, schemas, prompt, subagents.
│   │   ├── repl.py          # Interactive REPL with the agent via the SDK (continuous session).
│   │   └── serve.py         # Tool collection and the MCP stdio tool server (``serve-tools``).
│   ├── dev/                 # Dev operations: worktrees, branches, and pre-flight checks.
│   │   ├── app.py           # What only a template adds to the `dev` tree the library already builds.
│   │   ├── init.py          # Package renaming for downstream project initialization.
│   │   └── library.py       # How this project obtains the ``lup`` library.
│   ├── harness/             # Canonical harness generation and native launch commands.
│   │   ├── catalog.py       # Root of the project-owned harness declaration graph.
│   │   ├── composition.py   # What this project publishes through each native target, and what writes it.
│   │   └── content/         # Declaration leaves of the harness graph.
│   │       ├── assets/      # Typed harness content declarations.
│   │       ├── catalog.py   # This repository's harness content: what it inherits, and what only it has.
│   │       ├── docs/        # Typed source for every document under ``docs/``.
│   │       │   ├── catalog.py # Every document this repository publishes under ``docs/``.
│   │       │   ├── decisions.py # Architectural decisions behind the development tooling.
│   │       │   ├── index.py # The documentation index: what this repository is, and where each part is.
│   │       │   └── template.py # Guide to ``src/lup_template``, the application built on the library.
│   │       ├── guidance.py  # Canonical repository guidance.
│   │       ├── provenance.py # What a project settles about where its lup came from.
│   │       ├── requirements.py # The external programs this repository needs, and what going without costs.
│   │       ├── settings.py  # What this repository grants, refuses, and enables for itself.
│   │       ├── shell_vocabulary.py # Where this project's shell vocabulary differs from the one lup offers.
│   │       ├── skills/      # Typed harness content declarations.
│   │       │   ├── brainstorm.py # Canonical declaration for the brainstorm skill.
│   │       │   ├── import_skill.py # Canonical declaration for the import skill.
│   │       │   ├── init.py  # Canonical declaration for the init skill.
│   │       │   ├── install.py # Canonical declaration for the install skill.
│   │       │   ├── meta.py  # Canonical declaration for the meta skill.
│   │       │   └── update.py # Canonical declaration for the update skill.
│   │       ├── template_claude.py # Canonical downstream template guidance in its Claude flavor.
│   │       ├── template_codex.py # Canonical downstream template guidance in its Codex AGENTS.md flavor.
│   │       └── template_sections.py # Portable downstream-template sections shared by every guidance flavor.
│   ├── main.py              # Root CLI app composing all devtools sub-apps.
│   ├── setup.py             # This project's setup integrations, over the reusable wizard framework.
│   └── subapps.py           # This application's sub-app delta: what it declines, and what only it has.
└── environment/             # Environment harness — how the outside world reaches the agent.
    └── cli/                 # CLI package for the environment client.
        └── __main__.py      # Environment CLI for running agent sessions.
```

Nothing above is written down. The structure is walked from the checkout when
this page is generated, and each caption is the module's own docstring — a
package's from its `__init__.py`. So a module that is renamed, moved, or
re-described changes this page by being edited, and one that is deleted leaves
it by being deleted. A module with no docstring simply has no caption, which
is the only nudge this page gives about writing one.

## `agent/` — what you change first

| Module | What it holds | Adapt it by |
| --- | --- | --- |
| `models.py` | `AgentOutput` and `Factor`: the structured result a turn must submit. | Replacing the fields with your domain's result. The prompt's output section is generated from this schema, so it cannot drift. |
| `prompts.py` | The system prompt composed from named sections. | Editing `PURPOSE` and `GUIDELINES`. Leave `output_format()` alone — it reads the schema. |
| `toolsets.py` | The MCP tool groups a session gets, as one registry. | Adding a group to `build_session_toolset()` and to the `ServerGroup` literal beside it. |
| `tools/` | The tool implementations. `example.py` is placeholder search/fetch/read/glob; `reflect.py`, `realtime.py`, and `nested.py` are working patterns. | Replacing `example.py` with your domain's tools. |
| `subagents.py` | Portable `SubagentSpec` declarations and their tool lists. | Adding specs to `ALL_SPECS`. |
| `tool_policy.py` | Which tools are available given the configuration — a missing API key bans its tools rather than failing at call time. | Adding an exclusion for each new conditional dependency. |
| `config.py` | Pydantic settings from `.env` and `.env.local`: model, budget, turn cap, sandbox, paths. | Adding settings, never reading the environment directly elsewhere. |
| `core.py` | `provider_factory()` — the **one** place a concrete adapter is named. | Rarely. Everything downstream takes the portable `SessionFactory` it returns. |

That last row is the load-bearing one. `seam-boundary` permits a concrete
adapter import in `agent/core.py` and a short list of other composition roots,
and rejects it everywhere else — so provider choice cannot spread by
accident.

## `environment/` — where a run begins

`environment/cli/__main__.py` is the `lup` entry point, with `run` and `loop`
commands. A run opens a session through the agent's factory, executes the
task, and disposes of the result. The template's disposal is a git commit of
the session directory, which suits a batch domain and is the first thing an
interactive domain deletes.

The boundary is deliberate: outside events arrive here, and only here.

## Configuration

`.env` holds the template's committed defaults; `.env.local` holds secrets
and personal overrides and is gitignored. `.env.local` wins where both
declare a value. `ANTHROPIC_API_KEY` is read straight from the environment by
the SDK; everything else is loaded through pydantic-settings in
`agent/config.py`, which is the only module that reads the environment.

```bash
# .env.local — secrets and overrides

# AGENT_MODEL=claude-opus-5
# AGENT_MAX_BUDGET_USD=5.00
# AGENT_MAX_TURNS=50
# AGENT_SANDBOX_ENABLED=false   # run without Docker (disables code execution tools)
# AGENT_NOTES_PATH=./notes      # relocate session data
# AGENT_LOGS_PATH=./logs        # relocate trace logs
```

## `devtools/` — the development CLI

`lup-devtools` is the second entry point, and most of it is not here. The
workflow sub-apps live in `lup.devtools` and are *inherited*: an upgrade
brings their improvements without a merge, which is the point — they are
development tooling, not this domain, and a fork of them goes stale the day
it is taken. `devtools/subapps.py` names the ones this project takes and
declares the ones only it has; `devtools/main.py` is where each name meets
the app answering to it.

That is also where `usage` is decided, twice over: whether to serve it, and
which backends' accounts it reads. The display, the pacing bars, and the
snapshot live in `lup.usage`; each adapter contributes a reader that turns
its own account call into the one report shape, and the roster composes the
display around the readers it names.

- `agent` — Agent introspection and debugging
- `dashboard` — Host the local setup dashboard
- `dev` — Worktrees, branches, and pre-flight checks
- `feedback` — Feedback state, metrics, and commits
- `harness` — Generate and launch the native harnesses
- `hooks` — Query the permission policy
- `py` — Python module introspection
- `report` — Everything left to implement, in one place
- `setup` — Interactive setup wizard
- `sync` — Track sync.json repos and review their commits
- `trace` — Trace display, search, and analysis
- `usage` — Runtime usage display
- `version` — Agent version, changelog, and bump

Run `uv run lup-devtools --help` for the full command tree. The three you will
use daily:

- **`dev`** — worktrees, branches, pull requests, conflict resolution, review
  markers, and the pre-flight `dev check`. This is the git workflow.
- **`harness`** — generate, verify, and launch the native trees. See
  [harness.md](harness.md).
- **`trace`** — read what a session actually did: `trace show`, `trace search`,
  `trace errors`.

If you run the same shell incantation twice, add a command here instead. The
CLI is written with [typer](https://typer.tiangolo.com/), and shells out with
[sh](https://sh.readthedocs.io/) rather than `subprocess`. One-off work goes
through the reviewable ladder in
[contributing.md](contributing.md) rather than a script in `tmp/`, which is
gitignored and so reaches no diff and no reviewer.

### `devtools/harness/` — the declaration graph

The harness lives under devtools because generating it is a development
activity. `catalog.py` is the root: it assembles the skills and agents from
`content/` with the application-owned `HookSet` and the resolver spec into one
`Harness`. `content/` holds the leaves — one module per skill, per agent, per
document — and `generate.py` compiles them. [harness.md](harness.md) is the
guide; this is only where the files are.

### The setup dashboard

`uv run lup-devtools dashboard` serves a local browser interface at
`http://127.0.0.1:8765`. It is the web face of the same declarative
`INTEGRATIONS` registry that `uv run lup-devtools setup` walks in the
terminal: a domain customizes the registry once and gets both.

A progress-oriented wizard covers first setup; an all-integrations view covers
later maintenance. Browser forms are generated only for declarative
environment fields, from an explicit per-integration allowlist, so the page
cannot write an arbitrary variable; anything needing OAuth or bespoke
validation routes to its existing CLI command. FastAPI serves one packaged
HTML asset — zero build, no Node — and `--no-open` and `--port` cover the
cases where the defaults do not fit.

`--host` takes only a loopback address, and every request's `Host` header is
checked against one. The page writes credentials into `.env.local`, and a
local bind alone leaves that reachable by DNS rebinding from any page the
browser has open. Both halves are `lup.web.loopback`, shared with the
resolver's supervisor page; see [supervisor.md](supervisor.md).

### The sync registry

`lup-devtools sync` tracks the other repositories this project exchanges
improvements with and reviews their commits since the last sync. The /lup:update and /lup:import skills are built on it. Two files declare
what to track.

**`sync.json` (committed)** is the template's default registry. It ships with
a single entry — the repository this template comes from — so a fresh project
can immediately pull template improvements:

```json
{
  "projects": [
    {
      "name": "lup",
      "url": "https://github.com/joy-void-joy/lup"
    }
  ]
}
```

It is scaffold, not personal state. **Agents must never modify the tracked
`sync.json`**, and neither should routine project work; the edit policy
enforces this by treating it as a protected path. Every personal registration
belongs in the gitignored **`sync.json.local`**: local paths, per-project
`last_synced_commit` state, branch overrides, `"ignore": true` opt-outs, and
additional projects. Entries there override tracked entries by name or add
local-only ones, and `sync setup` and `mark-synced` write only there.

The registry has no direction in its name because direction depends on where
you sit. A project built on the template keeps the shipped `lup` entry and
pulls *from* it. The lup repository itself sets `"ignore": true` on its own
entry and registers its downstream fleet in `sync.json.local`, so /lup:update can generalize emerged patterns back into the template. Same
registry, opposite seats.

Repositories created before the rename may still carry
`downstream.json`/`downstream.json.local`; the tooling reads them as a
fallback with a deprecation warning, and renaming the files is the migration.

## How the two halves depend on each other

`lup_template` imports `lup`. `lup` never imports `lup_template` — it is
published standalone and could not. The placement test for any new utility is
the same question in both directions: *would another project built on lup want
this?* If yes it belongs in `packages/lup/`; if it only makes sense for this
application it belongs here.

`lup[claude,codex,docker]` is declared as a workspace dependency in the root
`pyproject.toml`, so a checkout resolves the library from source and an edit to
either half is immediately live in the other.
