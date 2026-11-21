// Markdown shown as Markdown, as the second lup's dashboard showed it: a view's `Markdown` blocks and the operator's
// comments are written in it, and the document shows them as such rather than as the marks they're written with. Each
// stretch of the text written in Markdown (`Source`), a block's own lines or a comment, is read on its own by
// `@codemirror/lang-markdown`'s GFM parser, mounted in the editor's syntax tree where the stretch is (`language`), the
// comments under a block's lines left out of the block's text, so a table or a list goes on past them. The sources
// come from the document's tree as the shell lays it out (`sourcesOf`), and are carried through what the operator
// types until it's laid out again.
//
// From the tree: emphasis, strong, code, headings and links highlighted by their tags; the marks of each hidden, but on
// the line the cursor is on in a comment, where they're shown to be edited, as Markdown editors preview; a hidden mark
// no place for vim's cursor, which has no width to show on it, so a motion put on one goes on past it the way it was
// going (`pastHidden`); each line of a block of code barred; and each table's cells padded so its columns line up, by
// decorations and never text, so a row stays one line of the document, vim moves over it as one, and a comment on it
// quotes what it says.
//
// A comment's lists are written as neovim's Markdown writes them: Enter opens a line at the indentation of the one it's
// on, never with a list's bullet or number, as vim's `o` and `O` do (`brokenLine`); an indentation nothing's typed
// after goes as the writing ends (`unindented`); and vim's `>>` and `<<`, and Ctrl+T and Ctrl+D in insert mode, which
// Tab and Shift+Tab are, move a line in and out by the list's indentation, nesting it under the item above as the tree
// reads it (`shifted`).

import { markdownLanguage } from "@codemirror/lang-markdown";
import {
    Language,
    ParseContext,
    defineLanguageFacet,
    getIndentUnit,
    indentString,
    languageDataProp,
    syntaxHighlighting,
    syntaxTree,
} from "@codemirror/language";
import {
    EditorSelection,
    Prec,
    StateEffect,
    StateField,
    countColumn,
    type ChangeDesc,
    type EditorState,
    type Extension,
    type Line,
    type Range,
    type Text,
    type TransactionSpec,
} from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, WidgetType, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import { NodeType, Parser, Tree, parseMixed, type Input, type PartialParse, type SyntaxNode, type SyntaxNodeRef, type TreeFragment } from "@lezer/common";
import { classHighlighter, tagHighlighter, tags } from "@lezer/highlight";
import { Vim, getCM } from "@replit/codemirror-vim";

import { every, offsetOf, ownLines, type Node } from "../document/tree";

/** A stretch of the editor's text: from its start to its end. */
export interface Span {
    readonly from: number;
    readonly to: number;
}

/** A stretch of the text written in Markdown, read as one: a block's own lines, the comments under them left out; or one comment, which may be edited. */
export interface Source extends Span {
    readonly kind: "text" | "comment";
    /** The stretches it's read from, in the text's order, each ending after its line break: a block's lines, or the comment whole. */
    readonly lines: readonly Span[];
}

/**
 * Return what's written in Markdown in the document under `root`, as it's laid out: each `Markdown` block's own lines,
 * each ending after its line break, and each comment whole; none past the text's end, `root`'s size.
 */
export function sourcesOf(root: Node): Source[] {
    const end = root.size;
    const clamped = (span: Span): Span => ({ from: Math.min(span.from, end), to: Math.min(span.to, end) });
    return every(root).flatMap((node): Source[] => {
        if (node.lines === 0) {
            return [];
        }
        if (node.kind === "comment") {
            const from = offsetOf(node);
            const whole = clamped({ from, to: from + node.size });
            return [{ kind: "comment", ...whole, lines: [whole] }];
        }
        if (node.block?.block !== "markdown") {
            return [];
        }
        const lines = ownLines(node).map((line) => clamped({ from: line.from, to: line.to + 1 }));
        const first = lines[0];
        const last = lines.at(-1);
        return first === undefined || last === undefined ? [] : [{ kind: "text", from: first.from, to: last.to, lines }];
    });
}

/** Sets the sources of the text as it's laid out: in the transaction that lays it out, since the text is parsed in that transaction, by the sources it holds. */
export const sourced = StateEffect.define<readonly Source[]>();

/** Return `span` carried through `changes`: what's typed at its end goes into a comment (`grows`), and out of a block's text, whose end belongs to the comment under it. */
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

/** A node of the outer tree being built: its stretch, the source it's the node of, none for the text whole, and its children so far, each at its place from the node's start. */
interface Building {
    readonly type: NodeType;
    readonly from: number;
    readonly to: number;
    readonly source: Source | null;
    readonly children: Tree[];
    readonly positions: number[];
}

