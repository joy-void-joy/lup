// The review: everything waiting for the operator laid out as one text to read
// and move through, in groups, one per agent, every agent running having one,
// empty or not; their comments in it, each under the line it's on, and their
// messages to each agent under its banner. Under an approval or a held change,
// each file it changes, whole (`code.ts`), its lines commented on as the item's
// own are, the lines that matter in it, by the judge's reading, kept in order
// for the keys to walk; under each item its context. At the end of each agent's
// group, after its items, its drawers (`docs/dashboard.md`, *The drawers*): its
// task list, its trace since the operator's last message, what its branch
// changed since they approved it, each file laid out as an item's, and its whole
// conversation (`conversation.ts`), each a fold of its own kind, folded until
// opened; a comment in the trace, the conversation or on the changed files is a
// remark to the agent, which records the version of the code it was written on.
// Its groups and items in the order they arrived, never sorted again, so what
// the operator reads stays put as items come; their kind's rank, which the host
// gives, says only which `]a` and `[a` stop at. Each fold has a kind: the item
// whole, a file, a function's or a class's body, a run of unchanged lines, the
// context, a drawer. What's folded by default: the context, each run of a file's
// unchanged lines away from its changes and the lines that matter, so a held
// change and a drawer's file show every change, and, in an approval's file whose
// asks are each on a line, every run of lines away from those, changed ones too;
// an automatic file whole under its header, an item marked read or left for
// later, and each drawer; a body is open, but a new module's in its drawer,
// which shows its design. Each fold is named by what it hides, so an item or a
// drawer laid out again keeps the folds the operator left; and where the cursor
// is, said in the header over the review, is the group, the item or the drawer
// and the folds it's in. Pure: the editor (`Review.tsx`) draws it, folds it and
// lets what's written be edited, and the host keeps the draft
// (`docs/dashboard.md`, *The review*). What it shares with a conversation's
// text is in `comments.ts`.
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
import {
    UNEXCHANGED,
    aboutAt as aboutTalk,
    history,
    laid as laidTalk,
    opened as openedTalk,
    quoted as quotedTalk,
    shifted,
    type Entry,
    type Exchanged,
    type Laid as Talk,
} from "./conversation";
import { around } from "./folds";
import type { components } from "./generated/api";
import { DRAWERS, type DrawerKind, type FoldKind, type ReviewPlace } from "./keys";

export { calls, type Block, type ChangedFile, type Line, type Span };

export type Item = components["schemas"]["Item"];
export type Draft = components["schemas"]["Draft"];
export type Comment = components["schemas"]["Comment"];
export type Letter = components["schemas"]["Letter"];
export type Remark = components["schemas"]["Remark"];
export type Conversation = components["schemas"]["Conversation"];
export type { Quote } from "./comments";
export type Context = components["schemas"]["Context"];
export type Since = components["schemas"]["Since"];
export type SinceFile = components["schemas"]["SinceFile"];
export type Task = components["schemas"]["Task"];
export type Usage = components["schemas"]["Usage"];
export type { Entry, Exchanged };

/** What the operator writes in the review, as its editor holds it: a comment on an item, a message to an agent, or a remark in one of its drawers. */
export type Written = Comment | Letter | Remark;

/** What the host answered, asked for more of an item than its own text: what it showed, or why it refused. */
export type Answered<T> = { shown: T } | { refused: string };

/** What the review shows of each item beyond its own text, by the item's number, once the host has answered: its context, and each file it changes (`changing`). */
export interface Around {
    contexts: Map<number, Answered<Context>>;
    files: Map<number, Answered<ChangedFile[]>>;
}

/**
 * What the page holds of one agent, for its banner and its drawers: its conversation's steps as read so far, its task
 * list and what its context holds, the items it exchanged where they were asked, what its branch changed since the
 * operator approved it as they read it (`since`), and what stands now where that differs (`latest`), which Space `l`
 * brings in. None of a drawer's before the host has answered.
 */
export interface AgentDrawers {
    entries: Entry[];
    tasks: Task[];
    usage: Usage | null;
    exchanged: Exchanged | null;
    since: Since | null;
    latest: Since | null;
}

/** Each agent's drawers' data, by `whose` its conversation is. */
export type Drawers = Map<string, AgentDrawers>;

export const UNREAD: AgentDrawers = { entries: [], tasks: [], usage: null, exchanged: null, since: null, latest: null };

/**
 * What a line under an item or in a drawer that isn't the operator's or the agent's own text shows: a fold's summary;
 * a step of a context or a conversation, the operator's words, the agent's, a run of calls, or the call that made the
 * item; an item of the inbox in a conversation, and a line of its text; a task; or why the host showed none.
 */
export type Kind = "summary" | "you" | "agent" | "calls" | "anchor" | "refused" | "item-from" | "item-to" | "item-text" | "task";

/** A line under an item that isn't its own text, so no comment is on it. */
export interface Aside extends Span {
    kind: Kind;
}

/** A line of a changed file under an item or in a drawer, which comments may be on: the file's header, where `row` is none, or one of its rows, and what it triggered where it's a line that matters. */
export interface Coded extends Span {
    file: ChangedFile;
    row: Row | null;
    matter: Matter | null;
}

/**
 * What folds in an item or a drawer, by its kind (`FoldKind`): the item whole under its header, folded where it's
 * marked read or left for later; a drawer under its summary line, folded until opened; each file it changes under its
 * header, folded where it's automatic; a function's or a class's body under the line declaring it, open but in a new
 * module of a drawer; a run of a file's unchanged lines under a summary line, folded; and its context, folded. Each
 * sits whole inside another or beside it. It hides `from` to `to`, from the end of its summary line to the end of its
 * last; a file's and a body's from the end of the comments on their first line, which stay in view.
 */
export interface Fold extends Span {
    /** What it's in: an item, by its number, or a drawer, by its agent and kind (`ownerOf`). */
    of: string;
    kind: FoldKind;
    /**
     * What names it among its owner's folds of its kind, by what it hides rather than the row it's laid out on, so an
     * item laid out again keeps each fold as the operator left it: a file by its path; a body by its file and the
     * bodies it's in; a run by its file and what it hides (`Run.name`); an item's own, a drawer's and its context by
     * nothing more.
     */
    name: string;
    /** What the header calls it: the item's own by its header, a drawer by its summary, a file by its path, a body by its name, a run by its summary. */
    label: string;
    /** Whether it's folded until the operator opens it. */
    closed: boolean;
    summary: Span;
}

