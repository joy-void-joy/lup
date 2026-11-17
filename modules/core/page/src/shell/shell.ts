// The shell: the document views answer, shown in an editor, folded, moved through and acted on by the keymap's
// commands. The core decides what's shown; the shell keeps what the operator does to it (what's open, where the
// cursor is) by each block's key, so a view answering again moves nothing they didn't move.

import { foldEffect, foldedRanges, foldState, unfoldEffect } from "@codemirror/language";
import { history } from "@codemirror/commands";
import { EditorState, Facet, StateEffect, StateField, Transaction, type ChangeSpec, type Extension, type Range } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, showPanel, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import { getCM, vim } from "@replit/codemirror-vim";

import type { Blocks, Comment, Delivered, Draft, Looks, Viewing } from "../generated/read";
import { depthOf, Document, every, foldKind, foldRange, mountedOf, nodeAt, offsetOf, section, viewKey, type Change, type Node } from "../document/tree";
import { fromCore, redrawn } from "./annotations";
import { Comments } from "./comments";
import { Kinds } from "./looks";

/** Where views are read from and the draft is kept: the core, through the server, or the harness. */
export interface Source {
    /** Read `viewing`, and again each time what it shows changes, handing each answer to `answered`; return what stops it. */
    watch(viewing: Viewing, answered: (blocks: Blocks) => void): () => void;
    /** Keep `comment` in the draft, in place of the one of its id where there's one. */
    write(comment: Comment): void;
    /** Take the comment or mark of id `id` out of the draft. */
    erase(id: string): void;
    /** Send the draft. */
    send(): void;
    /**
     * Hand the draft to `drafted` as it stands, then each time another page or a send changes it, and what each send
     * delivered to `delivered`; return what stops it.
     */
    drafts(drafted: (draft: Draft) => void, delivered: (delivered: Delivered) => void): () => void;
}


/** Sets what the shell says on its status line; none clears it. */
const say = StateEffect.define<string | null>();

/** What the shell last said on its status line: a command that found nothing to act on saying why. */
const said = StateField.define<string | null>({
    create: () => null,
    update(value, transaction) {
        for (const effect of transaction.effects) {
            if (effect.is(say)) {
                return effect.value;
            }
        }
        return value;
    },
    provide: (field) =>
        showPanel.from(field, (text) =>
            text === null
                ? null
                : () => {
                      const dom = document.createElement("div");
                      dom.className = "lup-status";
                      dom.textContent = text;
                      return { dom, top: false };
                  },
        ),
});

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
    /** Whether the operator opened or closed each fold, by its key: what they did, kept as views answer again. */
    readonly #opened = new Map<string, boolean>();
    /** What stops each fold's view from being watched, by the fold's key, while it's open. */
    readonly #watching = new Map<string, () => void>();
    /** The keys of the folds chosen, for an action to act on every one of. */
    #chosen: readonly string[] = [];
    readonly #stop: () => void;

    constructor(parent: Element, root: Viewing, looks: Looks, source: Source, extensions: Extension[] = []) {
        this.kinds = new Kinds(looks);
        this.source = source;
        this.document = new Document(section("root", root, { blocks: [], summary: [], offers: [] }));
        this.comments = new Comments(this);
        const shell = this;
        this.view = new EditorView({
            parent,
            state: EditorState.create({
                doc: "",
                extensions: [
                    vim(),
                    EditorView.lineWrapping,
                    EditorState.changeFilter.of((transaction) => transaction.annotation(fromCore) === true || shell.comments.allows(transaction)),
                    // vim's `u` and Ctrl+R undo and redo what the operator wrote, never what views answered.
                    history(),
                    EditorState.transactionExtender.of((transaction) => (transaction.annotation(fromCore) === true ? { annotations: Transaction.addToHistory.of(false) } : null)),
                    EditorView.updateListener.of((update) => {
                        shell.comments.changed(update);
                    }),
                    foldState,
                    said,
                    drawing,
                    shells.of(shell),
                    ...extensions,
                ],
            }),
        });
        this.comments.start();
        getCM(this.view)?.on("vim-mode-change", (event: { mode: string }) => {
            this.comments.moded(event.mode);
        });
        this.#stop = source.watch(root, (blocks) => {
            this.answered("root", blocks);
        });
    }

    /** Stop reading every view, and leave the page. */
    destroy(): void {
        this.comments.destroy();
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
            if (open && each.block?.block === "fold" && !Array.isArray(each.block.content) && !this.#watching.has(each.key)) {
                this.#read(each.key, { ...each.block.content, module: each.block.content.module ?? moduleOf(each) });
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
        stop = this.source.watch(viewing, (blocks) => {
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

/** Return the module whose view laid `node` out: the module of the nearest section above it that names one. */
function moduleOf(node: Node): string | null {
    let at: Node | null = node;
    while (at !== null) {
        if (at.viewing !== null && at.viewing.module !== null) {
            return at.viewing.module;
        }
        at = at.parent;
    }
    return null;
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
        ".lup-letter.lup-drafted": { textDecoration: "underline 2px var(--lup-warn)", textUnderlineOffset: "2px" },
        ".lup-line.lup-chosen": { background: "var(--lup-selection)" },
        ".lup-line.lup-comment": {
            color: "var(--lup-warn)",
            background: "var(--lup-float)",
            boxShadow: "inset 2px 0 0 var(--lup-warn)",
        },
        ".lup-comment-first::before": { content: '"¶ "', color: "var(--lup-muted)" },
        ".lup-quoted": { textDecoration: "underline 2px var(--lup-warn)", textUnderlineOffset: "3px" },
        ".lup-comment-first::after": { content: '"  " attr(data-to)', color: "var(--lup-muted)", fontStyle: "italic" },
        ".lup-comment-first[data-said]::after": {
            content: '"  " attr(data-to) "  ◂ " attr(data-said)',
            color: "var(--lup-err)",
            fontStyle: "italic",
        },
        ".lup-status": { padding: "0 1ch", borderTop: "1px solid var(--lup-border)", color: "var(--lup-fg)" },
        ".cm-panels": { background: "var(--lup-float)", color: "var(--lup-fg)" },
        ".cm-panels-bottom": { borderTop: "0" },
        ".lup-placeholder": { border: "1px solid currentColor", padding: "0 0.5ch", marginLeft: "1ch", cursor: "pointer" },
    },
    { dark: true },
);
