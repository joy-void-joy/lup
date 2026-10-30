// The review: everything waiting for the operator laid out as one text to read
// and move through, grouped by thread, in sections, each thread's conversation
// from where the operator last read it, each agent's own views in a group of
// theirs among the agents (`layThreaded`); or, where the host reads no threads,
// in groups, one per agent, every agent running having one, empty or not;
// their comments in it, each under the line it's on, and their messages to
// each agent under the agent's banner, or on a thread under its banner. A tree (`laid`, `Laid.nodes`): the
// core lays out the frame, the groups in the order they arrived, never sorted
// again, each banner, each item's header and what's around its body (the
// operator's words an answer answers, its edits, its citations' passages, the
// replies kept from before, its context) and the comments; inside it, each
// module's view (`views.ts`): an item's body is its kind's view of it, its text
// and its files, each file whole (`code.ts`), its lines commented on as the
// item's own are, the lines that matter in it, by the judge's reading
// (`views/judge.ts`), kept in order for the keys to walk; under each agent's
// banner, before their items, each drawer their repository's looks place
// (`docs/dashboard.md`, *The drawers*), their task list, what their branch
// changed since the operator approved it, each file laid out as an item's, and
// their whole conversation, `Transcripts`' view of it, each a fold of its own kind under a
// short label, one under the other, folded until opened in place; a comment on
// the agent's words in the conversation, a Markdown block of a drawer's, or on
// the changed files is a remark to the agent, the one on code recording the
// version it was written on. Each comment goes under the
// last line it quotes of the block it's on, followed there as the block
// changes (`anchors.ts`). A subagent's group under their parent's, each group
// folding whole under its banner. Each part keeps an id across layouts, and
// each line is the innermost part's laid out on it, which the editor keeps the
// buffer by (`reconcile.ts`). Their kind's rank, which the host gives, says only which
// `]a` and `[a` stop at. Each fold has a kind: the item whole, a file, a
// function's or a class's body, a run of unchanged lines, the context, a
// drawer's, a module's own. What's folded by default: the context, each run of
// a file's unchanged lines away from its changes and the lines that matter, so
// every change shows, never a changed line among unchanged ones; a file its
// view folds whole, as a test, a data file and each file of a first approval;
// an item marked read or left for later, and each drawer; a body is open, but
// a new module's in its drawer, which shows its design. Each fold is named by
// what it hides, so an item or a drawer laid out again keeps the folds the
// operator left; and where the cursor is, said in the header over the review,
// is the group, the item or the drawer and the folds it's in. Pure: the editor
// (`Review.tsx`) draws it, folds it and lets what's written be edited, and the
// host keeps the draft (`docs/dashboard.md`, *The review*). What it shares
// with an item's context is in `comments.ts`.
import { since } from "./agents";
import { endInLast, keptId, linesOf, placed as placedOn, quoting, type Lines, type Placement } from "./anchors";
import { shownOnce, type Body, type ChangedFile, type Filed, type Matter, type Row } from "./code";
import {
    calls,
    lineOf,
    passage,
    saying,
    cited,
    shownIn,
    spoken,
    starts as startsOf,
    under,
    type Block,
    type Line,
    type Quote,
    type Span,
} from "./comments";
import { SET_IN, above, citedOn, editedOf, markerEnd, passageOf, type Citation, type Row as Beside, type RowKind } from "./exchange";
import { around } from "./folds";
import type { components } from "./generated/api";
import type { DrawerKind, FoldKind } from "./keys";
import { adopted, kindOf, type Merged } from "./looks";
import {
    blockId,
    conversationOf,
    instanceOf,
    whose,
    UNREAD,
    type AgentDrawers,
    type Answered,
    type Block as ViewBlock,
    type Drawers,
    type Instance,
    type Mounted,
    type Offer,
    type PlacedFile,
    type Remote,
    type Running,
    type Shown,
    type Span as ViewSpan,
} from "./views";
import type { Run } from "./reconcile";
import { kindView, mount, producerOf } from "./views/index";
import { plain } from "./views/core";
import { body } from "./views/inbox";
import { sinceSummary } from "./views/judge";

export { body, calls, plain, sinceSummary, UNREAD, whose, type AgentDrawers, type Answered, type Block, type ChangedFile, type Drawers, type Line, type Span };

export type Item = components["schemas"]["Item"];
export type Draft = components["schemas"]["Draft"];
export type Comment = components["schemas"]["Comment"];
/** The operator's message: to a conversation, under their agent's banner; or on a thread, to whoever answers for it as they write, or to no one (`to` none). Never on an item, nor quoting anything, which a comment and a remark are. */
export type Letter = components["schemas"]["Letter"] & { item?: never; quote?: never };
export type Remark = components["schemas"]["Remark"];
export type Conversation = components["schemas"]["Conversation"];
export type PartId = components["schemas"]["PartId"];
export type Reply = components["schemas"]["Reply"];
export type { Quote } from "./comments";
export type Context = components["schemas"]["Context"];
export type Since = components["schemas"]["Since"];
export type SinceFile = components["schemas"]["SinceFile"];
export type SincePlace = components["schemas"]["SincePlace"];
export type Viewed = components["schemas"]["ViewedFile"];
export type Wait = components["schemas"]["Wait"];
export type { PlacedFile };
export type Task = components["schemas"]["Task"];
export type Usage = components["schemas"]["Usage"];
export type ThreadRead = components["schemas"]["ThreadRead"];
export type ThreadShown = components["schemas"]["ThreadShown"];
export type ThreadsRead = components["schemas"]["ThreadsRead"];
export type ThreadEntry = components["schemas"]["ThreadEntry"];
export type CheckRead = components["schemas"]["CheckRead"];

/**
 * A section of the review grouped by thread, in its order: what asks the operator, what came that they haven't read,
 * the front, every other thread still open, the pile to read, what's settled or declined, and each agent with their
 * own views.
 */
export type SectionName = "waiting on you" | "new" | "open" | "to read" | "settled" | "agents";

/** The sections, in the review's order, and whether each starts folded: the front, open, is there to look at. */
export const SECTIONS: readonly { name: SectionName; folded: boolean }[] = [
    { name: "waiting on you", folded: false },
    { name: "new", folded: false },
    { name: "open", folded: false },
    { name: "to read", folded: true },
    { name: "settled", folded: true },
    { name: "agents", folded: true },
];

/**
 * The review's threads, as the host reads them (`docs/inbox.md`, *Threads in the review*), and what of each the page has
 * read: each thread, its section and what asks; each one's conversation from where the operator last read it, for those
 * shown; each read whole, for those whose earlier part was opened; how many files a landing waits on in each, read from
 * the landings waiting by the thread their lander works in; and the banner's words for each.
 */
export interface Threading {
    read: ThreadsRead;
    shown: ReadonlyMap<number, ThreadShown>;
    whole: ReadonlyMap<number, ThreadShown>;
    landing: ReadonlyMap<number, number>;
    banner: (read: ThreadRead, landing: number) => string;
}

/** One section of the review where it's laid out: its line, saying what it holds, and its fold whole under it. */
export interface Section {
    name: SectionName;
    header: Span;
    fold: Fold | null;
}

/** A check in a thread, where it's laid out: from its first line to its last, the comments under it among them. */
export interface CheckLine extends Span {
    check: CheckRead;
    thread: number;
}

/** A fold read from the host as it opens, by its key (`foldKey`): a thread's conversation, from where it was read or whole. */
export interface Loading {
    key: string;
    number: number;
    whole: boolean;
}

/** What the operator writes in the review, as its editor holds it: a comment on an item, a message to an agent, or a remark in one of their drawers. */
export type Written = Comment | Letter | Remark;

/**
 * What the review shows of each item beyond its own text, by the item's number, once the host has answered: its
 * context, and each file it changes (`changing`); the operator's own items about those listed, those a turn's end
 * answers or cites, shown above it (`above`), and those on an item, with any replies kept on them from before, shown
 * under it (`threadsOf`); and the agents' items those are on, as they stand (`commented`).
 */
export interface Around {
    contexts: Map<number, Answered<Context>>;
    files: Map<number, Answered<ChangedFile[]>>;
    answers: Item[];
    commented: Item[];
}

/** One of the operator's own earlier comments on an item, as an item of theirs that answered it carried it: its part's id in that item, and what it's on. */
export interface Earlier {
    id: PartId;
    text: string;
    /** The passage of the item's text it's on; of the reply `on`'s text, where it continues a thread. */
    quote: Quote | null;
    /** The agent's reply it answers, where it continues a thread. */
    on: PartId | null;
    /** The decision it rules on, from 1, for an answer's ruling. */
    decision: number | null;
}

/** One reply of the agent's, as the operator's item kept it from before agents answered in their turn's last words: its own id, the part it answers, and its words. */
export interface Replied {
    id: PartId;
    to: PartId;
    text: string;
}

/** What's under an item kept with replies from before: the operator's earlier comments on it, and the agent's replies to them (`docs/dashboard.md`, *The review*). */
export interface Thread {
    said: Earlier[];
    replies: Replied[];
}

/** Return whether two ids name the same part. */
export function sameId(a: PartId | null | undefined, b: PartId | null | undefined): boolean {
    return a != null && b != null && a.item === b.item && a.part === b.part;
}

/** Say a part's id as lup cites it, `546.2`. */
export function idOf(id: PartId): string {
    return `${id.item}.${id.part}`;
}

/** Say a ruling as the operator's words: its verdict, then its comment. */
function ruled(verdict: string | null | undefined, comment: string): string {
    return [verdict ?? null, comment === "" ? null : comment].filter((each) => each !== null).join(" · ");
}

/**
 * Return the thread under item `number`: the operator's comments on it as their items `answers` carry them (a review's
 * comments in its order, each numbered as the host numbers its parts; a reply's comment; an answer's rulings, then its
 * comment), and the replies the agent made on those items.
 */
export function threadsOf(answers: Item[], number: number): Thread {
    const said: Earlier[] = [];
    const replies: Replied[] = [];
    for (const answer of answers) {
        const reason = answer.reason;
        const at = (part: number): PartId => ({ item: answer.number, part });
        if (reason.reason === "review") {
            reason.comments.forEach((comment, index) => {
                if (comment.item === number) {
                    said.push({ id: at(index + 1), text: comment.text, quote: comment.quote ?? null, on: comment.on ?? null, decision: null });
                }
            });
        } else if (reason.reason === "message" && reason.of === number) {
            said.push({ id: at(1), text: reason.text, quote: null, on: null, decision: null });
        } else if (reason.reason === "answer" && reason.question === number) {
            const rulings = reason.rulings ?? [];
            rulings.forEach((ruling, index) => {
                said.push({ id: at(index + 1), text: ruled(ruling.verdict, ruling.comment ?? ""), quote: null, on: null, decision: ruling.decision });
            });
            if ((reason.comment ?? "") !== "") {
                said.push({ id: at(rulings.length + 1), text: reason.comment ?? "", quote: null, on: null, decision: null });
            }
        } else {
            continue;
        }
        // A reply is kept on the item of the part it answers: those on this item's comments.
        for (const reply of answer.replies ?? []) {
            if (said.some((each) => sameId(each.id, reply.to))) {
                replies.push({ id: at(reply.number), to: reply.to, text: reply.text });
            }
        }
    }
    return { said, replies };
}


/**
 * What a line under an item or in a drawer that isn't the operator's or the agent's own text shows: a fold's summary;
 * a step of a context or a conversation, the operator's words, the agent's, a run of calls, a call and a line of its
 * input and output, or the call that made the item; an item of the inbox in a conversation, and a line of its text; a
 * task; a file standing as the operator last saw it, in "since you approved"; or why the host showed none. Around an
 * agent's answer, who wrote what follows, what the operator's words are on, their words, the agent's, a passage a
 * citation cites, and a line an edit took away or put in (`RowKind`, `exchange.ts`).
 */
export type Kind =
    | "summary"
    | RowKind
    | "calls"
    | "call"
    | "call-text"
    | "anchor"
    | "refused"
    | "item-from"
    | "item-to"
    | "item-text"
    | "task"
    | "reviewed"
    | (string & {});

/** A line of an item's or a drawer's own, which comments may be on: where it is, where it starts in its own text, and the block it's of (`blockId`), at its line there. */
export interface OwnLine extends Line {
    block: string;
    line: number;
}

/** A line under an item that isn't its own text, so no comment is on it. */
export interface Aside extends Span {
    kind: Kind;
}


/** A line of a changed file under an item or in a drawer, which comments may be on: the file's header, where `row` is none, or one of its rows, and what it triggered where it's a line that matters. */
export interface Coded extends Span {
    file: Filed;
    row: Row | null;
    matter: Matter | null;
}

/**
 * What folds in an item or a drawer, by its kind (`FoldKind`): the item whole under its header, folded where it's
 * marked read or left for later; a drawer under its summary line, folded until opened, but "since you approved", open;
 * each file it changes under its
 * header, folded where its view folds it whole, automatic, asking nothing held or flagged, a test, data, or a first approval's; a function's or a class's body under the
 * line declaring it, open but in a new module of a drawer; a run of a file's unchanged lines under a summary line,
 * folded; and its context, folded. Each sits whole inside another or beside it. It hides `from` to `to`, from the end
 * of its summary line to the end of its last; a file's and a body's from the end of the comments on their first line,
 * which stay in view.
 */
export interface Fold extends Span {
    /** What it's in: an item, by its number, or a drawer, by its agent and kind (`ownerOf`). */
    of: string;
    kind: FoldKind;
    /**
     * What names it among its owner's folds of its kind, by what it hides rather than the row it's laid out on, so an
     * item laid out again keeps each fold as the operator left it: a file by its path; a body by its file and the
     * bodies it's in; a run by its file and what it hides (`Run.name`); an item's own, a drawer's and its context by
     * nothing more.
     */
    name: string;
    /** What the header calls it: the item's own by its header, a drawer by its summary, a file by its path, a body by its name, a run by its summary. */
    label: string;
    /** Whether it's folded until the operator opens it. */
    closed: boolean;
    summary: Span;
    /** Whether it's a scope's: a group's, an item's or a drawer's whole, or a file's. */
    scope?: boolean;
    /** Whether what it holds is read from another view as it opens and isn't read yet, a line saying so in its place. */
    unread?: boolean;
}

/** Where a changed file is under its item or in its drawer: from its header to its last line and the comments under it. */
export interface FileSpan extends Span {
    file: Filed;
}

/** What names an agent's group in its banner: its first item, or, for a group with none, the agent's conversation. */
export type Head = { item: Item } | { conversation: Conversation };

/** What names a group in its banner: an agent's (`Head`), or a thread's, the thread. */
export type GroupHead = Head | { thread: ThreadRead };

/**
 * One group, where it's shown: its banner and, unless it's of the items left for later, the messages to its agent
 * under it, each a comment's block; its items' regions follow it, then its drawers, up to the next group.
 */
export interface Group {
    /** The agent it's of; none for lup's approvals, which no message goes to. */
    conversation: Conversation | null;
    /** The parts of its banner, each a view of its agent's, where they're running. */
    parts: Mounted[];
    /** What its banner names it by. */
    head: GroupHead;
    later: boolean;
    /** What names its place across layouts: whose it is, and whether it's of what's left for later. */
    place: string;
    banner: Span;
    blocks: Block[];
    drawers: Drawer[];
    /** How many groups it's laid out under, a subagent's under their parent's, where they're nested (`Arranging.parents`); 0 else. */
    depth: number;
    /** Its fold whole, under its banner; none where nothing's under its banner. */
    fold: Fold | null;
    /** The thread it is, as the host reads it; none for an agent's group or lup's approvals. */
    thread: ThreadRead | null;
    /** Where its last line ends, its fold's end, or its banner's where nothing's under it. */
    end: number;
}

/**
 * How the review's groups are arranged beyond the order items came in: each subagent's group under their parent's, by
 * `whose` each conversation is and their parent's; how the views look, which drawers and banner parts each repository's
 * agents have (`looks.ts`); each conversation running, with their banner's parts; and what the host answered of
 * each view mounted that the page doesn't lay out itself (`views.ts`).
 */
export interface Arranging {
    parents?: ReadonlyMap<string, string> | null;
    looks?: Merged;
    running?: ReadonlyMap<string, Running>;
    /** The landings waiting on the operator, which the judge's banner part says. */
    landings?: readonly Wait[];
    remote?: Remote;
    /** The review as the page last laid it out, which each comment is followed from, through its block's change since (`placed`, `anchors.ts`); none as it's first laid out. */
    previous?: Laid | null;
    /** The review's threads, which it's grouped by where given (`layThreaded`); none groups it by agent. */
    threads?: Threading | null;
}

/**
 * What an item and a drawer lay out alike: a header line, the lines comments may be on (an item's own, a file's
 * headers and rows, the agent's words) with the comments among them; the lines under it that aren't, and what folds.
 */
export interface Scope {
    /** What names it among the review's folds' owners (`Fold.of`). */
    of: string;
    header: Span;
    lines: OwnLine[];
    blocks: Block[];
    /** Its lines that are a file's, each with its file and row. */
    code: Coded[];
    /** Where each file it shows is, from its header to its last line and the comments under it. */
    filed: FileSpan[];
    asides: Aside[];
    folds: Fold[];
    /** Where its last line ends, the blank line after an item among them: what's after it is its group's. */
    end: number;
    /** Where its lines that matter start, in order: a file's header where what it asks is about the file whole, then the first row of each thing a line triggered. */
    stops: number[];
}

/** A line of the operator's words shown above an agent's that answer them, with the part it's of and where it starts in that part's text: where a passage its citations cite is marked. */
export interface SaidLine extends Span {
    part: PartId;
    own: number;
}

/** One item, where it's shown: its body, its kind's view of it; what its header names it by, `@51 question`; with the lines of the operator's words it answers, shown above it, and where each line of its own an edit changed starts. */
export interface Region extends Scope {
    item: Item;
    body: Mounted;
    named: string;
    said: SaidLine[];
    changed: number[];
}

