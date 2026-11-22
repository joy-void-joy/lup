"""What an agent is told right after a write: what the write introduced on the lines it changed, each finding once, as type errors are told (`README.md` here, *Told after a write*).

Of what a check of the files written finds:
- **told** is what first appears on a line the write changed: lup's design
  rules' findings, pyright's and ruff's, each once in a conversation, a rule's
  reason and steer with its first finding and a line after;
- **counted** is what stands elsewhere in those files, in a line saying how
  to list it;
- **held back** is what a half-finished edit leaves (a name used before its
  import is written, an import written before its use), told only if it
  still stands once the agent's writes pause, at their next call that isn't a
  write;
- **never told** is what the gate's `--fix` fixes, a spelling rule's or a
  heuristic's finding, which the gate lists, and pyright's unknown types
  following another error of the same file, which are counted under it.
"""

import difflib
from datetime import datetime
from typing import Literal

from lup.code_rules.checking import Checked, Table
from lup.code_rules.reporting import line
from lup.code_rules.reports import Finding
from lup.types import Model, MutableModel

type Kept = Literal["told", "held"]


class Key(Model):
    """What a finding is known by in a conversation, across edits that move it: its file, owner, rule and what it says, and the text of its line rather than its number."""

    path: str
    owner: str
    rule: str
    said: str
    text: str


type Became = Literal["told", "fixed", "kept"]
"""What became of a finding told after a write: told, then gone from its line
by a later write, or kept there by an `ignore`. One told and neither, left
for the gate."""


class Ended(Model):
    """A finding told after a write that a later check found gone, or kept by an `ignore`."""

    key: Key
    became: Became


class Outcome(Model):
    """One thing that became of a finding told after a write, as lup records it for the next review of its rules."""

    at: datetime
    agent: str
    path: str
    owner: str
    rule: str
    text: str
    """The text of its line, which it's known by across edits."""
    became: Became


class Conversation(MutableModel):
    """What one conversation has been told, and what waits for their writes to pause."""

    watched: list[Key] = []
    """What they were told after a write that's neither gone nor kept yet."""
    told: list[Key] = []
    explained: list[str] = []
    """The rules whose reason and steer they've been told."""
    quietly: list[str] = []
    """The files they wrote while quiet, by their paths from the root, told
    once they lift it."""
    held: list[Finding] = []
    """What their half-finished edits left, by the latest check of each file,
    told if it still stands when their writes pause."""


