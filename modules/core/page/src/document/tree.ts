// The document: what views answer, laid out as one text the editor holds, and
// kept as a tree whose every node knows where it starts relative to its parent.
//
// A view's answer is a section; each of its blocks a node, a fold's content its
// children, a fold read as it opens the section mounted there once it's read. A
// node's text is its own lines (a line's, a fold's summary, a file's header and
// lines), each followed by the comments written under it, then each child's, one
// per line, never indented: nesting is drawn, not written, so what's quoted of a
// line is what it says. Where a node starts is summed from its parent's start and
// its earlier siblings', each parent keeping those sums until one of its children
// changes, so a change in one section never lays out another, and finding a
// node's place costs the depth of the tree.
//
// A view answered again is reconciled into the text as the fewest edits: what
// keeps its key keeps its text, a node's own lines matched by what they say, so
// a comment being written, the cursor in it, and the folds around a change keep
// their place.

import type { Block, Blocks, Viewing } from "../generated/read";

/** What a node is: a view's answer, one of its blocks, or a comment the operator wrote under one of a block's lines. */
export type Kind = "section" | Block["block"] | "comment";

/** One node of the document: a section, or a block of one. */
export interface Node {
    /** Unique in the document, and kept from one answer to the next: its section's key, then its block's id. */
    readonly key: string;
    readonly kind: Kind;
    /** The block it lays out; none for a section. */
    readonly block: Block | null;
    /** For a section, the view it's the answer of. */
    readonly viewing: Viewing | null;
    /** Its own lines, before its children's: a comment's, what it says, as the operator writes it. */
    head: readonly string[];
    children: Node[];
    parent: Node | null;
    /** How many characters its text holds, its lines joined by newlines. */
    size: number;
    /** How many lines its text holds: none for a section with nothing in it. */
    lines: number;
    /** Where each child starts, from where this node starts; none until asked again after a change. */
    starts: number[] | null;
    /** For a comment, which of its parent's own lines it's written under, from 0; none for anything else. */
    after: number | null;
}

/** Where a fold's content is hidden: from the end of its first line to its end. */
export interface FoldRange {
    readonly key: string;
    readonly kind: string;
    readonly from: number;
    readonly to: number;
}

/** A change to the document's text, as the editor takes it. */
export interface Change {
    readonly from: number;
    readonly to: number;
    readonly insert: string;
}

/**
 * Return `text`'s lines, broken where the editor breaks them, at `\r\n`, `\r` and `\n` alike, which it keeps as one
 * line break each: split anywhere else, the tree would count a character the editor's text doesn't hold.
 */
export function broken(text: string): string[] {
    return text.split(/\r\n?|\n/);
}

/** Return `text` as one line of the editor, each line break in it a space, so it keeps its length and its spans their places. */
function oneLine(text: string): string {
    return text.replace(/[\r\n]/g, " ");
}

/** Say a block's own lines: what it shows before what's under it. */
export function headOf(block: Block): string[] {
    switch (block.block) {
        case "line":
            return [oneLine(block.spans.map((span) => span.text).join(""))];
        case "markdown":
            return broken(block.text);
        case "fold":
            return [oneLine(block.summary.map((span) => span.text).join(""))];
        case "code":
            return [oneLine([block.path, counted(linesOf(block.text).length, "line"), ...block.says].join(" · ")), ...linesOf(block.text)];
        case "diff":
            return [oneLine([block.path, ...block.says].join(" · ")), ...rowsOf(block).map((row) => row.text)];
    }
}

/** Say how many of a thing there are: `1 line`, `5 lines`. */
export function counted(count: number, one: string): string {
    return `${count} ${one}${count === 1 ? "" : "s"}`;
}

function linesOf(text: string): string[] {
    if (text === "") {
        return [];
    }
    const lines = broken(text);
    return lines.at(-1) === "" ? lines.slice(0, -1) : lines;
}

/** One line of a file's change: how the change takes it, and its text. */
export interface Row {
    readonly change: "added" | "removed" | "same";
    readonly text: string;
}

