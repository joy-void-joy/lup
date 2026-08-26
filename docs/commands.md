<!-- Generated from lup.devtools.dev.commands by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# Command reference

Every command `lup-devtools` serves, walked from the composed CLI at generation time. A command reaches this page by existing, so nothing is left out for want of being remembered — including the ones a session rarely runs directly, which are exactly the ones a hand-written list loses first.

Run any of them with `uv run lup-devtools <command>`, and add `--help` for its arguments and options: the summary here is the first line of each command's own documentation, not a substitute for reading it.

## `agent`

| Command | What it does |
| --- | --- |
| `agent inspect` | Inspect the full agent configuration: tools, schemas, prompt, subagents. |
| `agent capabilities` | Show the backend capability matrix (the parity contract, generated). |
| `agent serve-tools` | Start SDK tools as an MCP stdio server (the ``notes`` server). |
| `agent repl` | Interactive REPL — continuous session with the agent via the SDK. |

## `conversation`

| Command | What it does |
| --- | --- |
| `conversation chatgpt` | Retain a ChatGPT conversation and all downloadable attachments. |
| `conversation claude` | Retain a Claude conversation and its API-provided attachment content. |

## `dev`

| Command | What it does |
| --- | --- |
| `dev branches` | Analyze branch containment, PR status, and worktree info. |
| `dev base-branch` | Detect the base branch for the current (or specified) branch. |
| `dev freshness` | Report how far this checkout sits behind its own remote and its base. |
| `dev pr-body` | Generate a PR body (summary, commits, test plan) from branch commits. |
| `dev pending` | Report the real pending changes, excluding sandbox-masked device paths. |
| `dev survey` | Full branch inventory: containment, PRs, unique commits, diff sizes. |
| `dev merge-driver` | Register the ownership-manifest merge driver `.gitattributes` names. |
| `dev delete` | Delete a branch and its worktree, and origin&#x27;s copy if it is spent. |
| `dev retire` | Retire a branch through a pull request, so its commits outlive it. |
| `dev archive-traces` | Copy a worktree&#x27;s session records into the archive beside the repository. |
| `dev resolve-branch` | Create + switch to the resolve/&lt;id&gt; branch (a resolve editor&#x27;s first step). |
| `dev resolve-review` | Render a resolve manifest and its branch diffs into one static HTML review. |
| `dev resolve-summary` | Print per-concern verdicts from a resolve manifest. |
| `dev check` | Run ruff format, ruff check, pyright, and pytest. Read-only by default. |
| `dev comments` | List unresolved `# lup:` feedback comments, or act on specific ones. |
| `dev todos` | List `# lup: template:` markers — a scaffold&#x27;s open decisions. |
| `dev seams` | Show what this project settled about itself, or settle one of them. |
| `dev refutations` | Resolve one file&#x27;s proposed content and report what it refutes. |
| `dev directives` | Measure every `# lup: ignore` against the canonical inline placement. |
| `dev report-friction` | File or correct workflow friction in this checkout&#x27;s repository. |
| `dev upstream` | Print a measured upstream defect, or list the ones declared. |
| `dev undo` | List the recoverable snapshots of this tree, or take and expire them. |
| `dev issues` | List the open issues a resolver run would take as evidence. |
| `dev rules` | Generate the Lup rule and typed-suppression reference. |
| `dev guidance` | Report what each section of the always-loaded guidance costs. |
| `dev relocate` | Move a module and repoint every import of it. |
| `dev policy` | Show what the declared permission policy decides about an input, and why. |
| `dev vocabulary` | Show every shell form the declared vocabulary judges, and how. |
| `dev worktree create` | Create or re-attach a git worktree. |
| `dev worktree list` | List all git worktrees with branch and status info. |
| `dev worktree remove` | Remove a git worktree. |
| `dev pr status` | Fetch PR review status, checks, and comments for a branch. |
| `dev pr merge` | Merge a PR and pull changes into the integration branch. |
| `dev pr sync-base` | Sync the base branch and merge it into the current feature branch. |
| `dev pr push` | Push the current branch and report any existing PR. |
| `dev pr create` | Create a new PR. |
| `dev pr update` | Update a PR body. |
| `dev conflict list` | Show conflicted files with scope classification (in-scope vs out-of-scope). |
| `dev conflict status` | Detect conflict state, list files, and show both sides&#x27; history. |
| `dev conflict audit` | Post-resolution deletion audit: check for accidentally dropped code. |
| `dev conflict complete` | Finalize the merge/rebase/cherry-pick after all conflicts are resolved. |
| `dev plugin name` | Name this repo&#x27;s plugin marketplace uniquely (the plugin entry is kept). |
| `dev git-hooks install` | Install every git hook this repository declares. |
| `dev git-hooks status` | Report what this clone refuses, at every moment a hook sits at. |
| `dev git-hooks uninstall` | Remove them, leaving hooks written elsewhere alone. |
| `dev preserve capture` | Record the surface this repository offers, as a checked-in fixture. |
| `dev preserve check` | Resolve every captured capability against the tree as it stands. |
| `dev preserve migration` | Print the relocation that repoints an importer of the captured tree. |
| `dev model-config census` | Enumerate every `model_config` declaration by right-hand-side shape. |
| `dev model-config aliases` | List every shared configuration alias, and who imports each one. |
| `dev model-config convert` | Rewrite every assigned `model_config` as class keywords, in place. |
| `dev model-config declared` | Record every class&#x27;s declared configuration, without importing it. |
| `dev model-config declared-at` | Record what every class declared as of a git revision. |
| `dev model-config snapshot` | Record the configuration pydantic resolved onto every model. |
| `dev model-config snapshot-at` | Record the configuration pydantic resolved at a git revision. |
| `dev model-config compare` | Diff two snapshots; exit non-zero when any model&#x27;s config moved. |
| `dev init rename-package` | Rename the lup Python package to a project-specific name. |
| `dev init drop-examples` | Remove the scaffold&#x27;s demonstrations of itself, which no adopter wants. |
| `dev library status` | Report where the lup library is resolved from. |
| `dev library release` | Ask the package index whether a release exists, and which mode that settles. |
| `dev library use` | Resolve lup from the package index, or from the vendored copy. |
| `dev library git` | Resolve lup from its repository, for use before a release is published. |
| `dev library link` | Develop against a lup checkout so library changes land in its repo. |
| `dev library unlink` | Stop developing against a checkout and go back to the published release. |

## `feedback`

| Command | What it does |
| --- | --- |
| `feedback status` | Show feedback status: version, data, analysis state, and stats. |
| `feedback collect` | Collect feedback metrics from sessions. |
| `feedback costs` | Per-backend cost/token rollup from session JSONs (any backend). |
| `feedback tools` | Show tool usage aggregates. |
| `feedback errors` | Show sessions with high error rates from structured metrics. |
| `feedback trends` | Show metric trends over time. |
| `feedback history` | Show previous feedback collection runs. |
| `feedback mark` | Mark sessions as analyzed in the feedback loop. |
| `feedback unmark` | Remove analysis marks from sessions. |
| `feedback prompt-health` | Analyze the agent prompt for size and patch accumulation. |
| `feedback unanalyzed` | List unanalyzed session IDs, one per line. |
| `feedback analyze` | Produce a structured JSON analysis report (tools, errors, gaps). |
| `feedback commit` | Commit all uncommitted session result files, one commit per session. |

## `harness`

| Command | What it does |
| --- | --- |
| `harness generate` | Deterministically generate owned native artifacts without launching. |
| `harness check` | Read-only ownership and generated-artifact drift check for CI. |
| `harness reconcile` | Classify local differences without rewriting canonical Python source. |
| `harness apply-reconciliation` | Apply a stale-base-checked source patch, then regenerate every target. |
| `harness propose-reconciliation` | Persist a source patch for separate review and stale-base-checked apply. |
| `harness doctor` | Report installed native runtime evidence without updating either CLI. |
| `harness requirements` | Exercise the external programs this project expects on this machine. |
| `harness image` | Render the container image this project&#x27;s sessions run in. |
| `harness egress` | Report or remove the network boundary this project&#x27;s sessions run behind. |
| `harness serve-resolver-tools` | Serve one worker&#x27;s question tools over stdio, for out-of-process runtimes. |
| `harness claude` | Generate/reconcile Claude artifacts and launch the verified plugin. |
| `harness codex` | Generate/reconcile Codex artifacts and launch without updating the CLI. |
| `harness resolve status` | Say whether a run is alive, where it stands, and what it last did. |
| `harness resolve supervise` | Answer any run under ``.lup/resolve``, live or parked. |
| `harness resolve questions` | List a run&#x27;s questions and what each one has been answered. |
| `harness resolve answer` | Offer an answer to one or more of a run&#x27;s questions. |
| `harness resolve actors` | List every actor this run has recorded, and what each has not read yet. |
| `harness resolve say` | Tell an actor something. It reads this and keeps going. |
| `harness resolve accept` | Accept one concern over one failing verification, on the human&#x27;s word. |
| `harness resolve retire` | Retire one concern whose work was settled somewhere other than this run. |
| `harness resolve redirect` | Stop an actor and put it on something else. |
| `harness resolve park` | Ask every open wait in this run to give up now. |
| `harness resolve drain` | Ask a busy run to finish what is in flight and stop, resumably. |
| `harness resolve refresh` | Bring a run&#x27;s base, and the leases holding work, up to its branch. |
| `harness resolve intake` | Print what a run started now would plan from, without starting one. |
| `harness profile list` | Show every profile, and which one a launch selects by default. |
| `harness profile add` | Register a runtime configuration home under a name. |
| `harness profile use` | Select the profile a launch uses when none is named. |
| `harness profile remove` | Forget a profile, leaving its configuration home on disk. |

## `hooks`

| Command | What it does |
| --- | --- |
| `hooks classify` | Say what the policy decides about one shell command, and why. |
| `hooks classify-fetch` | Say whether a URL is inside this project&#x27;s declared fetch scopes. |
| `hooks sweep` | Classify a list of commands at once, and exit non-zero if any is not allowed. |
| `hooks roots` | List the path roles and protected roots the declaration carries. |
| `hooks learn` | Review the commands the policy declined to interrupt about. |

## `py`

| Command | What it does |
| --- | --- |
| `py info` | Inspect a Python object — adapts to modules, classes, functions, values. |
| `py source` | View source code for a Python object, or a package file tree with --tree. |
| `py imports` | Show what a module imports, or what imports it (--reverse). |
| `py text` | Search literal source text within explicitly selected Python paths. |
| `py search` | Search for symbols across installed packages by name (case-insensitive). |

## `setup`

| Command | What it does |
| --- | --- |
| `setup status` | Show current integration status. |
| `setup slack` | Set up Slack tokens. |
| `setup google` | Set up Google OAuth. |
| `setup notion` | Set up Notion integration. |
| `setup api-key` | Set up Example API key. |
| `setup codex` | Set Codex/OpenAI per-MTok pricing (enables budget caps). |
| `setup timezone` | Set timezone. |
| `setup conversation chatgpt` | Open a browser to authenticate ChatGPT conversation access. |
| `setup conversation claude` | Open a browser to authenticate Claude conversation access. |
| `setup profile list` | Show every profile, and which one a launch selects by default. |
| `setup profile add` | Register a runtime configuration home under a name. |
| `setup profile use` | Select the profile a launch uses when none is named. |
| `setup profile remove` | Forget a profile, leaving its configuration home on disk. |

## `sync`

| Command | What it does |
| --- | --- |
| `sync status` | Show tracked projects and their sync status (read-only). |
| `sync fetch` | Clone missing repos and fetch/reset cached ones (network + writes). |
| `sync log` | List commits to review: everything upstream added since the last sync. |
| `sync diff` | Show full diff for a specific commit. |
| `sync mark-synced` | Advance the sync checkpoint to the upstream&#x27;s current HEAD. |
| `sync setup` | Set the local path for a project (writes to sync.json.local). |

## `trace`

| Command | What it does |
| --- | --- |
| `trace show` | Show trace for a session. |
| `trace search` | Search traces for a pattern. |
| `trace list` | List available traces. |
| `trace errors` | Show sessions with errors found in trace files. |
| `trace capabilities` | Extract capability requests from traces. |

## `usage`

| Command | What it does |
| --- | --- |
| `usage claude` | Show live Claude Code usage with pacing bars (Anthropic OAuth). |
| `usage codex` | Show live Codex usage with pacing bars (ChatGPT plan). |

## `version`

| Command | What it does |
| --- | --- |
| `version changelog` | Show changes since a version tag, classified by type. |
| `version bump` | Bump agent version, record the release, and create a git tag. |
