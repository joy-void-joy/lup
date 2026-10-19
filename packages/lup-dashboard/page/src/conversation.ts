// One conversation laid out as one text to read and move through: the
// operator's words and the agent's, each run of calls in a line, the items of
// lup's inbox it sent and was sent, what the operator sent it from here among
// them, each in a line with its text folded under it, and their comments on the
// agent's words, each under the line it's on, with their message on the whole
// last. What came before their last words folds. It grows at its end as the
// conversation does, what's before staying where it was. Pure: the editor
// (`Conversation.tsx`) draws it, lets the comments be written, and keeps the
// reader where they are as it grows (`docs/dashboard.md`, *The conversation*).
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
export type Item = components["schemas"]["Item"];
export type Exchange = components["schemas"]["Exchange"];
type Party = components["schemas"]["Conversation"];

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

/** The items of lup's inbox the conversation sent, and those it was sent, each with its text whole. */
export interface Exchanged {
    sent: Exchange[];
    received: Exchange[];
}

export const UNEXCHANGED: Exchanged = { sent: [], received: [] };

/** Whose conversation it is, as its items are said: its subagent's id, none for its session's own; and how a conversation is called. */
export interface Whose {
    agent: string | null;
    name: (party: Party) => string;
}

/**
 * What a line no comment is on shows: the summary of what folds, the operator's words, a run of calls, an item the
 * conversation sent or one it was sent, a line of an item's text, or the line the operator's message is under.
 */
export type Kind = "summary" | "you" | "agent" | "calls" | "item-from" | "item-to" | "item-text" | "message";

/** A line no comment is on. */
export interface Aside extends Span {
    kind: Kind;
}

/** An item of lup's inbox where it's shown: its line, and the fold its text is under, where it has any. */
export interface Placed {
    number: number;
    line: Span;
    fold: Folding | null;
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
    /** Each item of lup's inbox, in the text's order. */
    items: Placed[];
    /** Where each thing said starts: the operator's words, the agent's, an item. */
    turns: number[];
    /** The conversation's last line, before the operator's message. */
    last: Span | null;
    /** The line the operator's message is under, where they're writing one. */
    message: Span | null;
}

/** Where an item goes among the steps: just after the call that made it, where the record holds it; after the steps the conversation had when it was sent from here; else by when it was told, or made. */
type Where = { call: string; at: string } | { after: number; at: string } | { at: string };

/** An item of lup's inbox as the conversation shows it: whether the conversation sent it, its line, its text's lines, and where it goes. */
interface Inboxed {
    number: number;
    from: boolean;
    line: string;
    text: string[];
    where: Where;
}

/** One step of the conversation, or an item of lup's inbox between its steps. */
type Turn = { step: number; entry: Entry } | { inboxed: Inboxed };

/** How an item's text is set in under its line. */
const ITEM_INDENT = "  ";

/** Return an item's text as the lines it's shown in under its line: its paragraphs kept, each line set in. */
function setIn(text: string): string[] {
    return kept(text, true).map((line) => (line === "" ? "" : `${ITEM_INDENT}${line}`));
}

/** Say what an item is, in a word or two: a message's kind, a question, an answer, a review, a held change, an approval, a friction, how it went, a stop. */
function what(item: Item): string {
    const reason = item.reason;
    switch (reason.reason) {
        case "message":
            return reason.kind;
        case "held":
            return "held change";
        case "stop":
            return "stopped";
        default:
            return reason.reason;
    }
}

/** Return the items `received` holds that answer `item`: an answer to it, a reply to it, a review covering it; by number. */
function answering(item: Item, received: Exchange[]): number[] {
    const found = received.flatMap(({ item: each }) => {
        const reason = each.reason;
        const answers =
            (reason.reason === "answer" && reason.question === item.number) ||
            (reason.reason === "message" && reason.of === item.number) ||
            (reason.reason === "review" && reason.covers.includes(item.number));
        return answers ? [each.number] : [];
    });
    const answered = item.state.state === "answered" ? [item.state.answer] : [];
    return [...new Set([...answered, ...found])].sort((a, b) => a - b);
}

/** Say where an item the conversation sent stands: withdrawn, decided, answered and by what, or waiting on whom; nothing once told. */
function standing(item: Item, received: Exchange[]): string | null {
    const state = item.state;
    switch (state.state) {
        case "withdrawn":
            return `withdrawn: ${state.why}`;
        case "decided":
            return state.approved ? "approved" : "declined";
        case "superseded":
            return `superseded by #${state.by}`;
    }
    const answers = answering(item, received);
    if (answers.length > 0) {
        return `answered by ${answers.map((each) => `#${each}`).join(", ")}`;
    }
    switch (state.state) {
        case "waiting":
            return item.recipient.party === "operator" ? "waiting on you" : "not told yet";
        case "done":
            return "read";
        default:
            return null;
    }
}

