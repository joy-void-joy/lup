# The graveyard: what was tried and left behind, and why

Each entry is something the first lup did, or this one proposed, that the design leaves behind, with the reason, so it isn't proposed again without new evidence. The design itself is `DESIGN.md`.

## From the first lup

- **The copied half** (`src/` and `tests/` stamped out at init, updated by merge): every update was a large merge, and projects spent their sessions on it.
- **Committed runtime trees** (`.claude/`, `.codex/`, about 88k lines each): conflict markers in a compiled hook dispatcher refused every command; the launcher rebuilt them anyway.
- **Projects declining modules by subtracting from a full copy:** leaky; declined modules' commands were still served, and skills failed before their first step.
- **Pins to branches:** deleted branches broke installs.
- **A linear pre-release per project:** projects changing lup at once drift apart.
- **The shell-spelling analyzer** (about 17k lines) and per-command verdicts: it grew a case per spelling and couldn't see what a script writes.
- **The "inner" posture** (the runtime's own sandbox as lup's wall): replaced by "container, or no lup policy".
- **The `execute_code` sandbox module:** the agent runs inside the wall with Bash.
- **The single-agent template app** (tool policy, system prompt, subagents, reflect gate): every adopter deleted it.
- **Native subagents as workers, and native messaging between sessions:** subagents share their parent's identity, can't reach it, and can't be stopped after a resume; native messages don't cross containers.
- **Routing lup through each runtime's own orchestration features:** "mostly a nightmare".
- **"Equal on both runtimes" with nothing that runs regularly:** Codex rotted between uses.
- **Turtle mode:** a one-key slowdown, replaced by budget shares and pace.
- **A proxy replaying requests to keep caches warm:** Anthropic's terms forbid intermediating subscription tokens.
- **Explicit roster describe calls and path locks:** 251 describe calls in nine days; replaced by a roster that fills itself and conflict detection at merge.
- **Informational-only code rules:** they'd be bypassed.
- **The feedback loop's five-skill chain built on the template's agent:** it had no place for outcomes, and the loop never closed.
- **Guidance grown by patches:** 18 KB of bare imperatives, overriding the runtime's own advice and contradicting skills.
- **Undo snapshots taken for read-only commands:** writes into a repository the agent was only reading.
- **A prompt for every decision** (manual review before lup): it wore review down into approving everything, while files that looked fine carried design directions and regexes through. Approving whole new files, and code rules pointing at the risky decisions, are what made review work.
- **Refusals that report one violation at a time:** the art studio's agent resent a 550-line file four times, once per rule.
- **Guidance teaching agents to split a change under the edit-size limit:** it dodged the review the limit exists for, and turned one change into many tiny edits.
- **A bare client with web tools by default** (`builtin="web"`): live-translator had to get "no tools" built upstream and assert it in its own test.

## Proposed in this lup, and declined

- **Code rules enforced only at landing:** by then an approach a rule exists to stop has had code built around it.
- **A keepalive loop for held agents** (re-entering a wait about every 50 minutes to keep the cache warm): the operator won't put an agent in an automatic wait loop. A hold past the hour pays a rebuild instead.
- **Contribution branches in lup's repository:** a project fixes locally and declares a candidate instead, so it never touches lup's repository or points at a branch.
- **Running a half-built judge on its own construction** (the bridge, October 2026): each of its bugs blocked the work it guarded. 12 of the 18 open issues were the judge's; workers built in scratch clones and retyped 1,400-line files to land them. A piece of the environment goes live in lup's own sessions once it's finished.
- **Parking reviews: refuse, wait, repeat the exact call** (the bridge's interim review): agents routed around long waits, and repeats went stale or failed ("File has not been read yet").
- **The drafts flow** (a write needing review landing in a draft under `.lup/drafts/`, submitted to the first lup's dashboard and carried out once approved): the write was invisible but not its use; a test importing a drafted module failed to import, so each new file was a wait.
- **Asking on a new file's first write:** it showed the operator a half-written file. The agent proposes a coherent design instead.
- **Approval at landing** (judging branches, not writes): the agent built a whole architecture on an early choice, and when told late, changed only the flagged thing.
- **A cap on unproposed code:** it would ping the agent; the dashboard shows unproposed work instead.
- **An MCP edit tool with a mode on every edit:** it would rebuild the runtimes' edit tools, and make the agent decide intent at every edit; intent belongs to a set of files, which `propose` carries.
- **Modules that never depend on each other:** everything two modules share went into the core. Dependencies are declared instead, and the loader refuses a broken drop.
- **Dashboard views as data only:** the first lup's hardcoded views pushed projects to build their own pages (adlib's preview server). Modules ship panels as code.
- **A style rule refusing at every edit** (`elif`, collection loops, private names): it made agents rewrite correct code into a house style; such rules are checked at the gate.
