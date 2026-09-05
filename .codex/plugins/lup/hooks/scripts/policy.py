#!/usr/bin/env python3
# Generated from lup.policy.assets.host and lup.providers.codex.assets.policy_dispatcher by `uv run lup-devtools harness generate all` — edit the source, not this file.
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
from hashlib import sha256
from datetime import UTC, datetime, timedelta

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
from kernel.shell import decide_shell, sandbox_excluded
from kernel.tools import decide_tool
from policy_data import (
    ACCEPTANCE_GUARD,
    ALLOWANCE_GRANTS_ENV,
    ALLOWED_FETCH_SCOPES,
    ANTI_PATTERN_ROWS,
    RESOLUTION_COMMAND,
    DENIED_FETCH_SCOPES,
    EDIT_RULES,
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


def measured_boundary(
    root: Path | None, ledger: str = ".lup/preflight"
) -> dict[str, list[str]]:
    """What the launch that opened this session measured about its boundary.

    Read back from the ledger that launch wrote, and only from the one it
    named: ``LUP_BOUNDARY_NONCE`` says which file this session is entitled to
    believe. That is what the nonce is for. A ledger left by some other launch
    is a measurement of some other session, and reading it would be the same
    class of wrong answer as the constant this replaces, arrived at from the
    other direction.

    Absent, unnamed, or unparseable all come back empty, and every caller
    reads empty as "no boundary was measured" -- the fail-closed answer and
    the honest one. A session whose launcher predates this has no ledger, and
    gets exactly what a session whose boundary failed to stand gets.
    """
    environ = os.environ  # lup: ignore[os-environ]
    nonce = environ["LUP_BOUNDARY_NONCE"] if "LUP_BOUNDARY_NONCE" in environ else ""
    if root is None or not nonce:
        return {}
    try:
        raw = (root / ledger / f"{nonce}.json").read_text()
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


def contained(measured: dict[str, list[str]]) -> bool:
    """Whether this session runs inside the boundary its profile promised.

    A different question from :func:`sandbox_active`, and the two are not
    interchangeable: the native sandbox confines one call at a time and can
    be told to leave some alone, where a container confines the process and
    was never asked.

    Read from what the launch *measured* rather than from a variable. The
    variable was ``LUP_CONTAINED``, a constant an image bakes, and a constant
    answers yes for any container built from that image, for a bare ``run``
    holding none of the lease, and -- since a launcher forwards its own
    environment -- for an uncontained session started from a shell that
    happened to export it. That last one is not hypothetical: it is a session
    reporting a boundary with no container under it, placing every operation
    by a wall that is not there.
    """
    return "yes" in (measured["contained"] if "contained" in measured else [])


def delivers(measured: dict[str, list[str]], capability: str) -> bool:
    """Whether the launch observed one capability this session depends on."""
    return capability in (measured["delivered"] if "delivered" in measured else [])


def defers_unjudged(measured: dict[str, list[str]]) -> bool:
    """Whether this profile hands legible work nothing judged to the runtime.

    A bool rather than the policy's own word for it, because this half may
    reach nothing but a pinned standard library and cannot name the literal
    the kernel takes. The caller spells the vocabulary; what crosses here is
    the fact.

    False wherever nothing was measured, which is both the declared default
    and the visible answer. A session that could not read its own profile is
    not one that should infer a seamless posture from the silence.
    """
    declared = measured["unjudged_ambient"] if "unjudged_ambient" in measured else []
    return bool(declared) and declared[0] == "defer"


def append_hook_evidence(path: Path, encoded: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(encoded + "\n")


def record_hook_evidence(
    data_root: Path | None,
    payload: dict,
    phase: str,
    outcome: str | None = None,
    detail: str | None = None,
) -> None:
    """Append hook metadata without retaining a tool's input or output."""
    if data_root is None:
        return
    record = {
        "schema_version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "phase": phase,
    }
    fields = ("session_id", "turn_id", "tool_name", "tool_use_id")
    record["event_name"] = (
        payload["hook_event_name"]
        if "hook_event_name" in payload and isinstance(payload["hook_event_name"], str)
        else None
    )
    record.update(
        {
            field: payload[field]
            for field in fields
            if field in payload and isinstance(payload[field], str)
        }
    )
    record.update({"outcome": outcome} if outcome is not None else {})
    record.update({"detail": detail} if detail is not None else {})
    encoded = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
    try:
        append_hook_evidence(data_root / "hook-events.jsonl", encoded)
    except OSError as error:
        print(f"lup: could not record hook evidence: {error}", file=sys.stderr)


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


def record_question(
    root: Path | None,
    command: str,
    reason: str,
    rule: str,
    purpose: str,
    reviewer: str,
    escalated: str,
    placement: str,
    session: str = "",
    requester: str = "",
    relay: str = ".lup/questions.jsonl",
) -> str:
    """Park one final ask in the durable relay, before anybody is shown it.

    Every route to a question passes through a verdict, and the boundary that
    reaches one is what every provider has in common — so a record written
    here is a record both of them produce, which is what makes the relay one
    authority rather than a store the in-process seam happens to use.

    Primitives rather than a verdict, because this half may reach nothing but
    the pinned standard library and a verdict is the kernel's. The caller
    reads the fields off it.

    Append-only, because the failure this survives is a crash between
    recording a question and answering it, and a store rewritten in place has
    a window where the question is neither the old one nor the new one.

    The id is derived from the session and what is being asked, so the same
    question reached twice folds to one record instead of filling a queue
    nobody can then read. What it deliberately does not record is *who
    answered*: on the interactive path that is a receipt inferred from the
    provider's own behaviour, and inventing one here would be writing down a
    decision nobody made.

    Silent about its own failure, for the reason every writer in this module
    is: it runs in front of an operation somebody asked for, and a read-only
    checkout is an ordinary place to be running. What it must not do is turn
    a policy question into a crash.
    """
    if root is None or not command:
        return ""
    identifier = sha256(f"{session}:{command}:{reason}".encode()).hexdigest()[:16]
    entry = json.dumps(
        {
            "id": identifier,
            "operation": {
                "id": identifier,
                "session": session,
                "requester": requester,
                "tool": "Bash",
                "payload": {"command": command},
                "cwd": str(root),
                "worktree": str(root),
                "placement": placement,
            },
            "fingerprint": identifier,
            "reason": reason,
            "rule": rule,
            "purpose": purpose or None,
            "requirement": reviewer,
            # Empty and *said to be unresolved*, which are different facts: this
            # boundary is hermetic and cannot reach the session's principals, so
            # it has no chain to resolve rather than a chain that resolved to
            # nobody. Written as the second, every question parked here would be
            # answerable by nobody and the queue could only grow.
            "eligible": [],
            "chain_resolved": False,
            "escalation": escalated,
            "state": "pending",
            "created": datetime.now(UTC).isoformat(),
        },
        sort_keys=True,
    )
    path = root / relay
    try:
        held = path.read_text(encoding="utf-8") if path.exists() else ""
        if f'"id": "{identifier}"' in held:
            return identifier
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as sink:
            sink.write(entry + "\n")
    except OSError:
        return ""
    return identifier


def record_deferral(
    root: Path | None,
    command: str,
    reason: str,
    judged: bool,
    corpus: str = ".lup/hooks/learned.jsonl",
) -> str:
    """Write down one command this policy declined to interrupt about.

    The other half of allow-and-log, and what makes the relaxation honest.
    The lattice asked about everything unjudged for an *observability*
    reason, and logging serves that without spending anybody's attention --
    but only if something is actually written down, or the relaxation is
    just the asking removed.

    **Two kinds of deferral reach here and they are worth very different
    things**, which is why ``judged`` is recorded rather than inferred later.
    An unjudged one is a gap in the vocabulary: nobody has ever said anything
    about this command, and it is a candidate for a rule. A judged one is the
    relaxation working -- a rule looked, and the boundary answered for the
    loss -- and it is an audit trail rather than a candidate. Collapsing them
    would put `git reset --hard` in the same list as a command nobody has
    classified, and the list is read to find the second.

    **Written at the moment the verdict exists**, rather than after the
    command has run. The later event was proposed and refuted: a runtime
    offers both "yes" and "yes, don't ask again" and the later event cannot
    tell them apart, and a human may answer by *editing* the command, so it
    fires for something other than what was judged. None of that touches a
    deferral, which is nobody's approval and is exactly known here.

    **One line per distinct command.** A session defers the same `grep` fifty
    times, and fifty identical lines is a list nobody reads -- the same
    failure the undo layer's dedup exists to prevent, in the same shape. So a
    command already written down is skipped, and the file is a set: what a
    diff shows is what this session met that no session had met before.

    Silent about its own failure, and for the reason :func:`undo_snapshot`
    is: this runs in front of a command somebody asked for, and a read-only
    checkout is an ordinary place to be running. An empty string says nothing
    was recorded.
    """
    if root is None or not command:
        return ""
    path = root / corpus
    try:
        seen = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return ""
    entry = json.dumps(
        {
            "command": command,
            "reason": reason,
            "judged": judged,
            "first_seen": datetime.now(UTC).isoformat(),
        },
        sort_keys=True,
    )
    # Compared on the command alone, because the rest of the row is what this
    # session happened to say about it: the same command reached twice under
    # two reasons is one candidate, and a timestamp differs every time.
    for line in seen.splitlines():
        try:
            held = json.loads(line)
        except ValueError:
            continue
        if isinstance(held, dict) and "command" in held and held["command"] == command:
            return ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as sink:
            sink.write(entry + "\n")
    except OSError:
        return ""
    return entry


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


def is_git_marker(marker: Path) -> bool:
    """Whether *marker* carries Git metadata rather than only its name."""
    return marker.is_file() or (marker.is_dir() and (marker / "HEAD").is_file())


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
        if is_git_marker(root / ".git"):
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


def undo_retention_days() -> int:
    """How long a snapshot is worth keeping, absent a caller's own answer.

    How long ago a mistake is still worth undoing is a judgement about how
    somebody works rather than a fact about git, so it reaches its caller as a
    default they may differ on. Long enough to cover a week of sessions, short
    enough that a snapshot per mutating command does not accumulate without
    bound.

    A function for the reason :func:`undo_namespace` is one: the dispatcher
    splices this half in a function at a time, and the command that expires
    snapshots on request has to read the same number the dispatcher expires
    them by, or the two halves disagree about how long the net holds.
    """
    return 7


def undo_retention_count() -> int:
    """How many snapshots are worth keeping, absent a caller's own answer.

    A second bound because the window answers a different question. "How long
    ago is still worth undoing" is about how somebody works; this is about what
    the net is allowed to cost, and neither answers the other -- a burst
    session reaches a thousand snapshots inside the window, and a quiet
    fortnight holds three that are all past it.

    Measured on this checkout: a working day produces on the order of fifty
    distinct states, so a week inside the window lands near three hundred and
    this bound is the one that usually binds. That is deliberate. What the
    listing is *for* is finding the snapshot from before the thing that went
    wrong, and a reader who cannot see the entries cannot choose one -- so the
    cap is set where the list stays readable rather than where growth would
    become alarming.
    """
    return 200


def undo_expire(
    root: Path | None,
    keep_days: int = 0,
    namespace: str = "",
    now: datetime | None = None,
    keep_most: int = 0,
) -> list[str]:
    """Retire what outlived the window or sits past the cap; report what went.

    Two bounds, and a snapshot need only fail one of them. The window cannot
    hold a burst -- a session that touches a thousand states reaches them all
    inside a week -- and the cap cannot express that a fortnight-old snapshot
    has stopped being worth keeping when only three exist. Read together they
    bound the namespace by age *and* by size, which is what makes the listing
    finite whatever a session does.

    Selection reads the stamp the ref name already carries rather than asking
    git for each commit's date. The name was built to order the listing
    exactly, which makes it fixed-width, zero-padded and UTC -- so comparing
    it against a cutoff spelled the same way is the same judgement one string
    comparison later, and sorting by name is sorting by age. Both bounds come
    off one listing that costs a single call.

    Deleting the ref is the whole of it: the objects it held become
    unreachable and git's own housekeeping reclaims them.

    Silent about its own failure, exactly as its caller is. This runs in front
    of a command somebody asked for, and a repository that will not let a ref
    be deleted is not a reason to stop them.
    """
    if root is None:
        return []
    where = namespace or undo_namespace()
    taken = now or datetime.now(UTC)
    cutoff = taken - timedelta(days=keep_days or undo_retention_days())
    stamped = cutoff.strftime("%Y%m%dT%H%M%S%f")

    def outlived(ref: str) -> bool:
        """Whether this ref's own stamp sorts before the cutoff's."""
        # lup: ignore[string-split] — the ref name is this module's own
        # protocol, spelled `<stamp>-<tree>` by `undo_snapshot` below; git
        # ships no parser for a ref name, and the separator being read here is
        # the one that call chose
        stamp = ref.removeprefix(f"{where}/").split("-")[0]
        return len(stamp) == len(stamped) and stamp < stamped

    listed = sorted(
        git_answers(["for-each-ref", "--format=%(refname)", where], root) or []
    )
    # Taken off the front because the sort is by name and the name leads with
    # the stamp, so the oldest are exactly the ones the cap has no room for.
    limit = keep_most or undo_retention_count()
    surplus = {ref for ref in listed[: max(0, len(listed) - limit)]}
    retired = [ref for ref in listed if outlived(ref) or ref in surplus]
    for ref in retired:
        git_answers(["update-ref", "-d", ref], root)
    return retired


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
    mutating command has to cost what this costs, or it is the first thing
    somebody turns off -- and the warm figure is the one that matters, because
    the cold index is paid once and reused for the rest of the session.
    """
    if root is None:
        return ""
    directory = git_answers(["rev-parse", "--absolute-git-dir"], root)
    if not directory:
        return ""
    index = Path(f"{directory[0]}/lup-undo-{session}.index")
    # The session's index is written by the first snapshot and reused by every
    # one after it, so its absence is what "nobody has snapshotted in this
    # session yet" looks like -- already on disk, already being stat'd, and
    # true exactly once however long the session runs. Read before the index is
    # created and acted on after the ref is written, so the sweep counts the
    # snapshot it runs beside and the cap means the same number here as it does
    # to the command that offers it.
    cold = not index.exists()
    private = {"GIT_INDEX_FILE": str(index)}
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
    if cold:
        undo_expire(root, namespace=where)
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


def unleased_write_targets(
    targets: list[str], measured: dict[str, list[str]], root: Path | None = None
) -> list[str]:
    """Report which targets fall outside what this launch mounted writable.

    The lease is a snapshot. A contained launch enumerates its siblings when
    the container starts and punches a read-only overlay over each; a worktree
    cut afterwards gets the writable base with no overlay, and the mount
    namespace is fixed by then, so nothing can be remounted to cover it. The
    judgement is what is left, which is the arrangement the lease already
    relies on elsewhere.

    Nothing is reported where no boundary was measured. A session that could
    not read its own lease knows of no writable roots at all, and reporting
    every target as unleased would put a question in front of every write in
    the checkout -- which teaches nobody anything and buries the real ones.
    """
    leased = measured["writable_roots"] if "writable_roots" in measured else []
    if not leased:
        return []
    where = Path.cwd() if root is None else root
    return [
        target
        for target in targets
        for resolved in [str((where / target).resolve())]
        if not any(
            resolved == root_path or resolved.startswith(root_path + "/")
            for root_path in leased
        )
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
    relayed: bool = False,
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
    # Read once and passed to each fact that needs it, rather than re-read per
    # question: the ledger is one measurement of one launch, and a second read
    # partway through a verdict could answer from a file the first did not see.
    boundary = measured_boundary(cwd)
    inside = contained(boundary)
    acted_on = shell_path_verb_targets(command)
    # Before the verdict rather than after it, because the verdict reads it:
    # an approval question exists where a loss is permanent, and a tree the
    # object store already holds has no permanent loss to ask about. Ordered
    # the other way the relaxation would be judging a snapshot that did not
    # exist yet, and a refused command is snapshotted too -- one ref for a
    # state the tree was already in, which dedup collapses.
    reference = undo_snapshot(cwd, command)
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
        # A reviewed worker is non-interactive and not therefore alone: it
        # holds a mailbox reaching the human supervising its run, and a
        # refusal that named no route sent it to queue a blocking question
        # instead.
        relayed=relayed,
        # What `outside` means is the launcher's host, and a runtime's own
        # per-call escape only reaches it where there is no container in
        # between. Uncontained, that escape genuinely is the way out of the
        # only boundary there is; contained, it lands in the container and a
        # placement settled on it would send an operation somewhere nothing
        # can carry it. So the runtime still answers for its escape and the
        # measurement answers for whether that escape reaches the host.
        escapable=(escapable and not inside) or delivers(boundary, "host_executor"),
        # Read here rather than passed by each dispatcher, unlike `escapable`
        # above: whether this process sits inside the boundary its profile
        # promised is a fact about the host with no runtime variation to it,
        # so neither dispatcher is given the chance to forget it.
        contained=inside,
        # The other half of that pair, and the reason the first one alone
        # settles nothing: a container is a promise about where an operation
        # lands, and `bounded()` counts it only where the launch measured that
        # the promise holds. Passed from the same ledger read, so the two
        # cannot describe different launches.
        inside_placement=delivers(boundary, "inside_placement"),
        # The profile's own answer for the long tail, which only an
        # uncontained session ever reaches: contained, the row above settles
        # the same operation first.
        unjudged_ambient="defer" if defers_unjudged(boundary) else "ask",
        # Resolved against what this launch mounted writable, so a write into a
        # worktree cut after the container started reaches a reviewer instead of
        # the writable base no overlay covers.
        unleased_targets=unleased_write_targets(
            [*shell_write_targets(command), *acted_on], boundary, cwd
        ),
        recovered=bool(reference),
    )
    # Parked before anything is rendered, because the relay is the durable
    # record every final ask is written to and the provider's own prompt is
    # that record's renderer rather than a second authority. Written here, at
    # the one call site both runtimes pass through, so neither can reach a
    # question the queue does not hold.
    if verdict.effect == "ask":
        record_question(
            cwd,
            command,
            verdict.reason,
            verdict.rule,
            verdict.purpose or "",
            verdict.reviewer,
            verdict.escalated,
            verdict.sandbox,
        )
    if verdict.effect == "deny":
        return verdict
    # The log half of allow-and-log. A deferral is this policy declining to
    # interrupt, which is the one verdict that reaches nobody: the runtime's
    # own gate decides and the reason goes to no human. Written down here or
    # it is not written down anywhere.
    if verdict.effect == "defer":
        record_deferral(cwd, command, verdict.reason, verdict.checkpoint != "nothing")
    pointed = undo_point(verdict, reference)
    if pointed.effect != "allow":
        return pointed
    nudge = script_run_nudge(python_script_targets(command, INTERPRETERS), cwd)
    if not nudge:
        return pointed
    return KernelDecision(
        pointed.effect,
        pointed.reason + nudge,
        pointed.sandbox,
        pointed.escalated,
        checkpoint=pointed.checkpoint,
    )


def unconfined_by_declaration(command: str) -> bool:
    """Whether the boundary declaration takes this command out of isolation.

    A command excluded from the boundary runs unconfined because the profile
    said so, which is a grant a native escape request is spending rather than
    circumventing. Read here, beside every other reading of the same table, so
    a runtime cannot answer it differently from the classifier.
    """
    return sandbox_excluded(command, SANDBOX_EXCLUDED_COMMANDS)


def undo_point(verdict: KernelDecision, reference: str) -> KernelDecision:
    """Say the tree was snapshotted, on the one verdict that changes for it.

    The snapshot itself is taken above, before the verdict, because the
    verdict reads it. What is left here is what the human is told.

    On an approval question, which is the one moment the information changes
    an answer: somebody deciding whether to permit something destructive is
    weighing exactly whether it can be undone. On an allowed command the
    snapshot is silent, because a line appended to every mutating command is
    one nobody reads by the third time — and ``dev undo`` is where a snapshot
    is looked for anyway. On a deferral the reason reaches no human at all;
    it reaches the record, which is where the relaxation is reviewed.
    """
    if not reference or verdict.effect != "ask":
        return verdict
    return KernelDecision(
        verdict.effect,
        f"{verdict.reason} — the tree was snapshotted first; "
        f"`lup-devtools dev undo` lists it as {reference}",
        verdict.sandbox,
        verdict.escalated,
        checkpoint=verdict.checkpoint,
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
    operation: str = "modify",
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
        suffix=suffix,
        operation=operation,
        edit_rules=EDIT_RULES,
        foreign=outside_this_repository,
    )


def hook_environment():
    """The native environment passed to this bare hook process."""
    # lup: ignore[os-environ] — bare hooks have no settings package
    return os.environ


def plugin_data_root():
    """The plugin-owned writable directory Codex gives hook processes."""
    environ = hook_environment()
    root = environ["PLUGIN_DATA"] if "PLUGIN_DATA" in environ else ""
    return Path(root) if root else None


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


def uncorrelated(payload):
    """Why a call that should carry an approval does not, in one sentence.

    Empty when nothing is amiss, which is the ordinary case: a call that was
    never escalated has no approval to find and no problem to report.

    This exists because the failure it names is otherwise indistinguishable
    from the one it is not. A call whose native approval was accepted and
    whose receipt then failed to correlate reaches the same refusal as a call
    nobody approved at all -- so #180 reads as "the policy rejected my
    escalated diff" and the actual defect, whichever field the two events
    disagreed on, leaves no trace. Naming the step that failed does not fix
    it and does make the next run conclusive.
    """
    root = approval_receipt_root()
    if root is None or not root.exists() or not list(root.iterdir()):
        return ""
    if approval_fingerprint(payload) is None:
        missing = [
            field
            for field in ("session_id", "turn_id", "cwd", "tool_name")
            if field not in payload or not payload[field]
        ]
        named = ", ".join(missing) if missing else "the command"
        return (
            f" — an approval is pending for this run and this call could not be"
            f" matched to it: the event carries no {named}, so the two cannot"
            " be correlated"
        )
    return (
        " — an approval is pending for this run but none matches this exact"
        " call; the escalation and this call disagree on the session, the turn,"
        " the directory or the command text"
    )


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
    # Whether this session is a reviewed worker, which decides two unrelated
    # things: how a patch is judged, and whether a refusal has a route to
    # name. Read once at the top rather than inside the branch that needed it
    # first, since both branches need it now.
    autonomous = declared_identity(AGENT_IDENTITY_ENV) in AUTONOMOUS_AGENT_IDENTITIES
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
            # A reviewed worker's session has nobody at a keyboard and is not
            # therefore alone: the run it belongs to carries a mailbox that
            # reaches whoever is supervising it.
            relayed=autonomous,
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
            and not unconfined_by_declaration(tool_input["command"])
        ):
            return KernelDecision(
                "deny",
                f"call requested outside but policy places it {decision.sandbox}; remove sandbox_permissions and retry",
            )
        return decision
    if name == "web_fetch":
        return fetch_decision(tool_input["url"])
    if name == "apply_patch":
        return joined(
            [
                edit_decision(
                    change.path,
                    change.before,
                    change.after,
                    change.path_exists,
                    autonomous,
                    change.operation(),
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


def observe(payload):
    """Record which checkout an edit landed in, and decide nothing.

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
    if root:
        publish_edition(root)


def main():
    payload = {}
    try:
        payload = json.load(sys.stdin)
        record_hook_evidence(plugin_data_root(), payload, "started")
        # Watching and deciding are separate events, and this one returns
        # before a verdict exists: the patch has already applied, so there is
        # nothing left to permit, and the fail-closed exit below would refuse
        # a call that already happened.
        event = payload["hook_event_name"] if "hook_event_name" in payload else ""
        if event == "PostToolUse":
            observe(payload)
            record_hook_evidence(plugin_data_root(), payload, "completed", "observed")
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
        # performs. Asking for the launcher's host is a marker a reviewer
        # answers, and it reaches the same relay under every runtime, so
        # nothing about that route depends on this channel existing.
        decision = decision.placed(escapable=False)
    # Every way this can fail means one thing — the call went unjudged — and
    # one answer is right for all of them. Naming the exceptions instead is
    # what let a plain unreadable file escape, and a traceback exit is not the
    # fail-closed exit this boundary takes, so the call proceeded ungoverned.
    # Nothing is swallowed: the reason carries whatever went wrong, and an
    # interrupt still passes through as the BaseException it is.
    except Exception as error:
        record_hook_evidence(
            plugin_data_root(),
            payload,
            "failed",
            "error",
            f"{type(error).__name__}: {error}",
        )
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
        record_hook_evidence(plugin_data_root(), payload, "completed", "allow")
        return
    if permission_request and decision.effect == "ask":
        record_hook_evidence(plugin_data_root(), payload, "completed", "ask")
        return
    if decision.effect in ("allow", "defer"):
        record_hook_evidence(plugin_data_root(), payload, "completed", decision.effect)
        return
    # A refusal that arrives while an approval is pending is two failures
    # wearing one face -- the policy declining a call, and the correlation
    # between a native approval and the call it approved not landing. They
    # read identically without this, which is how #180 reads as the first
    # when it is the second.
    detail = decision.reason + uncorrelated(payload)
    record_hook_evidence(
        plugin_data_root(), payload, "completed", decision.effect, detail
    )
    sys.stderr.write(detail)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