/** Return a new tree of `node` as built. */
function built(node: Building): Tree {
    return new Tree(node.type, node.children, node.positions, node.to - node.from);
}

/**
 * Return the tree of the text's sources, `length` long: a node for each, a comment under a block's lines inside the
 * block's node, in the text's order, each node's tree `made` of it as built, new unless the maker has one to reuse.
 */
function treeOf(found: readonly Source[], length: number, made: (node: Building) => Tree = built): Tree {
    const ordered = [...found].sort((a, b) => a.from - b.from || b.to - a.to);
    const open: Building[] = [{ type: TEXT, from: 0, to: length, source: null, children: [], positions: [] }];
    const close = () => {
        const done = open.pop();
        const parent = open.at(-1);
        if (done !== undefined && parent !== undefined) {
            parent.children.push(made(done));
            parent.positions.push(done.from - parent.from);
        }
    };
    for (const each of ordered) {
        while (open.length > 1 && each.from >= (open.at(-1)?.to ?? 0)) {
            close();
        }
        open.push({ type: MARKDOWN, from: each.from, to: Math.min(each.to, length), source: each, children: [], positions: [] });
    }
    while (open.length > 1) {
        close();
    }
    const top = open[0];
    return new Tree(TEXT, top?.children ?? [], top?.positions ?? [], length);
}

/** Return what names a node across parses: its source's kind, its length, the text of each of its lines where it is from the node's start, and each child's name where it is. */
function keyOf(node: Building, input: Input, named: WeakMap<Tree, string>): string {
    const lines = (node.source?.lines ?? []).map((line) => [line.from - node.from, input.read(line.from, Math.min(line.to, input.length))]);
    const children = node.children.map((child, at) => [node.positions[at] ?? 0, named.get(child) ?? ""]);
    return JSON.stringify([node.source?.kind ?? "", node.to - node.from, lines, children]);
}

/**
 * The text's own parser: the tree of its sources (`treeOf`), read from the state being parsed, with the Markdown parser
 * mounted on each over its lines (`parseMixed`), so each is read as one whatever lies between its lines. A source's
 * node is the very `Tree` the last parse built for a source of the same text and shape (`keyOf`), the Markdown tree
 * mounted on it going with it, since the mixed parser reuses a mounted tree on the very node it was mounted on alone:
 * an edit reads anew the source it touched, and the block's text a comment under its lines is in, and a layout anew
 * the sources it changed, every other source being read as it was.
 */
class Sourced extends Parser {
    /** Each source's node as last built, by what names it (`keyOf`), kept from one parse to the next. */
    kept = new Map<string, Tree>();

    createParse(input: Input, fragments: readonly TreeFragment[], ranges: readonly Span[]): PartialParse {
        const found = ParseContext.get()?.state.field(sources, false) ?? [];
        const named = new WeakMap<Tree, string>();
        const nodes = new Map<string, Tree>();
        const tree = treeOf(found, input.length, (node) => {
            const key = keyOf(node, input, named);
            const made = nodes.get(key) ?? this.kept.get(key) ?? built(node);
            nodes.set(key, made);
            named.set(made, key);
            return made;
        });
        this.kept = nodes;
        const byStart = new Map(found.map((each) => [each.from, each]));
        const whole: PartialParse = { parsedPos: input.length, stoppedAt: null, advance: () => tree, stopAt: () => undefined };
        const nest = (node: SyntaxNodeRef) => {
            const each = node.type === MARKDOWN ? byStart.get(node.from) : undefined;
            if (each === undefined) {
                return null;
            }
            const overlay = each.lines.map((line) => ({ from: line.from, to: Math.min(line.to, input.length) })).filter((line) => line.to > line.from);
            return overlay.length === 0 ? null : { parser: markdownLanguage.parser, overlay };
        };
        return parseMixed(nest)(whole, input, fragments, ranges);
    }
}

/** The text's language: its sources read as Markdown, each in a tree of its own, the rest of the text plain. */
const language = new Language(own, new Sourced(), [], "sources");

/** Return the indentation `text`, a line, begins with: its spaces and tabs before anything else. */
function indentationOf(text: string): string {
    let at = 0;
    while (text[at] === " " || text[at] === "\t") {
        at += 1;
    }
    return text.slice(0, at);
}

/** Return the comment the position `at` of `state` is in; none where it's in none. */
function commentAt(state: EditorState, at: number): Source | null {
    return state.field(sources, false)?.find((each) => each.kind === "comment" && at >= each.from && at <= each.to) ?? null;
}

