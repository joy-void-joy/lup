// The list of the panes (`panes.ts`): a buffer with vim's keys, its own CodeMirror, made as the review's is
// (`useEditor`), read-only since nothing here is what the operator wrote. Each row kept by its id through what changes,
// so the cursor stays on it as agents come and go, a fold named by its key; Enter opens the row's buffer in the second
// pane and goes into it, a click opens it, `o` opens it writing to whom it reaches (`docs/dashboard.md`, *The panes*).
import { foldedRanges } from "@codemirror/language";
import { RangeSet, StateEffect, type EditorState, type Range } from "@codemirror/state";
import { Decoration, EditorView, highlightActiveLine } from "@codemirror/view";
import { useEffect, useMemo, useRef, useState, type RefObject } from "react";

import { hiddenAt, rebuilt, refold, useEditor } from "./editor";
import type { Here } from "./keys";
import { listLaid, nearestShown, rowAt, type PlacedRow, type Row, type Showing, bufferKey } from "./panes";
import { owned, owning, ownersOf, reconcile } from "./reconcile";
import { clock, ticked, ticking } from "./ticking";

/** How the review reaches the list: giving it the keyboard, and asking what the line of keys says of it. */
export interface ListHandle {
    focus: () => void;
    here: () => Here;
}

interface Props {
    rows: readonly Row[];
    /** The buffer on screen, whose row says so. */
    showing: Showing;
    /** What of it the second pane has in view, and the row its cursor is on, each by the row's id: what's kept in sight here, on the nearest row showing where a closed nest hides its own, never a cursor, which says where the keys go. */
    viewed: Viewed;
    /** Show a row's buffer: going into it, staying in the list, or going into it writing to whom it reaches; on the item or check `node`, where it's one's. */
    open: (showing: Showing, how: "in" | "stay" | "write", node?: number | null) => void;
    send: () => void;
    say: (text: string) => void;
    /** Told Esc with nothing left for vim to end. */
    escaped: () => void;
    /** Told vim's window commands. */
    window: (how: "h" | "l" | "w" | "p") => void;
    placed: (here: Here) => void;
    list: () => void;
    whole: () => void;
    pending: (keys: string) => void;
    handle: RefObject<ListHandle | null>;
}

/** What of the buffer on screen the second pane has in view, by row. */
export interface Viewed {
    seen: readonly string[];
    cursor: string | null;
}

/** What the list's editor keeps no draft of: nothing here is written. */
const NOTHING = null;

