(All code in this repository has been reviewed by humans, this README has been written by a human)

# Lup

A meta repository for speed-boosting your Claude Code development and create self-improving [ClaudeAgentSDK] applications

<img width="1535" height="863" alt="image" src="https://github.com/user-attachments/assets/d5159e28-1669-433b-8f89-e012c3abfa1c" />
<img width="1532" height="554" alt="image" src="https://github.com/user-attachments/assets/6f272a6e-71b6-4720-89bf-6b811081343d" />

# Why this repo?

I believe that claude code may be underappreciated right now. Not just the agent, but its [SDK](https://platform.claude.com/docs/en/agent-sdk/overview). The SDK of claude code allows it to:

- Think through a task by using many tools to fetch information, and decompose it carefully
- Delegate part of its task to other agents through tool calls that augment or gatekeep the results
- React in real time through auto-deny hooks and get_current_state tools

... all of that through your claude code subscription, without having to pay any extra API cost or setup.

The basic pattern is to create a ClaudeAgentSDK client, connect many tools to it (like fetching from APIs, searching the web, executing code, interacting with the world) and let claude code decide when to call them.

I've found developping those SDK applications with the help of Claude Code to work very well, as well as using Claude Code to improve the whole development scaffolding, using it to add /-commands that speeds up my development, to document general principles and developping devtools to help me or itself navigate it faster. More importantly, Claude Code can review results from past sessions, and tweak the agent based on it, be it its tools, prompts, or all aspect of the pipeline and workflow.

This repository is focused on this sort of agent-improvement and meta-self-improvement. It contains tools for storing the traces of all past agents, versionning the current agent, commands for reviewing them and seeing how to improve based on it, common multi-agents pattterns I've found useful, as well as meta-commands to add commands or review your own development with Claude Code.

Over writing and reusing this technique over the past month, I have come to find that having a template and plugin as a base can really speed up the development and the coherence of Claude. This repository is a sort of extract of all the common patterns and plugin command and scripts I have found useful.

It is a template to help bootstrap this pattern and create your own ClaudeAgentSDK easily.

# Examples

Some examples of things I'm using this self-scaffolding for (still in early WIP):

- [joy.void.joy-bot]: Not yet opensource. A forecasting agent written for the [FutureEval] tournament. Basically this repo with news-searching and many API-fetching tools, and using the feedback-loop mechanism on newly resolved/retrodicted forecast
- [harmon]: real-time discord bot focused on presence and reactivity/helpfulness, as well as background tasks. The tools here are things like reply, follow_ups, sleep, and contains a gate that forbids it from replying if it hasn't read the new messages first.
- [mettle]: A bot whose main tool is writing its own tools
- [botc]: Having bots compete with one another while playing [Blood on the Clocktower]

But you could use it for so much more. Real-time monitoring, mathematical proofs or formal verification or for [[AIMO3]], anything that can be automated where the kind of resources or tools it needs is easy to explore and refine.

# Getting started

To start using this repo either:

- For a fresh repository: Use the "Use this template" button on github, or clone this repository. In the newly cloned repository, use /lup:init [description of your project] or /lup:brainstorm to first flesh out the broad shape of it
- For an already existing repository, clone lup inside it, and either use /lup:install to install the bare plugin, or /lup:install --interactive to pick which pieces (plugin, devtools, feedback scaffolding) to bring in

You will need to install [uv] for python management and [fzf] for fuzzy-file matching. Docker is an additional dependency if you plan to use the sandboxing capabilities.

To run the inner agent once everything is synced:

```bash
uv run lup run "your task here"            # single session
uv run lup loop "task1" "task2"            # batch with auto-commit
AGENT_SDK=codex AGENT_MODEL=gpt-5.5 uv run lup run "same task, Codex backend"
```

The agent runs on the Claude Agent SDK by default; setting `AGENT_SDK=codex` (or `openai` for any OpenAI-compatible endpoint) runs the same agent — same tools, reflection gate, structured output — on the Codex runtime. Budget caps and persistent (sleep/wake) mode work on every backend too: `AGENT_MAX_BUDGET_USD` on codex/openai needs `CODEX_USD_PER_MTOK_*` rates in `.env` (the Codex SDK reports tokens, not cost), and persistent mode runs in-process on Claude or through the file relay (`lup.realtime_relay`) on the Codex runtime.

### Backend support

The portable contract is **tiered**, deliberately. Tier 1 — the core loop every backend gets — is: run → MCP tools → reflection gate → `submit_output` finalization → session JSON, traces, and metrics, plus subagents (native on Claude, the `run_subagent` tool elsewhere), budget caps, and persistent mode. Tier 2 is Claude-native and intentionally unported: in-process hooks, parallel native subagents, permission modes, live streaming, and SDK-reported cost. Don't generalize Tier 2 features into the adapter abstraction — pass native options to `ClaudeAdapter` instead.

Each adapter declares what it supports (`adapter.capabilities`); the matrix below is generated from those declarations (`uv run lup-devtools agent capabilities --markdown`) and a regression test keeps it current:

| Capability | claude | codex | openai |
|---|---|---|---|
| hooks | ✅ | — | — |
| native_subagents | ✅ | — | — |
| streaming | live | post_hoc | post_hoc |
| interrupt | ✅ | — | — |
| stop_event | ✅ | — | — |
| cost_reporting | native | rates | rates |
| duration_reporting | ✅ | ✅ | ✅ |
| permission_modes | ✅ | — | — |
| max_turns | ✅ | — | — |
| max_thinking_tokens | ✅ | — | — |
| background_tools | ✅ | — | — |
| realtime | in_process | relay | relay |
| turn_timeout | — | ✅ | ✅ |

(`rates` = cost is estimated from `CODEX_USD_PER_MTOK_*`; without them it degrades to `none`. Codex `duration` is wall-clock, not API-reported. Where there's no `stop_event`, the completion guard runs as corrective turns instead of a Stop hook. `turn_timeout` is the Codex-side substitute for `max_turns`/`interrupt`: `AGENT_TURN_TIMEOUT_SECONDS` cancels a runaway turn client-side after a wall-clock cap.)

**Security model per backend.** On Claude, enforcement is layered: PreToolUse permission hooks (per-tool, per-path), permission modes, and the SDK sandbox. On Codex/OpenAI there are **no hooks** (config.toml command hooks never fire — live-probed) and no permission modes: enforcement is the runtime's `workspace-write` filesystem sandbox plus in-tool checks (reflection gate, output validation). A Codex agent may run any command the sandbox permits — there is no command-policy or tool-allowlist layer. Domains that depend on fine-grained tool gating are Claude-only until Codex ships working hooks; `packages/lup/src/lup/adapters/codex_hooks.py` keeps the hook wire format quarantined, ready to re-verify.

The intended workflow while using this repository is to:

- Have it cloned as a bare repo with worktrees as siblings under `tree/`: `git clone --bare <url> myproject.git && cd myproject.git && git worktree add tree/main main`
- When working on a new feature, branching off with `uv run lup-devtools dev worktree create <branch-name>`
- Going into this new worktree, and working on it there
- Then /lup:commit it
- When it works and you've tested it works well /lup:rebase it
- Review it in github before merging it
- Call /lup:close on the merged branch or /lup:clean-gone on any branch (like main) to keep the worktree clean

# Overview

This repository contains many elements and code template that are designed to make creating your own scaffolding with ClaudeAgentSDK seamless:

- Code template and utilities to create a ClaudeAgentSDK with appropriate tools and hooks from scratch
- Many quality of life improvement to the claude code experience through a lup plugin
- devtools aimed at both human use and agent use
- Feedback loop and note-taking mechanisms for auditing and improving your agent

## Intended workflow

### Meta development

Whenever you hit a pain point in your own development flow, turn it into scaffolding: /lup:add-command creates a new slash command from a description, /lup:meta reviews and reshapes the whole .claude structure, and /lup:hooks adjusts the permission patterns. The repo treats your development workflow as just another agent to improve.

### Worktree management

All code changes happen in worktrees, never directly on dev. `uv run lup-devtools dev worktree create <name>` creates a sibling checkout under tree/, syncs dependencies, and refreshes the plugin cache. `lup-devtools dev check` runs the pre-flight (format, lint, pyright, pytest) before a PR, and /lup:rebase squashes history and opens it.

### Feedback loop

Every agent session writes its trace, structured output, and tool metrics under notes/traces/\<version\>/. The /lup:feedback-loop command (or the individual /lup:fb-\* stages) reads those traces, classifies failures, and proposes changes to tools, prompts, or pipeline — which you then land, bump with /lup:bump, and compare across versions.

# More thorough description

## Code template

### lib

packages/lup is the standalone library: SDK adapters (Claude, Codex, OpenAI-compatible) behind one AgentAdapter interface, the shared type vocabulary (lup.types), MCP tool plumbing, the submit_output finalization tool, the reflection gate, session storage, tracing, metrics, the Docker sandbox, and the persistent-agent scheduler. It is complete as-is and configurable through function arguments — domain code never modifies it.

### agent

src/lup_template/agent is the part the feedback loop improves: orchestration (core.py), output models, prompts, subagent specs, tool policy, and the domain tools (reflect, realtime, examples). /lup:init customizes these for your domain.

### Environment

src/lup_template/environment is the harness around the agent — the CLI that runs sessions and auto-commits results. It evolves with application requirements rather than via the feedback loop.

## Claude code plugin

This repository contains many quality of life improvements over the barebone claude code experience:

- Hooks for automatically aproving and denying edition and code executions: I am too worried with potential prompt injections and hallucination to let Claude Code run python unprompted. Likewise, I have found that letting claude code in auto-edit mode makes a patch of code that's quite unreadable with many questionable decision, no matter the initial direction and content of Claude.md. On the other hand, manually reviewing everything is exhausting and leads to counterproductive decision-fatigue where you just approve everything repeatedly. I have found that auto-denying python calls while pre-approving investigative commands (see #devtools) means it's manageable, and same for auto-accepting small edits.
- Commands and meta-commands for modifying your experience whenever you find a pain point (like /lup:add-command or /lup:meta)
- subagents specialized in reading the traces and the different versions of your project, and understanding the strength of one version over another
- fzf fuzzy matching for @ file references

### Subagents

The plugin ships analysis subagents the feedback loop relies on: trace-explorer reads session traces in depth, version-explorer and version-reviewer compare agent versions, and implementer executes prioritized changes from an analysis.

### Hooks

Three PreToolUse hook scripts manage permissions by pattern: auto_allow_bash.py (allow/deny rules for commands, last-match-wins), auto_allow_fetch.py (URL patterns for WebFetch), and auto_allow_edits.py (auto-allows small edits, counts "real" changed lines, detects anti-patterns like bare excepts or Any). /lup:hooks edits the patterns.

### Claude commands

To speed up development, many claude commands and meta-commands are built in this repository:

- add-command
- modify-command

- bump

- commit
- rebase
- merge
- clean-gone
- close

- create-investigator
- debug

- feedback-loop
- fb-status
- fb-investigate
- fb-analyze
- fb-reflect
- fb-implement

- hooks
- meta
- principle
- review

- refactor
- refactor-tools

- update
- import
- brainstorm
- install
- init

## Devtools

One CLI, `uv run lup-devtools`, with sub-apps used by both Claude and humans:

- `agent` — inspect the full agent configuration, serve its MCP tools (the Codex backend launches this as its tool server), chat or REPL with the agent
- `trace` — list, show, and search session traces; scan for errors and capability gaps
- `feedback` — collect session metrics, show analysis state, commit session results
- `dev` — worktrees, branches, PRs, conflict resolution, and the `check` pre-flight
- `py` — Python module introspection (signatures, sources, trees)
- `setup` — interactive wizard for integrations and API keys
- `sync` — track downstream/upstream repos for /lup:update and /lup:import
- `version` — agent version, classified changelog, version bumps
- `usage` — live Claude Code usage display with pacing
