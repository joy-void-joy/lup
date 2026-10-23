// What the "since you approved" drawer shows beyond each changed file's own
// lines (`docs/dashboard.md`, *The drawers*): the line a file standing as the
// operator last saw it is said in, marked reviewed with the version where they
// marked it so. Pure: the review lays the line out (`review.ts`).
import { cited } from "./comments";
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
