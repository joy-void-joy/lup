// Views read from memory, for the page's promises: what each answers is set by the promise, and pushed to whoever
// watches it, as the core pushes a view answered again; and the draft, kept as the core keeps it, a send taking out
// every comment that says something and isn't held back, and dropping those that say nothing. The document's root, where
// one is named, answers with the review at its top as the server's does (`lup.environment.shell.review`), each part a
// line of its id, without the server's grouping by where each goes.

import type { Block, Blocks, Comment, Delivered, Draft, Looks, Viewing } from "../generated/read";
import { viewKey } from "../document/tree";
import declared from "../generated/core-looks.json";
import type { Source } from "../shell/shell";

/** Views answered from memory: each view's latest answer, pushed to every watch of it as it's set. */
export class Memory implements Source {
    readonly #answers = new Map<string, Blocks>();
    readonly #watches = new Map<string, Set<(blocks: Blocks) => void>>();
    readonly #drafted = new Set<(draft: Draft) => void>();
    readonly #delivered = new Set<(delivered: Delivered) => void>();
    /** The draft, as the core keeps it. */
    draft: Draft = { comments: [], marks: [] };

    /** Keep views answered by the promise, the document's root, where one is named, answering with the review at its top. */
    constructor(readonly root: Viewing | null = null) {}

    /** Set what `viewing` answers, and push it to every watch of it. */
    set(viewing: Viewing, blocks: Blocks): void {
        const key = viewKey(viewing);
        this.#answers.set(key, blocks);
        for (const answered of this.#watches.get(key) ?? []) {
            answered(this.#topped(key, blocks));
        }
    }

    /** Return what the view keyed `key` answers as a watch is told it: the root with the review at its top. */
    #topped(key: string, blocks: Blocks): Blocks {
        if (this.root === null || key !== viewKey(this.root) || this.draft.comments.length === 0) {
            return blocks;
        }
        const parts: Block[] = this.draft.comments.map((comment) => ({
            block: "line",
            id: comment.id,
            version: null,
            offers: [],
            reaches: null,
            sighted: null,
            spans: [{ text: comment.words.split("\n")[0] ?? "", tone: "strong", ticking: null, gauge: null, refers: null }],
        }));
        const review: Block = {
            block: "fold",
            id: "draft",
            version: null,
            offers: [],
            reaches: null,
            sighted: null,
            kind: "draft",
            summary: [{ text: `draft · ${parts.length}`, tone: "strong", ticking: null, gauge: null, refers: null }],
            open: null,
            content: parts,
        };
        return { ...blocks, blocks: [review, ...blocks.blocks] };
    }

    /** Answer the root again for every watch of it, the review as the draft stands. */
    #reviewed(): void {
        if (this.root === null) {
            return;
        }
        const key = viewKey(this.root);
        const blocks = this.#answers.get(key);
        if (blocks !== undefined) {
            this.set(this.root, blocks);
        }
    }

    watch(viewing: Viewing, answered: (blocks: Blocks) => void): () => void {
        const key = viewKey(viewing);
        const watches = this.#watches.get(key) ?? new Set();
        watches.add(answered);
        this.#watches.set(key, watches);
        const answer = this.#answers.get(key);
        if (answer !== undefined) {
            answered(this.#topped(key, answer));
        }
        return () => {
            watches.delete(answered);
        };
    }

    write(comment: Comment): void {
        const kept = this.draft.comments.some((each) => each.id === comment.id);
        this.draft = {
            ...this.draft,
            comments: kept ? this.draft.comments.map((each) => (each.id === comment.id ? comment : each)) : [...this.draft.comments, comment],
        };
        this.#reviewed();
    }

    erase(id: string): void {
        this.draft = { comments: this.draft.comments.filter((each) => each.id !== id), marks: this.draft.marks.filter((each) => each.id !== id) };
        this.#reviewed();
    }

    send(): void {
        const held = this.draft.comments.filter((each) => each.held);
        const went = this.draft.comments.filter((each) => !each.held && each.words.trim() !== "").map((each) => each.id);
        this.draft = { comments: held, marks: this.draft.marks.filter((each) => each.held) };
        this.told(this.draft);
        for (const delivered of this.#delivered) {
            delivered({ kind: "delivered", went, stayed: [], held: held.map((each) => each.id) });
        }
    }

    drafts(drafted: (draft: Draft) => void, delivered: (delivered: Delivered) => void): () => void {
        this.#drafted.add(drafted);
        this.#delivered.add(delivered);
        drafted(this.draft);
        return () => {
            this.#drafted.delete(drafted);
            this.#delivered.delete(delivered);
        };
    }

    /** Tell every page following the draft that it's now `draft`, as the core tells the other pages a page's change. */
    told(draft: Draft): void {
        this.draft = draft;
        for (const drafted of this.#drafted) {
            drafted(draft);
        }
        this.#reviewed();
    }
}

const core = declared as Looks;

/** The kinds the core declares, as the core's own declaration gives them, and a module's `note` fold kind: what the page's promises lay their blocks out with. */
export const looks: Looks = {
    ...core,
    folds: [
        ...core.folds,
        { module: "notes", kind: { name: "note", letter: "n", called: "note", level: 1, starts_open: false, colour: "cyan" } },
    ],
};
