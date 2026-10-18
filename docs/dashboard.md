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
- The requests the page may send: the launches served and their conversations (`ListLaunches`), a launch renamed, the operator's inbox listed, an item shown, answered, finished or sent, an approval answered and its diff read. Any other is refused before it reaches the host.
- The server (`lup_dashboard/server.py`, FastAPI) talks to the host through `Host`, a seam its tests fill with a stand-in; `Sockets` reaches the running service, through `lup_dev/host/client.py`'s `answer` and `replies`.
- The API's description is the server's own OpenAPI document (`lup-dashboard openapi`), made from the host's pydantic models; the page's types are generated from it.

## Access

Rooms share the host's network, so being on localhost keeps out only other machines.

- Every call to the API carries the token: in the page's cookie (`HttpOnly`, `SameSite=Strict`) or as a bearer.
- The page is handed the token in its address's fragment, which no request carries, trades it for the cookie (`POST /api/session`) and takes it out of the address.
- A request naming another host than `127.0.0.1` or `localhost` is refused, as is a call from a page of another origin.

## The page

- **Built** from `packages/lup-dashboard/page/`: TypeScript, React, React Aria Components for controls the keyboard reaches, cmdk for the command palette, and Vite, which writes the page into the package (`lup_dashboard/page/`, ignored by git). `packages/lup-dashboard/build.py` installs its packages from their lock, writes the API's description and generates the types from it, type-checks, runs its tests (Vitest), and builds. It's `LupDevelopment`'s `dashboard` step in lup's gate, run where one of its sources, the host's models among them, is newer than the page; trust runs it too when it builds the copy the operator approves. Its packages are pinned exactly, nothing published in the last three days resolving (`min-release-age`).
- **The agents tree:** each launch with its session's conversation, each subagent under the conversation that spawned it, and what each is doing and for how long (`Talker.activity`): calling a tool, asking lup, between calls, ended. Arrows move through it, Enter selects, Left and Right fold.
- **The details** of the conversation selected: its kind, its session and subagent ids, its subagents, and its launch's runtime, worktree and id.
- **The command palette,** Ctrl+K: every agent, to go to.
- **The look:** the operator's Claude Code theme, `dark-daltonized`, its colours as Claude Code 2.1.302 defines them: blue for good where other themes use green, red for bad, white text at a moderate contrast.

## Tests

- `packages/lup-dashboard/tests/test_server.py`: the API on a stand-in host, a request relayed and its reply returned, a refusal returned as a reply, a watch streamed as events, a request the page may not send refused before the host, the token and the origin required, the cookie traded for the token, another host's name refused, a host out of reach said, and the page served for every other path.
- `packages/lup-dev/tests/test_host.py`: the dashboard begun with the service and handed its token on its input, the token kept between starts and readable by its owner alone, the dashboard ending with the service, started again when its address is asked after it died, and one that can't listen, or isn't installed, said.
- `page/src/agents.test.ts`: the tree each conversation is placed in, and what each is said to be doing.
