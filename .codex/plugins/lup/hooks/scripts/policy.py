#!/usr/bin/env python3
# Generated from lup.policy.assets.host and lup.adapters.codex.assets.policy_dispatcher by `uv run lup-devtools harness generate all` — edit the source, not this file.
# See docs/harness.md.

"""Codex hook dispatcher over the canonical semantic kernel.

Runs as a bare script beside its own runtime directory, reaching only
the standard library and the kernel copied beside it.
"""

import json
import os
import sys
from pathlib import Path

# The hook is launched as a bare script, promised no cwd, PYTHONPATH, or
# interpreter environment, and `runtime/` is a plain sibling directory holding
# the kernel package and this plugin's policy data rather than an installed
# distribution. Naming it as a search path is what lets the imports below
# resolve, for the interpreter and for a type checker alike.
sys.path.insert(0, str(Path(__file__).parents[1] / "runtime"))
from codex_patch import patched_files
from kernel.decision import KernelDecision, SANDBOX_TRAPPED_REASON
from kernel.shell import auto_escape_matches
from policy_data import AUTO_ESCAPE_PREFIXES
from policy_data import AGENT_IDENTITY_ENV, AUTONOMOUS_AGENT_IDENTITIES
from datetime import UTC, datetime

# lup: ignore[subprocess] — `sh` is third-party and this half is compiled into a bare script that has no virtual environment to resolve it from
import subprocess
from kernel.edit import (
    awaits_resolution,
    decide_edit,
    relocated_edit_text,
    relocated_suppressions,
)
from kernel.fetch import decide_fetch
from kernel.lex import (
    python_script_targets,
    shell_path_verb_targets,
    shell_write_targets,
)
from kernel.words import INTERPRETERS
from kernel.shell import decide_shell
from kernel.tools import decide_tool
from policy_data import (
    ACCEPTANCE_GUARD,
    ALLOWANCE_GRANTS_ENV,
    ALLOWED_FETCH_SCOPES,
    ANTI_PATTERN_ROWS,
    RESOLUTION_COMMAND,
    DENIED_FETCH_SCOPES,
    KNOWN_ALLOWANCES,
    MAXIMUM_ADDED_LINES,
    PATH_ROLES,
    PATH_RULES,
    RECOVERABLE_TARGET_LIMIT,
    REFUSED_TOOLS,
    RUNNER_TARGET_TABLES,
    RUNNER_TARGETS,
    SANDBOX_EXCLUDED_COMMANDS,
    SHELL_RULES,
)


def sandbox_active() -> bool:
    """Whether the launcher confined this session to an OS sandbox."""
    environ = os.environ  # lup: ignore[os-environ]
    return "LUP_SANDBOX_ACTIVE" in environ and environ["LUP_SANDBOX_ACTIVE"] == "1"


def script_run_nudge(
    scripts: list[str],
    root: Path | None,
    after: int = 5,
    every: int = 10,
    ledger: str = ".lup/script-runs.json",
) -> str:
    """Count each script's runs and say when one has stopped being a one-off.

    The ladder allows a scratch script because computing something once does
    not earn a command. Nothing in that argument survives the fifth run: by
    then the thing is a tool, and a tool nobody can invoke by name is one the
    next session rewrites from scratch. This is what notices, because the
    agent doing the rewriting has no memory of the previous four.

    Advice rather than a gate. It rides along with a verdict that already
    allowed the command, so a genuine repeat is a sentence to read and not a
    wall -- the only form this can take without punishing the case it exists
    to improve.

    Said once at ``after`` and then only every ``every`` runs, because the
    two ways to get this wrong are opposite and both fatal to it. On every
    run it becomes noise attached to a command that worked, which is read
    once and skipped forever after. Once and never again, and a session that
    was mid-thought when it arrived never hears it a second time, however
    many more times it runs the thing.

    A ledger that cannot be read or written yields no nudge. A counter is not
    worth failing a command over, and a read-only checkout is an ordinary
    place to be running.
    """
    if root is None or not scripts:
        return ""
    path = root / ledger
    # An unreadable ledger and an unparseable one are different failures. The
    # first is a checkout this process cannot read, where the honest answer is
    # to say nothing. The second is a file whose contents are not a tally, and
    # treating that as fatal would disable the nudge permanently -- the file
    # never gets rewritten, so every later run reads the same wreckage. Start
    # the count over instead.
    try:
        raw = path.read_text() if path.exists() else ""
    except OSError:
        return ""
    try:
        loaded = json.loads(raw) if raw else None
    except ValueError:
        loaded = None
    try:
        counts = loaded if isinstance(loaded, dict) else {}
        seen = {
            script: (
                counts[script]
                if script in counts and isinstance(counts[script], int)
                else 0
            )
            for script in dict.fromkeys(scripts)
        }
        bumped = {
            script: before + scripts.count(script) for script, before in seen.items()
        }
        # A nudge point is `after`, then every `every` runs past it. This run
        # earns a nudge when it carried the count across one of them.
        earned = [
            script
            for script, total in bumped.items()
            if any(
                seen[script] < point <= total
                for point in range(after, total + 1, every)
            )
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**counts, **bumped}, indent=2, sort_keys=True))
    except OSError:
        return ""
    if not earned:
        return ""
    counted = ", ".join(f"{script} ({bumped[script]}x)" for script in earned)
    return (
        f" — {counted}: more than a one-off by now, so consider making it a"
        " `lup-devtools` command, which lands in the diff and can be run"
        " again by name"
    )


def contained() -> bool:
    """Whether this session is running inside the project's container.

    A different question from :func:`sandbox_active`, and the two are not
    interchangeable: the native sandbox confines one call at a time and can
    be told to leave some alone, where a container confines the process and
    was never asked. Read from the image's own baked-in variable rather than
    from anything a launch passes, so a session cannot be told it is
    contained by something standing outside the container.
    """
    environ = os.environ  # lup: ignore[os-environ]
    return "LUP_CONTAINED" in environ and environ["LUP_CONTAINED"] == "1"


def managed_script_roots(root: Path | None) -> list[str]:
    """Name the package roots a runtime installed and therefore trusts.

    The workspace-local plugin directory is deliberately not a root: it is
    agent-adjacent and verified only at launch, so an approved write there
    must not grant silent execution rights for the rest of the session.
    """
    if root is None or not root.is_absolute():
        return []
    return [str(root / "skills"), str(root / "plugins" / "cache")]


