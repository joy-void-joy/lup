// The margin: the document's structure beside its text, as the second lup's page drew it. A column for each depth
// folds nest to, outermost leftmost; each fold's letter, its kind's, in its column on the line its summary is on, in
// its kind's colour and outlined where it's closed, so the margin also says which key reaches it (`zf` and the
// letter); and beside every line under an open fold, a bar down that fold's column, dim, bright for the folds the
// cursor is in. A CodeMirror gutter, whose rows are as tall as the lines beside them, wrapped or not, so the
// structure's heights are the text's by construction. A click on a letter opens or closes its fold. A closed fold
// says how many lines it hides after its summary, in its kind's colour.

import { codeFolding } from "@codemirror/language";
import { type EditorState, type Extension } from "@codemirror/state";
import { EditorView, GutterMarker, gutter, type ViewUpdate } from "@codemirror/view";

import { depthOf, foldKind, foldRange, nodeAt, offsetOf, type Node as Laid } from "../document/tree";
import { redrawn } from "./annotations";
import { shells, type Shell } from "./shell";

/** A fold's letter, on the line its summary is on. */
export interface Lettered {
    readonly key: string;
    readonly letter: string;
    readonly colour: string;
    readonly column: number;
    readonly closed: boolean;
    /** Whether a comment is written under it, its own or one of what it holds. */
    readonly drafted: boolean;
}

/** A bar beside a line under an open fold, in the fold's column. */
export interface Barred {
    readonly key: string;
    readonly colour: string;
    readonly column: number;
    /** Whether the cursor is in its fold. */
    readonly bright: boolean;
    /** Whether the line holds the fold's end, where the bar stops short, so two folds one after another show apart. */
    readonly last: boolean;
}

/** What the margin shows beside one line: the letters of the folds whose summary is on it, and the bars of those it's under. */
export interface Beside {
    readonly letters: readonly Lettered[];
    readonly bars: readonly Barred[];
}

/** Return what the margin shows beside the line from `from` to `to`, the folds the cursor is in being `bright`. */
export function beside(shell: Shell, from: number, to: number, bright: ReadonlySet<string>): Beside {
    const letters: Lettered[] = [];
    const bars: Barred[] = [];
    let node: Laid | null = nodeAt(shell.document.root, from);
    while (node !== null) {
        const kind = foldKind(node);
        if (kind !== null) {
            const declared = shell.kinds.folds.get(kind);
            const colour = declared?.colour ?? "muted";
            const column = depthOf(node);
            const start = offsetOf(node);
            if (start === from) {
                letters.push({ key: node.key, letter: declared?.letter ?? "?", colour, column, closed: !shell.isOpen(node), drafted: shell.comments.within(node) > 0 });
            } else {
                const end = start + node.size;
                bars.push({ key: node.key, colour, column, bright: bright.has(node.key), last: end >= from && end <= to });
            }
        }
        node = node.parent;
    }
    return { letters: letters.reverse(), bars: bars.reverse() };
}

/** Return the keys of the folds the cursor is in, in `state`. */
export function cursorFolds(shell: Shell, state: EditorState): ReadonlySet<string> {
    const keys = new Set<string>();
    let node: Laid | null = nodeAt(shell.document.root, state.selection.main.head);
    while (node !== null) {
        if (foldKind(node) !== null) {
            keys.add(node.key);
        }
        node = node.parent;
    }
    return keys;
}

/** The folds the cursor is in, worked out once for each state the margin draws. */
const brightIn = new WeakMap<EditorState, ReadonlySet<string>>();

class Marked extends GutterMarker {
    readonly #signature: string;

    constructor(
        readonly shown: Beside,
        readonly columns: number,
    ) {
        super();
        this.#signature = JSON.stringify(shown);
    }

    override eq(other: GutterMarker): boolean {
        return other instanceof Marked && other.#signature === this.#signature;
    }

