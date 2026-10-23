// The review: everything waiting for the operator in one buffer moved through
// with vim (`editor.ts`), in groups, one per agent, every agent running having
// one, empty or not; their comments written into it, each under the line it's
// on: Space `c` opens one on the item whole; `o` or Space `c` on a banner, a
// message to its agent, under the banner; `o` in an agent's drawer, a remark to
// it. Ctrl+Enter elsewhere than in a comment or a message sends. Space `d`
// marks an item read, Space `p` parks it, leaving it for later, Space `a` or
// `x` answers an approval or a held change; `]]` and `[[` go to the next and
// previous item, landing on its first line that matters, `]a` and `[a` to the
// next and previous item to answer, in the order they came, `]c` and `[c` to the
// next and previous such line. Under an approval or a held change, each file it
// changes, whole, its lines numbered, marked and highlighted as they come into
// view, each line that matters by the judge's reading barred and saying what it
// triggered; the item's header counts its files by why each is open; under each
// item, its context. At the end of each agent's group, its drawers
// (`review.ts`): its tasks, its trace, what its branch changed since the
// operator approved it, where Space `a` on a file approves its flags, Space `A`
// marks all of it good and Space `l` brings the latest in, and its conversation;
// `h` on a banner turns the operator's switch to hold the agent's flagged
// writes. Each fold has a kind, its letter in the margin beside its summary
// line, in the column of its depth, a bar under it for each fold the cursor is
// in (`margin.ts`); the context, each run of unchanged lines, each automatic
// file fold and each drawer, folded until opened, and `zr`, `zm`, `zR`, `zM` and
// Space `z` act on the item or the drawer the cursor is in. The header over the
// review says where the cursor is: the group, the item or the drawer, the file
// and the folds it's in, and, while a comment is being written, whom it goes
// to; at its end, how many items are to answer and how many are new
// (`docs/dashboard.md`, *The review*, *The drawers*).
import { RangeSetBuilder, type Range } from "@codemirror/state";
import { Decoration, EditorView, type DecorationSet } from "@codemirror/view";
import { useEffect, useMemo, useRef, useState } from "react";

import { shownOnce, tally, tokensOf, within, type Matter, type Taken } from "./code";
import { changes, cited, moved, shownIn, type Block, type Change, type Folding, type Span } from "./comments";
import { closedAs, folding, isFolded, rebuilt, refold, uncovered, useEditor, type Landing } from "./editor";
import { levelled, ofKind } from "./folds";
import { FOLD_KINDS, type DrawerKind, type ReviewPlace } from "./keys";
import { source, sourced, without, type Source } from "./markdown";
import {
    REPLY_MARK,
    aboutAt,
    answerAfter,
    answering,
    arrival,
    blockAt,
    blocksOf,
    codeAt,
    codeFrom,
    drawerAt,
    foldKey,
    foldsOf,
    fresh,
    groupAt,
    heading,
    isDrawer,
    isLetter,
    isRegion,
    isRemark,
    laid,
    news,
    opened,
    placeAt,
    quoted,
    regionAt,
    sameId,
    scopeAt,
    shownAt,
    shownInReply,
    showing,
    stepped,
    stranded,
    tallied,
    threaded,
    toggled,
    waited,
    whose,
    withWritten,
    written,
    type Around,
    type Aside,
    type Conversation,
    type Draft,
    type Drawer,
    type Drawers,
    type Group,
    type Head,
    type Item,
    type Laid,
    type Region,
    type Scope,
    type Threaded,
    type Where,
    type Written,
} from "./review";

/** Where the page asks the review to go: an agent's group, by its conversation, numbered so the same one asked twice goes twice. */
export interface Jump {
    to: Conversation;
    number: number;
}

