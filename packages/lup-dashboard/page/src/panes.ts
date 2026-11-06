// The review in two panes, where the page's address asks for it (`?panes=agents`, `?panes=threads`), to compare with
// the review as one buffer (#363): on the left, a list, itself a buffer with vim's keys; on the right, one buffer at a
// time (`Showing`), a subset of the review's tree that the one layout lays out (`laid`, `review.ts`). This is the list,
// by agent or by thread, read from what the review is laid out from, each row saying what it opens, how it stands and
// how much of it waits on the operator; its text, whose each line is, and what's drawn on it. And how the list's rows
// and a buffer say whom the operator's words reach. Pure: `Panes.tsx` draws it.
import type { Span } from "./comments";
import { doing, type Activity } from "./agents";
import type { Run } from "./reconcile";
import type { Merged } from "./looks";
import {
    about,
    cutAt,
    grouped,
    nested,
    news,
    toAnswer,
    waits,
    whose,
    type Conversation,
    type Draft,
    type Drawers,
    type Grouping,
    type Head,
    type Item,
    type Laid,
    type Showing,
    type ThreadRead,
    type Threading,
} from "./review";
import { currentTask } from "./views/adapters";
import { mount } from "./views/index";
import type { Remote, Running, Shown } from "./views";

export type { Showing };

/** What the list goes by. */
export type PanesBy = "agents" | "threads";

/** Return what the page's address asks the panes to go by; none lays the review out as one buffer. */
export function panesAsked(search: string): PanesBy | null {
    const asked = new URLSearchParams(search).get("panes");
    return asked === "agents" || asked === "threads" ? asked : null;
}

/** Return what names a buffer among the others, which the cursor is kept by while another is on screen. */
export function bufferKey(showing: Showing): string {
    switch (showing.kind) {
        case "agent":
            return `agent ${showing.key}`;
        case "thread":
            return `thread ${showing.number}`;
        default:
            return showing.kind;
    }
}

/** How much of what a row stands for waits on the operator: what asks them, what's news, the files to review, the pile to read; and what they've drafted there. */
export interface Tally {
    asks: number;
    news: number;
    files: number;
    pile: number;
    written: number;
}

const NOTHING: Tally = { asks: 0, news: 0, files: 0, pile: 0, written: 0 };

/** Return `tallies` added up. */
function added(tallies: readonly Tally[]): Tally {
    return tallies.reduce((sum, each) => ({ asks: sum.asks + each.asks, news: sum.news + each.news, files: sum.files + each.files, pile: sum.pile + each.pile, written: sum.written + each.written }), NOTHING);
}

/** A stretch of a row's line, in the look it's drawn in, a class of the review's. */
export interface Stretch {
    text: string;
    look?: string;
}

/** One line of a row: its stretches, the look of the line, and what's drawn beside its text as the time passes (`ticking.ts`), after its first `after` characters. */
export interface RowLine {
    stretches: Stretch[];
    look?: string;
    tick?: { after: number; said: (now: Date) => string; look: string };
}

/** One row of the list: what names it, its lines, what it opens where it opens anything, what the line of keys calls it and what the keys do on it. */
export interface Row {
    id: string;
    lines: RowLine[];
    opens: Showing | null;
    says: string;
    /** Whether `o` writes to what it opens: a message to an agent, or on a thread. */
    writes: boolean;
    /** The section it heads, folding what's under it, by what names the fold; none for a row that folds nothing. */
    folds?: { key: string; closed: boolean; kind: string };
}

/** How wide the list writes a row, tallies at its end, in characters. */
const COLUMNS = 46;

/** The glyphs of how a row stands, as the overview's (`Outline.tsx`). */
const WAITING = "◆";
const NEWS = "•";
const TO_REVIEW = "◇";
const PILE = "≈";
const DRAFTED = "»";

