import { describe, expect, it } from "vitest";

import { shownOnce, type ChangedFile } from "./code";
import { freshRows, reviewedLine } from "./since";

const file = (before: string | null, after: string | null): ChangedFile => ({
    path: "reader.py",
    before: before === null ? null : { kind: "text", text: before },
    after: after === null ? null : { kind: "text", text: after },
});

describe("a file standing as the operator last saw it", () => {
    it("is said in a line: reviewed at its version, deleted, or as seen in an item, with what flagged it since", () => {
        const at = "2026-10-17T12:00:00Z";
        expect(reviewedLine({ path: "a.py", version: "a1b2c3d4e5f6a7b8", flags: [], reviewed: at })).toBe("a.py · reviewed at a1b2c3d");
        expect(reviewedLine({ path: "a.py", version: null, flags: [], reviewed: at })).toBe("a.py · deleted · reviewed");
        expect(reviewedLine({ path: "a.py", version: "a1", flags: [70, 72], since: 12 })).toBe("a.py · as you saw it in @12 · flagged @70, @72");
    });
});

describe("the lines changed since the operator last looked at a file", () => {
    const first = file(null, "a = 1\nb = 2\nc = 3\n");

    it("are none where they look at it as it stands", () => {
        const fresh = freshRows(first, first);
        expect([fresh.rows.size, fresh.gaps.size]).toEqual([0, 0]);
    });

    it("are each line the file changes where they never looked at it", () => {
        const changed = file("a = 1\nb = 2\n", "a = 1\nb = 20\nc = 3\n");
        const rows = shownOnce(changed, "changes").rows;
        const fresh = freshRows(null, changed);
        expect(rows.filter((row) => fresh.rows.has(row)).map((row) => `${row.change} ${row.text}`)).toEqual(["removed b = 2", "added b = 20", "added c = 3"]);
    });

    it("are each row shown anew or otherwise, and the row after one gone, against the version they looked at", () => {
        const now = file(null, "a = 1\nb = 2\nd = 4\nc = 3\n");
        const rows = shownOnce(now, "changes").rows;
        const grown = freshRows(first, now);
        expect(rows.filter((row) => grown.rows.has(row)).map((row) => row.text)).toEqual(["d = 4"]);
        expect(grown.gaps.size).toBe(0);
        // A line of the integration branch's the agent took out shows removed, which it didn't.
        const based = file("a = 1\nb = 2\n", "a = 1\nb = 2\nc = 3\n");
        const cut = file("a = 1\nb = 2\n", "b = 2\nc = 3\n");
        const taken = freshRows(based, cut);
        const shown = shownOnce(cut, "changes").rows;
        expect(shown.filter((row) => taken.rows.has(row)).map((row) => `${row.change} ${row.text}`)).toEqual(["removed a = 1"]);
        // A line only added, then taken out again, leaves its mark on the row after where it was.
        const gone = freshRows(now, first);
        const after = shownOnce(first, "changes").rows;
        expect([gone.rows.size, after.filter((row) => gone.gaps.has(row)).map((row) => row.text)]).toEqual([0, ["c = 3"]]);
        // Worked out once for each pair, as it's painted at each scroll.
        expect(freshRows(first, now)).toBe(grown);
    });
});
