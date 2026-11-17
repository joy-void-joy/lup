"""The shell's promises on its Python side: what a module's views and their readers can count on.

Each is checked through the harness over an example module defined here, a
pile of notes, started as a project's declaration starts it and its views read
as a party reads them. The page's own laws, about its cursor, its modes and its
folds, are the page's, in TypeScript (`README.md` here, *Promises*).
"""

import asyncio

from pydantic import Field

import lup
from lup import (
    Agent,
    Blocks,
    Commented,
    Fold,
    FoldKind,
    Folds,
    Line,
    Markdown,
    Model,
    Module,
    Modules,
    Offer,
    Operator,
    Part,
    Parts,
    Project,
    ProjectError,
    Span,
    Tone,
    Tones,
    Viewing,
)
from lup.inbox.said import PartyOf, Pile
from lup.testing import (
    Accepted,
    Answered,
    Comment,
    Delivered,
    Drafted,
    Hello,
    Opened,
    Page,
    Quote,
    Refused,
    Send,
    Started,
    Testing,
    Unanswered,
    Watch,
    Write,
    raises,
)


class PileOf(Model):
    """Which pile of notes to show."""

    pile: str


class NoteOf(Model):
    """Which note to show whole."""

    number: int


class Clearing(Model):
    """The note to clear."""

    number: int


class NotesPart(Part):
    """A pile of notes, each a fold under its title, its text read as it opens, and the comments it took."""

    module: Notes
    heard: list[str] = []
    """What each comment it took said, in the order they came."""
    released: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set once the comments it holds may go through, where its module holds
    them (`Notes.holding`)."""

    @lup.view
    async def pile(self, of: PileOf) -> Blocks:
        """Show a pile's notes, each under its title."""
        return Blocks.of(
            *(
                Fold(
                    id=f"note-{number}",
                    kind="note",
                    summary=[Span(text=title, tone="title")],
                    content=Viewing.of(NotesPart.note, NoteOf(number=number)),
                    offers=[
                        Offer.of(NotesPart.clear, Clearing(number=number)),
                        Offer.of(NotesPart.comment, NoteOf(number=number)),
                    ],
                )
                for number, title in enumerate(self.titles(), start=1)
            ),
            summary=[Span(text=f"{of.pile} · {len(self.titles())} notes")],
        )

    @lup.view
    async def note(self, of: NoteOf) -> Blocks:
        """Show a note's text."""
        return Blocks.of(Markdown(id=f"text-{of.number}", text=f"note {of.number}"))

    @lup.view
    async def unknown(self, of: PileOf) -> Blocks:
        """Show a line in a tone nobody declares."""
        return Blocks.of(Line(id="1", spans=[Span(text=of.pile, tone="neon")]))

    @lup.view
    async def reaching(self, of: PileOf) -> Blocks:
        """Show a line that reaches the pile's own pile in the inbox, and one that reaches no party, neither offering a comment of its own."""
        return Blocks.of(
            Line(
                id="reaches",
                spans=[Span(text=f"what {of.pile} reaches")],
                reaches=Pile(repository="harness", path=f"notes/{of.pile}"),
            ),
            Line(id="alone", spans=[Span(text="what reaches no one")]),
        )

    @lup.view
    async def taken(self, of: PileOf) -> Blocks:
        """Show what each comment the pile took said, a line each, in the order they came."""
        return Blocks.of(
            *(
                Line(id=str(at), spans=[Span(text=words)])
                for at, words in enumerate(self.heard)
            ),
            summary=[Span(text=f"{of.pile} · {len(self.heard)} comments")],
        )

    def titles(self) -> list[str]:
        """Return the notes' titles, in order."""
        return [
            f"{self.module.titled} {number}"
            for number in range(1, self.module.notes + 1)
        ]

    @lup.command(verb="done", says="clear it")
    async def clear(self, clearing: Clearing, by: lup.Operator) -> str:
        """Clear a note."""
        return f"cleared {clearing.number}"

    @lup.command(verb="comment", says="comment on it")
    async def comment(self, commented: Commented[NoteOf], by: lup.Operator) -> str:
        """Take a comment on a note, once the pile lets comments through where it holds them."""
        del by
        if self.module.holding:
            await self.released.wait()
        self.heard.append(commented.words)
        return f"note {commented.on.number}: {commented.words}"

    @lup.command(verb="release", says="let the comments held through")
    async def release(self, of: PileOf, by: lup.Operator) -> str:
        """Let every comment held, and every one after, through."""
        del by
        self.released.set()
        return f"{of.pile}: comments let through"