/** Return the stretches of `tally`, each count in its colour; none where nothing's counted. */
function tallied(tally: Tally): Stretch[] {
    const each = [
        { count: tally.asks, glyph: WAITING, look: "mark-waiting" },
        { count: tally.news, glyph: NEWS, look: "mark-news" },
        { count: tally.files, glyph: TO_REVIEW, look: "mark-to-review" },
        { count: tally.pile, glyph: PILE, look: "mark-pile" },
        { count: tally.written, glyph: DRAFTED, look: "outline-draft" },
    ].filter((one) => one.count > 0);
    return each.flatMap((one, at) => [...(at === 0 ? [] : [{ text: " " }]), { text: `${one.glyph}${one.count}`, look: one.look }]);
}

/** Return the stretches of a row's first line: `left`, cut where it's too long, then its tally at the list's width. */
function padded(left: readonly Stretch[], tally: Tally): Stretch[] {
    const right = tallied(tally);
    const rightWidth = right.reduce((sum, each) => sum + [...each.text].length, 0);
    const room = Math.max(COLUMNS - rightWidth - 1, 8);
    const kept: Stretch[] = [];
    let width = 0;
    for (const each of left) {
        const length = [...each.text].length;
        if (width + length > room) {
            const cut = [...each.text].slice(0, Math.max(room - width - 1, 0)).join("");
            kept.push({ ...each, text: `${cut}…` });
            width = room;
            break;
        }
        kept.push(each);
        width += length;
    }
    return right.length === 0 ? kept : [...kept, { text: " ".repeat(Math.max(COLUMNS - width - rightWidth, 1)) }, ...right];
}

/** What the list reads, beside what its rows say: the review's own. */
export interface ListReading {
    items: readonly Item[];
    draft: Draft;
    /** Those the review gives a group with nothing to answer: each running, then each holding what waits. */
    agents: readonly Conversation[];
    parents: ReadonlyMap<string, string>;
    called: (party: Conversation) => string;
    banner: (head: Head) => string;
    drawers: Drawers;
    looks: Merged;
    remote: Remote;
    running: ReadonlyMap<string, Running>;
    activities: ReadonlyMap<string, Activity | null>;
    states: ReadonlyMap<string, string | null>;
    threads: Threading | null;
    landings?: Shown["landings"];
}

/** Return how the agent `group` is of stands: what of theirs asks the operator, what's news, what's left to review in their "since you approved", and what's drafted to them. */
function agentTally(group: Grouping, reading: ListReading): Tally {
    const { draft, drawers, looks, remote, called } = reading;
    const conversation = group.conversation;
    const parked = draft.parked ?? [];
    const done = draft.done ?? [];
    const open = group.items.filter((each) => !parked.includes(each.number));
    const asks = open.filter((each) => toAnswer(each, draft)).length;
    const newsCount = open.filter((each) => news(each) && waits(each) && !done.includes(each.number)).length;
    const numbers = new Set(group.items.map((each) => each.number));
    const comments = (draft.comments ?? []).filter((each) => numbers.has(each.item) && each.text.trim() !== "").length;
    const letters = conversation === null ? 0 : (draft.letters ?? []).filter((each) => each.to != null && whose(each.to) === group.key && each.text.trim() !== "").length;
    const remarks = conversation === null ? 0 : (draft.remarks ?? []).filter((each) => whose(each.to) === group.key && each.text.trim() !== "").length;
    let files = 0;
    if (conversation !== null && drawers.has(group.key)) {
        const drawn = looks.drawers(conversation.repository).find((each) => each.view === "since");
        if (drawn !== undefined) {
            const of = { runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null };
            const shown: Shown = { items: new Map(), beyond: { contexts: new Map(), files: new Map() }, drawers, running: reading.running, landings: reading.landings ?? [], called };
            files = mount(conversation.repository, drawn.module, drawn.view, of, shown, remote).answer?.blocks.count ?? 0;
        }
    }
    return { asks, news: newsCount, files, pile: 0, written: comments + letters + remarks };
}

