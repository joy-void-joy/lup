// The shell: the document views answer, shown in an editor, folded, moved through and acted on by the keymap's
// commands. The core decides what's shown; the shell keeps what the operator does to it (what's open, where the
// cursor is) by each block's key, so a view answering again moves nothing they didn't move.

import { foldEffect, foldedRanges, foldState, unfoldEffect } from "@codemirror/language";
import { Annotation, EditorState, Facet, type ChangeSpec, type Extension, type Range } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import { getCM, vim } from "@replit/codemirror-vim";

import type { Blocks, Looks, Viewing } from "../generated/read";
import { Document, every, foldKind, foldRange, nodeAt, offsetOf, section, viewKey, type Change, type Node } from "../document/tree";
import { Kinds } from "./looks";

/** Where views are read from: the core, through the server, or the harness. */
export interface Source {
    /** Read `viewing`, and again each time what it shows changes, handing each answer to `answered`; return what stops it. */
    watch(viewing: Viewing, answered: (blocks: Blocks) => void): () => void;
}

/** Marks a transaction the shell makes as views answer, rather than one the operator's keys make. */
export const fromCore = Annotation.define<boolean>();

/** The shell's state, as its laws read it: a value of its own, which later events don't change. */
export interface ShellState {
    readonly mode: "normal" | "insert" | "visual";
    /** The line the cursor is on, from 1. */
    readonly line: number;
    /** The key of the block the cursor is in. */
    readonly at: string;
    /** The keys of the folds closed. */
    readonly closed: readonly string[];
    readonly text: string;
}

/** The document's shell, in an editor of its own. */
export class Shell {
    readonly view: EditorView;
    readonly document: Document;
    readonly kinds: Kinds;
    readonly #source: Source;
    /** Whether the operator opened or closed each fold, by its key: what they did, kept as views answer again. */
    readonly #opened = new Map<string, boolean>();
    /** What stops each fold's view from being watched, by the fold's key, while it's open. */
    readonly #watching = new Map<string, () => void>();
    readonly #stop: () => void;

    constructor(parent: Element, root: Viewing, looks: Looks, source: Source, extensions: Extension[] = []) {
        this.kinds = new Kinds(looks);
        this.#source = source;
        this.document = new Document(section("root", root, { blocks: [], summary: [], offers: [] }));
        const shell = this;
        this.view = new EditorView({
            parent,
            state: EditorState.create({
                doc: "",
                extensions: [
                    vim(),
                    EditorState.changeFilter.of((transaction) => transaction.annotation(fromCore) === true),
                    foldState,
                    drawing,
                    shells.of(shell),
                    ...extensions,
                ],
            }),
        });
        this.#stop = source.watch(root, (blocks) => {
            this.answered("root", blocks);
        });
    }

    /** Stop reading every view, and leave the page. */
    destroy(): void {
        this.#stop();
        for (const stop of this.#watching.values()) {
            stop();
        }
        this.view.destroy();
    }

    /** Put what the view of the section keyed `key` answered in its place. */
    answered(key: string, blocks: Blocks): void {
        const changes = this.document.replace(key, blocks);
        this.#apply(changes, key);
    }

    #apply(changes: Change[], key: string): void {
        this.view.dispatch({ changes: changes as ChangeSpec[], annotations: fromCore.of(true) });
        const node = this.document.node(key);
        if (node !== null) {
            this.#settle(node);
        }
    }

    /** Fold or unfold each fold in `node` as the operator left it, else as its view or its kind says; and read what each open fold reads as it opens. */
    #settle(node: Node): void {
        const effects = [];
        const closed = new Map<string, { from: number; to: number }>();
        foldedRanges(this.view.state).between(0, this.view.state.doc.length, (from, to) => {
            closed.set(`${from}:${to}`, { from, to });
        });
        for (const each of every(node)) {
            const start = offsetOf(each);
            const range = foldRange(each, start);
            const open = this.isOpen(each);
            if (open && each.block?.block === "fold" && !Array.isArray(each.block.content) && !this.#watching.has(each.key)) {
                this.#read(each.key, each.block.content);
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
        if (effects.length > 0) {
            this.view.dispatch({ effects, annotations: fromCore.of(true) });
        }
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
        this.#watching.set(key, () => {
            stop();
        });
        stop = this.#source.watch(viewing, (blocks) => {
            const mounted = this.document.node(key)?.children[0];
            if (mounted?.viewing !== undefined && mounted.viewing !== null && viewKey(mounted.viewing) === viewKey(viewing)) {
                this.answered(mounted.key, blocks);
            } else {
                this.#apply(this.document.mount(key, viewing, blocks), key);
            }
        });
    }

    /** Open or close the fold keyed `key`, as the operator does. */
    toggle(key: string, open?: boolean): void {
        const node = this.document.node(key);
        if (node === null || foldKind(node) === null) {
            return;
        }
        this.#opened.set(key, open ?? !this.isOpen(node));
        this.#settle(node);
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
        this.#settle(this.document.root);
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
            text: this.view.state.doc.toString(),
        };
    }
}

