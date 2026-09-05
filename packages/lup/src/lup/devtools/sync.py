"""Track repos to sync with and review their commits since the last sync.

These commands are the read/fetch half of ``/lup:update`` — the workflow that
pulls improvements *from* the lup template (and other tracked upstreams) *into*
this repo. ``/lup:update`` reviews every upstream commit since the last sync,
generalizes the domain-specific ones back into reusable scaffold, and applies
them; this module is what gives it the diffs to review and remembers how far it
got. ``status`` shows which upstreams have new commits, ``log``/``diff`` feed
the commit-by-commit review, and ``mark-synced`` advances the per-project
checkpoint once a review is done so the next run starts where this one stopped.

Reviewing a diff means reading the upstream's *current* code, so commits are
fetched into a local working copy before comparison (see ``ensure_local``):
``status`` stays read-only and never touches the network, while ``log``/``diff``
clone-or-fetch on demand. Each materialized upstream also gets a stable
``refs/<name>`` symlink so other commands (e.g. ``/lup:import``) can browse it
by name without re-resolving cache paths.

Two registry files declare what to track:

- sync.json (committed): the template's registry default, shipping only the
  lup entry so a fresh project can immediately pull template improvements.
  It is template scaffold: agents must never modify it — every personal
  registration belongs in sync.json.local, and the edit policy asks before
  any change to the tracked file.
- sync.json.local (gitignored): personal registrations — local paths, sync
  state, overrides by project name, and local-only projects. Set
  "ignore": true to skip a project (useful when you ARE the upstream).

The registry is direction-neutral: "sync" names the mechanism, not a
direction. Seen from a project built on the template, the shipped lup entry
is an upstream to pull improvements from; seen from the lup repo itself,
sync.json.local registers the downstream fleet whose commits /lup:update
reviews. Same tooling, opposite seats.

The script merges both: .local entries override sync.json entries by name.
Projects with a URL but no local path are auto-cloned to .cache/sync/.

An entry carrying a "mount" is also a declaration about *access*: a session
can open that project, at the mode it names, wherever the project lives on
this machine. Absent, nothing is mounted — which is the whole difference
between a registry and a boundary, and the reason the key has to be written
rather than defaulted. sync.json is committed scaffold, so a default here
would decide what every project adopting this template opens.

Examples::

    $ uv run lup-devtools sync status
    $ uv run lup-devtools sync log my-project
    $ uv run lup-devtools sync log my-project --no-stat
    $ uv run lup-devtools sync diff my-project abc1234
    $ uv run lup-devtools sync mark-synced my-project
    $ uv run lup-devtools sync mark-synced my-project --at 4c6293a6
    $ uv run lup-devtools sync setup my-project /path/to/repo --synced
    $ uv run lup-devtools sync setup my-project /path/to/repo --branch main
"""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal, Required, TypedDict, get_args

import sh
import typer
from pydantic import ConfigDict, TypeAdapter, with_config

from lup.workspace.paths import project_root
from lup.devtools.subapps import subapp
from lup.devtools.utils import decode_stderr, format_table, short_sha
from lup.execution.shell import git
from lup.sandbox.rail import AccessibleRoot

app = typer.Typer(no_args_is_help=True)
SUBAPP = subapp("sync", "Track sync.json repos and review their commits", app)
logger = logging.getLogger(__name__)


