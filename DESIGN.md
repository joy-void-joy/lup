# lup

lup is the environment agents and the operator work in together: the workflows, skills, defaults and patterns that make a session on Claude Code or Codex better than a plain one, for the agent working in it and for the operator working with it, as modules every project can use. It began as a way to build agent loops for aib, and grew into the environment projects are developed and run in.

This document describes lup as it's meant to be. Parts of it aren't built yet; `docs/` describes what is. It isn't a record of decisions: where your work reaches a choice, ask the operator.

## Who it's for

- **The operator stays in the loop.** They talk things through with whoever builds the thing, see the shape of what agents build while it forms, and are shown risky patterns (a regex, string parsing, `Any`) where they appear, so they can comment and redirect early. Reviewing often is welcome.
- **Agents work comfortably.** lup doesn't repeat itself, reports instead of denying where it can, and lets an agent choose when they're paused or interrupted. Anything that makes the work more comfortable for an agent is allowed, as long as the operator can still pace the work and check on it. Its guidance is written by agents for agents, each line with its reason, so an agent can tell when one doesn't fit and say so.
- **The operator can let agents run without watching.** The containers and the limits on the operator's credentials are the walls, and they're for inattention, a one-turn injection and a malicious package, including one that runs an agent of its own: what such a thing could do with a room's ordinary powers and common knowledge of git and the network. They aren't for an agent set on escaping, which no sandbox would stop, nor to make poor code impossible: code rules, the review and the gate steer the work and guard accidents, and a way around one that needs a plan against lup's own checks is out of scope. What a room can do is accepted so that the work stays natural: read and write the repository and its git store, so a session can look at another worktree; push and act on GitHub within the declaration's limits; use a login and history of the rooms' own, shared among them and apart from the operator's, so logging in and resuming work as they do outside a room; and reach anything listening on the operator's machine, so a dev server is shared between them. What changes the walls themselves (the declaration, and the code holding a secret or the operator's approvals) goes through the operator, so they see it.
- **Projects grow lup.** A session in any project can spawn an agent on lup's repository for what lup lacks, so lup is built from what its projects need, and a project is worked on with lup from its first day.

## Modules

Everything lup does comes from a module, and a project declares which modules its sessions use. lup's own parts are modules declared the same way a project's are, so a project can change or replace any of them.

- **The core is a module** packaging the submodules every project has: loading the declaration; starting rooms, sessions and services; the broker of the operator's credentials and secrets; the runtimes' adapter; the inbox's machinery; and the dashboard's shell. A project changes or replaces them as it would any module, but can't drop them. The one thing that isn't a module is the program that loads them (*Where code runs*).
- **A module is a directory and a package,** with up to three sides: its library, what code calling agents imports, which never imports the other two; its environment, what a project's sessions get; and its page, what it shows the operator. A project's own modules take the same shape in its repository, so one that turns out to be general moves into lup as a directory.

A module can declare:
- the tools, skills and subagents its sessions get;
- the room its sessions run in: packages, GPU, caches, network, privileges;
- services: a program running during a launch or always, such as a preview server, a bot, or one holding an API key that agents use without seeing it, with the secrets it gets from the machine's secret store and the port it listens on;
- guidance, code rules, gate steps, path roles and requirements;
- promises: what someone can count on, each checked through lup's doors;
- what it shows the operator: views, embeds, kinds of item, and parts of the shell, keymaps among them.

A module refers to its code by importing it, so pyright checks the reference and renames follow it. The declaration is loaded at every hook, so the gate checks that loading it imports nothing heavy, and names the import chain when it does.

**Rooms.** A project declares named rooms, each a selection of modules on top of the project's own. A maintaining room, for working on the project's code, has the code rules and reviews. A playground room, where an agent makes things freely (art, or podcasts), leaves them out: the container is its only wall.

**The measure:** a project is its own logic and its views, and what every project would otherwise rebuild is lup's. A story reader built outside lup, which reads a story aloud and edits it with Claude in a page beside the session, is its corpus, its reading of the story and one view: the room, the session's wiring to the page, the panes, comments on passages and voice are modules it selects.

## Where code runs