class Notes(Module):
    """Notes in a pile: an example module the shell's promises read views of."""

    name = "notes"
    notes: int = 0
    """How many notes the pile holds, each titled by its number."""
    titled: str = "note"
    """What each note's title says before its number."""
    holding: bool = False
    """Whether a comment waits to be taken until the pile releases them
    (`release`): what keeps a send running while a promise writes beside it."""
    folds: Folds = Folds.of(FoldKind(name="note", letter="n", called="note", level=1))
    tones: Tones = Tones.of(Tone(name="title", like="strong"))
    parts: Parts = Parts.of(NotesPart)


class Echoes(Module):
    """Another module, declaring a fold kind on a letter the notes' takes."""

    name = "echoes"
    folds: Folds = Folds.of(FoldKind(name="echo", letter="n", called="echo"))


def noted(notes: int, *, holding: bool = False, titled: str = "note") -> Project:
    """Return a project of lup's default modules and a pile of `notes` notes titled `titled` and their number, the dashboard's document its pile, holding the comments it takes until released where `holding`.

    `lup.Core` is read as it's called, not imported with the module: the core
    lists these promises, so it's still being made as this module is.
    """
    document = Viewing(module="notes", view="pile", given={"pile": "p"})
    return Project(
        modules=Modules.default()
        .edit(lup.Core(document=document))
        .add(Notes(notes=notes, holding=holding, titled=titled))
    )


class Drawn(Model):
    """How many notes a pile holds, as a promise draws it."""

    notes: int = Field(ge=0, le=20)


