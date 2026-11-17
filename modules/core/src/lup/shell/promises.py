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
from lup.testing import Accepted, Refused, Testing, raises


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
    """Return a project of lup's default modules and a pile of `notes` notes."""
    return Project(modules=Modules.default().add(Notes(notes=notes)))


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
