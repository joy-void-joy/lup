# Guidance across launches: a resumed conversation runs under its launch's

**One sentence:** a conversation continued in a later launch runs under that launch's guidance, the system prompt rendered afresh on Claude Code and the managed developer message replaced on Codex, and the one hook's `SessionStart` tells it which sections changed since the launch it last ran in, read from the session's record lup keeps with its transcripts.

Issue #73. A launch puts its guidance at system level (`docs/launch.md`, *Guidance*), and a conversation brought back with `/resume` in a later launch kept the guidance of its first: on Claude Code 2.1.301, a related repository's old path, marked mounted, where the later launch had mounted it elsewhere. The guidance is where a session learns its walls, lup's tools, what's mounted and what waits for the operator, so any of these can go stale without a word. The facts below were read on 2026-10-16: Claude Code's docs (code.claude.com/docs/en: *hooks*, *cli-reference*, *sessions*) and its 2.1.301 binary's help (a byte search); Codex's docs (developers.openai.com/codex: *hooks*, *config-reference*) and its source at `rust-v0.163.0` (paths under `codex-rs/`), the same at `rust-v0.162.1` where checked. The operator took decisions 1, 2 and 6 on 2026-10-16, built first; 3 to 5 are designed with the transcripts module, and stay **(leaning)** until then.

## Why the conversation kept its first guidance

- **Claude Code records the system prompt.** "By default, Claude Code builds the system prompt once, on a conversation's first request, with the text from any system prompt flags applied, and records it in the session. Until the conversation is compacted, every later request uses that recorded prompt, including after you return to the conversation with `--resume` or `--continue`" (*cli-reference*, *System prompt flags in resumed conversations*). The 2.1.301 binary's help: "every later request and resume sends the record as-is, even when a later launch passes different text". `--system-prompt-snapshot off` (2.1.257 and later): "never record; the prompt is rendered fresh every request".
- **Codex sends a resumed thread its later `developer_instructions` only once it's compacted.** They're part of the initial context (`core/src/session/mod.rs`, `build_initial_context_with_world_state`), which Codex writes only to a thread with no recorded turn context, and again at a compaction (`core/src/compact.rs`); a resumed thread has one from its rollout, and after it only the changes to Codex's world state are written (`record_context_updates_and_set_reference_context_item`; the test `record_initial_history_restores_world_state_baseline` writes nothing on resume). `developer_instructions` aren't in the world state. `additional_developer_instructions`, a managed requirement, are (`core/src/context/world_state/managed_developer_instructions.rs`): kept by their hash, and where they changed, sent again whole, opening "These managed developer instructions replace all previously provided managed developer instructions."
- **Both runtimes keep the conversation's id on resume, and say it's a resume.** Claude Code's `SessionStart` `source` is `resume` for "`--resume`, `--continue`, or `/resume`" (*hooks*), so `lup-dev launch claude --resume` and `/resume` in a session are one case (#73's first unverified point), and it's `--fork-session` that makes "a new session ID instead of reusing the original" (*cli-reference*). Codex's is `resume` too, run at the thread's first turn after it (`core/src/hook_runtime.rs`), its id the rollout's (`core/src/session/session.rs`). Each also has `startup`, `clear`, `compact` and `fork`. A `SessionStart` answer reaches the model: Claude Code puts `additionalContext` in a system reminder "at the point where the hook fired", and `/resume` "waits for the hooks to finish"; Codex adds it "as extra developer context".

## The guidance at system level is the launch's own (decided)

- **Claude Code: `--system-prompt-snapshot off`** beside `--append-system-prompt-file` (`adapters/claude/terminal.py`), so every request, a resumed conversation's too, carries this launch's guidance, and this CLI's own prompt. A resume after the guidance changed writes the conversation's cache again once; across launches it has usually expired anyway, which Claude Code says at the resume (`prompt_cache_likely_expired`). Within a launch the prompt should render the same each time, so the cache holds: owed live.
- **Codex: the guidance as `additional_developer_instructions`,** in the requirements file the launch already mounts for its hooks (`/etc/codex/requirements.toml`, `adapters/codex/terminal.py`), in place of the `developer_instructions` override. Codex then replaces it itself, whole, at a resume where it changed. The costs:
  - the whole guidance again in the conversation at each such resume: about 19 KB for lup's own repository (17.4 KB of its four sections' files at `dev`'s tip, before lup's tools and the other repositories are listed);
  - Codex refuses to start past "a limit of 10,000 estimated tokens, including context markers" (*config-reference*), 4 bytes a token (`utils/string`, `approx_bytes_for_tokens`), so a launch refuses a render past it first, naming its size and the limit, rather than fall back to `developer_instructions` and the stale guidance with them. Codex counts the instructions as it would send them at a resume where they changed: the `<managed_developer_instructions>` markers and the notice opening them, 169 bytes, beside the render (`validate_managed_developer_instructions`), which the launch's count follows (`adapters/codex/terminal.py`, `managed`);
  - a workspace's own managed requirements outrank the system file (*config-reference*), so an account whose workspace sets managed instructions would drop lup's.
