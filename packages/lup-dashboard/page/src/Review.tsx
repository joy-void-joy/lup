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
// (`review.ts`): its tasks, what its branch changed since the operator last saw
// it, live, where Space `a` marks a file reviewed at the version shown and Space
// `A` every file shown, each line changed since they last looked at its file
// marked (`since.ts`), and its conversation, each call's input and output read
// as its fold opens;
// `h` on a banner turns the operator's switch to hold the agent's flagged
// writes. Each fold has a kind, its letter in the margin beside its summary
// line, in the column of its depth, a bar under it for each fold the cursor is
// in (`margin.ts`); the context, each run of unchanged lines, each test, data
// and first approval's file and each drawer but "since you approved", folded until opened, and `zr`, `zm`, `zR`, `zM` and
// Space `z` act on the item or the drawer the cursor is in. The header over the
// review says where the cursor is: the group, the item or the drawer, the file
// and the folds it's in, and, while a comment is being written, whom it goes
// to; at its end, how many items are to answer and how many are new. As what
// it shows changes, the cursor's line stays where it is on screen, so nothing
// arriving above moves what the operator reads. An agent's answer shows the
// operator's words it answers above it, each of its citations of them as its
// id, the passage it cites folded under its line, opened by a click on the id,
// and the passage it answers marked among the operator's words, a click there
// going to it (`exchange.ts`; `docs/dashboard.md`, *The review*, *The
// drawers*).
import { foldedRanges } from "@codemirror/language";
import { RangeSetBuilder, StateEffect, type Range } from "@codemirror/state";
import { Decoration, EditorView, type DecorationSet } from "@codemirror/view";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { shownOnce, tally, tokensOf, within, type ChangedFile, type Matter, type Taken } from "./code";
import { changes, cited, moved, shownIn, type Block, type Change, type Folding, type Span } from "./comments";
import { closedAs, folding, hiddenAt, isFolded, reached, reaching, rebuilt, refold, scrollAfterKey, uncovered, useEditor, type Landing } from "./editor";
import { Following } from "./follow";
import { timed } from "./timing";
import { mapOutlineKey, Outline, setOutlineFocus, useNarrow } from "./Outline";
import { Stack, type Mark as StackMark } from "./Stack";
import { linesOver, stickies, type Sticky } from "./stack";
import { rowed, stacked, type Trials } from "./trials";
import { levelled, ofKind } from "./folds";
import { FOLD_KINDS, type DrawerKind, type ReviewPlace } from "./keys";
import { markerEnd, outdated, unfound } from "./exchange";
import { source, sourced, without, type Source } from "./markdown";
import {
    aboutAt,
    answerAfter,
    citationsOf,
    following,
    answering,
    arrival,
    blockAt,
    blocksOf,
    codeAt,
    codeFrom,
    drawerAt,
    fileHeads,
    firstApproval,
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
    recipient,
    regionAt,
    sameId,
    scopeAt,
    shownAt,
    sinceFileAt,
    stepped,
    stranded,
    tallied,
    toggled,
    waited,
    whose,
    withWritten,
    written,
    type Around,
    type Aside,
    type Cited,
    type Conversation,
    type Draft,
    type Drawer,
    type Drawers,
    type Group,
    type Head,
    type Item,
    type Laid,
    type Region,
    type RowLabel,
    type Scope,
    type SinceFile,
    type Viewed,
    type Where,
    type Written,
} from "./review";
import { freshRows, type Fresh } from "./since";

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
    /** Mark files of an agent's branch reviewed at the versions shown, approving their flags where they stand so. */
    reviewSince: (conversation: Conversation, files: Viewed[]) => void;
    /** Turn the operator's switch for an agent: whether each flagged write of it and its subagents is held. */
    hold: (conversation: Conversation) => void;
    /** Told each drawer the operator opens, so the page reads what it shows. */
    opened: (conversation: Conversation, kind: DrawerKind) => void;
    /** Told the calls whose input and output the operator opens in an agent's conversation, so the page reads them whole. */
    details: (conversation: Conversation, ids: string[]) => void;
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
    /** The layout trials as they stand (`trials.ts`). */
    trials: Trials;
    /** Each conversation's parent, by `whose` each is: what nests a subagent's group, and the outline's tree. */
    parents: ReadonlyMap<string, string>;
    /** What each conversation running is doing, by `whose` it is, for the outline's marks. */
    states: ReadonlyMap<string, string | null>;
    /** Whether the outline is open as an overlay, on a narrow screen. */
    outlining: boolean;
    setOutlining: (open: boolean) => void;
}

/** Return the classes a line under an item or in a drawer is drawn with: what it shows, and whether it's set in under a summary or a file's header, as a file's reviewed line isn't. */
function asideClasses(aside: Aside, code: boolean): string {
    const under = aside.kind === "summary" || aside.kind === "refused" || aside.kind === "reviewed" ? null : "aside-under";
    return [`aside-${aside.kind}`, under, code ? "code-run" : null].filter((each) => each !== null).join(" ");
}

