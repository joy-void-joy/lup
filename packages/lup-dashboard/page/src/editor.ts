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
// previous line that matters, where a view has some, `]f` and `[f` to the next
// and previous file's header, `]n` and `[n` to the next and previous comment,
// where the cursor last was in it. A motion repeated by a key held down, or a
// page scroll, Ctrl+D, U, F or B, stops on the next file's header it reaches,
// held there until the key is pressed afresh (`stopAt`). Ctrl+Enter in a comment ends
// it, back on what it's about; elsewhere it sends. `u` and Ctrl+R undo and redo
// any change to the draft, `g-` and `g+` go through its history in the order it
// was made (`History`). Each fold is folded or open as the view lays it out
// until the operator opens or closes it, which is kept by its key: `za` opens or
// closes the fold the cursor is in, `zo` and `zc` open and close it; `zr` and
// `zm` open or close a level more, `zR` and `zM` all of them, and Space `z` `f`
// and a letter those of a kind, Space `z` `F` closing them, within what the view
// says (in the review, the item the cursor is in; in a conversation,
// everything); `zf` and a kind's letter closes the one of that kind the cursor
// is in; `zj` and `zk` go to the next fold's start and the previous one's end,
// `[z` and `]z` to the start and the end of the open fold the cursor is in
// (`folds.ts`). A closed fold counts as its summary line: no motion opens it,
// the cursor passing over it (`outOfFolds`); a search, and a jump to what it
// hides, as `]n`, opens the folds around where it goes, saying so under the view
// (`reached`). `?` opens the list of every key, in place of vim's search
// backward; once a chord is begun, as with Space or `zf`, the view is told what's
// pressed, to show what may follow. `"+` and `"*` are the system clipboard, and a
// yank or a put the clipboard refused is said in the page's top line
// (`clipboard.ts`). What's written, an agent's text and a comment, is
// Markdown, shown as such, Enter in a comment continuing the list it's in, and
// `o` and `O` on one of its items opening the next item or the one before it
// (`markdown.ts`); each view says which stretches of its text those are, in the
// transaction that lays the text out. Each view says what else its keys do, lays
// its own text out and draws it, and may paint the lines in view as well, as the
// review paints a changed file's, and draw its folds' marks and bars in the
// margin (`margin.ts`; `Review.tsx`, `Conversation.tsx`; `docs/dashboard.md`).
// A fold may be inside another, as an item's text is inside what came before the
// operator's last words: the fold keys act on the innermost the cursor is in.
import { foldEffect, foldedRanges, syntaxTree, unfoldEffect } from "@codemirror/language";
import { Annotation, EditorSelection, EditorState, Facet, Prec, StateEffect, StateField, type Range } from "@codemirror/state";
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

import { defineClipboard, shownBelow } from "./clipboard";
import { saying, type Block, type Folding, type Span } from "./comments";
import { around, aroundOf, foldEdge, levelled, nextFold } from "./folds";
import { FOLD_KINDS, type FoldKind } from "./keys";
import { continued, hiddenOn, markdown, openedLine } from "./markdown";
import { margin, placeheld, type Margined } from "./margin";

/** What the vim keys and the editor's own events do, as a view stands: replaced at each render. */
interface Actions {
    /** Open a comment on the line or the whole, or, in a comment, a line below it to write on (`line`) or above it (`above`). */
    comment: (cm: CodeMirrorV, on: "line" | "above" | "whole") => void;
    entered: (cm: CodeMirrorV) => void;
    left: () => void;
    finish: (cm: CodeMirrorV) => void;
    toggle: (list: "done" | "parked") => void;
    move: (forward: boolean) => void;
    answer: (forward: boolean) => void;
    matter: (forward: boolean) => void;
    /** `]f` and `[f`: the next or previous file's header. */
    file: (forward: boolean) => void;
    /** The start of each file's header line, in the text's order: where a key held down, or a page scroll, stops. */
    stops: () => readonly number[];
    written: (forward: boolean) => void;
    /** `]q` and `[q`: the next or previous citation of the operator's words. */
    cite: (forward: boolean) => void;
    /** `gd`: follow a citation to the passage it cites, or a passage cited back to its citation. */
    follow: () => void;
    approve: (approved: boolean) => void;
    /** Space `A`: mark every file of a "since you approved" drawer reviewed. */
    approveAll: () => void;
    /** `h` on a banner: turn the operator's switch to hold the agent's flagged writes; elsewhere it's vim's `h`, said by false. */
    hold: () => boolean;
    list: () => void;
    fold: (how: "toggle" | "open" | "close") => void;
    foldLevel: (opening: boolean, all: boolean) => void;
    foldKind: (kind: FoldKind, closing: boolean) => void;
    /** `zf` and a kind's letter: close the fold of that kind the cursor is in, the cursor going to its summary line. */
    foldAround: (kind: FoldKind) => void;
    /** Where `zj` and `zk` (`next`), or `[z` and `]z` (`edge`), go from the line starting at `line`. */
    foldMotion: (line: number, how: "next" | "edge", forward: boolean) => number | undefined;
    folded: (update: ViewUpdate) => void;
    folds: () => readonly Folding[];
    undo: (way: "undo" | "redo" | "earlier" | "later") => void;
    send: () => void;
    blocks: () => Block[];
    chord: (keys: string) => void;
    say: (text: string) => void;
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
    /** Whether it begins or makes a search, `/`, `n`, `N`, `*` or `#`, whose match opens the folds around it, where the cursor goes next. */
    searching: boolean;
    /** Whether it's a key held down, repeated by the browser (`KeyboardEvent.repeat`), whose motion stops at a file. */
    repeat: boolean;
    /** Whether it scrolls a page or half of one, Ctrl+D, U, F or B, whose motion stops at a file, pressed afresh or held. */
    paging: boolean;
    /** Whether a key held down stopped on a file's header, where it stays until a key is pressed afresh. */
    stopped: boolean;
    /** Where a dead key pressed outside insert mode is. */
    dead: Dead;
}

