// The review: everything waiting for the operator in one buffer moved through
// with vim, in groups, one per agent, their comments written into it, each under
// the line it's on. Insert mode is writing a comment: a key that enters it opens
// one where the cursor is, or edits the one it's in, and the cursor stays in it
// until it ends. `c` opens one on the item whole; `o`, `C` and vim's other keys
// of insert mode on the line; `v` and a motion, then `c` or `s`, on the
// selection. Ctrl+Enter in a comment ends it, back on what it's about; elsewhere
// it sends. `u` and Ctrl+R undo and redo any change to the draft. Space `d` marks
// an item read, Space `z` leaves it for later, Space `a` or `x` answers an
// approval; `J` and `K` go to the next and previous item. Under each item, its
// context and an approval's whole diff fold, folded until opened: `za` opens or
// closes the one under the cursor, `zo` and `zc` open and close it, `zR` and `zM`
// open and close them all (`docs/dashboard.md`, *The review*).
import { codeFolding, foldEffect, foldedRanges, unfoldEffect } from "@codemirror/language";
import { Annotation, EditorState, Prec, RangeSetBuilder, StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, drawSelection, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import { Vim, getCM, vim, type CodeMirror, type CodeMirrorV } from "@replit/codemirror-vim";
import { useEffect, useMemo, useRef } from "react";

import {
    blockAt,
    foldAt,
    foldKey,
    laid,
    onBanner,
    opened,
    pruned,
    quoted,
    regionAt,
    shownAt,
    toggled,
    type Around,
    type Aside,
    type Block,
    type Comment,
    type Draft,
    type Fold,
    type Item,
    type Laid,
    type Span,
} from "./review";

interface Props {
    items: Item[];
    draft: Draft;
    change: (draft: Draft) => void;
    /** Name the group an item is in: the agent that sent it, and where. */
    banner: (item: Item) => string;
    /** What the host has answered of each item beyond its own text: its context, and an approval's whole diff. */
    around: Around;
    send: () => void;
    approve: (number: number, approved: boolean) => void;
    /** Whether the confirmation has the keyboard: once it's gone, the review takes it back. */
    confirming: boolean;
    /** Told each time vim enters or leaves insert mode, so the page can say what the keys do in it. */
    inserting: (yes: boolean) => void;
    /** Changed each time the draft is replaced from outside, as when it's sent: what was done before can't be undone. */
    epoch: number;
}

/** What the vim keys and the editor's own events do, as the review stands: replaced at each render. */
interface Actions {
    comment: (cm: CodeMirrorV, on: "line" | "selection" | "item") => void;
    entered: (cm: CodeMirrorV) => void;
    left: () => void;
    finish: (cm: CodeMirrorV) => void;
    toggle: (list: "done" | "parked") => void;
    move: (forward: boolean) => void;
    approve: (approved: boolean) => void;
    fold: (how: "toggle" | "open" | "close") => void;
    foldAll: (closing: boolean) => void;
    folded: (state: EditorState) => void;
    undo: (back: boolean) => void;
    send: () => void;
    blocks: () => Block[];
    edited: (update: ViewUpdate) => void;
}

let current: Actions | null = null;

let mapped = false;

/** What the editor knows of the last key, read once vim has made of it what it does. */
const keyed: {
    /** Where the cursor was when it was pressed: the line a comment it opens is on, wherever vim moved the cursor since. */
    from: number;
    /** Whether it was pressed in visual mode, where a comment it opens is on the selection. */
    visual: boolean;
    /** The passage it tried to change outside every comment, as `v` then `R` would: what such a comment quotes. */
    passage: Span | null;
    /** Whether vim is in insert mode, that is, whether a comment is being written. */
    inserting: boolean;
} = { from: 0, visual: false, passage: null, inserting: false };

/** Map the review's keys into vim's keymap, once: user mappings go before its own. */
function mapKeys(): void {
    if (mapped) {
        return;
    }
    mapped = true;
    // Space moves right in vim's own keymap, under every context; taken off, it leads
    // the review's keys. Its types want a context, where none names that mapping.
    const unmap = Vim.unmap as (keys: string, context?: string) => boolean;
    unmap("<Space>");
    const action = (name: string, fn: (cm: CodeMirrorV) => void) => Vim.defineAction(name, (cm) => fn(cm));
    action("lupCommentLine", (cm) => current?.comment(cm, "line"));
    action("lupCommentSelection", (cm) => current?.comment(cm, "selection"));
    action("lupDone", () => current?.toggle("done"));
    action("lupLater", () => current?.toggle("parked"));
    action("lupNext", () => current?.move(true));
    action("lupPrevious", () => current?.move(false));
    action("lupApprove", () => current?.approve(true));
    action("lupDecline", () => current?.approve(false));
    // Vim's own fold keys, which its CodeMirror mode leaves unmapped, on CodeMirror's folds.
    action("lupFoldToggle", () => current?.fold("toggle"));
    action("lupFoldOpen", () => current?.fold("open"));
    action("lupFoldClose", () => current?.fold("close"));
    action("lupFoldOpenAll", () => current?.foldAll(false));
    action("lupFoldCloseAll", () => current?.foldAll(true));
    action("lupUndo", () => current?.undo(true));
    action("lupRedo", () => current?.undo(false));
    const map = (keys: string, name: string, context: string) =>
        Vim.mapCommand(keys, "action", name, {}, { context });
    map("o", "lupCommentLine", "normal");
    map("c", "lupCommentSelection", "visual");
    map("s", "lupCommentSelection", "visual");
    map("<Space>d", "lupDone", "normal");
    map("<Space>z", "lupLater", "normal");
    map("<Space>a", "lupApprove", "normal");
    map("<Space>x", "lupDecline", "normal");
    map("za", "lupFoldToggle", "normal");
    map("zo", "lupFoldOpen", "normal");
    map("zc", "lupFoldClose", "normal");
    map("zR", "lupFoldOpenAll", "normal");
    map("zM", "lupFoldCloseAll", "normal");
    map("u", "lupUndo", "normal");
    map("<C-r>", "lupRedo", "normal");
    map("J", "lupNext", "normal");
    map("K", "lupPrevious", "normal");
}

/** Return the editor's vim, once it's started. */
function vimOf(view: EditorView): CodeMirrorV | null {
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
function commentAt(position: number): Block | undefined {
    return (current?.blocks() ?? []).find((each) => position >= each.from && position <= each.to);
}

/**
 * The review's keys that vim's keymap can't say, read ahead of vim, which takes every key it's given before a keymap
 * would: Ctrl+Enter, which ends a comment in insert mode and sends elsewhere; and `c` and `C` alone on an item's text,
 * a comment on the item whole and on the line, which in a comment stay vim's change. Every key is noted first, for
 * what vim makes of it (`keyed`).
 */
const keys = Prec.highest(
    EditorView.domEventHandlers({
        keydown: (event, view) => {
            const cm = vimOf(view);
            if (cm === null) {
                return false;
            }
            const head = view.state.selection.main.head;
            keyed.from = head;
            keyed.visual = cm.state.vim.visualMode;
            keyed.passage = null;
            const modified = event.ctrlKey || event.metaKey || event.altKey;
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                if (cm.state.vim.insertMode) {
                    current?.finish(cm);
                } else {
                    current?.send();
                }
                event.preventDefault();
                return true;
            }
            if ((event.key === "c" || event.key === "C") && !modified && idle(cm) && commentAt(head) === undefined) {
                current?.comment(cm, event.key === "c" ? "item" : "line");
                event.preventDefault();
                return true;
            }
            return false;
        },
    }),
);

/** Marks the review's own replacing of its text, which isn't the operator's edit. */
const rebuilt = Annotation.define<boolean>();

const drawn = StateEffect.define<DecorationSet>();

const drawing = StateField.define<DecorationSet>({
    create: () => Decoration.none,
    update: (set, transaction) => {
        const replaced = transaction.effects.find((each) => each.is(drawn));
        return replaced === undefined ? set.map(transaction.changes) : (replaced.value as DecorationSet);
    },
    provide: (field) => EditorView.decorations.from(field),
});

/**
 * Let the operator change the text only inside a comment: a change from its start to just past its end. A change
 * tried elsewhere is dropped, its passage noted, for the comment vim's insert mode opens next.
 */
const onlyComments = EditorState.transactionFilter.of((transaction) => {
    if (!transaction.docChanged || transaction.annotation(rebuilt) === true) {
        return transaction;
    }
    const blocks = current?.blocks() ?? [];
    let inside = true;
    transaction.changes.iterChangedRanges((from, to) => {
        if (!blocks.some((each) => from >= each.from && to <= each.to + 1)) {
            inside = false;
            if (to > from && keyed.passage === null) {
                keyed.passage = { from, to };
            }
        }
    });
    return inside ? transaction : [];
});

/** Keep the cursor in the comment being written while insert mode lasts, as a text field would; a click elsewhere ends it instead. */
const withinComment = EditorState.transactionFilter.of((transaction) => {
    const moved = transaction.selection;
    if (
        !keyed.inserting ||
        moved === undefined ||
        transaction.docChanged ||
        transaction.isUserEvent("select.pointer") ||
        transaction.annotation(rebuilt) === true
    ) {
        return transaction;
    }
    const block = commentAt(transaction.startState.selection.main.head);
    const head = moved.main.head;
    if (block === undefined || (head >= block.from && head <= block.to)) {
        return transaction;
    }
    return { selection: { anchor: Math.min(Math.max(head, block.from), block.to) }, scrollIntoView: true };
});

/** Return how a line of a diff is drawn: added, removed, a hunk's header or a file's; none for a line of context or of anything else. */
function diffLine(line: string): string | null {
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff --git")) {
        return "diff-file";
    }
    if (line.startsWith("@@")) {
        return "diff-hunk";
    }
    if (line.startsWith("+")) {
        return "diff-added";
    }
    if (line.startsWith("-")) {
        return "diff-removed";
    }
    return null;
}

