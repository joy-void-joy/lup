// The review: everything waiting for the operator in one buffer moved through
// with vim, their comments written into it, each under the line it's on. `o`
// opens a comment under the line (on the item whole from its header), `v` and a
// motion then `c` on the selection, and `c` alone on the item whole; a comment
// is edited as text, and only comments are. Ctrl+Enter in a comment ends it,
// back on what it's about; elsewhere it sends. Space `d` takes an item off the
// list, Space `z` leaves it for later, Space `e` opens an approval's diff, Space
// `a` or `x` answers it; `J` and `K` go to the next and previous item
// (`docs/dashboard.md`, *The review*).
import { Annotation, EditorState, Prec, RangeSetBuilder, StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, drawSelection, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import { Vim, getCM, vim, type CodeMirror, type CodeMirrorV } from "@replit/codemirror-vim";
import { useEffect, useMemo, useRef } from "react";

import {
    blockAt,
    laid,
    opened,
    pruned,
    quoted,
    regionAt,
    shownAt,
    toggled,
    type Block,
    type Comment,
    type Draft,
    type Item,
    type Laid,
} from "./review";

interface Props {
    items: Item[];
    draft: Draft;
    change: (draft: Draft) => void;
    name: (item: Item) => string;
    diffs: Map<number, string>;
    open: (number: number) => void;
    send: () => void;
    approve: (number: number, approved: boolean) => void;
    /** Whether the confirmation has the keyboard: once it's gone, the review takes it back. */
    confirming: boolean;
    /** Told each time vim enters or leaves insert mode, so the page can say what the keys do in it. */
    inserting: (yes: boolean) => void;
}

/** What the vim keys and the editor's own events do, as the review stands: replaced at each render. */
interface Actions {
    comment: (cm: CodeMirrorV, on: "line" | "selection" | "item") => void;
    finish: (cm: CodeMirrorV) => void;
    toggle: (list: "done" | "parked") => void;
    move: (forward: boolean) => void;
    approve: (approved: boolean) => void;
    expand: () => void;
    send: () => void;
    blocks: () => Block[];
    edited: (update: ViewUpdate) => void;
    settled: () => void;
}

let current: Actions | null = null;

let mapped = false;

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
    action("lupExpand", () => current?.expand());
    const map = (keys: string, name: string, context: string) =>
        Vim.mapCommand(keys, "action", name, {}, { context });
    map("o", "lupCommentLine", "normal");
    map("c", "lupCommentSelection", "visual");
    map("<Space>d", "lupDone", "normal");
    map("<Space>z", "lupLater", "normal");
    map("<Space>a", "lupApprove", "normal");
    map("<Space>x", "lupDecline", "normal");
    map("<Space>e", "lupExpand", "normal");
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

/**
 * The review's keys that vim's keymap can't say: Ctrl+Enter, which ends a comment in insert mode and
 * sends elsewhere, and `c` alone on an item's text, a comment on the item whole, which in a comment
 * stays vim's change. Vim takes every key it's given before a keymap would, so these are read first.
 */
const keys = Prec.highest(
    EditorView.domEventHandlers({
        keydown: (event, view) => {
            const cm = vimOf(view);
            if (cm === null || event.altKey) {
                return false;
            }
            const modified = event.ctrlKey || event.metaKey;
            if (event.key === "Enter" && modified) {
                if (cm.state.vim.insertMode) {
                    current?.finish(cm);
                } else {
                    current?.send();
                }
                event.preventDefault();
                return true;
            }
            const head = view.state.selection.main.head;
            const inComment = (current?.blocks() ?? []).some((each) => head >= each.from && head <= each.to);
            if (event.key === "c" && !modified && idle(cm) && !inComment) {
                current?.comment(cm, "item");
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

/** Let the operator change the text only inside a comment: a change from its start to just past its end. */
const onlyComments = EditorState.transactionFilter.of((transaction) => {
    if (!transaction.docChanged || transaction.annotation(rebuilt) === true) {
        return transaction;
    }
    const blocks = current?.blocks() ?? [];
    let inside = true;
    transaction.changes.iterChangedRanges((from, to) => {
        if (!blocks.some((each) => from >= each.from && to <= each.to + 1)) {
            inside = false;
        }
    });
    return inside ? transaction : [];
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

/** Draw the review: headers, done and parked items, diffs' lines, each comment's lines, and the passage each comment is on. */
function decorations(laidOut: Laid, draft: Draft): DecorationSet {
    const marks: { from: number; to: number; value: Decoration }[] = [];
    const comments = draft.comments ?? [];
    for (const region of laidOut.regions) {
        const number = region.item.number;
        const states = [
            "review-header",
            (draft.done ?? []).includes(number) ? "is-done" : "",
            (draft.parked ?? []).includes(number) ? "is-parked" : "",
        ].join(" ");
        marks.push({ from: region.header.from, to: region.header.from, value: Decoration.line({ class: states }) });
        if (region.item.reason.reason === "approval") {
            for (const line of region.lines) {
                const kind = diffLine(laidOut.text.slice(line.from, line.to));
                if (kind !== null) {
                    marks.push({ from: line.from, to: line.from, value: Decoration.line({ class: kind }) });
                }
            }
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
    return Math.min(now.header.from + (head - was.header.from), after.text.length);
}

export function Review({ items, draft, change, name, diffs, open, send, approve, confirming, inserting }: Props) {
    const parent = useRef<HTMLDivElement>(null);
    const view = useRef<EditorView | null>(null);
    const shown = useRef<Laid | null>(null);
    const landing = useRef<Landing>(null);
    const latest = useRef(draft);
    latest.current = draft;
    const telling = useRef(inserting);
    telling.current = inserting;
    const laidOut = useMemo(
        () =>
            laid(
                items,
                (item, later) => {
                    const what = item.reason.reason === "message" ? item.reason.kind : item.reason.reason;
                    const from = item.sender.party === "operator" ? "lup" : name(item);
                    return `── #${item.number} ${what} · ${from} · ${when(item.made)}${later ? " · later" : ""} ──`;
                },
                draft,
                diffs,
            ),
        [items, name, draft, diffs],
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
                    EditorView.lineWrapping,
                    drawing,
                    EditorView.updateListener.of((update) => {
                        const replaced = update.transactions.some((each) => each.annotation(rebuilt) === true);
                        if (update.docChanged && !replaced) {
                            current?.edited(update);
                        }
                        // A click out of the comment being written ends it, as Esc would: typing there
                        // could change nothing, and the thin cursor of insert mode is easily lost.
                        const clicked = update.transactions.some((each) => each.isUserEvent("select.pointer"));
                        const cm = vimOf(update.view);
                        const head = update.state.selection.main.head;
                        const inComment = (current?.blocks() ?? []).some((each) => head >= each.from && head <= each.to);
                        if (clicked && cm?.state.vim.insertMode === true && !inComment) {
                            queueMicrotask(() => Vim.exitInsertMode(cm, true));
                        }
                    }),
                    keys,
                ],
            }),
        });
        view.current = created;
        getCM(created)?.on("vim-mode-change", (event: { mode: string }) => {
            telling.current(event.mode === "insert");
            if (event.mode !== "insert") {
                current?.settled();
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
            const head = followed(shown.current, laidOut, editor.state.selection.main.head, arriving);
            editor.dispatch({
                changes: { from: 0, to: editor.state.doc.length, insert: laidOut.text },
                selection: { anchor: head },
                scrollIntoView: true,
                annotations: rebuilt.of(true),
            });
        }
        shown.current = laidOut;
        landing.current = null;
        editor.dispatch({ effects: drawn.of(decorations(laidOut, draft)) });
        const cm = getCM(editor);
        if (arriving !== null && "comment" in arriving && cm !== null) {
            Vim.handleKey(cm, "i", "mapping");
        }
    }, [laidOut, draft]);

    useEffect(() => {
        if (!confirming) {
            view.current?.focus();
        }
    }, [confirming]);

    function head(): number {
        return view.current?.state.selection.main.head ?? 0;
    }

    function here() {
        return regionAt(laidOut.regions, head());
    }

    function added(comment: Comment) {
        const comments = latest.current.comments ?? [];
        landing.current = { comment: comments.length };
        change({ ...latest.current, comments: [...comments, comment] });
    }

    current = {
        comment: (cm, on) => {
            const editor = view.current;
            if (editor === null) {
                return;
            }
            if (on === "item") {
                const region = here();
                if (region !== undefined) {
                    added({ item: region.item.number, quote: null, text: "" });
                }
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
            if (blockAt(laidOut, head()) !== undefined) {
                const end = editor.state.doc.lineAt(head()).to;
                editor.dispatch({ changes: { from: end, insert: "\n" }, selection: { anchor: end + 1 } });
                Vim.handleKey(cm, "i", "mapping");
                return;
            }
            const comment = opened(laidOut, head());
            if (comment !== undefined) {
                added(comment);
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
            change(toggled(latest.current, list, region.item.number));
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
            if (region?.item.reason.reason === "approval") {
                approve(region.item.number, approved);
            }
        },
        expand: () => {
            const region = here();
            if (region?.item.reason.reason === "approval") {
                open(region.item.number);
            }
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
            const inserting = getCM(update.view)?.state.vim?.insertMode === true;
            change(inserting ? next : pruned(next));
        },
        settled: () => {
            const comments = latest.current.comments ?? [];
            const trimmed = comments.map((each) => ({ ...each, text: each.text.replace(/\s+$/, "") }));
            const kept = pruned({ ...latest.current, comments: trimmed });
            const same = (kept.comments ?? []).length === comments.length && trimmed.every((each, at) => each.text === comments[at]?.text);
            if (!same) {
                change(kept);
            }
        },
    };

    return <div className="review-buffer" ref={parent} />;
}
