// The review: everything waiting for the operator laid out as one text to read
// and move through, in groups, one per agent, every agent running having one,
// empty or not; their comments in it, each under the line it's on, and their
// messages to each agent under its banner. Under an approval, a held change or a
// write that landed flagged, each file it changes, whole (`code.ts`), its lines
// commented on as the item's own are, the lines that matter in it, by the judge's
// reading, kept in order for the keys to walk; under each item its context. Its
// items by their kind's rank, which the host gives. Each fold has a kind: the
// item whole, a file, a function's or a class's body, a run of unchanged lines,
// the context. What's folded by default: the context, each run of a file's
// unchanged lines away from its changes and the lines that matter, so a held
// change and a flagged write show every change, and, in an approval's file whose
// asks are each on a line, every run of lines away from those, changed ones too;
// an automatic file whole under its header, and an item marked read or left for
// later; a body is open. Each fold is named by what it hides, so an item laid
// out again keeps the folds the operator left; and where the cursor is, said in
// the header over the review, is the group, the item and the folds it's in.
// Pure: the editor (`Review.tsx`) draws it, folds it and lets the comments and
// messages be edited, and the host keeps the draft (`docs/dashboard.md`, *The
// review*). What it shares with a conversation's text is in `comments.ts`.
import { since } from "./agents";
import { shownOnce, type Body, type ChangedFile, type Matter, type Row, type Showing } from "./code";
import {
    calls,
    lastOf,
    passage,
    saying,
    shownIn,
    spoken,
    starts as startsOf,
    under,
    type Block,
    type Line,
    type Span,
} from "./comments";
import { around } from "./folds";
import type { components } from "./generated/api";
import type { FoldKind, ReviewPlace } from "./keys";

export { calls, type Block, type ChangedFile, type Line, type Span };

export type Item = components["schemas"]["Item"];
export type Draft = components["schemas"]["Draft"];
export type Comment = components["schemas"]["Comment"];
export type Letter = components["schemas"]["Letter"];
export type Conversation = components["schemas"]["Conversation"];
export type { Quote } from "./comments";
export type Context = components["schemas"]["Context"];

/** What the operator writes in the review, as its editor holds it: a comment on an item, or a message to an agent. */
export type Written = Comment | Letter;

/** What the host answered, asked for more of an item than its own text: what it showed, or why it refused. */
export type Answered<T> = { shown: T } | { refused: string };

/** What the review shows of each item beyond its own text, by the item's number, once the host has answered: its context, and each file it changes (`changing`). */
export interface Around {
    contexts: Map<number, Answered<Context>>;
    files: Map<number, Answered<ChangedFile[]>>;
}

/**
 * What a line under an item that isn't its own text shows: a fold's summary; a step of its context, the operator's
 * words, the agent's, a run of calls, or the call that made the item; or why the host showed none.
 */
export type Kind = "summary" | "you" | "agent" | "calls" | "anchor" | "refused";

/** A line under an item that isn't its own text, so no comment is on it. */
export interface Aside extends Span {
    kind: Kind;
}

/** A line of a changed file under an item, which comments may be on: the file's header, where `row` is none, or one of its rows, and what it triggered where it's a line that matters. */
export interface Coded extends Span {
    file: ChangedFile;
    row: Row | null;
    matter: Matter | null;
}

/**
 * What folds in an item, by its kind (`FoldKind`): the item whole under its header, folded where it's marked read or
 * left for later; each file it changes under its header, folded where it's automatic; a function's or a class's body
 * under the line declaring it, open; a run of a file's unchanged lines under a summary line, folded; and its context,
 * folded. Each sits whole inside another or beside it. It hides `from` to `to`, from the end of its summary line to the
 * end of its last; a file's and a body's from the end of the comments on their first line, which stay in view.
 */
export interface Fold extends Span {
    item: number;
    kind: FoldKind;
    /**
     * What names it among its item's folds of its kind, by what it hides rather than the row it's laid out on, so an
     * item laid out again keeps each fold as the operator left it: a file by its path; a body by its file and the
     * bodies it's in; a run by its file and what it hides (`Run.name`); an item's own and its context by nothing more.
     */
    name: string;
    /** What the header calls it: the item's own by its header, a file by its path, a body by its name, a run by its summary. */
    label: string;
    /** Whether it's folded until the operator opens it. */
    closed: boolean;
    summary: Span;
}

/** Where a changed file is under its item: from its header to its last line and the comments under it. */
export interface FileSpan extends Span {
    file: ChangedFile;
}

/** What names a group in its banner: its first item, or, for a group with none, the agent's conversation. */
export type Head = { item: Item } | { conversation: Conversation };

/**
 * One group, where it's shown: its banner and, unless it's of the items left for later, the messages to its agent
 * under it, each a comment's block; its items' regions follow it, up to the next group.
 */
export interface Group {
    /** The agent it's of; none for lup's approvals, which no message goes to. */
    conversation: Conversation | null;
    /** What its banner names it by. */
    head: Head;
    later: boolean;
    /** What names its place across layouts: whose it is, and whether it's of what's left for later. */
    place: string;
    banner: Span;
    blocks: Block[];
}

/**
 * One item, where it's shown: its header line, the lines comments may be on (its own, then its files' headers and
 * rows) with its comments among them; then the lines under it, and what folds.
 */