/** Return the classes a line under an item is drawn with: what it shows, a diff's line as git colours it, and whether it folds under a summary. */
function asideClasses(laidOut: Laid, aside: Aside): string {
    const diff = aside.kind === "diff" ? diffLine(laidOut.text.slice(aside.from, aside.to)) : null;
    const under = aside.kind === "summary" || aside.kind === "refused" ? null : "aside-under";
    return [`aside-${aside.kind}`, under, diff].filter((each) => each !== null).join(" ");
}

/** Draw the review: groups' banners, items' headers, done and parked items, the lines under each item, each comment's lines, and the passage each comment is on. */
function decorations(laidOut: Laid, draft: Draft): DecorationSet {
    const marks: { from: number; to: number; value: Decoration }[] = [];
    const comments = draft.comments ?? [];
    for (const region of laidOut.regions) {
        const number = region.item.number;
        if (region.banner !== null) {
            marks.push({
                from: region.banner.from,
                to: region.banner.from,
                value: Decoration.line({ class: "review-banner" }),
            });
        }
        const states = [
            "review-header",
            (draft.done ?? []).includes(number) ? "is-done" : "",
            (draft.parked ?? []).includes(number) ? "is-parked" : "",
        ].join(" ");
        marks.push({ from: region.header.from, to: region.header.from, value: Decoration.line({ class: states }) });
        for (const aside of region.asides) {
            marks.push({ from: aside.from, to: aside.from, value: Decoration.line({ class: asideClasses(laidOut, aside) }) });
        }
        for (const block of region.blocks) {
            let at = block.from;
            for (const line of laidOut.text.slice(block.from, block.to).split("\n")) {
                marks.push({ from: at, to: at, value: Decoration.line({ class: "remark" }) });
                at += line.length + 1;
            }
            const quote = comments[block.comment]?.quote;
            if (quote != null && quote.end > quote.start) {
                const from = shownAt(region, quote.start);
                const to = shownAt(region, quote.end);
                if (to > from) {
                    marks.push({ from, to, value: Decoration.mark({ class: "commented" }) });
                }
            }
        }
    }
    marks.sort((a, b) => a.from - b.from || a.to - b.to);
    const builder = new RangeSetBuilder<Decoration>();
    for (const each of marks) {
        builder.add(each.from, each.to, each.value);
    }
    return builder.finish();
}