/** Say a change's lines as the page shows them: what the file becomes, each line it removes in place before those replacing it. */
export function rowsOf(diff: Extract<Block, { block: "diff" }>): Row[] {
    const before = diff.before?.kind === "text" ? linesOf(diff.before.text) : [];
    const after = diff.after?.kind === "text" ? linesOf(diff.after.text) : [];
    const common = longestCommon(before, after);
    const rows: Row[] = [];
    let i = 0;
    let j = 0;
    for (const [a, b] of common) {
        while (i < a) rows.push({ change: "removed", text: before[i++] ?? "" });
        while (j < b) rows.push({ change: "added", text: after[j++] ?? "" });
        rows.push({ change: "same", text: after[j] ?? "" });
        i += 1;
        j += 1;
    }
    while (i < before.length) rows.push({ change: "removed", text: before[i++] ?? "" });
    while (j < after.length) rows.push({ change: "added", text: after[j++] ?? "" });
    return rows;
}

/** The pairs of lines two texts share, in order, as the longest common subsequence finds them. */
function longestCommon(before: string[], after: string[]): [number, number][] {
    const width = after.length + 1;
    const lengths = new Uint32Array((before.length + 1) * width);
    for (let i = before.length - 1; i >= 0; i--) {
        for (let j = after.length - 1; j >= 0; j--) {
            lengths[i * width + j] =
                before[i] === after[j]
                    ? (lengths[(i + 1) * width + j + 1] ?? 0) + 1
                    : Math.max(lengths[(i + 1) * width + j] ?? 0, lengths[i * width + j + 1] ?? 0);
        }
    }
    const pairs: [number, number][] = [];
    let i = 0;
    let j = 0;
    while (i < before.length && j < after.length) {
        if (before[i] === after[j]) {
            pairs.push([i, j]);
            i += 1;
            j += 1;
        } else if ((lengths[(i + 1) * width + j] ?? 0) >= (lengths[i * width + j + 1] ?? 0)) {
            i += 1;
        } else {
            j += 1;
        }
    }
    return pairs;
}

/** Return a view's answer as a section, keyed under `key`, its blocks its children. */
export function section(key: string, viewing: Viewing | null, blocks: Blocks): Node {
    const node = made(key, "section", null, viewing, []);
    node.children = blocks.blocks.map((block) => blockNode(`${key}/${block.id}`, block, node));
    return sized(node);
}

function blockNode(key: string, block: Block, parent: Node): Node {
    const node = made(key, block.block, block, null, headOf(block));
    node.parent = parent;
    if (block.block === "fold" && Array.isArray(block.content)) {
        node.children = block.content.map((child) => blockNode(`${key}/${child.id}`, child, node));
    }
    return sized(node);
}

function made(key: string, kind: Kind, block: Block | null, viewing: Viewing | null, head: string[]): Node {
    return { key, kind, block, viewing, head, children: [], parent: null, size: 0, lines: 0, starts: null, after: null };
}

/** Return a comment, keyed `key`, saying `text`, to be written under the line `after` of a block's own lines. */
export function comment(key: string, text: string, after: number): Node {
    const node = made(key, "comment", null, null, broken(text));
    node.after = after;
    return sized(node);
}

/** One part of a node's text, in the order it's shown: one of its own lines, or a child's text. */
type Unit = { readonly line: string } | { readonly child: Node };

/** Return the parts of `node`'s text, in order: each of its own lines followed by the comments written under it, then its other children. */
function unitsOf(node: Node): Unit[] {
    const last = node.head.length - 1;
    const under = new Map<number, Node[]>();
    for (const child of node.children) {
        if (child.after !== null) {
            const at = Math.min(child.after, last);
            under.set(at, [...(under.get(at) ?? []), child]);
        }
    }
    const units: Unit[] = [];
    node.head.forEach((line, at) => {
        units.push({ line });
        for (const child of under.get(at) ?? []) {
            units.push({ child });
        }
    });
    for (const child of node.children) {
        if (child.after === null) {
            units.push({ child });
        }
    }
    return units;
}

/** Say how many lines a part of a node's text holds. */
function linesIn(unit: Unit): number {
    return "line" in unit ? 1 : unit.child.lines;
}

/** Say how many characters a part of a node's text holds. */
function sizeOf(unit: Unit): number {
    return "line" in unit ? unit.line.length : unit.child.size;
}

