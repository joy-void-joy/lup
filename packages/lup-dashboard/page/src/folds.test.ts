import { LOOKS, STANDING } from "./fixtures/looks";
import { describe, expect, it } from "vitest";

import type { Folding } from "./comments";
import { around, aroundOf, depths, foldEdge, levelled, nextFold, ofKind, recursive } from "./folds";
import type { FoldKind } from "./keys";
import { adopt, merged, type Looks } from "./looks";

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

    it("opens with zO every fold the cursor is in and every one within the innermost, and closes with zC every one it's in", () => {
        expect(recursive(FOLDS, start(4), true).map((each) => each.key)).toEqual(["A", "B", "C", "D"]);
        expect(recursive(FOLDS, start(2), true).map((each) => each.key)).toEqual(["A", "B", "C", "D", "E"]);
        expect(recursive(FOLDS, start(7), false).map((each) => each.key)).toEqual(["A", "B", "C", "D"]);
        expect(recursive(FOLDS, start(21), true)).toEqual([]);
        // A call's input and output, read as it opens, isn't opened by zO from around it.
        const deep = [fold("K", "calls", 0, 10, false), fold("L", "call", 2, 4, true)];
        expect(recursive(deep, start(0), true).map((each) => each.key)).toEqual(["K"]);
        expect(recursive(deep, start(3), true).map((each) => each.key)).toEqual(["K", "L"]);
    });

    it("sets each as deep as the folds holding it, so its column in the margin is its place among those the cursor is in", () => {
        const deep = depths(FOLDS);
        expect(FOLDS.map((each) => `${each.key}${deep.get(each)}`)).toEqual(["A0", "B1", "C2", "D3", "E2", "F1", "G0", "H1", "I2"]);
        for (const at of [7, 13, 18, 25]) {
            const chain = around(FOLDS, start(at));
            expect(chain.map((each) => deep.get(each))).toEqual(chain.map((_, depth) => depth));
        }
        // Two folds under one summary line, as two bodies declared on it: the one around the other is outermost.
        const inner = fold("K", "body", 2, 4, false);
        const outer = fold("J", "body", 2, 6, false);
        expect([...depths([inner, outer]).entries()].map(([each, depth]) => `${each.key}${depth}`)).toEqual(["J0", "K1"]);
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

    it("leaves with `zR` and `zM` the folds of a kind a person's layer says they don't reach, as `zr` still opens them", () => {
        const kept: Looks = { ...STANDING, folds: (STANDING.folds ?? []).map((each) => (each.name === "lines" ? { ...each, by_all: false } : each)) };
        adopt(merged({}, kept));
        try {
            expect(levelled(READ, closed, true, true).map((each) => each.key)).toEqual(["item", "file", "context"]);
            expect(levelled(READ, () => false, false, true).map((each) => each.key)).toEqual(["file", "body", "context"]);
        } finally {
            adopt(LOOKS);
        }
    });

    it("finds the innermost fold of a kind the cursor is in, from its summary line, for z f and the kind's letter", () => {
        const at = (key: string) => READ.find((each) => each.key === key)!;
        const lines = at("lines");
        expect(aroundOf(READ, lines.summary.from, "lines")?.key).toBe("lines");
        expect(aroundOf(READ, lines.to, "file")?.key).toBe("file");
        expect(aroundOf(READ, lines.to, "item")?.key).toBe("item");
        expect(aroundOf(READ, at("item").summary.from, "file")).toBeUndefined();
    });

    it("in a conversation, opens with each `zr` one exchange further back, the latest first, then its runs of calls, never a call's input and output", () => {
        // A conversation drawer, 0–30: what came before the operator's first words, 1–4; two earlier exchanges, 5–12 and
        // 13–20, a run of calls in each, one holding a call's input and output; the last exchange, open, 21–30, a run in it.
        const talk = [
            fold("drawer", "conversation", 0, 30, true),
            fold("before", "earlier", 1, 4, true),
            fold("first", "earlier", 5, 12, true),
            fold("run 1", "calls", 7, 10, true),
            fold("call 1", "call", 8, 9, true),
            fold("second", "earlier", 13, 20, true),
            fold("run 2", "calls", 15, 18, true),
            fold("run 3", "calls", 23, 26, true),
        ];
        const state = new Set(talk);
        const step = (opening: boolean) => {
            const changed = levelled(talk, (each) => state.has(each), opening, false);
            for (const each of changed) {
                if (opening) {
                    state.delete(each);
                } else {
                    state.add(each);
                }
            }
            return changed.map((each) => each.key);
        };
        expect([true, true, true, true, true, true].map(step)).toEqual([["drawer"], ["second"], ["first"], ["before"], ["run 1", "run 2", "run 3"], []]);
        // `zm` closes the runs, then each exchange, the earliest first.
        expect([false, false, false].map(step)).toEqual([["run 1", "run 2", "run 3"], ["before"], ["first"]]);
        expect(levelled(talk, closed, true, true).map((each) => each.key)).not.toContain("call 1");
        expect(ofKind(talk, (each) => each.key !== "drawer", "call", false).map((each) => each.key)).toEqual(["call 1"]);
    });

    it("opens with Space z f and a letter each fold of a kind, and the item's own so they're seen; closes with Space z F and the letter", () => {
        expect(ofKind(READ, closed, "lines", false).map((each) => each.key)).toEqual(["item", "lines"]);
        expect(ofKind(READ, closed, "body", false).map((each) => each.key)).toEqual(["item"]);
        expect(ofKind(READ, closed, "body", true).map((each) => each.key)).toEqual(["body"]);
        expect(ofKind(READ, closed, "lines", true)).toEqual([]);
    });
});
