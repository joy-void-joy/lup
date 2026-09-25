"""Accept changed destination policy bytes for a live, already granted launch."""

import json
import os
import unicodedata
from collections.abc import Callable
from difflib import SequenceMatcher, unified_diff
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import NoneType, UnionType
from typing import (
    Literal,
    TypeAliasType,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)
from tempfile import NamedTemporaryFile

import typer
import sh
from pydantic import BaseModel, TypeAdapter, ValidationError

from lup.devtools.harness.preflight import NONCE_VARIABLE, ledger_path
from lup.execution.shell import git
from lup.policy.bundle import PolicyData
from lup.policy.assets.host import (
    contents_digest,
    policy_data_literals,
    worktree_refusal,
)
from lup.policy.snapshots import (
    DestinationPolicy,
    PolicyRuntime,
    RepositoryPolicyAuthority,
    captured_policy,
    evaluator_source,
)
from lup.sandbox.rail import Lease, lease_for, repository_layout
from lup.types import JsonObject, JsonValue


class PolicyLaunchLedger(BaseModel, extra="allow"):
    """The grant field plus boundary measurements preserved without reinterpretation.

    The runtime is read as the closed vocabulary rather than as text: it is
    spelled into the path an evaluator is accepted from, and the ledger is a
    file in the checkout the session works in.
    """

    destination_policies: list[str] = []
    destination_authorities: list[str] = []
    writable_roots: list[str] = []
    read_only_roots: list[str] = []
    runtime: list[PolicyRuntime] = []

    def grant_for(
        self, checkout: Path, launch: Path, runtime: PolicyRuntime | None = None
    ) -> DestinationPolicy:
        """A checkout no grant named, reached through an authority the launch holds.

        Two authorities reach one. An explicitly mounted writable bare
        repository covers the worktrees beneath that mount. The launch
        checkout's own repository covers the worktrees its own lease holds:
        the lease that opens a session mounts that repository's shared
        directory writable, so a worktree the session cuts there is one it
        could already write, and whose edits were already judged as that
        repository's code, by the policy the session launched with. Accepting
        it changes which of that repository's generated policies judges those
        edits and nothing about what the launch may write -- which is why,
        under either authority, the deepest measured root over the checkout
        has to hold it writable.

        Either way the checkout has to be a worktree Git registered, and
        neither the launch checkout nor one nested inside a checkout of its
        repository: :func:`~lup.policy.assets.host.worktree_refusal` says
        which of those failed, and why none of it proves where a worktree came
        from.

        The evaluator accepted is the one generated for the runtime the launch
        opened. The ledger records it; ``runtime`` names it for a ledger that
        records none, and must agree with whichever the ledger does record.
        """
        if not checkout.is_dir():
            raise ValueError(
                f"No recorded writable repository authority covers {checkout}"
            )
        try:
            top = Path(
                git.out("-C", str(checkout), "rev-parse", "--show-toplevel").strip()
            ).resolve()
        except sh.ErrorReturnCode as error:
            raise ValueError(f"{checkout} is not a Git worktree") from error
        if top != checkout:
            raise ValueError(f"Use the canonical Git worktree root: {top}")
        repository = str(repository_layout(checkout).common.resolve())
        mounted: list[PolicyRuntime] = [
            row.runtime
            for row in (
                RepositoryPolicyAuthority.model_validate_json(encoded)
                for encoded in self.destination_authorities
            )
            if row.repository == repository and checkout.is_relative_to(Path(row.root))
        ]
        own = repository == str(repository_layout(launch).common.resolve())
        covering = {
            Path(path): writable
            for paths, writable in (
                (self.writable_roots, True),
                (self.read_only_roots, False),
            )
            for path in paths
            if checkout.is_relative_to(Path(path))
        }
        deepest = max(covering, key=lambda path: len(path.parts), default=None)
        if (not mounted and not own) or deepest is None or not covering[deepest]:
            raise ValueError(
                f"No recorded writable repository authority covers {checkout}; changing repository access requires another launch"
            )
        refusal = worktree_refusal(str(checkout), str(launch))
        if refusal:
            raise ValueError(refusal)
        if not mounted and not self.leased(checkout, launch):
            raise ValueError(
                f"{checkout} lies outside the launch repository's own lease: "
                f"neither the shared directory {repository} nor a checkout the "
                "launch leased holds it, so it is writable only through some "
                "other mount, and a mount grants no policy authority. Cut the "
                f"worktree under {repository}, or name it with --mount at the "
                "next launch"
            )
        recorded: list[PolicyRuntime] = [*self.runtime, *mounted]
        if any(name != recorded[0] for name in recorded):
            raise ValueError(
                "This launch's grants name more than one runtime "
                f"({', '.join(dict.fromkeys(recorded))}); "
                "changing repository access requires another launch"
            )
        launched = recorded[0] if recorded else runtime
        if launched is None:
            raise ValueError(
                "This launch recorded no runtime; name the one it opened with "
                "--runtime claude or --runtime codex"
            )
        if runtime is not None and runtime != launched:
            raise ValueError(
                f"This launch opened {launched}; --runtime {runtime} names another runtime"
            )
        return DestinationPolicy(
            repository=repository,
            checkout=str(checkout),
            runtime=launched,
            writable_roots=[str(checkout)],
            read_only_roots=self.read_only_roots,
        )

    def leased(self, checkout: Path, launch: Path) -> bool:
        """Whether the launch repository's own lease holds a checkout.

        Recomputed from Git here rather than read back from the ledger the
        session's checkout holds: the checkout, every worktree Git lists, and
        the shared directory writable, its `config` and `hooks/` read-only.
        Git lists a registered worktree wherever it sits, so the lease would
        hold any one of them as a mount of its own; what counts is a root
        other than the checkout's own registration -- the shared directory,
        where the session cuts its worktrees -- or the checkout itself where
        the launch measured it writable as a mount of its own, a sibling that
        was there when the session started. A worktree reachable only through
        some other writable mount lies outside it.
        """
        own = lease_for(launch)
        roots = {root.resolve(): inside for root, inside in own.writable.items()}
        beneath = Lease(
            writable={
                root: inside for root, inside in roots.items() if root != checkout
            },
            read_only={
                root.resolve(): inside for root, inside in own.read_only.items()
            },
        )
        measured = [Path(item).resolve() for item in self.writable_roots]
        return beneath.writable_at(checkout) or (
            checkout in roots and checkout in measured
        )