export interface Region {
    item: Item;
    header: Span;
    lines: Line[];
    blocks: Block[];
    /** Its lines that are its files', each with its file and row. */
    code: Coded[];
    /** Where each file it changes is, from its header to its last line and the comments under it. */
    filed: FileSpan[];
    asides: Aside[];
    folds: Fold[];
    /** Where its lines that matter start, in order: a file's header where what it asks is about the file whole, then the first row of each thing a line triggered. */
    stops: number[];
}

/** The review's text, and where each group and each item is in it. */
export interface Laid {
    text: string;
    groups: Group[];
    regions: Region[];
}

export const EMPTY: Draft = { comments: [], letters: [], done: [], parked: [] };

/** Return what names a conversation among others: its repository, runtime, session and subagent. */
export function whose(conversation: Conversation): string {
    return JSON.stringify([conversation.repository, conversation.runtime, conversation.session, conversation.agent ?? null]);
}

/** Return what the operator wrote in a draft as the editor holds it, in one list: the comments, then the messages. */
export function written(draft: Draft): Written[] {
    return [...(draft.comments ?? []), ...(draft.letters ?? [])];
}

/** Return `draft` with `list`, as the editor holds what's written, for its comments and its messages. */
export function withWritten(draft: Draft, list: Written[]): Draft {
    return { ...draft, comments: list.filter(isComment), letters: list.filter(isLetter) };
}

/** Return whether what's written is a message to an agent, rather than a comment on an item. */
export function isLetter(each: Written): each is Letter {
    return "to" in each;
}

function isComment(each: Written): each is Comment {
    return !isLetter(each);
}

/**
 * Return an item's own text as the review shows it: a message's, a friction's or how the work went's words as written,
 * a question's with its decisions, an approval's question and summary; a subagent's end's last message, where lup
 * passed it on.
 */
export function body(item: Item): string {
    const reason = item.reason;
    switch (reason.reason) {
        case "message":
        case "friction":
        case "how it went":
            return reason.text;
        case "stop":
            return reason.why;
        case "ended":
            return reason.said ?? "";
        case "question": {
            const decisions = reason.decisions.map(
                (each, at) => `${at + 1}. ${each.text}\n   lean: ${each.lean}`,
            );
            return [reason.text, ...decisions].join("\n");
        }
        case "approval":
            return `${reason.text}\n${plain(reason.summary)}`;
        case "held":
        case "flagged":
            return `${reason.text}\n${reason.summary}`;
        case "answer":
            return reason.comment;
        case "review":
            return [...(reason.letters ?? []), ...reason.comments].map((each) => each.text).join("\n");
    }
}