interface Props {
    items: Item[];
    /** The conversations running, in the order the host lists them: each has a group, empty or not. */
    agents: Conversation[];
    draft: Draft;
    change: (draft: Draft) => void;
    /** Name a group: the agent that sent its items, or the one it's of, and where; what it's doing; its context. */
    banner: (head: Head) => string;
    /** Name a conversation as it's called, as whom a comment goes to. */
    called: (party: Conversation) => string;
    /** What the host has answered of each item beyond its own text: its context, and each file it changes, an approval's or a held change's. */
    around: Around;
    /** What the host has answered of each agent, for its banner and its drawers. */
    drawers: Drawers;
    send: () => void;
    approve: (number: number, approved: boolean) => void;
    /** Approve the flagged writes on an agent's branch: those on one file, or every one. */
    approveSince: (conversation: Conversation, path: string | null) => void;
    /** Bring the latest of what an agent's branch changed into its drawer. */
    latest: (conversation: Conversation) => void;
    /** Turn the operator's switch for an agent: whether each flagged write of it and its subagents is held. */
    hold: (conversation: Conversation) => void;
    /** Told each drawer the operator opens, so the page reads what it shows. */
    opened: (conversation: Conversation, kind: DrawerKind) => void;
    /** Where the page asks the review to go, as the palette does: an agent's group. */
    jump: Jump | null;
    /** Say something on the page's line of messages, as why a key did nothing. */
    say: (text: string) => void;
    /** Told each time vim enters or leaves insert mode, so the page can say what the keys do in it. */
    inserting: (yes: boolean) => void;
    /** Changed each time the draft is replaced from outside, as when it's sent: what was done before can't be undone. */
    epoch: number;
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

/** Return the classes a line under an item or in a drawer is drawn with: what it shows, and whether it folds under a summary. */
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

/** Every scope laid out, the items' and the drawers', in the text's order. */
function scopesOf(laidOut: Laid): Scope[] {
    return [...laidOut.regions, ...laidOut.drawers].sort((a, b) => a.header.from - b.header.from);
}

/** Paint the changed files' lines from `from` to `to`: each row numbered and marked added, removed or the same, its text highlighted in its file's language, and each that matters barred, saying what it triggered. */
function painted(laidOut: Laid, from: number, to: number): Range<Decoration>[] {
    const ranges: Range<Decoration>[] = [];
    for (const scope of scopesOf(laidOut)) {
        for (let at = codeFrom(scope.code, from); at < scope.code.length; at += 1) {
            const coded = scope.code[at];
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

/**
 * Return what of the review is written in Markdown (`markdown.ts`): each item's own text, its lines whole and the
 * comments under them left out; the agent's words in a context, in a trace and in a conversation, each run of them one,
 * the remarks under them left out; and each comment, message and remark.
 */
function sourcesOf(laidOut: Laid): Source[] {
    const found: Source[] = [];
    const add = (made: Source | null) => {
        if (made !== null) {
            found.push(made);
        }
    };
    const whole = (line: Span) => ({ from: line.from, to: Math.min(line.to + 1, laidOut.text.length) });
    for (const group of laidOut.groups) {
        for (const block of group.blocks) {
            add(source("comment", [block]));
        }
    }
    for (const region of laidOut.regions) {
        add(source("text", region.lines.filter((line) => codeAt(region, line.from) === undefined).map(whole)));
        let run: Span[] = [];
        for (const aside of region.asides) {
            if (aside.kind === "agent" || aside.kind === "you") {
                run.push(whole(aside));
            } else {
                add(source("text", run));
                run = [];
            }
        }
        add(source("text", run));
        // Each reply in the thread under the item, its lines one stretch.
        let reply: Span[] = [];
        let last: Threaded | undefined;
        for (const line of region.threads) {
            if (last !== undefined && !sameId(last.reply.id, line.reply.id)) {
                add(source("text", reply));
                reply = [];
            }
            reply.push(whole(line));
            last = line;
        }
        add(source("text", reply));
        for (const block of region.blocks) {
            add(source("comment", [block]));
        }
    }
    for (const drawer of laidOut.drawers) {
        const talk = drawer.talk;
        if (talk !== null) {
            for (const words of talk.words) {
                const first = words.lines[0];
                const last = words.lines.at(-1);
                if (first !== undefined && last !== undefined) {
                    const span = { from: first.start, to: whole(last).to };
                    add(source("text", without(span, words.blocks.map(whole))));
                }
            }
        }
        for (const block of drawer.blocks) {
            add(source("comment", [block]));
        }
    }
    return found;
}

/** Mark each line of a comment, a message or a remark shown at `block`. */
function remarks(laidOut: Laid, block: Block): { from: number; to: number; value: Decoration }[] {
    const marks: { from: number; to: number; value: Decoration }[] = [];
    let at = block.from;
    for (const line of laidOut.text.slice(block.from, block.to).split("\n")) {
        marks.push({ from: at, to: at, value: Decoration.line({ class: "remark" }) });
        at += line.length + 1;
    }
    return marks;
}

/** Return where a remark's quote is shown in `drawer`: in the agent's words at its step, or in the file's lines; none where it isn't laid out. */
function quotedIn(drawer: Drawer, written: Written): Span | null {
    if (!isRemark(written) || written.quote.end <= written.quote.start) {
        return null;
    }
    const quote = written.quote;
    if (drawer.talk !== null) {
        const words = drawer.talk.words.find((each) => each.step === written.step);
        if (words === undefined) {
            return null;
        }
        return { from: shownIn(words.lines, quote.start, 0), to: shownIn(words.lines, quote.end, 0) };
    }
    return drawer.lines.length === 0 ? null : { from: shownAt(drawer, quote.start), to: shownAt(drawer, quote.end) };
}

/** Return where a comment on `region`'s item quotes, in the item's text or in the reply of the thread it's on; none for a remark, a comment on the whole, or an empty passage. */
function quotedUnder(region: Region, written: Written): Span | null {
    if (isRemark(written) || isLetter(written) || written.quote == null || written.quote.end <= written.quote.start) {
        return null;
    }
    const quote = written.quote;
    const on = written.on ?? null;
    return on === null
        ? { from: shownAt(region, quote.start), to: shownAt(region, quote.end) }
        : { from: shownInReply(region, on, quote.start), to: shownInReply(region, on, quote.end) };
}

/** Draw the review: groups' banners and the messages under them, items' headers, done and parked items, the lines under each item and in each drawer, the changed files' headers, each comment's lines, and the passage each comment is on. */
function decorations(laidOut: Laid, draft: Draft, reviewed: string | null): DecorationSet {
    const marks: { from: number; to: number; value: Decoration }[] = [];
    const comments = written(draft);
    for (const group of laidOut.groups) {
        marks.push({ from: group.banner.from, to: group.banner.from, value: Decoration.line({ class: "review-banner" }) });
        marks.push(...group.blocks.flatMap((block) => remarks(laidOut, block)));
    }
    for (const scope of scopesOf(laidOut)) {
        if (isDrawer(scope)) {
            marks.push({ from: scope.header.from, to: scope.header.from, value: Decoration.line({ class: `drawer-summary drawer-${scope.kind}` }) });
        } else {
            const region = scope as Region;
            const number = region.item.number;
            const states = [
                "review-header",
                fresh(region.item, reviewed) ? "is-new" : "",
                news(region.item) ? "is-news" : "",
                (draft.done ?? []).includes(number) ? "is-done" : "",
                (draft.parked ?? []).includes(number) ? "is-parked" : "",
            ].join(" ");
            marks.push({ from: region.header.from, to: region.header.from, value: Decoration.line({ class: states }) });
        }
        const runs = new Set(scope.folds.filter((each) => each.kind === "lines").map((each) => each.summary.from));
        for (const aside of scope.asides) {
            const classes = asideClasses(aside, runs.has(aside.from));
            marks.push({ from: aside.from, to: aside.from, value: Decoration.line({ class: classes }) });
        }
        const stops = new Set(scope.stops);
        for (const coded of scope.code) {
            if (coded.row === null) {
                const shown = isDrawer(scope) ? "changes" : showing((scope as Region).item);
                const automatic = shownOnce(coded.file, shown).automatic ? " code-automatic" : "";
                const whole = stops.has(coded.from) ? " code-matters" : "";
                marks.push({
                    from: coded.from,
                    to: coded.from,
                    value: Decoration.line({ class: `code-file${automatic}${whole}` }),
                });
            }
        }
        // Each line of a reply in the thread under an item, marked as the agent's answer.
        if (isRegion(scope)) {
            for (const line of scope.threads) {
                marks.push({ from: line.from - REPLY_MARK.length, to: line.from - REPLY_MARK.length, value: Decoration.line({ class: "thread-reply" }) });
            }
        }
        for (const block of scope.blocks) {
            marks.push(...remarks(laidOut, block));
            const comment = comments[block.comment];
            if (comment === undefined || isLetter(comment)) {
                continue;
            }
            const span = isDrawer(scope) ? quotedIn(scope, comment) : quotedUnder(scope as Region, comment);
            if (span !== null && span.to > span.from) {
                marks.push({ from: span.from, to: span.to, value: Decoration.mark({ class: "commented" }) });
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

/**
 * Say what an item is in its header: a message by its kind, or as a turn's end; a held change, or one holding a
 * landing; a stop by choice; or the reason's own name.
 */
function what(item: Item): string {
    const reason = item.reason;
    switch (reason.reason) {
        case "message":
            return reason.ending === true ? "turn ended" : reason.kind;
        case "held":
            return reason.landing == null ? "held change" : "holds a landing";
        case "stop":
            return "stopped";
        case "flagged":
            return "landed, flagged";
        default:
            return reason.reason;
    }
}

/** Say whom the operator's copy of a message between conversations was sent to, after what it is in its header (` to explore-auth`); nothing for any other item. */
function sentTo(item: Item, called: (party: Conversation) => string): string {
    const reason = item.reason;
    return reason.reason === "message" && reason.to != null ? ` to ${called(reason.to)}` : "";
}

/** How an item's header says when it came: made once, since `toLocaleString` makes one at each call, and the review is laid out again at each key typed in a comment. */
const WHEN = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

function when(made: string): string {
    return WHEN.format(new Date(made));
}

/** Return what names an item in the header over the review: the first part of its header, before its first ` · `, without the rule around it. */
function itemNamed(header: string): string {
    const inner = header.slice("── ".length, header.length - " ──".length);
    return inner.split(" · ")[0] ?? inner;
}

/** The header over the review: where the cursor is, each part marked by its kind, and whom what's being written goes to; at its end, what waits below (`tallied`). */
function Heading({ parts, tally }: { parts: Where[]; tally: string }) {
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
                    {tally === "" ? null : <span className="where-tally">{tally}</span>}
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
 * `landing` names, the place carried by the changes `made` to the text `doc`; else on the same item or drawer, as far
 * into it as it was; at the same place where its item is gone.
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
    const was = before === null ? undefined : scopeAt(before, head);
    const now = was === undefined ? undefined : scopesOf(after).find((each) => each.of === was.of);
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
    drawers,
    send,
    approve,
    approveSince,
    latest,
    hold,
    opened: told,
    jump,
    say,
    inserting,
    epoch,
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
                        `${cited(item.number)} ${what(item)}${sentTo(item, called)}`,
                        ...(counted === "" ? [] : [counted]),
                        ...(typing ? ["reading types"] : []),
                        ...(threaded(around.answers, item) ? ["replied"] : []),
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
                drawers,
            ),
        [items, agents, banner, called, draft, around, drawers, reviewed, now],
    );
    const laidFor = useMemo(
        () => ({
            text: laidOut.text,
            blocks: blocksOf(laidOut),
            // In the text's order, as CodeMirror takes the folds a transaction makes: a fold over others, as an
            // automatic file's or an item's marked read, is laid out after them.
            folds: scopesOf(laidOut)
                .flatMap((each) => each.folds)
                .map((each) => ({ ...each, key: foldKey(each) }))
                .sort((a, b) => a.from - b.from || b.to - a.to),
            sources: sourcesOf(laidOut),
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
        shownNow: true,
        say,
        moved: (at) => {
            setHead(at);
            placed(placeAt(laidOut, at));
        },
        list,
        pending,
        margin: true,
        unfolded: (fold) => {
            const drawer = laidOut.drawers.find((each) => each.folds.some((own) => foldKey(own) === fold.key && own.kind === each.kind));
            if (drawer !== undefined) {
                told(drawer.conversation, drawer.kind);
            }
        },
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
            // A comment being written keeps the cursor, as far into it as it was, wherever what arrived moved it;
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
            // What's written in Markdown goes with the text, which is read by it in this transaction.
            current.dispatch({
                changes: changing,
                selection: { anchor: uncovered(closed, anchor) },
                scrollIntoView: landed,
                annotations: rebuilt.of(true),
                effects: sourced.of(laidFor.sources),
            });
            refold(current, laidFor.folds, kept.current);
            // Restored after the folds, whose heights it takes in. It keeps a comment being written where it is on
            // screen too, as only what arrives above moves it; a scroll to the cursor after it would replace it, since
            // CodeMirror keeps the last scroll asked of it alone.
            if (!landed && scrolled !== undefined) {
                current.dispatch({ effects: scrolled });
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

    // Asked to go to an agent's group, as from the palette: onto its banner.
    const jumped = useRef<number>(0);
    useEffect(() => {
        const current = view.current;
        if (jump === null || current === null || jump.number === jumped.current) {
            return;
        }
        jumped.current = jump.number;
        const key = whose(jump.to);
        const group = laidOut.groups.find((each) => each.conversation !== null && whose(each.conversation) === key && !each.later);
        if (group !== undefined) {
            current.dispatch({ selection: { anchor: group.banner.from }, effects: EditorView.scrollIntoView(group.banner.from, { y: "start" }) });
            current.focus();
        }
    }, [jump, laidOut]);

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
        kept.current.delete(foldKey({ of: region.of, kind: "item", name: "" }));
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

    /** Go to `region`'s item, where there's one: onto where it lands (`arrival`), its header kept in view above the line where both fit. */
    function goTo(region: Region | undefined) {
        const current = view.current;
        if (current === null || region === undefined) {
            return;
        }
        const at = arrival(region);
        opening(current, at);
        if (at === region.header.from) {
            current.dispatch({ selection: { anchor: at }, scrollIntoView: true });
            return;
        }
        // Its header stays in view above the line it lands on, where both fit.
        const top = current.lineBlockAt(region.header.from).top;
        const fits = current.lineBlockAt(at).bottom - top < current.scrollDOM.clientHeight * 0.8;
        current.dispatch({
            selection: { anchor: at },
            effects: fits ? EditorView.scrollIntoView(region.header.from, { y: "start" }) : EditorView.scrollIntoView(at, { y: "center" }),
        });
    }

    /** Return the "since you approved" drawer the cursor is in, where it's in one. */
    function sinceHere(): Drawer | undefined {
        const drawer = drawerAt(laidOut, editor.head());
        return drawer?.kind === "since" ? drawer : undefined;
    }

    editor.bind({
        whole: (position) => {
            // On a group, a message to its agent; on an item, a comment on it whole; in a drawer, a remark on its line.
            if (groupAt(laidOut, position) !== undefined || drawerAt(laidOut, position) !== undefined) {
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
            const head = editor.head();
            const landings = laidOut.regions.map((region) => ({ region, at: arrival(region) }));
            const target = forward
                ? landings.find((each) => each.at > head)
                : [...landings].reverse().find((each) => each.at < head);
            goTo(target?.region);
        },
        answer: (forward) => goTo(answerAfter(laidOut, draft, editor.head(), forward)),
        matter: (forward) => {
            const current = view.current;
            if (current === null) {
                return;
            }
            const line = current.state.doc.lineAt(editor.head()).from;
            // An item marked read or left for later, and folded, is put by, as a drawer folded: their lines aren't walked until opened.
            const walked = scopesOf(laidOut).filter(
                (scope) =>
                    !laidFor.folds.some(
                        (fold) => fold.of === scope.of && FOLD_KINDS.some((each) => each.kind === fold.kind && each.own) && isFolded(current.state, fold),
                    ),
            );
            const target = stepped(
                walked.flatMap((scope) => scope.stops),
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
            const drawer = sinceHere();
            if (drawer !== undefined) {
                const coded = codeAt(drawer, editor.head());
                if (coded === undefined) {
                    say("Space a approves a file's flagged writes: put the cursor on one of its lines.");
                } else if (!approved) {
                    say("A flagged write is approved or commented on, never declined.");
                } else {
                    approveSince(drawer.conversation, coded.file.path);
                }
                return;
            }
            const region = here();
            if (region === undefined) {
                return;
            }
            if (answering(region.item).kind === "answer") {
                approve(region.item.number, approved);
            }
        },
        approveAll: () => {
            const drawer = sinceHere();
            if (drawer === undefined) {
                say('Space A marks a "since you approved" drawer good: put the cursor in one.');
                return;
            }
            approveSince(drawer.conversation, null);
        },
        latest: () => {
            const drawer = sinceHere();
            if (drawer === undefined) {
                say('Space l brings the latest into a "since you approved" drawer: put the cursor in one.');
                return;
            }
            latest(drawer.conversation);
        },
        hold: () => {
            const group = groupAt(laidOut, editor.head());
            if (group === undefined || group.conversation === null) {
                return false;
            }
            hold(group.conversation);
            return true;
        },
        send,
        paint: (from, to) => painted(laidOut, from, to),
        level: (position, opening, all, closed) => levelled(scopeFolds(position), closed, opening, all),
        kind: (position, kind, closing, closed) => {
            // On a banner, Space z and a drawer's letter opens that drawer of the agent's.
            const group = groupAt(laidOut, position);
            if (group !== undefined) {
                const drawer = group.drawers.find((each) => each.kind === kind);
                return drawer === undefined ? [] : laidFor.folds.filter((each) => each.of === drawer.of && each.kind === kind && closed(each) !== closing);
            }
            return ofKind(scopeFolds(position), closed, kind, closing);
        },
    });

    /** Return the folds of the item or the drawer `position` is in, as the editor holds them: those the fold keys reach. */
    function scopeFolds(position: number): Folding[] {
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
            <Heading parts={heading(laidOut, Math.min(head, laidOut.text.length), commenting, written(draft), naming)} tally={tallied(items, draft, reviewed)} />
            <div className="buffer review-buffer" ref={editor.parent} />
        </>
    );
}

export type { DrawerKind };