class ConstantChange(BaseModel, frozen=True):
    """One named constant of a generated policy, as accepting it would rewrite it.

    Positional, because a table read first match first -- the path rules, the
    path roles -- decides by order as well as by content: an entry moved above
    another changes what a path is judged by though nothing was added or
    dropped, so a move reads as the entry leaving one place and arriving at
    another, each at the position it holds.
    """

    name: str
    removed: list[str]
    added: list[str]
    lines: list[str]
    """The change in reading order: where it falls, then what leaves and arrives."""


class CodeChange(BaseModel, frozen=True):
    """One evaluator file whose code differs from what this launch's lup generates."""

    name: str
    state: Literal["changed", "added", "removed"]
    diff: list[str]
    """The unified diff from the launch's generated file to the checkout's."""


class PolicyPreview(BaseModel, frozen=True):
    """What accepting a checkout's generated policy changes, shown before anything is.

    The data is read from both sides' ``policy_data.py`` without running
    either -- :func:`~lup.policy.assets.host.policy_data_literals` -- because
    the side being accepted was written by the session asking for it. The
    code beside that data runs once accepted, so every evaluator file that
    differs from what this launch's own lup generates is shown as a diff.

    ``contents`` is every file accepting takes, as read once: the digest is
    theirs, what is shown was parsed from them, and the snapshot is written
    from them, so the bytes shown and the bytes accepted cannot come apart.
    """

    checkout: str
    runtime: PolicyRuntime
    digest: str
    judging: str
    changes: list[ConstantChange]
    code: list[CodeChange]
    code_digest: str
    """What the differing code is, which ``--accept-code`` has to name to run it."""
    contents: dict[PurePosixPath, bytes]

    def lines(self) -> list[str]:
        """The preview as the operator reads it, one compact line per entry."""
        entries = [
            line
            for change in self.changes
            for line in [f"  {change.name}", *[f"    {row}" for row in change.lines]]
        ]
        code = [
            "  Code that runs once accepted, where it differs from what this "
            f"launch's lup generates ({self.code_digest}):",
            *[
                line
                for change in self.code
                for line in [
                    f"    {change.name} ({change.state})",
                    *[f"      {row}" for row in change.diff],
                ]
            ],
        ]
        return [
            f"Accepting the {self.runtime} policy {visible(self.checkout)} "
            f"generates ({self.digest}),",
            f"in place of the one that judges it now ({visible(self.judging)}):",
            *(entries or ["  No constant differs."]),
            *(code if self.code else ["  No code differs."]),
        ]


