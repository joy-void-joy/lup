import { describe, expect, it } from "vitest";

import type { Folding } from "./comments";
import { around, foldEdge, levelled, nextFold, ofKind } from "./folds";
import type { FoldKind } from "./keys";

// A text of lines two characters long, line `n` starting at `3n`.
const start = (line: number) => line * 3;
const startOf = (position: number) => start(Math.floor(position / 3));

/** A fold of `kind` whose summary is line `first` and whose last line is `last`. */
function fold(key: string, kind: FoldKind, first: number, last: number, closed: boolean): Folding {
    return { key, kind, closed, summary: { from: start(first), to: start(first) + 2 }, from: start(first) + 2, to: start(last) + 2 };
}

// An item, 0–20: a file, 2–15, holding a body, 4–10, with folded lines in it, 6–8, and folded lines, 12–14; its
// context, folded, 17–20. Another item, 22–30, holding a folded body, 24–28, with folded lines hidden in it, 25–26.
const FOLDS = [
    fold("A", "item", 0, 20, false),
    fold("B", "file", 2, 15, false),
    fold("C", "body", 4, 10, false),
    fold("D", "lines", 6, 8, true),
    fold("E", "lines", 12, 14, true),
    fold("F", "context", 17, 20, true),
    fold("G", "item", 22, 30, false),
    fold("H", "body", 24, 28, true),
    fold("I", "lines", 25, 26, true),
];
const closed = (each: Folding) => each.closed;
const line = (position: number | undefined) => (position === undefined ? undefined : position / 3);

describe("the folds the cursor is in", () => {
    it("finds them from a summary line to a last line, outermost first", () => {
        expect(around(FOLDS, start(7)).map((each) => each.key)).toEqual(["A", "B", "C", "D"]);
        expect(around(FOLDS, start(4)).map((each) => each.key)).toEqual(["A", "B", "C"]);
        expect(around(FOLDS, start(21))).toEqual([]);
    });
});

describe("moving by folds", () => {
    const zj = (from: number) => line(nextFold(FOLDS, closed, start(from), true, startOf));
    const zk = (from: number) => line(nextFold(FOLDS, closed, start(from), false, startOf));
    const openStart = (from: number) => line(foldEdge(FOLDS, closed, start(from), true, startOf));
    const openEnd = (from: number) => line(foldEdge(FOLDS, closed, start(from), false, startOf));

    it("goes with `zj` to the next fold's start, a folded one's own hidden in it not counted", () => {
        expect([0, 2, 4, 6, 12, 17, 22].map(zj)).toEqual([2, 4, 6, 12, 17, 22, 24]);
        expect(zj(24)).toBeUndefined();
    });

    it("goes with `zk` to the end of the fold before, a folded one's being its summary line, an open one's the line seen last", () => {
        // The first item ends on its context's last line, which its folded context shows as its summary line.
        expect([30, 24, 17, 15, 12, 10].map(zk)).toEqual([24, 17, 15, 12, 10, 6]);
        expect(zk(6)).toBeUndefined();
    });

    it("goes with `[z` to the start of the open fold the cursor is in, and again to the one around it", () => {
        expect([9, 4, 2].map(openStart)).toEqual([4, 2, 0]);
        expect(openStart(0)).toBeUndefined();
        expect(openStart(21)).toBeUndefined();
    });

    it("goes with `]z` to the end of the open fold the cursor is in, the line seen last, and again to the one around it", () => {
        expect([5, 10, 15].map(openEnd)).toEqual([10, 15, 17]);
        expect(openEnd(17)).toBeUndefined();
        // On a folded fold's summary line, the open one around it.
        expect(openEnd(24)).toBe(30);
    });
});

describe("opening and closing one item's folds", () => {
    // One item, folded, as one marked read: a file, its lines and a body in it, its context.
    const READ = [
        fold("item", "item", 0, 20, true),
        fold("file", "file", 2, 15, true),
        fold("body", "body", 4, 10, false),
        fold("lines", "lines", 12, 14, true),
        fold("context", "context", 17, 20, true),
    ];

    it("opens a level more with `zr`, the item's own first, and closes one with `zm`, never the item's own", () => {
        const state = new Set(READ.filter(closed));
        const step = (opening: boolean) => {
            const changed = levelled(READ, (each) => state.has(each), opening, false);
            for (const each of changed) {
                if (opening) {
                    state.delete(each);
                } else {
                    state.add(each);
                }
            }
            return changed.map((each) => each.key);
        };
        expect([true, true, true, true, true].map(step)).toEqual([["item"], ["file"], ["lines"], ["context"], []]);
        expect([false, false, false, false].map(step)).toEqual([["context"], ["body", "lines"], ["file"], []]);
        expect(state.has(READ[0]!)).toBe(false);
    });

    it("opens with `zR` every fold of it, and closes with `zM` every one but its own", () => {
        expect(levelled(READ, closed, true, true).map((each) => each.key)).toEqual(["item", "file", "lines", "context"]);
        const open = () => false;
        expect(levelled(READ, open, false, true).map((each) => each.key)).toEqual(["file", "body", "lines", "context"]);
    });

    it("opens with Space z and a letter each fold of a kind, and the item's own so they're seen; closes with Shift and the letter", () => {
        expect(ofKind(READ, closed, "lines", false).map((each) => each.key)).toEqual(["item", "lines"]);
        expect(ofKind(READ, closed, "body", false).map((each) => each.key)).toEqual(["item"]);
        expect(ofKind(READ, closed, "body", true).map((each) => each.key)).toEqual(["body"]);
        expect(ofKind(READ, closed, "lines", true)).toEqual([]);
    });
});