/** Put `node`'s comments first, in the order of the lines they're under, as its text shows its children. */
function ordered(node: Node): void {
    const rank = (child: Node): number => child.after ?? Number.POSITIVE_INFINITY;
    if (node.children.every((child, at) => at === 0 || rank(node.children[at - 1] ?? child) <= rank(child))) {
        return;
    }
    node.children = [...node.children].sort((one, other) => rank(one) - rank(other));
}

/** Work out a node's size and line count from its own lines and its children's, which are already sized. */
function sized(node: Node): Node {
    ordered(node);
    let size = 0;
    let lines = 0;
    for (const child of node.children) {
        child.parent = node;
    }
    for (const unit of unitsOf(node)) {
        const count = linesIn(unit);
        if (count === 0) {
            continue;
        }
        size += (lines > 0 ? 1 : 0) + sizeOf(unit);
        lines += count;
    }
    node.size = size;
    node.lines = lines;
    node.starts = null;
    return node;
}

/** Return where each of a node's children starts, from where the node starts. */
function startsOf(node: Node): number[] {
    if (node.starts !== null) {
        return node.starts;
    }
    const at = new Map<Node, number>();
    let offset = 0;
    let any = false;
    for (const unit of unitsOf(node)) {
        const count = linesIn(unit);
        const start = any && count > 0 ? offset + 1 : offset;
        if ("child" in unit) {
            at.set(unit.child, start);
        }
        if (count > 0) {
            offset = start + sizeOf(unit);
            any = true;
        }
    }
    const starts = node.children.map((child) => at.get(child) ?? offset);
    node.starts = starts;
    return starts;
}

/** Return where `node` starts in the document. */
export function offsetOf(node: Node): number {
    let at = 0;
    let child = node;
    let parent = node.parent;
    while (parent !== null) {
        at += startsOf(parent)[parent.children.indexOf(child)] ?? 0;
        child = parent;
        parent = parent.parent;
    }
    return at;
}

/** Return the text of a part of a node's text. */
function textIn(unit: Unit): string {
    return "line" in unit ? unit.line : textOf(unit.child);
}

/** Return the text of `node`: its own lines, each followed by the comments under it, then each child's. */
export function textOf(node: Node): string {
    return unitsOf(node)
        .filter((unit) => linesIn(unit) > 0)
        .map(textIn)
        .join("\n");
}

/** Where one of a node's own lines is in the document: from its start to its end, a newline not counted. */
export interface Placed {
    readonly from: number;
    readonly to: number;
}

/** Return where each of `node`'s own lines is in the document, in order, the comments under them skipped. */
export function ownLines(node: Node): Placed[] {
    const placed: Placed[] = [];
    let offset = offsetOf(node);
    let any = false;
    for (const unit of unitsOf(node)) {
        const count = linesIn(unit);
        const start = any && count > 0 ? offset + 1 : offset;
        if ("line" in unit) {
            placed.push({ from: start, to: start + unit.line.length });
        }
        if (count > 0) {
            offset = start + sizeOf(unit);
            any = true;
        }
    }
    return placed;
}

/** Return the innermost node holding `position`, from `root` down. */
export function nodeAt(root: Node, position: number): Node {
    let node = root;
    let at = 0;
    for (;;) {
        const starts = startsOf(node);
        let found = -1;
        for (let i = node.children.length - 1; i >= 0; i--) {
            const child = node.children[i];
            const start = starts[i];
            if (child !== undefined && start !== undefined && child.lines > 0 && at + start <= position) {
                if (position <= at + start + child.size) {
                    found = i;
                }
                break;
            }
        }
        const next = node.children[found];
        if (next === undefined) {
            return node;
        }
        at += starts[found] ?? 0;
        node = next;
    }
}

/** Return every node of `root`'s tree, in the order they're shown. */
export function every(root: Node): Node[] {
    return [root, ...root.children.flatMap(every)];
}

/** Return the section a fold read as it opens has mounted under it; none where it hasn't been read. */
export function mountedOf(node: Node): Node | null {
    return node.children.find((child) => child.kind === "section") ?? null;
}

/**
 * Return the view the fold `node` reads as it opens, its module named: where the fold names none, the module of the
 * nearest section above it that does, whose view laid the fold out; none where it reads no view.
 */