class RefreshDeclined(Exception):
    """The operator was shown what accepting would change and said no."""


class UnreviewedCode(Exception):
    """The checkout's evaluator code differs, and nobody said to accept code.

    Carries the preview, so the refusal is read beside the diff it is about:
    accepting code is its own answer, given with ``--accept-code`` naming the
    digest of the code that was shown, so an answer given to one diff cannot
    run whatever the checkout holds by the time it is given.
    """

    def __init__(self, preview: PolicyPreview, named: str) -> None:
        shown = (
            f"--accept-code named {visible(named)}, but the code shown above is "
            f"{preview.code_digest}"
            if named
            else "The code shown above differs from what this launch's lup generates"
        )
        super().__init__(
            f"{shown}. Nothing was accepted for {visible(preview.checkout)}; once "
            "that diff is code you mean to run, refresh again with "
            f"--accept-code {preview.code_digest}."
        )
        self.preview = preview


def terminal_control(character: str) -> bool:
    """Whether printing one character could move, erase or reorder what is shown.

    Every C0 and C1 control and DEL -- a carriage return, an erase-line, a
    cursor move -- the line and paragraph separators that break a line where
    no newline is, and the bidirectional controls that reorder a line as it
    is displayed without changing a byte a diff compares.
    """
    return (
        unicodedata.category(character) in ("Cc", "Zl", "Zp")
        or unicodedata.bidirectional(character)
        in ("LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI")
        or character in "\u200e\u200f\u061c"
    )


def visible(text: str) -> str:
    """Text a session wrote, with every terminal control spelled as its code point.

    What the operator reads is the decision this preview exists for, and the
    session writing the checkout writes these strings too: a carriage return
    and an erase-line can take a removed protected path off the screen.
    """
    return "".join(
        f"\\u{ord(character):04x}" if terminal_control(character) else character
        for character in text
    )


def literal(value: JsonValue) -> str:
    """One value as its JSON spelling, every character that could hide it spelled out."""
    return visible(json.dumps(value, ensure_ascii=False))


def departures(value: object, annotation: object, where: str) -> list[str]:
    """Every way a value departs from the type a generated constant declares.

    Rows are held to their row type exactly: a field the type lacks, or one
    it has left out, is a departure rather than something to render around,
    so a missing field and an empty one can never read alike.
    """
    shape = (
        annotation.__value__ if isinstance(annotation, TypeAliasType) else annotation
    )
    origin = get_origin(shape)
    if is_typeddict(shape):
        if not isinstance(value, dict):
            return [f"{where} is not a row"]
        fields = get_type_hints(shape)
        required: frozenset[str] = vars(shape)["__required_keys__"]
        return [
            *[
                f"{where}[{literal(key)}] is no field of its row"
                for key in value
                if key not in fields
            ],
            *[
                f"{where} lacks {key}"
                for key in fields
                if key in required and key not in value
            ],
            *[
                problem
                for key, field in fields.items()
                if key in value
                for problem in departures(value[key], field, f"{where}.{key}")
            ],
        ]
    match origin:
        case _ if origin is list:
            if not isinstance(value, list):
                return [f"{where} is not a list"]
            (item,) = get_args(shape)
            return [
                problem
                for index, entry in enumerate(value)
                for problem in departures(entry, item, f"{where}[{index}]")
            ]
        case _ if origin is dict:
            if not isinstance(value, dict):
                return [f"{where} is not a mapping"]
            _, item = get_args(shape)
            return [
                *[
                    f"{where} has a key that is not text"
                    for key in value
                    if not isinstance(key, str)
                ],
                *[
                    problem
                    for key, entry in value.items()
                    for problem in departures(
                        entry, item, f"{where}[{literal(str(key))}]"
                    )
                ],
            ]
        case _ if origin is Literal:
            allowed = get_args(shape)
            return (
                []
                if any(
                    type(value) is type(option) and value == option
                    for option in allowed
                )
                else [
                    f"{where} is none of {', '.join(literal(option) for option in allowed)}"
                ]
            )
        case _ if origin is Union or origin is UnionType:
            branches = [departures(value, branch, where) for branch in get_args(shape)]
            return [] if any(not problems for problems in branches) else branches[0]
        case _ if shape is NoneType:
            return [] if value is None else [f"{where} is not None"]
        case _ if shape in (str, int, bool, float):
            return [] if type(value) is shape else [f"{where} is not {shape.__name__}"]
    raise TypeError(f"{where} is declared as {shape!r}, which no check here reads")


