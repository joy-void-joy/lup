// The review kept in its editor as it's laid out anew (`docs/dashboard.md`, *The review*): each line of the text is a
// part's of the review's tree, the innermost laid out on it (`Laid.owners`), and the editor keeps whose each line of
// its buffer is, mapped through every change to it, the operator's typing in a comment among them (`owning`). A new
// layout is made from the buffer by the fewest changes that keep each part's lines its own: a line of the buffer
// stays only as a line of the same part's, an unchanged part's untouched and a changed one's changed in its own lines
// alone, by their own diff; a part gone is taken out, a new one put in where its tree puts it; and the lines of what
// the operator wrote are kept before anything else's. So CodeMirror carries the cursor, a selection, the folds, the
// view and every comment through a layout as it does through typing, and nothing of where the reader is, is worked out
// again. What a layout puts in or changes flashes as it arrives (`arriving`). Pure, but for the state fields its runs
// and its flashes are kept in.
import { StateEffect, StateField, type ChangeSpec, type Text } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from "@codemirror/view";

import { hunks, lineChange, type Hunk } from "./comments";

/** A run of a part's lines, by the part's id, from the start of its first line to the end of its last. */
export interface Run {
    owner: string;
    from: number;
    to: number;
}

/** Sets whose each line of the buffer is, as a layout lays it out, in the transaction that does. */
export const owned = StateEffect.define<Run[]>();

/** Whose each line of the buffer is: as the last layout laid it out, carried through every change since, a comment's run growing with what's typed in it. */
export const owning = StateField.define<Run[]>({
    create: () => [],
    update: (runs, transaction) => {
        for (const effect of transaction.effects) {
            if (effect.is(owned)) {
                return effect.value;
            }
        }
        if (!transaction.docChanged) {
            return runs;
        }
        const changes = transaction.changes;
        return runs.map((each) => {
            const from = changes.mapPos(each.from, -1);
            return { owner: each.owner, from, to: Math.max(changes.mapPos(each.to, 1), from) };
        });
    },
});

/** Return the runs of `text`'s lines, each of the part `owners` says is its, by its place: none for a line no part's, as the empty one after the last line break. */
export function runsOf(text: string, owners: readonly string[]): Run[] {
    const runs: Run[] = [];
    let at = 0;
    text.split("\n").forEach((line, index) => {
        const owner = owners[index] ?? "";
        const last = runs.at(-1);
        if (owner !== "") {
            if (last !== undefined && last.owner === owner && last.to === at - 1) {
                last.to = at + line.length;
            } else {
                runs.push({ owner, from: at, to: at + line.length });
            }
        }
        at += line.length + 1;
    });
    return runs;
}

/** Return whose each line of `doc` is, by `runs`, a later run's where two hold one, as a comment emptied and taken out; none's where no run holds it. */
export function ownersOf(doc: Text, runs: readonly Run[]): string[] {
    const owners: string[] = new Array<string>(doc.lines).fill("");
    for (const run of runs) {
        if (run.from > doc.length) {
            continue;
        }
        const first = doc.lineAt(run.from).number;
        const last = doc.lineAt(Math.min(run.to, doc.length)).number;
        for (let line = first; line <= last; line += 1) {
            owners[line - 1] = run.owner;
        }
    }
    return owners;
}

/** What a layout changes of the buffer: the changes, in the buffer's positions; and, in the new text's, each line put in or changed but the operator's own words, what arrived. */
export interface Reconciled {
    changes: ChangeSpec[];
    arrived: { from: number; to: number }[];
}

/** A line of the buffer kept as a line of the new text: their places, and how much keeping it weighs. */
interface Pair {
    old: number;
    now: number;
    weight: number;
}

/**
 * Return the changes that make `doc`, whose lines `before` says whose they are, into `text`, whose lines `after` says,
 * keeping as many of its lines as can be, a line only as one of the same part's, its weight its part's (`weight`): each
 * part's lines kept by their own diff (`hunks`), and of those, the most weighed that stay in order; the rest changed,
 * each run of them between lines kept by the fewest changes, a line replaced by one in its place by what differs within
 * it. Applied to `doc`, they make `text` exactly.
 */
