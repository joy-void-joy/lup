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
fetched into a local clone before comparison (see ``ensure_local``):
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
A project with a URL and no local path is materialized under
``~/.cache/lup/sync/`` in the layout a registration naming a local path
already points at -- a bare repository with a worktree attached to it -- so a
session opens either one on the same terms and can branch, commit and push in
it. Nothing a review does moves a local branch: the upstream's commits are
read from a remote-tracking ref, and refreshing one of these clones is a
fetch and nothing else.

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
from pydantic import BaseModel, ConfigDict, TypeAdapter, with_config

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
    """Where a registration carrying only a URL is materialized on this machine.

    Beside the rest of lup's per-user cache rather than under the project
    root, and the placement is load-bearing rather than tidy. A clone inside
    the checkout is inside the session's own writable mount, so
    :func:`~lup.sandbox.rail.fleet_lease` drops it as already covered and a
    registration asking for ``ro`` silently gets ``rw`` -- the one mode the
    key exists to be able to say. It is also re-cloned once per worktree,
    where a full history is worth having once per machine, and the ``refs/``
    symlinks ``worktree create`` copies into a new checkout point back into
    the cache of the one it was cut from.
    """
    return Path.home() / ".cache" / "lup" / "sync"


def legacy_cache_dir() -> Path:
    """Where clones used to land, still read so nothing quietly abandons one.

    A clone under the project root was writable with the checkout, so a
    session could commit in one and some did. Moving the cache would leave
    that work in a directory nothing looks at again, which is the failure
    this whole change is about -- so the old location is still resolved, and
    a project found there is used where it stands rather than re-cloned
    beside it.
    """
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


class Upstream(BaseModel, frozen=True):
    """A registration located on disk, and the ref its commits are read from.

    Two fields because the second stopped being ``HEAD`` for everything. A
    registration naming a local path is somebody's own checkout and its HEAD
    is what they have. A clone this module made is a checkout somebody may be
    *working in*, whose HEAD is theirs rather than the upstream's -- so the
    review reads the remote-tracking ref there, which a fetch moves and
    nothing local does. That is what lets the refresh be a fetch and nothing
    else: the hard reset that used to keep a review current is the same reset
    that took a session's work with it.
    """

    checkout: Path
    """Where git runs: the attached worktree, or the bare half while there is none."""

    tip: str = "HEAD"
    """The ref whose commits are the upstream's, resolved in that checkout."""


def bare_path(name: str) -> Path:
    """Where this project's own bare repository sits inside the cache.

    Spelled ``<name>.git`` with a ``tree/`` of worktrees inside it, which is
    the layout ``dev worktree`` already assumes and ``get_tree_dir`` already
    finds — so a session opening one of these clones cuts a worktree in it
    with the same command it uses at home.
    """
    return cache_dir() / f"{name}.git"


def cached_clone(name: str) -> Path | None:
    """This project's clone in the cache, wherever this machine put it."""
    return next(
        (
            candidate
            for candidate in (bare_path(name), legacy_cache_dir() / name)
            if candidate.is_dir()
        ),
        None,
    )


def bare_repository(path: Path) -> bool:
    """Whether git calls this directory a bare repository, which has no tree.

    A directory git does not answer for is not one: a corpus or a set of
    reference material is registered for access alone, the lease binds it
    plainly, and asking it for a worktree would be asking git about a place
    git knows nothing of.
    """
    return (
        git.out("-C", str(path), "rev-parse", "--is-bare-repository", _ok_code=[0, 128])
        == "true"
    )


def clone_branch(proj: ProjectEntry, repository: Path) -> str:
    """The branch a clone tracks: the registered one, or the clone's own HEAD.

    Empty where HEAD names no branch, which a detached checkout is and a
    review still has to answer for — the caller falls back to the remote's
    own default rather than failing over a state nobody asked about.
    """
    return proj.get("branch", "") or git.out(
        "-C", str(repository), "symbolic-ref", "--short", "HEAD", _ok_code=[0, 1]
    )


