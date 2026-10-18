import { describe, expect, it } from "vitest";

import {
    EMPTY,
    blockAt,
    calls,
    covered,
    foldAt,
    laid,
    opened,
    plain,
    pruned,
    quoted,
    regionAt,
    shownAt,
    steps,
    toggled,
    type Around,
    type Context,
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

const APPROVAL: Item = {
    number: 54,
    reason: {
        reason: "approval",
        text: "Approve?",
        summary: " a.py | 2 +-",
        repository: "/r/.git",
        fingerprint: "f",
    },
    sender: { party: "operator" },
    recipient: { party: "operator" },
    made: AT,
    state: { state: "waiting" },
};

const CONTEXT: Context = {
    kind: "inbox-context",
    number: 51,
    anchor: 5,
    entries: [
        { kind: "said", by: "operator", text: "Build the reader.\n\nAsk me first.", at: "2026-10-17T11:51:00Z" },
        { kind: "said", by: "agent", text: "Reading the records." },
        { kind: "called", tool: "Bash" },
        { kind: "called", tool: "Bash" },
        { kind: "called", tool: "Read" },
        { kind: "called", tool: "mcp__lup__ask", id: "call-51" },
        { kind: "called", tool: "Grep" },
    ],
};

const NOTHING: Around = { contexts: new Map(), diffs: new Map() };

const header = (item: Item, parked: boolean) => `── #${item.number}${parked ? " · later" : ""} ──`;
const banner = (item: Item, parked: boolean) => `━━ ${item.sender.party === "conversation" ? item.sender.session : "lup"}${parked ? " · later" : ""} ━━`;

describe("laid", () => {
    it("lays each item under its header in its sender's group, the parked ones last, each comment under its line", () => {
        const draft: Draft = {
            comments: [
                { item: 51, quote: { text: "Use lark", start: 17, end: 25 }, text: "Yes." },
                { item: 51, quote: null, text: "On the whole: fine." },
                { item: 52, quote: null, text: "Noted." },
            ],
            done: [],
            parked: [52],
        };
        const out = laid([QUESTION, NOTE], banner, header, draft, NOTHING);
        expect(out.text).toBe(
            "━━ s1 ━━\n── #51 ──\nOn the whole: fine.\nWhich parser?\n1. Use lark\nYes.\n   lean: yes\n2. Keep the cache\n   lean: no\n\n" +
                "━━ s2 · later ━━\n── #52 · later ──\nNoted.\nI assumed UTF-8.\n\n",
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
        const out = laid([QUESTION, NOTE], banner, header, EMPTY, NOTHING);
        expect(opened(out, out.text.indexOf("Keep the cache"))).toEqual({
            item: 51,
            quote: { text: "2. Keep the cache", start: "Which parser?\n1. Use lark\n   lean: yes\n".length, end: "Which parser?\n1. Use lark\n   lean: yes\n2. Keep the cache".length },
            text: "",
        });
        expect(opened(out, out.text.indexOf("── #51"))).toEqual({ item: 51, quote: null, text: "" });
        expect(opened(out, 2)).toBeUndefined();
    });

    it("quotes a passage within one item's own lines, and not across items", () => {
        const draft: Draft = { comments: [{ item: 51, quote: null, text: "x" }], done: [], parked: [] };
        const out = laid([QUESTION, NOTE], banner, header, draft, NOTHING);
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

describe("what folds under an item", () => {
    const around: Around = {
        contexts: new Map([
            [51, { shown: CONTEXT }],
            [54, { refused: "item 54 was made by no agent's call" }],
        ]),
        diffs: new Map([[54, { shown: "\u001b[1mdiff --git a/a.py b/a.py\u001b[m\n-old\n+new\n" }]]),
    };

    it("says each step of a context in a line, its words' own lines kept, a run of calls in one, the call that made the item marked", () => {
        expect(steps(CONTEXT)).toEqual([
            { kind: "you", text: "you: Build the reader." },
            { kind: "you", text: "     Ask me first." },
            { kind: "agent", text: "agent: Reading the records." },
            { kind: "calls", text: "· called Bash ×2, Read" },
            { kind: "anchor", text: "→ called mcp__lup__ask · this item" },
            { kind: "calls", text: "· called Grep" },
        ]);
        expect(calls(["Read", "Read", "Bash", "Read"])).toBe("· called Read ×2, Bash, Read");
    });

    it("lays an approval's diff, then the item's context, under its own text, each folding under its summary line", () => {
        const out = laid([QUESTION, APPROVAL], banner, header, EMPTY, around);
        expect(out.text).toBe(
            "━━ lup ━━\n── #54 ──\nApprove?\n a.py | 2 +-\n" +
                "whole diff · 3 lines\ndiff --git a/a.py b/a.py\n-old\n+new\n" +
                "no context: item 54 was made by no agent's call\n\n" +
                "━━ s1 ━━\n── #51 ──\nWhich parser?\n1. Use lark\n   lean: yes\n2. Keep the cache\n   lean: no\n" +
                "context · 7 steps, from your words 9m before this item\n" +
                "you: Build the reader.\n     Ask me first.\nagent: Reading the records.\n" +
                "· called Bash ×2, Read\n→ called mcp__lup__ask · this item\n· called Grep\n\n",
        );
        const [approval, question] = out.regions;
        const shown = (from: number, to: number) => out.text.slice(from, to);

        const [diff] = approval!.folds;
        expect(approval!.folds).toHaveLength(1);
        expect(diff!.kind).toBe("diff");
        expect(shown(diff!.summary.from, diff!.summary.to)).toBe("whole diff · 3 lines");
        expect(diff!.from).toBe(diff!.summary.to);
        expect(shown(diff!.from, diff!.to)).toBe("\ndiff --git a/a.py b/a.py\n-old\n+new");
        expect(approval!.asides.map((each) => each.kind)).toEqual(["summary", "diff", "diff", "diff", "refused"]);

        const [context] = question!.folds;
        expect(context).toMatchObject({ item: 51, kind: "context" });
        expect(shown(context!.summary.from, context!.summary.to)).toBe(
            "context · 7 steps, from your words 9m before this item",
        );
        expect(shown(context!.from, context!.to)).toBe(
            "\nyou: Build the reader.\n     Ask me first.\nagent: Reading the records.\n" +
                "· called Bash ×2, Read\n→ called mcp__lup__ask · this item\n· called Grep",
        );
        expect(question!.asides.find((each) => each.kind === "anchor")).toMatchObject({
            from: out.text.indexOf("→ called"),
        });
    });

    it("finds the fold the cursor is on, from its summary line to its last, and opens no comment on a line that isn't the item's own", () => {
        const out = laid([QUESTION, APPROVAL], banner, header, EMPTY, around);
        expect(foldAt(out, out.text.indexOf("context ·"))?.kind).toBe("context");
        expect(foldAt(out, out.text.indexOf("Ask me first"))?.kind).toBe("context");
        expect(foldAt(out, out.text.indexOf("+new"))?.kind).toBe("diff");
        expect(foldAt(out, out.text.indexOf("Keep the cache"))).toBeUndefined();
        expect(foldAt(out, out.text.indexOf("no context"))).toBeUndefined();
        for (const line of ["context ·", "→ called", "-old", "no context"]) {
            expect(opened(out, out.text.indexOf(line))).toBeUndefined();
        }
        expect(opened(out, out.text.indexOf("lean: no"))?.item).toBe(51);
    });

    it("says where a context starts by its first step, and how long before the item", () => {
        const agents: Context = {
            ...CONTEXT,
            anchor: 1,
            entries: [
                { kind: "said", by: "agent", text: "Starting.", at: "2026-10-17T10:00:00Z" },
                { kind: "called", tool: "report", id: "call-51" },
            ],
        };
        const untimed: Context = { ...agents, entries: [{ kind: "called", tool: "report", id: "call-51" }], anchor: 0 };
        const summary = (context: Context) => {
            const out = laid([QUESTION], banner, header, EMPTY, { contexts: new Map([[51, { shown: context }]]), diffs: new Map() });
            const [fold] = out.regions[0]!.folds;
            return out.text.slice(fold!.summary.from, fold!.summary.to);
        };
        expect(summary(agents)).toBe("context · 2 steps, from 2h before this item");
        expect(summary(untimed)).toBe("context · 1 step");
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