export function reconcile(doc: Text, before: readonly string[], text: string, after: readonly string[], weight: (owner: string) => number): Reconciled {
    const old = doc.toString().split("\n");
    const now = text.split("\n");
    const owners = new Map<string, { old: number[]; now: number[] }>();
    const of = (owner: string) => {
        const found = owners.get(owner) ?? { old: [], now: [] };
        owners.set(owner, found);
        return found;
    };
    old.forEach((_, at) => of(before[at] ?? "").old.push(at));
    now.forEach((_, at) => of(after[at] ?? "").now.push(at));
    const pairs: Pair[] = [];
    for (const [owner, lines] of owners) {
        if (lines.old.length === 0 || lines.now.length === 0) {
            continue;
        }
        const was = lines.old.map((at) => old[at] ?? "");
        const is = lines.now.map((at) => now[at] ?? "");
        const weighs = weight(owner);
        const pair = (a: number, b: number) => {
            const i = lines.old[a];
            const j = lines.now[b];
            if (i !== undefined && j !== undefined) {
                pairs.push({ old: i, now: j, weight: weighs });
            }
        };
        let a = 0;
        let b = 0;
        for (const hunk of hunks(was, is)) {
            for (; a < hunk.from; a += 1, b += 1) {
                pair(a, b);
            }
            a = hunk.to;
            b = hunk.until;
        }
        for (; a < was.length; a += 1, b += 1) {
            pair(a, b);
        }
    }
    const kept = heaviest(pairs.sort((x, y) => x.old - y.old), now.length);
    return made(old, now, before, after, kept);
}

/** Return the most weighed of `pairs`, in their old order, that stay in order in the new one too, of `count` lines: by a tree of the best found up to each new line. */
function heaviest(pairs: readonly Pair[], count: number): Pair[] {
    const best = new Float64Array(count + 1);
    const at = new Int32Array(count + 1).fill(-1);
    const total = new Float64Array(pairs.length);
    const previous = new Int32Array(pairs.length).fill(-1);
    // The best up to new line `line`, exclusive, and which pair ends it.
    const upTo = (line: number): { weight: number; pair: number } => {
        let weight = 0;
        let pair = -1;
        for (let index = line; index > 0; index -= index & -index) {
            if ((best[index] ?? 0) > weight) {
                weight = best[index] ?? 0;
                pair = at[index] ?? -1;
            }
        }
        return { weight, pair };
    };
    const raise = (line: number, weight: number, pair: number) => {
        for (let index = line + 1; index <= count; index += index & -index) {
            if ((best[index] ?? 0) < weight) {
                best[index] = weight;
                at[index] = pair;
            }
        }
    };
    let top = -1;
    pairs.forEach((each, index) => {
        const found = upTo(each.now);
        total[index] = found.weight + each.weight;
        previous[index] = found.pair;
        raise(each.now, total[index] ?? 0, index);
        if (top < 0 || (total[index] ?? 0) > (total[top] ?? 0)) {
            top = index;
        }
    });
    const kept: Pair[] = [];
    for (let index = top; index >= 0; index = previous[index] ?? -1) {
        const each = pairs[index];
        if (each !== undefined) {
            kept.push(each);
        }
    }
    return kept.reverse();
}

/** Return where each of `lines` starts in them joined, and one past the end of the last. */
function startsOf(lines: readonly string[]): number[] {
    const starts: number[] = [];
    let at = 0;
    for (const line of lines) {
        starts.push(at);
        at += line.length + 1;
    }
    starts.push(at);
    return starts;
}

/** A run of lines of one part's, by their places, from `from` up to `to`. */
interface Owned {
    owner: string;
    from: number;
    to: number;
}

/** Return the runs of lines `from` up to `to`, each of one part's by `owners`. */
function ownedIn(owners: readonly string[], from: number, to: number): Owned[] {
    const runs: Owned[] = [];
    for (let line = from; line < to; line += 1) {
        const owner = owners[line] ?? "";
        const last = runs.at(-1);
        if (last !== undefined && last.owner === owner) {
            last.to = line + 1;
        } else {
            runs.push({ owner, from: line, to: line + 1 });
        }
    }
    return runs;
}

/** The most pairs of runs two stretches are matched over, past which they're changed as one, as a stretch of a review laid out anew whole. */
const MOST_RUNS = 250_000;

/** Return which of runs `a` are the same part's as which of runs `b`, the most of them in order (their longest common sequence by owner); none past `MOST_RUNS`. */
function matchedRuns(a: readonly Owned[], b: readonly Owned[]): [number, number][] {
    if (a.length * b.length > MOST_RUNS || a.length === 0 || b.length === 0) {
        return [];
    }
    const width = b.length + 1;
    const table = new Int32Array((a.length + 1) * width);
    for (let i = a.length - 1; i >= 0; i -= 1) {
        for (let j = b.length - 1; j >= 0; j -= 1) {
            table[i * width + j] =
                a[i]?.owner === b[j]?.owner ? (table[(i + 1) * width + j + 1] ?? 0) + 1 : Math.max(table[(i + 1) * width + j] ?? 0, table[i * width + j + 1] ?? 0);
        }
    }
    const pairs: [number, number][] = [];
    let i = 0;
    let j = 0;
    while (i < a.length && j < b.length) {
        if (a[i]?.owner === b[j]?.owner) {
            pairs.push([i, j]);
            i += 1;
            j += 1;
        } else if ((table[(i + 1) * width + j] ?? 0) >= (table[i * width + j + 1] ?? 0)) {
            i += 1;
        } else {
            j += 1;
        }
    }
    return pairs;
}