/** How a changed file's line is marked after its number: added, removed, or neither. */
const SIGNS = { added: "+", removed: "−", same: " " } as const;

/** Return what a changed file's line shows in its gutter: its number, a dot where it changed since the operator last looked at its file, then its mark, in the gutter's width. */
function gutter(number: number, change: keyof typeof SIGNS, fresh: boolean = false): string {
    return `${`${number}`.padStart(5)}${fresh ? "•" : " "}${SIGNS[change]} `;
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

/** Which lines of a file in `scope` changed since the operator last looked at it; none outside "since you approved". */
type Freshness = (scope: Scope, file: ChangedFile) => Fresh | null;

/** Paint the changed files' lines from `from` to `to`: each row numbered and marked added, removed or the same, its text highlighted in its file's language, each that matters barred, saying what it triggered, and each changed since the operator last looked at its file (`fresh`) marked. */
function painted(laidOut: Laid, from: number, to: number, fresh: Freshness): Range<Decoration>[] {
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
            const since = fresh(scope, coded.file);
            const changed = since?.rows.has(row) === true;
            const gap = since?.gaps.has(row) === true ? " code-gap" : "";
            const line = Decoration.line({
                class: `code-row code-${row.change}${matters.classes}${changed ? " code-fresh" : ""}${gap}`,
                attributes: { "data-gutter": gutter(row.number, row.change, changed), ...matters.said },
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
 * comments under them left out; the agent's words in a context and in a conversation, each run of them one,
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
        const text = source("text", region.lines.filter((line) => codeAt(region, line.from) === undefined).map(whole));
        // Each citation that found its passage shows its id alone, its words hidden: the passage unfolds under its line.
        const hidden = (region.item.citations ?? []).flatMap((each) =>
            each.found == null || markerEnd(each) >= each.end ? [] : [{ from: shownAt(region, markerEnd(each)), to: shownAt(region, each.end) }],
        );
        // Each that found none, or several, shows as written, its brackets kept.
        const written = (region.item.citations ?? []).flatMap((each) => (each.found == null ? [{ from: shownAt(region, each.start), to: shownAt(region, each.end) }] : []));
        add(text === null ? null : { ...text, hidden, written });
        let run: Span[] = [];
        for (const aside of region.asides) {
            if (aside.kind === "agent" || aside.kind === "you" || aside.kind === "cited") {
                run.push(whole(aside));
            } else {
                add(source("text", run));
                run = [];
            }
        }
        add(source("text", run));
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

/** Return where a comment on `region`'s item quotes in the item's text; none for a remark, a comment on the whole, one copies before kept on a reply, or an empty passage. */
function quotedUnder(region: Region, written: Written): Span | null {
    if (isRemark(written) || isLetter(written) || written.quote == null || written.on != null || written.quote.end <= written.quote.start) {
        return null;
    }
    return { from: shownAt(region, written.quote.start), to: shownAt(region, written.quote.end) };
}

/**
 * Return what the citations of the operator's words in agents' answers draw (`citationsOf`): each that found its
 * passage, its id marked as a citation, saying the passage on hover, and the passage among the operator's words above
 * marked as answered there, saying where; each that found none, or several, marked as written, saying why.
 */
function citing(cited: Cited[]): { from: number; to: number; value: Decoration }[] {
    return cited.flatMap(({ citation, written, marker, passages }) => {
        const found = citation.found;
        if (found == null) {
            return [{ ...written, value: Decoration.mark({ class: "citation-unresolved", attributes: { title: unfound(citation) } }) }];
        }
        const title = `you, @${found.part.item}.${found.part.part}: ${found.text}\n(za or a click opens it under the line, gd goes to it above; ]q [q move between citations)`;
        const answered = Decoration.mark({ class: "answered", attributes: { title: "answered below: gd or a click goes to it", "data-answered": `${written.from}` } });
        return [
            { ...marker, value: Decoration.mark({ class: "citation", attributes: { title } }) },
            ...passages.map((each) => ({ ...each, value: answered })),
        ];
    });
}

/** Return the classes a group's banner is drawn with: set in by how deep it's nested, where it is. */
function bannerClasses(depth: number): string {
    return depth > 0 ? `review-banner is-nested nest-${Math.min(depth, 4)}` : "review-banner";
}

/**
 * Draw the review: groups' banners and the messages under them, items' headers, done and parked items, the lines under
 * each item and in each drawer, the changed files' headers, each comment's lines, and the passage each comment is on.
 * A banner nested under its parent's is set in; the row of a group's drawers has each label marked, pulling its drawer
 * out on a click; and where `to` says it, each comment, message and remark says whom it reaches on its first line.
 */
function decorations(laidOut: Laid, draft: Draft, reviewed: string | null, to: ((written: Written) => string) | null = null): DecorationSet {
    const marks: { from: number; to: number; value: Decoration }[] = [];
    const comments = written(draft);
    const reaching = (block: Block) => {
        const comment = comments[block.comment];
        if (to !== null && comment !== undefined) {
            marks.push({ from: block.from, to: block.from, value: Decoration.line({ class: "remark-to", attributes: { "data-to": to(comment) } }) });
        }
    };
    for (const group of laidOut.groups) {
        marks.push({ from: group.banner.from, to: group.banner.from, value: Decoration.line({ class: bannerClasses(group.depth) }) });
        marks.push(...group.blocks.flatMap((block) => remarks(laidOut, block)));
        group.blocks.forEach(reaching);
        if (group.row !== null) {
            marks.push({ from: group.row.from, to: group.row.from, value: Decoration.line({ class: "drawer-row" }) });
            for (const label of group.row.labels) {
                const classes = `row-label row-${label.kind}${label.pulled ? " is-pulled" : ""}${label.waiting ? " is-waiting" : ""}`;
                marks.push({ from: label.from, to: label.to, value: Decoration.mark({ class: classes, attributes: { "data-pull": label.of, title: label.pulled ? "put it back in the row" : "pull it out below the row" } }) });
            }
        }
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
                const first = !isDrawer(scope) && firstApproval((scope as Region).item);
                const automatic = shownOnce(coded.file, first).automatic ? " code-automatic" : "";
                const whole = stops.has(coded.from) ? " code-matters" : "";
                marks.push({
                    from: coded.from,
                    to: coded.from,
                    value: Decoration.line({ class: `code-file${automatic}${whole}` }),
                });
            }
        }
        // Each of an item's lines an edit changed, barred.
        if (isRegion(scope)) {
            for (const at of scope.changed) {
                marks.push({ from: at, to: at, value: Decoration.line({ class: "edited-line" }) });
            }
        }
        for (const block of scope.blocks) {
            marks.push(...remarks(laidOut, block));
            reaching(block);
            const comment = comments[block.comment];
            if (comment === undefined || isLetter(comment)) {
                continue;
            }
            // A comment on a passage an edit changed since it was written is said to be outdated.
            if (!isRemark(comment) && isRegion(scope) && outdated(scope.item, comment.quote)) {
                marks.push({ from: block.from, to: block.from, value: Decoration.line({ class: "outdated", attributes: { "data-said": "outdated: the passage changed" } }) });
            }
            const span = isDrawer(scope) ? quotedIn(scope, comment) : quotedUnder(scope as Region, comment);
            if (span !== null && span.to > span.from) {
                marks.push({ from: span.from, to: span.to, value: Decoration.mark({ class: "commented" }) });
            }
        }
    }
    marks.push(...citing(citationsOf(laidOut)));
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

/** Return what names a file of a "since you approved" drawer among what the operator looked at: the drawer, and its path. */
function lookedAt(of: string, path: string): string {
    return `${of}\n${path}`;
}

/** Return a file of a "since you approved" drawer as marking it reviewed names it: its path, and the version shown. */
function viewed(file: SinceFile): Viewed {
    return { path: file.path, version: file.version ?? null };
}

/** Return how far below the top of the view the start of the line at `head` is, as a scroll to it measures it, where it's in view; none where it isn't. */
function screenOffset(view: EditorView, head: number): number | null {
    const start = view.coordsAtPos(view.state.doc.lineAt(head).from);
    const top = start === null ? -1 : start.top - view.scrollDOM.getBoundingClientRect().top;
    return top >= 0 && top < view.scrollDOM.clientHeight ? top : null;
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
    reviewSince,
    hold,
    opened: told,
    details,
    jump,
    say,
    inserting,
    epoch,
    placed,
    pending,
    list,
    reviewed,
    now,
    trials,
    parents,
    states,
    outlining,
    setOutlining,
}: Props) {
    // Where the cursor is, and whether a comment is being written: what the header says.
    const [head, setHead] = useState(0);
    const [commenting, setCommenting] = useState(false);
    // Where the groups were laid out this sitting, which ends once nothing's left to read: each keeps its place.
    const places = useRef<string[]>([]);
    // The drawers pulled out of the row under their banner, where the drawers are a row, by what names each (`ownerOf`).
    const [pulled, setPulled] = useState<ReadonlySet<string>>(new Set());
    const narrow = useNarrow();
    const stacking = stacked(trials);
    const arranging = useMemo(
        () => ({ parents: trials.nest ? parents : null, row: rowed(trials) ? { pulled } : null }),
        [trials, parents, pulled],
    );
    const laidOut = useMemo(
        () =>
            timed("lup-laid", () => laid(
                items,
                agents,
                (head, later) => `━━ ${banner(head)}${later ? " · later" : ""} ━━`,
                (item, later) => {
                    const files = around.files.get(item.number);
                    const counted = files !== undefined && "shown" in files ? tally(files.shown, firstApproval(item)) : "";
                    const typing = item.reason.reason === "approval" && item.reason.typing;
                    const told = [
                        `${cited(item.number)} ${what(item)}${sentTo(item, called)}`,
                        ...(counted === "" ? [] : [counted]),
                        ...(typing ? ["reading types"] : []),
                        ...((item.edits ?? []).length > 0 ? ["edited"] : []),
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
                called,
                arranging,
            )),
        [items, agents, banner, called, draft, around, drawers, reviewed, now, arranging],
    );
    // The scopes the header stack pins the headers of, where it's on.
    const roots = useMemo(
        () => (stacking ? timed("lup-stickies", () => stickies(laidOut, laidOut.groups.map((each) => each.depth), trials.drawers === "stack")) : []),
        [stacking, laidOut, trials.drawers],
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
    // The start of each file's header line: where `]f` and `[f` go, and where a key held down or a page scroll stops.
    const heads = useMemo(() => fileHeads(laidOut), [laidOut]);
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
            left(at);
        },
        list,
        pending,
        margin: true,
        unfolded: (fold) => {
            const drawer = laidOut.drawers.find((each) => each.folds.some((own) => foldKey(own) === fold.key && own.kind === each.kind));
            if (drawer !== undefined) {
                told(drawer.conversation, drawer.kind);
            }
            // A call's input and output, read as its fold opens.
            for (const each of laidOut.drawers) {
                const call = each.talk?.calls.find((shown) => foldKey({ of: each.of, kind: "call", name: shown.fold.key }) === fold.key);
                if (call !== undefined) {
                    details(each.conversation, [call.id]);
                }
            }
        },
    });
    const { view, landing, kept } = editor;
    const before = useRef<Laid | null>(null);

    // What follows the view, the header stack and the outline, told as it moves.
    const follower = useMemo(() => new Following(), []);
    // How many lines of the stack are over a line once it's the first under it: what a scroll to the cursor keeps
    // clear, so the cursor's line never goes under the stack. Read as it scrolls, of what's laid out then.
    const over = useRef<(position: number) => number>(() => 0);
    over.current = (position) => (stacking ? linesOver(roots, position, narrow) * (view.current?.defaultLineHeight ?? 18) : 0);
    // The pulled-out drawers and the folds, as they're laid out now, which the editor's listener reads.
    const pulledNow = useRef(pulled);
    pulledNow.current = pulled;
    const foldsNow = useRef(laidFor.folds);
    foldsNow.current = laidFor.folds;
    useEffect(() => {
        const current = view.current;
        if (current === null) {
            return;
        }
        follower.attach(current);
        mapOutlineKey(say);
        current.dispatch({
            effects: StateEffect.appendConfig.of([
                EditorView.scrollMargins.of((seen) => ({ top: over.current(seen.state.selection.main.head) })),
                // A drawer pulled out of the row goes back into it once the operator closes it, by its keys or a click.
                EditorView.updateListener.of((update) => {
                    if (pulledNow.current.size === 0 || foldedRanges(update.startState) === foldedRanges(update.state) || update.transactions.some((each) => each.annotation(rebuilt) === true)) {
                        return;
                    }
                    const closed = foldsNow.current.filter(
                        (fold) => fold.name === "" && pulledNow.current.has(fold.of) && fold.of.startsWith(`${fold.kind} `) && isFolded(update.state, fold),
                    );
                    if (closed.length > 0) {
                        queueMicrotask(() => putBackNow.current(closed.map((each) => each.of)));
                    }
                }),
            ]),
        });
        // Made once, with the editor.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    // What's laid out now, which a click on a citation, or on the passage of the operator's words it answers, reads.
    const laidNow = useRef(laidOut);
    laidNow.current = laidOut;

    // A click on a citation's id opens or folds the passage it cites under its line; one on the passage it answers,
    // among the operator's words above, goes to the citation.
    useEffect(() => {
        const current = view.current;
        if (current === null) {
            return undefined;
        }
        const clicked = (event: MouseEvent) => {
            const label = event.target instanceof Element ? event.target.closest("[data-pull]") : null;
            if (label !== null) {
                pullNow.current(label.getAttribute("data-pull") ?? "");
                return;
            }
            const target = event.target instanceof Element ? event.target.closest("[data-answered], .citation") : null;
            if (target === null) {
                return;
            }
            const answered = target.getAttribute("data-answered");
            if (answered !== null) {
                current.dispatch({ selection: { anchor: Number(answered) }, scrollIntoView: true });
                return;
            }
            const at = current.posAtDOM(target);
            const fold = citationsOf(laidNow.current).find((each) => at >= each.marker.from && at <= each.marker.to)?.fold;
            if (fold != null) {
                current.dispatch({ effects: folding(fold, !isFolded(current.state, fold)) });
            }
        };
        current.dom.addEventListener("click", clicked);
        return () => current.dom.removeEventListener("click", clicked);
    }, [view]);

    // What the operator last looked at of each file of a "since you approved" drawer (`lookedAt`): the version shown
    // as the cursor last left it, or as the drawer was first read; none for a file they never looked at, as one that
    // came later or came back once reviewed. And the file the cursor is in, which it's looked at once the cursor leaves.
    const looked = useRef(new Map<string, ChangedFile>());
    const firstRead = useRef(new Set<string>());
    const inFile = useRef<{ of: string; path: string } | null>(null);
    // The file Space `a` marked reviewed, and what its drawer showed then, so the cursor goes onto its line once the
    // drawer reads it as reviewed.
    const reviewing = useRef<{ of: string; path: string; files: SinceFile[] } | null>(null);
    const freshOf: Freshness = (scope, file) =>
        isDrawer(scope) && scope.kind === "since" ? freshRows(looked.current.get(lookedAt(scope.of, file.path)) ?? null, file) : null;

    /** Say whom what's written reaches, on its first line, where the header no longer says it: the stack's. */
    const reachesOf = stacking
        ? (each: Written): string => {
              if (isLetter(each) || isRemark(each)) {
                  return `to ${called(each.to)}`;
              }
              const item = laidOut.regions.find((region) => region.item.number === each.item)?.item;
              const party = item === undefined ? null : recipient(item);
              return party === null ? "to no agent: no session's push asked it" : `to ${called(party)}`;
          }
        : null;

    /** Take each "since you approved" drawer read for the first time as looked at, and forget what was looked at of each file standing as the operator last saw it, which shows each of its changes once it comes back. */
    function read(laid: Laid) {
        // A drawer read with nothing in it isn't shown, but it's been read: a file coming to it later is new to the operator.
        for (const [key, data] of drawers) {
            if (data.since?.worktree != null && (data.since.files ?? []).length === 0) {
                firstRead.current.add(`since ${key}`);
            }
        }
        for (const drawer of laid.drawers) {
            if (drawer.kind !== "since" || drawer.worktree === null) {
                continue;
            }
            const first = !firstRead.current.has(drawer.of);
            firstRead.current.add(drawer.of);
            for (const each of drawer.files) {
                const key = lookedAt(drawer.of, each.path);
                if (each.file == null) {
                    looked.current.delete(key);
                } else if (first) {
                    looked.current.set(key, each.file);
                }
            }
        }
    }

    /** Take the file of a "since you approved" drawer the cursor leaves, moving to `at`, as looked at, as it stands: its marks of what changed go. */
    function left(at: number) {
        const drawer = drawerAt(laidOut, at);
        const file = drawer?.kind === "since" ? sinceFileAt(drawer, at) : undefined;
        const now = drawer === undefined || file === undefined ? null : { of: drawer.of, path: file.path };
        const was = inFile.current;
        inFile.current = now;
        if (was === null || (now !== null && now.of === was.of && now.path === was.path)) {
            return;
        }
        const standing = laidOut.drawers.find((each) => each.of === was.of)?.files.find((each) => each.path === was.path)?.file;
        if (standing == null) {
            return;
        }
        looked.current.set(lookedAt(was.of, was.path), standing);
        // Drawn once the cursor's move is done, which this is told of while CodeMirror is still telling it.
        queueMicrotask(() => editor.draw(decorations(laidOut, draft, reviewed, reachesOf)));
    }
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
            const onReviewed = arriving === null && writing === undefined ? reviewedLine(laidOut) : undefined;
            const anchor =
                writing ??
                away ??
                onReviewed ??
                (arriving === null ? moved(head, made, doc) : followed(before.current, laidOut, head, made, doc, arriving));
            const landed = arriving !== null || away !== undefined;
            // Where the cursor's line is on screen, where it's in view: kept there, whatever arrives above it.
            const onScreen = landed ? null : screenOffset(current, head);
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
            // A comment opened where a closed fold hides it, as on the header of an item marked read, opens the folds
            // over it, as a jump does, saying so, so the cursor goes into it.
            const opens = arriving !== null && "comment" in arriving ? reaching(current.state, anchor) : [];
            if (opens.length > 0) {
                current.dispatch({ effects: opens, selection: { anchor }, scrollIntoView: true, annotations: reached.of(opens.length) });
            }
            // Restored after the folds, whose heights it takes in: the cursor's line where it was on screen, or, where
            // it was out of view, the text at the view's top. Either keeps a comment being written where it is on
            // screen too, as only what arrives above moves it; a scroll to the cursor after it would replace it, since
            // CodeMirror keeps the last scroll asked of it alone.
            if (onScreen !== null) {
                const line = current.state.doc.lineAt(current.state.selection.main.head).from;
                // Where the stack is on, a scroll keeps clear what it pins over the line, which it takes off here.
                current.dispatch({ effects: EditorView.scrollIntoView(line, { y: "start", yMargin: onScreen - over.current(current.state.selection.main.head) }) });
            } else if (!landed && scrolled !== undefined) {
                current.dispatch({ effects: scrolled });
            }
        } else {
            // What folds can change with the text the same, as an item marked read folds.
            refold(current, laidFor.folds, kept.current);
        }
        read(laidOut);
        before.current = laidOut;
        wrote.current = written(draft);
        places.current = items.length === 0 ? [] : laidOut.groups.map((each) => each.place);
        landing.current = null;
        editor.draw(decorations(laidOut, draft, reviewed, reachesOf));
        // A drawer just pulled out of the row: the cursor goes onto its summary line, in view.
        const out = pulledTo.current === null ? undefined : laidOut.drawers.find((each) => each.of === pulledTo.current);
        if (out !== undefined) {
            pulledTo.current = null;
            current.dispatch({ selection: { anchor: out.header.from }, scrollIntoView: true });
        }
        follower.tell();
        if (arriving !== null && "comment" in arriving) {
            editor.enter();
        }
    }, [laidOut, draft, reviewed, stacking]);

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

    /** Open each fold over `target`, as a jump to it does, so the line it's on is in view, saying so under the review. */
    function opening(current: EditorView, target: number) {
        const effects = reaching(current.state, target);
        if (effects.length > 0) {
            current.dispatch({ effects, annotations: reached.of(effects.length) });
        }
    }

    /** Return where `target` is seen: there, or, where a closed fold hides it, on the outermost one's summary line, which a closed fold counts as. */
    function seen(current: EditorView, target: number): number {
        return uncovered(
            laidFor.folds.filter((each) => isFolded(current.state, each)),
            target,
        );
    }

    /**
     * Go to `region`'s item, where there's one: onto where it lands (`arrival`), its header kept in view above the line
     * where both fit; `reaching` it, as `]a` does, opening the folds over it, else, as `]]` does, on the summary line of
     * the closed fold hiding it, which a plain motion never opens.
     */
    function goTo(region: Region | undefined, reaches: boolean) {
        const current = view.current;
        if (current === null || region === undefined) {
            return;
        }
        const at = reaches ? arrival(region) : seen(current, arrival(region));
        if (reaches) {
            opening(current, at);
        }
        // Its header at the view's top, the line it lands on under it, where both fit; else that line in the middle.
        const top = current.lineBlockAt(region.header.from).top;
        const fits = at === region.header.from || current.lineBlockAt(at).bottom - top < current.scrollDOM.clientHeight * 0.8;
        current.dispatch({ selection: { anchor: at } });
        scrollAfterKey(current, fits ? EditorView.scrollIntoView(region.header.from, { y: "start" }) : EditorView.scrollIntoView(at, { y: "center" }));
    }

    /**
     * Return where the cursor goes once the file Space `a` marked reviewed is, as its drawer is read anew and shows it
     * so: onto what's left after it, the next file to review or one with flagged writes waiting, else the line its
     * settled files fold under, where it went; none else, or before.
     */
    function reviewedLine(laid: Laid): number | undefined {
        const asked = reviewing.current;
        const drawer = asked === null ? undefined : laid.drawers.find((each) => each.of === asked.of);
        if (asked === null || drawer === undefined || drawer.files === asked.files) {
            return undefined;
        }
        reviewing.current = null;
        const settled = drawer.settled?.from ?? Infinity;
        const at = (file: SinceFile): number | undefined =>
            drawer.filed.find((each) => each.file === file.file)?.from ?? drawer.reviewed.find((each) => each.file === file && each.from < settled)?.from;
        const after = drawer.files.slice(drawer.files.findIndex((each) => each.path === asked.path) + 1);
        for (const file of after) {
            const found = at(file);
            if (found !== undefined) {
                return found;
            }
        }
        return drawer.settled?.from ?? drawer.header.from;
    }

    /** Return the "since you approved" drawer the cursor is in, where it's in one. */
    function sinceHere(): Drawer | undefined {
        const drawer = drawerAt(laidOut, editor.head());
        return drawer?.kind === "since" ? drawer : undefined;
    }

    /** Pull a drawer out of its row under the banner, open, reading what it shows; or put it back. */
    function pull(of: string) {
        const label = laidOut.groups.flatMap((group) => (group.row?.labels ?? []).map((each) => ({ group, label: each }))).find((each) => each.label.of === of);
        if (label === undefined) {
            return;
        }
        const { group, label: drawer } = label;
        // Pulled out, it's open, however it was last closed.
        kept.current.delete(foldKey({ of, kind: drawer.kind, name: "" }));
        if (!drawer.pulled && group.conversation !== null) {
            told(group.conversation, drawer.kind);
        }
        if (drawer.pulled) {
            putBack([of]);
            return;
        }
        pulledTo.current = of;
        setPulled((before) => new Set([...before, of]));
    }
    const pullNow = useRef(pull);
    pullNow.current = pull;

    /** Put drawers pulled out back in their row, the cursor going onto the row where it was in one. */
    function putBack(ofs: string[]) {
        const group = laidOut.groups.find((each) => each.row?.labels.some((label) => ofs.includes(label.of)) === true);
        const inside = drawerAt(laidOut, editor.head());
        if (group?.row != null && (inside === undefined || ofs.includes(inside.of))) {
            landing.current = { at: group.row.from };
        }
        setPulled((before) => new Set([...before].filter((each) => !ofs.includes(each))));
    }
    const putBackNow = useRef(putBack);
    putBackNow.current = putBack;
    // The drawer just pulled out, which the cursor goes onto once it's laid out.
    const pulledTo = useRef<string | null>(null);

    /** Go to `position` in the review, as the stack and the outline do, opening the folds over it, its line under the stack. */
    const jumpTo = useCallback(
        (position: number) => {
            const current = view.current;
            if (current === null) {
                return;
            }
            const effects = reaching(current.state, position);
            current.dispatch({ selection: { anchor: position }, effects: [...effects, EditorView.scrollIntoView(position, { y: "start" })], annotations: reached.of(effects.length) });
            current.focus();
        },
        [view],
    );

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
            const current = view.current;
            if (current === null) {
                return;
            }
            const head = editor.head();
            // Where each item is seen to land, a closed fold over it counting as its summary line, which `]]` never opens.
            const landings = laidOut.regions.map((region) => ({ region, at: seen(current, arrival(region)) }));
            const target = forward
                ? landings.find((each) => each.at > head)
                : [...landings].reverse().find((each) => each.at < head);
            goTo(target?.region, false);
        },
        answer: (forward) => goTo(answerAfter(laidOut, draft, editor.head(), forward), true),
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
            current.dispatch({ selection: { anchor: target } });
            // A third of the view from its edges, so what's around it shows.
            scrollAfterKey(current, EditorView.scrollIntoView(target, { y: "nearest", yMargin: current.scrollDOM.clientHeight / 3 }));
        },
        file: (forward) => {
            const current = view.current;
            if (current === null) {
                return;
            }
            const line = current.state.doc.lineAt(editor.head()).from;
            // A file a closed fold hides, in an item marked read or a drawer closed, is passed over, the fold counting as
            // its summary line; one folded whole is gone to on its header, which it doesn't open.
            const target = stepped(
                heads.filter((each) => !hiddenAt(current.state, each)),
                line,
                forward,
            );
            if (target === undefined) {
                return;
            }
            current.dispatch({ selection: { anchor: target } });
            // Its header at the view's top, its lines under it.
            scrollAfterKey(current, EditorView.scrollIntoView(target, { y: "start" }));
        },
        stops: () => heads,
        cite: (forward) => {
            const current = view.current;
            if (current === null) {
                return;
            }
            const head = editor.head();
            const all = citationsOf(laidOut);
            const target = forward ? all.find((each) => each.marker.from > head) : all.findLast((each) => each.marker.from < head);
            if (target === undefined) {
                say(`No citation of your words ${forward ? "after" : "before"} this.`);
                return;
            }
            // The folds hiding it open, said under the review, and the passages cited on its line under it.
            const effects = reaching(current.state, target.marker.from);
            const passages = target.fold !== null && isFolded(current.state, target.fold) ? [folding(target.fold, false)] : [];
            current.dispatch({
                selection: { anchor: target.marker.from },
                effects: [...effects, ...passages],
                scrollIntoView: true,
                annotations: reached.of(effects.length),
            });
        },
        follow: () => {
            const current = view.current;
            const target = current === null ? undefined : following(citationsOf(laidOut), editor.head());
            if (current === null || target === undefined) {
                say("gd follows a citation of your words to the passage it cites, and that passage back: put the cursor on one.");
                return;
            }
            const effects = reaching(current.state, target);
            current.dispatch({ selection: { anchor: target }, effects, scrollIntoView: true, annotations: reached.of(effects.length) });
        },
        approve: (approved) => {
            const drawer = sinceHere();
            if (drawer !== undefined) {
                const file = sinceFileAt(drawer, editor.head());
                if (file === undefined) {
                    say("Space a marks a file reviewed: put the cursor on one of its lines.");
                } else if (!approved) {
                    say("A file is marked reviewed or commented on, never declined.");
                } else {
                    reviewing.current = { of: drawer.of, path: file.path, files: drawer.files };
                    reviewSince(drawer.conversation, [viewed(file)]);
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
                say('Space A marks every file of a "since you approved" drawer reviewed: put the cursor in one.');
                return;
            }
            if (drawer.files.length === 0) {
                say("Nothing in this drawer to mark reviewed.");
                return;
            }
            reviewSince(drawer.conversation, drawer.files.map(viewed));
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
        paint: (from, to) => painted(laidOut, from, to, freshOf),
        level: (position, opening, all, closed) => levelled(scopeFolds(position), closed, opening, all),
        kind: (position, kind, closing, closed) => {
            // On a banner, Space z and a drawer's letter opens that drawer of the agent's.
            const group = groupAt(laidOut, position);
            // Where the drawers are a row, Space z f and a drawer's letter pulls it out below the row, Space z F puts it back.
            const label = group?.row?.labels.find((each) => each.kind === kind);
            if (label !== undefined && label.pulled === closing) {
                pull(label.of);
                return [];
            }
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

    // What the outline reads beside the review as it's laid out.
    const reading = useMemo(() => ({ draft, reviewed, parents, states, called }), [draft, reviewed, parents, states, called]);
    const focusing = useCallback((focus: (() => void) | null) => setOutlineFocus(focus), []);

    const naming = {
        group: (group: Group) => banner(group.head),
        item: (region: Region) => itemNamed(laidOut.text.slice(region.header.from, region.header.to)),
        party: called,
    };
    const where = <Heading parts={heading(laidOut, Math.min(head, laidOut.text.length), commenting, written(draft), naming)} tally={tallied(items, draft, reviewed)} />;
    // Each header pinned is drawn as the buffer draws its line.
    const classesOf = (sticky: Sticky): string => {
        switch (sticky.kind) {
            case "group": {
                return bannerClasses(laidOut.groups.find((each) => each.banner.from === sticky.header.from)?.depth ?? 0);
            }
            case "item": {
                const region = laidOut.regions.find((each) => each.header.from === sticky.header.from);
                if (region === undefined) {
                    return "review-header";
                }
                const number = region.item.number;
                return [
                    "review-header",
                    fresh(region.item, reviewed) ? "is-new" : "",
                    news(region.item) ? "is-news" : "",
                    (draft.done ?? []).includes(number) ? "is-done" : "",
                    (draft.parked ?? []).includes(number) ? "is-parked" : "",
                ].join(" ");
            }
            case "drawer": {
                const drawer = laidOut.drawers.find((each) => each.header.from === sticky.header.from);
                return `drawer-summary drawer-${drawer?.kind ?? "since"}`;
            }
            case "file":
                return "code-file";
        }
    };
    const markOf = (sticky: Sticky): StackMark | null => {
        if (sticky.kind === "group") {
            return null;
        }
        const kind = sticky.kind === "drawer" ? (laidOut.drawers.find((each) => each.header.from === sticky.header.from)?.kind ?? "since") : sticky.kind;
        const letter = FOLD_KINDS.find((each) => each.kind === kind)?.letter ?? "";
        return { kind, letter, depth: sticky.kind === "file" ? 1 : 0 };
    };
    // What settles what a pinned header heads, so the operator knows what would validate the file they're in.
    const hintOf = (sticky: Sticky): string | null => {
        const region = sticky.kind === "item" || sticky.kind === "file" ? regionAt(laidOut, sticky.header.from) : undefined;
        const drawer = sticky.kind === "drawer" || sticky.kind === "file" ? drawerAt(laidOut, sticky.header.from) : undefined;
        if (drawer?.kind === "since") {
            return sticky.kind === "file" ? "␣a marks it reviewed" : "␣A marks every file reviewed";
        }
        if (region === undefined) {
            return null;
        }
        const number = cited(region.item.number);
        if (answering(region.item).kind === "answer") {
            return sticky.kind === "file" ? `␣a approves ${number}, every file` : "␣a approves · ␣x declines";
        }
        return region.item.reason.reason === "question" ? "a comment answers it · ␣d reads it" : "␣d marks it read";
    };
    const labelsOf = (sticky: Sticky): RowLabel[] => laidOut.groups.find((each) => each.banner.from === sticky.header.from)?.row?.labels ?? [];
    return (
        <>
            {stacking ? null : where}
            <div className={`review-body${trials.outline ? " with-outline" : ""}`}>
                {trials.outline ? (
                    <Outline
                        following={follower}
                        laidOut={laidOut}
                        reading={reading}
                        narrow={narrow}
                        open={outlining}
                        setOpen={setOutlining}
                        jump={jumpTo}
                        back={() => view.current?.focus()}
                        focusing={focusing}
                    />
                ) : null}
                <div className="buffer-wrap">
                    <div className="buffer review-buffer" ref={editor.parent} />
                    {stacking ? (
                        <Stack
                            following={follower}
                            roots={roots}
                            text={laidOut.text}
                            classesOf={classesOf}
                            labelsOf={labelsOf}
                            markOf={markOf}
                            hintOf={hintOf}
                            narrow={narrow}
                            jump={jumpTo}
                            pull={(label) => pull(label.of)}
                        />
                    ) : null}
                </div>
            </div>
            {trials.header === "stack-status" ? <div className="status-line">{where}</div> : null}
        </>
    );
}

export type { DrawerKind };
