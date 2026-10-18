import { describe, expect, it } from "vitest";

import {
    MESSAGE,
    UNSAID,
    aboutAt,
    blockAt,
    history,
    laid,
    message,
    opened,
    quoted,
    reading,
    type Entry,
    type Sent,
    type Talk,
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

const MORE: Entry[] = [
    { kind: "called", tool: "Grep", at: at(12) },
    { kind: "said", by: "agent", text: "Found the four.", at: at(13) },
];

describe("a conversation laid out", () => {
    it("says each step in a line, the agent's paragraphs kept, a run of calls in one, what came before the operator's last words folded", () => {
        const folded = history(STEPS, []);
        expect(folded).toBe(5);
        const out = laid(STEPS, [], UNSAID, folded);
        expect(out.text).toBe(
            [
                "earlier · 5 steps, from 9m before your last words",
                "you: Look into reading transcripts.",
                "agent: Each session is a JSONL file;",
                "       subagents get their own.",
                "· called Bash ×2, Read",
                "you: Build the reader.",
                "agent: Twenty kinds of line.",
                "",
                "       Four carry what was said.",
                "· called Grep",
            ].join("\n"),
        );
        const shown = (from: number, to: number) => out.text.slice(from, to);
        expect(out.fold).not.toBeNull();
        expect(shown(out.fold!.summary.from, out.fold!.summary.to)).toBe("earlier · 5 steps, from 9m before your last words");
        expect(shown(out.fold!.from, out.fold!.to)).toBe(
            "\nyou: Look into reading transcripts.\nagent: Each session is a JSONL file;\n       subagents get their own.\n· called Bash ×2, Read",
        );
        expect(out.last).toEqual({ from: out.text.indexOf("· called Grep"), to: out.text.length });
        expect(out.turns.map((each) => shown(each, out.text.indexOf("\n", each)))).toEqual([
            "you: Look into reading transcripts.",
            "agent: Each session is a JSONL file;",
            "you: Build the reader.",
            "agent: Twenty kinds of line.",
        ]);
        expect(out.message).toBeNull();
    });

    it("folds nothing where the operator's last words are its first step", () => {
        const out = laid(STEPS.slice(0, 3), [], UNSAID, history(STEPS.slice(0, 3), []));
        expect(out.fold).toBeNull();
        expect(out.text.startsWith("you: Look into")).toBe(true);
    });
});

describe("comments on the agent's words", () => {
    const out = laid(STEPS, [], UNSAID, history(STEPS, []));

    it("opens one on a line of the agent's words, quoting it, and none on any other line", () => {
        expect(opened(out, out.text.indexOf("subagents"))).toEqual({
            step: 1,
            quote: { text: "subagents get their own.", start: "Each session is a JSONL file;\n".length, end: "Each session is a JSONL file;\nsubagents get their own.".length },
            text: "",
        });
        // From the start of the line, before the agent's words, it's the same line.
        expect(opened(out, out.text.indexOf("agent: Twenty"))?.quote?.text).toBe("Twenty kinds of line.");
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
        const line = out.text.indexOf("agent: Each");
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
        const commented = laid(STEPS, [], talk, history(STEPS, []));
        expect(commented.text).toBe(
            [
                "earlier · 5 steps, from 9m before your last words",
                "you: Look into reading transcripts.",
                "agent: Each session is a JSONL file;",
                "Even for codex?",
                "       subagents get their own.",
                "· called Bash ×2, Read",
                "you: Build the reader.",
                "agent: Twenty kinds of line.",
                "",
                "       Four carry what was said.",
                "Which four?",
                "· called Grep",
                MESSAGE,
                "Carry on after.",
            ].join("\n"),
        );
        expect(blockAt(commented, commented.text.indexOf("codex"))?.comment).toBe(1);
        expect(blockAt(commented, commented.text.indexOf("Carry on"))?.comment).toBe(0);
        expect(opened(commented, commented.text.indexOf(MESSAGE))).toEqual({ step: null, quote: null, text: "" });
        expect(aboutAt(commented, talk.comments[1]!)).toBe(commented.text.indexOf("JSONL"));
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
        const before = laid(STEPS, [], talk, folded);
        const after = laid([...STEPS, ...MORE], [], talk, folded);
        const made = changes(before.text, after.text);
        // What arrives lands on the last line and after it, before the message, which stays last.
        expect(made.length).toBe(1);
        expect(made[0]!.from).toBeGreaterThanOrEqual(before.last!.from);
        expect(after.text.slice(0, before.last!.from)).toBe(before.text.slice(0, before.last!.from));
        expect(after.text.endsWith(`${MESSAGE}\nCarry on.`)).toBe(true);
        expect(after.text.slice(after.last!.from, after.last!.to)).toBe("agent: Found the four.");
        // The run of calls the conversation ended on goes on in its line.
        expect(after.text).toContain("· called Grep ×2\nagent: Found the four.");
        // The fold, the comments on earlier words, and a cursor reading mid-conversation stay where they were.
        expect(after.fold).toEqual(before.fold);
        expect(after.blocks[0]).toEqual(before.blocks[0]);
        const reader = before.text.indexOf("you: Build");
        expect(moved(reader, made, before.text.length)).toBe(reader);
        expect(reading(before, reader)).toBe("elsewhere");
        // One writing their message stays in it, moved down with it.
        const writer = before.text.indexOf("Carry on.") + 3;
        expect(after.text.slice(moved(writer, made, before.text.length))).toBe("ry on.");
        expect(reading(before, before.last!.from)).toBe("last");
    });

    it("keeps what fold, however the operator's later words, and a message sent from here after the steps it followed", () => {
        const sent: Sent[] = [{ number: 101, text: "> JSONL\n\nEven for codex?", after: STEPS.length, at: at(12) }];
        const later: Entry[] = [...STEPS, { kind: "said", by: "agent", text: "Yes, both.", at: at(14) }, { kind: "said", by: "operator", text: "Good.", at: at(15) }];
        const out = laid(later, sent, UNSAID, folded);
        expect(out.fold).toEqual(laid(STEPS, [], UNSAID, folded).fold);
        expect(out.text.slice(out.text.indexOf("· called Grep"))).toBe(
            ["· called Grep", "you, through lup · #101:", "     > JSONL", "", "     Even for codex?", "agent: Yes, both.", "you: Good."].join("\n"),
        );
        // Opened again, it folds up to the operator's last words, a message sent from here among them.
        expect(history(STEPS, sent)).toBe(STEPS.length);
        expect(history(later, sent)).toBe(later.length);
    });
});

describe("the changes between two texts", () => {
    const apply = (text: string, made: { from: number; to: number; insert: string }[]) =>
        [...made].reverse().reduce((done, each) => done.slice(0, each.from) + each.insert + done.slice(each.to), text);

    it("are line by line, each line both keep left where it is", () => {
        expect(changes("a\nb\nc", "a\nb\nx\nc")).toEqual([{ from: 4, to: 4, insert: "x\n" }]);
        expect(changes("ab", "ab")).toEqual([]);
        expect(changes("· called Bash", "· called Bash ×2\nagent: hi")).toEqual([{ from: 0, to: 13, insert: "· called Bash ×2\nagent: hi" }]);
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
        const before = laid(STEPS, [], talk, folded);
        const sent: Sent[] = [{ number: 101, text: message(talk), after: STEPS.length, at: at(12) }];
        const after = laid([...STEPS, ...MORE], sent, UNSAID, folded);
        const made = changes(before.text, after.text);
        expect(made.length).toBe(2);
        expect(apply(before.text, made)).toBe(after.text);
        const reader = before.text.indexOf("you: Build");
        expect(after.text.slice(moved(reader, made, before.text.length)).startsWith("you: Build")).toBe(true);
    });

    it("move a cursor with the character it's on, to a change's start where that's replaced, and not at the text's end", () => {
        const added = [{ from: 4, to: 4, insert: "x\n" }];
        expect(moved(2, added, 5)).toBe(2);
        expect(moved(4, added, 5)).toBe(6);
        expect(moved(5, [{ from: 5, to: 5, insert: "\nd" }], 5)).toBe(5);
        expect(moved(3, [{ from: 2, to: 4, insert: "zz" }], 5)).toBe(2);
        expect(moved(8, [{ from: 0, to: 2, insert: "" }, { from: 4, to: 4, insert: "x\n" }], 9)).toBe(8);
    });
});
