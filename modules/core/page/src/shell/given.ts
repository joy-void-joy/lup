// A document given rather than read: what the page's own shells beside the document show, the window's and the
// outline's, answered as their root and answered again as it's given again, keeping no draft of their own.

import type { Blocks, Comment, Delivered, Draft, Viewing } from "../generated/read";
import type { Source } from "./shell";

/** A document given: answered as its root, and again each time it's given again; nothing kept as a draft. */
export class Given implements Source {
    #blocks: Blocks;
    readonly #answered = new Set<(blocks: Blocks) => void>();

    constructor(blocks: Blocks) {
        this.#blocks = blocks;
    }

    /** Show `blocks` in place of what's shown. */
    set(blocks: Blocks): void {
        this.#blocks = blocks;
        for (const answered of this.#answered) {
            answered(blocks);
        }
    }

    watch(_viewing: Viewing, answered: (blocks: Blocks) => void): () => void {
        this.#answered.add(answered);
        answered(this.#blocks);
        return () => {
            this.#answered.delete(answered);
        };
    }

    write(_comment: Comment): void {}

    erase(_id: string): void {}

    send(): void {}

    drafts(_drafted: (draft: Draft) => void, _delivered: (delivered: Delivered) => void): () => void {
        return () => {};
    }

    reviews(_reviewed: (review: Blocks) => void): () => void {
        return () => {};
    }
}