/** One of an agent's drawers, where it's shown: which, whose, the view it shows, and what of it is laid out where. */
export interface Drawer extends Scope {
    kind: DrawerKind;
    conversation: Conversation;
    /** The view it shows, of its agent. */
    view: Mounted;
    /** Each file it shows, by its path, as its view shows it. */
    diffs: ReadonlyMap<string, Filed>;
    /** Each of its folds read from another view as it opens, by the fold's name, and that view. */
    loads: ReadonlyMap<string, Instance>;
    /** Each span of a view its module answers, in the tone it names: what's drawn in its look. */
    toned: (Span & { tone: string })[];
    /** Each Markdown block it shows, from its first line to its last, the remarks under its lines among them: what's highlighted as Markdown. */
    texts: Span[];
    /** What each fold its view says is set off under its summary line holds (`Fold.barred`), with the fold's kind: drawn set in, a bar in the kind's colour beside it. */
    bars: Bar[];
    /** What its "since you approved" shows, each file with its place and the block it's in, where it's that drawer. */
    files: PlacedFile[];
    /** Where its "since you approved" says each file standing as the operator last saw it, in a line of its own: one with flagged writes still waiting or held at landing in its place, the rest under `settled`. */
    reviewed: ReviewedLine[];
    /** The line at the end of its "since you approved" that the files settled fold under, reviewed or as the operator saw them in an item with nothing waiting (`5 reviewed`); none where there's none. */
    settled: Span | null;
    /** Whether it holds what waits on the operator: files to review, flagged writes or files held at landing, in "since you approved". */
    waiting: boolean;
}

/** What a fold set off by a bar holds, from the line after its summary to its last, and the fold's kind, whose colour the bar is drawn in. */
export interface Bar extends Span {
    kind: string;
}

/** A file standing as the operator last saw it, where its line is in "since you approved". */
export interface ReviewedLine extends Span {
    file: PlacedFile;
}

/**
 * One part of the review where it's laid out, by an id it keeps across layouts: a group, its banner, an item, its
 * header, what the core lays out around its body, a view mounted in either, one of the view's blocks, and what the
 * operator wrote; from its first line to its last, its first line its header, the parts within it in order.
 */
export interface Placed extends Span {
    id: string;
    kind: "section" | "group" | "banner" | "item" | "header" | "frame" | "view" | "block" | "written";
    header: Span;
    children: Placed[];
    view?: Mounted;
    block?: ViewBlock;
}

/** Where a comment is laid out on the block it's on (`anchors.ts`), and whether the lines under it aren't those it quotes. */
export interface Seated extends Placement {
    outdated: boolean;
}

/**
 * The review's text, where each group, each item and each drawer is in it, and its tree, each part where it's laid
 * out; whose each of its lines is, by the id of the innermost part laid out on it, what the editor keeps each part by
 * as the review is laid out anew (`reconcile.ts`); where each comment is on its block, each block's lines a comment may
 * be on, by the block's id, as they're laid out; and what's written, where some of it was drafted before it was
 * anchored to a block or had an id and is so now, which the draft takes in once.
 */
export interface Laid {
    text: string;
    groups: Group[];
    regions: Region[];
    drawers: Drawer[];
    nodes: Placed[];
    owners: string[];
    /** The runs of its lines of one part's each, in order, as the editor keeps them (`reconcile.ts`). */
    runs: Run[];
    seated: ReadonlyMap<string, Seated>;
    lines: ReadonlyMap<string, Lines>;
    /** What's written as it's laid out, each with its id, what was anchored or kept on what it's on whole as it was laid out among it. */
    written: Written[];
    converted: Written[] | null;
    /** Each span drawn beside the text rather than written in it, where it goes (`isDrawn`). */
    drawn: Drawn[];
    /** Each section, grouped by thread; none grouped by agent. */
    sections: Section[];
    /** The folds of no scope: each section's whole, and what of a thread came before where the operator read it. */
    outer: Fold[];
    /** The lines of a thread that are no item's nor drawer's: the operator's words moved in or on what isn't laid out, a check, what's to try. */
    asides: Aside[];
    /** Each check laid out, in the text's order. */
    checks: CheckLine[];
    /** Each fold read from the host as it opens. */
    loading: Loading[];
}

export const EMPTY: Draft = { comments: [], letters: [], remarks: [], done: [], declined: [], parked: [], marks: [] };

/** Return what names an item among the folds' owners: its number; a drawer: its kind and whose it is. */
export function ownerOf(owner: { item: Item } | { drawer: DrawerKind; conversation: Conversation }): string {
    return "item" in owner ? `${owner.item.number}` : `${owner.drawer} ${whose(owner.conversation)}`;
}

/** Return what the operator wrote in a draft as the editor holds it, in one list: the comments, the messages, then the remarks. */
export function written(draft: Draft): Written[] {
    return [...(draft.comments ?? []), ...(draft.letters ?? []), ...(draft.remarks ?? [])];
}

/** Return `draft` with `list`, as the editor holds what's written, for its comments, its messages and its remarks. */
export function withWritten(draft: Draft, list: Written[]): Draft {
    return { ...draft, comments: list.filter(isComment), letters: list.filter(isLetter), remarks: list.filter(isRemark) };
}

/** Return whether what's written is a message, to an agent or on a thread, rather than a comment on an item or a remark in a drawer. */
export function isLetter(each: Written): each is Letter {
    return !("item" in each) && !("quote" in each);
}

/** Return whether what's written is a remark in one of an agent's drawers. */
export function isRemark(each: Written): each is Remark {
    return !("item" in each) && "quote" in each;
}

function isComment(each: Written): each is Comment {
    return "item" in each;
}

/** One line under an item that isn't its own text, and what it shows. */
export interface Said {
    kind: Kind;
    text: string;
}

/** What shows under an item's files: its context, its summary line with the lines that fold under it; or, where the host refused it, a line saying why. */
interface Under {
    summary: Said;
    lines: Said[];
}

/** Return an item's context as the lines it's shown in: each thing said after who said it, its own lines kept; each run of calls in one line; and the call that made the item, marked. */
export function steps(context: Context): Said[] {
    const shown: Said[] = [];
    let run: string[] = [];
    const ran = () => {
        if (run.length > 0) {
            shown.push({ kind: "calls", text: calls(run) });
            run = [];
        }
    };
    context.entries.forEach((entry, at) => {
        if (entry.kind === "called" && at !== context.anchor) {
            run.push(entry.tool);
            return;
        }
        ran();
        if (entry.kind === "called") {
            shown.push({ kind: "anchor", text: `→ called ${entry.tool} · this item` });
            return;
        }
        const who: Kind = entry.by === "operator" ? "you" : "agent";
        shown.push(...spoken(who === "you" ? who : null, entry.text, false).map((row) => ({ kind: who, text: row.text })));
    });
    ran();
    return shown;
}

/** Say what an item's context holds: how many steps, and from whose words and how long before the item. */
function told(item: Item, context: Context): string {
    const count = `context · ${context.entries.length} ${context.entries.length === 1 ? "step" : "steps"}`;
    const first = context.entries[0];
    const yours = first?.kind === "said" && first.by === "operator";
    const before = first?.at == null ? "" : ` ${since(new Date(first.at), new Date(item.made))} before this item`;
    if (!yours && before === "") {
        return count;
    }
    return `${count}, from${yours ? " your words" : ""}${before}`;
}

/** Return the item's context as it shows under the item, of what the host has answered; none before it has. */
function beneath(item: Item, around: Around): Under | null {
    const context = around.contexts.get(item.number);
    if (context === undefined) {
        return null;
    }
    return {
        summary:
            "shown" in context
                ? { kind: "summary", text: told(item, context.shown) }
                : { kind: "refused", text: `no context: ${context.refused}` },
        lines: "shown" in context ? steps(context.shown) : [],
    };
}

/**
 * One line of a changed file that comments may be on: its header, or one of its rows, the run of unchanged rows it
 * opens, if any, before it, and whether it ends one; what it triggered, where it's a line that matters, and whether
 * it's a stop, the first line of what triggered; the bodies it declares and those it ends; and, for a file with rows,
 * the fold its header opens, folded where the file folds whole, and its last row ends.
 */
interface FileLine {
    file: Filed;
    row: Row | null;
    text: string;
    opens: { summary: string; name: string } | null;
    closes: boolean;
    matter: Matter | null;
    stop: boolean;
    declares: Body[];
    finishes: Body[];
    folds: { closed: boolean } | null;
    ends: boolean;
    /** Whether the bodies it declares fold until opened: a file's that shows its design, but one holding a line that matters. */
    designed: boolean;
}

/** Whether an item keeps the files it changes beside it, for the review to show under it: an approval, a held change, or a flagged write. */
export function changing(item: Item): boolean {
    const reason = item.reason.reason;
    return reason === "approval" || reason === "held" || reason === "flagged";
}

/** Each file's lines as laid out, once: the review is laid out again at each key typed in a comment, and a file's lines don't change (`shownOnce`). */
const filedOut = new WeakMap<Filed, FileLine[]>();

/** Return the lines of `file` as a view gives it, laid out once and kept: its header, then its rows, each with the run it opens, the bodies it declares and those it ends, found by row; its bodies folding where it shows its design, but those holding a line that matters. */
function filedOnce(file: Filed): FileLine[] {
    const found = filedOut.get(file);
    if (found !== undefined) {
        return found;
    }
    const laidOut = shownOnce(file);
    const designed = file.design ?? false;
    const header: FileLine = {
        file,
        row: null,
        text: laidOut.header,
        opens: null,
        closes: false,
        matter: null,
        stop: laidOut.whole,
        declares: [],
        finishes: [],
        folds: laidOut.rows.length > 0 ? { closed: !laidOut.open } : null,
        ends: false,
        designed: false,
    };
    const matters = new Map(laidOut.matters.map((each) => [each.row, each]));
    const opens = new Map(laidOut.runs.map((each) => [each.from, each]));
    const closes = new Set(laidOut.runs.map((each) => each.to));
    const byRow = (at: (body: Body) => number) => {
        const rows = new Map<number, Body[]>();
        for (const body of laidOut.bodies) {
            rows.set(at(body), [...(rows.get(at(body)) ?? []), body]);
        }
        return rows;
    };
    const declares = byRow((body) => body.from);
    const finishes = byRow((body) => body.to);
    // A body holding a line that matters stays open in a design.
    const mattering = (body: Body) => laidOut.matters.some((each) => each.row > body.from && each.row <= body.to);
    const rows = laidOut.rows.map((row, at): FileLine => {
        const run = opens.get(at);
        const matter = matters.get(at) ?? null;
        const declared = declares.get(at) ?? [];
        return {
            file,
            row,
            text: row.text,
            opens: run === undefined ? null : { summary: run.summary, name: run.name },
            closes: closes.has(at + 1),
            matter,
            stop: (matter?.notes.length ?? 0) > 0,
            declares: declared,
            finishes: finishes.get(at) ?? [],
            folds: null,
            ends: at === laidOut.rows.length - 1,
            designed: designed && !declared.some(mattering),
        };
    });
    const made = [header, ...rows];
    filedOut.set(file, made);
    return made;
}

/** A scope's own lines, by the block each is of: each block's run of them, in order, so a line's block is found among a few. */
class OfBlocks {
    private runs: { block: string; first: number; count: number }[] = [];
    length = 0;

    /** Add `count` lines of `block`'s after the others. */
    add(block: string, count: number): void {
        this.runs.push({ block, first: this.length, count });
        this.length += count;
    }

    /** Return the block line `at` of the scope's own is of, and its line there; none past the last. */
    at(at: number): { block: string; line: number } | undefined {
        const run = this.runs.find((each) => at >= each.first && at < each.first + each.count);
        return run === undefined ? undefined : { block: run.block, line: at - run.first };
    }
}

/** Each file's lines as a comment counts them, and their version, once: laid out again at each key typed in a comment, a file's lines don't change. */
const fileLinesKept = new WeakMap<FileLine[], Map<string | null, Lines>>();

/** Return the lines of a file laid out as `lines`, and their version, the file's own `given` (`linesOf`), made once. */
function fileLines(lines: FileLine[], given: string | null): Lines {
    const kept = fileLinesKept.get(lines) ?? new Map<string | null, Lines>();
    const found = kept.get(given);
    if (found !== undefined) {
        return found;
    }
    const made = linesOf(lines.map((each) => each.text), given);
    fileLinesKept.set(lines, kept.set(given, made));
    return made;
}

/** Return whether a view's block is a file, a change's or one as it stands. */
function isFiled(block: ViewBlock): block is Filed {
    return block.block === "diff" || block.block === "code";
}

/** Return each file `blocks` show whole, those in their folds given whole among them, in the order they're laid out. */
function filedIn(blocks: readonly ViewBlock[]): Filed[] {
    return blocks.flatMap((block) => (isFiled(block) ? [block] : block.block === "fold" && Array.isArray(block.content) ? filedIn(block.content) : []));
}

/** A group as it's laid out: what names it among the others, the agent it's of, what its banner names it by, and its items. */
export interface Grouping {
    key: string;
    conversation: Conversation | null;
    head: Head;
    items: Item[];
}

/**
 * Whether an item is news, to read and mark read rather than answer, as its kind's rank says (`Item.rank`, which the
 * host gives each item): a note, a turn's last words among them, a friction, how it felt, or a stop by choice.
 */
export function news(item: Item): boolean {
    return item.rank.name === "news";
}

/** Whether an item is a write that landed flagged, which the review shows in its agent's "since you approved" drawer rather than as an item (`docs/dashboard.md`, *The review*). */
export function flag(item: Item): boolean {
    return item.rank.name === "flag";
}

/**
 * Return `items` in groups, one per agent, and one per banner of lup's approvals, in the order they arrived: each
 * group where its first item came, by that item's number, and its items by theirs. A later item comes after every
 * earlier one, at the end of its group or in a group of its own after the others, and a change of an item's rank or
 * state moves nothing: `Item.rank` orders nothing here, saying only which items `]a` and `[a` stop at (`toAnswer`).
 */
function grouped(items: Item[], banner: (item: Item) => string): Grouping[] {
    const groups = new Map<string, Grouping>();
    for (const item of items.toSorted((a, b) => a.number - b.number)) {
        const sender = item.sender;
        const conversation = sender.party === "conversation" ? sender : null;
        const key = conversation === null ? `lup ${banner(item)}` : whose(conversation);
        const group = groups.get(key) ?? { key, conversation, head: { item }, items: [] };
        groups.set(key, { ...group, items: [...group.items, item] });
    }
    return [...groups.values()];
}

/** Return what names a group's place across layouts: `key`, whose it is, and whether it's of what's left for later. */
function placeOf(key: string, later: boolean): string {
    return `${later ? "later" : "now"} ${key}`;
}

/** Return what names thread `number`'s group's place across layouts, as the host keeps the order (`placeOf`). */
export function threadPlace(number: number): string {
    return placeOf(`thread:${number}`, false);
}

/**
 * Return a thread's conversation as the host answered it, `shown`, as it's laid out: `before`, what folds with what came
 * before where the operator last read it; and `after`, what's shown. A thread they never read, as a past session's
 * whole history lup put in its root, shows only what calls for them, what's new to them, what asks them, a part of their
 * words still open (`ThreadRead`), with what each is under; the rest folds, all of it where nothing calls for them, so
 * what they've answered never comes back once nothing's left. One they read shows whatever came since.
 */
export function untilCalled(shown: ThreadShown, read: ThreadRead): { before: ThreadEntry[]; after: ThreadEntry[] } {
    const entries = shown.entries;
    if (read.mark != null) {
        return { before: [], after: [...entries] };
    }
    const calls = new Set([...(read.new ?? []), ...(read.asks ?? []).map((each) => each.node)]);
    const called = (entry: ThreadEntry) => (entry.member && entry.spot.part == null && calls.has(entry.spot.node)) || entry.unanswered === true;
    const byKey = new Map(entries.map((each) => [spotKey(each.spot), each]));
    const kept = new Set<string>();
    for (const entry of entries.filter(called)) {
        let at: ThreadEntry | undefined = entry;
        for (let depth = 0; at !== undefined && depth <= entries.length; depth += 1) {
            kept.add(spotKey(at.spot));
            at = at.under == null ? undefined : byKey.get(spotKey(at.under));
        }
    }
    return {
        before: entries.filter((each) => !kept.has(spotKey(each.spot))),
        after: entries.filter((each) => kept.has(spotKey(each.spot))),
    };
}

/** Return what names an entry of a thread's conversation among the others: its node, and its part where it's one. */
function spotKey(spot: { node: number; part?: number | null }): string {
    return `${spot.node}.${spot.part ?? ""}`;
}

/**
 * How an item is laid out in its thread's conversation: whether it answers what's above it there, whose words then
 * aren't shown above its own again; the operator's words on it, each part laid out after its own; and whether it folds to
 * its header, as a message between agents does.
 */
interface Threaded {
    under?: boolean;
    words?: readonly ThreadEntry[];
    folded?: boolean;
}

/**
 * Return where the groups go, as `laid` takes them: `own`, this page's order, the groups it laid out last, as it laid
 * them; then each place of `kept`, the order the host keeps for every page, it doesn't hold, in the host's order, as
 * one another page laid out, or every one as the page first lays the review out, after a reload among others. So what
 * this page shows never moves for what another did (`docs/dashboard.md`, *The review*).
 */
export function ordered(own: readonly string[], kept: readonly string[]): string[] {
    const held = new Set(own);
    return [...own, ...kept.filter((each) => !held.has(each))];
}

/** What the host is told of the order once the page laid the review out: the places laid out, in order, and those it no longer lays out. */
export interface Keeping {
    places: string[];
    gone: string[];
}

/**
 * Return what to tell the host of the order, `kept` as it keeps it, once the page laid out the groups at `shown`, in
 * order, having laid out those at `before` (as it first lays the review out from the host's order, that order): what
 * it lays out, and each kept it laid out before and no longer does, gone; nothing where the host keeps it so already,
 * as it does a place another page laid out and this one doesn't, which this one leaves it to.
 */
export function toKeep(shown: readonly string[], before: readonly string[], kept: readonly string[]): Keeping | null {
    const laidNow = new Set(shown);
    const held = new Set(kept);
    const gone = before.filter((each) => !laidNow.has(each) && held.has(each));
    return gone.length === 0 && shown.every((each) => held.has(each)) ? null : { places: [...shown], gone };
}

/** Return a group for each of `conversations` with none among `groups`, in their order, once each. */
function emptyGroups(conversations: Conversation[], groups: Grouping[]): Grouping[] {
    const keys = new Set(groups.map((each) => each.key));
    return conversations.flatMap((conversation) => {
        const key = whose(conversation);
        if (keys.has(key)) {
            return [];
        }
        keys.add(key);
        return [{ key, conversation, head: { conversation }, items: [] }];
    });
}

/** Say how long an item has waited, to the minute: what came in under a minute ago is just in. */
export function waited(made: string, now: Date): string {
    const at = new Date(made);
    return now.getTime() - at.getTime() < 60_000 ? "just in" : `waiting ${since(at, now)}`;
}

