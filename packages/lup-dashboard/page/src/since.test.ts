import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import { shownOnce, type Diff } from "./code";
import type { components } from "./generated/api";
import { freshRows, marked, reviewedLine, sameShown } from "./since";
import { judged } from "./views/judge";

type Since = components["schemas"]["Since"];
type SinceFile = components["schemas"]["SinceFile"];

const file = (before: string | null, after: string | null): Diff =>
    judged(
        {
            path: "reader.py",
            before: before === null ? null : { kind: "text", text: before },
            after: after === null ? null : { kind: "text", text: after },
        },
        false,
    );

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
        const rows = shownOnce(changed).rows;
        const fresh = freshRows(null, changed);
        expect(rows.filter((row) => fresh.rows.has(row)).map((row) => `${row.change} ${row.text}`)).toEqual(["removed b = 2", "added b = 20", "added c = 3"]);
    });

    it("are each row shown anew or otherwise, and the row after one gone, against the version they looked at", () => {
        const now = file(null, "a = 1\nb = 2\nd = 4\nc = 3\n");
        const rows = shownOnce(now).rows;
        const grown = freshRows(first, now);
        expect(rows.filter((row) => grown.rows.has(row)).map((row) => row.text)).toEqual(["d = 4"]);
        expect(grown.gaps.size).toBe(0);
        // A line of the integration branch's the agent took out shows removed, which it didn't.
        const based = file("a = 1\nb = 2\n", "a = 1\nb = 2\nc = 3\n");
        const cut = file("a = 1\nb = 2\n", "b = 2\nc = 3\n");
        const taken = freshRows(based, cut);
        const shown = shownOnce(cut).rows;
        expect(shown.filter((row) => taken.rows.has(row)).map((row) => `${row.change} ${row.text}`)).toEqual(["removed a = 1"]);
        // A line only added, then taken out again, leaves its mark on the row after where it was.
        const gone = freshRows(now, first);
        const after = shownOnce(first).rows;
        expect([gone.rows.size, after.filter((row) => gone.gaps.has(row)).map((row) => row.text)]).toEqual([0, ["c = 3"]]);
        // Worked out once for each pair, as it's painted at each scroll.
        expect(freshRows(first, now)).toBe(grown);
    });
});

describe("a file being marked reviewed", () => {
    const at = "2026-10-23T21:00:00Z";
    const a: SinceFile = { path: "a.py", version: "a1", flags: [70], file: { path: "a.py", before: null, after: { kind: "text", text: "a = 1\n" } } };
    const b: SinceFile = { path: "b.py", version: "b1", flags: [], file: { path: "b.py", before: { kind: "text", text: "b = 1\n" }, after: { kind: "text", text: "b = 2\n" } } };
    const feat = { worktree: "/r/tree/feat", branch: "feat", gone: false, files: [a, b] };
    // The same path on another of the agent's places, at its tip.
    const fix = { worktree: null, branch: "fix", gone: false, files: [{ ...a, version: "a2" }] };
    const drawer: Since = { kind: "policy-since", version: "t1 0 s1", same: false, places: [feat, fix] };
    const line: SinceFile = { path: "a.py", version: "a1", flags: [], file: null, since: null, reviewed: at, held: null };
    const mark = { worktree: "/r/tree/feat", branch: "feat", path: "a.py", version: "a1", at };

    it("is the line of one reviewed at once, its flags approved with it, in its place alone, the other files as they are", () => {
        const shown = marked(drawer, [mark]);
        expect(shown.places?.[0]?.files).toEqual([line, b]);
        expect(shown.places?.[0]?.files?.[1]).toBe(b);
        expect(shown.places?.[1]).toBe(fix);
        expect(reviewedLine(line)).toBe("a.py · reviewed at a1");
    });

    it("stays as it is where it moved since the version marked, and the drawer is the one read where nothing's marked", () => {
        expect(marked(drawer, [{ ...mark, version: "a0" }])).toBe(drawer);
        expect(marked(drawer, [{ ...mark, branch: "other" }])).toBe(drawer);
        expect(marked(drawer, [])).toBe(drawer);
    });

    it("is laid out the same as the host's answer marking it, so the answer lays out nothing again", () => {
        const shown = marked(drawer, [mark]);
        const answer: Since = { ...drawer, version: "t1 1 s2", places: [{ ...feat, files: [{ path: "a.py", version: "a1", flags: [], reviewed: "2026-10-23T21:00:01Z" }, b] }, fix] };
        expect(sameShown(shown, answer)).toBe(true);
        // A flag waiting on it still, a file shown otherwise, another branch, or a place more are laid out anew.
        const waiting: Since = { ...answer, places: [{ ...feat, files: [{ path: "a.py", version: "a1", flags: [70], reviewed: at }, b] }, fix] };
        expect(sameShown(shown, waiting)).toBe(false);
        expect(sameShown(shown, drawer)).toBe(false);
        expect(sameShown(drawer, { ...drawer, places: [{ ...feat, branch: "other" }, fix] })).toBe(false);
        expect(sameShown(drawer, { ...drawer, places: [feat] })).toBe(false);
    });
});

describe("a file held at landing", () => {
    const held = { key: "w1", lander: { party: "conversation" as const, repository: "/r.git", runtime: "claude", session: "s1" }, named: "`feat` on `dev`", tip: "c0ffee", declined: false };

    it("says so on its line, and that it's declined once it is", () => {
        expect(reviewedLine({ path: "a.py", version: "a1b2c3d4", flags: [70], reviewed: "2026-10-23T21:00:00Z", held })).toBe("a.py · reviewed at a1b2c3d · flagged @70 · held at landing: `feat` on `dev`");
        expect(reviewedLine({ path: "a.py", version: "a1", flags: [70], held: { ...held, declined: true } })).toBe("a.py · flagged @70 · landing declined: `feat` on `dev`");
    });
});
