"""The reports the agent reads, in pyright's shape: `path:line:column - rule: message`.

lup's findings on the lines a call changed are told after it, each with its
steer, beside the type errors and ruff's findings, and those on lines no change
touched apart; none refuses (`docs/judging-writes.md`, *Findings*). A refusal
is a held change the operator declined or left unanswered, put back or never
written, with where the agent's version is saved; an approval, one the operator
approved, in a line saying lup held it for their review. A move of `HEAD` is
told as its commits', never put back.

A session hears about several worktrees, from any working directory, so every
report names each file by its absolute path, as pyright's command line does.
The texts name no runtime: each adapter carries them as its runtime hears them.

**Told once** (`docs/judging-writes.md`, *Told once*): a conversation is told a
finding when it first appears, and not again while it stands (`Known`, `news`);
and the standing words around findings, a section's instructions and a lup
rule's mistake and steer, the first time they're due, each finding of a rule
told before saying in a line what its check saw (`Words`).
**Quiet** (*Quiet*): a conversation can ask not to be told some kinds of
findings for a while (`Kind`, `Quiet`); what a quiet holds back isn't told, and
isn't remembered as told, so it's told once the quiet lifts (`summary`).
**Fitted:** a report past what a hook tells whole is kept whole in a file
(`Reports`), and told with each section that doesn't fit shortened to a line
per file (`fitted`), so the runtime never moves it out of the agent's sight.
"""

import hashlib
from collections import Counter
from functools import reduce
from pathlib import Path
from typing import TYPE_CHECKING, Literal, get_args

from lup.types import Model
from lup_dev.clock import Clock
from lup_dev.codescan.contract import Finding, Owner
from lup_dev.confined import Confined
from lup_dev.layout import GitDirectoryLayout
from lup_dev.policy.judge import PRIVATE, Ask, RemovedNote

if TYPE_CHECKING:
    from collections.abc import Iterator


def placed(root: Path, findings: list[Finding]) -> list[Finding]:
    """Name each finding's file by its absolute path, from the worktree at `root`.

    >>> from lup_dev.codescan.contract import Position, Span
    >>> at = Position(line=1, column=1)
    >>> found = Finding(path=Path("a.py"), span=Span(start=at, end=at), owner="ruff",
    ...     rule="E501", message="too long")
    >>> [each.path for each in placed(Path("/work"), [found])]
    [PosixPath('/work/a.py')]
    """
    return [found.model_copy(update={"path": root / found.path}) for found in findings]


class Known(Model):
    """A finding as a conversation was told it, which they aren't told again while it stands.

    Known by its file, owner, rule and message, and by the text of the line it
    starts on rather than the line's number, so a finding an edit above moves
    along isn't new. Two alike on lines alike are one: told together, and the
    turn's end lists each.
    """

    path: Path
    """The file, from its worktree's root."""
    owner: Owner
    rule: str
    message: str
    line: str
    """The text of the line it starts on, as it was found; empty where that
    content wasn't read."""


class Look(Model):
    """One reading of a file's findings: every one it holds of the owners read, and the content they were found in."""

    path: Path
    """The file, from its worktree's root."""
    owners: list[Owner]
    """Whose findings it read in full: every owner for a file judged, pyright's
    alone for one the importers pass re-checked."""
    findings: list[Finding] = []
    """What it found that's told, each file named as `path` is."""
    held: list[Finding] = []
    """What it found that the conversation's quiet holds back (`Quiet`): not
    told, and not remembered as told, though what was told of it before stays
    known while it stands."""
    content: str | None = None
    """The content they were found in; none where there's none to read."""

    def known(self, found: Finding) -> Known:
        r"""Return `found` as a conversation told it knows it.

        >>> from lup_dev.codescan.contract import Position, Span
        >>> at = Position(line=2, column=1)
        >>> found = Finding(path=Path("a.py"), span=Span(start=at, end=at),
        ...     owner="pyright", rule="reportCallIssue", message="bad call")
        >>> Look(path=Path("a.py"), owners=["pyright"], content="x\ncall()\n").known(found).line
        'call()'
        """
        lines = (self.content or "").splitlines()
        number = found.span.start.line
        line = lines[number - 1] if 0 < number <= len(lines) else ""
        return Known(
            path=found.path,
            owner=found.owner,
            rule=found.rule,
            message=found.message,
            line=line,
        )

    def covers(self, known: Known) -> bool:
        """Say whether this look read `known`'s file and owner, so what it found stands in its place."""
        return known.path == self.path and known.owner in self.owners


