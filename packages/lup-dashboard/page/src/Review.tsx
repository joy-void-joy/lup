// The review: everything waiting for the operator in one buffer moved through
// with vim (`editor.ts`), grouped by thread, in sections (`review.ts`,
// `layThreaded`), each thread's banner saying where it stands
// (`threadBanner`), Space `d` and `x` on one done settling and declining it,
// `o` on its banner writing on it, Space `s` sending that to no one, `gd` on an
// agent's name going to their own views; each agent in a group of their own
// among the agents, every agent running having one, empty or not; their comments written into it, each under the line it's
// on: Space `c` opens one on the item whole; `o` or Space `c` on a banner, a
// message to its agent, under the banner; `o` in an agent's drawer, a remark to
// them. Ctrl+Enter elsewhere than in a comment or a message sends. Space and a
// verb's key acts on the innermost thing at the cursor it applies to, as a
// mark in the draft (`grammar.ts`): Space `d` marks an item read, approves an
// approval or a held change, marks a file of "since you approved" reviewed,
// Space `x` declines, Space `s` leaves an item for later, Space `h` holds an
// agent's flagged writes from anywhere in their group; `]]` and `[[` go to the next and
// previous item, landing on its first line that matters, `]a` and `[a` to the
// next and previous item to answer, in the order they came, `]c` and `[c` to the
// next and previous such line. Under an approval or a held change, each file it
// changes, whole, its lines numbered, marked and highlighted as they come into
// view, each line that matters by the judge's reading barred and saying what it
// triggered; the item's header counts its files by why each is open; under each
// item, its context. Under each agent's banner, their drawers
// (`review.ts`): their tasks, what their branch changed since the operator last
// saw it, live, where Space `d` marks a file reviewed at the version shown and, on
// the drawer's line, every file shown, each line changed since they last looked at its file
// marked (`since.ts`), and their conversation, each call's input and output read
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
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";

import { tokensOf, within, type Filed, type Matter, type Taken } from "./code";
import { cited, type Block, type Folding, type Span } from "./comments";
import { BARE, chosenKind, closedAs, folding, hiddenAt, isFolded, jumped as recordJump, mapLetters, mapVerbs, reached, reaching, rebuilt, refold, scrollAfterKey, uncovered, useEditor, vimOf, type Landing } from "./editor";
import { arrivedLines, arriving, owned, owning, ownersOf, readBy, reconcile, settling, type Reading } from "./reconcile";
import { clock, ticked, ticking, type Tick } from "./ticking";
import { doing, since, type Activity } from "./agents";
import { Following } from "./follow";
import { usePaced } from "./hooks";
import { mapOutlineKey, mapScopeKeys, Outline, setOutlineFocus, setOutlineToggle, setScopeJump, useNarrow, type ScopeKey } from "./Outline";
import { Stack, type Mark as StackMark } from "./Stack";
import { redrawn, structureMargin, type Labelled, type Structured } from "./rails";
import { itemStanding } from "./outline";
import { DRAFTED, GLYPHS } from "./Outline";
import { linesOver, stickies, type Sticky } from "./stack";
import { depths, levelled } from "./folds";
import { chainAt, findNode, implied, isMarked, marking, marksOn, movedInto, reachOf, reachedIn, type Act, type Destination, type Marked } from "./grammar";
import { ThreadPalette } from "./Palette";
import type { DrawerKind, FoldKind, Here } from "./keys";
import { kindOf, type Merged } from "./looks";
import { markerEnd, outdated, unfound } from "./exchange";
import { source, sourced, without, type Source } from "./markdown";
import {
    ROOT_TITLE,
    barsOf,
    aboutAt,
    headerClasses,
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
    nextToReview,
    pageUnits,
    foldKey,
    foldsOf,
    fresh,
    type Seeing,
    groupAround,
    groupAt,
    heading,
    isDrawer,
    isLetter,
    isRegion,
    isRemark,
    laid,
    opened,
    ordered,
    quoted,
    quotedAt,
    recipient,
    regionAt,
    sameId,
    scopeAt,
    sectionAt,
    shownAt,
    shownAs,
    sinceFileAt,
    stepped,
    tallied,
    toAnswer,
    toKeep,
    waits,
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
    type PlacedFile,
    type Region,
    type Scope,
    type SectionName,
    type Threading,
    type ThreadRead,
    type Wait,
    type Where,
    type Written,
    reachedBy,
    checkAt,
    placeIn,
    threadPlace,
} from "./review";
import { filesOf, freshRows, type Fresh } from "./since";
import type { Instance, Offer, Remote, Running, Span as ViewSpan } from "./views";

/** The least and the most time between two layouts of what the host answers, in milliseconds (`usePaced`). */
const PACED_LEAST = 250;
const PACED_MOST = 2000;

/** Where the page asks the review to go: an agent's group, by their conversation, numbered so the same one asked twice goes twice. */
export interface Jump {
    to: Conversation;
    number: number;
}

interface Props {
    items: Item[];
    /** The review's threads, as the host reads them, and what of each the page has read: what it's grouped by, where given; none groups it by agent. */
    threads?: Omit<Threading, "banner"> | null;
    /** Told each thread whose conversation a fold reads as it opens, whole where it's what came before, so the page asks it of the host. */
    openThread?: (number: number, whole: boolean) => void;
    /** The conversations running, in the order the host lists them: each has a group, empty or not. */
    agents: Conversation[];
    draft: Draft;
    /** What's typed in a comment and not yet given as `draft`, the editor showing it already: whatever lays the review out lays it out with it. */
    typed: { readonly current: Draft | null };
    /** Change the draft; `typed` where it's only what's typed in a comment, which the editor shows already (`Config.change`). */
    change: (draft: Draft, typed?: boolean) => void;
    /** Name a group: the agent who sent its items, or the one it's of, and where; what they're doing; their context. */
    banner: (head: Head) => string;
    /** Name a conversation as it's called, as whom a comment goes to. */
    called: (party: Conversation) => string;
    /** What the host has answered of each item beyond its own text: its context, and each file it changes, an approval's or a held change's. */
    around: Around;
    /** What the host has answered of each agent, for their banner and their drawers. */
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
    /** How far the operator has seen each group, and what they commented on in a reply sent: what an item is new by. */
    seeing: Seeing;
    /** Told the marks the operator's comments imply, a comment counting as a review (`implied`), as the review is laid out. */
    implying: (marks: Marked[]) => void;
    /** What each conversation running is doing, by `whose` they are, drawn on their banner as the time passes (`ticking.ts`). */
    activities: ReadonlyMap<string, Activity | null>;
    /** Each conversation's parent, by `whose` each is: what nests a subagent's group under their parent's. */
    parents: ReadonlyMap<string, string>;
    /** What each conversation running is doing, by `whose` they are, for the overview's marks. */
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
    /** Each conversation running, by `whose` they are: their banner's parts, and what holding their writes asks. */
    running: ReadonlyMap<string, Running>;
    /** The landings waiting on the operator, which the judge's part of a banner says. */
    landings: readonly Wait[];
    /** What the host answered of each view the page doesn't lay out itself, by its instance's id (`views.ts`). */
    remote: Remote;
    /** Told each view a fold reads as it opens, its module's, as the operator opens it, so the page asks it of the host. */
    load: (view: Instance) => void;
    /** Given how to read the review's size, as the page's timings take it (`timings.ts`): its lines, the items, the drawers open. */
    sizing?: RefObject<(() => Readonly<Record<string, number>>) | null>;
}

