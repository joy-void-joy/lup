import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import {
    RUN,
    UNEXCHANGED,
    UNSAID,
    aboutAt,
    blockAt,
    detailed,
    given,
    laid,
    opened,
    quoted,
    shifted,
    type Beside,
    type Detail,
    type Entry,
    type Exchange,
    type Item,
    type Laid,
    type Talk,
    type Whose,
} from "./conversation";
import { cited, type Span } from "./comments";

const at = (minute: number) => `2026-10-18T10:${String(minute).padStart(2, "0")}:00Z`;

const STEPS: Entry[] = [
    { kind: "said", by: "operator", text: "Look into reading transcripts.", at: at(0) },
    { kind: "said", by: "agent", text: "Each session is a JSONL file;\nsubagents get their own.", at: at(1) },
    { kind: "called", tool: "Bash", at: at(2) },
    { kind: "called", tool: "Bash", at: at(2) },
    { kind: "called", tool: "Read", at: at(3) },
    { kind: "said", by: "operator", text: "Build the reader.", at: at(9) },
    { kind: "said", by: "agent", text: "Twenty kinds of line.\n\n\nFour carry what was said.  ", at: at(10) },
    { kind: "called", tool: "Grep", at: at(11) },
];

/** The session's own conversation, its subagents called by their kind. */
const WHOSE: Whose = { agent: null, name: (party) => (party.agent == null ? "lup-impl" : `lup-impl/${party.agent}`) };

/** A conversation with nothing exchanged through lup, and no call read whole. */
const ALONE: Beside = { exchanged: UNEXCHANGED, whose: WHOSE, calls: new Map() };

const MORE: Entry[] = [
    { kind: "called", tool: "Grep", at: at(12) },
    { kind: "said", by: "agent", text: "Found the four.", at: at(13) },
];

/** Return what `span` shows of `out`. */
const shown = (out: Laid, span: Span) => out.text.slice(span.from, span.to);

/** Return each fold of `out` by its key: its kind, and its summary line. */
const folding = (out: Laid) => out.folds.map((each) => [each.key, each.kind, shown(out, each.summary)]);

describe("a conversation laid out", () => {
    it("says each step in a line, the agent's paragraphs kept, each exchange before the operator's last words folded under their words", () => {
        const out = laid(STEPS, ALONE, UNSAID);
        expect(out.text).toBe(
            [
                "you: Look into reading transcripts.",
                "Each session is a JSONL file;",
                "subagents get their own.",
                "· called Bash ×2, Read",
                "  · Bash",
                "  · Bash",
                "  · Read",
                "you: Build the reader.",
                "Twenty kinds of line.",
                "",
                "Four carry what was said.",
                "· Grep",
            ].join("\n"),
        );
        expect(folding(out)).toEqual([
            ["calls 2", "calls", "· called Bash ×2, Read"],
            ["you 0", "earlier", "you: Look into reading transcripts."],
        ]);
        const [run, exchange] = out.folds;
        expect(shown(out, { from: exchange!.from, to: exchange!.to })).toBe(
            "\nEach session is a JSONL file;\nsubagents get their own.\n· called Bash ×2, Read\n  · Bash\n  · Bash\n  · Read",
        );
        expect(shown(out, { from: run!.from, to: run!.to })).toBe("\n  · Bash\n  · Bash\n  · Read");
        // Each is folded until opened, and named by what it holds, its label its summary line.
        expect(out.folds.every((each) => each.closed && each.label === shown(out, each.summary))).toBe(true);
    });

    it("folds each exchange but the last, what came before the operator's first words under a line of its own, and nothing where they never spoke", () => {
        const steps: Entry[] = [
            { kind: "said", by: "agent", text: "Starting.", at: at(0) },
            { kind: "called", tool: "Bash", at: at(1) },
            { kind: "said", by: "operator", text: "First.\nTwo lines.", at: at(5) },
            { kind: "said", by: "agent", text: "One.", at: at(6) },
            { kind: "said", by: "operator", text: "Second.", at: at(7) },
            { kind: "said", by: "agent", text: "Two.", at: at(8) },
            { kind: "said", by: "operator", text: "Third.", at: at(9) },
            { kind: "said", by: "agent", text: "Three.", at: at(10) },
        ];
        const out = laid(steps, ALONE, UNSAID);
        expect(folding(out)).toEqual([
            ["before", "earlier", "earlier · 2 steps, from 5m before your first words"],
            ["you 2", "earlier", "you: First."],
            ["you 4", "earlier", "you: Second."],
        ]);
        // The rest of their words fold with what they opened; the last exchange is open, their words whole.
        expect(shown(out, { from: out.folds[1]!.from, to: out.folds[1]!.to })).toBe("\n     Two lines.\nOne.");
        expect(out.text.endsWith("you: Third.\nThree.")).toBe(true);
        expect(laid(steps.slice(0, 2), ALONE, UNSAID).folds).toEqual([]);
        expect(laid(steps.slice(2, 4), ALONE, UNSAID).folds).toEqual([]);
    });
});