@with_config(ConfigDict(extra="allow"))
class ProjectEntry(TypedDict, total=False):
    """One tracked project, merged from sync.json(.local).

    A ``TypedDict``, not a ``BaseModel``: per CLAUDE.md, ``TypedDict`` types
    the JSON-shaped config we read from and write back to disk verbatim, while
    ``BaseModel`` is for values we validate and construct. These entries are
    hand-edited config, so loads validate the declared keys (catching typos
    with a real error instead of silent misbehavior) and ``extra="allow"``
    keeps any hand-added keys so the document round-trips unchanged.
    """

    name: Required[str]
    path: str
    url: str
    branch: str
    last_synced_commit: str
    ignore: bool
    mount: Literal["rw", "ro"]
    """Whether a session may open this project, and in which mode.

    Written or absent, never defaulted. Tracking a project for review and
    handing a session the keys to it are different claims, and the file that
    makes the first one is committed scaffold shipped to every project built
    on this template -- so a default would open a repository on machines
    nobody here has seen.

    A separate question from ``ignore``, which governs sync *review*: being
    the upstream of this repository is a reason not to read its commits back
    and no reason at all to be unable to open it. Spelled as a literal so a
    misspelling is the error this registry's validation exists to raise
    rather than a project quietly out of reach."""


@with_config(ConfigDict(extra="allow"))
class SyncConfig(TypedDict):
    """Top-level shape of sync.json and sync.json.local.

    Same rationale as :class:`ProjectEntry`: a ``TypedDict`` mirroring the
    on-disk JSON document, validated on read with extras preserved.
    """

    projects: list[ProjectEntry]


SYNC_CONFIG_ADAPTER = TypeAdapter(SyncConfig)
PROJECT_ENTRY_ADAPTER = TypeAdapter(ProjectEntry)

MOUNT_MODES: tuple[str, ...] = get_args(ProjectEntry.__annotations__["mount"])
"""The modes a registration may ask for, read off the entry that declares them.

Derived rather than restated, so the command line and the document cannot come
to accept different words. A second spelling here is how the CLI would end up
taking a mode the registry then refuses to validate."""


def sync_file() -> Path:
    return project_root() / "sync.json"


def local_file() -> Path:
    return project_root() / "sync.json.local"


def cache_dir() -> Path:
    return project_root() / ".cache" / "sync"


def refs_dir() -> Path:
    return project_root() / "refs"


def load_json(path: Path) -> SyncConfig:
    if not path.exists():
        return {"projects": []}
    try:
        return SYNC_CONFIG_ADAPTER.validate_python(json.loads(path.read_text()))
    except json.JSONDecodeError as error:
        raise typer.BadParameter(f"{path} is not valid JSON: {error}") from error


def save_local(data: SyncConfig) -> None:
    local_file().write_text(json.dumps(data, indent=2) + "\n")


def ensure_ref_symlink(name: str, target: str) -> None:
    """Point the stable ``refs/<name>`` symlink at a project's working copy.

    ``refs/`` (gitignored) is a directory of by-name shortcuts into the
    repos this project tracks for sync, wherever each one actually lives —
    a user-configured path, or a clone under ``.cache/sync/``. It exists
    so commands and humans can reach a tracked repo as ``refs/<name>`` without
    knowing or re-deriving its real location (e.g. ``/lup:import`` does
    ``cd refs/<project> && git log``). Every time a project is materialized the
    link is re-pointed at its current path; a pre-existing non-symlink at that
    name is left untouched so we never clobber real files.
    """
    refs_dir().mkdir(exist_ok=True)
    link = refs_dir() / name
    target_path = Path(target).resolve()
    if link.is_symlink():
        if link.resolve() == target_path:
            return
        link.unlink()
    elif link.exists():
        logger.warning("refs/%s exists but is not a symlink, skipping", name)
        return
    link.symlink_to(target_path)
    logger.debug("refs/%s -> %s", name, target_path)


def load_projects() -> list[ProjectEntry]:
    """Load and merge projects from sync.json + sync.json.local."""
    base = load_json(sync_file())
    local = load_json(local_file())

    merged: dict[str, ProjectEntry] = {}  # lup: ignore[empty-collection] — merge fold
    for p in base.get("projects", []):
        merged[p["name"]] = p.copy()
    for p in local.get("projects", []):
        name = p["name"]
        if name in merged:
            base_entry = merged[name]
            merged[name] = PROJECT_ENTRY_ADAPTER.validate_python({**base_entry, **p})
        else:
            merged[name] = p.copy()

    return list(merged.values())


