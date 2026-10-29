import { ChangeSet, EditorState, Text } from "@codemirror/state";
import { describe, expect, it } from "vitest";

import { arrivedLines, arriving, owned, owning, ownersOf, readBy, reconcile, runsOf, settled, type Reading } from "./reconcile";

/** Lines, each with whose it is, as a layout lays them out: `owner:text`. */
function layout(...lines: string[]): { text: string; owners: string[] } {
    const split = lines.map((each) => {
        const at = each.indexOf(":");
        return { owner: each.slice(0, at), text: each.slice(at + 1) };
    });
    return { text: `${split.map((each) => each.text).join("\n")}\n`, owners: split.map((each) => each.owner) };
}

/** The weight of each part's lines: what the operator wrote above all. */
const weight = (owner: string) => (owner.startsWith("written ") ? 1e6 : 1);

/** Lay `after` out over `before`, as the editor holds it: the changes, applied, and the doc made. */
function laidOver(before: { text: string; owners: string[] }, after: { text: string; owners: string[] }) {
    const doc = Text.of(before.text.split("\n"));
    const made = reconcile(doc, before.owners, after.text, after.owners, weight);
    const changes = ChangeSet.of(made.changes, doc.length);
    return { changes, doc: changes.apply(doc).toString(), arrived: made.arrived };
}

/** Return whether any of `changes` touches the text from `from` to `to`, or puts anything inside it. */
function touches(changes: ChangeSet, from: number, to: number): boolean {
    let touched = false;
    changes.iterChangedRanges((fromA, toA) => {
        touched ||= fromA < to && toA > from;
        touched ||= fromA === toA && fromA > from && fromA < to;
    });
    return touched;
}

describe("a layout made from what the editor holds", () => {
    const before = layout("file:a = 1", "file:b = 2", "written c1:Why b?", "file:c = 3", "end:");

    it("makes the text laid out exactly", () => {
        for (const after of [
            layout("file:a = 1", "file:x = 0", "file:b = 2", "written c1:Why b?", "file:c = 3", "end:"),
            layout("end:"),
            layout("other:q", "file:a = 1", "end:"),
            layout("written c1:Why b?", "file:b = 2", "file:a = 1", "end:"),
        ]) {
            expect(laidOver(before, after).doc).toBe(after.text);
        }
        expect(laidOver(layout("end:"), before).doc).toBe(before.text);
    });

    it("leaves a comment untouched where its block's lines change above and below it", () => {
        const after = layout("file:a = 1", "file:new", "file:new too", "file:b = 2", "written c1:Why b?", "file:c = 33", "end:");
        const made = laidOver(before, after);
        const comment = before.text.indexOf("Why b?");
        expect(touches(made.changes, comment, comment + "Why b?".length)).toBe(false);
        expect(made.doc.slice(made.changes.mapPos(comment), made.changes.mapPos(comment) + 6)).toBe("Why b?");
    });

    it("keeps a comment over the lines around it, where its block's diff and where it's laid out disagree", () => {
        // Its block's lines unchanged, but the comment laid out a line further down: the code moves, not the comment.
        const after = layout("file:a = 1", "file:b = 2", "file:c = 3", "written c1:Why b?", "end:");
        const made = laidOver(before, after);
        const comment = before.text.indexOf("Why b?");
        expect(made.doc).toBe(after.text);
        expect(touches(made.changes, comment, comment + "Why b?".length)).toBe(false);
    });

    it("keeps a line only as one of the same part's, what's said alike in another part put in afresh", () => {
        const doc = layout("one:same", "two:other", "end:");
        const after = layout("two:same", "two:other", "end:");
        const made = laidOver(doc, after);
        expect(made.doc).toBe(after.text);
        // `same` is replaced, though its text is the same: it's another part's now, ...
        expect(touches(made.changes, 0, 4)).toBe(false);
        // ... but what's alike between two lines kept is kept too, whose ever it is: nothing to change.
        expect(made.changes.empty).toBe(true);
    });

    it("changes a line replaced by one in its place by what differs within it, so a cursor on it keeps its column", () => {
        const doc = layout("head:── @51 question · edited ──", "end:");
        const after = layout("head:── @51 question · edited · new ──", "end:");
        const made = laidOver(doc, after);
        expect(made.doc).toBe(after.text);
        const cursor = doc.text.indexOf("question");
        expect(made.changes.mapPos(cursor)).toBe(cursor);
        expect(made.arrived).toEqual([{ from: 0, to: after.text.indexOf("\n") }]);
    });

    it("takes a part gone out, and puts one in where its tree puts it, a cursor in one gone landing on the next's start", () => {
        const doc = layout("item 1:one", "item 1:1", "item 2:two", "end:");
        const after = layout("item 2:two", "item 3:three", "end:");
        const made = laidOver(doc, after);
        expect(made.doc).toBe(after.text);
        expect(made.changes.mapPos(doc.text.indexOf("1\n"))).toBe(0);
        expect(made.arrived.map((each) => after.text.slice(each.from, each.to))).toEqual(["three"]);
    });

    it("changes each part's lines apart between two kept, so a cursor in a part gone lands where what replaced it is, not in a part changed beside it", () => {
        // A file marked reviewed: its drawer's summary says so, and a line of its own stands where the file was.
        const doc = layout("banner:━━ parser ━━", "summary:since · 1 flagged", "file:reader.py · created", "file:class Reader:", "reviewed:", "end:");
        const after = layout("banner:━━ parser ━━", "summary:since · 1 reviewed", "line:reader.py · reviewed", "reviewed:", "end:");
        const made = laidOver(doc, after);
        expect(made.doc).toBe(after.text);
        expect(after.text.slice(made.changes.mapPos(doc.text.indexOf("reader.py · created")))).toMatch(/^reader\.py · reviewed/);
        expect(after.text.slice(made.changes.mapPos(doc.text.indexOf("1 flagged")))).toMatch(/^1 reviewed/);
    });

    it("says what arrived but the operator's own words", () => {
        const after = layout("file:a = 1", "file:b = 2", "written c1:Why b?", "written c2:And c?", "file:c = 3", "end:");
        expect(laidOver(before, after).arrived).toEqual([]);
    });
});