/** Return the classes a line under an item or in a drawer is drawn with: what it shows, and whether it's set in under a summary or a file's header, as a file's reviewed line isn't. */
function asideClasses(aside: Aside, code: boolean): string {
    const under = aside.kind === "summary" || aside.kind === "refused" || aside.kind === "reviewed" ? null : "aside-under";
    return [`aside-${aside.kind}`, under, code ? "code-run" : null].filter((each) => each !== null).join(" ");
}

/**
 * Say a thread's banner, as the core says it: its name and what it's about, a root by whose it is; who holds it, or who
 * answers for it where its holder has ended; and where it stands, what asks the operator in it, how many files a
 * landing waits on there, `landing`, done for them to confirm, what's new, else its state.
 */
export function threadBanner(read: ThreadRead, landing: number, called: (party: Conversation) => string, section: SectionName = "open"): string {
    const thread = read.thread;
    // A root is its session's own, named as they are: an ended session's, which lup knows only by its ids, is said so.
    const root = thread.parent == null && thread.title === ROOT_TITLE;
    const about = root ? "the session's own" : thread.title;
    const holder = thread.holder == null ? null : called(thread.holder);
    const answering = read.answering == null ? null : called(read.answering);
    const ended = root && holder !== null && holder !== answering ? "its session has ended" : null;
    const holds =
        holder === null
            ? answering === null
                ? "nobody holds it"
                : `nobody holds it, ${answering} answers`
            : holder === answering
              ? `${holder} holds`
              : `${ended ?? `${holder} held it`}${answering === null ? "" : `, ${answering} answers`}`;
    const asks = tallyWords((read.asks ?? []).map((each) => each.what));
    const fresh = (read.new ?? []).length;
    const waiting = (read.asks ?? []).length + (landing === 0 ? 0 : 1);
    const status = read.status ?? null;
    // Where it stands: working, where what waits on the operator in it is counted; parked until what wakes it.
    const state =
        status !== null && status.kind === "ledger:parked"
            ? `parked until ${status.until.map((each) => until(each, called)).join(" or ")}`
            : read.state === "waiting on the operator"
              ? "working"
              : read.state === "done to confirm"
                ? "done, to confirm"
                : read.state;
    // What the section says of it: in waiting on you, what asks the operator there; in new, how much is new; in open and
    // settled, where it stands, and how much of it waits on them or is new, which those sections show.
    const says =
        section === "waiting on you"
            ? [...asks, ...(landing === 0 ? [] : [`landing waits on ${landing === 1 ? "1 file" : `${landing} files`}`]), ...(read.state === "done to confirm" ? ["done, to confirm"] : [])].join(", ")
            : section === "new"
              ? `${fresh} new`
              : [state, [...(waiting === 0 ? [] : [`${waiting} waiting`]), ...(fresh === 0 ? [] : [`${fresh} new`])].join(", ")].filter((each) => each !== "").join(" · ");
    return `━━ @${thread.name} · ${about} · ${holds} · ${says} ━━`;
}

/** Say what a parked thread waits for, one of what wakes it, as `thread`'s `park` takes it. */
function until(trigger: NonNullable<ThreadRead["status"]> extends infer S ? (S extends { until: (infer T)[] } ? T : never) : never, called: (party: Conversation) => string): string {
    switch (trigger.trigger) {
        case "issue closed":
            return typeof trigger.issue === "number" ? `#${trigger.issue} closes` : `${trigger.issue} closes`;
        case "branch landed":
            return `${trigger.branch} lands`;
        case "commit landed":
            return `${trigger.commit.slice(0, 8)} lands`;
        case "conversation ended":
            return `${called(trigger.conversation)} ends`;
        case "time came":
            return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(trigger.at));
        case "condition held":
            return `${trigger.when} holds`;
        default:
            return "what it waits for comes";
    }
}

/** Say what of each kind there is, `a question` once, `2 questions` twice, in the order first said. */
function tallyWords(whats: readonly string[]): string[] {
    const counted = new Map<string, number>();
    for (const each of whats) {
        counted.set(each, (counted.get(each) ?? 0) + 1);
    }
    return [...counted].map(([what, count]) => (count === 1 ? what : `${count} ${what.replace(/^an? /, "")}s`));
}