export function opening(node: Node): Viewing | null {
    const content = node.block?.block === "fold" ? node.block.content : null;
    if (content === null || Array.isArray(content)) {
        return null;
    }
    let module = content.module;
    let at: Node | null = node;
    while (module === null && at !== null) {
        module = at.viewing?.module ?? null;
        at = at.parent;
    }
    return { ...content, module };
}

/** Return the fold kind a node folds as, where it folds: a fold's own, a file's `file`; none for a node that doesn't. */
export function foldKind(node: Node): string | null {
    switch (node.block?.block) {
        case "fold":
            return node.block.kind;
        case "code":
        case "diff":
            return "file";
        default:
            return null;
    }
}

/** Return how deep `node` sits: how many folds hold it, the root's own section not counted. */
export function depthOf(node: Node): number {
    let depth = 0;
    let at = node.parent;
    while (at !== null && at.parent !== null) {
        if (foldKind(at) !== null) {
            depth += 1;
        }
        at = at.parent;
    }
    return depth;
}

/** Return where `node`'s content is hidden as it folds, from `start`, where it starts; none where it doesn't fold, or holds nothing under its first line. */
export function foldRange(node: Node, start: number): FoldRange | null {
    const kind = foldKind(node);
    const first = node.head[0];
    if (kind === null || first === undefined || node.lines < 2) {
        return null;
    }
    return { key: node.key, kind, from: start + first.length, to: start + node.size };
}

/** What a part of a node's text is matched by between two layouts of it: a child's key, or what one of its own lines says. */
function identity(unit: Unit): string {
    return "line" in unit ? `line ${unit.line}` : `node ${unit.child.key}`;
}

/**
 * Return the pairs of indexes of `before` and `after` that match, in order: the longest run they share at their start
 * and their end, and between them the longest common subsequence, where it's small enough to work out; where it isn't,
 * nothing between them matches, and what's there is laid out again whole.
 */
function matched(before: readonly string[], after: readonly string[], limit = 4_000_000): [number, number][] {
    let head = 0;
    while (head < before.length && head < after.length && before[head] === after[head]) {
        head += 1;
    }
    let tail = 0;
    while (tail < before.length - head && tail < after.length - head && before[before.length - 1 - tail] === after[after.length - 1 - tail]) {
        tail += 1;
    }
    const pairs: [number, number][] = [];
    for (let i = 0; i < head; i++) {
        pairs.push([i, i]);
    }
    const middleBefore = before.slice(head, before.length - tail);
    const middleAfter = after.slice(head, after.length - tail);
    if (middleBefore.length > 0 && middleAfter.length > 0 && middleBefore.length * middleAfter.length <= limit) {
        for (const [i, j] of longestCommon(middleBefore, middleAfter)) {
            pairs.push([head + i, head + j]);
        }
    }
    for (let i = 0; i < tail; i++) {
        pairs.push([before.length - tail + i, after.length - tail + i]);
    }
    return pairs;
}

/**
 * Return the pairs of indexes of `before` and `after`, two layouts' parts by their identities, that match, in order:
 * first every node both hold in the same order, a comment among them, then, between each two, the lines both hold,
 * so a comment is never given up for two lines that happen to say the same.
 */
function aligned(before: readonly string[], after: readonly string[]): [number, number][] {
    const nodes = (ids: readonly string[]): number[] => ids.flatMap((id, at) => (id.startsWith("node ") ? [at] : []));
    const inBefore = nodes(before);
    const inAfter = nodes(after);
    const anchors = matched(
        inBefore.map((at) => before[at] ?? ""),
        inAfter.map((at) => after[at] ?? ""),
    ).map(([one, other]): [number, number] => [inBefore[one] ?? 0, inAfter[other] ?? 0]);
    const pairs: [number, number][] = [];
    let from: [number, number] = [0, 0];
    for (const anchor of [...anchors, [before.length, after.length] as [number, number]]) {
        for (const [one, other] of matched(before.slice(from[0], anchor[0]), after.slice(from[1], anchor[1]))) {
            pairs.push([from[0] + one, from[1] + other]);
        }
        if (anchor[0] < before.length) {
            pairs.push(anchor);
        }
        from = [anchor[0] + 1, anchor[1] + 1];
    }
    return pairs;
}

