import { describe, expect, it } from "vitest";

import { endInLast, hashed, keptId, linesOf, mappedLine, newId, placed, quoting, type Quote } from "./anchors";
import { hunks } from "./comments";

/** A quote of lines `first` on of `lines`, whole, on block `b`. */
function on(lines: string[], first: number, count = 1): Quote {
    const quoted = lines.slice(first, first + count);
    return { text: quoted.join("\n"), block: "b", version: hashed(lines), line: first, lines: quoted, start: 0, end: quoted.join("\n").length };
}

describe("a block's version", () => {
    it("is the same for the same lines, and other for any other", () => {
        expect(hashed(["a", "b"])).toBe(hashed(["a", "b"]));
        expect(hashed(["a", "b"])).not.toBe(hashed(["ab"]));
        expect(hashed(["a", "b"])).not.toBe(hashed(["a", "b", ""]));
        expect(linesOf(["a"], "v1")).toEqual({ version: hashed(["a"]), lines: ["a"], given: "v1" });
    });
});

describe("a line followed through its block's change", () => {
    const before = ["a", "b", "c", "d"];

    it("moves with the lines before it, where it's kept", () => {
        const made = hunks(before, ["x", "y", "a", "b", "c", "d"]);
        expect(mappedLine(2, made)).toBe(4);
        expect(mappedLine(0, hunks(before, ["a", "b", "c", "d", "e"]))).toBe(0);
    });

    it("goes to what replaces it at its place, or the last of fewer, and before what's removed with nothing for it", () => {
        expect(mappedLine(1, hunks(before, ["a", "B", "c", "d"]))).toBe(1);
        expect(mappedLine(2, hunks(before, ["a", "X", "d"]))).toBe(1);
        expect(mappedLine(2, hunks(before, ["a", "d"]))).toBe(0);
        expect(mappedLine(0, hunks(before, ["c", "d"]))).toBe(0);
    });
});

describe("where a comment goes on its block", () => {
    const lines = ["def a():", "    return 1", "", "def b():", "    return 1"];

    it("follows the block's own diff from where it was laid out last, so a line like another isn't taken for it", () => {
        const now = linesOf(["def z():", "    pass", ...lines]);
        const was = linesOf(lines);
        const quote = on(lines, 4);
        expect(placed(quote, now, { placement: { block: "b", version: was.version, first: 4, last: 4 }, lines: was })).toEqual({ first: 6, last: 6, outdated: false });
    });

    it("goes where it was written as the review is first laid out, where its lines stand there", () => {
        expect(placed(on(lines, 3, 2), linesOf(lines), null)).toEqual({ first: 3, last: 4, outdated: false });
    });

    it("goes where its lines stand nearest where it was written, as after a reload once the block changed", () => {
        const now = linesOf(["# head", ...lines]);
        expect(placed(on(lines, 4), now, null)).toEqual({ first: 5, last: 5, outdated: false });
        expect(placed(on(lines, 1), now, null)).toEqual({ first: 2, last: 2, outdated: false });
    });

    it("is outdated where the lines under it aren't those it quotes, and stays within the block", () => {
        const now = linesOf(["def a():", "    return 2"]);
        expect(placed(on(lines, 1), now, null)).toEqual({ first: 1, last: 1, outdated: true });
        expect(placed(on(lines, 4), now, null)).toEqual({ first: 1, last: 1, outdated: true });
        const was = linesOf(lines);
        const changed = linesOf(["def a():", "    return 1", "", "def b():", "    return 2"]);
        expect(placed(on(lines, 4), changed, { placement: { block: "b", version: was.version, first: 4, last: 4 }, lines: was })).toEqual({ first: 4, last: 4, outdated: true });
    });
});

describe("a quote", () => {
    it("records the block's own version where it gives one, else its lines' hash, and the lines it's on whole", () => {
        const now = linesOf(["one", "two", "three"], "git1");
        expect(quoting("b", now, 1, 2, 1, 7, "wo\nthr")).toEqual({ text: "wo\nthr", block: "b", version: "git1", line: 1, lines: ["two", "three"], start: 1, end: 7 });
        expect(quoting("b", linesOf(["one"]), 0, 0, 0, 3, "one").version).toBe(hashed(["one"]));
    });

    it("says where it ends in its last line", () => {
        expect(endInLast({ text: "", block: "b", version: "", line: 0, lines: ["two", "three"], start: 1, end: 7 })).toBe(3);
        expect(endInLast({ text: "", block: "b", version: "", line: 0, lines: ["two"], start: 1, end: 2 })).toBe(2);
    });
});

describe("what's written's ids", () => {
    it("names one kept from before ids by its kind and place, and a new one unlike any other", () => {
        expect(keptId("remark", 2)).toBe("kept remark 2");
        const made = new Set(Array.from({ length: 50 }, newId));
        expect(made.size).toBe(50);
        expect([...made].every((each) => /^[0-9a-f]{18}$/.test(each))).toBe(true);
    });
});
