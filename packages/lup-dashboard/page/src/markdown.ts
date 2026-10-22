// Markdown shown as Markdown, in the review and a conversation alike: an
// agent's message and the operator's comments are written in it, and the buffer
// shows them as such rather than as the marks they're written with. Each
// stretch of the text written in Markdown (`Source`), an item's text, an
// agent's words or a comment, is read on its own by `@codemirror/lang-markdown`'s
// GFM parser, mounted in the buffer's syntax tree where the stretch is
// (`language`), the comments under an item's lines left out of the item's text,
// so a table or a list goes on past them; so the tree knows the list item at
// the cursor, and Enter in a comment continues it (`continued`). From the
// tree: emphasis, strong, code, headings and links highlighted by their tags,
// as a changed file's code is; the marks of each hidden, but on the line the
// cursor is on in a comment, where they're shown to be edited, as Markdown
// editors preview; and each table's cells padded so its columns line up, by
// decorations and never text, so a row stays one line of the buffer, vim moves
// over it as one, and a comment on it quotes its source (`decorate`;
// `docs/dashboard.md`, *The review*).
import { insertNewlineContinueMarkupCommand, markdownLanguage } from "@codemirror/lang-markdown";
import { Language, ParseContext, defineLanguageFacet, languageDataProp, syntaxHighlighting, syntaxTree } from "@codemirror/language";
import { StateEffect, StateField, type ChangeDesc, type EditorState, type Extension, type Range, type Text } from "@codemirror/state";
import { Decoration, ViewPlugin, WidgetType, type DecorationSet, type EditorView, type ViewUpdate } from "@codemirror/view";
import { NodeType, Parser, Tree, parseMixed, type Input, type PartialParse, type SyntaxNode, type SyntaxNodeRef, type TreeFragment } from "@lezer/common";
import { classHighlighter, tagHighlighter, tags } from "@lezer/highlight";

import type { Span } from "./comments";

/**
 * A stretch of the text written in Markdown, read as one: an item's or an agent's text, each of its lines whole, the
 * comments under its lines left out; or one comment, which may be edited.
 */
export interface Source extends Span {
    kind: "text" | "comment";
    /** The stretches it's read from, in the text's order, each ending after its line break, the comments among them left out: one, the whole, for a comment. */
    lines: Span[];
}

/**
 * Return a source of `kind` read from `lines`, in the text's order, those that touch joined; none from no line. An
 * empty comment is a source of one empty line, read as nothing until what's typed in it carries its end along.
 */
export function source(kind: Source["kind"], lines: readonly Span[]): Source | null {
    const joined: Span[] = [];
    for (const line of lines) {
        const last = joined.at(-1);
        if (last !== undefined && last.to === line.from) {
            last.to = line.to;
        } else {
            joined.push({ from: line.from, to: line.to });
        }
    }
    const first = joined[0];
    const last = joined.at(-1);
    return first === undefined || last === undefined ? null : { kind, from: first.from, to: last.to, lines: joined };
}

/** Return `span` without each of `holes`, in order: what's left on each side of each. */
export function without(span: Span, holes: readonly Span[]): Span[] {
    const kept: Span[] = [];
    let at = span.from;
    for (const hole of [...holes].sort((a, b) => a.from - b.from)) {
        if (hole.from > at) {
            kept.push({ from: at, to: Math.min(hole.from, span.to) });
        }
        at = Math.max(at, hole.to);
    }
    if (at < span.to) {
        kept.push({ from: at, to: span.to });
    }
    return kept;
}

/** Sets the sources of the text as it's laid out: in the transaction that lays it out, since the text is parsed in that transaction, by the sources it holds. */
export const sourced = StateEffect.define<readonly Source[]>();

/** Return `span` carried through `changes`: what's typed at its end goes into a comment (`grows`), and out of a text, whose end belongs to the comment under it. */
function carried(span: Span, changes: ChangeDesc, grows: boolean): Span {
    return { from: changes.mapPos(span.from, -1), to: changes.mapPos(span.to, grows ? 1 : -1) };
}