    override toDOM(): Node {
        const cell = document.createElement("span");
        cell.className = "lup-rails";
        for (const bar of this.shown.bars) {
            const drawn = document.createElement("span");
            drawn.className = `lup-rail${bar.bright ? " lup-bright" : ""}${bar.last ? " lup-last" : ""}`;
            drawn.style.setProperty("--lup-at", String(Math.min(bar.column, this.columns - 1)));
            drawn.style.color = `var(--lup-${bar.colour})`;
            cell.append(drawn);
        }
        for (const letter of this.shown.letters) {
            const drawn = document.createElement("span");
            drawn.className = `lup-letter${letter.closed ? " lup-closed" : ""}${letter.drafted ? " lup-drafted" : ""}`;
            drawn.dataset.key = letter.key;
            drawn.textContent = letter.letter;
            drawn.title = letter.closed ? "open" : "close";
            drawn.style.setProperty("--lup-at", String(Math.min(letter.column, this.columns - 1)));
            drawn.style.color = `var(--lup-${letter.colour})`;
            cell.append(drawn);
        }
        return cell;
    }
}

/** Say whether `update` may change what the margin shows: the text, the cursor, or what's open. */
function moved(update: ViewUpdate): boolean {
    return (
        update.docChanged ||
        update.selectionSet ||
        update.transactions.some((transaction) => transaction.effects.some((effect) => effect.is(redrawn)))
    );
}

/** The margin, `columns` wide: folds deeper than that share its last column. */
export function margin(columns = 6): Extension {
    return [
        EditorView.editorAttributes.of({ style: `--lup-columns: ${columns}` }),
        gutter({
            class: "lup-margin",
            lineMarker(view, line) {
                const shell = view.state.facet(shells);
                if (shell === null) {
                    return null;
                }
                let bright = brightIn.get(view.state);
                if (bright === undefined) {
                    bright = cursorFolds(shell, view.state);
                    brightIn.set(view.state, bright);
                }
                const shown = beside(shell, line.from, view.state.doc.lineAt(line.from).to, bright);
                return shown.letters.length === 0 && shown.bars.length === 0 ? null : new Marked(shown, columns);
            },
            lineMarkerChange: moved,
            domEventHandlers: {
                mousedown(view, _line, event) {
                    const key = event.target instanceof HTMLElement ? event.target.closest<HTMLElement>(".lup-letter")?.dataset.key : undefined;
                    if (key === undefined) {
                        return false;
                    }
                    view.state.facet(shells)?.toggle(key);
                    return true;
                },
            },
        }),
    ];
}

/** A closed fold's placeholder: how many lines it hides, outlined in its kind's colour; a click opens it, as the operator does. */
export const placeholder: Extension = codeFolding({
    preparePlaceholder(state, range) {
        const shell = state.facet(shells);
        const node = shell === null ? null : nodeAt(shell.document.root, range.from);
        const kind = node === null ? null : foldKind(node);
        if (shell === null || node === null || kind === null || foldRange(node, offsetOf(node))?.to !== range.to) {
            return null;
        }
        return { key: node.key, colour: shell.kinds.folds.get(kind)?.colour ?? "muted", hidden: node.lines - 1, comments: shell.comments.within(node) };
    },
    placeholderDOM(view, _onclick, prepared: { key: string; colour: string; hidden: number; comments: number } | null) {
        const shown = document.createElement("span");
        shown.className = "lup-placeholder";
        shown.title = "open";
        if (prepared === null) {
            shown.textContent = "⋯";
            return shown;
        }
        const comments = prepared.comments === 0 ? "" : ` · ${prepared.comments} ${prepared.comments === 1 ? "comment" : "comments"}`;
        shown.textContent = `⋯ ${prepared.hidden} ${prepared.hidden === 1 ? "line" : "lines"}${comments}`;
        shown.style.color = `var(--lup-${prepared.colour})`;
        shown.addEventListener("mousedown", (event) => {
            event.preventDefault();
            view.state.facet(shells)?.toggle(prepared.key, true);
        });
        return shown;
    },
});