class News(Model):
    """What of some looks a conversation wasn't told yet, and what they know once told it."""

    findings: list[Finding] = []
    """Those they weren't told, in the looks' order."""
    known: list[Known] = []


def news(told: list[Known], looks: list[Look]) -> News:
    r"""Say what of `looks` wasn't `told`, and what's known once it is.

    What each look found replaces what was known of its file and owners, so a
    finding that's gone is forgotten, and told again if it comes back; what no
    look read stays known. What a quiet held back (`Look.held`) is neither told
    nor learned: it stays known where it was told before, and is forgotten
    where it wasn't, so it's told once the quiet lifts.

    >>> from lup_dev.codescan.contract import Position, Span
    >>> def at(line: int, rule: str = "reportCallIssue") -> Finding:
    ...     where = Position(line=line, column=1)
    ...     return Finding(path=Path("a.py"), span=Span(start=where, end=where),
    ...         owner="pyright", rule=rule, message="bad call")
    >>> first = Look(path=Path("a.py"), owners=["pyright"], findings=[at(1)],
    ...     content="call()\n")
    >>> heard = news([], [first])
    >>> len(heard.findings)
    1
    >>> moved = Look(path=Path("a.py"), owners=["pyright"], findings=[at(2)],
    ...     content="# added above\ncall()\n")
    >>> news(heard.known, [moved]).findings
    []
    >>> quiet = Look(path=Path("a.py"), owners=["pyright"],
    ...     held=[at(1), at(1, "reportArgumentType")], content="call()\n")
    >>> still = news(heard.known, [quiet])
    >>> (still.findings, [known.rule for known in still.known])
    ([], ['reportCallIssue'])
    """
    # lup: ignore("set-shape", why="membership alone: what the conversation was told, looked up for each finding of a report that can hold thousands")
    already = set(told)
    found = [
        (finding, look.known(finding)) for look in looks for finding in look.findings
    ]
    kept = [
        known
        for look in looks
        for finding in look.held
        if (known := look.known(finding)) in already
    ]
    unread = [known for known in told if not any(look.covers(known) for look in looks)]
    return News(
        findings=[finding for finding, known in found if known not in already],
        known=[*unread, *dict.fromkeys([*(known for _, known in found), *kept])],
    )


type Kind = Literal["rules", "changed", "untouched", "importers"]
"""A kind of finding a conversation can quiet, as a report's sections tell them
(`information`): lup's findings on the lines changed (`rules`); type errors and
ruff's findings in the files changed (`changed`); lup's findings on lines no
change touched, in those files (`untouched`); and type errors in the files
importing what changed (`importers`)."""


