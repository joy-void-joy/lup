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

A block can say how it stands for the operator (`Shown.standing`): new to them, waiting on them, done, or held back from a send, the same for every module. The page draws it alike wherever it shows, a glyph in its own colour (◆ waiting, ● new, ✓ done, ‖ held): in the document's margin, in a column of its own left of the folds' beside the block's first line, its fold's letter keeping its kind's colour, and across that line, what's new barred, what waits and what's held back tinted, what's done set back; before the first line in the outline and the window; and in the header; its text form says it in brackets.

A block's line says what it says alone; what names it and what it is (a concern's @name, an item's kind and number) is said aside (`Shown.aside`), which the page's header shows while the cursor is in it and its text form after its line. A friction is a fold of its own kind, its letter and colour in the margin saying it's one. The inbox's views say it of their items and concerns rather than in their words.

Every block (`Shown`) has an id its module keeps from one answer to the next, by which the page keeps the cursor, folds and comments where they were; a version where what it shows changes, which a comment written on it records; what it offers (`Offer.of(command, given)`: one of its module's commands given a verb, under that verb's key); and the party a comment on it reaches (`reaches`). `Offer.of` and `Viewing.of` take the method read through its class, so pyright follows a rename, and fail with `BlockError` where it isn't a command given a verb, or a view, or doesn't take what's given.

Every block a view answers carries a version: the module's where it gives one, else a digest the core works out of what the block shows itself (`Blocks.versioned`, `Shown.shows`), so a comment or a mark can always tell what it's on changed.

## Kinds

A block names its tone, fold kind or mark kind by name, and the kind says how it's drawn and how it behaves: whether a fold starts open and what `zr` and `zm` reach is its kind's rule, never one view's. A module declares its own as fields (`Tones`, `Folds`, `Marks`), which a layer changes as any field; the core declares the shell's (`Core.tones`, `Core.folds`: plain, muted, strong and the operator's tone; a party's section, a file, a body, a run of unchanged lines). A view may name the core's and its own module's. Resolving a declaration refuses two kinds of one name, or two fold kinds of one letter, naming both modules, since the page has one table of them and one set of keys; answering a view refuses, with `BlockError` naming its module, blocks that name what neither the core nor that module declares.

## The document

The dashboard is one document (`DESIGN.md`, *The dashboard*): its root is the view the home repository's declaration names (`Core.document`), a view listing the parties, each a fold of the core's `party` kind whose content reads what's shown of it. Every fold read as it opens is read once it's open, and kept under it while it reads the same view.

The page (`modules/core/page/`) holds it as one text in CodeMirror, kept as a tree whose every node knows where it starts relative to its parent (`page/src/document/tree.ts`): a view answered again is reconciled into the text as the fewest edits, what keeps its key keeping its text and a block's own lines matched by what they say, and lays out nothing outside its section, so typing stays immediate at a real day's size. A comment the operator writes is a node of the tree under one of a block's lines, kept under it as its view answers again, its text never written over.

Comments are written into the document as the second lup's page had them (`page/src/shell/comments.ts`), with nothing bound to a key: the views' text takes no edit, and going into insert mode in it opens a comment there, on the passage an edit vim tried to make covered (`c` with a motion, `s`, `S`, `v…s`), or under the cursor's line (`i`, `a`, `o`); Space `c` comments on a block whole. In a comment vim edits as anywhere; `dd` takes a line out of it, and one left saying nothing is dropped. Each shows under the last line it quotes, the passage underlined, its first line saying whom it reaches and, where it is, that what it quotes changed or why the last send kept it. It's written to the draft at a pause in typing, as insert mode ends, and at `:w`; Ctrl+Enter ends the comment being written, and outside one opens the review of what the draft sends where (*The draft*). `]n` and `[n` go from comment to comment, opening what folds over them; a closed fold says how many comments it holds, and its letter in the margin is underlined. The draft as another page changes it is laid out as it comes, each comment under the lines it quotes, found again where they moved. Nesting is drawn, never written, so what's quoted of a line is what it says. What the operator does to the document, which folds they opened or closed, is kept by each block's key as views answer again (`page/src/shell/shell.ts`).