/**
 * How far the operator has seen what waits on them (`docs/dashboard.md`, *Review marks*): each agent's group up to the
 * last of its items they'd seen as they marked it, Space d on its banner, by `whose` its conversation is (`Items.seen`);
 * and the items they commented on in a reply already sent, a comment counting as a review.
 */
export interface Seeing {
    groups: ReadonlyMap<string, number>;
    commented: ReadonlySet<number>;
    /** Grouped by thread, the items new to the operator: each that came after where they last read its thread. */
    threaded?: ReadonlySet<number>;
}

/** Nothing seen: every item new. */
export const UNSEEN: Seeing = { groups: new Map(), commented: new Set() };

/** Return how far the operator has seen what the inbox's listing `items` holds: each group's mark, and the items their replies sent commented on (`Items.answers`). */
export function seeingOf(items: components["schemas"]["Items"] | null): Seeing {
    if (items === null) {
        return UNSEEN;
    }
    const groups = new Map((items.seen ?? []).map((each) => [whose(each.conversation), each.item]));
    const commented = new Set(
        (items.answers ?? []).flatMap((each) => (each.reason.reason === "review" ? (each.reason.comments ?? []).map((comment) => comment.item) : [])),
    );
    return { groups, commented };
}

/** Say whether an item is new to the operator: they haven't seen its group since it came, nor commented on it in a reply they sent; grouped by thread, it came after where they last read its thread. */
export function fresh(item: Item, seeing: Seeing): boolean {
    if (seeing.commented.has(item.number)) {
        return false;
    }
    if (seeing.threaded !== undefined) {
        return seeing.threaded.has(item.number);
    }
    const seen = item.sender.party === "conversation" ? seeing.groups.get(whose(item.sender)) : undefined;
    return seen === undefined || item.number > seen;
}

/** Say how many of a thing there are: `1 step`, `5 steps`. */
function counted(count: number, one: string): string {
    return `${count} ${one}${count === 1 ? "" : "s"}`;
}

/**
 * The text being laid out, line by line: kept as its lines, joined once it's whole (`text`), since a string built by
 * adding to it is copied whole each time it's read; and each line's text and end by where it starts, which is what's
 * read of it as it's laid out.
 */
class Writer {
    private chunks: string[] = [];
    private starts: number[] = [];
    // Each line written, in order: where it starts, and its text.
    private lineStarts: number[] = [];
    private lineTexts: string[] = [];
    private length = 0;
    /** Whose each line written is: the id of the innermost part laid out on it. */
    owners: string[] = [];
    /** The runs of lines of one part's each, in order (`reconcile.ts`). */
    runs: Run[] = [];
    /** Whose the next line is. */
    owner = "";

    /** Write `line` on a line of its own, `owner`'s or the writer's own, and return where it is. */
    line(line: string, owner: string = this.owner): Span {
        const from = this.length;
        this.add(`${line}\n`);
        this.own(from, line, owner);
        return { from, to: from + line.length };
    }

    /** Write `text`, lines laid out elsewhere, each `owned` as it says by its place among them, and a line break after it. */
    lines(text: string, owned: (line: number) => string): void {
        let at = this.length;
        this.add(`${text}\n`);
        text.split("\n").forEach((each, index) => {
            this.own(at, each, owned(index));
            at += each.length + 1;
        });
    }

    private add(chunk: string): void {
        this.chunks.push(chunk);
        this.starts.push(this.length);
        this.length += chunk.length;
    }

    /** Keep a line written at `from`, its text and whose it is, its run going on where it's the last's part's. */
    private own(from: number, text: string, owner: string): void {
        this.lineStarts.push(from);
        this.lineTexts.push(text);
        this.owners.push(owner);
        const last = this.runs.at(-1);
        if (last !== undefined && last.owner === owner && last.to === from - 1) {
            last.to = from + text.length;
        } else {
            this.runs.push({ owner, from, to: from + text.length });
        }
    }

    /** Lay out what `lay` writes as `owner`'s, then go on as before. */
    as<T>(owner: string, lay: () => T): T {
        const was = this.owner;
        this.owner = owner;
        try {
            return lay();
        } finally {
            this.owner = was;
        }
    }

    /** Take back everything written from `at`, the start of a line written. */
    cut(at: number): void {
        while ((this.starts.at(-1) ?? -1) >= at) {
            const chunk = this.chunks.pop() ?? "";
            this.starts.pop();
            this.length -= chunk.length;
        }
        while ((this.lineStarts.at(-1) ?? -1) >= at) {
            this.lineStarts.pop();
            this.lineTexts.pop();
            this.owners.pop();
        }
        while ((this.runs.at(-1)?.from ?? -1) >= at) {
            this.runs.pop();
        }
        const last = this.runs.at(-1);
        if (last !== undefined && last.to >= at) {
            last.to = at - 1;
        }
    }

    /** Return which line written starts at `from`, found by halving; none where none does. */
    private lineAt(from: number): number | undefined {
        let low = 0;
        let high = this.lineStarts.length;
        while (low < high) {
            const middle = (low + high) >> 1;
            if ((this.lineStarts[middle] ?? 0) < from) {
                low = middle + 1;
            } else {
                high = middle;
            }
        }
        return this.lineStarts[low] === from ? low : undefined;
    }

    /** Return the end of the line written starting at `from`; the text's end where none does. */
    endOf(from: number): number {
        const at = this.lineAt(from);
        return at === undefined ? this.length : from + (this.lineTexts[at] ?? "").length;
    }

    /** Return the line written starting at `from`, as it was written; none where none starts there. */
    lineFrom(from: number): string {
        const at = this.lineAt(from);
        return at === undefined ? "" : (this.lineTexts[at] ?? "");
    }

    /** The text written, whole. */
    get text(): string {
        const whole = this.chunks.join("");
        this.chunks = [whole];
        this.starts = [0];
        return whole;
    }

    /** Where the next line starts. */
    get at(): number {
        return this.length;
    }
}

/** What's gathered of a scope as it's laid out. */
interface Gathering {
    lines: OwnLine[];
    blocks: Block[];
    code: Coded[];
    filed: FileSpan[];
    asides: Aside[];
    folds: Fold[];
    stops: number[];
}

function gathering(): Gathering {
    return { lines: [], blocks: [], code: [], filed: [], asides: [], folds: [], stops: [] };
}

/**
 * Lay `files` into `w` as part of the scope `of`, gathered in `into`: each line written with its comments under it
 * (`writeBlocks`, by the line's place among the scope's own lines from `first`), its runs, bodies and files folding;
 * each file's lines, the summaries of its runs among them, its block's (`owner`).
 */
function layCode(w: Writer, into: Gathering, of: string, files: FileLine[], first: number, starts: number[], writeBlocks: (line: number) => void, owner: (file: Filed) => string): void {
    // What each fold opened is, until the line ending it: the run, with its summary line's words, the file, each body by its name.
    let run: { summary: Aside; name: string; said: string } | null = null;
    let whole: { summary: Span; from: number; closed: boolean } | null = null;
    const bodies = new Map<string, { summary: Span; from: number; closed: boolean }>();
    // A fold under a file's lines, named by the file's path and what it hides within it, hiding up to `to`.
    const fold = (kind: FoldKind, path: string, name: string, label: string, closed: boolean, summary: Span, from: number, to: number) =>
        into.folds.push({ of, kind, name: name === "" ? path : `${path} ${name}`, label, closed, summary, from, to, ...(kind === "file" ? { scope: true } : {}) });
    let inFile = 0;
    // Whose a file's lines are, said once for each file.
    let ownerOf: { file: Filed | null; whose: string } = { file: null, whose: "" };
    files.forEach((each, index) => {
        const path = each.file.path;
        if (ownerOf.file !== each.file) {
            ownerOf = { file: each.file, whose: owner(each.file) };
        }
        const whose = ownerOf.whose;
        inFile = each.row === null ? 0 : inFile + 1;
        if (each.opens !== null) {
            const aside = { kind: "summary" as const, ...w.line(each.opens.summary, whose) };
            into.asides.push(aside);
            run = { summary: aside, name: each.opens.name, said: each.opens.summary };
        }
        const at = first + index;
        const span = w.line(each.text, whose);
        into.lines.push({ ...span, own: starts[at] ?? 0, block: whose, line: inFile });
        into.code.push({ from: span.from, to: span.to, file: each.file, row: each.row, matter: each.matter });
        if (each.stop) {
            into.stops.push(span.from);
        }
        const ran: { summary: Aside; name: string; said: string } | null = run;
        if (each.closes && ran !== null) {
            const summary = { from: ran.summary.from, to: ran.summary.to };
            // Labelled by the words written, not sliced from the text being built, which copies it whole each time.
            fold("lines", path, ran.name, ran.said, true, summary, summary.to, span.to);
            run = null;
        }
        for (const body of each.finishes) {
            const declared = bodies.get(body.name);
            if (declared !== undefined) {
                fold("body", path, body.name, body.names.at(-1) ?? "", declared.closed, declared.summary, declared.from, span.to);
                bodies.delete(body.name);
            }
        }
        const opening: { summary: Span; from: number; closed: boolean } | null = whole;
        if (each.ends && opening !== null) {
            fold("file", path, "", path, opening.closed, opening.summary, opening.from, span.to);
            whole = null;
        }
        writeBlocks(at);
        // A file and a body fold under their first line and the comments on it, which stay in view.
        if (each.folds !== null) {
            whole = { summary: span, from: w.at - 1, closed: each.folds.closed };
        }
        for (const body of each.declares) {
            bodies.set(body.name, { summary: span, from: w.at - 1, closed: each.designed });
        }
        if (each.row === null) {
            into.filed.push({ file: each.file, from: span.from, to: w.at - 1 });
        } else {
            const last = into.filed.at(-1);
            if (last !== undefined) {
                last.to = w.at - 1;
            }
        }
    });
}

/** Return the id of what's written, which the editor keeps it by. */
export function writtenId(each: Written): string {
    return each.id ?? "";
}

/** Return the id of the part of the review what's written with `id` is laid out as, and whose its lines are. */
export function writtenOwner(id: string): string {
    return `written ${id}`;
}

/** Return `draft` with an id for each of what's written that has none, kept from before what's written had ids (`keptId`), and whether any had none. */
function identified(draft: Draft): { draft: Draft; changed: boolean } {
    let changed = false;
    const named = <W extends Written>(list: W[] | undefined, kind: "comment" | "letter" | "remark"): W[] =>
        (list ?? []).map((each, at) => {
            if ((each.id ?? "") !== "") {
                return each;
            }
            changed = true;
            return { ...each, id: keptId(kind, at) };
        });
    return { draft: { ...draft, comments: named(draft.comments, "comment"), letters: named(draft.letters, "letter"), remarks: named(draft.remarks, "remark") }, changed };
}

/** Return the operator's words `text` after the passage `quote` they were on, set off as a mail quotes, where it's no longer laid out: so what it was on goes with them, kept on what it's on whole. */
function unplaced(quote: string, text: string): string {
    return `${quote.split("\n").map((line) => (line === "" ? ">" : `> ${line}`)).join("\n")}\n${text}`;
}

/**
 * Return `groups` with each subagent's under their parent's, after it and the subagents laid under it before, each with
 * how deep it's set in: under its nearest forebear with a group among them, by `parents`, each conversation's parent by
 * `whose` each is; those with none where they were. As they are, none set in, where `parents` is none.
 */
export function nested(groups: Grouping[], parents: ReadonlyMap<string, string> | null): { group: Grouping; depth: number }[] {
    if (parents === null) {
        return groups.map((group) => ({ group, depth: 0 }));
    }
    const keys = new Set(groups.map((each) => each.key));
    const forebear = (key: string): string | undefined => {
        let at = parents.get(key);
        while (at !== undefined && !keys.has(at)) {
            at = parents.get(at);
        }
        return at;
    };
    const under = new Map<string, Grouping[]>();
    const roots: Grouping[] = [];
    for (const group of groups) {
        const parent = group.conversation === null ? undefined : forebear(group.key);
        if (parent === undefined) {
            roots.push(group);
        } else {
            under.set(parent, [...(under.get(parent) ?? []), group]);
        }
    }
    const out: { group: Grouping; depth: number }[] = [];
    const walk = (group: Grouping, depth: number) => {
        out.push({ group, depth });
        for (const child of under.get(group.key) ?? []) {
            walk(child, depth + 1);
        }
    };
    roots.forEach((each) => walk(each, 0));
    return out;
}

/** Say a line of spans as text. */
function worded(spans: readonly { text: string }[]): string {
    return spans.map((each) => each.text).join("");
}

/** A span of a view's that ticks or measures (`Ticking`, `Gauge`), where it's drawn beside the text, never written in it (`ticking.ts`). */
export interface Drawn {
    at: number;
    span: ViewSpan;
}

/** Return whether a span is drawn rather than written: one that ticks, saying the time since a moment, or measures. */
export function isDrawn(span: ViewSpan): boolean {
    return span.ticking != null || span.gauge != null;
}

/** Say a line of spans as text, those drawn left out (`isDrawn`), and where in it each of those goes. */
function wording(spans: readonly ViewSpan[]): { text: string; drawn: { offset: number; span: ViewSpan }[] } {
    let text = "";
    const drawn: { offset: number; span: ViewSpan }[] = [];
    for (const span of spans) {
        if (isDrawn(span)) {
            drawn.push({ offset: text.length, span });
        } else {
            text += span.text;
        }
    }
    return { text, drawn };
}

/** What a producer reads where there's nothing read: no item, nothing beyond any, no agent's data, no one running. */
const NOTHING_SHOWN: Shown = {
    items: new Map(),
    beyond: { contexts: new Map(), files: new Map() },
    drawers: new Map(),
    running: new Map(),
    landings: [],
    called: (party) => party.agent ?? party.session,
};

/**
 * Return a drawer's label under its banner, the drawer of `kind` as the looks declare it, from what the host answered
 * of its agent, `data`, as its view says it (`views.ts`), and whether it holds what waits on the operator; none where
 * it has nothing in it, or where the page doesn't lay its view out itself.
 */
export function rowLabel(kind: DrawerKind, data: AgentDrawers): { text: string; waiting: boolean } | null {
    const drawn = adopted().drawers("").find((each) => each.view === kind);
    const producer = drawn === undefined ? undefined : producerOf(drawn.module, drawn.view);
    if (producer === undefined) {
        return null;
    }
    const of = { runtime: "claude", session: "s", agent: null };
    const shown = { ...NOTHING_SHOWN, drawers: new Map([[whose(conversationOf("", of)), data]]) };
    const answer = producer.answer(of, shown, "");
    return answer === null ? null : { text: worded(answer.blocks.summary ?? []), waiting: answer.blocks.waiting ?? false };
}

/** Return the text of a line of a view's, its spans drawn left out, where each of those goes, and the kind of line it's drawn as: its first span's tone. */
function lineOfView(line: { spans?: ViewSpan[] }): { kind: Kind; text: string; drawn: { offset: number; span: ViewSpan }[] } {
    const spans = line.spans ?? [];
    return { kind: spans[0]?.tone ?? "plain", ...wording(spans) };
}

/** Return what of an item's kind's summary names it in the header over the review, after its number: its words up to the first ` · `, `question`, `message to explore-auth`. */
function namedBy(summary: readonly { text: string }[]): string {
    const first = summary.findIndex((each) => each.text.startsWith(" · "));
    return worded(first < 0 ? summary : summary.slice(0, first));
}

/**
 * Lay `items` out as one text, in groups, one per agent, each under its banner, in the order they arrived: those with
 * items now first, each where its first item came (`grouped`); then a group for each agent of `agents` (those running,
 * in the tree's order) with none, and for each the draft writes to with none; then the parked items' groups, each
 * where its first item came. Each banner says `banner`'s words of its agent, with the parts of it its banner views
 * say, for an agent running (`parts`). Under each banner but the parked ones', the draft's messages to its agent; then
 * each item, in the order they came, under a header naming it, `header`'s words around what its kind's view says of
 * it, each comment of the draft on it under the line it's on: a comment on a passage under the passage's last line,
 * one on the item whole under its header. Under its header, its body, its kind's view of it (`kindView`, `views/`): its
 * text, then each file it changes, its header then its lines, each run of unchanged ones folding under a summary line,
 * or a line saying why the host showed none; then the item's context, a summary line with the lines that fold under
 * it. Then, at the end of each agent's group but the parked ones, their drawers, each a view of the agent's in the
 * order their repository's looks list them (`layDrawer`), the draft's remarks in them each under its line, a
 * conversation among the items they exchanged called by `name`.
 *
 * An agent's item that answers the operator's (`Message.answers`) is laid out as the exchange it is: under its header,
 * their words it answers, after `you` and what each item of theirs is, folding under that line, open (`above`), then
 * the agent's name and its own words, each line followed by the comments on it, then the passages its citations on
 * that line cite, folded under it (`citedOn`); what its edits changed folds under a summary line before its words
 * (`editedOf`). An item kept with replies from before shows, after its own words, each of the operator's comments on
 * it after `you`, and the agent's replies after their name (`threadsOf`).
 *
 * `places` are where the groups go (`Group.place`, in order), as this page laid them out and the host keeps them for
 * every page and across reloads (`ordered`): each among them keeps its place, items coming and going, and any other
 * comes after them, in the order above. So a group appears where its first item puts it, or after every group with
 * items as its conversation is first seen, and stays there for as long as it's laid out.
 *
 * Each part laid out is kept in the tree it returns (`Laid.nodes`), by an id it keeps across layouts: a group by whose
 * it is (`group <place>`), an item by its number (`item <number>`), a view mounted by its instance (`views.ts`), each of
 * its blocks by the instance and its own id, what the operator wrote by its own id; and each line of the text is the
 * innermost part's laid out on it (`Laid.owners`). A comment or a remark goes under the last line it quotes of the
 * block it's on, followed from where it was laid out last through the block's change (`arranging.previous`,
 * `anchors.ts`); one drafted before it was anchored so is anchored as it's laid out (`Laid.converted`).
 */
