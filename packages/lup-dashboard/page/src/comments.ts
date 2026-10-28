// What the review's laid-out text is made of: the lines the operator's comments
// may be on, the comments written under them, the passages they quote, and how a
// step of an item's context is said. Pure: the review lays its text out with
// these (`review.ts`, `exchange.ts`), and the editor (`editor.ts`) lets the
// comments be written.
import type { components } from "./generated/api";

export type Quote = components["schemas"]["Quote"];

/** A stretch of the text, from its start to its end. */
export interface Span {
    from: number;
    to: number;
}

/** One line of a text comments may be on, where it's shown, and where it starts in that text. */
export interface Line extends Span {
    own: number;
}

/** One comment, where its lines are shown: `comment` is its id in the draft. */
export interface Block extends Span {
    comment: string;
}

/** A passage of a text: what it says, and where it starts and ends in that text. */
export interface Offsets {
    text: string;
    start: number;
    end: number;
}

/**
 * What folds: it hides `from` to `to`, from the end of its summary line to the end of its last; `key` names it across
 * layouts. Folds nest, each whole inside another or beside it.
 */
export interface Folding extends Span {
    key: string;
    summary: Span;
    /** Whether it's folded until the operator opens it. */
    closed: boolean;
    /** What it holds, by its kind's name (`looks.ts`), which its mark, its bar and the header show; none in a view whose folds have no kinds. */
    kind?: string;
    /** What the header calls it. */
    label?: string;
    /** Whether it's a scope's, a group's, an item's, a drawer's or a file's, which the margin bars its full height and labels. */
    scope?: boolean;
    /** Whether what it holds is read from another view as it opens and isn't read yet: its placeholder counts no lines. */
    unread?: boolean;
}

/** One row of a thing said: its text, where its words start in it, and where they start in the words kept. */
export interface Spoken {
    text: string;
    words: number;
    own: number;
    /** Whether it's a blank line between paragraphs, which no comment is on. */
    blank: boolean;
}

/** Say a run of calls in a line, each tool once with how many times in a row: `· called Bash ×2, Read`. */
export function calls(tools: string[]): string {
    const runs: { tool: string; times: number }[] = [];
    for (const tool of tools) {
        const last = runs.at(-1);
        if (last?.tool === tool) {
            last.times += 1;
        } else {
            runs.push({ tool, times: 1 });
        }
    }
    return `· called ${runs.map(({ tool, times }) => (times === 1 ? tool : `${tool} ×${times}`)).join(", ")}`;
}

/** Name an inbox item as the operator reads it named, `@270`, as the host's `cited` does: nobody takes it for a GitHub issue or pull request's `#270`. */
export function cited(number: number): string {
    return `@${number}`;
}

/** Return the lines of `text` kept to show it: each without its trailing space; blank ones dropped, or, where `blanks`, kept one between paragraphs. */
export function kept(text: string, blanks: boolean): string[] {
    const lines = text.split("\n").map((line) => line.trimEnd());
    if (!blanks) {
        return lines.filter((line) => line.trim() !== "");
    }
    const shown: string[] = [];
    for (const line of lines) {
        const blank = line.trim() === "";
        if (!blank || (shown.length > 0 && shown.at(-1) !== "")) {
            shown.push(blank ? "" : line);
        }
    }
    return shown.at(-1) === "" ? shown.slice(0, -1) : shown;
}

/** Say one thing said after who said it: its first line after `who:`, the others set in under it, as `kept` keeps them. */
export function spoken(who: string | null, text: string, blanks: boolean): Spoken[] {
    const lines = kept(text, blanks);
    const label = who === null ? "" : `${who}:`;
    if (lines.length === 0) {
        return [{ text: label, words: label.length, own: 0, blank: true }];
    }
    const indent = who === null ? "" : " ".repeat(who.length + 2);
    let own = 0;
    return lines.map((line, at) => {
        const prefix = at === 0 && who !== null ? `${who}: ` : indent;
        const row = { text: line === "" ? "" : `${prefix}${line}`, words: prefix.length, own, blank: line === "" };
        own += line.length + 1;
        return row;
    });
}

/** Return the line of a text an offset is on, by where each of its lines starts, counting from 0. */
export function lineOf(starts: number[], offset: number): number {
    // The last line starting at or before `offset`, found by halving: the starts are in order.
    let low = 0;
    let high = starts.length;
    while (low < high) {
        const middle = (low + high) >> 1;
        if ((starts[middle] ?? 0) <= offset) {
            low = middle + 1;
        } else {
            high = middle;
        }
    }
    return Math.max(low - 1, 0);
}

/** Return where each line of `lines` starts in them joined. */
export function starts(lines: string[]): number[] {
    let at = 0;
    return lines.map((line) => {
        const start = at;
        at += line.length + 1;
        return start;
    });
}

/** Return the line, of those starting at `starts`, a comment's quote is shown under: the one its passage ends on; none for a comment on the whole. */
export function under(starts: number[], quote: Offsets | null | undefined): number | null {
    return quote == null ? null : lineOf(starts, Math.max(quote.end - 1, quote.start));
}

/** Return where in its text a passage's last character is, where the cursor goes back to once a comment on it ends, as reading carries on there; its start where it's empty. */
export function lastOf(quote: Offsets): number {
    return Math.max(quote.end - 1, quote.start);
}

/** Return the passage `from` to `to` selects, from its first line to its last, counted in the text `own` they're lines of; a start before the first line's words counts from them. */
export function passage(own: string, first: Line, last: Line, from: number, to: number): Offsets {
    const start = first.own + Math.max(from - first.from, 0);
    const end = last.own + Math.max(Math.min(to, last.to) - last.from, 0);
    return { text: own.slice(start, end), start, end };
}