class Quiet(Model):
    """What a conversation asked not to be told after their calls, for now (`docs/judging-writes.md`, *Quiet*).

    A value never published is a finding of lup's, but no quiet holds it: no
    `ignore` keeps it either, and a push carrying it is refused. Nor does one
    hold anything but findings: a refusal, a hold's answer, a move of `HEAD`,
    a notice, a removed note, or the turn's end's list.
    """

    kinds: list[Kind] = []
    """The kinds held; none where the conversation isn't quiet."""

    def told(self, kind: Kind, found: list[Finding]) -> list[Finding]:
        """Return what of `found`, findings of `kind`, is told: each one where `kind` isn't held; else the values never published alone."""
        if kind not in self.kinds:
            return found
        return [each for each in found if each.rule == PRIVATE]

    def look(self, kind: Kind, look: Look) -> Look:
        """Return `look`, whose findings are of `kind`, with what this holds of them moved to `held`.

        >>> from lup_dev.codescan.contract import Position, Span
        >>> at = Position(line=1, column=1)
        >>> def found(rule: str) -> Finding:
        ...     return Finding(path=Path("a.py"), span=Span(start=at, end=at),
        ...         owner="lup", rule=rule, message="m")
        >>> seen = Look(path=Path("a.py"), owners=["lup"],
        ...     findings=[found("regex"), found("private")])
        >>> quiet = Quiet(kinds=["rules"]).look("rules", seen)
        >>> ([each.rule for each in quiet.findings], [each.rule for each in quiet.held])
        (['private'], ['regex'])
        >>> Quiet(kinds=["rules"]).look("untouched", seen) == seen
        True
        """
        if kind not in self.kinds:
            return look
        return look.model_copy(
            update={
                "findings": self.told(kind, look.findings),
                "held": [
                    *look.held,
                    *(each for each in look.findings if each.rule != PRIVATE),
                ],
            }
        )

    def said(self) -> str:
        """Say what this holds, in words, the kinds in the order a report tells them.

        >>> Quiet(kinds=["importers", "changed"]).said()
        "type errors and ruff's findings in the files changed, and type errors in the files importing what changed"
        """
        order: list[Kind] = list(get_args(Kind.__value__))
        named = [described(kind) for kind in order if kind in self.kinds]
        if len(named) < 2:
            return "".join(named)
        return f"{', '.join(named[:-1])}, and {named[-1]}"

    def reminder(self) -> str:
        """Tell a conversation starting again, compacted or resumed, that they're still quiet; nothing where they aren't.

        >>> Quiet().reminder()
        ''
        >>> print(Quiet(kinds=["rules"]).reminder())
        You're still quiet: lup doesn't tell you lup's findings on the lines changed after your calls. `quiet` with no kinds lifts it, and tells you what stands that you weren't told.
        """
        if not self.kinds:
            return ""
        return (
            f"You're still quiet: lup doesn't tell you {self.said()} after your "
            "calls. `quiet` with no kinds lifts it, and tells you what stands that "
            "you weren't told."
        )


def described(kind: Kind) -> str:
    """Say what findings of `kind` are, in words.

    >>> described("untouched")
    "lup's findings on lines no change touched"
    """
    match kind:
        case "rules":
            return "lup's findings on the lines changed"
        case "changed":
            return "type errors and ruff's findings in the files changed"
        case "untouched":
            return "lup's findings on lines no change touched"
        case "importers":
            return "type errors in the files importing what changed"


class Words(Model):
    """The standing words a conversation was told around findings, which a report tells them once (`docs/judging-writes.md`, *Told once*).

    A section of findings says what to do with them, in a parenthesis after its
    title, the first time a conversation is told that section; its title alone
    after. A lup rule's finding says the mistake the rule prevents and where it
    steers the first time a conversation is told one of that rule's; after, what
    its check saw alone, in a line, where the engine told that apart
    (`Finding.detail`). pyright's and ruff's findings have no such words, nor do
    those the judge makes itself, so they're told whole each time. Kept with the
    session's conversations, every worktree's reports alike, and forgotten as
    what they knew is, when their runtime compacts or clears them.
    """

    headers: list[str] = []
    """The sections told with their instructions, each by its header so."""
    rules: list[str] = []
    """The lup rules whose mistake and steer were told, by id."""

    def then(self, later: Words) -> Words:
        """Return these words and `later`'s."""
        return Words(
            headers=list(dict.fromkeys([*self.headers, *later.headers])),
            rules=list(dict.fromkeys([*self.rules, *later.rules])),
        )

    def firsts(self, found: list[Finding]) -> list[Finding]:
        """Return the findings of `found` that tell their rule's mistake and steer: of each lup rule these words don't hold, its first finding that says apart what its check saw (`Finding.detail`)."""
        fresh = dict.fromkeys(
            each.rule for each in found if each.detail and each.rule not in self.rules
        )
        return [
            next(each for each in found if each.detail and each.rule == rule)
            for rule in fresh
        ]

    def lines(self, found: list[Finding]) -> list[str]:
        """Spell `found` as pyright does: each lup rule's mistake and steer with its first finding where these words don't hold them (`firsts`), and its other findings in a line each (`finding_lines`)."""
        firsts = self.firsts(found)
        return [
            line
            for each in found
            for line in finding_lines(each, standing=each in firsts)
        ]

    def taught(self, found: list[Finding]) -> Words:
        """Return the words telling `found` tells beyond these: the rules whose mistake and steer it says."""
        return Words(rules=[each.rule for each in self.firsts(found)])


