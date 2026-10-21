// The editor the review and a conversation share: one buffer moved through with
// vim, the operator's comments written into it, each under the line it's on, as
// the only text they can change. Insert mode is writing a comment: a key that
// enters it opens one where the cursor is, or edits the one it's in, and the
// cursor stays in it until it ends. Space `c` opens one on the whole (an item,
// a conversation); vim's change, `c` and a motion, on the passage it covers
// (`ct.`, `ciw`, `cip`, `cc` a line's, `C` to the line's end); `o` and vim's other
// keys of insert mode on the line; `v` and a motion, then `c` or `s`, on the
// selection; where what's covered isn't one item's or one turn's, on the line. `]]` and
// `[[` go to the next and previous item or turn, `]c` and `[c` to the next and
// previous line that matters, where a view has some, `]n` and `[n` to the next
// and previous comment, where the cursor last was in it. Ctrl+Enter in a comment ends
// it, back on what it's about; elsewhere it sends. `u` and Ctrl+R undo and redo
// any change to the draft, `g-` and `g+` go through its history in the order it
// was made (`History`). Each fold is folded or open as the view lays it out
// until the operator opens or closes it, which is kept by its key: `za` opens or
// closes the fold the cursor is in, `zo` and `zc` open and close it; `zr` and
// `zm` open or close a level more, `zR` and `zM` all of them, and Space `f` and a
// letter those of a kind, within what the view says (in the review, the item the
// cursor is in; in a conversation, everything); `zj` and `zk` go to the next
// fold's start and the previous one's end, `[z` and `]z` to the start and the end
// of the open fold the cursor is in (`folds.ts`). Space `h`, or Space `w` `h`,
// goes to the agents' tree; `?` opens the list of every key, in place of vim's
// search backward; once a chord is begun, as with Space, the view is told what's
// pressed, to show what may follow. Each view says what else its keys do, lays
// its own text out and draws it, and may paint the lines in view as well, as the
// review paints a changed file's, and draw its folds' marks and bars in the
// margin (`margin.ts`; `Review.tsx`, `Conversation.tsx`; `docs/dashboard.md`).
// A fold may be inside another, as an item's text is inside what came before the
// operator's last words: the fold keys act on the innermost the cursor is in.
import { foldEffect, foldedRanges, unfoldEffect } from "@codemirror/language";
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
import { around, foldEdge, levelled, nextFold } from "./folds";
import { FOLD_KINDS, type FoldKind } from "./keys";
import { margin, placeheld, type Margined } from "./margin";

/** What the vim keys and the editor's own events do, as a view stands: replaced at each render. */
interface Actions {
    comment: (cm: CodeMirrorV, on: "line" | "whole") => void;
    entered: (cm: CodeMirrorV) => void;
    left: () => void;
    finish: (cm: CodeMirrorV) => void;
    toggle: (list: "done" | "parked") => void;
    move: (forward: boolean) => void;
    matter: (forward: boolean) => void;
    written: (forward: boolean) => void;
    approve: (approved: boolean) => void;
    back: () => void;
    tree: () => void;
    list: () => void;
    fold: (how: "toggle" | "open" | "close") => void;
    foldLevel: (opening: boolean, all: boolean) => void;
    foldKind: (kind: FoldKind, closing: boolean) => void;
    /** Where `zj` and `zk` (`next`), or `[z` and `]z` (`edge`), go from the line starting at `line`. */
    foldMotion: (line: number, how: "next" | "edge", forward: boolean) => number | undefined;
    folded: (update: ViewUpdate) => void;
    folds: () => readonly Folding[];
    undo: (way: "undo" | "redo" | "earlier" | "later") => void;
    send: () => void;
    blocks: () => Block[];
    chord: (keys: string) => void;
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
    /** Where a dead key pressed outside insert mode is. */
    dead: Dead;
}

/**
 * Where a dead key pressed outside insert mode is: none; pressed, vim waiting for what it types; or given to vim, the
 * key that completes it, as Space does, still to come.
 */
export type Dead = "none" | "pressed" | "given";

/** A key pressed outside insert mode, as a dead key reads it: its name, and whether the browser composes it. */
export interface Pressed {
    key: string;
    composing: boolean;
}

