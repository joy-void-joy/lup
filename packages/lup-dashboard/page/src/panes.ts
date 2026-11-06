// The review in two panes, as the page opens (`docs/dashboard.md`, *The panes*): on the left, a list, itself a buffer with
// vim's keys; on the right, one buffer at a time (`Showing`), a subset of the review's tree that the one layout lays out
// (`laid`, `review.ts`). This is the list, by agent, or by thread where the address asks (`?panes=threads`), read from what
// the review is laid out from, each row saying what it opens, how it stands and how much of it waits on the operator; its
// text, whose each line is, and what's drawn on it. And how the list's rows and a buffer say whom the operator's words
// reach. Pure: `Panes.tsx` draws it.
import type { Folding, Span } from "./comments";
import { doing, type Activity } from "./agents";
import type { Run } from "./reconcile";
import type { Merged } from "./looks";
import { itemStanding } from "./outline";
import { DRAFTED, GLYPHS } from "./Outline";
import {
    about,
    checkOwner,
    cutAt,
    grouped,
    nested,
    PARTIES,
    rootThread,
    taskOwner,
    toAnswer,
    toRead,
    UNSEEN,
    whose,
    type Conversation,
    type Draft,
    type Drawers,
    type Grouping,
    type Item,
    type Laid,
    type OwnedCheck,
    type Party,
    type Seeing,
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

/**
 * Return what the panes go by, as the page's address asks: by agent, as the page opens; by thread where it says
 * `?panes=threads`; none, the review as one buffer beside the overview, where it says `?panes=off`, or `?threads`, that buffer
 * grouped by thread.
 */
export function panesAsked(search: string): PanesBy | null {
    const address = new URLSearchParams(search);
    const asked = address.get("panes");
    if (asked === "threads") {
        return asked;
    }
    return asked === "off" || (asked === null && address.has("threads")) ? null : "agents";
}

/** Return what names a buffer among the others, which the cursor is kept by while another is on screen, and its row in the list. */
export function bufferKey(showing: Showing): string {
    switch (showing.kind) {
        case "agent":
            return `agent ${showing.key}`;
        case "thread":
            return `thread ${showing.number}`;
        case "party":
            return `party ${showing.name}`;
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
    /** The item or check it stands for, by number, which going to it lands on. */
    node?: number;
    /** The rows nested under it, folding under it, quiet until opened; what names their fold, and whether it starts closed. */
    under?: { key: string; closed: boolean; kind: string; rows: Row[] };
}

/** How wide the list writes a row, tallies at its end, in characters. */
const COLUMNS = 46;

/** The glyphs of how a row stands, as the overview's (`Outline.tsx`). */
const WAITING = "◆";
const NEWS = "•";
const TO_REVIEW = "◇";
const PILE = "≈";
const WRITTEN = "»";

/** Return the stretches of `tally`, each count in its colour; none where nothing's counted. */
function tallied(tally: Tally): Stretch[] {
    const each = [
        { count: tally.asks, glyph: WAITING, look: "mark-waiting" },
        { count: tally.news, glyph: NEWS, look: "mark-news" },
        { count: tally.files, glyph: TO_REVIEW, look: "mark-to-review" },
        { count: tally.pile, glyph: PILE, look: "mark-pile" },
        { count: tally.written, glyph: WRITTEN, look: "outline-draft" },
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
    /** The words naming the group of what `item` is of, by which the review tells lup's approvals of one repository's from another's (`grouped`). */
    banner: (item: Item) => string;
    drawers: Drawers;
    looks: Merged;
    remote: Remote;
    running: ReadonlyMap<string, Running>;
    activities: ReadonlyMap<string, Activity | null>;
    states: ReadonlyMap<string, string | null>;
    threads: Threading | null;
    landings?: Shown["landings"];
    /** The checks waiting on the operator, by agent (`checkOwner`), where the list goes by agent. */
    checks?: readonly OwnedCheck[];
    /** What's new to the operator, which an item's row says. */
    seeing?: Seeing;
    /** The rows whose nest is open however little of it waits: what's on screen and where the second pane's cursor has been, by row. */
    opened?: ReadonlySet<string>;
    /** The parties listed beside the agents; unsaid, those declared (`PARTIES`). */
    parties?: readonly Party[];
}

/** Return the number of a check as the draft marks it answered: ticked, or a comment on it its answer in words. */
function checkAnswered(number: number, draft: Draft): boolean {
    return (draft.marks ?? []).some((each) => each.block === `check ${number}`) || (draft.comments ?? []).some((each) => each.item === number && each.text.trim() !== "");
}

/** Return how many checks of the agent named `key` still wait on the operator, as the draft stands. */
function checksWaiting(key: string, reading: Pick<ListReading, "checks" | "draft">): number {
    return (reading.checks ?? []).filter((each) => {
        const owner = checkOwner(each);
        return owner !== null && whose(owner) === key && !checkAnswered(each.check.check.number, reading.draft);
    }).length;
}

/** Return each thread open that the agent named `key` owns, as a task (`taskOwner`). */
function tasksOf(key: string, reading: Pick<ListReading, "threads">): ThreadRead[] {
    return (reading.threads?.read.threads ?? []).filter((each) => {
        const owner = taskOwner(each);
        return !closedTask(each) && owner !== null && whose(owner) === key;
    });
}

/** Return whether a thread's over, settled or declined. */
function closedTask(read: ThreadRead): boolean {
    return read.state === "settled" || read.state === "declined";
}

/** Return each thread the agent named `key` owns that's done, for the operator to confirm. */
function confirmingOf(key: string, reading: Pick<ListReading, "threads">): ThreadRead[] {
    return tasksOf(key, reading).filter((each) => each.state === "done to confirm");
}

/** Return how the agent `group` is of stands: what of theirs asks the operator, what's news, what's left to review in their "since you approved", and what's drafted to them. */
function agentTally(group: Grouping, reading: ListReading): Tally {
    const { draft, drawers, looks, remote, called } = reading;
    const conversation = group.conversation;
    const parked = draft.parked ?? [];
    const open = group.items.filter((each) => !parked.includes(each.number));
    const asks = open.filter((each) => toAnswer(each, draft)).length + checksWaiting(group.key, reading) + confirmingOf(group.key, reading).length;
    const newsCount = open.filter((each) => toRead(each, draft, reading.seeing ?? UNSEEN)).length;
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

/** Return whoever owns a check waiting on the operator, or a task the list shows (`taskShown`). */
function ownersIn(reading: Pick<ListReading, "checks" | "threads">): Conversation[] {
    const ofChecks = (reading.checks ?? []).flatMap((each) => {
        const owner = checkOwner(each);
        return owner === null ? [] : [owner];
    });
    const ofTasks = (reading.threads?.read.threads ?? []).filter(taskShown).flatMap((each) => {
        const owner = taskOwner(each);
        return owner === null ? [] : [owner];
    });
    return [...ofChecks, ...ofTasks];
}

/**
 * Return whether the list shows a thread as a task: one still open, but a session's own root with nothing in it asking,
 * which is no concern of its own, and would list each session a second time.
 */
function taskShown(read: ThreadRead): boolean {
    return !closedTask(read) && (!rootThread(read) || (read.asks ?? []).length > 0 || (read.new ?? []).length > 0 || read.state === "done to confirm");
}

/** Return the conversation of the agent named `key`, among those the review names; none where it isn't one of them, as lup's approvals. */
export function conversationNamed(key: string, reading: Pick<ListReading, "agents" | "items" | "checks" | "threads">): Conversation | undefined {
    return [...reading.agents, ...ownersIn(reading)].find((each) => whose(each) === key) ?? reading.items.flatMap((each) => (each.sender.party === "conversation" && whose(each.sender) === key ? [each.sender] : []))[0];
}

/** Return every agent's group the list names, with those of lup's approvals: each with an item, then each of `agents` with none. */
function groupsOf(reading: ListReading): Grouping[] {
    const groups = grouped([...reading.items], reading.banner);
    const keys = new Set(groups.map((each) => each.key));
    const owners = ownersIn(reading);
    const empty = [...reading.agents, ...owners].flatMap((conversation): Grouping[] => {
        const key = whose(conversation);
        if (keys.has(key)) {
            return [];
        }
        keys.add(key);
        return [{ key, conversation, head: { conversation }, items: [] }];
    });
    return [...groups, ...empty];
}

/** Return the row of the agent `group` is of, set in `depth` deep: how they stand, their name and their tally; under it, what they're doing, drawn, and what they're working on. */
function agentRow(group: Grouping, depth: number, reading: ListReading, nesting: boolean = true): Row {
    const conversation = group.conversation;
    const tally = agentTally(group, reading);
    const set = "  ".repeat(depth);
    const under = nesting ? nestOf(group, depth, tally, reading) : undefined;
    if (conversation === null) {
        return {
            id: `agent ${group.key}`,
            lines: [{ stretches: padded([{ text: `${set}⚑ `, look: "mark-flagged" }, { text: "lup's approvals" }], tally) }],
            opens: { kind: "agent", key: group.key },
            says: "lup's approvals",
            writes: false,
            ...(under === undefined ? {} : { under }),
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
    const setIn = `${set}    `;
    const sub: RowLine | null = runs
        ? {
              stretches: [{ text: `${setIn}${working === null ? "" : cutAt(working, COLUMNS)}`, look: "list-sub" }],
              tick: { after: setIn.length, said: (now) => `${doing(activity, now)}${working === null ? "" : " · "}`, look: "list-doing" },
          }
        : null;
    return {
        id: `agent ${group.key}`,
        lines: [{ stretches: padded([{ text: `${set}${glyph} `, look: mark }, { text: name, look: "list-name" }], tally) }, ...(sub === null ? [] : [sub])],
        opens: { kind: "agent", key: group.key },
        says: runs ? called : `${called}, ended`,
        writes: true,
        ...(under === undefined ? {} : { under }),
    };
}

/**
 * Return what's nested under the agent `group` is of, `depth` deep: each item of theirs, as the review lays it out, marked
 * as the overview marks it; then each task of theirs, a line each, quiet, but what waits on the operator there, its checks
 * among it. Folded where nothing of it asks them, until what's on screen comes to it; none where there's nothing.
 */
function nestOf(group: Grouping, depth: number, tally: Tally, reading: ListReading): Row["under"] {
    const set = "  ".repeat(depth + 1);
    const items = group.items.map((each) => itemRow(each, group, set, reading));
    const tasks = tasksOf(group.key, reading).filter(taskShown);
    const threads = reading.threads;
    const rows = [...items, ...(threads === null ? [] : threadsNested(tasks, threads.read.threads).map(({ read, depth: within }) => taskRow(read, set, within, threads, reading)))];
    if (rows.length === 0) {
        return undefined;
    }
    const id = `agent ${group.key}`;
    return { key: `nest ${id}`, closed: tally.asks === 0 && reading.opened?.has(id) !== true, kind: "section", rows };
}

/** Return the first words of what an item says, for its row: its own title where it has one; none where it says nothing of its own. */
function itemWords(item: Item): string {
    const reason = item.reason;
    const text = "text" in reason && typeof reason.text === "string" ? reason.text : "";
    return text.split("\n").find((each) => each.trim() !== "")?.trim() ?? "";
}

/** Say what kind of item it is, as a word: a message by its own kind, or as a turn's end. */
function itemKind(item: Item): string {
    const reason = item.reason;
    return reason.reason === "message" ? (reason.ending ? "turn ended" : reason.kind) : reason.reason;
}

/** Return the row of `item`, of the group `group`, set in by `set`: how it stands, as the overview marks it, its number, what it is and how it begins, what's drafted on it at its end. */
function itemRow(item: Item, group: Grouping, set: string, reading: ListReading): Row {
    const standing = itemStanding({ item }, reading.draft, reading.seeing ?? UNSEEN);
    const mark = standing.marks[0];
    const glyph = mark === undefined ? " " : (GLYPHS[mark] ?? " ");
    const drafted = standing.draft.map((each) => DRAFTED[each].glyph).join("");
    const named = `@${item.number} ${itemKind(item)}`;
    const left: Stretch[] = [
        { text: `${set}` },
        { text: `${glyph} `, look: mark === undefined ? "list-sub" : `mark-${mark}` },
        { text: named, look: mark === "waiting" ? "list-asks" : "list-sub" },
        ...(standing.fresh ? [{ text: " new", look: "outline-fresh" }] : []),
        ...(drafted === "" ? [] : [{ text: ` ${drafted}`, look: "outline-draft" }]),
        { text: ` ${itemWords(item)}`, look: "list-sub" },
    ];
    return { id: `item ${item.number}`, lines: [{ stretches: fitted(left) }], opens: { kind: "agent", key: group.key }, says: named, writes: false, node: item.number };
}

/** Return `left` cut at the list's width, as a row with no tally. */
function fitted(left: readonly Stretch[]): Stretch[] {
    return padded(left, NOTHING);
}

/**
 * Return a task's row, set in by `set` and how deep it's nested among its owner's: one line, quiet, but what waits on the
 * operator there; opened, it reads across agents as a conversation, the thread's own buffer.
 */
function taskRow(read: ThreadRead, set: string, depth: number, threads: Threading, reading: ListReading): Row {
    const tally = threadTally(read, threads, reading.draft);
    const waiting = tally.asks + tally.files > 0;
    // Working in the ledger's word, though whoever held it has ended and someone else answers for it: nobody is.
    const holder = read.thread.holder ?? null;
    const answering = read.answering ?? null;
    const fell = read.state === "working" && holder !== null && answering !== null && whose(holder) !== whose(answering);
    const state = fell ? { text: "holder ended", look: "list-sub" } : threadState(read);
    const left: Stretch[] = [
        { text: `${set}${"  ".repeat(depth)}` },
        { text: `@${read.thread.name}`, look: waiting ? "list-name" : "list-sub" },
        { text: " " },
        waiting ? state : { text: state.text, look: "list-sub" },
    ];
    // What asks them alone: what's new is on the item's row under who sent it, read by being seen there, as a thread's mark isn't.
    const quiet = { ...tally, news: 0, pile: 0 };
    return { id: `thread ${read.thread.number}`, lines: [{ stretches: padded(left, quiet) }], opens: { kind: "thread", number: read.thread.number }, says: `@${read.thread.name}: ${about(read.thread)}`, writes: true };
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

/** Return `party`'s row, opening its buffer, with `count` of what's in it. */
function partyRow(party: Party, count: number, tally: Tally): Row {
    return heading(`party ${party.name}`, party.called, `${count}`, { kind: "party", name: party.name }, party.says, tally);
}

/**
 * Return the list by agent: what's for the operator; each agent running, a subagent under their parent, a repository
 * named where there are several; each party, each agent it holds with what's theirs nested under them, and each task it
 * holds that nobody ever owned; and lup's approvals. What nobody's in, no party and not running, isn't an agent.
 */
export function listedByAgent(reading: ListReading): Row[] {
    const groups = groupsOf(reading);
    const counted = groups.map((each) => ({ group: each, tally: agentTally(each, reading) }));
    const tallyOf = (group: Grouping) => counted.find((each) => each.group === group)?.tally ?? NOTHING;
    const rows: Row[] = [forYouRow(added(counted.map((each) => each.tally)))];
    const parties = reading.parties ?? PARTIES;
    // Each agent under the first party holding them; the rest, running, on their own.
    const partyOf = (group: Grouping) => parties.find((each) => each.holds(group, reading.running));
    const runningGroups = groups.filter((each) => each.conversation !== null && reading.running.has(each.key) && partyOf(each) === undefined);
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
    const threads = reading.threads;
    for (const party of parties) {
        const held = groups.filter((each) => partyOf(each) === party);
        // A task no agent's ever owned sits in the party itself; one whose owner it holds, with them.
        const unowned = threads === null ? [] : threads.read.threads.filter((each) => taskShown(each) && taskOwner(each) === null && party.holdsTask(each, reading.running));
        if (held.length > 0 || unowned.length > 0) {
            rows.push(partyRow(party, held.length + unowned.length, added(held.map(tallyOf))));
            if (threads !== null) {
                for (const { read, depth } of threadsNested(unowned, threads.read.threads)) {
                    rows.push(taskRow(read, "", depth, threads, reading));
                }
            }
            for (const { group, depth } of nested(held, reading.parents)) {
                rows.push(agentRow(group, depth, reading));
            }
        }
    }
    for (const group of groups.filter((each) => each.conversation === null)) {
        rows.push(agentRow(group, 0, reading));
    }
    if (threads !== null) {
        const done = threads.read.threads.filter(closedTask);
        if (done.length > 0) {
            rows.push({
                ...heading("heading settled", "settled", `${done.length}`),
                under: { key: "list settled", closed: true, kind: "section", rows: threadsNested(done, threads.read.threads).map(({ read, depth }) => taskRow(read, "", depth, threads, reading)) },
            });
        }
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
    const settled = new Set([...(draft.done ?? []), ...(draft.declined ?? []), ...(draft.parked ?? [])]);
    const asking = (read.asks ?? []).filter((each) => !settled.has(each.node) && !checkAnswered(each.node, draft));
    return { asks: asking.length + (read.state === "done to confirm" ? 1 : 0), news: (read.new ?? []).length, files: threads.landing.get(read.thread.number) ?? 0, pile: (read.pile ?? []).length, written };
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
    // Whom to talk to, a line each: what's theirs is under the threads here, each a row of its own.
    const asAgents: ListReading = { ...reading, threads: null };
    for (const { group, depth } of nested(runningGroups, reading.parents)) {
        rows.push(agentRow(group, depth, asAgents, false));
    }
    const open = reads.filter((each) => !closed(each));
    const parties = reading.parties ?? PARTIES;
    const partyOf = (read: ThreadRead) => parties.find((each) => each.holdsTask(read, reading.running));
    rows.push(heading("heading threads", "threads", `${open.length} open`));
    for (const { read, depth } of threadsNested(open.filter((each) => partyOf(each) === undefined), reads)) {
        rows.push(threadRow(read, depth, threads, reading));
    }
    for (const party of parties) {
        const held = open.filter((each) => partyOf(each) === party);
        if (held.length > 0) {
            rows.push(partyRow(party, held.length, added(held.map((each) => threadTally(each, threads, reading.draft)))));
            for (const { read, depth } of threadsNested(held, reads)) {
                rows.push(threadRow(read, depth, threads, reading));
            }
        }
    }
    const done = reads.filter(closed);
    if (done.length > 0) {
        rows.push({
            ...heading("heading settled", "settled", `${done.length}`),
            under: { key: "list settled", closed: true, kind: "section", rows: threadsNested(done, reads).map(({ read, depth }) => threadRow(read, depth, threads, reading)) },
        });
    }
    for (const group of groups.filter((each) => each.conversation === null)) {
        rows.push(agentRow(group, 0, asAgents, false));
    }
    return rows;
}

/** Return the rows holding the row named `id`, outermost first, and it last; none where it's in none of `rows`. */
export function pathTo(rows: readonly Row[], id: string): Row[] | null {
    for (const row of rows) {
        if (row.id === id) {
            return [row];
        }
        const within = row.under === undefined ? null : pathTo(row.under.rows, id);
        if (within !== null) {
            return [row, ...within];
        }
    }
    return null;
}

/** One part of the buffer on screen a row of the list stands for: the row's id, where it is, and how deep. */
export interface BufferSpan extends Span {
    id: string;
    depth: number;
}

/**
 * Return what the rows of the list stand for in the buffer `laid`, `showing`: each group, its agent's row or its
 * thread's; each item and check, its own; and a thread's own buffer, whole, its thread's row, its items being under their
 * senders.
 */
export function bufferSpans(laid: Laid, showing: Showing): BufferSpan[] {
    if (showing.kind === "thread") {
        return [{ id: `thread ${showing.number}`, from: 0, to: laid.text.length, depth: 0 }];
    }
    return [
        ...laid.groups.map((each) => ({
            id: each.thread === null ? `agent ${each.place.replace(/^(now|later) /, "")}` : `thread ${each.thread.thread.number}`,
            from: each.banner.from,
            to: each.end,
            depth: each.depth,
        })),
        ...laid.regions.map((each) => ({ id: `item ${each.item.number}`, from: each.header.from, to: each.end, depth: 100 })),
        // A check is its task's: they're one row in the list.
        ...laid.checks.map((each) => ({ id: `thread ${each.thread}`, from: each.from, to: each.to, depth: 100 })),
    ];
}

/** Return the row the second pane's cursor is on: the deepest of `spans` holding `head`, that the list has (`known`). */
export function spanAt(spans: readonly BufferSpan[], head: number, known: (id: string) => boolean): string | null {
    let found: BufferSpan | null = null;
    for (const each of spans) {
        if (head >= each.from && head <= each.to && known(each.id) && (found === null || each.depth >= found.depth)) {
            found = each;
        }
    }
    return found?.id ?? null;
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
    const write = (row: Row) => {
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
        runs.push({ owner: row.id, from, to });
        placed.push({ from, to, row });
        const under = row.under;
        if (under !== undefined && under.rows.length > 0) {
            under.rows.forEach(write);
            folds.push({ key: under.key, closed: under.closed, kind: under.kind, summary: { from, to }, from: to, to: text.length - 1 });
        }
    };
    rows.forEach(write);
    folds.sort((a, b) => a.from - b.from || b.to - a.to);
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
export function titled(showing: Showing, reading: Pick<ListReading, "agents" | "called" | "running" | "threads" | "items" | "checks" | "parties">): Titled {
    switch (showing.kind) {
        case "for you":
            return { name: "what's for you", whom: "a comment reaches who sent the item" };
        case "party": {
            const party = (reading.parties ?? PARTIES).find((each) => each.name === showing.name);
            return { name: party?.called ?? showing.name, whom: party?.whom ?? "" };
        }
        case "thread": {
            const read = reading.threads?.read.threads.find((each) => each.thread.number === showing.number);
            if (read === undefined) {
                return { name: "a thread", whom: "" };
            }
            const answering = read.answering ?? null;
            return { name: `@${read.thread.name}`, whom: answering === null ? "nobody answers for it: what you write stays on it" : `your words reach ${reading.called(answering)}` };
        }
        case "agent": {
            const conversation = conversationNamed(showing.key, reading);
            if (conversation === undefined) {
                return { name: "lup's approvals", whom: "a comment reaches the session whose push asked it" };
            }
            const name = reading.called(conversation);
            return { name, whom: reading.running.has(showing.key) ? `your words reach ${name}` : `${name} has ended: their session's main conversation reads what you write` };
        }
    }
}

/**
 * Return where the cursor goes as a buffer is first opened: on the first item to answer there; else on the line what's
 * written to them is written under, at its end, the latest of what's live and any checks of theirs just above it; else
 * on what's first there.
 */
export function arrivalIn(laid: Laid, draft: Draft): number {
    const asking = laid.regions.find((each) => toAnswer(each.item, draft))?.header.from;
    const writing = laid.groups.find((each) => each.writing !== undefined)?.writing?.from;
    return asking ?? writing ?? laid.checks[0]?.from ?? laid.regions[0]?.header.from ?? 0;
}

/** The folds' kinds the margin leaves out in panes, what the list and each banner say already. */
const NOT_IN_MARGIN = new Set(["group", "section"]);

const marginKept = new WeakMap<readonly Folding[], readonly Folding[]>();

/** Return of `folds` those the margin shows in panes, the same list while they're the same, which the margin reads each by. */
export function marginFolds<F extends Folding>(folds: readonly F[]): readonly F[] {
    const kept = marginKept.get(folds);
    if (kept !== undefined) {
        return kept as readonly F[];
    }
    const made = folds.filter((each) => !NOT_IN_MARGIN.has(each.kind ?? ""));
    marginKept.set(folds, made);
    return made;
}
