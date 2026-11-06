// The overview beside the review (`Outline.tsx`; `docs/dashboard.md`, *The
// review*), read from the review as it's laid out, never a second source, in
// its order: each agent, a subagent under their parent as the review nests them,
// and each agent's items, a repository named where it changes, each with a mark of how it stands (waiting on the operator, news,
// parked) and apart, in the draft's colour, what the next Ctrl+Enter does with
// it (a comment goes, it's read, it's approved); what an agent's "since you
// approved" holds counted beside them. What's in view is bracketed and
// the cursor's entry highlighted as the view moves. Pure.
import { cited, type Span } from "./comments";
import { MOVE } from "./grammar";
import {
    fresh,
    type Seeing,
    toAnswer,
    toRead,
    waits,
    whose,
    type Conversation,
    type Draft,
    type Group,
    type Laid,
    type Region,
    type ThreadRead,
} from "./review";
import { NOTHING_WAITS, type BlocksTally } from "./views";

/** What an entry of the overview is: a heading, a repository's or, grouped by thread, a section's; an agent; lup's approvals; a thread; an item. */
export type OutlineKind = "repository" | "agent" | "approvals" | "thread" | "item";

/**
 * How an entry stands, the state it's in, each in its own colour: what stays stopped until the operator answers it;
 * what asks for their eyes with nothing stopped, as what's flagged, or to review with nothing holding it; news to read,
 * or parked; a file with a line that matters, or one folded whole as a test or data, in the margin; an agent calling,
 * between calls or ended. What's settled, a file reviewed, isn't shown at all.
 */
export type OutlineMark = "waiting" | "asking" | "news" | "parked" | "to-review" | "flagged" | "folded" | "calling" | "idle" | "ended";

/**
 * What the draft does with an item on the next Ctrl+Enter, all in the draft's colour: comments on it go, it's marked
 * read, it's approved, an approval or a held change marked done or read alone, or a held change commented on, it's
 * declined, or, of the pile to read, it's moved into a thread.
 */
export type DraftMark = "comment" | "read" | "approve" | "decline" | "move";

/** One entry: what it is, how deep it's set in, what it says, how it stands, what the draft does with it, where it is in the review, and where going to it lands. */
export interface OutlineRow extends Span {
    key: string;
    kind: OutlineKind;
    depth: number;
    text: string;
    title: string;
    marks: OutlineMark[];
    draft: DraftMark[];
    /** Whether it's new to the operator: its group not seen since it came, nor commented on in a reply sent. */
    fresh: boolean;
    at: number;
    /** How much of a thread or an agent's own waits on the operator, each counted by what it is to them; none else. */
    counts?: Counts;
}

/** How much of a thread or an agent's own stays stopped until the operator answers it, what's flagged for their eyes with nothing stopped, what's to review with nothing holding it, and what's only to read. */
export interface Counts extends BlocksTally {
    toRead: number;
}

/** What the overview reads beside the review as laid out. */
export interface Reading {
    draft: Draft;
    seeing: Seeing;
    /** What each conversation running is doing, by `whose` they are. */
    states: ReadonlyMap<string, string | null>;
    called: (party: Conversation) => string;
}

/** Return the last part of a path: a repository's name without its `.git`. */
function last(path: string): string {
    const name = path.split("/").filter((each) => each !== "").at(-1) ?? path;
    return name.endsWith(".git") ? name.slice(0, -".git".length) : name;
}

/** Return the repository a group is of: its thread's, its agent's, or an approval's. */
function repositoryOf(group: Group): string {
    if (group.thread !== null) {
        return group.thread.thread.repository;
    }
    if (group.conversation !== null) {
        return group.conversation.repository;
    }
    const head = group.head;
    if ("item" in head && head.item.reason.reason === "approval") {
        return head.item.reason.repository;
    }
    return "lup";
}

/** How an item stands, apart from what the draft does with it, and what that is, and whether it's new to the operator. */
export interface Standing {
    marks: OutlineMark[];
    draft: DraftMark[];
    fresh: boolean;
}

/**
 * Return how a thread's row stands in `section`: as what the host says asks the operator there, what stays stopped until
 * they answer it, or, with nothing stopped, what wants their eyes, a thread done for them to confirm among that, as in
 * waiting on you; only to read where it's only that, as in new, whatever else in it asks them, which its row there says;
 * and how much of each it holds.
 */
export function threadStanding(read: ThreadRead, section: string | undefined): { marks: OutlineMark[]; counts: Counts } {
    const asks = read.asks ?? [];
    const holds = asks.filter((each) => each.holds).length;
    const flagged = asks.length - holds + (read.state === "done to confirm" ? 1 : 0);
    const reading = (read.new ?? []).length;
    const asking: OutlineMark = holds === 0 && flagged > 0 ? "asking" : "waiting";
    if (section === "new") {
        return { marks: ["news"], counts: { ...NOTHING_WAITS, toRead: reading } };
    }
    if (section === "waiting on you") {
        return { marks: [asking], counts: { ...NOTHING_WAITS, holds, flagged, toRead: 0 } };
    }
    return { marks: holds + flagged > 0 ? [asking] : reading > 0 ? ["news"] : [], counts: { ...NOTHING_WAITS, holds, flagged, toRead: reading } };
}

