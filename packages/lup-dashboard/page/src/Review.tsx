// The review: everything waiting for the operator in one read-only buffer moved
// through with vim, the draft reply drawn over it. `v` and a motion then `c`
// comments on a passage, `C` on the item, `c` alone on the whole reply; Space
// then `l`, `u` or `o` rules on the decision under the cursor; Space `d` takes an
// item off the list, Space `z` leaves it for later; `J` and `K` go to the next
// and previous item; Ctrl+Enter sends (`docs/dashboard.md`, *The review*).
import { EditorState, Prec, RangeSetBuilder, StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, WidgetType, keymap, type DecorationSet } from "@codemirror/view";
import { Vim, vim, type CodeMirrorV } from "@replit/codemirror-vim";
import { useEffect, useMemo, useRef, useState } from "react";

import {
    decisionAt,
    laid,
    quoted,
    regionAt,
    ruled,
    toggled,
    type Draft,
    type Item,
    type Laid,
    type Quote,
    type Verdict,
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
}

/** Where a comment being written goes: an item's passage, an item whole, or the whole reply. */
interface Writing {
    item: number | null;
    quote: Quote | null;
}

/** What the vim keys do, as the review stands: replaced at each render. */
interface Actions {
    comment: (cm: CodeMirrorV, on: "selection" | "item" | "whole") => void;
    verdict: (cm: CodeMirrorV, verdict: Verdict) => void;
    toggle: (cm: CodeMirrorV, list: "done" | "parked") => void;
    move: (cm: CodeMirrorV, forward: boolean) => void;
    approve: (cm: CodeMirrorV, approved: boolean) => void;
    expand: (cm: CodeMirrorV) => void;
    send: () => void;
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
    const action = (name: string, fn: (cm: CodeMirrorV) => void) =>
        Vim.defineAction(name, (cm) => fn(cm));
    action("lupCommentSelection", (cm) => current?.comment(cm, "selection"));
    action("lupCommentItem", (cm) => current?.comment(cm, "item"));
    action("lupCommentWhole", (cm) => current?.comment(cm, "whole"));
    action("lupLeaning", (cm) => current?.verdict(cm, "leaning"));
    action("lupUndecided", (cm) => current?.verdict(cm, "undecided"));
    action("lupLeaveOpen", (cm) => current?.verdict(cm, "leave open"));
    action("lupDone", (cm) => current?.toggle(cm, "done"));
    action("lupLater", (cm) => current?.toggle(cm, "parked"));
    action("lupNext", (cm) => current?.move(cm, true));
    action("lupPrevious", (cm) => current?.move(cm, false));
    action("lupApprove", (cm) => current?.approve(cm, true));
    action("lupDecline", (cm) => current?.approve(cm, false));
    action("lupExpand", (cm) => current?.expand(cm));
    const map = (keys: string, name: string, context: string) =>
        Vim.mapCommand(keys, "action", name, {}, { context });
    map("c", "lupCommentSelection", "visual");
    map("c", "lupCommentWhole", "normal");
    map("C", "lupCommentItem", "normal");
    map("<Space>l", "lupLeaning", "normal");
    map("<Space>u", "lupUndecided", "normal");
    map("<Space>o", "lupLeaveOpen", "normal");
    map("<Space>d", "lupDone", "normal");
    map("<Space>z", "lupLater", "normal");
    map("<Space>a", "lupApprove", "normal");
    map("<Space>x", "lupDecline", "normal");
    map("<Space>e", "lupExpand", "normal");
    map("J", "lupNext", "normal");
    map("K", "lupPrevious", "normal");
}

const drawn = StateEffect.define<DecorationSet>();

const drawing = StateField.define<DecorationSet>({
    create: () => Decoration.none,
    update: (set, transaction) => {
        const replaced = transaction.effects.find((each) => each.is(drawn));
        return replaced === undefined ? set.map(transaction.changes) : (replaced.value as DecorationSet);
    },
    provide: (field) => EditorView.decorations.from(field),
});

class Remark extends WidgetType {
    constructor(
        readonly text: string,
        readonly where: string,
    ) {
        super();
    }

    override eq(other: Remark): boolean {
        return other.text === this.text && other.where === this.where;
    }