/**
 * Where a dead key pressed outside insert mode is (`at`): none; pressed, waiting for the key that completes it;
 * completing, that key pressed, what the browser types next being what the two make; giving, vim given text typed of
 * it, more of which may follow from the same key, as `"` then `+` typing `"+` in two; or given, vim given what a
 * composition ended with, so the same text typed after it is dropped. And what a composition showed of it while it
 * waited (`shown`), as `¨` for `"` on Linux.
 */
export interface Dead {
    at: "none" | "pressed" | "completing" | "giving" | "given";
    shown: string;
}

/** No dead key pressed. */
export const UNPRESSED: Dead = { at: "none", shown: "" };

/**
 * A key pressed outside insert mode, as a dead key reads it: its name; whether the browser composes it; and whether it
 * types a character, as a letter, a sign or Space do and Escape, an arrow, or a key held with Ctrl don't.
 */
export interface Pressed {
    key: string;
    composing: boolean;
    printable: boolean;
}

/** Where a key pressed outside insert mode goes: to vim; nowhere, neither vim nor the browser; or to the browser alone, to type what it composes. */
export type Goes = "vim" | "nowhere" | "browser";

/** The keys that only modify another, which a dead key waits through, as Shift for the `+` after `"`. */
const MODIFIERS = new Set(["Shift", "Control", "Alt", "AltGraph", "Meta", "CapsLock", "Fn", "OS", "Super", "Hyper"]);

/** The signs Linux shows for a dead key while it waits that aren't the character it types on its own: `¨` for `"`, `´` for `'`. */
const SIGNS = new Map([
    ["¨", '"'],
    ["´", "'"],
]);

/** Return the character a dead key types on its own, from what a composition showed of it. */
export function ownOf(shown: string): string {
    return [...shown].map((each) => SIGNS.get(each) ?? each).join("");
}

/**
 * Return where a key pressed outside insert mode goes, where a dead key is after it, and what vim is given first. The
 * dead key itself goes nowhere, as does a key the browser composes with it: vim gets what they type once they're done
 * (`deadTyped`), never the keys, the Space completing `"` among them, which would begin a chord. The key after a dead
 * key that the browser doesn't compose goes to the browser alone, so it types what the two make (`"` then Space a
 * `"`), as where a dead key starts no composition. Where one did, and the browser dropped it with nothing typed, as
 * once the page has taken what it showed, vim is given the dead key's own character, then the key, but for a Space,
 * which only completed it. A key that only modifies another changes nothing; any other goes to vim, ending the dead key.
 */
export function deadPressed(dead: Dead, pressed: Pressed): { goes: Goes; dead: Dead; given: string } {
    if (pressed.key === "Dead") {
        return { goes: "nowhere", dead: { at: "pressed", shown: "" }, given: "" };
    }
    if (pressed.composing || pressed.key === "Process") {
        return { goes: "nowhere", dead: dead.at === "pressed" ? { ...dead, at: "completing" } : dead, given: "" };
    }
    if (MODIFIERS.has(pressed.key)) {
        return { goes: "vim", dead, given: "" };
    }
    if (dead.at === "pressed" && pressed.printable) {
        if (dead.shown === "") {
            return { goes: "browser", dead: { at: "completing", shown: "" }, given: "" };
        }
        return { goes: pressed.key === " " ? "nowhere" : "vim", dead: UNPRESSED, given: ownOf(dead.shown) };
    }
    return { goes: "vim", dead: UNPRESSED, given: "" };
}

/**
 * How the browser types text into the page: as part of a composition still going on, what a dead key shows while it
 * waits among it (`¨` for `"`, on Linux); typed; or as what a composition ends with.
 */
export type Typing = "composing" | "typed" | "ended";

/**
 * Return what `text`, typed into the page outside insert mode, does, which never lands there: whether vim gets it as
 * keys, and where the dead key is after it. Vim gets what a dead key types once it's completed, all of it, as `"+` for
 * `"` then `+` on a layout that types both, and once: from the composition's end, or typed, but not both. What's shown
 * while it's composed is kept for where nothing's typed (`deadPressed`), never given; anything else typed is dropped,
 * as a paste.
 */
