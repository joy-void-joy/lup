// The review in two panes, as the page opens (`docs/dashboard.md`, *The panes*): on the left, a list, itself a buffer with
// vim's keys; on the right, one buffer at a time (`Showing`), a subset of the review's tree that the one layout lays out
// (`laid`, `review.ts`). This is the list, by agent, read from what the review is laid out from, each row saying what it
// opens, how it stands and how much of it waits on the operator; its text, whose each line is, and what's drawn on it. And
// how the list's rows and a buffer say whom the operator's words reach. Pure: `Panes.tsx` draws it.
import type { Folding, Span } from "./comments";
import { doing, type Activity } from "./agents";
import type { Run } from "./reconcile";
import type { Merged } from "./looks";
import { itemStanding } from "./outline";
import { DRAFTED, GLYPHS } from "./Outline";
import {
    checkOwner,
    concernReads,
    concernsNested,
    concernWords,
    cutAt,
    grouped,
    keptUnder,
    nested,
    PARTIES,
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
    type Nested,
    type OwnedCheck,
    type Party,
    type Seeing,
    type Showing,
    type ThreadRead,
    type Threading,
} from "./review";
import { currentTask } from "./views/adapters";
import { mount } from "./views/index";
import { instanceOf, NOTHING_WAITS, type BlocksTally, type Remote, type Running, type Shown } from "./views";

export type { Showing };

/** Return whether the page's address lays the review out in panes, as the page opens, but where it says `?panes=off`, one buffer beside the overview. */
export function panesAsked(search: string): boolean {
    return new URLSearchParams(search).get("panes") !== "off";
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
        case "view":
            return `view ${showing.repository} ${showing.module} ${showing.view}`;
        default:
            return showing.kind;
    }
}

/**
 * How much of what a row stands for waits on the operator, each counted once by what it is to them: what stays stopped
 * until they answer it (an approval, a held change, a question, a problem, a file a landing waits on); what's flagged for
 * their eyes, with nothing stopped (a file with flagged writes, a check, a thread done for them to confirm, a
 * disagreement, a question that waits on no answer); the files to review with nothing holding them; what's news; and, no
 * status at all, what they've drafted there themselves.
 */
export interface Tally extends BlocksTally {
    news: number;
    written: number;
}

const NOTHING: Tally = { ...NOTHING_WAITS, news: 0, written: 0 };

/** Return `tallies` added up. */
function added(tallies: readonly Tally[]): Tally {
    return tallies.reduce((sum, each) => ({ holds: sum.holds + each.holds, flagged: sum.flagged + each.flagged, review: sum.review + each.review, news: sum.news + each.news, written: sum.written + each.written }), NOTHING);
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
    /** The row Enter goes to, where it opens nothing of its own: a concern's, from where it's context, dim, above one nested under it. */
    goes?: string;
}

/** How wide the list writes a row, tallies at its end, in characters. */
const COLUMNS = 46;

/**
 * Return the stretches of `tally`, each count in its colour, at the row's end, what stands in the order it asks of the
 * operator; what they've drafted before them, muted and set apart, being no status, so what stands stays where it is as
 * they write. None where nothing's counted.
 */
