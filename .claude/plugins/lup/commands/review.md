---
allowed-tools: Read, Grep, Glob, Agent, Bash(ls:*, wc:*, sort:*, tail:*, stat:*, uv run lup-devtools:*)
description: Something feels off — review a trace, diagnose collaboratively, then fix
argument-hint: <console log, session ID, file path, or what feels off>
---

# Review

The user is sharing a trace and describing something that went wrong. This could be tone, timing, workflow friction, a subtle bug, a broken flow — anything where the experience doesn't match expectations.

## Input

**Trace input**: $ARGUMENTS

### Resolve the trace

**Session ID** (e.g., `repl_20260228_123036`, `20260228_123036`):
- Look in `notes/traces/` for matching session directories
- Read the `.md` trace log from `notes/traces/<version>/logs/<session_id>/`
- Also read the `SessionResult` JSON from `notes/traces/<version>/sessions/<session_id>/` for metadata

**File path** (contains `/` or ends in `.md`/`.json`):
- Read the file directly

**Raw pasted trace** (anything else):
- Work with what's pasted

If you can't find the trace, use `uv run lup-devtools trace list` to show available sessions.

## Process

### 1. Feel it first

Read the trace through the lens of the user's description. Don't jump to mechanics — sit with what they're describing and see if you feel it too.

### 2. Reconstruct the experience

Separate what the user experienced (inputs + visible outputs) from the agent's inner world (thinking, tool calls, intermediate results). The gap between expectation and reality is where things go wrong.

Walk through chronologically:
- Did the agent correctly interpret the task?
- Where did the conversation move toward the goal vs. meander?
- At each major decision point, was the choice reasonable?

### 3. Name what you see

Present your reading concisely, pointing at specific moments in the trace. **This is the start of a conversation — not a final diagnosis, not a fix proposal.** Name the pattern you see, then stop and let the user react.

Include:
- Tool calls that were wasteful, misused, or missing
- Workflow friction points
- Reasoning quality issues (jumped to conclusions, ignored evidence, unnecessary loops)

### 4. Brainstorm

**Do not jump to fixes.** Talk it through with the user first. Share hypotheses, ask what resonates, dig into source code together as questions arise.

Read source code as the conversation calls for it — don't front-load research. Start from what the trace tells you. Key source files when needed:
- `src/lup/agent/prompts.py` — System prompt
- `src/lup/agent/core.py` — Agent orchestration
- `src/lup/agent/tools/` — Tool implementations
- `src/lup/agent/tool_policy.py` — Tool availability
- `src/lup/agent/subagents.py` — Subagent definitions

### 5. Converge

Only after agreement on what's wrong, propose specific changes. Each improvement should reference:
- What evidence from the trace motivates it
- Which file to modify
- What the change would be

Categorize as: **Tool changes** (preferred) > **Prompt changes** > **Workflow changes** > **Observability**

Wait for the user to greenlight before editing.

## Rules

- **Don't front-load massive research.** Start from the trace, dig into source as needed.
- **Don't jump to code fixes before the user confirms the diagnosis.**
- **Quote the trace.** When citing evidence, quote the actual trace text — don't paraphrase.
- **Focus on the general.** Per the Bitter Lesson: prefer improvements that add capabilities over rules.
- **Diagnose before prescribing.** What data was missing, and where did the wrong decision enter?
- **Be honest about quality.** If the session went well, say so. Not every review needs problems.
- If you don't see it, name it. Don't hedge.
