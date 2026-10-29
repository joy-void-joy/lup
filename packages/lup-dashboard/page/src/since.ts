// What the "since you approved" drawer shows beyond each changed file's own
// lines (`docs/dashboard.md`, *The drawers*): the line a file standing as the
// operator last saw it is said in, marked reviewed with the version where they
// marked it so, held at landing where a landing waits on it, each file Space
// `d` marked one at once as the reply is sent, while the host marks it; which
// place of the conversation's each file is in, a worktree and its branch or a
// branch alone; and which lines of a file changed since they last looked at it,
// the version shown when the cursor last left it, so what came in live is found
// at a glance. Pure: the review lays the line out (`review.ts`), its editor
// paints the marks on the lines in view (`Review.tsx`), and the page holds what's
// being marked (`App.tsx`).
import { shownOnce, type Filed, type Row } from "./code";
import { cited, hunks } from "./comments";
import type { components } from "./generated/api";

type Since = components["schemas"]["Since"];
type SinceFile = components["schemas"]["SinceFile"];
type SincePlace = components["schemas"]["SincePlace"];

/** How many characters of git's id for a version a line says, as git abbreviates one. */
const SHORT = 7;

/**
 * Say the line a file standing as the operator last saw it is shown in: its path, then that it's reviewed and at which
 * version, or deleted, where they marked it reviewed; else the item they saw it in; then the flagged writes on it
 * still waiting, where one came that left it as it was.
 */
export function reviewedLine(file: SinceFile): string {
    const version = file.version ?? null;
    const saw =
        file.reviewed == null
            ? file.since == null
                ? null
                : `as you saw it in ${cited(file.since)}`
            : version === null
              ? "deleted · reviewed"
              : `reviewed at ${version.slice(0, SHORT)}`;
    const flags = file.flags ?? [];
    const waiting = flags.length === 0 ? [] : [`flagged ${flags.map(cited).join(", ")}`];
    return [file.path, ...(saw === null ? [] : [saw]), ...waiting, ...heldSaid(file)].join(" · ");
}

/** Say what a file's landing waits on, where one does: held at the landing of what lands where, or that the operator declined it, which the landing answers. */
export function heldSaid(file: SinceFile): string[] {
    const held = file.held ?? null;
    if (held === null) {
        return [];
    }
    return [held.declined === true ? `landing declined: ${held.named}` : `held at landing: ${held.named}`];
}

/** Whether a file is held at landing, a landing waiting on the operator's answer to it, not declined yet. */
export function isHeld(file: SinceFile): boolean {
    return file.held != null && file.held.declined !== true;
}

/** Say which place of a conversation's a drawer's place is: its branch, in its worktree, where a worktree has it; its branch alone, read at its tip; or gone. */
export function placeSaid(place: SincePlace): string {
    const branch = place.branch == null ? "a detached HEAD" : place.branch;
    if (place.gone === true) {
        return `${branch}, gone`;
    }
    return place.worktree == null ? `${branch}, at its tip` : `${branch} in ${place.worktree}`;
}

/** Return the files of every place of a drawer, in order. */
export function filesOf(shown: Since): SinceFile[] {
    return (shown.places ?? []).flatMap((each) => each.files ?? []);
}

/** Which rows of a file changed since the operator last looked at it: each row that's new or shows otherwise; and each row lines that were shown just above it are gone from. */
export interface Fresh {
    rows: Set<Row>;
    gaps: Set<Row>;
}

const NOTHING: Fresh = { rows: new Set(), gaps: new Set() };

/** Each pair of versions' marks, once worked out: they're painted again at each scroll. */
const freshOnce = new WeakMap<Filed, WeakMap<Filed, Fresh>>();

/**
 * Return which rows of `file`, as the drawer shows it, changed since `looked`, the file as the operator last looked at
 * it: each row it shows that the drawer didn't then, or shows otherwise, an added line become one it removes say; and
 * the row after each run of rows shown then that's gone. Where they never looked at it, as a file that came after the
 * drawer was first read or came back once reviewed, each line it changes.
 */
