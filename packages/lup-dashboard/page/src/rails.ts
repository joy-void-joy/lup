// The review's margin: its structure, one column for each depth folds nest to,
// line for line with the text (`docs/dashboard.md`, *The review*). Each scope
// the review is made of, an agent's group (a subagent's beside its parent's),
// an item, a drawer, a file, is a bar its full height in its kind's colour,
// starting with its fold's letter, outlined where it's folded, then a short
// label: the agent's name, `@55`, `since`, `records.py`, marked by how it stands
// and what the draft does with it; the bars of the scopes the cursor is in
// bright, the others dim. Each fold that isn't a scope, a body, a run of
// unchanged lines, an item's context, an exchange, a call, has its letter in
// its column, and a bar down it while the cursor's in it. A click on a label
// goes there, on a letter opens or closes its fold. A CodeMirror gutter, whose
// rows are as tall as the lines beside them, so the outline's heights are the
// text's by construction.
import { foldedRanges } from "@codemirror/language";
import { StateEffect, type EditorState, type Extension } from "@codemirror/state";
import { GutterMarker, gutter, type BlockInfo } from "@codemirror/view";

import type { Folding } from "./comments";
import { around, depths } from "./folds";
import { FOLD_KINDS, type FoldKind } from "./keys";
import { measured } from "./timing";

/** The kinds of fold that are the review's scopes, a bar their full height in the margin, labelled: an agent's group, an item, a drawer, a file. */
export const SCOPES: ReadonlySet<FoldKind> = new Set<FoldKind>(["group", "item", "tasks", "since", "conversation", "file"]);

/** One scope's label in the margin: what it says, how it stands before it, and after it whether it's new and what the draft does with it. */
export interface Labelled {
    text: string;
    /** How it stands, a glyph in its own colour: waiting on the operator, news, parked, a file to review or flagged, an agent calling. */
    state: { glyph: string; mark: string } | null;
    /** What the draft does with it on the next Ctrl+Enter, glyphs in the draft's colour. */
    draft: string | null;
    /** Whether it's new to the operator since they last sent. */
    fresh: boolean;
}

/** What the margin reads, as the review last laid out: its folds, each scope's label, and what a click does. */
export interface Structured {
    folds: readonly Folding[];
    label: (fold: Folding) => Labelled | null;
    jump: (position: number) => void;
    toggle: (fold: Folding) => void;
}

/** Marks a transaction after which the margin is drawn again, what its labels say having changed with nothing laid out anew. */
export const redrawn = StateEffect.define<null>();

/** One fold beside a line: its column, its kind, whether it's a scope's, bright, and whether the line is its first or its last. */
interface Bar {
    depth: number;
    kind: FoldKind;
    scope: boolean;
    bright: boolean;
    first: boolean;
    last: boolean;
}

/** One fold's letter on its summary line, outlined where it's folded, with its label where it's a scope's. */
interface Mark {
    depth: number;
    kind: FoldKind;
    closed: boolean;
    at: number;
    label: Labelled | null;
    key: string;
}

class Beside extends GutterMarker {
    constructor(
        readonly bars: Bar[],
        readonly marks: Mark[],
    ) {
        super();
    }

    override eq(other: Beside): boolean {
        return JSON.stringify([this.bars, this.marks]) === JSON.stringify([other.bars, other.marks]);
    }