export function laid(
    items: Item[],
    agents: Conversation[],
    banner: (head: Head, parked: boolean, parts: string) => string,
    header: (item: Item, parked: boolean, said: string) => string,
    draft: Draft,
    around: Around,
    places: readonly string[] = [],
    drawers: Drawers = new Map(),
    name: (party: Conversation) => string = (party) => party.agent ?? party.session,
    arranging: Arranging = {},
): Laid {
    const parked = draft.parked ?? [];
    // Marked done or declined, an item folds; and a block marked done, as a file marked reviewed (`grammar.ts`).
    const settling = [...(draft.done ?? []), ...(draft.declined ?? [])];
    const markedDone = new Set((draft.marks ?? []).filter((each) => each.verb === "done").map((each) => each.block));
    // The folds a mark or what's left for later folds, which start so whatever their kind says.
    const byMarks = new Set<Fold>();
    // What's written, each with its id; and, by its id, what of it is anchored to its block, or kept on what it's on
    // whole, as it's laid out, having been drafted before it was.
    const named = identified(draft);
    const letters = named.draft.letters ?? [];
    const remarks = named.draft.remarks ?? [];
    const wrote = written(named.draft);
    const converting = new Map<string, Written>();
    const previous = arranging.previous ?? null;
    const seated = new Map<string, Seated>();
    const blockLines = new Map<string, Lines>();
    // Each file a view shows, by its block's id.
    const filedBy = new Map<string, Filed>();
    // Each span drawn beside the text, where it goes; and `drawnIn` puts those of a line where its text is.
    const drawnAt: Drawn[] = [];
    const drawnIn = (from: number, drawn: readonly { offset: number; span: ViewSpan }[]) => {
        for (const each of drawn) {
            drawnAt.push({ at: from + each.offset, span: each.span });
        }
    };
    // Where words written into a line by a callback are in it, which it writes as given: its first place or its last,
    // as the callback puts them first or last, else the line's end.
    const placedIn = (line: Span, words: string, last: boolean) => {
        const shown = w.lineFrom(line.from);
        const at = words === "" ? -1 : last ? shown.lastIndexOf(words) : shown.indexOf(words);
        return at < 0 ? line.to : line.from + at;
    };
    const looks = arranging.looks ?? adopted();
    const remote = arranging.remote ?? new Map();
    // Each item the views read by its number: those waiting, and those in each thread's conversation read, as they stand.
    const threadItems = [...(arranging.threads?.shown.values() ?? []), ...(arranging.threads?.whole.values() ?? [])].flatMap((each) => each.items);
    const shown: Shown = {
        items: new Map([...threadItems, ...items].map((each) => [each.number, each])),
        beyond: { contexts: around.contexts, files: around.files },
        drawers,
        running: arranging.running ?? new Map(),
        landings: arranging.landings ?? [],
        called: name,
    };
    const now = grouped(items.filter((each) => !parked.includes(each.number)), (item) => banner({ item }, false, ""));
    const empty = emptyGroups([...agents, ...letters.flatMap((each) => (each.to == null ? [] : [each.to])), ...remarks.map((each) => each.to)], now);
    const later = grouped(items.filter((each) => parked.includes(each.number)), (item) => banner({ item }, true, ""));
    const w = new Writer();
    const groups: Group[] = [];
    const regions: Region[] = [];
    const laidDrawers: Drawer[] = [];
    const nodes: Placed[] = [];
    const sections: Section[] = [];
    const outer: Fold[] = [];
    const asides: Aside[] = [];
    const checkLines: CheckLine[] = [];
    const loading: Loading[] = [];
    // The groups whose fold starts closed, as each thread's of the front and of what's settled does, and those whose
    // conversation isn't read yet.
    const closedGroups = new Set<string>();
    const unreadGroups = new Set<string>();
    // Each agent whose "since you approved" is laid out at the end of the thread they work in, by `whose` they are.
    const sinceLaid = new Set<string>();
    const threading = arranging.threads ?? null;
    if (threading === null) {
        for (const { group, depth } of nested(kept([...now, ...empty], false), arranging.parents ?? null)) {
            layGroup(group, false, depth);
        }
        for (const group of kept(later, true)) {
            layGroup(group, true, 0);
        }
    } else {
        layThreaded(threading);
    }
    // Each group folds whole under its banner, up to the next as deep or shallower, a subagent's inside their parent's,
    // a thread's under its parent's in its section, and never past its section's end.
    {
        groups.forEach((group, at) => {
            const next = groups.findIndex((each, after) => after > at && each.depth <= group.depth);
            const section = sections.find((each) => each.header.from > group.banner.from)?.header.from ?? w.at;
            const end = Math.min(next < 0 ? w.at : (groups[next]?.banner.from ?? w.at), section) - 1;
            const id = `group ${group.place}`;
            if (end > group.banner.to) {
                const label = w.lineFrom(group.banner.from);
                group.fold = { of: id, kind: "group", name: "", label, closed: closedGroups.has(id), summary: group.banner, from: group.banner.to, to: end, scope: true, ...(unreadGroups.has(id) ? { unread: true } : {}) };
            }
            group.end = Math.max(end, group.banner.to);
            const node = nodes.find((each) => each.id === id);
            if (node !== undefined) {
                node.to = group.end;
            }
        });
    }
    // Each section folds whole under its line, up to the next.
    sections.forEach((section, at) => {
        const end = (sections[at + 1]?.header.from ?? w.at) - 1;
        const id = `section ${section.name}`;
        if (end > section.header.to) {
            const folded = SECTIONS.find((each) => each.name === section.name)?.folded ?? false;
            section.fold = { of: id, kind: "section", name: "", label: w.lineFrom(section.header.from), closed: folded, summary: section.header, from: section.header.to, to: end, scope: true };
            outer.push(section.fold);
        }
        const node = nodes.find((each) => each.id === id);
        if (node !== undefined) {
            node.to = Math.max(end, section.header.to);
        }
    });
    // Each fold starts as its kind says where it says (`Kind.startsOpen`, a person's layer's), else as its view laid it
    // out; one a mark folded stays folded.
    for (const fold of [...regions, ...laidDrawers].flatMap((each) => each.folds).concat(groups.flatMap((each) => (each.fold === null ? [] : [each.fold])), outer)) {
        const starts = kindOf(fold.kind)?.startsOpen ?? null;
        if (starts !== null && !byMarks.has(fold)) {
            fold.closed = !starts;
        }
    }
    const text = w.text;
    const asLaid = wrote.map((each) => converting.get(writtenId(each)) ?? each);
    const converted = named.changed || converting.size > 0 ? asLaid : null;
    return {
        text,
        groups,
        regions,
        drawers: laidDrawers,
        nodes: nestedNodes(nodes),
        owners: w.owners,
        runs: w.runs,
        seated,
        lines: blockLines,
        written: asLaid,
        converted,
        drawn: drawnAt,
        sections,
        outer: outer.sort((a, b) => a.from - b.from || b.to - a.to),
        asides,
        checks: checkLines,
        loading,
    };

    /** Return `section` with each group laid out before in its place, any other after them, in its own order. */
    function kept(section: Grouping[], isParked: boolean): Grouping[] {
        const rank = (group: Grouping) => {
            const at = places.indexOf(placeOf(group.key, isParked));
            return at < 0 ? places.length : at;
        };
        return [...section].sort((a, b) => rank(a) - rank(b));
    }

    /** Return a part of the review laid out from `from` to `to`, its first line its header. */
    function part(id: string, kind: Placed["kind"], from: number, to: number, extra: Partial<Placed> = {}): Placed {
        return { id, kind, from, to, header: { from, to: Math.min(w.endOf(from), Math.max(to, from)) }, children: [], ...extra };
    }

    /** Return what the operator wrote, laid out at `block`, as a part of the review: by its id. */
    function writtenPart(block: Block): Placed {
        return part(writtenOwner(block.comment), "written", block.from, block.to);
    }

    /** Write what the operator wrote, `each`, on its lines, as its own, gathered in `blocks` and, as parts of the review, in `within`. */
    function writeWritten(each: Written, blocks: Block[], within: Placed[]): void {
        const id = writtenId(each);
        const block = { comment: id, ...w.line(each.text, writtenOwner(id)) };
        blocks.push(block);
        within.push(writtenPart(block));
    }

    /** Return where `id`, a comment on block `block`, was laid out last, and the block's lines then; none where it wasn't laid out on it. */
    function before(id: string, block: string): { placement: Placement; lines: Lines } | null {
        const was = previous?.seated.get(id);
        const lines = previous?.lines.get(block);
        return was !== undefined && was.block === block && lines !== undefined ? { placement: was, lines } : null;
    }

    /**
     * Return the line of `own`, a scope's lines, each of a block (`blocks`, with each block's first among them),
     * `quote`, what `id` is on, is laid out under, on its block, and keep where it is (`seated`); none where its block
     * isn't laid out here.
     */
    function seat(id: string, quote: Quote, blocks: ReadonlyMap<string, number>): number | null {
        const block = quote.block ?? "";
        const lines = blockLines.get(block);
        const first = blocks.get(block);
        if (lines === undefined || first === undefined) {
            // Its block isn't laid out here: it's kept where what it's on whole is, said to be outdated.
            seated.set(id, { block, version: "", first: 0, last: 0, outdated: true });
            return null;
        }
        const at = placedOn(quote, lines, before(id, block));
        seated.set(id, { block, version: lines.version, first: at.first, last: at.last, outdated: at.outdated });
        return first + at.last;
    }

    /**
     * Return the quote kept from before quotes named their block, `quote`, whose `start` and `end` are offsets into the
     * scope's lines `own` joined (`starts`), each of a block (`ofLine`), anchored to the block of the line its passage
     * ends on (`quoting`); none where it's past them.
     */
    function anchored(quote: Quote, starts: readonly number[], length: number, ofLine: OfBlocks): Quote | null {
        if (ofLine.length === 0 || quote.start > length) {
            return null;
        }
        const top = lineOf([...starts], quote.start);
        const bottom = lineOf([...starts], Math.max(quote.end - 1, quote.start));
        const last = ofLine.at(bottom);
        const lines = last === undefined ? undefined : blockLines.get(last.block);
        if (last === undefined || lines === undefined) {
            return null;
        }
        // A passage running over blocks is anchored to the last, from its first line.
        const first = ofLine.at(top)?.block === last.block ? top : bottom - last.line;
        const start = Math.max(quote.start - (starts[first] ?? 0), 0);
        const end = Math.max(quote.end - (starts[first] ?? 0), start);
        return quoting(last.block, lines, ofLine.at(first)?.line ?? 0, last.line, start, end, quote.text);
    }

    /** Return `list` with each laid out before in its place (`places`), the rest after them in their order. */
    function keptBy<T>(list: readonly T[], place: (each: T) => string): T[] {
        const rank = (each: T) => {
            const at = places.indexOf(place(each));
            return at < 0 ? places.length : at;
        };
        return [...list].sort((a, b) => rank(a) - rank(b));
    }

    /**
     * Lay the review out by thread (`docs/dashboard.md`, *The review*), each section under its line, in its order:
     * waiting on you, each thread something in asks the operator, a landing waiting on files among it, those blocked on
     * them first, then those done for them to confirm, each in the order it came into the section, and never sorted
     * again, its place kept (`places`), then what asks them in no thread, as lup's own approvals, by whom it's from; new,
     * each thread with something they haven't read that asks nothing; open, the front, every thread still open those
     * don't hold, a line each, nested under its parent among them, folded, the section open; to read, the pile's count;
     * settled, each thread settled or declined, nested so, folded; and agents, each agent's group as it was, their banner
     * and their own views, folded. A thread of the front or of what's settled is read as it opens.
     */
    function layThreaded(threading: Threading): void {
        const reads = threading.read.threads;
        const landed = (read: ThreadRead) => threading.landing.get(read.thread.number) ?? 0;
        // What the host reads as every thread is the front, each open, or what's settled or declined.
        const sectionOf = (read: ThreadRead): SectionName =>
            landed(read) > 0 ? "waiting on you" : read.section !== "every thread" ? read.section : read.state === "settled" || read.state === "declined" ? "settled" : "open";
        // Where each conversation works, by the thread: whose "since you approved" is laid out at its group's end; and
        // each writer of a file a landing waits on, where they work nowhere now, as an ended subagent, at the end of the
        // thread their lander works in, where what the landing waits on is asked.
        const homes = new Map<number, Conversation[]>();
        const working = new Map((threading.read.working ?? []).map((each) => [whose(each.conversation), each.thread]));
        for (const each of threading.read.working ?? []) {
            homes.set(each.thread, [...(homes.get(each.thread) ?? []), each.conversation]);
        }
        for (const wait of arranging.landings ?? []) {
            const thread = working.get(whose(wait.lander));
            for (const writer of (wait.files ?? []).flatMap((file) => file.writers ?? [])) {
                if (thread !== undefined && !working.has(whose(writer))) {
                    working.set(whose(writer), thread);
                    homes.set(thread, [...(homes.get(thread) ?? []), writer]);
                }
            }
        }
        const since = (read: ThreadRead) => new Date(read.since).getTime();
        const inOrder = (list: ThreadRead[]) => keptBy(list.toSorted((a, b) => since(a) - since(b)), (each) => threadPlace(each.thread.number));
        const waiting = reads.filter((each) => sectionOf(each) === "waiting on you");
        const blocked = inOrder(waiting.filter((each) => (each.asks ?? []).length > 0 || landed(each) > 0));
        const confirming = inOrder(waiting.filter((each) => !blocked.includes(each)));
        const fresh = inOrder(reads.filter((each) => sectionOf(each) === "new"));
        const front = reads.filter((each) => sectionOf(each) === "open");
        const done = reads.filter((each) => sectionOf(each) === "settled");
        // What asks the operator in no thread, as lup's own approvals.
        const asked = new Set(reads.flatMap((each) => (each.asks ?? []).map((ask) => ask.node)));
        const loose = grouped(
            items.filter((each) => each.rank.name === "waiting on you" && !asked.has(each.number) && !parked.includes(each.number)),
            (item) => banner({ item }, false, ""),
        );
        layThreadSection("waiting on you", `${blocked.length + confirming.length + loose.length}`, () => {
            for (const each of [...blocked, ...confirming]) {
                layThread(each, 0, false);
            }
            for (const group of kept(loose, false)) {
                layGroup(group, false, 0);
            }
        });
        layThreadSection("new", `${fresh.length}`, () => {
            for (const each of fresh) {
                layThread(each, 0, false);
            }
        });
        // The front: every thread still open the sections above don't hold, a line each, nested as threads nest.
        layThreadSection("open", `${front.length}`, () => {
            for (const { read, depth } of nestedThreads(front)) {
                layThread(read, depth, true);
            }
        });
        const piled = new Map(items.map((each) => [each.number, each]));
        const pile = reads.flatMap((each) => each.pile ?? []);
        const frictions = pile.filter((each) => piled.get(each)?.reason.reason === "friction").length;
        layThreadSection("to read", [`${frictions} ${frictions === 1 ? "friction" : "frictions"}`, `${pile.length - frictions} how it felt`].join(", "), () => {
            const line = { kind: "summary" as const, ...w.line("frictions and how it felt, by their titles: piece 4c lists them here", "section to read pile") };
            asides.push(line);
        });
        const declined = done.filter((each) => each.state === "declined").length;
        layThreadSection("settled", `${done.length - declined} settled · ${declined} declined`, () => {
            for (const { read, depth } of nestedThreads(done)) {
                layThread(read, depth, true);
            }
        });
        // Each agent's group, their banner and their own views, as an agent's group was: those running, those holding
        // what waits on the operator, and each a message is written to under their banner.
        const agentGroups = emptyGroups(
            [...agents, ...letters.flatMap((each) => (each.to != null && each.thread == null ? [each.to] : [])), ...remarks.map((each) => each.to)],
            [],
        );
        layThreadSection("agents", `${agentGroups.length}`, () => {
            for (const { group, depth } of nested(kept(agentGroups, false), arranging.parents ?? null)) {
                layGroup(group, false, depth);
            }
        });

        /** Return `threads`, each under its parent among them, in the order each was opened, with how deep it's set in. */
        function nestedThreads(threads: readonly ThreadRead[]): { read: ThreadRead; depth: number }[] {
            const numbers = new Set(threads.map((each) => each.thread.number));
            const under = new Map<number | null, ThreadRead[]>();
            for (const each of threads.toSorted((a, b) => a.thread.number - b.thread.number)) {
                let parent = each.thread.parent ?? null;
                while (parent !== null && !numbers.has(parent)) {
                    parent = reads.find((one) => one.thread.number === parent)?.thread.parent ?? null;
                }
                under.set(parent, [...(under.get(parent) ?? []), each]);
            }
            const walk = (read: ThreadRead, depth: number): { read: ThreadRead; depth: number }[] => [
                { read, depth },
                ...(under.get(read.thread.number) ?? []).flatMap((child) => walk(child, depth + 1)),
            ];
            return (under.get(null) ?? []).flatMap((each) => walk(each, 0));
        }

        /** Lay a section's line, saying what it holds, then what `lay` lays in it. */
        function layThreadSection(name: SectionName, holds: string, lay: () => void): void {
            const id = `section ${name}`;
            const header = w.line(`${name} · ${holds}`, id);
            sections.push({ name, header, fold: null });
            nodes.push(part(id, "section", header.from, header.to));
            lay();
        }

        /**
         * Lay thread `read` out as a group, `depth` deep among its section's: its banner, the operator's messages on it,
         * what's to try where it's done, then its conversation from where they last read it, what came before folded
         * under one line and read whole as it opens, and the "since you approved" of each agent working in it; folded,
         * where `folded` says, as the front's and what's settled start, and its conversation read as it opens where it
         * isn't yet.
         */
        function layThread(read: ThreadRead, depth: number, folded: boolean): void {
            const number = read.thread.number;
            const place = threadPlace(number);
            const id = `group ${place}`;
            const opening = w.line(threading.banner(read, landed(read)), `${id} banner`);
            const blocks: Block[] = [];
            const writtenParts: Placed[] = [];
            for (const letter of letters) {
                if (letter.thread === number) {
                    writeWritten(letter, blocks, writtenParts);
                }
            }
            const made: Group = {
                conversation: read.answering ?? null,
                parts: [],
                head: { thread: read },
                later: false,
                place,
                banner: opening,
                blocks,
                drawers: [],
                depth,
                fold: null,
                thread: read,
                end: opening.to,
            };
            groups.push(made);
            const node = part(id, "group", opening.from, opening.to);
            nodes.push(node);
            node.children.push(part(`${id} banner`, "banner", opening.from, opening.to), ...writtenParts);
            if (folded) {
                closedGroups.add(id);
            }
            const status = read.status ?? null;
            const toldFrom = w.at;
            if (status !== null && status.kind === "ledger:done") {
                const [first = "", ...rest] = status.to_try.split("\n");
                asides.push({ kind: "to-try", ...w.line(`◆ to try: ${first}`, `${id} to try`) });
                for (const line of rest) {
                    asides.push({ kind: "to-try", ...w.line(`${SET_IN}${line}`, `${id} to try`) });
                }
            } else if (status !== null && status.kind === "ledger:parked" && (status.why ?? "") !== "") {
                asides.push({ kind: "summary", ...w.line(`parked: ${status.why ?? ""}`, `${id} parked`) });
            }
            if (w.at > toldFrom) {
                node.children.push(part(`${id} status`, "frame", toldFrom, w.at - 1));
            }
            const shownNow = threading.shown.get(number) ?? null;
            if (shownNow === null) {
                // Its conversation is read from the host as its fold opens: a line saying so until it is.
                const reading = w.line("reading…", `${id} reading`);
                asides.push({ kind: "summary", ...reading });
                node.children.push(part(`${id} reading`, "frame", reading.from, reading.to));
                unreadGroups.add(id);
                loading.push({ key: foldKey({ of: id, kind: "group", name: "" }), number, whole: false });
                return;
            }
            // What came before what's new or asks the operator in it, never read, as a past session's whole history
            // lup put in its root, folds with what came before where they last read it.
            const { before, after } = untilCalled(shownNow, read);
            if (shownNow.left > 0 || before.length > 0) {
                // What came before where the operator last read it, or what calls for nothing in one never read, under
                // one line, read whole as it opens: laying a long history out folded cost seconds at the operator's size.
                const whole = threading.whole.get(number) ?? null;
                const earlierFrom = w.at;
                const count = shownNow.left + before.filter((each) => each.member).length;
                const summary = w.line(`${count} earlier${before.length === 0 ? ", read" : ", calling for nothing"}`, `${id} earlier`);
                asides.push({ kind: "summary", ...summary });
                const inner: Placed[] = [];
                if (whole === null) {
                    const reading = w.line("reading…", `${id} earlier reading`);
                    asides.push({ kind: "summary", ...reading });
                    loading.push({ key: foldKey({ of: id, kind: "read", name: "" }), number, whole: true });
                } else {
                    const later = new Set(after.map((each) => spotKey(each.spot)));
                    layEntries(
                        whole.entries.filter((each) => !later.has(spotKey(each.spot))),
                        whole,
                        number,
                        inner,
                    );
                }
                outer.push({ of: id, kind: "read", name: "", label: `${count} earlier`, closed: true, summary, from: summary.to, to: w.at - 1, ...(whole === null ? { unread: true } : {}) });
                node.children.push(part(`${id} earlier`, "frame", earlierFrom, w.at - 1, { children: inner }));
            }
            layEntries(after, shownNow, number, node.children);
            // The "since you approved" of each agent working in it, at its end: the code its agents changed.
            for (const conversation of homes.get(number) ?? []) {
                const key = whose(conversation);
                const drawn = looks.drawers(conversation.repository).find((each) => each.view === "since");
                if (sinceLaid.has(key) || !drawers.has(key) || drawn === undefined) {
                    continue;
                }
                const of = { runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null };
                const view = mount(conversation.repository, drawn.module, drawn.view, of, shown, remote);
                const drawer = layDrawer(drawn.view, conversation, view, name(conversation));
                if (drawer !== null) {
                    sinceLaid.add(key);
                    made.drawers.push(drawer);
                    laidDrawers.push(drawer);
                    node.children.push(drawer.node);
                }
            }
            const lastDrawer = made.drawers.at(-1);
            if (lastDrawer !== undefined) {
                lastDrawer.end = w.line("", `${id} drawers`).from;
            }
        }
    }

    /**
     * Lay `entries` of thread `number`'s conversation, `from` what the host answered of it, into `within`, each reply
     * under what it answers: an item as its region, the operator's words on it inside it after its own, a message between
     * agents folded to its header; a check, what's to try, with what the operator saw where they answered it, ticked with
     * Space `d`, answered in words with a comment under it; a part of the operator's words moved in, or their words on
     * what isn't laid out here, each after who wrote it, saying where it's open.
     */
    function layEntries(entries: readonly ThreadEntry[], from: ThreadShown, number: number, within: Placed[]): void {
        const known = new Map(from.items.map((each) => [each.number, each]));
        const checks = new Map((from.checks ?? []).map((each) => [each.check.number, each]));
        const byKey = new Map(entries.map((each) => [spotKey(each.spot), each]));
        const children = new Map<string, ThreadEntry[]>();
        const roots: ThreadEntry[] = [];
        for (const entry of entries) {
            const parent = entry.under == null ? undefined : byKey.get(spotKey(entry.under));
            if (parent === undefined) {
                roots.push(entry);
            } else {
                children.set(spotKey(parent.spot), [...(children.get(spotKey(parent.spot)) ?? []), entry]);
            }
        }
        const walk = (entry: ThreadEntry, under: boolean) => {
            const below = children.get(spotKey(entry.spot)) ?? [];
            const item = entry.spot.part == null ? known.get(entry.spot.node) : undefined;
            // A flagged write is no item of the review: it's in its writer's "since you approved".
            if (entry.member && item !== undefined && flag(item)) {
                return;
            }
            if (entry.member && item !== undefined) {
                const words = below.filter((each) => !each.member);
                // A message between agents folds to its header, as does what no longer waits on the operator: answered,
                // marked done, decided, which is the thread's history.
                // And what's shown as context before what's new, read already (`ThreadEntry.seen`).
                const between = item.reason.reason === "message" && item.reason.to != null && item.sender.party === "conversation";
                within.push(layItem(item, parked.includes(item.number), { under, words, folded: between || !waits(item) || entry.seen === true }));
                for (const each of words) {
                    for (const child of children.get(spotKey(each.spot)) ?? []) {
                        walk(child, true);
                    }
                }
                for (const child of below.filter((each) => each.member)) {
                    walk(child, true);
                }
                return;
            }
            const check = entry.spot.part == null ? checks.get(entry.spot.node) : undefined;
            if (check !== undefined) {
                layCheck(check, number, within);
            } else if (entry.said != null) {
                layWords(entry, number, from, within);
            }
            for (const child of below) {
                walk(child, true);
            }
        };
        for (const root of roots) {
            walk(root, false);
        }
    }

    /** Lay a check of thread `number` into `within`: what's to try, its lines set in, what the operator saw where they answered it, and the comments drafted on it, an answer in their words. */
    function layCheck(check: CheckRead, number: number, within: Placed[]): void {
        const id = `check ${check.check.number}`;
        const answer = check.answer ?? null;
        const [first = "", ...rest] = check.check.text.split("\n");
        const head = w.line(`${answer === null ? "◆" : "✓"} check ${cited(check.check.number)}: ${first}`, id);
        asides.push({ kind: answer === null ? "check" : "checked", ...head });
        for (const line of rest) {
            asides.push({ kind: "check-text", ...w.line(`${SET_IN}${line}`, id) });
        }
        if (answer !== null) {
            asides.push({ kind: "you", ...w.line(`${SET_IN}you: ${answer.text === "" ? "tried it" : answer.text}`, id) });
        }
        const children: Placed[] = [];
        const blocks: Block[] = [];
        for (const each of wrote) {
            if (isComment(each) && each.item === check.check.number) {
                writeWritten(each, blocks, children);
            }
        }
        const offers: Offer[] =
            answer === null
                ? [{ action: "inbox-check-answer", argument: { number: check.check.number }, verb: "done", chord: null, runs: "send", commented: false, says: "tick it: you tried it" }]
                : [];
        const block: ViewBlock = { block: "line", id, offers, spans: [] };
        within.push(part(id, "block", head.from, w.at - 1, { block, children }));
        checkLines.push({ from: head.from, to: w.at - 1, check, thread: number });
        // What's drafted on it is the thread's group's, which is the one being laid out.
        groups.at(-1)?.blocks.push(...blocks);
    }

    /**
     * Lay the operator's words of `entry` into thread `number`'s `within`, `shown` what the host answered of it, where no
     * item of the thread's holds them: a message they wrote on it, or a part moved in, after who wrote it, saying where
     * it's open, waiting on whoever answers for the thread.
     */
    function layWords(entry: ThreadEntry, number: number, shownNow: ThreadShown, within: Placed[]): void {
        const id = `group ${threadPlace(number)} words ${spotKey(entry.spot)}`;
        const from = w.at;
        const theirs = shownNow.items.find((each) => each.number === entry.spot.node);
        const written = theirs?.reason.reason === "review" && (theirs.reason.letters ?? []).some((each) => each.thread === number);
        const how = !entry.member || written ? "" : ", moved here";
        const answering = shownNow.read.answering ?? null;
        const open = entry.unanswered === true ? ` · open: waits on ${answering === null ? "whoever takes it" : name(answering)}` : "";
        for (const row of wordsRows(entry, `${how}${open}`)) {
            asides.push({ kind: row.kind, ...w.line(row.text, id) });
        }
        within.push(part(id, "frame", from, w.at - 1));
    }

    /** Return the rows the operator's words of `entry` are shown as: who wrote them, whom to and `how`, then each of their lines set in, each with the part it's of. */
    function wordsRows(entry: ThreadEntry, how: string = ""): Beside[] {
        const said = (entry.said ?? "").trimEnd().split("\n");
        const at = startsOf(said);
        const id = { item: entry.spot.node, part: entry.spot.part ?? 0 };
        const to = entry.to == null ? "" : ` to ${name(entry.to)}`;
        return [
            { kind: "by", text: `you · ${cited(entry.spot.node)}.${entry.spot.part ?? 0}${to}${how}`, part: null, own: 0 },
            ...said.map((line, index): Beside => ({ kind: "you", text: `${SET_IN}${line}`, part: id, own: (at[index] ?? 0) - SET_IN.length })),
        ];
    }

    function layGroup(group: Grouping, isParked: boolean, depth: number): void {
        const conversation = group.conversation;
        const repository = conversation?.repository ?? "";
        const of = conversation === null ? null : { runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null };
        // The parts of its banner, each a view of its agent's, where they're running; and, where they're not, those that
        // say something of them still, as an ended agent's files a landing waits on.
        const parts =
            conversation !== null && of !== null
                ? looks
                      .banners(repository)
                      .map((each) => mount(repository, each.module, each.view, of, shown, remote))
                      .filter(
                          (each) =>
                              shown.running.has(group.key) ||
                              wording(each.answer?.blocks.summary ?? []).text !== "" ||
                              (each.answer?.blocks.offers ?? []).length > 0,
                      )
                : [];
        // What each part says, its spans that tick or measure drawn beside the words rather than written.
        const told = parts.flatMap((each) => {
            const spoken = wording(each.answer?.blocks.summary ?? []);
            return spoken.text === "" && spoken.drawn.length === 0 ? [] : [spoken];
        });
        const place = placeOf(group.key, isParked);
        const id = `group ${place}`;
        const partsSaid = told.map((each) => each.text).join(" · ");
        const opening = w.line(banner(group.head, isParked, partsSaid), `${id} banner`);
        let partAt = placedIn(opening, partsSaid, true);
        for (const each of told) {
            drawnIn(partAt, each.drawn);
            partAt += each.text.length + " · ".length;
        }
        const data = conversation !== null && !isParked ? drawers.get(group.key) : undefined;
        const blocks: Block[] = [];
        const writtenParts: Placed[] = [];
        if (!isParked) {
            // A message written on a thread is laid out there, never again under its agent's banner.
            for (const letter of letters) {
                if (letter.to != null && letter.thread == null && whose(letter.to) === group.key) {
                    writeWritten(letter, blocks, writtenParts);
                }
            }
        }
        const made: Group = {
            conversation: group.conversation,
            parts,
            head: group.head,
            later: isParked,
            place,
            banner: opening,
            blocks,
            drawers: [],
            depth,
            fold: null,
            thread: null,
            end: opening.to,
        };
        groups.push(made);
        const node = part(id, "group", opening.from, opening.to);
        nodes.push(node);
        node.children.push(
            part(`${id} banner`, "banner", opening.from, opening.to, { children: parts.map((each) => part(each.id, "view", opening.from, opening.to, { view: each })) }),
            ...writtenParts,
        );
        // Under the banner, before the items, one under the other: each drawer a label, folded until opened in place.
        if (conversation !== null && of !== null && data !== undefined) {
            // An agent's "since you approved" laid out at the end of the thread they work in isn't laid out again here.
            for (const drawn of looks.drawers(repository).filter((each) => !(each.view === "since" && sinceLaid.has(group.key)))) {
                const view = mount(repository, drawn.module, drawn.view, of, shown, remote);
                const drawer = layDrawer(drawn.view, conversation, view);
                if (drawer !== null) {
                    made.drawers.push(drawer);
                    laidDrawers.push(drawer);
                    node.children.push(drawer.node);
                }
            }
            const lastDrawer = made.drawers.at(-1);
            if (lastDrawer !== undefined) {
                // The blank line after them is the last one's, as an item's is its own.
                lastDrawer.end = w.line("", `${id} drawers`).from;
            }
        }
        for (const item of group.items) {
            node.children.push(layItem(item, isParked));
        }
        if (group.items.length === 0 && made.drawers.length === 0 && blocks.length > 0) {
            w.line("", `${id} end`);
        }
    }

    function layItem(item: Item, isParked: boolean, threaded: Threaded = {}): Placed {
        const kind = kindView(item);
        const repository =
            item.sender.party === "conversation" ? item.sender.repository : item.reason.reason === "approval" ? item.reason.repository : "";
        const view = mount(repository, kind.module, kind.view, { number: item.number }, shown, remote);
        const answer = view.answer?.blocks;
        const bodyBlocks = answer?.blocks ?? [];
        const id = `item ${item.number}`;
        const filedBlocks = bodyBlocks.filter(isFiled);
        const files = filedBlocks.flatMap(filedOnce);
        // Its own lines, its text's then its files', each of its block, at its line there: what comments are on.
        const ofLine = new OfBlocks();
        const firstOf = new Map<string, number>();
        const ownLines: string[] = [];
        const ownBlock = (block: ViewBlock, lines: Lines) => {
            const bid = blockId(view.id, block.id);
            firstOf.set(bid, ofLine.length);
            ofLine.add(bid, lines.lines.length);
            blockLines.set(bid, lines);
        };
        for (const block of bodyBlocks) {
            if (block.block === "markdown") {
                const lines = block.text.split("\n");
                ownBlock(block, linesOf(lines, block.version ?? null));
                ownLines.push(...lines);
            }
        }
        for (const block of filedBlocks) {
            ownBlock(block, fileLines(filedOnce(block), block.version ?? null));
            filedBy.set(blockId(view.id, block.id), block);
        }
        const own = [...ownLines, ...files.map((each) => each.text)];
        const starts = startsOf(own);
        const ownCount = ownLines.length;
        const ownLength = own.join("\n").length;
        // Each comment on the item, by the line it's under, once: on the item whole under its header, as is one copies
        // before kept on a reply; one drafted before quotes named their block anchored to it once its files are read.
        const filesRead = !changing(item) || around.files.has(item.number);
        const placed = new Map<number | null, Written[]>();
        const under_ = (line: number | null, comment: Written) => placed.set(line, [...(placed.get(line) ?? []), comment]);
        for (const each of wrote) {
            if (!isComment(each) || each.item !== item.number) {
                continue;
            }
            const cid = writtenId(each);
            const quote = each.quote ?? null;
            if (quote === null || each.on != null) {
                under_(null, each);
            } else if ((quote.block ?? "") !== "") {
                under_(seat(cid, quote, firstOf), each);
            } else if (!filesRead) {
                under_(null, each);
            } else {
                const found = anchored(quote, starts, ownLength, ofLine);
                const now: Comment = found === null ? { ...each, quote: null, text: unplaced(quote.text, each.text) } : { ...each, quote: found };
                converting.set(cid, now);
                under_(found === null ? null : seat(cid, found, firstOf), now);
            }
        }
        const into = gathering();
        const said_: SaidLine[] = [];
        const changed: number[] = [];
        const of = ownerOf({ item });
        const children: Placed[] = [];
        const writeBlocks = (line: number | null) => {
            for (const comment of placed.get(line) ?? []) {
                writeWritten(comment, into.blocks, children);
            }
        };
        // Lines that aren't the item's own, the operator's words among them, each kept with its part where it's theirs.
        const writeRows = (rows: Beside[], owner: string): Aside[] =>
            rows.map((row) => {
                const aside = { kind: row.kind, ...w.line(row.text, owner) };
                into.asides.push(aside);
                if (row.part !== null && row.kind === "you") {
                    said_.push({ from: aside.from, to: aside.to, part: row.part, own: row.own });
                }
                return aside;
            });
        // A fold of the context's kind under `summary`, hiding the lines after it, open or folded.
        const foldUnder = (name: string, label: string, summary: Span, last: Span | undefined, closed: boolean) => {
            if (last !== undefined && last.to > summary.to) {
                into.folds.push({ of, kind: "context", name, label, closed, summary: { from: summary.from, to: summary.to }, from: summary.to, to: last.to });
            }
        };
        // What the core lays out around the body, from `from` up to where the text's at now, as a part of the item's.
        const frame = (name: string, from: number) => {
            if (w.at > from) {
                children.push(part(`${id} ${name}`, "frame", from, w.at - 1));
            }
        };
        const summary = answer?.summary ?? [];
        const spoken = wording(summary);
        const head = header(item, isParked, spoken.text);
        const headed = w.line(head, `${id} header`);
        drawnIn(placedIn(headed, spoken.text, false), spoken.drawn);
        children.push(part(`${id} header`, "header", headed.from, headed.to));
        writeBlocks(null);
        // The operator's words it answers, above its own, each after who wrote it; in a thread, where they show above it
        // in the thread's conversation, not again.
        const theirs = threaded.under === true ? [] : above(item, around.answers, around.commented);
        const sender = item.sender.party === "conversation" ? item.sender : null;
        const aboveFrom = w.at;
        if (theirs.length > 0 && sender !== null) {
            const [first, ...rest] = writeRows(theirs, `${id} above`);
            if (first !== undefined) {
                foldUnder("you", first.kind === "by" ? laidOut(theirs[0]) : "you", first, rest.at(-1), false);
            }
            writeRows([{ kind: "by", text: `${name(sender)} · ${cited(item.number)}, its answer`, part: null, own: 0 }], `${id} above`);
        }
        frame("above", aboveFrom);
        // What its edits changed, folded under a summary line.
        const edited = editedOf(item, (at) => since(new Date(item.made), new Date(at)));
        const editedFrom = w.at;
        if (edited !== null) {
            const line = { kind: "summary" as const, ...w.line(edited.summary, `${id} edited`) };
            into.asides.push(line);
            foldUnder("edited", "edited", line, writeRows(edited.rows, `${id} edited`).at(-1), true);
        }
        frame("edited", editedFrom);
        // Its body, its kind's view of it: its text, each passage its citations cite folded under the line the citation
        // is on; the replies kept from before after it; then its files, and what the host refused.
        const bodyFrom = w.at;
        const inBody: Placed[] = [];
        const citations = citedOn(item, ownLines);
        const textFrom = w.at;
        own.slice(0, ownCount).forEach((line, at) => {
            const block = ofLine.at(at) ?? { block: `${id} text`, line: at };
            const span = w.line(line, block.block);
            into.lines.push({ ...span, own: starts[at] ?? 0, block: block.block, line: block.line });
            if (edited?.changed.includes(at) === true) {
                changed.push(span.from);
            }
            writeBlocks(at);
            const passages = citations.filter((each) => each.line === at).flatMap((each) => passageOf(each.citation));
            foldUnder(`cited ${at}`, "cited", span, writeRows(passages, `${id} cited ${at}`).at(-1), true);
        });
        const textBlock = bodyBlocks.find((each) => each.block === "markdown");
        if (textBlock !== undefined) {
            inBody.push(part(blockId(view.id, textBlock.id), "block", textFrom, w.at - 1, { block: textBlock }));
        }
        // The operator's comments on it and the replies kept on them from before, after its own words.
        const keptFrom = w.at;
        writeRows(keptReplies(item), `${id} replies`);
        if (w.at > keptFrom) {
            inBody.push(part(`${id} replies`, "frame", keptFrom, w.at - 1));
        }
        // In a thread, the operator's words on it, each part after who wrote it and under what it's on, in the order
        // they came: what an agent's later answer in the thread is under, and what its citations of them find.
        const wordsFrom = w.at;
        for (const words of threaded.words ?? []) {
            writeRows(wordsRows(words), `${id} words`);
        }
        if (w.at > wordsFrom) {
            inBody.push(part(`${id} words`, "frame", wordsFrom, w.at - 1));
        }
        const filedBefore = into.filed.length;
        layCode(w, into, of, files, ownCount, starts, writeBlocks, (file) => blockId(view.id, file.id));
        into.filed.slice(filedBefore).forEach((each, at) => {
            const block = filedBlocks[at];
            if (block !== undefined) {
                inBody.push(part(blockId(view.id, block.id), "block", each.from, each.to, { block }));
            }
        });
        for (const block of bodyBlocks) {
            if (block.block === "line") {
                const line = lineOfView(block);
                const aside = { kind: line.kind, ...w.line(line.text, blockId(view.id, block.id)) };
                into.asides.push(aside);
                drawnIn(aside.from, line.drawn);
                inBody.push(part(blockId(view.id, block.id), "block", aside.from, aside.to, { block }));
            }
        }
        if (w.at > bodyFrom) {
            children.push(part(view.id, "view", bodyFrom, w.at - 1, { view, children: inBody }));
        }
        const context = beneath(item, around);
        const contextFrom = w.at;
        if (context !== null) {
            const line = { kind: context.summary.kind, ...w.line(context.summary.text, `${id} context`) };
            into.asides.push(line);
            const shownLines = context.lines.map((each) => {
                const aside = { kind: each.kind, ...w.line(each.text, `${id} context`) };
                into.asides.push(aside);
                return aside;
            });
            const last = shownLines.at(-1);
            if (last !== undefined) {
                into.folds.push({ of, kind: "context", name: "", label: "context", closed: true, summary: { from: line.from, to: line.to }, from: line.to, to: last.to });
            }
        }
        frame("context", contextFrom);
        // The item whole folds under its header, what folds within it inside: folded once it's left for later, or marked
        // done or declined, but where it holds what the operator wrote, which stays in view until it's sent.
        // Folded too where its thread folds it to its header, as a message between agents.
        const closed = isParked || (settling.includes(item.number) && into.blocks.length === 0) || (threaded.folded === true && into.blocks.length === 0);
        const whole: Fold = { of, kind: "item", name: "", label: head, closed, summary: headed, from: headed.to, to: w.at - 1, scope: true };
        into.folds.push(whole);
        if (closed) {
            byMarks.add(whole);
        }
        const placedItem = part(id, "item", headed.from, w.at - 1, { children });
        const blank = w.line("", `${id} end`);
        regions.push({ item, body: view, named: `${cited(item.number)} ${namedBy(summary)}`, of, header: headed, said: said_, changed, end: blank.from, ...into });
        return placedItem;
    }

    /** Return a row's text as its fold's label says it. */
    function laidOut(row: Beside | undefined): string {
        return row?.text.trim() ?? "";
    }

    /**
     * Return the lines of what copies before kept under `item`: each of the operator's comments on it after who wrote
     * it and what it's on, then each reply the agent made to it, after who made it, and the operator's comments on that
     * reply in turn (`threadsOf`); none for an item kept with no reply.
     */
    function keptReplies(item: Item): Beside[] {
        const thread = threadsOf(around.answers, item.number);
        if (thread.replies.length === 0) {
            return [];
        }
        const agent = item.sender.party === "conversation" ? name(item.sender) : "the agent";
        const words = (kind: Beside["kind"], text: string): Beside[] =>
            text.split("\n").map((line) => ({ kind, text: `${SET_IN}${line}`, part: null, own: 0 }));
        const saying = (each: Earlier): Beside[] => [
            { kind: "by", text: `you · ${cited(each.id.item)}.${each.id.part}`, part: null, own: 0 },
            ...(each.quote === null ? [] : [{ kind: "quoted" as const, text: `${SET_IN}on “${each.quote.text.split("\n")[0] ?? ""}”`, part: null, own: 0 }]),
            ...words("you", each.text),
            ...thread.replies.filter((reply) => sameId(reply.to, each.id)).flatMap(replying),
        ];
        const replying = (reply: Replied): Beside[] => [
            { kind: "by", text: `${agent} · ${cited(reply.id.item)}.${reply.id.part}, a reply kept from before`, part: null, own: 0 },
            ...words("agent", reply.text),
            ...thread.said.filter((each) => sameId(each.on, reply.id)).flatMap(saying),
        ];
        return thread.said.filter((each) => each.on === null).flatMap(saying);
    }

    /**
     * Lay `conversation`'s drawer of `kind`, the view `view` of it, and return it; none where its view answers nothing,
     * or nothing under its label, as a task list none keeps, a branch with nothing since the operator approved it, or
     * one not read yet; its label its view's summary line, folded until the operator opens it. A Markdown block's lines
     * are the drawer's own, as a file's are, which a remark may be on (the agent's words in their conversation). The
     * remarks to its agent on one of its blocks go under the line they're on; one on a block not laid out now, as one
     * under a fold not read yet, under its summary line. One drafted before quotes named their block, on the agent's
     * words at a step or on a file's lines, is anchored to it once its block is laid out, else, where what it was on
     * isn't there, kept as a message to the agent.
     */
    function layDrawer(kind: DrawerKind, conversation: Conversation, view: Mounted, owner: string = ""): (Drawer & { node: Placed }) | null {
        const answer = view.answer;
        const labelled = wording(answer?.blocks.summary ?? []);
        const label = labelled.text;
        if (answer === null || label === "") {
            return null;
        }
        const of = ownerOf({ drawer: kind, conversation });
        const into = gathering();
        const key = whose(conversation);
        const ours = `${view.id} `;
        // The remarks to its agent this drawer shows, its own and those it takes from before quotes named their block.
        const mine = (taking: (remark: Remark) => boolean): Remark[] =>
            wrote.flatMap((each) => {
                if (!isRemark(each) || whose(each.to) !== key) {
                    return [];
                }
                const block = each.quote.block ?? "";
                return (block === "" ? taking(each) : block.startsWith(ours)) ? [each] : [];
            });
        const reviewed: ReviewedLine[] = [];
        let settled: Span | null = null;
        const diffs = new Map<string, Filed>();
        const loads = new Map<string, Instance>();
        const toned: (Span & { tone: string })[] = [];
        const texts: Span[] = [];
        const bars: Bar[] = [];
        // A view its module answers is drawn in its tones; the page's own views' lines in what the review draws them as.
        const remotely = producerOf(view.module, view.view) === undefined;
        const tones = (from: number, spans: readonly { text: string; tone?: string }[]) => {
            let at = from;
            for (const each of spans) {
                if (remotely && each.text !== "") {
                    toned.push({ from: at, to: at + each.text.length, tone: each.tone ?? "plain" });
                }
                at += each.text.length;
            }
        };
        const children: Placed[] = [];
        // Laid out in a thread rather than under its agent's banner, its line says whose it is first.
        const said = owner === "" ? "" : `${owner} · `;
        const summary = w.line(`${said}${label}`, `${view.id} summary`);
        const drawnBefore = drawnAt.length;
        drawnIn(summary.from + said.length, labelled.drawn);
        const blocks = answer.blocks.blocks ?? [];
        // What a fold reads as it opens, another of its module's views, and what the host last answered of it.
        const loaded = (content: { view: string; argument: unknown }): Instance => ({ repository: view.repository, module: view.module, view: content.view, argument: content.argument });
        const read = (each: Instance) => remote.get(instanceOf(each.repository, each.module, each.view, each.argument));
        // Each block laid out of the view, given or read, by its id: each Markdown block's lines, which a remark on it
        // is placed by, and each line's, which says the step is no words of the agent's.
        const markdown = new Map<string, string[]>();
        const lineBlocks = new Set<string>();
        const walk = (list: readonly ViewBlock[]) => {
            for (const block of list) {
                const bid = blockId(view.id, block.id);
                if (block.block === "markdown") {
                    const lines = block.text.split("\n");
                    markdown.set(bid, lines);
                    blockLines.set(bid, linesOf(lines, block.version ?? null));
                } else if (block.block === "line") {
                    lineBlocks.add(bid);
                } else if (block.block === "fold") {
                    walk(Array.isArray(block.content) ? block.content : (read(loaded(block.content))?.blocks ?? []));
                }
            }
        };
        walk(blocks);
        // A remark on a file's lines goes under the line it's on, each file's block its own, a file in a fold of the
        // view's, as a place of "since you approved", among them, in the order they're laid out.
        const topFiles = filedIn(blocks);
        const counted = new Set<string>(topFiles.map((each) => each.id));
        const ofLine = new OfBlocks();
        const firstOf = new Map<string, number>();
        const shownFiles: FileLine[] = [];
        for (const block of topFiles) {
            const bid = blockId(view.id, block.id);
            const lines = filedOnce(block);
            filedBy.set(bid, block);
            firstOf.set(bid, ofLine.length);
            ofLine.add(bid, lines.length);
            blockLines.set(bid, fileLines(lines, block.version ?? null));
            shownFiles.push(...lines);
        }
        const starts = startsOf(shownFiles.map((each) => each.text));
        const length = shownFiles.map((each) => each.text).join("\n").length;
        const placed = new Map<number | null, Written[]>();
        // Those on a Markdown block's line, by the block's id and the line.
        const onWords = new Map<string, Written[]>();
        const place = (rid: string, remark: Written, quote: Quote) => {
            const block = quote.block ?? "";
            const lines = markdown.get(block);
            if (lines === undefined) {
                const line = seat(rid, quote, firstOf);
                placed.set(line, [...(placed.get(line) ?? []), remark]);
                return;
            }
            const line = Math.min(seat(rid, quote, new Map([[block, 0]])) ?? 0, lines.length - 1);
            onWords.set(`${block} ${line}`, [...(onWords.get(`${block} ${line}`) ?? []), remark]);
        };
        // One drafted before quotes named their block: on the agent's words at a step, the conversation's; on a file's
        // lines, "since you approved"'s.
        for (const remark of mine((each) => (each.step != null ? kind === "conversation" : kind === "since"))) {
            const rid = writtenId(remark);
            const quote = remark.quote;
            if ((quote.block ?? "") !== "") {
                place(rid, remark, quote);
                continue;
            }
            if (remark.step != null) {
                const block = blockId(view.id, `step ${remark.step}`);
                const lines = markdown.get(block);
                if (lines === undefined && !lineBlocks.has(block)) {
                    // Its step isn't laid out now, under a fold not read yet: under the summary line, until it is.
                    placed.set(null, [...(placed.get(null) ?? []), remark]);
                    continue;
                }
                if (lines === undefined) {
                    converting.set(rid, { id: rid, to: remark.to, text: unplaced(quote.text, remark.text) });
                    continue;
                }
                const at = startsOf(lines);
                const top = lineOf(at, quote.start);
                const bottom = lineOf(at, Math.max(quote.end - 1, quote.start));
                const start = quote.start - (at[top] ?? 0);
                const now: Remark = { ...remark, quote: quoting(block, linesOf(lines), top, bottom, start, Math.max(quote.end - (at[top] ?? 0), start), quote.text), step: null };
                converting.set(rid, now);
                place(rid, now, now.quote);
                continue;
            }
            const found = remark.code != null ? onCode(remark.code, view.id, quote) : anchored(quote, starts, length, ofLine);
            if (found === null) {
                converting.set(rid, { id: rid, to: remark.to, text: unplaced(quote.text, remark.text) });
                continue;
            }
            const now: Remark = { ...remark, quote: found, step: null };
            converting.set(rid, now);
            place(rid, now, found);
        }
        const writeBlocks = (line: number | null) => {
            for (const comment of placed.get(line) ?? []) {
                writeWritten(comment, into.blocks, children);
            }
        };
        // A remark on a file the drawer no longer shows whole goes under the file's line where it stands as the
        // operator last saw it, else under the drawer's summary line, as one on a block not laid out now does.
        const standing = new Set<string>();
        const stands = (list: readonly ViewBlock[]) => {
            for (const block of list) {
                if (block.block === "line") {
                    standing.add(block.id);
                } else if (block.block === "fold" && Array.isArray(block.content)) {
                    stands(block.content);
                }
            }
        };
        stands(blocks);
        const fileOf = (remark: Written) => ("quote" in remark ? (remark.quote?.block ?? "") : "").slice(`${view.id} file `.length);
        const orphans = placed.get(null) ?? [];
        // By what follows `reviewed ` in the line's id, its path and its place's.
        const under = (key: string) => orphans.filter((each) => standing.has(`reviewed ${key}`) && fileOf(each) === key);
        for (const comment of orphans.filter((each) => !standing.has(`reviewed ${fileOf(each)}`))) {
            writeWritten(comment, into.blocks, children);
        }
        let first = 0;
        const layBlocks = (list: readonly ViewBlock[], top: boolean, within: Placed[]) => {
            for (const block of list) {
                const id = blockId(view.id, block.id);
                switch (block.block) {
                    case "diff":
                    case "code": {
                        const lines = filedOnce(block);
                        const before = into.filed.length;
                        layCode(w, into, of, lines, first, starts, writeBlocks, () => id);
                        first += counted.has(block.id) ? lines.length : 0;
                        diffs.set(block.id, block);
                        const span = into.filed[before];
                        if (span !== undefined) {
                            within.push(part(id, "block", span.from, span.to, { block }));
                            // Marked reviewed, it folds under its header, but where it holds what the operator wrote.
                            const writes = into.blocks.some((each) => each.from >= span.from && each.from <= span.to);
                            const own = into.folds.find((each) => each.kind === "file" && each.summary.from === span.from);
                            if (own !== undefined && markedDone.has(id) && !writes) {
                                own.closed = true;
                                byMarks.add(own);
                            }
                        }
                        break;
                    }
                    case "line": {
                        const line = lineOfView(block);
                        const aside = { kind: line.kind, ...w.line(line.text, id) };
                        into.asides.push(aside);
                        drawnIn(aside.from, line.drawn);
                        tones(aside.from, (block.spans ?? []).filter((each) => !isDrawn(each)));
                        const file = answer.files?.get(block.id);
                        if (file !== undefined) {
                            reviewed.push({ from: aside.from, to: aside.to, file });
                            for (const comment of under(block.id.slice("reviewed ".length))) {
                                writeWritten(comment, into.blocks, children);
                            }
                        }
                        within.push(part(id, "block", aside.from, aside.to, { block }));
                        break;
                    }
                    case "markdown": {
                        // Each line its own, a passage over several keeping the blank ones between; the remarks on
                        // it under it.
                        const from = w.at;
                        block.text.split("\n").forEach((text, line) => {
                            const shown = w.line(text, id);
                            const last = into.lines.at(-1);
                            const own = last === undefined ? 0 : last.own + (last.to - last.from) + 1;
                            into.lines.push({ from: shown.from, to: shown.to, own, block: id, line });
                            for (const comment of onWords.get(`${id} ${line}`) ?? []) {
                                writeWritten(comment, into.blocks, children);
                            }
                        });
                        texts.push({ from, to: w.at - 1 });
                        within.push(part(id, "block", from, w.at - 1, { block }));
                        break;
                    }
                    case "fold": {
                        const line = lineOfView({ spans: block.summary });
                        const head = { kind: line.kind, ...w.line(line.text, id) };
                        into.asides.push(head);
                        drawnIn(head.from, line.drawn);
                        tones(head.from, block.summary.filter((each) => !isDrawn(each)));
                        const inner: Placed[] = [];
                        let unread = false;
                        if (Array.isArray(block.content)) {
                            layBlocks(block.content, false, inner);
                        } else {
                            // Read from another of its module's views as it opens: what the host answered of it, or a
                            // line saying it's being read, which opening the fold asks for.
                            const reading = loaded(block.content);
                            loads.set(block.id, reading);
                            const answered = read(reading);
                            if (answered === undefined) {
                                into.asides.push({ kind: "plain", ...w.line("reading…", `${id} reading`) });
                                unread = true;
                            } else {
                                layBlocks(answered.blocks ?? [], false, inner);
                            }
                        }
                        const last = w.at - 1;
                        if (block.kind === "lines" && block.id.startsWith("reviewed")) {
                            settled ??= { from: head.from, to: head.to };
                        }
                        if (last > head.to) {
                            into.folds.push({ of, kind: block.kind, name: block.id, label: line.text, closed: !(block.open ?? false), summary: { from: head.from, to: head.to }, from: head.to, to: last, unread });
                            if (block.barred ?? false) {
                                bars.push({ from: head.to + 1, to: last, kind: block.kind });
                            }
                        }
                        within.push(part(id, "block", head.from, last, { block, children: inner }));
                        break;
                    }
                }
            }
        };
        layBlocks(blocks, true, children);
        const last = w.at - 1;
        // A drawer with nothing under its summary line isn't shown: it would say only that it's empty.
        if (last <= summary.to) {
            w.cut(summary.from);
            drawnAt.length = drawnBefore;
            return null;
        }
        // Folded until opened, a line under the banner; marked done, as a conversation marked read, it folds however
        // the operator left it, but where it holds what they wrote.
        const drawerFold: Fold = { of, kind, name: "", label: `${said}${label}`, closed: true, summary, from: summary.to, to: last, scope: true };
        into.folds.push(drawerFold);
        if (markedDone.has(view.id) && into.blocks.length === 0) {
            byMarks.add(drawerFold);
        }
        const node = part(view.id, "view", summary.from, last, { view, children });
        return {
            end: last,
            kind,
            conversation,
            view,
            diffs,
            loads,
            toned,
            texts,
            bars,
            files: [...(answer.files?.values() ?? [])],
            reviewed,
            settled,
            waiting: answer.blocks.waiting ?? false,
            of,
            header: summary,
            node,
            ...into,
        };
    }

    /**
     * Return the quote of a remark on code drafted before quotes named their block, `quote`, on the lines `code` names
     * of a file of the view `view`, anchored to that file's block: where the file shows them at the numbers they had,
     * as they were, else where it shows them nearest, else at those numbers, outdated; none where the view shows no
     * such file, or neither.
     */
    function onCode(code: NonNullable<Remark["code"]>, view: string, quote: Quote): Quote | null {
        const block = blockId(view, `file ${code.path}`);
        const lines = blockLines.get(block);
        const file = filedBy.get(block);
        if (lines === undefined || file === undefined) {
            return null;
        }
        const at = filedOnce(file).findIndex((each) => each.row?.side === "after" && each.row.number === code.first);
        const end = code.lines.join("\n").length;
        const found = placedOn({ ...quote, block, line: Math.max(at, 0), lines: code.lines, start: 0, end }, lines, null);
        if (found.outdated && at < 0) {
            return null;
        }
        return { text: quote.text, block, version: code.version, line: found.first, lines: code.lines, start: 0, end };
    }
}