export function freshRows(looked: Filed | null, file: Filed): Fresh {
    if (looked === file) {
        return NOTHING;
    }
    const now = shownOnce(file).rows;
    if (looked === null) {
        return { rows: new Set(now.filter((row) => row.change !== "same")), gaps: new Set() };
    }
    const kept = freshOnce.get(looked) ?? new WeakMap<Filed, Fresh>();
    const found = kept.get(file);
    if (found !== undefined) {
        return found;
    }
    const was = shownOnce(looked).rows;
    const said = (row: Row) => `${row.change} ${row.text}`;
    const changed = hunks(was.map(said), now.map(said));
    const rows = new Set(changed.flatMap((hunk) => now.slice(hunk.into, hunk.until)));
    const gaps = new Set(
        changed.flatMap((hunk) => {
            const after = now[hunk.into];
            return hunk.into === hunk.until && after !== undefined ? [after] : [];
        }),
    );
    const made = { rows, gaps };
    freshOnce.set(looked, kept.set(file, made));
    return made;
}

/** A file of a drawer the operator marked reviewed, at the version shown, which the host hasn't answered yet: its place, by its worktree and branch, its path, its version, and when they marked it. */
export interface Marking {
    worktree: string | null;
    branch: string | null;
    path: string;
    version: string | null;
    at: string;
}

/** Whether `place` is the place a marking or an answer names, by its worktree and branch. */
export function isPlace(place: SincePlace, worktree: string | null, branch: string | null): boolean {
    return (place.worktree ?? null) === worktree && (place.branch ?? null) === branch;
}

/**
 * Return the drawer `shown` as it's laid out while the host marks `marking`: each file being marked at the version it
 * shows is the line of one reviewed there, its flags approved with it, as the host's answer shows it but where the file
 * moved since; the rest as they are.
 */
export function marked(shown: Since, marking: Marking[]): Since {
    const places = shown.places ?? [];
    const now = places.map((place) => {
        const files = place.files ?? [];
        const lines = files.map((each) => {
            const mark = marking.find(
                (one) => isPlace(place, one.worktree, one.branch) && one.path === each.path && one.version === (each.version ?? null),
            );
            return mark === undefined ? each : { ...each, file: null, flags: [], since: null, reviewed: mark.at, held: null };
        });
        return lines.every((each, at) => each === files[at]) ? place : { ...place, files: lines };
    });
    return now.every((each, at) => each === places[at]) ? shown : { ...shown, places: now };
}

/**
 * Whether two readings of a drawer are laid out the same: the same places, each file the same, or each the same line
 * of one standing as the operator last saw it, as a file shown being marked and the host's answer marking it are; so
 * the review isn't laid out again for the answer.
 */
export function sameShown(a: Since, b: Since): boolean {
    const was = a.places ?? [];
    const now = b.places ?? [];
    const line = (x: SinceFile, y: SinceFile) =>
        x.file == null &&
        y.file == null &&
        x.path === y.path &&
        (x.version ?? null) === (y.version ?? null) &&
        (x.since ?? null) === (y.since ?? null) &&
        (x.reviewed == null) === (y.reviewed == null) &&
        (x.flags ?? []).join() === (y.flags ?? []).join() &&
        JSON.stringify(x.held ?? null) === JSON.stringify(y.held ?? null);
    const samePlace = (x: SincePlace, y: SincePlace) => {
        const xs = x.files ?? [];
        const ys = y.files ?? [];
        return (
            isPlace(x, y.worktree ?? null, y.branch ?? null) &&
            (x.gone ?? false) === (y.gone ?? false) &&
            xs.length === ys.length &&
            xs.every((each, at) => {
                const other = ys[at];
                return other !== undefined && (each === other || line(each, other));
            })
        );
    };
    return was.length === now.length && was.every((each, at) => {
        const other = now[at];
        return other !== undefined && (each === other || samePlace(each, other));
    });
}
