// The shell: the document views answer, shown in an editor, folded, moved through and acted on by the keymap's
// commands. The core decides what's shown; the shell keeps what the operator does to it (what's open, where the
// cursor is) by each block's key, so a view answering again moves nothing they didn't move.

import { foldEffect, foldedRanges, foldState, unfoldEffect } from "@codemirror/language";
import { history } from "@codemirror/commands";
import { EditorState, Facet, StateEffect, StateField, Transaction, type ChangeSpec, type Extension, type Range } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, WidgetType, drawSelection, highlightActiveLine, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import { getCM, vim, Vim } from "@replit/codemirror-vim";

import type { Blocks, Comment, Delivered, Draft, Looks, Marked, Standing, Viewing } from "../generated/read";
import { depthOf, Document, every, foldKind, foldRange, mountedOf, nodeAt, offsetOf, opening, section, viewKey, type Change, type Node } from "../document/tree";
import { fromCore, redrawn } from "./annotations";
import { Comments } from "./comments";
import { Kinds } from "./looks";
import { glyphOf, Marks } from "./marks";
import { markdown, sourced, sourcesOf, unindented } from "./markdown";
import { standings } from "./palette";
import { framed } from "./frame";
import { Outline } from "./outline";
import { Panes } from "./panes";
import { said, say, Window } from "./window";

/** Where views are read from and the draft is kept: the core, through the server, or the harness. */
export interface Source {
    /** Read `viewing`, and again each time what it shows changes, handing each answer to `answered`; return what stops it. */
    watch(viewing: Viewing, answered: (blocks: Blocks) => void): () => void;
    /** Keep `comment` in the draft, in place of the one of its id where there's one. */
    write(comment: Comment): void;
    /** Keep `marked` in the draft, in place of the mark of its id where there's one. */
    mark(marked: Marked): void;
    /** Take the comment or mark of id `id` out of the draft. */
    erase(id: string): void;
    /** Send the draft. */
    send(): void;
    /**
     * Hand the draft to `drafted` as it stands, then each time another page or a send changes it, and what each send
     * delivered to `delivered`; return what stops it.
     */
    drafts(drafted: (draft: Draft) => void, delivered: (delivered: Delivered) => void): () => void;
    /** Hand the review of what the draft sends where to `reviewed` as it stands, then each time it changes; return what stops it. */
    reviews(reviewed: (review: Blocks) => void): () => void;
}

/** Where a shell is: the page's document's, or its window's, beside what else is drawn with it. */
export interface Placing {
    /** More of the editor: the page's look, its margin, its folds' placeholders, a window's own too. */
    readonly extensions?: readonly Extension[];
    /** The document's shell, where this one draws its window or its outline; none for the document's own, which takes comments. */
    readonly owner?: Shell | null;
    /** Where the document's outline goes, beside it; none for no outline. */
    readonly aside?: HTMLElement | null;
    /** What holds the page's panes, whose keys pane mode hears first; none for no pane mode. */
    readonly page?: HTMLElement | null;
    /** The header over the document, saying where its cursor is; none for no header. */
    readonly header?: HTMLElement | null;
    /** The line of keys under the document, saying what the keys do where the cursor of the pane the keys are in is; none for no line of keys. */
    readonly keys?: HTMLElement | null;
    /** More of the outline's own editor: how it's drawn, as the second lup's overview rows were. */
    readonly outlining?: readonly Extension[];
}


/** The shell's state, as its laws read it: a value of its own, which later events don't change. */
export interface ShellState {
    readonly mode: "normal" | "insert" | "visual";
    /** The line the cursor is on, from 1. */
    readonly line: number;
    /** The key of the block the cursor is in. */
    readonly at: string;
    /** The keys of the folds closed. */
    readonly closed: readonly string[];
    /** The keys of the folds chosen, in the order the document shows them. */
    readonly chosen: readonly string[];
    /** What the shell last said on its status line. */
    readonly said: string | null;
    /** Each comment laid out, by its node's key: what it says. */
    readonly comments: Readonly<Record<string, string>>;
    /** The key of the comment being written; none outside one. */
    readonly writing: string | null;
    readonly text: string;
}