/** Return the mark of a drawer holding `tally`: what stays stopped first, then what's flagged, then what's to review. */
export function drawerMark(tally: BlocksTally): OutlineMark {
    return tally.holds > 0 ? "waiting" : tally.flagged > 0 ? "asking" : "to-review";
}

/**
 * Return how an item stands: parked, asking the operator or only to read, each but where the draft settles it; what the
 * draft does with it on the next Ctrl+Enter, as the reply does: comments on it go, it's marked read, or approved, an
 * approval marked read alone, one commented on left unanswered, a held change marked read or commented on approved, a
 * mark on one past waiting doing nothing, which the host drops; and whether it's new.
 */
export function itemStanding(region: Pick<Region, "item">, draft: Draft, seeing: Seeing): Standing {
    const item = region.item;
    const number = item.number;
    const commented = (draft.comments ?? []).some((each) => each.item === number && each.text.trim() !== "");
    const open = waits(item);
    const done = open && (draft.done ?? []).includes(number);
    const declined = open && (draft.declined ?? []).includes(number);
    const parked = open && (draft.parked ?? []).includes(number);
    const reason = item.reason.reason;
    // Marked done, an approval or a held change is approved, its comments going with the yes; a held change commented on is too.
    const approved = open && !declined && ((reason === "approval" && done) || (reason === "held" && (done || commented)));
    const answered: DraftMark[] = declined ? ["decline"] : approved ? ["approve"] : done && reason !== "approval" ? ["read"] : [];
    const drafted: DraftMark[] = parked ? [] : [...(commented ? ["comment" as const] : []), ...answered];
    const marks: OutlineMark[] = parked ? ["parked"] : toAnswer(item, draft) ? [item.holds ? "waiting" : "asking"] : toRead(item, draft, seeing) ? ["news"] : [];
    return { marks, draft: drafted, fresh: fresh(item, seeing) };
}


/** Return where each group's own lines end: up to the next group's banner, a subagent's nested under it among them. */
function ownEnds(laidOut: Laid): number[] {
    return laidOut.groups.map((_, at) => (laidOut.groups[at + 1]?.banner.from ?? laidOut.text.length + 1) - 1);
}

/** Return what a group's drawers hold waiting on the operator, as each drawer's view counts it: its files in "since you approved". */
function inDrawers(group: Group): BlocksTally {
    const tallies = group.drawers.map((each) => each.view.answer?.blocks.tally ?? NOTHING_WAITS);
    return tallies.reduce((sum, each) => ({ holds: sum.holds + each.holds, flagged: sum.flagged + each.flagged, review: sum.review + each.review }), NOTHING_WAITS);
}

/** Return `counts` with `drawers`, what's in their drawers, beside what's the group's own. */
function withDrawers(counts: Counts, drawers: BlocksTally): Counts {
    return { ...counts, holds: counts.holds + drawers.holds, flagged: counts.flagged + drawers.flagged, review: counts.review + drawers.review };
}

/**
 * Return the overview of `laidOut`, in the review's order, so the two never disagree: each group's agent, set in as
 * the review nests it, then its items; a repository named before the first group of it after one of another, and
 * what's left for later after a line saying so.
 */
