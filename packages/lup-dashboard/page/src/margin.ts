// The review's margin: a column for each depth the folds nest to, the item's
// outermost, leftmost (`depths`, `folds.ts`). Beside each fold's summary line,
// in its depth's column, the letter of its kind (`FOLD_KINDS`) in its kind's
// colour, outlined where the fold is folded, as its placeholder is; and for each
// fold the cursor is in, a thin bar in its kind's colour down the same column,
// from under its letter to its last line, as indent guides show a block's, so
// each bar begins with its letter and how the folds nest is seen at a glance. A
// CodeMirror gutter, whose rows are as tall as the lines beside them, wrapped
// or not. A folded fold's placeholder, at its summary line's end, is drawn in
// its kind's colour, saying how many lines a file, a body or an item hides
// (`editor.ts`; `docs/dashboard.md`, *The review*).
import { codeFolding, foldedRanges } from "@codemirror/language";
import type { EditorState, Extension } from "@codemirror/state";
import { GutterMarker, gutter, type BlockInfo, type ViewUpdate } from "@codemirror/view";

import type { Folding } from "./comments";
import { around, depths } from "./folds";
import { FOLD_KINDS, type FoldKind } from "./keys";

/** Where the margin reads what folds and when to draw again: the view's folds, and whether an update laid them out anew. */
export interface Margined {
    folds: (state: EditorState) => readonly Folding[];
    redrawn: (update: ViewUpdate) => boolean;
}

/** Return whether `state` holds `fold` folded. */
function folded(state: EditorState, fold: Folding): boolean {
    let found = false;
    foldedRanges(state).between(fold.from, fold.from, (from, to) => {
        found ||= from === fold.from && to === fold.to;
    });
    return found;
}

/** One bar beside a line: its fold's kind, how deep the fold is, its column, and whether the line is the fold's first or its last. */
interface Bar {
    kind: FoldKind;
    depth: number;
    first: boolean;
    last: boolean;
}

/** One fold's mark beside its summary line: its kind, how deep it is, its column, and whether it's folded. */
interface Mark {
    kind: FoldKind;
    depth: number;
    closed: boolean;
}

/** What the margin shows beside one line: the bars of the folds the cursor is in that hold it, and the marks of the folds it's the summary line of, each in its fold's column. */
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
        cell.className = "fold-cell";
        for (const bar of this.bars) {
            const drawn = document.createElement("span");
            drawn.className = ["fold-bar", `fold-${bar.kind}`, bar.first ? "is-first" : "", bar.last ? "is-last" : ""].join(" ");
            drawn.style.setProperty("--depth", `${bar.depth}`);
            cell.append(drawn);
        }
        for (const { kind, depth, closed } of this.marks) {
            const mark = document.createElement("span");
            mark.className = `fold-mark fold-${kind}${closed ? " is-folded" : ""}`;
            mark.style.setProperty("--depth", `${depth}`);
            mark.textContent = FOLD_KINDS.find((each) => each.kind === kind)?.letter ?? "";
            mark.title = `${closed ? "folded" : "open"}: ${kind}`;
            cell.append(mark);
        }
        return cell;
    }
}

/** The folds the cursor was last found in, by the folds and where it was, kept while neither changes: every line in view asks. */
let chained: { folds: readonly Folding[]; head: number; chain: Folding[] } | null = null;

/** Each view's folds by where their summary line starts, and how deep each is, made once a laying out. */
const placed = new WeakMap<readonly Folding[], { starts: Map<number, Folding[]>; deep: Map<Folding, number> }>();

/** Return the margin beside `line`: the bars of the folds the cursor is in holding it, and the marks of the folds it's the summary line of. */
function besideLine(state: EditorState, folds: readonly Folding[], line: BlockInfo): Beside | null {
    const head = state.selection.main.head;
    if (chained === null || chained.folds !== folds || chained.head !== head) {
        chained = { folds, head, chain: around(folds, head).filter((each) => each.kind !== undefined) };
    }
    let found = placed.get(folds);
    if (found === undefined) {
        const kinded = folds.filter((each) => each.kind !== undefined);
        const starts = new Map<number, Folding[]>();
        for (const fold of kinded) {
            starts.set(fold.summary.from, [...(starts.get(fold.summary.from) ?? []), fold]);
        }
        found = { starts, deep: depths(kinded) };
        placed.set(folds, found);
    }
    const { starts, deep } = found;
    const bars = chained.chain.flatMap((fold): Bar[] => {
        if (fold.kind === undefined || line.to < fold.summary.from || line.from > fold.to) {
            return [];
        }
        return [{ kind: fold.kind, depth: deep.get(fold) ?? 0, first: line.from <= fold.summary.from, last: line.to >= fold.to }];
    });
    const marks = (starts.get(line.from) ?? []).flatMap((fold): Mark[] =>
        fold.kind === undefined ? [] : [{ kind: fold.kind, depth: deep.get(fold) ?? 0, closed: folded(state, fold) }],
    );
    return bars.length === 0 && marks.length === 0 ? null : new Beside(bars, marks);
}

/** Return the margin's gutter, and its folds' placeholders, for a view whose folds `margined` says. */
export function margin(margined: Margined): Extension[] {
    return [
        gutter({
            class: "fold-margin",
            lineMarker: (view, line) => besideLine(view.state, margined.folds(view.state), line),
            lineMarkerChange: (update) =>
                update.selectionSet ||
                update.docChanged ||
                foldedRanges(update.startState) !== foldedRanges(update.state) ||
                margined.redrawn(update),
            initialSpacer: () => new Beside([], []),
        }),
    ];
}

/** The fold kinds whose placeholder says how many lines they hide: the others' summary lines say what they hide. */
const COUNTED = new Set<FoldKind>(["group", "item", "file", "body", "tasks", "since", "conversation", "earlier", "call"]);

/**
 * Return CodeMirror's folding, each placeholder drawn by the kind of the fold it stands for, of those `margined` says:
 * `⋯`, and how many lines a file, a body or an item hides; a fold of no kind's as `…`.
 */
export function placeheld(margined: Margined): Extension {
    return codeFolding({
        preparePlaceholder: (state, range) => {
            const fold = margined.folds(state).find((each) => each.from === range.from && each.to === range.to);
            if (fold?.kind === undefined) {
                return "";
            }
            const hidden = state.doc.lineAt(range.to).number - state.doc.lineAt(range.from).number;
            return JSON.stringify({ kind: fold.kind, hidden });
        },
        placeholderDOM: (_, onclick, prepared: string) => {
            const shown = document.createElement("span");
            shown.className = "cm-foldPlaceholder";
            shown.title = "unfold";
            shown.onclick = onclick;
            if (prepared === "") {
                shown.textContent = "…";
                return shown;
            }
            const { kind, hidden } = JSON.parse(prepared) as { kind: FoldKind; hidden: number };
            shown.classList.add("fold-placeholder", `fold-${kind}`);
            shown.textContent = COUNTED.has(kind) ? `⋯ ${hidden} ${hidden === 1 ? "line" : "lines"}` : "⋯";
            return shown;
        },
    });
}