def worktree_path(path_text: str) -> str:
    """Relativize against the worktree holding the path, not the cwd.

    Every repo-relative rule — human-owned files, protected directories, the
    role a path carries — matches on this answer, so anchoring it anywhere
    but the file's own worktree decides policy by where the runtime happened
    to be launched. A sibling worktree is writable and is not under the
    launch directory; the cwd this script is promised nothing about is not a
    root at all. Both leave the path absolute, and every rule silently misses.
    """
    root = worktree_root(path_text)
    if not root:
        return path_text
    return Path(path_text).resolve().relative_to(root).as_posix()


def worktree_root(path_text: str) -> str:
    """The checkout a path belongs to, or "" when it belongs to none.

    The same walk :func:`worktree_path` relativizes against, kept whole
    rather than discarded, because the root is the answer to a second
    question: a language server asked about this file resolves its imports
    against exactly this directory, and resolving them against wherever the
    session was launched reads the same module names out of another tree.
    """
    path = Path(path_text)
    if not path.is_absolute():
        return ""
    resolved = path.resolve()
    # The path itself is a candidate, not only its parents: a file never
    # holds a `.git`, so nothing changes for one, and a directory that is
    # already a checkout root would otherwise be answered for by whatever
    # encloses it — or by nothing at all.
    for root in [resolved, *resolved.parents]:
        if (root / ".git").exists():
            return str(root)
    return ""


def shared_git_directory(path_text: str) -> str:
    """The one directory every worktree of a repository can name alike.

    The publisher sits in whichever checkout was edited and the reader in
    whichever one its server was launched from, and neither can see the
    other's. What they share is git's own directory: a linked worktree's
    ``.git`` is a file naming its per-worktree directory beneath the common
    one, and a main checkout's ``.git`` is that common directory. So both
    ends resolve to one place without either being told where the other is,
    and without depending on a variable reaching a hook and a server alike.

    The common directory rather than the main checkout, because a checkout
    is not guaranteed to be there: a repository can keep its git directory
    beside its worktrees rather than inside one, and then the path above
    `worktrees/` is not a checkout at all — it is whatever happens to
    enclose the repository, which is nobody's to write into.
    """
    root = worktree_root(path_text)
    if not root:
        return ""
    marker = Path(root) / ".git"
    if marker.is_dir():
        return str(marker)
    try:
        named = marker.read_text(encoding="utf-8")
    except OSError:
        return ""
    gitdir = named.removeprefix("gitdir:").strip()
    if not gitdir:
        return ""
    # `<common>/worktrees/<name>` — two levels up in either layout.
    linked = Path(gitdir)
    if len(linked.parents) < 2:
        return ""
    return str(linked.parents[1])


def boundary_description(
    root: Path | None, ledger: str = ".lup/boundary.json"
) -> dict[str, list[str]]:
    """What the launcher recorded about the boundary this session runs behind.

    The mount table and the egress allowlist are *launch* facts, not
    generation facts: which worktrees exist and which of them this session
    leased is decided when the container starts, long after this dispatcher
    was compiled. So the launcher writes them down and this reads them back,
    the same shape the run ledger already uses.

    An absent file is the ordinary answer rather than a failure: an
    uncontained session has no boundary to describe, and one whose launcher
    predates this has none recorded. Both mean the same thing to every caller
    -- there is nothing here to attribute a failure to -- so both come back
    empty.
    """
    if root is None:
        return {}
    try:
        raw = (root / ledger).read_text()
    except OSError:
        return {}
    try:
        loaded = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {
        name: [item for item in value if isinstance(item, str)]
        for name, value in loaded.items()
        if isinstance(name, str) and isinstance(value, list)
    }


def unquoted_path(word: str) -> str:
    """One word of a diagnostic, with the punctuation it was quoted in removed.

    An error message is prose with a path in it, and prose has no parser --
    which is why this trims rather than parses. Kept as its own function so
    that reasoning sits beside the one line it excuses.
    """
    # lup: ignore[string-strip] — the quotes a diagnostic wraps a path in are
    # exactly what has to come off, and no parser reads free-form prose
    return word.strip("'\"`:,;()[]<>")


def boundary_refusal(failure: str, described: dict[str, list[str]]) -> str:
    """Name the boundary as the cause of a failure, or say nothing at all.

    A confined command that fails fails in the vocabulary of whatever it was
    doing. A write the mount table refused arrives as ``Read-only file
    system`` and a host the proxy refused arrives as a timeout, and neither
    says "you are confined" -- so an agent reading them debugs the filesystem
    or the network library, for as long as it takes somebody to notice.

    The discipline that makes this worth having is the refusal to guess. A
    marker in the text never suffices on its own, because ``Read-only file
    system`` appears for a genuinely read-only disk too; the claim is made
    only where a *declared* read-only mount covers the path the failure named.
    Everything else says nothing, and silence is the right answer here far
    more often than a claim is. A wrong boundary claim is worse than none: it
    teaches an agent to reach for the host when the bug was in its own code,
    and that lesson outlives the one command it was wrong about.

    The same reading as :mod:`lup.sandbox.attribution`, in the pinned standard
    library, because this one runs inside the compiled dispatcher where that
    module cannot be imported. What it deliberately does not repeat is the
    egress half: a refused host is read out of the proxy's own log rather than
    out of the client's guess about why its connection died, and reaching that
    log means reaching the container runtime, which this half must not do.
    """
    markers = described["write_refusals"] if "write_refusals" in described else []
    read_only = described["read_only"] if "read_only" in described else []
    if not markers or not read_only:
        return ""
    if not any(marker in failure for marker in markers):
        return ""
    covering = [
        mount
        for word in failure.split()
        for candidate in [unquoted_path(word)]
        if candidate.startswith("/") and len(candidate) > 1
        for mount in read_only
        if candidate == mount or candidate.startswith(mount + "/")
    ]
    if not covering:
        return ""
    return (
        f"The boundary refused this, not the filesystem: {covering[0]} is "
        "mounted read-only on purpose, so retrying, changing permissions or "
        "creating the parent will not help. Work inside your own tree, or "
        "propose adding the path to the image declaration if it genuinely "
        "belongs in every session."
    )