/**
 * Return what Enter does in a comment, as neovim's Markdown has it: a line break, the new line at the indentation of
 * the one it's broken from, and never a list's bullet or number, which the operator types where they want an item
 * (`- `, `1. `). As vim's `autoindent` has it, the spaces after the cursor go, so what follows starts at that
 * indentation, and a line left holding nothing but spaces is emptied.
 */
export function brokenLine(state: EditorState): TransactionSpec {
    return state.changeByRange((range) => {
        const line = state.doc.lineAt(range.from);
        const indentation = indentationOf(line.text);
        const before = state.sliceDoc(line.from, range.from);
        const from = indentationOf(before) === before ? line.from : range.from;
        const end = state.doc.lineAt(range.to);
        const to = range.to + indentationOf(state.sliceDoc(range.to, end.to)).length;
        const insert = `\n${indentation}`;
        return { changes: { from, to, insert }, range: EditorSelection.cursor(from + insert.length) };
    });
}

/**
 * Return what ending insert mode does to the line of a comment at `position`: emptied where it holds nothing but its
 * indentation, as vim's `autoindent` takes back an indentation nothing was typed after; none elsewhere.
 */
export function unindented(state: EditorState, position: number): TransactionSpec | null {
    const line = state.doc.lineAt(position);
    if (commentAt(state, position) === null || line.length === 0 || indentationOf(line.text) !== line.text) {
        return null;
    }
    return { changes: { from: line.from, to: line.to }, userEvent: "delete" };
}

/** Where a line that begins a list's item begins, and where the item's words begin, in columns. */
interface Item {
    readonly indentation: number;
    readonly words: number;
}

/**
 * Return where the line `line` of `state` begins a list's item (`Item`), its bullet or number read from the Markdown
 * tree, right after its indentation; none where it begins none, as in a block of code. An item's words begin one column
 * past its mark where nothing follows it, or where what follows is indented as code is, five columns or more past it,
 * as Markdown reads them.
 */
function itemOf(state: EditorState, line: Line): Item | null {
    const indentation = indentationOf(line.text);
    const at = line.from + indentation.length;
    const mark = at < line.to ? syntaxTree(state).resolveInner(at, 1) : null;
    if (mark === null || mark.name !== "ListMark" || mark.from !== at) {
        return null;
    }
    const marked = line.text.slice(0, mark.to - line.from);
    const spaces = indentationOf(line.text.slice(marked.length));
    const column = countColumn(marked, state.tabSize);
    const gap = countColumn(marked + spaces, state.tabSize) - column;
    const empty = marked.length + spaces.length === line.length;
    return { indentation: countColumn(indentation, state.tabSize), words: column + (empty || gap > 4 ? 1 : gap) };
}

/**
 * Return the column the line `number` of `state` goes to as it's moved in (`inward`) or out, from `column`, its
 * indentation, by the list's indentation, read from the lines above it in its comment: in, to where the words of the
 * nearest item above at its indentation or less begin, which nests it under that item as Markdown nests one; out, to
 * where the words of the nearest item above indented less begin, where the line is past them, else to where that item
 * begins. One indent unit where no item above says, or where the line is in past that item's words already.
 */
function shiftedTo(state: EditorState, number: number, column: number, inward: boolean): number {
    const comment = commentAt(state, state.doc.line(number).from);
    const first = comment === null ? number : state.doc.lineAt(comment.from).number;
    for (let above = number - 1; above >= first; above -= 1) {
        const item = itemOf(state, state.doc.line(above));
        if (item === null || (inward ? item.indentation > column : item.indentation >= column)) {
            continue;
        }
        if (inward) {
            return item.words > column ? item.words : column + getIndentUnit(state);
        }
        return item.words < column ? item.words : item.indentation;
    }
    return Math.max(0, column + (inward ? 1 : -1) * getIndentUnit(state));
}

/**
 * Return what vim's `>` and `<` do to the lines of `state`'s selection, `>>` and `<<` to the cursor's line, as Ctrl+T
 * and Ctrl+D do in insert mode: the first of them moved in (`inward`) or out by the list's indentation (`shiftedTo`),
 * and each other by as much, so an item's own items go with it; an empty line stays empty, but the cursor's, as on a
 * line just begun. The cursor stays on what it was on, or after the indentation where it was in it. None where nothing
 * moves.
 */
