// The document's promises: what the editor and everything drawn on the document (folds, comments, the cursor) can
// count on of where each block is, as views answer again.

import fc from "fast-check";
import { expect } from "vitest";

import type { Block, Blocks, Fold } from "../generated/read";
import { blocks } from "../testing/blocks";
import { scenario } from "../testing/promise";
import { Document, every, nodeAt, offsetOf, section, textOf, type Change } from "./tree";

function answer(content: Block[]): Blocks {
    return { blocks: content, summary: [], offers: [] };
}

/** Return `text` with `changes`, each counted on the text before any of them, made. */
function applied(text: string, changes: Change[]): string {
    return [...changes]
        .sort((one, other) => other.from - one.from)
        .reduce((made, change) => made.slice(0, change.from) + change.insert + made.slice(change.to), text);
}

scenario("Every block starts where the document's text shows it, so what's drawn on a block lands on its lines", (by) => {
    const root = section("root", null, answer(by.any(blocks(3))));
    const text = textOf(root);
    for (const node of every(root)) {
        const start = offsetOf(node);
        expect(text.slice(start, start + node.size)).toBe(textOf(node));
    }
});

scenario("The innermost block at a position is the one whose text holds it", (by) => {
    const root = section("root", null, answer(by.any(blocks(3))));
    const text = textOf(root);
    const position = by.any(fc.integer({ min: 0, max: text.length }));
    const found = nodeAt(root, position);
    const start = offsetOf(found);
    expect(start <= position && position <= start + found.size).toBe(true);
    for (const child of found.children) {
        const from = offsetOf(child);
        expect(child.lines === 0 || position < from || position > from + child.size).toBe(true);
    }
});

scenario("A view answered again leaves the document's text as if it were laid out afresh", (by) => {
    const document = new Document(section("root", null, answer(by.any(blocks(3)))));
    const before = document.text();
    const again = answer(by.any(blocks(3)));
    const changes = document.replace("root", again);
    expect(applied(before, changes)).toBe(textOf(section("root", null, again)));
    expect(document.text()).toBe(textOf(section("root", null, again)));
});

scenario("A view answered again with the same blocks changes the text of those that changed alone, so the rest keep their place", (by) => {
    const first = by.any(blocks(2));
    const document = new Document(section("root", null, answer(first)));
    const text = document.text();
    const second = first.map((block, at) =>
        at % 2 === 0 && block.block === "line"
            ? { ...block, spans: [{ text: `${block.spans[0]?.text ?? ""}!`, tone: "plain", ticking: null, gauge: null, refers: null }] }
            : block,
    );
    const unchanged = first.filter((block, at) => second[at] === block).map((block) => `root/${block.id}`);
    const kept = unchanged.map((key) => {
        const node = document.node(key);
        return node === null ? null : { from: offsetOf(node), to: offsetOf(node) + node.size };
    });
    const changes = document.replace("root", answer(second));
    for (const range of kept) {
        if (range === null) {
            continue;
        }
        for (const change of changes) {
            expect(change.to <= range.from || change.from >= range.to).toBe(true);
        }
    }
    expect(applied(text, changes)).toBe(document.text());
});

scenario("What a fold reads as it opens stays under it while its view answers again with the fold reading the same view", (by) => {
    const reads = { module: null, view: "note", given: { number: 1 } };
    const opening: Fold = {
        block: "fold",
        id: "n1",
        version: null,
        offers: [],
        reaches: null,
        sighted: null,
        kind: "note",
        summary: [{ text: "note 1", tone: "plain", ticking: null, gauge: null, refers: null }],
        open: null,
        content: reads,
    };
    const around = by.any(blocks(1));
    const document = new Document(section("root", null, answer([opening, ...around])));
    const read = answer(by.any(blocks(1)));
    document.mount("root/n1", reads, read);
    const mounted = section("x", null, read);
    document.replace("root", answer([opening, ...by.any(blocks(1))]));
    const fold = document.node("root/n1");
    const expected = ["note 1", ...(mounted.lines > 0 ? [textOf(mounted)] : [])].join("\n");
    expect(fold === null ? null : textOf(fold)).toBe(expected);
});
