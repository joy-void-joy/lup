// The editor the review and a conversation share: one buffer moved through with
// vim, the operator's comments written into it, each under the line it's on, as
// the only text they can change. Insert mode is writing a comment: a key that
// enters it opens one where the cursor is, or edits the one it's in, and the
// cursor stays in it until it ends. Space `c` opens one on the whole (an item,
// a conversation); vim's change, `c` and a motion, on the passage it covers
// (`ct.`, `ciw`, `cip`, `cc` a line's); `o`, `C` and vim's other keys of insert
// mode on the line; `v` and a motion, then `c` or `s`, on the selection. `]]` and
// `[[` go to the next and previous item or turn. Ctrl+Enter in a comment ends
// it, back on what it's about; elsewhere it sends. `u` and Ctrl+R undo and redo
// any change to the draft. What folds is folded until opened: `za` opens or
// closes the fold under the cursor, `zo` and `zc` open and close it, `zR` and
// `zM` open and close them all. Space `h`, or Space `w` `h`, goes to the agents'
// tree. Each view says what else its keys do, lays its own text out and draws
// it, and may paint the lines in view as well, as the review paints a changed
// file's (`Review.tsx`, `Conversation.tsx`; `docs/dashboard.md`). A fold may be
// inside another, as an item's text is inside what came before the operator's
// last words: the fold keys act on the innermost the cursor is on.
import { codeFolding, foldEffect, foldedRanges, unfoldEffect } from "@codemirror/language";
import { Annotation, EditorState, Facet, Prec, StateEffect, StateField, type Range } from "@codemirror/state";
import {
    Decoration,
    EditorView,
    ViewPlugin,
    drawSelection,
    type DecorationSet,
    type ViewUpdate,
} from "@codemirror/view";
import { Vim, getCM, vim, type CodeMirror, type CodeMirrorV } from "@replit/codemirror-vim";
import { useEffect, useRef, type RefObject } from "react";

import { saying, type Block, type Folding, type Span } from "./comments";

/** What the vim keys and the editor's own events do, as a view stands: replaced at each render. */
interface Actions {
    comment: (cm: CodeMirrorV, on: "line" | "selection" | "whole") => void;
    entered: (cm: CodeMirrorV) => void;
    left: () => void;
    finish: (cm: CodeMirrorV) => void;
    toggle: (list: "done" | "parked") => void;
    move: (forward: boolean) => void;
    approve: (approved: boolean) => void;
    back: () => void;
    tree: () => void;
    fold: (how: "toggle" | "open" | "close") => void;
    foldAll: (closing: boolean) => void;
    folded: (state: EditorState) => void;
    undo: (back: boolean) => void;
    send: () => void;
    blocks: () => Block[];
    edited: (update: ViewUpdate) => void;
    paint: (from: number, to: number) => Range<Decoration>[];
}

/** What an editor knows of the last key, read once vim has made of it what it does. */
interface Keyed {
    /** Where the cursor was when it was pressed: the line a comment it opens is on, wherever vim moved the cursor since. */
    from: number;
    /** Whether it was pressed in visual mode, where a comment it opens is on the selection. */
    visual: boolean;
    /** The passage it tried to change outside every comment, as `v` then `R` would: what such a comment quotes. */
    passage: Span | null;
    /** Whether it's part of vim's change, `c` and a motion, begun in normal mode: a comment it opens is on the passage the motion covers. */
    changing: boolean;
    /** Whether vim is in insert mode, that is, whether a comment is being written. */
    inserting: boolean;
}

/** One editor's own: what its keys do, and what it knows of the last key. */
interface Bound {
    actions: Actions | null;
    keyed: Keyed;
}

/** Each editor's own, read by the keys, the filters and vim's actions, which vim's keymap shares between editors. */
const binding = Facet.define<Bound, Bound | null>({ combine: (values) => values[0] ?? null });

const NONE: Keyed = { from: 0, visual: false, passage: null, changing: false, inserting: false };

function boundOf(state: EditorState): Bound {
    return state.facet(binding) ?? { actions: null, keyed: NONE };
}

let mapped = false;