/** The shell an editor shows, for the keymap's commands to find it by its editor. */
export const shells = Facet.define<Shell, Shell | null>({ combine: (values) => values[0] ?? null });

/** How deep a node sits: the folds and sections above it, the root's own not counted. */
function depthOf(node: Node): number {
    let depth = 0;
    let at = node.parent;
    while (at !== null && at.parent !== null) {
        if (at.kind === "fold") {
            depth += 1;
        }
        at = at.parent;
    }
    return depth;
}

/** Draws what the text doesn't say: how deep each line sits, a fold's summary in its kind's colour, each span in its tone. */
const drawing = ViewPlugin.fromClass(
    class {
        decorations: DecorationSet;

        constructor(view: EditorView) {
            this.decorations = this.drawn(view);
        }

        update(update: ViewUpdate): void {
            if (update.docChanged || update.viewportChanged) {
                this.decorations = this.drawn(update.view);
            }
        }

        drawn(view: EditorView): DecorationSet {
            const shell = view.state.facet(shells);
            if (shell === null) {
                return Decoration.none;
            }
            const ranges: Range<Decoration>[] = [];
            for (const { from, to } of view.visibleRanges) {
                let position = from;
                while (position <= to) {
                    const line = view.state.doc.lineAt(position);
                    const node = nodeAt(shell.document.root, line.from);
                    const kind = foldKind(node);
                    const start = offsetOf(node);
                    const heading = kind !== null && start === line.from;
                    const classes = ["lup-line", `lup-${node.kind}`];
                    if (heading) {
                        classes.push("lup-summary");
                    }
                    const colour = heading && kind !== null ? shell.kinds.folds.get(kind)?.colour : undefined;
                    ranges.push(
                        Decoration.line({
                            attributes: {
                                class: classes.join(" "),
                                style: `--lup-depth: ${depthOf(node)};${colour === undefined ? "" : ` --lup-fold: var(--lup-${colour});`}`,
                            },
                        }).range(line.from),
                    );
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
            return Decoration.set(ranges, true);
        }
    },
    { decorations: (plugin) => plugin.decorations },
);

/** The editor's look: the shell's palette, each line set in by how deep it sits. */
export const look = EditorView.theme(
    {
        "&": { height: "100%", backgroundColor: "#000", color: "var(--lup-fg)" },
        ".cm-content": { fontFamily: "ui-monospace, monospace" },
        ".lup-line": { paddingLeft: "calc(var(--lup-depth) * 2ch + 1ch)" },
        ".lup-summary": { color: "var(--lup-fold, var(--lup-fg))" },
        ".lup-bold": { fontWeight: "bold" },
        ".lup-dim": { opacity: "0.6" },
    },
    { dark: true },
);
