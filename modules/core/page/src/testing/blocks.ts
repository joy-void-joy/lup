// Blocks as fast-check draws them, for the page's promises: lines, Markdown and folds, each with an id of its own
// among its siblings, folds nested a few deep.

import fc from "fast-check";

import type { Block, Fold, Line, Markdown } from "../generated/read";

export const words = fc.string({ unit: fc.constantFrom("a", "b", "c", " ", "é"), maxLength: 12 });

export function line(id: string): fc.Arbitrary<Line> {
    return words.map((text) => ({
        block: "line",
        id,
        version: null,
        offers: [],
        reaches: null,
        spans: [{ text, tone: "plain", ticking: null, gauge: null, refers: null }],
    }));
}

export function markdown(id: string): fc.Arbitrary<Markdown> {
    return fc.array(words, { minLength: 1, maxLength: 3 }).map((lines) => ({
        block: "markdown",
        id,
        version: null,
        offers: [],
        reaches: null,
        text: lines.join("\n"),
        tone: "plain",
    }));
}

export function fold(id: string, depth: number): fc.Arbitrary<Fold> {
    return fc.record({ summary: words, content: blocks(depth - 1) }).map(({ summary, content }) => ({
        block: "fold",
        id,
        version: null,
        offers: [],
        reaches: null,
        kind: "note",
        summary: [{ text: summary, tone: "plain", ticking: null, gauge: null, refers: null }],
        open: null,
        content,
    }));
}

/** Blocks with ids of their own, folds nested `depth` deep at most. */
export function blocks(depth: number): fc.Arbitrary<Block[]> {
    return fc.array(fc.integer({ min: 0, max: depth > 0 ? 2 : 1 }), { maxLength: 5 }).chain((kinds) =>
        fc.tuple(
            ...kinds.map((kind, at): fc.Arbitrary<Block> => {
                const id = `b${at}`;
                return kind === 0 ? line(id) : kind === 1 ? markdown(id) : fold(id, depth);
            }),
        ),
    );
}

