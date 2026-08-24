---
name: debug
description: "Trace an error through logs to find root cause"
---

# Debug: Trace an Error

**Do not hypothesize -- trace.** Find the actual logs, read the exact exception, and report what happened. Never list "likely causes" or suggest the user check things.

## Input

**Error text**: the arguments supplied with this skill invocation

## Process

### 1. Search logs for the error

If the input names a session or run ID, open that exact run first:

```bash
uv run lup-devtools trace show "<session-or-run-id>" --full
```

This view includes both reasoning traces and browser events. An empty browser
event log is evidence: compare its timestamps and files with the run record
rather than treating silence as absence of a run. Use `Glob` for
`**/<session-or-run-id>/run.json`; when an application-owned run record exists,
read it and every sibling artifact to establish how far the run got.

First, check if there are sessions with errors:

```bash
uv run lup-devtools feedback errors
uv run lup-devtools trace errors
```

Then search traces for the specific error text:

```bash
uv run lup-devtools trace search "<distinctive part of error>"
```

If devtools search doesn't find it, fall back to `grep` over `logs/` with the most specific substring from the error.

For a Lup command-hook error, first use `Glob` for
`**/plugins/data/**/hook-events.jsonl`. The Lup dispatcher writes one
metadata-only `started` record and one terminal record there for each hook it
executes. Correlate by `session_id`, `turn_id`, `tool_use_id`, and timestamp:

- `failed` carries the exact dispatcher exception in `detail`.
- `completed` with `deny` carries the policy reason in `detail`.
- `started` with no terminal record means the dispatcher was interrupted.
- no matching `started` record, while the native runtime reports the hook event,
  means failure occurred before the plugin command began. Inspect its hook
  status notification and the trusted/enabled plugin definition; do not infer
  a dispatcher cause from an execution that never reached it.

The journal deliberately omits `tool_input` and tool output. Read the session
trace for those only after the identifiers establish which call is relevant.

### 2. Find the right log file

If multiple log files match, identify the **most recent** one (logs are named by timestamp: `YYYYMMDD-HHMMSS.log` or `YYYYMMDD_HHMMSS.log`).

If no matches found:

- Try `notes/traces/<version>/sessions/` for meta-reflections mentioning the error
- Try broader search terms (exception class name, HTTP status code)
- If still nothing: report exactly what was searched and that no logs contain this error. State what logging would need to be added and where.

### 3. Read the full context

Once you find the log file containing the error:

1. **Read the traceback** -- Find the full exception chain. Read 50-100 lines around the error to see the complete traceback and what led to it.
2. **Trace backwards** -- What was the agent doing when the error occurred? Read earlier in the log to find the tool call or action that triggered it.
3. **Check the source** -- Use `Read` and `find_definition` to reach the exact line in the source code (`src/`) where the exception was raised or where the failing logic lives.

### 4. Report findings

Structure your report as:

**What happened:**

- The exact exception/error (quote the traceback)
- Which file and line in the source code

**Why it happened:**

- What the agent was doing at the time (from the log context)
- The chain of events that led to the error

**How to fix it:**

- Specific code changes needed (show the code, point to the file and line)

**If logs are insufficient:**

- State exactly what logging to add and where, so the error is captured next time
- Be specific: "Add `logger.exception(...)` at `src/lup_template/agent/core.py:42` inside the `except` block"

## Rules

- **Never guess.** If you can't find the error in the logs, say so. Don't speculate about what might have caused it.
- **Quote exactly.** Show the actual traceback and log lines, not paraphrased summaries.
- **Read the source.** After finding the error location, read the actual source code to understand the failure.
- **Be specific about fixes.** Point to exact files and lines, show before/after code.