/** Return every agent's group the list names, with those of lup's approvals: each with an item, then each of `agents` with none. */
function groupsOf(reading: ListReading): Grouping[] {
    const groups = grouped([...reading.items], (item) => reading.banner({ item }));
    const keys = new Set(groups.map((each) => each.key));
    const empty = reading.agents.flatMap((conversation): Grouping[] => {
        const key = whose(conversation);
        return keys.has(key) ? [] : [{ key, conversation, head: { conversation }, items: [] }];
    });
    return [...groups, ...empty];
}

/** Return the row of the agent `group` is of, set in `depth` deep: how they stand, their name and their tally; under it, what they're doing, drawn, and what they're working on. */
function agentRow(group: Grouping, depth: number, reading: ListReading): Row {
    const conversation = group.conversation;
    const tally = agentTally(group, reading);
    const set = "  ".repeat(depth);
    if (conversation === null) {
        return {
            id: `agent ${group.key}`,
            lines: [{ stretches: padded([{ text: `${set}⚑ `, look: "mark-flagged" }, { text: "lup's approvals" }], tally) }],
            opens: { kind: "agent", key: group.key },
            says: "lup's approvals",
            writes: false,
        };
    }
    const called = reading.called(conversation);
    const name = depth > 0 ? (called.split("/").at(-1) ?? called) : called;
    const state = reading.states.get(group.key) ?? null;
    const runs = reading.running.has(group.key);
    const glyph = !runs || state === "ended" ? "✕" : state === "calling" ? "▶" : "○";
    const mark = !runs || state === "ended" ? "mark-ended" : state === "calling" ? "mark-calling" : "mark-idle";
    const activity = reading.activities.get(group.key) ?? null;
    const working = currentTask(reading.drawers.get(group.key)?.tasks ?? []);
    const under = `${set}    `;
    const sub: RowLine | null = runs
        ? {
              stretches: [{ text: `${under}${working === null ? "" : cutAt(working, COLUMNS)}`, look: "list-sub" }],
              tick: { after: under.length, said: (now) => `${doing(activity, now)}${working === null ? "" : " · "}`, look: "list-doing" },
          }
        : null;
    return {
        id: `agent ${group.key}`,
        lines: [{ stretches: padded([{ text: `${set}${glyph} `, look: mark }, { text: name, look: "list-name" }], tally) }, ...(sub === null ? [] : [sub])],
        opens: { kind: "agent", key: group.key },
        says: runs ? called : `${called}, ended`,
        writes: true,
    };
}

/** Return the row of what's for the operator, with `tally`, what's there counted across everyone. */
function forYouRow(tally: Tally): Row {
    return {
        id: "for you",
        lines: [{ stretches: padded([{ text: "» what's for you", look: "list-for-you" }], tally) }],
        opens: { kind: "for you" },
        says: "what's for you",
        writes: false,
    };
}

/** Return a heading's row, saying `text`, with `count`. */
function heading(id: string, text: string, count: string, opens: Showing | null = null, says: string = text, tally: Tally = NOTHING): Row {
    return { id, lines: [{ stretches: padded([{ text: `${text} ` }, ...(count === "" ? [] : [{ text: `· ${count}`, look: "list-count" }])], tally), look: "list-heading" }], opens, says, writes: false };
}

/** Return the last part of a repository's path, without its `.git`. */
function repositoryNamed(path: string): string {
    const name = path.split("/").filter((each) => each !== "").at(-1) ?? path;
    return name.endsWith(".git") ? name.slice(0, -".git".length) : name;
}

/**
 * Return the list by agent: what's for the operator; each agent running, a subagent under their parent, a repository
 * named where there are several; each agent no longer running with something here, under `No agent`, which opens them
 * together, nobody answering there; and lup's approvals.
 */
