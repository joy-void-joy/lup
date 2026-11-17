# The shell

The dashboard's page that knows no module: modules lay out what they show from blocks, and the shell does the rest, folding, selecting, commenting, sending, clearing, marks (`DESIGN.md`, *The dashboard*). Its library side (`lup.shell`, re-exported by `lup`) is the view door, the blocks a view answers and the kinds a module declares for them; answering a view is the environment's (`lup.environment.shell`).

```python
import lup
from lup import Blocks, Fold, FoldKind, Folds, Markdown, Model, Module, Offer, Part, Parts, Span, Viewing


class PileOf(Model):
    """Which pile to show."""

    pile: str


class NotesPart(Part):
    """A pile's notes."""

    module: Notes

    @lup.view
    async def pile(self, of: PileOf) -> Blocks:
        """Show a pile's notes, each under its title."""
        return Blocks.of(
            *(
                Fold(
                    id=f"note-{note.number}",
                    kind="note",
                    summary=[Span(text=note.title, tone="strong")],
                    content=Viewing.of(NotesPart.note, NoteOf(number=note.number)),
                    offers=[Offer.of(NotesPart.clear, Clearing(number=note.number))],
                )
                for note in self.module.read(of.pile)
            )
        )


class Notes(Module):
    """Notes in piles."""

    name = "notes"
    folds: Folds = Folds.of(FoldKind(name="note", letter="n", called="note"))
    parts: Parts = Parts.of(NotesPart)
```

## The view door

`@lup.view` puts a method behind a door the dashboard reads it through, kept live, and its command prints it as text. It takes what's viewed, one model, and answers `Blocks`. The operator and agents may both read a view, unless its `by` says who may. Its command takes the model's fields as its arguments, as a command's do, and prints the view's text form (`Blocks.text`): a closed fold as its summary line, an open one with its content indented, and a fold read as it opens with the view that shows what's under it (`▸ note 3  [note number=3]`), so an agent reads what the operator saw and knows which command opens the rest.

## Blocks

They hold nothing of any module, so every view is drawn, folded and commented on the same way:
- **`Line`,** made of `Span`s, each in a tone. A span may also tick (`Ticking`: time since a moment, said again by the page as it passes, so nothing is answered again for a clock), measure (`Gauge`: how full something is), or refer (`Viewing`: the view that shows what it names, which following it opens: a concern, an agent, a file).
- **`Markdown`,** in a tone.
- **`Fold`:** a summary line and what's under it, of a fold kind; its content given, or read from a view as it opens (`Viewing`), so a long view sends only what's open. Whether it starts open is its kind's, unless its view says otherwise (`open`).
- **`Code` and `Diff`:** a file as it stands, or as it changed, under a fold of the shell's `file` kind, its bodies in `body` folds and its runs of unchanged lines in `lines` folds, with `Mark`s on its lines of kinds its module declares.

Every block (`Shown`) has an id its module keeps from one answer to the next, by which the page keeps the cursor, folds and comments where they were; a version where what it shows changes, which a comment written on it records; what it offers (`Offer.of(action, given)`: one of its module's actions, under its verb's key); and the party a comment on it reaches (`reaches`). `Offer.of` and `Viewing.of` take the method read through its class, so pyright follows a rename, and fail with `BlockError` where it isn't an action, or a view, or doesn't take what's given.

## Kinds

A block names its tone, fold kind or mark kind by name, and the kind says how it's drawn and how it behaves: whether a fold starts open and what `zr` and `zm` reach is its kind's rule, never one view's. A module declares its own as fields (`Tones`, `Folds`, `Marks`), which a layer changes as any field; the core declares the shell's (`Core.tones`, `Core.folds`: plain, muted, strong and the operator's tone; a party's section, a file, a body, a run of unchanged lines). A view may name the core's and its own module's. Resolving a declaration refuses two kinds of one name, or two fold kinds of one letter, naming both modules, since the page has one table of them and one set of keys; answering a view refuses, with `BlockError` naming its module, blocks that name what neither the core nor that module declares.

## Promises

The shell's Python side promises what a view's reader can count on (`promises.py`, over an example module): a view answers its blocks to whoever may read it, says in text what the operator sees, fails rather than draws wrong where it names a kind nobody declares, and refuses what it doesn't take. The page's own laws, about its cursor, its modes, its folds and its selections, are the page's, in TypeScript, checked the same way.
