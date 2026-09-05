(Written by an agent, for now. This README will be rewritten from scratch by a human later, and the repository reviewed by one as well.)

# Lup

A meta repository for speed-boosting your Claude Code and Codex development, and for building self-improving [ClaudeAgentSDK](https://platform.claude.com/docs/en/agent-sdk/overview) and [CodexSDK](https://learn.chatgpt.com/docs/codex-sdk) applications.

<img width="1535" height="863" alt="image" src="https://github.com/user-attachments/assets/d5159e28-1669-433b-8f89-e012c3abfa1c" />
<img width="1532" height="554" alt="image" src="https://github.com/user-attachments/assets/6f272a6e-71b6-4720-89bf-6b811081343d" />

> **TBD.** This is a short map of the repository, not a manual. Each construct below is one line; the long-form description of each still needs writing. `docs/` carries what exists today.

## What it is

Two things that grew together. A **library** for building tool-using agents that stay provider-neutral — the same declaration compiles to a Claude plugin and a Codex one — and a **template** that uses it, with the scaffolding for improving an agent from its own recorded sessions.

The bet is that the setup is part of the product: when the workflow hurts, you fix the workflow. Slash commands, permission policy, devtools and this guidance are all editable from inside a session, and regenerate rather than drift.

## Getting started

Install [uv](https://docs.astral.sh/uv/) and [fzf](https://github.com/junegunn/fzf); Docker only if you want the sandbox.

- **Fresh repository** — "Use this template" on GitHub, then `/lup:init <what you are building>`, or `/lup:brainstorm` to shape it first.
- **Existing repository** — clone lup inside it and run `/lup:install`.

## The constructs

### The library — `packages/lup`

A uv workspace member any project can depend on unmodified. Provider SDKs sit behind adapters, so nothing in an application imports one.

| Module | What it is |
| --- | --- |
| `sessions` | Provider-neutral session/turn engine: how any one agent turn runs |
| `tools` | What an agent is given to act with, and what decides which of it it gets |
| `providers` | Native implementations of the independently composed capabilities |
| `policy` | Semantic permission policy that must decide identically in two homes |
| `harness` | Canonical agent declarations compiled to native plugins |
| `resolver` | Provider-neutral resolution of reviewed code concerns, split by concern |
| `runs` | Work that outlives the tool call which started it, and stays watchable |
| `execution` | What carrying work out runs into, and what to do about each of it |
| `orchestration` | Running more than one piece of work, and staying able to speak to it |
| `sandbox` | Docker-based Python sandbox |
| `workspace` | Where a run's data lives and how it is addressed |
| `observability` | What happened, recorded so that a later reader can answer for it |
| `channels` | File-backed channels: a value that settles, and an ordered log |
| `formats` | What a generated artifact is written as, at the leaf where data enters it |
| `web` | Local web surfaces: the boundaries a page served on this machine keeps |
| `devtools` | The `lup-devtools` CLI, half of it reusable and half template-specific |

#### Runtime capabilities

Optional behavior is present on `SessionHandle` and `TurnHandle` or absent as `None` — no unsupported-operation stubs. This checked-in evidence targets Claude Agent SDK 0.2.89 and Codex CLI/app-server 0.144.4; regenerate it with `uv run lup-devtools agent capabilities --markdown` when native evidence changes.

| Capability | claude-sdk-0.2.89 | codex-app-server-0.144.4 |
| --- | --- | --- |
| live_events | ✅ | ✅ |
| interrupt | ✅ | ✅ |
| steer | — | ✅ |
| fork | ✅ | ✅ |
| resume | ✅ | without a fresh dynamic tool |
| typed_submission | reconnect per turn | thread-start schema only |
| background | ✅ | ✅ |


Codex accepts dynamic tools only on `thread/start`, so Lup rejects a typed-schema transition or typed resume rather than silently using a stale schema.

### The template — `src/lup_template`

- **`agent`** — the part the feedback loop improves: orchestration, prompts, output models, subagent specs, MCP tools, and the tag-based tool policy. `/lup:init` renames it for your domain.
- **`environment`** — the domain scaffolding around the agent, and the `lup` CLI that runs sessions.
- **`devtools`** — the commands that are about *being this template*, composed with the library's half into one CLI.

### The plugin

33 commands and 4 subagents, rendered from typed catalogs into both `.claude/` and `.codex/` — generated trees, never hand-edited.

- **Gates** — one semantic policy drives both native dispatchers: every shell segment, URL scope and edit in a batch is classified, and a denial names what tripped and how to answer it.
- **Commands** — the workflow (`commit`, `rebase`, `merge`, `land`), the meta-workflow (`add-command`, `hooks`, `meta`, `principle`), and the feedback loop (`feedback-loop`, `review`, `bump`).
- **Subagents** — trace and version explorers, a version reviewer, and a TDD implementer that writes production code without touching tests.

## Workflow

Work happens in git worktrees, one directory per branch under `tree/`. `dev worktree create <name>` opens one, `dev check` runs format, lint, pyright, tests and drift before a PR, `/lup:rebase` cleans the history and opens it, and `/lup:land` drives every branch to a terminal state. Sessions write traces that `/lup:feedback-loop` reads back to decide what to change — tools first, prompts last.