export function listedByAgent(reading: ListReading): Row[] {
    const groups = groupsOf(reading);
    const counted = groups.map((each) => ({ group: each, tally: agentTally(each, reading) }));
    const tallyOf = (group: Grouping) => counted.find((each) => each.group === group)?.tally ?? NOTHING;
    const rows: Row[] = [forYouRow(added(counted.map((each) => each.tally)))];
    const runningGroups = groups.filter((each) => each.conversation !== null && reading.running.has(each.key));
    rows.push(heading("heading running", "running", `${runningGroups.length}`));
    const repositories = new Set(runningGroups.map((each) => each.conversation?.repository));
    let repository: string | null = null;
    for (const { group, depth } of nested(runningGroups, reading.parents)) {
        const of = group.conversation?.repository ?? "";
        if (repositories.size > 1 && depth === 0 && of !== repository) {
            repository = of;
            rows.push({ id: `repository ${of}`, lines: [{ stretches: [{ text: repositoryNamed(of), look: "list-repository" }] }], opens: null, says: of, writes: false });
        }
        rows.push(agentRow(group, depth, reading));
    }
    const gone = groups.filter((each) => each.conversation !== null && !reading.running.has(each.key));
    if (gone.length > 0) {
        rows.push(heading("heading no agent", "No agent", `${gone.length}`, { kind: "no agent" }, "No agent: what agents who've ended left", added(gone.map(tallyOf))));
        for (const { group, depth } of nested(gone, reading.parents)) {
            rows.push(agentRow(group, depth, reading));
        }
    }
    for (const group of groups.filter((each) => each.conversation === null)) {
        rows.push(agentRow(group, 0, reading));
    }
    return rows;
}

/** Say how a thread stands in a word or two. */
function threadState(read: ThreadRead): { text: string; look: string } {
    switch (read.state) {
        case "waiting on the operator":
            return { text: "waiting on you", look: "mark-waiting" };
        case "done to confirm":
            return { text: "done, to confirm", look: "mark-waiting" };
        case "parked":
            return { text: "parked", look: "mark-parked" };
        case "settled":
            return { text: "settled", look: "list-sub" };
        case "declined":
            return { text: "declined", look: "list-sub" };
        default:
            return (read.answering ?? null) === null ? { text: "nobody running", look: "mark-ended" } : { text: read.state, look: "mark-calling" };
    }
}

/** Return how thread `read` stands: what asks the operator, what's news, the files a landing waits on and the pile; and what's drafted on it. */
function threadTally(read: ThreadRead, threads: Threading, draft: Draft): Tally {
    const written = (draft.letters ?? []).filter((each) => each.thread === read.thread.number && each.text.trim() !== "").length;
    return { asks: (read.asks ?? []).length, news: (read.new ?? []).length, files: threads.landing.get(read.thread.number) ?? 0, pile: (read.pile ?? []).length, written };
}

/** Return thread `read`'s row, set in `depth` deep: its name, how it stands and its tally; under it, what it's about and who holds it. */
function threadRow(read: ThreadRead, depth: number, threads: Threading, reading: ListReading): Row {
    const set = "  ".repeat(depth);
    const state = threadState(read);
    const holder = read.thread.holder == null ? null : reading.called(read.thread.holder);
    const answering = read.answering == null ? null : reading.called(read.answering);
    const who = answering === null ? (holder === null ? "nobody holds it" : `${holder}, ended`) : holder === answering ? `${holder} holds` : `${answering} answers`;
    return {
        id: `thread ${read.thread.number}`,
        lines: [
            { stretches: padded([{ text: set }, { text: `@${read.thread.name}`, look: "list-name" }, { text: " " }, state], threadTally(read, threads, reading.draft)) },
            { stretches: [{ text: `${set}    ${cutAt(`${about(read.thread)} · ${who}`, COLUMNS + 20)}`, look: "list-sub" }] },
        ],
        opens: { kind: "thread", number: read.thread.number },
        says: `@${read.thread.name}: ${about(read.thread)}`,
        writes: true,
    };
}

/** Return `threads`, each under its parent among them, in the order each was opened, with how deep it's set in. */
function threadsNested(threads: readonly ThreadRead[], all: readonly ThreadRead[]): { read: ThreadRead; depth: number }[] {
    const numbers = new Set(threads.map((each) => each.thread.number));
    const under = new Map<number | null, ThreadRead[]>();
    for (const each of threads.toSorted((a, b) => a.thread.number - b.thread.number)) {
        let parent = each.thread.parent ?? null;
        while (parent !== null && !numbers.has(parent)) {
            parent = all.find((one) => one.thread.number === parent)?.thread.parent ?? null;
        }
        under.set(parent, [...(under.get(parent) ?? []), each]);
    }
    const walk = (read: ThreadRead, depth: number): { read: ThreadRead; depth: number }[] => [{ read, depth }, ...(under.get(read.thread.number) ?? []).flatMap((child) => walk(child, depth + 1))];
    return (under.get(null) ?? []).flatMap((each) => walk(each, 0));
}