    override toDOM(): Node {
        const cell = document.createElement("span");
        cell.className = "rail-cell";
        for (const bar of this.bars) {
            const drawn = document.createElement("span");
            drawn.className = ["rail", `fold-${bar.kind}`, bar.scope ? "is-scope" : "", bar.bright ? "is-bright" : "", bar.first ? "is-first" : "", bar.last ? "is-last" : ""].join(" ");
            drawn.style.setProperty("--depth", `${bar.depth}`);
            cell.append(drawn);
        }
        for (const mark of this.marks) {
            const letter = document.createElement("span");
            letter.className = `fold-mark fold-${mark.kind}${mark.closed ? " is-folded" : ""}`;
            letter.style.setProperty("--depth", `${mark.depth}`);
            letter.textContent = FOLD_KINDS.find((each) => each.kind === mark.kind)?.letter ?? "";
            letter.title = `${mark.closed ? "folded" : "open"}: ${mark.kind} (a click ${mark.closed ? "opens" : "closes"} it)`;
            letter.dataset["fold"] = mark.key;
            cell.append(letter);
            if (mark.label !== null) {
                const label = document.createElement("span");
                label.className = `rail-label fold-${mark.kind}`;
                label.style.setProperty("--depth", `${mark.depth}`);
                label.dataset["at"] = `${mark.at}`;
                if (mark.label.state !== null) {
                    const state = document.createElement("span");
                    state.className = `rail-state mark-${mark.label.state.mark}`;
                    state.textContent = mark.label.state.glyph;
                    label.append(state);
                }
                label.append(mark.label.text);
                if (mark.label.fresh) {
                    const fresh = document.createElement("span");
                    fresh.className = "rail-fresh";
                    fresh.textContent = " new";
                    label.append(fresh);
                }
                if (mark.label.draft !== null) {
                    const draft = document.createElement("span");
                    draft.className = "rail-draft";
                    draft.textContent = ` ${mark.label.draft}`;
                    label.append(draft);
                }
                label.title = `${mark.label.text}: a click goes there`;
                cell.append(label);
            }
        }
        return cell;
    }
}

/** A scope's fold nested in the others, for finding those holding a line by halving at each depth. */
interface Nested {
    fold: Folding;
    children: Nested[];
}

/** What's worked out of a laying out's folds once: how deep each is, the folds by where their summary line starts, and the scopes nested. */
interface Placed {
    deep: Map<Folding, number>;
    starts: Map<number, Folding[]>;
    scopes: Nested[];
    byKey: Map<string, Folding>;
}

const placedOnce = new WeakMap<readonly Folding[], Placed>();

function placedOf(folds: readonly Folding[]): Placed {
    const found = placedOnce.get(folds);
    if (found !== undefined) {
        return found;
    }
    const kinded = folds.filter((each) => each.kind !== undefined);
    const starts = new Map<number, Folding[]>();
    for (const fold of kinded) {
        starts.set(fold.summary.from, [...(starts.get(fold.summary.from) ?? []), fold]);
    }
    // The scopes, each inside the one before it that holds it, from its summary line to its last.
    const roots: Nested[] = [];
    const holding: Nested[] = [];
    const scopes = kinded.filter((each) => each.kind !== undefined && SCOPES.has(each.kind)).sort((a, b) => a.summary.from - b.summary.from || b.to - a.to);
    for (const fold of scopes) {
        while (holding.length > 0 && (holding.at(-1)?.fold.to ?? 0) < fold.summary.from) {
            holding.pop();
        }
        const made: Nested = { fold, children: [] };
        (holding.at(-1)?.children ?? roots).push(made);
        holding.push(made);
    }
    const placed = { deep: depths(kinded), starts, scopes: roots, byKey: new Map(kinded.map((each) => [each.key, each])) };
    placedOnce.set(folds, placed);
    return placed;
}

/** Return the scope of `level`, in the text's order, holding `position`, from its summary line to its last; none where it's between them. */
function holdingOf(level: readonly Nested[], position: number): Nested | undefined {
    let low = 0;
    let high = level.length;
    while (low < high) {
        const middle = (low + high) >> 1;
        if ((level[middle]?.fold.summary.from ?? 0) <= position) {
            low = middle + 1;
        } else {
            high = middle;
        }
    }
    const found = level[low - 1];
    return found !== undefined && position <= found.fold.to ? found : undefined;
}

