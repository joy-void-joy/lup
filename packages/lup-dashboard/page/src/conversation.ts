// One conversation laid out as one text to read and move through: the
// operator's words and the agent's, each run of calls in a line, what the
// operator sent it from here, and their comments on the agent's words, each
// under the line it's on, with their message on the whole last. What came before
// their last words folds. It grows at its end as the conversation does, what's
// before staying where it was. Pure: the editor (`Conversation.tsx`) draws it,
// lets the comments be written, and keeps the reader where they are as it grows
// (`docs/dashboard.md`, *The conversation*).
import { since } from "./agents";
import {
    calls,
    kept,
    passage,
    saying,
    shownIn,
    spoken,
    starts as startsOf,
    under,
    type Block,
    type Folding,
    type Line,
    type Quote,
    type Span,
} from "./comments";
import type { components } from "./generated/api";

export type Entry = components["schemas"]["Entry"];

/** A comment of the operator's: on a line or a passage of what the agent said at step `step`; or, with no step, their message on the conversation whole. */
export interface Remark {
    step: number | null;
    quote: Quote | null;
    text: string;
}

/** What the operator writes on one conversation, until it's sent. */
export interface Talk {
    comments: Remark[];
}

export const UNSAID: Talk = { comments: [] };

/** A message the operator sent the conversation from here, through lup: the item it made, what it said, and how many steps the conversation had then. */
export interface Sent {
    number: number;
    text: string;
    after: number;
    at: string;
}

/** What a line no comment is on shows: the summary of what folds, the operator's words, a run of calls, a message sent through lup, or the line the operator's message is under. */
export type Kind = "summary" | "you" | "agent" | "calls" | "sent" | "message";

/** A line no comment is on. */
export interface Aside extends Span {
    kind: Kind;
}

/** What the agent said at one step, which comments may be on: its lines, each shown after `start`, and the comments under them. */
export interface Words {
    step: number;
    own: string;
    lines: (Line & { start: number })[];
    blocks: Block[];
}

/** The conversation's text, and where each part of it is. */
export interface Laid {
    text: string;
    words: Words[];
    asides: Aside[];
    /** Every comment, on the agent's words and the message's. */
    blocks: Block[];
    /** What came before the operator's last words, folded under its summary. */
    fold: Folding | null;
    /** Where each thing said starts: the operator's words, the agent's, a message sent. */
    turns: number[];
    /** The conversation's last line, before the operator's message. */
    last: Span | null;
    /** The line the operator's message is under, where they're writing one. */
    message: Span | null;
}

/** One step of the conversation, or a message sent through lup between its steps. */
type Turn = { step: number; entry: Entry } | { sent: Sent };

/** Return the steps and the messages sent through lup in order, each message after the steps the conversation had when it was sent. */
function merged(entries: Entry[], sent: Sent[]): Turn[] {
    const turns: Turn[] = [];
    const between = (step: number, last: boolean) =>
        sent.filter((each) => (last ? each.after >= step : each.after === step)).map((each) => ({ sent: each }));
    entries.forEach((entry, step) => {
        turns.push(...between(step, false), { step, entry });
    });
    turns.push(...between(entries.length, true));
    return turns;
}

/** Return how many turns come before the operator's last words, a message sent through lup among them: what's folded once the conversation opens. */
export function history(entries: Entry[], sent: Sent[]): number {
    const turns = merged(entries, sent);
    const last = turns.findLastIndex((each) => "sent" in each || (each.entry.kind === "said" && each.entry.by === "operator"));
    return Math.max(last, 0);
}

/** Return when a turn was, where its record says. */
function at(turn: Turn): string | null {
    return "sent" in turn ? turn.sent.at : (turn.entry.at ?? null);
}

/** The line a message sent through lup is shown under. */
export function sentLine(sent: Sent): string {
    return `you, through lup · #${sent.number}:`;
}

const SENT_INDENT = "     ";

/** The line the operator's message is under, at the end. */
export const MESSAGE = "── your message ──";