/**
 * Return the changes that make the text of `old`, starting at `start`, the text of `fresh`: what both hold under the
 * same key, or the same own line, keeps its place, each child held by both reconciled the same way, so only what
 * changed is written again.
 */
export function reconciled(old: Node, fresh: Node, start: number): Change[] {
    if (old === fresh) {
        return [];
    }
    const before = unitsOf(old).filter((unit) => linesIn(unit) > 0);
    const after = unitsOf(fresh).filter((unit) => linesIn(unit) > 0);
    // Each part followed by a newline, so a run of parts is replaced by another as one change; the newline after the
    // last is the text's end, put right below.
    const starts: number[] = [];
    let offset = 0;
    for (const unit of before) {
        starts.push(offset);
        offset += sizeOf(unit) + 1;
    }
    starts.push(offset);
    const pairs = aligned(before.map(identity), after.map(identity));
    const changes: Change[] = [];
    let i = 0;
    let j = 0;
    const flush = (untilBefore: number, untilAfter: number): void => {
        if (i === untilBefore && j === untilAfter) {
            return;
        }
        const insert = after
            .slice(j, untilAfter)
            .map((unit) => `${textIn(unit)}\n`)
            .join("");
        const change = ended(starts[i] ?? 0, starts[untilBefore] ?? 0, insert, offset);
        changes.push({ from: start + change.from, to: start + change.to, insert: change.insert });
        i = untilBefore;
        j = untilAfter;
    };
    for (const [one, other] of pairs) {
        flush(one, other);
        const was = before[one];
        const now = after[other];
        if (was !== undefined && now !== undefined && "child" in was && "child" in now) {
            changes.push(...reconciled(was.child, now.child, start + (starts[one] ?? 0)));
        }
        i = one + 1;
        j = other + 1;
    }
    flush(before.length, after.length);
    return changes;
}

/**
 * Return a change made to a text with a newline after each part, `length` long with it, as a change to the text itself,
 * which has none after its last part.
 */
function ended(from: number, to: number, insert: string, length: number): Change {
    if (to < length) {
        return { from, to, insert };
    }
    if (length === 0) {
        return { from: 0, to: 0, insert: insert.slice(0, -1) };
    }
    if (from === to) {
        return { from: from - 1, to: to - 1, insert: `\n${insert.slice(0, -1)}` };
    }
    if (insert === "") {
        return from === 0 ? { from: 0, to: to - 1, insert: "" } : { from: from - 1, to: to - 1, insert: "" };
    }
    return { from, to: to - 1, insert: insert.slice(0, -1) };
}

/**
 * Return the line of `after` the line `at` of `before` became, where a block's own lines changed: the same line where
 * it's kept, else the nearest kept line before it, so a comment written under it stays near what it was on.
 */
function moved(before: readonly string[], after: readonly string[], at: number): number {
    if (before.length === after.length && before.every((line, index) => line === after[index])) {
        return at;
    }
    let found = 0;
    for (const [one, other] of matched(before, after)) {
        if (one > at) {
            break;
        }
        found = other;
    }
    return Math.min(found, Math.max(after.length - 1, 0));
}

/** The document's tree, and every node by its key. */
export class Document {
    readonly root: Node;
    readonly #byKey = new Map<string, Node>();

    constructor(root: Node) {
        this.root = root;
        for (const node of every(root)) {
            this.#byKey.set(node.key, node);
        }
    }

    /** Return the node of `key`; none where the document holds none. */
    node(key: string): Node | null {
        return this.#byKey.get(key) ?? null;
    }

    /** Return the document's text. */
    text(): string {
        return textOf(this.root);
    }

    /**
     * Put `answer` in place of the section keyed `key`, and return the changes to the text that make the old text the new.
     *
     * The new text is reconciled with the old (`reconciled`): what keeps its key keeps its text, so what's around a
     * change keeps its place. A fold read as it opens keeps the section mounted under it while it reads the same view,
     * and a block keeps the comments written under its lines, each under the line it was under where that line is
     * kept. Nothing outside the section is laid out again.
     */
    replace(key: string, answer: Blocks): Change[] {
        const old = this.#byKey.get(key);
        if (old === undefined || old.kind !== "section") {
            throw new Error(`the document holds no section \`${key}\``);
        }
        const fresh = section(key, old.viewing, answer);
        for (const child of fresh.children) {
            this.#carry(child);
        }
        sized(fresh);
        return this.#adopt(old, fresh.children);
    }