export function shifted(state: EditorState, inward: boolean): TransactionSpec | null {
    const numbers = new Set<number>();
    for (const range of state.selection.ranges) {
        const last = state.doc.lineAt(range.to);
        // A selection of whole lines ends at the start of the line after them.
        const end = !range.empty && range.to === last.from && last.number > 1 ? last.number - 1 : last.number;
        for (let number = state.doc.lineAt(range.from).number; number <= end; number += 1) {
            if (range.empty || state.doc.line(number).length > 0) {
                numbers.add(number);
            }
        }
    }
    const lines = [...numbers].sort((a, b) => a - b).map((number) => state.doc.line(number));
    const top = lines[0];
    if (top === undefined) {
        return null;
    }
    const columnOf = (text: string) => countColumn(indentationOf(text), state.tabSize);
    const step = shiftedTo(state, top.number, columnOf(top.text), inward) - columnOf(top.text);
    const moving = lines.flatMap((line) => {
        const was = indentationOf(line.text);
        const now = indentString(state, Math.max(0, columnOf(line.text) + step));
        return now === was ? [] : [{ line, from: line.from, to: line.from + was.length, insert: now }];
    });
    if (moving.length === 0) {
        return null;
    }
    const changes = state.changes(moving.map(({ from, to, insert }) => ({ from, to, insert })));
    const carriedTo = (position: number) => {
        const moved = moving.find(({ line }) => position >= line.from && position <= line.to);
        return moved !== undefined && position <= moved.to ? changes.mapPos(moved.to, 1) : changes.mapPos(position, 1);
    };
    const selection = EditorSelection.create(
        state.selection.ranges.map((range) => EditorSelection.range(carriedTo(range.anchor), carriedTo(range.head))),
        state.selection.mainIndex,
    );
    return { changes, selection, userEvent: inward ? "input.indent" : "delete.dedent" };
}

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
function hiddenBy(node: SyntaxNodeRef, doc: Text): Span | null {
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
const CODE = Decoration.line({ class: "lup-md-code" });

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
        made.className = "lup-md-pad";
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

/** How many columns a text takes in the monospace document: its characters. */
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
    readonly cell: SyntaxNode | null;
}