/** The sources of the text as it's laid out, each carried with the text's changes until it's laid out again. */
export const sources = StateField.define<readonly Source[]>({
    create: () => [],
    update: (value, transaction) => {
        const set = transaction.effects.findLast((each) => each.is(sourced));
        if (set !== undefined) {
            return set.value as readonly Source[];
        }
        if (!transaction.docChanged) {
            return value;
        }
        return value.map((each) => ({
            ...each,
            ...carried(each, transaction.changes, each.kind === "comment"),
            lines: each.lines.map((line) => carried(line, transaction.changes, each.kind === "comment")),
        }));
    },
});

const own = defineLanguageFacet();

/** The outer tree's node types: the text whole, and a stretch written in Markdown, which the Markdown parser is mounted on over its lines. */
const TEXT = NodeType.define({ id: 0, name: "Text", top: true, props: [[languageDataProp, own]] });
const MARKDOWN = NodeType.define({ id: 1, name: "Markdown" });

/** A node of the outer tree being built: its stretch, and its children so far, each at its place from the node's start. */
interface Building {
    type: NodeType;
    from: number;
    to: number;
    children: Tree[];
    positions: number[];
}

/** Return the tree of the text's sources, `length` long: a node for each, a comment under an item's lines inside the item's node, in the text's order. */
export function treeOf(found: readonly Source[], length: number): Tree {
    const ordered = [...found].sort((a, b) => a.from - b.from || b.to - a.to);
    const open: Building[] = [{ type: TEXT, from: 0, to: length, children: [], positions: [] }];
    const close = () => {
        const done = open.pop();
        const parent = open.at(-1);
        if (done !== undefined && parent !== undefined) {
            parent.children.push(new Tree(done.type, done.children, done.positions, done.to - done.from));
            parent.positions.push(done.from - parent.from);
        }
    };
    for (const each of ordered) {
        while (open.length > 1 && each.from >= (open.at(-1)?.to ?? 0)) {
            close();
        }
        open.push({ type: MARKDOWN, from: each.from, to: Math.min(each.to, length), children: [], positions: [] });
    }
    while (open.length > 1) {
        close();
    }
    const top = open[0];
    return new Tree(TEXT, top?.children ?? [], top?.positions ?? [], length);
}

/**
 * The text's own parser: the tree of its sources (`treeOf`), read from the state being parsed, with the Markdown parser
 * mounted on each over its lines (`parseMixed`), so each is read as one whatever lies between its lines.
 */
class Sourced extends Parser {
    createParse(input: Input, fragments: readonly TreeFragment[], ranges: readonly Span[]): PartialParse {
        const found = ParseContext.get()?.state.field(sources, false) ?? [];
        const tree = treeOf(found, input.length);
        const byStart = new Map(found.map((each) => [each.from, each]));
        const whole: PartialParse = { parsedPos: input.length, stoppedAt: null, advance: () => tree, stopAt: () => undefined };
        const nest = (node: SyntaxNodeRef) => {
            const each = node.type === MARKDOWN ? byStart.get(node.from) : undefined;
            if (each === undefined) {
                return null;
            }
            const overlay = each.lines
                .map((line) => ({ from: line.from, to: Math.min(line.to, input.length) }))
                .filter((line) => line.to > line.from);
            return overlay.length === 0 ? null : { parser: markdownLanguage.parser, overlay };
        };
        return parseMixed(nest)(whole, input, fragments, ranges);
    }
}

/** The text's language: its sources read as Markdown, each in a tree of its own, the rest of the text plain. */
export const language = new Language(own, new Sourced(), [], "sources");

/**
 * Enter in a comment: the next item of the list the cursor is in, at its indentation, with its bullet or the next
 * number, or the quote mark of the quote it's in; on an empty item, the list's end. A plain line break elsewhere.
 */
export const continued = insertNewlineContinueMarkupCommand({ nonTightLists: false });

/** Return the Markdown tree's root of `each`, in `tree`, where it's been read; none before it has. */
function rootOf(tree: Tree, each: Source): SyntaxNode | null {
    const first = each.lines[0];
    if (first === undefined) {
        return null;
    }
    let node: SyntaxNode | null = tree.topNode;
    while (node !== null && node.name !== "Document") {
        node = node.enter(first.from, 1);
    }
    return node;
}

