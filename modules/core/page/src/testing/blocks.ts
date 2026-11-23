// Blocks as fast-check draws them, for the page's promises: lines, Markdown and folds, each with an id of its own
// among its siblings, folds nested a few deep.

import fc from "fast-check";

import type { Block, Fold, Line, Markdown } from "../generated/read";

/** Words as views answer them: a line break among them now and then, as `\r\n` or `\r` as well as `\n`, which a line shows as a space and a block of text breaks at. */
export const words = fc.string({ unit: fc.constantFrom("a", "b", "c", " ", "é", "\n", "\r"), maxLength: 12 });

export function line(id: string): fc.Arbitrary<Line> {
    return words.map((text) => ({
        block: "line",
        id,
        version: null,
        offers: [],
        reaches: null,
        sighted: null, standing: null,
        aside: [],
        spans: [{ text, tone: "plain", ticking: null, gauge: null, refers: null }],
    }));
}

/** A piece of a line of Markdown: plain words, or one of its constructs, whose marks the shell hides. */
const written = fc.constantFrom("a", "b c", " ", "\r\n", "*em*", "**strong**", "`code`", "[link](https://x.y)", "# ", "- ", "1. ", "~~gone~~", "\\*", "| a | bb |", "|---|---|");

/** A line of Markdown: a few of its pieces, or plain words. */
export const markdownLine = fc.oneof(words, fc.array(written, { maxLength: 5 }).map((pieces) => pieces.join("")));

export function markdown(id: string): fc.Arbitrary<Markdown> {
    return fc.array(markdownLine, { minLength: 1, maxLength: 3 }).map((lines) => ({
        block: "markdown",
        id,
        version: null,
        offers: [],
        reaches: null,
        sighted: null, standing: null,
        aside: [],
        text: lines.join("\n"),
        tone: "plain",
        anchors: [],
    }));
}

/** A fold of one of `kinds`, holding blocks nested `depth` deep at most. */
export function fold(id: string, depth: number, kinds: readonly string[] = ["note"]): fc.Arbitrary<Fold> {
    return fc.record({ summary: words, content: blocks(depth - 1, kinds), kind: fc.constantFrom(...kinds) }).map(({ summary, content, kind }) => ({
        block: "fold",
        id,
        version: null,
        offers: [],
        reaches: null,
        sighted: null, standing: null,
        aside: [],
        kind,
        summary: [{ text: summary, tone: "plain", ticking: null, gauge: null, refers: null }],
        open: null,
        content,
    }));
}

/** Blocks with ids of their own, folds of `kinds` nested `depth` deep at most. */
export function blocks(depth: number, kinds: readonly string[] = ["note"]): fc.Arbitrary<Block[]> {
    return fc.array(fc.integer({ min: 0, max: depth > 0 ? 2 : 1 }), { maxLength: 5 }).chain((shapes) =>
        fc.tuple(
            ...shapes.map((shape, at): fc.Arbitrary<Block> => {
                const id = `b${at}`;
                return shape === 0 ? line(id) : shape === 1 ? markdown(id) : fold(id, depth, kinds);
            }),
        ),
    );
}

