// The outline: the document with its text taken out, beside it, as the second lup's overview was. Each fold of a kind
// that says it's outlined (`FoldKind.outlined`: a party, a concern, a file, a module's items) is a fold here under its
// summary, nested as the document nests them, a fold read as it opens holding what it read; other folds, lines,
// Markdown and comments are left out, what's outlined under them shown under the nearest fold that is. It's drawn by a shell of its own as the document is,
// its look, margin and folds alike, and each moves with the other: the cursor in the document marks the fold it's in
// here, and moving here takes the document there, opening what folds over it.

import type { Block, Blocks, Span } from "../generated/read";
import { foldKind, nodeAt, offsetOf, type Node } from "../document/tree";
import { redrawn } from "./annotations";
import { Given } from "./given";
import type { Shell, Source } from "./shell";

/** Makes the shell drawing the outline, in `parent`, from `source`. */
export type Making = (parent: HTMLElement, source: Source) => Shell;

/** Return the summary a fold-like node says of itself: a fold's, else its first line, as a file's header is. */
function summaryOf(node: Node): Span[] {
    if (node.block?.block === "fold") {
        return node.block.summary;
    }
    return [{ text: node.head[0] ?? "", tone: "plain", ticking: null, gauge: null, refers: null }];
}

/**
 * Return the folds under `node` as the outline shows them: each a fold of its kind under its summary, keyed by the
 * document's key for it, holding the folds under it, open as it is in the document (`open`); a section's folds as
 * its parent's, what a fold read as it opens laid out where it's read.
 */
function outlined(node: Node, open: (node: Node) => boolean, shown: (kind: string) => boolean): Block[] {
    return node.children.flatMap((child): Block[] => {
        if (child.kind === "section") {
            return outlined(child, open, shown);
        }
        const kind = foldKind(child);
        if (kind === null || !shown(kind)) {
            return kind === null ? [] : outlined(child, open, shown);
        }
        return [
            {
                block: "fold",
                id: child.key,
                version: null,
                offers: [],
                reaches: null,
                sighted: null,
                standing: child.block?.standing ?? null,
                kind,
                summary: summaryOf(child),
                open: open(child),
                content: outlined(child, open, shown),
            },
        ];
    });
}

/** The outline of a shell's document, beside it. */
export class Outline {
    readonly shell: Shell;
    readonly #owner: Shell;
    readonly #source: Given;

    /** Outline `owner`'s document in `parent`, by a shell `making` makes. */
    constructor(owner: Shell, parent: HTMLElement, making: Making) {
        this.#owner = owner;
        this.#source = new Given(this.#laidOut());
        this.shell = making(parent, this.#source);
    }

    /** Lay the outline out again as the document stands: after each view answers, and each fold opens or closes. */
    laid(): void {
        this.#source.set(this.#laidOut());
    }

    /** Mark, here, the folds the document shows on screen, a bar beside them, as it scrolls and changes. */
    viewed(): void {
        const { from, to } = this.#owner.view.viewport;
        const shown = new Set<string>();
        const visit = (node: Node): void => {
            if (node.block?.block === "fold") {
                const there = this.#owner.document.node(node.block.id);
                const start = there === null ? -1 : offsetOf(there);
                if (there !== null && start <= to && start + there.size >= from) {
                    shown.add(node.block.id);
                }
            }
            node.children.forEach(visit);
        };
        visit(this.shell.document.root);
        if (shown.size === this.shell.marked.size && [...shown].every((key) => this.shell.marked.has(key))) {
            return;
        }
        this.shell.marked = shown;
        queueMicrotask(() => {
            this.shell.view.dispatch({ effects: redrawn.of(null) });
        });
    }

    /** Mark, here, the outlined fold the document's cursor is in, as the document's cursor moves. */
    followed(): void {
        let fold = this.#owner.foldAt();
        let here = fold === null ? null : this.#node(fold.key);
        while (fold !== null && here === null) {
            fold = fold.parent;
            here = fold === null ? null : this.#node(fold.key);
        }
        if (here !== null && !this.shell.view.hasFocus) {
            this.shell.go(offsetOf(here));
        }
    }

    /** Take the document to the fold the outline's cursor is on, opening what folds over it, as the outline's cursor moves. */
    went(): void {
        const here = nodeAt(this.shell.document.root, this.shell.view.state.selection.main.head);
        const key = here.block?.block === "fold" ? here.block.id : null;
        const there = key === null ? null : this.#owner.document.node(key);
        if (there === null) {
            return;
        }
        const over: string[] = [];
        let at = there.parent;
        while (at !== null) {
            if (foldKind(at) !== null && !this.#owner.isOpen(at)) {
                over.push(at.key);
            }
            at = at.parent;
        }
        if (over.length > 0) {
            this.#owner.fold(over, true);
        }
        this.#owner.go(offsetOf(there));
    }

    #laidOut(): Blocks {
        const kinds = this.#owner.kinds.folds;
        return {
            blocks: outlined(
                this.#owner.document.root,
                (node) => this.#owner.isOpen(node),
                (kind) => kinds.get(kind)?.outlined === true,
            ),
            summary: [],
            offers: [],
        };
    }

    /** Return the outline's fold for the document's node keyed `key`; none where the outline has none. */
    #node(key: string): Node | null {
        const found: Node[] = [];
        const visit = (node: Node): void => {
            if (node.block?.block === "fold" && node.block.id === key) {
                found.push(node);
                return;
            }
            node.children.forEach(visit);
        };
        visit(this.shell.document.root);
        return found[0] ?? null;
    }
}