/**
 * Return what a key pressed outside insert mode does to a dead key: whether it's kept from vim, and where the dead key
 * is after it. The dead key itself, and a key the browser composes it with, are kept from vim, which gets what they
 * type instead (`deadTyped`); so is the Space that completes one whose character vim has, which would begin a chord.
 * Any other key goes to vim, ending the dead key, as `a` after `` ` `` jumps to mark `a`.
 */
export function deadPressed(dead: Dead, pressed: Pressed): { kept: boolean; dead: Dead } {
    if (pressed.key === "Dead") {
        return { kept: true, dead: "pressed" };
    }
    if (pressed.composing || pressed.key === "Process") {
        return { kept: true, dead };
    }
    return { kept: dead === "given" && pressed.key === " ", dead: "none" };
}

/**
 * Return what text the browser types into the page outside insert mode does, which never lands there: whether vim gets
 * it as keys, and where the dead key is after it. A dead key gives vim the first text it types, as `` ` `` composing
 * shows `` ` ``, once; anything else typed is dropped, the rest of a composition, a paste, or a dead key's own
 * character typed again as the key after it commits it.
 */
export function deadTyped(dead: Dead): { given: boolean; dead: Dead } {
    return dead === "pressed" ? { given: true, dead: "given" } : { given: false, dead };
}

/**
 * Return where the cursor last was in each comment it left, once it moves from `from` to `to` with the text the same:
 * where it was in the one it leaves, in place of where it was in it before; none outside every comment of `blocks`.
 */
export function visit(visited: readonly number[], blocks: readonly Span[], from: number, to: number): number[] {
    const inside = (at: number, block: Span) => at >= block.from && at <= block.to;
    const left = blocks.find((each) => inside(from, each));
    if (left === undefined || inside(to, left)) {
        return [...visited];
    }
    const others = visited.filter((at) => !inside(at, left) && blocks.some((each) => inside(at, each)));
    return [...others, from];
}

/**
 * Return where `]n` goes from `head`, or `[n` where `forward` isn't: into the next or the previous comment of `blocks`,
 * past the one the cursor is in, where the cursor last was in it (`visit`), else on its last character, where writing
 * carries on; none past the last, or before the first.
 */
export function nextWritten(blocks: readonly Span[], head: number, forward: boolean, visited: readonly number[]): number | undefined {
    const sorted = [...blocks].sort((a, b) => a.from - b.from);
    const here = sorted.find((each) => head >= each.from && head <= each.to);
    const target = forward
        ? sorted.find((each) => each.from > (here?.to ?? head))
        : sorted.findLast((each) => each.to < (here?.from ?? head));
    if (target === undefined) {
        return undefined;
    }
    // On a character, as vim's cursor is outside insert mode, where writing ended past the last one.
    const last = Math.max(target.to - 1, target.from);
    return Math.min(visited.find((at) => at >= target.from && at <= target.to) ?? last, last);
}

/** One state the draft was in, in its history: what it was, the state it was made from, and the one Ctrl+R goes to. */
interface State<D> {
    draft: D;
    /** The state it was made from, `u`'s; none for the first. */
    parent: number | null;
    /** The state made from it last, or last undone back to it, Ctrl+R's. */
    child: number | null;
}

/**
 * The draft's history, as vim's undo tree: each state it was in after a step, numbered in the order they were made,
 * each but the first made from another; and the state it's in. `u` and Ctrl+R go to the state one was made from and
 * back; `g-` and `g+` to the state made before and after, whatever it was made from, so a state undone and left by a
 * change after it is still reached.
 */
export interface History<D> {
    states: State<D>[];
    at: number;
}

/** Return a history of `draft` alone. */
export function begun<D>(draft: D): History<D> {
    return { states: [{ draft, parent: null, child: null }], at: 0 };
}

/** Return `history` with the state it's in now holding `draft`: a step still being made, as a comment being written, or a change no step made. */
export function rewritten<D>(history: History<D>, draft: D): History<D> {
    return { ...history, states: history.states.map((each, at) => (at === history.at ? { ...each, draft } : each)) };
}