    toDOM(): HTMLElement {
        const box = document.createElement("div");
        box.className = "remark";
        box.textContent = `${this.where} ${this.text}`;
        return box;
    }
}

class Ruling extends WidgetType {
    constructor(readonly verdict: Verdict) {
        super();
    }

    override eq(other: Ruling): boolean {
        return other.verdict === this.verdict;
    }

    toDOM(): HTMLElement {
        const badge = document.createElement("span");
        badge.className = `ruling ruling-${this.verdict.replace(" ", "-")}`;
        badge.textContent = ` [${this.verdict}]`;
        return badge;
    }
}

/** Draw the draft over the laid-out review: headers, done and parked items, verdicts, and each comment under its passage. */
function decorations(laidOut: Laid, draft: Draft): DecorationSet {
    const marks: { from: number; to: number; value: Decoration }[] = [];
    for (const region of laidOut.regions) {
        const number = region.item.number;
        const states = [
            "review-header",
            (draft.done ?? []).includes(number) ? "is-done" : "",
            (draft.parked ?? []).includes(number) ? "is-parked" : "",
        ].join(" ");
        marks.push({ from: region.header.from, to: region.header.from, value: Decoration.line({ class: states }) });
        for (const asked of region.decisions) {
            const given = (draft.verdicts ?? []).find((each) => each.item === number && each.decision === asked.number);
            if (given !== undefined) {
                marks.push({ from: asked.to, to: asked.to, value: Decoration.widget({ widget: new Ruling(given.verdict), side: 1 }) });
            }
        }
        for (const comment of (draft.comments ?? []).filter((each) => each.item === number)) {
            if (comment.quote == null) {
                marks.push({
                    from: region.body.to,
                    to: region.body.to,
                    value: Decoration.widget({ widget: new Remark(comment.text, "on the item:"), side: 1, block: true }),
                });
                continue;
            }
            const from = region.body.from + comment.quote.start;
            const to = Math.min(region.body.from + comment.quote.end, region.body.to);
            if (to > from) {
                marks.push({ from, to, value: Decoration.mark({ class: "commented" }) });
            }
            const lineEnd = laidOut.text.indexOf("\n", to - 1);
            const at = lineEnd === -1 ? to : lineEnd;
            marks.push({
                from: at,
                to: at,
                value: Decoration.widget({ widget: new Remark(comment.text, "»"), side: 1, block: true }),
            });
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

export function Review({ items, draft, change, name, diffs, open, send, approve }: Props) {
    const parent = useRef<HTMLDivElement>(null);
    const view = useRef<EditorView | null>(null);
    const [writing, setWriting] = useState<Writing | null>(null);
    const [said, setSaid] = useState("");
    const parked = draft.parked ?? [];
    const laidOut = useMemo(
        () =>
            laid(
                items,
                (item, later) => {
                    const what = item.reason.reason === "message" ? item.reason.kind : item.reason.reason;
                    const from = item.sender.party === "operator" ? "lup" : name(item);
                    return `── #${item.number} ${what} · ${from} · ${when(item.made)}${later ? " · later" : ""} ──`;
                },
                parked,
                diffs,
            ),
        [items, name, parked, diffs],
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
                    EditorState.readOnly.of(true),
                    EditorView.lineWrapping,
                    drawing,
                    Prec.highest(
                        keymap.of([
                            {
                                key: "Mod-Enter",
                                run: () => {
                                    current?.send();
                                    return true;
                                },
                            },
                        ]),
                    ),
                ],
            }),
        });
        view.current = created;
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
        const head = Math.min(editor.state.selection.main.head, laidOut.text.length);
        if (editor.state.doc.toString() !== laidOut.text) {
            editor.dispatch({
                changes: { from: 0, to: editor.state.doc.length, insert: laidOut.text },
                selection: { anchor: head },
            });
        }
        editor.dispatch({ effects: drawn.of(decorations(laidOut, draft)) });
    }, [laidOut, draft]);

    current = {
        comment: (cm, on) => {
            const editor = view.current;
            if (editor === null) {
                return;
            }
            if (on === "whole") {
                setWriting({ item: null, quote: null });
                return;
            }
            if (on === "item") {
                const region = regionAt(laidOut.regions, editor.state.selection.main.head);
                if (region !== undefined) {
                    setWriting({ item: region.item.number, quote: null });
                }
                return;
            }
            const from = cm.indexFromPos(cm.getCursor("start"));
            const to = cm.indexFromPos(cm.getCursor("end"));
            Vim.exitVisualMode(cm);
            const passage = quoted(laidOut, from, to);
            if (passage !== undefined) {
                setWriting({ item: passage.item, quote: passage.quote });
            }
        },
        verdict: (_cm, verdict) => {
            const editor = view.current;
            const region = editor === null ? undefined : regionAt(laidOut.regions, editor.state.selection.main.head);
            const asked = region === undefined || editor === null ? undefined : decisionAt(region, editor.state.selection.main.head);
            if (region !== undefined && asked !== undefined) {
                change(ruled(draft, region.item.number, asked.number, verdict));
            }
        },
        toggle: (_cm, list) => {
            const editor = view.current;
            const region = editor === null ? undefined : regionAt(laidOut.regions, editor.state.selection.main.head);
            if (region !== undefined) {
                change(toggled(draft, list, region.item.number));
            }
        },
        move: (_cm, forward) => {
            const editor = view.current;
            if (editor === null) {
                return;
            }
            const head = editor.state.selection.main.head;
            const headers = laidOut.regions.map((each) => each.header.from);
            const target = forward
                ? headers.find((each) => each > head)
                : [...headers].reverse().find((each) => each < head);
            if (target !== undefined) {
                editor.dispatch({ selection: { anchor: target }, scrollIntoView: true });
            }
        },
        approve: (_cm, approved) => {
            const editor = view.current;
            const region = editor === null ? undefined : regionAt(laidOut.regions, editor.state.selection.main.head);
            if (region?.item.reason.reason === "approval") {
                approve(region.item.number, approved);
            }
        },
        send,
        expand: () => {
            const editor = view.current;
            const region = editor === null ? undefined : regionAt(laidOut.regions, editor.state.selection.main.head);
            if (region?.item.reason.reason === "approval") {
                open(region.item.number);
            }
        },
    };

    function kept() {
        if (writing !== null && said.trim() !== "") {
            const comment = { item: writing.item, quote: writing.quote, text: said.trim() };
            change({ ...draft, comments: [...(draft.comments ?? []), comment] });
        }
        setWriting(null);
        setSaid("");
        view.current?.focus();
    }

    const onWhat =
        writing === null
            ? ""
            : writing.item === null
              ? "the whole reply"
              : writing.quote === null
                ? `item #${writing.item}`
                : `“${writing.quote.text}” in #${writing.item}`;

    return (
        <div className="review">
            <div className="review-buffer" ref={parent} />
            {writing === null ? null : (
                <div className="writing">
                    <div className="writing-on">Comment on {onWhat}</div>
                    <textarea
                        aria-label={`Comment on ${onWhat}`}
                        autoFocus
                        value={said}
                        onChange={(event) => setSaid(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                                event.preventDefault();
                                kept();
                            }
                            if (event.key === "Escape") {
                                event.preventDefault();
                                setWriting(null);
                                setSaid("");
                                view.current?.focus();
                            }
                        }}
                    />
                    <div className="muted">
                        <kbd>Ctrl</kbd> <kbd>Enter</kbd> keeps it · <kbd>Esc</kbd> drops it
                    </div>
                </div>
            )}
            <div className="keys muted">
                <kbd>v</kbd>…<kbd>c</kbd> on a passage · <kbd>C</kbd> on the item · <kbd>c</kbd> on the whole ·{" "}
                <kbd>␣</kbd> <kbd>l</kbd>/<kbd>u</kbd>/<kbd>o</kbd> verdict · <kbd>␣</kbd> <kbd>d</kbd> done ·{" "}
                <kbd>␣</kbd> <kbd>z</kbd> later · <kbd>␣</kbd> <kbd>a</kbd>/<kbd>x</kbd> approve/decline ·{" "}
                <kbd>␣</kbd> <kbd>e</kbd> diff · <kbd>J</kbd>/<kbd>K</kbd> items · <kbd>Ctrl</kbd> <kbd>Enter</kbd> send
            </div>
        </div>
    );
}