def find_project(name: str) -> ProjectEntry:
    """Find a project by name, raising Exit if not found."""
    projects = load_projects()
    proj = next((p for p in projects if p["name"] == name), None)
    if not proj:
        typer.echo(f"Project '{name}' not found.")
        typer.echo(f"Available: {', '.join(p['name'] for p in projects)}")
        raise typer.Exit(1)
    return proj


def resolve_existing_path(proj: ProjectEntry) -> str | None:
    """Return a usable local path WITHOUT cloning or fetching, or None.

    Read-only counterpart to :func:`ensure_local` — for status reporting
    that must never mutate the working tree or hit the network.
    """
    path = proj.get("path", "")
    if path and Path(path).exists():
        return path
    cache_path = cache_dir() / proj["name"]
    if cache_path.exists():
        return str(cache_path)
    return None


def own_commits(path: str, upstream: str) -> bool:
    """Whether this checkout holds commits its upstream ref does not.

    Asked before a hard reset, because the reset is how a cached checkout
    stays current for review and it is also how work done inside one
    disappears with nothing said. A cache checkout lives under the project
    root, so it is writable with the checkout and a session can commit there
    -- and could, before anything asked this.

    A checkout that cannot answer is read as holding nothing, which is the
    reset's own precondition rather than a guess: `rev-list` fails where the
    upstream ref is missing, and a reset to a ref that is not there fails
    immediately after, naming it.
    """
    try:
        return commit_count(path, upstream) > 0
    except (sh.ErrorReturnCode, ValueError):
        return False


def accessible_roots(
    report: Callable[[str], None] = typer.echo,
) -> list[AccessibleRoot]:
    """Every registered project that asked to be reachable, as mounts.

    Only the entries carrying a ``mount``. Registering a project says the
    tooling may read its commits; nothing about it says a session may open
    it, and the two live in the same file only because the file is where a
    project is named. Silence here is the answer for every registration
    written before this key existed, and for the lup entry the committed
    scaffold ships to every adopter.

    Read from the registry rather than from `refs/`, and that difference is
    the whole of why this exists. `refs/` is a directory of symlinks built
    from this registry; it is gitignored, and it sits inside the checkout, so
    it is writable from inside the boundary. A mount table read off it would
    be one the confined session could extend by writing a symlink, which is
    the confined thing choosing what confines it.

    A registration carrying only a URL is materialized on the way past, so
    naming a project on a forge is enough to be able to open it. That happens
    on the host, before the boundary and on the only side that can reach the
    forge -- and only where nothing is on disk yet, because
    :func:`ensure_local` also fetches and resets, and opening a session is
    not a review.

    A registration that asked for a mount and has neither a path nor a URL is
    reported and skipped. That is a note somebody did not finish, in a
    gitignored file, and failing a launch over one would turn it into a
    session that will not open.
    """

    def located(project: ProjectEntry) -> AccessibleRoot | None:
        """Where one registration is on disk, materializing it if it is not."""
        if "mount" not in project:
            return None
        mode = project["mount"]
        found = resolve_existing_path(project)
        if found is None and project.get("url", ""):
            found = ensure_local(project, report)
        if found is None:
            report(
                f"'{project['name']}' has neither a local path nor a URL, "
                "so it stays out of reach"
            )
            return None
        return AccessibleRoot(path=Path(found).resolve(), writable=mode == "rw")

    return [
        root for project in load_projects() if (root := located(project)) is not None
    ]