def foreign_repository(path_text: str, root: Path | None) -> bool:
    """Whether this path belongs to a repository other than the session's.

    The discriminator is the *repository*, never the checkout. A sibling
    worktree of this repository is still this repository's code and still
    answers to its conventions, so comparing checkout roots would lift every
    rule the moment work moved one directory sideways -- which is most of how
    this project is worked on. :func:`shared_git_directory` is the answer both
    ends can name alike, whichever worktree either of them is sitting in.

    Undecidable answers say no. A path in no repository, a session in no
    repository, and an unreadable ``.git`` all leave one side blank, and the
    honest reading of "cannot tell" is that this project's rules still apply:
    lifting them on a guess would silence the gates on this repository's own
    files, where keeping them costs friction somewhere that is not ours.
    """
    if root is None:
        return False
    here = shared_git_directory(str(root))
    there = shared_git_directory(path_text)
    return bool(here) and bool(there) and here != there


def publish_edition(path_text: str) -> None:
    """Say which checkout an edit landed in, for the servers that would guess.

    A language server and the code-intelligence tools are started once and
    hold the directory the session opened in for the rest of their lives.
    Editing moves — this project asks that it move, into a worktree — and
    nothing about that reaches them, so they answer about the launch tree
    with no sign that they have. The edited file is the one thing that knows
    where editing is happening, and this is the only place that sees it.

    Written after the tool ran, never before: the same call from the
    permission path would put a filesystem failure between an edit and its
    verdict, and this must not be able to decide anything. For the same
    reason an unwritable destination is reported and dropped — a session
    whose diagnostics stay rooted where they were is worth strictly more
    than one that stopped editing over it.

    The rename is the whole guarantee, and the temporary is dot-prefixed, for
    the reasons ``lup.channels.models.write_atomic`` gives. This cannot call
    that one: it is compiled into a bare script with no ``lup`` to import.
    """
    root = worktree_root(path_text)
    shared = shared_git_directory(path_text)
    if not root or not shared:
        return
    destination = Path(shared) / "lup" / "edition.json"
    record = json.dumps(
        {"workspace": root, "file": str(Path(path_text).resolve())}, indent=2
    )
    temporary_path = destination.with_name(f".{destination.name}.tmp")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(record + "\n", encoding="utf-8")
        temporary_path.replace(destination)
    except OSError as error:
        print(f"lup: could not publish the edition: {error}", file=sys.stderr)


def project_environment(
    root: Path,
    variable: str = "UV_PROJECT_ENVIRONMENT",
    default: str = ".venv",
) -> Path:
    """Where a sync puts *root*'s environment.

    ``.venv`` beside the manifest is `uv`'s default and this project's own
    layout, but it is a default rather than the answer: *variable* redirects
    it, which is how one environment gets shared across worktrees, kept off a
    slow filesystem, or placed where a container expects it. A relative value
    resolves against the project, the way `uv` resolves it, rather than
    against whatever directory a command happened to run in.

    Lives in this half because this is the constrained one: the hook is
    compiled to a bare script that may import nothing but the standard
    library, so logic it needs cannot sit anywhere it would have to import
    from. Everything else reads it from here, which is what keeps one answer
    rather than two that agree until they do not.

    Both names arrive as defaults rather than as module constants because the
    compiler that splices this half into each hook carries functions alone —
    a name declared beside one would be left behind, and the script would
    reference it undefined.
    """
    environ = os.environ  # lup: ignore[os-environ] — uv's own configuration
    declared = (environ[variable] if variable in environ else "").strip()
    if not declared:
        return root / default
    return Path(declared) if Path(declared).is_absolute() else root / declared


def declared_program(root: str, declared: str) -> str:
    """Where a declared program is, or "" when it is not there to run.

    The checkout answers first, whatever the spelling. That is what makes the
    verdict the edited tree's rather than whichever environment the session
    was launched from, and it is the property worth keeping — a sibling
    worktree holds the same relative path with different contents.

    Only where the checkout holds nothing does the spelling decide. A bare
    name goes to the OS to find on ``PATH``, for a project whose toolchain
    lives somewhere else entirely: a conda environment, a pyenv shim, a
    system or user-level install, an environment ``UV_PROJECT_ENVIRONMENT``
    put outside the project. A path that resolved to nothing stays nothing,
    because a project that named a location meant that location.

    Accepting only the first is what made this gate unavailable rather than
    configurable. A declared program it could not resolve produced no
    diagnostics and said nothing about why, so a project outside one layout
    did not get a weaker check — it got silence indistinguishable from a
    clean file, on every edit.

    A bare name is asked of the checkout's own environment before ``PATH``,
    because that is where a project's toolchain is installed and asking is
    what keeps the declaration from naming a layout. Spelling the path in
    would answer only for the layout it spelled: ``.venv`` is `uv`'s default
    and nothing else's, so a project that redirected it, or that installs
    through conda or pyenv, resolved to nothing and was gated in silence.
    The scripts directory comes from the running interpreter — ``bin`` on
    POSIX, ``Scripts`` on Windows — because that is a property of how Python
    is installed rather than of any project, and reading it is what keeps
    this from being a second layout assumption behind the one it replaces.
    """
    located = Path(root) / declared
    if located.is_file():
        return str(located)
    if "/" in declared or "\\" in declared:
        return ""
    installed = (
        project_environment(Path(root)) / Path(sys.executable).parent.name / declared
    )
    return str(installed) if installed.is_file() else declared


def conflicted(path_text: str) -> bool:
    """Whether a file is holding a merge open, and so is not source yet.

    Both markers, at the start of a line. A lone `<<<<<<<` is reachable in
    honest text — a diff quoted in a docstring, a fixture about conflicts, this
    very sentence — and answering yes to one would silence the checker for a
    file nothing is wrong with. A conflict always writes the pair, so requiring
    both costs nothing it was meant to catch.

    Unreadable is not conflicted. Whatever the reason, the checker is about to
    meet the same file and is the one that should say so.
    """
    try:
        lines = (
            Path(path_text).read_text(encoding="utf-8", errors="replace").splitlines()
        )
    except OSError:
        return False
    return any(line.startswith("<<<<<<<") for line in lines) and any(
        line.startswith(">>>>>>>") for line in lines
    )