describe("each call", () => {
    const steps: Entry[] = [
        { kind: "said", by: "operator", text: "Fix it.", at: at(0) },
        { kind: "called", tool: "Bash", gist: "Run the tests", id: "t1", at: at(1) },
        { kind: "said", by: "agent", text: "Two fail.", at: at(2) },
        { kind: "called", tool: "Read", gist: "review.ts:480", id: "t2", at: at(3) },
        { kind: "called", tool: "Edit", gist: "review.ts", id: "t3", at: at(4) },
        { kind: "called", tool: "Edit", gist: "review.ts", id: "t4", at: at(4) },
        { kind: "called", tool: "Bash", at: at(5) },
    ];
    const read: Detail = { shown: { id: "t1", input: { command: "uv run pytest -q", description: "Run the tests" }, output: "2 failed\n3 passed\n", failed: false } };

    it("is a line saying what it did, a run of them under one line, and its input and output fold under it, read as it opens", () => {
        const out = laid(steps, ALONE, UNSAID);
        expect(out.text).toBe(
            [
                "you: Fix it.",
                "· Bash: Run the tests",
                "    reading its input and output…",
                "Two fail.",
                "· called Read, Edit ×2, Bash",
                "  · Read: review.ts:480",
                "      reading its input and output…",
                "  · Edit: review.ts",
                "      reading its input and output…",
                "  · Edit: review.ts",
                "      reading its input and output…",
                "  · Bash",
            ].join("\n"),
        );
        expect(folding(out)).toEqual([
            ["call t1", "call", "· Bash: Run the tests"],
            ["call t2", "call", "  · Read: review.ts:480"],
            ["call t3", "call", "  · Edit: review.ts"],
            ["call t4", "call", "  · Edit: review.ts"],
            ["calls 3", "calls", "· called Read, Edit ×2, Bash"],
        ]);
        expect(out.calls.map((each) => [each.id, each.fold.key])).toEqual([
            ["t1", "call t1"],
            ["t2", "call t2"],
            ["t3", "call t3"],
            ["t4", "call t4"],
        ]);
        expect(out.folds[1]!.label).toBe("· Read: review.ts:480");
        // The lines of calls aren't the agent's words: no remark opens on them.
        expect(opened(out, out.text.indexOf("· Bash: Run"))).toBeUndefined();
        expect(RUN).toBe(3);
    });

    it("shows its input and output once read: each argument after its name, what it returned, or that it's still running", () => {
        const calls = new Map<string, Detail>([
            ["t1", read],
            ["t2", { shown: { id: "t2", input: { file_path: "/w/review.ts", offset: 480 }, failed: false } }],
            ["t3", { refused: "its record doesn't hold it" }],
        ]);
        const out = laid(steps.slice(0, 5), { ...ALONE, calls }, UNSAID);
        expect(out.text).toBe(
            [
                "you: Fix it.",
                "· Bash: Run the tests",
                "    input:",
                "      command: uv run pytest -q",
                "      description: Run the tests",
                "    output:",
                "      2 failed",
                "      3 passed",
                "Two fail.",
                "· Read: review.ts:480",
                "    input:",
                "      file_path: /w/review.ts",
                "      offset: 480",
                "    output: none yet",
                "· Edit: review.ts",
                "    not read: its record doesn't hold it",
            ].join("\n"),
        );
        const [first] = out.folds;
        expect(shown(out, { from: first!.from, to: first!.to }).split("\n").length).toBe(7);
    });

    it("says a failed call failed, and lays out text given as it is, a long value under its name", () => {
        const failed: Detail = { shown: { id: "x", input: "*** Begin Patch\n*** Update File: a.py\n*** End Patch", output: "a.py: no such file", failed: true } };
        expect(detailed(failed, "")).toEqual(["input:", "  *** Begin Patch", "  *** Update File: a.py", "  *** End Patch", "failed:", "  a.py: no such file"]);
        expect(detailed(undefined, "  ")).toEqual(["  reading its input and output…"]);
        const decisions = [{ text: "A model per kind, read by pydantic", lean: "yes" }, { text: "A dict walked by hand, key by key", lean: "no" }];
        expect(given({ question: "Which?\nOr neither?", limit: 3, tags: ["a"], decisions }, "")).toEqual([
            "question:",
            "  Which?",
            "  Or neither?",
            "limit: 3",
            'tags: ["a"]',
            "decisions:",
            "  [",
            "    {",
            '      "text": "A model per kind, read by pydantic",',
            '      "lean": "yes"',
            "    },",
            "    {",
            '      "text": "A dict walked by hand, key by key",',
            '      "lean": "no"',
            "    }",
            "  ]",
        ]);
        expect(given(null, "  ")).toEqual(["  null"]);
    });
});

