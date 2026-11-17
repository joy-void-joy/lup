// Views read from memory, for the page's promises: what each answers is set by the promise, and pushed to whoever
// watches it, as the core pushes a view answered again.

import type { Blocks, Looks, Viewing } from "../generated/read";
import { viewKey } from "../document/tree";
import declared from "../generated/core-looks.json";
import type { Source } from "../shell/shell";

/** Views answered from memory: each view's latest answer, pushed to every watch of it as it's set. */
export class Memory implements Source {
    readonly #answers = new Map<string, Blocks>();
    readonly #watches = new Map<string, Set<(blocks: Blocks) => void>>();

    /** Set what `viewing` answers, and push it to every watch of it. */
    set(viewing: Viewing, blocks: Blocks): void {
        const key = viewKey(viewing);
        this.#answers.set(key, blocks);
        for (const answered of this.#watches.get(key) ?? []) {
            answered(blocks);
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
