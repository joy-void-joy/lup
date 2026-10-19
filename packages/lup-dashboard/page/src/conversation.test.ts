import { describe, expect, it } from "vitest";

import {
    MESSAGE,
    UNEXCHANGED,
    UNSAID,
    aboutAt,
    blockAt,
    folds,
    history,
    laid,
    message,
    opened,
    quoted,
    reading,
    type Beside,
    type Entry,
    type Exchange,
    type Item,
    type Sent,
    type Talk,
    type Whose,
} from "./conversation";
import { changes, moved } from "./comments";

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

/** A conversation with nothing exchanged through lup. */
const ALONE: Beside = { sent: [], exchanged: UNEXCHANGED, whose: WHOSE };

const MORE: Entry[] = [
    { kind: "called", tool: "Grep", at: at(12) },
    { kind: "said", by: "agent", text: "Found the four.", at: at(13) },
];

describe("a conversation laid out", () => {
    it("says each step in a line, the agent's paragraphs kept, a run of calls in one, what came before the operator's last words folded", () => {
        const folded = history(STEPS, []);
        expect(folded).toEqual({ step: 5 });
        const out = laid(STEPS, ALONE, UNSAID, folded);
        expect(out.text).toBe(
            [
                "earlier · 5 steps, from 9m before your last words",
                "you: Look into reading transcripts.",
                "Each session is a JSONL file;",
                "subagents get their own.",
                "· called Bash ×2, Read",
                "you: Build the reader.",
                "Twenty kinds of line.",
                "",
                "Four carry what was said.",
                "· called Grep",
            ].join("\n"),
        );
        const shown = (from: number, to: number) => out.text.slice(from, to);
        expect(out.fold).not.toBeNull();
        expect(shown(out.fold!.summary.from, out.fold!.summary.to)).toBe("earlier · 5 steps, from 9m before your last words");
        expect(shown(out.fold!.from, out.fold!.to)).toBe(
            "\nyou: Look into reading transcripts.\nEach session is a JSONL file;\nsubagents get their own.\n· called Bash ×2, Read",
        );
        expect(out.last).toEqual({ from: out.text.indexOf("· called Grep"), to: out.text.length });
        expect(out.turns.map((each) => shown(each, out.text.indexOf("\n", each)))).toEqual([
            "you: Look into reading transcripts.",
            "Each session is a JSONL file;",
            "you: Build the reader.",
            "Twenty kinds of line.",
        ]);
        expect(out.message).toBeNull();
    });

    it("folds nothing where the operator's last words are its first step", () => {
        const out = laid(STEPS.slice(0, 3), ALONE, UNSAID, history(STEPS.slice(0, 3), []));
        expect(out.fold).toBeNull();
        expect(out.text.startsWith("you: Look into")).toBe(true);
    });
});