describe("comments on the agent's words", () => {
    const out = laid(STEPS, ALONE, UNSAID);

    it("opens one on a line of the agent's words, quoting it, and none on any other line", () => {
        const words = ["Each session is a JSONL file;", "subagents get their own."];
        expect(opened(out, out.text.indexOf("subagents"))).toEqual({ step: 1, lines: words, first: 1, last: 1, start: 0, end: "subagents get their own.".length, text: "subagents get their own." });
        // From the start of the line, before the agent's words, it's the same line.
        expect(opened(out, out.text.indexOf("Twenty"))?.text).toBe("Twenty kinds of line.");
        for (const line of ["you: Build", "· Grep", "· called Bash", "  · Read"]) {
            expect(opened(out, out.text.indexOf(line))).toBeUndefined();
        }
        // The blank line between two paragraphs is no line of words.
        expect(opened(out, out.text.indexOf("\n\n") + 1)).toBeUndefined();
    });

    it("quotes a passage within one step, from its words' start where the selection takes whole lines, and not across steps", () => {
        const from = out.text.indexOf("JSONL");
        const words = ["Each session is a JSONL file;", "subagents get their own."];
        expect(quoted(out, from, from + "JSONL".length)).toEqual({ step: 1, lines: words, first: 0, last: 0, start: "Each session is a ".length, end: "Each session is a JSONL".length, text: "JSONL" });
        const line = out.text.indexOf("Each");
        const next = out.text.indexOf("· called Bash");
        expect(quoted(out, line, next)).toMatchObject({ first: 0, last: 1, text: "Each session is a JSONL file;\nsubagents get their own." });
        expect(quoted(out, from, out.text.indexOf("Twenty"))).toBeUndefined();
    });

    it("shows each comment under the line its passage ends on, in an earlier exchange as in the last", () => {
        const talk: Talk = {
            comments: [
                { id: "codex", step: 1, line: 0, text: "Even for codex?" },
                { id: "four", step: 6, line: 2, text: "Which four?" },
            ],
        };
        const commented = laid(STEPS, ALONE, talk);
        expect(commented.text).toBe(
            [
                "you: Look into reading transcripts.",
                "Each session is a JSONL file;",
                "Even for codex?",
                "subagents get their own.",
                "· called Bash ×2, Read",
                "  · Bash",
                "  · Bash",
                "  · Read",
                "you: Build the reader.",
                "Twenty kinds of line.",
                "",
                "Four carry what was said.",
                "Which four?",
                "· Grep",
            ].join("\n"),
        );
        expect(blockAt(commented, commented.text.indexOf("codex"))?.comment).toBe("codex");
        expect(blockAt(commented, commented.text.indexOf("Which four?"))?.comment).toBe("four");
        // Ctrl+Enter ending it lands on the last character of what it quotes, where reading carries on.
        expect(aboutAt(commented, 1, 0, 18, 23)).toBe(commented.text.indexOf("JSONL") + "JSONL".length - 1);
        // The comment in the earlier exchange is inside its fold.
        const exchange = commented.folds.find((each) => each.key === "you 0")!;
        expect(commented.text.indexOf("Even for codex?")).toBeGreaterThan(exchange.from);
        expect(commented.text.indexOf("Even for codex?")).toBeLessThan(exchange.to);
    });

    it("moves whole where a drawer lays it", () => {
        const by = 100;
        const moved = shifted(out, by);
        expect(moved.words[0]!.lines.map((each) => [each.from - by, each.start - by])).toEqual(out.words[0]!.lines.map((each) => [each.from, each.start]));
        expect(moved.asides.map((each) => each.from)).toEqual(out.asides.map((each) => each.from + by));
        expect(moved.folds.map((each) => [each.summary.from, each.from, each.to])).toEqual(out.folds.map((each) => [each.summary.from + by, each.from + by, each.to + by]));
    });
});