export function deadTyped(dead: Dead, typing: Typing, text: string): { given: boolean; dead: Dead } {
    const waiting = dead.at === "pressed" || dead.at === "completing";
    if (typing === "composing") {
        return { given: false, dead: dead.at === "pressed" ? { ...dead, shown: text } : dead };
    }
    if (typing === "ended") {
        return waiting ? { given: true, dead: { at: "given", shown: "" } } : { given: false, dead };
    }
    return waiting || dead.at === "giving" ? { given: true, dead: { at: "giving", shown: "" } } : { given: false, dead };
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

const NONE: Keyed = {
    from: 0,
    visual: false,
    passage: null,
    changing: false,
    inserting: false,
    searching: false,
    repeat: false,
    paging: false,
    stopped: false,
    dead: UNPRESSED,
};

function boundOf(state: EditorState): Bound {
    return state.facet(binding) ?? { actions: null, keyed: NONE };
}

/** The editor a key was last pressed in, which says what the clipboard couldn't do on a yank or a put the key made. */
let speaking: Bound | null = null;

/**
 * Each chord Space leads in the review, as vim's keymap writes its keys, and the action it does: Space `p` parks an
 * item, leaving it for later; Space `A` marks every file of a "since you approved" drawer reviewed; Space `z` `f` and a
 * letter, as vim's fold keys begin with `z`, opens every fold of its kind in the item or the drawer, Space `z` `F` and
 * the letter closing them. The list of keys (`keys.ts`) says each of them.
 */
export const SPACED: readonly (readonly [keys: string, action: string])[] = [
    ["<Space>c", "lupCommentWhole"],
    ["<Space>d", "lupDone"],
    ["<Space>p", "lupLater"],
    ["<Space>a", "lupApprove"],
    ["<Space>x", "lupDecline"],
    ["<Space>A", "lupApproveAll"],
    ...FOLD_KINDS.filter((each) => each.chord).flatMap(({ kind, letter }) => [
        [`<Space>zf${letter}`, `lupFoldOpen-${kind}`] as const,
        [`<Space>zF${letter}`, `lupFoldClose-${kind}`] as const,
    ]),
];

/**
 * `zf` and each kind's letter, as vim's keymap writes them, and the action closing the fold of that kind the cursor is
 * in: vim's `zf` makes a fold, which nothing here needs, the folds being laid out.
 */
export const AROUND: readonly (readonly [keys: string, action: string])[] = FOLD_KINDS.map(
    ({ kind, letter }) => [`zf${letter}`, `lupFoldAround-${kind}`] as const,
);

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
    // The system clipboard as `+` and `*`, where the browser gives the page one: a secure one, as on localhost.
    defineClipboard({
        clipboard: () => (window.isSecureContext && "clipboard" in navigator ? navigator.clipboard : null),
        tell: (text) => speaking?.actions?.say(text),
    });
    const action = (name: string, fn: (actions: Actions, cm: CodeMirrorV) => void) =>
        Vim.defineAction(name, (cm) => {
            const actions = boundOf(cm.cm6.state).actions;
            if (actions !== null) {
                fn(actions, cm);
            }
        });
    action("lupCommentLine", (actions, cm) => actions.comment(cm, "line"));
    action("lupCommentAbove", (actions, cm) => actions.comment(cm, "above"));
    action("lupCommentWhole", (actions, cm) => actions.comment(cm, "whole"));
    action("lupDone", (actions) => actions.toggle("done"));
    action("lupLater", (actions) => actions.toggle("parked"));
    action("lupNext", (actions) => actions.move(true));
    action("lupPrevious", (actions) => actions.move(false));
    action("lupNextAnswer", (actions) => actions.answer(true));
    action("lupPreviousAnswer", (actions) => actions.answer(false));
    action("lupNextMatter", (actions) => actions.matter(true));
    action("lupPreviousMatter", (actions) => actions.matter(false));
    action("lupNextFile", (actions) => actions.file(true));
    action("lupPreviousFile", (actions) => actions.file(false));
    action("lupNextWritten", (actions) => actions.written(true));
    action("lupPreviousWritten", (actions) => actions.written(false));
    action("lupNextCitation", (actions) => actions.cite(true));
    action("lupPreviousCitation", (actions) => actions.cite(false));
    action("lupFollow", (actions) => actions.follow());
    action("lupApprove", (actions) => actions.approve(true));
    action("lupDecline", (actions) => actions.approve(false));
    action("lupApproveAll", (actions) => actions.approveAll());
    // `h` holds an agent's flagged writes on its banner, and moves left, as vim's `h` does, anywhere else.
    action("lupHold", (actions, cm) => {
        if (!actions.hold()) {
            Vim.handleKey(cm, "<Left>", "mapping");
        }
    });
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
        action(`lupFoldAround-${kind}`, (actions) => actions.foldAround(kind));
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
    map("O", "lupCommentAbove", "normal");
    map("h", "lupHold", "normal");
    for (const [keys, name] of SPACED) {
        map(keys, name, "normal");
    }
    // The list of every key, in place of vim's search backward, which `/` then `N` still does.
    map("?", "lupKeys", "normal");
    map("za", "lupFoldToggle", "normal");
    map("zo", "lupFoldOpen", "normal");
    map("zc", "lupFoldClose", "normal");
    map("zR", "lupFoldOpenAll", "normal");
    map("zM", "lupFoldCloseAll", "normal");
    map("zr", "lupFoldOpenLevel", "normal");
    map("zm", "lupFoldCloseLevel", "normal");
    for (const [keys, name] of AROUND) {
        map(keys, name, "normal");
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
    map("]a", "lupNextAnswer", "normal");
    map("[a", "lupPreviousAnswer", "normal");
    map("]c", "lupNextMatter", "normal");
    map("[c", "lupPreviousMatter", "normal");
    map("]f", "lupNextFile", "normal");
    map("[f", "lupPreviousFile", "normal");
    map("]n", "lupNextWritten", "normal");
    map("[n", "lupPreviousWritten", "normal");
    map("]q", "lupNextCitation", "normal");
    map("[q", "lupPreviousCitation", "normal");
    map("gd", "lupFollow", "normal");
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
 * A dead key, as `` ` `` or `"` on a layout where it waits for the next key, gives no key of its own: the browser
 * composes it with the next, `"` then Space making a `"`, `"` then `+` making `"+` on a layout that types both. Outside
 * insert mode, vim gets what they make once the second is pressed (`typed`), and neither key, the Space among them,
 * which would begin a chord. Each key is read here as it goes down, ahead of CodeMirror and vim (`deadPressed`): the
 * dead key, and a key the browser composes with it, go nowhere; the key after one that the browser doesn't compose, as
 * where a dead key starts no composition, goes to the browser alone, which types what the two make; where a
 * composition showed the dead key and the browser dropped it, vim is given the dead key's own character first. In a
 * comment, the browser composes into the text as usual.
 */
const deadKeys = ViewPlugin.fromClass(
    class {
        constructor(readonly view: EditorView) {
            view.dom.addEventListener("keydown", this.pressed, { capture: true });
        }

        readonly pressed = (event: KeyboardEvent) => {
            const cm = vimOf(this.view);
            if (cm === null || cm.state.vim.insertMode || event.target !== this.view.contentDOM) {
                return;
            }
            const { keyed } = boundOf(this.view.state);
            const printable = [...event.key].length === 1 && !event.ctrlKey && !event.metaKey;
            const step = deadPressed(keyed.dead, { key: event.key, composing: event.isComposing, printable });
            keyed.dead = step.dead;
            if (step.given !== "") {
                give(cm, step.given);
            }
            if (step.goes === "nowhere") {
                // CodeMirror runs no handler of a key whose default is prevented, vim's among them.
                event.preventDefault();
            } else if (step.goes === "browser") {
                event.stopPropagation();
            }
        };

        destroy() {
            this.view.dom.removeEventListener("keydown", this.pressed, { capture: true });
        }
    },
);

/**
 * The keys that vim's keymap can't say, read ahead of vim, which takes every key it's given before a keymap would:
 * Ctrl+Enter, which ends a comment in insert mode and sends elsewhere; Enter in insert mode, which continues the list
 * the cursor is in, where it's in one (`continued`), and is vim's otherwise. Every key is noted first, for what vim
 * makes of it (`Keyed`): one with no key of vim's pending begins what it notes, `c` or `C` in normal mode beginning
 * vim's change. A composition outside insert mode is a dead key's, as some browsers give one with no dead key pressed
 * first, and what it ends with is what vim gets of it, where nothing it typed was given first (`deadTyped`).
 */
const keys = Prec.highest(
    EditorView.domEventHandlers({
        compositionstart: (_, view) => {
            const cm = vimOf(view);
            if (cm !== null && !cm.state.vim.insertMode) {
                boundOf(view.state).keyed.dead = { at: "pressed", shown: "" };
            }
            return false;
        },
        compositionend: (event, view) => {
            const cm = vimOf(view);
            const { keyed } = boundOf(view.state);
            if (cm === null || cm.state.vim.insertMode || !(event instanceof CompositionEvent) || event.data === "") {
                return false;
            }
            const step = deadTyped(keyed.dead, "ended", event.data);
            keyed.dead = step.dead;
            if (step.given) {
                give(cm, event.data);
            }
            return false;
        },
        keyup: (_, view) => {
            const { keyed } = boundOf(view.state);
            keyed.repeat = false;
            keyed.paging = false;
            return false;
        },
        keydown: (event, view) => {
            const cm = vimOf(view);
            if (cm === null) {
                return false;
            }
            const bound = boundOf(view.state);
            speaking = bound;
            // Once vim has the key: the chord begun, if any, for the view to show what may follow.
            queueMicrotask(() => bound.actions?.chord(chordOf(cm)));
            const { keyed } = bound;
            const head = view.state.selection.main.head;
            keyed.from = head;
            keyed.visual = cm.state.vim.visualMode;
            keyed.passage = null;
            const modified = event.ctrlKey || event.metaKey || event.altKey;
            if (idle(cm)) {
                keyed.changing = (event.key === "c" || event.key === "C") && !modified && !keyed.visual;
            }
            // A key pressed afresh goes on from a file a key held down stopped on.
            keyed.repeat = event.repeat;
            keyed.paging = event.ctrlKey && !event.altKey && !event.metaKey && PAGES.includes(event.key);
            if (!event.repeat) {
                keyed.stopped = false;
            }
            // A key typed in the search's prompt is the query's: the search stays begun until it's made.
            if (event.target === view.contentDOM) {
                keyed.searching = !modified && searches(cm, event.key);
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
            if (event.key === "Enter" && !modified && !event.isComposing && cm.state.vim.insertMode && continued(view)) {
                event.preventDefault();
                return true;
            }
            return false;
        },
    }),
);

/**
 * Return the keys of a chord begun with Space, or of `zf` waiting for a kind's letter, as the list of keys writes them
 * (`␣`, `␣z`, `zf`): what vim holds of a mapping typed but not done, in normal mode; none for any other, as `z` alone,
 * which begins vim's own keys too.
 */
export function chordOf(cm: CodeMirrorV): string {
    const vim = cm.state.vim;
    const held = vim.insertMode || vim.visualMode ? [] : vim.inputState.keyBuffer;
    if (held.join("") === "zf") {
        return "zf";
    }
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
 * type it, so what's typed is a dead key's, or a paste. What a dead key types once completed reaches vim as keys
 * (`deadTyped`); what it shows while it's composed doesn't, as `¨` for `"` on Linux, and that composition ends there,
 * as CodeMirror is told, so it doesn't wait for one whose text the page took. Read here, ahead of vim's own reading of
 * typed text, which takes a composition's text as keys each time it's typed, so a mark or a jump never types into a
 * comment the cursor is on, nor reaches vim twice.
 */
const typed = Prec.highest(
    EditorView.inputHandler.of((view, _from, _to, text) => {
        const cm = vimOf(view);
        if (cm === null || cm.state.vim.insertMode) {
            return false;
        }
        const { keyed } = boundOf(view.state);
        const composing = view.compositionStarted;
        const step = deadTyped(keyed.dead, composing ? "composing" : "typed", text);
        keyed.dead = step.dead;
        if (step.given) {
            give(cm, text);
        }
        if (composing) {
            view.contentDOM.dispatchEvent(new CompositionEvent("compositionend"));
        }
        return true;
    }),
);

/** The keys that search: vim's `/`, `n`, `N`, `*` and `#`, and `g*` and `g#`; `?` lists the keys instead. */
const SEARCHES = new Set(["/", "n", "N", "*", "#"]);

/** Return whether `key`, pressed outside insert mode, begins or makes a search, rather than finishing another command, as `fn` does. */
function searches(cm: CodeMirrorV, key: string): boolean {
    const held = cm.state.vim.inputState.keyBuffer;
    return !cm.state.vim.insertMode && SEARCHES.has(key) && (held.length === 0 || (held.join("") === "g" && (key === "*" || key === "#")));
}

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

/**
 * Return where vim's cursor rests once `state`'s selection is made, where it was put on a mark the Markdown hides
 * (`hiddenOn`), which has no width to show it on: on the next character shown the way it came from `was`, as if the
 * mark weren't there, or back where going on would leave the line, since outside `visual` mode a block cursor rests
 * on a character and never on the line's end. In visual mode the cursor is the character before the head where the
 * selection runs forward, as vim draws it, and the anchor stays. None where the cursor rests on a character shown
 * already, or the line has none to rest on.
 */
export function pastHidden(state: EditorState, was: number, visual: boolean): EditorSelection | null {
    const { main } = state.selection;
    const ahead = main.anchor < main.head;
    const at = ahead ? main.head - 1 : main.head;
    const hidden = hiddenOn(state, at);
    if (!hidden.some((each) => at >= each.from && at < each.to)) {
        return null;
    }
    const line = state.doc.lineAt(at);
    const last = visual && line.to < state.doc.length ? line.to : line.to - 1;
    // The first character shown from `at` on, or back from it; none before the line's edge.
    const shown = (step: 1 | -1): number | null => {
        let position = at;
        let within = hidden.find((each) => position >= each.from && position < each.to);
        while (within !== undefined) {
            position = step > 0 ? within.to : within.from - 1;
            within = hidden.find((each) => position >= each.from && position < each.to);
        }
        return position < line.from || position > last ? null : position;
    };
    const forward = main.head >= was;
    const rest = shown(forward ? 1 : -1) ?? shown(forward ? -1 : 1);
    if (rest === null) {
        return null;
    }
    if (main.empty) {
        return EditorSelection.single(rest);
    }
    return EditorSelection.single(main.anchor, ahead ? rest + 1 : rest);
}

/** Return where vim's cursor rests in `view` past the hidden marks (`pastHidden`), from `was`, as vim stands; none where it rests already, or in insert, visual line or visual block mode. */
function restingIn(view: EditorView, was: number): EditorSelection | null {
    const mode = vimOf(view)?.state.vim;
    if (mode === undefined || mode.insertMode || mode.visualLine || mode.visualBlock) {
        return null;
    }
    return pastHidden(view.state, was, mode.visualMode);
}

/**
 * Keep vim's cursor off the marks the Markdown hides: put on one, by a motion, a jump, a click, the text laid out anew
 * or read further, it's moved past it once vim's key is done (`restingIn`), as a selection vim didn't make, so vim
 * takes the cursor from the editor, as it does after a click. Vim's key may dispatch again after the selection, to
 * scroll, so where it rests is read again as it's moved. Not in insert mode, where the cursor's line shows its marks
 * and a thin cursor rests between characters, nor in visual line or block mode, whose selection vim keeps by lines or
 * columns.
 */
const offHidden = EditorView.updateListener.of((update) => {
    const reread = syntaxTree(update.startState) !== syntaxTree(update.state);
    if (!update.selectionSet && !update.docChanged && !reread) {
        return;
    }
    const was = update.startState.selection.main.head;
    if (restingIn(update.view, was) === null) {
        return;
    }
    const { view } = update;
    queueMicrotask(() => {
        const moved = restingIn(view, was);
        if (moved !== null) {
            view.dispatch({ selection: moved });
        }
    });
});

/**
 * Marks a transaction that opened folds to reach where it puts the cursor, a search's match or a jump's line, by how
 * many: the editor says so under the view.
 */
export const reached = Annotation.define<number>();

/** Marks a selection a plain motion put in what a closed fold hides, moved past it (`pastFolds`). */
const passed = Annotation.define<boolean>();

/** Return the effects that open each fold folded in `state` around `target`, the lines it hides holding it or ending at it: what a search or a jump opens to reach it. */
export function reaching(state: EditorState, target: number): StateEffect<Span>[] {
    const effects: StateEffect<Span>[] = [];
    foldedRanges(state).between(target, target, (from, to) => {
        if (target > from && target <= to) {
            effects.push(unfoldEffect.of({ from, to }));
        }
    });
    return effects;
}

/** Say how many folds a search or a jump opened to reach where it went. */
export function openedSaid(count: number): string {
    return count === 1 ? "opened a fold to reach it" : `opened ${count} folds to reach it`;
}

/**
 * Return where a plain motion's cursor rests where it was put in what a closed fold hides, coming from `was`, as if
 * the fold were the summary line it shows as: past it the way it went, on the start of the line after it, where it
 * went on past the summary line's end; back on the summary line's last character where it came back into it, or where
 * no line follows the fold. Of folds one inside another, past the outermost folded. Where the selection is a visual
 * one, the anchor stays, and where it runs forward the head is past the character the cursor is on, as vim draws it.
 * None where the head isn't in what a closed fold hides, where CodeMirror would open it.
 */
export function pastFolds(state: EditorState, selection: EditorSelection, was: number): EditorSelection | null {
    const { main } = selection;
    const holding: Span[] = [];
    foldedRanges(state).between(main.head, main.head, (from, to) => {
        if (from < main.head && main.head < to) {
            holding.push({ from, to });
        }
    });
    const fold = holding.sort((a, b) => a.from - b.from || b.to - a.to)[0];
    if (fold === undefined) {
        return null;
    }
    // The character the cursor is on: before the head where a visual selection runs forward.
    const at = main.anchor < main.head ? main.head - 1 : main.head;
    const forward = main.head > was && at > fold.from && fold.to < state.doc.length;
    const rest = forward ? fold.to + 1 : Math.max(fold.from - 1, state.doc.lineAt(fold.from).from);
    if (main.empty) {
        return EditorSelection.single(rest);
    }
    return EditorSelection.single(main.anchor, main.anchor <= rest ? Math.min(rest + 1, state.doc.length) : rest);
}

/**
 * Keep the cursor out of what a closed fold hides, where CodeMirror would open the fold: a plain motion put there, as
 * `w` past a folded file's header, `b` back into one or `G` into a folded drawer, rests past the fold instead
 * (`pastFolds`), so a fold opens by the fold keys, a click, a search or a jump alone. A search, `/`, `n`, `N`, `*` or
 * `#`, opens the folds around its match, said under the view (`reached`); a jump opens what it reaches itself. Not in
 * insert mode, where the cursor stays in the comment being written, nor where a view lays its text out, or a click.
 */
const outOfFolds = EditorState.transactionFilter.of((transaction) => {
    const moved = transaction.selection;
    if (
        moved === undefined ||
        transaction.docChanged ||
        transaction.annotation(rebuilt) === true ||
        transaction.annotation(reached) !== undefined ||
        transaction.isUserEvent("select.pointer")
    ) {
        return transaction;
    }
    const { keyed } = boundOf(transaction.startState);
    if (keyed.inserting) {
        return transaction;
    }
    const before = transaction.startState;
    if (keyed.searching) {
        const opening = reaching(before, moved.main.head);
        return opening.length === 0 ? transaction : [transaction, { effects: opening, annotations: reached.of(opening.length) }];
    }
    const was = before.selection.main.head;
    const past = pastFolds(before, moved, was);
    const landed = past ?? moved;
    const stop = keyed.repeat || keyed.paging ? stopping(before, landed, was, keyed) : null;
    if (stop !== null) {
        return [transaction, { selection: EditorSelection.single(stop) }];
    }
    return past === null ? transaction : [transaction, { selection: past, annotations: passed.of(true) }];
});

/** The keys that, with Ctrl, scroll half a page or a page, in vim: `^d` and `^u`, `^f` and `^b`. */
const PAGES = ["d", "u", "f", "b"];

/**
 * Return where a key held down, or a page scroll, leaves the cursor, its motion putting the selection at `landed` from
 * `was` (`keyed`): where a key held down stopped on a file's header, there, until a key is pressed afresh; else on the
 * first file's header the motion reaches or goes through (`stopAt`), held there; none where it goes on, or the
 * selection is a visual one, which runs past files as vim makes it.
 */
function stopping(state: EditorState, landed: EditorSelection, was: number, keyed: Keyed): number | null {
    const { head } = landed.main;
    if (!landed.main.empty || head === was) {
        return null;
    }
    if (keyed.repeat && keyed.stopped) {
        return was;
    }
    const at = stopAt(state, boundOf(state).actions?.stops() ?? [], was, head);
    if (at === undefined) {
        return null;
    }
    keyed.stopped = true;
    // Landed on the header's line, it stays where on it the motion put it.
    return state.doc.lineAt(head).from === at ? head : at;
}

/**
 * Return the file's header a motion from `was` to `head` stops on, of `stops`, the start of each header's line, in the
 * text's order: going forward, the first after the line it left, up to where it lands; going back, the last before
 * that line, down to the line it lands on, the file it was in among them, so it stops at the top of that file; a header
 * a closed fold hides passed over, the fold counting as its summary line. None where it reaches none.
 */
export function stopAt(state: EditorState, stops: readonly number[], was: number, head: number): number | undefined {
    const from = state.doc.lineAt(was).from;
    const shown = (at: number) => !hiddenAt(state, at);
    if (head > was) {
        return stops.find((each) => each > from && each <= head && shown(each));
    }
    const to = state.doc.lineAt(head).from;
    return stops.findLast((each) => each < from && each >= to && shown(each));
}

/** Return whether a closed fold hides `position`, the start of a line: it's among the lines the fold hides. */
export function hiddenAt(state: EditorState, position: number): boolean {
    let hidden = false;
    foldedRanges(state).between(position, position, (from, to) => {
        hidden ||= from < position && position <= to;
    });
    return hidden;
}

/**
 * Say under the view how many folds a search or a jump opened to reach where it went (`reached`); and, where a plain
 * motion's visual selection was moved past a fold (`pastFolds`), give it to vim as a selection it didn't make, once its
 * key is done, so vim's own selection goes on from there.
 */
const foldsTold = EditorView.updateListener.of((update) => {
    const opened = update.transactions.reduce((sum, each) => sum + (each.annotation(reached) ?? 0), 0);
    const cm = vimOf(update.view);
    if (opened > 0 && cm !== null) {
        queueMicrotask(() => shownBelow(cm, openedSaid(opened)));
    }
    const moved = update.transactions.some((each) => each.annotation(passed) === true);
    if (moved && !update.state.selection.main.empty) {
        const { view } = update;
        queueMicrotask(() => view.dispatch({ selection: view.state.selection }));
    }
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
    // What's folded, by where each range starts: each fold finds its own range there, rather than walking every
    // range inside it, and a range no fold starts is found once, with thousands of folds laid out.
    const folded = new Map<number, number[]>();
    foldedRanges(view.state).between(0, view.state.doc.length, (from, to) => {
        folded.set(from, [...(folded.get(from) ?? []), to]);
    });
    const starts = new Set(folds.map((each) => each.from));
    for (const fold of folds) {
        const ends = folded.get(fold.from) ?? [];
        const exact = ends.includes(fold.to);
        for (const to of ends) {
            if (to !== fold.to) {
                effects.push(unfoldEffect.of({ from: fold.from, to }));
            }
        }
        const closing = closedAs(fold, kept);
        if (closing && !exact) {
            effects.push(foldEffect.of({ from: fold.from, to: fold.to }));
        }
        if (!closing && exact) {
            effects.push(unfoldEffect.of({ from: fold.from, to: fold.to }));
        }
    }
    // A range folded where nothing folds any more, as an item's text once it's no longer marked read, opens.
    for (const [from, ends] of folded) {
        if (!starts.has(from)) {
            for (const to of ends) {
                effects.push(unfoldEffect.of({ from, to }));
            }
        }
    }
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
    /** Open the list of every key (`?`). */
    list: () => void;
    /** Told the keys of a chord begun, as the list writes them (`␣`, `␣z`), each time they change: none once it's done. */
    pending?: (keys: string) => void;
    /** Told each fold the operator opens, by its keys or a click, as a view reads what a drawer shows on opening it. */
    unfolded?: (fold: Folding) => void;
    /** Whether the margin shows each fold's mark and the bars of those the cursor is in (`margin.ts`). */
    margin?: boolean;
    /** Say something in the page's top line, as why a yank didn't reach the clipboard. */
    say?: (text: string) => void;
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
    /** Go to the next or previous item to answer, as the review's `]a` and `[a` do; none where the view has none. */
    answer?: (forward: boolean) => void;
    send: () => void;
    toggle?: (list: "done" | "parked") => void;
    /** Go to the next or previous line that matters, as the review's are by the judge's reading, opening what folds it on the way. */
    matter?: (forward: boolean) => void;
    /** Go to the next or previous file's header, as the review's `]f` and `[f` do; none where the view has none. */
    file?: (forward: boolean) => void;
    /** The start of each file's header line, in the text's order, where a key held down or a page scroll stops (`stopAt`); none where the view has none. */
    stops?: () => readonly number[];
    /** Go to the next or previous citation of the operator's words, as the review's `]q` and `[q` do; none where the view has none. */
    cite?: (forward: boolean) => void;
    /** Follow a citation to what it cites, or back, as the review's `gd` does; none where the view has none. */
    follow?: () => void;
    approve?: (approved: boolean) => void;
    /** Mark every file of the "since you approved" drawer the cursor is in reviewed, as Space `A` does; none where the view has none. */
    approveAll?: () => void;
    /** Turn the operator's switch for the agent whose banner the cursor is on, and say whether it was on one. */
    hold?: () => boolean;
    /** What's painted on the lines from `from` to `to` while they're in view, beyond what `draw` drew: a changed file's lines and their highlighting. */
    paint?: (from: number, to: number) => Range<Decoration>[];
    /** The folds `zr` opens (`opening`) or `zm` closes from `position`, or with `all` `zR` and `zM`; where none's said, those of every fold (`levelled`). */
    level?: (position: number, opening: boolean, all: boolean, closed: (fold: Folding) => boolean) => Folding[];
    /** The folds Space `z` `f` and a letter opens, or Space `z` `F` and the letter closes, from `position`; none where none's said. */
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
    const unfolding = useRef(config.unfolded);
    unfolding.current = config.unfolded;
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
                    outOfFolds,
                    foldsTold,
                    offHidden,
                    EditorView.lineWrapping,
                    placeheld(margined),
                    config.margin === true ? margin(margined) : [],
                    drawing,
                    painting,
                    markdown(),
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
                    deadKeys,
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
                // In a comment, a line below or above to write on, a list's next item or the one before it.
                if (on !== "whole" && blockAt(head()) !== undefined) {
                    editor.dispatch(openedLine(editor.state, head(), on === "line"));
                    // The line opened and what's written on it are one step, as a comment opened is.
                    writing.current = true;
                    Vim.handleKey(cm, "A", "mapping");
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
            answer: (forward) => own.answer?.(forward),
            matter: (forward) => own.matter?.(forward),
            file: (forward) => own.file?.(forward),
            stops: () => own.stops?.() ?? [],
            cite: (forward) => own.cite?.(forward),
            follow: () => own.follow?.(),
            written: (forward) => {
                const editor = view.current;
                const target = editor === null ? undefined : nextWritten(shown.blocks, head(), forward, visited.current);
                if (editor === null || target === undefined) {
                    return;
                }
                // Each fold it's in opens, said under the view.
                const effects = reaching(editor.state, target);
                editor.dispatch({ selection: { anchor: target }, effects, scrollIntoView: true, annotations: reached.of(effects.length) });
            },
            approve: (approved) => own.approve?.(approved),
            approveAll: () => own.approveAll?.(),
            hold: () => own.hold?.() ?? false,
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
            foldAround: (kind) => {
                const editor = view.current;
                const fold = aroundOf(shown.folds, head(), kind);
                if (editor === null || fold === undefined) {
                    return;
                }
                const effects = isFolded(editor.state, fold) ? [] : [folding(fold, true)];
                editor.dispatch({ effects, selection: { anchor: fold.summary.from }, scrollIntoView: true });
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
                for (const fold of shown.folds) {
                    if (isFolded(update.startState, fold) && !isFolded(update.state, fold)) {
                        unfolding.current?.(fold);
                    }
                }
            },
            folds: () => shown.folds,
            chord: (keys) => chording.current?.(keys),
            say: (text) => config.say?.(text),
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