/** Return `history` with a step made from the state it's in to `draft`, numbered after every other. */
export function stepped<D>(history: History<D>, draft: D): History<D> {
    const made = history.states.length;
    const states = history.states.map((each, at) => (at === history.at ? { ...each, child: made } : each));
    return { states: [...states, { draft, parent: history.at, child: null }], at: made };
}

/**
 * Return `history` gone to another state: `undo` to the one the state it's in was made from, its own Ctrl+R's;
 * `redo` to the one Ctrl+R goes to; `earlier` and `later` to the one made before or after it. As it was where there's
 * none.
 */
export function went<D>(history: History<D>, way: "undo" | "redo" | "earlier" | "later"): History<D> {
    const now = history.states[history.at];
    if (now === undefined) {
        return history;
    }
    const to = { undo: now.parent, redo: now.child, earlier: history.at - 1, later: history.at + 1 }[way];
    if (to === null || to < 0 || to >= history.states.length) {
        return history;
    }
    if (way !== "undo") {
        return { ...history, at: to };
    }
    const states = history.states.map((each, at) => (at === to ? { ...each, child: history.at } : each));
    return { states, at: to };
}

/** One editor's own: what its keys do, and what it knows of the last key. */
interface Bound {
    actions: Actions | null;
    keyed: Keyed;
}

/** Each editor's own, read by the keys, the filters and vim's actions, which vim's keymap shares between editors. */
const binding = Facet.define<Bound, Bound | null>({ combine: (values) => values[0] ?? null });

