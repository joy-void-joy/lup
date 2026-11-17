// The document: what views answer, laid out as one text the editor holds, and
// kept as a tree whose every node knows where it starts relative to its parent.
//
// A view's answer is a section; each of its blocks a node, a fold's content its
// children, a fold read as it opens the section mounted there once it's read. A
// node's text is its own lines (a line's, a fold's summary, a file's header and
// lines), then each child's, one per line, never indented: nesting is drawn, not
// written, so what's quoted of a line is what it says. Where a node starts is
// summed from its parent's start and its earlier siblings', each parent keeping
// those sums until one of its children changes, so a change in one section never
// lays out another, and finding a node's place costs the depth of the tree.

import type { Block, Blocks, Viewing } from "../generated/read";

/** What a node is: a view's answer, or one of its blocks. */
export type Kind = "section" | Block["block"];

/** One node of the document: a section, or a block of one. */
export interface Node {
    /** Unique in the document, and kept from one answer to the next: its section's key, then its block's id. */
    readonly key: string;
    readonly kind: Kind;
    /** The block it lays out; none for a section. */
    readonly block: Block | null;
    /** For a section, the view it's the answer of. */
    readonly viewing: Viewing | null;
    /** Its own lines, before its children's. */
    readonly head: readonly string[];
    children: Node[];
    parent: Node | null;
    /** How many characters its text holds, its lines joined by newlines. */
    size: number;
    /** How many lines its text holds: none for a section with nothing in it. */
    lines: number;
    /** Where each child starts, from where this node starts; none until asked again after a change. */
    starts: number[] | null;
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

/** Say a block's own lines: what it shows before what's under it. */
export function headOf(block: Block): string[] {
    switch (block.block) {
        case "line":
            return [block.spans.map((span) => span.text).join("")];
        case "markdown":
            return block.text.split("\n");
        case "fold":
            return [block.summary.map((span) => span.text).join("")];
        case "code":
            return [
                [block.path, counted(block.text === "" ? 0 : block.text.split("\n").length, "line"), ...block.says].join(" · "),
                ...linesOf(block.text),
            ];
        case "diff":
            return [[block.path, ...block.says].join(" · "), ...rowsOf(block).map((row) => row.text)];
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
    const lines = text.split("\n");
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
    return { key, kind, block, viewing, head, children: [], parent: null, size: 0, lines: 0, starts: null };
}

/** Work out a node's size and line count from its own lines and its children's, which are already sized. */
function sized(node: Node): Node {
    let size = node.head.length > 0 ? node.head.join("\n").length : 0;
    let lines = node.head.length;
    for (const child of node.children) {
        child.parent = node;
        if (child.lines === 0) {
            continue;
        }
        size += (lines > 0 ? 1 : 0) + child.size;
        lines += child.lines;
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
    const starts: number[] = [];
    let at = node.head.length > 0 ? node.head.join("\n").length : 0;
    let any = node.head.length > 0;
    for (const child of node.children) {
        starts.push(any && child.lines > 0 ? at + 1 : at);
        if (child.lines > 0) {
            at += (any ? 1 : 0) + child.size;
            any = true;
        }
    }
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

/** Return the text of `node`: its own lines, then each child's. */
export function textOf(node: Node): string {
    const lines = [...node.head];
    for (const child of node.children) {
        if (child.lines > 0) {
            lines.push(textOf(child));
        }
    }
    return lines.join("\n");
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

/** Return where `node`'s content is hidden as it folds, from `start`, where it starts; none where it doesn't fold, or holds nothing under its first line. */
export function foldRange(node: Node, start: number): FoldRange | null {
    const kind = foldKind(node);
    const first = node.head[0];
    if (kind === null || first === undefined || node.lines < 2) {
        return null;
    }
    return { key: node.key, kind, from: start + first.length, to: start + node.size };
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
     * Where its blocks are the same blocks, by id and in order, only those whose text changed are changed, so what's
     * around them keeps its place; a fold read as it opens keeps the section mounted under it while it reads the same
     * view. Otherwise the section's whole text is replaced. Nothing outside the section is laid out again.
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
        const start = offsetOf(old);
        const same =
            old.children.length === fresh.children.length &&
            old.children.every((child, at) => {
                const other = fresh.children[at];
                return other !== undefined && other.key === child.key && (other.lines > 0) === (child.lines > 0);
            });
        const changes: Change[] = [];
        if (same) {
            const starts = startsOf(old);
            old.children.forEach((child, at) => {
                const other = fresh.children[at];
                if (other === undefined) {
                    return;
                }
                const before = textOf(child);
                const after = textOf(other);
                if (before !== after) {
                    const from = start + (starts[at] ?? 0);
                    changes.push({ from, to: from + child.size, insert: after });
                }
            });
        } else {
            changes.push({ from: start, to: start + old.size, insert: textOf(fresh) });
        }
        for (const child of old.children) {
            this.#forget(child);
        }
        old.children = fresh.children;
        for (const child of old.children) {
            this.#remember(child);
        }
        this.#resize(old);
        return changes;
    }

    /**
     * Mount `answer`, what the view a fold reads answers, under the fold keyed `fold`, and return the changes to the text.
     */
    mount(fold: string, viewing: Viewing, answer: Blocks): Change[] {
        const node = this.#byKey.get(fold);
        if (node === undefined) {
            throw new Error(`the document holds no fold \`${fold}\``);
        }
        const head = node.head.join("\n").length;
        const from = offsetOf(node) + head;
        const to = from + node.size - head;
        const mounted = section(`${fold}>${viewKey(viewing)}`, viewing, answer);
        for (const child of node.children) {
            this.#forget(child);
        }
        node.children = [mounted];
        this.#remember(mounted);
        this.#resize(node);
        return [{ from, to, insert: textOf(node).slice(head) }];
    }

    /** Take, for a fold read as it opens, the section the old document mounted under it, where it reads the same view. */
    #carry(node: Node): void {
        const old = this.#byKey.get(node.key);
        const content = node.block?.block === "fold" ? node.block.content : null;
        const mounted = old?.children[0];
        if (
            content !== null &&
            !Array.isArray(content) &&
            mounted?.viewing !== undefined &&
            mounted.viewing !== null &&
            viewKey(mounted.viewing) === viewKey(content)
        ) {
            node.children = [mounted];
        } else {
            for (const child of node.children) {
                this.#carry(child);
            }
        }
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