/** The document's shell, in an editor of its own. */
export class Shell {
    readonly view: EditorView;
    readonly document: Document;
    readonly kinds: Kinds;
    readonly source: Source;
    readonly comments: Comments;
    /** The verbs marked on the document's blocks, waiting in the draft. */
    readonly marks: Marks;
    /** The document's shell, where this one draws its window; none for the document's own. */
    readonly owner: Shell | null;
    /** The page's window, under the document: none for a window's own shell. */
    readonly window: Window | null;
    /** The document's outline, beside it; none where the page has none. */
    readonly outline: Outline | null;
    /** Pane mode, moving between the outline, the document and the window; none where the page has none. */
    readonly panes: Panes | null;
    /** The ids of the blocks marked, each fold summary of one drawn so: in the outline, the folds the document shows. */
    marked: ReadonlySet<string> = new Set();
    readonly #header: HTMLElement | null;
    readonly #keys: HTMLElement | null;
    /** Whether the shell is made: its editor's first updates come while it's being made, before there's a frame to say them in. */
    #made = false;
    /** The review of what the draft sends where, as the core last told it. */
    #review: Blocks = { blocks: [], summary: [], offers: [] };
    #stopReviews: () => void = () => {};
    /** Whether the operator opened or closed each fold, by its key: what they did, kept as views answer again. */
    readonly #opened = new Map<string, boolean>();
    /** Each fold's view watched while it's open, by the fold's key: which view, whether it's answered yet, and what stops it. */
    readonly #watching = new Map<string, { view: string; answered: boolean; stop: () => void }>();
    /** The keys of the folds chosen, for an action to act on every one of. */
    #chosen: readonly string[] = [];
    /** Where the cursor was as the review was opened, to go back to as it's left. */
    #reviewing: number | null = null;
    readonly #stop: () => void;