It's drawn as the second lup's page was (`page/src/shell/palette.ts`, `page/src/shell/margin.ts`): the first lup's dark palette, every colour reading at 7:1 or more on black, keyed by the core's `Colour` so a colour a module may name always has a value; one monospaced font, a row a line; and a margin beside the text, a column of how each block stands, then a column for each depth folds nest to, each fold's letter in its column on its summary's line, outlined where it's closed, and a bar beside each line under it, bright while the cursor's in it. A party's summary is a band across in its kind's colour, and a closed fold says how many lines it hides.

The tree breaks a block's text into lines where the editor does, at `\r\n`, `\r` and `\n` alike, so the two never count a character apart; a line's spans and a fold's summary, a line each, show a line break in them as a space.

### Markdown

A view's `Markdown` blocks and the operator's comments show as Markdown, as the second lup's page showed them (`page/src/shell/markdown.ts`); a `Line`'s spans and a fold's summary stay plain, in their tones. Each block's own lines, the comments under them left out, and each comment are read on their own by `@codemirror/lang-markdown`'s GFM parser, mounted in the editor's syntax tree where they are, so a list or a table goes on past a comment under one of its lines. Emphasis, strong, code, headings, links and strikethrough show as such, the marks that write them hidden, but on the line the cursor is on in a comment, where they show to be edited; a link says its address on hover. A hidden mark is no place for vim's cursor: a motion that would put it on one goes on past it the way it was going, to the next character shown (`pastHidden`). Each line of a block of code is barred, with no highlighting by language until `Code` blocks have it. A table's columns line up by padding drawn beside its cells and never written, so a row stays one line, which vim moves over as one and a comment quotes as it's written. In a comment, lists are written as neovim's Markdown writes them: Enter, `o` and `O` open a line at the indentation of the one they're on and never with a bullet or a number; an indentation nothing's typed after goes as the writing ends; and `>>` and `<<`, and Tab and Shift+Tab in insert mode (vim's Ctrl+T and Ctrl+D, which the browser keeps), move a line in to where the words of the item above begin, nesting it under that item, and out to the item it's nested in.

### The frame, the outline and the panes

The page is framed as the second lup's dashboard was (`page/src/shell/frame.ts`): each pane framed in the border colour, the one the keys are in outlined in the focus colour; over the document the header of where its cursor is, the folds it's in from the outermost, each with its kind's letter in its colour; under it the line of keys, the keys that do something where the cursor of the pane the keys are in is, ending with Ctrl+K and every command. A comment's first line starts with `»`.


The document is shown beside its outline (`page/src/shell/outline.ts`), drawn as the second lup's overview rows were, a row a fold cut where the pane ends rather than wrapped, `\` hiding it and showing it again, a bar beside those the document shows on screen and the one its cursor is in highlighted: each fold of a kind that says it's outlined (`FoldKind.outlined`: the core's party, concern and file; a module's items), under its summary, nested and open as the document has them, its text taken out, drawn by a shell of its own as the document is. A cursor shows only in the pane the keys are in; elsewhere the line it's on is marked. Each moves with the other: the document's cursor marks the fold it's in there, and moving there takes the document to that fold, opening what folds over it; Enter there goes into the document.

Space w and h, j, k or l go straight to the pane to that side, as vim's `Ctrl+W` and a direction do. Pane mode moves between the outline, the document and the window under it (`page/src/shell/panes.ts`): entered by Space w w, or by Esc twice in Normal mode, an Esc pressed out of insert or visual mode not counted, so pressing Esc to be sure never lands there. There h, j, k and l choose the pane to their side, and Enter or Esc goes into it.

### The window

Every modal the page has is its window (`page/src/shell/window.ts`): a split under the document, as vim's `:split` is, the document staying in view above with its cursor where it was. The review of the draft (Ctrl+Enter), the picker of whom a comment reaches (Space s) and the palette of commands (Ctrl+K: every command with its keys and what it does, run by Enter, asking for a fold kind where the command takes one) are shown there, and so will what comes after them. What it shows is a document of its own, drawn by a shell of its own as the page's is, its look, margin and folds alike, whose commands act for the page's shell, moved through and searched as the document is (`/`, `n`); in a picker, Enter chooses the line the cursor is on. Esc closes it. The page's status line is drawn there too; no other module draws a panel, a dialog or an overlay, which a promise holds the page to.

The page holds the keymaps' engines and no module's code: a keymap's bindings name the shell's commands (`page/src/shell/keymap.ts`), vim's its actions, a key's `{kind}` the letter of a fold kind typed after it. Folds are chosen to be acted on together: Space `f` and a kind's letter chooses the nearest fold of the kind around the cursor, Space `F` and a letter every fold of the kind within what's chosen, or anywhere where nothing is, so choices narrow (Space `ff` Space `Fb` `za` opens or closes every body of the file the cursor is in). An action (`za`, `zo`, `zc`) acts on every fold chosen, or on the innermost the cursor is in where none is, and then nothing is chosen; `zf` and a letter is Space `f` and it, then `za`; Esc chooses nothing. A choice that finds nothing says so on the status line and leaves what was chosen. vim's own Space, a character right, is unbound, Space being the shell's leader.

vim's visual mode (`v`, `V`) selects as vim's does, its selection drawn: Space and a verb's key, `za`, `zo`, `zc` and Space `f` or `F` and a letter act on each block whose first line it holds, and `c` comments on the passage it covers; a block a closed fold hides is never reached, and acting leaves visual mode.

A verb's key marks what a block offers under the verb (`page/src/shell/marks.ts`): a binding names `verb:` and the verb, vim's Space d `done`, Space x `decline` and Space t `toggle`. It marks each block a visual selection holds that offers the verb, else every fold chosen that does, else the innermost block at the cursor that does, the block it's on first, then each holding it; the same key again takes the mark off, and a block holds one mark at most, another verb's taking its place. A mark is a part of the draft, shown at the end of its block's first line as what the send will do, and nothing runs until the draft is sent. A block offers one action under each verb at most, so a key does one thing on it, and one offering two fails as it's made (`Shown`); the line of keys says what each verb's key does where the cursor is.

## The server

The dashboard's server (`lup.environment.shell.server`) serves the page and one socket carrying every view the page watches (`lup.shell.wire`): the page says the token it was handed in its address's fragment, which no request carries, before anything is answered, since rooms reach every port on the operator's machine. It keeps the token for every tab on the dashboard's address (`localStorage`), so a tab opened there by hand, on the address `lup` says without the token, says it too; a page whose socket the server closes, a token refused among the reasons, says why in its place rather than stay blank. It's then told the document's root view and the project's kinds (`Opened`), and each view it watches is answered under the number it picked (`Answered`), each as a task of its own, so a slow view holds up no other, and again whenever what it shows changes. No module says when its view changes, so the server reads each view watched again (`Session.watched`): two seconds after it changed, then twice as long after each read that finds it the same, up to fifteen, or up to two minutes while it can't be answered; and at once after the operator's send. A view the page stops watching (`Unwatch`), or that a page closed watched, is read no more. A frame it can't read is answered alone (`Unanswered`), the socket staying open. The page's types are generated from these models' description (`described`), so the two can't disagree.

The machine serves it (`lup.environment.shell.hosted`), started beside its socket from the commit the operator approved, before that socket listens, and stopped with it. Its calls go through the operator's socket, as a terminal's do, so the machine routes them and vouches they're the operator's; the server itself can't run in a container, since only that socket, which no container mounts, says a call is theirs. Whether it serves and on which of localhost's ports is the core's (`Core.dashboard`, 8770 unless the machine's layer says otherwise); its token and draft are kept in the machine's state across restarts, so an open page reconnects, and its address with the token in the machine's runtime place while it serves, each readable by the operator alone, which `lup` typed alone on their machine opens in their browser. Its document is the core's `document`, else the inbox's parties of the home repository.