describe("comments on the agent's words", () => {
    const out = laid(STEPS, ALONE, UNSAID, history(STEPS, []));

    it("opens one on a line of the agent's words, quoting it, and none on any other line", () => {
        expect(opened(out, out.text.indexOf("subagents"))).toEqual({
            step: 1,
            quote: { text: "subagents get their own.", start: "Each session is a JSONL file;\n".length, end: "Each session is a JSONL file;\nsubagents get their own.".length },
            text: "",
        });
        // From the start of the line, before the agent's words, it's the same line.
        expect(opened(out, out.text.indexOf("Twenty"))?.quote?.text).toBe("Twenty kinds of line.");
        for (const line of ["earlier", "you: Build", "· called Grep", "· called Bash"]) {
            expect(opened(out, out.text.indexOf(line))).toBeUndefined();
        }
        // The blank line between two paragraphs is no line of words.
        expect(opened(out, out.text.indexOf("\n\n") + 1)).toBeUndefined();
    });

    it("quotes a passage within one step, from its words' start where the selection takes whole lines, and not across steps", () => {
        const from = out.text.indexOf("JSONL");
        expect(quoted(out, from, from + "JSONL".length)).toEqual({
            step: 1,
            quote: { text: "JSONL", start: "Each session is a ".length, end: "Each session is a JSONL".length },
            text: "",
        });
        const line = out.text.indexOf("Each");
        const next = out.text.indexOf("· called Bash");
        expect(quoted(out, line, next)?.quote?.text).toBe("Each session is a JSONL file;\nsubagents get their own.");
        expect(quoted(out, from, out.text.indexOf("Twenty"))).toBeUndefined();
    });

    it("shows each comment under the line its passage ends on, and the message last under its line", () => {
        const talk: Talk = {
            comments: [
                { step: null, quote: null, text: "Carry on after." },
                { step: 1, quote: { text: "JSONL", start: 18, end: 23 }, text: "Even for codex?" },
                { step: 6, quote: { text: "Four carry what was said.", start: 23, end: 48 }, text: "Which four?" },
            ],
        };
        const commented = laid(STEPS, ALONE, talk, history(STEPS, []));
        expect(commented.text).toBe(
            [
                "earlier · 5 steps, from 9m before your last words",
                "you: Look into reading transcripts.",
                "Each session is a JSONL file;",
                "Even for codex?",
                "subagents get their own.",
                "· called Bash ×2, Read",
                "you: Build the reader.",
                "Twenty kinds of line.",
                "",
                "Four carry what was said.",
                "Which four?",
                "· called Grep",
                MESSAGE,
                "Carry on after.",
            ].join("\n"),
        );
        expect(blockAt(commented, commented.text.indexOf("codex"))?.comment).toBe(1);
        expect(blockAt(commented, commented.text.indexOf("Carry on"))?.comment).toBe(0);
        expect(opened(commented, commented.text.indexOf(MESSAGE))).toEqual({ step: null, quote: null, text: "" });
        // Ctrl+Enter ending it lands on the last character of what it quotes, where reading carries on.
        expect(aboutAt(commented, talk.comments[1]!)).toBe(commented.text.indexOf("JSONL") + "JSONL".length - 1);
        expect(reading(commented, commented.text.indexOf("Carry on"))).toBe("message");
    });

    it("says them as one message: each under what it quotes, in the conversation's order, the message on the whole last", () => {
        const talk: Talk = {
            comments: [
                { step: null, quote: null, text: "Carry on after.  " },
                { step: 6, quote: { text: "Twenty kinds of line.\n\nFour", start: 0, end: 27 }, text: "Which four?" },
                { step: 1, quote: { text: "JSONL", start: 18, end: 23 }, text: "Even for codex?" },
                { step: 1, quote: { text: "file", start: 24, end: 28 }, text: "   " },
            ],
        };
        expect(message(talk)).toBe(
            "> JSONL\n\nEven for codex?\n\n> Twenty kinds of line.\n>\n> Four\n\nWhich four?\n\nCarry on after.",
        );
        expect(message(UNSAID)).toBe("");
    });
});

describe("the conversation growing", () => {
    const folded = history(STEPS, []);
    const talk: Talk = {
        comments: [
            { step: 1, quote: { text: "JSONL", start: 18, end: 23 }, text: "Even for codex?" },
            { step: null, quote: null, text: "Carry on." },
        ],
    };

    it("adds what arrives at the end, before the operator's message, everything before it where it was", () => {
        const before = laid(STEPS, ALONE, talk, folded);
        const after = laid([...STEPS, ...MORE], ALONE, talk, folded);
        const made = changes(before.text, after.text);
        // What arrives lands on the last line and after it, before the message, which stays last.
        expect(made.length).toBe(1);
        expect(made[0]!.from).toBeGreaterThanOrEqual(before.last!.from);
        expect(after.text.slice(0, before.last!.from)).toBe(before.text.slice(0, before.last!.from));
        expect(after.text.endsWith(`${MESSAGE}\nCarry on.`)).toBe(true);
        expect(after.text.slice(after.last!.from, after.last!.to)).toBe("Found the four.");
        // The run of calls the conversation ended on goes on in its line.
        expect(after.text).toContain("· called Grep ×2\nFound the four.");
        // The fold, the comments on earlier words, and a cursor reading mid-conversation stay where they were.
        expect(after.fold).toEqual(before.fold);
        expect(after.blocks[0]).toEqual(before.blocks[0]);
        const reader = before.text.indexOf("you: Build");
        expect(moved(reader, made, before.text)).toBe(reader);
        expect(reading(before, reader)).toBe("elsewhere");
        // One writing their message stays in it, moved down with it.
        const writer = before.text.indexOf("Carry on.") + 3;
        expect(after.text.slice(moved(writer, made, before.text))).toBe("ry on.");
        expect(reading(before, before.last!.from)).toBe("last");
    });

    it("keeps what fold, however the operator's later words, and a message sent from here after the steps it followed", () => {
        const sent: Sent[] = [{ number: 101, text: "> JSONL\n\nEven for codex?", after: STEPS.length, at: at(12) }];
        const later: Entry[] = [...STEPS, { kind: "said", by: "agent", text: "Yes, both.", at: at(14) }, { kind: "said", by: "operator", text: "Good.", at: at(15) }];
        const out = laid(later, { ...ALONE, sent }, UNSAID, folded);
        expect(out.fold).toEqual(laid(STEPS, ALONE, UNSAID, folded).fold);
        expect(out.text.slice(out.text.indexOf("· called Grep"))).toBe(
            ["· called Grep", "← #101 your message, from here", "  > JSONL", "", "  Even for codex?", "Yes, both.", "you: Good."].join("\n"),
        );
        // Its text folds under its line.
        const [item] = out.items;
        expect(item?.fold?.key).toBe("item 101");
        expect(out.text.slice(item!.fold!.from, item!.fold!.to)).toBe("\n  > JSONL\n\n  Even for codex?");
        // Opened again, it folds up to the operator's last words, a message sent from here among them.
        expect(history(STEPS, sent)).toEqual({ item: 101 });
        expect(history(later, sent)).toEqual({ step: later.length - 1 });
    });
});

