// One conversation laid out as one text to read and move through: the
// operator's words and the agent's, each call a line saying what it did, the
// items of lup's inbox it sent and was sent, each in a line with its text
// folded under it, and the operator's remarks on the agent's words, each under
// the line it's on. Its latest part is open: everything since the operator's
// last words. Each earlier exchange folds under the line of their words that
// opened it, so each step back is one more fold to open; a run of calls folds
// under one line saying how many of which, and each call's input and output
// under its line, read whole as it opens. It grows at its end as the
// conversation does, what's before staying where it was. Pure: the review lays
// it into an agent's conversation drawer (`review.ts`; `docs/dashboard.md`,
// *The drawers*).
import { since } from "./agents";
import {
    calls,
    cited,
    kept,
    lastOf,
    passage,
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
import type { FoldKind } from "./keys";

export type Entry = components["schemas"]["Entry"];
export type Item = components["schemas"]["Item"];
export type Exchange = components["schemas"]["Exchange"];
export type Call = components["schemas"]["Call"];
type Called = components["schemas"]["Called"];
type Party = components["schemas"]["Conversation"];

/** A comment of the operator's on a line or a passage of what the agent said at step `step`: what the review's remark on the conversation holds of it (`Remark`, `review.ts`). */
export interface Remark {
    step: number;
    quote: Quote;
    text: string;
}

/** What the operator writes on one conversation, until it's sent. */
export interface Talk {
    comments: Remark[];
}

export const UNSAID: Talk = { comments: [] };

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

/** A call read whole, as the host answered: what it was given and what it returned, or why it wasn't read. */
export type Detail = { shown: Call } | { refused: string };

/** What a conversation shows beside its steps: the items of lup's inbox it exchanged, said as to whose conversation it is, and each call read whole so far, by its id. */
export interface Beside {
    exchanged: Exchanged;
    whose: Whose;
    calls: ReadonlyMap<string, Detail>;
}

/** How many calls in a row start folded under one line saying how many of which; fewer show a line each. */
export const RUN = 3;

/**
 * What a line no comment is on shows: a fold's summary, the operator's words, a run of calls, a call, a line of a
 * call's input and output, an item the conversation sent or one it was sent, or a line of an item's text.
 */
export type Kind = "summary" | "you" | "agent" | "calls" | "call" | "call-text" | "item-from" | "item-to" | "item-text";

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

/** A call where it's shown, by the runtime's id for it: its line, and the fold its input and output are under. */
export interface Shown {
    id: string;
    fold: Folding;
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
    /** Every comment on the agent's words. */
    blocks: Block[];
    /** What folds, each of its kind: each exchange before the operator's last words, a run of calls, a call's input and output, an item's text. */
    folds: Folding[];
    /** Each item of lup's inbox, in the text's order. */
    items: Placed[];
    /** Each call with an id, in the text's order. */
    calls: Shown[];
}

/** Where an item goes among the steps: just after the call that made it, where the record holds it; else by when it was told, or made. */
type Where = { call: string; at: string } | { at: string };

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

/** How an item's text is set in under its line, and a call's input and output under its. */
export const ITEM_INDENT = "  ";

/** Return an item's text as the lines it's shown in under its line: its paragraphs kept, each line set in. */
function setIn(text: string): string[] {
    return kept(text, true).map((line) => (line === "" ? "" : `${ITEM_INDENT}${line}`));
}

/** Say what an item is, in a word or two: a message's kind, a question, an answer, a review, a held change, an approval, a friction, how it went, a stop, a flagged write. */
function what(item: Item): string {
    const reason = item.reason;
    switch (reason.reason) {
        case "message":
            return reason.kind;
        case "held":
            return "held change";
        case "stop":
            return "stopped";
        case "flagged":
            return "flagged write";
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

/**
 * Say where an item the conversation sent stands: withdrawn, decided, answered and by what, read, or waiting; nothing
 * once told. One waiting for the operator is waiting on them where its kind's rank says so (`Item.rank`), as the review
 * ranks it; news and a flagged write are unread.
 */
function standing(item: Item, received: Exchange[]): string | null {
    const state = item.state;
    switch (state.state) {
        case "withdrawn":
            return `withdrawn: ${state.why}`;
        case "decided":
            return state.approved ? "approved" : "declined";
        case "superseded":
            return `superseded by ${cited(state.by)}`;
    }
    const answers = answering(item, received);
    if (answers.length > 0) {
        return `answered by ${answers.map(cited).join(", ")}`;
    }
    switch (state.state) {
        case "waiting":
            if (item.recipient.party !== "operator") {
                return "not told yet";
            }
            return item.rank.name === "waiting on you" ? "waiting on you" : "unread";
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
            return `your answer to ${cited(reason.question)}`;
        case "review":
            return reason.covers.length === 0
                ? "your message, from the review"
                : `your review of ${reason.covers.map(cited).join(", ")}`;
        case "message":
            return reason.of == null ? "your message" : `your reply to ${cited(reason.of)}`;
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
 * sent, `→`, what it is, whom to and where it stands (answered and by what, read, waiting on you, unread, withdrawn, decided);
 * one it was sent, `←`, what it is, for whom where it was passed on, and whether it's told yet. A turn's last words,
 * which lup made a note, aren't: they're the agent's words already shown.
 */
function inboxed(exchanged: Exchanged, whose: Whose): Inboxed[] {
    const spoken = exchanged.sent.filter(({ item }) => !(item.reason.reason === "message" && item.reason.ending === true));
    const its = spoken.map(({ item, text }): Inboxed => {
        const to = item.recipient.party === "operator" ? "you" : whose.name(item.recipient);
        const state = item.state;
        const comment = state.state === "decided" && state.comment ? ["", ...setIn(`your comment: ${state.comment}`)] : [];
        return {
            number: item.number,
            from: true,
            line: dotted(`→ ${cited(item.number)} ${what(item)} to ${to}`, standing(item, exchanged.received)),
            text: [...setIn(text), ...comment],
            where: item.call == null ? { at: item.made } : { call: item.call, at: item.made },
        };
    });
    const theirs = exchanged.received.map(({ item, text }): Inboxed => {
        const passed = item.addressed;
        const ours = passed != null && (passed.agent ?? null) === whose.agent;
        const recipient = item.recipient;
        const head = [`← ${cited(item.number)} ${came(item, whose)}`, passed == null || ours ? "" : `, for ${whose.name(passed)}, which had ended`].join("");
        const onward =
            ours && recipient.party === "conversation" ? `passed on to ${whose.name(recipient)}, this one having ended` : null;
        const state = item.state;
        return {
            number: item.number,
            from: false,
            line: dotted(head, state.state === "waiting" ? "not told yet" : null, onward),
            text: setIn(text),
            where: { at: state.state === "told" ? state.at : item.made },
        };
    });
    return [...its, ...theirs];
}

/**
 * Return the steps and the items in order: an item the conversation sent just after the call that made it, where the
 * record holds it; any other by when it was told, or made, after the last step at or before then. A step its record
 * gives no time takes the time of the last before it, and one before any time counts as before every item, so in a
 * record with no times they're all at its end. Items between the same two steps go in the order they came.
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
        } else {
            const when = new Date(where.at).getTime();
            before[times.findLastIndex((time) => time === null || time <= when) + 1]?.push(item);
        }
    }
    const order = (a: Inboxed, b: Inboxed) =>
        new Date(a.where.at).getTime() - new Date(b.where.at).getTime() || a.number - b.number;
    const turns = (each: Inboxed[]): Turn[] => [...each].sort(order).map((inboxed) => ({ inboxed }));
    return [
        ...entries.flatMap((entry, step): Turn[] => [...turns(before[step] ?? []), { step, entry }, ...turns(after[step] ?? [])]),
        ...turns(before[entries.length] ?? []),
    ];
}

/** Return whether `turn` is the operator's own words, which open an exchange. */
function theirs(turn: Turn): boolean {
    return "entry" in turn && turn.entry.kind === "said" && turn.entry.by === "operator";
}

/** Return when a turn was, where its record says. */
function at(turn: Turn): string | null {
    return "inboxed" in turn ? turn.inboxed.where.at : (turn.entry.at ?? null);
}

/** Say how many of a thing there are: `1 step`, `5 steps`. */
function counted(count: number, one: string): string {
    return `${count} ${one}${count === 1 ? "" : "s"}`;
}

/** Say a call in its line: its tool, and what it did where its record says (`Called.gist`). */
export function called(call: Called): string {
    return call.gist == null ? call.tool : `${call.tool}: ${call.gist}`;
}

/** Return `text`'s lines as they are, each set in by `indent`, but for an empty one; none for no text. */
function lined(text: string, indent: string): string[] {
    if (text === "") {
        return [];
    }
    const lines = text.replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n");
    return lines.map((line) => (line.trim() === "" ? "" : `${indent}${line.trimEnd()}`));
}

/** How long a value given a call may be, as JSON, to show on its argument's line; a longer one is laid out under it. */
const INLINE = 100;

/** Return what a call was given as the lines it's shown in, set in by `indent`: each argument after its name, a value of several lines under it; text as it is. */
export function given(input: unknown, indent: string): string[] {
    if (typeof input === "string") {
        return lined(input, indent);
    }
    if (input === null || typeof input !== "object" || Array.isArray(input)) {
        return lined(JSON.stringify(input, null, 2), indent);
    }
    return Object.entries(input as Record<string, unknown>).flatMap(([name, value]) => {
        if (typeof value === "string") {
            return value.includes("\n") ? [`${indent}${name}:`, ...lined(value, `${indent}${ITEM_INDENT}`)] : [`${indent}${name}: ${value}`];
        }
        const compact = JSON.stringify(value);
        return compact.length <= INLINE ? [`${indent}${name}: ${compact}`] : [`${indent}${name}:`, ...lined(JSON.stringify(value, null, 2), `${indent}${ITEM_INDENT}`)];
    });
}

/**
 * Return a call's input and output as the lines they're shown in under its line, set in by `indent`: what it was given
 * after `input:`, what it returned after `output:`, or `failed:` where the runtime says it failed, `none yet` while it
 * runs; a line saying it's being read before the host has answered, or why it wasn't read.
 */
export function detailed(detail: Detail | undefined, indent: string): string[] {
    if (detail === undefined) {
        return [`${indent}reading its input and output…`];
    }
    if ("refused" in detail) {
        return [`${indent}not read: ${detail.refused}`];
    }
    const call = detail.shown;
    const inner = `${indent}${ITEM_INDENT}`;
    const returned =
        call.output == null ? [`${indent}output: none yet`] : [`${indent}${call.failed ? "failed" : "output"}:`, ...lined(call.output, inner)];
    return [`${indent}input:`, ...given(call.input, inner), ...returned];
}

/**
 * Lay a conversation out as one text: each step in order, the operator's words after `you:`, the agent's as they are,
 * each call a line saying what it did, each run of `RUN` calls or more under one line saying how many of which; each
 * item of lup's inbox it exchanged in a line among them, its text folded under it (`merged`); under each line of the
 * agent's words, the comments on it. Everything since the operator's last words is open; each exchange before them
 * folds under the first line of their words that opened it, and what came before their first words under a line of
 * its own. Each call's input and output fold under its line, as `beside.calls` holds them. Laid out again with more
 * steps, or an item arriving, everything before the last line stays as it was: what arrives is added after it.
 */
export function laid(entries: Entry[], beside: Beside, talk: Talk): Laid {
    const turns = merged(entries, inboxed(beside.exchanged, beside.whose));
    const rows: string[] = [];
    let length = 0;
    const words: Words[] = [];
    const asides: Aside[] = [];
    const blocks: Block[] = [];
    const folds: Folding[] = [];
    const items: Placed[] = [];
    const shown: Shown[] = [];
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
    // A fold under `summary`, of what's written after it up to here, where anything is.
    const fold = (key: string, kind: FoldKind, summary: Span, label: string): Folding | null => {
        if (length <= summary.to) {
            return null;
        }
        const made: Folding = { key, kind, label, summary, from: summary.to, to: length, closed: true };
        folds.push(made);
        return made;
    };
    const comments = talk.comments.map((comment, at) => ({ comment, at }));
    const writeBlocks = (mine: { comment: Remark; at: number }[]) => {
        for (const { comment, at } of mine) {
            const span = write(comment.text);
            blocks.push({ comment: at, ...span });
        }
    };

    // A call's line, and its input and output folded under it where its record gives it an id.
    const writeCall = (entry: Called, indent: string) => {
        const said = `${indent}· ${called(entry)}`;
        const line = aside("call", said);
        if (entry.id == null) {
            return;
        }
        for (const row of detailed(beside.calls.get(entry.id), `${indent}${ITEM_INDENT}${ITEM_INDENT}`)) {
            aside("call-text", row);
        }
        const made = fold(`call ${entry.id}`, "call", line, said.trim());
        if (made !== null) {
            shown.push({ id: entry.id, fold: made });
        }
    };
    let run: { step: number; entry: Called }[] = [];
    const ran = () => {
        const [first] = run;
        if (first === undefined) {
            return;
        }
        if (run.length < RUN) {
            run.forEach(({ entry }) => writeCall(entry, ""));
        } else {
            const said = calls(run.map(({ entry }) => entry.tool));
            const summary = aside("calls", said);
            run.forEach(({ entry }) => writeCall(entry, ITEM_INDENT));
            fold(`calls ${first.step}`, "calls", summary, said);
        }
        run = [];
    };

    // Each exchange before the operator's last words folds under the first line of their words; what came before
    // their first words, under a line of its own.
    const opening = turns.flatMap((turn, index) => (theirs(turn) ? [index] : []));
    const lastWords = opening.at(-1);
    let earlier: { key: string; summary: Span; label: string } | null = null;
    const closeEarlier = () => {
        ran();
        if (earlier !== null) {
            fold(earlier.key, "earlier", earlier.summary, earlier.label);
            earlier = null;
        }
    };
    const firstWords = opening[0];
    if (firstWords !== undefined && firstWords > 0) {
        const before = turns.slice(0, firstWords);
        const steps = before.filter((each) => "entry" in each).length;
        const itemsBefore = before.length - steps;
        const start = before[0] === undefined ? null : at(before[0]);
        const until = turns[firstWords] === undefined ? null : at(turns[firstWords]);
        const ago = start === null || until === null ? "" : `, from ${since(new Date(start), new Date(until))} before your first words`;
        const count = [counted(steps, "step"), ...(itemsBefore === 0 ? [] : [counted(itemsBefore, "item")])].join(", ");
        const label = `earlier · ${count}${ago}`;
        earlier = { key: "before", summary: aside("summary", label), label };
    }

    turns.forEach((turn, index) => {
        if ("inboxed" in turn) {
            ran();
            const { inboxed: item } = turn;
            const line = aside(item.from ? "item-from" : "item-to", item.line);
            for (const row of item.text) {
                aside("item-text", row);
            }
            items.push({ number: item.number, line, fold: fold(`item ${item.number}`, "context", line, item.line) });
            return;
        }
        const { entry, step } = turn;
        if (entry.kind === "called") {
            run.push({ step, entry });
            return;
        }
        if (entry.by === "operator") {
            closeEarlier();
            const rowsSaid = spoken("you", entry.text, true);
            rowsSaid.forEach((row, at) => {
                const span = aside("you", row.text);
                if (at === 0 && index !== lastWords) {
                    earlier = { key: `you ${step}`, summary: span, label: row.text };
                }
            });
            return;
        }
        ran();
        // The agent's words, which are most of it, unlabelled.
        const lines = kept(entry.text, true);
        const own = lines.join("\n");
        const lineStarts = startsOf(lines);
        const mine = comments.filter(({ comment }) => comment.step === step);
        const said: Words = { step, own, lines: [], blocks: [] };
        const before = blocks.length;
        spoken(null, entry.text, true).forEach((row, at) => {
            const span = write(row.text);
            if (row.blank) {
                asides.push({ kind: "agent", ...span });
                return;
            }
            said.lines.push({ from: span.from + row.words, to: span.to, own: row.own, start: span.from });
            writeBlocks(mine.filter(({ comment }) => (under(lineStarts, comment.quote) ?? 0) === at));
        });
        said.blocks = blocks.slice(before);
        words.push(said);
    });
    closeEarlier();

    return { text: rows.join("\n"), words, asides, blocks, folds, items, calls: shown };
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

/** Return where a comment opened on the line at `position` goes: on that line of the agent's words; none on any other line. */
export function opened(laidOut: Laid, position: number): Remark | undefined {
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

/** Return where a comment on the agent's words is about, in the text: the last character of what it quotes; none where its step isn't laid out. */
export function aboutAt(laidOut: Laid, comment: Remark): number | undefined {
    const words = laidOut.words.find((each) => each.step === comment.step);
    if (words === undefined) {
        return undefined;
    }
    return shownIn(words.lines, lastOf(comment.quote), words.lines[0]?.start ?? 0);
}

/** Return `laidOut` moved by `by` in the text: each span of it where it is once the conversation is laid out after `by` characters, as a drawer lays it; its text is still its own, which the drawer replaces by the whole once that's laid out. */
export function shifted(laidOut: Laid, by: number): Laid {
    const span = <S extends Span>(each: S): S => ({ ...each, from: each.from + by, to: each.to + by });
    const folding = (fold: Folding): Folding => ({ ...span(fold), summary: span(fold.summary) });
    const moved = new Map(laidOut.folds.map((fold) => [fold, folding(fold)]));
    const kept = (fold: Folding): Folding => moved.get(fold) ?? folding(fold);
    return {
        text: laidOut.text,
        words: laidOut.words.map((each) => ({ ...each, lines: each.lines.map((line) => ({ ...span(line), start: line.start + by })), blocks: each.blocks.map(span) })),
        asides: laidOut.asides.map(span),
        blocks: laidOut.blocks.map(span),
        folds: laidOut.folds.map(kept),
        items: laidOut.items.map((each) => ({ ...each, line: span(each.line), fold: each.fold === null ? null : kept(each.fold) })),
        calls: laidOut.calls.map((each) => ({ ...each, fold: kept(each.fold) })),
    };
}