export function Listing({ rows, showing, viewed, open, send, say, escaped, window: windowCommand, placed, list, whole, pending, handle }: Props) {
    const laid = useMemo(() => listLaid(rows), [rows]);
    const placedBy = useMemo(() => new Map(laid.rows.map((each) => [each.row, each])), [laid]);
    /** Return where the row showing the row named `id` is laid out in `state`: itself, else the nearest holding it no closed nest hides. */
    const shownOf = (state: EditorState, id: string | null): PlacedRow | undefined => {
        const shown = id === null ? undefined : nearestShown(rows, id, (row) => hiddenAt(state, placedBy.get(row)?.from ?? 0));
        return shown === undefined ? undefined : placedBy.get(shown);
    };
    const shown = useMemo(() => ({ text: laid.text, blocks: [], folds: laid.folds }), [laid]);
    const hereOf = (at: number): Here => {
        const row = rowAt(laid, at);
        if (row === undefined) {
            return { on: "", reached: [] };
        }
        return {
            on: row.says,
            reached: [
                ...(row.opens === null ? [] : [{ keys: "⏎", says: row.node === undefined ? "open it, and go in" : "go to it", on: null }]),
                ...(row.writes ? [{ keys: "o", says: "write to them", on: null }] : []),
                ...(row.under === undefined ? [] : [{ keys: "za", says: "open or fold what's under it", on: null }]),
                { keys: "␣ww", says: "to the buffer, as Ctrl+W w", on: null },
            ],
        };
    };
    const editor = useEditor<null, { id: string; text: string }>({
        shown,
        draft: NOTHING,
        comments: () => [],
        withComments: (draft) => draft,
        change: () => undefined,
        inserting: () => undefined,
        epoch: 0,
        shownNow: false,
        rows: true,
        escaped,
        window: windowCommand,
        say,
        moved: (at) => placed(hereOf(at)),
        list,
        whole,
        pending,
    });
    const { view } = editor;
    const [nestsMoved, setNestsMoved] = useState(0);
    // Whose each line is, what's drawn on it as the time passes, and which line the cursor's on, whatever has the keyboard;
    // and a nest the operator opens or closes, which changes the row showing what the second pane has in view.
    useEffect(() => {
        const nestMoved = EditorView.updateListener.of((update) => {
            if (foldedRanges(update.startState) !== foldedRanges(update.state) && !update.transactions.some((each) => each.annotation(rebuilt) === true)) {
                setNestsMoved((count) => count + 1);
            }
        });
        view.current?.dispatch({ effects: StateEffect.appendConfig.of([owning, ticking, clock, highlightActiveLine(), nestMoved]) });
        // Made once, with the editor.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    handle.current = {
        // Going in, the cursor's on the row showing what the second pane's cursor is on, as `gO` went to in the overview.
        focus: () => {
            const current = view.current;
            const row = current === null ? undefined : shownOf(current.state, viewed.cursor);
            if (current !== null && row !== undefined && !current.hasFocus) {
                current.dispatch({ selection: { anchor: row.from }, scrollIntoView: true, annotations: rebuilt.of(true) });
            }
            current?.focus();
        },
        here: () => hereOf(editor.head()),
    };
    const openAt = useRef<(at: number, how: "in" | "stay" | "write") => void>(() => undefined);
    openAt.current = (at, how) => {
        const row = rowAt(laid, at);
        if (row?.opens != null) {
            open(row.opens, how, row.node ?? null);
        }
    };
    // A click on a row opens it, the keyboard staying in the list.
    useEffect(() => {
        const current = view.current;
        if (current === null) {
            return undefined;
        }
        const clicked = (event: MouseEvent) => {
            const at = current.posAtCoords({ x: event.clientX, y: event.clientY });
            if (at !== null) {
                openAt.current(at, "stay");
            }
        };
        current.dom.addEventListener("click", clicked);
        return () => current.dom.removeEventListener("click", clicked);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    // Laid out anew as it changes, each row's lines kept as its own, so the cursor stays on it; drawn with which is on screen.
    useEffect(() => {
        const current = view.current;
        if (current === null) {
            return;
        }
        const state = current.state;
        const runs = state.field(owning);
        const same = state.doc.length === laid.text.length && state.sliceDoc() === laid.text;
        const made = same ? { changes: [], arrived: [] } : reconcile(state.doc, ownersOf(state.doc, runs), laid.text, laid.owners, () => 1);
        current.dispatch({ changes: state.changes(made.changes), annotations: rebuilt.of(true), effects: owned.of(laid.runs) });
        refold(current, laid.folds, editor.kept.current);
        const showingId = bufferKey(showing);
        // Each on the nearest row showing where its own is in a closed nest: where the second pane goes moves no row.
        const seen = new Set(viewed.seen.map((each) => shownOf(current.state, each)?.row.id));
        const entry = shownOf(current.state, viewed.cursor);
        const classes = (each: { look: string; row: string }) =>
            ["list-row", each.look, each.row === showingId ? "list-showing" : "", seen.has(each.row) ? "list-in-view" : "", each.row === entry?.row.id ? "list-cursor" : ""].filter((one) => one !== "").join(" ");
        const ranges: Range<Decoration>[] = [
            ...laid.lines.map((each) => Decoration.line({ class: classes(each) }).range(each.at)),
            ...laid.marks.map((each) => Decoration.mark({ class: each.look }).range(each.from, each.to)),
        ];
        editor.draw(RangeSet.of(ranges, true));
        current.dispatch({ effects: ticked.of(laid.ticks) });
        // The row showing what the second pane's cursor is on stays in sight, while the keyboard isn't here to move the list.
        if (entry !== undefined && !current.hasFocus) {
            current.dispatch({ effects: EditorView.scrollIntoView(entry.from, { y: "nearest", yMargin: 2 * current.defaultLineHeight }) });
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [laid, showing, viewed, nestsMoved]);
    // The cursor goes to the row of what's on screen where it was opened from elsewhere, as `gd` or the palette.
    const shownRow = useRef(bufferKey(showing));
    useEffect(() => {
        const current = view.current;
        const key = bufferKey(showing);
        if (current === null || shownRow.current === key) {
            return;
        }
        shownRow.current = key;
        if (!current.hasFocus) {
            const row = laid.rows.find((each) => each.row.id === bufferKey(showing));
            if (row !== undefined) {
                current.dispatch({ selection: { anchor: row.from }, scrollIntoView: true, annotations: rebuilt.of(true) });
            }
        }
    }, [showing, laid, view]);
    editor.bind({
        whole: (at) => {
            openAt.current(at, "write");
            return undefined;
        },
        opened: (at) => {
            if (rowAt(laid, at)?.writes === true) {
                openAt.current(at, "write");
            }
            return undefined;
        },
        quoted: () => undefined,
        about: () => undefined,
        move: (forward) => {
            const current = view.current;
            if (current === null) {
                return;
            }
            const at = editor.head();
            const opening = laid.rows.filter((each) => each.row.opens !== null);
            const target = forward ? opening.find((each) => each.from > at) : opening.findLast((each) => each.to < at);
            if (target !== undefined) {
                current.dispatch({ selection: { anchor: target.from }, scrollIntoView: true });
            }
        },
        send,
        enter: () => openAt.current(editor.head(), "in"),
        verb: () => say("␣ and a key marks what's in the second pane: Enter goes into this row's buffer."),
    });
    return <div className="buffer list-buffer" ref={editor.parent} />;
}

