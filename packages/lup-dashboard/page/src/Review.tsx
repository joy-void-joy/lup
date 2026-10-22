// The review: everything waiting for the operator in one buffer moved through
// with vim (`editor.ts`), in groups, one per agent, every agent running having
// one, empty or not; their comments written into it, each under the line it's
// on: Space `c` opens one on the item whole; `o` or Space `c` on a banner, a
// message to its agent, under the banner. Ctrl+Enter elsewhere than in a comment
// or a message sends. Space `d` marks an item read, Space `p` parks it,
// leaving it for later, Space `a` or `x` answers an approval or a held change;
// `]]` and `[[` go to the next and previous item, landing on its first line that
// matters, `]c` and `[c` to the next and previous such line. Under an approval or
// a held change, each file it changes, whole, its lines numbered, marked and
// highlighted as they come into view, each line that matters by the judge's
// reading barred and saying what it triggered; the item's header counts its files
// by why each is open; under each item, its context. Each fold has a kind,
// marked in the margin beside its summary line, with a bar for each fold the
// cursor is in (`margin.ts`); the context, each run of unchanged lines and each
// automatic file fold, folded until opened, and `zr`, `zm`, `zR`, `zM` and Space
// `z` act on the item the cursor is in. The header over the review says where
// the cursor is: the group, the item, the file and the folds it's in, and,
// while a comment is being written, whom it goes to (`docs/dashboard.md`, *The
// review*).
import { RangeSetBuilder, type Range } from "@codemirror/state";
import { Decoration, EditorView, type DecorationSet } from "@codemirror/view";
import { useEffect, useMemo, useRef, useState } from "react";

import { shownOnce, tally, tokensOf, within, type Matter, type Taken } from "./code";
import { changes, cited, moved, type Block, type Change, type Folding } from "./comments";
import { closedAs, folding, isFolded, rebuilt, refold, uncovered, useEditor, type Landing } from "./editor";
import { levelled, ofKind } from "./folds";
import { FOLD_KINDS, type ReviewPlace } from "./keys";
import {
    aboutAt,
    answering,
    arrival,
    blockAt,
    blocksOf,
    codeFrom,
    flag,
    foldKey,
    foldsOf,
    fresh,
    groupAt,
    heading,
    isLetter,
    laid,
    news,
    opened,
    placeAt,
    quoted,
    regionAt,
    shownAt,
    showing,
    stepped,
    stranded,
    toggled,
    waited,
    withWritten,
    written,
    type Around,
    type Aside,
    type Conversation,
    type Draft,
    type Group,
    type Head,
    type Item,
    type Laid,
    type Region,
    type Where,
    type Written,
} from "./review";

interface Props {
    items: Item[];
    /** The conversations running, in the tree's order: each has a group, empty or not. */
    agents: Conversation[];
    draft: Draft;
    change: (draft: Draft) => void;
    /** Name a group: the agent that sent its items, or the one it's of, and where. */
    banner: (head: Head) => string;
    /** Name a conversation as the tree calls it, as whom a comment goes to. */
    called: (party: Conversation) => string;
    /** What the host has answered of each item beyond its own text: its context, and each file it changes, an approval's, a held change's or a flagged write's. */
    around: Around;
    send: () => void;
    approve: (number: number, approved: boolean) => void;
    /** Say something on the page's line of messages, as why a key did nothing. */
    say: (text: string) => void;
    /** Told each time vim enters or leaves insert mode, so the page can say what the keys do in it. */
    inserting: (yes: boolean) => void;
    /** Changed each time the draft is replaced from outside, as when it's sent: what was done before can't be undone. */
    epoch: number;
    /** Whether the review is shown, rather than a conversation: shown again, it takes the keyboard. */
    shown: boolean;
    /** Give the keyboard to the agents' tree. */
    tree: () => void;
    /** Told where the cursor is, outside insert mode, so the line of keys says what applies there. */
    placed: (place: Exclude<ReviewPlace, "insert">) => void;
    /** Told the keys of a chord begun, so what may follow is shown. */
    pending: (keys: string) => void;
    /** Open the list of every key. */
    list: () => void;
    /** When the operator last settled an item of theirs: what came after is new to them. */
    reviewed: string | null;
    /** The time, to the minute, which each item's wait is told from. */
    now: Date;
}

/** Return the classes a line under an item is drawn with: what it shows, and whether it folds under a summary. */
function asideClasses(aside: Aside, code: boolean): string {
    const under = aside.kind === "summary" || aside.kind === "refused" ? null : "aside-under";
    return [`aside-${aside.kind}`, under, code ? "code-run" : null].filter((each) => each !== null).join(" ");
}