The page isn't in git, nor are its types, so the machine builds it (`Pages`, `lup/shell/pages.py`): from the source of the commit it runs, with what the core says it sends written beside it, in a container on Arch Linux's image with node and pnpm from the archive every project's image comes from, since `pnpm install` runs packages' own code. The source is copied into a directory of the part's and mounted with pnpm's store and where the page is written, and nothing else of the machine's; each step's words go to the build's log, which a failure names. A page is kept under a digest of everything it's built from, so each is built once and a commit that leaves the page alone serves the one built already. Until it's there, or where it can't be (no podman, or the installed `lup`, which ships no page's source), the server serves why in its place; a build that fails is asked again after half a minute, then twice as long each time, half an hour at most, since what it fetches (the archive's packages, the page's) may be out of reach for a while.

## The draft

What the operator writes and marks waits in one draft (`lup.shell.draft`), kept by the dashboard's server rather than by a page, so two open pages show the same one and a closed tab loses nothing. A page changes it a part at a time: a comment written or rewritten (`Write`), a verb marked on a block (`Mark`), a part taken out (`Erase`); every other open page is told the draft as it changes (`Drafted`), the page that changed it holding it already, so what's typed since is never laid over by an older copy. Each part is on a block of a view (`Quote`): the block's id, its version as the part was written, the lines quoted and where they start among the block's own, so a comment goes back under the right one of two lines that read the same. A comment reaches whom its block reaches, or whom the operator chose (`to`).

Sending (`Send`, Ctrl+Enter) sends each part on its own: a comment to what its block offers under the `comment` verb, given the comment (`Commented`), a mark to the action it marks, refused where its block's version changed since. A part that went leaves the draft; one that can't stays in it with why, and holds up nothing else (`Delivered`). A comment on a block whose version changed since it was written stays the first time, saying so (`warned`), and goes the next, sent as it is. A part the operator keeps back (`held`: Space h on a comment or a marked block, or unticked in the review) isn't sent, and stays as it is until they let it go.

A comment goes to what its block offers under the `comment` verb, unless the operator chose whom it reaches (Space s); else the core's inbox tells it to the party chosen, the one what it's on reaches, or the repository's No agent pile where it reaches none (`comment_to`, `Dashboard.taking`). What a block reaches is its own `reaches`, else that of the nearest fold holding it in its view, else, outward, of the fold its view was read under, which the quote names (`Quote.within`): a comment in an agent's conversation reaches the agent whose section it's in.

The core tells every page the review of what the next send would do (`Reviewed`, `lup.environment.shell.review`), as a page opens and whenever the draft changes, the page that changed it among them: a checklist, a fold of the `sent-to` kind for each place its comments go, then one of its marks, each part a line ticked where it goes and blank where it's kept back, saying its words, or what the mark does, and what it's on and, where it can't go, why. The page shows it in its window (*The window*): Ctrl+Enter outside a comment opens it, Esc closes it, and Ctrl+Enter in it sends what's ticked; on a part's line Space d ticks it, Space x unticks it, Space t and Space h either; Space s chooses whom a comment reaches from the parties the document shows, in the window, `/` searching them and Enter choosing, and outside a comment writes one to whom's chosen. A comment that says nothing is dropped rather than sent, and what one says goes trimmed. One send runs at a time, whichever pages ask, so each part is sent once, and a send settles against the draft as it stands when it ends, so what's written or erased while it runs is kept as it is.

## Promises

The shell's Python side promises what a view's reader and the page can count on (`promises.py`, over an example module): a view answers its blocks to whoever may read it, says in text what the operator sees, fails rather than draws wrong where it names a kind nobody declares, and refuses what it doesn't take; the dashboard answers nothing before its token, tells a page each view it watches under its number, and refuses a frame it can't read alone; every page shows the one draft, a send sends each part on its own, never a comment that says nothing, and each comment once, however sends and writes meet. A promise reaches the dashboard through the harness's page (`Started.dashboard`), its socket in memory, served as the server serves one. The page's build promises its own (`PagesPromises`), over podman stood in for: a page built once for what it's built from, a failed step leaving no page and naming its log, and a build mounting only what it works in, never the source itself.

The page's own promises are in TypeScript, declared the same way (`page/src/testing/promise.ts`): a sentence, and a scenario that asserts or a law over every step of generated runs of a machine, checked by fast-check against the editor run headless, with no browser and no real time, seeded from the sentence for the gate and at random under `LUP_EXPLORE`. Each lives in a `promises.ts` beside what it promises: the document's (where each block starts, answering again as laying out afresh, a comment shown under its line and left untouched as its view answers again) and the shell's (insert mode left only by the operator, a view answering again leaving folds as the operator left them, a fold read as it opens, the margin showing each fold where it is and as it stands, choosing and acting on what's chosen, the editor's text always the tree's, keys changing nothing but comments, insert mode only in a comment, every comment shown out of it saying something the draft holds, a view answering again leaving each comment's text as it was, and in Normal mode vim's cursor never resting on a mark the Markdown hides; with scenarios of Markdown's constructs shown and their marks hidden, `l` going past each hidden mark to the line's end, a comment's own line showing its marks, a comment's lists written as neovim writes them, and a table's rows lined up a line each). Each run lets the timers the editor left queued run before the next, so shrinking thousands of runs keeps none of their editors.