/** Map the shared keys into vim's keymap, once: user mappings go before its own, and act on the editor the key is pressed in. */
function mapKeys(): void {
    if (mapped) {
        return;
    }
    mapped = true;
    // Space moves right in vim's own keymap, under every context; taken off, it leads
    // the views' keys. Its types want a context, where none names that mapping.
    const unmap = Vim.unmap as (keys: string, context?: string) => boolean;
    unmap("<Space>");
    const action = (name: string, fn: (actions: Actions, cm: CodeMirrorV) => void) =>
        Vim.defineAction(name, (cm) => {
            const actions = boundOf(cm.cm6.state).actions;
            if (actions !== null) {
                fn(actions, cm);
            }
        });
    action("lupCommentLine", (actions, cm) => actions.comment(cm, "line"));
    action("lupCommentWhole", (actions, cm) => actions.comment(cm, "whole"));
    action("lupCommentSelection", (actions, cm) => actions.comment(cm, "selection"));
    action("lupDone", (actions) => actions.toggle("done"));
    action("lupLater", (actions) => actions.toggle("parked"));
    action("lupNext", (actions) => actions.move(true));
    action("lupPrevious", (actions) => actions.move(false));
    action("lupApprove", (actions) => actions.approve(true));
    action("lupDecline", (actions) => actions.approve(false));
    action("lupBack", (actions) => actions.back());
    action("lupTree", (actions) => actions.tree());
    // Vim's own fold keys, which its CodeMirror mode leaves unmapped, on CodeMirror's folds.
    action("lupFoldToggle", (actions) => actions.fold("toggle"));
    action("lupFoldOpen", (actions) => actions.fold("open"));
    action("lupFoldClose", (actions) => actions.fold("close"));
    action("lupFoldOpenAll", (actions) => actions.foldAll(false));
    action("lupFoldCloseAll", (actions) => actions.foldAll(true));
    action("lupUndo", (actions) => actions.undo(true));
    action("lupRedo", (actions) => actions.undo(false));
    const map = (keys: string, name: string, context: string) =>
        Vim.mapCommand(keys, "action", name, {}, { context });
    map("o", "lupCommentLine", "normal");
    map("c", "lupCommentSelection", "visual");
    map("s", "lupCommentSelection", "visual");
    map("<Space>c", "lupCommentWhole", "normal");
    map("<Space>d", "lupDone", "normal");
    map("<Space>z", "lupLater", "normal");
    map("<Space>a", "lupApprove", "normal");
    map("<Space>x", "lupDecline", "normal");
    map("<Space>r", "lupBack", "normal");
    map("<Space>h", "lupTree", "normal");
    map("<Space>wh", "lupTree", "normal");
    map("za", "lupFoldToggle", "normal");
    map("zo", "lupFoldOpen", "normal");
    map("zc", "lupFoldClose", "normal");
    map("zR", "lupFoldOpenAll", "normal");
    map("zM", "lupFoldCloseAll", "normal");
    map("u", "lupUndo", "normal");
    map("<C-r>", "lupRedo", "normal");
    map("]]", "lupNext", "normal");
    map("[[", "lupPrevious", "normal");
}

/** Return the editor's vim, once it's started. */
export function vimOf(view: EditorView): CodeMirrorV | null {
    const cm = getCM(view);
    return cm !== null && started(cm) ? cm : null;
}

function started(cm: CodeMirror): cm is CodeMirrorV {
    return cm.state.vim !== null && cm.state.vim !== undefined;
}

/** Return whether vim waits for nothing in normal mode: no count, operator or keys of a mapping typed yet. */
function idle(cm: CodeMirrorV): boolean {
    const state = cm.state.vim;
    if (state.insertMode || state.visualMode) {
        return false;
    }
    const input = state.inputState;
    return input.keyBuffer.length === 0 && input.prefixRepeat.length === 0 && !input.operator && !input.motion;
}

/** Return the comment shown around `position`, by the blocks the actions know. */
function commentAt(bound: Bound, position: number): Block | undefined {
    return (bound.actions?.blocks() ?? []).find((each) => position >= each.from && position <= each.to);
}