/**
 * Lay a conversation out as one text: each step in order, the operator's words after `you:`, the agent's after
 * `agent:`, each run of calls in one line, each message sent through lup where it was sent; under each line of the
 * agent's words, the comments on it; then the operator's message on the whole, under its line. The first `folded`
 * turns fold under a summary line. Laid out again with more steps or more sent, everything before the last line
 * stays as it was: what arrives is added after it.
 */
export function laid(entries: Entry[], sent: Sent[], talk: Talk, folded: number): Laid {
    const turns = merged(entries, sent);
    const rows: string[] = [];
    let length = 0;
    const words: Words[] = [];
    const asides: Aside[] = [];
    const blocks: Block[] = [];
    const starts: number[] = [];
    let last: Span | null = null;
    const write = (text: string): Span => {
        const from = length + (rows.length === 0 ? 0 : 1);
        rows.push(text);
        length = from + text.length;
        return { from, to: from + text.length };
    };
    const aside = (kind: Kind, text: string): Span => {
        const span = write(text);
        asides.push({ kind, ...span });
        return span;
    };
    const comments = talk.comments.map((comment, at) => ({ comment, at }));
    const said = new Set(turns.flatMap((each) => ("entry" in each && each.entry.kind === "said" && each.entry.by === "agent" ? [each.step] : [])));
    const writeBlocks = (shown: { comment: Remark; at: number }[]) => {
        for (const { comment, at } of shown) {
            const span = write(comment.text);
            blocks.push({ comment: at, ...span });
        }
    };

    let summary: Span | null = null;
    if (folded > 0 && turns.length > folded) {
        const count = folded;
        const first = turns[0] === undefined ? null : at(turns[0]);
        const until = turns[folded] === undefined ? null : at(turns[folded]);
        const before = first === null || until === null ? "" : `, from ${since(new Date(first), new Date(until))} before your last words`;
        summary = aside("summary", `earlier · ${count} ${count === 1 ? "step" : "steps"}${before}`);
    }
    let foldTo: number | null = null;
    let run: string[] = [];
    const ran = () => {
        if (run.length > 0) {
            last = aside("calls", calls(run));
            run = [];
        }
    };
    turns.forEach((turn, index) => {
        if (index === folded && summary !== null) {
            ran();
            foldTo = length;
        }
        if ("sent" in turn) {
            ran();
            const head = aside("sent", sentLine(turn.sent));
            starts.push(head.from);
            last = head;
            for (const line of kept(turn.sent.text, true)) {
                last = aside("sent", line === "" ? "" : `${SENT_INDENT}${line}`);
            }
            return;
        }
        const { entry, step } = turn;
        if (entry.kind === "called") {
            run.push(entry.tool);
            return;
        }
        ran();
        const who = entry.by === "operator" ? "you" : "agent";
        const rowsSaid = spoken(who, entry.text, true);
        if (who === "you") {
            rowsSaid.forEach((row, at) => {
                const span = aside("you", row.text);
                if (at === 0) {
                    starts.push(span.from);
                }
                last = span;
            });
            return;
        }
        const lines = kept(entry.text, true);
        const own = lines.join("\n");
        const lineStarts = startsOf(lines);
        const mine = comments.filter(({ comment }) => comment.step === step);
        const shown: Words = { step, own, lines: [], blocks: [] };
        const before = blocks.length;
        rowsSaid.forEach((row, at) => {
            const span = write(row.text);
            if (at === 0) {
                starts.push(span.from);
            }
            last = span;
            if (row.blank) {
                asides.push({ kind: "agent", ...span });
                return;
            }
            shown.lines.push({ from: span.from + row.words, to: span.to, own: row.own, start: span.from });
            writeBlocks(mine.filter(({ comment }) => (under(lineStarts, comment.quote) ?? 0) === at));
        });
        shown.blocks = blocks.slice(before);
        words.push(shown);
    });
    ran();
    if (summary !== null && foldTo === null) {
        foldTo = length;
    }
    const fold =
        summary === null || foldTo === null || foldTo <= summary.to
            ? null
            : { key: "earlier", summary, from: summary.to, to: foldTo };

    // The message on the whole, and any comment on words no longer laid out, last, under the message's line.
    const closing = comments.filter(({ comment }) => comment.step === null || !said.has(comment.step));
    const message = closing.length === 0 ? null : aside("message", MESSAGE);
    writeBlocks(closing);
    return { text: rows.join("\n"), words, asides, blocks, fold, turns: starts, last, message };
}

