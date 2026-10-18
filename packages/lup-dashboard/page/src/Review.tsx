// The review: everything waiting for the operator in one buffer moved through
// with vim (`editor.ts`), in groups, one per agent, their comments written into
// it, each under the line it's on: `c` opens one on the item whole. Ctrl+Enter
// elsewhere than in a comment sends. Space `d` marks an item read, Space `z`
// leaves it for later, Space `a` or `x` answers an approval; `J` and `K` go to
// the next and previous item. Under each item, its context and an approval's
// whole diff fold, folded until opened (`docs/dashboard.md`, *The review*).
import { RangeSetBuilder } from "@codemirror/state";
import { Decoration, type DecorationSet } from "@codemirror/view";
import { useEffect, useMemo, useRef } from "react";

import { changes, moved } from "./comments";
import { rebuilt, refold, uncovered, useEditor, type Landing } from "./editor";
import {
    foldKey,
    laid,
    onBanner,
    opened,
    quoted,
    regionAt,
    shownAt,
    toggled,
    type Around,
    type Aside,
    type Comment,
    type Draft,
    type Item,
    type Laid,
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
    /** Told each time vim enters or leaves insert mode, so the page can say what the keys do in it. */
    inserting: (yes: boolean) => void;
    /** Changed each time the draft is replaced from outside, as when it's sent: what was done before can't be undone. */
    epoch: number;
    /** Whether the review is shown, rather than a conversation: shown again, it takes the keyboard. */
    shown: boolean;
    /** Give the keyboard to the agents' tree. */
    tree: () => void;
}

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

function when(made: string): string {
    const at = new Date(made);
    return at.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

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

export function Review({ items, draft, change, banner, around, send, approve, inserting, epoch, shown, tree }: Props) {
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
    const laidFor = useMemo(
        () => ({
            text: laidOut.text,
            blocks: laidOut.regions.flatMap((each) => each.blocks),
            folds: laidOut.regions.flatMap((each) => each.folds).map((each) => ({ ...each, key: foldKey(each) })),
        }),
        [laidOut],
    );
    const editor = useEditor<Draft, Comment>({
        shown: laidFor,
        draft,
        comments: (each) => each.comments ?? [],
        withComments: (each, comments) => ({ ...each, comments }),
        change,
        inserting,
        epoch,
        shownNow: shown,
        tree,
    });
    const { view, landing, unfolded } = editor;
    const before = useRef<Laid | null>(null);

    useEffect(() => {
        const current = view.current;
        if (current === null) {
            return;
        }
        const arriving = landing.current;
        const doc = current.state.doc.toString();
        if (doc !== laidOut.text) {
            // Changed line by line, so what the operator reads stays where it is as items come and go
            // above it: the cursor moves with its text, and the view only follows a landing of their own.
            const head = current.state.selection.main.head;
            const made = changes(doc, laidOut.text);
            const anchor =
                arriving === null ? moved(head, made, doc.length) : followed(before.current, laidOut, head, arriving);
            const closed = laidFor.folds.filter((each) => !unfolded.current.has(each.key));
            // Where the view is, anchored to the text at its top and mapped through the changes.
            const changing = current.state.changes(made);
            const kept = current.scrollSnapshot().map(changing);
            current.dispatch({
                changes: changing,
                selection: { anchor: uncovered(closed, anchor) },
                scrollIntoView: arriving !== null,
                annotations: rebuilt.of(true),
            });
            refold(current, laidFor.folds, unfolded.current);
            if (arriving === null && kept !== undefined) {
                current.dispatch({ effects: kept });
            }
        }
        before.current = laidOut;
        landing.current = null;
        editor.draw(decorations(laidOut, draft));
        if (arriving !== null && "comment" in arriving) {
            editor.enter();
        }
    }, [laidOut, draft]);

    function here() {
        return regionAt(laidOut.regions, editor.head());
    }

    editor.bind({
        whole: (position) => {
            const region = regionAt(laidOut.regions, position);
            if (region === undefined || onBanner(region, position)) {
                return undefined;
            }
            return { item: region.item.number, quote: null, text: "" };
        },
        opened: (position) => opened(laidOut, position),
        quoted: (from, to) => quoted(laidOut, from, to),
        about: (comment, block) => {
            const region = regionAt(laidOut.regions, block.from);
            if (region === undefined) {
                return undefined;
            }
            return comment.quote == null ? region.header.from : shownAt(region, comment.quote.start);
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
            editor.record(toggled(editor.latest.current, list, region.item.number));
        },
        move: (forward) => {
            const current = view.current;
            if (current === null) {
                return;
            }
            const head = editor.head();
            const headers = laidOut.regions.map((each) => each.header.from);
            const target = forward
                ? headers.find((each) => each > head)
                : [...headers].reverse().find((each) => each < head);
            if (target !== undefined) {
                current.dispatch({ selection: { anchor: target }, scrollIntoView: true });
            }
        },
        approve: (approved) => {
            const region = here();
            const reason = region?.item.reason.reason;
            if (region !== undefined && (reason === "approval" || reason === "held")) {
                approve(region.item.number, approved);
            }
        },
        send,
    });

    return <div className="buffer review-buffer" ref={editor.parent} />;
}