/**
 * Return the list by thread: what's for the operator; each agent running, a line each, whom they talk to; every thread
 * still open, nested under its parent; those nobody answers for under `No agent`; and those settled or declined, under a
 * line folding them.
 */
export function listedByThread(reading: ListReading): Row[] {
    const threads = reading.threads;
    if (threads === null) {
        return [];
    }
    const reads = threads.read.threads;
    const closed = (read: ThreadRead) => read.state === "settled" || read.state === "declined";
    const groups = groupsOf(reading);
    const counted = added(reads.map((each) => threadTally(each, threads, reading.draft)));
    // What asks the operator in no thread, as lup's own approvals, by whom it's from.
    const asked = new Set(reads.flatMap((each) => (each.asks ?? []).map((ask) => ask.node)));
    const loose = reading.items.filter((each) => toAnswer(each, reading.draft) && !asked.has(each.number)).length;
    const rows: Row[] = [forYouRow({ ...counted, asks: counted.asks + loose })];
    const runningGroups = groups.filter((each) => each.conversation !== null && reading.running.has(each.key));
    rows.push(heading("heading running", "running", `${runningGroups.length}`));
    for (const { group, depth } of nested(runningGroups, reading.parents)) {
        rows.push(agentRow(group, depth, reading));
    }
    const open = reads.filter((each) => !closed(each));
    const nobody = (read: ThreadRead) => (read.answering ?? null) === null && read.state !== "parked";
    rows.push(heading("heading threads", "threads", `${open.length} open`));
    for (const { read, depth } of threadsNested(open.filter((each) => !nobody(each)), reads)) {
        rows.push(threadRow(read, depth, threads, reading));
    }
    const gone = open.filter(nobody);
    if (gone.length > 0) {
        rows.push(heading("heading no agent", "No agent", `${gone.length}`, { kind: "no agent" }, "No agent: threads nobody answers for", added(gone.map((each) => threadTally(each, threads, reading.draft)))));
        for (const { read, depth } of threadsNested(gone, reads)) {
            rows.push(threadRow(read, depth, threads, reading));
        }
    }
    const done = reads.filter(closed);
    if (done.length > 0) {
        rows.push({ ...heading("heading settled", "settled", `${done.length}`), folds: { key: "list settled", closed: true, kind: "section" } });
        for (const { read, depth } of threadsNested(done, reads)) {
            rows.push(threadRow(read, depth, threads, reading));
        }
    }
    for (const group of groups.filter((each) => each.conversation === null)) {
        rows.push(agentRow(group, 0, reading));
    }
    return rows;
}

/** A row where it's laid out in the list's text. */
export interface PlacedRow extends Span {
    row: Row;
}

/** What's marked of the list's text: a stretch's look, from a place to another. */
export interface Marked extends Span {
    look: string;
}

/** One fold of the list, a section's. */
export interface ListFold extends Span {
    key: string;
    closed: boolean;
    kind: string;
    summary: Span;
}

/** The list's text, whose each line is, where each row is, and what's drawn on it. */
export interface ListLaid {
    text: string;
    owners: string[];
    runs: Run[];
    rows: PlacedRow[];
    marks: Marked[];
    lines: { at: number; look: string; row: string }[];
    folds: ListFold[];
    ticks: { at: number; said: (now: Date) => string; look: string }[];
}