/** Return whether CodeMirror holds `fold` folded. */
function isFolded(state: EditorState, fold: Fold): boolean {
    let found = false;
    foldedRanges(state).between(fold.from, fold.from, (from, to) => {
        found ||= from === fold.from && to === fold.to;
    });
    return found;
}

/** Return the effect that folds or unfolds `fold`. */
function folding(fold: Fold, closing: boolean): StateEffect<Span> {
    const range = { from: fold.from, to: fold.to };
    return closing ? foldEffect.of(range) : unfoldEffect.of(range);
}

/** Return where the cursor goes once a fold closes over it: on its summary line where it was in what the fold hides, else where it was. */
function uncovered(closed: Fold[], head: number): number {
    return closed.find((each) => head > each.summary.to && head <= each.to)?.summary.from ?? head;
}

function when(made: string): string {
    const at = new Date(made);
    return at.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Where the cursor goes once the text is laid out again: into a comment just opened, onto an item, or nowhere in particular. */
type Landing = { comment: number } | { item: number } | null;

/** Return where the cursor goes once the text is laid out again: into the comment or onto the item `landing` names, else on the same item, as far into it as it was; at the same place where its item is gone. */
function followed(before: Laid | null, after: Laid, head: number, landing: Landing): number {
    const clamped = Math.min(head, after.text.length);
    if (landing !== null && "comment" in landing) {
        const block = after.regions.flatMap((each) => each.blocks).find((each) => each.comment === landing.comment);
        return block?.from ?? clamped;
    }
    if (landing !== null) {
        return after.regions.find((each) => each.item.number === landing.item)?.header.from ?? clamped;
    }
    const was = before === null ? undefined : regionAt(before.regions, head);
    const now = was === undefined ? undefined : after.regions.find((each) => each.item.number === was.item.number);
    if (was === undefined || now === undefined) {
        return clamped;
    }
    return Math.max(Math.min(now.header.from + (head - was.header.from), after.text.length), 0);
}

export function Review({ items, draft, change, banner, around, send, approve, confirming, inserting, epoch }: Props) {
    const parent = useRef<HTMLDivElement>(null);
    const view = useRef<EditorView | null>(null);
    const shown = useRef<Laid | null>(null);
    const landing = useRef<Landing>(null);
    // The folds the operator opened, by `foldKey`: each laying out folds every other one.
    const unfolded = useRef(new Set<string>());
    const latest = useRef(draft);
    latest.current = draft;
    const telling = useRef(inserting);
    telling.current = inserting;
    // The drafts before each change, for `u`; those undone, for Ctrl+R; and whether the comment being
    // written has its step already, so it's undone whole.
    const past = useRef<Draft[]>([]);
    const future = useRef<Draft[]>([]);
    const writing = useRef(false);
    const laidOut = useMemo(
        () =>
            laid(
                items,
                (item, later) => `━━ ${banner(item)}${later ? " · later" : ""} ━━`,
                (item, later) => {
                    const what =
                        item.reason.reason === "message"
                            ? item.reason.kind
                            : item.reason.reason === "held"
                              ? "held change"
                              : item.reason.reason;
                    return `── #${item.number} ${what} · ${when(item.made)}${later ? " · later" : ""} ──`;
                },
                draft,
                around,
            ),
        [items, banner, draft, around],
    );

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
                    vim(),
                    drawSelection(),
                    onlyComments,
                    withinComment,
                    EditorView.lineWrapping,
                    codeFolding({ placeholderText: "…" }),
                    drawing,
                    EditorView.updateListener.of((update) => {
                        const replaced = update.transactions.some((each) => each.annotation(rebuilt) === true);
                        if (update.docChanged && !replaced) {
                            current?.edited(update);
                        }
                        // A fold opened or closed however it was, by its keys, a click, or the cursor going into it,
                        // is kept for the next laying out; an edit only moves the folds with the text.
                        if (!update.docChanged && foldedRanges(update.startState) !== foldedRanges(update.state)) {
                            current?.folded(update.state);
                        }
                        // A click out of the comment being written ends it, as Esc would.
                        const clicked = update.transactions.some((each) => each.isUserEvent("select.pointer"));
                        const cm = vimOf(update.view);
                        const head = update.state.selection.main.head;
                        if (clicked && cm !== null && keyed.inserting && commentAt(head) === undefined) {
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
                queueMicrotask(() => current?.entered(cm));
            }
            if (was && !now) {
                current?.left();
            }
        });
        created.focus();
        return () => {
            created.destroy();
            view.current = null;
        };
        // The editor is made once; what it shows is sent to it below.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        const editor = view.current;
        if (editor === null) {
            return;
        }
        const arriving = landing.current;
        if (editor.state.doc.toString() !== laidOut.text) {
            // Replacing the text drops every fold; each the operator hasn't opened is folded again with it.
            const head = followed(shown.current, laidOut, editor.state.selection.main.head, arriving);
            const closed = laidOut.regions
                .flatMap((each) => each.folds)
                .filter((each) => !unfolded.current.has(foldKey(each)));
            editor.dispatch({
                changes: { from: 0, to: editor.state.doc.length, insert: laidOut.text },
                selection: { anchor: uncovered(closed, head) },
                effects: closed.map((each) => folding(each, true)),
                scrollIntoView: true,
                annotations: rebuilt.of(true),
            });
        }
        shown.current = laidOut;
        landing.current = null;
        editor.dispatch({ effects: drawn.of(decorations(laidOut, draft)) });
        const cm = getCM(editor);
        if (arriving !== null && "comment" in arriving && cm !== null && !keyed.inserting) {
            Vim.handleKey(cm, "i", "mapping");
        }
    }, [laidOut, draft]);

    useEffect(() => {
        if (!confirming) {
            view.current?.focus();
        }
    }, [confirming]);

    useEffect(() => {
        past.current = [];
        future.current = [];
    }, [epoch]);

    function head(): number {
        return view.current?.state.selection.main.head ?? 0;
    }

    function here() {
        return regionAt(laidOut.regions, head());
    }

    /** Change the draft as one step `u` undoes: the comment being written, from its opening to its end, is one. */
    function record(next: Draft) {
        if (!writing.current) {
            past.current = [...past.current, latest.current];
            future.current = [];
        }
        writing.current = keyed.inserting;
        change(next);
    }

    function added(comment: Comment) {
        const comments = latest.current.comments ?? [];
        landing.current = { comment: comments.length };
        record({ ...latest.current, comments: [...comments, comment] });
        writing.current = true;
    }

    current = {
        comment: (cm, on) => {
            const editor = view.current;
            if (editor === null) {
                return;
            }
            if (on === "selection") {
                const from = cm.indexFromPos(cm.getCursor("start"));
                const to = cm.indexFromPos(cm.getCursor("end"));
                Vim.exitVisualMode(cm);
                const comment = quoted(laidOut, from, to);
                if (comment !== undefined) {
                    added(comment);
                }
                return;
            }
            if (on === "line" && blockAt(laidOut, head()) !== undefined) {
                const end = editor.state.doc.lineAt(head()).to;
                editor.dispatch({ changes: { from: end, insert: "\n" }, selection: { anchor: end + 1 } });
                Vim.handleKey(cm, "i", "mapping");
                return;
            }
            const region = here();
            if (region === undefined || onBanner(region, head())) {
                return;
            }
            const comment =
                on === "item" ? { item: region.item.number, quote: null, text: "" } : opened(laidOut, head());
            if (comment !== undefined) {
                added(comment);
            }
        },
        entered: (cm) => {
            if (blockAt(laidOut, head()) !== undefined) {
                return;
            }
            const passage = keyed.visual ? keyed.passage : null;
            const comment =
                passage === null ? opened(laidOut, keyed.from) : quoted(laidOut, passage.from, passage.to);
            if (comment === undefined) {
                Vim.exitInsertMode(cm, true);
                return;
            }
            added(comment);
        },
        left: () => {
            // The comment's trailing space trimmed, and an emptied one dropped, as part of the step that wrote it.
            const comments = latest.current.comments ?? [];
            const trimmed = comments.map((each) => ({ ...each, text: each.text.replace(/\s+$/, "") }));
            const kept = pruned({ ...latest.current, comments: trimmed });
            const same =
                (kept.comments ?? []).length === comments.length &&
                trimmed.every((each, at) => each.text === comments[at]?.text);
            writing.current = false;
            if (!same) {
                change(kept);
            }
        },
        finish: (cm) => {
            const editor = view.current;
            const block = blockAt(laidOut, head());
            const region = here();
            const comment = block === undefined ? undefined : latest.current.comments?.[block.comment];
            Vim.exitInsertMode(cm, true);
            if (editor === null || region === undefined || comment === undefined) {
                return;
            }
            const back = comment.quote == null ? region.header.from : shownAt(region, comment.quote.start);
            editor.dispatch({ selection: { anchor: back }, scrollIntoView: true });
        },
        toggle: (list) => {
            const region = here();
            if (region === undefined) {
                return;
            }
            if (list === "parked") {
                const at = laidOut.regions.indexOf(region);
                landing.current = { item: (laidOut.regions[at + 1] ?? region).item.number };
            }
            record(toggled(latest.current, list, region.item.number));
        },
        move: (forward) => {
            const editor = view.current;
            if (editor === null) {
                return;
            }
            const headers = laidOut.regions.map((each) => each.header.from);
            const target = forward
                ? headers.find((each) => each > head())
                : [...headers].reverse().find((each) => each < head());
            if (target !== undefined) {
                editor.dispatch({ selection: { anchor: target }, scrollIntoView: true });
            }
        },
        approve: (approved) => {
            const region = here();
            const reason = region?.item.reason.reason;
            if (region !== undefined && (reason === "approval" || reason === "held")) {
                approve(region.item.number, approved);
            }
        },
        fold: (how) => {
            const editor = view.current;
            const at = head();
            const fold = foldAt(laidOut, at);
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
            const changing = laidOut.regions
                .flatMap((each) => each.folds)
                .filter((each) => isFolded(editor.state, each) !== closing);
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
            if (state.sliceDoc() !== laidOut.text) {
                return;
            }
            for (const fold of laidOut.regions.flatMap((each) => each.folds)) {
                if (isFolded(state, fold)) {
                    unfolded.current.delete(foldKey(fold));
                } else {
                    unfolded.current.add(foldKey(fold));
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
        send,
        blocks: () => laidOut.regions.flatMap((each) => each.blocks),
        edited: (update) => {
            const blocks = laidOut.regions.flatMap((each) => each.blocks);
            const comments = [...(latest.current.comments ?? [])];
            for (const block of blocks) {
                const from = update.changes.mapPos(block.from, -1);
                const to = update.changes.mapPos(block.to, 1);
                const text = update.state.doc.sliceString(from, to);
                const before = comments[block.comment];
                if (before !== undefined && before.text !== text) {
                    comments[block.comment] = { ...before, text };
                }
            }
            const next = { ...latest.current, comments };
            record(keyed.inserting ? next : pruned(next));
        },
    };

    return <div className="review-buffer" ref={parent} />;
}