    /**
     * Mount `answer`, what the view a fold reads answers, under the fold keyed `fold`, and return the changes to the text.
     */
    mount(fold: string, viewing: Viewing, answer: Blocks): Change[] {
        const node = this.#byKey.get(fold);
        if (node === undefined) {
            throw new Error(`the document holds no fold \`${fold}\``);
        }
        const mounted = section(`${fold}>${viewKey(viewing)}`, viewing, answer);
        return this.#adopt(node, [...node.children.filter((child) => child.kind === "comment"), mounted]);
    }

    /**
     * Write `written`, a comment, under the line `written.after` of the block keyed `block`'s own lines, after the
     * comments already under it, and return the change to the text.
     */
    remark(block: string, written: Node): Change[] {
        const node = this.#byKey.get(block);
        if (node === undefined || node.head.length === 0) {
            throw new Error(`the document holds no block \`${block}\` with lines to comment under`);
        }
        written.after = Math.min(written.after ?? 0, node.head.length - 1);
        return this.#adopt(node, [...node.children, written]);
    }

    /** Take the comment keyed `key` out of the document, and return the change to the text. */
    unremark(key: string): Change[] {
        const node = this.#byKey.get(key);
        const parent = node?.parent ?? null;
        if (node === undefined || node.kind !== "comment" || parent === null) {
            return [];
        }
        return this.#adopt(
            parent,
            parent.children.filter((child) => child !== node),
        );
    }

    /**
     * Say what the comment keyed `key` says, as the operator wrote it in the editor, whose text already says it: the
     * tree follows the text, and nothing changes in it.
     */
    rewrite(key: string, text: string): void {
        const node = this.#byKey.get(key);
        if (node === undefined || node.kind !== "comment") {
            throw new Error(`the document holds no comment \`${key}\``);
        }
        node.head = broken(text);
        this.#resize(node);
    }

    /** Give `node` the children `children`, and return the changes to the text that lay them out in place of its own. */
    #adopt(node: Node, children: Node[]): Change[] {
        const fresh = made(node.key, node.kind, node.block, node.viewing, [...node.head]);
        fresh.after = node.after;
        fresh.children = children;
        sized(fresh);
        const changes = reconciled(node, fresh, offsetOf(node));
        for (const child of node.children) {
            if (!children.includes(child)) {
                this.#forget(child);
            }
        }
        node.children = fresh.children;
        for (const child of node.children) {
            this.#remember(child);
        }
        this.#resize(node);
        return changes;
    }

    /**
     * Take into `node`, a block of a view answered again, what the old document holds under its key that the view
     * doesn't answer: the section mounted under it, where it reads the same view, and the comments written under its
     * lines, each moved with the line it's under.
     */
    #carry(node: Node): void {
        const old = this.#byKey.get(node.key);
        // Copies, each under the line it moved to: the old document's own are still laid out where they were, for the
        // changes to be worked out from.
        const comments = (old?.children ?? [])
            .filter((child) => child.kind === "comment")
            .map((each) => comment(each.key, each.head.join("\n"), moved(old?.head ?? [], node.head, each.after ?? 0)));
        const reads = opening(node);
        const mounted = old === undefined ? null : mountedOf(old);
        if (reads !== null && mounted?.viewing !== undefined && mounted.viewing !== null && viewKey(mounted.viewing) === viewKey(reads)) {
            node.children = [mounted];
        } else {
            for (const child of node.children) {
                this.#carry(child);
            }
        }
        node.children = [...comments, ...node.children];
        sized(node);
    }

    #forget(node: Node): void {
        for (const each of every(node)) {
            this.#byKey.delete(each.key);
        }
    }

    #remember(node: Node): void {
        for (const each of every(node)) {
            this.#byKey.set(each.key, each);
        }
    }

    /** Size `node` again, and every node above it, each forgetting where its children start. */
    #resize(node: Node): void {
        let at: Node | null = node;
        while (at !== null) {
            sized(at);
            at = at.parent;
        }
    }
}

/** Say a view and what it's given as one key. */
export function viewKey(viewing: Viewing): string {
    return JSON.stringify([viewing.module, viewing.view, viewing.given]);
}
