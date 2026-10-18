import { describe, expect, it } from "vitest";

import {
    EMPTY,
    covered,
    decisionAt,
    laid,
    plain,
    quoted,
    regionAt,
    ruled,
    toggled,
    type Item,
} from "./review";

const AT = "2026-10-17T12:00:00Z";

function from(session: string, agent: string | null = null): Item["sender"] {
    return { party: "conversation", repository: "/r/.git", runtime: "claude", session, agent };
}

const QUESTION: Item = {
    number: 51,
    reason: {
        reason: "question",
        text: "Which parser?",
        decisions: [
            { text: "Use lark", lean: "yes" },
            { text: "Keep the cache", lean: "no" },
        ],
    },
    sender: from("s1", "a1"),
    recipient: { party: "operator" },
    made: AT,
    state: { state: "waiting" },
};

const NOTE: Item = {
    number: 52,
    reason: { reason: "message", kind: "note", text: "I assumed UTF-8." },
    sender: from("s2"),
    recipient: { party: "operator" },
    made: AT,
    state: { state: "waiting" },
};

const header = (item: Item, parked: boolean) => `── #${item.number}${parked ? " · later" : ""} ──`;

describe("laid", () => {
    it("lays each item under its header, the parked ones last", () => {
        const out = laid([QUESTION, NOTE], header, [51], new Map());
        expect(out.text).toBe(
            "── #52 ──\nI assumed UTF-8.\n\n" +
                "── #51 · later ──\nWhich parser?\n1. Use lark\n   lean: yes\n2. Keep the cache\n   lean: no\n\n",
        );
        const [note, question] = out.regions;
        expect(out.text.slice(note!.body.from, note!.body.to)).toBe("I assumed UTF-8.");
        expect(question!.decisions.map((each) => out.text.slice(each.from, each.to))).toEqual([
            "1. Use lark",
            "2. Keep the cache",
        ]);
    });

    it("finds the item and decision at a position, and a passage within one item", () => {
        const out = laid([QUESTION, NOTE], header, [], new Map());
        const lean = out.text.indexOf("lean: no");
        const region = regionAt(out.regions, lean);
        expect(region?.item.number).toBe(51);
        expect(decisionAt(region!, lean)?.number).toBe(2);
        const lark = out.text.indexOf("lark");
        expect(quoted(out, lark, lark + 4)).toEqual({
            item: 51,
            quote: { text: "lark", start: "Which parser?\n1. Use ".length, end: "Which parser?\n1. Use lark".length },
        });
        expect(quoted(out, lark, out.text.indexOf("UTF-8"))).toBeUndefined();
    });

    it("shows an approval's diff without git's colours", () => {
        expect(plain("\u001b[32m+added\u001b[m")).toBe("+added");
    });
});

describe("the draft", () => {
    it("toggles done and parked, gives and takes back verdicts, and says what it covers", () => {
        let draft = toggled(EMPTY, "done", 52);
        draft = ruled(draft, 51, 1, "leaning");
        draft = ruled(draft, 51, 1, "undecided");
        expect(draft.verdicts).toEqual([{ item: 51, decision: 1, verdict: "undecided" }]);
        expect(ruled(draft, 51, 1, "undecided").verdicts).toEqual([]);
        draft = { ...draft, comments: [{ item: 53, text: "x" }, { text: "on the whole" }] };
        expect(covered(draft)).toEqual([51, 52, 53]);
        expect(covered(toggled(draft, "parked", 53))).toEqual([51, 52]);
        expect(toggled(toggled(EMPTY, "done", 52), "done", 52).done).toEqual([]);
    });
});