class Part(Model):
    """One section of what lup tells after an event: told whole where the report fits what a hook tells whole, else short where it can be (`fitted`)."""

    whole: str
    short: str | None = None
    """The section with a line per file, saying how many findings it has of
    each rule; none where it's always told whole: a refusal, a move, a notice,
    a value never published, a removed note."""
    words: Words = Words()
    """The standing words it tells whole, which its reader then knows; told
    short, its header's alone."""

    def told(self, *, whole: bool) -> Words:
        """Return the standing words this tells, `whole` or short."""
        return self.words if whole else Words(headers=self.words.headers)


def heard(parts: list[Part]) -> Words:
    """Return the standing words `parts` tell, each whole."""
    return reduce(Words.then, [part.words for part in parts], Words())


class Section(Model):
    """A section of findings under its header, told whole, or short where it can be (`fitted`)."""

    title: str
    instructions: str
    """What to do with its findings, said in a parenthesis after its title the
    first time a conversation is told the section."""
    findings: list[Finding]
    short: bool = True
    """Whether it can be told short: a value never published is always told
    whole."""

    @property
    def header(self) -> str:
        """Its header whole: its title, then its instructions in a parenthesis."""
        return f"{self.title} ({self.instructions}):"

    def part(self, words: Words) -> Part:
        """Say this section to a reader who knows `words`: its title alone where they hold its header, and each lup rule's mistake and steer once (`Words.lines`).

        >>> from lup_dev.codescan.contract import Position, Span
        >>> at = Position(line=3, column=1)
        >>> found = Finding(path=Path("/w/a.py"), span=Span(start=at, end=at),
        ...     owner="lup", rule="set-shape", message="`set()` builds a set. Sets forget.",
        ...     steer="a dict", detail="`set()` builds a set")
        >>> section = Section(title="Findings", instructions="clear each",
        ...     findings=[found, found.model_copy(update={"detail": "`{1}` builds a set"})])
        >>> first = section.part(Words())
        >>> print(first.whole)
        Findings (clear each):
          /w/a.py:3:1 - set-shape: `set()` builds a set. Sets forget.
              steer: a dict
          /w/a.py:3:1 - set-shape: `{1}` builds a set
        >>> print(section.part(first.words).whole)
        Findings:
          /w/a.py:3:1 - set-shape: `set()` builds a set
          /w/a.py:3:1 - set-shape: `{1}` builds a set
        """
        known = self.header in words.headers
        header = f"{self.title}:" if known else self.header
        said = Words(headers=[] if known else [self.header])
        return Part(
            whole="\n".join([header, *words.lines(self.findings)]),
            short=counted(header, self.findings) if self.short else None,
            words=said.then(words.taught(self.findings)),
        )


def parts_of(found: list[Section], words: Words) -> list[Part]:
    """Say each section of `found` that has findings, in order, to a reader who knows `words` and what the sections before it tell."""

    def each() -> Iterator[Part]:
        knows = words
        for section in found:
            if section.findings:
                part = section.part(knows)
                knows = knows.then(part.words)
                yield part

    return list(each())


def text(parts: list[Part]) -> str:
    """Say every part whole, a blank line between each."""
    return sections([part.whole for part in parts])