/**
 * The keys that vim's keymap can't say, read ahead of vim, which takes every key it's given before a keymap would:
 * Ctrl+Enter, which ends a comment in insert mode and sends elsewhere; and `C` alone outside every comment, a comment
 * on the line, which in a comment stays vim's change. Every key is noted first, for what vim makes of it (`Keyed`):
 * one with no key of vim's pending begins what it notes, `c` in normal mode beginning vim's change.
 *
 * A dead key, as `` ` `` on a layout where it waits for the next key, gives no key of its own: the browser composes it
 * with the next, `` ` `` then Space making a `` ` ``. Outside insert mode, vim gets what's composed, as typed, and
 * neither key that composed it, the Space among them, which would begin a chord; in a comment, the browser composes
 * into the text as usual.
 */
const keys = Prec.highest(
    EditorView.domEventHandlers({
        compositionend: (event, view) => {
            const cm = vimOf(view);
            if (cm === null || cm.state.vim.insertMode || event.data === "") {
                return false;
            }
            for (const typed of event.data) {
                Vim.handleKey(cm, typed, "user");
            }
            return true;
        },
        keydown: (event, view) => {
            const cm = vimOf(view);
            if (cm === null) {
                return false;
            }
            if ((event.key === "Dead" || event.isComposing) && !cm.state.vim.insertMode) {
                return true;
            }
            const bound = boundOf(view.state);
            const { keyed } = bound;
            const head = view.state.selection.main.head;
            keyed.from = head;
            keyed.visual = cm.state.vim.visualMode;
            keyed.passage = null;
            const modified = event.ctrlKey || event.metaKey || event.altKey;
            if (idle(cm)) {
                keyed.changing = event.key === "c" && !modified && !keyed.visual;
            }
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                if (cm.state.vim.insertMode) {
                    bound.actions?.finish(cm);
                } else {
                    bound.actions?.send();
                }
                event.preventDefault();
                return true;
            }
            if (event.key === "C" && !modified && idle(cm) && commentAt(bound, head) === undefined) {
                bound.actions?.comment(cm, "line");
                event.preventDefault();
                return true;
            }
            return false;
        },
    }),
);

/** Marks a view's own replacing of its text, which isn't the operator's edit. */
export const rebuilt = Annotation.define<boolean>();

const drawn = StateEffect.define<DecorationSet>();

const drawing = StateField.define<DecorationSet>({
    create: () => Decoration.none,
    update: (set, transaction) => {
        const replaced = transaction.effects.find((each) => each.is(drawn));
        return replaced === undefined ? set.map(transaction.changes) : (replaced.value as DecorationSet);
    },
    provide: (field) => EditorView.decorations.from(field),
});

/** Return what the view paints on the lines in view, beyond what it drew on the whole text. */
function painted(view: EditorView): DecorationSet {
    const actions = boundOf(view.state).actions;
    if (actions === null) {
        return Decoration.none;
    }
    return Decoration.set(
        view.visibleRanges.flatMap(({ from, to }) => actions.paint(from, to)),
        true,
    );
}

/**
 * What a view paints on the lines in view alone, as a changed file's lines and their highlighting: painted again as
 * the view scrolls, a fold opens, the text changes or the view draws anew, so a long text costs only what's seen.
 */
const painting = ViewPlugin.fromClass(
    class {
        decorations: DecorationSet;

        constructor(view: EditorView) {
            this.decorations = painted(view);
        }

        update(update: ViewUpdate) {
            const redrawn = update.transactions.some((each) => each.effects.some((effect) => effect.is(drawn)));
            if (update.docChanged || update.viewportChanged || redrawn) {
                this.decorations = painted(update.view);
            }
        }
    },
    { decorations: (plugin) => plugin.decorations },
);

/**
 * Let the operator change the text only inside a comment: a change from its start to just past its end. A change
 * tried elsewhere is dropped, its passage noted, for the comment vim's insert mode opens next.
 */