/** Return the agent's words, and their line, shown at `position`, where it's on one. */
function lineAt(laidOut: Laid, position: number): { words: Words; line: Words["lines"][number] } | undefined {
    for (const words of laidOut.words) {
        const line = words.lines.find((each) => position >= each.start && position <= each.to);
        if (line !== undefined) {
            return { words, line };
        }
    }
    return undefined;
}

/** Return the comment shown at `position`, where it's in one; a comment's end counts, so an empty one can be typed in. */
export function blockAt(laidOut: Laid, position: number): Block | undefined {
    return laidOut.blocks.find((each) => position >= each.from && position <= each.to);
}

/** Return where a comment opened on the line at `position` goes: on that line of the agent's words, or the operator's message from its line; none on any other line. */
export function opened(laidOut: Laid, position: number): Remark | undefined {
    if (laidOut.message !== null && position >= laidOut.message.from && position <= laidOut.message.to) {
        return { step: null, quote: null, text: "" };
    }
    const found = lineAt(laidOut, position);
    if (found === undefined) {
        return undefined;
    }
    const { words, line } = found;
    const text = laidOut.text.slice(line.from, line.to);
    return { step: words.step, quote: { text, start: line.own, end: line.own + text.length }, text: "" };
}

/** Return a comment on the passage `from` to `to` selects, counted in what the agent said; none where it isn't all inside one step of its words. */
export function quoted(laidOut: Laid, from: number, to: number): Remark | undefined {
    const first = lineAt(laidOut, from);
    const last = lineAt(laidOut, Math.max(to - 1, from));
    if (first === undefined || last === undefined || first.words !== last.words || to <= from) {
        return undefined;
    }
    const quote = passage(first.words.own, first.line, last.line, from, to);
    return quote.end > quote.start ? { step: first.words.step, quote, text: "" } : undefined;
}

/** Return where a comment on the agent's words is about, in the text: the start of what it quotes; none for the message. */
export function aboutAt(laidOut: Laid, comment: Remark): number | undefined {
    const words = laidOut.words.find((each) => each.step === comment.step);
    if (words === undefined || comment.quote == null) {
        return undefined;
    }
    return shownIn(words.lines, comment.quote.start, words.lines[0]?.start ?? 0);
}

/**
 * Say the operator's comments as one message an agent reads: each comment on its words under what it quotes, set
 * off as a quotation is in a mail, in the order they were said; then the message on the whole.
 */
export function message(talk: Talk): string {
    const comments = saying(talk.comments);
    const quoted = comments
        .filter((each) => each.step !== null && each.quote != null)
        .sort((a, b) => (a.step ?? 0) - (b.step ?? 0) || (a.quote?.start ?? 0) - (b.quote?.start ?? 0));
    const rest = comments.filter((each) => each.step === null || each.quote == null);
    const parts = quoted.map((each) => {
        const lines = (each.quote?.text ?? "").split("\n").map((line) => (line === "" ? ">" : `> ${line}`));
        return `${lines.join("\n")}\n\n${each.text.trim()}`;
    });
    return [...parts, ...rest.map((each) => each.text.trim())].join("\n\n");
}

/** Where the reader is, as the conversation grows: on its last line, writing their message at its end, or anywhere else, where nothing they see moves. */
export type Reading = "last" | "message" | "elsewhere";

/** Return where the reader is with the cursor at `head`. */
export function reading(laidOut: Laid, head: number): Reading {
    if (laidOut.message !== null && head >= laidOut.message.from) {
        return "message";
    }
    const last = laidOut.last;
    return last === null || (head >= last.from && head <= last.to) ? "last" : "elsewhere";
}
