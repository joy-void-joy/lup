### Diagnosing Failures

When the agent fails, trace the failure through the pipeline before changing anything:

1. **What data did the agent have?** Read the trace. What tools did it call? What did they return?
2. **Where in the workflow did the wrong decision enter?** Find the entry point, not the symptom.
3. **What structural change prevents it?** A new tool, a better tool description, a restructured step, richer data.

A prompt rule is a patch that coexists with the failure. A structural change makes the failure impossible.

### Three Levels of Analysis

1. **Object Level** -- The agent itself: tools, capabilities, behavior
2. **Meta Level** -- The agent's self-tracking: what it monitors about itself
3. **Meta-Meta Level** -- The feedback loop process: scripts, analysis methods

### Running the Feedback Loop

1. **Collect feedback**: `uv run lup-devtools feedback collect`
2. **Read traces deeply**: Don't skip to aggregates. Read 5-10 sessions in detail.
3. **Extract patterns**: Tool failures, capability requests, reasoning quality
4. **Implement changes**: Fix tools -> Build requested capabilities -> Simplify prompts
5. **Update documentation**: This file should evolve with the agent

### What to Track Per Session

- **Sessions**: Results saved to `notes/traces/<version>/sessions/<session_id>/`
- **Outputs**: Task outputs saved to `notes/traces/<version>/outputs/<task_id>/`
- **Traces**: Reasoning logs saved to `notes/traces/<version>/logs/<session_id>/`
- **Metrics**: Tool calls, timing, errors via metrics tracking

---

# Configuration

### Environment Variables

The `.env` file contains the template configuration. Create `.env.local` for your secrets (gitignored):

```bash
# .env.local - your secrets (ANTHROPIC_API_KEY is read directly by the SDK from env)

# Optional overrides
# AGENT_MODEL=claude-opus-5
# AGENT_MAX_BUDGET_USD=5.00
# AGENT_MAX_TURNS=50
# AGENT_SANDBOX_ENABLED=false   # run without Docker (disables code execution tools)
# AGENT_NOTES_PATH=./notes      # relocate session data
# AGENT_LOGS_PATH=./logs        # relocate trace logs
```

Settings in `.env.local` override `.env`.

### Settings

Configuration is loaded via pydantic-settings. See `src/<project>/agent/config.py` for all options.

---

<!-- section: Anti-Patterns to Avoid -->
# Anti-Patterns to Avoid

- Adding numeric patches ("subtract 10% from estimates") or absolute thresholds ("if X happens N times, do Y")
- Prompting the agent with rigid mechanical procedures instead of guidelines and rationale
- Copying examples from a specific trace into the prompt instead of deriving general principles and writing fresh examples
- Adding rules the agent can't act on (no access to required data)
- Patching for one observed symptom instead of tracing the failure through the pipeline to find the structural cause
- Adding "CRITICAL: Never do X" warnings instead of restructuring the workflow so X has no entry point
- Listing tools by name in the system prompt (creates two sources of truth that drift apart)
- Writing terse tool descriptions (the agent can't use a tool well if it doesn't know when or why)
- Skipping trace analysis to jump to aggregate statistics
- Over-engineering initial implementations

### Questions to Ask

When proposing changes:

1. Does this add a capability or just a rule?
2. Would this help if the domain changed completely?
3. Are we changing the right level (object/meta/meta-meta)?
4. What general principle would have prevented this failure?
5. What data would we need to validate this change worked?
