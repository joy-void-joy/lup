---
allowed-tools: Bash(uv run lup-devtools:*), Read, Grep, Glob, AskUserQuestion
description: Aggregate tool health, capability gaps, and reasoning patterns across sessions
---

# Analyze: Tool Health & Capability Gaps

Aggregate findings across sessions to identify systemic patterns.

## Process

### 1. Tool health

```bash
uv run lup-devtools metrics tools
uv run lup-devtools metrics errors
```

Identify: which tools fail most? Are failures transient or systematic? What's the error rate by tool?

### 2. Capability gaps

From investigation findings and trace analysis:
- What does the agent say it needs? Trust capability requests — the agent knows what it lacks.
- Quote the agent's exact words so you can act on them.

```bash
uv run lup-devtools trace capabilities
```

### 3. Reasoning patterns

From investigation findings:
- Are there systematic reasoning errors, or just individual misjudgments?
- Does the agent consistently struggle with certain task types?
- Are expensive tools providing proportional value?

### 4. Version comparison (if relevant)

If comparing across versions, launch the version-explorer subagent for code-level diffs:

```
Agent(subagent_type="lup:version-explorer", prompt="Compare vX.Y.Z and vA.B.C")
```

### 5. Summarize

From tool-health and capability-gap data:
- Which tools consistently fail? What's the root cause?
- What does the agent need but doesn't have?
- Are there reasoning quality patterns across sessions?