/** Return `text` without the terminal's colour codes git colours a diff with. */
export function plain(text: string): string {
    return text.replace(/\u001b\[[0-9;]*m/g, "");
}

/** One line under an item that isn't its own text, and what it shows. */
export interface Said {
    kind: Kind;
    text: string;
}

/** What shows under an item's files: its context, its summary line with the lines that fold under it; or, where the host refused it, a line saying why. */
interface Under {
    summary: Said;
    lines: Said[];
}

/** Return an item's context as the lines it's shown in: each thing said after who said it, its own lines kept; each run of calls in one line; and the call that made the item, marked. */
export function steps(context: Context): Said[] {
    const shown: Said[] = [];
    let run: string[] = [];
    const ran = () => {
        if (run.length > 0) {
            shown.push({ kind: "calls", text: calls(run) });
            run = [];
        }
    };
    context.entries.forEach((entry, at) => {
        if (entry.kind === "called" && at !== context.anchor) {
            run.push(entry.tool);
            return;
        }
        ran();
        if (entry.kind === "called") {
            shown.push({ kind: "anchor", text: `→ called ${entry.tool} · this item` });
            return;
        }
        const who: Kind = entry.by === "operator" ? "you" : "agent";
        shown.push(...spoken(who === "you" ? who : null, entry.text, false).map((row) => ({ kind: who, text: row.text })));
    });
    ran();
    return shown;
}

/** Say what an item's context holds: how many steps, and from whose words and how long before the item. */
function told(item: Item, context: Context): string {
    const count = `context · ${context.entries.length} ${context.entries.length === 1 ? "step" : "steps"}`;
    const first = context.entries[0];
    const yours = first?.kind === "said" && first.by === "operator";
    const before = first?.at == null ? "" : ` ${since(new Date(first.at), new Date(item.made))} before this item`;
    if (!yours && before === "") {
        return count;
    }
    return `${count}, from${yours ? " your words" : ""}${before}`;
}

/** Return the item's context as it shows under the item, of what the host has answered; none before it has. */
function beneath(item: Item, around: Around): Under | null {
    const context = around.contexts.get(item.number);
    if (context === undefined) {
        return null;
    }
    return {
        summary:
            "shown" in context
                ? { kind: "summary", text: told(item, context.shown) }
                : { kind: "refused", text: `no context: ${context.refused}` },
        lines: "shown" in context ? steps(context.shown) : [],
    };
}

/**
 * One line under an item's own text that comments may be on, of a changed file: its header, or one of its rows, the
 * run of unchanged rows it opens, if any, before it, and whether it ends one; what it triggered, where it's a line that
 * matters, and whether it's a stop, the first line of what triggered; the bodies it declares and those it ends; and, for
 * a file with rows, the fold its header opens, folded where the file is automatic, and its last row ends.
 */
interface Filed {
    file: ChangedFile;
    row: Row | null;
    text: string;
    opens: { summary: string; name: string } | null;
    closes: boolean;
    matter: Matter | null;
    stop: boolean;
    declares: Body[];
    finishes: Body[];
    folds: { closed: boolean } | null;
    ends: boolean;
}

/** Whether an item keeps the files it changes beside it, for the review to show under it: an approval, a held change, or a write that landed flagged. */
export function changing(item: Item): boolean {
    const reason = item.reason.reason;
    return reason === "approval" || reason === "held" || reason === "flagged";
}

/**
 * Return what an item's files whose asks are each on a line keep open (`Showing`): an approval's, which may change tens
 * of thousands of lines, the lines that ask alone; a held change's and a flagged write's, every change, as the
 * operator reads them whole.
 */
export function showing(item: Item): Showing {
    return item.reason.reason === "approval" ? "asks" : "changes";
}

/**
 * Return the lines of each file an item changes (`changing`), as the host answered them: each file's header, then its
 * rows, its runs of unchanged ones folding, or for an approval every run away from the lines that ask (`showing`),
 * each body able to fold under the row declaring it, and the whole of each file able to fold under its header, an
 * automatic one folded; none for any other item, or before the host has answered.
 */
function filed(item: Item, around: Around): Filed[] {
    const files = around.files.get(item.number);
    if (!changing(item) || files === undefined || !("shown" in files)) {
        return [];
    }
    return files.shown.flatMap((file) => {
        const laidOut = shownOnce(file, showing(item));
        const header: Filed = {
            file,
            row: null,
            text: laidOut.header,
            opens: null,
            closes: false,
            matter: null,
            stop: laidOut.whole,
            declares: [],
            finishes: [],
            folds: laidOut.rows.length > 0 ? { closed: laidOut.automatic } : null,
            ends: false,
        };
        const matters = new Map(laidOut.matters.map((each) => [each.row, each]));
        const rows = laidOut.rows.map((row, at): Filed => {
            const run = laidOut.runs.find((each) => each.from === at);
            const matter = matters.get(at) ?? null;
            return {
                file,
                row,
                text: row.text,
                opens: run === undefined ? null : { summary: run.summary, name: run.name },
                closes: laidOut.runs.some((each) => each.to === at + 1),
                matter,
                stop: (matter?.notes.length ?? 0) > 0,
                declares: laidOut.bodies.filter((each) => each.from === at),
                finishes: laidOut.bodies.filter((each) => each.to === at),
                folds: null,
                ends: at === laidOut.rows.length - 1,
            };
        });
        return [header, ...rows];
    });
}

/** A group as it's laid out: what names it among the others, the agent it's of, what its banner names it by, and its items. */
interface Grouping {
    key: string;
    conversation: Conversation | null;
    head: Head;
    items: Item[];
}

/**
 * Whether an item is news, to read and mark read rather than answer, as its kind's rank says (`Item.rank`, which the
 * host gives each item): a note, a turn's last words among them, a friction, how the work went, or a stop by choice.
 */
export function news(item: Item): boolean {
    return item.rank.name === "news";
}

/** Whether an item is a write that landed flagged, ranked last, to read or comment on: it waits on no one. */
export function flag(item: Item): boolean {
    return item.rank.name === "flag";
}

/** What Space a or Space x does on an item: answer it, mark it read, say why it does nothing, or nothing. */
export type Answering = { kind: "answer" } | { kind: "read" } | { kind: "say"; text: string } | { kind: "nothing" };

/** Why Space x does nothing on a flagged write, as the page says it. */
export const NEVER_DECLINED = "A flag is read or commented on, never declined.";

/**
 * Return what Space a (`approved`) or Space x does on `item`: approve or decline an approval or a held change; on a
 * flagged write, Space a marks it read, "looks good", as Space d does, and Space x says it's never declined; on any
 * other item, nothing.
 */
export function answering(item: Item, approved: boolean): Answering {
    switch (item.reason.reason) {
        case "approval":
        case "held":
            return { kind: "answer" };
        case "flagged":
            return approved ? { kind: "read" } : { kind: "say", text: NEVER_DECLINED };
        default:
            return { kind: "nothing" };
    }
}

/**
 * Return `items` in groups, one per agent, and one per banner of lup's approvals: the group whose first item ranks
 * first first (`Item.rank`: what's waiting on the operator, then news, then flags), then the group with the newest item
 * first; in each, its items by their rank, each rank's in their own order.
 */
function grouped(items: Item[], banner: (item: Item) => string): Grouping[] {
    const groups = new Map<string, Grouping>();
    for (const item of items) {
        const sender = item.sender;
        const conversation = sender.party === "conversation" ? sender : null;
        const key = conversation === null ? `lup ${banner(item)}` : whose(conversation);
        const group = groups.get(key) ?? { key, conversation, head: { item }, items: [] };
        groups.set(key, { ...group, items: [...group.items, item] });
    }
    const ranked = [...groups.values()].map((group) => ({
        ...group,
        items: group.items.toSorted((a, b) => a.rank.order - b.rank.order),
    }));
    const first = (group: Grouping) => Math.min(...group.items.map((each) => each.rank.order));
    const made = (group: Grouping) => Math.max(...group.items.map((each) => new Date(each.made).getTime()));
    const numbered = (group: Grouping) => Math.max(...group.items.map((each) => each.number));
    return ranked.sort((a, b) => first(a) - first(b) || made(b) - made(a) || numbered(b) - numbered(a));
}

/** Return what names a group's place across layouts: `key`, whose it is, and whether it's of what's left for later. */
function placeOf(key: string, later: boolean): string {
    return `${later ? "later" : "now"} ${key}`;
}

/** Return a group for each of `conversations` with none among `groups`, in their order, once each. */
function emptyGroups(conversations: Conversation[], groups: Grouping[]): Grouping[] {
    const keys = new Set(groups.map((each) => each.key));
    return conversations.flatMap((conversation) => {
        const key = whose(conversation);
        if (keys.has(key)) {
            return [];
        }
        keys.add(key);
        return [{ key, conversation, head: { conversation }, items: [] }];
    });
}

/** Say how long an item has waited, to the minute: what came in under a minute ago is just in. */
export function waited(made: string, now: Date): string {
    const at = new Date(made);
    return now.getTime() - at.getTime() < 60_000 ? "just in" : `waiting ${since(at, now)}`;
}

/** Say whether an item is new to the operator: made after they last settled one of theirs, `reviewed`; none before their first. */
export function fresh(item: Item, reviewed: string | null | undefined): boolean {
    return reviewed != null && new Date(item.made) > new Date(reviewed);
}

/**
 * Lay `items` out as one text, in groups, one per agent, each under its banner: those with items now first, by the
 * rank of their first item (`Item.rank`), the newest first; then a group for each agent of `agents` (those running, in
 * the tree's order) with none, and for each the draft writes to with none; then the parked items' groups. Under each
 * banner but the parked ones', the draft's messages to its agent; then each item, by its rank, under a header naming
 * it, each comment of the draft on it under the
 * line it's on: a comment on a passage under the passage's last line, one on the item whole under its header. Under
 * each item's own text, what the host has answered of it: each file it changes (`changing`), its header
 * then its lines, each run of unchanged ones folding under a summary line; then the item's context, a summary line
 * with the lines that fold under it. Where the host showed none, a line says why.
 *
 * `places` are where the groups were laid out before in this sitting (`Group.place`, in order): each among them keeps
 * its place, items coming and going, and any other comes after them, in the order above.
 */
export function laid(
    items: Item[],
    agents: Conversation[],
    banner: (head: Head, parked: boolean) => string,
    header: (item: Item, parked: boolean) => string,
    draft: Draft,
    around: Around,
    places: readonly string[] = [],
): Laid {
    const parked = draft.parked ?? [];
    const done = draft.done ?? [];
    const comments = draft.comments ?? [];
    const letters = draft.letters ?? [];
    const now = grouped(items.filter((each) => !parked.includes(each.number)), (item) => banner({ item }, false));
    const empty = emptyGroups([...agents, ...letters.map((each) => each.to)], now);
    const later = grouped(items.filter((each) => parked.includes(each.number)), (item) => banner({ item }, true));
    let text = "";
    const groups: Group[] = [];
    const regions: Region[] = [];
    for (const group of kept([...now, ...empty], false)) {
        layGroup(group, false);
    }
    for (const group of kept(later, true)) {
        layGroup(group, true);
    }
    return { text, groups, regions };

    /** Return `section` with each group laid out before in its place, any other after them, in its own order. */
    function kept(section: Grouping[], isParked: boolean): Grouping[] {
        const rank = (group: Grouping) => {
            const at = places.indexOf(placeOf(group.key, isParked));
            return at < 0 ? places.length : at;
        };
        return [...section].sort((a, b) => rank(a) - rank(b));
    }

    function layGroup(group: Grouping, isParked: boolean): void {
        const said = banner(group.head, isParked);
        const opening = { from: text.length, to: text.length + said.length };
        text += `${said}\n`;
        const blocks: Block[] = [];
        if (!isParked) {
            letters.forEach((letter, at) => {
                if (whose(letter.to) === group.key) {
                    const from = text.length;
                    text += `${letter.text}\n`;
                    blocks.push({ comment: comments.length + at, from, to: from + letter.text.length });
                }
            });
        }
        if (group.items.length === 0 && blocks.length > 0) {
            text += "\n";
        }
        groups.push({
            conversation: group.conversation,
            head: group.head,
            later: isParked,
            place: placeOf(group.key, isParked),
            banner: opening,
            blocks,
        });
        for (const item of group.items) {
            layItem(item, isParked);
        }
    }

    function layItem(item: Item, isParked: boolean): void {
        const files = filed(item, around);
        // Its own lines, then its files': the text comments are placed in, by where each quote ends.
        const own = [...body(item).split("\n"), ...files.map((each) => each.text)];
        const starts = startsOf(own);
        const ownCount = own.length - files.length;
        // Each comment on the item, by the line it's under, once.
        const placed = new Map<number | null, { comment: Comment; at: number }[]>();
        comments.forEach((comment, at) => {
            if (comment.item === item.number) {
                const line = under(starts, comment.quote);
                placed.set(line, [...(placed.get(line) ?? []), { comment, at }]);
            }
        });
        const blocks: Block[] = [];
        const lines: Line[] = [];
        const code: Coded[] = [];
        const asides: Aside[] = [];
        const folds: Fold[] = [];
        const writeBlocks = (line: number | null) => {
            for (const { comment, at } of placed.get(line) ?? []) {
                const from = text.length;
                text += `${comment.text}\n`;
                blocks.push({ comment: at, from, to: from + comment.text.length });
            }
        };
        const writeLine = (line: string, at: number): Line => {
            const from = text.length;
            text += `${line}\n`;
            const written = { from, to: from + line.length, own: starts[at] ?? 0 };
            lines.push(written);
            return written;
        };
        const writeAside = (said: Said): Aside => {
            const from = text.length;
            text += `${said.text}\n`;
            const aside = { kind: said.kind, from, to: from + said.text.length };
            asides.push(aside);
            return aside;
        };
        const head = header(item, isParked);
        const headFrom = text.length;
        text += `${head}\n`;
        writeBlocks(null);
        own.slice(0, ownCount).forEach((line, at) => {
            writeLine(line, at);
            writeBlocks(at);
        });
        const stops: number[] = [];
        const filedSpans: FileSpan[] = [];
        // What each fold under the item opened is, until the line ending it: the run, the file, each body by its name.
        let run: { summary: Aside; name: string } | null = null;
        let whole: { summary: Span; from: number; closed: boolean } | null = null;
        const bodies = new Map<string, { summary: Span; from: number }>();
        files.forEach((each, index) => {
            const path = each.file.path;
            if (each.opens !== null) {
                run = { summary: writeAside({ kind: "summary", text: each.opens.summary }), name: each.opens.name };
            }
            const at = ownCount + index;
            const written = writeLine(each.text, at);
            const span = { from: written.from, to: written.to };
            code.push({ ...span, file: each.file, row: each.row, matter: each.matter });
            if (each.stop) {
                stops.push(written.from);
            }
            const fold = (kind: FoldKind, name: string, label: string, closed: boolean, summary: Span, from: number) =>
                folds.push({ item: item.number, kind, name: name === "" ? path : `${path} ${name}`, label, closed, summary, from, to: written.to });
            const ran: { summary: Aside; name: string } | null = run;
            if (each.closes && ran !== null) {
                const summary = { from: ran.summary.from, to: ran.summary.to };
                fold("lines", ran.name, text.slice(summary.from, summary.to), true, summary, summary.to);
                run = null;
            }
            for (const body of each.finishes) {
                const declared = bodies.get(body.name);
                if (declared !== undefined) {
                    fold("body", body.name, body.names.at(-1) ?? "", false, declared.summary, declared.from);
                    bodies.delete(body.name);
                }
            }
            const opening: { summary: Span; from: number; closed: boolean } | null = whole;
            if (each.ends && opening !== null) {
                fold("file", "", path, opening.closed, opening.summary, opening.from);
                whole = null;
            }
            writeBlocks(at);
            // A file and a body fold under their first line and the comments on it, which stay in view.
            if (each.folds !== null) {
                whole = { summary: span, from: text.length - 1, closed: each.folds.closed };
            }
            for (const body of each.declares) {
                bodies.set(body.name, { summary: span, from: text.length - 1 });
            }
            if (each.row === null) {
                filedSpans.push({ file: each.file, from: written.from, to: text.length - 1 });
            } else {
                const last = filedSpans.at(-1);
                if (last !== undefined) {
                    last.to = text.length - 1;
                }
            }
        });
        const refused = around.files.get(item.number);
        if (refused !== undefined && "refused" in refused) {
            writeAside({ kind: "refused", text: `no files: ${refused.refused}` });
        }
        const context = beneath(item, around);
        if (context !== null) {
            const summary = writeAside(context.summary);
            const last = context.lines.map(writeAside).at(-1);
            if (last !== undefined) {
                const shown = { from: summary.from, to: summary.to };
                folds.push({ item: item.number, kind: "context", name: "", label: "context", closed: true, summary: shown, from: summary.to, to: last.to });
            }
        }
        // The item whole folds under its header, what folds within it inside: folded once it's marked read, or left for later.
        const headed = { from: headFrom, to: headFrom + head.length };
        const closed = isParked || done.includes(item.number);
        folds.push({ item: item.number, kind: "item", name: "", label: head, closed, summary: headed, from: headed.to, to: text.length - 1 });
        text += "\n";
        regions.push({
            item,
            header: { from: headFrom, to: headFrom + head.length },
            lines,
            blocks,
            code,
            filed: filedSpans,
            asides,
            folds,
            stops,
        });
    }
}

/** Return where going to an item lands: on its first line that matters, as the judge read its files, unless it's folded whole, marked read or left for later; else on its header. */
export function arrival(region: Region): number {
    const whole = region.folds.some((each) => each.kind === "item" && each.closed);
    return (whole ? undefined : region.stops[0]) ?? region.header.from;
}

/** Return the stop after the line starting at `line`, or before it, of `stops`, in the text's order; none past the last, or before the first. */
export function stepped(stops: number[], line: number, forward: boolean): number | undefined {
    return forward ? stops.find((each) => each > line) : [...stops].reverse().find((each) => each < line);
}

/** Return the last of `spans`, in the text's order, starting at or before `position`. */
function lastFrom<T>(spans: T[], from: (each: T) => number, position: number): T | undefined {
    return spans.findLast((each) => from(each) <= position);
}

/** Return the region `position` is in: its header, its lines, its comments, or the blank line after it; none on a group's banner or the messages under it. */
export function regionAt(laidOut: Laid, position: number): Region | undefined {
    const region = lastFrom(laidOut.regions, (each) => each.header.from, position);
    const group = lastFrom(laidOut.groups, (each) => each.banner.from, position);
    return region !== undefined && (group === undefined || region.header.from > group.banner.from) ? region : undefined;
}

/** Return the group `position` is on: on its banner, the messages under it, or the blank line after them; none on an item. */
export function groupAt(laidOut: Laid, position: number): Group | undefined {
    const region = lastFrom(laidOut.regions, (each) => each.header.from, position);
    const group = lastFrom(laidOut.groups, (each) => each.banner.from, position);
    return group !== undefined && (region === undefined || group.banner.from > region.header.from) ? group : undefined;
}

/** Return whether two of what's written are the same one, whatever it says: a comment on the same passage of the same item, or a message to the same agent. */
function same(a: Written, b: Written): boolean {
    if (isLetter(a) || isLetter(b)) {
        return isLetter(a) && isLetter(b) && whose(a.to) === whose(b.to);
    }
    return a.item === b.item && a.quote?.start === b.quote?.start && a.quote?.end === b.quote?.end;
}

/**
 * Return where the cursor goes as the review is laid out again, from `before` and what was written in it to `after`
 * and what's written now, where what it was on at `head` is gone, as a reply sent takes what it covered: from a
 * comment or a message gone, back on what it was about (`aboutAt`), the last character of its passage, its item's
 * header, its group's banner; from an item gone, or what it was about gone too, onto its group's banner. None where
 * what it was on is still there, or its group is gone too, where the text's changes carry it.
 */
export function stranded(before: Laid, wrote: Written[], after: Laid, writes: Written[], head: number): number | undefined {
    const group = lastFrom(before.groups, (each) => each.banner.from, head);
    const banner = after.groups.find((each) => each.place === group?.place)?.banner.from;
    const block = blockAt(before, head);
    const was = block === undefined ? undefined : wrote[block.comment];
    if (was !== undefined) {
        if (writes.some((each) => same(each, was))) {
            return undefined;
        }
        const region = isLetter(was) ? undefined : after.regions.find((each) => each.item.number === was.item);
        return isLetter(was) || region === undefined ? banner : commentedAt(region, was);
    }
    const region = regionAt(before, head);
    const gone = region !== undefined && !after.regions.some((each) => each.item.number === region.item.number);
    return gone ? banner : undefined;
}

/** Return where the cursor at `head` is, outside insert mode, for the line of keys: what it's on, by what the keys there do. */
export function placeAt(laidOut: Laid, head: number): Exclude<ReviewPlace, "insert"> {
    if (laidOut.text === "") {
        return "nothing";
    }
    if (blockAt(laidOut, head) !== undefined) {
        return "written";
    }
    const group = groupAt(laidOut, head);
    if (group !== undefined) {
        return group.conversation === null ? "approvals" : "banner";
    }
    const region = regionAt(laidOut, head);
    if (region === undefined || asideAt(region, head) !== undefined) {
        return "aside";
    }
    const reason = region.item.reason.reason;
    if (codeAt(region, head) !== undefined) {
        return reason === "flagged" ? "flagged" : "file";
    }
    return reason === "approval" || reason === "held" ? "change" : "item";
}

/** One part of what the header over the review says: whom what's being written goes to, the group, or a fold the cursor is in, by its kind. */
export interface Where {
    kind: "to" | "group" | FoldKind;
    text: string;
}

/** How the header names what it says: a group, by its banner; an item, by its header; a conversation, as the tree calls it. */
export interface Naming {
    group: (group: Group) => string;
    item: (region: Region) => string;
    party: (conversation: Conversation) => string;
}

/** Return the conversation a comment on `item` goes to: the session whose push asked an approval, none where none did; the agent that sent any other. */
export function recipient(item: Item): Conversation | null {
    if (item.reason.reason === "approval") {
        return item.reason.pushed_by ?? null;
    }
    return item.sender.party === "conversation" ? item.sender : null;
}

/**
 * Return what the header over the review says with the cursor at `head`: while a comment or a message is being written
 * (`writing`; `wrote`, what's written as the editor holds it), whom it goes to; then the group the cursor is in, the
 * item, the file, and each fold it's in within them, a body, a run of lines, or the item's context. Nothing before the
 * first group, as where nothing's waiting.
 */
export function heading(laidOut: Laid, head: number, writing: boolean, wrote: Written[], naming: Naming): Where[] {
    const group = lastFrom(laidOut.groups, (each) => each.banner.from, head);
    if (group === undefined) {
        return [];
    }
    const block = writing ? blockAt(laidOut, head) : undefined;
    const being = block === undefined ? undefined : wrote[block.comment];
    const goesTo = (written: Written): Conversation | null => {
        if (isLetter(written)) {
            return written.to;
        }
        const item = laidOut.regions.find((each) => each.item.number === written.item)?.item;
        return item === undefined ? null : recipient(item);
    };
    const party = being === undefined ? undefined : goesTo(being);
    const going: Where[] =
        party === undefined
            ? []
            : [{ kind: "to", text: party === null ? "to no agent: no session's push asked it" : `to ${naming.party(party)}` }];
    const region = regionAt(laidOut, head);
    if (region === undefined) {
        return [...going, { kind: "group", text: naming.group(group) }];
    }
    const file = region.filed.find((each) => head >= each.from && head <= each.to);
    const inner = around(region.folds, head).filter((each) => each.kind !== "item" && each.kind !== "file");
    return [
        ...going,
        { kind: "group", text: naming.group(group) },
        { kind: "item", text: naming.item(region) },
        ...(file === undefined ? [] : [{ kind: "file" as const, text: file.file.path }]),
        ...inner.map((each) => ({ kind: each.kind, text: each.label })),
    ];
}

/** Return every comment and message shown, as blocks of the editor's list of what's written. */
export function blocksOf(laidOut: Laid): Block[] {
    return [...laidOut.groups.flatMap((each) => each.blocks), ...laidOut.regions.flatMap((each) => each.blocks)];
}

/** Return the comment or message shown at `position`, where it's in one; a comment's end counts, so an empty one can be typed in. */
export function blockAt(laidOut: Laid, position: number): Block | undefined {
    return blocksOf(laidOut).find((each) => position >= each.from && position <= each.to);
}

/** Return a message to the agent `group` is of, as it's opened: empty; none for a group no message goes to. */
function letterTo(group: Group): Letter | undefined {
    return group.conversation === null ? undefined : { to: group.conversation, text: "" };
}

/** Return the item's own line shown at `position`, where it's on one. */
export function lineAt(region: Region, position: number): Line | undefined {
    return region.lines.find((each) => position >= each.from && position <= each.to);
}

/** Return the line under an item that isn't its own text shown at `position`, where it's on one. */
export function asideAt(region: Region, position: number): Aside | undefined {
    return region.asides.find((each) => position >= each.from && position <= each.to);
}

/** Return the folds of the item `position` is in, which `zr`, `zm`, `zR`, `zM` and Space `z` reach: none on a group's banner or the messages under it. */
export function foldsOf(laidOut: Laid, position: number): Fold[] {
    return regionAt(laidOut, position)?.folds ?? [];
}

/** Return the innermost fold `position` is in: on its summary line or the lines it hides. */
export function foldAt(laidOut: Laid, position: number): Fold | undefined {
    return around(
        laidOut.regions.flatMap((each) => each.folds),
        position,
    ).at(-1);
}

/** Return what names a fold across layouts: its item's number, what it holds, and which of those it is. */
export function foldKey(fold: Pick<Fold, "item" | "kind" | "name">): string {
    return `${fold.item} ${fold.kind} ${fold.name}`;
}

/** Return where the first of `code` ending at or after `position` is among them, found by halving: they're in the text's order. */
export function codeFrom(code: Coded[], position: number): number {
    let low = 0;
    let high = code.length;
    while (low < high) {
        const middle = (low + high) >> 1;
        if ((code[middle]?.to ?? 0) < position) {
            low = middle + 1;
        } else {
            high = middle;
        }
    }
    return low;
}

/** Return the line of a changed file shown at `position`, where it's on one. */
export function codeAt(region: Region, position: number): Coded | undefined {
    const found = region.code[codeFrom(region.code, position)];
    return found !== undefined && position >= found.from && position <= found.to ? found : undefined;
}

/** How a line of a changed file is marked where a comment quotes it, as a diff marks it. */
const SIGNS: Record<Row["change"], string> = { added: "+", removed: "-", same: " " };

/**
 * Say the passage `from` to `to` selects on `lines` as a comment quotes it, so the agent can find it: the item's own
 * words as they are; a changed file's lines under the file's path and where they are in it (`path:12-14`, the
 * numbers what the file becomes, or what it was where they're all removed), each marked as a diff marks it; a file's
 * header alone, its path.
 */
function said(text: string, region: Region, lines: Line[], from: number, to: number): string {
    const parts = lines.map((line) => ({
        line,
        coded: codeAt(region, line.from),
        text: text.slice(Math.max(line.from, from), Math.min(line.to, Math.max(to, line.from))),
    }));
    const groups: (typeof parts)[] = [];
    for (const part of parts) {
        const last = groups.at(-1);
        const same = last?.[0]?.coded?.file === part.coded?.file;
        if (last !== undefined && same) {
            last.push(part);
        } else {
            groups.push([part]);
        }
    }
    return groups
        .map((group) => {
            const file = group[0]?.coded?.file;
            if (file === undefined) {
                return group.map((each) => each.text).join("\n");
            }
            const rows = group.flatMap((each) => (each.coded?.row == null ? [] : [{ row: each.coded.row, text: each.text }]));
            const kept = rows.filter((each) => each.row.side === "after");
            const numbered = (kept.length > 0 ? kept : rows).map((each) => each.row.number);
            const span = numbered.length === 0 ? "" : `:${spanOf(numbered)}`;
            const before = kept.length === 0 && rows.length > 0 ? ", as it was before the change" : "";
            return [`${file.path}${span}${before}`, ...rows.map((each) => `${SIGNS[each.row.change]}${each.text}`)].join(
                "\n",
            );
        })
        .join("\n");
}

/** Say a run of line numbers as a span: `12`, or `12-14`. */
function spanOf(numbers: number[]): string {
    const first = Math.min(...numbers);
    const last = Math.max(...numbers);
    return first === last ? `${first}` : `${first}-${last}`;
}

/**
 * Return where a comment opened on the line at `position` goes: on that line of its item, or on the item whole from
 * its header or an empty line of its own; on a line of a changed file, or its header, empty or not. On a group's
 * banner, a message to its agent, laid out under its group among those to answer now, from the banner of what's left
 * for later too. None on a line no comment is on, or on the banner of lup's approvals.
 */
export function opened(laidOut: Laid, position: number): Written | undefined {
    const group = groupAt(laidOut, position);
    if (group !== undefined) {
        return letterTo(group);
    }
    const region = regionAt(laidOut, position);
    if (region === undefined || asideAt(region, position) !== undefined) {
        return undefined;
    }
    const line = lineAt(region, position);
    const shown = line === undefined ? "" : laidOut.text.slice(line.from, line.to);
    if (line === undefined || (shown === "" && codeAt(region, line.from) === undefined)) {
        return { item: region.item.number, quote: null, text: "" };
    }
    return {
        item: region.item.number,
        quote: { text: said(laidOut.text, region, [line], line.from, line.to), start: line.own, end: line.own + shown.length },
        text: "",
    };
}

/**
 * Return a comment on the passage `from` to `to` selects, counted in its item's text, its own and its files'; a
 * message to a group's agent where it's on its banner, which no comment quotes; none where it isn't all inside one
 * item's lines, or one group's.
 */
export function quoted(laidOut: Laid, from: number, to: number): Written | undefined {
    const group = groupAt(laidOut, from);
    if (group !== undefined) {
        return group === groupAt(laidOut, Math.max(to - 1, from)) ? letterTo(group) : undefined;
    }
    const region = regionAt(laidOut, from);
    const first = region === undefined ? undefined : lineAt(region, from);
    const last = region === undefined ? undefined : lineAt(region, Math.max(to - 1, from));
    if (region === undefined || first === undefined || last === undefined || to <= from) {
        return undefined;
    }
    const own = region.lines.map((each) => laidOut.text.slice(each.from, each.to)).join("\n");
    const quote = passage(own, first, last, from, to);
    const lines = region.lines.slice(region.lines.indexOf(first), region.lines.indexOf(last) + 1);
    if (lines.every((each) => codeAt(region, each.from) === undefined)) {
        return { item: region.item.number, quote, text: "" };
    }
    return { item: region.item.number, quote: { ...quote, text: said(laidOut.text, region, lines, from, to) }, text: "" };
}

/** Say an item's comments as one answer, as its agent reads them: each under the passage it quotes, set off as a mail quotes, in the order they were written; those on the whole after. */
export function answer(comments: Comment[]): string {
    const saying = comments.filter((each) => each.text.trim() !== "");
    const quoted = saying.filter((each) => each.quote != null).sort((a, b) => (a.quote?.start ?? 0) - (b.quote?.start ?? 0));
    const whole = saying.filter((each) => each.quote == null);
    const parts = quoted.map((each) => {
        const lines = (each.quote?.text ?? "").split("\n").map((line) => (line === "" ? ">" : `> ${line}`));
        return `${lines.join("\n")}\n\n${each.text.trim()}`;
    });
    return [...parts, ...whole.map((each) => each.text.trim())].join("\n\n");
}

/** Return where in the text an offset of an item's own text is shown. */
export function shownAt(region: Region, offset: number): number {
    return shownIn(region.lines, offset, region.header.to);
}

/**
 * Return where what's written, shown at `block`, is about, which Ctrl+Enter ending it goes back to: a message's
 * banner; the last character of the passage a comment quotes, where reading carries on, or its item's header for one
 * on the item whole.
 */
export function aboutAt(laidOut: Laid, written: Written, block: Block): number | undefined {
    if (isLetter(written)) {
        return groupAt(laidOut, block.from)?.banner.from;
    }
    const region = regionAt(laidOut, block.from);
    return region === undefined ? undefined : commentedAt(region, written);
}

/** Return where a comment on `region`'s item is about: the last character of the passage it quotes, or the item's header for one on the item whole. */
function commentedAt(region: Region, comment: Comment): number {
    return comment.quote == null ? region.header.from : shownAt(region, lastOf(comment.quote));
}

/** Return `draft` with `number` in `list` if it wasn't, and out of it if it was. */
export function toggled(draft: Draft, list: "done" | "parked", number: number): Draft {
    const present = draft[list] ?? [];
    const next = present.includes(number) ? present.filter((each) => each !== number) : [...present, number];
    return { ...draft, [list]: next };
}

/** Return the items a draft answers: each with a comment that says something, or marked done, but the parked ones. */
export function covered(draft: Draft): number[] {
    const parked = draft.parked ?? [];
    const mentioned = [
        ...(draft.comments ?? []).filter((each) => each.text.trim() !== "").map((each) => each.item),
        ...(draft.done ?? []),
    ];
    return [...new Set(mentioned)].filter((each) => !parked.includes(each)).sort((a, b) => a - b);
}

/** Return the messages a draft sends: those that say something. */
export function messages(draft: Draft): Letter[] {
    return saying(draft.letters ?? []);
}

/** Return `draft` as it's sent: without the comments and messages that say nothing, each without the trailing space Esc leaves in it. */
export function pruned(draft: Draft): Draft {
    const trimmed = <W extends Written>(list: W[]) => saying(list).map((each) => ({ ...each, text: each.text.trimEnd() }));
    return { ...draft, comments: trimmed(draft.comments ?? []), letters: trimmed(draft.letters ?? []) };
}