const SESSION: Item["recipient"] = { party: "conversation", repository: "/r.git", runtime: "claude", session: "s1", agent: null };
const SURVEY: Item["recipient"] = { ...SESSION, agent: "a04" };
const OPERATOR: Item["sender"] = { party: "operator" };

/** The rank the host gives what waits on the operator (`ranked`, `inbox/store.py`), which the conversation doesn't read. */
const WAITING: Item["rank"] = { name: "waiting on you", order: 0, notifies: true };

/** An item of the session's, sent to the operator unless `fields` say otherwise. */
function item(number: number, reason: Item["reason"], minute: number, fields: Partial<Item> = {}): Item {
    return {
        number,
        reason,
        sender: SESSION,
        recipient: OPERATOR,
        made: at(minute),
        state: { state: "waiting" },
        rank: WAITING,
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
const NOTED = item(52, { reason: "message", ending: false, kind: "note", text: "I assumed UTF-8." }, 7, { state: { state: "done", at: at(9) } });
const ANSWERED = item(53, { reason: "answer", question: 51, rulings: [{ decision: 1, verdict: "leaning", comment: "" }], comment: "" }, 4, {
    sender: OPERATOR,
    recipient: SESSION,
    state: { state: "told", at: at(5), how: "call" },
});
const REPLIED = item(54, { reason: "message", ending: false, kind: "note", text: "Good.", of: 52 }, 9, { sender: OPERATOR, recipient: SESSION });

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
        const out = laid(CALLED, EXCHANGED, UNSAID, history(CALLED, []));
        expect(out.text).toBe(
            [
                "you: Look into reading transcripts.",
                "Each session is a JSONL file.",
                "· called Bash, mcp__lup__ask",
                "→ #51 question to you · answered by #53",
                "  Which parser?",
                "  1. A model per kind (lean: yes)",
                "· called Read",
                "← #53 your answer to #51",
                "  Asked: Which parser?",
                "  1. A model per kind (lean: yes): leaning: they go with the lean.",
                "Reading the second runtime's.",
                "→ #52 note to you · answered by #54",
                "  I assumed UTF-8.",
                "· called Grep",
                "← #54 your reply to #52 · not told yet",
                "  Good.",
            ].join("\n"),
        );
        const line = (number: number) => out.items.find((each) => each.number === number)!;
        const shown = (span: { from: number; to: number }) => out.text.slice(span.from, span.to);
        // Each item's text folds under its line, read and never commented on.
        expect(out.items.map((each) => each.number)).toEqual([51, 53, 52, 54]);
        expect(folds(out).map((each) => each.key)).toEqual(["item 51", "item 53", "item 52", "item 54"]);
        expect(shown(line(53).fold!)).toBe("\n  Asked: Which parser?\n  1. A model per kind (lean: yes): leaning: they go with the lean.");
        for (const number of [51, 53]) {
            expect(opened(out, line(number).line.from)).toBeUndefined();
            expect(opened(out, line(number).fold!.to - 1)).toBeUndefined();
        }
        expect(out.asides.filter((each) => each.kind === "item-from").map(shown)).toEqual([
            "→ #51 question to you · answered by #53",
            "→ #52 note to you · answered by #54",
        ]);
        // `]]` and `[[` stop at each, and the reader on the last one follows what arrives.
        expect(out.turns).toContain(line(52).line.from);
        expect(out.last).toEqual(line(54).line);
    });

    it("leaves out a turn's last words lup made a note, which are the agent's words already shown", () => {
        const ended = item(55, { reason: "message", ending: true, kind: "note", text: "Reading the second runtime's." }, 8);
        const beside: Beside = {
            ...EXCHANGED,
            exchanged: { ...EXCHANGED.exchanged, sent: [...EXCHANGED.exchanged.sent, exchange(ended, "Reading the second runtime's.")] },
        };
        const out = laid(CALLED, beside, UNSAID, history(CALLED, []));
        expect(out.items.map((each) => each.number)).toEqual([51, 53, 52, 54]);
        expect(out.text).not.toContain("#55");
    });

    it("says where each it sent stands: waiting on you, read, withdrawn, approved or declined with your comment", () => {
        const held = item(55, { reason: "held", text: "Let the change land?", summary: "AGENTS.md: the operator's", worktree: "/w", key: "k" }, 12, {
            state: { state: "decided", at: at(13), approved: false, comment: "Not this file." },
        });
        const sent = [
            item(56, { reason: "message", ending: false, kind: "problem", text: "Stuck." }, 12),
            item(57, { reason: "message", ending: false, kind: "note", text: "Done." }, 12, { state: { state: "done", at: at(13) } }),
            item(58, { reason: "question", text: "Which?", decisions: [] }, 12, { state: { state: "withdrawn", at: at(13), why: "Found it." } }),
        ];
        const out = laid(
            STEPS,
            { ...ALONE, exchanged: { sent: [exchange(held, "Let the change land?\nAGENTS.md: the operator's"), ...sent.map((each) => exchange(each, "…"))], received: [] } },
            UNSAID,
            "nothing",
        );
        expect(out.text.slice(out.text.indexOf("→ #55"))).toBe(
            [
                "→ #55 held change to you · declined",
                "  Let the change land?",
                "  AGENTS.md: the operator's",
                "",
                "  your comment: Not this file.",
                "→ #56 problem to you · waiting on you",
                "  …",
                "→ #57 note to you · read",
                "  …",
                "→ #58 question to you · withdrawn: Found it.",
                "  …",
            ].join("\n"),
        );
    });

    it("says one passed on from an ended subagent: in its session's, whose it was; in the subagent's, where it went", () => {
        const noted = item(44, { reason: "message", ending: false, kind: "note", text: "No cache." }, 2, { sender: SURVEY, state: { state: "done", at: at(3) } });
        const reply = item(46, { reason: "message", ending: false, kind: "note", text: "Right.", of: 44 }, 3, {
            sender: OPERATOR,
            recipient: SESSION,
            addressed: SURVEY,
            state: { state: "told", at: at(4), how: "call" },
        });
        const session = laid(STEPS.slice(0, 3), { ...ALONE, exchanged: { sent: [], received: [exchange(reply, "Right.")] } }, UNSAID, "nothing");
        const subagent = laid(
            STEPS.slice(0, 3),
            { ...ALONE, whose: { ...WHOSE, agent: "a04" }, exchanged: { sent: [exchange(noted, "No cache.")], received: [exchange(reply, "Right.")] } },
            UNSAID,
            "nothing",
        );
        expect(session.text.split("\n").filter((each) => each.startsWith("←") || each.startsWith("→"))).toEqual([
            "← #46 your reply to #44, for lup-impl/a04, which had ended",
        ]);
        expect(subagent.text.split("\n").filter((each) => each.startsWith("←") || each.startsWith("→"))).toEqual([
            "→ #44 note to you · answered by #46",
            "← #46 your reply to #44 · passed on to lup-impl, this one having ended",
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
        const early = item(60, { reason: "message", ending: false, kind: "note", text: "Early." }, 4);
        const late = item(61, { reason: "message", ending: false, kind: "note", text: "Late." }, 6);
        const beside: Beside = { ...ALONE, exchanged: { sent: [exchange(late, "Late."), exchange(early, "Early.")], received: [] } };
        const lines = (entries: Entry[]) =>
            laid(entries, beside, UNSAID, "nothing")
                .text.split("\n")
                .filter((each) => !each.startsWith("  "));
        expect(lines(untimed)).toEqual([
            "you: Go.",
            "· called Bash",
            "→ #60 note to you · waiting on you",
            "Ran it.",
            "· called Read",
            "Read it.",
            "→ #61 note to you · waiting on you",
        ]);
        expect(lines(untimed.map(({ at: _, ...each }) => each))).toEqual([
            "you: Go.",
            "· called Bash",
            "Ran it.",
            "· called Read",
            "Read it.",
            "→ #60 note to you · waiting on you",
            "→ #61 note to you · waiting on you",
        ]);
    });

    it("shows a message sent from here once, as its item, after the steps the conversation had then, and one not listed yet from what was sent", () => {
        const sent: Sent[] = [
            { number: 101, text: "Go on.", after: 3, at: at(20) },
            { number: 102, text: "And then?", after: STEPS.length, at: at(21) },
        ];
        const told = item(101, { reason: "message", ending: false, kind: "note", text: "Go on." }, 20, {
            sender: OPERATOR,
            recipient: SESSION,
            state: { state: "told", at: at(25), how: "call" },
        });
        const out = laid(STEPS, { ...ALONE, sent, exchanged: { sent: [], received: [exchange(told, "Go on.")] } }, UNSAID, "nothing");
        expect(out.text.split("\n").filter((each) => each.startsWith("←"))).toEqual([
            "← #101 your message, from here",
            "← #102 your message, from here",
        ]);
        expect(out.text).toContain("· called Bash\n← #101 your message, from here\n  Go on.\n· called Bash, Read");
        expect(out.text.endsWith("· called Grep\n← #102 your message, from here\n  And then?")).toBe(true);
    });

    it("folds the items before the operator's last words with what came before, counting them", () => {
        const before = item(50, { reason: "message", ending: false, kind: "note", text: "Early." }, 4);
        const out = laid(STEPS, { ...ALONE, exchanged: { sent: [exchange(before, "Early.")], received: [] } }, UNSAID, history(STEPS, []));
        expect(out.text.split("\n")[0]).toBe("earlier · 5 steps, 1 item, from 9m before your last words");
        const fold = out.fold!;
        const inner = out.items[0]!.fold!;
        expect(inner.from > fold.from && inner.to <= fold.to).toBe(true);
        expect(folds(out).map((each) => each.key)).toEqual(["earlier", "item 50"]);
    });

    it("adds an item arriving, and changes its question's line as its answer arrives, the rest where it was", () => {
        const asked: Beside = { ...ALONE, exchanged: { sent: [exchange({ ...ASKED, state: { state: "waiting" } }, "Which parser?")], received: [] } };
        const before = laid(CALLED, asked, UNSAID, history(CALLED, []));
        const after = laid(CALLED, { ...asked, exchanged: { sent: [exchange(ASKED, "Which parser?")], received: [exchange(ANSWERED, "Asked.")] } }, UNSAID, history(CALLED, []));
        const made = changes(before.text, after.text);
        expect(before.text).toContain("→ #51 question to you · waiting on you");
        expect(after.text).toContain("→ #51 question to you · answered by #53\n  Which parser?\n· called Read\n← #53 your answer to #51\n  Asked.\nReading the second runtime");
        const reader = before.text.indexOf("Reading");
        expect(after.text.slice(moved(reader, made, before.text)).startsWith("Reading")).toBe(true);
    });
});

