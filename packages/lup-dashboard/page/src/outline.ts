// The overview beside the review (`Outline.tsx`; `docs/dashboard.md`, *The
// review*), read from the review as it's laid out, never a second source: each
// repository, its agents, each subagent under its parent, and each agent's
// items, each with a mark of how it stands (waiting on the operator, news,
// parked) and apart, in the draft's colour, what the next Ctrl+Enter does with
// it (a comment goes, it's read, it's approved); an agent's files to review in
// its "since you approved" counted beside it. What's in view is bracketed and
// the cursor's entry highlighted as the view moves. Pure.
import type { Span } from "./comments";
import {
    fresh,
    news,
    toAnswer,
    whose,
    type Conversation,
    type Draft,
    type Group,
    type Laid,
    type Region,
} from "./review";

/** What an entry of the outline is. */
export type OutlineKind = "repository" | "agent" | "approvals" | "item";

/**
 * How an entry stands, the state it's in, each in its own colour: an item waiting on the operator, news to read, or
 * parked; a file to review, one with flagged writes waiting, or one folded whole as a test or data, in the margin; an
 * agent calling, between calls or ended. What's settled, a file reviewed, isn't shown at all.
 */
export type OutlineMark = "waiting" | "news" | "parked" | "to-review" | "flagged" | "folded" | "calling" | "idle" | "ended";

/**
 * What the draft does with an item on the next Ctrl+Enter, all in the draft's colour: comments on it go, it's marked
 * read, or it's approved, an approval marked read alone or a held change marked read or commented on.
 */
export type DraftMark = "comment" | "read" | "approve";

/** One entry: what it is, how deep it's set in, what it says, how it stands, what the draft does with it, where it is in the review, and where going to it lands. */
export interface OutlineRow extends Span {
    key: string;
    kind: OutlineKind;
    depth: number;
    text: string;
    title: string;
    marks: OutlineMark[];
    draft: DraftMark[];
    /** Whether it's new to the operator since they last sent. */
    fresh: boolean;
    at: number;
    /** What waits beside it: an agent's files to review in its "since you approved", `◇3`; none else. */
    tag: string | null;
}

