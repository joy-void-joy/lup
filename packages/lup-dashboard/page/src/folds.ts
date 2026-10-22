// What the fold keys reach among a view's folds, whatever the view: the folds
// the cursor is in, outermost first, which the review's margin bars and header
// show; within one item, the folds `zr` and `zm` open or close a level at a
// time, and those Space `z` and a letter open or close by kind; and where `zj`,
// `zk`, `[z` and `]z` go. Folds nest, each whole inside another or beside it
// (`review.ts`, `code.ts`). Pure: the editor folds what these return
// (`editor.ts`; `docs/dashboard.md`, *The keys*).
import type { Folding } from "./comments";
import { FOLD_KINDS, type FoldKind } from "./keys";

/** What these read of a fold: where its summary line is, what it hides, and its kind. */
type Folded = Pick<Folding, "summary" | "from" | "to" | "kind">;

/** Return the folds `at` is in, from a summary line to a last line, outermost first. */
export function around<F extends Pick<Folding, "summary" | "to">>(folds: readonly F[], at: number): F[] {
    return folds.filter((each) => at >= each.summary.from && at <= each.to).sort((a, b) => a.summary.from - b.summary.from);
}

/**
 * Return how deep each of `folds` is: how many of the others hold it, from a summary line to a last line, the outermost
 * none. Folds nest, each whole inside another or beside it, so a fold the cursor is in is as deep as its place among
 * those `around` it, and the review's margin draws each in the column of its depth (`margin.ts`).
 */
export function depths<F extends Pick<Folding, "summary" | "to">>(folds: readonly F[]): Map<F, number> {
    const ordered = [...folds].sort((a, b) => a.summary.from - b.summary.from || b.to - a.to);
    // The folds holding the one reached so far, outermost first.
    const holding: F[] = [];
    const found = new Map<F, number>();
    for (const fold of ordered) {
        while (holding.length > 0 && (holding.at(-1)?.to ?? 0) < fold.summary.from) {
            holding.pop();
        }
        found.set(fold, holding.length);
        holding.push(fold);
    }
    return found;
}

/** Return the level `zr` and `zm` open and close `fold` at, by its kind (`FOLD_KINDS`); a fold of no kind is at none. */
export function levelOf(fold: Folded): number | undefined {
    return FOLD_KINDS.find((each) => each.kind === fold.kind)?.level;
}

/** Return whether `fold` is the one holding the rest of its item or drawer: the item's own, or a drawer's (`FoldKindKeys.own`). */
export function isOwn(fold: Folded): boolean {
    return FOLD_KINDS.find((each) => each.kind === fold.kind)?.own === true;
}

/**
 * Return the folds of one item or drawer, `folds`, that `zr` opens (`opening`) or `zm` closes, `closed` saying which
 * are folded: `zr` those folded at the first level any is folded at, the item's own or the drawer's first; `zm` those
 * open at the last level any is open at, never the own one, which `za` on its header folds. With `all`, as `zR` and
 * `zM`, every one of them: each folded one, or each open one but the own one.
 */
export function levelled<F extends Folded>(folds: readonly F[], closed: (fold: F) => boolean, opening: boolean, all: boolean): F[] {
    const reached = opening ? folds.filter(closed) : folds.filter((each) => !closed(each) && !isOwn(each));
    if (all) {
        return reached;
    }
    const levels = reached.flatMap((each) => levelOf(each) ?? []);
    const level = opening ? Math.min(...levels) : Math.max(...levels);
    return reached.filter((each) => levelOf(each) === level);
}

/**
 * Return the folds of one item or drawer, `folds`, that Space `z` and a letter opens, `closed` saying which are folded:
 * each of `kind` folded, and the own one where it's folded, so what opens is seen; or, `closing`, as Shift and the
 * letter, each of `kind` open.
 */
export function ofKind<F extends Folded>(folds: readonly F[], closed: (fold: F) => boolean, kind: FoldKind, closing: boolean): F[] {
    if (closing) {
        return folds.filter((each) => each.kind === kind && !closed(each));
    }
    return folds.filter((each) => (each.kind === kind || isOwn(each)) && closed(each));
}

/** Return whether `fold` is hidden in another one folded, its summary line among the lines that one hides. */
function hidden<F extends Folded>(folds: readonly F[], closed: (fold: F) => boolean, fold: F): boolean {
    return folds.some((each) => each !== fold && closed(each) && fold.summary.from > each.from && fold.summary.from <= each.to);
}

/** Return where the line starting at `line` is seen: there, or, where a folded fold hides it, that fold's summary line, the outermost's. */
function seenAt<F extends Folded>(folds: readonly F[], closed: (fold: F) => boolean, line: number): number {
    return folds.filter((each) => closed(each) && line > each.from && line <= each.to).sort((a, b) => a.from - b.from)[0]?.summary.from ?? line;
}

/** Return where `fold` ends as it's seen: its summary line where it's folded, else its last line, or the summary line of the folded fold hiding that. */
function endOf<F extends Folded>(folds: readonly F[], closed: (fold: F) => boolean, fold: F, startOf: (position: number) => number): number {
    return closed(fold) ? fold.summary.from : seenAt(folds, closed, startOf(fold.to));
}

/**
 * Return where `zj` goes from the line starting at `line` (`forward`), or `zk`: to the start of the next fold, the
 * summary line of the first starting after it; or to the end of the one before, the last line seen of the last ending
 * before it. A folded fold counts as its summary line, and those hidden in it aren't counted. `startOf` gives the start
 * of the line a position is on. None past the last fold, or before the first.
 */
export function nextFold<F extends Folded>(
    folds: readonly F[],
    closed: (fold: F) => boolean,
    line: number,
    forward: boolean,
    startOf: (position: number) => number,
): number | undefined {
    const seen = folds.filter((each) => !hidden(folds, closed, each));
    if (forward) {
        const starts = seen.map((each) => each.summary.from).filter((each) => each > line);
        return starts.length === 0 ? undefined : Math.min(...starts);
    }
    const ends = seen.map((each) => endOf(folds, closed, each, startOf)).filter((each) => each < line);
    return ends.length === 0 ? undefined : Math.max(...ends);
}

/**
 * Return where `[z` goes from the line starting at `line` (`start`), or `]z`: to the summary line, or the last line
 * seen, of the innermost open fold it's in; where it's there already, of the open fold around that one. `startOf` gives
 * the start of the line a position is on. None outside every open fold.
 */
export function foldEdge<F extends Folded>(
    folds: readonly F[],
    closed: (fold: F) => boolean,
    line: number,
    start: boolean,
    startOf: (position: number) => number,
): number | undefined {
    const edges = around(folds, line)
        .filter((each) => !closed(each))
        .map((each) => (start ? each.summary.from : endOf(folds, closed, each, startOf)))
        .reverse();
    return edges.find((each) => each !== line);
}