/** Return where in the text an offset of the text `lines` show is shown; `none` where no line is. */
export function shownIn(lines: Line[], offset: number, none: number): number {
    const line = [...lines].reverse().find((each) => each.own <= offset) ?? lines[0];
    return line === undefined ? none : Math.min(line.from + (offset - line.own), line.to);
}

/** Return the comments that say something. */
export function saying<C extends { text: string }>(comments: C[]): C[] {
    return comments.filter((each) => each.text.trim() !== "");
}

/** One change of a text: what's from `from` to `to` replaced by `insert`. */
export interface Change {
    from: number;
    to: number;
    insert: string;
}

/** The most lines two texts may differ by for their changes to be found line by line; beyond it, all between their common start and end is one change. */
const MOST = 1000;

/** Lines `from` to `to` of one text, replaced by lines `into` to `until` of the other. */
export interface Hunk {
    from: number;
    to: number;
    into: number;
    until: number;
}

/**
 * Return the hunks that make lines `a` into lines `b`, as few lines changed as can be, in order (Myers' diff, after
 * their common first and last lines); where more than `MOST` lines differ, all between those is one hunk.
 */
export function hunks(a: string[], b: string[]): Hunk[] {
    let first = 0;
    while (first < a.length && first < b.length && a[first] === b[first]) {
        first += 1;
    }
    let last = 0;
    while (last < a.length - first && last < b.length - first && a[a.length - 1 - last] === b[b.length - 1 - last]) {
        last += 1;
    }
    if (first === a.length && first === b.length) {
        return [];
    }
    const whole = { from: 0, to: a.length - first - last, into: 0, until: b.length - first - last };
    // Lines only added, or only removed, between the common ones are one hunk, with nothing to search.
    const searched = whole.to === 0 || whole.until === 0 ? null : diff(a.slice(first, a.length - last), b.slice(first, b.length - last));
    const middle = searched ?? [whole];
    return middle.map((each) => ({
        from: each.from + first,
        to: each.to + first,
        into: each.into + first,
        until: each.until + first,
    }));
}

/** Return the change of `before`, of `count` lines starting at `starts` (and one past its end), that replaces its lines `from` to `to` with `lines`. */
export function lineChange(before: string, count: number, starts: readonly number[], from: number, to: number, lines: readonly string[]): Change {
    const start = starts[from] ?? before.length;
    const end = (starts[to] ?? before.length + 1) - 1;
    const insert = lines.join("\n");
    if (to > from && lines.length > 0) {
        return { from: start, to: end, insert };
    }
    if (to > from) {
        // Lines removed: with the line break after them, or, at the end, the one before them.
        if (to < count) {
            return { from: start, to: end + 1, insert: "" };
        }
        return { from: Math.max(start - 1, 0), to: before.length, insert: "" };
    }
    // Lines added: before line `from`, or after the last.
    if (from < count) {
        return { from: start, to: start, insert: `${insert}\n` };
    }
    return count === 0 ? { from: 0, to: 0, insert } : { from: before.length, to: before.length, insert: `\n${insert}` };
}

/** Return the hunks that make lines `a` into lines `b`, as few lines changed as can be; none where more than `MOST` differ. */
function diff(a: string[], b: string[]): Hunk[] | null {
    const n = a.length;
    const m = b.length;
    const most = Math.min(n + m, MOST);
    const offset = most + 1;
    const v = new Int32Array(2 * most + 3);
    const trace: Int32Array[] = [];
    let found = false;
    for (let d = 0; d <= most && !found; d += 1) {
        trace.push(v.slice());
        for (let k = -d; k <= d; k += 2) {
            const down = k === -d || (k !== d && (v[offset + k - 1] ?? 0) < (v[offset + k + 1] ?? 0));
            let x = down ? (v[offset + k + 1] ?? 0) : (v[offset + k - 1] ?? 0) + 1;
            let y = x - k;
            while (x < n && y < m && a[x] === b[y]) {
                x += 1;
                y += 1;
            }
            v[offset + k] = x;
            if (x >= n && y >= m) {
                found = true;
                break;
            }
        }
    }
    if (!found) {
        return null;
    }
    // Back from the end: each step a line both keep, one removed, or one added.
    const steps: ("same" | "removed" | "added")[] = [];
    let x = n;
    let y = m;
    for (let d = trace.length - 1; d >= 0; d -= 1) {
        const was = trace[d] ?? v;
        const k = x - y;
        const down = k === -d || (k !== d && (was[offset + k - 1] ?? 0) < (was[offset + k + 1] ?? 0));
        const fromK = down ? k + 1 : k - 1;
        const fromX = d === 0 ? 0 : (was[offset + fromK] ?? 0);
        const fromY = d === 0 ? 0 : fromX - fromK;
        while (x > fromX && y > fromY) {
            steps.push("same");
            x -= 1;
            y -= 1;
        }
        if (d > 0) {
            steps.push(x === fromX ? "added" : "removed");
        }
        x = fromX;
        y = fromY;
    }
    const made: Hunk[] = [];
    let i = 0;
    let j = 0;
    let open: Hunk | null = null;
    for (const step of steps.reverse()) {
        if (step === "same") {
            open = null;
            i += 1;
            j += 1;
            continue;
        }
        if (open === null) {
            open = { from: i, to: i, into: j, until: j };
            made.push(open);
        }
        if (step === "removed") {
            i += 1;
            open.to = i;
        } else {
            j += 1;
            open.until = j;
        }
    }
    return made;
}
