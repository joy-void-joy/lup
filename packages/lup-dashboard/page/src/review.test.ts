import { describe, expect, it } from "vitest";

import {
    EMPTY,
    answer,
    arrival,
    blockAt,
    calls,
    covered,
    foldAt,
    foldKey,
    fresh,
    groupAt,
    isLetter,
    laid,
    messages,
    opened,
    plain,
    pruned,
    quoted,
    regionAt,
    shownAt,
    stepped,
    steps,
    toggled,
    waited,
    whose,
    withWritten,
    written,
    type Around,
    type ChangedFile,
    type Comment,
    type Context,
    type Conversation,
    type Draft,
    type Head,
    type Item,
    type Written,
} from "./review";

const AT = "2026-10-17T12:00:00Z";

function from(session: string, agent: string | null = null): Conversation {
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
    reason: { reason: "message", ending: false, kind: "note", text: "I assumed UTF-8." },
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
        typing: false,
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

const NOTHING: Around = { contexts: new Map(), files: new Map() };

const header = (item: Item, parked: boolean) => `── #${item.number}${parked ? " · later" : ""} ──`;
const banner = (head: Head, parked: boolean) => {
    const party = "item" in head ? head.item.sender : head.conversation;
    return `━━ ${party.party === "conversation" ? party.session : "lup"}${parked ? " · later" : ""} ━━`;
};

/** What's written at a line, as a comment on an item: none where it's a message to an agent. */
function onItem(written: Written | undefined): Comment | undefined {
    return written === undefined || isLetter(written) ? undefined : written;
}

describe("laid", () => {
    it("folds an item marked read whole under its header, and nothing else", () => {
        const out = laid([QUESTION, NOTE], [], banner, header, { ...EMPTY, done: [52] }, NOTHING);
        const question = out.regions.find((each) => each.item.number === 51);
        const note = out.regions.find((each) => each.item.number === 52);
        expect(question!.folds.filter((each) => each.kind === "read")).toEqual([]);
        const [read] = note!.folds.filter((each) => each.kind === "read");
        expect(out.text.slice(read!.summary.from, read!.summary.to)).toBe("── #52 ──");
        expect(out.text.slice(read!.from, read!.to)).toBe("\nI assumed UTF-8.");
    });

    it("puts the group with the newest item first, each group's items in their order", () => {
        const later: Item = { ...QUESTION, number: 53, reason: { ...NOTE.reason } };
        const out = laid([QUESTION, NOTE, later], [], banner, header, EMPTY, NOTHING);
        expect(out.text.split("\n").filter((line) => line.startsWith("━━") || line.startsWith("──"))).toEqual([
            "━━ s1 ━━",
            "── #51 ──",
            "── #53 ──",
            "━━ s2 ━━",
            "── #52 ──",
        ]);
        const two = laid([QUESTION, NOTE], [], banner, header, EMPTY, NOTHING);
        expect(two.text.startsWith("━━ s2 ━━")).toBe(true);
    });

    it("lays each item under its header in its sender's group, the parked ones last, each comment under its line", () => {
        const draft: Draft = {
            comments: [
                { item: 51, quote: { text: "Use lark", start: 17, end: 25 }, text: "Yes." },
                { item: 51, quote: null, text: "On the whole: fine." },
                { item: 52, quote: null, text: "Noted." },
            ],
            letters: [],
            done: [],
            parked: [52],
        };
        const out = laid([QUESTION, NOTE], [], banner, header, draft, NOTHING);
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

    it("opens a comment on the line under the cursor, on the item from its header, or a message to its agent from its banner", () => {
        const out = laid([QUESTION, NOTE], [], banner, header, EMPTY, NOTHING);
        expect(opened(out, out.text.indexOf("Keep the cache"))).toEqual({
            item: 51,
            quote: { text: "2. Keep the cache", start: "Which parser?\n1. Use lark\n   lean: yes\n".length, end: "Which parser?\n1. Use lark\n   lean: yes\n2. Keep the cache".length },
            text: "",
        });
        expect(opened(out, out.text.indexOf("── #51"))).toEqual({ item: 51, quote: null, text: "" });
        expect(opened(out, 2)).toEqual({ to: from("s2"), text: "" });
    });

    it("quotes a passage within one item's own lines, and not across items", () => {
        const draft: Draft = { ...EMPTY, comments: [{ item: 51, quote: null, text: "x" }] };
        const out = laid([QUESTION, NOTE], [], banner, header, draft, NOTHING);
        const lark = out.text.indexOf("lark");
        expect(quoted(out, lark, lark + 4)).toEqual({
            item: 51,
            quote: { text: "lark", start: "Which parser?\n1. Use ".length, end: "Which parser?\n1. Use lark".length },
            text: "",
        });
        expect(quoted(out, lark, out.text.indexOf("UTF-8"))).toBeUndefined();
        expect(blockAt(out, out.text.indexOf("x\n"))?.comment).toBe(0);
        expect(regionAt(out, out.text.indexOf("UTF-8"))?.item.number).toBe(52);
    });

    it("shows an approval's diff without git's colours", () => {
        expect(plain("\u001b[32m+added\u001b[m")).toBe("+added");
    });
});

/** Twelve lines, `l1` to `l12`, the seventh `seventh` in place of `l7`. */
function twelve(seventh = "l7"): string {
    return Array.from({ length: 12 }, (_, at) => (at === 6 ? seventh : `l${at + 1}`)).join("\n") + "\n";
}

const CHANGED: ChangedFile = { path: "a.py", before: { kind: "text", text: twelve() }, after: { kind: "text", text: twelve("L7") } };

describe("what folds under an item", () => {
    const around: Around = {
        contexts: new Map([
            [51, { shown: CONTEXT }],
            [54, { refused: "item 54 was made by no agent's call" }],
        ]),
        files: new Map([[54, { shown: [CHANGED] }]]),
    };

    it("says each step of a context in a line, its words' own lines kept, a run of calls in one, the call that made the item marked", () => {
        expect(steps(CONTEXT)).toEqual([
            { kind: "you", text: "you: Build the reader." },
            { kind: "you", text: "     Ask me first." },
            { kind: "agent", text: "Reading the records." },
            { kind: "calls", text: "· called Bash ×2, Read" },
            { kind: "anchor", text: "→ called mcp__lup__ask · this item" },
            { kind: "calls", text: "· called Grep" },
        ]);
        expect(calls(["Read", "Read", "Bash", "Read"])).toBe("· called Read ×2, Bash, Read");
    });

    it("lays an approval's files, then the item's context, under its own text, a file's unchanged runs and the context folding", () => {
        const out = laid([QUESTION, APPROVAL], [], banner, header, EMPTY, around);
        expect(out.text).toBe(
            "━━ lup ━━\n── #54 ──\nApprove?\n a.py | 2 +-\n" +
                "a.py · changed · +1 −1\n" +
                "3 unchanged lines, 1–3\nl1\nl2\nl3\nl4\nl5\nl6\nl7\nL7\nl8\nl9\nl10\n" +
                "2 unchanged lines, 11–12\nl11\nl12\n" +
                "no context: item 54 was made by no agent's call\n\n" +
                "━━ s1 ━━\n── #51 ──\nWhich parser?\n1. Use lark\n   lean: yes\n2. Keep the cache\n   lean: no\n" +
                "context · 7 steps, from your words 9m before this item\n" +
                "you: Build the reader.\n     Ask me first.\nReading the records.\n" +
                "· called Bash ×2, Read\n→ called mcp__lup__ask · this item\n· called Grep\n\n",
        );
        const [approval, question] = out.regions;
        const shown = (from: number, to: number) => out.text.slice(from, to);

        const [top, bottom] = approval!.folds;
        expect(approval!.folds).toHaveLength(2);
        expect(top).toMatchObject({ item: 54, kind: "code", name: "a.py:0" });
        expect(shown(top!.summary.from, top!.summary.to)).toBe("3 unchanged lines, 1–3");
        expect(top!.from).toBe(top!.summary.to);
        expect(shown(top!.from, top!.to)).toBe("\nl1\nl2\nl3");
        expect(shown(bottom!.from, bottom!.to)).toBe("\nl11\nl12");
        expect(foldKey(top!)).not.toBe(foldKey(bottom!));
        expect(approval!.asides.map((each) => each.kind)).toEqual(["summary", "summary", "refused"]);
        expect(approval!.code.map((each) => [shown(each.from, each.to), each.row?.change ?? "header"])).toEqual([
            ["a.py · changed · +1 −1", "header"],
            ...["l1", "l2", "l3", "l4", "l5", "l6"].map((each) => [each, "same"]),
            ["l7", "removed"],
            ["L7", "added"],
            ...["l8", "l9", "l10", "l11", "l12"].map((each) => [each, "same"]),
        ]);

        const [context] = question!.folds;
        expect(context).toMatchObject({ item: 51, kind: "context" });
        expect(shown(context!.summary.from, context!.summary.to)).toBe(
            "context · 7 steps, from your words 9m before this item",
        );
        expect(shown(context!.from, context!.to)).toBe(
            "\nyou: Build the reader.\n     Ask me first.\nReading the records.\n" +
                "· called Bash ×2, Read\n→ called mcp__lup__ask · this item\n· called Grep",
        );
        expect(question!.asides.find((each) => each.kind === "anchor")).toMatchObject({
            from: out.text.indexOf("→ called"),
        });
    });

    it("folds an automatic file whole under its header, and keeps where each line that matters starts, landing on the first", () => {
        const read: Around = {
            contexts: new Map(),
            files: new Map([
                [
                    54,
                    {
                        shown: [
                            {
                                path: "t.py",
                                before: { kind: "text", text: "a\nb\n" },
                                after: { kind: "text", text: "a\nB\n" },
                                reading: { role: "test", asks: [], findings: [] },
                            },
                            {
                                path: "n.py",
                                before: null,
                                after: { kind: "text", text: "x = 1\nimport re\n" },
                                reading: {
                                    role: "production",
                                    asks: [{ name: "new-file", taken: "flagged", side: "after" }],
                                    findings: [{ rule: "regex", message: "a pattern", steer: "", start: 2, end: 2, taken: "told" }],
                                },
                            },
                        ],
                    },
                ],
            ]),
        };
        const out = laid([APPROVAL, NOTE], [], banner, header, EMPTY, read);
        const [approval, note] = out.regions;
        const shown = (from: number, to: number) => out.text.slice(from, to);
        const [file] = approval!.folds.filter((each) => each.kind === "file");
        expect(file).toMatchObject({ item: 54, kind: "file", name: "t.py" });
        expect(shown(file!.summary.from, file!.summary.to)).toBe("t.py · changed · +1 −1 · automatic");
        expect(shown(file!.from, file!.to)).toBe("\na\nb\nB");
        expect(approval!.stops.map((each) => shown(each, out.text.indexOf("\n", each)))).toEqual([
            "n.py · created · 2 lines · new file · told: regex",
            "import re",
        ]);
        expect(approval!.code.find((each) => each.row?.text === "import re")?.matter).toEqual({
            row: 1,
            notes: [{ taken: "told", said: "regex: a pattern" }],
        });
        const commented = laid(
            [APPROVAL],
            [],
            banner,
            header,
            { ...EMPTY, comments: [{ item: 54, quote: { text: "t.py", start: 15, end: 49 }, text: "Why?" }] },
            read,
        );
        const [kept] = commented.regions[0]!.folds.filter((each) => each.kind === "file");
        expect(commented.text.slice(kept!.summary.to, kept!.from)).toBe("\nWhy?");
        expect(commented.text.slice(kept!.from, kept!.to)).toBe("\na\nb\nB");
        expect(arrival(approval!)).toBe(approval!.stops[0]);
        expect(arrival(note!)).toBe(note!.header.from);
        const done = laid([APPROVAL], [], banner, header, { ...EMPTY, done: [54] }, read);
        expect(arrival(done.regions[0]!)).toBe(done.regions[0]!.header.from);
        expect(stepped([10, 20, 30], 20, true)).toBe(30);
        expect(stepped([10, 20, 30], 20, false)).toBe(10);
        expect(stepped([10, 20, 30], 30, true)).toBeUndefined();
        expect(stepped([10, 20, 30], 5, false)).toBeUndefined();
    });

    it("finds the fold the cursor is on, from its summary line to its last, and opens no comment on a line that isn't the item's own", () => {
        const out = laid([QUESTION, APPROVAL], [], banner, header, EMPTY, around);
        expect(foldAt(out, out.text.indexOf("context ·"))?.kind).toBe("context");
        expect(foldAt(out, out.text.indexOf("Ask me first"))?.kind).toBe("context");
        expect(foldAt(out, out.text.indexOf("l2\n"))?.kind).toBe("code");
        expect(foldAt(out, out.text.indexOf("L7"))).toBeUndefined();
        expect(foldAt(out, out.text.indexOf("Keep the cache"))).toBeUndefined();
        expect(foldAt(out, out.text.indexOf("no context"))).toBeUndefined();
        for (const line of ["context ·", "→ called", "3 unchanged", "no context"]) {
            expect(opened(out, out.text.indexOf(line))).toBeUndefined();
        }
        expect(onItem(opened(out, out.text.indexOf("lean: no")))?.item).toBe(51);
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
            const out = laid([QUESTION], [], banner, header, EMPTY, { contexts: new Map([[51, { shown: context }]]), files: new Map() });
            const [fold] = out.regions[0]!.folds;
            return out.text.slice(fold!.summary.from, fold!.summary.to);
        };
        expect(summary(agents)).toBe("context · 2 steps, from 2h before this item");
        expect(summary(untimed)).toBe("context · 1 step");
    });
});

describe("comments on a changed file's lines", () => {
    const HELD: Item = {
        number: 55,
        reason: { reason: "held", text: "Let the change to 2 files land?", summary: "a.py: asks", worktree: "/w", key: "k" },
        sender: from("s1"),
        recipient: { party: "operator" },
        made: AT,
        state: { state: "waiting" },
    };
    const CREATED: ChangedFile = { path: "b.md", before: null, after: { kind: "text", text: "# B\n\nNew.\n" } };
    const around: Around = { contexts: new Map(), files: new Map([[55, { shown: [CHANGED, CREATED] }]]) };
    const out = laid([HELD], [], banner, header, EMPTY, around);
    const at = (line: string) => out.text.indexOf(`\n${line}\n`) + 1;

    it("quotes a line under its file's path and number, marked as a diff marks it, and shows the comment under it", () => {
        const added = onItem(opened(out, at("L7")));
        expect(added?.quote?.text).toBe("a.py:7\n+L7");
        expect(onItem(opened(out, at("l7")))?.quote?.text).toBe("a.py:7, as it was before the change\n-l7");
        expect(onItem(opened(out, at("l8")))?.quote?.text).toBe("a.py:8\n l8");
        expect(onItem(opened(out, at("a.py · changed · +1 −1")))?.quote?.text).toBe("a.py");
        expect(onItem(opened(out, at("b.md · created · 3 lines")))?.quote?.text).toBe("b.md");

        const commented = laid([HELD], [], banner, header, { ...EMPTY, comments: [{ ...added!, text: "Why capitals?" }] }, around);
        expect(commented.text).toContain("\nL7\nWhy capitals?\nl8\n");
        const [region] = commented.regions;
        expect(commented.text.slice(shownAt(region!, added!.quote!.start), shownAt(region!, added!.quote!.end))).toBe("L7");
    });

    it("opens a comment on an empty line of a file, not on the item whole", () => {
        const empty = out.text.indexOf("# B\n\n") + "# B\n".length;
        expect(onItem(opened(out, empty))?.quote?.text).toBe("b.md:2\n+");
    });

    it("quotes a passage across a file's lines, and across files, each under its path and the span of its lines", () => {
        const from = at("l6");
        expect(onItem(quoted(out, from, at("l8") - 1))?.quote?.text).toBe("a.py:6-7\n l6\n-l7\n+L7");
        expect(onItem(quoted(out, at("l12") + 1, at("New.") + 3))?.quote?.text).toBe("a.py:12\n 12\nb.md:1-3\n+# B\n+\n+New");
    });

    it("says an item's comments as one answer, each under what it quotes", () => {
        const comments: Comment[] = [
            { item: 55, quote: null, text: "Otherwise fine." },
            { item: 55, quote: { text: "a.py:7\n+L7", start: 40, end: 42 }, text: "Why capitals?" },
            { item: 55, quote: { text: "a.py", start: 20, end: 24 }, text: " " },
        ];
        expect(answer(comments)).toBe("> a.py:7\n> +L7\n\nWhy capitals?\n\nOtherwise fine.");
    });
});

describe("every agent's group, and the messages under its banner", () => {
    const S3 = from("s3");
    const S4 = from("s4");

    it("gives each agent running a group, empty after those with items in the agents' order, and the parked ones last", () => {
        const out = laid([QUESTION, NOTE], [S3, from("s2"), S4, from("s1", "a1")], banner, header, { ...EMPTY, parked: [52] }, NOTHING);
        expect(out.text).toBe(
            "━━ s1 ━━\n── #51 ──\nWhich parser?\n1. Use lark\n   lean: yes\n2. Keep the cache\n   lean: no\n\n" +
                "━━ s3 ━━\n━━ s2 ━━\n━━ s4 ━━\n" +
                "━━ s2 · later ━━\n── #52 · later ──\nI assumed UTF-8.\n\n",
        );
        expect(out.groups.map((each) => [each.conversation?.session ?? null, each.later])).toEqual([
            ["s1", false],
            ["s3", false],
            ["s2", false],
            ["s4", false],
            ["s2", true],
        ]);
        const approvals = laid([APPROVAL], [], banner, header, EMPTY, NOTHING);
        expect(approvals.groups.map((each) => each.conversation)).toEqual([null]);
    });

    it("writes each message under its agent's banner, after the comments in what's written, an empty group's set off by a blank line", () => {
        const S9 = from("s9");
        const draft: Draft = {
            ...EMPTY,
            comments: [{ item: 52, quote: null, text: "Noted." }],
            letters: [
                { to: S3, text: "Look at the cache too." },
                { to: from("s2"), text: "And rename it." },
                { to: S9, text: "Still there?" },
            ],
        };
        const out = laid([NOTE], [S3, S4], banner, header, draft, NOTHING);
        expect(out.text).toBe(
            "━━ s2 ━━\nAnd rename it.\n── #52 ──\nNoted.\nI assumed UTF-8.\n\n" +
                "━━ s3 ━━\nLook at the cache too.\n\n━━ s4 ━━\n━━ s9 ━━\nStill there?\n\n",
        );
        const shown = (block: { from: number; to: number }) => out.text.slice(block.from, block.to);
        expect(out.groups.map((each) => each.blocks.map((block) => [block.comment, shown(block)]))).toEqual([
            [[2, "And rename it."]],
            [[1, "Look at the cache too."]],
            [],
            [[3, "Still there?"]],
        ]);
        expect(blockAt(out, out.text.indexOf("Still there?"))?.comment).toBe(3);
        expect(written(draft).map((each) => each.text)).toEqual(["Noted.", "Look at the cache too.", "And rename it.", "Still there?"]);
    });

    it("opens a message to a group's agent on its banner, a parked group's among them, but none to lup's approvals", () => {
        const draft: Draft = { ...EMPTY, parked: [51], letters: [{ to: S3, text: "Hi." }] };
        const out = laid([QUESTION, APPROVAL], [S3], banner, header, draft, NOTHING);
        const at = (line: string) => out.text.indexOf(line);
        expect(opened(out, at("━━ s3"))).toEqual({ to: S3, text: "" });
        expect(opened(out, at("Hi."))).toEqual({ to: S3, text: "" });
        expect(opened(out, at("━━ s1 · later"))).toEqual({ to: from("s1", "a1"), text: "" });
        expect(opened(out, at("━━ lup"))).toBeUndefined();
        expect(quoted(out, at("━━ s3"), at("━━ s3") + 4)).toEqual({ to: S3, text: "" });
        expect(quoted(out, at("━━ s1 · later"), at("Which parser?") + 5)).toBeUndefined();
        expect(regionAt(out, at("━━ s3"))).toBeUndefined();
        expect(regionAt(out, at("── #51"))?.item.number).toBe(51);
        expect(regionAt(out, at("Approve?"))?.item.number).toBe(54);
        expect(groupAt(out, at("Hi."))?.conversation).toEqual(S3);
        expect(groupAt(out, at("Approve?"))).toBeUndefined();
    });

    it("keeps what the editor holds in the draft's two lists, and sends only the messages that say something", () => {
        const letter = { to: S3, text: "Hi." };
        const comment = { item: 51, quote: null, text: "Yes." };
        const draft = withWritten(EMPTY, [letter, comment, { to: S4, text: " " }]);
        expect(draft.comments).toEqual([comment]);
        expect(draft.letters).toEqual([letter, { to: S4, text: " " }]);
        expect(written(draft).indexOf(letter)).toBe(1);
        expect(messages(draft)).toEqual([letter]);
        expect(pruned(draft).letters).toEqual([letter]);
        expect(isLetter(letter)).toBe(true);
        expect(isLetter(comment)).toBe(false);
        expect(whose(from("s1", "a1"))).not.toBe(whose(from("s1")));
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

describe("waited and fresh", () => {
    it("says how long an item has waited, to the minute", () => {
        const now = new Date("2026-10-17T14:00:30Z");
        expect(waited("2026-10-17T14:00:00Z", now)).toBe("just in");
        expect(waited("2026-10-17T13:55:00Z", now)).toBe("waiting 5m");
        expect(waited("2026-10-15T14:00:00Z", now)).toBe("waiting 2d");
    });

    it("marks what came after the operator last settled an item, and nothing before they first did", () => {
        expect(fresh(QUESTION, "2026-10-17T11:00:00Z")).toBe(true);
        expect(fresh(QUESTION, "2026-10-17T12:30:00Z")).toBe(false);
        expect(fresh(QUESTION, null)).toBe(false);
    });
});
