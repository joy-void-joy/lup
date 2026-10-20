# The operator's credentials, used on the host

A room holds no SSH agent, key, token or `gh` login (`docs/launch.md`, *The mounts*). The host carries out a fixed set of actions with the operator's credentials for it, each held to the limits the project's declaration sets (`DESIGN.md`, *Defaults*). Lent into the room, credentials would answer to nothing: a forwarded SSH agent "can sign anything that key can sign, for every host it reaches", as the first lup found.

## What the declaration allows

`Core`'s `credentials` (`Credentials`, `declaration/kinds.py`) holds three selections, each changed where it stands with its reason (`docs/declaration.md`, *What a launch reads*):
- **`actions`,** from a fixed set: `fetch`, `push`, `force-push`, `delete-ref`, `read-issues`, `file-issue`, `comment`, `draft-pull-request`. lup's default is all but `force-push` and `delete-ref` (`catalog/credentials.py`), so an action a later release adds is allowed unless it's withheld too.
- **`protected`,** refs no push updates: `refs/heads/main`, since what reaches `main` is the operator's to merge, and `refs/tags/*`, since a tag marks a release.
- **`gated`,** refs a push from a room updates only once the gate passed on the commit it would put there: `refs/heads/dev` by default, lup's integration branch.

Beyond the limits, an action is refused, saying that allowing it is the operator's call (`Limits.refusal`). The launch resolves the limits at the approved commit and sends them with its registration as plain data, so the host service never loads a project's declaration, which would run the project's code there.

## git through a remote helper

**In the room** (`remote/helper.py`, `remote/config.py`):
- **The room's git configuration** (`GIT_CONFIG_GLOBAL`) rewrites each URL the repository's remotes name to `lup::<url>` (`insteadOf`), so git runs `git-remote-lup`, written into the launch's `bin/`, for every push and fetch. Fetching needs it as much as pushing, since a remote's URL may use an alias of the operator's SSH configuration, which the room can't resolve.
- **The helper turns each batch git sends into one typed request** on `/run/lup/request.sock`: listing the remote's refs, pushing (each source resolved in the room to an object id, with its destination and whether it's forced), and fetching objects into the repository's own store, which the room shares. It runs on the room's Python with the standard library alone, which an import contract keeps.
- **No upstream is recorded:** `git push -u` pushes, fails to write the upstream ("Device or resource busy", since `config` is read-only) and exits 0, so the configuration sets `push.default = current` and `branch.autoSetupMerge = false`.
- **A push to a gated ref runs the gate first,** on exactly the commit it would put there, so the integration branch never takes a commit the gate fails on, whoever forgot to run it. The helper runs `lup-dev check --at <commit>` through the project's runner, and holds the update where it fails, git printing the gate's report. A pass recorded for the commit's files answers at once, the usual case, since the session landing work ran the gate on the merged result. It runs in the room, since the gate runs the project's code, which the host never runs; so it steers, and a room speaking to the socket directly pushes ungated.

**On the host** (`remote/protocol.py`):
- **Where it pushes is the repository's word, never the room's:** git runs in the repository's own git directory, found by the launcher before the room started, and the remote's URL is the one the repository's `config` gives. A URL from the room, even one equal to a remote's, is refused, or a room could point the operator's credentials at anything they reach. A destination must be a full `refs/…` name.
- **Each update is checked against the limits** before git runs (a force, a deletion, a protected destination), since a room can speak to the socket directly. Then what it would publish goes through the `publishing` moment, where the `Private` module refuses a value never published (`docs/private.md`).
- **It pushes by object id,** `git push <url> <oid>:<dst>`, one update at a time or an `--atomic` batch as one; an update git didn't force is never forced. The objects are already in the shared store, so nothing crosses the socket but ids.
- **The operator's credentials are the service's environment:** their SSH agent and git's credential helpers as the terminal had them when a launch started the service. Every push and fetch is said in the service's log.
- **A push that moves the integration branch** asks trust's approval of its tip, where it isn't the one approved (`docs/trust.md`).

## Running git on the host

A room can't write the git directory's `config` or `hooks/`, but it writes the rest: refs, `objects/`, `info/`, each worktree's directory and `.git` file, and the common directory's `config.worktree`. What host git does about each was measured on scratch repositories laid out as lup's against a hostile room (`docs/field-notes.md`, *Host-side git in a repository the room writes*):
- **Pinned to the git directory.** Host git for a room runs with `GIT_DIR` and `GIT_COMMON_DIR` both naming the repository's common git directory (`pinning`, `Git.pinned`, `git.py`), never found from a working directory. Naming it alone isn't enough: a `commondir` the room writes at its top, which a common git directory never has, turns it into a pointer that `--git-dir`, `-C` and `GIT_DIR` alone all follow to another directory's `config`. Pinned so: every push, fetch and `ls-remote` for a room, `gh` and the git it runs, and the reading of `config` for the room's git. `safe.directory` is no backstop: under `--userns=keep-id` the room's files are the operator's.
- **A self-contained object store.** The host refuses to push or fetch while `objects/info/alternates` exists, or anything under `objects/` is a link: alternates naming another repository's objects let a push copy its blob to the forge.
- **Refused at launch:** a repository whose `config` sets `extensions.worktreeConfig`, under which host git reads the room-written `config.worktree`, or includes a file inside the room's mounts.
- **Quiet otherwise:** `GIT_NO_REPLACE_OBJECTS=1`, `core.fsmonitor` and hooks off for every git lup runs, and automatic maintenance off, since a fetch started a detached `git maintenance` that outlived it.

**Where the host's git still finds its directory through a worktree.** Trust on launch, the launch's own reading of the common git directory (which becomes the registration's `repository`, the directory every pinned git trusts), the judge's places and stores, and the command line's own run git in a worktree and let it follow the worktree's `.git`. A room can plant a link there between launches, aiming the next of these at a `config` of its own. Checking each worktree's links before they're read is #165; protecting the `.git` file at the write is #54.

## GitHub through `gh`

- **From the host, through `gh`** and the operator's login (`forge/github.py`), each answer read with `--json` into a pydantic model naming the fields asked for (`docs/field-notes.md`, *GitHub through `gh` on the host*).
- **The repository is named once,** by the launcher, from the repository's own remotes read in its git directory, and passed to every call as `--repo`, but for a reading call naming another. A worktree's `.git` file is the room's to write, so naming it from a worktree would let a room choose which repository the operator's login acts on.
- **Each tool's action is checked against the limits** before `gh` runs, and what a tool that writes would post goes through the `publishing` moment first.
- **What the tools do:** read and search any repository the operator's login can read; file an issue, comment, and open a draft pull request from a pushed branch into the integration branch, on the launch's own repository alone. None merges, closes or edits an issue: closing one is the operator's judgement, which a comment can ask for (#153).
- **Bodies go on `gh`'s standard input,** and every value the model writes as `--flag=value` or after `--`, never through a shell.
- **`gh` missing or logged out on the host:** each tool answers why, and the launch says it once; `gh` is an optional requirement of the host.

**The gate in a room.** The gate checks that each `defer(issue=…)`'s issue is still open (`docs/judging-writes.md`, *The `# lup:` directives*), and a room has no `gh`. So in a room it asks the host, an `IssueState` on the request socket answered by the `GitHub` module within `read-issues`; elsewhere it runs `gh` itself. An issue the host doesn't answer goes unchecked, said with its reason.