class ShellPromises(Part):
    """What a module's views and their readers can count on of the shell's Python side."""

    @lup.promise
    async def a_view_answers_its_blocks_to_whoever_may_read_it(
        self, by: Testing
    ) -> None:
        """A view read by the operator or an agent answers its blocks, each fold of a kind and offering what the module offers on it."""
        notes = by.any(Drawn).notes
        started = await by.started(noted(notes))
        for reader in [Operator(), by.any(Agent)]:
            answered = await started.view("notes", "pile", PileOf(pile="p"), reader)
            assert isinstance(answered, Accepted)
            assert isinstance(answered.output, Blocks)
            folds = [each for each in answered.output.blocks if isinstance(each, Fold)]
            assert len(folds) == notes
            assert all(fold.kind == "note" for fold in folds)
            assert all(
                any(
                    offer.verb == "done" and offer.command == "clear"
                    for offer in fold.offers
                )
                for fold in folds
            )

    @lup.promise
    async def a_view_says_in_text_what_the_operator_sees(self, by: Testing) -> None:
        """A view's text form says its summary, then each block, a fold read as it opens as its summary with the view that shows what's under it."""
        notes = by.any(Drawn).notes
        started = await by.started(noted(notes))
        answered = await started.view("notes", "pile", PileOf(pile="p"), Operator())
        assert isinstance(answered, Accepted)
        assert isinstance(answered.output, Blocks)
        text = answered.output.text().splitlines()
        assert len(text) == 1 + notes
        assert all("note number=" in line for line in text[1:])

    @lup.promise
    async def a_view_naming_a_kind_nobody_declares_fails(self, by: Testing) -> None:
        """A view whose blocks name a tone, a fold kind or a mark kind neither the core nor its module declares fails as it's answered, naming its module, rather than drawing wrong."""
        started = await by.started(noted(1))
        with raises(lup.BlockError) as failed:
            await started.view("notes", "unknown", PileOf(pile="p"), Operator())
        assert "notes" in failed.raised().about

    @lup.promise
    async def what_a_view_doesnt_take_is_refused(self, by: Testing) -> None:
        """A view read with what it doesn't take, or one no module serves, is refused with what was sent, rather than answered."""
        started = await by.started(noted(1))
        sent = {"pile": 1, "extra": True}
        wrong = await started.view("notes", "pile", sent, Operator())
        assert isinstance(wrong, Refused)
        assert wrong.rejection.submitted == sent
        nothing = await started.view("notes", "elsewhere", {}, Operator())
        assert isinstance(nothing, Refused)

    @lup.promise
    async def two_modules_cant_take_one_fold_letter(self, by: Testing) -> None:
        """Two modules' fold kinds taking one letter fail the declaration as it starts, naming both modules: the page has one set of keys."""
        project = Project(modules=Modules.default().add(Notes(), Echoes()))
        with raises(ProjectError) as clash:
            await by.started(project)
        assert all(name in clash.raised().about for name in ["notes", "echoes"])

    @lup.promise
    async def a_block_offers_only_a_command_with_a_key(self, by: Testing) -> None:
        """A block offering a method that isn't a command given a verb, or reading a method that isn't a view, fails as it's laid out, naming the method."""
        del by
        with raises(lup.BlockError) as offered:
            Offer.of(NotesPart.pile, PileOf(pile="p"))
        assert "NotesPart.pile" in offered.raised().about
        with raises(lup.BlockError) as read:
            Viewing.of(NotesPart.clear, Clearing(number=1))
        assert "NotesPart.clear" in read.raised().about

    @lup.promise
    async def the_dashboard_answers_nothing_before_its_token(self, by: Testing) -> None:
        """The dashboard answers no view until the page has said its token, and closes a page that says another, since rooms reach every port on the operator's machine."""
        started = await by.started(noted(1))
        page = await started.dashboard()
        await page.say(
            Watch(
                watch=1,
                viewing=Viewing(module="notes", view="pile", given={"pile": "p"}),
            )
        )
        refused = await page.told()
        assert isinstance(refused, Unanswered)
        assert refused.watch is None
        await page.say(Hello(token=f"not-{page.token}"))
        assert await page.told() is None

    @lup.promise
    async def a_page_watching_a_view_is_told_its_blocks(self, by: Testing) -> None:
        """A page that has said its token is told the document's root view and the project's kinds, and each view it watches is answered under the number it picked, with the view's blocks as the operator reads them."""
        notes = by.any(Drawn).notes
        watch = by.any(Picked).watch
        started = await by.started(noted(notes))
        page = await started.dashboard()
        await page.say(Hello(token=page.token))
        opened = await page.told()
        assert isinstance(opened, Opened)
        assert opened.root is not None
        assert any(each.kind.name == "note" for each in opened.looks.folds)
        assert isinstance(await page.told(), Drafted)
        await page.say(Watch(watch=watch, viewing=opened.root))
        answered = await page.told()
        assert isinstance(answered, Answered)
        assert answered.watch == watch
        assert len(answered.blocks.blocks) == notes
        await page.leave()

    @lup.promise
    async def a_frame_the_server_cant_read_is_refused_alone(self, by: Testing) -> None:
        """A frame the dashboard can't read is refused on its own, and the page's socket keeps answering what comes after it."""
        garbage = by.any(Garbage).text
        started = await by.started(noted(1))
        page = await started.dashboard()
        await page.say(Hello(token=page.token))
        assert isinstance(await page.told(), Opened)
        assert isinstance(await page.told(), Drafted)
        await page.say(f"not a frame: {garbage}")
        refused = await page.told()
        assert isinstance(refused, Unanswered)
        await page.say(
            Watch(
                watch=7,
                viewing=Viewing(module="notes", view="pile", given={"pile": "p"}),
            )
        )
        answered = await page.told()
        assert isinstance(answered, Answered)
        assert answered.watch == 7
        await page.leave()

    @lup.promise
    async def every_page_shows_the_same_draft(self, by: Testing) -> None:
        """Every other page open on the dashboard is told the draft as one changes it, so a comment written in one shows in the other, and a closed tab loses nothing; the page that wrote it holds it already, and isn't told it back over what's typed since."""
        words = f"said {by.any(Words).words}"
        started = await by.started(noted(1))
        first = await opened(started)
        second = await opened(started)
        await first.say(
            Write(comment=Comment(id="c1", on=quoted("note-1"), words=words))
        )
        drafted = await second.told()
        assert isinstance(drafted, Drafted)
        assert [each.words for each in drafted.draft.comments] == [words]
        await first.leave()
        third = await opened(started, drafted=False)
        drafted = await third.told()
        assert isinstance(drafted, Drafted)
        assert [each.id for each in drafted.draft.comments] == ["c1"]
        await second.leave()
        await third.leave()

    @lup.promise
    async def sending_sends_each_part_on_its_own(self, by: Testing) -> None:
        """Sending the draft sends each comment on its own: one whose block takes comments goes, and leaves the draft; one whose block takes none stays in it, saying why, and holds up nothing else."""
        words = f"said {by.any(Words).words}"
        started = await by.started(noted(1))
        page = await opened(started)
        going = Comment(id="going", on=quoted("note-1"), words=words)
        staying = Comment(id="staying", on=quoted("nowhere"), words=words)
        for comment in [going, staying]:
            await page.say(Write(comment=comment))
        await page.say(Send())
        drafted = await page.told()
        delivered = await page.told()
        assert isinstance(drafted, Drafted)
        assert isinstance(delivered, Delivered)
        assert "going" in delivered.went
        assert "staying" in delivered.stayed
        assert [each.id for each in drafted.draft.comments] == ["staying"]
        assert all(each.reason for each in drafted.draft.comments)
        await page.leave()

    @lup.promise
    async def a_comment_that_says_nothing_is_never_sent(self, by: Testing) -> None:
        """A comment that says nothing, blank or only spaces, is dropped at the send rather than sent: what it's on never hears of it, and it leaves the draft, while what was said goes trimmed."""
        blank = by.any(Blank).text()
        words = f" said {by.any(Words).words} "
        started = await by.started(noted(1))
        page = await opened(started)
        for comment in [
            Comment(id="blank", on=quoted("note-1"), words=blank),
            Comment(id="said", on=quoted("note-1"), words=words),
        ]:
            await page.say(Write(comment=comment))
        await page.say(Send())
        drafted = await page.told()
        delivered = await page.told()
        assert isinstance(drafted, Drafted)
        assert isinstance(delivered, Delivered)
        assert delivered.went == ["said"]
        assert delivered.stayed == []
        assert drafted.draft.comments == []
        assert await taken(started) == [words.strip()]
        await page.leave()

    @lup.promise
    async def each_comment_is_taken_once_however_sends_and_writes_meet(
        self, by: Testing
    ) -> None:
        """A comment written while a send runs stays in the draft for the next send rather than being lost, and two pages sending at once send each comment once."""
        words = by.any(Words).words
        started = await by.started(noted(1, holding=True))
        first = await opened(started)
        second = await opened(started)
        await first.say(
            Write(
                comment=Comment(id="sent", on=quoted("note-1"), words=f"first {words}")
            )
        )
        await first.say(Send())
        await second.say(
            Write(
                comment=Comment(
                    id="later", on=quoted("note-1"), words=f"second {words}"
                )
            )
        )
        await second.say(Send())
        released = await started.run("notes", "release", PileOf(pile="p"), Operator())
        assert isinstance(released, Accepted)
        sends = [await delivered(first), await delivered(second)]
        assert sorted(part for each in sends for part in each.went) == ["later", "sent"]
        assert all(each.stayed == [] for each in sends)
        assert sorted(await taken(started)) == sorted(
            [f"first {words}".strip(), f"second {words}".strip()]
        )
        third = await opened(started, drafted=False)
        drafted = await third.told()
        assert isinstance(drafted, Drafted)
        assert drafted.draft.comments == []
        for page in [first, second, third]:
            await page.leave()

    @lup.promise
    async def a_comment_on_what_changed_goes_at_the_second_send(
        self, by: Testing
    ) -> None:
        """A comment on a block whose version changed since it was written stays at the first send, saying so, while the rest goes; sent again as it is, it goes."""
        words = f"said {by.any(Words).words}"
        started = await by.started(noted(1))
        page = await opened(started)
        stale = quoted("note-1").model_copy(update={"version": "as it was"})
        await page.say(Write(comment=Comment(id="stale", on=stale, words=words)))
        await page.say(Send())
        drafted = await page.told()
        first = await page.told()
        assert isinstance(drafted, Drafted)
        assert isinstance(first, Delivered)
        assert first.stayed == ["stale"]
        assert [each.warned for each in drafted.draft.comments] == [True]
        assert await taken(started) == []
        await page.say(Send())
        drafted = await page.told()
        second = await page.told()
        assert isinstance(drafted, Drafted)
        assert isinstance(second, Delivered)
        assert second.went == ["stale"]
        assert drafted.draft.comments == []
        assert await taken(started) == [words.strip()]
        await page.leave()

    @lup.promise
    async def a_part_held_back_stays_through_sends_and_goes_once_let_go(
        self, by: Testing
    ) -> None:
        """A comment the operator holds back stays in the draft as it is through every send, while the rest goes; let go, it goes at the next."""
        words = f"said {by.any(Words).words}"
        sends = by.any(Drawn).notes % 3 + 1
        started = await by.started(noted(1))
        page = await opened(started)
        held = Comment(id="held", on=quoted("note-1"), words=words, held=True)
        await page.say(Write(comment=held))
        for _ in range(sends):
            await page.say(Send())
            drafted = await page.told()
            delivered = await page.told()
            assert isinstance(drafted, Drafted)
            assert isinstance(delivered, Delivered)
            assert delivered.held == ["held"]
            assert drafted.draft.comments == [held]
        assert await taken(started) == []
        await page.say(Write(comment=held.model_copy(update={"held": False})))
        await page.say(Send())
        drafted = await page.told()
        delivered = await page.told()
        assert isinstance(delivered, Delivered)
        assert delivered.went == ["held"]
        assert await taken(started) == [words.strip()]
        await page.leave()

    @lup.promise
    async def every_block_answered_carries_a_version_of_what_it_shows(
        self, by: Testing
    ) -> None:
        """Every block a view answers carries a version, the core working one out where the module gives none: the same while the block shows the same, another once it shows something else."""
        notes = by.any(Drawn).notes
        started = await by.started(noted(notes))
        renamed = await by.started(noted(notes, titled="memo"))
        versions = [await versioned(each) for each in [started, started, renamed]]
        assert all(version is not None for version in versions[0])
        assert versions[0] == versions[1]
        assert all(
            one != other for one, other in zip(versions[0], versions[2], strict=True)
        )

    @lup.promise
    async def a_comment_reaches_its_party_whoever_takes_it(self, by: Testing) -> None:
        """A comment on a block offering none of its own goes through the inbox to the party the block reaches, or to the No agent pile where it reaches none; one the operator sent elsewhere goes there instead of to what its block offers."""
        words = f"said {by.any(Words).words}".strip()
        started = await by.started(noted(1))
        page = await opened(started)
        reaching = Viewing(module="notes", view="reaching", given={"pile": "p"})
        comments = [
            Comment(
                id="reaches",
                on=Quote(viewing=reaching, block="reaches", lines=["what p reaches"]),
                words=f"{words} 1",
            ),
            Comment(
                id="alone",
                on=Quote(
                    viewing=reaching, block="alone", lines=["what reaches no one"]
                ),
                words=f"{words} 2",
            ),
            Comment(
                id="chosen",
                on=quoted("note-1"),
                words=f"{words} 3",
                to=Pile(repository="harness", path="chosen").model_dump(mode="json"),
            ),
        ]
        for comment in comments:
            await page.say(Write(comment=comment))
        await page.say(Send())
        sent = await delivered(page)
        assert sorted(sent.went) == ["alone", "chosen", "reaches"]
        assert await taken(started) == []
        for pile, said in [("notes/p", "1"), ("no-agent", "2"), ("chosen", "3")]:
            answered = await started.view(
                "core", "party", PartyOf(repository="harness", name=pile), Operator()
            )
            assert isinstance(answered, Accepted)
            assert isinstance(answered.output, Blocks)
            assert any(
                isinstance(each, Markdown) and each.text == f"{words} {said}"
                for each in answered.output.every()
            )
        await page.leave()

    @lup.promise
    async def the_review_tops_the_document_saying_where_each_part_goes(
        self, by: Testing
    ) -> None:
        """While the draft holds something, the document's root opens with the review, a fold for each place its parts go and one for those held back, laid out again for the page as the draft changes."""
        words = f"said {by.any(Words).words}".strip()
        started = await by.started(noted(1))
        page = await opened(started)
        pile = Viewing(module="notes", view="pile", given={"pile": "p"})
        await page.say(Watch(watch=1, viewing=pile))
        first = await page.told()
        assert isinstance(first, Answered)
        assert all(each.id != "draft" for each in first.blocks.blocks)
        comment = Comment(id="c", on=quoted("note-1"), words=words)
        await page.say(Write(comment=comment))
        review = await reviewed_in(page)
        assert list(parts_in(review).values()) == [["c"]]
        await page.say(Write(comment=comment.model_copy(update={"held": True})))
        held = await reviewed_in(page)
        assert parts_in(held) == {"held": ["c"]}
        await page.leave()