/** Lay `rows` out as the list's text. */
export function listLaid(rows: readonly Row[]): ListLaid {
    let text = "";
    const owners: string[] = [];
    const runs: Run[] = [];
    const placed: PlacedRow[] = [];
    const marks: Marked[] = [];
    const lines: ListLaid["lines"] = [];
    const ticks: ListLaid["ticks"] = [];
    const folds: ListFold[] = [];
    let folding: { row: Row; summary: Span; opens: NonNullable<Row["folds"]> } | null = null;
    const endFold = (to: number) => {
        if (folding !== null && to > folding.summary.to) {
            folds.push({ key: folding.opens.key, closed: folding.opens.closed, kind: folding.opens.kind, summary: folding.summary, from: folding.summary.to, to });
        }
        folding = null;
    };
    for (const row of rows) {
        const from = text.length;
        for (const line of row.lines) {
            const at = text.length;
            let column = at;
            for (const stretch of line.stretches) {
                if (stretch.look !== undefined && stretch.text !== "") {
                    marks.push({ from: column, to: column + stretch.text.length, look: stretch.look });
                }
                column += stretch.text.length;
            }
            const said = line.stretches.map((each) => each.text).join("");
            text += `${said}\n`;
            owners.push(row.id);
            lines.push({ at, look: line.look ?? "", row: row.id });
            if (line.tick !== undefined) {
                ticks.push({ at: at + line.tick.after, said: line.tick.said, look: line.tick.look });
            }
        }
        const to = text.length - 1;
        const last = runs.at(-1);
        if (last !== undefined && last.owner === row.id) {
            last.to = to;
        } else {
            runs.push({ owner: row.id, from, to });
        }
        placed.push({ from, to, row });
        if (row.folds !== undefined) {
            endFold(from - 1);
            folding = { row, summary: { from, to }, opens: row.folds };
        }
    }
    endFold(text.length - 1);
    return { text, owners, runs, rows: placed, marks, lines, folds, ticks };
}

/** Return the row at `position` of what's laid out; none on no row's line. */
export function rowAt(laid: ListLaid, position: number): Row | undefined {
    return laid.rows.find((each) => position >= each.from && position <= each.to)?.row;
}

/** What a buffer says of itself over its pane, unmistakably: what it is, and whom the operator's words reach from it. */
export interface Titled {
    name: string;
    whom: string;
}

/** Return what the buffer `showing` says of itself over its pane. */
export function titled(showing: Showing, reading: Pick<ListReading, "agents" | "called" | "running" | "threads" | "items" | "banner">): Titled {
    switch (showing.kind) {
        case "for you":
            return { name: "what's for you", whom: "a comment reaches who sent the item" };
        case "no agent":
            return { name: "No agent", whom: "nobody's running: an agent's main session reads what you write when it next runs" };
        case "thread": {
            const read = reading.threads?.read.threads.find((each) => each.thread.number === showing.number);
            if (read === undefined) {
                return { name: "a thread", whom: "" };
            }
            const answering = read.answering ?? null;
            return { name: `@${read.thread.name}`, whom: answering === null ? "nobody answers for it: what you write stays on it" : `your words reach ${reading.called(answering)}` };
        }
        case "agent": {
            const conversation = reading.agents.find((each) => whose(each) === showing.key) ?? reading.items.flatMap((each) => (each.sender.party === "conversation" && whose(each.sender) === showing.key ? [each.sender] : []))[0];
            if (conversation === undefined) {
                return { name: "lup's approvals", whom: "a comment reaches the session whose push asked it" };
            }
            const name = reading.called(conversation);
            return { name, whom: reading.running.has(showing.key) ? `your words reach ${name}` : `${name} has ended: their session's main conversation reads what you write` };
        }
    }
}

/**
 * Return where the cursor goes as a buffer is first opened: on what's first to answer there; else on the line what's
 * written to them is written under, at its end, the latest of what's live just above it; else on its first item.
 */
export function arrivalIn(laid: Laid, draft: Draft): number {
    const asking = laid.regions.find((each) => toAnswer(each.item, draft));
    if (asking !== undefined) {
        return asking.header.from;
    }
    const writing = laid.groups.find((each) => each.writing !== undefined)?.writing;
    return writing?.from ?? laid.regions[0]?.header.from ?? 0;
}