def counted(header: str, findings: list[Finding]) -> str:
    """Say a section of findings short: its header, then a line per file, how many findings it has, and of which rules.

    >>> from lup_dev.codescan.contract import Position, Span
    >>> at = Position(line=1, column=1)
    >>> def found(rule: str) -> Finding:
    ...     return Finding(path=Path("/w/a.py"), span=Span(start=at, end=at),
    ...         owner="pyright", rule=rule, message="m")
    >>> print(counted("Type errors:", [found("x"), found("y"), found("x")]))
    Type errors:
      /w/a.py: 3 (x 2, y 1)
    """
    rules = Counter((found.path, found.rule) for found in findings)
    files = Counter(found.path for found in findings)

    def line(path: Path) -> str:
        each = ", ".join(
            f"{rule} {count}"
            for (where, rule), count in rules.most_common()
            if where == path
        )
        return f"  {path}: {files[path]} ({each})"

    return "\n".join([header, *(line(path) for path in files)])


class Reports(Model, arbitrary_types_allowed=True):
    """Where the judge keeps a report too long for a hook, whole, for the agent to read: the repository's git directory, which every room reads (`GitDirectoryLayout.reports`)."""

    layout: GitDirectoryLayout
    clock: Clock
    kept: int = 100
    """How many reports are kept, the latest: each is read within minutes of
    the call it follows, if at all."""

    def keep(self, report: str) -> Path:
        """Keep `report` whole, and return where; forget all but the latest `kept`.

        Each is named by the time it was kept, then its digest, so the latest
        sort last and the same report is kept once. A room writes the git
        directory, so what it left in the way is replaced, never followed
        (`Confined`), and only what's in the directory itself is forgotten.
        """
        common = self.layout.common
        home = self.layout.reports
        confined = Confined(root=common)
        digest = hashlib.blake2b(report.encode(), digest_size=6).hexdigest()
        name = f"{self.clock.now():%Y%m%dT%H%M%S}-{digest}.txt"
        confined.laid(home.relative_to(common) / name, report.encode())
        for old in sorted(each.name for each in home.glob("*.txt"))[: -self.kept]:
            confined.removed(home.relative_to(common) / old)
        return home / name


class Fitted(Model):
    """A report as a hook tells it, and the standing words it tells (`Words`)."""

    text: str
    words: Words = Words()


def fitted(parts: list[Part], fits: int, reports: Reports) -> Fitted:
    """Say `parts` in `fits` bytes: whole where they fit, else shortened.

    A report past `fits` is kept whole (`reports`) and told with a line saying
    where; then each part that can be shortened is told whole where it still
    fits, in order, and short where it doesn't, so what matters most comes
    whole. Parts always told whole may still take it past `fits`. A part told
    short tells its header and none of its rules' mistakes and steers, which
    its reader is told with the next finding of each.
    """
    whole = text(parts)
    size = len(whole.encode())
    if size <= fits:
        return Fitted(text=whole, words=heard(parts))
    where = reports.keep(whole)
    note = (
        f"lup's report is {size:,} bytes, more than a hook tells whole: it's kept "
        f"whole at {where}, and each section that doesn't fit here says how many "
        "findings each file has."
    )
    whole_at = [part.short is None for part in parts]

    def said(chosen: list[bool]) -> str:
        return sections(
            [
                note,
                *(
                    part.whole if wholly else part.short or ""
                    for part, wholly in zip(parts, chosen, strict=True)
                ),
            ]
        )

    for index, part in enumerate(parts):
        if part.short is None:
            continue
        trial = [*whole_at[:index], True, *whole_at[index + 1 :]]
        if len(said(trial).encode()) <= fits:
            whole_at = trial
    words = [
        part.told(whole=wholly) for part, wholly in zip(parts, whole_at, strict=True)
    ]
    return Fitted(text=said(whole_at), words=reduce(Words.then, words, Words()))