/** Return `groups`' parts, each subagent's inside their parent's, where its range is inside the parent's, as their folds nest. */
function nestedNodes(groups: Placed[]): Placed[] {
    const roots: Placed[] = [];
    const holding: Placed[] = [];
    for (const each of groups) {
        while (holding.length > 0 && (holding.at(-1)?.to ?? 0) < each.from) {
            holding.pop();
        }
        (holding.at(-1)?.children ?? roots).push(each);
        holding.push(each);
    }
    return roots;
}

/**
 * Return each line a fold set off by a bar holds, by where it starts, with the classes it's drawn with: set in by how many
 * such folds it's in, at most three (`bar-1`), and the innermost's bar, in its kind's colour (`barred-<kind>`, `looks.ts`).
 */
export function barsOf(text: string, bars: readonly Bar[]): Map<number, string> {
    const lines = new Map<number, { depth: number; kind: string; width: number }>();
    // The outermost first, so the innermost's kind is the one left on each line.
    for (const bar of [...bars].sort((a, b) => b.to - b.from - (a.to - a.from))) {
        let at = bar.from;
        while (at <= bar.to) {
            const was = lines.get(at);
            lines.set(at, { depth: (was?.depth ?? 0) + 1, kind: bar.kind, width: bar.to - bar.from });
            const end = text.indexOf("\n", at);
            if (end < 0) {
                break;
            }
            at = end + 1;
        }
    }
    return new Map([...lines].map(([at, each]) => [at, `bar-${Math.min(each.depth, 3)} barred-${each.kind}`]));
}