def generated_data(path: Path, text: str) -> JsonObject:
    """One side's constants, held to exactly the shape generation writes."""
    data = policy_data_literals(path, text)
    problems = departures(data, PolicyData, "")
    if problems:
        raise ValueError(
            f"{visible(str(path))} holds data generation never writes, so none of "
            f"it is shown: {'; '.join(problem.lstrip('.') for problem in problems)}"
        )
    return TypeAdapter(JsonObject).validate_python(data)


def readable_code(name: PurePosixPath, content: bytes) -> str:
    """One evaluator file's code, refused where printing it could lie.

    Code is shown as a diff before it is accepted, and a line holding a
    terminal control or a bidirectional control can read as other code than
    it is. Generation writes neither -- a tab and a newline are all the
    control a source needs -- so either is refused rather than escaped.
    """
    try:
        code = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{visible(name.as_posix())} is not UTF-8: {error}") from error
    found = next(
        (
            index
            for index, character in enumerate(code)
            if terminal_control(character) and character not in "\t\n"
        ),
        None,
    )
    if found is not None:
        raise ValueError(
            f"{visible(name.as_posix())}:{code.count(chr(10), 0, found) + 1} holds "
            f"U+{ord(code[found]):04X}, a control that could make the diff shown "
            "read as other code than it is; generation writes none, so it is refused"
        )
    return code


def entry_line(entry: JsonValue) -> str:
    """One entry of a generated constant, on one line, every field spelled.

    A row shows each of its fields as its JSON value, empty ones included:
    a field going from absent to empty, or from ``null`` to ``false``, is a
    change, and a line that left empty fields out would show none.
    """
    match entry:
        case dict():
            return " ".join(f"{key}={literal(field)}" for key, field in entry.items())
        case _:
            return literal(entry)


def constant_entries(value: JsonValue) -> list[str]:
    """Every entry a generated constant holds, one compact line each.

    A table's entries are its rows. A table of tables -- the anti-pattern
    rows keyed by suffix -- lists each row under its key, so a rule retired
    for one suffix reads apart from the same rule kept for another. Anything
    else is the one entry it is.
    """
    match value:
        case list():
            return [entry_line(item) for item in value]
        case dict() if value and all(isinstance(rows, list) for rows in value.values()):
            return [
                f"{literal(key)}: {entry_line(row)}"
                for key, rows in value.items()
                if isinstance(rows, list)
                for row in rows
            ]
        case _:
            return [entry_line(value)]


def constant_change(
    name: str, judging: JsonObject, accepting: JsonObject
) -> ConstantChange:
    """One constant's entries as accepting rewrites them, position by position."""
    before = constant_entries(judging[name]) if name in judging else []
    after = constant_entries(accepting[name]) if name in accepting else []
    hunks = [
        (start, end, first, last)
        for tag, start, end, first, last in SequenceMatcher(
            a=before, b=after, autojunk=False
        ).get_opcodes()
        if tag != "equal"
    ]
    return ConstantChange(
        name=name,
        removed=[line for start, end, _, _ in hunks for line in before[start:end]],
        added=[line for _, _, first, last in hunks for line in after[first:last]],
        lines=[
            row
            for start, end, first, last in hunks
            for row in [
                f"@ entry {start + 1} of {len(before)}",
                *[f"- {line}" for line in before[start:end]],
                *[f"+ {line}" for line in after[first:last]],
            ]
        ],
    )


