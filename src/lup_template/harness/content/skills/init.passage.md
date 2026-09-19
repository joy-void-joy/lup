# Initialize Self-Improvement Loop

This command sets up the project identity, renames the source package, and customizes the feedback collection, metrics, and trace analysis for your specific agent domain.

**This project builds on an agent SDK, not raw model API calls.** The SDK is the default and expected framework. If the user wants bare API calls instead, ask them to explain why -- the SDK provides structured outputs, tool use, subagents, and hooks out of the box.

## Your Task

Interview the user about their domain, rename the source package, and generate the appropriate scaffolding.

### The branch you start from is the library you get

This checkout is a clone of lup, so the branch it stands on *is* the library
version the project begins at: `packages/lup/` is that branch's code, and the
acquisition mode settled in Phase 2 pins that same ref. A feature branch
carries work the stable branch has not reviewed, and nothing downstream
announces that. Resolve both before Phase 0, while `origin` still points at lup
rather than at the project's own repository:

