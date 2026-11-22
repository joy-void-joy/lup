// Views read from memory, for the page's promises: what each answers is set by the promise, and pushed to whoever
// watches it, as the core pushes a view answered again; and the draft, kept as the core keeps it, a send taking out
// every comment that says something and isn't held back, and dropping those that say nothing; and its review, as the
// server's (`lup.environment.shell.review`), each part a line of its id.

import type { Block, Blocks, Comment, Delivered, Draft, Looks, Marked, Viewing } from "../generated/read";
import { viewKey } from "../document/tree";
import declared from "../generated/core-looks.json";
import type { Source } from "../shell/shell";

/** Views answered from memory: each view's latest answer, pushed to every watch of it as it's set. */
export class Memory implements Source {
    readonly #answers = new Map<string, Blocks>();
    readonly #watches = new Map<string, Set<(blocks: Blocks) => void>>();
    readonly #drafted = new Set<(draft: Draft) => void>();
    readonly #delivered = new Set<(delivered: Delivered) => void>();
    readonly #reviews = new Set<(review: Blocks) => void>();
    /** The draft, as the core keeps it. */
    draft: Draft = { comments: [], marks: [] };
    /** Every mark sent, in the order sends sent them: the actions the core ran. */
    sent: Marked[] = [];

    /** Set what `viewing` answers, and push it to every watch of it. */
    set(viewing: Viewing, blocks: Blocks): void {
        const key = viewKey(viewing);
        this.#answers.set(key, blocks);
        for (const answered of this.#watches.get(key) ?? []) {
            answered(blocks);
        }
    }

    /**
     * Return the review of the draft as the server lays it out, each part a line under where it goes, then what's held
     * back: but each place a comment goes said by whom it's chosen to reach alone, and a mark's by what it does.
     */
    review(): Blocks {
        interface Part {
            readonly id: string;
            readonly text: string;
            readonly held: boolean;
            readonly to: string;
        }
        const parts: Part[] = [
            ...this.draft.comments.map((each) => ({
                id: each.id,
                text: each.words.split("\n")[0] ?? "",
                held: each.held,
                to: each.to === null ? "to what it's on" : `to ${JSON.stringify(each.to)}`,
            })),
            ...this.draft.marks.map((each) => ({ id: each.id, text: each.offer.says, held: each.held, to: "marked" })),
        ];
        const line = (part: Part): Block => ({
            block: "line",
            id: part.id,
            version: null,
            offers: [],
            reaches: null,
            sighted: null, standing: null,
            spans: [{ text: part.text, tone: "strong", ticking: null, gauge: null, refers: null }],
        });
        const place = (id: string, summary: string, placed: readonly Part[]): Block => ({
            block: "fold",
            id,
            version: null,
            offers: [],
            reaches: null,
            sighted: null, standing: null,
            kind: "sent-to",
            summary: [{ text: summary, tone: "strong", ticking: null, gauge: null, refers: null }],
            open: null,
            content: placed.map(line),
        });
        const sending = parts.filter((each) => !each.held);
        const held = parts.filter((each) => each.held);
        const places = [...new Set(sending.map((each) => each.to))].map((to) =>
            place(to === "marked" ? to : `to ${to}`, to, sending.filter((each) => each.to === to)),
        );
        return {
            blocks: [...places, ...(held.length > 0 ? [place("held", "held back", held)] : [])],
            summary: parts.length > 0 ? [{ text: `draft · ${sending.length} to send`, tone: "strong", ticking: null, gauge: null, refers: null }] : [],
            offers: [],
        };
    }

    #reviewed(): void {
        const review = this.review();
        for (const reviewed of this.#reviews) {
            reviewed(review);
        }
    }

    watch(viewing: Viewing, answered: (blocks: Blocks) => void): () => void {
        const key = viewKey(viewing);
        const watches = this.#watches.get(key) ?? new Set();
        watches.add(answered);
        this.#watches.set(key, watches);
        const answer = this.#answers.get(key);
        if (answer !== undefined) {
            answered(answer);
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

    mark(marked: Marked): void {
        const kept = this.draft.marks.some((each) => each.id === marked.id);
        this.draft = {
            ...this.draft,
            marks: kept ? this.draft.marks.map((each) => (each.id === marked.id ? marked : each)) : [...this.draft.marks, marked],
        };
        this.#reviewed();
    }

    erase(id: string): void {
        this.draft = { comments: this.draft.comments.filter((each) => each.id !== id), marks: this.draft.marks.filter((each) => each.id !== id) };
        this.#reviewed();
    }

    send(): void {
        const held = this.draft.comments.filter((each) => each.held);
        const marksHeld = this.draft.marks.filter((each) => each.held);
        const went = [
            ...this.draft.comments.filter((each) => !each.held && each.words.trim() !== "").map((each) => each.id),
            ...this.draft.marks.filter((each) => !each.held).map((each) => each.id),
        ];
        this.sent = [...this.sent, ...this.draft.marks.filter((each) => !each.held)];
        this.draft = { comments: held, marks: marksHeld };
        this.told(this.draft);
        for (const delivered of this.#delivered) {
            delivered({ kind: "delivered", went, stayed: [], held: [...held, ...marksHeld].map((each) => each.id) });
        }
    }

    reviews(reviewed: (review: Blocks) => void): () => void {
        this.#reviews.add(reviewed);
        reviewed(this.review());
        return () => {
            this.#reviews.delete(reviewed);
        };
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
        { module: "notes", kind: { name: "note", letter: "n", called: "note", level: 1, starts_open: false, colour: "cyan", outlined: true } },
    ],
};