- **The program the operator installs is a loader.** It starts the machine's own parts (`Hosting`, which the home repository's declaration selects) on the machine itself, from the commit of the home repository the operator approved, falling back to the last one that came up where a new one doesn't. Those parts hold what no container gets: podman, since whatever starts containers can do anything the operator can; the machine's secret store; the operator's approvals; and the sockets every call crosses. They're the only module code that runs outside a container.
- **Everything else runs in a container:** agents in rooms, and each project's parts, the core's included, so the dashboard is a service like any other. A part holding nothing runs in its project's container. A part holding a secret, or anything only approved code may, runs in a container of its own with what it holds alone. A container is the wall against a program's dependencies, a malicious package among them. A part that needs the machine itself (its desktop, a device) says so, and runs there.
- **Nothing runs that the operator hasn't approved.** Each project runs the commit they approved last. It's written out from git's objects, each checked against its id, since rooms write the store. Approving is reviewing a landing, whose yes approves the commit it lands, or answering the question lup asks when a project's running branch moved without their review: a pull, their own push, a first run. So an agent writes freely, and the operator sees a change before it runs. A project can opt out for its parts holding nothing, which then follow its running branch; its parts holding something still run the approved commit.
- **Who calls is the socket's word.** Each container gets sockets of its own, and the machine says who a call is by from the socket it came in on, never from what the call says. So a container can't speak as the operator, as the machine, or as another project.

## Sessions

- **lup starts every session itself,** on Claude Code or Codex, each in a room and worktree of its own. The operator talks with it in its buffer in the dashboard, and a terminal can attach.
- **Work is handed on with its conversation.** A session forks the agents it hands work to, so they know what was discussed, ask the operator what they're still unsure of, and build. A brief is for a side job, a search or a measurement, whose report comes back to whoever asked.
- **Spawning reaches the other repositories the declaration names:** a session in a project spawns an agent on lup's repository for what lup lacks.
- **A long session hands its place to a fresh one,** its state going with it, and a reply to an agent who has ended starts them again.
- **A limit on how many run,** against runaway loops.
- **Both runtimes.** Every shared construct works on Claude Code and on Codex, built for both at once and tested on both with real logins, and nothing above the runtimes' adapter names one. Codex rotted in the first lup because features were built per runtime above the adapter.

## Concerns and piles

A concern is something to keep an eye on: a feature to build, a problem met, a direction to think about. The operator writes one in a line wherever they are, and so does an agent the moment something's worth keeping an eye on, even if nobody will work on it. It has a title, a description its holder rewrites as it changes, the words it came from (the operator's or an agent's, each linked to its moment), and the concerns under it. Concerns outlive agents.

**A pile is a party that holds concerns and does nothing else.** It shows in the dashboard as an agent does, named as one (`@containment`, `@containment/ssh`), and is sent to and mentioned as one, so the operator can make a pile, write into it as they think, and come back to it later: what's sent to a pile becomes a concern in it at once. Every concern is held by an agent or a pile, and piles go under agents or other piles, so the dashboard's list is the parties and what each holds. Each repository has `No agent`, where an agent's open concerns go when they end, and `frictions`.

- **An agent starts by saying what they're taking up:** the concerns they're working on, made or moved under them, and the same when they hand work to an agent they spawn. Concerns aren't a task list: leaving some open is fine, and what's open stays visible.
- **A friction is the agent's feedback:** what got in their way and annoyed them, in their own words, the moment it does. It becomes a concern where the agent sends it: a pile by its path, made if it isn't there yet (`frictions/dashboard/keys`), or an agent, and `frictions` where they name none. A session the operator starts turns what gathers there into the concerns it's about.
- **An agent holding a concern says when they think it's done,** with what's done, what isn't and what to try, and the operator clears it when they agree. What the agent couldn't finish stays in the concern, saying why.
- **lup never reminds an agent of a concern,** or filing becomes a chore and agents file less.

## Keeping the operator in the loop

**Code rules** catch patterns that are rarely the right choice.
- Design rules (regex, splitting strings, tuples as records, `Any`, a second library for a job) are reported to the agent right after a write, like a type error. The agent fixes the code, or keeps it with `# lup: ignore("<rule>", why="<reason>")`, which goes to the operator.
- Spelling rules (`elif` chains, loops that fill a list) aren't reported while the agent works. The gate fixes them where a fixer exists, and reports the rest once before landing.
- Fixes are applied at the gate, never to a file the agent has just written.

**`# lup:` comments** are how code speaks to its next reader: `ignore` keeps one finding, `defer` marks work knowingly left undone with what brings it back, and anything else is a note, the operator's included.