class Refused(Model):
    """One held file the operator declined or left unanswered, put back or never written, its version saved."""

    path: Path
    """The file, by its absolute path."""
    saved: Path
    """Where the agent's version is saved, by its absolute path."""
    new: bool
    """Whether the file didn't exist before the change."""
    declined: str | None = None
    """The operator's comment on a declined hold; empty when they gave none."""
    unanswered: bool = False
    """Whether it was held and nobody answered in time."""
    interrupted: bool = False
    """Whether its call was interrupted while it waited for the operator."""


def finding_lines(
    finding: Finding, indent: str = "  ", *, standing: bool = True
) -> list[str]:
    """Spell one finding as pyright does, with lup's steer beneath it; without its `standing` words, a lup rule's told before (`Words`), in a line saying what its check saw, where the engine told that apart.

    >>> from lup_dev.codescan.contract import Position, Span
    >>> at = Position(line=41, column=12)
    >>> found = Finding(path=Path("a.py"), span=Span(start=at, end=at), owner="lup",
    ...     rule="tuple-shape", message="`tuple[str, int]` is a tuple type. A tuple hides its fields.",
    ...     steer="a model", detail="`tuple[str, int]` is a tuple type")
    >>> finding_lines(found)
    ['  a.py:41:12 - tuple-shape: `tuple[str, int]` is a tuple type. A tuple hides its fields.', '      steer: a model']
    >>> finding_lines(found, standing=False)
    ['  a.py:41:12 - tuple-shape: `tuple[str, int]` is a tuple type']
    """
    start = finding.span.start
    place = f"{finding.path}:{start.line}:{start.column}"
    short = not standing and bool(finding.detail)
    message = finding.detail if short else finding.message
    said = f"{indent}{place} - {finding.rule}: {message}"
    steer = (
        [f"{indent}    steer: {finding.steer}"] if finding.steer and not short else []
    )
    return [said, *steer]


def sections(parts: list[str]) -> str:
    """Join the non-empty parts of a report, a blank line between each."""
    return "\n\n".join(part for part in parts if part)


def refusal(refused: list[Refused]) -> str:
    """Report the held files the operator declined or left unanswered, each with where the agent's version is saved."""
    if not refused:
        return ""
    count = len(refused)
    header = (
        "lup refused 1 file. It is unchanged; your version is saved."
        if count == 1
        else f"lup refused {count} files. They are unchanged; your versions are saved."
    )

    def block(one: Refused) -> str:
        comment = f": {one.declined}" if one.declined else "."
        declined = (
            [f"  The operator declined it{comment}"] if one.declined is not None else []
        )
        unanswered = (
            ["  Nobody answered in time; the hold stays open in the operator's inbox."]
            if one.unanswered
            else []
        )
        interrupted = (
            [
                (
                    "  Its call was interrupted while it waited for the operator; the "
                    "hold stays open in their inbox, and their answer reaches you at "
                    "a later call."
                )
            ]
            if one.interrupted
            else []
        )
        lines = [
            f"{one.path} (saved at {one.saved})",
            *declined,
            *unanswered,
            *interrupted,
        ]
        return "\n".join(lines)

    return sections([header, *(block(one) for one in refused)])


def approval(paths: list[Path], comment: str) -> str:
    """Tell a held change the operator approved, in one line: lup held it for their review, and they approved it, their comment after.

    It says nothing of how long they took: the agent needs to know the
    operator saw the change, not to pace itself on their time.

    >>> approval([Path("/work/AGENTS.md")], "")
    "lup held the write to /work/AGENTS.md for the operator's review, and they approved it."
    >>> approval([Path("/work/a.py"), Path("/work/b.py")], "keep it")
    "lup held the write to /work/a.py, /work/b.py for the operator's review, and they approved it: keep it"
    """
    named = ", ".join(str(path) for path in paths)
    said = f": {comment}" if comment else "."
    return f"lup held the write to {named} for the operator's review, and they approved it{said}"


