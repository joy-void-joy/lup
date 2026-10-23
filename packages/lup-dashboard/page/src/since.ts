// What the "since you approved" drawer shows beyond each changed file's own
// lines (`docs/dashboard.md`, *The drawers*): the line a file standing as the
// operator last saw it is said in, marked reviewed with the version where they
// marked it so; and which lines of a file changed since they last looked at
// it, the version shown when the cursor last left it, so what came in live is
// found at a glance. Pure: the review lays the line out (`review.ts`), and its
// editor paints the marks on the lines in view (`Review.tsx`).
import { shownOnce, type ChangedFile, type Row } from "./code";
import { cited, hunks } from "./comments";
import type { components } from "./generated/api";

type SinceFile = components["schemas"]["SinceFile"];

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
            ? `as you saw it in ${file.since == null ? "an item" : cited(file.since)}`
            : version === null
              ? "deleted · reviewed"
              : `reviewed at ${version.slice(0, SHORT)}`;
    const flags = file.flags ?? [];
    const waiting = flags.length === 0 ? [] : [`flagged ${flags.map(cited).join(", ")}`];
    return [file.path, saw, ...waiting].join(" · ");
}

/** Which rows of a file changed since the operator last looked at it: each row that's new or shows otherwise; and each row lines that were shown just above it are gone from. */
export interface Fresh {
    rows: Set<Row>;
    gaps: Set<Row>;
}

const NOTHING: Fresh = { rows: new Set(), gaps: new Set() };

/** Each pair of versions' marks, once worked out: they're painted again at each scroll. */
const freshOnce = new WeakMap<ChangedFile, WeakMap<ChangedFile, Fresh>>();

/**
 * Return which rows of `file`, as the drawer shows it, changed since `looked`, the file as the operator last looked at
 * it: each row it shows that the drawer didn't then, or shows otherwise, an added line become one it removes say; and
 * the row after each run of rows shown then that's gone. Where they never looked at it, as a file that came after the
 * drawer was first read or came back once reviewed, each line it changes.
 */
export function freshRows(looked: ChangedFile | null, file: ChangedFile): Fresh {
    if (looked === file) {
        return NOTHING;
    }
    const now = shownOnce(file, "changes").rows;
    if (looked === null) {
        return { rows: new Set(now.filter((row) => row.change !== "same")), gaps: new Set() };
    }
    const kept = freshOnce.get(looked) ?? new WeakMap<ChangedFile, Fresh>();
    const found = kept.get(file);
    if (found !== undefined) {
        return found;
    }
    const was = shownOnce(looked, "changes").rows;
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