/** How a changed file's line is marked after its number: added, removed, or neither. */
const SIGNS = { added: "+", removed: "−", same: " " } as const;

/** Return what a changed file's line shows in its gutter: its number, then its mark, in the gutter's width. */
function gutter(number: number, change: keyof typeof SIGNS): string {
    return `${`${number}`.padStart(5)} ${SIGNS[change]} `;
}

/** Each class of highlighting, as one mark, made once. */
const MARKS = new Map<string, Decoration>();

function marked(classes: string): Decoration {
    const found = MARKS.get(classes);
    if (found !== undefined) {
        return found;
    }
    const made = Decoration.mark({ class: classes });
    MARKS.set(classes, made);
    return made;
}

/** The order of what a line triggered, the first the strongest: what its bar is drawn as. */
const WEIGHTS: Taken[] = ["held", "flagged", "told"];

/** Return how a line that matters is drawn: its classes, its bar as the strongest of what it triggered, and what it says at its end, each said after how it's taken. */
function mattering(matter: Matter | null): { classes: string; said: Record<string, string> } {
    if (matter === null) {
        return { classes: "", said: {} };
    }
    const strongest = WEIGHTS.find((weight) => matter.notes.some((note) => note.taken === weight));
    const classes = ` code-matters${strongest === undefined ? "" : ` code-${strongest}`}`;
    if (matter.notes.length === 0) {
        return { classes, said: {} };
    }
    const said = matter.notes.map((note) => `${note.taken}: ${note.said}`).join(" · ");
    return { classes, said: { "data-said": said } };
}

/** Paint the changed files' lines from `from` to `to`: each row numbered and marked added, removed or the same, its text highlighted in its file's language, and each that matters barred, saying what it triggered. */
function painted(laidOut: Laid, from: number, to: number): Range<Decoration>[] {
    const ranges: Range<Decoration>[] = [];
    for (const region of laidOut.regions) {
        for (let at = codeFrom(region.code, from); at < region.code.length; at += 1) {
            const coded = region.code[at];
            if (coded === undefined || coded.from > to) {
                break;
            }
            const row = coded.row;
            if (row === null) {
                continue;
            }
            const matters = mattering(coded.matter);
            const line = Decoration.line({
                class: `code-row code-${row.change}${matters.classes}`,
                attributes: { "data-gutter": gutter(row.number, row.change), ...matters.said },
            });
            ranges.push(line.range(coded.from));
            for (const token of within(tokensOf(coded.file, row.side), row)) {
                ranges.push(marked(token.classes).range(coded.from + token.from, coded.from + token.to));
            }
        }
    }
    return ranges;
}

/** Mark each line of a comment or a message shown at `block`. */
function remarks(laidOut: Laid, block: Block): { from: number; to: number; value: Decoration }[] {
    const marks: { from: number; to: number; value: Decoration }[] = [];
    let at = block.from;
    for (const line of laidOut.text.slice(block.from, block.to).split("\n")) {
        marks.push({ from: at, to: at, value: Decoration.line({ class: "remark" }) });
        at += line.length + 1;
    }
    return marks;
}