/** What the outline reads beside the review as laid out. */
export interface Reading {
    draft: Draft;
    reviewed: string | null;
    /** Each conversation's parent, by `whose` each is. */
    parents: ReadonlyMap<string, string>;
    /** What each conversation running is doing, by `whose` it is. */
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

/**
 * Return how an item stands: parked, waiting on the operator or news, each but where the draft settles it; what the
 * draft does with it on the next Ctrl+Enter, as the reply does: comments on it go, it's marked read, or approved, an
 * approval marked read alone, one commented on left unanswered, a held change marked read or commented on approved;
 * and whether it's new.
 */
export function itemStanding(region: Region, draft: Draft, reviewed: string | null): Standing {
    const item = region.item;
    const number = item.number;
    const commented = (draft.comments ?? []).some((each) => each.item === number && each.text.trim() !== "");
    const done = (draft.done ?? []).includes(number);
    const parked = (draft.parked ?? []).includes(number);
    const reason = item.reason.reason;
    const approved = (reason === "approval" && done && !commented) || (reason === "held" && (done || commented));
    const drafted: DraftMark[] = parked ? [] : [...(commented ? ["comment" as const] : []), ...(approved ? ["approve" as const] : done && reason !== "approval" ? ["read" as const] : [])];
    const marks: OutlineMark[] = parked ? ["parked"] : toAnswer(item, draft) ? ["waiting"] : news(item) && !done ? ["news"] : [];
    return { marks, draft: drafted, fresh: fresh(item, reviewed) };
}

/** Return what names an item in the outline: its header's first part, `@51 question`. */
function itemText(text: string, region: Region): string {
    const header = text.slice(region.header.from, region.header.to);
    const inner = header.replace(/^── /, "").replace(/ ──$/, "");
    return inner.split(" · ")[0] ?? inner;
}

/** Return where each group's own lines end: up to the next group's banner, a subagent's nested under it among them. */
function ownEnds(laidOut: Laid): number[] {
    return laidOut.groups.map((_, at) => (laidOut.groups[at + 1]?.banner.from ?? laidOut.text.length + 1) - 1);
}

/** Return how many files a group's "since you approved" has to review, as its summary line or its label says; none where it has none. */
function toReview(text: string, group: Group): number {
    const since = group.drawers.find((each) => each.kind === "since");
    const said = since !== undefined ? text.slice(since.header.from, since.header.to) : text.slice(group.row?.labels.find((each) => each.kind === "since")?.from ?? 0, group.row?.labels.find((each) => each.kind === "since")?.to ?? 0);
    return Number(/(\d+) to review/.exec(said)?.[1] ?? 0);
}

/**
 * Return the overview of `laidOut`: each repository in the order its first group is laid out, its agents in their
 * groups' order, each subagent under its nearest forebear with a group, and under each its items, in the review's
 * order; what's left for later last.
 */
export function outlineOf(laidOut: Laid, reading: Reading): OutlineRow[] {
    const { draft, reviewed, parents, states, called } = reading;
    const text = laidOut.text;
    const ends = ownEnds(laidOut);
    const regions = laidOut.regions;
    const keyed = laidOut.groups.map((group) => (group.conversation === null ? null : whose(group.conversation)));
    const present = new Set(keyed.flatMap((each) => (each === null ? [] : [each])));
    const forebear = (key: string): string | undefined => {
        let at = parents.get(key);
        while (at !== undefined && !present.has(at)) {
            at = parents.get(at);
        }
        return at;
    };
    // Each group under the one it's under, by its place among the groups; those under none by repository.
    const under = new Map<number, number[]>();
    const tops = new Map<string, number[]>();
    laidOut.groups.forEach((group, at) => {
        if (group.later) {
            return;
        }
        const key = keyed[at] ?? null;
        const parent = key === null ? undefined : forebear(key);
        const parentAt = parent === undefined ? -1 : keyed.findIndex((each, index) => each === parent && !(laidOut.groups[index]?.later ?? true));
        if (parentAt >= 0) {
            under.set(parentAt, [...(under.get(parentAt) ?? []), at]);
        } else {
            const repository = repositoryOf(group);
            tops.set(repository, [...(tops.get(repository) ?? []), at]);
        }
    });
    const rows: OutlineRow[] = [];
    const laidGroup = (at: number, depth: number) => {
        const group = laidOut.groups[at];
        if (group === undefined) {
            return;
        }
        const from = group.banner.from;
        const to = ends[at] ?? from;
        const key = keyed[at] ?? null;
        const state = key === null ? null : (states.get(key) ?? null);
        const path = group.conversation === null ? "lup's approvals" : called(group.conversation);
        const files = toReview(text, group);
        rows.push({
            key: `group ${group.place}`,
            kind: group.conversation === null ? "approvals" : "agent",
            depth,
            text: depth > 1 ? (path.split("/").at(-1) ?? path) : path,
            title: text.slice(group.banner.from, group.banner.to),
            marks: state === "calling" ? ["calling"] : state === "idle" ? ["idle"] : state === "ended" || (state === null && group.conversation !== null) ? ["ended"] : [],
            draft: [],
            fresh: false,
            from,
            to,
            at: from,
            tag: files === 0 ? null : `◇${files}`,
        });
        const own = regions.filter((each) => each.header.from > from && each.header.from <= to);
        own.forEach((region, index) => {
            rows.push({
                key: `item ${region.item.number}`,
                kind: "item",
                depth: depth + 1,
                text: itemText(text, region),
                title: text.slice(region.header.from, region.header.to),
                ...itemStanding(region, draft, reviewed),
                from: region.header.from,
                to: Math.min((own[index + 1]?.header.from ?? to + 1) - 1, to),
                at: region.header.from,
                tag: null,
            });
        });
        for (const child of under.get(at) ?? []) {
            laidGroup(child, depth + 1);
        }
    };
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
        tag: null,
    });
    for (const [repository, groups] of tops) {
        rows.push(heading(`repository ${repository}`, last(repository), repository, laidOut.groups[groups[0] ?? 0]?.banner.from ?? 0));
        for (const at of groups) {
            laidGroup(at, 1);
        }
    }
    // What's left for later, last, as the review lays it out.
    const later = laidOut.groups.flatMap((group, at) => (group.later ? [at] : []));
    if (later.length > 0) {
        rows.push(heading("later", "later", "left for later", laidOut.groups[later[0] ?? 0]?.banner.from ?? 0));
        for (const at of later) {
            laidGroup(at, 1);
        }
    }
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