describe("the conversation growing", () => {
    const talk: Talk = {
        comments: [{ id: "codex", step: 1, line: 0, text: "Even for codex?" }],
    };

    it("adds what arrives at the end, everything before it where it was", () => {
        const before = laid(STEPS, ALONE, talk);
        const after = laid([...STEPS, ...MORE], ALONE, talk);
        const last = before.text.lastIndexOf("\n") + 1;
        // What arrives lands on the last line and after it.
        expect(after.text.slice(0, last)).toBe(before.text.slice(0, last));
        // The calls the conversation ended on go on: two now, each a line.
        expect(after.text.endsWith("· Grep\n· Grep\nFound the four.")).toBe(true);
        // The folds, the comments on earlier words, and a cursor reading mid-conversation stay where they were.
        expect(after.folds).toEqual(before.folds);
        expect(after.blocks[0]).toEqual(before.blocks[0]);
    });

    it("folds the exchange that was the last once the operator speaks again, and a run once it's long enough, each named as before", () => {
        const later: Entry[] = [...STEPS, ...MORE, { kind: "called", tool: "Read", at: at(14) }, { kind: "called", tool: "Read", at: at(14) }, { kind: "called", tool: "Read", at: at(14) }];
        const out = laid(later, ALONE, UNSAID);
        expect(out.text.endsWith("Found the four.\n· called Read ×3\n  · Read\n  · Read\n  · Read")).toBe(true);
        const spoke = laid([...later, { kind: "said", by: "operator", text: "Good.", at: at(15) }], ALONE, UNSAID);
        expect(folding(spoke).map(([key]) => key)).toEqual(["calls 2", "you 0", "calls 10", "you 5"]);
    });
});

const SESSION: Item["recipient"] = { party: "conversation", repository: "/r.git", runtime: "claude", session: "s1", agent: null };
const SURVEY: Item["recipient"] = { ...SESSION, agent: "a04" };
const OPERATOR: Item["sender"] = { party: "operator" };

/** The ranks the host gives each item by its kind (`ranked`, `inbox/store.py`), which say whether one waiting is waiting on the operator. */
const WAITING: Item["rank"] = { name: "waiting on you", order: 0, notifies: true };
const NEWS: Item["rank"] = { name: "news", order: 1, notifies: false };
const FLAG: Item["rank"] = { name: "flag", order: 2, notifies: false };

/** The rank the host gives an item of `reason`'s kind, for the kinds these tests make. */
function ranked(reason: Item["reason"]): Item["rank"] {
    switch (reason.reason) {
        case "message":
            return reason.kind === "note" ? NEWS : WAITING;
        case "friction":
        case "how it went":
        case "stop":
            return NEWS;
        case "flagged":
            return FLAG;
        default:
            return WAITING;
    }
}

/** An item of the session's, sent to the operator unless `fields` say otherwise. */
function item(number: number, reason: Item["reason"], minute: number, fields: Partial<Item> = {}): Item {
    return {
        number,
        reason,
        sender: SESSION,
        recipient: OPERATOR,
        replies: [],
        citations: [],
        edits: [],
        quiet: false,
        made: at(minute),
        state: { state: "waiting" },
        rank: ranked(reason),
        ...fields,
    };
}

/** An item and its text, as the host lists it. */
function exchange(each: Item, text: string): Exchange {
    return { item: each, text };
}