/** Return where going to an item lands: on its first line that matters, as the judge read its files, unless it's folded whole, marked read or left for later; else on its header. */
export function arrival(region: Region): number {
    const whole = region.folds.some((each) => each.kind === "item" && each.closed);
    return (whole ? undefined : region.stops[0]) ?? region.header.from;
}

/**
 * Return the start of each file's header line, of every change and "since you approved" drawer, in the text's order:
 * where `]f` and `[f` go, and where a key held down or a page scroll stops (`stopAt`, `editor.ts`). A file folded whole
 * is one, its header the fold's summary line; one standing as the operator last saw it, a line with nothing under it to
 * read, isn't.
 */
export function fileHeads(laidOut: Laid): number[] {
    return [...laidOut.regions, ...laidOut.drawers].flatMap((scope) => scope.filed.map((each) => each.from)).sort((a, b) => a - b);
}

/**
 * Return each file of every change and "since you approved" drawer, and each item, from its header's line to its last,
 * in the text's order: what a page scroll holds at the end of (`pageStop`, `page/src/editor.ts`), so it never shows two
 * of them at once where it can help it.
 */
export function pageUnits(laidOut: Laid): Span[] {
    const files = [...laidOut.regions, ...laidOut.drawers].flatMap((scope) => scope.filed.map((each) => ({ from: each.from, to: each.to })));
    const items = (nodes: readonly Placed[]): Span[] => nodes.flatMap((each) => (each.kind === "item" ? [{ from: each.from, to: each.to }] : items(each.children)));
    return [...files, ...items(laidOut.nodes)].sort((a, b) => a.from - b.from || b.to - a.to);
}