def ensure_local(
    proj: ProjectEntry,
    report: Callable[[str], None] = typer.echo,
) -> str:
    """Materialize an upstream so its commits can be read, return its path.

    Reviewing upstream commits (``log``/``diff``) means reading the upstream's
    actual git history, which only exists in a local checkout — so before any
    such command can run, the project must be present and current on disk. This
    is that guarantee: it clones a project that has only a URL, fetches and
    hard-resets one already cached so the review sees the latest commits rather
    than a stale snapshot, and leaves a user-provided local path as-is. In
    every case it (re)points ``refs/<name>`` at the result and hands back the
    path the caller runs git in. ``status`` deliberately does *not* call this
    (it uses :func:`resolve_existing_path` instead) so a status check never
    clones, fetches, or writes.

    Progress and error text goes through ``report`` so callers rendering
    tables can defer the messages instead of interleaving them mid-table.
    """
    path = proj.get("path", "")
    name = proj["name"]
    branch = proj.get("branch", "")
    if path and Path(path).exists():
        ensure_ref_symlink(name, path)
        return path

    cache_path = cache_dir() / name
    url = proj.get("url", "")
    reset_target = f"origin/{branch}" if branch else "origin/HEAD"

    if cache_path.exists():
        report(f"Fetching latest for '{name}' from cache...")
        try:
            git("-C", str(cache_path), "fetch", "--quiet")
            if own_commits(str(cache_path), reset_target):
                report(
                    f"'{name}' holds commits {reset_target} does not, so it was "
                    "left where it stands rather than reset over. Push them or "
                    "drop them to review against the upstream again."
                )
            else:
                git("-C", str(cache_path), "reset", "--hard", reset_target, "--quiet")
        except sh.ErrorReturnCode as e:
            report(f"Warning: fetch failed: {decode_stderr(e)}")
        ensure_ref_symlink(name, str(cache_path))
        return str(cache_path)

    if url:
        report(f"Cloning '{name}' from {url}...")
        cache_dir().mkdir(parents=True, exist_ok=True)
        clone_args = ["clone", "--depth=200"]
        if branch:
            clone_args.extend(["--branch", branch])
        clone_args.extend([url, str(cache_path)])
        try:
            git(*clone_args)
        except sh.ErrorReturnCode as e:
            report(f"Clone failed: {decode_stderr(e)}")
            raise typer.Exit(1)
        ensure_ref_symlink(name, str(cache_path))
        return str(cache_path)

    report(
        f"Project '{name}' has no local path or URL configured.\n"
        "Either:\n"
        "  1. Add a URL for it in sync.json.local\n"
        f"  2. Run: uv run lup-devtools sync setup {name} /path/to/repo"
    )
    raise typer.Exit(1)


def git_in(path: str, *args: str) -> str:
    """Run git command in a specific directory."""
    return git.out("-C", path, *args)


def commit_count(path: str, since: str) -> int:
    """Count commits since a given ref."""
    if not since:
        output = git_in(path, "rev-list", "--count", "HEAD")
        return int(output)
    output = git_in(path, "rev-list", "--count", f"{since}..HEAD")
    return int(output)


def current_head(path: str) -> str:
    """Get current HEAD sha."""
    return git_in(path, "rev-parse", "HEAD")


def resolved_checkpoint(path: str, ref: str) -> str:
    """The commit a checkpoint should record, from a ref or from HEAD.

    Resolution happens in the upstream checkout rather than being taken on
    trust, so a tag or branch name works and a commit that checkout does not
    have is refused here — where the caller can still fix it — instead of
    landing in the record as a checkpoint nothing can compute a range from.
    """
    if not ref:
        return current_head(path)
    try:
        return git_in(path, "rev-parse", "--verify", f"{ref}^{{commit}}")
    except sh.ErrorReturnCode as error:
        raise typer.BadParameter(f"{ref!r} does not name a commit in {path}") from error