const CALLED: Entry[] = [
    { kind: "said", by: "operator", text: "Look into reading transcripts.", at: at(0) },
    { kind: "said", by: "agent", text: "Each session is a JSONL file.", at: at(1) },
    { kind: "called", tool: "Bash", id: "b1", at: at(2) },
    { kind: "called", tool: "mcp__lup__ask", id: "q1", at: at(3) },
    { kind: "called", tool: "Read", id: "r1", at: at(4) },
    { kind: "said", by: "agent", text: "Reading the second runtime's.", at: at(6) },
    { kind: "called", tool: "Grep", id: "g1", at: at(8) },
];

const ASKED = item(51, { reason: "question", text: "Which parser?", decisions: [{ text: "A model per kind", lean: "yes" }] }, 3, {
    call: "q1",
    state: { state: "answered", at: at(4), answer: 53 },
});
const NOTED = item(52, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "I assumed UTF-8." }, 7, { state: { state: "done", at: at(9) } });
const ANSWERED = item(53, { reason: "answer", question: 51, rulings: [{ decision: 1, verdict: "leaning", comment: "" }], comment: "" }, 4, {
    sender: OPERATOR,
    recipient: SESSION,
    state: { state: "told", at: at(5), how: "call" },
});
const REPLIED = item(54, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "Good.", of: 52 }, 9, { sender: OPERATOR, recipient: SESSION });

const EXCHANGED: Beside = {
    ...ALONE,
    exchanged: {
        sent: [exchange(ASKED, "Which parser?\n1. A model per kind (lean: yes)"), exchange(NOTED, "I assumed UTF-8.")],
        received: [
            exchange(ANSWERED, "Asked: Which parser?\n1. A model per kind (lean: yes): leaning: they go with the lean."),
            exchange(REPLIED, "Good."),
        ],
    },
};