function tallied(tally: Tally): Stretch[] {
    const standing = [
        { count: tally.holds, glyph: GLYPHS.waiting, look: "mark-waiting" },
        { count: tally.flagged, glyph: GLYPHS.asking, look: "mark-asking" },
        { count: tally.review, glyph: GLYPHS["to-review"], look: "mark-to-review" },
        { count: tally.news, glyph: GLYPHS.news, look: "mark-news" },
    ].filter((one) => one.count > 0);
    const marks = standing.flatMap((one, at) => [...(at === 0 ? [] : [{ text: " " }]), { text: `${one.glyph}${one.count}`, look: one.look }]);
    return tally.written === 0 ? marks : [{ text: `${DRAFTED.comment.glyph}${tally.written}`, look: "list-written" }, ...(marks.length === 0 ? [] : [{ text: "  " }]), ...marks];
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
    /** Those the review gives a group with nothing to answer: each running, in the host's order, which is the list's, then each holding what waits. */
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
    /** The checks waiting on the operator, by agent (`checkOwner`). */
    checks?: readonly OwnedCheck[];
    /** What's new to the operator, which an item's row says. */
    seeing?: Seeing;
    /** The buffer on screen: an agent's row keeps their nest open while it's theirs, however little of it waits. */
    showing?: Showing;
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

/** Return each concern the agent named `key` answers for, as the list shows it under them (`taskOwner`, `taskShown`). */
function tasksOf(key: string, reading: Pick<ListReading, "threads">): ThreadRead[] {
    return (reading.threads?.read.threads ?? []).filter((each) => {
        const owner = taskOwner(each);
        return taskShown(each) && owner !== null && whose(owner) === key;
    });
}

/** Return whether the operator cleared a concern, settled or declined, whatever the agent's mark says: it's under what's settled. */
function cleared(read: ThreadRead): boolean {
    return (read.cleared ?? null) !== null;
}

/** Return each concern the agent said is done that the operator hasn't cleared, for their eyes, under the agent named `key`, who answers for it or left it (`keptUnder`). */
function confirmingOf(key: string, reading: Pick<ListReading, "threads">): ThreadRead[] {
    return (reading.threads?.read.threads ?? []).filter((each) => {
        const owner = keptUnder(each);
        return concernReads(each) === "for your eyes" && owner !== null && whose(owner) === key;
    });
}

/** Return what of the agent `group` is of asks the operator from what's nested under their row: their items, what stays stopped until they're answered apart from what only wants their eyes, their checks and their threads done, for them to confirm, among that. */
function askedOf(group: Grouping, reading: ListReading): Pick<BlocksTally, "holds" | "flagged"> {
    const parked = reading.draft.parked ?? [];
    const asking = group.items.filter((each) => !parked.includes(each.number) && toAnswer(each, reading.draft));
    const holds = asking.filter((each) => each.holds).length;
    return { holds, flagged: asking.length - holds + checksWaiting(group.key, reading) + confirmingOf(group.key, reading).length };
}

/** Return how the agent `group` is of stands: what of theirs waits on the operator, what's asked of them and what their "since you approved" holds, what's news, and what's drafted to them. */
function agentTally(group: Grouping, reading: ListReading): Tally {
    const { draft, drawers, looks, remote, called } = reading;
    const conversation = group.conversation;
    const parked = draft.parked ?? [];
    const open = group.items.filter((each) => !parked.includes(each.number));
    const asked = askedOf(group, reading);
    const newsCount = open.filter((each) => toRead(each, draft, reading.seeing ?? UNSEEN)).length;
    const numbers = new Set(group.items.map((each) => each.number));
    const comments = (draft.comments ?? []).filter((each) => numbers.has(each.item) && each.text.trim() !== "").length;
    const letters = conversation === null ? 0 : (draft.letters ?? []).filter((each) => each.to != null && whose(each.to) === group.key && each.text.trim() !== "").length;
    const remarks = conversation === null ? 0 : (draft.remarks ?? []).filter((each) => whose(each.to) === group.key && each.text.trim() !== "").length;
    let files = NOTHING_WAITS;
    if (conversation !== null && drawers.has(group.key)) {
        const drawn = looks.drawers(conversation.repository).find((each) => each.view === "since");
        if (drawn !== undefined) {
            const of = { runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null };
            const shown: Shown = { items: new Map(), beyond: { contexts: new Map(), files: new Map() }, drawers, running: reading.running, landings: reading.landings ?? [], called };
            files = mount(conversation.repository, drawn.module, drawn.view, of, shown, remote).answer?.blocks.tally ?? NOTHING_WAITS;
        }
    }
    return { holds: asked.holds + files.holds, flagged: asked.flagged + files.flagged, review: files.review, news: newsCount, written: comments + letters + remarks };
}

/** Return whoever owns a check waiting on the operator, or a task the list shows (`taskShown`). */
function ownersIn(reading: Pick<ListReading, "checks" | "threads">): Conversation[] {
    const ofChecks = (reading.checks ?? []).flatMap((each) => {
        const owner = checkOwner(each);
        return owner === null ? [] : [owner];
    });
    const ofTasks = (reading.threads?.read.threads ?? []).filter(taskShown).flatMap((each) => {
        const owner = keptUnder(each);
        return owner === null ? [] : [owner];
    });
    return [...ofChecks, ...ofTasks];
}

/** Return whether the list shows a concern under whoever answers for it, or in a party: one not gone, as its two marks read (`concernReads`), but what the host says is nothing to list. */
function taskShown(read: ThreadRead): boolean {
    return concernReads(read) !== "gone" && read.bare !== true;
}

/** Return the conversation of the agent named `key`, among those the review names; none where it isn't one of them, as lup's approvals. */
export function conversationNamed(key: string, reading: Pick<ListReading, "agents" | "items" | "checks" | "threads">): Conversation | undefined {
    return [...reading.agents, ...ownersIn(reading)].find((each) => whose(each) === key) ?? reading.items.flatMap((each) => (each.sender.party === "conversation" && whose(each.sender) === key ? [each.sender] : []))[0];
}

/**
 * Return every agent's group the list names, in an order what they hold has no part in: each of `agents`, as the host's
 * tree has them, so those running stay where they are; then whoever else owns a check or a task, or sent an item, and
 * lup's approvals, whom the list goes on to order by name (`byName`).
 */
function groupsOf(reading: ListReading): Grouping[] {
    const holding = new Map(grouped([...reading.items], reading.banner).map((each) => [each.key, each]));
    const listed = new Map<string, Grouping>();
    for (const conversation of [...reading.agents, ...ownersIn(reading)]) {
        const key = whose(conversation);
        if (!listed.has(key)) {
            listed.set(key, holding.get(key) ?? { key, conversation, head: { conversation }, items: [] });
        }
    }
    for (const [key, group] of holding) {
        if (!listed.has(key)) {
            listed.set(key, group);
        }
    }
    return [...listed.values()];
}

/** Return `groups` by what they're called, as those no tree of the host's orders are listed: what they hold, or when it came, moves none of them. */
function byName(groups: readonly Grouping[], called: ListReading["called"]): Grouping[] {
    const name = (group: Grouping) => (group.conversation === null ? group.key : called(group.conversation));
    return groups.toSorted((a, b) => name(a).localeCompare(name(b)) || a.key.localeCompare(b.key));
}

/** Return the row of the agent `group` is of, set in `depth` deep: how they stand, their name and their tally; under it, what they're doing, drawn, and what they're working on, and, `nesting`, what's theirs. */
function agentRow(group: Grouping, depth: number, reading: ListReading, nesting: boolean = true): Row {
    const conversation = group.conversation;
    const tally = agentTally(group, reading);
    const set = "  ".repeat(depth);
    const under = nesting ? nestOf(group, depth, reading) : undefined;
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
 * among it. Folded where nothing of it asks them and their buffer isn't on screen, so where the second pane's cursor goes
 * moves no row (`nearestShown`); none where there's nothing.
 */
function nestOf(group: Grouping, depth: number, reading: ListReading): Row["under"] {
    const set = "  ".repeat(depth + 1);
    const items = group.items.map((each) => itemRow(each, group, set, reading));
    const tasks = tasksOf(group.key, reading);
    const threads = reading.threads;
    const rows = [...items, ...(threads === null ? [] : concernsNested(tasks, threads.read.threads).map((each) => taskRow(each, set, threads, reading, group.key)))];
    if (rows.length === 0) {
        return undefined;
    }
    const id = `agent ${group.key}`;
    const onScreen = reading.showing !== undefined && bufferKey(reading.showing) === id;
    const asked = askedOf(group, reading);
    return { key: `nest ${id}`, closed: asked.holds + asked.flagged === 0 && !onScreen, kind: "section", rows };
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

/** Return the last part of what `called` calls `conversation`: a subagent by their own name, which a row has room for. */
function shortly(conversation: Conversation, reading: Pick<ListReading, "called">): string {
    const name = reading.called(conversation);
    return name.split("/").at(-1) ?? name;
}

/** Return the row of `item`, of the group `group`, set in by `set`: how it stands, as the overview marks it, its number, what it is, who left it, in a party (`left`), and how it begins, what's drafted on it at its end. */
function itemRow(item: Item, group: Grouping, set: string, reading: ListReading, left: boolean = false): Row {
    const standing = itemStanding({ item }, reading.draft, reading.seeing ?? UNSEEN);
    const mark = standing.marks[0];
    const glyph = mark === undefined ? " " : (GLYPHS[mark] ?? " ");
    const drafted = standing.draft.filter((each) => each !== "comment").map((each) => DRAFTED[each].glyph).join("");
    const named = `@${item.number} ${itemKind(item)}`;
    const leaver = left && group.conversation !== null ? group.conversation : null;
    const texts: Stretch[] = [
        { text: `${set}` },
        { text: `${glyph} `, look: mark === undefined ? "list-sub" : `mark-${mark}` },
        { text: named, look: mark === "waiting" || mark === "asking" ? "list-asks" : "list-sub" },
        ...(standing.fresh ? [{ text: " new", look: "outline-fresh" }] : []),
        ...(standing.draft.includes("comment") ? [{ text: ` ${DRAFTED.comment.glyph}`, look: "list-written" }] : []),
        ...(drafted === "" ? [] : [{ text: ` ${drafted}`, look: "outline-draft" }]),
        ...(leaver === null ? [] : [{ text: ` ${shortly(leaver, reading)}:`, look: "list-name" }]),
        { text: ` ${itemWords(item)}`, look: "list-sub" },
    ];
    return { id: `item ${item.number}`, lines: [{ stretches: fitted(texts) }], opens: { kind: "agent", key: group.key }, says: leaver === null ? named : `${named}, left by ${reading.called(leaver)}`, writes: false, node: item.number };
}

/** Return `left` cut at the list's width, as a row with no tally. */
function fitted(left: readonly Stretch[]): Stretch[] {
    return padded(left, NOTHING);
}

/**
 * Return a concern's row, set in by `set` and how deep it's nested in its nest, `entry`, among those of `at`, the nest's:
 * one line saying what it is (`concernWords`), in a look of its own, unlike an agent's name; then, as its two marks read
 * (`concernReads`), `done` where it's for the operator's eyes, `cleared` where it's quiet, the whole row muted and
 * counting nothing, and where it's gone, as under what's settled, how it ended; else what else says where it stands,
 * parked, its holder ended, or who left it where nobody running answers for it; how many of what's nested under it are
 * done or cleared; and what waits on the operator there. Dim, as context above one nested under it held elsewhere, it
 * counts nothing and Enter goes to its own row. Opened, it reads across agents as a conversation, the thread's own buffer.
 */
function taskRow(entry: Nested, set: string, threads: Threading, reading: ListReading, at: string): Row {
    const { read, depth, dim } = entry;
    const inset = `${set}${"  ".repeat(depth)}`;
    const words = concernWords(read);
    const number = read.thread.number;
    if (dim) {
        return {
            id: `context ${at} ${number}`,
            lines: [{ stretches: fitted([{ text: inset }, { text: words, look: "list-context" }]) }],
            opens: null,
            says: `${words}: what it's nested under, held elsewhere`,
            writes: false,
            goes: `thread ${number}`,
        };
    }
    const reads = concernReads(read);
    const quiet = reads === "quiet" || reads === "gone";
    // What asks them alone: what's new is on the item's row under who sent it, read by being seen there, as a thread's mark isn't.
    const tally = quiet ? NOTHING : { ...threadTally(read, threads, reading.draft), news: 0 };
    const waiting = tally.holds + tally.flagged > 0;
    // Working in the ledger's word, though whoever held it has ended and someone else answers for it: nobody is.
    const holder = read.thread.holder ?? null;
    const answering = read.answering ?? null;
    const fell = read.state === "working" && holder !== null && answering !== null && whose(holder) !== whose(answering);
    const leaver = read.left_by ?? null;
    const whoLeft = leaver === null ? null : `left by ${shortly(leaver, reading)}`;
    const stands = fell ? { text: "holder ended", look: "list-sub" } : concernState(read);
    // Being left says nobody's running.
    const word = whoLeft !== null && read.state === "nobody running" ? { ...stands, text: "" } : stands;
    const says = whoLeft === null ? word.text : word.text === "" ? whoLeft : `${word.text}, ${whoLeft}`;
    const nested = threads.read.threads.filter((each) => (each.thread.parent ?? null) === number && each.bare !== true);
    const finished = nested.filter((each) => (each.done ?? null) !== null || cleared(each)).length;
    const progress = nested.length === 0 ? "" : `${finished} of ${nested.length}`;
    const after = [says, progress].filter((each) => each !== "");
    const afterWidth = after.reduce((sum, each) => sum + each.length + 1, 0);
    const room = Math.max(COLUMNS - tallied(tally).reduce((sum, each) => sum + each.text.length, 0) - inset.length - afterWidth - 2, 14);
    const look = quiet ? "list-concern list-quiet" : "list-concern";
    const left: Stretch[] = [
        { text: inset },
        { text: cutName(words, room), look },
        ...(says === "" ? [] : [{ text: " " }, { text: says, look: waiting || reads === "for your eyes" ? word.look : "list-sub" }]),
        ...(progress === "" ? [] : [{ text: " " }, { text: progress, look: "list-sub" }]),
    ];
    return {
        id: `thread ${number}`,
        lines: [{ stretches: padded(left, tally) }],
        opens: { kind: "thread", number },
        says: [words, word.text, ...(leaver === null ? [] : [`left by ${reading.called(leaver)}`])].filter((each) => each !== "").join(", "),
        writes: !quiet,
    };
}

/** Return `name` in `most` characters, its end cut where it doesn't fit. */
function cutName(name: string, most: number): string {
    return name.length <= most ? name : `${name.slice(0, Math.max(most - 1, 1))}…`;
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
 * Return the list by agent: what's for the operator; each view a repository's modules place under it; each agent running, a subagent under their parent, a repository
 * named where there are several; each party, flat: each task it holds, with what's nested under each staying so, each
 * item an agent it holds left, and each of those agents whose drawers hold what waits, whatever else they left; and
 * lup's approvals. What nobody's in, no party and not running, isn't an agent.
 */
export function listedByAgent(reading: ListReading): Row[] {
    const groups = groupsOf(reading);
    const counted = groups.map((each) => ({ group: each, tally: agentTally(each, reading) }));
    const tallyOf = (group: Grouping) => counted.find((each) => each.group === group)?.tally ?? NOTHING;
    // What runs comes straight under what's for the operator, always in sight however long the list gets.
    const rows: Row[] = [forYouRow(added(counted.map((each) => each.tally))), ...viewRows(reading)];
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
        const held = byName(groups.filter((each) => partyOf(each) === party), reading.called);
        const tasks = threads === null ? [] : threads.read.threads.filter((each) => taskShown(each) && party.holdsTask(each, reading.running));
        const within: Row[] = [
            ...(threads === null ? [] : concernsNested(tasks, threads.read.threads).map((each) => taskRow(each, "", threads, reading, `party ${party.name}`))),
            ...held.flatMap((group) => group.items.map((item) => ({ item, group }))).toSorted((a, b) => a.item.number - b.item.number).map(({ item, group }) => itemRow(item, group, "", reading, true)),
            ...held.filter((group) => reading.agents.some((each) => whose(each) === group.key)).map((group) => agentRow(group, 0, reading, false)),
        ];
        if (within.length > 0) {
            rows.push(partyRow(party, within.length, added(held.map(tallyOf))), ...within);
        }
    }
    for (const group of byName(groups.filter((each) => each.conversation === null), reading.called)) {
        rows.push(agentRow(group, 0, reading));
    }
    if (threads !== null) {
        // Each concern the operator cleared, gone or quiet, still readable here.
        const done = threads.read.threads.filter(cleared);
        if (done.length > 0) {
            rows.push({
                ...heading("heading settled", "settled", `${done.length}`),
                under: { key: "list settled", closed: true, kind: "section", rows: concernsNested(done, threads.read.threads).map((each) => taskRow(each, "", threads, reading, "settled")) },
            });
        }
    }
    return rows;
}

/**
 * Return a row for each view a repository's modules place under the repository rather than an agent: what its view says
 * of itself and its marks, each its module's; the repository named where there are several; opening it as a buffer of
 * its own.
 */
function viewRows(reading: ListReading): Row[] {
    const { rows } = reading.looks;
    return rows.map(({ repository, drawn }) => {
        const opens: Showing = { kind: "view", repository, module: drawn.module, view: drawn.view, called: drawn.place.called };
        const answer = reading.remote.get(instanceOf(repository, drawn.module, drawn.view, {}));
        const words = (answer?.summary ?? []).map((each) => each.text).join("") || drawn.place.called;
        const left: Stretch[] = [...(rows.length > 1 ? [{ text: `${repositoryNamed(repository)} ` }] : []), { text: words, look: "list-name" }];
        return { id: bufferKey(opens), lines: [{ stretches: padded(left, { ...NOTHING, ...answer?.tally }) }], opens, says: drawn.place.called, writes: false };
    });
}

/**
 * Say how a concern stands in a word or two, by its two marks (`concernReads`): `done` for the operator's eyes; `cleared`
 * while someone's still on it; how it ended, gone; else where it stands, but working or waiting on the operator, which
 * the row's marks say, nothing.
 */
function concernState(read: ThreadRead): { text: string; look: string } {
    switch (concernReads(read)) {
        case "for your eyes":
            return { text: "done", look: "mark-asking" };
        case "quiet":
            return { text: "cleared", look: "list-sub" };
        case "gone":
            return { text: (read.done ?? null) === null ? read.state : `done, ${read.state}`, look: "list-sub" };
        default:
            break;
    }
    switch (read.state) {
        case "parked":
            return { text: "parked", look: "mark-parked" };
        case "nobody running":
            return { text: "nobody running", look: "mark-ended" };
        default:
            return { text: "", look: "list-sub" };
    }
}

/** Return how thread `read` stands: what stays stopped on the operator in it, the files a landing waits on among that; what's flagged for their eyes, its being done for them to confirm among that; what's news; and what's drafted on it. */
function threadTally(read: ThreadRead, threads: Threading, draft: Draft): Tally {
    const written = (draft.letters ?? []).filter((each) => each.thread === read.thread.number && each.text.trim() !== "").length;
    const settled = new Set([...(draft.done ?? []), ...(draft.declined ?? []), ...(draft.parked ?? [])]);
    const asking = (read.asks ?? []).filter((each) => !settled.has(each.node) && !checkAnswered(each.node, draft));
    const holds = asking.filter((each) => each.holds).length;
    return {
        holds: holds + (threads.landing.get(read.thread.number) ?? 0),
        flagged: asking.length - holds + (concernReads(read) === "for your eyes" ? 1 : 0),
        review: 0,
        news: (read.new ?? []).length,
        written,
    };
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

/** Return the row that shows the row named `id`: itself, else the nearest holding it that a closed nest doesn't hide, as `hidden` says; none where no row's named so. */
export function nearestShown(rows: readonly Row[], id: string, hidden: (row: Row) => boolean): Row | undefined {
    return pathTo(rows, id)?.findLast((each) => !hidden(each));
}

/** One part of the buffer on screen a row of the list stands for: the row's id, where it is, and how deep. */
export interface BufferSpan extends Span {
    id: string;
    depth: number;
}

/**
 * Return what the rows of the list stand for in the buffer `laid`, `showing`: each group, its agent's row; each item and
 * check, its own; and a thread's own buffer, whole, its thread's row, its items being under their senders.
 */
export function bufferSpans(laid: Laid, showing: Showing): BufferSpan[] {
    if (showing.kind === "thread") {
        return [{ id: `thread ${showing.number}`, from: 0, to: laid.text.length, depth: 0 }];
    }
    if (showing.kind === "view") {
        return [{ id: bufferKey(showing), from: 0, to: laid.text.length, depth: 0 }];
    }
    return [
        ...laid.groups.map((each) => ({
            id: `agent ${each.place.replace(/^(now|later) /, "")}`,
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

/** One fold of the list, what's nested under a row. */
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
        case "view":
            return { name: showing.called, whom: "a comment reaches whom its first line says" };
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