const onlyComments = EditorState.transactionFilter.of((transaction) => {
    if (!transaction.docChanged || transaction.annotation(rebuilt) === true) {
        return transaction;
    }
    const bound = boundOf(transaction.startState);
    const blocks = bound.actions?.blocks() ?? [];
    let inside = true;
    transaction.changes.iterChangedRanges((from, to) => {
        if (!blocks.some((each) => from >= each.from && to <= each.to + 1)) {
            inside = false;
            if (to > from && bound.keyed.passage === null) {
                bound.keyed.passage = { from, to };
            }
        }
    });
    return inside ? transaction : [];
});

/** Keep the cursor in the comment being written while insert mode lasts, as a text field would; a click elsewhere ends it instead. */
const withinComment = EditorState.transactionFilter.of((transaction) => {
    const moved = transaction.selection;
    const bound = boundOf(transaction.startState);
    if (
        !bound.keyed.inserting ||
        moved === undefined ||
        transaction.docChanged ||
        transaction.isUserEvent("select.pointer") ||
        transaction.annotation(rebuilt) === true
    ) {
        return transaction;
    }
    const block = commentAt(bound, transaction.startState.selection.main.head);
    const head = moved.main.head;
    if (block === undefined || (head >= block.from && head <= block.to)) {
        return transaction;
    }
    return { selection: { anchor: Math.min(Math.max(head, block.from), block.to) }, scrollIntoView: true };
});

/** Return whether CodeMirror holds `fold` folded. */
export function isFolded(state: EditorState, fold: Span): boolean {
    let found = false;
    foldedRanges(state).between(fold.from, fold.from, (from, to) => {
        found ||= from === fold.from && to === fold.to;
    });
    return found;
}

/** Return the effect that folds or unfolds `fold`. */
export function folding(fold: Span, closing: boolean): StateEffect<Span> {
    const range = { from: fold.from, to: fold.to };
    return closing ? foldEffect.of(range) : unfoldEffect.of(range);
}

/** Fold each of `folds` again as the operator left it, where the text around it changed: folded unless they opened it, its range as laid out. */
export function refold(view: EditorView, folds: Folding[], unfolded: Set<string>): void {
    const effects: StateEffect<Span>[] = [];
    for (const fold of folds) {
        let exact = false;
        foldedRanges(view.state).between(fold.from, fold.to, (from, to) => {
            if (from === fold.from && to === fold.to) {
                exact = true;
            } else if (from === fold.from) {
                effects.push(unfoldEffect.of({ from, to }));
            }
        });
        const closing = !unfolded.has(fold.key);
        if (closing && !exact) {
            effects.push(foldEffect.of({ from: fold.from, to: fold.to }));
        }
        if (!closing && exact) {
            effects.push(unfoldEffect.of({ from: fold.from, to: fold.to }));
        }
    }
    // A range folded where nothing folds any more, as an item's text once it's no longer marked read, opens.
    foldedRanges(view.state).between(0, view.state.doc.length, (from, to) => {
        if (!folds.some((each) => each.from === from)) {
            effects.push(unfoldEffect.of({ from, to }));
        }
    });
    if (effects.length > 0) {
        view.dispatch({ effects });
    }
}

/** Return where the cursor goes once a fold closes over it: on its summary line where it was in what the fold hides, else where it was. */
export function uncovered(closed: Folding[], head: number): number {
    return closed.find((each) => head > each.summary.to && head <= each.to)?.summary.from ?? head;
}

/** Where the cursor goes once the text is laid out again: into a comment just opened, onto an item, or nowhere in particular. */
export type Landing = { comment: number } | { item: number } | null;

/** What a view lays out for the editor: its text, the comments in it, and what folds. */
export interface Shown {
    text: string;
    blocks: Block[];
    folds: Folding[];
}

interface Config<D, C> {
    shown: Shown;
    draft: D;
    /** The draft's comments, in their places, and the draft with others. */
    comments: (draft: D) => C[];
    withComments: (draft: D, comments: C[]) => D;
    change: (draft: D) => void;
    /** Told each time vim enters or leaves insert mode, so the page can say what the keys do in it. */
    inserting: (yes: boolean) => void;
    /** Changed each time the draft is replaced from outside, as when it's sent: what was done before can't be undone. */
    epoch: number;
    /** Whether the editor is shown: shown again, it takes the keyboard. */
    shownNow: boolean;
    /** Give the keyboard to the agents' tree. */
    tree: () => void;
}