/** Draw the review: groups' banners and the messages under them, items' headers, done and parked items, the lines under each item, the changed files' headers, each comment's lines, and the passage each comment is on. */
function decorations(laidOut: Laid, draft: Draft, reviewed: string | null): DecorationSet {
    const marks: { from: number; to: number; value: Decoration }[] = [];
    const comments = written(draft);
    for (const group of laidOut.groups) {
        marks.push({ from: group.banner.from, to: group.banner.from, value: Decoration.line({ class: "review-banner" }) });
        marks.push(...group.blocks.flatMap((block) => remarks(laidOut, block)));
    }
    for (const region of laidOut.regions) {
        const number = region.item.number;
        const states = [
            "review-header",
            fresh(region.item, reviewed) ? "is-new" : "",
            news(region.item) ? "is-news" : "",
            flag(region.item) ? "is-flag" : "",
            (draft.done ?? []).includes(number) ? "is-done" : "",
            (draft.parked ?? []).includes(number) ? "is-parked" : "",
        ].join(" ");
        marks.push({ from: region.header.from, to: region.header.from, value: Decoration.line({ class: states }) });
        const runs = new Set(region.folds.filter((each) => each.kind === "lines").map((each) => each.summary.from));
        for (const aside of region.asides) {
            const classes = asideClasses(aside, runs.has(aside.from));
            marks.push({ from: aside.from, to: aside.from, value: Decoration.line({ class: classes }) });
        }
        const stops = new Set(region.stops);
        for (const coded of region.code) {
            if (coded.row === null) {
                const automatic = shownOnce(coded.file, showing(region.item)).automatic ? " code-automatic" : "";
                const whole = stops.has(coded.from) ? " code-matters" : "";
                marks.push({
                    from: coded.from,
                    to: coded.from,
                    value: Decoration.line({ class: `code-file${automatic}${whole}` }),
                });
            }
        }
        for (const block of region.blocks) {
            marks.push(...remarks(laidOut, block));
            const comment = comments[block.comment];
            const quote = comment === undefined || isLetter(comment) ? null : comment.quote;
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

/** Say what an item is in its header: a message by its kind, or as a turn's end; a held change, a stop by choice, a write that landed flagged, with how many writes it gathers, or the reason's own name. */
function what(item: Item): string {
    const reason = item.reason;
    switch (reason.reason) {
        case "message":
            return reason.ending === true ? "turn ended" : reason.kind;
        case "held":
            return "held change";
        case "stop":
            return "stopped";
        case "flagged":
            return reason.writes > 1 ? `landed, flagged · ${reason.writes} writes` : "landed, flagged";
        default:
            return reason.reason;
    }
}

function when(made: string): string {
    const at = new Date(made);
    return at.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Return what names an item in the header over the review: the first part of its header, before its first ` · `, without the rule around it. */
function itemNamed(header: string): string {
    const inner = header.slice("── ".length, header.length - " ──".length);
    return inner.split(" · ")[0] ?? inner;
}

/** The header over the review: where the cursor is, each part marked by its kind, and whom what's being written goes to. */
function Heading({ parts }: { parts: Where[] }) {
    const letter = (kind: Where["kind"]) => FOLD_KINDS.find((each) => each.kind === kind)?.letter ?? null;
    // A body around another, which a narrow screen leaves out for the innermost.
    const inner = parts.findLast((each) => each.kind === "body");
    const shown = (part: Where) => (
        <span
            key={`${part.kind} ${part.text}`}
            className={`where-part where-${part.kind}${part.kind === "body" && part !== inner ? " where-outer" : ""}`}
            title={part.text}
        >
            {letter(part.kind) === null ? null : <span className="where-mark">{letter(part.kind)}</span>}
            {/* A path keeps its end in view where it's cut, the file's name. */}
            {part.kind === "file" ? <bdi className="where-text">{part.text}</bdi> : <span className="where-text">{part.text}</span>}
        </span>
    );
    const who = parts.filter((each) => each.kind === "to" || each.kind === "group");
    const path = parts.filter((each) => each.kind !== "to" && each.kind !== "group");
    return (
        <div className="where">
            {parts.length === 0 ? (
                <span className="where-who muted">nothing waiting</span>
            ) : (
                <>
                    <span className="where-who">{who.map(shown)}</span>
                    <span className="where-path">{path.map(shown)}</span>
                </>
            )}
        </div>
    );
}

/** Return where the cursor goes in the comment or message being written at `head` once the text is laid out again: as far into the same one as it was, wherever an item arriving moved it; none where it isn't in one. */
function writtenAt(before: Laid | null, after: Laid, head: number): number | undefined {
    const was = before === null ? undefined : blockAt(before, head);
    if (was === undefined) {
        return undefined;
    }
    const now = blocksOf(after).find((each) => each.comment === was.comment);
    return now === undefined ? undefined : Math.min(now.from + (head - was.from), now.to);
}

/**
 * Return where the cursor goes once the text is laid out again: into the comment, onto the item or to the place
 * `landing` names, the place carried by the changes `made` to the text `doc`; else on the same item, as far into it as
 * it was; at the same place where its item is gone.
 */
function followed(before: Laid | null, after: Laid, head: number, made: Change[], doc: string, landing: Landing): number {
    const clamped = Math.min(head, after.text.length);
    if (landing !== null && "at" in landing) {
        return moved(landing.at, made, doc);
    }
    if (landing !== null && "comment" in landing) {
        const block = blocksOf(after).find((each) => each.comment === landing.comment);
        return block?.from ?? clamped;
    }
    if (landing !== null) {
        return after.regions.find((each) => each.item.number === landing.item)?.header.from ?? clamped;
    }
    const was = before === null ? undefined : regionAt(before, head);
    const now = was === undefined ? undefined : after.regions.find((each) => each.item.number === was.item.number);
    if (was === undefined || now === undefined) {
        return clamped;
    }
    return Math.max(Math.min(now.header.from + (head - was.header.from), after.text.length), 0);
}

export function Review({
    items,
    agents,
    draft,
    change,
    banner,
    called,
    around,
    send,
    approve,
    say,
    inserting,
    epoch,
    shown,
    tree,
    placed,
    pending,
    list,
    reviewed,
    now,
}: Props) {
    // Where the cursor is, and whether a comment is being written: what the header says.
    const [head, setHead] = useState(0);
    const [commenting, setCommenting] = useState(false);
    // Where the groups were laid out this sitting, which ends once nothing's left to read: each keeps its place.
    const places = useRef<string[]>([]);
    const laidOut = useMemo(
        () =>
            laid(
                items,
                agents,
                (head, later) => `━━ ${banner(head)}${later ? " · later" : ""} ━━`,
                (item, later) => {
                    const files = around.files.get(item.number);
                    const counted = files !== undefined && "shown" in files ? tally(files.shown) : "";
                    const typing = item.reason.reason === "approval" && item.reason.typing;
                    const told = [
                        `${cited(item.number)} ${what(item)}`,
                        ...(counted === "" ? [] : [counted]),
                        ...(typing ? ["reading types"] : []),
                        ...(fresh(item, reviewed) ? ["new"] : []),
                        when(item.made),
                        waited(item.made, now),
                        ...(later ? ["later"] : []),
                    ];
                    return `── ${told.join(" · ")} ──`;
                },
                draft,
                around,
                places.current,
            ),
        [items, agents, banner, draft, around, reviewed, now],
    );
    const laidFor = useMemo(
        () => ({
            text: laidOut.text,
            blocks: blocksOf(laidOut),
            // In the text's order, as CodeMirror takes the folds a transaction makes: a fold over others, as an
            // automatic file's or an item's marked read, is laid out after them.
            folds: laidOut.regions
                .flatMap((each) => each.folds)
                .map((each) => ({ ...each, key: foldKey(each) }))
                .sort((a, b) => a.from - b.from || b.to - a.to),
        }),
        [laidOut],
    );
    const editor = useEditor<Draft, Written>({
        shown: laidFor,
        draft,
        comments: written,
        withComments: withWritten,
        change,
        inserting: (yes) => {
            setCommenting(yes);
            inserting(yes);
        },
        epoch,
        shownNow: shown,
        tree,
        say,
        moved: (at) => {
            setHead(at);
            placed(placeAt(laidOut, at));
        },
        list,
        pending,
        margin: true,
    });
    const { view, landing, kept } = editor;
    const before = useRef<Laid | null>(null);
    // What was written as it was last laid out.
    const wrote = useRef<Written[]>([]);

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
            // A comment being written keeps the cursor, though what arrived moved it, as its agent's group comes first;
            // one just opened takes it, though vim moved it into another under the same line, as `S` does.
            const writing = arriving === null && editor.writing() ? writtenAt(before.current, laidOut, head) : undefined;
            // What it was on gone, as a reply sent takes what it covered, it goes back to what that was about.
            const away =
                arriving === null && writing === undefined && before.current !== null
                    ? stranded(before.current, wrote.current, laidOut, written(draft), head)
                    : undefined;
            const anchor =
                writing ??
                away ??
                (arriving === null ? moved(head, made, doc) : followed(before.current, laidOut, head, made, doc, arriving));
            const landed = arriving !== null || away !== undefined;
            const closed = laidFor.folds.filter((each) => closedAs(each, kept.current));
            // Where the view is, anchored to the text at its top and mapped through the changes.
            const changing = current.state.changes(made);
            const scrolled = current.scrollSnapshot().map(changing);
            current.dispatch({
                changes: changing,
                selection: { anchor: uncovered(closed, anchor) },
                scrollIntoView: landed,
                annotations: rebuilt.of(true),
            });
            refold(current, laidFor.folds, kept.current);
            if (!landed && scrolled !== undefined) {
                current.dispatch({ effects: scrolled });
            }
            if (writing !== undefined) {
                current.dispatch({ effects: EditorView.scrollIntoView(writing, { y: "nearest" }) });
            }
        } else {
            // What folds can change with the text the same, as an item marked read folds.
            refold(current, laidFor.folds, kept.current);
        }
        before.current = laidOut;
        wrote.current = written(draft);
        places.current = items.length === 0 ? [] : laidOut.groups.map((each) => each.place);
        landing.current = null;
        editor.draw(decorations(laidOut, draft, reviewed));
        if (arriving !== null && "comment" in arriving) {
            editor.enter();
        }
    }, [laidOut, draft, reviewed]);

    function here() {
        return regionAt(laidOut, editor.head());
    }

    /** Mark the item the cursor is in read, or left for later, folding it; or unmark it. */
    function toggle(list: "done" | "parked") {
        const region = here();
        if (region === undefined) {
            return;
        }
        if (list === "parked") {
            const at = laidOut.regions.indexOf(region);
            landing.current = { item: (laidOut.regions[at + 1] ?? region).item.number };
        }
        // Marked or unmarked, it folds as that says, however it was left before.
        kept.current.delete(foldKey({ item: region.item.number, kind: "item", name: "" }));
        editor.record(toggled(editor.latest.current, list, region.item.number));
    }

    /** Open each fold over `target`, as a motion into it would, so the line it's on is in view. */
    function opening(current: EditorView, target: number) {
        const effects = laidFor.folds
            .filter((fold) => target > fold.from && target <= fold.to && isFolded(current.state, fold))
            .map((fold) => folding(fold, false));
        if (effects.length > 0) {
            current.dispatch({ effects });
        }
    }

    editor.bind({
        whole: (position) => {
            // On a group, a message to its agent; on an item, a comment on it whole.
            if (groupAt(laidOut, position) !== undefined) {
                return opened(laidOut, position);
            }
            const region = regionAt(laidOut, position);
            return region === undefined ? undefined : { item: region.item.number, quote: null, text: "" };
        },
        opened: (position) => opened(laidOut, position),
        quoted: (from, to) => quoted(laidOut, from, to),
        about: (comment, block) => aboutAt(laidOut, comment, block),
        toggle,
        move: (forward) => {
            const current = view.current;
            if (current === null) {
                return;
            }
            const head = editor.head();
            const landings = laidOut.regions.map((region) => ({ region, at: arrival(region) }));
            const target = forward
                ? landings.find((each) => each.at > head)
                : [...landings].reverse().find((each) => each.at < head);
            if (target === undefined) {
                return;
            }
            opening(current, target.at);
            if (target.at === target.region.header.from) {
                current.dispatch({ selection: { anchor: target.at }, scrollIntoView: true });
                return;
            }
            // Its header stays in view above the line it lands on, where both fit.
            const top = current.lineBlockAt(target.region.header.from).top;
            const fits = current.lineBlockAt(target.at).bottom - top < current.scrollDOM.clientHeight * 0.8;
            current.dispatch({
                selection: { anchor: target.at },
                effects: fits
                    ? EditorView.scrollIntoView(target.region.header.from, { y: "start" })
                    : EditorView.scrollIntoView(target.at, { y: "center" }),
            });
        },
        matter: (forward) => {
            const current = view.current;
            if (current === null) {
                return;
            }
            const line = current.state.doc.lineAt(editor.head()).from;
            // An item marked read or left for later, and folded, is put by: its lines aren't walked until it's opened.
            const walked = laidOut.regions.filter(
                (region) =>
                    !laidFor.folds.some(
                        (fold) => fold.kind === "item" && fold.item === region.item.number && isFolded(current.state, fold),
                    ),
            );
            const target = stepped(
                walked.flatMap((region) => region.stops),
                line,
                forward,
            );
            if (target === undefined) {
                return;
            }
            opening(current, target);
            current.dispatch({
                selection: { anchor: target },
                effects: EditorView.scrollIntoView(target, { y: "nearest", yMargin: current.scrollDOM.clientHeight / 3 }),
            });
        },
        approve: (approved) => {
            const region = here();
            if (region === undefined) {
                return;
            }
            const does = answering(region.item, approved);
            switch (does.kind) {
                case "answer":
                    approve(region.item.number, approved);
                    return;
                case "read":
                    toggle("done");
                    return;
                case "say":
                    say(does.text);
                    return;
                case "nothing":
                    return;
            }
        },
        send,
        paint: (from, to) => painted(laidOut, from, to),
        level: (position, opening, all, closed) => levelled(itemFolds(position), closed, opening, all),
        kind: (position, kind, closing, closed) => ofKind(itemFolds(position), closed, kind, closing),
    });

    /** Return the folds of the item `position` is in, as the editor holds them: those the fold keys of an item reach. */
    function itemFolds(position: number): Folding[] {
        const keys = new Set(foldsOf(laidOut, position).map(foldKey));
        return laidFor.folds.filter((each) => keys.has(each.key));
    }

    const naming = {
        group: (group: Group) => banner(group.head),
        item: (region: Region) => itemNamed(laidOut.text.slice(region.header.from, region.header.to)),
        party: called,
    };
    return (
        <>
            <Heading parts={heading(laidOut, Math.min(head, laidOut.text.length), commenting, written(draft), naming)} />
            <div className="buffer review-buffer" ref={editor.parent} />
        </>
    );
}