def clone_upstream(proj: ProjectEntry, repository: Path) -> Upstream:
    """One cached clone read as an upstream, whichever layout it is in.

    The bare layout keeps its working tree at ``tree/<branch>``; a clone made
    before this module cloned bare *is* its own working tree. Both are
    reviewed against a remote-tracking ref, which is the whole reason neither
    has to be reset — and the bare half answers for itself until a worktree
    is attached, because ``rev-list`` and ``show`` read a repository rather
    than a checkout.
    """
    branch = clone_branch(proj, repository)
    attached = repository / "tree" / branch
    return Upstream(
        checkout=attached if branch and attached.is_dir() else repository,
        tip=f"refs/remotes/origin/{branch}" if branch else "refs/remotes/origin/HEAD",
    )


def existing_upstream(proj: ProjectEntry) -> Upstream | None:
    """Where this registration already is, WITHOUT cloning or fetching.

    Read-only counterpart to :func:`ensure_local` — for status reporting that
    must never mutate the working tree or hit the network.
    """
    path = proj.get("path", "")
    if path and Path(path).exists():
        return Upstream(checkout=Path(path))
    repository = cached_clone(proj["name"])
    return None if repository is None else clone_upstream(proj, repository)


def openable(
    proj: ProjectEntry, found: Upstream, report: Callable[[str], None]
) -> Path:
    """The working tree a session opens for this registration.

    Separate from :func:`existing_upstream` so that locating a clone stays a
    question and opening one stays a claim: this is allowed to cut a worktree
    where a bare clone has none, and ``status`` must never do that.
    """
    if not bare_repository(found.checkout):
        return found.checkout
    branch = clone_branch(proj, found.checkout)
    if not branch:
        report(
            f"The clone at {found.checkout} has no branch checked out and "
            f"'{proj['name']}' names none, so there is no worktree to open"
        )
        raise typer.Exit(1)
    return attach_worktree(found.checkout, branch, report)


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
    :func:`ensure_local` also fetches, and opening a session is not a review.

    What is mounted is always a working tree, never the bare half of a clone.
    `lease_for` reads a bare directory as a repository whose every worktree
    belongs to somebody else and holds all of them read-only, so a session
    handed one would get a checkout it cannot work in and siblings it cannot
    write -- a boundary nobody declared rather than the mode the registration
    named. So a clone found without one has a worktree attached here, which
    costs no network and is the one write locating a project may do.

    A registration that asked for a mount and cannot be located is reported
    and skipped -- whether it named neither a path nor a URL, or its
    materialization failed. That is a note somebody did not finish, in a
    gitignored file, or a forge that did not answer; failing a launch over
    one would turn either into a session that will not open.
    """

    def located(project: ProjectEntry) -> AccessibleRoot | None:
        """Where one registration is on disk, materializing it if it is not."""
        if "mount" not in project:
            return None
        found = existing_upstream(project)
        try:
            if found is None:
                found = ensure_local(project, report)
            opened = openable(project, found, report)
        except typer.Exit:
            report(
                f"'{project['name']}' could not be materialized, so it stays out of reach"
            )
            return None
        return AccessibleRoot(path=opened.resolve(), writable=project["mount"] == "rw")

    return [
        root for project in load_projects() if (root := located(project)) is not None
    ]


def clone_bare(url: str, repository: Path, report: Callable[[str], None]) -> None:
    """Clone a URL as the bare half of the layout, with its whole history.

    Whole rather than the ``--depth=200`` this used to take, and that flag is
    the reason a URL registration was never as good as a path one. A shallow
    clone is a review window that quietly ends — a checkpoint older than the
    window computes no range at all — and it is single-branch besides, so
    every branch but one is missing and none can be cut a worktree from. A
    session working in one cannot rebase past the graft or push a branch that
    reaches behind it. The depth bought a faster first launch, once, for a
    clone that is now made once per machine rather than once per worktree.

    ``--bare`` writes no ``remote.origin.fetch``, so the standard refspec is
    configured immediately afterwards. Without it every later fetch writes
    ``FETCH_HEAD`` alone: ``refs/remotes`` stays empty, and the ref the
    review reads never appears — a silence shaped exactly like an upstream
    with nothing new.
    """
    report(f"Cloning {url} into {repository}...")
    repository.parent.mkdir(parents=True, exist_ok=True)
    try:
        git("clone", "--bare", url, str(repository))
        git(
            "-C",
            str(repository),
            "config",
            "remote.origin.fetch",
            "+refs/heads/*:refs/remotes/origin/*",
        )
        git("-C", str(repository), "fetch", "--quiet", "origin")
    except sh.ErrorReturnCode as error:
        report(f"Clone failed: {decode_stderr(error)}")
        raise typer.Exit(1)


def refresh(name: str, repository: Path, report: Callable[[str], None]) -> None:
    """Bring this clone's remote-tracking refs level, moving nothing local.

    The whole refresh, where it used to be a fetch followed by a hard reset
    onto the upstream. The reset was there because the review read ``HEAD``,
    and it is what made a cached clone impossible to work in: a session's
    uncommitted files went with it and said nothing. Reading the review off
    the remote-tracking ref removes the reason for it rather than guarding
    it, so there is no case left in which this destroys anything.

    The refspec is named for the same reason :func:`clone_bare` configures
    one, and naming it here as well covers a clone made before that line
    existed.
    """
    report(f"Fetching latest for '{name}' from {repository}...")
    try:
        for remote in git.lines("-C", str(repository), "remote"):
            git(
                "-C",
                str(repository),
                "fetch",
                "--prune",
                "--quiet",
                remote,
                f"+refs/heads/*:refs/remotes/{remote}/*",
            )
    except sh.ErrorReturnCode as error:
        report(f"Warning: fetch failed: {decode_stderr(error)}")


def attach_worktree(
    repository: Path, branch: str, report: Callable[[str], None]
) -> Path:
    """The worktree this clone is worked in, cut where there is not one yet.

    A bare repository has no working tree, and a review reads files as well
    as commits — so the clone is only half made until one is attached. Cut at
    ``tree/<branch>`` rather than anywhere else because that is where
    ``get_tree_dir`` looks, which is what lets a session inside the clone
    reach for ``dev worktree create`` and have the next one land beside this.

    ``worktree prune`` first, because a directory somebody removed leaves its
    administrative entry behind and ``worktree add`` refuses the path while
    one stands.
    """
    checkout = repository / "tree" / branch
    if checkout.is_dir():
        return checkout
    report(f"Attaching a worktree for '{branch}' at {checkout}...")
    try:
        git("-C", str(repository), "worktree", "prune")
        git("-C", str(repository), "worktree", "add", str(checkout), branch)
    except sh.ErrorReturnCode as error:
        report(f"Could not attach a worktree for '{branch}': {decode_stderr(error)}")
        raise typer.Exit(1)
    return checkout


def registered_elsewhere(repository: Path, url: str) -> str:
    """The origin this clone actually points at, when it is not the declared one.

    The cache is per user and keyed by the registered name, so two projects
    on this machine registering different repositories under one name would
    otherwise share a clone — and the second would review, mount and commit
    into the first one's history under its own name. Empty where they agree,
    or where either side has nothing to compare.
    """
    if not url:
        return ""
    found = git.out(
        "-C", str(repository), "remote", "get-url", "origin", _ok_code=[0, 1]
    )
    return "" if not found or found == url else found


def ensure_local(
    proj: ProjectEntry,
    report: Callable[[str], None] = typer.echo,
) -> Upstream:
    """Materialize an upstream so its commits can be read, and locate it.

    Reviewing upstream commits (``log``/``diff``) means reading the upstream's
    actual git history, which only exists locally — so before any such command
    can run, the project must be present and current on disk. This is that
    guarantee: it clones a project that has only a URL, fetches one already
    cached so the review sees the latest commits rather than a stale snapshot,
    and leaves a user-provided local path as-is. In every case it (re)points
    ``refs/<name>`` at the result and hands back where the caller runs git.
    ``status`` deliberately does *not* call this (it uses
    :func:`existing_upstream` instead) so a status check never clones,
    fetches, or writes.

    What a clone gets is the layout a path registration already points at: a
    bare repository with a worktree attached, holding every branch and the
    whole history. The point is that the two stop differing — a session can
    open either one, cut a branch in it, commit, and push, and a later review
    of the same project neither notices nor disturbs any of that.

    Progress and error text goes through ``report`` so callers rendering
    tables can defer the messages instead of interleaving them mid-table.
    """
    path = proj.get("path", "")
    name = proj["name"]
    if path and Path(path).exists():
        ensure_ref_symlink(name, path)
        return Upstream(checkout=Path(path))

    url = proj.get("url", "")
    repository = cached_clone(name)
    if repository is None:
        if not url:
            report(
                f"Project '{name}' has no local path or URL configured.\n"
                "Either:\n"
                "  1. Add a URL for it in sync.json.local\n"
                f"  2. Run: uv run lup-devtools sync setup {name} /path/to/repo"
            )
            raise typer.Exit(1)
        repository = bare_path(name)
        clone_bare(url, repository, report)
    else:
        pointing = registered_elsewhere(repository, url)
        if pointing:
            report(
                f"The clone at {repository} points at {pointing}, and '{name}' "
                f"is registered as {url}. Two projects on this machine are "
                "registering different repositories under one name; rename one "
                "registration, or remove that directory to re-clone."
            )
            raise typer.Exit(1)
        refresh(name, repository, report)

    branch = clone_branch(proj, repository)
    if branch and bare_repository(repository):
        attach_worktree(repository, branch, report)
    found = clone_upstream(proj, repository)
    ensure_ref_symlink(name, str(found.checkout))
    return found


def git_in(path: str, *args: str) -> str:
    """Run git command in a specific directory."""
    return git.out("-C", path, *args)


def commit_count(path: str, since: str, tip: str = "HEAD") -> int:
    """Count the commits on ``tip`` a checkpoint has not reached."""
    return int(
        git_in(path, "rev-list", "--count", tip if not since else f"{since}..{tip}")
    )


def current_head(path: str) -> str:
    """Get current HEAD sha."""
    return git_in(path, "rev-parse", "HEAD")


def resolved_checkpoint(path: str, ref: str, tip: str = "HEAD") -> str:
    """The commit a checkpoint should record, from a ref or from the tip.

    Resolution happens in the upstream checkout rather than being taken on
    trust, so a tag or branch name works and a commit that checkout does not
    have is refused here — where the caller can still fix it — instead of
    landing in the record as a checkpoint nothing can compute a range from.

    ``tip`` is the ref the review was read from, which is the one a finished
    review means. Defaulting it to ``HEAD`` would record what a clone happens
    to be checked out on — somebody's own branch, in a clone this project's
    sessions work in — as the point every upstream commit up to it was
    considered.
    """
    if not ref:
        return git_in(path, "rev-parse", tip)
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

        resolved = existing_upstream(p)
        if resolved is None:
            has_url = bool(p.get("url"))
            note = "not cloned (run: sync fetch)" if has_url else "no path/url"
            return [p["name"], "—", synced_short, reach(p), note]

        try:
            behind: int | str = commit_count(
                str(resolved.checkout), synced, resolved.tip
            )
        except (sh.ErrorReturnCode, ValueError):
            behind = "?"
        branch = p.get("branch", "")
        source = f"{resolved.checkout}" + (f" ({branch})" if branch else "")
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
    """Clone missing repos and fetch cached ones (network + writes).

    A fetch and nothing else: no branch a session may be working on is moved,
    and no working tree is reset. What keeps the review current is that it
    reads the remote-tracking ref this refreshes.
    """
    projects = load_projects()
    targets = (
        [find_project(project)]
        if project
        else [p for p in projects if not p.get("ignore")]
    )
    for p in targets:
        try:
            resolved = ensure_local(p)
            typer.echo(f"{p['name']}: ready at {resolved.checkout}")
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
    first so the list reflects where it now stands.
    """
    proj = find_project(project)
    found = ensure_local(proj)

    synced = proj.get("last_synced_commit", "")
    range_spec = f"{synced}..{found.tip}" if synced else found.tip

    args = ["log", "--oneline"]
    if stat:
        args.append("--stat")
    args.append(range_spec)

    output = git_in(str(found.checkout), *args)
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
    found = ensure_local(proj)
    output = git_in(str(found.checkout), "show", commit)
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
    """Advance the sync checkpoint to where the upstream now stands.

    Run once a review is finished: it records that every commit up to the
    upstream's tip has been considered, so the next ``sync log`` / ``status``
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
    found = ensure_local(proj)

    head = resolved_checkpoint(str(found.checkout), at, found.tip)

    local_data = load_json(local_file())
    local_projects = local_data.get("projects", [])

    entry = next((p for p in local_projects if p["name"] == project), None)
    if entry:
        entry["last_synced_commit"] = head
    else:
        # The checkpoint alone, where this used to record the path beside it.
        # A registration that named only a URL is materialized in the cache,
        # and writing that location back as its `path` turns it into a
        # registration naming a local checkout -- one whose commits are then
        # read from whatever branch a session left it on rather than from the
        # upstream. Nothing needs the path recorded: it is derived from the
        # name every time it is wanted.
        local_projects.append({"name": project, "last_synced_commit": head})
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