/** What a view's keys do with what it laid out. */
export interface Own<C> {
    /** The comment `c` opens on the whole at `position`, none where none goes. */
    whole: (position: number) => C | undefined;
    /** The comment `o`, `C` and the keys of insert mode open on the line at `position`. */
    opened: (position: number) => C | undefined;
    /** The comment `v`, a motion, then `c` opens on the passage `from` to `to`. */
    quoted: (from: number, to: number) => C | undefined;
    /** Where the cursor goes back to once `comment`, shown at `block`, ends: what it's about; `opener` is where the key that opened it was pressed, where it was opened since insert mode began. */
    about: (comment: C, block: Block, opener: number | null) => number | undefined;
    move: (forward: boolean) => void;
    send: () => void;
    toggle?: (list: "done" | "parked") => void;
    approve?: (approved: boolean) => void;
    back?: () => void;
    /** What's painted on the lines from `from` to `to` while they're in view, beyond what `draw` drew: a changed file's lines and their highlighting. */
    paint?: (from: number, to: number) => Range<Decoration>[];
}

/** One editor, as a view uses it. */
export interface Editor<D, C> {
    parent: RefObject<HTMLDivElement | null>;
    view: RefObject<EditorView | null>;
    /** Where the cursor is. */
    head: () => number;
    /** Where the cursor goes once the text is laid out again, read and cleared by the view. */
    landing: RefObject<Landing>;
    /** The folds the operator opened, by key: each laying out folds every other one. */
    unfolded: RefObject<Set<string>>;
    /** The draft as it was last rendered. */
    latest: RefObject<D>;
    /** Whether a comment is being written. */
    writing: () => boolean;
    /** Change the draft as one step `u` undoes. */
    record: (next: D) => void;
    /** Draw the text: `decorations` replace those drawn before. */
    draw: (decorations: DecorationSet) => void;
    /** Go into the comment just opened, in insert mode, once the text holds it. */
    enter: () => void;
    /** Say what the keys do with what this render laid out. */
    bind: (own: Own<C>) => void;
}

/**
 * The editor a view draws into `parent`: made once, its keys bound at each render to what the view laid out. The
 * view lays its text into it itself, once it changes, keeping what it must of where the reader is.
 */