/** The nodes that are a construct's marks, hidden where it's shown as written: emphasis', strong's, code's, a link's, a strikethrough's. */
const MARKS = new Set(["EmphasisMark", "CodeMark", "LinkMark", "StrikethroughMark"]);

/** What of a link's or an image's is its address, hidden with its marks; the text stays, saying the address on hover. */
const ADDRESSES = new Set(["URL", "LinkTitle", "LinkLabel"]);

/** The blocks of code, each line of which is barred. */
const CODE_BLOCKS = new Set(["FencedCode", "CodeBlock"]);

/**
 * Return what of `node` is hidden where its construct is shown as written: a mark (`MARKS`); a heading's `#`s with the
 * space beside them, or its underline; a link's address (`ADDRESSES`); the backslash of an escape. None of any other.
 */
export function hiddenBy(node: SyntaxNodeRef, doc: Text): Span | null {
    if (MARKS.has(node.name)) {
        return { from: node.from, to: node.to };
    }
    if (node.name === "HeaderMark") {
        if (doc.sliceString(node.to, node.to + 1) === " ") {
            return { from: node.from, to: node.to + 1 };
        }
        const before = doc.sliceString(node.from - 1, node.from);
        return { from: before === " " ? node.from - 1 : node.from, to: node.to };
    }
    if (ADDRESSES.has(node.name)) {
        const parent = node.node.parent?.name;
        return parent === "Link" || parent === "Image" ? { from: node.from, to: node.to } : null;
    }
    if (node.name === "Escape") {
        return { from: node.from, to: node.from + 1 };
    }
    return null;
}

const HIDDEN = Decoration.replace({});
const CODE = Decoration.line({ class: "md-code" });

/** Padding beside a table's cell, drawn and never written: as many spaces, or dashes on the row under the header, as its column is wider than it. */
class Padding extends WidgetType {
    constructor(readonly text: string) {
        super();
    }

    override eq(other: Padding): boolean {
        return other.text === this.text;
    }

    override toDOM(): HTMLElement {
        const made = document.createElement("span");
        made.className = "md-pad";
        made.textContent = this.text;
        return made;
    }
}

/** Return a widget of `count` of `filler` at `at`, after what's there where `after`, else before it; none for no padding. */
function padding(at: number, count: number, filler: string, after: boolean): Range<Decoration>[] {
    if (count <= 0) {
        return [];
    }
    return [Decoration.widget({ widget: new Padding(filler.repeat(count)), side: after ? 1 : -1 }).range(at)];
}

/** How many columns a text takes in the monospace buffer: its characters. */
function width(text: string): number {
    return [...text].length;
}

/** Return what's hidden in `node`'s subtree, in order (`hiddenBy`). */
function hiddenIn(node: SyntaxNode, doc: Text): Span[] {
    const found: Span[] = [];
    node.cursor().iterate((each) => {
        const hidden = hiddenBy(each, doc);
        if (hidden !== null) {
            found.push(hidden);
        }
    });
    return found;
}

/** How a column's cells are aligned, as the row under the header says with its colons. */
type Alignment = "left" | "right" | "center";

/** One slot of a table's row, between two pipes, or a pipe and the row's edge: its stretch, with the spaces around its cell, and the cell in it, if any. */
interface Slot extends Span {
    cell: SyntaxNode | null;
}

/** One slot of the row under a table's header, `|:---:|`: its stretch, where its dashes end, and the alignment it gives its column. */
interface Ruled extends Span {
    dashes: number;
    alignment: Alignment;
}

/** Return the slots of a table's row, between its pipes: an edge's, where the row has no pipe there, counted. */
function slotsOf(row: SyntaxNode): Slot[] {
    const cells = row.getChildren("TableCell");
    const edges = [row.from, ...row.getChildren("TableDelimiter").flatMap((pipe) => [pipe.from, pipe.to]), row.to];
    const found: Slot[] = [];
    for (let at = 0; at + 1 < edges.length; at += 2) {
        const from = edges[at] ?? row.from;
        const to = edges[at + 1] ?? row.to;
        const cell = cells.find((each) => each.from >= from && each.to <= to) ?? null;
        // Nothing before a leading pipe, or after a trailing one.
        if (to > from || (at > 0 && at + 2 < edges.length)) {
            found.push({ from, to, cell });
        }
    }
    return found;
}

