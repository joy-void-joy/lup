"""Citations of the operator's words in what an agent sends them: `@820.9[first words … last words]`, each resolved against the operator's words sent to the agent's conversation.

`docs/inbox.md`, *Citing the operator's words*. An agent answers the operator
in their own words, and may point at the operator's inline: a part of one of
the operator's items by its id, as `@414.3` cites a part already, with the
passage they mean named
by its first and last words between brackets, as a browser's text fragment
names one (`#:~:text=start,end`); its words alone where they're short
(`@820.9[why not split it]`); the item's number alone where the tag gave the
part no id (`@820[…]`), any of its parts read. An id with no brackets cites the
part whole, where it's one of the operator's words to the conversation; any
other is the inbox's own citation of an item or a part, and isn't read here.

Each is read where Markdown reads text, by an inline rule of markdown-it, the
parser the inbox reads an item's parts with (`inbox/parts.py`), so none is read
in code, and a backslash written before its `@` keeps it as text (`written`);
and it's resolved against the parts of the operator's items addressed to the
conversation (`spoken`, `inbox/threads.py`): found where its words read one
place, case aside, any run of white space for one, a straight or a curly quote
for either, from a word's start to a word's end (`places`). One that reads
none, or several, is kept as written with the places it might mean
(`Citation.candidates`): the message is never held back for it, and the agent
is told (`unresolved`).
"""

import itertools
from collections import Counter
from typing import TYPE_CHECKING, Literal, Self

from markdown_it import MarkdownIt

from lup.types import Model
from lup_dev.inbox.parts import Lines
from lup_dev.inbox.store import Citation, Place
from lup_dev.inbox.tags import Tag
from lup_dev.inbox.threads import Anchor, cue

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from markdown_it.rules_inline import StateInline


class Said(Model):
    """What an inline rule read, as it's written; where it is in the text it's in, once it's placed (`placed`)."""

    said: str
    before: int = 0
    """How many times the same is written before it in the inline text it's
    read in, code among it, which places it in the text whole."""
    start: int = 0
    end: int = 0


class Written(Said):
    """A citation as it's written: the citation whole, what it names, and its words; where it is in the text it's in, once it's placed (`written`)."""

    item: int
    part: int | None = None
    words: str | None = None
    first: str = ""
    """Its words before an ellipsis, or its words whole where there's none."""
    last: str = ""
    """Its words after an ellipsis; none where there's none."""


class Parted(Model):
    """A citation's words: its first, and its last where an ellipsis parts them; none where it has no ellipsis."""

    first: str
    last: str


class Scanned(Model):
    """What a scan of an inline text read from one place: the characters, and where the scan stopped."""

    text: str
    at: int


def scanned(src: str, at: int, takes: Callable[[str], bool]) -> Scanned:
    """Read the characters of `src` from `at` as long as `takes` takes each.

    >>> scanned("@820.9", 1, str.isdigit)
    Scanned(text='820', at=4)
    """
    text = "".join(itertools.takewhile(takes, itertools.islice(src, at, None)))
    return Scanned(text=text, at=at + len(text))


def bracketed(src: str, at: int) -> Scanned | None:
    """Read what's between the brackets opening at `at` of `src`, on its line; none where no bracket opens there, or none closes it on its line.

    >>> bracketed("[first … last] then", 0)
    Scanned(text='first … last', at=14)
    """
    if at >= len(src) or src[at] != "[":
        return None
    inside = scanned(src, at + 1, lambda char: char not in "]\n")
    if inside.at >= len(src) or src[inside.at] != "]":
        return None
    return Scanned(text=inside.text, at=inside.at + 1)


def opens(src: str, at: int) -> bool:
    """Say whether a citation may start at `at` of `src`: an `@` with no letter, digit, `@` or `_` just before it, as an address's has."""
    after_word = at > 0 and (src[at - 1].isalnum() or src[at - 1] in "@_")
    return src[at] == "@" and not after_word


def parted(src: str, start: int, end: int) -> Parted:
    """Read a citation's words, from `start` to `end` of `src`: its first words and its last, where an ellipsis, `…` or `...`, parts them; else its words, and no last.

    >>> parted("[why … it]", 1, 9), parted("[why it]", 1, 7)
    (Parted(first='why', last='it'), Parted(first='why it', last=''))
    """

    def read(begin: int, until: int) -> str:
        return "".join(itertools.islice(src, begin, until)).strip()

    for mark in ["…", "..."]:
        cut = src.find(mark, start, end)
        if cut >= 0:
            return Parted(first=read(start, cut), last=read(cut + len(mark), end))
    return Parted(first=read(start, end), last="")