export function useEditor<D, C extends { text: string }>(config: Config<D, C>): Editor<D, C> {
    const { shown, comments, withComments, change } = config;
    const parent = useRef<HTMLDivElement>(null);
    const view = useRef<EditorView | null>(null);
    const bound = useRef<Bound>({ actions: null, keyed: { ...NONE } });
    const landing = useRef<Landing>(null);
    const unfolded = useRef(new Set<string>());
    const latest = useRef(config.draft);
    latest.current = config.draft;
    const telling = useRef(config.inserting);
    telling.current = config.inserting;
    // The drafts before each change, for `u`; those undone, for Ctrl+R; and whether the comment being
    // written has its step already, so it's undone whole.
    const past = useRef<D[]>([]);
    const future = useRef<D[]>([]);
    const writing = useRef(false);
    // Where the key that opened the comment being written was pressed.
    const opener = useRef<number | null>(null);
    const keyed = bound.current.keyed;

    useEffect(() => {
        mapKeys();
        const host = parent.current;
        if (host === null) {
            return;
        }
        const created = new EditorView({
            parent: host,
            state: EditorState.create({
                doc: "",
                extensions: [
                    binding.of(bound.current),
                    vim(),
                    drawSelection(),
                    onlyComments,
                    withinComment,
                    EditorView.lineWrapping,
                    codeFolding({ placeholderText: "…" }),
                    drawing,
                    painting,
                    EditorView.updateListener.of((update) => {
                        const actions = bound.current.actions;
                        const replaced = update.transactions.some((each) => each.annotation(rebuilt) === true);
                        if (update.docChanged && !replaced) {
                            actions?.edited(update);
                        }
                        // A fold opened or closed however it was, by its keys, a click, or the cursor going into it,
                        // is kept for the next laying out; an edit only moves the folds with the text.
                        if (!update.docChanged && foldedRanges(update.startState) !== foldedRanges(update.state)) {
                            actions?.folded(update.state);
                        }
                        // A click out of the comment being written ends it, as Esc would.
                        const clicked = update.transactions.some((each) => each.isUserEvent("select.pointer"));
                        const cm = vimOf(update.view);
                        const head = update.state.selection.main.head;
                        if (clicked && cm !== null && keyed.inserting && commentAt(bound.current, head) === undefined) {
                            queueMicrotask(() => Vim.exitInsertMode(cm, true));
                        }
                    }),
                    keys,
                ],
            }),
        });
        view.current = created;
        getCM(created)?.on("vim-mode-change", (event: { mode: string }) => {
            const now = event.mode === "insert" || event.mode === "replace";
            const was = keyed.inserting;
            keyed.inserting = now;
            telling.current(now);
            const cm = vimOf(created);
            if (now && !was && cm !== null) {
                // Vim has done all the key does, a change refused among it, once this returns.
                queueMicrotask(() => bound.current.actions?.entered(cm));
            }
            if (was && !now) {
                bound.current.actions?.left();
            }
        });
        created.focus();
        return () => {
            created.destroy();
            view.current = null;
        };
        // The editor is made once; what it shows is sent to it by the view.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        if (!config.shownNow) {
            return;
        }
        view.current?.focus();
        // Shown by a click elsewhere, as on the tree, it takes the keyboard once that click is done with it.
        const later = requestAnimationFrame(() => view.current?.focus());
        return () => cancelAnimationFrame(later);
    }, [config.shownNow]);

    useEffect(() => {
        past.current = [];
        future.current = [];
    }, [config.epoch]);

    function head(): number {
        return view.current?.state.selection.main.head ?? 0;
    }

    function blockAt(position: number): Block | undefined {
        return shown.blocks.find((each) => position >= each.from && position <= each.to);
    }

    /** Change the draft as one step `u` undoes: the comment being written, from its opening to its end, is one. */
    function record(next: D) {
        if (!writing.current) {
            past.current = [...past.current, latest.current];
            future.current = [];
        }
        writing.current = keyed.inserting;
        change(next);
    }

    function added(comment: C) {
        const present = comments(latest.current);
        landing.current = { comment: present.length };
        opener.current = keyed.from;
        record(withComments(latest.current, [...present, comment]));
        writing.current = true;
    }

    function bind(own: Own<C>) {
        bound.current.actions = {
            comment: (cm, on) => {
                const editor = view.current;
                if (editor === null) {
                    return;
                }
                if (on === "selection") {
                    const from = cm.indexFromPos(cm.getCursor("start"));
                    const to = cm.indexFromPos(cm.getCursor("end"));
                    Vim.exitVisualMode(cm);
                    const comment = own.quoted(from, to);
                    if (comment !== undefined) {
                        added(comment);
                    }
                    return;
                }
                if (on === "line" && blockAt(head()) !== undefined) {
                    const end = editor.state.doc.lineAt(head()).to;
                    editor.dispatch({ changes: { from: end, insert: "\n" }, selection: { anchor: end + 1 } });
                    Vim.handleKey(cm, "i", "mapping");
                    return;
                }
                const comment = on === "whole" ? own.whole(head()) : own.opened(head());
                if (comment !== undefined) {
                    added(comment);
                }
            },
            entered: (cm) => {
                if (blockAt(head()) !== undefined) {
                    return;
                }
                const passage = keyed.visual || keyed.changing ? keyed.passage : null;
                const comment = passage === null ? own.opened(keyed.from) : own.quoted(passage.from, passage.to);
                if (comment === undefined) {
                    Vim.exitInsertMode(cm, true);
                    return;
                }
                added(comment);
            },
            left: () => {
                // The comment's trailing space trimmed, and an emptied one dropped, as part of the step that wrote it.
                const present = comments(latest.current);
                const trimmed = present.map((each) => ({ ...each, text: each.text.replace(/\s+$/, "") }));
                const kept = saying(trimmed);
                const same =
                    kept.length === present.length && trimmed.every((each, at) => each.text === present[at]?.text);
                writing.current = false;
                opener.current = null;
                if (!same) {
                    change(withComments(latest.current, kept));
                }
            },
            finish: (cm) => {
                const editor = view.current;
                const block = blockAt(head());
                const comment = block === undefined ? undefined : comments(latest.current)[block.comment];
                const back = block === undefined || comment === undefined ? undefined : own.about(comment, block, opener.current);
                Vim.exitInsertMode(cm, true);
                if (editor === null || back === undefined) {
                    return;
                }
                editor.dispatch({ selection: { anchor: back }, scrollIntoView: true });
            },
            toggle: (list) => own.toggle?.(list),
            move: own.move,
            approve: (approved) => own.approve?.(approved),
            back: () => own.back?.(),
            tree: config.tree,
            fold: (how) => {
                const editor = view.current;
                const at = head();
                // Of folds one inside another, the innermost the cursor is on: the one whose summary line starts last.
                const fold = shown.folds
                    .filter((each) => at >= each.summary.from && at <= each.to)
                    .reduce<Folding | undefined>((inner, each) => (inner === undefined || each.summary.from > inner.summary.from ? each : inner), undefined);
                if (editor === null || fold === undefined) {
                    return;
                }
                const closed = isFolded(editor.state, fold);
                const closing = how === "toggle" ? !closed : how === "close";
                if (closing !== closed) {
                    // From what the fold hides, or past its placeholder, the cursor goes to its summary line.
                    const back = at > fold.summary.to ? { anchor: fold.summary.from } : undefined;
                    editor.dispatch({ effects: folding(fold, closing), selection: back, scrollIntoView: true });
                }
            },
            foldAll: (closing) => {
                const editor = view.current;
                if (editor === null) {
                    return;
                }
                const changing = shown.folds.filter((each) => isFolded(editor.state, each) !== closing);
                const at = head();
                const back = closing ? uncovered(changing, at) : at;
                editor.dispatch({
                    effects: changing.map((each) => folding(each, closing)),
                    selection: back === at ? undefined : { anchor: back },
                    scrollIntoView: true,
                });
            },
            folded: (state) => {
                // The folds are where this layout puts them only while the text is still its own.
                if (state.sliceDoc() !== shown.text) {
                    return;
                }
                for (const fold of shown.folds) {
                    if (isFolded(state, fold)) {
                        unfolded.current.delete(fold.key);
                    } else {
                        unfolded.current.add(fold.key);
                    }
                }
            },
            undo: (back) => {
                const from = back ? past : future;
                const to = back ? future : past;
                const restored = from.current.at(-1);
                if (restored === undefined) {
                    return;
                }
                from.current = from.current.slice(0, -1);
                to.current = [...to.current, latest.current];
                change(restored);
            },
            send: own.send,
            paint: (from, to) => own.paint?.(from, to) ?? [],
            blocks: () => shown.blocks,
            edited: (update) => {
                const next = [...comments(latest.current)];
                for (const block of shown.blocks) {
                    const from = update.changes.mapPos(block.from, -1);
                    const to = update.changes.mapPos(block.to, 1);
                    const text = update.state.doc.sliceString(from, to);
                    const before = next[block.comment];
                    if (before !== undefined && before.text !== text) {
                        next[block.comment] = { ...before, text };
                    }
                }
                record(withComments(latest.current, keyed.inserting ? next : saying(next)));
            },
        };
    }

    return {
        parent,
        view,
        head,
        landing,
        unfolded,
        latest,
        writing: () => keyed.inserting,
        record,
        draw: (decorations) => view.current?.dispatch({ effects: drawn.of(decorations) }),
        enter: () => {
            const editor = view.current;
            const cm = editor === null ? null : getCM(editor);
            if (cm !== null && !keyed.inserting) {
                Vim.handleKey(cm, "i", "mapping");
            }
        },
        bind,
    };
}