/** Return the slots of the row under a table's header, `from` to `to` of `doc`: between its pipes, each with where its dashes end and the alignment its colons say. */
function ruled(doc: Text, from: number, to: number): Ruled[] {
    const text = doc.sliceString(from, to);
    const found: Ruled[] = [];
    let start = 0;
    const slot = (end: number) => {
        const raw = text.slice(start, end);
        const inner = raw.trim();
        if (inner !== "") {
            const left = inner.startsWith(":");
            const right = inner.endsWith(":");
            const leading = raw.length - raw.trimStart().length;
            found.push({
                from: from + start,
                to: from + end,
                dashes: from + start + leading + inner.length - (right ? 1 : 0),
                alignment: left && right ? "center" : right ? "right" : "left",
            });
        }
        start = end + 1;
    };
    for (let at = 0; at < text.length; at += 1) {
        if (text[at] === "|" && text[at - 1] !== "\\") {
            slot(at);
        }
    }
    slot(text.length);
    return found;
}

/**
 * Return the decorations that line a table's columns up: in each slot of each row, the padding its column is wider
 * than it, after its cell, before it or on each side as the column is aligned; the row under the header's dashes drawn
 * out to each column's width. A slot is as wide as its text shows, its cell's hidden marks left out, but on a revealed
 * line, where they show.
 */
function table(node: SyntaxNode, doc: Text, revealed: (line: number) => boolean): Range<Decoration>[] {
    const rows = [...node.getChildren("TableHeader"), ...node.getChildren("TableRow")].map((row) =>
        slotsOf(row).map((slot) => {
            const shown = slot.cell === null || revealed(doc.lineAt(slot.from).from);
            const hidden = shown || slot.cell === null ? [] : hiddenIn(slot.cell, doc);
            const unseen = hidden.reduce((sum, each) => sum + width(doc.sliceString(each.from, each.to)), 0);
            return { ...slot, width: width(doc.sliceString(slot.from, slot.to)) - unseen };
        }),
    );
    const rule = node.getChild("TableDelimiter");
    const rules = rule === null ? [] : ruled(doc, rule.from, rule.to);
    const widths: number[] = [];
    for (const slots of [...rows, rules.map((each) => ({ width: each.to - each.from }))]) {
        slots.forEach(({ width: wide }, column) => {
            widths[column] = Math.max(widths[column] ?? 0, wide);
        });
    }
    const made: Range<Decoration>[] = [];
    for (const slots of rows) {
        slots.forEach(({ cell, from, to, width: wide }, column) => {
            const missing = (widths[column] ?? 0) - wide;
            const alignment = rules[column]?.alignment ?? "left";
            const before = alignment === "right" ? missing : alignment === "center" ? Math.floor(missing / 2) : 0;
            // Beside the cell; in an empty slot, inside its pipes.
            made.push(...padding(cell?.from ?? from, before, " ", cell === null), ...padding(cell?.to ?? to, missing - before, " ", cell !== null));
        });
    }
    rules.forEach((each, column) => {
        made.push(...padding(each.dashes, (widths[column] ?? 0) - (each.to - each.from), "-", true));
    });
    return made;
}

/** Return the decorations of the Markdown read in `tree` under `root`, from `from` to `to`, a source's: as `decorate` says them. */
function decorated(root: SyntaxNode, doc: Text, from: number, to: number, revealed: (line: number) => boolean): Range<Decoration>[] {
    const made: Range<Decoration>[] = [];
    root.cursor().iterate((node) => {
        if (node.to < from || node.from > to) {
            return false;
        }
        if (node.name === "Table") {
            made.push(...table(node.node, doc, revealed));
        }
        if (CODE_BLOCKS.has(node.name)) {
            for (let line = doc.lineAt(node.from).number; line <= doc.lineAt(node.to).number; line += 1) {
                made.push(CODE.range(doc.line(line).from));
            }
        }
        if (node.name === "Link" || node.name === "Image") {
            const address = node.node.getChild("URL");
            if (address !== null) {
                const title = doc.sliceString(address.from, address.to);
                made.push(Decoration.mark({ attributes: { title } }).range(node.from, node.to));
            }
        }
        const hidden = hiddenBy(node, doc);
        if (hidden !== null && hidden.to > hidden.from && !revealed(doc.lineAt(hidden.from).from)) {
            made.push(HIDDEN.range(hidden.from, hidden.to));
        }
        return true;
    });
    return made;
}

