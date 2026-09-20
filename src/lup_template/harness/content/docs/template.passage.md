<!-- passage: template -->

Run `uv run lup-devtools --help` for the full command tree. The three you will
use daily:

- **`dev`** — worktrees, branches, pull requests, conflict resolution, review
  markers, and the pre-flight `dev check`. This is the git workflow.
- **`harness`** — generate, verify, and launch the native trees. See
  [harness.md](harness.md).
- **`trace`** — read what a session actually did: `trace show`, `trace search`,
  `trace errors`.

If you run the same shell incantation twice, add a command here instead. The
CLI is written with [typer](https://typer.tiangolo.com/), and shells out with
[sh](https://sh.readthedocs.io/) rather than `subprocess`. One-off work goes
through the reviewable ladder in
[contributing.md](contributing.md) rather than a script in `tmp/`, which is
gitignored and so reaches no diff and no reviewer.

### `harness/` — the declaration graph

Declaration content sits above the tooling that compiles it, so the harness is
its own package rather than a corner of `devtools/`. `catalog.py` is the root:
it assembles the skills and agents this project composes with the
application-owned `HookSet` and the resolver spec into one `Harness`.
`content/` holds the leaves — one module per skill, per agent, per document —
and `content/modules/` groups them by subject: a module carries its content,
its page, its paragraph in the always-loaded document, its command tree and
its tool group, and `content/catalog.py` states which of them this project
takes. What the plugin ships, what `docs/` publishes, what the CLI serves and
what a session is offered are all derived from that one answer.
[harness.md](harness.md) is the guide; this is only where the files are.

### The setup dashboard

`uv run lup-devtools setup dashboard` serves a local browser interface at
`http://127.0.0.1:8765`. It is the web face of the same declarative
`INTEGRATIONS` registry that `uv run lup-devtools setup` walks in the
terminal: a domain customizes the registry once and gets both.

A progress-oriented wizard covers first setup; an all-integrations view covers
later maintenance. Browser forms are generated only for declarative
environment fields, from an explicit per-integration allowlist, so the page
cannot write an arbitrary variable; anything needing OAuth or bespoke
validation routes to its existing CLI command. FastAPI serves the `wizard`
surface Vite built into `lup.web`'s package data — the wheel carries the
bundle, and bun is needed only to change it — and `--no-open` and `--port`
cover the cases where the defaults do not fit.

`--host` takes only a loopback address, and every request's `Host` header is
checked against one. The page writes credentials into `.env.local`, and a
local bind alone leaves that reachable by DNS rebinding from any page the
browser has open. Both halves are `lup.web.loopback`, shared with the
resolver's supervisor page; see [supervisor.md](supervisor.md).

### The sync registry

`lup-devtools sync` tracks the other repositories this project exchanges
improvements with and reviews their commits since the last sync. The {{ update_skill }} and {{ import_skill }} skills are built on it. Two files declare
what to track.

**`sync.json` (committed)** declares the upstream's name without choosing
a hosting account. Configure its URL or checkout path in `sync.json.local`
before fetching template improvements:

```json
{
  "projects": [
    {
      "name": "lup"
    }
  ]
}
```

For example, a local registration can supply
`{"projects": [{"name": "lup", "url": "https://github.com/example/framework"}]}`.
A checkout can be registered with `uv run lup-devtools sync setup lup /path/to/repo`.

Repository identity is configured independently from the adopting project's
own Git origin. `uv run lup-devtools dev library git --url <repository>` selects the dependency's
source explicitly. Without `--url`, it uses the existing Git dependency pin,
then the scaffold's named sync registration: its URL, or its checkout's origin.
An absent source is reported before any pin is changed. Library friction reports
use that same configured upstream; the consuming project's reports use its own
origin. Package metadata may declare `[project.urls]` for publication; the
template supplies no account-specific URLs.

It is scaffold, not personal state. **Agents must never modify the tracked
`sync.json`**, and neither should routine project work; the edit policy
enforces this by treating it as a protected path. Every personal registration
belongs in the gitignored **`sync.json.local`**: local paths, per-project
`last_synced_commit` state, branch overrides, `"ignore": true` opt-outs, and
additional projects. Entries there override tracked entries by name or add
local-only ones, and `sync setup` and `mark-synced` write only there.

The registry has no direction in its name because direction depends on where
you sit. A project built on the template configures the shipped `lup` entry and
pulls *from* it. The lup repository itself sets `"ignore": true` on its own
entry and registers its downstream fleet in `sync.json.local`, so {{ update_skill_2 }} can generalize emerged patterns back into the template. Same
registry, opposite seats.

An entry may also carry a `"mount"` of `"rw"` or `"ro"`, which is a
declaration about *access* rather than about review: a session opens that
project at its own path, inside the container as well as outside it, and
`refs/<name>` resolves there rather than dangling. Written or absent, never
defaulted — tracking a project and handing a session the keys to it are
different claims, and `sync.json` is committed scaffold that would otherwise
make the second one on every adopter's behalf.

The same file grants host devices, for the same reason: `sync grant
nvidia.com/gpu=all` writes the CDI name into a top-level `"devices"` list
after starting a throwaway container with it, and every session and resolver
worker opened on this machine is handed it from then on. Which GPU a machine
holds is that machine's fact, so the list lives only in the local half, never
in a committed declaration; `sync revoke` takes one back, `sync status` shows
each grant beside whether a spec on this machine still names it, and the
launchers take `--device <name>` for one launch.

A registration that names only a URL is materialized under
`~/.cache/lup/sync/<name>.git` in the layout one naming a local path already
points at: a full bare clone — every branch, whole history — with a worktree
attached at `tree/<branch>`. What is mounted is that worktree, so a session
opens either kind of registration on the same terms, and `git worktree
create` inside one lands its next checkout beside the first. The cache sits
outside the project deliberately. A clone under the checkout is inside the
session's own writable mount, which makes a `"ro"` registration silently
`"rw"`, and it is re-cloned once per worktree where the history is worth
having once per machine.

Nothing a review does moves a branch in one of those clones. The upstream's
commits are read from its remote-tracking ref rather than from `HEAD`, so
refreshing is a fetch: `sync fetch`, `sync log` and `sync diff` leave a
branch cut in the clone, a commit made on it, and every uncommitted file
beside it exactly where they stand. `sync log` reports what the *upstream*
added, never what a session working in the clone did.

## How the two halves depend on each other

`lup_template` imports `lup`. `lup` never imports `lup_template` — it is
published standalone and could not. The placement test for any new utility is
the same question in both directions: *would another project built on lup want
this?* If yes it belongs in `packages/lup/`; if it only makes sense for this
application it belongs here.

`lup[claude,codex,docker]` is declared as a workspace dependency in the root
`pyproject.toml`, so a checkout resolves the library from source and an edit to
either half is immediately live in the other.