/**
 * Return where Space `d` goes on to once it marks `blocks`, a file of a "since you approved" drawer, done in `draft`: the
 * header of the next file of that drawer after it that's still to review, offering done and marked by nothing in the
 * draft; none past the last, or where what was marked isn't one drawer's file, as the drawer whole.
 */
export function nextToReview(laidOut: Laid, blocks: readonly string[], draft: Draft): number | undefined {
    const marked = blocks.flatMap((id) => {
        const node = findPlaced(laidOut.nodes, id);
        return node === undefined ? [] : [node];
    });
    const last = marked.at(-1);
    const drawer = last === undefined ? undefined : laidOut.drawers.find((each) => each.kind === "since" && last.id.startsWith(`${each.view.id} `));
    if (last === undefined || drawer === undefined || marked.length !== blocks.length || !marked.every((each) => drawer.files.some((file) => each.id === blockId(drawer.view.id, file.block)))) {
        return undefined;
    }
    const next = drawer.files
        .map((file) => findPlaced(laidOut.nodes, blockId(drawer.view.id, file.block)))
        .filter((node): node is Placed => node !== undefined && node.from > last.from)
        .sort((a, b) => a.from - b.from)
        .find((node) => (node.block?.offers ?? []).some((each) => each.verb === "done") && !(draft.marks ?? []).some((mark) => mark.block === node.id));
    return next?.from;
}

/** Return the part of `nodes` whose id is `id`, at any depth; none where none is. */
function findPlaced(nodes: readonly Placed[], id: string): Placed | undefined {
    for (const each of nodes) {
        if (each.id === id) {
            return each;
        }
        const found = findPlaced(each.children, id);
        if (found !== undefined) {
            return found;
        }
    }
    return undefined;
}

/** Return the stop after the line starting at `line`, or before it, of `stops`, in the text's order; none past the last, or before the first. */
export function stepped(stops: number[], line: number, forward: boolean): number | undefined {
    return forward ? stops.find((each) => each > line) : [...stops].reverse().find((each) => each < line);
}

/**
 * Whether an item is to answer rather than to read: ranked as waiting on the operator (`Item.rank`, which the host
 * gives), a question, a held change, an approval or a hold at landing, still waiting where it stands, and neither marked
 * read nor left for later in `draft`, which settles it until the reply is sent.
 */
export function toAnswer(item: Item, draft: Draft): boolean {
    const settled = [...(draft.done ?? []), ...(draft.declined ?? []), ...(draft.parked ?? [])];
    return item.rank.name === "waiting on you" && waits(item) && !settled.includes(item.number);
}

/** Whether an item still waits where it stands, as each the inbox lists does: grouped by thread, a thread's conversation shows those answered, done or decided too. */
export function waits(item: Item): boolean {
    return item.state.state === "waiting";
}

/**
 * Return the classes of an item's header line: new to the operator, news; struck through where the draft marks it done,
 * declined or left for later, which the next Ctrl+Enter does; and muted where it no longer waits, answered, read or
 * decided, a thread's history, never struck through as the draft's own marks are.
 */
export function headerClasses(item: Item, draft: Draft, seeing: Seeing): string {
    const number = item.number;
    return [
        "review-header",
        fresh(item, seeing) ? "is-new" : "",
        news(item) ? "is-news" : "",
        (draft.done ?? []).includes(number) ? "is-done" : waits(item) ? "" : "is-past",
        (draft.declined ?? []).includes(number) ? "is-declined" : "",
        (draft.parked ?? []).includes(number) ? "is-parked" : "",
    ].join(" ");
}

/**
 * Return where `]a` or `[a` goes from `head`: the next (`forward`) or previous item to answer (`toAnswer`), in the
 * order they came, by their numbers, whatever order the text lays them out in, so each is reached once. From the item
 * the cursor is in, the one after or before it among them; from a banner or a line of no item, the first item laid
 * out after the cursor, that one counting, or going back the last before it. None past the last, or before the first.
 */
export function answerAfter(laidOut: Laid, draft: Draft, head: number, forward: boolean): Region | undefined {
    const inside = regionAt(laidOut, head);
    const beside = forward
        ? laidOut.regions.find((each) => each.header.from > head)
        : laidOut.regions.findLast((each) => each.header.from < head);
    const from = inside ?? beside;
    if (from === undefined) {
        return undefined;
    }
    const number = from.item.number;
    const bound = inside === undefined ? number : forward ? number + 1 : number - 1;
    const walk = laidOut.regions.filter((each) => toAnswer(each.item, draft)).toSorted((a, b) => a.item.number - b.item.number);
    return forward ? walk.find((each) => each.item.number >= bound) : walk.findLast((each) => each.item.number <= bound);
}

/**
 * Say what waits below, for the header over the review, so the operator knows without the text moving to show it: how
 * many items are to answer (`toAnswer`), and how many are new to them, their groups not seen since (`fresh`), among
 * those neither marked read nor left for later; nothing where no item waits.
 */
export function tallied(items: Item[], draft: Draft, seeing: Seeing): string {
    if (items.length === 0) {
        return "";
    }
    const settled = [...(draft.done ?? []), ...(draft.declined ?? []), ...(draft.parked ?? [])];
    const open = items.filter((each) => !settled.includes(each.number));
    const answering = open.filter((each) => toAnswer(each, draft)).length;
    const arrived = open.filter((each) => fresh(each, seeing)).length;
    return [`${answering} to answer`, ...(arrived === 0 ? [] : [`${arrived} new`])].join(" · ");
}

/** Return the last of `spans`, in the text's order, starting at or before `position`. */
function lastFrom<T>(spans: T[], from: (each: T) => number, position: number): T | undefined {
    return spans.findLast((each) => from(each) <= position);
}

/** Return every scope, the items' and the drawers', in the text's order. */
function scopes(laidOut: Laid): Scope[] {
    return [...laidOut.regions, ...laidOut.drawers].sort((a, b) => a.header.from - b.header.from);
}

/** Return the item or the drawer `position` is in: its header, its lines, its comments, or the blank line after it; none on a group's banner or the messages under it, nor on a thread's own lines between its items, a check, the operator's words moved in. */
export function scopeAt(laidOut: Laid, position: number): Scope | undefined {
    const scope = lastFrom(scopes(laidOut), (each) => each.header.from, position);
    const group = lastFrom(laidOut.groups, (each) => each.banner.from, position);
    return scope !== undefined && position <= scope.end && (group === undefined || scope.header.from > group.banner.from) ? scope : undefined;
}

/** Return whether `scope` is an item's. */
export function isRegion(scope: Scope): scope is Region {
    return "item" in scope;
}

/** Return whether `scope` is a drawer. */
export function isDrawer(scope: Scope): scope is Drawer {
    return "kind" in scope;
}

/** Return the region `position` is in: an item's header, its lines, its comments, or the blank line after it; none on a group's banner, the messages under it, or a drawer. */
export function regionAt(laidOut: Laid, position: number): Region | undefined {
    const scope = scopeAt(laidOut, position);
    return scope !== undefined && isRegion(scope) ? scope : undefined;
}

/** Return the drawer `position` is in: its summary line, its lines, its comments, or the blank line after it; none elsewhere. */
export function drawerAt(laidOut: Laid, position: number): Drawer | undefined {
    const scope = scopeAt(laidOut, position);
    return scope !== undefined && isDrawer(scope) ? scope : undefined;
}

/** Return the group `position` is on: on its banner, the messages under it, or the blank line after them, a thread's own lines among them; none on an item or a drawer, nor on a section's line. */
export function groupAt(laidOut: Laid, position: number): Group | undefined {
    return scopeAt(laidOut, position) === undefined ? groupAround(laidOut, position) : undefined;
}

/** Return the group `position` is in, on its banner, its items or its drawers; none on a section's line. */
export function groupAround(laidOut: Laid, position: number): Group | undefined {
    return laidOut.groups.findLast((each) => each.banner.from <= position && position <= each.end);
}

/** Return the check `position` is on, its lines or the comments drafted on it; none elsewhere. */
export function checkAt(laidOut: Laid, position: number): CheckLine | undefined {
    return laidOut.checks.find((each) => position >= each.from && position <= each.to);
}

/** Return the section `position` is in; none grouped by agent. */
export function sectionAt(laidOut: Laid, position: number): Section | undefined {
    return lastFrom(laidOut.sections, (each) => each.header.from, position);
}

/** One part of what the header over the review says: whom what's being written goes to, the group, or a fold the cursor is in, by its kind. */
export interface Where {
    kind: "to" | "group" | FoldKind;
    text: string;
}

/** How the header names what it says: a group, by its banner; an item, by its header; a conversation, as it's called. */
export interface Naming {
    group: (group: Group) => string;
    item: (region: Region) => string;
    party: (conversation: Conversation) => string;
}

/** Return the conversation a comment on `item` goes to: the session whose push asked an approval, none where none did; the agent who sent any other. */
export function recipient(item: Item): Conversation | null {
    if (item.reason.reason === "approval") {
        return item.reason.pushed_by ?? null;
    }
    return item.sender.party === "conversation" ? item.sender : null;
}

/**
 * Return what the header over the review says with the cursor at `head`: while a comment, a message or a remark is
 * being written (`writing`; `wrote`, what's written as the editor holds it), whom it goes to; then the group the cursor
 * is in, the item or the drawer, the file, and each fold it's in within them, a body, a run of lines, or the item's
 * context. Nothing before the first group, as where nothing's waiting.
 */
export function heading(laidOut: Laid, head: number, writing: boolean, wrote: Written[], naming: Naming): Where[] {
    const group = groupAround(laidOut, head);
    if (group === undefined) {
        const section = sectionAt(laidOut, head);
        return section === undefined ? [] : [{ kind: "section", text: section.name }];
    }
    const block = writing ? blockAt(laidOut, head) : undefined;
    const being = block === undefined ? undefined : wrote.find((each) => writtenId(each) === block.comment);
    const goesTo = (written: Written): Conversation | null => {
        if (isLetter(written) || isRemark(written)) {
            return written.to ?? null;
        }
        const item = laidOut.regions.find((each) => each.item.number === written.item)?.item;
        return item === undefined ? null : recipient(item);
    };
    const party = being === undefined ? undefined : goesTo(being);
    const going: Where[] =
        party === undefined || being === undefined ? [] : [{ kind: "to", text: reachedBy(laidOut, being, party, naming.party) }];
    const scope = scopeAt(laidOut, head);
    if (scope === undefined) {
        return [...going, { kind: "group", text: naming.group(group) }];
    }
    // A file's path: from its lines, or from its line in "since you approved" once it stands as the operator last saw it.
    const file = scope.filed.find((each) => head >= each.from && head <= each.to)?.file.path ?? (isDrawer(scope) ? reviewedAt(scope, head)?.file.file.path : undefined);
    const inner = around(scope.folds, head).filter((each) => each.kind !== "file" && each.of !== scope.of || (each.kind !== "item" && each.kind !== "file" && kindOf(each.kind)?.drawer !== true));
    const named: Where = isRegion(scope) ? { kind: "item", text: naming.item(scope) } : { kind: (scope as Drawer).kind, text: (scope as Drawer).kind };
    return [
        ...going,
        { kind: "group", text: naming.group(group) },
        named,
        ...(file === undefined ? [] : [{ kind: "file" as const, text: file }]),
        ...inner.map((each) => ({ kind: each.kind, text: each.label })),
    ];
}

/**
 * Say whom what's written reaches, `party` as `goesTo` reads it: a conversation as `called` calls them; a message on a
 * thread to no one, kept there; a comment on an approval no session's push asked, no agent.
 */
export function reachedBy(laidOut: Laid, written: Written, party: Conversation | null, called: (party: Conversation) => string): string {
    if (party !== null) {
        return `to ${called(party)}`;
    }
    if (isLetter(written) && written.thread != null) {
        const thread = laidOut.groups.find((each) => each.thread?.thread.number === written.thread)?.thread?.thread.name;
        return `to no one, kept in @${thread ?? written.thread}`;
    }
    return "to no agent: no session's push asked it";
}

/** Return every comment, message and remark shown, as blocks of the editor's list of what's written. */
export function blocksOf(laidOut: Laid): Block[] {
    return [...laidOut.groups.flatMap((each) => each.blocks), ...scopes(laidOut).flatMap((each) => each.blocks)];
}

/** Return the comment, message or remark shown at `position`, where it's in one; a comment's end counts, so an empty one can be typed in. */
export function blockAt(laidOut: Laid, position: number): Block | undefined {
    return blocksOf(laidOut).find((each) => position >= each.from && position <= each.to);
}

/** Return a message to the agent `group` is of, as it's opened: empty; on a thread, to whoever answers for it, or to no one where nobody does; none for a group no message goes to. */
function letterTo(group: Group): Letter | undefined {
    if (group.thread !== null) {
        return { id: "", to: group.conversation, thread: group.thread.thread.number, text: "" };
    }
    return group.conversation === null ? undefined : { id: "", to: group.conversation, text: "" };
}

/** Return the scope's own line shown at `position`, where it's on one. */
export function lineAt(scope: Scope, position: number): OwnLine | undefined {
    return scope.lines.find((each) => position >= each.from && position <= each.to);
}

/** Return the line under an item or in a drawer that isn't its own text shown at `position`, where it's on one. */
export function asideAt(scope: Scope, position: number): Aside | undefined {
    return scope.asides.find((each) => position >= each.from && position <= each.to);
}