/**
 * Return the decorations of the Markdown shown in `ranges` of `state`'s text, by its sources' trees as far as they're
 * read: each construct's marks hidden (`hiddenBy`), but on a line `revealed` says is, the cursor's in a comment; each
 * line of a block of code barred; each link's text saying its address on hover; and each table's cells padded so its
 * columns line up (`table`), those on a revealed line as they show there.
 */
export function decorate(state: EditorState, ranges: readonly Span[], revealed: (line: number) => boolean): Range<Decoration>[] {
    const tree = syntaxTree(state);
    const made: Range<Decoration>[] = [];
    for (const each of state.field(sources, false) ?? []) {
        const root = ranges.some((range) => each.to >= range.from && each.from <= range.to) ? rootOf(tree, each) : null;
        if (root === null) {
            continue;
        }
        for (const range of ranges) {
            if (each.to >= range.from && each.from <= range.to) {
                made.push(...decorated(root, state.doc, Math.max(range.from, each.from), Math.min(range.to, each.to), revealed));
            }
        }
    }
    return made;
}

/** Return which line the cursor reveals the marks of: the one it's on, where that's in a comment; none elsewhere. */
export function revealing(state: EditorState): number | null {
    const head = state.selection.main.head;
    const inComment = (state.field(sources, false) ?? []).some((each) => each.kind === "comment" && head >= each.from && head <= each.to);
    return inComment ? state.doc.lineAt(head).from : null;
}

/** Return what `decorate` hides on the line at `position` of `state`, in order: the stretches a cursor finds no character to rest on. */
export function hiddenOn(state: EditorState, position: number): Span[] {
    const line = state.doc.lineAt(position);
    const revealed = revealing(state);
    return decorate(state, [{ from: line.from, to: line.to }], (at) => at === revealed)
        .filter((each) => each.value === HIDDEN)
        .map((each) => ({ from: each.from, to: each.to }))
        .sort((a, b) => a.from - b.from);
}

/**
 * What the Markdown shows on the lines in view, drawn again as the view scrolls, the text changes, more of it is read,
 * the sources are laid out anew, or the cursor moves, since the line it's on in a comment shows its marks.
 */
const shown = ViewPlugin.fromClass(
    class {
        decorations: DecorationSet;

        constructor(view: EditorView) {
            this.decorations = this.drawn(view);
        }

        update(update: ViewUpdate) {
            const reread = syntaxTree(update.startState) !== syntaxTree(update.state);
            const relaid = update.startState.field(sources, false) !== update.state.field(sources, false);
            if (update.docChanged || update.viewportChanged || update.selectionSet || reread || relaid) {
                this.decorations = this.drawn(update.view);
            }
        }

        drawn(view: EditorView): DecorationSet {
            const revealed = revealing(view.state);
            return Decoration.set(
                decorate(view.state, view.visibleRanges, (line) => line === revealed),
                true,
            );
        }
    },
    { decorations: (plugin) => plugin.decorations },
);

/** The classes of Markdown's own tags, which CodeMirror's class highlighter gives none: code, a construct's marks, a quote, a strikethrough, a rule. */
const marked = tagHighlighter([
    { tag: tags.monospace, class: "tok-monospace" },
    { tag: tags.processingInstruction, class: "tok-processingInstruction" },
    { tag: tags.quote, class: "tok-quote" },
    { tag: tags.strikethrough, class: "tok-strikethrough" },
    { tag: tags.contentSeparator, class: "tok-contentSeparator" },
]);

/** Return the editor's Markdown: its sources, their language, their highlighting by CodeMirror's class highlighter and Markdown's own tags, and what's shown of them. */
export function markdown(): Extension {
    return [sources, language.extension, syntaxHighlighting(classHighlighter), syntaxHighlighting(marked), shown];
}