const NONE: Keyed = { from: 0, visual: false, passage: null, changing: false, inserting: false, dead: "none" };

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
    action("lupDone", (actions) => actions.toggle("done"));
    action("lupLater", (actions) => actions.toggle("parked"));
    action("lupNext", (actions) => actions.move(true));
    action("lupPrevious", (actions) => actions.move(false));
    action("lupNextMatter", (actions) => actions.matter(true));
    action("lupPreviousMatter", (actions) => actions.matter(false));
    action("lupNextWritten", (actions) => actions.written(true));
    action("lupPreviousWritten", (actions) => actions.written(false));
    action("lupApprove", (actions) => actions.approve(true));
    action("lupDecline", (actions) => actions.approve(false));
    action("lupBack", (actions) => actions.back());
    action("lupTree", (actions) => actions.tree());
    action("lupKeys", (actions) => actions.list());
    // Vim's own fold keys, which its CodeMirror mode leaves unmapped, on CodeMirror's folds.
    action("lupFoldToggle", (actions) => actions.fold("toggle"));
    action("lupFoldOpen", (actions) => actions.fold("open"));
    action("lupFoldClose", (actions) => actions.fold("close"));
    action("lupFoldOpenAll", (actions) => actions.foldLevel(true, true));
    action("lupFoldCloseAll", (actions) => actions.foldLevel(false, true));
    action("lupFoldOpenLevel", (actions) => actions.foldLevel(true, false));
    action("lupFoldCloseLevel", (actions) => actions.foldLevel(false, false));
    for (const { kind, chord } of FOLD_KINDS) {
        if (chord) {
            action(`lupFoldOpen-${kind}`, (actions) => actions.foldKind(kind, false));
            action(`lupFoldClose-${kind}`, (actions) => actions.foldKind(kind, true));
        }
    }
    // `zj`, `zk`, `[z` and `]z` are motions, as in vim, so `v]z` selects to a fold's end.
    const motion = (name: string, how: "next" | "edge", forward: boolean) =>
        Vim.defineMotion(name, (cm, head) => {
            const line = cm.indexFromPos({ line: head.line, ch: 0 });
            const target = boundOf(cm.cm6.state).actions?.foldMotion(line, how, forward);
            return target === undefined ? head : cm.posFromIndex(target);
        });
    motion("lupNextFold", "next", true);
    motion("lupPreviousFold", "next", false);
    motion("lupFoldStart", "edge", false);
    motion("lupFoldEnd", "edge", true);
    action("lupUndo", (actions) => actions.undo("undo"));
    action("lupRedo", (actions) => actions.undo("redo"));
    action("lupEarlierState", (actions) => actions.undo("earlier"));
    action("lupLaterState", (actions) => actions.undo("later"));
    const map = (keys: string, name: string, context: string) =>
        Vim.mapCommand(keys, "action", name, {}, { context });
    map("o", "lupCommentLine", "normal");
    map("<Space>c", "lupCommentWhole", "normal");
    map("<Space>d", "lupDone", "normal");
    map("<Space>z", "lupLater", "normal");
    map("<Space>a", "lupApprove", "normal");
    map("<Space>x", "lupDecline", "normal");
    map("<Space>r", "lupBack", "normal");
    map("<Space>h", "lupTree", "normal");
    map("<Space>wh", "lupTree", "normal");
    // The list of every key, in place of vim's search backward, which `/` then `N` still does.
    map("?", "lupKeys", "normal");
    map("za", "lupFoldToggle", "normal");
    map("zo", "lupFoldOpen", "normal");
    map("zc", "lupFoldClose", "normal");
    map("zR", "lupFoldOpenAll", "normal");
    map("zM", "lupFoldCloseAll", "normal");
    map("zr", "lupFoldOpenLevel", "normal");
    map("zm", "lupFoldCloseLevel", "normal");
    // Space f and a letter, every fold of its kind in the item; Shift and the letter closes them.
    for (const { kind, letter, chord } of FOLD_KINDS) {
        if (chord) {
            map(`<Space>f${letter}`, `lupFoldOpen-${kind}`, "normal");
            map(`<Space>f${letter.toUpperCase()}`, `lupFoldClose-${kind}`, "normal");
        }
    }
    const motions = { zj: "lupNextFold", zk: "lupPreviousFold", "[z": "lupFoldStart", "]z": "lupFoldEnd" };
    for (const [keys, name] of Object.entries(motions)) {
        Vim.mapCommand(keys, "motion", name, {}, {});
    }
    map("u", "lupUndo", "normal");
    map("<C-r>", "lupRedo", "normal");
    map("g-", "lupEarlierState", "normal");
    map("g+", "lupLaterState", "normal");
    map("]]", "lupNext", "normal");
    map("[[", "lupPrevious", "normal");
    map("]c", "lupNextMatter", "normal");
    map("[c", "lupPreviousMatter", "normal");
    map("]n", "lupNextWritten", "normal");
    map("[n", "lupPreviousWritten", "normal");
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
 * Ctrl+Enter, which ends a comment in insert mode and sends elsewhere. Every key is noted first, for what vim makes of
 * it (`Keyed`): one with no key of vim's pending begins what it notes, `c` or `C` in normal mode beginning vim's
 * change.
 *
 * A dead key, as `` ` `` on a layout where it waits for the next key, gives no key of its own: the browser composes it
 * with the next, `` ` `` then Space making a `` ` ``. Outside insert mode, vim gets the first text it types, once, and
 * neither key that composed it, nor the Space completing it, which would begin a chord (`deadPressed`, `deadTyped`);
 * what's typed never lands (`typed`). In a comment, the browser composes into the text as usual.
 */
const keys = Prec.highest(
    EditorView.domEventHandlers({
        compositionstart: (_, view) => {
            // A composition with no dead key pressed before it, as some browsers give, waits as one does.
            const cm = vimOf(view);
            const { keyed } = boundOf(view.state);
            if (cm !== null && !cm.state.vim.insertMode && keyed.dead === "none") {
                keyed.dead = "pressed";
            }
            return false;
        },
        compositionend: (event, view) => {
            // What a composition made, where nothing it typed was seen first.
            const cm = vimOf(view);
            const { keyed } = boundOf(view.state);
            if (cm === null || cm.state.vim.insertMode || !(event instanceof CompositionEvent) || event.data === "") {
                return false;
            }
            const step = deadTyped(keyed.dead);
            keyed.dead = step.dead;
            if (step.given) {
                give(cm, event.data);
            }
            return false;
        },
        keydown: (event, view) => {
            const cm = vimOf(view);
            if (cm === null) {
                return false;
            }
            const bound = boundOf(view.state);
            // Once vim has the key: the chord begun, if any, for the view to show what may follow.
            queueMicrotask(() => bound.actions?.chord(chordOf(cm)));
            if (!cm.state.vim.insertMode) {
                const step = deadPressed(bound.keyed.dead, { key: event.key, composing: event.isComposing });
                bound.keyed.dead = step.dead;
                if (step.kept) {
                    return true;
                }
            }
            const { keyed } = bound;
            const head = view.state.selection.main.head;
            keyed.from = head;
            keyed.visual = cm.state.vim.visualMode;
            keyed.passage = null;
            const modified = event.ctrlKey || event.metaKey || event.altKey;
            if (idle(cm)) {
                keyed.changing = (event.key === "c" || event.key === "C") && !modified && !keyed.visual;
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
            return false;
        },
    }),
);

/**
 * Return the keys of a chord begun with Space, as the list of keys writes them (`␣`, `␣f`): what vim holds of a mapping
 * typed but not done, in normal mode; none for any other.
 */
export function chordOf(cm: CodeMirrorV): string {
    const vim = cm.state.vim;
    const held = vim.insertMode || vim.visualMode ? [] : vim.inputState.keyBuffer;
    return held[0] === "<Space>" ? held.map((key) => (key === "<Space>" ? "␣" : key)).join("") : "";
}

/** Give vim each character of `text`, as typed. */
function give(cm: CodeMirrorV, text: string): void {
    for (const typed of text) {
        Vim.handleKey(cm, typed, "user");
    }
}

/**
 * Outside insert mode, what the browser types into the page never lands: vim takes each key before the browser would
 * type it, so what's typed is a dead key's, or a paste. A dead key's first text reaches vim as keys (`deadTyped`), and
 * its composition ends there, as CodeMirror is told, so it doesn't wait for one the page took the text of. Read here,
 * ahead of vim's own reading of typed text, which takes a composition's text as keys each time it's typed, so a mark
 * or a jump never types into a comment the cursor is on, nor reaches vim twice.
 */
const typed = Prec.highest(
    EditorView.inputHandler.of((view, _from, _to, text) => {
        const cm = vimOf(view);
        if (cm === null || cm.state.vim.insertMode) {
            return false;
        }
        const { keyed } = boundOf(view.state);
        const step = deadTyped(keyed.dead);
        keyed.dead = step.dead;
        if (step.given) {
            give(cm, text);
            if (view.compositionStarted) {
                view.contentDOM.dispatchEvent(new CompositionEvent("compositionend"));
            }
        }
        return true;
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

/** Return whether `fold` is folded as the operator left it, `kept` by its key, else as it's laid out. */
export function closedAs(fold: Folding, kept: ReadonlyMap<string, boolean>): boolean {
    return kept.get(fold.key) ?? fold.closed;
}

/**
 * Fold each of `folds` again as the operator left it, where the text around it changed: as `kept` holds it, by its
 * key, else as it's laid out (`closedAs`), its range as laid out. What it does isn't the operator's, so isn't kept.
 */
export function refold(view: EditorView, folds: Folding[], kept: ReadonlyMap<string, boolean>): void {
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
        const closing = closedAs(fold, kept);
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
        view.dispatch({ effects, annotations: rebuilt.of(true) });
    }
}

/**
 * Return `kept` with each of `folds` the operator opened or closed from `before` to `after`, by its key: by its keys,
 * a click, or the cursor going into it. One they left alone isn't kept, so it keeps folding as it's laid out.
 */
export function keptFolds(
    folds: readonly Folding[],
    before: EditorState,
    after: EditorState,
    kept: ReadonlyMap<string, boolean>,
): Map<string, boolean> {
    const next = new Map(kept);
    for (const fold of folds) {
        const now = isFolded(after, fold);
        if (now !== isFolded(before, fold)) {
            next.set(fold.key, now);
        }
    }
    return next;
}

/** Return where the cursor goes once a fold closes over it: on its summary line where it was in what the fold hides, else where it was. */
export function uncovered(closed: Folding[], head: number): number {
    return closed.find((each) => head > each.from && head <= each.to)?.summary.from ?? head;
}

/**
 * Where the cursor goes once the text is laid out again: into a comment just opened, onto an item, to a place in the
 * text as it was, carried with the text's changes, or nowhere in particular.
 */
export type Landing = { comment: number } | { item: number } | { at: number } | null;

/** What a view lays out for the editor: its text, the comments in it, and what folds. */
export interface Shown {
    text: string;
    blocks: Block[];
    folds: Folding[];
}

interface Config<D, C> {
    shown: Shown;
    draft: D;
    /** The draft's comments, in their places, and the draft with others: what's written in it in one list, whatever lists the draft keeps it in. */
    comments: (draft: D) => C[];
    withComments: (draft: D, comments: C[]) => D;
    change: (draft: D) => void;
    /** Told each time vim enters or leaves insert mode, so the page can say what the keys do in it. */
    inserting: (yes: boolean) => void;
    /** Told where the cursor is each time it moves or the text changes, so the page can say what the keys do there. */
    moved?: (head: number) => void;
    /** Changed each time the draft is replaced from outside, as when it's sent: what was done before can't be undone. */
    epoch: number;
    /** Whether the editor is shown: shown again, it takes the keyboard. */
    shownNow: boolean;
    /** Give the keyboard to the agents' tree. */
    tree: () => void;
    /** Open the list of every key (`?`). */
    list: () => void;
    /** Told the keys of a chord begun, as the list writes them (`␣`, `␣f`), each time they change: none once it's done. */
    pending?: (keys: string) => void;
    /** Whether the margin shows each fold's mark and the bars of those the cursor is in (`margin.ts`). */
    margin?: boolean;
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
    /** Go to the next or previous line that matters, as the review's are by the judge's reading, opening what folds it on the way. */
    matter?: (forward: boolean) => void;
    approve?: (approved: boolean) => void;
    back?: () => void;
    /** What's painted on the lines from `from` to `to` while they're in view, beyond what `draw` drew: a changed file's lines and their highlighting. */
    paint?: (from: number, to: number) => Range<Decoration>[];
    /** The folds `zr` opens (`opening`) or `zm` closes from `position`, or with `all` `zR` and `zM`; where none's said, those of every fold (`levelled`). */
    level?: (position: number, opening: boolean, all: boolean, closed: (fold: Folding) => boolean) => Folding[];
    /** The folds Space `f` and a letter opens, or with Shift closes, from `position`; none where none's said. */
    kind?: (position: number, kind: FoldKind, closing: boolean, closed: (fold: Folding) => boolean) => Folding[];
}

/** One editor, as a view uses it. */
export interface Editor<D, C> {
    parent: RefObject<HTMLDivElement | null>;
    view: RefObject<EditorView | null>;
    /** Where the cursor is. */
    head: () => number;
    /** Where the cursor goes once the text is laid out again, read and cleared by the view. */
    landing: RefObject<Landing>;
    /** The folds the operator opened or closed, by key, whether each is folded: each laying out folds every other one as it's laid out. */
    kept: RefObject<Map<string, boolean>>;
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
    const kept = useRef(new Map<string, boolean>());
    const latest = useRef(config.draft);
    latest.current = config.draft;
    const telling = useRef(config.inserting);
    telling.current = config.inserting;
    const following = useRef(config.moved);
    following.current = config.moved;
    const chording = useRef(config.pending);
    chording.current = config.pending;
    // The draft's history, for `u`, Ctrl+R, `g-` and `g+`; and whether the comment being written has its step
    // already, so it's undone whole.
    const history = useRef<History<D>>(begun(config.draft));
    const writing = useRef(false);
    // Where the key that opened the comment being written was pressed.
    const opener = useRef<number | null>(null);
    // Whether insert mode is entered into the comment just opened, rather than by a key.
    const entering = useRef(false);
    // Where the cursor last was in each comment it left, for `]n` and `[n`, carried with the text's changes.
    const visited = useRef<number[]>([]);
    const keyed = bound.current.keyed;

    useEffect(() => {
        mapKeys();
        const host = parent.current;
        if (host === null) {
            return;
        }
        // What folds, for the margin and the placeholders: as this view last laid it out.
        const margined: Margined = {
            folds: (state) => boundOf(state).actions?.folds() ?? [],
            redrawn: (update) => update.transactions.some((each) => each.annotation(rebuilt) === true || each.effects.some((effect) => effect.is(drawn))),
        };
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
                    placeheld(margined),
                    config.margin === true ? margin(margined) : [],
                    drawing,
                    painting,
                    EditorView.updateListener.of((update) => {
                        const actions = bound.current.actions;
                        const replaced = update.transactions.some((each) => each.annotation(rebuilt) === true);
                        if (update.docChanged && !replaced) {
                            actions?.edited(update);
                        }
                        // A fold opened or closed by the operator, however it was, by its keys, a click, or the cursor
                        // going into it, is kept for the next laying out; an edit only moves the folds with the text,
                        // and the view folding again as it lays out isn't the operator's doing.
                        if (!update.docChanged && !replaced && foldedRanges(update.startState) !== foldedRanges(update.state)) {
                            actions?.folded(update);
                        }
                        const head = update.state.selection.main.head;
                        if (update.docChanged || update.selectionSet) {
                            following.current?.(head);
                        }
                        if (update.docChanged) {
                            visited.current = visited.current.map((at) => update.changes.mapPos(at));
                        } else if (update.selectionSet) {
                            const from = update.startState.selection.main.head;
                            visited.current = visit(visited.current, actions?.blocks() ?? [], from, head);
                        }
                        // A click out of the comment being written ends it, as Esc would.
                        const clicked = update.transactions.some((each) => each.isUserEvent("select.pointer"));
                        const cm = vimOf(update.view);
                        if (clicked && cm !== null && keyed.inserting && commentAt(bound.current, head) === undefined) {
                            queueMicrotask(() => Vim.exitInsertMode(cm, true));
                        }
                    }),
                    keys,
                    typed,
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
        history.current = begun(latest.current);
    }, [config.epoch]);

    function head(): number {
        return view.current?.state.selection.main.head ?? 0;
    }

    function blockAt(position: number): Block | undefined {
        return shown.blocks.find((each) => position >= each.from && position <= each.to);
    }

    /** Change the draft as one step `u` undoes: the comment being written, from its opening to its end, is one. */
    function record(next: D) {
        // What changed the draft since, by no step of its own, as an emptied comment dropped, is the state it was in.
        const now = rewritten(history.current, latest.current);
        history.current = writing.current ? rewritten(now, next) : stepped(now, next);
        writing.current = keyed.inserting;
        change(next);
    }

    function added(comment: C) {
        const next = withComments(latest.current, [...comments(latest.current), comment]);
        // Its place in the list the draft keeps, which may hold what's written in more lists than one.
        landing.current = { comment: comments(next).indexOf(comment) };
        opener.current = keyed.from;
        record(next);
        writing.current = true;
    }

    /** Fold or open each of `folds` not already so, the cursor going to the summary of one it was hidden in. */
    function foldEvery(folds: Folding[], closing: boolean) {
        const editor = view.current;
        if (editor === null) {
            return;
        }
        // In the text's order, a fold over others after them, as CodeMirror takes the folds a transaction makes; the
        // cursor going to the outermost one closing over it.
        const changing = folds
            .filter((each) => isFolded(editor.state, each) !== closing)
            .sort((a, b) => a.from - b.from || b.to - a.to);
        const at = head();
        const back = closing ? uncovered(changing, at) : at;
        editor.dispatch({
            effects: changing.map((each) => folding(each, closing)),
            selection: back === at ? undefined : { anchor: back },
            scrollIntoView: true,
        });
    }

    function bind(own: Own<C>) {
        bound.current.actions = {
            comment: (cm, on) => {
                const editor = view.current;
                if (editor === null) {
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
                // In the comment just opened, or one the key was pressed in, vim's own keys write. A key pressed
                // elsewhere opens one, though vim moved the cursor into the comment under the line, as `S` does.
                const opening = entering.current;
                entering.current = false;
                if (opening || blockAt(keyed.from) !== undefined) {
                    return;
                }
                const passage = keyed.visual || keyed.changing ? keyed.passage : null;
                // A passage no comment can quote, as `C` on an item's header, opens one on the line, as `o` does.
                const quoted = passage === null ? undefined : own.quoted(passage.from, passage.to);
                const comment = quoted ?? own.opened(keyed.from);
                if (comment === undefined) {
                    Vim.exitInsertMode(cm, true);
                    return;
                }
                added(comment);
            },
            left: () => {
                // What's written stays as written, as vim leaves it on Esc, the cursor where it is; an emptied comment
                // is dropped, as part of the step that wrote it, the cursor going back where the key that opened it
                // was pressed, or else to what it was about.
                const present = comments(latest.current);
                const kept = saying(present);
                const block = blockAt(head());
                const written = block === undefined ? undefined : present[block.comment];
                if (block !== undefined && written !== undefined && !kept.includes(written)) {
                    const back = opener.current ?? own.about(written, block, null);
                    landing.current = back === undefined ? null : { at: back };
                }
                writing.current = false;
                opener.current = null;
                if (kept.length !== present.length) {
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
                // Ended emptied, the comment is dropped as the text is laid out again, which lands back here too.
                if (landing.current !== null) {
                    landing.current = { at: back };
                }
                editor.dispatch({ selection: { anchor: back }, scrollIntoView: true });
            },
            toggle: (list) => own.toggle?.(list),
            move: own.move,
            matter: (forward) => own.matter?.(forward),
            written: (forward) => {
                const editor = view.current;
                const target = editor === null ? undefined : nextWritten(shown.blocks, head(), forward, visited.current);
                if (editor === null || target === undefined) {
                    return;
                }
                // Each fold it's in opens, as a motion into it would.
                const effects: StateEffect<Span>[] = [];
                foldedRanges(editor.state).between(target, target, (from, to) => {
                    if (target > from && target <= to) {
                        effects.push(unfoldEffect.of({ from, to }));
                    }
                });
                editor.dispatch({ selection: { anchor: target }, effects, scrollIntoView: true });
            },
            approve: (approved) => own.approve?.(approved),
            back: () => own.back?.(),
            tree: config.tree,
            list: config.list,
            fold: (how) => {
                const editor = view.current;
                const at = head();
                // Of folds one inside another, the innermost the cursor is in.
                const fold = around(shown.folds, at).at(-1);
                if (editor === null || fold === undefined) {
                    return;
                }
                const closed = isFolded(editor.state, fold);
                const closing = how === "toggle" ? !closed : how === "close";
                if (closing !== closed) {
                    // From what the fold hides, or past its placeholder, the cursor goes to its summary line.
                    const back = at > fold.from ? { anchor: fold.summary.from } : undefined;
                    editor.dispatch({ effects: folding(fold, closing), selection: back, scrollIntoView: true });
                }
            },
            foldLevel: (opening, all) => {
                const editor = view.current;
                if (editor === null) {
                    return;
                }
                const closed = (fold: Folding) => isFolded(editor.state, fold);
                const folds = own.level?.(head(), opening, all, closed) ?? levelled(shown.folds, closed, opening, all);
                foldEvery(folds, !opening);
            },
            foldKind: (kind, closing) => {
                const editor = view.current;
                if (editor === null) {
                    return;
                }
                foldEvery(own.kind?.(head(), kind, closing, (fold) => isFolded(editor.state, fold)) ?? [], closing);
            },
            foldMotion: (line, how, forward) => {
                const editor = view.current;
                if (editor === null) {
                    return undefined;
                }
                const closed = (fold: Folding) => isFolded(editor.state, fold);
                const startOf = (position: number) => editor.state.doc.lineAt(position).from;
                return how === "next"
                    ? nextFold(shown.folds, closed, line, forward, startOf)
                    : foldEdge(shown.folds, closed, line, !forward, startOf);
            },
            folded: (update) => {
                // The folds are where this layout puts them only while the text is still its own.
                if (update.state.sliceDoc() !== shown.text) {
                    return;
                }
                kept.current = keptFolds(shown.folds, update.startState, update.state, kept.current);
            },
            folds: () => shown.folds,
            chord: (keys) => chording.current?.(keys),
            undo: (way) => {
                const now = rewritten(history.current, latest.current);
                const gone = went(now, way);
                history.current = gone;
                if (gone.at !== now.at) {
                    change(gone.states[gone.at]?.draft ?? latest.current);
                }
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
        kept,
        latest,
        writing: () => keyed.inserting,
        record,
        draw: (decorations) => view.current?.dispatch({ effects: drawn.of(decorations) }),
        enter: () => {
            const editor = view.current;
            const cm = editor === null ? null : getCM(editor);
            if (cm !== null && !keyed.inserting) {
                entering.current = true;
                Vim.handleKey(cm, "i", "mapping");
            }
        },
        bind,
    };
}