def information(
    reported: list[Finding],
    findings: list[Finding],
    untouched: list[Finding],
    importers: list[Finding],
    words: Words,
) -> list[Part]:
    """Report what a checkpoint found in the files it judged, to a reader who knows `words`: values never published on the lines changed, lup's findings on them, type errors and ruff's findings, lup's findings elsewhere, and type errors in the files importing them.

    A value never published is told apart from a rule's finding, since no
    `ignore` keeps it: each names its kind, never the value, and its section is
    always told whole. The others can be told short (`fitted`).
    """
    return parts_of(
        [
            Section(
                title="Values never published, on the lines changed",
                instructions=(
                    "rewrite each before it's committed: the operator sees this "
                    "write with them, the gate's `private` step fails on them, and "
                    "a push or a post carrying one is refused"
                ),
                findings=[found for found in reported if found.rule == PRIVATE],
                short=False,
            ),
            Section(
                title="lup's findings on the lines changed",
                instructions=CLEARING,
                findings=[found for found in reported if found.rule != PRIVATE],
            ),
            Section(
                title="Type errors and ruff's findings in the files changed",
                instructions="clean them before the turn ends",
                findings=findings,
            ),
            Section(
                title="lup's findings on lines no change touched",
                instructions="they fail the gate too",
                findings=[found for found in untouched if found.rule != PRIVATE],
            ),
            Section(
                title="Values never published, on lines no change touched",
                instructions="the gate's `private` step fails on them too",
                findings=[found for found in untouched if found.rule == PRIVATE],
                short=False,
            ),
            importing(importers),
        ],
        words,
    )


CLEARING = (
    'clear each, or keep it with `# lup: ignore("<rule>", why="<reason>")` on its '
    "line or the line above, which the operator is asked about; they fail the gate"
)
"""What to do with lup's findings, which their section says after a call and as a quiet lifts."""


def importing(found: list[Finding]) -> Section:
    """Return the section of the type errors in the files importing what changed, after a call and as a quiet lifts."""
    return Section(
        title="Type errors in files that import what changed",
        instructions="clean them before the turn ends",
        findings=found,
    )


def summary(
    touched: list[Finding], importers: list[Finding], words: Words
) -> list[Part]:
    """Say what stands that a conversation wasn't told, as their quiet lifts, to a reader who knows `words`: in the files they touched, values never published, lup's findings, type errors and ruff's; then type errors in the files importing them.

    Which of lup's findings are on lines a change touched isn't said: that's
    what a change's judgement reads, and the files are read as they stand.

    >>> from lup_dev.codescan.contract import Position, Span
    >>> at = Position(line=3, column=1)
    >>> def found(path: str, owner: Owner, rule: str) -> Finding:
    ...     return Finding(path=Path(path), span=Span(start=at, end=at), owner=owner,
    ...         rule=rule, message="m")
    >>> told = summary([found("/w/a.py", "lup", "regex"), found("/w/a.py", "ruff", "E501")],
    ...     [found("/w/b.py", "pyright", "reportCallIssue")], Words())
    >>> print(text(told))
    lup's findings in the files you touched (clear each, or keep it with `# lup: ignore("<rule>", why="<reason>")` on its line or the line above, which the operator is asked about; they fail the gate):
      /w/a.py:3:1 - regex: m
    <BLANKLINE>
    Type errors and ruff's findings in the files you touched (clean them before the turn ends):
      /w/a.py:3:1 - E501: m
    <BLANKLINE>
    Type errors in files that import what changed (clean them before the turn ends):
      /w/b.py:3:1 - reportCallIssue: m
    """
    lup = [each for each in touched if each.owner == "lup"]
    return parts_of(
        [
            Section(
                title="Values never published, in the files you touched",
                instructions=(
                    "rewrite each before it's committed: the gate's `private` step "
                    "fails on them, and a push or a post carrying one is refused"
                ),
                findings=[each for each in lup if each.rule == PRIVATE],
                short=False,
            ),
            Section(
                title="lup's findings in the files you touched",
                instructions=CLEARING,
                findings=[each for each in lup if each.rule != PRIVATE],
            ),
            Section(
                title="Type errors and ruff's findings in the files you touched",
                instructions="clean them before the turn ends",
                findings=[each for each in touched if each.owner != "lup"],
            ),
            importing(importers),
        ],
        words,
    )