export function outlineOf(laidOut: Laid, reading: Reading): OutlineRow[] {
    const { draft, seeing, states, called } = reading;
    const text = laidOut.text;
    const ends = ownEnds(laidOut);
    const rows: OutlineRow[] = [];
    const heading = (key: string, said: string, title: string, at: number): OutlineRow => ({
        key,
        kind: "repository",
        depth: 0,
        text: said,
        title,
        marks: [],
        draft: [],
        fresh: false,
        from: at,
        to: at,
        at,
    });
    let repository: string | null = null;
    let later = false;
    // Grouped by thread, each section is a heading, as a repository is grouped by agent; and in open, the line the
    // ended sessions' roots are under, set in.
    let section: string | null = null;
    let endedSaid = false;
    const threaded = laidOut.sections.length > 0;
    laidOut.groups.forEach((group, at) => {
        const from = group.banner.from;
        const within = laidOut.sections.findLast((each) => each.header.from < from);
        const ended = laidOut.ended;
        if (threaded && within !== undefined && within.name !== section) {
            section = within.name;
            rows.push(heading(`section ${within.name}`, within.name, text.slice(within.header.from, within.header.to), within.header.from));
        }
        if (threaded && ended !== null && !endedSaid && from > ended.header.from && from <= ended.to) {
            endedSaid = true;
            rows.push({ ...heading("ended", "ended", text.slice(ended.header.from, ended.header.to), ended.header.from), depth: 1 });
        }
        if (threaded) {
            // Each section's heading stands for its repositories.
        } else if (group.later && !later) {
            later = true;
            rows.push(heading("later", "later", "left for later", from));
        } else if (!group.later && group.depth === 0 && repositoryOf(group) !== repository) {
            repository = repositoryOf(group);
            rows.push(heading(`repository ${repository} ${at}`, last(repository), repository, from));
        }
        const to = Math.min(ends[at] ?? from, group.end);
        if (group.thread !== null) {
            const read = group.thread;
            const own = laidOut.regions.filter((each) => each.header.from > from && each.header.from <= to);
            const standing = threadStanding(read, laidOut.sections.findLast((each) => each.header.from < from)?.name);
            rows.push({
                key: `group ${group.place}`,
                kind: "thread",
                depth: group.depth + 1,
                text: `@${read.thread.name}`,
                // Its title whole, which its banner cuts to keep to one row.
                title: `@${read.thread.name} · ${read.thread.title}`,
                marks: standing.marks,
                counts: withDrawers(standing.counts, inDrawers(group)),
                draft: [],
                fresh: false,
                from,
                to,
                at: from,
            });
            own.forEach((region, index) => {
                rows.push({
                    key: `item ${region.item.number}`,
                    kind: "item",
                    depth: group.depth + 2,
                    text: region.named,
                    title: text.slice(region.header.from, region.header.to),
                    ...itemStanding(region, draft, seeing),
                    from: region.header.from,
                    to: Math.min((own[index + 1]?.header.from ?? to + 1) - 1, to),
                    at: region.header.from,
                });
            });
            return;
        }
        const key = group.conversation === null ? null : whose(group.conversation);
        const state = key === null ? null : (states.get(key) ?? null);
        const path = group.conversation === null ? "lup's approvals" : called(group.conversation);
        const depth = group.depth + 1;
        const own = laidOut.regions.filter((each) => each.header.from > from && each.header.from <= to);
        rows.push({
            key: `group ${group.place}`,
            kind: group.conversation === null ? "approvals" : "agent",
            depth,
            text: group.depth > 0 ? (path.split("/").at(-1) ?? path) : path,
            title: text.slice(group.banner.from, group.banner.to),
            marks: state === "calling" ? ["calling"] : state === "idle" ? ["idle"] : state === "ended" || (state === null && group.conversation !== null) ? ["ended"] : [],
            draft: [],
            fresh: false,
            from,
            to,
            at: from,
            counts: withDrawers(
                {
                    ...NOTHING_WAITS,
                    holds: own.filter((each) => toAnswer(each.item, draft) && each.item.holds).length,
                    flagged: own.filter((each) => toAnswer(each.item, draft) && !each.item.holds).length,
                    toRead: own.filter((each) => toRead(each.item, draft, seeing)).length,
                },
                inDrawers(group),
            ),
        });
        own.forEach((region, index) => {
            rows.push({
                key: `item ${region.item.number}`,
                kind: "item",
                depth: depth + 1,
                text: region.named,
                title: text.slice(region.header.from, region.header.to),
                ...itemStanding(region, draft, seeing),
                from: region.header.from,
                to: Math.min((own[index + 1]?.header.from ?? to + 1) - 1, to),
                at: region.header.from,
            });
        });
    });
    // The pile to read, under its section's heading: each thread's run, and each friction and how it felt in it, news
    // until the draft reads it or moves it.
    const pileSection = laidOut.sections.find((each) => each.name === "to read");
    if (pileSection !== undefined && laidOut.pile.length > 0) {
        rows.push(heading("section to read", "to read", text.slice(pileSection.header.from, pileSection.header.to), pileSection.header.from));
        for (const run of laidOut.pile) {
            rows.push({
                key: `pile thread:${run.thread.thread.number}`,
                kind: "thread",
                depth: 1,
                text: `@${run.thread.thread.name}`,
                title: text.slice(run.header.from, run.header.to),
                marks: ["news"],
                draft: [],
                fresh: false,
                from: run.from,
                to: run.to,
                at: run.header.from,
            });
            for (const entry of run.entries) {
                const number = entry.item.number;
                const read = (draft.done ?? []).includes(number);
                const moved = (draft.marks ?? []).some((each) => each.action === MOVE && each.block === `pile ${number}`);
                rows.push({
                    key: `pile ${number}`,
                    kind: "item",
                    depth: 2,
                    text: `${cited(number)} ${entry.item.reason.reason === "friction" ? "friction" : "how it felt"}`,
                    title: text.slice(entry.header.from, entry.header.to),
                    marks: read || moved ? [] : ["news"],
                    draft: read ? ["read"] : moved ? ["move"] : [],
                    fresh: false,
                    from: entry.from,
                    to: entry.to,
                    at: entry.header.from,
                });
            }
        }
    }
    // In the review's order: the pile's among the groups', where its section is.
    return rows.toSorted((a, b) => a.from - b.from);
}

/** Return the deepest entry holding `head`: the cursor's. */
export function cursorRow(rows: readonly OutlineRow[], head: number): OutlineRow | undefined {
    let found: OutlineRow | undefined;
    for (const row of rows) {
        if (row.kind !== "repository" && head >= row.from && head <= row.to && (found === undefined || row.depth >= found.depth)) {
            found = row;
        }
    }
    return found;
}
