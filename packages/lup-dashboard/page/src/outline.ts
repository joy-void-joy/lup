// The outline, a layout trial (`trials.ts`): a narrow pane beside the review
// mirroring it, read from the review as it's laid out, never a second source:
// each repository, its agents, each subagent under its parent, then each agent's
// items and drawers, and the files of the items and drawers in view, each with a
// mark of how it stands (new, waiting, commented, marked read, approved, parked;
// a file reviewed or not). What's in view is bracketed and the cursor's entry
// highlighted as the view moves (`Outline.tsx`). Pure.
import type { Span } from "./comments";
import {
    fresh,
    isDrawer,
    news,
    toAnswer,
    whose,
    type Conversation,
    type Draft,
    type Drawer,
    type Group,
    type Laid,
    type Region,
    type Scope,
} from "./review";
import { foldedOf } from "./code";

/** What an entry of the outline is. */
export type OutlineKind = "repository" | "agent" | "approvals" | "item" | "drawer" | "file";

/**
 * How an entry stands, the state it's in, each in its own colour: an item waiting on the operator, news to read, or
 * parked; a file to review, one with flagged writes waiting, or one folded whole as a test or data; an agent calling,
 * between calls or ended; a drawer only a label in its row. What's settled, a file reviewed, isn't listed at all.
 */
export type OutlineMark = "waiting" | "news" | "parked" | "to-review" | "flagged" | "folded" | "calling" | "idle" | "ended" | "label";

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
    /** What names the item or drawer it's of, whose files the outline lists while it's in view. */
    of: string | null;
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
    /** The items and drawers in view, by what names each (`Scope.of`): their files are listed. */
    open: ReadonlySet<string>;
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

/** Return the entries of each file `scope` shows, set in at `depth`: a drawer's files in its order, those reviewed among them, an item's in its. */
function filesOf(scope: Scope, depth: number, text: string): OutlineRow[] {
    const rows: OutlineRow[] = [];
    const drawer = isDrawer(scope) ? scope : null;
    const flagged = (path: string) => (drawer?.files.find((each) => each.path === path)?.flags ?? []).length > 0;
    for (const filed of scope.filed) {
        const path = filed.file.path;
        const stops = scope.stops.some((each) => each >= filed.from && each <= filed.to);
        const folded = foldedOf(filed.file, false) !== null;
        const marks: OutlineMark[] = drawer === null ? [stops ? "flagged" : folded ? "folded" : "to-review"] : [flagged(path) ? "flagged" : folded ? "folded" : "to-review"];
        rows.push({ key: `${scope.of} file ${path}`, kind: "file", depth, text: last(path), title: path, marks, draft: [], fresh: false, from: filed.from, to: filed.to, at: filed.from, of: scope.of });
    }
    // A file standing as the operator saw it is listed only where flagged writes still wait on it: one settled isn't.
    for (const line of drawer?.reviewed ?? []) {
        const path = line.file.path;
        if (flagged(path)) {
            rows.push({ key: `${scope.of} file ${path}`, kind: "file", depth, text: last(path), title: text.slice(line.from, line.to), marks: ["flagged"], draft: [], fresh: false, from: line.from, to: line.to, at: line.from, of: scope.of });
        }
    }
    return rows.sort((a, b) => a.from - b.from);
}

/** Return how a drawer stands in the outline: what waits in it, from its summary line. */
function drawerMarks(text: string, drawer: Drawer): OutlineMark[] {
    const said = text.slice(drawer.header.from, drawer.header.to);
    return / to review| flagged/.test(said) ? ["waiting"] : [];
}

/**
 * Return the outline of `laidOut`: each repository in the order its first group is laid out, its agents in their
 * groups' order, each subagent under its nearest forebear with a group, whether or not the review nests them; under
 * each, its items and drawers in the review's order, a drawer only a label in its row as one, and under each item and
 * drawer in view (`Reading.open`), its files.
 */