class Picked(Model):
    """A number the page picks to watch a view under."""

    watch: int


class Garbage(Model):
    """Text a page might send, which, said after words that aren't JSON, no frame reads as."""

    text: str


class Words(Model):
    """What a comment says."""

    words: str


class Blank(Model):
    """A comment that says nothing: so many line breaks, then so many spaces."""

    breaks: int = Field(ge=0, le=3)
    spaces: int = Field(ge=0, le=5)

    def text(self) -> str:
        """Return the comment's text."""
        return "\n" * self.breaks + " " * self.spaces


async def opened(started: Started, *, drafted: bool = True) -> Page:
    """Open a page of `started`'s dashboard, its token said, told it's opened, and, where `drafted`, the draft too."""
    page = await started.dashboard()
    await page.say(Hello(token=page.token))
    assert isinstance(await page.told(), Opened)
    if drafted:
        assert isinstance(await page.told(), Drafted)
    return page


async def reviewed_in(page: Page) -> Fold:
    """Read what `page` is told until the document's root comes with the review at its top, and return the review."""
    while True:
        told = await page.told()
        assert told is not None, "the page was told nothing more before the review"
        if isinstance(told, Answered):
            top = told.blocks.blocks[0] if told.blocks.blocks else None
            if isinstance(top, Fold) and top.kind == "draft":
                return top