class Telling(Model):
    """How findings are told after a write: which wait for writes to pause, which follow from another, and how long a report may run."""

    table: Table
    paused: list[str] = [
        "reportUndefinedVariable",
        "reportUnusedImport",
        "reportUnusedExpression",
    ]
    """pyright's findings a half-finished edit leaves, held until writes
    pause: none of 2,400 such was still there at a turn's end in the second
    lup's records."""
    following: str = "reportUnknown"
    """What pyright's rules naming an unknown type start with: most follow from
    another error of the file, an unresolved name, so they're counted under
    it."""
    longest: int = 2000
    """The most a report says in full, in characters: past it, how many
    findings each file has, and how to list them."""

    def changed(self, before: str, after: str) -> list[int]:
        """Return the lines of `after`, counted from 1, that a change from `before` wrote."""
        matcher = difflib.SequenceMatcher(
            a=before.splitlines(), b=after.splitlines(), autojunk=False
        )
        return [
            number + 1
            for tag, _, _, start, end in matcher.get_opcodes()
            if tag in ["replace", "insert"]
            for number in range(start, end)
        ]

    def heard(
        self,
        conversation: Conversation,
        checked: Checked,
        before: str,
        after: str,
    ) -> list[Finding]:
        """Return what a write to `checked`'s file, from `before` to `after`, introduced and isn't told yet, keeping in `conversation` what waits for writes to pause."""
        changed = self.changed(before, after)
        lines = after.splitlines()
        told = [
            each
            for each in checked.standing
            if each.category == "design"
            and not each.fixable
            and each.span.start.line in changed
            and key(each, lines) not in conversation.told
        ]
        paused = [each for each in told if each.rule in self.paused]
        held = [
            each
            for each in told
            if each.rule in self.paused
            or (paused and each.rule.startswith(self.following))
        ]
        conversation.held = [
            *(each for each in conversation.held if each.path != checked.path),
            *held,
        ]
        return [each for each in told if each not in held]

    def elsewhere(
        self,
        conversation: Conversation,
        checked: Checked,
        introduced: list[Finding],
        text: str,
    ) -> int:
        """Return how many findings failing the gate stand in `checked`'s file beyond those just told and those waiting, which the conversation wasn't told: what's counted in a line."""
        lines = text.splitlines()
        return len(
            [
                each
                for each in checked.failing()
                if not each.fixable
                and each not in introduced
                and each not in conversation.held
                and key(each, lines) not in conversation.told
            ]
        )

    def became(
        self, conversation: Conversation, checked: Checked, text: str
    ) -> list[Ended]:
        """Return what became of each finding told in `checked`'s file that a check of it, `text` as it stands, doesn't find standing: gone, or kept by an `ignore`. Those still standing stay watched."""
        lines = text.splitlines()
        standing = [key(each, lines) for each in checked.standing]
        kept = [key(each.finding, lines) for each in checked.kept]
        ended = [
            each
            for each in conversation.watched
            if each.path == checked.path and each not in standing
        ]
        conversation.watched = [
            each for each in conversation.watched if each not in ended
        ]
        return [
            Ended(key=each, became="kept" if each in kept else "fixed")
            for each in ended
        ]

    def released(
        self, conversation: Conversation, texts: dict[str, str]
    ) -> list[Finding]:
        """Return what waited for writes to pause and isn't told yet, `texts` holding each file's text as it stands, emptying what waited."""
        waited = [
            each
            for each in conversation.held
            if key(each, texts.get(each.path, "").splitlines()) not in conversation.told
        ]
        conversation.held = []
        return waited

    def said(
        self,
        conversation: Conversation,
        findings: list[Finding],
        texts: dict[str, str],
        elsewhere: dict[str, int],
        *,
        title: str = "lup's findings on the lines you changed",
    ) -> str | None:
        """Return the words telling `findings`, each file's count of what stands `elsewhere`, and record them told in `conversation`; none where there's nothing to say."""
        if not findings and not any(elsewhere.values()):
            return None
        errors = [
            each
            for each in findings
            if each.owner == "pyright" and not each.rule.startswith(self.following)
        ]
        folded = [
            each
            for each in findings
            if each.rule.startswith(self.following)
            and any(error.path == each.path for error in errors)
        ]
        shown = [each for each in findings if each not in folded]
        ordered = sorted(
            shown,
            key=lambda each: (each.owner != "lup", each.path, each.span.start.line),
        )
        firsts = {
            each.rule: at
            for at, each in reversed(list(enumerate(ordered)))
            if each.owner == "lup" and each.rule not in conversation.explained
        }

        def lines() -> list[str]:
            said = [f"  {line(each)}" for each in ordered]
            for at, each in reversed(list(enumerate(ordered))):
                rule = self.table.rules.get(each.rule)
                if firsts.get(each.rule) == at and rule is not None:
                    said.insert(
                        at + 1, f"      {rule.mistake}\n      steer: {rule.steer}"
                    )
            return said

        parts = [
            f"{title} (fix each, or keep one with "
            '`# lup: ignore("<rule>", why="<reason>")` on its line or alone '
            "above it):"
            if ordered
            else "",
            *lines(),
            *(
                f"  and {count} of pyright's unknown types following from the "
                f"errors in {path}"
                for path, count in counted(folded).items()
            ),
            *(
                f"{count} more finding{'' if count == 1 else 's'} stand"
                f"{'s' if count == 1 else ''} elsewhere in {path}: "
                f"`lup code-rules check {path}` lists them."
                for path, count in elsewhere.items()
                if count
            ),
        ]
        words = "\n".join(each for each in parts if each)
        if len(words) > self.longest:
            words = self.short(findings, elsewhere)
        keys = [key(each, texts.get(each.path, "").splitlines()) for each in findings]
        conversation.told.extend(keys)
        conversation.watched.extend(keys)
        conversation.explained.extend(firsts)
        return words

    def short(self, findings: list[Finding], elsewhere: dict[str, int]) -> str:
        """Return a report too long to say whole as how many findings each file has, and how to list them."""
        found = counted(findings)
        files = list(dict.fromkeys([*found, *elsewhere]))
        return "\n".join(
            [
                "lup's findings on the lines you changed, too many to say here:",
                *(
                    f"  {path}: {found.get(path, 0)} on the lines changed, "
                    f"{elsewhere.get(path, 0)} elsewhere; "
                    f"`lup code-rules check {path}` lists them."
                    for path in files
                ),
            ]
        )


def key(finding: Finding, lines: list[str]) -> Key:
    """Return what `finding` is known by, `lines` being its file's as it stands."""
    number = finding.span.start.line
    text = lines[number - 1].strip() if 0 < number <= len(lines) else ""
    return Key(
        path=finding.path,
        owner=finding.owner,
        rule=finding.rule,
        said=finding.detail or finding.message,
        text=text,
    )


def counted(findings: list[Finding]) -> dict[str, int]:
    """Return how many of `findings` each file has, by its path, in the order they come."""
    paths = list(dict.fromkeys(each.path for each in findings))
    return {path: sum(each.path == path for each in findings) for path in paths}