/** Say what came to the conversation in an item it was sent: the operator's answer, reply, review or message; or what another sent it. */
function came(item: Item, whose: Whose): string {
    const reason = item.reason;
    if (item.sender.party === "conversation") {
        return `${what(item)} from ${whose.name(item.sender)}`;
    }
    switch (reason.reason) {
        case "answer":
            return `your answer to #${reason.question}`;
        case "review":
            return reason.covers.length === 0
                ? "your message, from the review"
                : `your review of ${reason.covers.map((each) => `#${each}`).join(", ")}`;
        case "message":
            return reason.of == null ? "your message" : `your reply to #${reason.of}`;
        default:
            return `your ${what(item)}`;
    }
}

/** Return the line `parts` make: the first, then each other after a dot. */
function dotted(first: string, ...parts: (string | null)[]): string {
    return [first, ...parts.filter((each) => each !== null)].join(" · ");
}

/**
 * Return the items the conversation exchanged as it shows them, each in a line and its text folded under it: one it
 * sent, `→`, what it is, whom to and where it stands (answered and by what, read, waiting on you, withdrawn, decided);
 * one it was sent, `←`, what it is, for whom where it was passed on, and whether it's told yet. A message sent from
 * here is one of them, said to be from here and placed after the steps the conversation had then; one its item isn't
 * listed for yet is shown from what was sent. A turn's last words, which lup made a note, aren't: they're the agent's
 * words already shown.
 */
function inboxed(exchanged: Exchanged, sent: Sent[], whose: Whose): Inboxed[] {
    const here = new Map(sent.map((each) => [each.number, each]));
    const spoken = exchanged.sent.filter(({ item }) => !(item.reason.reason === "message" && item.reason.ending === true));
    const its = spoken.map(({ item, text }): Inboxed => {
        const to = item.recipient.party === "operator" ? "you" : whose.name(item.recipient);
        const state = item.state;
        const comment = state.state === "decided" && state.comment ? ["", ...setIn(`your comment: ${state.comment}`)] : [];
        return {
            number: item.number,
            from: true,
            line: dotted(`→ #${item.number} ${what(item)} to ${to}`, standing(item, exchanged.received)),
            text: [...setIn(text), ...comment],
            where: item.call == null ? { at: item.made } : { call: item.call, at: item.made },
        };
    });
    const theirs = exchanged.received.map(({ item, text }): Inboxed => {
        const from = here.get(item.number);
        const passed = item.addressed;
        const ours = passed != null && (passed.agent ?? null) === whose.agent;
        const recipient = item.recipient;
        const head = [
            `← #${item.number} ${came(item, whose)}`,
            from === undefined ? "" : ", from here",
            passed == null || ours ? "" : `, for ${whose.name(passed)}, which had ended`,
        ].join("");
        const onward =
            ours && recipient.party === "conversation" ? `passed on to ${whose.name(recipient)}, this one having ended` : null;
        const state = item.state;
        return {
            number: item.number,
            from: false,
            line: dotted(head, state.state === "waiting" ? "not told yet" : null, onward),
            text: setIn(text),
            where:
                from !== undefined
                    ? { after: from.after, at: from.at }
                    : { at: state.state === "told" ? state.at : item.made },
        };
    });
    const listed = new Set(exchanged.received.map(({ item }) => item.number));
    const unlisted = sent
        .filter((each) => !listed.has(each.number))
        .map(
            (each): Inboxed => ({
                number: each.number,
                from: false,
                line: `← #${each.number} your message, from here`,
                text: setIn(each.text),
                where: { after: each.after, at: each.at },
            }),
        );
    return [...its, ...theirs, ...unlisted];
}

/**
 * Return the steps and the items in order: an item the conversation sent just after the call that made it, where the
 * record holds it; a message sent from here after the steps the conversation had then; any other by when it was told,
 * or made, after the last step at or before then. A step its record gives no time takes the time of the last before
 * it, and one before any time counts as before every item, so in a record with no times they're all at its end. Items
 * between the same two steps go in the order they came.
 */
function merged(entries: Entry[], items: Inboxed[]): Turn[] {
    const calls = new Map<string, number>();
    entries.forEach((entry, step) => {
        if (entry.kind === "called" && entry.id != null && !calls.has(entry.id)) {
            calls.set(entry.id, step);
        }
    });
    let known: number | null = null;
    const times = entries.map((entry) => {
        known = entry.at == null ? known : new Date(entry.at).getTime();
        return known;
    });
    // The items before each step, and after the last; and those just after each call that made them.
    const before: Inboxed[][] = [...entries, null].map(() => []);
    const after: Inboxed[][] = entries.map(() => []);
    for (const item of items) {
        const { where } = item;
        const call = "call" in where ? calls.get(where.call) : undefined;
        if (call !== undefined) {
            after[call]?.push(item);
        } else if ("after" in where) {
            before[Math.min(Math.max(where.after, 0), entries.length)]?.push(item);
        } else {
            const when = new Date(where.at).getTime();
            before[times.findLastIndex((time) => time === null || time <= when) + 1]?.push(item);
        }
    }
    const order = (a: Inboxed, b: Inboxed) =>
        new Date(a.where.at).getTime() - new Date(b.where.at).getTime() || a.number - b.number;
    const turns = (each: Inboxed[]): Turn[] => [...each].sort(order).map((inboxed) => ({ inboxed }));
    return [
        ...entries.flatMap((entry, step): Turn[] => [
            ...turns(before[step] ?? []),
            { step, entry },
            ...turns(after[step] ?? []),
        ]),
        ...turns(before[entries.length] ?? []),
    ];
}