/**
 * Return the changes that make lines `old` into lines `now`, `kept` kept, and what arrived, whose each line is by
 * `before` and `after`: between two lines kept, each part's lines there that both have are changed apart, by their own
 * diff, and the rest, a part's that went or came, replaced together, so a change of one part's lines never takes in
 * another's, nor a cursor in one lands in another.
 */
function made(old: readonly string[], now: readonly string[], before: readonly string[], after: readonly string[], kept: readonly Pair[]): Reconciled {
    const text = old.join("\n");
    const oldStarts = startsOf(old);
    const newStarts = startsOf(now);
    const changes: ChangeSpec[] = [];
    const arrived: { from: number; to: number }[] = [];
    const gap = (fromOld: number, toOld: number, fromNew: number, toNew: number) => {
        const was = ownedIn(before, fromOld, toOld);
        const is = ownedIn(after, fromNew, toNew);
        let o = fromOld;
        let n = fromNew;
        for (const [i, j] of matchedRuns(was, is)) {
            const a = was[i];
            const b = is[j];
            if (a === undefined || b === undefined) {
                continue;
            }
            stretch(o, a.from, n, b.from);
            for (const hunk of hunks(old.slice(a.from, a.to), now.slice(b.from, b.to))) {
                changed(shifted(hunk, a.from, b.from));
            }
            o = a.to;
            n = b.to;
        }
        stretch(o, toOld, n, toNew);
    };
    // Lines no part has on both sides, replaced together: by their own diff, so what's the same in them is kept.
    const stretch = (fromOld: number, toOld: number, fromNew: number, toNew: number) => {
        if (toOld > fromOld || toNew > fromNew) {
            for (const hunk of hunks(old.slice(fromOld, toOld), now.slice(fromNew, toNew))) {
                changed(shifted(hunk, fromOld, fromNew));
            }
        }
    };
    const changed = (hunk: Hunk) => {
        const taken = hunk.to - hunk.from;
        const put = hunk.until - hunk.into;
        for (let line = hunk.into; line < hunk.until; line += 1) {
            if (!(after[line] ?? "").startsWith("written ")) {
                arrived.push({ from: newStarts[line] ?? 0, to: (newStarts[line] ?? 0) + (now[line] ?? "").length });
            }
        }
        if (taken === put) {
            // Each line by what differs within it, so the cursor on one keeps its place there.
            for (let at = 0; at < taken; at += 1) {
                const was = old[hunk.from + at] ?? "";
                const is = now[hunk.into + at] ?? "";
                let start = 0;
                while (start < was.length && start < is.length && was[start] === is[start]) {
                    start += 1;
                }
                let end = 0;
                while (end < was.length - start && end < is.length - start && was[was.length - 1 - end] === is[is.length - 1 - end]) {
                    end += 1;
                }
                const from = (oldStarts[hunk.from + at] ?? 0) + start;
                changes.push({ from, to: from + was.length - start - end, insert: is.slice(start, is.length - end) });
            }
            return;
        }
        changes.push(lineChange(text, old.length, oldStarts, hunk.from, hunk.to, now.slice(hunk.into, hunk.until)));
    };
    let lastOld = -1;
    let lastNew = -1;
    for (const each of [...kept, { old: old.length, now: now.length, weight: 0 }]) {
        if (each.old > lastOld + 1 || each.now > lastNew + 1) {
            gap(lastOld + 1, each.old, lastNew + 1, each.now);
        }
        lastOld = each.old;
        lastNew = each.now;
    }
    return { changes, arrived };
}

/** Return `hunk` of lines from `old` and `now` on, as lines of the whole texts. */
function shifted(hunk: Hunk, old: number, now: number): Hunk {
    return { from: hunk.from + old, to: hunk.to + old, into: hunk.into + now, until: hunk.until + now };
}

/** How long the review goes laid out anew no more than this apart, as it's first read, before it's read: what's read after flashes as it arrives. */
const READ_QUIET = 1000;

/** How long after the review is first laid out from what it's laid out from it's read, however often it's laid out anew. */
const READ_AT_MOST = 5000;

/** How the review is being first read: when it was first laid out from all it's laid out from, when it was laid out last, and whether it's read. */
export interface Reading {
    since: number | null;
    last: number;
    read: boolean;
}

