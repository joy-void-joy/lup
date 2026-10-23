import { describe, expect, it } from "vitest";

import { reviewedLine } from "./since";

describe("a file standing as the operator last saw it", () => {
    it("is said in a line: reviewed at its version, deleted, or as seen in an item, with what flagged it since", () => {
        const at = "2026-10-17T12:00:00Z";
        expect(reviewedLine({ path: "a.py", version: "a1b2c3d4e5f6a7b8", flags: [], reviewed: at })).toBe("a.py · reviewed at a1b2c3d");
        expect(reviewedLine({ path: "a.py", version: null, flags: [], reviewed: at })).toBe("a.py · deleted · reviewed");
        expect(reviewedLine({ path: "a.py", version: "a1", flags: [70, 72], since: 12 })).toBe("a.py · as you saw it in @12 · flagged @70, @72");
    });
});