**Looking in.** The operator reviews what an agent changes while they work: each edit beside the agent's words that led to it, each file with what it's for, as its module says. A comment reaches the agent at their next call.

**Holding.** The operator can hold an agent's writes, every one or those the project flags by path or by rule, to see each before it stands, and answer it with a comment.

**Pausing.** The operator can pause any agent, and that wins over the agent's own preferences.

**Quiet.** An agent can ask not to be interrupted: no findings or messages after their calls. The operator's messages wait too, unless they mark one urgent. When the quiet ends, the agent gets one summary of what waited. It lasts until the agent lifts it or their work has completely ended, not when a turn stops.

**Said once.** A finding or a message is told once, never repeated.

**Landing.** The agent who wrote a branch lands it, never the session that handed them the work, so what waits on the operator at landing, and every comment on it, reaches whoever wrote it. It waits only for what asks for their eyes: what the project flags, an added `ignore`, a change to what's approved.

## The dashboard

The dashboard is where the operator works: every agent and concern across their projects, and what each project's modules show. Every view also has a command, for the operator and for agents. It runs from one home repository, lup's own unless the operator picks another, whose declaration configures what serves every project: the shell, the keymap, the store. A project's own settings for those take effect when it's the home, and another shell is tried by starting a dashboard from its branch beside the operator's.

- **The shell knows no module.** Modules lay out documents of lup's blocks, and the shell does everything else: folding, selecting, commenting, sending, clearing, marks. Where something can't be said in blocks, the blocks grow, for every module. An embed carries what blocks can't draw (a video, a site, a module's own viewer), sandboxed so that all it tells the shell is what the operator points at, and a comment there works as anywhere.
- **Keymaps are modules.** The shell has named commands, and a keymap turns the operator's input into them: vim's, with its modes, operators and motions, and a plain one, where typing on a line comments on it, selecting a passage replies to it, and every command is also a button, which is also the phone's. The operator's own settings pick one.
- **Comments sit where the buffer puts them:** under what they're on, or in a pane beside it that follows the cursor, a choice of the buffer's rather than of the module showing it.

Everything in it is read and commented on as the review is: the operator points at any part, says something, and it goes with the one draft to the agent concerned. A module's data is typed Python an agent reads too. A project making an animation is commented on frame by frame; a site being built is used as its end product, with an overlay to point at its parts.

What the operator can count on, wherever they are in it:
- **Sending always works.** Each part of a reply goes, or stays visibly where it is with the reason, and one part never stops the rest.
- **Clearing what they're on clears it.** It comes back only if something new happens in it.
- **Every comment reaches a party:** an agent, now or as they're started again, or a pile, which keeps it. The line under the review says which before it's sent.
- **A command does the same thing wherever it's offered,** and is offered only where it does that.
- **Each part shown has its fold,** and everything folds, opens and selects the same way.
- **What's been cleared stays cleared,** across reloads, restarts and pages.
- **Only what needs the operator counts as waiting.** Everything else is news that leaves once seen.

The core decides and the page only draws, keeping no rule of its own beside the core's, and each of these is tested over a copy of real data rather than hand-picked cases.

## Defaults

Every agent runs in a container. Commands run there without asking, because the container keeps them from harming the operator's machine, and it's the same standard machine whatever the host. The operator's credentials stay out of rooms, used on the agent's behalf within limits the project sets.

**The operator's own settings** (their keymap, accounts and profiles, and session defaults) are the home repository's gitignored layer, and `~/.config/lup/` can override them. What's theirs for one repository alone (the other repositories they relate to it, their private values) is a gitignored layer in that repository.

## Calling agents from code

A project's code asks an agent a question and gets a typed answer, with tools it serves. Agent loops are built on this (aib's forecasts), and so are the patterns the operator reuses across projects: budgets, and realtime agents with Jev.

## How work goes

- Decisions are made live: the agent explains the problem and their options, numbered, each with their lean, and the operator answers. They aren't written down as the operator's, since a recorded decision gives the next session a wrong view of it.
- **Agents can run what they build,** end to end, from their room: lup started from their branch with secrets of its own, both runtimes with real logins. Building against stubs is how work ends half done.
- **A test checks a promise** someone relies on, through the module's doors, and leaves what nobody promised (a message's words, an internal type, a whole list) free to change.
- Documentation describes what exists, briefly, once it's built. It carries no history: what was tried, when, and who decided stays out of it.
- lup is built with lup: its own sessions run under what it builds, and its projects' sessions grow it.