    constructor(parent: Element, root: Viewing, looks: Looks, source: Source, placing: Placing = {}) {
        this.kinds = new Kinds(looks);
        this.source = source;
        this.owner = placing.owner ?? null;
        this.document = new Document(section("root", root, { blocks: [], summary: [], offers: [] }));
        this.comments = new Comments(this);
        this.marks = new Marks(this);
        this.#header = placing.header ?? null;
        this.#keys = placing.keys ?? null;
        const extensions = placing.extensions ?? [];
        this.window =
            this.owner === null
                ? new Window(this, (body, given) => new Shell(body, { module: null, view: "window", given: {} }, looks, given, { extensions, owner: this }))
                : null;
        const aside = placing.aside ?? null;
        this.outline =
            this.owner === null && aside !== null
                ? new Outline(this, aside, (body, given) => {
                      const went = EditorView.updateListener.of((update) => {
                          if (update.selectionSet && update.view.hasFocus) {
                              this.outline?.went();
                          }
                      });
                      return new Shell(body, { module: null, view: "outline", given: {} }, looks, given, {
                          extensions: [...(placing.outlining ?? extensions), went],
                          owner: this,
                      });
                  })
                : null;
        const shell = this;
        this.view = new EditorView({
            parent,
            state: EditorState.create({
                doc: "",
                extensions: [
                    vim(),
                    // vim hides the browser's own selection, and draws its visual mode's through this layer.
                    drawSelection(),
                    EditorView.lineWrapping,
                    EditorState.changeFilter.of((transaction) => transaction.annotation(fromCore) === true || shell.comments.allows(transaction)),
                    // vim's `u` and Ctrl+R undo and redo what the operator wrote, never what views answered.
                    history(),
                    EditorState.transactionExtender.of((transaction) => (transaction.annotation(fromCore) === true ? { annotations: Transaction.addToHistory.of(false) } : null)),
                    // What's written in Markdown is read anew as the shell lays the text out, its tree already the text's.
                    EditorState.transactionExtender.of((transaction) =>
                        transaction.annotation(fromCore) === true && transaction.docChanged ? { effects: sourced.of(sourcesOf(shell.document.root)) } : null,
                    ),
                    markdown(),
                    EditorView.updateListener.of((update) => {
                        shell.comments.changed(update);
                        if (!shell.#made) {
                            return;
                        }
                        if (update.selectionSet) {
                            shell.outline?.followed();
                        }
                        if (update.viewportChanged || update.docChanged) {
                            shell.outline?.viewed();
                        }
                        (shell.owner ?? shell).reframe();
                    }),
                    foldState,
                    said,
                    ...(this.window === null ? [] : [this.window.extension]),
                    drawing,
                    shells.of(shell),
                    ...(this.owner === null ? [] : [highlightActiveLine()]),
                    ...extensions,
                ],
            }),
        });
        this.comments.start();
        this.marks.start();
        let inserting = false;
        getCM(this.view)?.on("vim-mode-change", (event: { mode: string }) => {
            const was = inserting;
            inserting = event.mode === "insert" || event.mode === "replace";
            if (was && !inserting) {
                // An indentation nothing was typed after goes as the writing ends, in the comment it was typed in.
                const emptied = unindented(this.view.state, this.view.state.selection.main.head);
                if (emptied !== null) {
                    this.view.dispatch(emptied);
                }
            }
            this.comments.moded(event.mode);
            (this.owner ?? this).reframe();
        });
        const page = placing.page ?? null;
        this.panes = this.owner === null && page !== null ? new Panes(this, page) : null;
        if (this.window !== null) {
            const window = this.window;
            this.#stopReviews = source.reviews((review) => {
                this.#review = review;
                window.reviewed(review);
            });
        }
        this.#made = true;
        this.#stop = source.watch(root, (blocks) => {
            this.answered("root", blocks);
        });
    }

    /** Stop reading every view, and leave the page. */
    destroy(): void {
        this.window?.close();
        this.outline?.shell.destroy();
        this.#stopReviews();
        this.comments.destroy();
        this.marks.destroy();
        this.#stop();
        for (const watched of this.#watching.values()) {
            watched.stop();
        }
        this.view.destroy();
    }

    /** Put what the view of the section keyed `key` answered in its place. */
    answered(key: string, blocks: Blocks): void {
        const changes = this.document.replace(key, blocks);
        this.#apply(changes, key);
    }

    #apply(changes: Change[], key: string): void {
        this.#chosen = this.#chosen.filter((chosen) => {
            const node = this.document.node(chosen);
            return node !== null && foldKind(node) !== null;
        });
        this.view.dispatch({ changes: changes as ChangeSpec[], annotations: fromCore.of(true) });
        const node = this.document.node(key);
        if (node !== null) {
            this.#settle([node]);
        }
        this.comments.laid();
    }

    /**
     * Fold or unfold each fold in `nodes` as the operator left it, else as its view or its kind says, in one
     * transaction; and read what each open fold reads as it opens.
     */
    #settle(nodes: readonly Node[]): void {
        const effects = [];
        const closed = new Map<string, { from: number; to: number }>();
        foldedRanges(this.view.state).between(0, this.view.state.doc.length, (from, to) => {
            closed.set(`${from}:${to}`, { from, to });
        });
        for (const each of nodes.flatMap(every)) {
            const start = offsetOf(each);
            const range = foldRange(each, start);
            const open = this.isOpen(each);
            const reads = open ? opening(each) : null;
            const watched = this.#watching.get(each.key);
            // A fold reading another view than it did, or whose answer its view laid out again without, reads afresh.
            if (reads !== null && (watched === undefined || watched.view !== viewKey(reads) || (watched.answered && mountedOf(each) === null))) {
                watched?.stop();
                this.#read(each.key, reads);
            }
            if (range === null) {
                continue;
            }
            const folded = closed.has(`${range.from}:${range.to}`);
            if (open && folded) {
                effects.push(unfoldEffect.of({ from: range.from, to: range.to }));
            } else if (!open && !folded) {
                effects.push(foldEffect.of({ from: range.from, to: range.to }));
            }
        }
        this.view.dispatch({ effects: [...effects, redrawn.of(null)], annotations: fromCore.of(true) });
        this.outline?.laid();
    }

    /** Say whether the fold `node` is open: as the operator left it, else as its view says, else as its kind says. */
    isOpen(node: Node): boolean {
        const kind = foldKind(node);
        if (kind === null) {
            return true;
        }
        const set = node.block !== null && "open" in node.block ? node.block.open : null;
        return this.#opened.get(node.key) ?? set ?? this.kinds.startsOpen(kind);
    }

    /** Read what the fold keyed `key` reads as it opens, and keep it under the fold, answered again as it changes. */
    #read(key: string, viewing: Viewing): void {
        let stop = (): void => {};
        const watched = {
            view: viewKey(viewing),
            answered: false,
            stop: () => {
                stop();
            },
        };
        this.#watching.set(key, watched);
        stop = this.source.watch(viewing, (blocks) => {
            watched.answered = true;
            const fold = this.document.node(key);
            const mounted = fold === null ? null : mountedOf(fold);
            if (mounted?.viewing !== undefined && mounted.viewing !== null && viewKey(mounted.viewing) === viewKey(viewing)) {
                this.answered(mounted.key, blocks);
            } else {
                this.#apply(this.document.mount(key, viewing, blocks), key);
            }
        });
    }

    /** Open or close the fold keyed `key`, as the operator does; toggle it where `open` is none. */
    toggle(key: string, open?: boolean): void {
        const node = this.document.node(key);
        if (node !== null && foldKind(node) !== null) {
            this.fold([key], open ?? !this.isOpen(node));
        }
    }

    /** Open every fold `keys` names, or close every one, as the operator does, in one transaction. */
    fold(keys: readonly string[], open: boolean): void {
        const nodes = keys.flatMap((key) => {
            const node = this.document.node(key);
            return node === null || foldKind(node) === null ? [] : [node];
        });
        for (const node of nodes) {
            this.#opened.set(node.key, open);
        }
        this.#settle(nodes);
    }

    /** Return the keys of the folds chosen, in the order the document shows them. */
    chosen(): readonly string[] {
        return this.#chosen;
    }

    /** Choose the folds of `keys`, in place of what was chosen; none chooses nothing. */
    choose(keys: readonly string[]): void {
        const wanted = new Set(keys);
        this.#chosen = every(this.document.root)
            .filter((node) => wanted.has(node.key) && foldKind(node) !== null)
            .map((node) => node.key);
        this.view.dispatch({ effects: redrawn.of(null) });
    }

    /** Say `text` on the status line, or clear it. */
    say(text: string | null): void {
        this.view.dispatch({ effects: say.of(text) });
    }

    /**
     * Put the cursor at `position` and bring it into view, through vim's own cursor where vim runs, which a key's
     * command otherwise puts back where vim last left it once the command is done.
     */
    go(position: number): void {
        const at = Math.min(position, this.view.state.doc.length);
        const cm = getCM(this.view);
        if (cm === null) {
            this.view.dispatch({ selection: { anchor: at }, scrollIntoView: true });
            return;
        }
        cm.setCursor(cm.posFromIndex(at));
        this.view.dispatch({ effects: EditorView.scrollIntoView(at) });
    }

    /** Say again, in the frame around the document, where its cursor is and what the keys do in the pane they're in. */
    reframe(): void {
        if (!this.#made || (this.#header === null && this.#keys === null)) {
            return;
        }
        const panes = [this.window?.shell() ?? null, this.outline?.shell ?? null].filter((each): each is Shell => each !== null);
        const keyed = panes.find((each) => each.view.hasFocus) ?? this;
        framed(this, this.#header, null);
        framed(keyed, null, this.#keys);
    }

    /** Return the review of what the draft sends where, as the core last told it. */
    review(): Blocks {
        return this.#review;
    }

    /** Return the id of the line block the cursor is on; none where it's on another kind of block. */
    lineId(): string | null {
        const node = nodeAt(this.document.root, this.view.state.selection.main.head);
        return node.block?.block === "line" ? node.block.id : null;
    }

    /**
     * Return the range vim's visual mode selects, from the first selected line's start to the last's end; none outside
     * visual mode.
     */
    visual(): { from: number; to: number } | null {
        const vimState = getCM(this.view)?.state.vim as { visualMode?: boolean } | undefined;
        if (vimState?.visualMode !== true) {
            return null;
        }
        const { from, to } = this.view.state.selection.main;
        const doc = this.view.state.doc;
        return { from: doc.lineAt(from).from, to: doc.lineAt(Math.max(from, to - 1)).to };
    }

    /**
     * Return each block whose first line `range` holds and that shows, under no closed fold, outermost first: what a
     * selection acts on, never what it passes over hidden.
     */
    blocksIn(range: { from: number; to: number }): Node[] {
        return every(this.document.root).filter((node) => {
            if (node.block === null || node.lines === 0) {
                return false;
            }
            const start = offsetOf(node);
            if (start < range.from || start > range.to) {
                return false;
            }
            for (let at = node.parent; at !== null; at = at.parent) {
                if (foldKind(at) !== null && !this.isOpen(at)) {
                    return false;
                }
            }
            return true;
        });
    }

    /** Leave vim's visual mode, the cursor where it is. */
    unselect(): void {
        const cm = getCM(this.view);
        const vimState = cm?.state.vim as { visualMode?: boolean } | undefined;
        if (cm !== null && vimState?.visualMode === true) {
            Vim.handleKey(cm, "<Esc>", "mapping");
        }
    }

    /** Return the innermost fold the cursor is in, of the kind named `kind` where one is named. */
    foldAt(kind?: string): Node | null {
        let node: Node | null = nodeAt(this.document.root, this.view.state.selection.main.head);
        while (node !== null) {
            const own = foldKind(node);
            if (own !== null && (kind === undefined || own === kind)) {
                return node;
            }
            node = node.parent;
        }
        return null;
    }

    /**
     * Open every fold whose kind's level is `level` or shallower, or close every one at `level` or deeper, as `zr` and
     * `zm` do; every fold where no level is given, as `zR` and `zM` do.
     */
    level(open: boolean, level?: number): void {
        for (const node of every(this.document.root)) {
            const kind = foldKind(node);
            const at = kind === null ? undefined : (this.kinds.folds.get(kind)?.level ?? 0);
            if (at !== undefined && (level === undefined || (open ? at <= level : at >= level))) {
                this.#opened.set(node.key, open);
            }
        }
        this.#settle([this.document.root]);
    }

    /** Return the shell's state, as a law reads it. */
    state(): ShellState {
        const vimState = getCM(this.view)?.state.vim as { insertMode?: boolean; visualMode?: boolean } | undefined;
        const head = this.view.state.selection.main.head;
        const closed: string[] = [];
        for (const node of every(this.document.root)) {
            if (foldKind(node) !== null && !this.isOpen(node)) {
                closed.push(node.key);
            }
        }
        return {
            mode: vimState?.insertMode === true ? "insert" : vimState?.visualMode === true ? "visual" : "normal",
            line: this.view.state.doc.lineAt(head).number,
            at: nodeAt(this.document.root, head).key,
            closed,
            chosen: this.#chosen,
            said: this.view.state.field(said),
            comments: Object.fromEntries(every(this.document.root).flatMap((node) => (node.kind === "comment" ? [[node.key, node.head.join("\n")]] : []))),
            writing: (() => {
                const id = this.comments.writing();
                return id === null ? null : `comment:${id}`;
            })(),
            text: this.view.state.doc.toString(),
        };
    }
}

/** Say whether `node` is one of the nodes keyed in `keys`, or under one. */
function within(node: Node, keys: ReadonlySet<string>): boolean {
    let at: Node | null = node;
    while (at !== null) {
        if (keys.has(at.key)) {
            return true;
        }
        at = at.parent;
    }
    return false;
}

/** How a block stands for the operator, drawn before its first line: its glyph, in its meaning's colour. */
class Stands extends WidgetType {
    constructor(readonly standing: Standing) {
        super();
    }

    override eq(other: Stands): boolean {
        return other.standing === this.standing;
    }

    override toDOM(): HTMLElement {
        const glyph = document.createElement("span");
        glyph.className = `lup-standing lup-standing-${this.standing}`;
        glyph.textContent = `${standings[this.standing]} `;
        glyph.style.color = `var(--lup-${this.standing})`;
        glyph.title = this.standing;
        return glyph;
    }
}

/** The shell an editor shows, for the keymap's commands to find it by its editor. */
export const shells = Facet.define<Shell, Shell | null>({ combine: (values) => values[0] ?? null });

/** Draws what the text doesn't say: how deep each line sits, a fold's summary in its kind's colour, each span in its tone. */
const drawing = ViewPlugin.fromClass(
    class {
        decorations: DecorationSet;

        constructor(view: EditorView) {
            this.decorations = this.drawn(view);
        }

        update(update: ViewUpdate): void {
            if (update.docChanged || update.viewportChanged || update.transactions.some((each) => each.effects.some((effect) => effect.is(redrawn)))) {
                this.decorations = this.drawn(update.view);
            }
        }

        drawn(view: EditorView): DecorationSet {
            const shell = view.state.facet(shells);
            if (shell === null) {
                return Decoration.none;
            }
            const ranges: Range<Decoration>[] = [];
            const chosen = new Set(shell.chosen());
            for (const { from, to } of view.visibleRanges) {
                let position = from;
                while (position <= to) {
                    const line = view.state.doc.lineAt(position);
                    const node = nodeAt(shell.document.root, line.from);
                    const kind = foldKind(node);
                    const start = offsetOf(node);
                    const heading = kind !== null && start === line.from;
                    const classes = ["lup-line", `lup-${node.kind}`];
                    const attributes: Record<string, string> = {};
                    if (node.kind === "comment" && start === line.from) {
                        const told = shell.comments.said(node.key);
                        if (told !== null) {
                            classes.push("lup-comment-first");
                            attributes["data-to"] = `to ${told.to}`;
                            const said = told.reason ?? (told.outdated ? "outdated: the lines it quotes changed" : null);
                            if (said !== null) {
                                attributes["data-said"] = said;
                            }
                        }
                    }
                    if (heading) {
                        classes.push("lup-summary", `lup-kind-${kind}`);
                    }
                    if (chosen.size > 0 && within(node, chosen)) {
                        classes.push("lup-chosen");
                    }
                    if (heading && node.block !== null && shell.marked.has(node.block.id)) {
                        classes.push("lup-marked");
                    }
                    const verb = start === line.from && node.block !== null ? shell.marks.on(node) : null;
                    if (verb !== null) {
                        classes.push("lup-verb");
                        attributes["data-verb"] = `${glyphOf(verb.offer.verb)} ${verb.offer.says}${verb.held ? " (held back)" : ""}`;
                        if (verb.reason !== null) {
                            attributes["data-said"] = verb.reason;
                        }
                    }
                    const colour =
                        heading && kind !== null
                            ? shell.kinds.folds.get(kind)?.colour
                            : node.block?.block === "markdown"
                              ? (shell.kinds.colour(node.block.tone) ?? undefined)
                              : undefined;
                    ranges.push(
                        Decoration.line({
                            attributes: {
                                ...attributes,
                                class: classes.join(" "),
                                style: `--lup-depth: ${depthOf(node)};${colour === undefined ? "" : ` --lup-fold: var(--lup-${colour});`}`,
                            },
                        }).range(line.from),
                    );
                    const standing = start === line.from ? (node.block?.standing ?? null) : null;
                    if (standing !== null) {
                        ranges.push(Decoration.widget({ widget: new Stands(standing), side: -1 }).range(line.from));
                    }
                    const spans =
                        node.block?.block === "line" ? node.block.spans : heading && node.block?.block === "fold" ? node.block.summary : [];
                    let at = line.from;
                    for (const span of spans) {
                        if (span.text.length > 0) {
                            const tone = shell.kinds.colour(span.tone ?? "plain");
                            const weight = shell.kinds.weight(span.tone ?? "plain");
                            ranges.push(
                                Decoration.mark({
                                    class: `lup-tone${weight === null ? "" : ` lup-${weight}`}`,
                                    attributes: tone === null ? {} : { style: `color: var(--lup-${tone})` },
                                }).range(at, at + span.text.length),
                            );
                        }
                        at += span.text.length;
                    }
                    position = line.to + 1;
                }
            }
            for (const quoted of shell.comments.quoted()) {
                ranges.push(Decoration.mark({ class: "lup-quoted" }).range(quoted.from, quoted.to));
            }
            return Decoration.set(ranges, true);
        }
    },
    { decorations: (plugin) => plugin.decorations },
);

/** The editor's look, the second lup's: Normal mode's cursor a block in the focus colour, Insert mode's a bar in the
 * text's; the selection lightening what's under it; each line set in by how deep it sits; a fold's summary in its kind's
 * colour, a party's a band across in it; the margin's letters and bars in their columns. */
export const look = EditorView.theme(
    {
        "&": { height: "100%", backgroundColor: "var(--lup-bg)", color: "var(--lup-fg)", fontSize: "var(--lup-fs)" },
        "&.cm-focused": { outline: "none" },
        ".cm-scroller": { fontFamily: "var(--lup-mono)", lineHeight: "var(--lup-lh)" },
        ".cm-content": { padding: "0", caretColor: "var(--lup-focus)" },
        ".cm-cursor": { borderLeft: "2px solid var(--lup-fg)" },
        ".cm-fat-cursor": { background: "var(--lup-focus) !important", color: "var(--lup-bg) !important" },
        "&.cm-focused .cm-fat-cursor": { outline: "none" },
        // A cursor shows only where the keys go: the outline's and the window's, the document's too, hide once the
        // keys are elsewhere, the line their cursor is on marked in their stead.
        "&:not(.cm-focused) .cm-cursorLayer, &:not(.cm-focused) .cm-vimCursorLayer": { visibility: "hidden" },
        ".cm-activeLine": { background: "color-mix(in srgb, var(--lup-selection) 60%, transparent)" },
        ".cm-selectionBackground, &.cm-focused .cm-selectionBackground, .cm-selectionLayer .cm-selectionBackground": {
            background: "var(--lup-selection) !important",
        },
        ".cm-selectionLayer": { zIndex: "1 !important", mixBlendMode: "lighten", pointerEvents: "none" },
        ".cm-content ::selection": { color: "currentColor" },
        ".lup-line": { paddingLeft: "calc(var(--lup-depth) * 2ch + 1ch)" },
        ".lup-summary": { color: "var(--lup-fold, var(--lup-fg))", fontWeight: "700" },
        ".lup-markdown": { color: "var(--lup-fold, var(--lup-fg))" },
        ".lup-summary.lup-kind-party": {
            background: "color-mix(in srgb, var(--lup-fold) 14%, var(--lup-bg))",
            borderTop: "1px solid var(--lup-fold)",
            boxShadow: "inset 4px 0 0 var(--lup-fold)",
        },
        ".lup-bold": { fontWeight: "700" },
        ".lup-dim": { opacity: "0.7" },
        // Markdown, in a block and a comment (`markdown.ts`): headings, strong, emphasis and links as such; code in
        // the colour of strings, each line of a block of it barred; a construct's marks, where they show, muted, as a
        // quote's and a list's always are; and a table's cells padded by what's drawn beside them, muted as its pipes.
        ".tok-heading": { color: "var(--lup-orange)", fontWeight: "700" },
        ".tok-strong": { fontWeight: "700" },
        ".tok-emphasis": { fontStyle: "italic" },
        ".tok-link, .tok-url": { color: "var(--lup-link)", textDecoration: "underline" },
        ".tok-monospace": { color: "var(--lup-cyan)" },
        ".tok-processingInstruction, .tok-labelName, .tok-contentSeparator, .tok-quote, .tok-meta": { color: "var(--lup-muted)" },
        ".tok-strikethrough": { textDecoration: "line-through" },
        ".lup-line.lup-md-code": { boxShadow: "inset 2px 0 0 var(--lup-muted)" },
        ".lup-md-pad": { whiteSpace: "pre", color: "var(--lup-muted)" },
        ".cm-gutters": { background: "var(--lup-bg)", border: "0" },
        ".lup-margin": { width: "calc(2px + var(--lup-columns) * var(--lup-column))", borderRight: "1px solid var(--lup-rule)" },
        ".lup-margin .cm-gutterElement": { position: "relative", padding: "0" },
        ".lup-rails": { position: "absolute", inset: "0" },
        ".lup-rail, .lup-letter": { "--lup-left": "calc(1px + var(--lup-at) * var(--lup-column))" },
        ".lup-rail": {
            position: "absolute",
            top: "0",
            bottom: "0",
            left: "calc(var(--lup-left) + var(--lup-column) / 2 - 1px)",
            width: "2px",
            background: "currentColor",
            opacity: "0.4",
        },
        ".lup-rail.lup-bright": { opacity: "1" },
        ".lup-rail.lup-last": { bottom: "3px" },
        ".lup-letter": {
            position: "absolute",
            top: "1px",
            left: "var(--lup-left)",
            width: "var(--lup-column)",
            height: "calc(var(--lup-lh) - 2px)",
            lineHeight: "calc(var(--lup-lh) - 2px)",
            textAlign: "center",
            fontWeight: "700",
            cursor: "pointer",
        },
        ".lup-letter.lup-closed": { boxShadow: "inset 0 0 0 1px currentColor" },
        ".lup-letter.lup-drafted": { textDecoration: "underline 2px var(--lup-comment)", textUnderlineOffset: "2px" },
        ".lup-line.lup-chosen": { background: "var(--lup-selection)" },
        ".lup-line.lup-comment": {
            color: "var(--lup-comment)",
            background: "var(--lup-float)",
            boxShadow: "inset 2px 0 0 var(--lup-comment)",
        },
        ".lup-comment-first::before": { content: '"» "', color: "var(--lup-muted)" },
        // A verb marked on a block, at its first line's end: what the send will do, in what the operator wrote's colour.
        ".lup-verb::after": { content: '"  " attr(data-verb)', color: "var(--lup-comment)", fontWeight: "700" },
        ".lup-verb[data-said]::after": { content: '"  " attr(data-verb) "  ◂ " attr(data-said)', color: "var(--lup-trouble)", fontWeight: "700" },
        ".lup-standing-waiting": { fontWeight: "700" },
        ".lup-quoted": { textDecoration: "underline 2px var(--lup-comment)", textUnderlineOffset: "3px" },
        ".lup-placeholder .lup-counted": { color: "var(--lup-comment)" },
        ".lup-comment-first::after": { content: '"  " attr(data-to)', color: "var(--lup-muted)", fontStyle: "italic" },
        ".lup-comment-first[data-said]::after": {
            content: '"  " attr(data-to) "  ◂ " attr(data-said)',
            color: "var(--lup-trouble)",
            fontStyle: "italic",
        },
        ".lup-status": { padding: "0 1ch", borderTop: "1px solid var(--lup-border)", color: "var(--lup-fg)" },
        ".lup-window": { borderTop: "1px solid var(--lup-border)", display: "flex", flexDirection: "column", height: "40vh" },
        ".lup-window-title": { padding: "0 1ch", background: "var(--lup-float)", color: "var(--lup-muted)" },
        ".lup-window-body": { flex: "1", minHeight: "0" },
        ".cm-panels": { background: "var(--lup-float)", color: "var(--lup-fg)" },
        ".cm-panels-bottom": { borderTop: "0" },
        ".lup-placeholder": { border: "1px solid currentColor", padding: "0 0.5ch", marginLeft: "1ch", cursor: "pointer" },
    },
    { dark: true },
);

/**
 * The outline's look, over the document's, as the second lup's overview rows were: a row a fold, set in by how deep it
 * is, in its kind's colour, no band and no margin; the folds the document shows on screen with a bar beside them, and
 * the one its cursor is in highlighted.
 */
export const overview = EditorView.theme({
    ".lup-line.lup-summary": { fontWeight: "400" },
    ".lup-line.lup-summary.lup-kind-party": { background: "none", borderTop: "none", boxShadow: "none", fontWeight: "700" },
    ".lup-line.lup-summary.lup-marked": { boxShadow: "inset 3px 0 0 var(--lup-border)", background: "var(--lup-float)" },
    ".cm-line.cm-activeLine": { background: "var(--lup-selection)" },
});