def removed_notes(notes: list[RemovedNote]) -> str:
    """Report the notes present when the session started that are gone since."""
    if not notes:
        return ""
    return "\n".join(
        [
            (
                "Notes present when the session started were removed; "
                "list them in your report and in the merge commit's message:"
            ),
            *(f"  {note.path}: # lup: {note.text}" for note in notes),
        ]
    )


class MovedFile(Model):
    """One file a move of `HEAD` brought, judged once as its commits'."""

    path: Path
    """The file, by its absolute path."""
    findings: list[Finding] = []
    """lup's findings on the lines its commits touched."""
    asks: list[Ask] = []
    removed: list[RemovedNote] = []
    """Notes it had before the move that its commits removed."""


class Moved(Model):
    """A move of `HEAD` whose commits brought content no checkpoint had judged."""

    worktree: Path
    head: str | None
    """The commit `HEAD` moved to; none where it names no commit."""
    files: list[MovedFile]
    hold: str | None = None
    """The hold asking the operator about it after the fact, if it asks."""


def moved(moves: list[Moved], words: Words) -> list[Part]:
    """Tell what moves of `HEAD` brought, to a reader who knows `words`: judged once, and left as committed, each lup rule's mistake and steer told once (`Words`); nothing where they brought no finding, ask or removed note."""
    found = [
        finding for move in moves for each in move.files for finding in each.findings
    ]
    firsts = words.firsts(found)

    def one(move: Moved) -> str:
        told = [
            each for each in move.files if each.findings or each.asks or each.removed
        ]
        if not told:
            return ""
        files = [
            line
            for each in told
            for line in [
                str(each.path),
                *(
                    line
                    for finding in each.findings
                    for line in finding_lines(finding, standing=finding in firsts)
                ),
                *(f"  asks: {ask.reason}" for ask in each.asks),
                *(f"  removes the note: # lup: {note.text}" for note in each.removed),
            ]
        ]
        gate = (
            ["lup's findings in them fail the gate: fix them in a later commit."]
            if any(each.findings for each in told)
            else []
        )
        asked = (
            [
                (
                    "The operator is asked about the rest after the fact, in their "
                    f"inbox (hold {move.hold})."
                )
            ]
            if move.hold
            else []
        )
        header = (
            f"HEAD moved to {move.head or 'no commit'} in {move.worktree}, bringing "
            "content no checkpoint judged. It was judged once, as its commits', "
            "and stays as committed:"
        )
        return "\n".join([header, *files, *gate, *asked])

    said = sections([one(move) for move in moves])
    return [Part(whole=said, words=words.taught(found))] if said else []


def turn_end(findings: list[Finding]) -> list[Part]:
    """Say why the turn can't end: what's still wrong in the files they touched, every finding whole, each lup rule's mistake and steer however often its reader was told them, or a line per file where that doesn't fit (`fitted`)."""
    if not findings:
        return []
    header = (
        "lup won't end the turn yet: files you touched have "
        "lup's findings, type errors or ruff findings."
    )
    footer = (
        "Fix them, or keep one with "
        '`# lup: ignore("<rule>", why="<reason>")` '
        "on its line or the line above (the operator is asked)."
    )
    lines = [line for found in findings for line in finding_lines(found)]
    return [
        Part(
            whole="\n".join([header, *lines, footer]),
            short="\n".join([counted(header, findings), footer]),
            words=Words().taught(findings),
        )
    ]


def judge_failed(failure: Exception) -> str:
    """Warn the operator that the judge failed at a turn's end, which ended anyway.

    >>> judge_failed(RuntimeError("the engine crashed")).startswith("lup's judge")
    True
    """
    return (
        f"lup's judge failed at a turn's end, so that end wasn't judged: {failure!r}. "
        "The turn ended, since the agent can't fix the judge: approving the running "
        "branch's tip (`lup-dev trust`), or fixing what the error names, is yours. "
        "You're told once for each failure in a session."
    )