/** Return the folds of the item or the drawer `position` is in, which `zr`, `zm`, `zR`, `zM` and Space `z` reach: none on a group's banner or the messages under it. */
export function foldsOf(laidOut: Laid, position: number): Fold[] {
    return scopeAt(laidOut, position)?.folds ?? [];
}

/** Return the innermost fold `position` is in: on its summary line or the lines it hides. */
export function foldAt(laidOut: Laid, position: number): Fold | undefined {
    return around(
        scopes(laidOut).flatMap((each) => each.folds),
        position,
    ).at(-1);
}

/** Return what names a fold across layouts: its owner, what it holds, and which of those it is. */
export function foldKey(fold: Pick<Fold, "of" | "kind" | "name">): string {
    return `${fold.of} ${fold.kind} ${fold.name}`;
}

/** Return where the first of `code` ending at or after `position` is among them, found by halving: they're in the text's order. */
export function codeFrom(code: Coded[], position: number): number {
    let low = 0;
    let high = code.length;
    while (low < high) {
        const middle = (low + high) >> 1;
        if ((code[middle]?.to ?? 0) < position) {
            low = middle + 1;
        } else {
            high = middle;
        }
    }
    return low;
}

/** Return the line of a file standing as the operator last saw it that `position` is on in a "since you approved" `drawer`; none where it's on none. */
export function reviewedAt(drawer: Drawer, position: number): ReviewedLine | undefined {
    return drawer.reviewed.find((each) => position >= each.from && position <= each.to);
}

/** Return the file of a "since you approved" `drawer` that `position` is on, by its lines or by its line standing as the operator last saw it, with its place and block; none where it's on none. */
export function sinceFileAt(drawer: Drawer, position: number): PlacedFile | undefined {
    const coded = codeAt(drawer, position);
    if (coded !== undefined) {
        return shownAs(drawer, coded.file);
    }
    return reviewedAt(drawer, position)?.file;
}

/** Return the file of a "since you approved" `drawer` shown whole as `filed`, with its place and block; none where it shows none so. */
export function shownAs(drawer: Drawer, filed: Filed): PlacedFile | undefined {
    return drawer.files.find((each) => each.file.file != null && drawer.diffs.get(each.block) === filed);
}

/** Return the line of a changed file shown at `position`, where it's on one. */
export function codeAt(scope: Scope, position: number): Coded | undefined {
    const found = scope.code[codeFrom(scope.code, position)];
    return found !== undefined && position >= found.from && position <= found.to ? found : undefined;
}

/** How a line of a changed file is marked where a comment quotes it, as a diff marks it. */
const SIGNS: Record<Row["change"], string> = { added: "+", removed: "-", same: " " };

/**
 * Say the passage `from` to `to` selects on `lines` as a comment quotes it, so the agent can find it: the item's own
 * words as they are; a changed file's lines under the file's path and where they are in it (`path:12-14`, the
 * numbers what the file becomes, or what it was where they're all removed), each marked as a diff marks it; a file's
 * header alone, its path.
 */
function said(text: string, scope: Scope, lines: Line[], from: number, to: number): string {
    const parts = lines.map((line) => ({
        line,
        coded: codeAt(scope, line.from),
        text: text.slice(Math.max(line.from, from), Math.min(line.to, Math.max(to, line.from))),
    }));
    const groups: (typeof parts)[] = [];
    for (const part of parts) {
        const last = groups.at(-1);
        const same = last?.[0]?.coded?.file === part.coded?.file;
        if (last !== undefined && same) {
            last.push(part);
        } else {
            groups.push([part]);
        }
    }
    return groups
        .map((group) => {
            const file = group[0]?.coded?.file;
            if (file === undefined) {
                return group.map((each) => each.text).join("\n");
            }
            const rows = group.flatMap((each) => (each.coded?.row == null ? [] : [{ row: each.coded.row, text: each.text }]));
            const kept = rows.filter((each) => each.row.side === "after");
            const numbered = (kept.length > 0 ? kept : rows).map((each) => each.row.number);
            const span = numbered.length === 0 ? "" : `:${spanOf(numbered)}`;
            const before = kept.length === 0 && rows.length > 0 ? ", as it was before the change" : "";
            return [`${file.path}${span}${before}`, ...rows.map((each) => `${SIGNS[each.row.change]}${each.text}`)].join(
                "\n",
            );
        })
        .join("\n");
}

/** Say a run of line numbers as a span: `12`, or `12-14`. */
function spanOf(numbers: number[]): string {
    const first = Math.min(...numbers);
    const last = Math.max(...numbers);
    return first === last ? `${first}` : `${first}-${last}`;
}

/**
 * Return the version of the file a remark on `lines` of a "since you approved" `drawer` records: the file, its version
 * as the drawer read it, and the lines quoted as that version holds them, those the file becomes; none where the
 * lines are of no file the drawer shows, or none of them is of the file as it stands.
 */
function quotedCode(drawer: Drawer, lines: Line[]): NonNullable<Remark["code"]> | null {
    const coded = lines.flatMap((line) => {
        const found = codeAt(drawer, line.from);
        return found === undefined ? [] : [found];
    });
    const file = coded[0]?.file;
    const placed = file === undefined ? undefined : shownAs(drawer, file);
    const shown = placed?.file;
    const worktree = placed?.place.worktree ?? null;
    const rows = coded.flatMap((each) => (each.file === file && each.row !== null && each.row.side === "after" ? [each.row] : []));
    const first = rows[0];
    if (shown === undefined || shown.version == null || worktree === null || first === undefined) {
        return null;
    }
    return { worktree, path: shown.path, version: shown.version, first: first.number, lines: rows.map((each) => each.text) };
}

/**
 * Return where a comment opened on the line at `position` goes: on that line of its item, or on the item whole from
 * its header or an empty line of its own; on a line of a changed file, or its header, empty or not; in a drawer, a
 * remark to its agent on the agent's words in their conversation, or on a line of a file since the operator approved
 * it, which records the file's version. On a group's banner, a message to its agent, laid out under its group among those
 * to answer now, from the banner of what's left for later too. None on a line no comment is on, or on the banner of
 * lup's approvals.
 */
export function opened(laidOut: Laid, position: number): Written | undefined {
    // On a check, a comment on it: the operator's answer in words.
    const check = checkAt(laidOut, position);
    if (check !== undefined) {
        return { id: "", item: check.check.check.number, quote: null, text: "" };
    }
    const group = groupAt(laidOut, position);
    if (group !== undefined) {
        return letterTo(group);
    }
    const drawer = drawerAt(laidOut, position);
    if (drawer !== undefined) {
        return openedIn(laidOut, drawer, position);
    }
    const region = regionAt(laidOut, position);
    if (region === undefined || asideAt(region, position) !== undefined) {
        return undefined;
    }
    const line = lineAt(region, position);
    const shown = line === undefined ? "" : laidOut.text.slice(line.from, line.to);
    if (line === undefined || (shown === "" && codeAt(region, line.from) === undefined)) {
        return { id: "", item: region.item.number, quote: null, text: "" };
    }
    const quote = onLines(laidOut, line, line, 0, shown.length, said(laidOut.text, region, [line], line.from, line.to));
    return { id: "", item: region.item.number, quote, text: "" };
}

/** Return the quote of the passage from `start` in line `first` to `end`, counted in lines `first` to `last` joined, of a scope's own lines, both of one block: anchored to that block (`quoting`), saying `text`; none where the block's lines aren't laid out. */
function onLines(laidOut: Laid, first: OwnLine, last: OwnLine, start: number, end: number, text: string): Quote | null {
    const lines = laidOut.lines.get(last.block);
    return lines === undefined ? null : quoting(last.block, lines, first.line, last.line, start, end, text);
}

/** Return the remark opened on the line at `position` of `drawer`: on a line of its own, a Markdown block's, as the agent's words in their conversation, or a file's, which records the file's version; none on any other line, nor on a blank one of a Markdown block's. */
function openedIn(laidOut: Laid, drawer: Drawer, position: number): Remark | undefined {
    const line = lineAt(drawer, position);
    const shown = line === undefined ? "" : laidOut.text.slice(line.from, line.to);
    if (line === undefined || (shown === "" && codeAt(drawer, line.from) === undefined)) {
        return undefined;
    }
    const quote = onLines(laidOut, line, line, 0, shown.length, said(laidOut.text, drawer, [line], line.from, line.to));
    return quote === null ? undefined : { id: "", to: drawer.conversation, quote, text: "", ...coded(drawer, [line]) };
}

/** Return what a remark on `lines` of `drawer` records of a file: its version and the lines quoted, for one on a file of "since you approved"; nothing on any other line. */
function coded(drawer: Drawer, lines: Line[]): Pick<Remark, "code"> {
    return drawer.kind === "since" ? { code: quotedCode(drawer, lines) } : {};
}

/**
 * Return the lines of a scope's own from `first` to `last`, those of the block `last` is of: a passage running over
 * blocks is anchored to its last, from the first of its lines the passage holds; and where the passage starts in them,
 * from `start` in the scope's own text.
 */
function ofLastBlock(scope: Scope, first: OwnLine, last: OwnLine, start: number): { first: OwnLine; start: number } {
    if (first.block === last.block) {
        return { first, start: start - first.own };
    }
    const from = scope.lines.find((each) => each.block === last.block && each.from >= first.from) ?? last;
    return { first: from, start: 0 };
}

/**
 * Return a comment on the passage `from` to `to` selects, counted in its item's text, its own and its files'; a
 * message to a group's agent where it's on its banner, which no comment quotes; a remark on a passage of a drawer's;
 * none where it isn't all inside one item's lines, one drawer's, or one group's. It's anchored to the block of the
 * line it ends on, what it says the whole passage.
 */
export function quoted(laidOut: Laid, from: number, to: number): Written | undefined {
    const group = groupAt(laidOut, from);
    if (group !== undefined) {
        return group === groupAt(laidOut, Math.max(to - 1, from)) ? letterTo(group) : undefined;
    }
    const drawer = drawerAt(laidOut, from);
    if (drawer !== undefined) {
        return quotedIn(laidOut, drawer, from, to);
    }
    const region = regionAt(laidOut, from);
    if (region === undefined || to <= from) {
        return undefined;
    }
    const first = lineAt(region, from);
    const last = lineAt(region, Math.max(to - 1, from));
    if (first === undefined || last === undefined) {
        return undefined;
    }
    const own = region.lines.map((each) => laidOut.text.slice(each.from, each.to)).join("\n");
    const offsets = passage(own, first, last, from, to);
    const lines = region.lines.slice(region.lines.indexOf(first), region.lines.indexOf(last) + 1);
    const text = lines.every((each) => codeAt(region, each.from) === undefined) ? offsets.text : said(laidOut.text, region, lines, from, to);
    const top = ofLastBlock(region, first, last, offsets.start);
    const quote = onLines(laidOut, top.first, last, top.start, offsets.end - top.first.own, text);
    return quote === null ? undefined : { id: "", item: region.item.number, quote, text: "" };
}

/** Return the remark on the passage `from` to `to` selects in `drawer`; none where it isn't all inside its lines. */
function quotedIn(laidOut: Laid, drawer: Drawer, from: number, to: number): Remark | undefined {
    if (drawer !== drawerAt(laidOut, Math.max(to - 1, from))) {
        return undefined;
    }
    const first = lineAt(drawer, from);
    const last = lineAt(drawer, Math.max(to - 1, from));
    if (first === undefined || last === undefined || to <= from) {
        return undefined;
    }
    const own = drawer.lines.map((each) => laidOut.text.slice(each.from, each.to)).join("\n");
    const offsets = passage(own, first, last, from, to);
    const lines = drawer.lines.slice(drawer.lines.indexOf(first), drawer.lines.indexOf(last) + 1);
    const top = ofLastBlock(drawer, first, last, offsets.start);
    const quote = onLines(laidOut, top.first, last, top.start, offsets.end - top.first.own, said(laidOut.text, drawer, lines, from, to));
    return quote === null ? undefined : { id: "", to: drawer.conversation, quote, text: "", ...coded(drawer, lines) };
}

/** Say an item's comments as one answer, as its agent reads them: each under the passage it quotes, set off as a mail quotes, in the order of what they're on, each block's by its lines; those on the whole after. */
export function answer(comments: Comment[]): string {
    const saying = comments.filter((each) => each.text.trim() !== "");
    const at = (each: Comment) => [each.quote?.block ?? "", each.quote?.line ?? 0, each.quote?.start ?? 0] as const;
    const quoted = saying
        .filter((each) => each.quote != null)
        .sort((a, b) => {
            const [blockA, lineA, startA] = at(a);
            const [blockB, lineB, startB] = at(b);
            return blockA < blockB ? -1 : blockA > blockB ? 1 : lineA - lineB || startA - startB;
        });
    const whole = saying.filter((each) => each.quote == null);
    const parts = quoted.map((each) => {
        const lines = (each.quote?.text ?? "").split("\n").map((line) => (line === "" ? ">" : `> ${line}`));
        return `${lines.join("\n")}\n\n${each.text.trim()}`;
    });
    return [...parts, ...whole.map((each) => each.text.trim())].join("\n\n");
}

/**
 * A citation of the operator's words in an agent's answer, where it's shown: its item's region; the citation as
 * written, and the id a resolved one shows of it; the fold of the passages cited on its line; and, for one that found
 * its passage, each stretch of the operator's words above the answer it marks.
 */
export interface Cited {
    region: Region;
    citation: Citation;
    written: Span;
    marker: Span;
    fold: Fold | null;
    passages: Span[];
}

/** Return each citation of the operator's words the agents' answers in `laidOut` hold, in the text's order (`Cited`). */
export function citationsOf(laidOut: Laid): Cited[] {
    return laidOut.regions.flatMap((region) =>
        (region.item.citations ?? []).map((citation): Cited => {
            const from = shownAt(region, citation.start);
            const found = citation.found;
            const passages =
                found == null
                    ? []
                    : region.said.flatMap((line) => {
                          const start = Math.max(line.from, line.from + found.start - line.own);
                          const end = Math.min(line.to, line.from + found.end - line.own);
                          return sameId(line.part, found.part) && end > start ? [{ from: start, to: end }] : [];
                      });
            const fold = region.folds.find((each) => each.name.startsWith("cited ") && from >= each.summary.from && from <= each.summary.to) ?? null;
            return {
                region,
                citation,
                written: { from, to: shownAt(region, citation.end) },
                marker: { from, to: shownAt(region, found == null ? citation.end : markerEnd(citation)) },
                fold,
                passages,
            };
        }),
    );
}

/**
 * Return where `gd` follows from `head`: from a citation that found its passage, to the passage among the operator's
 * words above the answer, where they're shown; from a passage they wrote that one cites, back to the citation; none
 * elsewhere.
 */
export function following(cited: Cited[], head: number): number | undefined {
    const on = (span: Span) => head >= span.from && head <= span.to;
    const from = cited.find((each) => on(each.written));
    if (from !== undefined) {
        return from.passages[0]?.from;
    }
    return cited.find((each) => each.passages.some(on))?.written.from;
}

/** Return where in the text an offset of a scope's own text is shown. */
export function shownAt(scope: Scope, offset: number): number {
    return shownIn(scope.lines, offset, scope.header.to);
}

/**
 * Return where what's written, shown at `block`, is about, which Ctrl+Enter ending it goes back to: a message's
 * banner; the last character of the passage a comment or a remark quotes, where reading carries on, as it's laid out
 * now (`quotedAt`), or its item's header for one on the item whole.
 */
export function aboutAt(laidOut: Laid, written: Written, block: Block): number | undefined {
    if (isLetter(written)) {
        return groupAt(laidOut, block.from)?.banner.from;
    }
    const scope = scopeAt(laidOut, block.from);
    if (scope === undefined) {
        return undefined;
    }
    const shown = quotedAt(laidOut, scope, written);
    if (shown !== null) {
        return Math.max(shown.to - 1, shown.from);
    }
    return isRegion(scope) ? scope.header.from : undefined;
}

/**
 * Return where the passage what's written quotes is in `scope`, as it's laid out now: from where it starts in the first
 * of its lines it's seated on (`Laid.seated`), to where it ends in the last, each kept within its line; none for a
 * message, what's on its item whole, one copies before kept on a reply, or one not seated in `scope`.
 */
export function quotedAt(laidOut: Laid, scope: Scope, written: Written): Span | null {
    // As it's laid out, anchored there where it was drafted before it was.
    const shown = laidOut.written.find((each) => writtenId(each) === writtenId(written)) ?? written;
    if (isLetter(shown) || shown.quote == null || ("on" in shown && shown.on != null)) {
        return null;
    }
    const quote = shown.quote;
    const seat = laidOut.seated.get(writtenId(shown));
    if (seat === undefined) {
        return null;
    }
    const first = scope.lines.find((each) => each.block === seat.block && each.line === seat.first);
    const last = scope.lines.find((each) => each.block === seat.block && each.line === seat.last);
    if (first === undefined || last === undefined) {
        return null;
    }
    const within = (line: OwnLine, at: number) => Math.min(Math.max(line.from + at, line.from), line.to);
    return { from: within(first, quote.start), to: within(last, seat.first === seat.last ? quote.end : endInLast(quote)) };
}

/** Return the items a draft answers: each with a comment that says something, marked done or declined, but the parked ones. */
export function covered(draft: Draft): number[] {
    const parked = draft.parked ?? [];
    const mentioned = [
        ...(draft.comments ?? []).filter((each) => each.text.trim() !== "").map((each) => each.item),
        ...(draft.done ?? []),
        ...(draft.declined ?? []),
    ];
    return [...new Set(mentioned)].filter((each) => !parked.includes(each)).sort((a, b) => a - b);
}

/** Return the messages a draft sends: those that say something. */
export function messages(draft: Draft): Letter[] {
    return saying(draft.letters ?? []);
}

/** Return the remarks a draft sends: those that say something. */
export function remarks(draft: Draft): Remark[] {
    return saying(draft.remarks ?? []);
}

/** Return `draft` as it's sent: without the comments, messages and remarks that say nothing, each without the trailing space Esc leaves in it. */
export function pruned(draft: Draft): Draft {
    const trimmed = <W extends Written>(list: W[]) => saying(list).map((each) => ({ ...each, text: each.text.trimEnd() }));
    return { ...draft, comments: trimmed(draft.comments ?? []), letters: trimmed(draft.letters ?? []), remarks: trimmed(draft.remarks ?? []) };
}