/**
 * Return whether what a layout at `now` puts in flashes, `reading` taking it in: once the review has been read. As the
 * page loads, the review is laid out empty, then again as each thing it reads answers, the items' contexts and files,
 * the agents' records and drawers, their views, in the first second or so; none of that is what came while the
 * operator reads, which is what flashes. So the review is read once it has gone `READ_QUIET` with no layout since it
 * was first laid out from what it's laid out from (`all`, the inbox, the agents running, the draft and the order),
 * or `READ_AT_MOST` after, as under the hooks of agents at work.
 */
export function readBy(reading: Reading, all: boolean, now: number): boolean {
    if (!reading.read && all) {
        if (reading.since === null) {
            reading.since = now;
        } else if (now - reading.last >= READ_QUIET || now - reading.since >= READ_AT_MOST) {
            reading.read = true;
        }
        reading.last = now;
    }
    return reading.read;
}

/** What a layout put in or changed, but the operator's own words, and when it arrived: each line flashes once, from then. */
export interface Arrival {
    lines: readonly { from: number; to: number }[];
    /** When it arrived, in the milliseconds `Date.now` counts. */
    at: number;
}

/** Marks the lines a layout put in or changed, which flash as they arrive, so what came while the operator reads is seen to come. */
export const arrivedLines = StateEffect.define<Arrival>();

/** Takes away the marks of what arrived up to a time, in the milliseconds `Date.now` counts: their flash is over. */
export const settled = StateEffect.define<number>();

/** How long a line that arrived is marked: its flash, and a little after. */
export const FLASH = 1600;

/** A line's mark that it arrived, and when: drawn alike whenever it came (`LineDecoration.eq` reads its class alone), so a mark kept never draws its line anew. */
function arrivedAt(at: number): Decoration {
    return Decoration.line({ class: "arrived", at });
}

/** When a mark of `arriving` was made. */
function markedAt(mark: Decoration): number {
    return (mark.spec as { at: number }).at;
}

/**
 * The lines that arrived and still flash, carried with the text; drawn apart from what's drawn of each layout, so
 * drawing anew never flashes a line again. Each is marked once, as it first arrives, and only for its own flash: a
 * line that arrives again while it flashes keeps its mark, and what arrives later never keeps an earlier mark, so
 * what's marked is what came in the last moments, never the review whole, and a line CodeMirror draws anew, as it
 * scrolls into view, flashes only while what came on it is new (#341).
 */
export const arriving = StateField.define<DecorationSet>({
    create: () => Decoration.none,
    update: (marks, transaction) => {
        let next = marks.map(transaction.changes);
        for (const effect of transaction.effects) {
            if (effect.is(settled)) {
                const until = effect.value;
                next = next.update({ filter: (_from, _to, mark) => markedAt(mark) > until });
            } else if (effect.is(arrivedLines) && effect.value.lines.length > 0) {
                const doc = transaction.state.doc;
                const marked = new Set<number>();
                next.between(0, doc.length, (from) => {
                    marked.add(from);
                });
                const starts = [...new Set(effect.value.lines.map((each) => doc.lineAt(Math.min(each.from, doc.length)).from))]
                    .filter((from) => !marked.has(from))
                    .sort((a, b) => a - b);
                const mark = arrivedAt(effect.value.at);
                next = next.update({ add: starts.map((from) => mark.range(from)), sort: true });
            }
        }
        return next;
    },
    provide: (field) => EditorView.decorations.from(field),
});

/** Takes the marks of what arrived away as each one's flash ends: the earliest first, then the next. */
export const settling = ViewPlugin.fromClass(
    class {
        timer: ReturnType<typeof setTimeout> | null = null;

        constructor(readonly view: EditorView) {}

        update(update: ViewUpdate) {
            if (this.timer === null && update.transactions.some((each) => each.effects.some((effect) => effect.is(arrivedLines) && effect.value.lines.length > 0))) {
                this.settleNext();
            }
        }

        /** Wait for the earliest mark's flash to end, then take away every mark whose flash has, and wait for the next. */
        settleNext() {
            let first = Infinity;
            this.view.state.field(arriving).between(0, this.view.state.doc.length, (_from, _to, mark) => {
                first = Math.min(first, markedAt(mark));
            });
            if (first === Infinity) {
                return;
            }
            this.timer = setTimeout(
                () => {
                    this.timer = null;
                    this.view.dispatch({ effects: settled.of(Date.now() - FLASH) });
                    this.settleNext();
                },
                Math.max(0, first + FLASH - Date.now()),
            );
        }

        destroy() {
            if (this.timer !== null) {
                clearTimeout(this.timer);
            }
        }
    },
);
