// The overview beside the review (`Outline.tsx`; `docs/dashboard.md`, *The
// review*), read from the review as it's laid out, never a second source, in
// its order: each agent, a subagent under their parent as the review nests them,
// and each agent's items, a repository named where it changes, each with a mark of how it stands (waiting on the operator, news,
// set aside in a pile) and apart, in the draft's colour, what the next Ctrl+Enter does with
// it (a comment goes, it's read, it's approved, it's sent somewhere); what an agent's "since you
// approved" holds counted beside them. What's in view is bracketed and
// the cursor's entry highlighted as the view moves. Pure.
import type { Span } from "./comments";
import {
    fresh,
    itemsSent,
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
} from "./review";
import { NOTHING_WAITS, type BlocksTally } from "./views";

/** What an entry of the overview is: a heading, a repository's; an agent; lup's approvals; an item. */
export type OutlineKind = "repository" | "agent" | "approvals" | "item";

/**
 * How an entry stands, the state it's in, each in its own colour: what stays stopped until the operator answers it;
 * what asks for their eyes with nothing stopped, as what's flagged, or to review with nothing holding it; news to read,
 * or set aside in a pile (`parked`); a file with a line that matters, or one folded whole as a test or data, in the margin; an agent calling,
 * between calls or ended. What's settled, a file reviewed, isn't shown at all.
 */
export type OutlineMark = "waiting" | "asking" | "news" | "parked" | "to-review" | "flagged" | "folded" | "calling" | "idle" | "ended";

/**
 * What the draft does with an item on the next Ctrl+Enter, all in the draft's colour: comments on it go, it's marked
 * read, it's approved, an approval or a held change marked done or read alone, or a held change commented on, it's
 * declined, or it's sent into a concern or a pile.
 */
export type DraftMark = "comment" | "read" | "approve" | "decline" | "send";

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
    /** How much of an agent's own waits on the operator, each counted by what it is to them; none else. */
    counts?: Counts;
}

/** How much of an agent's own stays stopped until the operator answers it, what's flagged for their eyes with nothing stopped, what's to review with nothing holding it, and what's only to read. */
export interface Counts extends BlocksTally {
    toRead: number;
}

/** What the overview reads beside the review as laid out. */
export interface Reading {
    draft: Draft;
    seeing: Seeing;
    /** The items set aside in a pile (`piledIn`). */
    piled: ReadonlySet<number>;
    /** What each conversation running is doing, by `whose` they are. */
    states: ReadonlyMap<string, string | null>;
    called: (party: Conversation) => string;
}

/** Return the last part of a path: a repository's name without its `.git`. */
function last(path: string): string {
    const name = path.split("/").filter((each) => each !== "").at(-1) ?? path;
    return name.endsWith(".git") ? name.slice(0, -".git".length) : name;
}

/** Return the repository a group is of: its agent's, or an approval's. */
function repositoryOf(group: Group): string {
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

/** Return the mark of a drawer holding `tally`: what stays stopped first, then what's flagged, then what's to review. */
export function drawerMark(tally: BlocksTally): OutlineMark {
    return tally.holds > 0 ? "waiting" : tally.flagged > 0 ? "asking" : "to-review";
}

/**
 * Return how an item stands: set aside in a pile, asking the operator or only to read, each but where the draft settles
 * it; what the draft does with it on the next Ctrl+Enter, as the reply does: comments on it go, it's marked read, or
 * approved, an approval marked read alone, one commented on left unanswered, a held change marked read or commented on
 * approved, it's sent into a concern or a pile, a mark on one past waiting doing nothing, which the host drops; and
 * whether it's new.
 */
export function itemStanding(region: Pick<Region, "item">, draft: Draft, seeing: Seeing, piled: ReadonlySet<number>): Standing {
    const item = region.item;
    const number = item.number;
    const commented = (draft.comments ?? []).some((each) => each.item === number && each.text.trim() !== "");
    const open = waits(item);
    const done = open && (draft.done ?? []).includes(number);
    const declined = open && (draft.declined ?? []).includes(number);
    const sent = open && itemsSent(draft).has(number);
    const reason = item.reason.reason;
    // Marked done, an approval or a held change is approved, its comments going with the yes; a held change commented on is too.
    const approved = open && !declined && ((reason === "approval" && done) || (reason === "held" && (done || commented)));
    const answered: DraftMark[] = sent ? ["send"] : declined ? ["decline"] : approved ? ["approve"] : done && reason !== "approval" ? ["read"] : [];
    const drafted: DraftMark[] = [...(commented ? ["comment" as const] : []), ...answered];
    const marks: OutlineMark[] = piled.has(number) ? ["parked"] : toAnswer(item, draft, piled) ? [item.holds ? "waiting" : "asking"] : toRead(item, draft, seeing, piled) ? ["news"] : [];
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
 * the review nests it, then its items; a repository named before the first group of it after one of another.
 */
export function outlineOf(laidOut: Laid, reading: Reading): OutlineRow[] {
    const { draft, seeing, states, called, piled } = reading;
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
    laidOut.groups.forEach((group, at) => {
        const from = group.banner.from;
        if (group.depth === 0 && repositoryOf(group) !== repository) {
            repository = repositoryOf(group);
            rows.push(heading(`repository ${repository} ${at}`, last(repository), repository, from));
        }
        const to = Math.min(ends[at] ?? from, group.end);
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
                    holds: own.filter((each) => toAnswer(each.item, draft, piled) && each.item.holds).length,
                    flagged: own.filter((each) => toAnswer(each.item, draft, piled) && !each.item.holds).length,
                    toRead: own.filter((each) => toRead(each.item, draft, seeing, piled)).length,
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
                ...itemStanding(region, draft, seeing, piled),
                from: region.header.from,
                to: Math.min((own[index + 1]?.header.from ?? to + 1) - 1, to),
                at: region.header.from,
            });
        });
    });
    return rows;
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