describe("the items of lup's inbox in a conversation", () => {
    it("shows each in a line, its text under it: one it sent just after the call that made it, one it was sent when it was told, any other when it was made", () => {
        const out = laid(CALLED, EXCHANGED, UNSAID);
        const reading = "    reading its input and output…";
        expect(out.text).toBe(
            [
                "you: Look into reading transcripts.",
                "Each session is a JSONL file.",
                "· Bash",
                reading,
                "· mcp__lup__ask",
                reading,
                "→ @51 question to you · answered by @53",
                "  Which parser?",
                "  1. A model per kind (lean: yes)",
                "· Read",
                reading,
                "← @53 your answer to @51",
                "  Asked: Which parser?",
                "  1. A model per kind (lean: yes): leaning: they go with the lean.",
                "Reading the second runtime's.",
                "→ @52 note to you · answered by @54",
                "  I assumed UTF-8.",
                "· Grep",
                reading,
                "← @54 your reply to @52 · not told yet",
                "  Good.",
            ].join("\n"),
        );
        const line = (number: number) => out.items.find((each) => each.number === number)!;
        // Each item's text folds under its line, read and never commented on.
        expect(out.items.map((each) => each.number)).toEqual([51, 53, 52, 54]);
        expect(out.folds.filter((each) => each.kind === "context").map((each) => each.key)).toEqual(["item 51", "item 53", "item 52", "item 54"]);
        expect(shown(out, line(53).fold!)).toBe("\n  Asked: Which parser?\n  1. A model per kind (lean: yes): leaning: they go with the lean.");
        for (const number of [51, 53]) {
            expect(opened(out, line(number).line.from)).toBeUndefined();
            expect(opened(out, line(number).fold!.to - 1)).toBeUndefined();
        }
        expect(out.asides.filter((each) => each.kind === "item-from").map((each) => shown(out, each))).toEqual([
            "→ @51 question to you · answered by @53",
            "→ @52 note to you · answered by @54",
        ]);
    });

    it("cites each item by `@` and its number, which nobody takes for a GitHub issue's `#`", () => {
        expect(cited(270)).toBe("@270");
        const out = laid(CALLED, EXCHANGED, UNSAID);
        expect(out.text).not.toMatch(/#\d/);
    });

    it("leaves out a turn's last words lup made a note, which are the agent's words already shown", () => {
        const ended = item(55, { reason: "message", passages: [], answers: [], ending: true, kind: "note", text: "Reading the second runtime's." }, 8);
        const beside: Beside = {
            ...EXCHANGED,
            exchanged: { ...EXCHANGED.exchanged, sent: [...EXCHANGED.exchanged.sent, exchange(ended, "Reading the second runtime's.")] },
        };
        const out = laid(CALLED, beside, UNSAID);
        expect(out.items.map((each) => each.number)).toEqual([51, 53, 52, 54]);
        expect(out.text).not.toContain("@55");
    });

    it("says where each it sent stands: waiting on you, unread, read, withdrawn, approved or declined with your comment", () => {
        const held = item(55, { reason: "held", text: "Let the change land?", summary: "AGENTS.md: the operator's", worktree: "/w", key: "k" }, 12, {
            state: { state: "decided", at: at(13), approved: false, comment: "Not this file." },
        });
        const flagged = { reason: "flagged", text: "a.py landed, flagged.", summary: "a.py is a new production file", worktree: "/w", path: "a.py", writes: 1 } as const;
        const sent = [
            item(56, { reason: "message", passages: [], answers: [], ending: false, kind: "problem", text: "Stuck." }, 12),
            item(57, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "Done." }, 12, { state: { state: "done", at: at(13) } }),
            item(58, { reason: "question", text: "Which?", decisions: [] }, 12, { state: { state: "withdrawn", at: at(13), why: "Found it." } }),
            // A flag and news wait on no one, as the review ranks them: unread, never waiting on you.
            item(59, flagged, 12),
            item(60, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "Assumed UTF-8." }, 12),
        ];
        const out = laid(
            STEPS,
            { ...ALONE, exchanged: { sent: [exchange(held, "Let the change land?\nAGENTS.md: the operator's"), ...sent.map((each) => exchange(each, "…"))], received: [] } },
            UNSAID,
        );
        expect(out.text.slice(out.text.indexOf("→ @55"))).toBe(
            [
                "→ @55 held change to you · declined",
                "  Let the change land?",
                "  AGENTS.md: the operator's",
                "",
                "  your comment: Not this file.",
                "→ @56 problem to you · waiting on you",
                "  …",
                "→ @57 note to you · read",
                "  …",
                "→ @58 question to you · withdrawn: Found it.",
                "  …",
                "→ @59 flagged write to you · unread",
                "  …",
                "→ @60 note to you · unread",
                "  …",
            ].join("\n"),
        );
    });

    it("says one passed on from an ended subagent: in its session's, whose it was; in the subagent's, where it went", () => {
        const noted = item(44, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "No cache." }, 2, { sender: SURVEY, state: { state: "done", at: at(3) } });
        const reply = item(46, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "Right.", of: 44 }, 3, {
            sender: OPERATOR,
            recipient: SESSION,
            addressed: SURVEY,
            state: { state: "told", at: at(4), how: "call" },
        });
        const session = laid(STEPS.slice(0, 3), { ...ALONE, exchanged: { sent: [], received: [exchange(reply, "Right.")] } }, UNSAID);
        const subagent = laid(
            STEPS.slice(0, 3),
            { ...ALONE, whose: { ...WHOSE, agent: "a04" }, exchanged: { sent: [exchange(noted, "No cache.")], received: [exchange(reply, "Right.")] } },
            UNSAID,
        );
        expect(session.text.split("\n").filter((each) => each.startsWith("←") || each.startsWith("→"))).toEqual([
            "← @46 your reply to @44, for lup-impl/a04, which had ended",
        ]);
        expect(subagent.text.split("\n").filter((each) => each.startsWith("←") || each.startsWith("→"))).toEqual([
            "→ @44 note to you · answered by @46",
            "← @46 your reply to @44 · passed on to lup-impl, this one having ended",
        ]);
    });

    it("places by time a step with none taking the last time before it, and in a record with no times at the end", () => {
        const untimed: Entry[] = [
            { kind: "said", by: "operator", text: "Go." },
            { kind: "called", tool: "Bash" },
            { kind: "said", by: "agent", text: "Ran it.", at: at(5) },
            { kind: "called", tool: "Read" },
            { kind: "said", by: "agent", text: "Read it." },
        ];
        const early = item(60, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "Early." }, 4);
        const late = item(61, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "Late." }, 6);
        const beside: Beside = { ...ALONE, exchanged: { sent: [exchange(late, "Late."), exchange(early, "Early.")], received: [] } };
        const lines = (entries: Entry[]) =>
            laid(entries, beside, UNSAID)
                .text.split("\n")
                .filter((each) => !each.startsWith("  "));
        expect(lines(untimed)).toEqual([
            "you: Go.",
            "· Bash",
            "→ @60 note to you · unread",
            "Ran it.",
            "· Read",
            "Read it.",
            "→ @61 note to you · unread",
        ]);
        expect(lines(untimed.map(({ at: _, ...each }) => each))).toEqual([
            "you: Go.",
            "· Bash",
            "Ran it.",
            "· Read",
            "Read it.",
            "→ @60 note to you · unread",
            "→ @61 note to you · unread",
        ]);
    });

    it("folds an item before the operator's last words in the exchange it came in, and one before their first words with what came before them, counting it", () => {
        const before = item(50, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "Early." }, 4);
        const out = laid(STEPS, { ...ALONE, exchanged: { sent: [exchange(before, "Early.")], received: [] } }, UNSAID);
        const exchange_ = out.folds.find((each) => each.key === "you 0")!;
        const inner = out.items[0]!.fold!;
        expect(inner.from > exchange_.from && inner.to <= exchange_.to).toBe(true);
        expect(out.folds.map((each) => each.key)).toEqual(["calls 2", "item 50", "you 0"]);
        const first = item(49, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "Earliest." }, 0);
        const early = laid(STEPS.slice(1), { ...ALONE, exchanged: { sent: [exchange(first, "Earliest.")], received: [] } }, UNSAID);
        expect(early.text.split("\n")[0]).toBe("earlier · 4 steps, 1 item, from 9m before your first words");
    });

    it("adds an item arriving, and changes its question's line as its answer arrives, the rest where it was", () => {
        const asked: Beside = { ...ALONE, exchanged: { sent: [exchange({ ...ASKED, state: { state: "waiting" } }, "Which parser?")], received: [] } };
        const before = laid(CALLED, asked, UNSAID);
        const after = laid(CALLED, { ...asked, exchanged: { sent: [exchange(ASKED, "Which parser?")], received: [exchange(ANSWERED, "Asked.")] } }, UNSAID);
        expect(before.text).toContain("→ @51 question to you · waiting on you");
        expect(after.text).toContain("→ @51 question to you · answered by @53\n  Which parser?\n· Read\n    reading its input and output…\n← @53 your answer to @51\n  Asked.\nReading the second runtime");
    });
});