describe("whose each line is, as the editor keeps it", () => {
    it("runs each part's lines together, from its first line's start to its last's end", () => {
        const laid = layout("a:one", "a:two", "b:three", "a:four", "end:");
        expect(runsOf(laid.text, laid.owners)).toEqual([
            { owner: "a", from: 0, to: 7 },
            { owner: "b", from: 8, to: 13 },
            { owner: "a", from: 14, to: 18 },
            { owner: "end", from: 19, to: 19 },
        ]);
    });

    it("carries the runs through typing, a comment's growing with what's typed at its end or its start", () => {
        const laid = layout("file:a = 1", "written c1:Why", "file:b = 2", "end:");
        let state = EditorState.create({ doc: laid.text, extensions: [owning] });
        state = state.update({ effects: owned.of(runsOf(laid.text, laid.owners)) }).state;
        const end = laid.text.indexOf("Why") + 3;
        state = state.update({ changes: { from: end, insert: "?\nAnd" } }).state;
        state = state.update({ changes: { from: laid.text.indexOf("Why"), insert: "So: " } }).state;
        expect(ownersOf(state.doc, state.field(owning))).toEqual(["file", "written c1", "written c1", "file", "end", ""]);
        expect(state.doc.line(2).text).toBe("So: Why?");
    });

    it("gives a line two runs hold, as a comment emptied and taken out, to the later", () => {
        const doc = Text.of(["x", "y"]);
        expect(ownersOf(doc, [{ owner: "written c1", from: 2, to: 2 }, { owner: "file", from: 2, to: 3 }])).toEqual(["", "file"]);
    });
});

describe("what arrived, flashing", () => {
    /** The lines marked arrived in `state`, by number, with when each arrived. */
    function marked(state: EditorState): [number, number][] {
        const found: [number, number][] = [];
        state.field(arriving).between(0, state.doc.length, (from, _to, mark) => {
            found.push([state.doc.lineAt(from).number, (mark.spec as { at: number }).at]);
        });
        return found;
    }

    /** Where line `number` of `state` starts and ends. */
    function line(state: EditorState, number: number) {
        const { from, to } = state.doc.line(number);
        return { from, to };
    }

    const start = EditorState.create({ doc: "a\nb\nc\nd", extensions: [arriving] });

    it("marks each line once, however often it arrives while it flashes, with when it first came", () => {
        let state = start.update({ effects: arrivedLines.of({ lines: [line(start, 1), line(start, 2)], at: 0 }) }).state;
        state = state.update({ effects: arrivedLines.of({ lines: [line(state, 2), line(state, 3)], at: 500 }) }).state;
        expect(marked(state)).toEqual([
            [1, 0],
            [2, 0],
            [3, 500],
        ]);
    });

    it("takes each mark away as its own flash ends, whatever arrived after it", () => {
        let state = start.update({ effects: arrivedLines.of({ lines: [line(start, 1)], at: 0 }) }).state;
        state = state.update({ effects: arrivedLines.of({ lines: [line(state, 3)], at: 1500 }) }).state;
        state = state.update({ effects: settled.of(100) }).state;
        expect(marked(state)).toEqual([[3, 1500]]);
        state = state.update({ effects: arrivedLines.of({ lines: [line(state, 1)], at: 2000 }) }).state;
        expect(marked(state)).toEqual([
            [1, 2000],
            [3, 1500],
        ]);
    });

    it("carries the marks with the text, and marks nothing where nothing arrived", () => {
        let state = start.update({ effects: arrivedLines.of({ lines: [], at: 0 }) }).state;
        expect(marked(state)).toEqual([]);
        state = state.update({ effects: arrivedLines.of({ lines: [line(state, 2)], at: 0 }) }).state;
        state = state.update({ changes: { from: 0, insert: "new\n" } }).state;
        expect(marked(state)).toEqual([[3, 0]]);
    });
});

describe("the review read as the page loads", () => {
    it("flashes nothing until it's laid out from all it's read, nor while what it read comes in, until a quiet second", () => {
        const reading: Reading = { since: null, last: 0, read: false };
        expect(readBy(reading, false, 0)).toBe(false);
        expect([100, 300, 900, 1800].map((now) => readBy(reading, true, now))).toEqual([false, false, false, false]);
        expect(readBy(reading, true, 2900)).toBe(true);
        expect(readBy(reading, true, 2950)).toBe(true);
    });

    it("is read five seconds after it's first laid out, however often it's laid out anew, as under agents at work", () => {
        const reading: Reading = { since: null, last: 0, read: false };
        const layouts = Array.from({ length: 30 }, (_, at) => 1000 + at * 200);
        const flashing = layouts.map((now) => readBy(reading, true, now));
        expect(flashing.indexOf(true)).toBe(25);
    });
});