/** Say what waits below, grouped by thread, for the header over the review: how many threads wait on the operator, and how many are new. */
function threadTally(laidOut: Laid): string {
    const count = (name: string) => laidOut.groups.filter((group) => group.depth === 0 && laidOut.sections.findLast((each) => each.header.from < group.banner.from)?.name === name).length;
    const waiting = count("waiting on you");
    const fresh = count("new");
    return [`${waiting} waiting on you`, ...(fresh === 0 ? [] : [`${fresh} new`])].join(" · ");
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
 * drawer's, as the agent's words in their conversation, the remarks under them left out; and each comment, message and
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
 * end it is, a subagent's with their parent's where they end together, set in as the innermost is.
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
    seeing: Seeing,
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
        // A thread's banner, marked by where it stands: what asks the operator, done for them to confirm, settled.
        const thread = group.thread === null ? "" : ` thread-banner state-${group.thread.state.replace(/ /g, "-")}`;
        marks.push({ from: group.banner.from, to: group.banner.from, value: Decoration.line({ class: `${bannerClasses(group.depth)}${thread}` }) });
        marks.push(...group.blocks.flatMap((block) => remarks(laidOut, block)));
        group.blocks.forEach(reaching);
    }
    // Each section's line; and each line of a thread's that's no item's nor drawer's, the operator's words moved in, a
    // check, what's to try, in what it shows.
    for (const section of laidOut.sections) {
        marks.push({ from: section.header.from, to: section.header.from, value: Decoration.line({ class: `review-section section-${section.name.replace(/ /g, "-")}` }) });
    }
    for (const aside of laidOut.asides) {
        marks.push({ from: aside.from, to: aside.from, value: Decoration.line({ class: `aside-${aside.kind} thread-line` }) });
    }
    // An item of the pile marked read, said on its line, as what else the draft marks is.
    for (const entry of laidOut.pile.flatMap((each) => each.entries)) {
        if ((draft.done ?? []).includes(entry.item.number)) {
            marks.push({ from: entry.header.from, to: entry.header.from, value: Decoration.line({ class: "is-marked mark-done", attributes: { "data-mark": "read" } }) });
        }
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
            const states = headerClasses(region.item, draft, seeing);
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

/**
 * Return where `gt` lands in thread `thread` laid out whole, in open or settled: on the line pointing to `node`, the item
 * or check it went from, laid out above; on `node` itself where it's laid out there; else on the thread's banner; none
 * where the thread isn't laid out whole.
 */
export function threadTarget(laidOut: Laid, thread: number, node: number | null): number | undefined {
    const whole = laidOut.groups.find((each) => each.place === threadPlace(thread));
    if (whole === undefined) {
        return undefined;
    }
    const within = (at: number) => at > whole.banner.from && at <= whole.end;
    const pointer = node === null ? undefined : laidOut.pointers.find((each) => each.thread === thread && each.node === node && within(each.from));
    const region = node === null ? undefined : laidOut.regions.find((each) => each.item.number === node && within(each.header.from));
    return pointer?.from ?? region?.header.from ?? whole.banner.from;
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
/**
 * Return where `gd` goes from a banner whose parts name another agent's drawer, as a landing waiting on files in its
 * writer's "since you approved" does: that drawer's line, the first named; none where the cursor is on no banner, or
 * its parts name none laid out.
 */
function namedDrawer(laidOut: Laid, position: number): number | undefined {
    const group = groupAt(laidOut, position);
    const named = (group?.parts ?? []).flatMap((part) => (part.answer?.blocks.summary ?? []).flatMap((span) => (span.conversation == null ? [] : [span.conversation])));
    for (const each of named) {
        const drawer = laidOut.drawers.find(
            (one) => one.kind === "since" && one.conversation.runtime === each.runtime && one.conversation.session === each.session && (one.conversation.agent ?? null) === (each.agent ?? null),
        );
        if (drawer !== undefined) {
            return drawer.header.from;
        }
    }
    return undefined;
}

/**
 * Return the agent whose name is under the cursor at `position`, grouped by thread, as a thread's banner or an item's
 * header says it, `called` naming them: their group among the agents, where their own views are; the longest name there
 * first, so a subagent's path wins over their session's. None where no agent's name is under it.
 */
export function agentNamed(laidOut: Laid, position: number, called: (party: Conversation) => string): Group | undefined {
    const start = laidOut.text.lastIndexOf("\n", position - 1) + 1;
    const end = laidOut.text.indexOf("\n", position);
    const line = laidOut.text.slice(start, end < 0 ? laidOut.text.length : end);
    const column = position - start;
    const agents = laidOut.groups
        .filter((each) => each.thread === null && each.conversation !== null)
        .map((group) => ({ group, name: called(group.conversation as Conversation) }))
        .sort((a, b) => b.name.length - a.name.length);
    for (const { group, name } of agents) {
        let at = line.indexOf(name);
        while (at >= 0) {
            const before = line[at - 1] ?? " ";
            const after = line[at + name.length] ?? " ";
            if (column >= at && column <= at + name.length && !/[\w/-]/.test(before) && !/[\w/-]/.test(after)) {
                return group;
            }
            at = line.indexOf(name, at + 1);
        }
    }
    return undefined;
}

/** What names a file of a "since you approved" drawer among its others: its block's id after `file ` or `reviewed `, its path and, past the drawer's first place, its place's. */
function fileKey(file: PlacedFile): string {
    return file.block.replace(/^(file|reviewed) /, "");
}

/** Return what names the file `filed` shows among the others of `drawer` (`fileKey`): its path where the drawer shows it in no block it knows. */
function fileKeyOf(drawer: Drawer, filed: Filed): string {
    const placed = shownAs(drawer, filed);
    return placed === undefined ? filed.path : fileKey(placed);
}

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
    items: itemsGiven,
    threads: threadsGiven = null,
    openThread = () => undefined,
    agents: agentsGiven,
    draft: given,
    typed,
    change,
    banner: bannerGiven,
    called: calledGiven,
    around: aroundGiven,
    drawers: drawersGiven,
    send,
    opened: told,
    jump,
    say,
    inserting,
    epoch,
    placed,
    pending,
    list,
    seeing: seeingGiven,
    implying,
    activities,
    parents,
    states,
    overview,
    setOverview,
    order: orderGiven,
    keepOrder,
    looks,
    running,
    landings,
    remote,
    load,
    sizing,
}: Props) {
    // Where the cursor is, and whether a comment is being written: what the header says.
    const [head, setHead] = useState(0);
    // The folds a fold-wise selection holds, while there's one: what the line of keys says the keys do to.
    const choosing = useRef<readonly Folding[] | null>(null);
    const [commenting, setCommenting] = useState(false);
    // What Space s moves from the pile while the operator names the thread it goes to, in the palette over the review.
    const [moving, setMoving] = useState<readonly Extract<Act, { kind: "move" }>[] | null>(null);
    // Where the groups go: as this page laid them out last, then as the host keeps them for those it didn't
    // (`ordered`), so each keeps its place, across reloads and on each page; and as it last told the host it laid
    // them out, none until it has, when what it doesn't lay out of the host's order is gone.
    const places = useRef<string[]>([]);
    const toldOrder = useRef<string[] | null>(null);
    const narrow = useNarrow();
    // What the host answers, as the review lays it out: once the review has been read as the page loads, taken no more
    // often than four times what laying the review out last cost, a quarter of a second at least and two at most, so
    // the hooks of agents at work, each answering the agent's record, its views and the listing again, lay it out at
    // most a few times a second, however often they come, whatever the machine (#341). The operator's own words and
    // marks are laid out at once.
    const cost = useRef(0);
    // How the review is being first read (`readBy`): until it's read, what the host answers is laid out as it comes.
    const loading = useRef<Reading>({ since: null, last: 0, read: false });
    const answered = useMemo(
        () => ({ items: itemsGiven, agents: agentsGiven, banner: bannerGiven, called: calledGiven, around: aroundGiven, drawers: drawersGiven, seeing: seeingGiven, order: orderGiven, parents, looks, running, landings, remote, threadsRead: threadsGiven }),
        [itemsGiven, agentsGiven, bannerGiven, calledGiven, aroundGiven, drawersGiven, seeingGiven, orderGiven, parents, looks, running, landings, remote, threadsGiven],
    );
    // While a comment is being typed, what's typed laid out once typing pauses, the host's answers wait as long as
    // they may, so the keys aren't held up behind a layout: what came meanwhile is laid out with what was typed.
    const { items, agents, banner, called, around, drawers, seeing: seenGiven, order, threadsRead, ...arrangedBy } = usePaced(answered, () =>
        !loading.current.read ? 0 : typed.current !== null ? PACED_MOST : Math.min(PACED_MOST, Math.max(PACED_LEAST, 4 * cost.current)),
    );
    // What's new to the operator: grouped by thread, each item that came after where they last read its thread.
    const seeing = useMemo(() => {
        if (threadsRead === null) {
            return seenGiven;
        }
        // What's new in a thread and what asks the operator there, of what came after where they last read it.
        const later = new Set(
            [...threadsRead.shown.values(), ...threadsRead.whole.values()].flatMap((each) =>
                each.entries.flatMap((entry) => (entry.member && entry.spot.part == null && entry.earlier !== true ? [entry.spot.node] : [])),
            ),
        );
        const calling = threadsRead.read.threads.flatMap((each) => [...(each.new ?? []), ...(each.asks ?? []).map((ask) => ask.node)]);
        return { ...seenGiven, threaded: new Set(calling.filter((each) => later.has(each))) };
    }, [seenGiven, threadsRead]);
    // The threads, each banner saying what the core says of it (`threadBanner`).
    const threads = useMemo<Threading | null>(() => (threadsRead === null ? null : { ...threadsRead, banner: (read, landing, section) => threadBanner(read, landing, called, section) }), [threadsRead, called]);
    // The same object while what it holds is the same, as the rest of what's taken is.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const arranging = useMemo(() => ({ ...arrangedBy, threads }), [arrangedBy.parents, arrangedBy.looks, arrangedBy.running, arrangedBy.landings, arrangedBy.remote, threads]);
    // The review as it was last laid out into the editor, which each comment is followed from (`Arranging.previous`).
    const before = useRef<Laid | null>(null);
    // Laid out with what's typed in a comment, though it isn't given yet, so the text laid out is what the editor holds.
    const layout = useMemo(() => {
        const drafted = typed.current ?? given;
        const began = performance.now();
        const laidOut = laid(
            items,
            agents,
            (head, later, parts) => `━━ ${banner(head)}${parts === "" ? "" : ` · ${parts}`}${later ? " · later" : ""} ━━`,
            // What the item's kind says of it, then what the core says of how it stands.
            (item, later, said) => {
                // Grouped by thread, an item says whose it is, as a conversation's line does: several agents write in one.
                const whose = threads !== null && item.sender.party === "conversation" ? [called(item.sender)] : [];
                // Grouped by thread, one no longer waiting says where it stands: answered, done, decided.
                const stands = threads !== null && !waits(item) ? [item.state.state] : [];
                const told = [
                    `${cited(item.number)} ${said}`,
                    ...whose,
                    ...stands,
                    ...((item.edits ?? []).length > 0 ? ["edited"] : []),
                    ...(fresh(item, seeing) ? ["new"] : []),
                    when(item.made),
                    ...(later ? ["later"] : []),
                ];
                return `── ${told.join(" · ")} ──`;
            },
            drafted,
            around,
            ordered(places.current, order ?? []),
            drawers,
            called,
            { ...arranging, previous: before.current },
        );
        return { drafted, laidOut, cost: performance.now() - began };
        // `typed` is read as the review is laid out, whatever else lays it out: what's typed alone doesn't.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [items, agents, banner, called, given, around, drawers, seeing, arranging, order, threads]);
    const { laidOut } = layout;
    // The draft as the review is laid out: with what was typed in a comment as it was laid out.
    const draft = layout.drafted;
    // What the operator's comments imply, a comment counting as a review, shown as the draft's own marks are and sent
    // with them.
    const impliedMarks = useMemo(() => implied(laidOut, draft), [laidOut, draft]);
    const withImplied = useMemo(() => (impliedMarks.length === 0 ? draft : { ...draft, marks: [...(draft.marks ?? []), ...impliedMarks] }), [draft, impliedMarks]);
    useEffect(() => implying(impliedMarks), [impliedMarks, implying]);
    // The scopes the header stack pins the headers of.
    const roots = useMemo(() => stickies(laidOut), [laidOut]);
    const laidFor = useMemo(
        () => ({
            text: laidOut.text,
            blocks: blocksOf(laidOut),
            // In the text's order, as CodeMirror takes the folds a transaction makes: a fold over others, as an
            // automatic file's or an item's marked read, is laid out after them.
            folds: [...scopesOf(laidOut).flatMap((each) => each.folds), ...laidOut.groups.flatMap((each) => (each.fold === null ? [] : [each.fold])), ...laidOut.outer]
                .map((each) => ({ ...each, key: foldKey(each) }))
                .sort((a, b) => a.from - b.from || b.to - a.to),
            sources: sourcesOf(laidOut),
        }),
        [laidOut],
    );
    // The start of each file's header line: where `]f` and `[f` go, and where a key held down or a page scroll stops.
    const heads = useMemo(() => fileHeads(laidOut), [laidOut]);
    const units = useMemo(() => pageUnits(laidOut), [laidOut]);
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
        moved: (moved) => {
            // Where it is in the review as it's laid out, what's typed in a comment since laid out once typing pauses.
            const at = editor.toLaid(moved);
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
            // A thread's conversation, read as its fold opens: from where it was read, or what came before, whole.
            for (const each of laidOut.loading) {
                if (each.key === fold.key) {
                    openThread(each.number, each.whole);
                }
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
    over.current = (position) => linesOver(roots, editor.toLaid(position), narrow) * (view.current?.defaultLineHeight ?? 18);
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
    // The review's size, as the page's timings take it, read as a key goes down, once a second at most: its lines, the
    // items waiting, and the drawers open, each by its own fold, read among the drawer's own folds as it's asked. Nothing
    // is worked out as the review is laid out, which a key typed waits on.
    if (sizing !== undefined) {
        sizing.current = () => {
            const current = view.current;
            if (current === null) {
                return {};
            }
            const open = laidOut.drawers.filter((drawer) => {
                const own = drawer.folds.find((each) => each.kind === drawer.kind && each.name === "");
                return own !== undefined && !isFolded(current.state, editor.live(own));
            });
            return { lines: current.state.doc.lines, items: items.length, "drawers open": open.length };
        };
    }

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
                const line = editor.toLaid(current.state.doc.lineAt(current.posAtDOM(label)).from);
                const drawer = laidNow.current.drawers.find((each) => each.header.from === line);
                const laidOwn = drawer?.folds.find((each) => each.kind === drawer.kind && each.name === "");
                if (laidOwn !== undefined) {
                    const own = editor.live(laidOwn);
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
                current.dispatch({ selection: { anchor: editor.fromLaid(Number(answered)) }, scrollIntoView: true });
                return;
            }
            const at = editor.toLaid(current.posAtDOM(target));
            const laidFold = citationsOf(laidNow.current).find((each) => at >= each.marker.from && at <= each.marker.to)?.fold;
            if (laidFold != null) {
                const fold = editor.live(laidFold);
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
        isDrawer(scope) && scope.kind === "since" ? freshRows(looked.current.get(lookedAt(scope.of, fileKeyOf(scope, file))) ?? null, file) : null;

    // What each group's end says of whose it is: a thread's, its name.
    const ends: Ends = (group) =>
        group.thread !== null ? `@${group.thread.thread.name}` : group.conversation === null ? "lup's approvals" : (called(group.conversation).split("/").at(-1) ?? "");

    /** Say whom what's written reaches, on its first line, where the header no longer says it: the stack's. */
    const reachesOf = (each: Written): string => {
        if (isLetter(each) || isRemark(each)) {
            return reachedBy(laidOut, each, each.to ?? null, called);
        }
        // A comment on a check answers it, which tells whoever asked it.
        if (laidOut.checks.some((check) => check.check.check.number === each.item)) {
            return `answering the check ${cited(each.item)}`;
        }
        const item = laidOut.regions.find((region) => region.item.number === each.item)?.item;
        const party = item === undefined ? null : recipient(item);
        return reachedBy(laidOut, each, party, called);
    };

    /** Take each "since you approved" drawer read for the first time as looked at, and forget what was looked at of each file standing as the operator last saw it, which shows each of its changes once it comes back. */
    function read(laid: Laid) {
        // A drawer read with nothing in it isn't shown, but it's been read: a file coming to it later is new to the operator.
        for (const [key, data] of drawers) {
            if (data.since != null && filesOf(data.since).length === 0) {
                firstRead.current.add(`since ${key}`);
            }
        }
        for (const drawer of laid.drawers) {
            if (drawer.kind !== "since") {
                continue;
            }
            const first = !firstRead.current.has(drawer.of);
            firstRead.current.add(drawer.of);
            for (const each of drawer.files) {
                const key = lookedAt(drawer.of, fileKey(each));
                const shownFile = each.file.file == null ? undefined : drawer.diffs.get(each.block);
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
        const now = drawer === undefined || file === undefined ? null : { of: drawer.of, path: fileKey(file) };
        const was = inFile.current;
        inFile.current = now;
        if (was === null || (now !== null && now.of === was.of && now.path === was.path)) {
            return;
        }
        const drawerWas = laidOut.drawers.find((each) => each.of === was.of);
        const placed = drawerWas?.files.find((each) => fileKey(each) === was.path);
        const standing = placed === undefined || placed.file.file == null ? undefined : drawerWas?.diffs.get(placed.block);
        if (standing === undefined) {
            return;
        }
        looked.current.set(lookedAt(was.of, was.path), standing);
        // Drawn once the cursor's move is done, which this is told of while CodeMirror is still telling it.
        queueMicrotask(() => editor.draw(decorations(laidOut, withImplied, seeing, reachesOf, ends)));
    }
    // Which comments each fold held as the review was last laid out, by its key: one that comes to hold another opens.
    const held = useRef(new Map<string, Set<string>>());

    useEffect(() => {
        const current = view.current;
        if (current === null) {
            return;
        }
        // Laid out before what was typed since, as where a key comes between a render the host's answer made and this,
        // it's not put in, lest it take back what was typed: the review is laid out again with it.
        if (editor.latest.current !== draft) {
            change(editor.latest.current);
            return;
        }
        const began = performance.now();
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
        // Nothing to change where the editor holds the text already, as once typing in a comment pauses.
        const same = state.doc.length === laidOut.text.length && state.sliceDoc() === laidOut.text;
        const made = same ? { changes: [], arrived: [] } : reconcile(state.doc, ownersOf(state.doc, runs), laidOut.text, laidOut.owners, weight);
        const changing = state.changes(made.changes);
        const visual = visualOf(current);
        const anchor = landed(laidOut, changing, arriving);
        const now = Date.now();
        const flashing = readBy(loading.current, order !== null, now);
        // What's written in Markdown goes with the text, which is read by it in this transaction; and whose each line
        // is; and, once the review has been read (`readBy`), what arrived flashes.
        current.dispatch({
            changes: changing,
            selection: anchor === null ? undefined : { anchor },
            scrollIntoView: anchor !== null,
            annotations: rebuilt.of(true),
            effects: [sourced.of(laidFor.sources), owned.of(laidOut.runs), ...(flashing ? [arrivedLines.of({ lines: made.arrived, at: now })] : [])],
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
        // The thread `gt` went to, read whole now: onto the item it went from, in its conversation.
        const pending = pendingThread.current;
        const whole = pending === null ? undefined : laidOut.groups.find((each) => each.place === threadPlace(pending.thread));
        if (pending !== null && whole !== undefined && whole.fold?.unread !== true) {
            pendingThread.current = null;
            const to = threadTarget(laidOut, pending.thread, pending.node);
            const at = editor.fromLaid(to ?? whole.banner.from);
            if (to !== undefined && to !== whole.banner.from) {
                current.dispatch({ selection: { anchor: at }, effects: reaching(current.state, at) });
                current.dispatch({ effects: EditorView.scrollIntoView(at, { y: "start" }) });
            }
            recordJump(current, Math.min(pending.from, current.state.doc.length), at);
        }
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
        editor.draw(decorations(laidOut, withImplied, seeing, reachesOf, ends));
        // The margin says what's drawn now.
        current.dispatch({ effects: redrawn.of(null) });
        follower.tell();
        if (arriving !== null && "comment" in arriving) {
            editor.enter();
        }
        // What laying the review out cost: laying it out, and putting it in the editor, which paces the next (`usePaced`).
        cost.current = layout.cost + performance.now() - began;
    }, [laidOut, withImplied, seeing]);

    // What's drawn beside the text, as it's laid out now and as each agent is doing: how long each item has waited,
    // after when it came; what each agent is doing and for how long, after the core's words on their banner; and each
    // span of a view's that ticks or measures, where it goes. Said again by the clock, not laid out. Each is placed in
    // the text laid out, so only once it's in the editor (`before`), and not while what's typed in a comment since waits
    // to be laid out (`TYPED`): each is laid out again with it, when they're placed anew. Placed in another text, one
    // past the editor's end would throw as the next change is mapped, and the page with it. The lengths say what's typed
    // without reading the whole text again at each hook: what's typed and leaves them equal moves no tick.
    useEffect(() => {
        const current = view.current;
        if (current === null || before.current !== laidOut || current.state.doc.length !== laidOut.text.length) {
            return;
        }
        const ticks: Tick[] = [
            ...laidOut.drawn.map((each) => ({ at: each.at, said: (at: Date) => spanSaid(each.span, at), look: each.span.gauge != null ? "drawn-gauge" : "drawn-ticking" })),
            // How long each item still waiting has waited: one answered or done, as a thread's conversation shows, has not.
            ...laidOut.regions.filter((region) => waits(region.item)).map((region) => {
                const line = laidOut.text.slice(region.header.from, region.header.to);
                const came = when(region.item.made);
                const at = line.indexOf(came);
                return { at: region.header.from + (at < 0 ? line.length : at + came.length), said: (now: Date) => ` · ${waited(region.item.made, now)}`, look: "drawn-wait" };
            }),
            ...laidOut.groups.flatMap((group) => {
                // An agent's group says what they're doing; a thread's banner says where it stands.
                const head = group.head;
                const key = group.conversation === null || "thread" in head ? null : whose(group.conversation);
                if (key === null || "thread" in head || !activities.has(key)) {
                    return [];
                }
                const activity = activities.get(key) ?? null;
                return [{ at: group.banner.from + "━━ ".length + banner(head).length, said: (now: Date) => ` · ${doing(activity, now)}`, look: "drawn-doing" }];
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

    // Where `gt` goes once the thread it went to is read whole: the thread, and the item or check it went from.
    const pendingThread = useRef<{ thread: number; node: number | null; from: number } | null>(null);

    /** Say whether `item` is new to the operator, its group not seen since it came: what done on a banner marks seen. */
    const isFresh = (item: Item) => fresh(item, seeing);

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
        const reach = reachOf(laidOut, editor.head(), known, { called, fresh: isFresh });
        if (reach.on === null) {
            say(`␣${known.key} ${known.called}: ${reach.why}.`);
            return;
        }
        if (moves(reach.acts, known.key, name)) {
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
        // A file of "since you approved" marked reviewed, the cursor goes on to the next one to review there.
        const marks = reach.acts.flatMap((each) => (each.kind === "mark" && !isMarked(now, each, name) ? [each.block] : []));
        const onward = name === "done" && marks.length > 0 ? nextToReview(laidOut, marks, next) : undefined;
        if (onward !== undefined) {
            landing.current = { at: editor.fromLaid(onward) };
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
        const acts = reachedIn(laidOut, folds, known, { called, fresh: isFresh });
        if (acts.length === 0) {
            say(`␣${known.key} ${known.called}: nothing selected takes it.`);
            return;
        }
        if (moves(acts, known.key, name)) {
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

    /**
     * Move what `acts` reach of the pile into a thread, as Space s, `key`, does there: where each is marked moved
     * already, take the marks off; else ask the operator which thread, in the palette, where they're one repository's.
     * Return whether `acts` were the pile's, which nothing else does.
     */
    function moves(acts: readonly Act[], key: string, name: string): boolean {
        const pile = acts.filter((each): each is Extract<Act, { kind: "move" }> => each.kind === "move");
        if (pile.length === 0) {
            return false;
        }
        const now = editor.latest.current;
        if (pile.every((each) => isMarked(now, each, name))) {
            editor.record(marking(now, pile, name));
            say(`␣${key}: ${pile.length === 1 ? "no longer moved" : `${pile.length} no longer moved`}.`);
            return true;
        }
        const repositories = [...new Set(pile.map((each) => each.repository))];
        if (repositories.length > 1) {
            say(`␣${key}: these are of ${repositories.length} repositories, and a thread holds one's: move each repository's apart.`);
            return true;
        }
        setMoving(pile);
        return true;
    }

    /** Mark what's being moved from the pile moved into `to`, the thread the operator named in the palette, and go back to the review. */
    function movedTo(to: Destination | null) {
        const pile = moving;
        setMoving(null);
        // The keyboard back to the review once the palette has let it go.
        requestAnimationFrame(() => view.current?.focus());
        if (pile === null || to === null) {
            return;
        }
        editor.record(movedInto(editor.latest.current, pile, to));
        const into = "thread" in to ? `into @${to.name}` : `into a new thread, “${to.title}”`;
        say(`␣s send to: ${pile.length === 1 ? "1 moved" : `${pile.length} moved`} ${into}, sent with Ctrl+Enter.`);
    }

    /** Forget how the operator left the fold of what `act` marks, an item's, a file's or a drawer's, so it folds as the layout says once marked or unmarked. */
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
        const drawer = node?.kind === "view" && laidOut.drawers.some((each) => each.view.id === node.id);
        const fold = node === undefined ? undefined : laidFor.folds.find((each) => (each.kind === "file" || (drawer && each.scope === true)) && each.summary.from === node.from);
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
            const reach = reachOf(laidOut, at, each, { called, fresh: isFresh });
            if (reach.on === null) {
                // Pause is declared, and said in an agent's group, where it would act once it's built; decline on a flagged
                // write says why it doesn't, the write having landed (#247).
                const agent = each.name === "pause" ? groupAround(laidOut, at)?.conversation : null;
                if (agent !== null && agent !== undefined) {
                    return [{ keys: `␣${each.key}`, says: `${each.called}, not built yet`, on: called(agent) }];
                }
                const drawer = each.name === "decline" ? drawerAt(laidOut, at) : undefined;
                const flagged = drawer?.kind === "since" && (sinceFileAt(drawer, at)?.file.flags ?? []).length > 0;
                return flagged ? [{ keys: `␣${each.key}`, says: `${each.called}, not yet: a flagged write has landed, and is declined once a landing waits on it`, on: null }] : [];
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
            const acts = reachedIn(laidOut, folds, each, { called, fresh: isFresh });
            return acts.length === 0 ? [] : [{ keys: `␣${each.key}${BARE.has(each.key) ? ` ${each.key}` : ""}`, says: `${each.called} ${acts.length}`, on: null }];
        });
        return { on: `${what}: ${folds.length} selected`, reached: [{ keys: "za zo zc", says: "toggle, open or close them", on: null }, ...verbs] };
    }

    /**
     * Say what Space c would open at `at`, as the editor opens it (`whole`): a message to an agent, a remark on a
     * drawer's line, on the line the cursor is on, a comment on an item whole; none where it opens none.
     */
    function commentSays(at: number): { says: string; on: string | null } | null {
        const check = checkAt(laidOut, at);
        if (check !== undefined) {
            return { says: "answer it in your words", on: `check ${cited(check.check.check.number)}` };
        }
        const group = groupAt(laidOut, at);
        if (group !== undefined && group.thread !== null) {
            return { says: group.conversation === null ? "write on it, to no one" : `write on it, to ${called(group.conversation)}`, on: `@${group.thread.thread.name}` };
        }
        if (group !== undefined) {
            return group.conversation === null ? null : { says: "write to them", on: called(group.conversation) };
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
        (laidAt: number) => {
            const current = view.current;
            if (current === null) {
                return;
            }
            const position = editor.fromLaid(laidAt);
            const effects = reaching(current.state, position);
            current.dispatch({ selection: { anchor: position }, effects: [...effects, EditorView.scrollIntoView(position, { y: "start" })], annotations: reached.of(effects.length) });
            current.focus();
        },
        // The editor's places are read from what it holds as it's called, whichever render's editor it is.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [view],
    );

    /** Open a drawer where it's laid out, at its group's end, and go to its summary line, as a click on it pinned below does. */
    const openDrawer = (drawer: Drawer) => {
        const current = view.current;
        if (current === null) {
            return;
        }
        const laidOwn = laidFor.folds.find((each) => each.of === drawer.of && each.kind === drawer.kind && each.name === "");
        const own = laidOwn === undefined ? undefined : editor.live(laidOwn);
        const header = editor.fromLaid(drawer.header.from);
        const effects = own !== undefined && isFolded(current.state, own) ? [folding(own, false)] : [];
        current.dispatch({ effects, selection: { anchor: header } });
        current.dispatch({ effects: EditorView.scrollIntoView(header, { y: "start" }) });
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
                // A thread by its name, marked as it stands: asking the operator, done for them to confirm, new.
                const read = group?.thread ?? null;
                if (read !== null) {
                    const waiting = read.state === "waiting on the operator" || read.state === "done to confirm";
                    return {
                        ...plain(`@${read.thread.name}`),
                        state: waiting ? { glyph: GLYPHS.waiting ?? "◆", mark: "waiting" } : (read.new ?? []).length > 0 ? { glyph: GLYPHS.news ?? "•", mark: "news" } : null,
                    };
                }
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
                const standing = itemStanding(region, draft, seeing);
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
                const marked = node !== undefined && marksOn(withImplied, node.id).some((each) => each.verb === "done");
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
    // Where the text is now, what's typed in a comment ahead of the layout (`Editor.toLaid`): the margin is drawn line
    // for line with the text as it stands, and says what the layout does.
    structured.current = {
        get folds() {
            return editor.folds();
        },
        label: (fold) => (fold.kind !== undefined && fold.scope === true ? labelOf(fold.kind, editor.toLaid(fold.summary.from)) : null),
        jump: (at) => jumpTo(editor.toLaid(at)),
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
            if (group !== undefined) {
                return { from: group.banner.from, to: group.fold?.to ?? group.banner.to };
            }
            // In the pile to read, the thread's run the cursor is in; on the section's line, the whole pile.
            const run = laidOut.pile.find((each) => position >= each.from && position <= each.to);
            if (run !== undefined) {
                return { from: run.from, to: run.to };
            }
            const section = sectionAt(laidOut, position);
            return section?.name === "to read" ? { from: section.header.from, to: section.fold?.to ?? section.header.to } : undefined;
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
        answer: (forward) => {
            // Grouped by thread, what asks the operator in the text's order: an item to answer, a check not answered, a
            // thread done for them to confirm, on its banner.
            const current = view.current;
            if (laidOut.sections.length === 0 || current === null) {
                goTo(answerAfter(laidOut, draft, editor.head(), forward), true);
                return;
            }
            const stops = [
                ...laidOut.regions.filter((each) => toAnswer(each.item, draft)).map(arrival),
                ...laidOut.checks.filter((each) => (each.check.answer ?? null) === null && !(draft.marks ?? []).some((mark) => mark.action === "inbox-check-answer" && mark.block === `check ${each.check.check.number}`)).map((each) => each.from),
                ...laidOut.groups
                    .filter((each) => each.thread?.state === "done to confirm" && each.place === placeIn("waiting", each.thread.thread.number) && !(draft.marks ?? []).some((mark) => mark.block === `group ${each.place}`))
                    .map((each) => each.banner.from),
            ].sort((a, b) => a - b);
            const head = editor.toLaid(editor.head());
            const target = forward ? stops.find((each) => each > head) : stops.findLast((each) => each < head);
            if (target === undefined) {
                say(`Nothing waits on you ${forward ? "after" : "before"} this.`);
                return;
            }
            const at = editor.fromLaid(target);
            opening(current, at);
            bring(current, at);
        },
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
        units: () => units.map((each) => ({ from: editor.fromLaid(each.from), to: editor.fromLaid(each.to) })),
        // The stack over the buffer's top, as it's drawn now.
        pinned: () => editor.parent.current?.parentElement?.querySelector(".stack")?.getBoundingClientRect().height ?? 0,
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
            const head = editor.head();
            const at = editor.toLaid(head);
            // On a thread's line in the pile to read, to that thread whole in open, or settled.
            const run = laidOut.pile.find((each) => at >= each.header.from && at <= each.header.to);
            const home = run === undefined ? undefined : laidOut.groups.find((each) => each.place === threadPlace(run.thread.thread.number));
            // A line in a thread's conversation standing for an item laid out above, to it there.
            const pointer = laidOut.pointers.find((each) => at >= each.from && at <= each.to);
            const pointed =
                pointer === undefined
                    ? undefined
                    : (laidOut.regions.find((each) => each.item.number === pointer.node)?.header.from ?? laidOut.checks.find((each) => each.check.check.number === pointer.node)?.from);
            const placed = home?.banner.from ?? pointed;
            const target = current === null ? undefined : placed !== undefined ? editor.fromLaid(placed) : (following(citationsOf(laidOut), head) ?? namedDrawer(laidOut, head));
            // Grouped by thread, an agent's name goes to their own views among the agents: their conversation, opened.
            const agent = current === null || target !== undefined ? undefined : agentNamed(laidOut, at, called);
            if (current !== null && agent !== undefined) {
                const drawer = agent.drawers.find((each) => each.kind === "conversation") ?? agent.drawers[0];
                const to = editor.fromLaid(drawer?.header.from ?? agent.banner.from);
                const own = drawer === undefined ? undefined : laidFor.folds.find((each) => each.of === drawer.of && each.kind === drawer.kind && each.name === "");
                const effects = [...reaching(current.state, to), ...(own === undefined ? [] : [folding(editor.live(own), false)])];
                current.dispatch({ selection: { anchor: to }, effects, annotations: reached.of(effects.length) });
                current.dispatch({ effects: EditorView.scrollIntoView(to, { y: "start" }) });
                recordJump(current, head, to);
                return;
            }
            if (current === null || target === undefined) {
                say("gd follows a citation of your words to the passage it cites, and that passage back, a banner naming another agent's drawer to it, an agent's name to their own views, a line pointing to an item above to it, and a thread's line in the pile to the thread: put the cursor on one.");
                return;
            }
            const effects = reaching(current.state, target);
            current.dispatch({ selection: { anchor: target }, effects, annotations: reached.of(effects.length) });
            current.dispatch({ effects: EditorView.scrollIntoView(target, { y: placed !== undefined ? "start" : "nearest" }) });
            recordJump(current, head, target);
        },
        thread: () => {
            // From an item of waiting on you or new, or its thread's header there, to the thread whole in open, opened,
            // on that item in its conversation; once read, where it isn't yet.
            const current = view.current;
            const head = editor.head();
            const at = editor.toLaid(head);
            const read = groupAround(laidOut, at)?.thread ?? null;
            if (current === null || read === null) {
                say("gt goes from an item of waiting on you or new, or its thread's header there, to the whole thread in open: put the cursor on one.");
                return;
            }
            const node = regionAt(laidOut, at)?.item.number ?? checkAt(laidOut, at)?.check.check.number ?? null;
            const whole = laidOut.groups.find((each) => each.place === threadPlace(read.thread.number));
            if (whole === undefined) {
                say(`@${read.thread.name} isn't laid out whole.`);
                return;
            }
            const to = editor.fromLaid(threadTarget(laidOut, read.thread.number, node) ?? whole.banner.from);
            const own = whole.fold;
            const fold = own === null ? undefined : laidFor.folds.find((each) => each.key === foldKey(own));
            const effects = [...reaching(current.state, to), ...(fold === undefined ? [] : [folding(editor.live(fold), false)])];
            current.dispatch({ selection: { anchor: to }, effects, annotations: reached.of(effects.length) });
            current.dispatch({ effects: EditorView.scrollIntoView(to, { y: "start" }) });
            // Recorded where it lands: once the thread is read whole, where it isn't yet, so Ctrl-O comes back from there.
            if (own?.unread === true) {
                pendingThread.current = { thread: read.thread.number, node, from: head };
            } else {
                pendingThread.current = null;
                recordJump(current, head, to);
            }
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
    const reading = useMemo(() => ({ draft, seeing, states, called }), [draft, seeing, states, called]);
    const focusing = useCallback((focus: (() => void) | null) => setOutlineFocus(focus), []);

    const naming = {
        // A group by its banner's words, the core's and each part's, as its banner says them.
        group: (group: Group) => {
            const head = group.head;
            if ("thread" in head) {
                return `@${head.thread.thread.name}`;
            }
            return [banner(head), ...group.parts.flatMap((each) => {
                const words = (each.answer?.blocks.summary ?? []).map((span) => span.text).join("");
                return words === "" ? [] : [words];
            })].join(" · ");
        },
        item: (region: Region) => region.named,
        party: called,
    };
    // The threads what's moved from the pile may go to: its repository's, neither settled nor declined, but each it
    // landed in, in the order they were opened.
    const movable = useMemo(() => {
        if (moving === null || threads === null) {
            return [];
        }
        const repository = moving[0]?.repository ?? "";
        const numbers = new Set(moving.map((each) => each.number));
        const landed = new Set(laidOut.pile.filter((run) => run.entries.some((each) => numbers.has(each.item.number))).map((run) => run.thread.thread.number));
        return threads.read.threads
            .filter((each) => each.thread.repository === repository && each.state !== "settled" && each.state !== "declined" && !landed.has(each.thread.number))
            .toSorted((a, b) => a.thread.number - b.thread.number);
    }, [moving, threads, laidOut.pile]);
    const where = <Heading parts={heading(laidOut, Math.min(head, laidOut.text.length), commenting, laidOut.written, naming)} tally={threads === null ? tallied(items, draft, seeing) : threadTally(laidOut)} />;
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
                return headerClasses(region.item, draft, seeing);
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
            <ThreadPalette moving={moving === null ? null : moving.map((each) => each.number)} threads={movable} choose={movedTo} />
        </>
    );
}

export type { DrawerKind };