describe("a review it was sent", () => {
    it("says what it answers, or that it's the operator's message from the review where it answers nothing", () => {
        const told = { state: { state: "told" as const, at: at(9), how: "call" as const }, sender: OPERATOR, recipient: SESSION };
        const written = item(60, { reason: "review", covers: [], comments: [], letters: [{ id: "", to: SESSION, text: "Rename it." }], remarks: [] }, 9, told);
        const reviewed = item(61, { reason: "review", covers: [52], comments: [{ id: "", item: 52, quote: null, text: "Fine." }], letters: [], remarks: [] }, 9, told);
        const beside: Beside = {
            ...ALONE,
            exchanged: {
                sent: [],
                received: [exchange(written, "The operator's message to you:\nRename it."), exchange(reviewed, "Fine.")],
            },
        };
        const out = laid(CALLED, beside, UNSAID);
        expect(out.text).toContain("← @60 your message, from the review\n  The operator's message to you:\n  Rename it.");
        expect(out.text).toContain("← @61 your review of @52\n  Fine.");
    });
});

describe("lup's word on its citations", () => {
    it("says it's lup's, and how many citations in which item named no passage, though the conversation is its sender", () => {
        const missed = { said: "@50[the tone]", start: 0, end: 13, item: 50, part: null, words: "the tone", found: null, candidates: [] };
        const told = { state: { state: "told" as const, at: at(9), how: "turn's end" as const }, recipient: SESSION };
        const one = item(63, { reason: "unresolved", of: 56, citations: [missed] }, 9, told);
        const two = item(64, { reason: "unresolved", of: 57, citations: [missed, missed] }, 9, told);
        const beside: Beside = { ...ALONE, exchanged: { sent: [], received: [exchange(one, "A citation in @56 doesn't name one passage."), exchange(two, "")] } };
        const out = laid(CALLED, beside, UNSAID);
        expect(out.text).toContain("← @63 from lup: a citation of your words in @56 named no one passage\n  A citation in @56 doesn't name one passage.");
        expect(out.text).toContain("← @64 from lup: 2 citations of your words in @57 named no one passage");
    });
});