- `docs/launch.md`'s *Guidance* and its table of compiled settings change with these.

## What lup knows a conversation saw

- **The session's record, kept by the transcripts module (leaning).** Agreed with the operator on 2026-10-16, to confirm: the environment core requires a transcripts module, keeping each launched session's record whole (#65; `docs/modules.md`'s map still lists transcripts under feedback, to discuss). The guidance a session ran under belongs to that record, and with the snapshot off nothing else keeps it: Claude Code records no prompt. So the record holds, beside the copy of the transcript #65 adds, each launch the session ran in, in order, with the guidance that launch rendered. This piece builds that part first.
- **Where:** in lup's data, per repository, as #65 has it: `$XDG_DATA_HOME/lup/transcripts/<repository>/`, a file per session, keyed as the inbox keys a session's main conversation (the repository, the runtime and its id for the session: `inbox/store.py`, `Conversation`), so the two agree; each render kept once beside it, by its digest, its sections by name. A subagent runs within its session's launch, so it never moves on its own.
- **Written by the host service,** its only writer, as the inbox's is. The launch hands it the render with its registration (`Register.guidance`), since the launcher renders it. At a session's start in a launch other than the one its record ends with, the service compares the two renders section by section, tells the conversation what changed (below), and adds this launch to the record once the hook's answer is written, as an inbox item is counted told (`Post.returned`): a start whose answer didn't go out is told again at the next.
- **What a conversation last saw** is then the render of the last launch its record names: the runtime gives it each launch's guidance at system level, and lup tells it what changed at each move.
- **A start with nothing to compare** is told that its earlier turns may have run under other guidance, naming no section **(leaning)**: a fork (Claude Code's `--fork-session` or `/branch`, Codex's fork: a new id carrying another session's history, whose hook names no parent), a conversation from before this lands, or one from another repository's launches.

## What a resumed conversation is told

What's told stays in the conversation, through later resumes too: Claude Code saves a hook's text in the transcript and replays it (*hooks*, *Add context for Claude*), and Codex's rollout keeps it. So it may itself go stale at the next move. A hook tells 10,000 characters whole on Claude Code and 2,500 tokens on Codex by default; past that, the text goes to a file the model isn't asked to read (`docs/host-tools.md`, *Told once*). The options:
- **The whole new guidance again:** about 19 KB for lup's own, past both hooks' caps, so it would arrive as a file nobody reads; and where the runtime already carries it at system level, twice.
- **The sections that changed, each whole:** bounded by what changed, saying only what's true now; but a large section (`AGENTS.md`, 8 KB) fills most of a hook, and what's told goes stale at the next change, superseded only by the next notice.
- **A diff of the two renders:** the least text for a small change, but its removed lines put the stale facts (the old path) back into the conversation beside the new, in hunks cut from their sections.
- **The names of the sections that changed (leaning):** "Since this conversation last ran, in an earlier launch, these sections of lup's guidance changed: Other repositories, The room. The guidance you have now is this launch's." A line or two, still true after later moves, and plain fact, as Claude Code's docs ask of hook context ("Text framed as out-of-band system commands can trigger Claude's prompt-injection defenses"). It rests on the runtime carrying the whole current guidance (decisions 1 and 2); where either is declined, the changed sections go whole instead.

It's told at `session-started`, before what the inbox tells there, within what the hook's answer tells whole (`Heard.fits`). A section is named by its heading, its text's first line; one added or removed is said so.

## Both runtimes

Each has what this needs, so neither declares a gap: `SessionStart` saying it's a resume, with context the model reads; the conversation's id kept across it; and a way to give a resumed conversation the later launch's guidance at system level. What each limits: Codex, the managed instructions' 10,000 estimated tokens; both, a fork's hook naming no parent.

## In `Core`'s guidance, either way

A paragraph of `Core`'s section (`declaration/modules/guidance/core.md`), after *What isn't*:

> **As of this launch.** This guidance was rendered when this session's launch started, and a conversation continued from an earlier launch may remember another. Where either disagrees with the room itself (a path, a mount, a tool), the room holds: look before concluding something isn't there.

## Modules and public API (leaning)

- `launch/guidance.py`: `render` returns a `Rendered`, its sections in order, each named with its text, and the document as today (`Rendered.text`), so two renders compare section by section.
- `host/protocol.py`: `Register.guidance`, the launch's `Rendered`.
- `host/courier.py`: `Heard.started`, how a session started, in neutral terms (`new`, `resumed`, `cleared`, `compacted`, `forked`), each adapter reading its runtime's `source`.
- `transcripts/`, in `lup_dev` until the packaging step: each session's record and the renders it names (`Records`), and what a moved conversation is told, handed to the host service by `cli.py` beside the inbox's `Post`.
- The library's terminal compiles: Claude Code's `--system-prompt-snapshot off` wherever guidance is passed; Codex's guidance in its `Requirements`, held to its limit.

## Tests

No agent, no network, and time through `lup_dev.clock`:
- each adapter's `SessionStart` read with each `source`, on recorded payloads;
- the record: a session heard in one launch, then in another, recorded once per launch; an unchanged render telling nothing; a changed, an added and a removed section named; a start with nothing to compare, a fork among them, told so; a start whose answer didn't go out told again at the next; a render kept once by its digest;
- the renderer's sections by name, the document unchanged;
- each terminal compile compared whole: `--system-prompt-snapshot off` beside the guidance on Claude Code; Codex's guidance in its requirements file and no `developer_instructions`; a render past Codex's limit refused, naming its size;
- through the host service with a stub judge: the notice in a resumed session's `SessionStart` answer, before the inbox's items, within what the hook tells whole;
- `Core`'s paragraph in the rendered guidance.

## Checks owed

- **Claude Code:** with the snapshot off, a conversation resumed through `/resume` and through `--resume` into a launch whose guidance changed answers from the later guidance; the cache holding across one launch's requests with it off (the transcript's `usage`); where a resumed conversation's `SessionStart` context lands (after the restored history, as "at the point where the hook fired" reads).
- **Codex:** `additional_developer_instructions` from the mounted requirements file reaching a launched session, and its subagents once; at `codex resume` and `/resume`, a changed render replaced whole and an unchanged one not sent again, as the source reads; `source: "resume"` at the first turn after; the thread's id kept.
- **Both:** whether a fork's transcript names the session it came from, so a fork could compare against its parent's record.

## Decisions for the operator

Answered by the operator on 2026-10-16: 1, 2 and 6 taken as stated, and built first. 3 to 5 are designed with the transcripts module, since the record they need is that module's, and building it ahead of the module's design would be a stopgap.

1. **Claude Code launches with `--system-prompt-snapshot off` (decided):** every request carries the launch's own guidance, a resumed conversation's too. The alternative: keep the recorded prompt and tell the later guidance through the hook, the stale one staying at system level, the whole later one past the hook's cap.
2. **Codex's guidance moves to `additional_developer_instructions` (decided),** in the requirements file the launch mounts, which Codex replaces whole itself at a resume where it changed; a render past its limit refused at launch. The alternative: keep `developer_instructions`, which a resumed thread never sees again until it's compacted, and tell the changed sections whole through the hook, its `additionalContextLimit` raised.
3. **What's told at a resume: the names of the sections that changed (leaning),** given 1 and 2. The alternatives: each changed section whole (the lean wherever 1 or 2 is declined); the whole guidance; a diff; nothing beyond 1, 2 and 6.
4. **The record is the session's, kept by the transcripts module (leaning),** in lup's data per repository, the host service its only writer. The alternatives: a digest on the inbox's `Whereabouts`, which hold where a conversation is now, not where it's been, and move onto the ledger; a store of this piece's own, a third keyed the same way.
5. **A start with nothing to compare is told so (leaning),** naming no section: a fork, a conversation from before this lands, or from another repository's launches. The alternative: told nothing, leaving it to 6.
6. **`Core`'s guidance says it holds as of its launch, and the room is the truth (decided),** worded as above, whatever 1 to 5 come to.
