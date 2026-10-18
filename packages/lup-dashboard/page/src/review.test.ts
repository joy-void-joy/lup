import { describe, expect, it } from "vitest";

import {
    EMPTY,
    blockAt,
    covered,
    laid,
    opened,
    plain,
    pruned,
    quoted,
    regionAt,
    shownAt,
    toggled,
    type Draft,
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
    it("lays each item under its header, the parked ones last, each comment under its line", () => {
        const draft: Draft = {
            comments: [
                { item: 51, quote: { text: "Use lark", start: 17, end: 25 }, text: "Yes." },
                { item: 51, quote: null, text: "On the whole: fine." },
                { item: 52, quote: null, text: "Noted." },
            ],
            done: [],
            parked: [52],
        };
        const out = laid([QUESTION, NOTE], header, draft, new Map());
        expect(out.text).toBe(
            "── #51 ──\nOn the whole: fine.\nWhich parser?\n1. Use lark\nYes.\n   lean: yes\n2. Keep the cache\n   lean: no\n\n" +
                "── #52 · later ──\nNoted.\nI assumed UTF-8.\n\n",
        );
        const [question] = out.regions;
        expect(question!.blocks.map((each) => out.text.slice(each.from, each.to))).toEqual([
            "On the whole: fine.",
            "Yes.",
        ]);
        expect(question!.blocks.map((each) => each.comment)).toEqual([1, 0]);
        const lark = out.text.indexOf("Use lark");
        expect(shownAt(question!, 17)).toBe(lark);
    });

    it("opens a comment on the line under the cursor, or on the item from its header", () => {
        const out = laid([QUESTION, NOTE], header, EMPTY, new Map());
        expect(opened(out, out.text.indexOf("Keep the cache"))).toEqual({
            item: 51,
            quote: { text: "2. Keep the cache", start: "Which parser?\n1. Use lark\n   lean: yes\n".length, end: "Which parser?\n1. Use lark\n   lean: yes\n2. Keep the cache".length },
            text: "",
        });
        expect(opened(out, 2)).toEqual({ item: 51, quote: null, text: "" });
    });

    it("quotes a passage within one item's own lines, and not across items", () => {
        const draft: Draft = { comments: [{ item: 51, quote: null, text: "x" }], done: [], parked: [] };
        const out = laid([QUESTION, NOTE], header, draft, new Map());
        const lark = out.text.indexOf("lark");
        expect(quoted(out, lark, lark + 4)).toEqual({
            item: 51,
            quote: { text: "lark", start: "Which parser?\n1. Use ".length, end: "Which parser?\n1. Use lark".length },
            text: "",
        });
        expect(quoted(out, lark, out.text.indexOf("UTF-8"))).toBeUndefined();
        expect(blockAt(out, out.text.indexOf("x\n"))?.comment).toBe(0);
        expect(regionAt(out.regions, out.text.indexOf("UTF-8"))?.item.number).toBe(52);
    });

    it("shows an approval's diff without git's colours", () => {
        expect(plain("\u001b[32m+added\u001b[m")).toBe("+added");
    });
});

describe("the draft", () => {
    it("toggles done and parked, says what it covers, and drops comments that say nothing", () => {
        let draft = toggled(EMPTY, "done", 52);
        draft = { ...draft, comments: [{ item: 53, text: "x" }, { item: 54, text: "  " }] };
        expect(covered(draft)).toEqual([52, 53]);
        expect(covered(toggled(draft, "parked", 53))).toEqual([52]);
        expect(pruned(draft).comments).toEqual([{ item: 53, text: "x" }]);
        expect(toggled(toggled(EMPTY, "done", 52), "done", 52).done).toEqual([]);
    });
});