/** What folds once the conversation opens: what came before the operator's words at a step, or before a message they sent from here; or nothing. */
export type Earlier = { step: number } | { item: number } | "nothing";

/** Return what folds once the conversation opens: what came before the operator's last words, a message they sent from here among them. */
export function history(entries: Entry[], sent: Sent[]): Earlier {
    const spoke = entries.findLastIndex((each) => each.kind === "said" && each.by === "operator");
    const later = sent.filter((each) => each.after > spoke);
    const last = later.reduce<Sent | null>((found, each) => (found === null || each.after >= found.after ? each : found), null);
    if (last !== null) {
        return { item: last.number };
    }
    return spoke < 0 ? "nothing" : { step: spoke };
}

/** Return whether `turn` is where what folds ends. */
function ending(turn: Turn, earlier: Earlier): boolean {
    if (earlier === "nothing") {
        return false;
    }
    return "step" in earlier ? "entry" in turn && turn.step === earlier.step : "inboxed" in turn && turn.inboxed.number === earlier.item;
}

/** Return when a turn was, where its record says. */
function at(turn: Turn): string | null {
    return "inboxed" in turn ? turn.inboxed.where.at : (turn.entry.at ?? null);
}

/** Say how many of a thing there are: `1 step`, `5 steps`. */
function counted(count: number, one: string): string {
    return `${count} ${one}${count === 1 ? "" : "s"}`;
}

/** The line the operator's message is under, at the end. */
export const MESSAGE = "── your message ──";

/** What a conversation shows beside its steps: the items of lup's inbox it exchanged, the messages sent to it from here among them, said as to whose conversation it is. */
export interface Beside {
    sent: Sent[];
    exchanged: Exchanged;
    whose: Whose;
}

/**
 * Lay a conversation out as one text: each step in order, the operator's words after `you:`, the agent's as they
 * are, each run of calls in one line; each item of lup's inbox it exchanged in a line among them, its text folded
 * under it (`merged`); under each line of the agent's words, the comments on it; then the operator's message on the
 * whole, under its line. What came before `earlier` folds under a summary line. Laid out again with more steps, or an
 * item arriving, everything before the last line stays as it was: what arrives is added after it.
 */
export function laid(entries: Entry[], beside: Beside, talk: Talk, earlier: Earlier): Laid {
    const turns = merged(entries, inboxed(beside.exchanged, beside.sent, beside.whose));
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

    // What folds: the turns before the one `earlier` names, where any come before it.
    const folded = turns.findIndex((turn) => ending(turn, earlier));
    let summary: Span | null = null;
    if (folded > 0) {
        const steps = turns.slice(0, folded).filter((each) => "entry" in each).length;
        const items = folded - steps;
        const first = turns[0] === undefined ? null : at(turns[0]);
        const until = turns[folded] === undefined ? null : at(turns[folded]);
        const before = first === null || until === null ? "" : `, from ${since(new Date(first), new Date(until))} before your last words`;
        const count = [counted(steps, "step"), ...(items === 0 ? [] : [counted(items, "item")])].join(", ");
        summary = aside("summary", `earlier · ${count}${before}`);
    }
    let foldTo: number | null = null;
    const items: Placed[] = [];
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
        if ("inboxed" in turn) {
            ran();
            const { inboxed: item } = turn;
            const line = aside(item.from ? "item-from" : "item-to", item.line);
            starts.push(line.from);
            last = line;
            const end = item.text.map((row) => aside("item-text", row)).at(-1);
            const fold = end === undefined ? null : { key: `item ${item.number}`, summary: line, from: line.to, to: end.to };
            items.push({ number: item.number, line, fold });
            return;
        }
        const { entry, step } = turn;
        if (entry.kind === "called") {
            run.push(entry.tool);
            return;
        }
        ran();
        // The operator's words after `you:`; the agent's, which are most of it, unlabelled.
        const who = entry.by === "operator" ? "you" : null;
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
    return { text: rows.join("\n"), words, asides, blocks, fold, items, turns: starts, last, message };
}

/** Return what folds in a laid-out conversation: what came before the operator's last words first, then each item's text. */
export function folds(laidOut: Laid): Folding[] {
    const each = laidOut.items.flatMap((item) => (item.fold === null ? [] : [item.fold]));
    return laidOut.fold === null ? each : [laidOut.fold, ...each];
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