def code_change(
    name: PurePosixPath, generated: bytes | None, accepting: bytes | None
) -> CodeChange:
    """One evaluator file as the launch's lup generates it against the checkout's."""

    def read(content: bytes | None) -> list[str]:
        """A file's lines, or none where the side holds no such file."""
        return [] if content is None else readable_code(name, content).splitlines()

    return CodeChange(
        name=visible(name.as_posix()),
        state=(
            "added"
            if generated is None
            else "removed"
            if accepting is None
            else "changed"
        ),
        diff=list(
            unified_diff(
                read(generated),
                read(accepting),
                fromfile=f"generated/{name}",
                tofile=f"checkout/{name}",
                lineterm="",
            )
        ),
    )


def policy_preview(
    existing: DestinationPolicy, root: Path, runtime: PolicyRuntime
) -> PolicyPreview:
    """What accepting ``existing``'s generated policy changes for the launch at ``root``.

    The data is compared with the policy that judges the checkout now: the
    snapshot its grant accepted, where it holds one, and otherwise the launch
    checkout's own generated tree, whose policy judges every worktree no grant
    names. The code is compared with that launch tree, which is what the
    launch's own lup generates, and with the snapshot judging now only where
    the launch checkout generates no tree for this runtime. Each side is read
    once, and what is shown is parsed from those bytes.
    """
    source = evaluator_source(Path(existing.checkout), runtime)
    theirs = captured_policy(source)
    snapshot = Path(existing.snapshot) if existing.snapshot else None
    granted = snapshot if snapshot is not None and snapshot.is_dir() else None
    judging = granted or evaluator_source(root, runtime)
    held_contents = captured_policy(judging)
    try:
        launch = evaluator_source(root, runtime)
    except ValueError:
        launch = judging
    generated = held_contents if launch == judging else captured_policy(launch)
    data = PurePosixPath("runtime", "policy_data.py")
    accepting = generated_data(source / data, theirs[data].decode("utf-8"))
    held = generated_data(judging / data, held_contents[data].decode("utf-8"))
    for name, content in theirs.items():
        if name != data:
            readable_code(name, content)
    changes = [
        constant_change(name, held, accepting)
        for name in dict.fromkeys([*accepting, *held])
    ]
    differing = [
        name
        for name in dict.fromkeys([*generated, *theirs])
        if name != data
        and (
            name not in generated
            or name not in theirs
            or generated[name] != theirs[name]
        )
    ]
    return PolicyPreview(
        checkout=existing.checkout,
        runtime=runtime,
        digest=contents_digest(theirs),
        judging=str(judging),
        changes=[change for change in changes if change.lines],
        code=[
            code_change(
                name,
                generated[name] if name in generated else None,
                theirs[name] if name in theirs else None,
            )
            for name in differing
        ],
        code_digest=sha256(
            json.dumps(
                [
                    [
                        name.as_posix(),
                        sha256(generated[name]).hexdigest()
                        if name in generated
                        else "",
                        sha256(theirs[name]).hexdigest() if name in theirs else "",
                    ]
                    for name in differing
                ]
            ).encode("utf-8")
        ).hexdigest(),
        contents=theirs,
    )