@app.command("status")
def status_cmd() -> None:
    """Show tracked projects and their sync status (read-only).

    Reports cached/not-cloned/behind state without cloning, fetching, or
    resetting. Run ``sync fetch`` to materialize and refresh repos.
    """
    projects = load_projects()

    if not projects:
        typer.echo("No projects tracked. Check sync.json(.local) or run 'setup'.")
        raise typer.Exit(1)

    def reach(p: ProjectEntry) -> str:
        """Whether a session can open this project, in the words it declared.

        Its own column rather than a note on the source, because it answers a
        different question from the rest of the table: everything else says
        how far behind an upstream is, and this says what the next session
        can write. A registration that never asked reads as `—`, which is the
        same absence the launch acts on.
        """
        return p["mount"] if "mount" in p else "—"

    def project_row(p: ProjectEntry) -> list[str]:
        synced = p.get("last_synced_commit", "")
        synced_short = short_sha(synced) if synced else "never"

        if p.get("ignore"):
            return [p["name"], "—", "ignored", reach(p), "(skipped)"]

        resolved = resolve_existing_path(p)
        if resolved is None:
            has_url = bool(p.get("url"))
            note = "not cloned (run: sync fetch)" if has_url else "no path/url"
            return [p["name"], "—", synced_short, reach(p), note]

        try:
            behind: int | str = commit_count(resolved, synced)
        except (sh.ErrorReturnCode, ValueError):
            behind = "?"
        branch = p.get("branch", "")
        source = f"{resolved} ({branch})" if branch else resolved
        return [p["name"], str(behind), synced_short, reach(p), source]

    rows = [project_row(p) for p in projects]

    typer.echo()
    typer.echo(
        format_table(("Project", "Behind", "Last Synced", "Mount", "Source"), rows)
    )
    typer.echo()


@app.command("fetch")
def fetch_cmd(
    project: Annotated[
        str | None,
        typer.Argument(help="Project to materialize/refresh (default: all)"),
    ] = None,
) -> None:
    """Clone missing repos and fetch/reset cached ones (network + writes)."""
    projects = load_projects()
    targets = (
        [find_project(project)]
        if project
        else [p for p in projects if not p.get("ignore")]
    )
    for p in targets:
        try:
            resolved = ensure_local(p)
            typer.echo(f"{p['name']}: ready at {resolved}")
        except (typer.Exit, sh.ErrorReturnCode):
            typer.echo(f"{p['name']}: could not materialize", err=True)


@app.command("log")
def show_log(
    project: Annotated[str, typer.Argument(help="Project name")],
    stat: Annotated[
        bool, typer.Option("--stat/--no-stat", help="Show file stats")
    ] = True,
) -> None:
    """List commits to review: everything upstream added since the last sync.

    This is the inventory ``/lup:update`` walks — the commits whose diffs get
    read (via ``sync diff``) and considered for porting. Fetches the upstream
    first so the list reflects its current HEAD.
    """
    proj = find_project(project)
    path = ensure_local(proj)

    synced = proj.get("last_synced_commit", "")
    range_spec = f"{synced}..HEAD" if synced else "HEAD"

    args = ["log", "--oneline"]
    if stat:
        args.append("--stat")
    args.append(range_spec)

    output = git_in(path, *args)
    if output:
        typer.echo(output)
    else:
        typer.echo(f"No new commits since {short_sha(synced)}.")


@app.command("diff")
def show_diff(
    project: Annotated[str, typer.Argument(help="Project name")],
    commit: Annotated[str, typer.Argument(help="Commit SHA to show")],
) -> None:
    """Show full diff for a specific commit."""
    proj = find_project(project)
    path = ensure_local(proj)
    output = git_in(path, "show", commit)
    typer.echo(output)