type Asked = Literal["read", "seen"]
"""What markdown-it asks an inline rule: to read what's there, leaving a token;
or only whether something is there, leaving none."""

type Reading = Callable[[StateInline, Asked], bool]
"""An inline rule of lup's: what it's asked said by name (`Asked`)."""

type Rule = Callable[[StateInline, bool], bool]
"""An inline rule as markdown-it calls it: `rule(state, silent)`."""


def ruled(reading: Reading) -> Rule:
    """Return `reading` as markdown-it calls an inline rule, its flag read as what it asks (`Asked`): the one place lup's rules take that flag positional."""

    # lup: ignore("FBT001", why="markdown-it calls each inline rule as `rule(state, silent)`, its flag positional")
    def rule(state: StateInline, silent: bool) -> bool:
        return reading(state, "seen" if silent else "read")

    return rule


def citing(state: StateInline, asked: Asked) -> bool:
    """Read a citation at the inline position `state` is at, as markdown-it's inline rules do: `@`, an item's number, a part's after a dot, the words between brackets on its line; one with neither a part nor words is an item's citation, read by nobody here.

    The token it leaves carries what it read (`Written`), and how many times
    the same citation is written before it in the inline text, so it's
    placed in the text whole; where it's `seen`, markdown-it only asks whether
    one is there, and none is left.
    """
    src, start = state.src, state.pos
    if not opens(src, start):
        return False
    item = scanned(src, start + 1, str.isdigit)
    if not item.text:
        return False
    part = None
    at = item.at
    if at + 1 < len(src) and src[at] == "." and src[at + 1].isdigit():
        read = scanned(src, at + 1, str.isdigit)
        part, at = read.text, read.at
    words = bracketed(src, at)
    if part is None and words is None:
        return False
    if words is not None:
        at = words.at
    said = "".join(
        [
            f"@{item.text}",
            "" if part is None else f".{part}",
            "" if words is None else f"[{words.text}]",
        ]
    )
    if asked == "read":
        read = (
            Parted(first="", last="")
            if words is None
            else parted(src, words.at - len(words.text) - 1, words.at - 1)
        )
        token = state.push("citation", "", 0)
        token.content = said
        token.meta = Written(
            said=said,
            item=int(item.text),
            part=None if part is None else int(part),
            words=None if words is None else words.text,
            first=read.first,
            last=read.last,
            before=src.count(said, 0, start),
        ).model_dump()
    state.pos = at
    return True


def reader() -> MarkdownIt:
    """Return the Markdown reader citations are read with: CommonMark with GitHub's tables and strikethrough, as an item's parts are read (`inbox/parts.py`), and the inline rule reading a citation (`citing`)."""
    made = MarkdownIt("commonmark").enable(["table", "strikethrough"])
    made.inline.ruler.push("citation", ruled(citing))
    return made


CITING = reader()
"""Reads a text's citations, where Markdown reads its text."""


def written(text: str) -> list[Written]:
    """Return each citation of the operator's words in `text`, in order, where it's written: one with words between brackets, or a part's id alone; none in code.

    >>> [(each.said, each.start) for each in written("On @820.9[why … it], @820[all], @414.3 and @7: `@1.2`.")]
    [('@820.9[why … it]', 3), ('@820[all]', 21), ('@414.3', 32)]
    """
    return placed(text, CITING, "citation", Written)


def placed[S: Said](
    text: str, reading: MarkdownIt, kind: str, read: type[S]
) -> list[S]:
    """Return what the inline rule of `reading` leaves in `text` as tokens of `kind`, each read as `read`, in order, where it's written.

    Each inline text Markdown reads is found where its first line is, from the
    lines its block spans on, and each token in it where what it says is
    written the same number of times after that as in the inline text.
    """
    lines = Lines.of(text)

    def made() -> Generator[S]:
        cursor = 0
        for token in reading.parse(text):
            if token.type != "inline" or token.map is None or not token.content:
                continue
            first, until = token.map
            bound = lines.starts[until]
            opening = next(iter(token.content.splitlines()), "")
            found = text.find(opening, max(cursor, lines.starts[first]), bound)
            if found < 0:
                continue
            cursor = found + len(opening)
            for child in token.children or []:
                if child.type != kind:
                    continue
                each = read.model_validate(child.meta)
                at = found
                for _ in range(each.before + 1):
                    at = text.find(each.said, at, bound) + len(each.said)
                yield each.model_copy(update={"start": at - len(each.said), "end": at})

    return list(made())