def parts_in(review: Fold) -> dict[str, list[str]]:
    """Return the parts a review shows, by the id of the fold of where they go: each part's id, in order."""
    places = review.content if isinstance(review.content, list) else []
    return {
        place.id: [
            each.id
            for each in (place.content if isinstance(place.content, list) else [])
        ]
        for place in places
        if isinstance(place, Fold)
    }


async def delivered(page: Page) -> Delivered:
    """Read what `page` is told until its send is delivered, and return what was."""
    while not isinstance(told := await page.told(), Delivered):
        assert told is not None, (
            "the page was told nothing more before its send was delivered"
        )
    return told


async def taken(started: Started) -> list[str]:
    """Return what each comment the pile took said, as its `taken` view shows it."""
    answered = await started.view("notes", "taken", PileOf(pile="p"), Operator())
    assert isinstance(answered, Accepted)
    assert isinstance(answered.output, Blocks)
    return [
        "".join(span.text for span in each.spans)
        for each in answered.output.blocks
        if isinstance(each, Line)
    ]


async def versioned(started: Started) -> list[str | None]:
    """Return the version of every block the pile's view answers, in the order they're shown."""
    answered = await started.view("notes", "pile", PileOf(pile="p"), Operator())
    assert isinstance(answered, Accepted)
    assert isinstance(answered.output, Blocks)
    return [block.version for block in answered.output.every()]


def quoted(block: str) -> Quote:
    """Return a quote of the block `block` of the pile's view."""
    pile = Viewing(module="notes", view="pile", given={"pile": "p"})
    return Quote(viewing=pile, block=block, lines=["note 1"])
