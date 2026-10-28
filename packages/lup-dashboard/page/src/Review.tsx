// The review: everything waiting for the operator in one buffer moved through
// with vim (`editor.ts`), in groups, one per agent, every agent running having
// one, empty or not; their comments written into it, each under the line it's
// on: Space `c` opens one on the item whole; `o` or Space `c` on a banner, a
// message to its agent, under the banner; `o` in an agent's drawer, a remark to
// it. Ctrl+Enter elsewhere than in a comment or a message sends. Space and a
// verb's key acts on the innermost thing at the cursor it applies to, as a
// mark in the draft (`grammar.ts`): Space `d` marks an item read, approves an
// approval or a held change, marks a file of "since you approved" reviewed,
// Space `x` declines, Space `s` leaves an item for later, Space `h` holds an
// agent's flagged writes from anywhere in its group; `]]` and `[[` go to the next and
// previous item, landing on its first line that matters, `]a` and `[a` to the
// next and previous item to answer, in the order they came, `]c` and `[c` to the
// next and previous such line. Under an approval or a held change, each file it
// changes, whole, its lines numbered, marked and highlighted as they come into
// view, each line that matters by the judge's reading barred and saying what it
// triggered; the item's header counts its files by why each is open; under each
// item, its context. Under each agent's banner, its drawers
// (`review.ts`): its tasks, what its branch changed since the operator last saw
// it, live, where Space `d` marks a file reviewed at the version shown and, on
// the drawer's line, every file shown, each line changed since they last looked at its file
// marked (`since.ts`), and its conversation, each call's input and output read
// as its fold opens. Each fold has a kind, its letter in the margin beside its summary
// line, in the column of its depth, each scope a bar its full height, labelled
// (`rails.ts`); the context, each run of unchanged lines, each test, data and
// first approval's file and each drawer, folded until opened, and `zr`, `zm`,
// `zR` and `zM` act on the item or the drawer the cursor is in, Space `f` and a letter selecting every fold of a kind there. The
// header over the review says where the cursor is: the group, the item or the
// drawer, the file and the folds it's in, and, while a comment is being
// written, whom it goes to; at its end, how many items are to answer and how
// many are new; under it, the stack pins the headers the top of the view is in
// (`Stack.tsx`); beside the review, the overview (`Outline.tsx`). As what
// it shows changes, the buffer is changed by the fewest changes that keep each
// part's lines its own (`reconcile.ts`), the cursor, a selection and the folds
// carried through them, each line that came flashing, and the cursor's line
// stays where it is on screen, so nothing arriving above moves what the
// operator reads; what ticks or measures is drawn beside the text
// (`ticking.ts`). An agent's answer shows the
// operator's words it answers above it, each of its citations of them as its
// id, the passage it cites folded under its line, opened by a click on the id,
// and the passage it answers marked among the operator's words, a click there
// going to it (`exchange.ts`; `docs/dashboard.md`, *The review*, *The
// drawers*).
import { foldedRanges } from "@codemirror/language";
import { Compartment, RangeSetBuilder, StateEffect, type ChangeSet, type Range } from "@codemirror/state";
import { Decoration, EditorView, type DecorationSet } from "@codemirror/view";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { tokensOf, within, type Filed, type Matter, type Taken } from "./code";
import { cited, type Block, type Folding, type Span } from "./comments";
import { BARE, chosenKind, closedAs, folding, hiddenAt, isFolded, mapLetters, mapVerbs, reached, reaching, rebuilt, refold, scrollAfterKey, uncovered, useEditor, vimOf, type Landing } from "./editor";
import { arrivedLines, arriving, owned, owning, ownersOf, reconcile, settling } from "./reconcile";
import { clock, ticked, ticking, type Tick } from "./ticking";
import { doing, since, type Activity } from "./agents";
import { Following } from "./follow";
import { mapOutlineKey, mapScopeKeys, Outline, setOutlineFocus, setOutlineToggle, setScopeJump, useNarrow, type ScopeKey } from "./Outline";
import { Stack, type Mark as StackMark } from "./Stack";
import { redrawn, structureMargin, type Labelled, type Structured } from "./rails";
import { itemStanding } from "./outline";
import { DRAFTED, GLYPHS } from "./Outline";
import { linesOver, stickies, type Sticky } from "./stack";
import { depths, levelled } from "./folds";
import { chainAt, findNode, isMarked, marking, marksOn, reachOf, reachedIn, type Act } from "./grammar";
import type { DrawerKind, FoldKind, Here } from "./keys";
import { kindOf, type Merged } from "./looks";
import { markerEnd, outdated, unfound } from "./exchange";
import { source, sourced, without, type Source } from "./markdown";
import {
    barsOf,
    aboutAt,
    answerAfter,
    citationsOf,
    following,
    arrival,
    blockAt,
    blocksOf,
    codeAt,
    codeFrom,
    drawerAt,
    fileHeads,
    foldKey,
    foldsOf,
    fresh,
    groupAround,
    groupAt,
    heading,
    isDrawer,
    isLetter,
    isRegion,
    isRemark,
    laid,
    news,
    opened,
    ordered,
    quoted,
    quotedAt,
    recipient,
    regionAt,
    sameId,
    scopeAt,
    shownAt,
    sinceFileAt,
    stepped,
    tallied,
    toKeep,
    waited,
    whose,
    withWritten,
    written,
    writtenId,
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
    type Keeping,
    type Laid,
    type Region,
    type Scope,
    type Where,
    type Written,
} from "./review";
import { freshRows, type Fresh } from "./since";
import type { Instance, Offer, Remote, Running, Span as ViewSpan } from "./views";

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
    /** Told what the cursor is on, outside insert mode, and what each verb would do to it, so the line of keys says it. */
    placed: (here: Here) => void;
    /** Told the keys of a chord begun, so what may follow is shown. */
    pending: (keys: string) => void;
    /** Open the list of every key. */
    list: () => void;
    /** When the operator last settled an item of theirs: what came after is new to them. */
    reviewed: string | null;
    /** What each conversation running is doing, by `whose` it is, drawn on its banner as the time passes (`ticking.ts`). */
    activities: ReadonlyMap<string, Activity | null>;
    /** Each conversation's parent, by `whose` each is: what nests a subagent's group under its parent's. */
    parents: ReadonlyMap<string, string>;
    /** What each conversation running is doing, by `whose` it is, for the overview's marks. */
    states: ReadonlyMap<string, string | null>;
    /** Whether the overview pane is shown: beside the review, or over it on a narrow screen. */
    overview: boolean;
    setOverview: (open: boolean) => void;
    /**
     * Where the groups go, as the host keeps it for every page and across reloads (`Group.place`, in order), once the
     * page has what the review is laid out from, that order among it; none until then.
     */
    order: readonly string[] | null;
    /** Tell the host where the groups go once the review is laid out: what's laid out, and what's gone from it; none where what the page shows isn't all the host's answers, as where it refused one. */
    keepOrder: ((keeping: Keeping) => void) | null;
    /** How the views look, every repository's merged (`looks.ts`): the kinds of fold the keys take, and each repository's drawers. */
    looks: Merged;
    /** Each conversation running, by `whose` it is: its banner's parts, and what holding its writes asks. */
    running: ReadonlyMap<string, Running>;
    /** What the host answered of each view the page doesn't lay out itself, by its instance's id (`views.ts`). */
    remote: Remote;
    /** Told each view a fold reads as it opens, its module's, as the operator opens it, so the page asks it of the host. */
    load: (view: Instance) => void;
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
type Freshness = (scope: Scope, file: Filed) => Fresh | null;

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
 * comments under them left out; the agent's words in a context, each run of them one; each Markdown block of a
 * drawer's, as the agent's words in its conversation, the remarks under them left out; and each comment, message and
 * remark.
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
        for (const span of drawer.texts) {
            add(source("text", without(whole(span), drawer.blocks.map(whole))));
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

/** Return the classes a drawer's label is drawn with: in its kind's colour, bold where it holds what waits on the operator. */
function drawerClasses(drawer: Drawer): string {
    return `drawer-label drawer-${drawer.kind}${drawer.waiting ? " is-waiting" : ""}`;
}

/** Return the classes a group's banner is drawn with: set in by how deep it's nested, where it is. */
function bannerClasses(depth: number): string {
    return ["review-banner", "frame-band", depth > 0 ? `is-nested nest-${Math.min(depth, 4)}` : ""].join(" ").trim();
}

/** What a group's end says of whose it is, `lup-impl`. */
type Ends = (group: Group) => string;

/**
 * Mark where each item and each group ends: the blank line after an item ruled, and a group's last line saying whose
 * end it is, a subagent's with its parent's where they end together, set in as the innermost is.
 */
function endings(laidOut: Laid, ends: Ends): { from: number; to: number; value: Decoration }[] {
    const text = laidOut.text;
    const blank = (at: number) => at < text.length && text[at] === "\n" && (at === 0 || text[at - 1] === "\n");
    const groupEnds = new Map<number, { names: string[]; depth: number }>();
    for (const group of laidOut.groups) {
        const fold = group.fold;
        if (fold === null) {
            continue;
        }
        const line = text.lastIndexOf("\n", fold.to - 1) + 1;
        if (blank(line)) {
            const was = groupEnds.get(line);
            groupEnds.set(line, { names: [...(was?.names ?? []), ends(group)], depth: Math.max(was?.depth ?? 0, group.depth) });
        }
    }
    const marks: { from: number; to: number; value: Decoration }[] = [];
    for (const [at, { names, depth }] of groupEnds) {
        // The innermost's end first, set in as its banner is.
        const said = `end of ${names.toReversed().join(", end of ")}`;
        marks.push({ from: at, to: at, value: Decoration.line({ class: `group-end${depth > 0 ? ` nest-${Math.min(depth, 4)}` : ""}`, attributes: { "data-end": said } }) });
    }
    for (const region of laidOut.regions) {
        const own = region.folds.find((each) => each.kind === "item");
        const after = own === undefined ? -1 : own.to + 1;
        if (own !== undefined && blank(after) && !groupEnds.has(after)) {
            marks.push({ from: after, to: after, value: Decoration.line({ class: "item-end" }) });
        }
    }
    return marks;
}

/**
 * Draw the review: groups' banners and the messages under them, items' headers, done and parked items, the lines under
 * each item and in each drawer, the changed files' headers, each comment's lines, and the passage each comment is on.
 * A banner nested under its parent's is set in; the row of a group's drawers has each label marked, pulling its drawer
 * out on a click; and where `to` says it, each comment, message and remark says whom it reaches on its first line.
 */
function decorations(
    laidOut: Laid,
    draft: Draft,
    reviewed: string | null,
    to: ((written: Written) => string) | null = null,
    ends: Ends = () => "",
): DecorationSet {
    const marks: { from: number; to: number; value: Decoration }[] = [...endings(laidOut, ends)];
    const comments = new Map(laidOut.written.map((each) => [writtenId(each), each]));
    const reaching = (block: Block) => {
        const comment = comments.get(block.comment);
        if (to !== null && comment !== undefined) {
            marks.push({ from: block.from, to: block.from, value: Decoration.line({ class: "remark-to", attributes: { "data-to": to(comment) } }) });
        }
    };
    for (const group of laidOut.groups) {
        marks.push({ from: group.banner.from, to: group.banner.from, value: Decoration.line({ class: bannerClasses(group.depth) }) });
        marks.push(...group.blocks.flatMap((block) => remarks(laidOut, block)));
        group.blocks.forEach(reaching);
    }
    for (const scope of scopesOf(laidOut)) {
        if (isDrawer(scope)) {
            marks.push({ from: scope.header.from, to: scope.header.from, value: Decoration.line({ class: drawerClasses(scope) }) });
            // A view its module answers, each span in the look of its tone (`looks.ts`); what a fold of its sets off,
            // set in by how many such folds it's in, the innermost's bar beside it.
            for (const span of scope.toned) {
                marks.push({ from: span.from, to: span.to, value: marked(`tone-${span.tone}`) });
            }
            for (const [from, classes] of barsOf(laidOut.text, scope.bars)) {
                marks.push({ from, to: from, value: Decoration.line({ class: classes }) });
            }
        } else {
            const region = scope as Region;
            const number = region.item.number;
            const states = [
                "review-header",
                fresh(region.item, reviewed) ? "is-new" : "",
                news(region.item) ? "is-news" : "",
                (draft.done ?? []).includes(number) ? "is-done" : "",
                (draft.declined ?? []).includes(number) ? "is-declined" : "",
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
                const automatic = coded.file.block === "diff" && coded.file.automatic ? " code-automatic" : "";
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
            const comment = comments.get(block.comment);
            if (comment === undefined || isLetter(comment)) {
                continue;
            }
            // A comment on lines that aren't what it quotes any more is said to be outdated: an edit of its item changed
            // them, or what its block shows did.
            const seat = laidOut.seated.get(block.comment);
            const edited = !isRemark(comment) && isRegion(scope) && outdated(scope.item, comment.quote);
            if (edited || seat?.outdated === true) {
                marks.push({ from: block.from, to: block.from, value: Decoration.line({ class: "outdated", attributes: { "data-said": edited ? "outdated: the passage changed" : "outdated: the lines it quotes changed" } }) });
            }
            const span = quotedAt(laidOut, scope, comment);
            if (span !== null && span.to > span.from) {
                marks.push({ from: span.from, to: span.to, value: Decoration.mark({ class: "commented" }) });
            }
        }
    }
    marks.push(...citing(citationsOf(laidOut)));
    // Each mark the draft holds beyond the items', on the first line of what it marks, saying what Ctrl+Enter does with it.
    for (const mark of draft.marks ?? []) {
        const node = findNode(laidOut.nodes, mark.block);
        if (node !== undefined) {
            marks.push({ from: node.from, to: node.from, value: Decoration.line({ class: `is-marked mark-${mark.verb}`, attributes: { "data-mark": mark.says } }) });
        }
    }
    marks.sort((a, b) => a.from - b.from || a.to - b.to);
    const builder = new RangeSetBuilder<Decoration>();
    for (const each of marks) {
        builder.add(each.from, each.to, each.value);
    }
    return builder.finish();
}

/** Say a span that ticks as of `now`: what it says for its first minute where it says other, else its words with the time since its moment; a gauge as it was answered. */
function spanSaid(span: ViewSpan, now: Date): string {
    const ticking = span.ticking;
    if (ticking == null) {
        return span.text;
    }
    const at = new Date(ticking.since);
    if (ticking.first != null && now.getTime() - at.getTime() < 60_000) {
        return ticking.first;
    }
    return (ticking.said ?? "{}").replace("{}", since(at, now));
}

/** How an item's header says when it came: made once, since `toLocaleString` makes one at each call, and the review is laid out again at each key typed in a comment. */
const WHEN = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

function when(made: string): string {
    return WHEN.format(new Date(made));
}

/** The header over the review: where the cursor is, each part marked by its kind, and whom what's being written goes to; at its end, what waits below (`tallied`). */
function Heading({ parts, tally }: { parts: Where[]; tally: string }) {
    const letter = (kind: Where["kind"]) => kindOf(kind)?.letter ?? null;
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

/** Return how far below the top of the view the start of the line at `head` is, as the editor's heights measure it, whether or not it's in view. */
function offsetOf(view: EditorView, head: number): number {
    const line = view.lineBlockAt(view.state.doc.lineAt(Math.min(head, view.state.doc.length)).from);
    return view.documentTop + line.top - view.scrollDOM.getBoundingClientRect().top;
}

/** Return how far below the top of the view the start of the line at `head` is, where it's in view; none where it isn't. */
function screenOffset(view: EditorView, head: number): number | null {
    const top = offsetOf(view, head);
    return top >= 0 && top < view.scrollDOM.clientHeight ? top : null;
}

/**
 * Return where the cursor goes as the review is laid out, where the operator's own act says it (`landing`): into the
 * comment just opened, onto an item's header, or to a place in the text as it was, carried by the layout's changes
 * `made`; none where it's to be carried by them alone.
 */
function landed(after: Laid, made: ChangeSet, landing: Landing): number | null {
    if (landing === null) {
        return null;
    }
    if ("at" in landing) {
        return Math.min(made.mapPos(landing.at), after.text.length);
    }
    if ("comment" in landing) {
        return blocksOf(after).find((each) => each.comment === landing.comment)?.from ?? null;
    }
    return after.regions.find((each) => each.item.number === landing.item)?.header.from ?? null;
}

/** Return where vim's visual selection is, by its anchor and head as offsets in the text; none outside visual mode. */
function visualOf(view: EditorView): { anchor: number; head: number } | null {
    const cm = vimOf(view);
    const vim = cm?.state.vim;
    if (cm === null || vim === undefined || !vim.visualMode || vim.sel === undefined) {
        return null;
    }
    return { anchor: cm.indexFromPos(vim.sel.anchor), head: cm.indexFromPos(vim.sel.head) };
}

/** Carry vim's visual selection, `was` before the changes `made`, through them, as CodeMirror carries its own: vim keeps it apart, by line and column, and goes on from it at its next key. */
function revisualized(view: EditorView, was: { anchor: number; head: number } | null, made: ChangeSet): void {
    const cm = vimOf(view);
    if (was === null || cm === null || !cm.state.vim.visualMode) {
        return;
    }
    cm.state.vim.sel = { anchor: cm.posFromIndex(made.mapPos(was.anchor)), head: cm.posFromIndex(made.mapPos(was.head)) };
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
    opened: told,
    jump,
    say,
    inserting,
    epoch,
    placed,
    pending,
    list,
    reviewed,
    activities,
    parents,
    states,
    overview,
    setOverview,
    order,
    keepOrder,
    looks,
    running,
    remote,
    load,
}: Props) {
    // Where the cursor is, and whether a comment is being written: what the header says.
    const [head, setHead] = useState(0);
    // The folds a fold-wise selection holds, while there's one: what the line of keys says the keys do to.
    const choosing = useRef<readonly Folding[] | null>(null);
    const [commenting, setCommenting] = useState(false);
    // Where the groups go: as this page laid them out last, then as the host keeps them for those it didn't
    // (`ordered`), so each keeps its place, across reloads and on each page; and as it last told the host it laid
    // them out, none until it has, when what it doesn't lay out of the host's order is gone.
    const places = useRef<string[]>([]);
    const toldOrder = useRef<string[] | null>(null);
    const narrow = useNarrow();
    const arranging = useMemo(() => ({ parents, looks, running, remote }), [parents, looks, running, remote]);
    // The review as it was last laid out into the editor, which each comment is followed from (`Arranging.previous`).
    const before = useRef<Laid | null>(null);
    const laidOut = useMemo(
        () =>
            laid(
                items,
                agents,
                (head, later, parts) => `━━ ${banner(head)}${parts === "" ? "" : ` · ${parts}`}${later ? " · later" : ""} ━━`,
                // What the item's kind says of it, then what the core says of how it stands.
                (item, later, said) => {
                    const told = [
                        `${cited(item.number)} ${said}`,
                        ...((item.edits ?? []).length > 0 ? ["edited"] : []),
                        ...(fresh(item, reviewed) ? ["new"] : []),
                        when(item.made),
                        ...(later ? ["later"] : []),
                    ];
                    return `── ${told.join(" · ")} ──`;
                },
                draft,
                around,
                ordered(places.current, order ?? []),
                drawers,
                called,
                { ...arranging, previous: before.current },
            ),
        [items, agents, banner, called, draft, around, drawers, reviewed, arranging, order],
    );
    // The scopes the header stack pins the headers of.
    const roots = useMemo(() => stickies(laidOut), [laidOut]);
    const laidFor = useMemo(
        () => ({
            text: laidOut.text,
            blocks: blocksOf(laidOut),
            // In the text's order, as CodeMirror takes the folds a transaction makes: a fold over others, as an
            // automatic file's or an item's marked read, is laid out after them.
            folds: [...scopesOf(laidOut).flatMap((each) => each.folds), ...laidOut.groups.flatMap((each) => (each.fold === null ? [] : [each.fold]))]
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
            if (choosing.current === null) {
                placed(hereAt(at));
            }
            left(at);
        },
        chosen: (folds) => {
            choosing.current = folds;
            placed(folds === null ? hereAt(editor.head()) : hereChosen(folds));
        },
        list,
        pending,
        unfolded: (fold) => {
            const drawer = laidOut.drawers.find((each) => each.folds.some((own) => foldKey(own) === fold.key && own.kind === each.kind));
            if (drawer !== undefined) {
                told(drawer.conversation, drawer.kind);
            }
            // A fold of a module's view's, read from another of its views as it opens.
            for (const each of laidOut.drawers) {
                for (const [name, view] of each.loads) {
                    if (each.folds.some((own) => own.name === name && foldKey(own) === fold.key)) {
                        load(view);
                    }
                }
            }
        },
    });
    const { view, landing, kept } = editor;

    // What follows the view, the header stack and the overview, told as it moves.
    const follower = useMemo(() => new Following(), []);
    // How many lines of the stack are over a line once it's the first under it: what a scroll to the cursor keeps
    // clear, so the cursor's line never goes under the stack. Read as it scrolls, of what's laid out then.
    const over = useRef<(position: number) => number>(() => 0);
    over.current = (position) => linesOver(roots, position, narrow) * (view.current?.defaultLineHeight ?? 18);
    // The margin, the review's structure: with its labels where there's room for them.
    const gutters = useMemo(() => new Compartment(), []);
    // Where the scroll being made is to, which its margins are read for.
    const scrollingTo = useRef<number | null>(null);
    useEffect(() => {
        const current = view.current;
        if (current === null) {
            return;
        }
        follower.attach(current);
        mapOutlineKey();
        current.dispatch({
            effects: StateEffect.appendConfig.of([
                gutters.of([]),
                // Whose each line is, and what arrived, carried through every change (`reconcile.ts`); and what's drawn
                // beside the text, said again as the time passes (`ticking.ts`).
                owning,
                arriving,
                settling,
                ticking,
                clock,
                // What a scroll is to: the stack pinned over its line is kept clear.
                EditorView.scrollHandler.of((_, range) => {
                    scrollingTo.current = range.head;
                    return false;
                }),
                EditorView.scrollMargins.of((seen) => {
                    const to = scrollingTo.current ?? seen.state.selection.main.head;
                    scrollingTo.current = null;
                    return { top: over.current(to) };
                }),
            ]),
        });
        // Made once, with the editor.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    // The keys each kind's letter takes, after `zf`, Space `f` and `F` and `]`, and each verb's after Space, as the looks change.
    useEffect(() => {
        mapLetters(looks.kinds);
        mapScopeKeys(looks.kinds);
        mapVerbs(looks.verbs);
    }, [looks]);
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
            // A click on a drawer's label opens it in place, or closes it.
            const label = event.target instanceof Element ? event.target.closest(".cm-line.drawer-label") : null;
            if (label !== null) {
                const line = current.state.doc.lineAt(current.posAtDOM(label)).from;
                const drawer = laidNow.current.drawers.find((each) => each.header.from === line);
                const own = drawer?.folds.find((each) => each.kind === drawer.kind && each.name === "");
                if (own !== undefined) {
                    current.dispatch({ effects: folding(own, !isFolded(current.state, own)) });
                }
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
    const looked = useRef(new Map<string, Filed>());
    const firstRead = useRef(new Set<string>());
    const inFile = useRef<{ of: string; path: string } | null>(null);
    const freshOf: Freshness = (scope, file) =>
        isDrawer(scope) && scope.kind === "since" ? freshRows(looked.current.get(lookedAt(scope.of, file.path)) ?? null, file) : null;

    // What each group's end says of whose it is.
    const ends: Ends = (group) => (group.conversation === null ? "lup's approvals" : (called(group.conversation).split("/").at(-1) ?? ""));

    /** Say whom what's written reaches, on its first line, where the header no longer says it: the stack's. */
    const reachesOf = (each: Written): string => {
        if (isLetter(each) || isRemark(each)) {
            return `to ${called(each.to)}`;
        }
        const item = laidOut.regions.find((region) => region.item.number === each.item)?.item;
        const party = item === undefined ? null : recipient(item);
        return party === null ? "to no agent: no session's push asked it" : `to ${called(party)}`;
    };

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
                const shownFile = each.file == null ? undefined : drawer.diffs.get(each.path);
                if (shownFile === undefined) {
                    looked.current.delete(key);
                } else if (first) {
                    looked.current.set(key, shownFile);
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
        const drawerWas = laidOut.drawers.find((each) => each.of === was.of);
        const standing = drawerWas?.files.find((each) => each.path === was.path)?.file == null ? undefined : drawerWas?.diffs.get(was.path);
        if (standing === undefined) {
            return;
        }
        looked.current.set(lookedAt(was.of, was.path), standing);
        // Drawn once the cursor's move is done, which this is told of while CodeMirror is still telling it.
        queueMicrotask(() => editor.draw(decorations(laidOut, draft, reviewed, reachesOf, ends)));
    }
    // Which comments each fold held as the review was last laid out, by its key: one that comes to hold another opens.
    const held = useRef(new Map<string, Set<string>>());

    useEffect(() => {
        const current = view.current;
        if (current === null) {
            return;
        }
        const arriving = landing.current;
        const state = current.state;
        const head = state.selection.main.head;
        // Where the cursor's line is on screen, where it's in view: kept there, whatever arrives above it.
        const onScreen = arriving === null ? screenOffset(current, head) : null;
        // The layout made from what's in the editor by the fewest changes that keep each part's lines its own, the
        // comment the cursor is in kept before anything else, then every other comment.
        const runs = state.field(owning);
        const writingIn = runs.find((each) => each.owner.startsWith("written ") && head >= each.from && head <= each.to)?.owner;
        const weight = (owner: string) => (owner === writingIn ? 1e9 : owner.startsWith("written ") ? 1e6 : 1);
        // Nothing to change where the editor holds the text already, as at each key typed in a comment.
        const same = state.doc.length === laidOut.text.length && state.sliceDoc() === laidOut.text;
        const made = same ? { changes: [], arrived: [] } : reconcile(state.doc, ownersOf(state.doc, runs), laidOut.text, laidOut.owners, weight);
        const changing = state.changes(made.changes);
        const visual = visualOf(current);
        const anchor = landed(laidOut, changing, arriving);
        // What's written in Markdown goes with the text, which is read by it in this transaction; and whose each line
        // is; and, but as the review is first laid out, what arrived flashes.
        current.dispatch({
            changes: changing,
            selection: anchor === null ? undefined : { anchor },
            scrollIntoView: anchor !== null,
            annotations: rebuilt.of(true),
            effects: [sourced.of(laidFor.sources), owned.of(laidOut.runs), ...(before.current === null ? [] : [arrivedLines.of(made.arrived)])],
        });
        if (current.state.doc.length !== laidOut.text.length || current.state.sliceDoc() !== laidOut.text) {
            // The changes always make the text laid out; were they ever not to, it's laid out whole, and said.
            console.error("lup: the review's changes didn't make its layout; laid out whole");
            current.dispatch({ changes: { from: 0, to: current.state.doc.length, insert: laidOut.text }, annotations: rebuilt.of(true), effects: owned.of(laidOut.runs) });
        }
        revisualized(current, visual, changing);
        // A fold never closes over the operator's words: one coming to hold a comment it didn't, or holding the one
        // being written, opens, as the operator would open it to write there.
        const at = current.state.selection.main.head;
        const writing = blocksOf(laidOut).find((each) => at >= each.from && at <= each.to)?.comment;
        const holding = new Map<string, Set<string>>();
        for (const block of blocksOf(laidOut)) {
            for (const fold of laidFor.folds) {
                if (block.from > fold.from && block.from <= fold.to) {
                    holding.set(fold.key, (holding.get(fold.key) ?? new Set()).add(block.comment));
                }
            }
        }
        for (const fold of laidFor.folds) {
            const holds = holding.get(fold.key);
            const was = held.current.get(fold.key);
            const came = holds !== undefined && [...holds].some((each) => each === writing || was === undefined || !was.has(each));
            if (came && closedAs(fold, kept.current)) {
                kept.current.set(fold.key, false);
            }
        }
        held.current = holding;
        refold(current, laidFor.folds, kept.current);
        // Where a fold closed over the cursor, as an item marked read folds, it goes to the fold's summary line.
        const closed = laidFor.folds.filter((each) => isFolded(current.state, each));
        const seen = uncovered(closed, current.state.selection.main.head);
        if (seen !== current.state.selection.main.head) {
            current.dispatch({ selection: { anchor: seen }, annotations: rebuilt.of(true) });
        }
        // A comment opened where a closed fold hides it opens the folds over it, as a jump does, saying so, so the
        // cursor goes into it.
        const opens = anchor !== null && arriving !== null && "comment" in arriving ? reaching(current.state, anchor) : [];
        if (anchor !== null && opens.length > 0) {
            current.dispatch({ effects: opens, selection: { anchor }, scrollIntoView: true, annotations: reached.of(opens.length) });
        }
        // The cursor's line kept where it was on screen, once the heights of what changed above it are measured: the
        // view's own scroll, written as it's measured rather than asked as a scroll, which a key in the same frame
        // would replace.
        if (onScreen !== null) {
            const kept = current.state.selection.main.head;
            current.requestMeasure({
                key: "lup-keep-cursor",
                read: (measured) => offsetOf(measured, kept),
                write: (offset, measured) => {
                    if (Math.abs(offset - onScreen) > 1) {
                        measured.scrollDOM.scrollTop += offset - onScreen;
                    }
                },
            });
        }
        read(laidOut);
        before.current = laidOut;
        // What was drafted before it was anchored to its block, or had an id, is taken into the draft as it's laid out
        // now, once, as no step `u` undoes.
        if (laidOut.converted !== null) {
            editor.rewrite(withWritten(editor.latest.current, laidOut.converted));
        }
        // The host keeps where the groups go, once the page has what the review is laid out from: what's laid out,
        // and what's gone from it since the page last told it, the host's places it doesn't lay out the first time.
        if (order !== null) {
            const shown = laidOut.groups.map((each) => each.place);
            if (keepOrder !== null) {
                const keeping = toKeep(shown, toldOrder.current ?? order, order);
                toldOrder.current = shown;
                if (keeping !== null) {
                    keepOrder(keeping);
                }
            }
            places.current = shown;
        }
        landing.current = null;
        editor.draw(decorations(laidOut, draft, reviewed, reachesOf, ends));
        // The margin says what's drawn now.
        current.dispatch({ effects: redrawn.of(null) });
        follower.tell();
        if (arriving !== null && "comment" in arriving) {
            editor.enter();
        }
    }, [laidOut, draft, reviewed]);

    // What's drawn beside the text, as it's laid out now and as each agent is doing: how long each item has waited,
    // after when it came; what each agent is doing and for how long, after the core's words on its banner; and each
    // span of a view's that ticks or measures, where it goes. Said again by the clock, not laid out.
    useEffect(() => {
        const current = view.current;
        if (current === null) {
            return;
        }
        const ticks: Tick[] = [
            ...laidOut.drawn.map((each) => ({ at: each.at, said: (at: Date) => spanSaid(each.span, at), look: each.span.gauge != null ? "drawn-gauge" : "drawn-ticking" })),
            ...laidOut.regions.map((region) => {
                const line = laidOut.text.slice(region.header.from, region.header.to);
                const came = when(region.item.made);
                const at = line.indexOf(came);
                return { at: region.header.from + (at < 0 ? line.length : at + came.length), said: (now: Date) => ` · ${waited(region.item.made, now)}`, look: "drawn-wait" };
            }),
            ...laidOut.groups.flatMap((group) => {
                const key = group.conversation === null ? null : whose(group.conversation);
                if (key === null || !activities.has(key)) {
                    return [];
                }
                const activity = activities.get(key) ?? null;
                return [{ at: group.banner.from + "━━ ".length + banner(group.head).length, said: (now: Date) => ` · ${doing(activity, now)}`, look: "drawn-doing" }];
            }),
        ];
        current.dispatch({ effects: ticked.of(ticks) });
    }, [laidOut, activities, banner, view]);

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

    /**
     * Do what the verb named `name` does where the cursor is (`reachOf`): mark what it reaches in the draft, or take the
     * mark off where it's marked already, each thing marked folding as the layout says, however the operator left it;
     * run what runs at once; or say why nothing there takes it. An item left for later goes to the review's end, the
     * cursor going on to the item after it.
     */
    function verb(name: string) {
        const known = looks.verbs.find((each) => each.name === name);
        if (known === undefined) {
            return;
        }
        const reach = reachOf(laidOut, editor.head(), known, { called });
        if (reach.on === null) {
            say(`␣${known.key} ${known.called}: ${reach.why}.`);
            return;
        }
        for (const each of reach.acts) {
            if (each.kind === "once") {
                act(each.offer, each.conversation);
            }
        }
        const now = editor.latest.current;
        const next = marking(now, reach.acts, name);
        if (next === now) {
            return;
        }
        for (const each of reach.acts) {
            unkeep(each);
        }
        const leaving = reach.acts.find((each) => each.kind === "item" && each.list === "parked" && !isMarked(now, each, name));
        if (leaving !== undefined && leaving.kind === "item") {
            const at = laidOut.regions.findIndex((each) => each.item.number === leaving.number);
            const after = laidOut.regions.slice(at + 1).find((each) => !(next.parked ?? []).includes(each.item.number));
            landing.current = after === undefined ? null : { item: after.item.number };
        }
        editor.record(next);
    }

    /**
     * Do what the verb named `name` does on each of `folds`, a visual selection's, as one mark (`reachedIn`): each thing
     * one of them holds whole and the verb reaches, marked, or every mark taken off where each is marked already.
     */
    function verbOn(name: string, folds: readonly Folding[]) {
        const known = looks.verbs.find((each) => each.name === name);
        if (known === undefined) {
            return;
        }
        const acts = reachedIn(laidOut, folds, known, { called });
        if (acts.length === 0) {
            say(`␣${known.key} ${known.called}: nothing selected takes it.`);
            return;
        }
        for (const each of acts) {
            if (each.kind === "once") {
                act(each.offer, each.conversation);
            }
        }
        const now = editor.latest.current;
        const next = marking(now, acts, name);
        if (next === now) {
            return;
        }
        for (const each of acts) {
            unkeep(each);
        }
        const off = acts.every((each) => isMarked(now, each, name));
        say(`␣${known.key} ${known.called}: ${off ? "unmarked" : "marked"} ${acts.length}, sent with Ctrl+Enter.`);
        editor.record(next);
    }

    /** Forget how the operator left the fold of what `act` marks, an item's or a file's, so it folds as the layout says once marked or unmarked. */
    function unkeep(act: Act) {
        if (act.kind === "item") {
            const region = laidOut.regions.find((each) => each.item.number === act.number);
            if (region !== undefined) {
                kept.current.delete(foldKey({ of: region.of, kind: "item", name: "" }));
            }
            return;
        }
        if (act.kind !== "mark") {
            return;
        }
        const node = findNode(laidOut.nodes, act.block);
        const fold = node === undefined ? undefined : laidFor.folds.find((each) => each.kind === "file" && each.summary.from === node.from);
        if (fold !== undefined) {
            kept.current.delete(fold.key);
        }
    }

    /**
     * Return what the line of keys says with the cursor at `at`: what it's on, the innermost thing a verb reaches there,
     * and what each verb would do, each with what it's on where that's another thing, as on an agent from an item.
     */
    function hereAt(at: number): Here {
        if (laidOut.text === "") {
            return { on: "nothing waiting", reached: [] };
        }
        const reached = looks.verbs.flatMap((each) => {
            if (each.name === "comment") {
                const said = commentSays(at);
                return said === null ? [] : [{ keys: `␣${each.key}`, ...said }];
            }
            const reach = reachOf(laidOut, at, each, { called });
            if (reach.on === null) {
                // Pause is declared, and said in an agent's group, where it would act once it's built.
                const agent = each.name === "pause" ? groupAround(laidOut, at)?.conversation : null;
                return agent === null || agent === undefined ? [] : [{ keys: `␣${each.key}`, says: `${each.called}, not built yet`, on: called(agent) }];
            }
            return [{ keys: `␣${each.key}`, says: reach.says, on: reach.on }];
        });
        const writtenOn = blockAt(laidOut, at) === undefined ? null : "your comment";
        const on = writtenOn ?? reached.find((each) => each.on !== null)?.on ?? "";
        return { on, reached: reached.map((each) => ({ ...each, on: each.on === on ? null : each.on })) };
    }

    /**
     * Return what the line of keys says of a fold-wise selection of `folds`: how many of its kind, and what the fold keys
     * and each verb would do to them, the verb's key alone with Space where it isn't a motion (`BARE`).
     */
    function hereChosen(folds: readonly Folding[]): Here {
        const kind = view.current?.state.field(chosenKind) ?? null;
        const what = kindOf(kind ?? undefined)?.called ?? "folds";
        const verbs = looks.verbs.flatMap((each) => {
            if (each.name === "comment") {
                return [];
            }
            const acts = reachedIn(laidOut, folds, each, { called });
            return acts.length === 0 ? [] : [{ keys: `␣${each.key}${BARE.has(each.key) ? ` ${each.key}` : ""}`, says: `${each.called} ${acts.length}`, on: null }];
        });
        return { on: `${what}: ${folds.length} selected`, reached: [{ keys: "za zo zc", says: "toggle, open or close them", on: null }, ...verbs] };
    }

    /**
     * Say what Space c would open at `at`, as the editor opens it (`whole`): a message to an agent, a remark on a
     * drawer's line, on the line the cursor is on, a comment on an item whole; none where it opens none.
     */
    function commentSays(at: number): { says: string; on: string | null } | null {
        const group = groupAt(laidOut, at);
        if (group !== undefined) {
            return group.conversation === null ? null : { says: "write to it", on: called(group.conversation) };
        }
        const drawer = drawerAt(laidOut, at);
        if (drawer !== undefined) {
            return opened(laidOut, at) === undefined ? null : { says: "remark on the line", on: null };
        }
        const region = regionAt(laidOut, at);
        return region === undefined ? null : { says: "comment on it", on: region.named };
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
     * Go to `region`'s item, where there's one: onto where it lands (`arrival`), brought into view where it isn't
     * (`bring`); `reaching` it, as `]a` does, opening the folds over it, else, as `]]` does, on the summary line of
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
        bring(current, at);
    }

    /**
     * Put the cursor on `target`, as a jump does (`]]`, `]a`, `]c`, `]f`, `]g`, `]i`, `]s`): where its line is in view,
     * under what the stack pins over it, the view stays; else it comes in a third of the view from the edge it came in
     * at, so what's around it shows, never at the top nor at the very edge. Vim, ending its key, scrolls the cursor
     * into view the nearest way, so the jump's own scroll is asked after it (`scrollAfterKey`).
     */
    function bring(current: EditorView, target: number) {
        const line = current.lineBlockAt(target);
        const scroller = current.scrollDOM.getBoundingClientRect();
        const top = current.documentTop + line.top;
        const shown = top >= scroller.top + over.current(target) && top + line.height <= scroller.top + current.scrollDOM.clientHeight;
        current.dispatch({ selection: { anchor: target } });
        if (!shown) {
            scrollAfterKey(current, EditorView.scrollIntoView(target, { y: "nearest", yMargin: current.scrollDOM.clientHeight / 3 }));
        }
    }

    /** Go to `position` in the review, as the stack, the margin and the overview do, opening the folds over it, its line under the stack. */
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

    /** Open a drawer where it's laid out, at its group's end, and go to its summary line, as a click on it pinned below does. */
    const openDrawer = (drawer: Drawer) => {
        const current = view.current;
        if (current === null) {
            return;
        }
        const own = laidFor.folds.find((each) => each.of === drawer.of && each.kind === drawer.kind && each.name === "");
        const effects = own !== undefined && isFolded(current.state, own) ? [folding(own, false)] : [];
        current.dispatch({ effects, selection: { anchor: drawer.header.from } });
        current.dispatch({ effects: EditorView.scrollIntoView(drawer.header.from, { y: "start" }) });
        current.focus();
    };

    /**
     * Return what the margin says of the scope whose header is at `from`, of `kind`: a short name, how it stands, what
     * the draft does with it on the next Ctrl+Enter, and whether it's new; none for a fold that isn't a scope's.
     */
    const labelOf = (kind: FoldKind | Sticky["kind"], from: number): Labelled | null => {
        const plain = (text: string): Labelled => ({ text, state: null, draft: null, fresh: false });
        switch (kind) {
            case "group": {
                const group = laidOut.groups.find((each) => each.banner.from === from);
                const conversation = group?.conversation ?? null;
                if (conversation === null) {
                    return plain("approvals");
                }
                const state = states.get(whose(conversation)) ?? null;
                const glyph = state === "calling" ? "▶" : state === "idle" ? "○" : "✕";
                return { ...plain(called(conversation).split("/").at(-1) ?? ""), state: { glyph, mark: state ?? "ended" } };
            }
            case "item": {
                const region = laidOut.regions.find((each) => each.header.from === from);
                if (region === undefined) {
                    return null;
                }
                const standing = itemStanding(region, draft, reviewed);
                const mark = standing.marks[0];
                return {
                    text: cited(region.item.number),
                    state: mark === undefined ? null : { glyph: GLYPHS[mark] ?? " ", mark },
                    draft: standing.draft.length === 0 ? null : standing.draft.map((each) => DRAFTED[each].glyph).join(""),
                    fresh: standing.fresh,
                };
            }
            case "drawer": {
                // A drawer by its view's name, the conversation's shorter, marked where it holds what waits on the operator, as its view says.
                const drawer = laidOut.drawers.find((each) => each.header.from === from);
                const which = drawer?.kind ?? "";
                return { ...plain(which === "conversation" ? "talk" : which), state: drawer?.waiting === true ? { glyph: "◇", mark: "to-review" } : null };
            }
            case "file": {
                // A file by its name, flagged where a line in it matters, folded where its view folds it whole, else to review.
                const scope = scopeAt(laidOut, from);
                const filed = scope?.filed.find((each) => each.from === from);
                if (filed === undefined || scope === undefined) {
                    return null;
                }
                const path = filed.file.path;
                const matters = scope.stops.some((each) => each >= filed.from && each <= filed.to);
                const folded = !(filed.file.open ?? true);
                const state = matters ? { glyph: "⚑", mark: "flagged" } : folded ? { glyph: "·", mark: "folded" } : { glyph: "◇", mark: "to-review" };
                // Marked reviewed in the draft, it says so as an item marked read does.
                const node = chainAt(laidOut.nodes, from).findLast((each) => each.kind === "block" && each.from === from);
                const marked = node !== undefined && marksOn(draft, node.id).some((each) => each.verb === "done");
                return { ...plain(path.split("/").at(-1) ?? path), state, draft: marked ? DRAFTED.read.glyph : null };
            }
            default:
                return kindOf(kind)?.drawer === true ? labelOf("drawer", from) : null;
        }
    };
    /** Go to the next or previous scope of `kind`, as `]` or `[` and its letter does: onto its header, a closed fold hiding it counting as its summary line, brought into view where it isn't (`bring`). */
    function scopeAfter(kind: ScopeKey, forward: boolean) {
        const current = view.current;
        if (current === null) {
            return;
        }
        const targets =
            kind === "group"
                ? laidOut.groups.map((each) => each.banner.from)
                : kind === "item"
                  ? laidOut.regions.map((each) => each.header.from)
                  : [
                        ...laidOut.drawers.filter((each) => each.kind === kind).map((each) => each.header.from),
                    ];
        const line = current.state.doc.lineAt(editor.head()).from;
        const landings = [...new Set(targets.map((each) => seen(current, each)))].sort((a, b) => a - b);
        const target = forward ? landings.find((each) => each > line) : landings.findLast((each) => each < line);
        if (target === undefined) {
            say(`No ${kind === "group" ? "agent's group" : kind === "item" ? "item" : `${kind} drawer`} ${forward ? "after" : "before"} this.`);
            return;
        }
        bring(current, target);
    }
    // `\` hides the overview pane or shows it again, as the overview is now.
    const setOverviewNow = useRef(() => setOverview(!overview));
    setOverviewNow.current = () => setOverview(!overview);
    const scopeNow = useRef(scopeAfter);
    scopeNow.current = scopeAfter;
    useEffect(() => {
        setScopeJump((kind, forward) => scopeNow.current(kind, forward));
        setOutlineToggle(() => setOverviewNow.current());
    }, []);
    // The margin: what it reads as the review's laid out now.
    const structured = useRef<Structured>({ folds: [], label: () => null, jump: jumpTo, toggle: () => undefined });
    structured.current = {
        folds: laidFor.folds,
        label: (fold) => (fold.kind !== undefined && fold.scope === true ? labelOf(fold.kind, fold.summary.from) : null),
        jump: jumpTo,
        toggle: (fold) => {
            const current = view.current;
            if (current !== null) {
                current.dispatch({ effects: folding(fold, !isFolded(current.state, fold)) });
            }
        },
    };
    useEffect(() => {
        view.current?.dispatch({ effects: gutters.reconfigure(structureMargin(() => structured.current, !narrow)) });
    }, [view, gutters, narrow]);

    editor.bind({
        whole: (position) => {
            // On a group, a message to its agent; on an item, a comment on it whole; in a drawer, a remark on its line.
            if (groupAt(laidOut, position) !== undefined || drawerAt(laidOut, position) !== undefined) {
                return opened(laidOut, position);
            }
            const region = regionAt(laidOut, position);
            return region === undefined ? undefined : { id: "", item: region.item.number, quote: null, text: "" };
        },
        opened: (position) => opened(laidOut, position),
        quoted: (from, to) => quoted(laidOut, from, to),
        about: (comment, block) => aboutAt(laidOut, comment, block),
        verb,
        verbOn,
        // Space f and a letter selects in the item or the drawer the cursor is in, or, on a banner, in its agent's group.
        chooseIn: (position) => {
            const scope = scopeAt(laidOut, position);
            if (scope !== undefined) {
                const own = scope.folds.find((each) => each.of === scope.of && kindOf(each.kind)?.whole === true);
                return { from: scope.header.from, to: own?.to ?? scope.header.to };
            }
            const group = groupAt(laidOut, position);
            return group === undefined ? undefined : { from: group.banner.from, to: group.fold?.to ?? group.banner.to };
        },
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
                        (fold) => fold.of === scope.of && kindOf(fold.kind)?.whole === true && isFolded(current.state, fold),
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
            bring(current, target);
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
            bring(current, target);
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
        send,
        paint: (from, to) => painted(laidOut, from, to, freshOf),
        level: (position, opening, all, closed) => levelled(scopeFolds(position), closed, opening, all),
        // `zO` and `zC` within the item or the drawer the cursor is in; on a banner, its group's.
        scope: (position) => {
            const within = scopeFolds(position);
            return within.length > 0 ? within : laidFor.folds.filter((each) => each.kind === "group");
        },
    });

    /**
     * Do what `offer` offers at once, on what's of `conversation`: a module's view key. None runs yet, since a module's
     * actions aren't a door the page reaches (#113, step 4), so it says so; the page's own views' offers are marks.
     */
    function act(offer: Offer, conversation: Conversation | null) {
        void conversation;
        say(`Nothing here does ${offer.says} yet: a module's actions come with #113's step 4.`);
    }

    /** Return the folds of the item or the drawer `position` is in, as the editor holds them: those the fold keys reach. */
    function scopeFolds(position: number): Folding[] {
        const keys = new Set(foldsOf(laidOut, position).map(foldKey));
        return laidFor.folds.filter((each) => keys.has(each.key));
    }

    // What the overview reads beside the review as it's laid out.
    const reading = useMemo(() => ({ draft, reviewed, states, called }), [draft, reviewed, states, called]);
    const focusing = useCallback((focus: (() => void) | null) => setOutlineFocus(focus), []);

    const naming = {
        // A group by its banner's words, the core's and each part's, as its banner says them.
        group: (group: Group) =>
            [banner(group.head), ...group.parts.flatMap((each) => {
                const words = (each.answer?.blocks.summary ?? []).map((span) => span.text).join("");
                return words === "" ? [] : [words];
            })].join(" · "),
        item: (region: Region) => region.named,
        party: called,
    };
    const where = <Heading parts={heading(laidOut, Math.min(head, laidOut.text.length), commenting, laidOut.written, naming)} tally={tallied(items, draft, reviewed)} />;
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
                    (draft.declined ?? []).includes(number) ? "is-declined" : "",
                    (draft.parked ?? []).includes(number) ? "is-parked" : "",
                ].join(" ");
            }
            case "drawer": {
                const drawer = laidOut.drawers.find((each) => each.header.from === sticky.header.from);
                return drawer === undefined ? "drawer-label" : drawerClasses(drawer);
            }
            case "file":
                return "code-file";
        }
    };
    // Each pinned header's fold, its letter in its column and its label, as the margin has them.
    const pinnedFolds = useMemo(() => {
        const kinded = laidFor.folds.filter((each) => each.kind !== undefined && each.scope === true);
        const deep = depths(laidFor.folds.filter((each) => each.kind !== undefined));
        return new Map(kinded.map((each) => [each.summary.from, { fold: each, depth: deep.get(each) ?? 0 }]));
    }, [laidFor.folds]);
    const markOf = (sticky: Sticky): StackMark | null => {
        const found = pinnedFolds.get(sticky.header.from);
        const kind = found?.fold.kind;
        if (found === undefined || kind === undefined) {
            return null;
        }
        const letter = kindOf(kind)?.letter ?? "";
        return { kind, letter, depth: found.depth, label: narrow ? null : labelOf(kind, sticky.header.from) };
    };
    // What settles what a pinned header heads, so the operator knows what would validate the file they're in.
    const hintOf = (sticky: Sticky): string | null => {
        if (sticky.kind === "group") {
            return null;
        }
        // What done and decline do there, from the same walk the keys take, each naming what it's on where that's another thing.
        const here = hereAt(sticky.header.from);
        const answers = here.reached.filter((each) => looks.verbs.some((verb) => `␣${verb.key}` === each.keys && (verb.name === "done" || verb.name === "decline")));
        const said = answers.map((each) => `${each.keys} ${each.says}${each.on === null ? "" : ` ${each.on}`}`);
        const region = sticky.kind === "item" ? regionAt(laidOut, sticky.header.from) : undefined;
        const asks = region?.item.reason.reason === "question" ? ["a comment answers it"] : [];
        return said.length === 0 && asks.length === 0 ? null : [...asks, ...said].join(" · ");
    };
    return (
        <>
            {where}
            <div className={`review-body${overview ? " with-overview" : ""}`}>
                <Outline
                    following={follower}
                    laidOut={laidOut}
                    reading={reading}
                    narrow={narrow}
                    open={overview}
                    setOpen={setOverview}
                    jump={jumpTo}
                    back={() => view.current?.focus()}
                    focusing={focusing}
                />
                <div className="buffer-wrap">
                    <div className="buffer review-buffer" ref={editor.parent} />
                    <Stack following={follower} roots={roots} text={laidOut.text} classesOf={classesOf} markOf={markOf} hintOf={hintOf} narrow={narrow} jump={jumpTo} />
                </div>
            </div>
        </>
    );
}

export type { DrawerKind };