/** Return whether `state` holds `fold` folded. */
function folded(state: EditorState, fold: Folding): boolean {
    let found = false;
    foldedRanges(state).between(fold.from, fold.from, (from, to) => {
        found ||= from === fold.from && to === fold.to;
    });
    return found;
}

/** The folds the cursor was last found in, kept while neither they nor where it is change: every line in view asks. */
let chained: { folds: readonly Folding[]; head: number; chain: Set<Folding> } | null = null;

/** Return what the margin shows beside `line`: the bar of each scope holding it, and of each other fold the cursor is in that does; each fold's letter on its summary line, a scope's labelled where there's room. */
function besideLine(state: EditorState, structured: Structured, line: BlockInfo, labels: boolean): Beside | null {
    const { folds } = structured;
    const head = state.selection.main.head;
    if (chained === null || chained.folds !== folds || chained.head !== head) {
        chained = { folds, head, chain: new Set(around(folds.filter((each) => each.kind !== undefined), head)) };
    }
    const { deep, starts, scopes } = placedOf(folds);
    const bars: Bar[] = [];
    // Each scope holding the line, its full height.
    let level = scopes;
    for (;;) {
        const inside = holdingOf(level, line.from);
        if (inside === undefined) {
            break;
        }
        const fold = inside.fold;
        bars.push({
            depth: deep.get(fold) ?? 0,
            kind: fold.kind ?? "item",
            scope: true,
            bright: chained.chain.has(fold),
            first: line.from <= fold.summary.from,
            last: line.to >= fold.to,
        });
        level = inside.children;
    }
    // Each other fold the cursor is in, down its lines.
    for (const fold of chained.chain) {
        if (fold.kind === undefined || SCOPES.has(fold.kind) || line.to < fold.summary.from || line.from > fold.to) {
            continue;
        }
        bars.push({ depth: deep.get(fold) ?? 0, kind: fold.kind, scope: false, bright: true, first: line.from <= fold.summary.from, last: line.to >= fold.to });
    }
    const marks = (starts.get(line.from) ?? []).flatMap((fold): Mark[] =>
        fold.kind === undefined
            ? []
            : [
                  {
                      depth: deep.get(fold) ?? 0,
                      kind: fold.kind,
                      closed: folded(state, fold),
                      at: fold.summary.from,
                      label: labels && SCOPES.has(fold.kind) ? structured.label(fold) : null,
                      key: fold.key,
                  },
              ],
    );
    return bars.length === 0 && marks.length === 0 ? null : new Beside(bars, marks);
}

/**
 * Return the margin, read from `structured` as it stands when each line is drawn; `labels` where there's room for
 * them, as there isn't on a phone, whose margin is the bars and the letters alone.
 */
export function structureMargin(structured: () => Structured, labels: boolean): Extension {
    return gutter({
        class: labels ? "fold-margin structure-margin" : "fold-margin structure-margin is-bare",
        lineMarker: (view, line) => {
            const began = performance.now();
            const beside = besideLine(view.state, structured(), line, labels);
            measured("lup-margin", began);
            return beside;
        },
        lineMarkerChange: (update) =>
            update.selectionSet ||
            update.docChanged ||
            foldedRanges(update.startState) !== foldedRanges(update.state) ||
            update.transactions.some((each) => each.effects.some((effect) => effect.is(redrawn))),
        initialSpacer: () => new Beside([], []),
        domEventHandlers: {
            mousedown: (_, __, event) => {
                const target = event.target instanceof HTMLElement ? event.target : null;
                const at = target?.closest<HTMLElement>("[data-at]")?.dataset["at"];
                const key = target?.closest<HTMLElement>("[data-fold]")?.dataset["fold"];
                if (at !== undefined) {
                    event.preventDefault();
                    structured().jump(Number(at));
                    return true;
                }
                const fold = key === undefined ? undefined : placedOf(structured().folds).byKey.get(key);
                if (fold !== undefined) {
                    event.preventDefault();
                    structured().toggle(fold);
                    return true;
                }
                return false;
            },
        },
    });
}