/** Where a changed file is under its item or in its drawer: from its header to its last line and the comments under it. */
export interface FileSpan extends Span {
    file: ChangedFile;
}

/** What names a group in its banner: its first item, or, for a group with none, the agent's conversation. */
export type Head = { item: Item } | { conversation: Conversation };

/**
 * One group, where it's shown: its banner and, unless it's of the items left for later, the messages to its agent
 * under it, each a comment's block; its items' regions follow it, then its drawers, up to the next group.
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
    drawers: Drawer[];
}

/**
 * What an item and a drawer lay out alike: a header line, the lines comments may be on (an item's own, a file's
 * headers and rows, the agent's words) with the comments among them; the lines under it that aren't, and what folds.
 */
export interface Scope {
    /** What names it among the review's folds' owners (`Fold.of`). */
    of: string;
    header: Span;
    lines: Line[];
    blocks: Block[];
    /** Its lines that are a file's, each with its file and row. */
    code: Coded[];
    /** Where each file it shows is, from its header to its last line and the comments under it. */
    filed: FileSpan[];
    asides: Aside[];
    folds: Fold[];
    /** Where its lines that matter start, in order: a file's header where what it asks is about the file whole, then the first row of each thing a line triggered. */
    stops: number[];
}

/** One item, where it's shown. */
export interface Region extends Scope {
    item: Item;
}

/** One of an agent's drawers, where it's shown: which, whose, and, for its trace and its conversation, the conversation as laid out in it, which its remarks are placed by. */
export interface Drawer extends Scope {
    kind: DrawerKind;
    conversation: Conversation;
    talk: Talk | null;
    /** What its "since you approved" shows, by file, where it's that drawer. */
    files: SinceFile[];
    /** The worktree its files are in, for a remark on one. */
    worktree: string | null;
}

/** The review's text, and where each group, each item and each drawer is in it. */
export interface Laid {
    text: string;
    groups: Group[];
    regions: Region[];
    drawers: Drawer[];
}

export const EMPTY: Draft = { comments: [], letters: [], remarks: [], done: [], parked: [] };

/** Return what names a conversation among others: its repository, runtime, session and subagent. */
export function whose(conversation: Conversation): string {
    return JSON.stringify([conversation.repository, conversation.runtime, conversation.session, conversation.agent ?? null]);
}

/** Return what names an item among the folds' owners: its number; a drawer: its kind and whose it is. */
export function ownerOf(owner: { item: Item } | { drawer: DrawerKind; conversation: Conversation }): string {
    return "item" in owner ? `${owner.item.number}` : `${owner.drawer} ${whose(owner.conversation)}`;
}

/** Return what the operator wrote in a draft as the editor holds it, in one list: the comments, the messages, then the remarks. */
export function written(draft: Draft): Written[] {
    return [...(draft.comments ?? []), ...(draft.letters ?? []), ...(draft.remarks ?? [])];
}

/** Return `draft` with `list`, as the editor holds what's written, for its comments, its messages and its remarks. */
export function withWritten(draft: Draft, list: Written[]): Draft {
    return { ...draft, comments: list.filter(isComment), letters: list.filter(isLetter), remarks: list.filter(isRemark) };
}

/** Return whether what's written is a message to an agent, rather than a comment on an item or a remark in a drawer. */
export function isLetter(each: Written): each is Letter {
    return "to" in each && !("quote" in each);
}

/** Return whether what's written is a remark in one of an agent's drawers. */
export function isRemark(each: Written): each is Remark {
    return "to" in each && "quote" in each;
}

function isComment(each: Written): each is Comment {
    return !("to" in each);
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
 * One line of a changed file that comments may be on: its header, or one of its rows, the run of unchanged rows it
 * opens, if any, before it, and whether it ends one; what it triggered, where it's a line that matters, and whether
 * it's a stop, the first line of what triggered; the bodies it declares and those it ends; and, for a file with rows,
 * the fold its header opens, folded where the file is automatic, and its last row ends.
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
    /** Whether the bodies it declares fold until opened: a new module's in a drawer, which shows its design, but one holding a line that matters. */
    designed: boolean;
}

/** Whether an item keeps the files it changes beside it, for the review to show under it: an approval, a held change, or a flagged write. */
export function changing(item: Item): boolean {
    const reason = item.reason.reason;
    return reason === "approval" || reason === "held" || reason === "flagged";
}

/**
 * Return what an item's files whose asks are each on a line keep open (`Showing`): an approval's, which may change tens
 * of thousands of lines, the lines that ask alone; a held change's, every change, as the operator reads them whole.
 */
export function showing(item: Item): Showing {
    return item.reason.reason === "approval" ? "asks" : "changes";
}

/**
 * Return the lines of `files`, each file's header, then its rows, its runs of unchanged ones folding, or for an
 * approval every run away from the lines that ask (`showing`), each body able to fold under the row declaring it, and
 * the whole of each file able to fold under its header, an automatic one folded. Where `design` says so of a file, a
 * new module in a drawer, its bodies fold until opened, but those holding a line that matters.
 */
function filedOf(files: ChangedFile[], showing: Showing, design: (file: ChangedFile) => boolean): Filed[] {
    return files.flatMap((file) => {
        const laidOut = shownOnce(file, showing);
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
            designed: false,
        };
        const matters = new Map(laidOut.matters.map((each) => [each.row, each]));
        const designed = design(file);
        const rows = laidOut.rows.map((row, at): Filed => {
            const run = laidOut.runs.find((each) => each.from === at);
            const matter = matters.get(at) ?? null;
            const declares = laidOut.bodies.filter((each) => each.from === at);
            return {
                file,
                row,
                text: row.text,
                opens: run === undefined ? null : { summary: run.summary, name: run.name },
                closes: laidOut.runs.some((each) => each.to === at + 1),
                matter,
                stop: (matter?.notes.length ?? 0) > 0,
                declares,
                finishes: laidOut.bodies.filter((each) => each.to === at),
                folds: null,
                ends: at === laidOut.rows.length - 1,
                designed: designed && !declares.some((body) => laidOut.matters.some((each) => each.row > body.from && each.row <= body.to)),
            };
        });
        return [header, ...rows];
    });
}

