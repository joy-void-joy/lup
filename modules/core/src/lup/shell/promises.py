"""The shell's promises on its Python side: what a module's views and their readers can count on.

Each is checked through the harness over an example module defined here, a
pile of notes, started as a project's declaration starts it and its views read
as a party reads them. The page's own laws, about its cursor, its modes and its
folds, are the page's, in TypeScript (`README.md` here, *Promises*).
"""

from pydantic import Field

import lup
from lup import (
    Agent,
    Blocks,
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
from lup.testing import (
    Accepted,
    Answered,
    Hello,
    Opened,
    Refused,
    Testing,
    Unanswered,
    Watch,
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
    """A pile of notes, each a fold under its title, its text read as it opens."""

    module: Notes

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
                    offers=[Offer.of(NotesPart.clear, Clearing(number=number))],
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

    def titles(self) -> list[str]:
        """Return the notes' titles, in order."""
        return [f"note {number}" for number in range(1, self.module.notes + 1)]

    @lup.action(verb="done", says="clear it")
    async def clear(self, clearing: Clearing) -> str:
        """Clear a note."""
        return f"cleared {clearing.number}"


class Notes(Module):
    """Notes in a pile: an example module the shell's promises read views of."""

    name = "notes"
    notes: int = 0
    """How many notes the pile holds, each titled by its number."""
    folds: Folds = Folds.of(FoldKind(name="note", letter="n", called="note", level=1))
    tones: Tones = Tones.of(Tone(name="title", like="strong"))
    parts: Parts = Parts.of(NotesPart)


class Echoes(Module):
    """Another module, declaring a fold kind on a letter the notes' takes."""

    name = "echoes"
    folds: Folds = Folds.of(FoldKind(name="echo", letter="n", called="echo"))


def noted(notes: int) -> Project:
    """Return a project of lup's default modules and a pile of `notes` notes, the dashboard's document its pile.

    `lup.Core` is read as it's called, not imported with the module: the core
    lists these promises, so it's still being made as this module is.
    """
    document = Viewing(module="notes", view="pile", given={"pile": "p"})
    return Project(
        modules=Modules.default()
        .edit(lup.Core(document=document))
        .add(Notes(notes=notes))
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
                offer.verb == "done" and offer.action == "clear"
                for fold in folds
                for offer in fold.offers
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
    async def a_block_offers_only_an_action(self, by: Testing) -> None:
        """A block offering a method that isn't an action, or reading a method that isn't a view, fails as it's laid out, naming the method."""
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


class Picked(Model):
    """A number the page picks to watch a view under."""

    watch: int


class Garbage(Model):
    """Text a page might send, which, said after words that aren't JSON, no frame reads as."""

    text: str
