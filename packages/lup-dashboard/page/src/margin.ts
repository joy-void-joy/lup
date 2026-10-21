// The review's margin: beside each fold's summary line its mark, ▸ where it's
// folded and ▾ where it's open, then the letter of its kind (`FOLD_KINDS`), in
// its kind's colour; and for each fold the cursor is in, outermost leftmost, a
// thin bar in its kind's colour from its summary line to its last, as indent
// guides show a block's, so how the folds nest is seen at a glance. A
// CodeMirror gutter, whose rows are as tall as the lines beside them, wrapped
// or not. A folded fold's placeholder, at its summary line's end, is drawn in
// its kind's colour, saying how many lines a file, a body or an item hides
// (`editor.ts`; `docs/dashboard.md`, *The review*).
import { codeFolding, foldedRanges } from "@codemirror/language";
import type { EditorState, Extension } from "@codemirror/state";
import { GutterMarker, gutter, type BlockInfo, type ViewUpdate } from "@codemirror/view";

import type { Folding } from "./comments";
import { around } from "./folds";
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

/** One bar beside a line: its fold's kind, how deep the fold is, and whether the line is the fold's first or its last. */
interface Bar {
    kind: FoldKind;
    depth: number;
    first: boolean;
    last: boolean;
}

/** What the margin shows beside one line: the bars of the folds the cursor is in that hold it, and the mark of the fold it's the summary line of. */
class Beside extends GutterMarker {
    constructor(
        readonly bars: Bar[],
        readonly mark: { kind: FoldKind; closed: boolean } | null,
    ) {
        super();
    }

    override eq(other: Beside): boolean {
        return JSON.stringify([this.bars, this.mark]) === JSON.stringify([other.bars, other.mark]);
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
        if (this.mark !== null) {
            const { kind, closed } = this.mark;
            const mark = document.createElement("span");
            mark.className = `fold-mark fold-${kind}`;
            mark.textContent = `${closed ? "▸" : "▾"}${FOLD_KINDS.find((each) => each.kind === kind)?.letter ?? ""}`;
            mark.title = `${closed ? "folded" : "open"}: ${kind}`;
            cell.append(mark);
        }
        return cell;
    }
}

/** The folds the cursor was last found in, by the folds and where it was, kept while neither changes: every line in view asks. */
let chained: { folds: readonly Folding[]; head: number; chain: Folding[] } | null = null;

/** Each view's folds by where their summary line starts, made once a laying out. */
const starting = new WeakMap<readonly Folding[], Map<number, Folding>>();

/** Return the margin beside `line`: the bars of the folds the cursor is in holding it, and the mark of the fold it's the summary line of. */
function besideLine(state: EditorState, folds: readonly Folding[], line: BlockInfo): Beside | null {
    const head = state.selection.main.head;
    if (chained === null || chained.folds !== folds || chained.head !== head) {
        chained = { folds, head, chain: around(folds, head).filter((each) => each.kind !== undefined) };
    }
    const bars = chained.chain.flatMap((fold, depth): Bar[] => {
        if (fold.kind === undefined || line.to < fold.summary.from || line.from > fold.to) {
            return [];
        }
        return [{ kind: fold.kind, depth, first: line.from <= fold.summary.from, last: line.to >= fold.to }];
    });
    let starts = starting.get(folds);
    if (starts === undefined) {
        starts = new Map(folds.map((each) => [each.summary.from, each]));
        starting.set(folds, starts);
    }
    const summary = starts.get(line.from);
    const mark = summary?.kind === undefined ? null : { kind: summary.kind, closed: folded(state, summary) };
    return bars.length === 0 && mark === null ? null : new Beside(bars, mark);
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
            initialSpacer: () => new Beside([], null),
        }),
    ];
}

/** The fold kinds whose placeholder says how many lines they hide: the others' summary lines say what they hide. */
const COUNTED = new Set<FoldKind>(["item", "file", "body"]);

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