def file_diagnostics(
    path_text: str,
    command: list[str],
    suffixes: tuple[str, ...] = (".py", ".pyi"),
    timeout_seconds: float = 20.0,
) -> list[str]:
    """Type-check one edited file, in the checkout that actually holds it.

    A language server the runtime starts is rooted once, where the session
    opened, and goes on resolving imports there after work moves to another
    checkout — same module names, different source, diagnostics about a file
    nobody edited. Running the checker per edit has no root to go stale:
    the file names its own checkout, and that is where the check runs.

    The checkout alone does not decide it. A checker finds the interpreter
    whose packages it resolves against by looking down ``PATH``, and a hook
    inherits whichever one the session was launched with, so a check running
    in one tree reads another tree's installed packages and calls every
    third-party import unresolvable. The checker's own directory goes first:
    that is the environment it was installed into, and therefore the one
    belonging to the checkout that holds the file. A checker the checkout
    does not hold has no such directory to prefer, and keeps the ``PATH`` it
    inherited — that is where the OS is about to find it.

    Reported for the edited file alone. The checker resolves whatever the
    file imports, so it can have opinions about the whole tree, and a hook
    that repeated them would answer every edit with the same backlog.

    Anything that goes wrong is no diagnostics. A checker that is missing, or
    slow, or writes something this cannot read, is not evidence about the
    edit — and this runs after the tool, so the alternative to saying
    nothing is failing an edit that already happened.

    *suffixes* is what the checker can read. A type checker handed a manifest,
    a document, or a lockfile parses it as source and reports the whole file
    as broken, so every edit to one answers with a wall of errors about lines
    the edit never touched — which teaches a reader to scroll past the output
    that exists to be read. It is a default rather than a constant because the
    checker is the caller's choice: a project whose checker reads more than
    Python says so instead of editing this.

    A file mid-merge is the same case arriving from the other direction. Its
    conflict markers are not source in any language, so the checker reports the
    file as broken from the first one onward and every line it names is about
    the merge rather than about the edit — during a resolution, which is
    exactly when a reader is editing that file and has the least attention to
    spare for a wall of output that cannot be acted on.
    """
    if not command or Path(path_text).suffix.lower() not in suffixes:
        return []
    if conflicted(path_text):
        return []
    root = worktree_root(path_text)
    if not root:
        return []
    located = declared_program(root, command[0])
    if not located:
        return []
    edited = str(Path(path_text).resolve())
    environ = os.environ  # lup: ignore[os-environ] — the checker inherits this
    inherited = environ["PATH"] if "PATH" in environ else ""
    # Only a checker the checkout holds has an own directory to put first.
    # A bare name is about to be found on the PATH this inherits, so that
    # PATH is already the environment it belongs to.
    searched = (
        f"{Path(located).parent}{os.pathsep}{inherited}"
        if Path(located).is_absolute()
        else inherited
    )
    try:
        finished = subprocess.run(
            [located, *command[1:], edited],
            capture_output=True,
            text=True,
            cwd=root,
            env={**environ, "PATH": searched},
            timeout=timeout_seconds,
            check=False,
        )
        reported = json.loads(finished.stdout)["generalDiagnostics"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return []
    return [
        f"{item['severity']} {item['range']['start']['line'] + 1}: {item['message']}"
        for item in reported
        if item["file"] == edited and item["severity"] != "information"
    ]


def resolved_refutations(
    path_text: str,
    proposed: str,
    command: list[str],
    timeout_seconds: float = 30.0,
) -> dict[str, list[int]] | None:
    """What a checker refutes in the text about to be written, or None.

    The kernel decides from primitive rows and reads nothing, which is what
    keeps a verdict a pure function of its inputs. Resolving a receiver's
    declaration is not a decision — it is a fact about the machine, the same
    kind this half already resolves — so it is answered here and passed in.

    Run in the checkout holding the file, like every other checker this half
    starts, and handed the proposed text on stdin: the change is judged before
    it is written, so the copy on disk is the one being replaced. *path_text*
    still names where the content belongs, because imports and the module's
    own name resolve against it and against nothing else.

    None where no answer was had — no declared resolver, none installed, a
    crash, a timeout, output that will not decode — and it has to stay
    distinct from an empty refutation. Empty means a checker looked and
    refuted nothing, which is evidence; None means nothing looked, which is
    the gate's cue to ask rather than refuse. Collapsing the two would turn
    every unresolvable session into a wall of confident denials.
    """
    if not command:
        return None
    root = worktree_root(path_text)
    if not root:
        return None
    located = declared_program(root, command[0])
    if not located:
        return None
    try:
        finished = subprocess.run(
            [located, *command[1:], "--path", str(Path(path_text).resolve())],
            capture_output=True,
            text=True,
            input=proposed,
            cwd=root,
            timeout=timeout_seconds,
            check=False,
        )
        reported = json.loads(finished.stdout)
        if not reported["resolved"]:
            return None
        return {rule: list(lines) for rule, lines in reported["refuted"].items()}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None


def existing_write_targets(targets: list[str], root: Path | None = None) -> list[str]:
    """Report which of a command's write targets already exist on disk.

    The kernel never reads the filesystem, so it cannot tell creating a file
    from overwriting one. Resolving that here keeps the decision itself a
    pure function of the command text and this list.
    """
    where = Path.cwd() if root is None else root
    return [target for target in targets if (where / target).exists()]


def git_answers(
    arguments: list[str],
    root: Path,
    # lup: ignore[dict-str-payload] — variable names are an open set the caller
    # supplies, not an enumerable one this signature could name
    overrides: dict[str, str] | None = None,
) -> list[str] | None:
    """One Git invocation's lines, or None when Git cannot answer.

    Git missing, the path outside a repository, a malformed pathspec, and a
    non-zero exit all collapse to None, so a caller reading this as evidence
    that something is safe to destroy treats an unanswerable question as a no.

    ``overrides`` are merged over the inherited environment rather than
    replacing it, because a replacement drops ``PATH`` and ``HOME`` and the
    invocation then fails for a reason that has nothing to do with what it
    was asked. The one caller that passes any is the snapshot, which needs
    ``GIT_INDEX_FILE`` pointed somewhere other than the index a human is in
    the middle of composing.
    """
    environ = os.environ  # lup: ignore[os-environ]
    try:
        finished = subprocess.run(
            ["git", *arguments],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env={**environ, **overrides} if overrides else None,
        )
    except OSError:
        return None
    return finished.stdout.splitlines() if finished.returncode == 0 else None


def undo_namespace() -> str:
    """Where snapshots live: a ref namespace of this project's own.

    Under ``refs/`` rather than in a stash so nothing a human does to their
    stash disturbs them, and outside ``refs/heads`` so no branch listing,
    push, or fetch treats them as work anybody meant to publish.

    A function rather than a constant because this half is spliced into the
    compiled dispatcher one function at a time, and a name beside them is
    dropped on the way in — read by the type checker, absent from the script.
    Being a function is also what makes it importable by the command that
    lists snapshots back, so the writer and the reader cannot end up looking
    in two different places for the same safety net.
    """
    return "refs/lup/undo"


def undo_snapshot(
    root: Path | None,
    reason: str,
    session: str = "default",
    namespace: str = "",
) -> str:
    """Write the working tree into the object store before something destroys it.

    The whole argument for relaxing a permission lattice is that a mistake can
    be undone, so this is what has to exist before that relaxation is honest.
    Tracked content *and* untracked files, through a throwaway index rather
    than through ``git stash create``: measured, ``stash create`` captures only
    tracked files that were modified, so the file written thirty seconds ago
    and not yet added -- precisely what ``rm -rf src/`` destroys -- is absent
    from it exactly when it is reached for.

    Ignored files are not captured, and that is a stated limit rather than an
    oversight: on the checkout this was built in, ignored-but-precious content
    came to 592 MB against a 21 MB object store, so capturing it would write
    twenty-eight times the repository's whole history before every mutating
    command. ``git clean -fdx`` therefore keeps asking, because it is the one
    command whose purpose is destroying what this cannot restore, and a
    credential belongs outside the checkout rather than inside one.

    **One ref per distinct state the tree was ever in**, and that is what
    makes taking one before *every* command affordable rather than merely
    cheap. Git addresses content, so a command that changed nothing produces
    a byte-identical tree -- and naming the ref after that tree means writing
    it again simply overwrites the existing one with the newer note. A read
    leaves no new ref at all.

    The alternative was a list of commands worth snapshotting before, and it
    was tried and measured wrong. Keying on whether the classifier waved a
    command through conflates *this destroys work* with *this was not
    recognised*, which are the same verdict and different questions: one
    session produced sixty refs, fifty-seven of them in front of a `grep` or
    a `sed`. Dedup needs no list, cannot miss a command nobody enumerated,
    and leaves a listing somebody can actually read -- which is the whole
    point of recording the reason, since what a reader looks for is the
    snapshot from before the thing that went wrong.

    Silent about its own failure, and deliberately. This runs in front of a
    command somebody asked for; a checkout mid-merge, a locked index, and a
    repository this process cannot write to are all reasons a snapshot cannot
    be taken, and none of them is a reason to stop the command. An empty
    string says no snapshot exists, which is what a caller needs to know and
    all it needs to know.

    In the compiled dispatcher rather than behind ``lup-devtools`` because of
    what it costs. Measured on a 2,634-file checkout of this repository: 81 ms
    for the first snapshot of a session, then a median of 11 ms warm and 14 ms
    with a file changed, against roughly a second of interpreter start for a
    subprocess that would do the same work. A safety net paid for on every
    command has to cost what this costs, or it is the first thing somebody
    turns off -- and the warm figure is the one that matters, because the cold
    index is paid once and reused for the rest of the session.
    """
    if root is None:
        return ""
    directory = git_answers(["rev-parse", "--absolute-git-dir"], root)
    if not directory:
        return ""
    private = {"GIT_INDEX_FILE": f"{directory[0]}/lup-undo-{session}.index"}
    if git_answers(["add", "-A"], root, private) is None:
        return ""
    tree = git_answers(["write-tree"], root, private)
    if not tree:
        return ""
    commit = git_answers(["commit-tree", tree[0], "-m", f"lup undo: {reason}"], root)
    if not commit:
        return ""
    # The name carries both, and needs both. The stamp orders the listing
    # exactly -- git records a commit's date to the second, so two states
    # reached inside one second would otherwise tie, and a tie in a safety
    # net's "newest" is wrong at the worst possible moment. The tree hash is
    # what makes the state findable again: every earlier ref holding this
    # same tree is retired just below, so the listing carries one entry per
    # distinct state rather than one per command.
    held = tree[0][:12]
    where = namespace or undo_namespace()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    for stale in (
        git_answers(["for-each-ref", "--format=%(refname)", where], root) or []
    ):
        if stale.endswith(f"-{held}"):
            git_answers(["update-ref", "-d", stale], root)
    reference = f"{where}/{stamp}-{held}"
    if git_answers(["update-ref", reference, commit[0]], root) is None:
        return ""
    return reference


def recoverable_write_targets(
    targets: list[str], root: Path | None = None
) -> list[str]:
    """Report which targets Git could restore byte for byte after a delete.

    Recoverable means tracked, carrying no uncommitted change, and a regular
    file: the object store then holds exactly what is on disk, so destroying
    it costs a checkout rather than any information.

    A directory is never reported, however clean everything beneath it is.
    One grant would otherwise cover a tree of unbounded size and depth, and
    the point of resolving this per path is that each grant stays the size of
    the thing named.
    """
    where = Path.cwd() if root is None else root
    return [
        target
        for target in targets
        if (where / target).is_file()
        and git_answers(["ls-files", "--error-unmatch", "--", target], where)
        is not None
        and git_answers(["status", "--porcelain", "--", target], where) == []
    ]


def empty_directory_targets(targets: list[str], root: Path | None = None) -> list[str]:
    """Report which targets are directories with nothing in them.

    An archive unpacked into one replaces nothing, whatever the archive
    holds — which is the only way to answer that without reading the archive
    itself. A path that is absent, a file, or unreadable is not reported, so
    an unanswerable question reads as "something is already there".
    """
    where = Path.cwd() if root is None else root
    found: list[str] = []
    for target in targets:
        path = where / target
        if not path.is_dir():
            continue
        try:
            if not any(path.iterdir()):
                found.append(target)
        except OSError:
            continue
    return found


def directory_write_targets(targets: list[str], root: Path | None = None) -> list[str]:
    """Report which of a command's targets are directories on disk.

    A refusal that can name this says which way out is open — remove the
    files it holds — rather than leaving the agent to guess why a delete it
    expected to pass did not.
    """
    where = Path.cwd() if root is None else root
    return [target for target in targets if (where / target).is_dir()]


def read_document(path_text: str) -> str | None:
    """Read a path's current text, or None when nothing is there yet."""
    path = Path(path_text)
    return path.read_text(encoding="utf-8") if path.exists() else None


def declared_identity(identity_env: str) -> str:
    """The identity this session's launcher declared, if it declared one.

    A hook payload need not carry an agent identity at all, so the
    environment is the only channel every launcher is guaranteed to have.
    """
    environ = os.environ  # lup: ignore[os-environ]
    return environ[identity_env] if identity_env in environ else ""


def document_allowances(document_text: str, known: list[str]) -> list[str]:
    """Edit gates one document grants, as it reads at this instant.

    Read here rather than carried in, because a grant is answered while the
    session it answers is already running: a list resolved when the process
    started can neither gain the gate a human just approved nor lose one they
    took back. The document is named from outside and its contents are read
    afresh, so the current state governs in both directions.

    Only names in the compiled vocabulary count. The document is a transport,
    not an authority: a name no launcher can legitimately publish — a typo, or
    a gate this policy never grants this way — is dropped rather than
    honoured, so hand-writing one buys nothing.

    Nothing to read is no grant, and so is anything unreadable: a missing
    document, a directory, a half-written replacement, a payload that is not a
    list of names. Every one of them leaves the gate exactly where it was, so
    the failure is a refusal a human can answer rather than a grant nobody
    made.
    """
    if not document_text:
        return []
    try:
        declared = json.loads(Path(document_text).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(declared, list):
        return []
    return [str(name) for name in declared if str(name) in known]


def granted_allowances(grants_env: str, known: list[str]) -> list[str]:
    """Edit gates a human approved for the lease this session is working.

    The environment names the document rather than carrying the grants, so
    what a hook process inherits at launch is a place to look and never an
    answer that has since moved on.
    """
    environ = os.environ  # lup: ignore[os-environ]
    return document_allowances(
        environ[grants_env] if grants_env in environ else "", known
    )


def bash_decision(
    command: str,
    managed_root: Path | None,
    sandboxed: bool,
    interactive: bool,
    escapable: bool,
    cwd: Path | None,
) -> KernelDecision:
    """Judge one shell command against the declared vocabulary.

    The kernel reads no filesystem, so every fact about the paths this command
    would touch is resolved here and passed as data: which of the paths it
    would write already exist, which operands Git could restore, and which
    are directories.

    Existence and recoverability both cover redirection targets and path-verb
    operands alike, because the questions they ask are the same ones —
    whether writing here brings something into being or replaces it, and what
    replacing it would cost. Resolving them for only one of the two writing
    forms is what left ``rm f`` granted while ``echo x > f`` asked about the
    same clean, tracked file.

    ``cwd`` is where the calling session is, which the command's relative
    operands resolve against. It is a parameter rather than a read of this
    process, because a hook is promised nothing about where it runs, and
    resolving a target against the wrong tree answers a different question.

    ``escapable`` is the one thing here a runtime answers rather than the host:
    whether it can put a single call outside its own sandbox. It arrives as an
    argument for the same reason the rest does — a fact one dispatcher stopped
    passing is a rule that silently stopped applying.
    """
    acted_on = shell_path_verb_targets(command)
    verdict = decide_shell(
        command,
        SHELL_RULES,
        ALLOWED_FETCH_SCOPES,
        DENIED_FETCH_SCOPES,
        sandboxed=sandboxed,
        excluded_commands=SANDBOX_EXCLUDED_COMMANDS,
        trusted_script_roots=managed_script_roots(managed_root),
        path_roles=PATH_ROLES,
        path_rules=PATH_RULES,
        existing_targets=existing_write_targets(
            [*shell_write_targets(command), *acted_on], cwd
        ),
        recoverable_targets=recoverable_write_targets(
            [*shell_write_targets(command), *acted_on], cwd
        ),
        directory_targets=directory_write_targets(acted_on, cwd),
        empty_directories=empty_directory_targets(acted_on, cwd),
        recoverable_target_limit=RECOVERABLE_TARGET_LIMIT,
        runner_targets=RUNNER_TARGETS,
        target_tables=RUNNER_TARGET_TABLES,
        interactive=interactive,
        escapable=escapable,
        # Read here rather than passed by each dispatcher, unlike `escapable`
        # above: whether this process sits inside the container is a fact
        # about the host with no runtime variation to it, so neither
        # dispatcher is given the chance to forget it.
        contained=contained(),
    )
    if verdict.effect == "deny":
        return verdict
    targets = [*shell_write_targets(command), *acted_on]
    recorded = undo_point(command, verdict, targets, cwd)
    # Counted only where the command was going to run anyway. A refused script
    # never ran, so counting it would nudge toward promoting something that
    # has not worked once.
    if verdict.effect != "allow":
        return recorded
    nudge = script_run_nudge(python_script_targets(command, INTERPRETERS), cwd)
    return (
        KernelDecision("allow", recorded.reason + nudge, recorded.sandbox)
        if nudge
        else recorded
    )


def undo_point(
    command: str, verdict: KernelDecision, targets: list[str], cwd: Path | None
) -> KernelDecision:
    """Snapshot the tree before a command that could destroy work in it.

    The whole case for relaxing a permission lattice is that a mistake can be
    put back, so this is what has to exist before that relaxation is honest.
    What it does not need is a second list of destructive spellings: the
    vocabulary already draws that line, and draws it more finely than a list
    of verbs could. ``git reset`` is allowed and ``git reset --hard`` asks;
    ``git switch`` is allowed and ``git switch --force`` asks. So the mark is
    the verdict itself — anything the classifier did not wave through — plus
    the paths the command was already resolved to be writing, which is what
    catches an allowed-because-recoverable ``rm`` of a tracked file.

    Said out loud only on an approval question, which is the one moment the
    information changes an answer: a human deciding whether to permit
    something destructive is weighing exactly whether it can be undone. On an
    allowed command the snapshot is silent, because a line appended to every
    mutating command is one nobody reads by the third time — and ``dev undo``
    is where a snapshot is looked for anyway.
    """
    if not targets and verdict.effect == "allow":
        return verdict
    reference = undo_snapshot(cwd, command)
    if not reference or verdict.effect != "ask":
        return verdict
    return KernelDecision(
        verdict.effect,
        f"{verdict.reason} — the tree was snapshotted first; "
        f"`lup-devtools dev undo` lists it as {reference}",
        verdict.sandbox,
    )


def fetch_decision(url: str) -> KernelDecision:
    """Judge one outbound fetch against the declared scopes."""
    return decide_fetch(url, ALLOWED_FETCH_SCOPES, DENIED_FETCH_SCOPES)


def refused_tool_decision(name: str, values: list[str]) -> KernelDecision | None:
    """Judge one native call against the calls this project refuses outright.

    ``None`` leaves the routing runtime's own answer for a tool no refusal
    mentions, because the table says what a project decided against and never
    what it approved — an unmentioned tool is still unclassified.
    """
    return decide_tool(name, values, REFUSED_TOOLS)


def placed_document(path_text: str, after: str) -> str:
    """One file's text with every suppression at its canonical placement.

    Only Python has a placement to settle here: the policy is written in terms
    of a comment the formatter cannot wrap, and the tokenizer that says where
    a comment really opens is Python's.
    """
    if Path(path_text).suffix.lower() not in (".py", ".pyi"):
        return after
    return relocated_suppressions(after)


def placed_edit_text(path_text: str, after: str, start: int, end: int) -> str | None:
    """The replacement for an edit's own span, or ``None`` to place nothing."""
    if Path(path_text).suffix.lower() not in (".py", ".pyi"):
        return None
    return relocated_edit_text(after, start, end)


def edit_decision(
    path_text: str,
    before: str | None,
    after: str | None,
    path_exists: bool,
    autonomous: bool,
    cwd: Path | None = None,
) -> KernelDecision:
    """Judge one file's before and after against the declared edit policy.

    The path is relativized against the worktree holding it rather than the
    directory the runtime started in, because every repo-relative rule matches
    on that answer and a session may be launched anywhere.

    The gates this lease holds are read here, per call, rather than resolved
    when the session started: a grant is answered by a human while the session
    that asked for it is still running, and one resolved at launch could not
    have carried the answer.

    A checker is started only where its answer decides something. The kernel
    is asked first, from the tree and the tables alone, whether this edit
    trips a rule whose verdict turns on a resolved declaration; almost none
    do, and those are judged for nothing. Only the rest pay for a language
    server, which is the difference between a gate that costs a second per
    edit and one that costs a second on the edits that need it.
    """
    outside_this_repository = foreign_repository(path_text, cwd)
    suffix = Path(path_text).suffix.lower()
    python_source = suffix in (".py", ".pyi")
    rows = ANTI_PATTERN_ROWS[suffix] if suffix in ANTI_PATTERN_ROWS else []
    # A checker is not started for a file this policy has already decided it
    # has nothing to say about. It would resolve another repository's imports
    # against another repository's environment to answer a rule that will not
    # be applied, and pay a language server's second for the privilege.
    refuted = (
        resolved_refutations(path_text, after, RESOLUTION_COMMAND)
        if not outside_this_repository
        and after is not None
        and awaits_resolution(before, after, rows, python_source)
        else None
    )
    return decide_edit(
        worktree_path(path_text),
        before,
        after,
        path_exists=path_exists,
        path_rules=PATH_RULES,
        antipattern_rows=rows,
        path_roles=PATH_ROLES,
        maximum_added_lines=MAXIMUM_ADDED_LINES,
        autonomous=autonomous,
        allowances=granted_allowances(ALLOWANCE_GRANTS_ENV, KNOWN_ALLOWANCES),
        python_source=python_source,
        acceptance_guard=ACCEPTANCE_GUARD,
        refuted=refuted,
        foreign=outside_this_repository,
    )


def hook_environment():
    """The native environment passed to this bare hook process."""
    # lup: ignore[os-environ] — bare hooks have no settings package
    return os.environ


def managed_root():
    """The home Codex installs and trusts packages beneath."""
    environ = hook_environment()
    return Path(environ["CODEX_HOME"]) if "CODEX_HOME" in environ else None


def spent_escape(tool_input):
    """Whether this call requested Codex's per-command sandbox escape."""
    return (
        "sandbox_permissions" in tool_input
        and tool_input["sandbox_permissions"] == "require_escalated"
    )


def approval_fingerprint(payload):
    """Identify the fields both approval events carry for one Bash call."""
    fields = ("session_id", "turn_id", "cwd", "tool_name")
    if any(
        field not in payload
        or not isinstance(payload[field], str)
        or not payload[field]
        for field in fields
    ):
        return None
    tool_input = payload["tool_input"]
    if (
        payload["tool_name"] != "Bash"
        or not isinstance(tool_input, dict)
        or "command" not in tool_input
        or not isinstance(tool_input["command"], str)
    ):
        return None
    identity = [payload[field] for field in fields]
    identity.append(tool_input["command"])
    return json.dumps(identity, ensure_ascii=True, separators=(",", ":"))


def approval_receipt_root():
    """The plugin-owned writable directory shared by hook processes."""
    environ = hook_environment()
    if "PLUGIN_DATA" not in environ:
        return None
    return Path(environ["PLUGIN_DATA"]) / "approval-receipts"


def record_approval(payload, max_pending=256):
    """Record one native permission event without merging identical calls."""
    fingerprint = approval_fingerprint(payload)
    root = approval_receipt_root()
    if fingerprint is None or root is None:
        return
    root.mkdir(parents=True, exist_ok=True)
    receipts = list(root.iterdir())
    overflow = len(receipts) - max_pending + 1
    for receipt in receipts[: max(0, overflow)]:
        receipt.unlink(missing_ok=True)
    receipt = root / os.urandom(16).hex()
    receipt.write_text(fingerprint, encoding="utf-8")


def spend_approval(payload):
    """Consume one pending permission event matching this exact Bash call."""
    fingerprint = approval_fingerprint(payload)
    root = approval_receipt_root()
    if fingerprint is None or root is None or not root.exists():
        return False
    for receipt in root.iterdir():
        try:
            matches = receipt.read_text(encoding="utf-8") == fingerprint
        except (FileNotFoundError, UnicodeDecodeError):
            continue
        if not matches:
            continue
        try:
            receipt.unlink()
        except FileNotFoundError:
            continue
        return True
    return False


def joined(decisions):
    """Join one envelope's files: deny beats ask beats defer beats allow."""
    for effect in ("deny", "ask", "defer"):
        for decision in decisions:
            if decision.effect == effect:
                return decision
    return KernelDecision("allow", "every patched file is declared safe")


def dispatch(payload, permission_request=False):
    name = payload["tool_name"]
    tool_input = payload["tool_input"]
    # Where this session is rooted, which is what says whether a patched file
    # belongs to the repository being worked on or to somebody else's. Read
    # once, because the shell path and the patch path ask the same question of
    # it and a second read is a second place it can be forgotten.
    session_directory = Path(payload["cwd"]) if "cwd" in payload else None
    if name == "Bash":
        requested_escape = spent_escape(tool_input)
        escaped = requested_escape or auto_escape_matches(
            tool_input["command"], AUTO_ESCAPE_PREFIXES
        )
        decision = bash_decision(
            tool_input["command"],
            managed_root(),
            False if permission_request else sandbox_active(),
            interactive=permission_request,
            # A native prefix rule can auto-escape one simple command; an explicit
            # request is the other supported route. Both are checked against
            # semantic placement before the hook lets the native boundary act.
            escapable=escaped,
            cwd=session_directory,
        )
        # PreToolUse can neither see nor place every native escape. Let Codex's
        # sandbox run a confined call or raise the PermissionRequest where this
        # same policy can judge the requested escape instead of preempting it.
        if not permission_request and decision.reason == SANDBOX_TRAPPED_REASON:
            return KernelDecision("defer", decision.reason)
        if (
            requested_escape
            and decision.effect == "allow"
            and decision.sandbox != "outside"
        ):
            return KernelDecision(
                "deny",
                f"call requested outside but policy places it {decision.sandbox}; remove sandbox_permissions and retry",
            )
        return decision
    if name == "web_fetch":
        return fetch_decision(tool_input["url"])
    if name == "apply_patch":
        autonomous = (
            declared_identity(AGENT_IDENTITY_ENV) in AUTONOMOUS_AGENT_IDENTITIES
        )
        return joined(
            [
                edit_decision(
                    change.path,
                    change.before,
                    change.after,
                    change.path_exists,
                    autonomous,
                    session_directory,
                )
                for change in patched_files(tool_input["command"], read_document)
            ]
        )
    # Asked of whatever reached here rather than of a listed few, exactly as
    # the Claude half asks it: which tools are worth refusing is the
    # declaration's answer, and a runtime that shipped the table without
    # consulting it would read as a refusal in force while the call went
    # through. The branches above keep their calls, which have semantics.
    refused = refused_tool_decision(
        name, [value for value in tool_input.values() if isinstance(value, str)]
    )
    if refused is not None:
        return refused
    return KernelDecision("ask", f"unknown tool {name!r} is not covered by policy")


def spoken_failure(payload):
    """Everything a finished call said about going wrong, as one text.

    Read out of whichever shape the response arrives in, because a hook is
    promised the field and not its type, and a runtime free to add a third
    shape must not turn this into an exception in a hook whose failure is a
    decision that never happened. The same reading Claude's dispatcher makes,
    which is the point: what a boundary refusal looks like is the kernel's
    words, not either runtime's.
    """
    response = payload["tool_response"] if "tool_response" in payload else ""
    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        return ""
    return "\n".join(
        str(value) for value in response.values() if isinstance(value, str)
    )


def observe(payload):
    """Explain a failure the boundary caused, or record where an edit landed.

    A finished shell command is read for a failure the *boundary* caused and
    stays silent about every other kind: the mount table refuses a write as
    ``Read-only file system``, which is what a broken disk says too, so an
    agent reading it changes permissions, creates the parent, and retries --
    none of which can work, and none of which says so. This is the only
    moment that failure can be explained, because the evidence is the
    command's own output and it does not exist until now.

    The rest records which checkout an edit landed in, and decides nothing.

    Codex reads the directory it ran in, where Claude reads the edited file.
    Not a lesser answer here, and not an available one either way: Codex
    names its files inside the patch envelope, and the parser that decodes
    one validates its context against the document on disk — which this
    event runs after the patch already rewrote. Re-decoding it here would
    fail on exactly the edits it was called for. Codex hands over its
    working directory instead, which Claude's hook is promised nothing
    about, and that is the same fact one step coarser.

    Coarser is enough to say which checkout is being edited and not enough
    to type-check what changed, so Codex records the edition and Claude also
    reports diagnostics. Checking the directory instead would answer every
    patch with every finding in the tree, most of them about files this
    edit never touched.
    """
    root = payload["cwd"] if "cwd" in payload else ""
    if payload["tool_name"] == "Bash" if "tool_name" in payload else False:
        described = boundary_description(Path(root) if root else None)
        return boundary_refusal(spoken_failure(payload), described)
    if root:
        publish_edition(root)
    return ""


def main():
    try:
        payload = json.load(sys.stdin)
        # Watching and deciding are separate events, and this one returns
        # before a verdict exists: the patch has already applied, so there is
        # nothing left to permit, and the fail-closed exit below would refuse
        # a call that already happened.
        event = payload["hook_event_name"] if "hook_event_name" in payload else ""
        if event == "PostToolUse":
            # Exit 2 is the one channel this event has to the agent here as
            # on the other runtime: the call already ran, so nothing is
            # undone, and a clean exit says nothing anywhere it will be read.
            # Silence unless the boundary is what refused, so the channel
            # means something when it is used.
            found = observe(payload)
            if found:
                sys.stderr.write(found)
                raise SystemExit(2)
            return
        permission_request = event == "PermissionRequest"
        permission_evidenced = event == "PreToolUse" and spend_approval(payload)
        decision = dispatch(payload, permission_request or permission_evidenced)
        # PermissionRequest has no tool-use id. A matching PreToolUse is the
        # native proof that its session-, turn-, cwd-, tool-, and command-bound
        # request proceeded; the policy is still re-run so a deny still wins.
        if permission_evidenced and decision.effect == "ask":
            decision = KernelDecision("allow", decision.reason, decision.sandbox)
        # Record before replying: an undecided request reaches a human, and a
        # later matching PreToolUse exists only when that human accepted it.
        if permission_request and decision.effect != "deny":
            record_approval(payload)
        # A verdict from here places nothing: this hook answers, and the call
        # runs with the arguments the model wrote, so a placement is degraded
        # to its plain effect rather than carrying an intent no channel here
        # performs. The agent's own escape is the other question and Codex
        # does have one, so a permission to escalate survives as reason text.
        decision = decision.placed(escapable=False, agent_escalates=True)
    # Every way this can fail means one thing — the call went unjudged — and
    # one answer is right for all of them. Naming the exceptions instead is
    # what let a plain unreadable file escape, and a traceback exit is not the
    # fail-closed exit this boundary takes, so the call proceeded ungoverned.
    # Nothing is swallowed: the reason carries whatever went wrong, and an
    # interrupt still passes through as the BaseException it is.
    except Exception as error:
        sys.stderr.write(f"Malformed hook input requires approval: {error}")
        raise SystemExit(2) from error
    if permission_request and decision.effect == "allow":
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "allow"},
                }
            },
            sys.stdout,
        )
        return
    if permission_request and decision.effect == "ask":
        return
    if decision.effect in ("allow", "defer"):
        return
    sys.stderr.write(decision.reason)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