def straight(char: str) -> str:
    r"""Return a quote as it's compared, straight; any other character as it is.

    >>> straight("\u2019"), straight("x")
    ("'", 'x')
    """
    match char:
        case "\u2018" | "\u2019":
            return "'"
        case "\u201c" | "\u201d":
            return '"'
        case _:
            return char


class Stretch(Model):
    """Where a stretch of a text is: from `start` to `end`, counted in characters."""

    start: int
    end: int


class Char(Model):
    """One character of a folded text, and where it came from in the text folded."""

    char: str
    origin: int


class Folded(Model):
    """A text as it's compared: case aside, its quotes straight, each run of white space one space; with where each of its characters came from in the text it was folded from."""

    text: str
    origins: list[int]
    """For each character of `text`, where it came from in `source`."""
    source: str

    @classmethod
    def of(cls, source: str) -> Self:
        r"""Fold `source`.

        >>> Folded.of("Don\u2019t  Split").text
        "don't split"
        """

        def chars() -> Generator[Char]:
            spaced = False
            for at, char in enumerate(source):
                if char.isspace():
                    if not spaced:
                        yield Char(char=" ", origin=at)
                    spaced = True
                    continue
                spaced = False
                for each in straight(char).casefold():
                    yield Char(char=each, origin=at)

        folded = list(chars())
        text = "".join(each.char for each in folded)
        origins = [each.origin for each in folded]
        return cls(text="".join(text), origins=origins, source=source)

    def bounded(self, stretch: Stretch) -> bool:
        """Say whether `stretch` of the source starts and ends at a word's edge: no letter or digit just outside it."""
        before = stretch.start == 0 or not self.source[stretch.start - 1].isalnum()
        after = (
            stretch.end >= len(self.source) or not self.source[stretch.end].isalnum()
        )
        return before and after

    def found(self, words: str, start: int = 0) -> list[Stretch]:
        """Return where `words`, folded, read in the source from `start` on, a word's edge on each side, in order."""
        needle = Folded.of(words.strip()).text
        if not needle:
            return []

        def found() -> Generator[Stretch]:
            at = self.text.find(needle, self.folded(start))
            while at >= 0:
                stretch = Stretch(
                    start=self.origins[at],
                    end=self.origins[at + len(needle) - 1] + 1,
                )
                if self.bounded(stretch):
                    yield stretch
                at = self.text.find(needle, at + 1)

        return list(found())

    def folded(self, start: int) -> int:
        """Return where the source's offset `start` is in the folded text: its first character from there on."""
        return next(
            (at for at, origin in enumerate(self.origins) if origin >= start),
            len(self.text),
        )

    def passage(self, stretch: Stretch) -> str:
        """Return `stretch` of the source, as written."""
        # lup: ignore("string-slice", why="the passage is the source's own characters between offsets found in that very source a moment before, never offsets kept across a change")
        return self.source[stretch.start : stretch.end]


def places(anchor: Anchor, first: str, last: str) -> list[Place]:
    """Return each passage of `anchor`'s text a citation's words read, in order: from its `first` words to its `last`, each start with the first end after it; its first words alone where it has no last. None for no words.

    >>> from lup_dev.inbox.parts import PartId
    >>> said = Anchor(id=PartId(item=8, part=1), text="Split it. Then split the reader out.")
    >>> [each.text for each in places(said, "split", "out")]
    ['Split it. Then split the reader out', 'split the reader out']
    >>> [each.text for each in places(said, "plit", "")]
    []
    """
    if not first:
        return []
    folded = Folded.of(anchor.text)

    def ended(start: Stretch) -> Stretch | None:
        if not last:
            return start
        return next(
            (
                Stretch(start=start.start, end=each.end)
                for each in folded.found(last, start.start)
                if each.end >= start.end
            ),
            None,
        )

    return [
        Place(
            part=anchor.id,
            start=stretch.start,
            end=stretch.end,
            text=folded.passage(stretch),
        )
        for start in folded.found(first)
        if (stretch := ended(start)) is not None
    ]


def whole(anchor: Anchor) -> Place:
    """Return `anchor`'s text whole, as a place."""
    return Place(part=anchor.id, start=0, end=len(anchor.text), text=anchor.text)


