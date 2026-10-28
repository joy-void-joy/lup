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
    return made(old, now, after, kept);
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

/** Return the changes that make lines `old` into lines `now`, `kept` kept, and what arrived, whose each new line is by `after`. */
function made(old: readonly string[], now: readonly string[], after: readonly string[], kept: readonly Pair[]): Reconciled {
    const before = old.join("\n");
    const oldStarts = startsOf(old);
    const newStarts = startsOf(now);
    const changes: ChangeSpec[] = [];
    const arrived: { from: number; to: number }[] = [];
    // The lines between two kept, by their own diff: what's the same in them kept too, whose ever they are.
    const gap = (fromOld: number, toOld: number, fromNew: number, toNew: number) => {
        const was = old.slice(fromOld, toOld);
        const is = now.slice(fromNew, toNew);
        for (const hunk of hunks(was, is)) {
            changed(shifted(hunk, fromOld, fromNew));
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
        changes.push(lineChange(before, old.length, oldStarts, hunk.from, hunk.to, now.slice(hunk.into, hunk.until)));
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

/** Marks the lines a layout put in or changed, which flash as they arrive, so what came while the operator reads is seen to come. */
export const arrivedLines = StateEffect.define<readonly { from: number; to: number }[]>();

/** Takes the marks of what arrived away, once their flash is over. */
const settled = StateEffect.define<null>();

/** How long a line that arrived is marked: its flash, and a little after. */
const FLASH = 1600;

const ARRIVED = Decoration.line({ class: "arrived" });

/** The lines that arrived and still flash, carried with the text; drawn apart from what's drawn of each layout, so drawing anew never flashes a line again. */
export const arriving = StateField.define<DecorationSet>({
    create: () => Decoration.none,
    update: (marks, transaction) => {
        let next = marks.map(transaction.changes);
        for (const effect of transaction.effects) {
            if (effect.is(settled)) {
                next = Decoration.none;
            } else if (effect.is(arrivedLines)) {
                const doc = transaction.state.doc;
                const starts = [...new Set(effect.value.map((each) => doc.lineAt(Math.min(each.from, doc.length)).from))].sort((a, b) => a - b);
                next = next.update({ add: starts.map((from) => ARRIVED.range(from)), sort: true });
            }
        }
        return next;
    },
    provide: (field) => EditorView.decorations.from(field),
});

/** Takes the marks of what arrived away once the last has flashed. */
export const settling = ViewPlugin.fromClass(
    class {
        timer: ReturnType<typeof setTimeout> | null = null;

        constructor(readonly view: EditorView) {}

        update(update: ViewUpdate) {
            if (!update.transactions.some((each) => each.effects.some((effect) => effect.is(arrivedLines)))) {
                return;
            }
            if (this.timer !== null) {
                clearTimeout(this.timer);
            }
            this.timer = setTimeout(() => {
                this.timer = null;
                this.view.dispatch({ effects: settled.of(null) });
            }, FLASH);
        }

        destroy() {
            if (this.timer !== null) {
                clearTimeout(this.timer);
            }
        }
    },
);