describe("the changes between two texts", () => {
    const apply = (text: string, made: { from: number; to: number; insert: string }[]) =>
        [...made].reverse().reduce((done, each) => done.slice(0, each.from) + each.insert + done.slice(each.to), text);

    it("are line by line, each line both keep left where it is", () => {
        expect(changes("a\nb\nc", "a\nb\nx\nc")).toEqual([{ from: 4, to: 4, insert: "x\n" }]);
        expect(changes("ab", "ab")).toEqual([]);
        expect(changes("· called Bash", "· called Bash ×2\nhi")).toEqual([{ from: 0, to: 13, insert: "· called Bash ×2\nhi" }]);
        for (const [before, after] of [
            ["", "a\nb"],
            ["a\nb", ""],
            ["a\nb\nc", "a"],
            ["a\nb\nc", "c"],
            ["a\nb", "a\nb\nc\nd"],
            ["x\na\ny\nb\nz", "a\nb\nq"],
        ] as const) {
            expect(apply(before, changes(before, after))).toBe(after);
        }
    });

    it("keep a reader between two of them where they were, as when a message sent clears comments above and adds below", () => {
        const talk: Talk = { comments: [{ step: 1, quote: { text: "JSONL", start: 18, end: 23 }, text: "Even for codex?" }, { step: null, quote: null, text: "Carry on." }] };
        const folded = history(STEPS, []);
        const before = laid(STEPS, ALONE, talk, folded);
        const sent: Sent[] = [{ number: 101, text: message(talk), after: STEPS.length, at: at(12) }];
        const after = laid([...STEPS, ...MORE], { ...ALONE, sent }, UNSAID, folded);
        const made = changes(before.text, after.text);
        expect(made.length).toBe(2);
        expect(apply(before.text, made)).toBe(after.text);
        const reader = before.text.indexOf("you: Build");
        expect(after.text.slice(moved(reader, made, before.text)).startsWith("you: Build")).toBe(true);
    });

    it("move a cursor with the character it's on, and not at the text's end", () => {
        const added = [{ from: 4, to: 4, insert: "x\n" }];
        expect(moved(2, added, "a\nb\nc")).toBe(2);
        expect(moved(4, added, "a\nb\nc")).toBe(6);
        expect(moved(5, [{ from: 5, to: 5, insert: "\nd" }], "a\nb\nc")).toBe(5);
        expect(moved(8, [{ from: 0, to: 2, insert: "" }, { from: 4, to: 4, insert: "x\n" }], "a\nb\nc\nd\ne")).toBe(8);
    });

    it("keep a cursor on its line and column where the line is replaced, to a change's start where it's removed", () => {
        // A header's wait said anew, the cursor on its `w`.
        const before = "── #51 · waiting 9m ──\nx";
        const after = "── #51 · waiting 10m ──\nx";
        const made = changes(before, after);
        expect(after.slice(moved(before.indexOf("waiting"), made, before))).toMatch(/^waiting 10m/);
        // A comment's line shortened under the cursor: on its last character.
        expect(moved(5, changes("hello \nx", "hello\nx"), "hello \nx")).toBe(4);
        // The second of two lines replaced by one: on the one.
        expect(moved(4, [{ from: 0, to: 5, insert: "zz" }], "ab\ncd\ne")).toBe(1);
        // Lines removed: at the change's start, the line after them.
        expect(moved(3, changes("a\nb\nc\nd", "a\nd"), "a\nb\nc\nd")).toBe(2);
    });
});

describe("a review it was sent", () => {
    it("says what it answers, or that it's the operator's message from the review where it answers nothing", () => {
        const told = { state: { state: "told" as const, at: at(9), how: "call" as const }, sender: OPERATOR, recipient: SESSION };
        const written = item(60, { reason: "review", covers: [], comments: [], letters: [{ to: SESSION, text: "Rename it." }] }, 9, told);
        const reviewed = item(61, { reason: "review", covers: [52], comments: [{ item: 52, quote: null, text: "Fine." }], letters: [] }, 9, told);
        const beside: Beside = {
            ...ALONE,
            exchanged: {
                sent: [],
                received: [exchange(written, "The operator's message to you:\nRename it."), exchange(reviewed, "Fine.")],
            },
        };
        const out = laid(CALLED, beside, UNSAID, history(CALLED, []));
        expect(out.text).toContain("← #60 your message, from the review\n  The operator's message to you:\n  Rename it.");
        expect(out.text).toContain("← #61 your review of #52\n  Fine.");
    });
});
