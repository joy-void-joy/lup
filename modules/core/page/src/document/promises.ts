// The document's promises: what the editor and everything drawn on the document (folds, comments, the cursor) can
// count on of where each block is, as views answer again.

import { ChangeSet, Text } from "@codemirror/state";
import fc from "fast-check";
import { expect } from "vitest";

import type { Block, Blocks, Fold } from "../generated/read";
import { blocks } from "../testing/blocks";
import { scenario } from "../testing/promise";
import { comment, Document, every, nodeAt, offsetOf, section, textOf, type Change, type Node } from "./tree";

function answer(content: Block[]): Blocks {
    return { blocks: content, summary: [], offers: [] };
}

/** Return `text` with `changes`, each counted on the text before any of them, made as the editor makes them. */
function applied(text: string, changes: Change[]): string {
    return ChangeSet.of(changes, text.length).apply(Text.of(text.split("\n"))).toString();
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
        sighted: null, standing: null,
        aside: [],
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

/** Return the blocks of `document` a comment can be written under: those with lines of their own. */
function commentable(document: Document): Node[] {
    return every(document.root).filter((node) => node.block !== null && node.head.length > 0);
}

/** Write a comment under a line of each of `count` blocks of `document`, as `by` draws them, and return their keys. */
function commented(document: Document, by: { any<T>(arbitrary: fc.Arbitrary<T>): T }, count: number): string[] {
    const keys: string[] = [];
    for (let at = 0; at < count; at++) {
        const blocks = commentable(document);
        if (blocks.length === 0) {
            break;
        }
        const block = blocks[by.any(fc.integer({ min: 0, max: blocks.length - 1 }))];
        if (block === undefined) {
            break;
        }
        const words = by.any(fc.array(fc.string({ unit: fc.constantFrom("x", "y", " "), maxLength: 6 }), { minLength: 1, maxLength: 3 })).join("\n");
        const line = by.any(fc.integer({ min: 0, max: block.head.length - 1 }));
        const key = `comment-${at}`;
        const before = document.text();
        const changes = document.remark(block.key, comment(key, words, line));
        expect(applied(before, changes)).toBe(document.text());
        keys.push(key);
    }
    return keys;
}

scenario("A comment written under one of a block's lines shows right under it, and taking it out leaves the text as it was", (by) => {
    const document = new Document(section("root", null, answer(by.any(blocks(2)))));
    const original = document.text();
    const [key] = commented(document, by, 1);
    if (key === undefined) {
        return;
    }
    const written = document.node(key);
    const block = written?.parent ?? null;
    expect(written === null || block === null).toBe(false);
    if (written === null || block === null) {
        return;
    }
    const lines = textOf(block).split("\n");
    const under = block.head.slice(0, (written.after ?? 0) + 1);
    expect(lines.slice(0, under.length)).toEqual(under);
    expect(lines.slice(under.length, under.length + written.head.length)).toEqual(written.head);
    const before = document.text();
    expect(applied(before, document.unremark(key))).toBe(original);
    expect(document.text()).toBe(original);
});

scenario("A view answered again leaves every comment it keeps the block of untouched, its text where it was, and writes nothing over it", (by) => {
    const document = new Document(section("root", null, answer(by.any(blocks(2)))));
    const keys = commented(document, by, by.any(fc.integer({ min: 1, max: 3 })));
    const before = document.text();
    const ranges = new Map(
        keys.flatMap((key) => {
            const node = document.node(key);
            return node === null ? [] : [[key, { from: offsetOf(node), to: offsetOf(node) + node.size, text: textOf(node) }] as const];
        }),
    );
    const changes = document.replace("root", answer(by.any(blocks(2))));
    expect(applied(before, changes)).toBe(document.text());
    for (const [key, range] of ranges) {
        const node = document.node(key);
        if (node === null) {
            continue;
        }
        expect(textOf(node)).toBe(range.text);
        for (const change of changes) {
            expect(change.from < range.to && change.to > range.from).toBe(false);
        }
    }
});