export function outlineOf(laidOut: Laid, reading: Reading): OutlineRow[] {
    const { draft, reviewed, parents, states, called, open } = reading;
    const text = laidOut.text;
    const ends = ownEnds(laidOut);
    const scopes = [...laidOut.regions, ...laidOut.drawers].sort((a, b) => a.header.from - b.header.from);
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
            of: null,
        });
        // Its drawers that are only a label in its row.
        for (const label of group.row?.labels ?? []) {
            if (!label.pulled) {
                rows.push({
                    key: `label ${label.of}`,
                    kind: "drawer",
                    depth: depth + 1,
                    text: text.slice(label.from, label.to).replace(/^[▸▾] /, ""),
                    title: "a label in the row under the banner",
                    marks: label.waiting ? ["label", "waiting"] : ["label"],
            draft: [],
            fresh: false,
                    from: label.from,
                    to: label.to,
                    at: label.from,
                    of: label.of,
                });
            }
        }
        for (const scope of scopes) {
            if (scope.header.from <= from || scope.header.from > to) {
                continue;
            }
            if (isDrawer(scope)) {
                rows.push({
                    key: `drawer ${scope.of}`,
                    kind: "drawer",
                    depth: depth + 1,
                    text: text.slice(scope.header.from, scope.header.to),
                    title: text.slice(scope.header.from, scope.header.to),
                    marks: drawerMarks(text, scope),
            draft: [],
            fresh: false,
                    from: scope.header.from,
                    to: scopeEnd(scope, scopes, to),
                    at: scope.header.from,
                    of: scope.of,
                });
            } else {
                const region = scope as Region;
                rows.push({
                    key: `item ${region.item.number}`,
                    kind: "item",
                    depth: depth + 1,
                    text: itemText(text, region),
                    title: text.slice(region.header.from, region.header.to),
                    ...itemStanding(region, draft, reviewed),
                    from: region.header.from,
                    to: scopeEnd(region, scopes, to),
                    at: region.header.from,
                    of: region.of,
                });
            }
            if (open.has(scope.of)) {
                rows.push(...filesOf(scope, depth + 2, text));
            }
        }
        for (const child of under.get(at) ?? []) {
            laidGroup(child, depth + 1);
        }
    };
    for (const [repository, groups] of tops) {
        const first = laidOut.groups[groups[0] ?? 0];
        rows.push({
            key: `repository ${repository}`,
            kind: "repository",
            depth: 0,
            text: last(repository),
            title: repository,
            marks: [],
            from: first?.banner.from ?? 0,
            draft: [],
            fresh: false,
            to: first?.banner.from ?? 0,
            at: first?.banner.from ?? 0,
            of: null,
        });
        for (const at of groups) {
            laidGroup(at, 1);
        }
    }
    // What's left for later, last, as the review lays it out.
    const later = laidOut.groups.flatMap((group, at) => (group.later ? [at] : []));
    if (later.length > 0) {
        const first = laidOut.groups[later[0] ?? 0];
        rows.push({ key: "later", kind: "repository", depth: 0, text: "later", title: "left for later", marks: [], draft: [], fresh: false, from: first?.banner.from ?? 0, to: first?.banner.from ?? 0, at: first?.banner.from ?? 0, of: null });
        for (const at of later) {
            laidGroup(at, 1);
        }
    }
    return rows;
}

/** Return where `scope` ends: before the next scope's header, or its group's end. */
function scopeEnd(scope: Scope, scopes: Scope[], groupEnd: number): number {
    const next = scopes.find((each) => each.header.from > scope.header.from);
    return Math.min(next === undefined ? groupEnd : next.header.from - 1, groupEnd);
}

/** Where each item and drawer with files is, from its header to the next scope or group: those whose files the outline lists while they're in view. */
export function filedScopes(laidOut: Laid): (Span & { of: string })[] {
    const scopes = [...laidOut.regions, ...laidOut.drawers].sort((a, b) => a.header.from - b.header.from);
    const banners = laidOut.groups.map((each) => each.banner.from);
    let group = 0;
    return scopes.flatMap((scope, at) => {
        while (group < banners.length && (banners[group] ?? Infinity) <= scope.header.from) {
            group += 1;
        }
        const next = Math.min(scopes[at + 1]?.header.from ?? Infinity, banners[group] ?? Infinity);
        const end = next === Infinity ? laidOut.text.length : next - 1;
        return scope.filed.length + (isDrawer(scope) ? scope.reviewed.length : 0) > 0 ? [{ of: scope.of, from: scope.header.from, to: end }] : [];
    });
}

/** Return the items and drawers with files `from` to `to` holds some of, of `filed`. */
export function scopesSeen(filed: readonly (Span & { of: string })[], from: number, to: number): string[] {
    return filed.flatMap((each) => (each.from <= to && each.to >= from ? [each.of] : []));
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