/** Return the lines of each file an item changes (`changing`), as the host answered them; none for any other item, or before the host has answered. */
function filed(item: Item, around: Around): Filed[] {
    const files = around.files.get(item.number);
    if (!changing(item) || files === undefined || !("shown" in files)) {
        return [];
    }
    return filedOf(files.shown, showing(item), () => false);
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

/** Whether an item is a write that landed flagged, which the review shows in its agent's "since you approved" drawer rather than as an item (`docs/dashboard.md`, *The review*). */
export function flag(item: Item): boolean {
    return item.rank.name === "flag";
}

/** What Space a or Space x does on an item: answer it, or nothing. */
export type Answering = { kind: "answer" } | { kind: "nothing" };

/** Return what Space a or Space x does on `item`: approve or decline an approval or a held change; on any other item, nothing. */
export function answering(item: Item): Answering {
    switch (item.reason.reason) {
        case "approval":
        case "held":
            return { kind: "answer" };
        default:
            return { kind: "nothing" };
    }
}

/**
 * Return `items` in groups, one per agent, and one per banner of lup's approvals, in the order they arrived: each
 * group where its first item came, by that item's number, and its items by theirs. A later item comes after every
 * earlier one, at the end of its group or in a group of its own after the others, and a change of an item's rank or
 * state moves nothing: `Item.rank` orders nothing here, saying only which items `]a` and `[a` stop at (`toAnswer`).
 */
function grouped(items: Item[], banner: (item: Item) => string): Grouping[] {
    const groups = new Map<string, Grouping>();
    for (const item of items.toSorted((a, b) => a.number - b.number)) {
        const sender = item.sender;
        const conversation = sender.party === "conversation" ? sender : null;
        const key = conversation === null ? `lup ${banner(item)}` : whose(conversation);
        const group = groups.get(key) ?? { key, conversation, head: { item }, items: [] };
        groups.set(key, { ...group, items: [...group.items, item] });
    }
    return [...groups.values()];
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

/** Say how many of a thing there are: `1 step`, `5 steps`. */
function counted(count: number, one: string): string {
    return `${count} ${one}${count === 1 ? "" : "s"}`;
}

/** The marks before a task, by its status: done, in progress, to do. */
const TASK_MARKS = { completed: "✓", in_progress: "▶", pending: "·" } as const;

/** Say a task list's summary line: how many entries, and how they stand. */
export function tasksSummary(tasks: Task[]): string {
    if (tasks.length === 0) {
        return "tasks · none kept";
    }
    const done = tasks.filter((each) => each.status === "completed").length;
    const going = tasks.filter((each) => each.status === "in_progress").length;
    const parts = [...(done === 0 ? [] : [`${done} done`]), ...(going === 0 ? [] : [`${going} in progress`])];
    const entries = tasks.length === 1 ? "1 entry" : `${tasks.length} entries`;
    return [`tasks · ${entries}`, ...parts].join(", ");
}

/** Return the current entry of a task list: the one in progress, what it says while in progress, else the first to do; none where there's neither. */
export function currentTask(tasks: Task[]): string | null {
    const going = tasks.find((each) => each.status === "in_progress");
    if (going !== undefined) {
        return going.active ?? going.subject;
    }
    return tasks.find((each) => each.status === "pending")?.subject ?? null;
}

/** Return where the operator last spoke in `entries`: the index of their last words; none before any. */
export function lastSpoken(entries: Entry[]): number {
    return entries.findLastIndex((each) => each.kind === "said" && each.by === "operator");
}

/** Say a trace's summary line: how many steps since the operator's last message, or that the record isn't read yet. */
export function traceSummary(entries: Entry[], read: boolean): string {
    if (!read) {
        return "trace · not read yet";
    }
    const spoke = lastSpoken(entries);
    const steps = entries.length - spoke - 1;
    const since = spoke < 0 ? "" : " since your last message";
    return steps === 0 ? `trace · nothing${since}` : `trace · ${counted(steps, "step")}${since}`;
}

/** Say a "since you approved" drawer's summary line: on which branch, how many files, and how many writes came since the operator read it, which Space `l` brings in. */
export function sinceSummary(shown: Since | null, latest: Since | null): string {
    if (shown === null) {
        return "since you approved · not read yet";
    }
    const branch = shown.branch == null ? "" : ` on ${shown.branch}`;
    const files = shown.files.length === 0 ? "nothing" : counted(shown.files.length, "file");
    const came = latest === null || latest.version === shown.version ? null : Math.max(latest.writes - shown.writes, 0);
    const newer = came === null ? "" : ` · ${came === 0 ? "changed" : counted(came, "write")} since · ␣l brings it in`;
    return `since you approved${branch} · ${files}${newer}`;
}

/** Say a conversation drawer's summary line: how many steps it has, or that the record isn't read yet. */
export function conversationSummary(entries: Entry[], read: boolean): string {
    return read ? `conversation · ${counted(entries.length, "step")}` : "conversation · not read yet";
}

/** The text being laid out, line by line. */
class Writer {
    text = "";

    /** Write `line` on a line of its own, and return where it is. */
    line(line: string): Span {
        const from = this.text.length;
        this.text += `${line}\n`;
        return { from, to: from + line.length };
    }

    /** Where the next line starts. */
    get at(): number {
        return this.text.length;
    }
}

/** What's gathered of a scope as it's laid out. */
interface Gathering {
    lines: Line[];
    blocks: Block[];
    code: Coded[];
    filed: FileSpan[];
    asides: Aside[];
    folds: Fold[];
    stops: number[];
}

function gathering(): Gathering {
    return { lines: [], blocks: [], code: [], filed: [], asides: [], folds: [], stops: [] };
}

/**
 * Lay `files` into `w` as part of the scope `of`, gathered in `into`: each line written with its comments under it
 * (`writeBlocks`, by the line's place among the scope's own lines from `first`), its runs, bodies and files folding.
 */
function layCode(w: Writer, into: Gathering, of: string, files: Filed[], first: number, starts: number[], writeBlocks: (line: number) => void): void {
    // What each fold opened is, until the line ending it: the run, the file, each body by its name.
    let run: { summary: Aside; name: string } | null = null;
    let whole: { summary: Span; from: number; closed: boolean } | null = null;
    const bodies = new Map<string, { summary: Span; from: number; closed: boolean }>();
    files.forEach((each, index) => {
        const path = each.file.path;
        if (each.opens !== null) {
            const aside = { kind: "summary" as const, ...w.line(each.opens.summary) };
            into.asides.push(aside);
            run = { summary: aside, name: each.opens.name };
        }
        const at = first + index;
        const span = w.line(each.text);
        into.lines.push({ ...span, own: starts[at] ?? 0 });
        into.code.push({ ...span, file: each.file, row: each.row, matter: each.matter });
        if (each.stop) {
            into.stops.push(span.from);
        }
        const fold = (kind: FoldKind, name: string, label: string, closed: boolean, summary: Span, from: number) =>
            into.folds.push({ of, kind, name: name === "" ? path : `${path} ${name}`, label, closed, summary, from, to: span.to });
        const ran: { summary: Aside; name: string } | null = run;
        if (each.closes && ran !== null) {
            const summary = { from: ran.summary.from, to: ran.summary.to };
            fold("lines", ran.name, w.text.slice(summary.from, summary.to), true, summary, summary.to);
            run = null;
        }
        for (const body of each.finishes) {
            const declared = bodies.get(body.name);
            if (declared !== undefined) {
                fold("body", body.name, body.names.at(-1) ?? "", declared.closed, declared.summary, declared.from);
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
            whole = { summary: span, from: w.at - 1, closed: each.folds.closed };
        }
        for (const body of each.declares) {
            bodies.set(body.name, { summary: span, from: w.at - 1, closed: each.designed });
        }
        if (each.row === null) {
            into.filed.push({ file: each.file, from: span.from, to: w.at - 1 });
        } else {
            const last = into.filed.at(-1);
            if (last !== undefined) {
                last.to = w.at - 1;
            }
        }
    });
}

/** What's written on a scope, with its place in the editor's list. */
interface Placed {
    comment: Written;
    at: number;
}

/** The comments on one scope, by the line each is under, once: a comment on the whole under none. */
function placedOn(comments: Placed[], starts: number[]): Map<number | null, Placed[]> {
    const placed = new Map<number | null, Placed[]>();
    for (const each of comments) {
        const quote = "quote" in each.comment ? each.comment.quote : null;
        const line = under(starts, quote);
        placed.set(line, [...(placed.get(line) ?? []), each]);
    }
    return placed;
}

/**
 * Lay `items` out as one text, in groups, one per agent, each under its banner, in the order they arrived: those with
 * items now first, each where its first item came (`grouped`); then a group for each agent of `agents` (those running,
 * in the tree's order) with none, and for each the draft writes to with none; then the parked items' groups, each
 * where its first item came. Under each banner but the parked ones', the draft's messages to its agent; then each
 * item, in the order they came, under a header naming it, each comment of the draft on it under the line it's on: a
 * comment on a passage under the passage's last line, one on the item whole under its header. Under each item's own
 * text, what the host has answered of it: each file it changes (`changing`), its header then its lines, each run of
 * unchanged ones folding under a summary line; then the item's context, a summary line with the lines that fold under
 * it. Where the host showed none, a line says why. Then, at the end of each agent's group but the parked ones, its
 * drawers, from `drawers` by its conversation (`layDrawer`), the draft's remarks in them each under its line, a
 * conversation among the items it exchanged called by `name`.
 *
 * `places` are where the groups were laid out before in this sitting (`Group.place`, in order): each among them keeps
 * its place, items coming and going, and any other comes after them, in the order above. So a group appears where its
 * first item puts it, or after every group with items as its conversation is first seen, and stays there while
 * anything's waiting; laid out anew from the items alone, as on reload, the order is the same but for a group that
 * emptied meanwhile.
 */
export function laid(
    items: Item[],
    agents: Conversation[],
    banner: (head: Head, parked: boolean) => string,
    header: (item: Item, parked: boolean) => string,
    draft: Draft,
    around: Around,
    places: readonly string[] = [],
    drawers: Drawers = new Map(),
    name: (party: Conversation) => string = (party) => party.agent ?? party.session,
): Laid {
    const parked = draft.parked ?? [];
    const done = draft.done ?? [];
    const comments = draft.comments ?? [];
    const letters = draft.letters ?? [];
    const remarks = draft.remarks ?? [];
    const wrote = written(draft);
    const now = grouped(items.filter((each) => !parked.includes(each.number)), (item) => banner({ item }, false));
    const empty = emptyGroups([...agents, ...letters.map((each) => each.to), ...remarks.map((each) => each.to)], now);
    const later = grouped(items.filter((each) => parked.includes(each.number)), (item) => banner({ item }, true));
    const w = new Writer();
    const groups: Group[] = [];
    const regions: Region[] = [];
    const laidDrawers: Drawer[] = [];
    for (const group of kept([...now, ...empty], false)) {
        layGroup(group, false);
    }
    for (const group of kept(later, true)) {
        layGroup(group, true);
    }
    // A conversation laid in a drawer reads its lines from the whole text, once it's whole.
    for (const drawer of laidDrawers) {
        if (drawer.talk !== null) {
            drawer.talk = { ...drawer.talk, text: w.text };
        }
    }
    return { text: w.text, groups, regions, drawers: laidDrawers };

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
        const opening = w.line(said);
        const blocks: Block[] = [];
        if (!isParked) {
            letters.forEach((letter, at) => {
                if (whose(letter.to) === group.key) {
                    blocks.push({ comment: comments.length + at, ...w.line(letter.text) });
                }
            });
        }
        const made: Group = {
            conversation: group.conversation,
            head: group.head,
            later: isParked,
            place: placeOf(group.key, isParked),
            banner: opening,
            blocks,
            drawers: [],
        };
        groups.push(made);
        for (const item of group.items) {
            layItem(item, isParked);
        }
        const conversation = group.conversation;
        if (conversation !== null && !isParked && drawers.has(group.key)) {
            const data = drawers.get(group.key) ?? UNREAD;
            for (const kind of DRAWERS) {
                const drawer = layDrawer(kind, conversation, data);
                made.drawers.push(drawer);
                laidDrawers.push(drawer);
            }
        }
        if (group.items.length === 0 && made.drawers.length === 0 && blocks.length > 0) {
            w.line("");
        }
    }

    function layItem(item: Item, isParked: boolean): void {
        const files = filed(item, around);
        // Its own lines, then its files': the text comments are placed in, by where each quote ends.
        const own = [...body(item).split("\n"), ...files.map((each) => each.text)];
        const starts = startsOf(own);
        const ownCount = own.length - files.length;
        const placed = placedOn(
            wrote.flatMap((comment, at) => (isComment(comment) && comment.item === item.number ? [{ comment, at }] : [])),
            starts,
        );
        const into = gathering();
        const writeBlocks = (line: number | null) => {
            for (const { comment, at } of placed.get(line) ?? []) {
                into.blocks.push({ comment: at, ...w.line(comment.text) });
            }
        };
        const head = header(item, isParked);
        const headed = w.line(head);
        writeBlocks(null);
        own.slice(0, ownCount).forEach((line, at) => {
            into.lines.push({ ...w.line(line), own: starts[at] ?? 0 });
            writeBlocks(at);
        });
        const of = ownerOf({ item });
        layCode(w, into, of, files, ownCount, starts, writeBlocks);
        const refused = around.files.get(item.number);
        if (refused !== undefined && "refused" in refused) {
            into.asides.push({ kind: "refused", ...w.line(`no files: ${refused.refused}`) });
        }
        const context = beneath(item, around);
        if (context !== null) {
            const summary = { kind: context.summary.kind, ...w.line(context.summary.text) };
            into.asides.push(summary);
            const shown = context.lines.map((said) => {
                const aside = { kind: said.kind, ...w.line(said.text) };
                into.asides.push(aside);
                return aside;
            });
            const last = shown.at(-1);
            if (last !== undefined) {
                into.folds.push({ of, kind: "context", name: "", label: "context", closed: true, summary: { from: summary.from, to: summary.to }, from: summary.to, to: last.to });
            }
        }
        // The item whole folds under its header, what folds within it inside: folded once it's marked read, or left for later.
        const closed = isParked || done.includes(item.number);
        into.folds.push({ of, kind: "item", name: "", label: head, closed, summary: headed, from: headed.to, to: w.at - 1 });
        w.line("");
        regions.push({ item, of, header: headed, ...into });
    }

    /** Lay one of `conversation`'s drawers of `kind` from `data`, and return it. */
    function layDrawer(kind: DrawerKind, conversation: Conversation, data: AgentDrawers): Drawer {
        const of = ownerOf({ drawer: kind, conversation });
        const into = gathering();
        const key = whose(conversation);
        const mine: Placed[] = wrote.flatMap((comment, at) => (isRemark(comment) && whose(comment.to) === key ? [{ comment, at }] : []));
        let talk: Talk | null = null;
        let files: SinceFile[] = [];
        let summary: Span;
        switch (kind) {
            case "tasks": {
                summary = w.line(tasksSummary(data.tasks));
                for (const task of data.tasks) {
                    const shown = task.status === "in_progress" ? (task.active ?? task.subject) : task.subject;
                    into.asides.push({ kind: "task", ...w.line(`${TASK_MARKS[task.status]} ${shown}`) });
                }
                break;
            }
            case "trace":
            case "conversation": {
                const spoke = lastSpoken(data.entries);
                const tracing = kind === "trace";
                summary = w.line(tracing ? traceSummary(data.entries, true) : conversationSummary(data.entries, true));
                // A remark on a step since the operator's last words shows in the trace, which holds the same steps, never twice.
                const steps = mine.flatMap(({ comment, at }) =>
                    isRemark(comment) && comment.step != null && (tracing ? comment.step > spoke : comment.step <= spoke)
                        ? [{ remark: { step: comment.step, quote: comment.quote, text: comment.text }, at }]
                        : [],
                );
                const first = tracing ? spoke + 1 : 0;
                const entries = tracing ? data.entries.slice(first) : data.entries;
                const beside = {
                    sent: [],
                    exchanged: tracing || data.exchanged === null ? UNEXCHANGED : data.exchanged,
                    whose: { agent: conversation.agent ?? null, name },
                };
                const earlier = tracing ? ("nothing" as const) : history(data.entries, []);
                const laidOut = laidTalk(entries, beside, { comments: steps.map((each) => each.remark) }, earlier, first);
                talk = shifted(laidOut, w.at);
                if (laidOut.text !== "") {
                    w.text += `${laidOut.text}\n`;
                }
                into.lines.push(...talk.words.flatMap((words) => words.lines.map(({ from, to, own }) => ({ from, to, own }))));
                into.blocks.push(...talk.blocks.map((block) => ({ ...block, comment: steps[block.comment]?.at ?? block.comment })));
                into.asides.push(...talk.asides);
                const folds = [...(talk.fold === null ? [] : [talk.fold]), ...talk.items.flatMap((item) => (item.fold === null ? [] : [item.fold]))];
                for (const fold of folds) {
                    into.folds.push({ of, kind: "context", name: fold.key, label: w.text.slice(fold.summary.from, fold.summary.to), closed: fold.closed, summary: fold.summary, from: fold.from, to: fold.to });
                }
                break;
            }
            case "since": {
                summary = w.line(sinceSummary(data.since, data.latest));
                files = data.since?.files ?? [];
                const shown = filedOf(files.map((each) => each.file), "changes", (file) => file.before == null);
                const starts = startsOf(shown.map((each) => each.text));
                const placed = placedOn(mine.filter(({ comment }) => isRemark(comment) && comment.code != null), starts);
                const writeBlocks = (line: number | null) => {
                    for (const { comment, at } of placed.get(line) ?? []) {
                        into.blocks.push({ comment: at, ...w.line(comment.text) });
                    }
                };
                layCode(w, into, of, shown, 0, starts, writeBlocks);
                break;
            }
        }
        const label = w.text.slice(summary.from, summary.to);
        const last = w.at - 1;
        // A drawer with nothing under its summary line hides nothing, so it has no fold.
        if (last > summary.to) {
            into.folds.push({ of, kind, name: "", label, closed: true, summary, from: summary.to, to: last });
        }
        w.line("");
        return { kind, conversation, talk, files, worktree: data.since?.worktree ?? null, of, header: summary, ...into };
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

/**
 * Whether an item is to answer rather than to read: ranked as waiting on the operator (`Item.rank`, which the host
 * gives), a question, a held change, an approval or a hold at landing, and neither marked read nor left for later in
 * `draft`, which settles it until the reply is sent.
 */
export function toAnswer(item: Item, draft: Draft): boolean {
    const settled = [...(draft.done ?? []), ...(draft.parked ?? [])];
    return item.rank.name === "waiting on you" && !settled.includes(item.number);
}

/**
 * Return where `]a` or `[a` goes from `head`: the next (`forward`) or previous item to answer (`toAnswer`), in the
 * order they came, by their numbers, whatever order the text lays them out in, so each is reached once. From the item
 * the cursor is in, the one after or before it among them; from a banner or a line of no item, the first item laid
 * out after the cursor, that one counting, or going back the last before it. None past the last, or before the first.
 */
export function answerAfter(laidOut: Laid, draft: Draft, head: number, forward: boolean): Region | undefined {
    const inside = regionAt(laidOut, head);
    const beside = forward
        ? laidOut.regions.find((each) => each.header.from > head)
        : laidOut.regions.findLast((each) => each.header.from < head);
    const from = inside ?? beside;
    if (from === undefined) {
        return undefined;
    }
    const number = from.item.number;
    const bound = inside === undefined ? number : forward ? number + 1 : number - 1;
    const walk = laidOut.regions.filter((each) => toAnswer(each.item, draft)).toSorted((a, b) => a.item.number - b.item.number);
    return forward ? walk.find((each) => each.item.number >= bound) : walk.findLast((each) => each.item.number <= bound);
}

/**
 * Say what waits below, for the header over the review, so the operator knows without the text moving to show it: how
 * many items are to answer (`toAnswer`), and how many are new since they last sent (`fresh`) among those neither
 * marked read nor left for later; nothing where no item waits.
 */
export function tallied(items: Item[], draft: Draft, reviewed: string | null | undefined): string {
    if (items.length === 0) {
        return "";
    }
    const settled = [...(draft.done ?? []), ...(draft.parked ?? [])];
    const open = items.filter((each) => !settled.includes(each.number));
    const answering = open.filter((each) => toAnswer(each, draft)).length;
    const arrived = open.filter((each) => fresh(each, reviewed)).length;
    return [`${answering} to answer`, ...(arrived === 0 ? [] : [`${arrived} new`])].join(" · ");
}

/** Return the last of `spans`, in the text's order, starting at or before `position`. */
function lastFrom<T>(spans: T[], from: (each: T) => number, position: number): T | undefined {
    return spans.findLast((each) => from(each) <= position);
}

/** Return every scope, the items' and the drawers', in the text's order. */
function scopes(laidOut: Laid): Scope[] {
    return [...laidOut.regions, ...laidOut.drawers].sort((a, b) => a.header.from - b.header.from);
}

/** Return the item or the drawer `position` is in: its header, its lines, its comments, or the blank line after it; none on a group's banner or the messages under it. */
export function scopeAt(laidOut: Laid, position: number): Scope | undefined {
    const scope = lastFrom(scopes(laidOut), (each) => each.header.from, position);
    const group = lastFrom(laidOut.groups, (each) => each.banner.from, position);
    return scope !== undefined && (group === undefined || scope.header.from > group.banner.from) ? scope : undefined;
}

/** Return whether `scope` is an item's. */
export function isRegion(scope: Scope): scope is Region {
    return "item" in scope;
}

/** Return whether `scope` is a drawer. */
export function isDrawer(scope: Scope): scope is Drawer {
    return "kind" in scope;
}

/** Return the region `position` is in: an item's header, its lines, its comments, or the blank line after it; none on a group's banner, the messages under it, or a drawer. */
export function regionAt(laidOut: Laid, position: number): Region | undefined {
    const scope = scopeAt(laidOut, position);
    return scope !== undefined && isRegion(scope) ? scope : undefined;
}

/** Return the drawer `position` is in: its summary line, its lines, its comments, or the blank line after it; none elsewhere. */
export function drawerAt(laidOut: Laid, position: number): Drawer | undefined {
    const scope = scopeAt(laidOut, position);
    return scope !== undefined && isDrawer(scope) ? scope : undefined;
}

/** Return the group `position` is on: on its banner, the messages under it, or the blank line after them; none on an item or a drawer. */
export function groupAt(laidOut: Laid, position: number): Group | undefined {
    const scope = lastFrom(scopes(laidOut), (each) => each.header.from, position);
    const group = lastFrom(laidOut.groups, (each) => each.banner.from, position);
    return group !== undefined && (scope === undefined || group.banner.from > scope.header.from) ? group : undefined;
}

/** Return the group `position` is in, on its banner, its items or its drawers. */
export function groupAround(laidOut: Laid, position: number): Group | undefined {
    return lastFrom(laidOut.groups, (each) => each.banner.from, position);
}

/** Return whether two of what's written are the same one, whatever it says: a comment on the same passage of the same item, a message to the same agent, or a remark on the same passage to the same agent. */
function same(a: Written, b: Written): boolean {
    if (isLetter(a) || isLetter(b)) {
        return isLetter(a) && isLetter(b) && whose(a.to) === whose(b.to);
    }
    if (isRemark(a) || isRemark(b)) {
        return (
            isRemark(a) &&
            isRemark(b) &&
            whose(a.to) === whose(b.to) &&
            a.quote.start === b.quote.start &&
            a.quote.end === b.quote.end &&
            (a.step ?? null) === (b.step ?? null) &&
            (a.code?.path ?? null) === (b.code?.path ?? null)
        );
    }
    return a.item === b.item && a.quote?.start === b.quote?.start && a.quote?.end === b.quote?.end;
}

/**
 * Return where the cursor goes as the review is laid out again, from `before` and what was written in it to `after`
 * and what's written now, where what it was on at `head` is gone, as a reply sent takes what it covered: from a
 * comment, a message or a remark gone, back on what it was about (`aboutAt`), the last character of its passage, its
 * item's header, its drawer's summary line, its group's banner; from an item gone, or what it was about gone too, onto
 * its group's banner. None where what it was on is still there, or its group is gone too, where the text's changes
 * carry it.
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
        if (isLetter(was)) {
            return banner;
        }
        if (isRemark(was)) {
            const drawer = drawerAt(before, head);
            const now = drawer === undefined ? undefined : after.drawers.find((each) => each.of === drawer.of);
            return now === undefined ? banner : (remarkedAt(now, was) ?? now.header.from);
        }
        const region = after.regions.find((each) => each.item.number === was.item);
        return region === undefined ? banner : commentedAt(region, was);
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
    const drawer = drawerAt(laidOut, head);
    if (drawer !== undefined) {
        if ((head >= drawer.header.from && head <= drawer.header.to) || drawer.kind === "tasks") {
            return "drawer";
        }
        if (drawer.kind === "since") {
            return codeAt(drawer, head) !== undefined ? "since" : "aside";
        }
        return lineAt(drawer, head) !== undefined ? "trace" : "aside";
    }
    const region = regionAt(laidOut, head);
    if (region === undefined || asideAt(region, head) !== undefined) {
        return "aside";
    }
    const reason = region.item.reason.reason;
    if (codeAt(region, head) !== undefined) {
        return "file";
    }
    return reason === "approval" || reason === "held" ? "change" : "item";
}

/** One part of what the header over the review says: whom what's being written goes to, the group, or a fold the cursor is in, by its kind. */
export interface Where {
    kind: "to" | "group" | FoldKind;
    text: string;
}

/** How the header names what it says: a group, by its banner; an item, by its header; a conversation, as it's called. */
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
 * Return what the header over the review says with the cursor at `head`: while a comment, a message or a remark is
 * being written (`writing`; `wrote`, what's written as the editor holds it), whom it goes to; then the group the cursor
 * is in, the item or the drawer, the file, and each fold it's in within them, a body, a run of lines, or the item's
 * context. Nothing before the first group, as where nothing's waiting.
 */
export function heading(laidOut: Laid, head: number, writing: boolean, wrote: Written[], naming: Naming): Where[] {
    const group = lastFrom(laidOut.groups, (each) => each.banner.from, head);
    if (group === undefined) {
        return [];
    }
    const block = writing ? blockAt(laidOut, head) : undefined;
    const being = block === undefined ? undefined : wrote[block.comment];
    const goesTo = (written: Written): Conversation | null => {
        if (isLetter(written) || isRemark(written)) {
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
    const scope = scopeAt(laidOut, head);
    if (scope === undefined) {
        return [...going, { kind: "group", text: naming.group(group) }];
    }
    const file = scope.filed.find((each) => head >= each.from && head <= each.to);
    const inner = around(scope.folds, head).filter((each) => each.kind !== "file" && each.of !== scope.of || (each.kind !== "item" && each.kind !== "file" && !(DRAWERS as string[]).includes(each.kind)));
    const named: Where = isRegion(scope) ? { kind: "item", text: naming.item(scope) } : { kind: (scope as Drawer).kind, text: (scope as Drawer).kind };
    return [
        ...going,
        { kind: "group", text: naming.group(group) },
        named,
        ...(file === undefined ? [] : [{ kind: "file" as const, text: file.file.path }]),
        ...inner.map((each) => ({ kind: each.kind, text: each.label })),
    ];
}

/** Return every comment, message and remark shown, as blocks of the editor's list of what's written. */
export function blocksOf(laidOut: Laid): Block[] {
    return [...laidOut.groups.flatMap((each) => each.blocks), ...scopes(laidOut).flatMap((each) => each.blocks)];
}

/** Return the comment, message or remark shown at `position`, where it's in one; a comment's end counts, so an empty one can be typed in. */
export function blockAt(laidOut: Laid, position: number): Block | undefined {
    return blocksOf(laidOut).find((each) => position >= each.from && position <= each.to);
}

/** Return a message to the agent `group` is of, as it's opened: empty; none for a group no message goes to. */
function letterTo(group: Group): Letter | undefined {
    return group.conversation === null ? undefined : { to: group.conversation, text: "" };
}

/** Return the scope's own line shown at `position`, where it's on one. */
export function lineAt(scope: Scope, position: number): Line | undefined {
    return scope.lines.find((each) => position >= each.from && position <= each.to);
}

/** Return the line under an item or in a drawer that isn't its own text shown at `position`, where it's on one. */
export function asideAt(scope: Scope, position: number): Aside | undefined {
    return scope.asides.find((each) => position >= each.from && position <= each.to);
}

/** Return the folds of the item or the drawer `position` is in, which `zr`, `zm`, `zR`, `zM` and Space `z` reach: none on a group's banner or the messages under it. */
export function foldsOf(laidOut: Laid, position: number): Fold[] {
    return scopeAt(laidOut, position)?.folds ?? [];
}

/** Return the innermost fold `position` is in: on its summary line or the lines it hides. */
export function foldAt(laidOut: Laid, position: number): Fold | undefined {
    return around(
        scopes(laidOut).flatMap((each) => each.folds),
        position,
    ).at(-1);
}

/** Return what names a fold across layouts: its owner, what it holds, and which of those it is. */
export function foldKey(fold: Pick<Fold, "of" | "kind" | "name">): string {
    return `${fold.of} ${fold.kind} ${fold.name}`;
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
export function codeAt(scope: Scope, position: number): Coded | undefined {
    const found = scope.code[codeFrom(scope.code, position)];
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
function said(text: string, scope: Scope, lines: Line[], from: number, to: number): string {
    const parts = lines.map((line) => ({
        line,
        coded: codeAt(scope, line.from),
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
 * Return the version of the file a remark on `lines` of a "since you approved" `drawer` records: the file, its version
 * as the drawer read it, and the lines quoted as that version holds them, those the file becomes; none where the
 * lines are of no file the drawer shows, or none of them is of the file as it stands.
 */
function quotedCode(drawer: Drawer, lines: Line[]): NonNullable<Remark["code"]> | null {
    const coded = lines.flatMap((line) => {
        const found = codeAt(drawer, line.from);
        return found === undefined ? [] : [found];
    });
    const file = coded[0]?.file;
    const shown = file === undefined ? undefined : drawer.files.find((each) => each.file === file);
    const rows = coded.flatMap((each) => (each.file === file && each.row !== null && each.row.side === "after" ? [each.row] : []));
    const first = rows[0];
    if (shown === undefined || shown.version == null || drawer.worktree === null || first === undefined) {
        return null;
    }
    return { worktree: drawer.worktree, path: shown.file.path, version: shown.version, first: first.number, lines: rows.map((each) => each.text) };
}

/**
 * Return where a comment opened on the line at `position` goes: on that line of its item, or on the item whole from
 * its header or an empty line of its own; on a line of a changed file, or its header, empty or not; in a drawer, a
 * remark to its agent on the agent's words in its trace or conversation, or on a line of a file since they approved it,
 * which records the file's version. On a group's banner, a message to its agent, laid out under its group among those
 * to answer now, from the banner of what's left for later too. None on a line no comment is on, or on the banner of
 * lup's approvals.
 */
export function opened(laidOut: Laid, position: number): Written | undefined {
    const group = groupAt(laidOut, position);
    if (group !== undefined) {
        return letterTo(group);
    }
    const drawer = drawerAt(laidOut, position);
    if (drawer !== undefined) {
        return openedIn(laidOut, drawer, position);
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

/** Return the remark opened on the line at `position` of `drawer`: on the agent's words, or on a line of a file; none on any other line. */
function openedIn(laidOut: Laid, drawer: Drawer, position: number): Remark | undefined {
    if (drawer.talk !== null) {
        const found = openedTalk(drawer.talk, position);
        return found === undefined ? undefined : { to: drawer.conversation, quote: found.quote, text: "", step: found.step };
    }
    if (drawer.kind !== "since") {
        return undefined;
    }
    const line = lineAt(drawer, position);
    if (line === undefined) {
        return undefined;
    }
    const shown = laidOut.text.slice(line.from, line.to);
    return {
        to: drawer.conversation,
        quote: { text: said(laidOut.text, drawer, [line], line.from, line.to), start: line.own, end: line.own + shown.length },
        text: "",
        code: quotedCode(drawer, [line]),
    };
}

/**
 * Return a comment on the passage `from` to `to` selects, counted in its item's text, its own and its files'; a
 * message to a group's agent where it's on its banner, which no comment quotes; a remark on a passage of a drawer's;
 * none where it isn't all inside one item's lines, one drawer's, or one group's.
 */
export function quoted(laidOut: Laid, from: number, to: number): Written | undefined {
    const group = groupAt(laidOut, from);
    if (group !== undefined) {
        return group === groupAt(laidOut, Math.max(to - 1, from)) ? letterTo(group) : undefined;
    }
    const drawer = drawerAt(laidOut, from);
    if (drawer !== undefined) {
        return quotedIn(laidOut, drawer, from, to);
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

/** Return the remark on the passage `from` to `to` selects in `drawer`; none where it isn't all inside its lines. */
function quotedIn(laidOut: Laid, drawer: Drawer, from: number, to: number): Remark | undefined {
    if (drawer.talk !== null) {
        const found = quotedTalk(drawer.talk, from, to);
        return found === undefined ? undefined : { to: drawer.conversation, quote: found.quote, text: "", step: found.step };
    }
    if (drawer !== drawerAt(laidOut, Math.max(to - 1, from)) || drawer.kind !== "since") {
        return undefined;
    }
    const first = lineAt(drawer, from);
    const last = lineAt(drawer, Math.max(to - 1, from));
    if (first === undefined || last === undefined || to <= from) {
        return undefined;
    }
    const own = drawer.lines.map((each) => laidOut.text.slice(each.from, each.to)).join("\n");
    const quote = passage(own, first, last, from, to);
    const lines = drawer.lines.slice(drawer.lines.indexOf(first), drawer.lines.indexOf(last) + 1);
    return {
        to: drawer.conversation,
        quote: { ...quote, text: said(laidOut.text, drawer, lines, from, to) },
        text: "",
        code: quotedCode(drawer, lines),
    };
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

/** Return where in the text an offset of a scope's own text is shown. */
export function shownAt(scope: Scope, offset: number): number {
    return shownIn(scope.lines, offset, scope.header.to);
}

/**
 * Return where what's written, shown at `block`, is about, which Ctrl+Enter ending it goes back to: a message's
 * banner; the last character of the passage a comment or a remark quotes, where reading carries on, or its item's
 * header for one on the item whole.
 */
export function aboutAt(laidOut: Laid, written: Written, block: Block): number | undefined {
    if (isLetter(written)) {
        return groupAt(laidOut, block.from)?.banner.from;
    }
    if (isRemark(written)) {
        const drawer = drawerAt(laidOut, block.from);
        return drawer === undefined ? undefined : remarkedAt(drawer, written);
    }
    const region = regionAt(laidOut, block.from);
    return region === undefined ? undefined : commentedAt(region, written);
}

/** Return where a comment on `region`'s item is about: the last character of the passage it quotes, or the item's header for one on the item whole. */
function commentedAt(region: Region, comment: Comment): number {
    return comment.quote == null ? region.header.from : shownAt(region, lastOf(comment.quote));
}

/** Return where a remark in `drawer` is about: the last character of the passage it quotes, in the agent's words or a file's lines; none where its passage isn't laid out. */
function remarkedAt(drawer: Drawer, remark: Remark): number | undefined {
    if (drawer.talk !== null) {
        return remark.step == null ? undefined : aboutTalk(drawer.talk, { step: remark.step, quote: remark.quote, text: remark.text });
    }
    return drawer.lines.length === 0 ? undefined : shownAt(drawer, lastOf(remark.quote));
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

/** Return the remarks a draft sends: those that say something. */
export function remarks(draft: Draft): Remark[] {
    return saying(draft.remarks ?? []);
}

/** Return `draft` as it's sent: without the comments, messages and remarks that say nothing, each without the trailing space Esc leaves in it. */
export function pruned(draft: Draft): Draft {
    const trimmed = <W extends Written>(list: W[]) => saying(list).map((each) => ({ ...each, text: each.text.trimEnd() }));
    return { ...draft, comments: trimmed(draft.comments ?? []), letters: trimmed(draft.letters ?? []), remarks: trimmed(draft.remarks ?? []) };
}
