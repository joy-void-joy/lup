
## First Principles Design

When considering changes, ask:

1. **Bitter Lesson Check**: Does this add a capability, or just a rule?
   - Prefer tools and capabilities over prompt constraints
   - Avoid pattern-matching patches

2. **Pipeline Diagnosis**: If fixing a failure, did you trace it?
   - What data did the agent have? What was missing?
   - Where in the workflow did the wrong decision enter?
   - Is the fix structural (new tool, better data, restructured step) or just a prompt patch?

3. **Generality Check**: Would this help if the domain changed?
   - General principles > specific patches
   - If it only works for one scenario, it's probably over-fitted

4. **Meta Level Check**: Are we changing the right layer?
   - Object level = the agent's behavior
   - Meta level = how the agent tracks itself
   - Meta-meta level = the feedback loop infrastructure

## Command Evolution

**After every command invocation**, reflect on how it was actually used:

1. **Compare intent vs usage**: Did the user use the command as documented, or did they adapt it?
2. **Notice patterns**: If the user provides documentation, links, or redirects the command's focus, that's a signal the command should evolve.
3. **Proactively propose updates**: When you notice the command being used differently than documented:
   - Propose updating the skill, as a question the user answers
   - Include the specific usage pattern you observed
   - Suggest concrete changes to its declaration

## Process

1. Read relevant files based on the user's direction
2. Analyze and identify potential improvements
3. Propose specific changes with rationale, and let the user choose among them
4. Implement approved changes immediately
5. **Reflect on this skill's execution** and propose updates to its own declaration if warranted
6. Continue brainstorming or summarize changes made
