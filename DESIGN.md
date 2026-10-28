# lup

lup is the environment agents and the operator work in together: the workflows, skills, defaults and patterns that make a session on Claude Code or Codex better than a plain one, for the agent working in it and for the operator working with it, in one codebase every project can use. It began as a way to build agent loops for aib, and grew into the environment projects are developed and run in.

This document describes lup as it's meant to be. Parts of it aren't built yet; `docs/` describes what is. It isn't a record of decisions: where your work reaches a choice, ask the operator.

## Who it's for

- **The operator stays in the loop.** They see the shape of what agents build while it forms, they're shown risky patterns (a regex, string parsing, `Any`) where they appear, and they can comment and redirect early. Reviewing often is welcome.
- **Agents work comfortably.** lup doesn't repeat itself, reports instead of denying where it can, and lets an agent choose when it's paused or interrupted. Anything that makes the work more comfortable for an agent is allowed, as long as the operator can still pace the work and check on it. Its guidance is written by agents for agents, each line with its reason, so an agent can tell when one doesn't fit and say so.
- **The operator can let agents run without watching.** The container and the limits on the operator's credentials are the walls, and they're for inattention, a one-turn injection and a malicious package, including one that runs an agent of its own: what such a thing could do with a room's ordinary powers and common knowledge of git and the network. They aren't for an agent set on escaping, which no sandbox would stop, nor to make poor code impossible: code rules, the judge, holds, flags, the private check and the gate steer the work and guard accidents, and a way around one that needs a plan against lup's own checks is out of scope. What a room can do is accepted so that the work stays natural: read and write the repository and its git store, so a session can look at another worktree; push and act on GitHub within the declaration's limits; use a login and history of the rooms' own, shared among them and apart from the operator's, so logging in and resuming work as they do outside a room; and reach anything listening on the operator's machine, so a dev server is shared between them. What changes the walls themselves (the declaration, protected paths, the code the host runs) goes through the operator, so they see it.

## Modules

Everything lup does comes from a module, and a project declares which modules its sessions use. lup's own parts are modules declared the same way a project's are, so a project can replace any of them. What's one per machine, shared by every repository, is the core instead: loading the declaration, the host service, launch and trust, the inbox's machinery and the dashboard's shell.

A module can declare:
- the tools, skills and subagents its sessions get;
- the room its sessions run in: packages, GPU, caches, network, privileges;
- helpers that run on the operator's machine, during a launch or always, such as a preview server or a service holding an API key, with the secrets they get from the machine's secret store and the port they listen on;
- guidance, code rules, gate steps, path roles and requirements;
- what it shows in the dashboard: kinds of item, a banner of its own, drawers, tabs and embeds.

A module refers to its code by importing it, so pyright checks the reference and renames follow it. The declaration is loaded at every hook, so the gate checks that loading it imports nothing heavy, and names the import chain when it does.

**Rooms.** A project declares named rooms, each a selection of modules on top of the project's own. A maintaining room, for working on the project's code, has the code rules and reviews. A playground room, where an agent makes things freely (art, or podcasts), leaves them out: the container is its only wall.

lup must be able to express every project that used the first lup, and everything the first lup did.

## Keeping the operator in the loop

**Code rules** catch patterns that are rarely the right choice.
- Design rules (regex, splitting strings, tuples as records, `Any`, a second library for a job) are reported to the agent right after a write, like a type error. The agent fixes the code, or keeps it with `# lup: ignore("<rule>", why="<reason>")`, which goes to the operator.
- Spelling rules (`elif` chains, loops that fill a list) aren't reported while the agent works. The gate fixes them where a fixer exists, and reports the rest once before landing.
- Fixes are applied at the gate, never to a file the agent has just written.

**Batches.** An agent gathers what the operator should see into a batch and proposes it when it's ready: one multi-file diff with the agent's explanation, each file headed by why it needs review, syntax highlighted, flagged lines marked. A batch holds new modules, files written whole, public API changes, added ignores and changes to protected paths. Nothing goes into one because of time or size alone.

**Pausing.** Proposing a batch pauses the agent until the operator answers, unless the agent chooses to carry on. The operator can pause any agent, and that wins over the agent's own preferences.

**Looking in.** The operator can open everything an agent has changed since they last looked, comment on it, or pause the agent. A comment reaches the agent at its next tool call.

**Quiet.** An agent can ask not to be interrupted: no findings or messages after its calls. The operator's messages wait too, unless they mark one urgent. When the quiet ends, the agent gets one summary of what waited. It lasts until the agent lifts it or its work has completely ended, not when a turn stops.

**Said once.** A finding or a message is told once, never repeated.

## The dashboard

The dashboard is where the operator works: every agent, its batches, questions and messages, and what each project's modules show. Every view also has a CLI command, for the operator and for agents.

Everything in it is read and commented on as the review is: the operator points at any part, says something, and it goes with the one draft to the agent concerned. A module's data is typed Python an agent reads too; it's drawn from lup's building blocks or TypeScript the module ships, each piece saying what in it can be pointed at: a line, a moment of a video, a region of a frame, an element of a page. A project making an animation is commented on frame by frame; a site being built is used as its end product, with an overlay to point at its parts.

## Defaults

Every agent runs in a container. Commands run there without asking, because the container keeps them from harming the operator's machine, and it's the same standard machine whatever the host. The operator's credentials stay on the host, used on the agent's behalf within limits the project sets.

## Calling agents from code

A project's code asks an agent a question and gets a typed answer, with tools it serves. Agent loops are built on this (aib's forecasts), and so are the patterns the operator reuses across projects: budgets, and realtime agents with Jev.

## How work goes

- Decisions are made live: the agent explains the problem and its options, numbered, each with its lean, and the operator answers. They aren't written down as the operator's, since a recorded decision gives the next session a wrong view of it.
- Documentation describes what exists, briefly, once it's built. It carries no history: what was tried, when, and who decided stays out of it.
- lup is built with lup: its own sessions run under what it builds.