def refresh_destination_policy(
    root: Path,
    nonce: str,
    repository: Path,
    approve: Callable[[PolicyPreview], bool],
    runtime: PolicyRuntime | None = None,
    accept_code: str = "",
) -> DestinationPolicy:
    """Replace one accepted snapshot without extending that launch's authority.

    ``root`` is the launch checkout, whose ledger this rewrites and whose
    repository is one of the two authorities a checkout no grant named can be
    reached through; ``runtime`` is read only where the ledger cannot say.

    ``approve`` is shown what accepting would change before anything is
    written. Declined, it raises :class:`RefreshDeclined` with the ledger and
    the snapshot store as they were; approved, it accepts the bytes it was
    shown and no others. Evaluator code differing from what the launch's lup
    generates raises :class:`UnreviewedCode` before anybody is asked, unless
    ``accept_code`` names the digest of exactly the code that was shown.
    """
    # lup: ignore[os-environ] — reject an operator-only action inherited by the requesting session
    if os.environ.get(NONCE_VARIABLE):
        raise ValueError(
            "Policy snapshot refresh requires an independent operator terminal outside "
            "the agent session. The requesting session cannot accept replacement policy."
        )
    if not nonce or Path(nonce).name != nonce or nonce in {".", ".."}:
        raise ValueError("The launch nonce must be a single ledger name")
    path = ledger_path(root, nonce)
    adapter = TypeAdapter(dict[str, list[str]])
    captured = path.read_text(encoding="utf-8")
    document = PolicyLaunchLedger.model_validate(adapter.validate_json(captured))
    policies = [
        DestinationPolicy.model_validate_json(row)
        for row in document.destination_policies
    ]
    checkout = str(repository.resolve())
    matches = [row for row in policies if row.checkout == checkout]
    if len(matches) > 1:
        raise ValueError(
            f"Launch {nonce} has no unique explicit policy grant for {checkout}; "
            "changing repository access requires another launch."
        )
    existing = (
        matches[0]
        if matches
        else document.grant_for(repository.resolve(), root.resolve(), runtime)
    )
    if str(repository_layout(repository).common.resolve()) != existing.repository:
        raise ValueError("Destination Git repository identity changed; launch again")
    if not existing.runtime:
        raise ValueError("Launch grant has no runtime identity; launch again")
    if runtime is not None and runtime != existing.runtime:
        raise ValueError(
            f"Launch {nonce} accepted {checkout} for {existing.runtime}; "
            f"--runtime {runtime} names another runtime"
        )
    preview = policy_preview(existing, root.resolve(), existing.runtime)
    if preview.code and accept_code != preview.code_digest:
        raise UnreviewedCode(preview, accept_code)
    if not approve(preview):
        raise RefreshDeclined(checkout)
    accepted = existing.accepted(root.resolve(), existing.runtime, preview.contents)
    if accepted.error:
        raise ValueError(accepted.error)
    document.destination_policies = [
        (accepted if row.checkout == checkout else row).model_dump_json()
        for row in policies
    ] + ([accepted.model_dump_json()] if not matches else [])
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as staged:
        json.dump(document.model_dump(), staged, indent=2)
        replacement = Path(staged.name)
    if path.read_text(encoding="utf-8") != captured:
        replacement.unlink()
        raise ValueError("The launch ledger changed during refresh; read it and retry")
    replacement.replace(path)
    return accepted


def refresh_command(
    root: Path,
    nonce: str,
    repository: Path,
    runtime: PolicyRuntime | None = None,
    yes: bool = False,
    accept_code: str = "",
) -> None:
    """Show the operator what a refresh changes, and accept it once they agree.

    The preview is printed either way, so what ``--yes`` accepted is on the
    record too; the flag skips only the question. Code differing from what
    the launch's lup generates is shown and refused until ``--accept-code``
    names the digest it was shown under.
    """

    def approve(preview: PolicyPreview) -> bool:
        """Show what accepting changes, then take the operator's answer."""
        typer.echo("\n".join(preview.lines()))
        return yes or typer.confirm("Accept this policy for the launch?")

    try:
        accepted = refresh_destination_policy(
            root, nonce, repository, approve, runtime, accept_code
        )
    except UnreviewedCode as unreviewed:
        typer.echo("\n".join(unreviewed.preview.lines()))
        typer.echo(str(unreviewed))
        raise typer.Exit(1) from None
    except RefreshDeclined:
        typer.echo(
            f"Nothing accepted: launch {nonce} judges {repository.resolve()} "
            "as it did before."
        )
        raise typer.Exit(1) from None
    except (OSError, ValueError, ValidationError, sh.ErrorReturnCode) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(
        f"Accepted {accepted.checkout} policy {accepted.digest} for launch {nonce}"
    )