@app.command("mark-synced")
def mark_synced(
    project: Annotated[str, typer.Argument(help="Project name")],
    at: Annotated[
        str,
        typer.Option(
            "--at", help="Record this commit as the checkpoint instead of HEAD"
        ),
    ] = "",
) -> None:
    """Advance the sync checkpoint to the upstream's current HEAD.

    Run once a review is finished: it records that every commit up to the
    upstream's HEAD has been considered, so the next ``sync log`` / ``status``
    only surfaces commits that land afterward. Marking synced even when nothing
    was ported is correct — it means "reviewed, decided to port none."

    ``--at`` records a commit the project already consumed rather than the
    one the upstream is on now. A project adopting a library mid-stream knows
    which commit it took and has, without this, no way to say so: marking
    synced would silently claim every commit that landed afterward as
    reviewed, which is the opposite of what the checkpoint is for. The ref is
    resolved in the upstream checkout, so a tag or a branch name works and a
    commit that is not there is refused rather than written.
    """
    proj = find_project(project)
    path = ensure_local(proj)

    head = resolved_checkpoint(path, at)

    local_data = load_json(local_file())
    local_projects = local_data.get("projects", [])

    entry = next((p for p in local_projects if p["name"] == project), None)
    if entry:
        entry["last_synced_commit"] = head
    else:
        local_projects.append(
            {
                "name": project,
                "path": path,
                "last_synced_commit": head,
            }
        )
        local_data["projects"] = local_projects

    save_local(local_data)
    typer.echo(f"Marked '{project}' as synced at {short_sha(head)}.")


@app.command("setup")
def setup_project(
    name: Annotated[str, typer.Argument(help="Project name")],
    path: Annotated[str, typer.Argument(help="Local path to the repo")],
    synced: Annotated[
        bool, typer.Option("--synced", help="Mark as already synced at current HEAD")
    ] = False,
    branch: Annotated[
        str,
        typer.Option("--branch", "-b", help="Branch to track (default: remote HEAD)"),
    ] = "",
    mount: Annotated[
        str,
        typer.Option(
            "--mount",
            help=(
                f"Open this project from a session: {' or '.join(MOUNT_MODES)}. "
                "Omitted, it is tracked and not reachable"
            ),
        ),
    ] = "",
) -> None:
    """Set the local path for a project (writes to sync.json.local).

    ``--mount`` is what makes the project *reachable* rather than merely
    tracked: a session opens it at this same path, inside the container as
    well as outside, and `refs/<name>` resolves there instead of dangling.
    Separate from registering it because the two are separate claims, and the
    one that hands a session the keys is the one worth typing out.
    """
    if mount and mount not in MOUNT_MODES:
        raise typer.BadParameter(f"--mount takes {' or '.join(MOUNT_MODES)}")
    resolved = Path(path).resolve()
    if not resolved.exists():
        typer.echo(f"Path does not exist: {resolved}")
        raise typer.Exit(1)

    repository = (resolved / ".git").exists() or (resolved / ".git").is_file()
    # A directory that is not a checkout can still be worth reaching -- a
    # corpus, a set of reference material -- and the lease mounts one as a
    # plain bind. What it cannot do is be *reviewed*, which is what the rest
    # of this registry is for, so it is admitted only where the mount is the
    # point and refused where somebody meant to track commits it has none of.
    if not repository and not mount:
        typer.echo(
            f"Not a git repository: {resolved}\n"
            "Pass --mount to register it for access alone; tracking a project "
            "means reading its commits, and there are none to read here."
        )
        raise typer.Exit(1)

    local_data = load_json(local_file())
    local_projects = local_data.get("projects", [])

    entry = next((p for p in local_projects if p["name"] == name), None)
    if entry:
        entry["path"] = str(resolved)
    else:
        entry = ProjectEntry(name=name, path=str(resolved))
        local_projects.append(entry)
        local_data["projects"] = local_projects

    if branch:
        entry["branch"] = branch

    if mount:
        entry["mount"] = "rw" if mount == "rw" else "ro"

    head = current_head(str(resolved)) if synced else ""
    if synced:
        entry["last_synced_commit"] = head

    save_local(local_data)
    ensure_ref_symlink(name, str(resolved))
    typer.echo(f"Set '{name}' local path to {resolved}")
    if branch:
        typer.echo(f"  Tracking branch: {branch}")
    if mount:
        typer.echo(
            f"  Reachable from a session {'read-write' if mount == 'rw' else 'read-only'}"
            " — takes effect at the next launch, which is when mounts are built"
        )
    if synced:
        typer.echo(f"  Marked as synced at {short_sha(head)}")