def resolved(text: str, said: list[Anchor]) -> list[Citation]:
    """Return each citation of the operator's words in `text`, outside code, resolved against `said`, the parts of the operator's items addressed to the conversation that wrote it.

    A part's id alone cites it whole, and one naming none of `said` isn't a
    citation of the operator's words, but the inbox's own. With words: the
    passage they read in the part named, or in any part of the item named
    alone, where they read one; else none found, and each place they read
    elsewhere among `said` a candidate, or each of the several they read.
    """

    def cited(each: Written) -> Citation | None:
        named = [
            anchor
            for anchor in said
            if anchor.id.item == each.item
            and (each.part is None or anchor.id.part == each.part)
        ]
        head = each.model_dump(exclude={"before": True, "first": True, "last": True})
        if each.words is None or not each.words.strip():
            match named:
                case [only]:
                    return Citation(**head, found=whole(only))
                case [] if each.words is None:
                    return None
                case _:
                    return Citation(**head, candidates=[whole(one) for one in named])
        here = [
            place for anchor in named for place in places(anchor, each.first, each.last)
        ]
        match here:
            case [only]:
                return Citation(**head, found=only)
            case []:
                elsewhere = [
                    place
                    for anchor in said
                    if anchor not in named
                    for place in places(anchor, each.first, each.last)
                ]
                return Citation(**head, candidates=elsewhere)
            case several:
                return Citation(**head, candidates=several)

    return [citation for each in written(text) if (citation := cited(each)) is not None]


def failing(citations: list[Citation]) -> list[Citation]:
    """Return those of `citations` that found no passage: none, or several."""
    return [each for each in citations if each.found is None]


def unresolved(citations: list[Citation], number: int) -> list[Tag | str]:
    """Say which of the citations in item `number` found no passage, each with the places it might mean, and how to fix them: what a tool's answer and lup's word at a turn's end say. Nothing where each found one."""
    missed = failing(citations)
    if not missed:
        return []
    told: list[Tag | str] = [
        Tag(name="citation", attributes={"said": each.said}, parts=[missing(each)])
        for each in missed
    ]
    return [opening(missed, number), *told, fixing(number)]


def plainly(citations: list[Citation], number: int) -> str:
    """Say what `unresolved` says, as lines of text rather than tags: where an item is listed or read as its sender wrote it."""
    missed = failing(citations)
    told = [f"{each.said}: {missing(each)}" for each in missed]
    return "\n".join([opening(missed, number), *told, fixing(number)])


def opening(missed: list[Citation], number: int) -> str:
    """Say how many citations in item `number` name no one passage, `missed`, and that it reached the operator all the same."""
    count = "A citation" if len(missed) == 1 else f"{len(missed)} citations"
    verb = "doesn't" if len(missed) == 1 else "don't"
    return (
        f"{count} in @{number} {verb} name one passage of the operator's words to "
        "you: it reached them as you wrote it, shown as written and marked as not "
        "found."
    )


def fixing(number: int) -> str:
    """Say how the agent mends citations in item `number` that name no one passage."""
    return (
        f"`edit` @{number} to name the place you meant, or to drop the citation: "
        "the edit's answer says what still doesn't resolve."
    )


def missing(citation: Citation) -> str:
    """Say what a citation that found no passage found instead: nothing; several places where it points, and that more of the words name one; or each place its words read elsewhere.

    >>> from lup_dev.inbox.parts import PartId
    >>> one = Place(part=PartId(item=820, part=2), start=0, end=5, text="Split")
    >>> missing(Citation(said="@820.9[split]", start=0, end=13, item=820, part=9, words="split", candidates=[one]))
    'Nothing in @820.9 reads it; it reads @820.2: “Split”.'
    >>> missing(Citation(said="@820[split]", start=0, end=11, item=820, words="split", candidates=[one, one]))
    'It reads 2 places in @820, in @820.2 twice: give more of the words, so they read one.'
    """
    named = f"@{citation.item}" + ("" if citation.part is None else f".{citation.part}")
    inside = [
        each
        for each in citation.candidates
        if each.part.item == citation.item
        and (citation.part is None or each.part.part == citation.part)
    ]
    if not citation.candidates:
        reading = (
            "" if citation.part is None else f"; `inbox` with `part` reads {named}"
        )
        return f"Nothing of the operator's words to you reads it{reading}."
    if len(inside) == len(citation.candidates):
        counted = Counter(each.part.cited() for each in citation.candidates)
        where = ", ".join(
            part if times == 1 else f"{part} {times_said(times)}"
            for part, times in counted.items()
        )
        many = len(citation.candidates)
        return (
            f"It reads {many} places in {named}, in {where}: give more of the "
            "words, so they read one."
        )
    places = "; ".join(
        f"{each.part.cited()}: “{cue(each.text, 200)}”" for each in citation.candidates
    )
    return f"Nothing in {named} reads it; it reads {places}."


def times_said(times: int) -> str:
    """Say how many times something is: `twice`, `3 times`.

    >>> times_said(2), times_said(3)
    ('twice', '3 times')
    """
    return "twice" if times == 2 else f"{times} times"