/** One slot of the row under a table's header, `|:---:|`: its stretch, where its dashes end, and the alignment it gives its column. */
interface Ruled extends Span {
    readonly dashes: number;
    readonly alignment: Alignment;
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

/** Return the slots of the row under a table's header, `rule`, between its pipes: each with where its dashes end and the alignment its colons say. */
function ruled(doc: Text, rule: SyntaxNode): Ruled[] {
    const text = doc.sliceString(rule.from, rule.to);
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
                from: rule.from + start,
                to: rule.from + end,
                dashes: rule.from + start + leading + inner.length - (right ? 1 : 0),
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
    const rules = rule === null ? [] : ruled(doc, rule);
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
function decorate(state: EditorState, ranges: readonly Span[], revealed: (line: number) => boolean): Range<Decoration>[] {
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
function revealing(state: EditorState): number | null {
    const head = state.selection.main.head;
    return commentAt(state, head) === null ? null : state.doc.lineAt(head).from;
}

/** Return what's hidden on the line at `position` of `state`, in order: the stretches a cursor finds no character to rest on. */
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

/**
 * Return where vim's cursor rests once `state`'s selection is made, where it was put on a mark the Markdown hides
 * (`hiddenOn`), which has no width to show it on: on the next character shown the way it came from `was`, as if the
 * mark weren't there, or back where going on would leave the line, since outside `visual` mode a block cursor rests
 * on a character and never on the line's end. In visual mode the cursor is the character before the head where the
 * selection runs forward, as vim draws it, and the anchor stays. None where the cursor rests on a character shown
 * already, or the line has none to rest on.
 */
export function pastHidden(state: EditorState, was: number, visual: boolean): EditorSelection | null {
    const { main } = state.selection;
    const ahead = main.anchor < main.head;
    const at = ahead ? main.head - 1 : main.head;
    const hidden = hiddenOn(state, at);
    if (!hidden.some((each) => at >= each.from && at < each.to)) {
        return null;
    }
    const line = state.doc.lineAt(at);
    const last = visual && line.to < state.doc.length ? line.to : line.to - 1;
    // The first character shown from `at` on, or back from it; none before the line's edge.
    const shownFrom = (step: 1 | -1): number | null => {
        let position = at;
        let within = hidden.find((each) => position >= each.from && position < each.to);
        while (within !== undefined) {
            position = step > 0 ? within.to : within.from - 1;
            within = hidden.find((each) => position >= each.from && position < each.to);
        }
        return position < line.from || position > last ? null : position;
    };
    const forward = main.head >= was;
    const rest = shownFrom(forward ? 1 : -1) ?? shownFrom(forward ? -1 : 1);
    if (rest === null) {
        return null;
    }
    if (main.empty) {
        return EditorSelection.single(rest);
    }
    return EditorSelection.single(main.anchor, ahead ? rest + 1 : rest);
}

/** Return where vim's cursor rests in `view` past the hidden marks (`pastHidden`), from `was`, as vim stands; none where it rests already, or in insert, visual line or visual block mode. */
function restingIn(view: EditorView, was: number): EditorSelection | null {
    const mode = getCM(view)?.state.vim as { insertMode?: boolean; visualMode?: boolean; visualLine?: boolean; visualBlock?: boolean } | null | undefined;
    if (mode === null || mode === undefined || mode.insertMode === true || mode.visualLine === true || mode.visualBlock === true) {
        return null;
    }
    return pastHidden(view.state, was, mode.visualMode === true);
}

/**
 * Keep vim's cursor off the marks the Markdown hides: put on one, by a motion, a jump, a click, the text laid out anew
 * or read further, it's moved past it once vim's key is done (`restingIn`), as a selection vim didn't make, so vim
 * takes the cursor from the editor, as it does after a click. Vim's key may dispatch again after the selection, to
 * scroll, so where it rests is read again as it's moved. Not in insert mode, where the cursor's line shows its marks
 * and a thin cursor rests between characters, nor in visual line or block mode, whose selection vim keeps by lines or
 * columns.
 */
const offHidden = EditorView.updateListener.of((update) => {
    const reread = syntaxTree(update.startState) !== syntaxTree(update.state);
    if (!update.selectionSet && !update.docChanged && !reread) {
        return;
    }
    const was = update.startState.selection.main.head;
    if (restingIn(update.view, was) === null) {
        return;
    }
    const { view } = update;
    queueMicrotask(() => {
        const moved = restingIn(view, was);
        if (moved !== null) {
            view.dispatch({ selection: moved });
        }
    });
});

/** Enter in insert mode in a comment breaks the line at its indentation (`brokenLine`), read ahead of the browser's own line break. */
const breaking = Prec.highest(
    EditorView.domEventHandlers({
        keydown: (event, view) => {
            const vim = getCM(view)?.state.vim as { insertMode?: boolean } | null | undefined;
            const modified = event.ctrlKey || event.metaKey || event.altKey || event.shiftKey;
            if (event.key !== "Enter" || modified || event.isComposing || vim?.insertMode !== true || commentAt(view.state, view.state.selection.main.head) === null) {
                return false;
            }
            view.dispatch({ ...brokenLine(view.state), scrollIntoView: true, userEvent: "input" });
            event.preventDefault();
            return true;
        },
    }),
);

/**
 * Vim's indenting, `>>` and `<<`, `>` and `<` with a motion or a selection, and Ctrl+T and Ctrl+D in insert mode, moving
 * lines by the list's indentation (`shifted`): vim does each through its editor's `indentMore` and `indentLess`, which
 * CodeMirror's own commands would move by a fixed unit.
 */
const shifting = ViewPlugin.fromClass(
    class {
        constructor(view: EditorView) {
            const cm = getCM(view) as { indentMore?: () => void; indentLess?: () => void } | null;
            if (cm === null) {
                return;
            }
            const shift = (inward: boolean) => {
                const spec = shifted(view.state, inward);
                if (spec !== null) {
                    view.dispatch(spec);
                }
            };
            cm.indentMore = () => {
                shift(true);
            };
            cm.indentLess = () => {
                shift(false);
            };
        }
    },
);

/**
 * Tab and Shift+Tab in insert mode, as vim's keymap writes them, and the keys of vim's they are: Ctrl+T and Ctrl+D, which
 * move the line in and out by the list's indentation. A browser tab keeps Ctrl+T to open a tab, never giving it to the
 * page; outside insert mode Tab stays the browser's, moving the keyboard through the page.
 */
const INDENTING: readonly (readonly [keys: string, as: string])[] = [
    ["<Tab>", "<C-t>"],
    ["<S-Tab>", "<C-d>"],
];

/** Map Tab and Shift+Tab in insert mode to vim's own Ctrl+T and Ctrl+D, once for every editor, as `inoremap <Tab> <C-t>` would. */
export function bindIndenting(): void {
    for (const [keys, as] of INDENTING) {
        Vim.noremap(keys, as, "insert");
    }
}

/** Return the editor's Markdown: its sources, their language and highlighting, what's shown of them, vim's cursor kept off what's hidden, and a comment's lines and lists written as neovim's Markdown writes them. */
export function markdown(): Extension {
    return [sources, language.extension, syntaxHighlighting(classHighlighter), syntaxHighlighting(marked), shown, offHidden, breaking, shifting];
}
