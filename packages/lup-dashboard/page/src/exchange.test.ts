import { describe, expect, it } from "vitest";

import { citedOn, editedOf, markerEnd, outdated, passageOf, unfound, type Citation } from "./exchange";
import type { components } from "./generated/api";

type Item = components["schemas"]["Item"];

const AT = "2026-10-17T12:00:00Z";

function note(text: string, fields: Partial<Item> = {}): Item {
    return {
        number: 7,
        reason: { reason: "message", passages: [], answers: [], ending: true, kind: "note", text },
        sender: { party: "conversation", repository: "/r/.git", runtime: "claude", session: "s1", agent: null },
        recipient: { party: "operator" },
        replies: [],
        citations: [],
        edits: [],
        quiet: false,
        made: AT,
        state: { state: "waiting" },
        rank: { name: "news", order: 1, notifies: false },
        ...fields,
    };
}

const FOUND: Citation = {
    said: "@5.1[split … out]",
    start: 3,
    end: 20,
    item: 5,
    part: 1,
    words: "split … out",
    found: { part: { item: 5, part: 1 }, start: 0, end: 21, text: "Split the reader\nout." },
    candidates: [],
};

describe("a citation", () => {
    it("shows its id alone where it found its passage, which unfolds under its line whole, after who wrote it", () => {
        expect(markerEnd(FOUND)).toBe(7);
        expect(markerEnd({ ...FOUND, said: "@5.1", end: 7, words: null })).toBe(7);
        expect(passageOf(FOUND).map((each) => each.text)).toEqual(["you, @5.1: Split the reader", "           out."]);
        expect(citedOn(note("One.\nAs @5.1[split … out] said.", { citations: [{ ...FOUND, start: 8, end: 25 }] }), ["One.", "As @5.1[split … out] said."])).toEqual([
            { line: 1, citation: { ...FOUND, start: 8, end: 25 } },
        ]);
    });

    it("says why one that found no passage is marked: nothing reads it, or the places it reads", () => {
        const place = { part: { item: 5, part: 2 }, start: 0, end: 5, text: "Split" };
        expect(unfound({ ...FOUND, found: null })).toBe("not found: no words of yours to this agent read it");
        expect(unfound({ ...FOUND, found: null, candidates: [place, place] })).toBe("not found: it reads 2 places, in @5.2");
    });
});

describe("an edit", () => {
    it("shows each line it took away and put in since the item was sent, and which of its lines it changed", () => {
        const edited = note("One.\nTwo, mended.\nThree.", {
            made: AT,
            edits: [
                { at: "2026-10-17T12:01:00Z", before: "One.\nTwo.\nThree." },
                { at: "2026-10-17T12:03:00Z", before: "One.\nTwo, half mended.\nThree." },
            ],
        });
        const shown = editedOf(edited, (at) => at.slice(11, 16));
        expect(shown?.summary).toBe("edited 12:03 after it was sent, 2 times · 1 line changed");
        expect(shown?.rows.map((each) => [each.kind, each.text])).toEqual([
            ["was", "− Two."],
            ["now", "+ Two, mended."],
        ]);
        expect(shown?.changed).toEqual([1]);
        expect(editedOf(note("Never edited."), (at) => at)).toBeNull();
    });

    it("leaves a comment on a question's decision as it is where only the question's text changed", () => {
        const asked: Item = {
            ...note(""),
            reason: { reason: "question", text: "Which, now?", decisions: [{ text: "Use lark", lean: "yes" }] },
            edits: [{ at: AT, before: "Which?" }],
        };
        expect(outdated(asked, { text: "1. Use lark", start: 12, end: 23 })).toBe(false);
        expect(outdated(asked, { text: "Which?", start: 0, end: 6 })).toBe(true);
    });
});
