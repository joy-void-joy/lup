# The dashboard

Where the operator works with lup: every agent the host serves, across every repository, in one page. `lup-dev dashboard` opens it.

Its package is `packages/lup-dashboard/` (`lup_dashboard`), which imports `lup-dev` and is never imported by it.

## Running

- **The host service runs it as its child** (`lup_dev/host/dashboard.py`, `DashboardProcess`), a `Companion` begun once the service listens and ended as it stops. The service runs `lup-dashboard serve <port>`, found beside the interpreter running the service: lup's own approval installs the dashboard there, in the person's own copy beside `lup-dev` (`uv tool install --with`, held to the lock like the rest; the repositories' judge copies leave it out), its page built by trust as the gate builds it. Where it isn't installed, there's no dashboard, and `lup-dev dashboard` says why.
- **Its input:** the service writes the API's token as its first line and keeps the input open; the dashboard ends when it closes, so it goes with the service however the service ends.
- **Its output:** its first line is the address it listens on, which the service reads; a dashboard that ends before printing it (a port another program holds) is said, and the service goes on without it.
- **On localhost, on one port** (`LUP_DASHBOARD_PORT`, 8766 by default), the same at each start, and **one token**, kept in the host's state (`HostLayout.dashboard_token`, mode 600), which no room mounts. So a page left open reconnects on its own once the service starts again, after an approval among others.
- **`lup-dev dashboard`** asks the service for the address (`ShowDashboard`), the token in its fragment, starting the dashboard again where it's gone; it prints it and opens it in the browser (`--no-open` only prints). It refuses inside an agent's session.

## The API

The page asks the host service only what the operator's commands ask it: the host's own control requests, relayed as they are.

- `POST /api/ask` takes one request (`lup_dashboard.api.Asked`) and returns its reply (`Replied`), a refusal among them.
- `POST /api/watch` takes one and streams its replies as server-sent events: at once, then again each time the reply changes, through the host's watch socket (`docs/host-tools.md`, *Watching*).
- The requests the page may send: the launches served and their conversations (`ListLaunches`), a launch renamed, the operator's inbox listed, an item shown, answered, finished or sent, an approval answered and its diff read, and the operator's draft shown, kept and sent. Any other is refused before it reaches the host.
- The server (`lup_dashboard/server.py`, FastAPI) talks to the host through `Host`, a seam its tests fill with a stand-in; `Sockets` reaches the running service, through `lup_dev/host/client.py`'s `answer` and `replies`.
- The API's description is the server's own OpenAPI document (`lup-dashboard openapi`), made from the host's pydantic models; the page's types are generated from it.

## Access

Rooms share the host's network, so being on localhost keeps out only other machines.

- Every call to the API carries the token: in the page's cookie (`HttpOnly`, `SameSite=Strict`) or as a bearer.
- The page is handed the token in its address's fragment, which no request carries, trades it for the cookie (`POST /api/session`) and takes it out of the address.
- A request naming another host than `127.0.0.1` or `localhost` is refused, as is a call from a page of another origin.

## The page

- **Built** from `packages/lup-dashboard/page/`: TypeScript, React, React Aria Components for controls the keyboard reaches, cmdk for the command palette, CodeMirror 6 with its vim mode for the review, and Vite, which writes the page into the package (`lup_dashboard/page/`, ignored by git). `packages/lup-dashboard/build.py` installs its packages from their lock, writes the API's description and generates the types from it, type-checks, runs its tests (Vitest), and builds. It's `LupDevelopment`'s `dashboard` step in lup's gate, run where one of its sources, the host's models among them, is newer than the page; trust runs it too when it builds the copy the operator approves. Its packages are pinned exactly, nothing published in the last three days resolving (`min-release-age`).
- **The review:** the page's home, beside the agents. Everything waiting for the operator, across every agent and repository, laid out as one buffer (`page/src/review.ts`, `Review.tsx`): each item under a header naming it, what it is and who sent it, a question's decisions numbered with their leans, an approval's summary with its whole diff a key away, coloured as git colours it. It's moved through with vim (CodeMirror 6 with `@replit/codemirror-vim`). The operator's comments are written into it, each under the line it's on, and edited as text with vim's own keys; only comments can be edited, and a comment emptied is dropped:
  - `o` opens a comment under the line the cursor is on, in insert mode: on that line, a decision's line among them ("Yes, but…"); on the item whole from its header line;
  - `v` and a motion, then `c`, opens one on the selection, under its last line;
  - Space `d` takes an item off the list, Space `z` leaves it for later (what's on it stays drafted), Space `e` opens an approval's diff, Space `a` or `x` approves or declines it; `J` and `K` go to the next and previous item;
  - Ctrl+Enter sends, after a confirmation naming who the reply reaches.
- **The draft** is kept on the host as it's written (`Draft`, `inbox/store.py`; `ShowDraft`, `KeepDraft`), so closing the page loses nothing; a line under the review says what it covers and who it reaches. Sending it (`SendDraft`, `Delivery.reviewed`) gives each conversation whose items carry a comment a review of those items, with the comments on them alone (`Review`); each question it covers is answered by it, which lets a held `ask` go. A message only marked done is taken off the list and its sender told nothing. A draft covering nothing, or an item no conversation sent, is refused, saying which.
- **The demo says it's one** (`GET /api/about`), in the page's top line.
- **Selecting an agent** in the tree narrows the review to what it and its subagents sent, its details under the tree.
- **The agents tree:** each repository, its launches under it, each launch's session's conversation, each subagent under the conversation that spawned it, its ended subagents folded under a count; and what each is doing and for how long (`Talker.activity`): calling a tool, asking lup, between calls, ended. What each is doing is kept with the launch's conversations (`Conversations.activities`), so a host service started again still shows it. Arrows move through it, Enter selects, Left and Right fold.
- **The details** of the conversation selected: its kind, its session and subagent ids, its subagents, and its launch's runtime, worktree and id.
- **The command palette,** Ctrl+K: every agent, to go to.
- **The look:** the first lup's dark palette (its `palette.ts`): Claude Code's `dark-daltonized` colours beside VS Code's high-contrast dark theme, each text colour at 7:1 or more on black; monospace throughout, one row a line, structure from borders, emphasis by outlines and bars rather than fills.
- **The demo:** `lup-dashboard demo` serves the real page over stand-in data (`lup_dashboard/demo.py`): launches over three repositories, subagents working, asking and ended, a question and a note. A session looks at a view with it while building it, driving the room's Chromium headless, and the operator can open it to try one.

## Tests

- `packages/lup-dashboard/tests/test_server.py`: the API on a stand-in host, a request relayed and its reply returned, a refusal returned as a reply, a watch streamed as events, a request the page may not send refused before the host, the token and the origin required, the cookie traded for the token, another host's name refused, a host out of reach said, and the page served for every other path.
- `packages/lup-dev/tests/test_host.py`: the dashboard begun with the service and handed its token on its input, the token kept between starts and readable by its owner alone, the dashboard ending with the service, started again when its address is asked after it died, and one that can't listen, or isn't installed, said.
- `page/src/agents.test.ts`: the tree each conversation is placed in, and what each is said to be doing.
