// The review: everything waiting for the operator laid out as one text to read
// and move through, in groups, one per agent, every agent running having one,
// empty or not; each concern of theirs a block (`layConcern`); their comments in it, each under the line it's on, and
// their messages to each agent under the agent's banner, or on a concern under its block. A tree (`laid`, `Laid.nodes`): the
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
    type OfAgent,
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
/**
 * The operator's message: to a conversation, under their agent's banner; or on a thread, to whoever answers for it as
 * they write, or to no one (`to` none), on the thread whole or on lines of its body (`quote`). Never on an item, which a
 * comment is; told from a remark by its thread, which a remark never has (`isRemark`).
 */
export type Letter = components["schemas"]["Letter"] & { item?: never };
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
export type Destination = components["schemas"]["Destination"];
export type Destined = components["schemas"]["Destined"];
export type ThreadsRead = components["schemas"]["ThreadsRead"];
export type Passage = ThreadRead["passages"] extends (infer P)[] | undefined ? P : never;

/**
 * The review's concerns, as the host reads them (`docs/inbox.md`, *Threads in the review*): each and what asks; and how
 * many files a landing waits on in each, read from the landings waiting by the concern their lander works in.
 */
export interface Threading {
    read: ThreadsRead;
    landing: ReadonlyMap<number, number>;
}


/** Return `text` cut at a word to `most` characters at most, `…` where it's cut. */
export function cutAt(text: string, most: number): string {
    if (text.length <= most) {
        return text;
    }
    const cut = text.lastIndexOf(" ", most - 1);
    return `${text.slice(0, cut > 0 ? cut : most - 1).trimEnd()}…`;
}

/**
 * A concern laid out as a block (`laid`): in its holder's own buffer, its party's, what's for the operator where it wants
 * their eyes, or what's settled. From its first line to its last, the messages written on it among them; its header, the
 * line a verb on it reaches it from; the concern as the host reads it; what's written on it; its body's lines, which a
 * message may quote, each of the body's block (`bodyBlock`), from where its words start after it's set in; or, `dim`, one
 * line, context above one nested under it held elsewhere, whose own block is where it's held.
 */
export interface ConcernBlock extends Span {
    read: ThreadRead;
    header: Span;
    dim: boolean;
    blocks: Block[];
    lines: OwnLine[];
    /** Its fold whole, under its header; none where nothing's under it, or it's dim. */
    fold: Fold | null;
    /** Where its header names who holds it, or who left it, which `gd` follows to their buffer; none where nobody did. */
    holder: (Span & { conversation: Conversation }) | null;
    /** Each passage of the operator's it came from, where its line is, which Enter goes to what it was on from. */
    passages: (Span & { passage: Passage })[];
    /** Each item that landed there and asks the operator or is new, where its line is, which Enter goes to the item from. */
    items: (Span & { number: number })[];
}

/** A concern's block laid out and open for what's nested under it (`layConcerns`): it, its part, and whether its fold is closed, and laid out closed, what it holds standing in one line. */
interface Opened {
    block: ConcernBlock;
    node: Placed;
    closed: boolean;
    unlaid: boolean;
}

/** Return the id of concern `number`'s body as a block a message quotes lines of (`Quote.block`): kept across its rewrites, each a version of it, its `at`. */
export function bodyBlock(number: number): string {
    return `concern ${number} body`;
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
    /**
     * Whether it's closed and what it holds isn't laid out, one line standing in its place, laid out as it opens
     * (`Arranging.folds`, `Laid.deferred`): its placeholder counts no lines.
     */
    unlaid?: boolean;
}

/** Where a changed file is under its item or in its drawer: from its header to its last line and the comments under it. */
export interface FileSpan extends Span {
    file: Filed;
}

/** What names an agent's group in its banner: its first item, or, for a group with none, the agent's conversation. */
export type Head = { item: Item } | { conversation: Conversation };

/**
 * One group, where it's shown: its banner and the messages to its agent under it, each a comment's block; its items'
 * regions follow it, then its drawers, up to the next group.
 */
export interface Group {
    /** The agent it's of; none for lup's approvals, which no message goes to. */
    conversation: Conversation | null;
    /** The parts of its banner, each a view of its agent's, where they're running. */
    parts: Mounted[];
    /** What its banner names it by. */
    head: Head;
    /** What names its place across layouts: whose it is. */
    place: string;
    banner: Span;
    blocks: Block[];
    drawers: Drawer[];
    /** How many groups it's laid out under, a subagent's under their parent's, where they're nested (`Arranging.parents`); 0 else. */
    depth: number;
    /** Its fold whole, under its banner; none where nothing's under its banner. */
    fold: Fold | null;
    /** Where its last line ends, its fold's end, or its banner's where nothing's under it. */
    end: number;
    /** The line at the end of its own buffer the messages to its agent are written under (`Showing`), so they're under what's live; none where they're under its banner. */
    writing?: Span;
}

/**
 * What the second pane shows, one buffer at a time, where the page lays the review out in panes, as it opens
 * (`panes.ts`): what's for the operator, across everyone; one agent's own buffer, by `whose` they are, their items and
 * their conversation, live, what the operator writes at its end reaching them; a party's, as every agent no longer
 * running; each concern the operator cleared; or a module's own view. Each is a subset of the review's tree, laid out by
 * the one layout.
 */
export type Showing = { kind: "for you" } | { kind: "agent"; key: string } | { kind: "party"; name: string } | { kind: "settled" } | { kind: "view"; repository: string; module: string; view: string; called: string };

/** Return who a module's view placed under its repository is laid out as of: no agent, so nothing it shows is anyone's unless a block says whose (`Line.by`). */
export function ofNobody(repository: string): Conversation {
    return { party: "conversation", repository, runtime: "", session: "" };
}

/** Return whether `conversation` is who a view placed under its repository is laid out as of (`ofNobody`). */
export function isNobody(conversation: Conversation): boolean {
    return conversation.session === "";
}

/**
 * A party beside the agents, a place for what no agent running answers in a repository (#113): listed flat and laid out
 * the same, whichever it is, by what it says of itself. `No agent` is one, a repository's each (`noAgent`). What's in it
 * is what the host says of each thing, whose words are here until a party is a node of the ledger.
 */
export interface Party {
    /** What names it among the others, by which its buffer's asked for. */
    name: string;
    /** The repository it's of. */
    repository: string;
    /** What it's called on its row and over its buffer. */
    called: string;
    /** What the line of keys says it is. */
    says: string;
    /** What its buffer says, over it, of whom the operator's words reach from there. */
    whom: string;
    /** Whether what the agent of this group left sits in it, each of their items a row of its own, by who's running. */
    holds: (group: Pick<Grouping, "key" | "conversation">, running: ReadonlyMap<string, unknown>) => boolean;
    /** Whether this task, a thread still open, sits in it, by who's running; each listed under the first holding it. */
    holdsTask: (read: ThreadRead, running: ReadonlyMap<string, unknown>) => boolean;
}

/**
 * Return the party of what nobody running answers in `repository`, `No agent`: each concern of it nobody running answers
 * for, as the host says, its piles among them, as nobody holds them; and what each agent of it who's ended left.
 */
export function noAgent(repository: string): Party {
    return {
        name: `no agent ${repository}`,
        repository,
        called: "No agent",
        says: `No agent in ${repositoryCalled(repository)}: what nobody running answers`,
        whom: "nobody's running: an agent's main session reads what you write when it next runs",
        holds: (group, running) => group.conversation !== null && group.conversation.repository === repository && !running.has(group.key),
        holdsTask: (read, running) => {
            const owner = taskOwner(read);
            return read.thread.repository === repository && (owner === null || !running.has(whose(owner)));
        },
    };
}

/** Return the parties a buffer may show and the list lists: `No agent` of each of `repositories`, once each, in their order. */
export function partiesOf(repositories: Iterable<string>): Party[] {
    return [...new Set(repositories)].map(noAgent);
}

/** Return what a repository's called on the page: the last part of its path, without its `.git`. */
export function repositoryCalled(path: string): string {
    const name = path.split("/").filter((each) => each !== "").at(-1) ?? path;
    return name.endsWith(".git") ? name.slice(0, -".git".length) : name;
}

/**
 * Return who owns a thread, as a task: whoever answers for it, as the host reads it, its holder where they go on, else the
 * nearest holder above; none where nobody does, which puts it in `No agent`.
 */
export function taskOwner(read: ThreadRead): Conversation | null {
    return read.answering ?? null;
}

/** Return whose group what asks the operator in a thread is laid out under: whoever answers for it; else who left it, as the host says, whose group `No agent`'s buffer lays out; none where nobody did. */
export function keptUnder(read: ThreadRead): Conversation | null {
    return taskOwner(read) ?? read.left_by ?? null;
}

/**
 * Return what a concern's row and its block say it is: its title; or, where its title is no real one but reads as a
 * name, what the host says it's about (`ThreadRead.about`), in quotes, words from what's in it rather than a title, so
 * neither reads as an agent's name.
 */
export function concernWords(read: ThreadRead): string {
    const about = read.about ?? null;
    return about === null ? read.thread.title : `“${about}”`;
}

/** Return how a concern reads on the dashboard, by its two marks, as the host says (`ThreadRead.reads`): open, for the operator's eyes, quiet or gone. */
export function concernReads(read: ThreadRead): NonNullable<ThreadRead["reads"]> {
    return read.reads ?? "open";
}

/**
 * Return the concerns of `all` the buffer `showing` lays out as blocks: in an agent's own, each they answer for that isn't
 * gone; in what's for the operator, each for their eyes, said done and not cleared, or holding an item moved there that
 * asks them, as `asking` says; in a party's, each it holds that isn't gone; in what's settled, each the operator cleared;
 * none elsewhere, or that the host says is nothing to list.
 */
export function concernsIn(all: readonly ThreadRead[], showing: Showing | null, party: Party | undefined, running: ReadonlyMap<string, unknown>, asking: (read: ThreadRead) => boolean = () => false): ThreadRead[] {
    const listed = (read: ThreadRead) => read.bare !== true && concernReads(read) !== "gone";
    switch (showing?.kind) {
        case "agent":
            return all.filter((each) => {
                const owner = taskOwner(each);
                return listed(each) && owner !== null && whose(owner) === showing.key;
            });
        case "for you":
            return all.filter((each) => each.bare !== true && (concernReads(each) === "for your eyes" || (listed(each) && asking(each))));
        case "party":
            return party === undefined ? [] : all.filter((each) => listed(each) && party.holdsTask(each, running));
        case "settled":
            return all.filter((each) => (each.cleared ?? null) !== null);
        default:
            return [];
    }
}

/**
 * Return the buffer a concern's block is in, where its row and `gt` go: what's settled, where it's gone; else its holder's
 * own, or whoever answers for it above them; else the party holding it, `No agent` where nobody running answers for it.
 */
export function concernHome(read: ThreadRead, running: ReadonlyMap<string, unknown>): Showing {
    if (concernReads(read) === "gone") {
        return { kind: "settled" };
    }
    const owner = taskOwner(read);
    if (owner !== null && running.has(whose(owner))) {
        return { kind: "agent", key: whose(owner) };
    }
    return { kind: "party", name: noAgent(read.thread.repository).name };
}

/**
 * Say a concern's two marks, in a few words: the agent's, `done` where they said it is, else where it stands; then the
 * operator's, `for you to clear` where it's done and they haven't, `cleared` or `declined` where they have.
 */
export function concernSaid(read: ThreadRead): string {
    const cleared = read.cleared ?? null;
    const done = (read.done ?? null) !== null;
    const agent = done ? "done" : cleared !== null ? "open" : read.state === "waiting on the operator" ? "working" : read.state;
    if (cleared !== null) {
        return `${agent}, ${cleared.kind === "ledger:declined" ? "declined" : "cleared"}`;
    }
    return done ? `${agent}, for you to clear` : agent;
}

/** A concern where a nest lays it out: as one of its own, or, `dim`, as context above one of its own nested under it, and how deep. */
export interface Nested {
    read: ThreadRead;
    depth: number;
    dim: boolean;
}

/**
 * Return `solid`, the concerns a nest shows as its own, each under its parent there, in the order each was opened, with
 * how deep it's set in; and, above each whose parent isn't among them, as where it's nested under one someone else holds,
 * or one gone, each of its ancestors up to one among them, dim, as context, once however many it's above. `all` is every
 * concern the host reads, which the ancestors are found among.
 */
export function concernsNested(solid: readonly ThreadRead[], all: readonly ThreadRead[]): Nested[] {
    const byNumber = new Map(all.map((each) => [each.thread.number, each]));
    const own = new Set(solid.map((each) => each.thread.number));
    const shown = new Map(solid.map((each) => [each.thread.number, each]));
    for (const each of solid) {
        let parent = each.thread.parent ?? null;
        while (parent !== null && !shown.has(parent)) {
            const above = byNumber.get(parent);
            if (above === undefined) {
                break;
            }
            shown.set(parent, above);
            parent = above.thread.parent ?? null;
        }
    }
    const under = new Map<number | null, ThreadRead[]>();
    // `Later` last among those at the top, as what's not for now.
    const last = (read: ThreadRead) => ((read.thread.parent ?? null) === null && read.thread.title === LATER ? 1 : 0);
    for (const each of [...shown.values()].toSorted((a, b) => last(a) - last(b) || a.thread.number - b.thread.number)) {
        const parent = each.thread.parent ?? null;
        const at = parent !== null && shown.has(parent) ? parent : null;
        under.set(at, [...(under.get(at) ?? []), each]);
    }
    const walk = (read: ThreadRead, depth: number): Nested[] => [
        { read, depth, dim: !own.has(read.thread.number) },
        ...(under.get(read.thread.number) ?? []).flatMap((child) => walk(child, depth + 1)),
    ];
    return (under.get(null) ?? []).flatMap((each) => walk(each, 0));
}

/** What a comment is followed from as the review is laid out anew (`placed`, `anchors.ts`): where each comment was last seated on its block, and that block's lines then. */
export type Followed = Pick<Laid, "seated" | "lines">;

/**
 * Return what each comment is followed from once `now` is laid out, where a layout holds a subset of the review (`Showing`):
 * each one's seat and its block's lines as `now` holds them, else as `was` did, so a comment whose block another buffer
 * was on screen for is followed through what its block did meanwhile, as it would be had it stayed on screen. A seat on
 * a block `now` doesn't lay out says nothing of where it is.
 */
export function followedFrom(was: Followed | null, now: Laid): Followed {
    const seated = new Map(was?.seated ?? []);
    for (const [id, seat] of now.seated) {
        if (now.lines.has(seat.block) || !seated.has(id)) {
            seated.set(id, seat);
        }
    }
    const lines = new Map<string, Lines>();
    for (const seat of seated.values()) {
        const held = now.lines.get(seat.block) ?? was?.lines.get(seat.block);
        if (held !== undefined) {
            lines.set(seat.block, held);
        }
    }
    return { seated, lines };
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
    previous?: Followed | null;
    /** The one buffer to lay out of the review, where it's laid out in panes; none lays it out whole. */
    showing?: Showing | null;
    /** Whether what the review is laid out from is all read, so a buffer with nothing in it holds nothing; unsaid, it is. */
    read?: boolean;
    /** What a buffer with nothing in it says until it's read. */
    unread?: string;
    /** Every concern, as the host reads it (`inbox-threads`), each laid out as a block where its buffer holds it, in panes; none else. */
    concerns?: readonly ThreadRead[];
    /** The parties a buffer may show; unsaid, `No agent` of each repository a concern or an item is of (`partiesOf`). */
    parties?: readonly Party[];
    /**
     * How the operator left each fold they opened or closed, by its key (`foldKey`), whether it's closed: given, a
     * drawer, an item's context and each fold of a drawer's view read from another of its views that's closed lays out
     * its summary line and one line standing for what it holds, rather than what it holds, which is laid out as it
     * opens (`Laid.deferred`), so the buffer holds what's open whatever's folded; but where it holds what the operator
     * wrote, which is always laid out. Unsaid, everything is laid out, folded or not.
     */
    folds?: ReadonlyMap<string, boolean> | null;
}

/** The line standing for what a closed fold holds, where it isn't laid out until it opens (`Fold.unlaid`): seen only for the moment it opens. */
export const UNLAID = "opening…";

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
    /** Who wrote each of its Markdown blocks, by the block's id, where that's another agent than its own (`Markdown.by`): whom a remark on it goes to. */
    writers: ReadonlyMap<string, Conversation>;
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
    kind: "group" | "banner" | "item" | "header" | "frame" | "view" | "block" | "written";
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
    /** The lines of a concern's block and of the buffer's own that are no item's nor drawer's: the operator's words moved in, what's to try, a line saying there's nothing here. */
    asides: Aside[];
    /** Each concern laid out, in the text's order, as a block or dim as context. */
    concerns: ConcernBlock[];
    /**
     * Each fold that lays out what it holds only while it's open (`Arranging.folds`), by its key, and whether it's
     * closed now, its summary line alone laid out (`Fold.unlaid`): what opening or closing it lays out anew. Empty where
     * everything's laid out.
     */
    deferred: ReadonlyMap<string, boolean>;
    /** The items in a pile, set aside there, which count as waiting nowhere (`piledIn`). */
    piled: ReadonlySet<number>;
    /** Each line an item moved into a concern leaves in its agent's group, dim, with the concern it went to, which `gt` goes to. */
    away: Away[];
}

/** The dim line an item moved into a concern leaves where it was, in its agent's group: the item, and the concern it went to. */
export interface Away extends Span {
    item: Item;
    into: ThreadRead;
}

export const EMPTY: Draft = { comments: [], letters: [], remarks: [], done: [], declined: [], marks: [], moves: [] };

/** The title of the pile things are left for later in, one at the top of each repository (`LATER_PILE`, `lup_dev.inbox.store`). */
export const LATER = "Later";

/** No item in a pile: what a count told of none counts as set aside there. */
export const NONE_PILED: ReadonlySet<number> = new Set();

/** Return each item the draft sends into a concern or a pile with Space s, by number, with where it goes. */
export function itemsSent(draft: Draft): Map<number, Destination> {
    return new Map((draft.moves ?? []).flatMap((each) => (each.item == null ? [] : [[each.item, each.to] as const])));
}

/** Return each concern the draft sends somewhere with Space s, by number, with where it goes. */
export function concernsSent(draft: Draft): Map<number, Destination> {
    return new Map((draft.moves ?? []).flatMap((each) => (each.thread == null ? [] : [[each.thread, each.to] as const])));
}

/**
 * Return the items `draft` marks: done, declined, or sent into a concern or a pile, which count as waiting no more until
 * the reply is sent, as the operator said what's to become of them.
 */
export function marked(draft: Draft): Set<number> {
    return new Set([...(draft.done ?? []), ...(draft.declined ?? []), ...itemsSent(draft).keys()]);
}

/**
 * Return the items the operator moved into a pile, a concern nobody answers for (`ThreadRead.moved`): they count as
 * waiting nowhere, being set aside there, until the pile is someone's or they're sent on.
 */
export function piledIn(concerns: readonly ThreadRead[]): Set<number> {
    return new Set(concerns.filter((each) => (each.answering ?? null) === null && (each.cleared ?? null) === null).flatMap((each) => each.moved ?? []));
}

/** Return each item moved into a concern (`ThreadRead.moved`), by number, with the concern, which lays it out in its block rather than in its agent's group. */
export function movedInto(concerns: readonly ThreadRead[]): Map<number, ThreadRead> {
    return new Map(concerns.flatMap((read) => (read.moved ?? []).map((number) => [number, read] as const)));
}

/** Return the concern laid out at `position`, as a block, from its header to its last line; none on a line of one dim as context, or elsewhere. */
export function concernAt(laidOut: Laid, position: number): ConcernBlock | undefined {
    return laidOut.concerns.findLast((each) => !each.dim && position >= each.from && position <= each.to);
}

/** Return the concern a line at `position` names, one laid out there as a block, or the one a line of a block names, dim as context or nested under it, which `gt` goes to: the innermost; none elsewhere. */
export function concernNamedAt(laidOut: Laid, position: number): ConcernBlock | undefined {
    return laidOut.concerns.find((each) => each.dim && position >= each.from && position <= each.to) ?? concernAt(laidOut, position);
}

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

/**
 * Return `left`, what a send left of the draft, with what was done to the draft while it was being sent: `before` as it
 * began, `during` as it last stood. So whatever's written or marked meanwhile survives the send's end, which keeps `left`:
 * each thing written whose words aren't what they were, and each mark or item marked that wasn't; what `before` held and
 * the send took is gone from `left`, and stays gone.
 */
export function withWrittenDuring(before: Draft, during: Draft, left: Draft): Draft {
    const was = new Map(written(before).map((each) => [writtenId(each), each.text]));
    const fresh = written(during).filter((each) => was.get(writtenId(each)) !== each.text);
    const replaced = new Set(fresh.map(writtenId));
    const marksWere = new Set((before.marks ?? []).map((each) => each.id));
    const listed = (list: "done" | "declined") => {
        const wasThere = new Set(before[list] ?? []);
        return [...new Set([...(left[list] ?? []), ...(during[list] ?? []).filter((each) => !wasThere.has(each))])];
    };
    const movesWere = new Set((before.moves ?? []).map((each) => each.id));
    return {
        ...withWritten(left, [...written(left).filter((each) => !replaced.has(writtenId(each))), ...fresh]),
        done: listed("done"),
        declined: listed("declined"),
        marks: [...(left.marks ?? []), ...(during.marks ?? []).filter((each) => !marksWere.has(each.id))],
        moves: [...(left.moves ?? []), ...(during.moves ?? []).filter((each) => !movesWere.has(each.id))],
    };
}

/** Return whether what's written is a message, to an agent or on a thread, lines of its body quoted or not, rather than a comment on an item or a remark in a drawer. */
export function isLetter(each: Written): each is Letter {
    return !("item" in each) && !isRemark(each);
}

/**
 * Return the agent whose drawer `remark` is on, which their group is laid out for: the one its block's view is of, as the
 * block's id names it (`instanceOf`, `blockId`), who's another than whom it goes to where it's on what another agent
 * wrote; else, on no such block, as one drafted before quotes named theirs, or on a view of no agent, as a module's own
 * buffer, whom it goes to.
 */
export function holderOf(remark: Remark): Conversation {
    const block = remark.quote.block ?? "";
    const end = block.indexOf("}] ");
    if (end < 0) {
        return remark.to;
    }
    const [repository, , , argument] = JSON.parse(block.slice(0, end + 2)) as [string, string, string, Partial<OfAgent>];
    return argument.runtime === undefined || argument.session === undefined ? remark.to : conversationOf(repository, { runtime: argument.runtime, session: argument.session, agent: argument.agent ?? null });
}

/**
 * Return whether what's written is a remark in one of an agent's drawers: it quotes what it's on, and is on no thread,
 * which tells it from a message on lines of a thread's body. A message the host keeps says its quote and its thread,
 * none, whether or not it has any.
 */
export function isRemark(each: Written): each is Remark {
    return !("item" in each) && each.quote != null && !("thread" in each && each.thread != null);
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

/**
 * How an agent's group is laid out: whole, each drawer under its banner, then
 * its items, what's written to them under the banner; `gone`, the same of an agent no longer running, whose drawers are
 * read only as their buffer's opened; or as their `own` buffer, their conversation live after their items, what's
 * written to them after it.
 */
type GroupShape = "whole" | "gone" | "own";

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

/** Say what kind of item it is, as a word: a message by its own kind, or as a turn's end. */
export function itemKind(item: Item): string {
    const reason = item.reason;
    return reason.reason === "message" ? (reason.ending ? "turn ended" : reason.kind) : reason.reason;
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
export function grouped(items: Item[], banner: (item: Item) => string): Grouping[] {
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

/** Return what names a group's place across layouts: `key`, whose it is, after `now`, as the host keeps every place (`Order`). */
function placeOf(key: string): string {
    return `now ${key}`;
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

/** Say whether an item is new to the operator: they haven't seen its group since it came, nor commented on it in a reply they sent. */
export function fresh(item: Item, seeing: Seeing): boolean {
    if (seeing.commented.has(item.number)) {
        return false;
    }
    const seen = item.sender.party === "conversation" ? seeing.groups.get(whose(item.sender)) : undefined;
    return seen === undefined || item.number > seen;
}

/**
 * Say whether an item is only to read: new to the operator, still waiting and left as it is in the draft, asking them
 * nothing (`Item.asks`, the host's), and in no pile (`piledIn`). Being seen takes it out of this, though it stays where
 * it is until Space d marks it read; what asks them never is, and is counted apart (`toAnswer`).
 */
export function toRead(item: Item, draft: Draft, seeing: Seeing, piled: ReadonlySet<number>): boolean {
    return !item.asks && news(item) && waits(item) && !marked(draft).has(item.number) && !piled.has(item.number) && fresh(item, seeing);
}

/** Return how many of `items` are only to read, what the top bar and the header over the review say apart from what asks the operator (`toRead`). */
export function countToRead(items: readonly Item[], draft: Draft, seeing: Seeing, piled: ReadonlySet<number>): number {
    return items.filter((each) => toRead(each, draft, seeing, piled)).length;
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
    // A room's hook can name another session as its own, so the host's tree can loop: each key is passed once.
    const forebear = (key: string): string | undefined => {
        const passed = new Set([key]);
        let at = parents.get(key);
        while (at !== undefined && !keys.has(at)) {
            if (passed.has(at)) {
                return undefined;
            }
            passed.add(at);
            at = parents.get(at);
        }
        return at === key ? undefined : at;
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
    const laid = new Set<string>();
    const walk = (group: Grouping, depth: number) => {
        if (laid.has(group.key)) {
            return;
        }
        laid.add(group.key);
        out.push({ group, depth });
        for (const child of under.get(group.key) ?? []) {
            walk(child, depth + 1);
        }
    };
    roots.forEach((each) => walk(each, 0));
    // Those on a loop have no root above them: each is laid at the top, where it would be with no parent.
    groups.forEach((each) => walk(each, 0));
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
    banner: (head: Head, parts: string) => string,
    header: (item: Item, said: string) => string,
    draft: Draft,
    around: Around,
    places: readonly string[] = [],
    drawers: Drawers = new Map(),
    name: (party: Conversation) => string = (party) => party.agent ?? party.session,
    arranging: Arranging = {},
): Laid {
    // Marked done or declined, or sent somewhere, an item folds; and a block marked done, as a file marked reviewed
    // (`grammar.ts`).
    const settling = marked(draft);
    const markedDone = new Set((draft.marks ?? []).filter((each) => each.verb === "done").map((each) => each.block));
    // The folds a mark folds, which start so whatever their kind says.
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
    // Each item the views read by its number, as they stand.
    const shown: Shown = {
        items: new Map(items.map((each) => [each.number, each])),
        beyond: { contexts: around.contexts, files: around.files },
        drawers,
        running: arranging.running ?? new Map(),
        landings: arranging.landings ?? [],
        called: name,
    };
    // Every concern the host reads; each item moved into one, which its block lays out rather than its agent's group,
    // where a dim line stands in its place; and those in a pile, which count as waiting nowhere.
    const allConcerns = arranging.concerns ?? [];
    const moved = movedInto(allConcerns);
    const piled = piledIn(allConcerns);
    const aways: Away[] = [];
    const now = grouped(items, (item) => banner({ item }, ""));
    const empty = emptyGroups([...agents, ...letters.flatMap((each) => (each.to == null ? [] : [each.to])), ...remarks.map(holderOf)], now);
    // What of a group is laid out there: its items but those moved into a concern.
    const present = (group: Grouping) => group.items.filter((each) => !moved.has(each.number));
    const w = new Writer();
    const groups: Group[] = [];
    const regions: Region[] = [];
    const laidDrawers: Drawer[] = [];
    const nodes: Placed[] = [];
    const asides: Aside[] = [];
    // The lines a group's fold never reaches past; and the groups whose conversation isn't read yet.
    const breaks: number[] = [];
    const unreadGroups = new Set<string>();
    const showing = arranging.showing ?? null;
    // How the operator left the folds, where what a closed one holds waits until it opens; and each fold laid out so,
    // whether it's closed now.
    const foldsLeft = arranging.folds ?? null;
    const deferred = new Map<string, boolean>();
    /**
     * Return whether `fold`, laid out closed as `laidClosed` says, is closed as the operator left it, where what it
     * holds waits until it opens, and note it among those that do; false where everything's laid out. Its kind says how
     * every one of it starts, as the review's last pass has it (`FoldKind.starts_open`), but where a mark or what's live
     * says (`marked`).
     */
    const deferring = (fold: Pick<Fold, "of" | "kind" | "name">, laidClosed: boolean, marked: boolean): boolean => {
        if (foldsLeft === null) {
            return false;
        }
        const starts = marked ? null : (kindOf(fold.kind)?.startsOpen ?? null);
        const key = foldKey(fold);
        const closed = foldsLeft.get(key) ?? (starts === null ? laidClosed : !starts);
        deferred.set(key, closed);
        return closed;
    };
    // Whether what the review is laid out from is read yet: until then, a buffer's empty for that alone.
    const readYet = arranging.read ?? true;
    // Of the concerns, those the buffer on screen lays out as blocks (`concernsIn`), each under its owner's group, by
    // `whose` they are, with a group for each owner who has none; and those no one owns, after them.
    const concernsOf = new Map<string, ThreadRead[]>();
    const concernOwners: Conversation[] = [];
    const unowned: ThreadRead[] = [];
    const parties = arranging.parties ?? partiesOf([...allConcerns.map((each) => each.thread.repository), ...items.flatMap((each) => (each.sender.party === "conversation" ? [each.sender.repository] : []))]);
    const party = showing?.kind === "party" ? parties.find((each) => each.name === showing.name) : undefined;
    // A concern holding an item moved there that asks the operator wants their eyes, as one done does, where someone
    // answers for it: one in a pile is set aside.
    const asking = (read: ThreadRead) => (read.answering ?? null) !== null && (read.moved ?? []).some((number) => shown.items.get(number)?.asks === true && !settling.has(number));
    for (const each of concernsIn(allConcerns, showing, party, arranging.running ?? new Map(), asking)) {
        // A party's concerns are its own, nobody's, at its top; the rest under whoever answers for each, or who left it.
        const owner = showing?.kind === "agent" ? taskOwner(each) : showing?.kind === "settled" || showing?.kind === "party" ? null : keptUnder(each);
        if (owner === null) {
            unowned.push(each);
        } else {
            concernsOf.set(whose(owner), [...(concernsOf.get(whose(owner)) ?? []), each]);
            concernOwners.push(owner);
        }
    }
    const concernLines: ConcernBlock[] = [];
    empty.push(...emptyGroups(concernOwners, [...now, ...empty]));
    if (showing?.kind === "agent") {
        // One agent's own buffer: their group, what's live and what's written to them last.
        for (const group of [...now, ...empty].filter((each) => each.key === showing.key)) {
            layGroup(group, 0, "own");
        }
    } else if (showing?.kind === "party") {
        // Each concern the party holds, nobody holding it, its piles among them, `Later` last; then what each agent of it
        // who's ended left, under their banner, under a line saying so.
        layConcerns(unowned, nodes, "nobody");
        const inIt = (group: Grouping) => party?.holds(group, shown.running) === true && (present(group).length > 0 || sinceWaits(group) !== null);
        const left = kept([...now, ...empty].filter(inIt));
        if (left.length > 0) {
            breaks.push(layNote("── what agents who've ended left ──", "left by agents").from);
            for (const { group, depth } of nested(left, arranging.parents ?? null)) {
                layGroup(group, depth, "gone");
            }
        }
    } else if (showing?.kind === "settled") {
        // Each concern the operator cleared, as a block, read here alone where it's gone from everywhere else.
        layConcerns(unowned, nodes, "settled");
    } else if (showing?.kind === "view") {
        // A module's own buffer: its view, open, nobody's but as each of its blocks says.
        const view = mount(showing.repository, showing.module, showing.view, {}, shown, remote);
        const drawer = layDrawer(showing.view, ofNobody(showing.repository), view, "", true);
        if (drawer !== null) {
            laidDrawers.push(drawer);
            nodes.push(drawer.node);
        }
    } else if (showing?.kind === "for you") {
        // What's for the operator: each group with an item, or something it holds waits on them, or written to under its
        // banner; each with its drawers, a line each until opened.
        const holds = (group: Grouping) => present(group).length > 0 || concernsOf.has(group.key) || letters.some((each) => each.to != null && whose(each.to) === group.key) || sinceWaits(group) !== null;
        const holding = [...now, ...empty].filter(holds);
        for (const { group, depth } of nested(kept(holding), arranging.parents ?? null)) {
            layGroup(group, depth);
        }
        // Never empty while anyone's at work: each agent running with nothing for the operator, with their drawers.
        const quiet = kept([...now, ...empty].filter((each) => !holding.includes(each) && shown.running.has(each.key)));
        if (holding.length === 0 && readYet) {
            layNote(quiet.length === 0 ? "Nothing waits on you, and nobody's running." : "Nothing waits on you.", "nothing waits");
        }
        if (quiet.length > 0) {
            const line = layNote(`── also running · ${quiet.length} · gd on a name goes to them ──`, "also running");
            breaks.push(line.from);
            for (const { group, depth } of nested(quiet, arranging.parents ?? null)) {
                layGroup(group, depth);
            }
        }
    } else {
        for (const { group, depth } of nested(kept([...now, ...empty]), arranging.parents ?? null)) {
            layGroup(group, depth);
        }
    }
    // A buffer with nothing in it says so, or that it's being read: the second pane never just looks empty.
    if (showing !== null && w.at === 0) {
        layNote(readYet ? "Nothing here now: the list beside this says what there is." : (arranging.unread ?? "Reading what's there…"), "nothing here");
    }
    // Each group folds whole under its banner, up to the next as deep or shallower, a subagent's inside their parent's,
    // and never past a line of the buffer's own that it holds none of.
    {
        groups.forEach((group, at) => {
            const next = groups.findIndex((each, after) => after > at && each.depth <= group.depth);
            const end = Math.min(next < 0 ? w.at : (groups[next]?.banner.from ?? w.at), breaks.find((each) => each > group.banner.from) ?? w.at) - 1;
            const id = `group ${group.place}`;
            if (end > group.banner.to) {
                const label = w.lineFrom(group.banner.from);
                group.fold = { of: id, kind: "group", name: "", label, closed: false, summary: group.banner, from: group.banner.to, to: end, scope: true, ...(unreadGroups.has(id) ? { unread: true } : {}) };
            }
            group.end = Math.max(end, group.banner.to);
            const node = nodes.find((each) => each.id === id);
            if (node !== undefined) {
                node.to = group.end;
            }
        });
    }
    // Each fold starts as its kind says where it says (`Kind.startsOpen`, a person's layer's), else as its view laid it
    // out; one a mark folded stays folded.
    for (const fold of [...regions, ...laidDrawers].flatMap((each) => each.folds).concat(groups.flatMap((each) => (each.fold === null ? [] : [each.fold])), concernLines.flatMap((each) => (each.fold == null ? [] : [each.fold])))) {
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
        asides,
        concerns: concernLines,
        deferred,
        piled,
        away: aways,
    };

    /** Lay a line of the buffer's own, no part's but its own: what's said where there's nothing else to read. */
    function layNote(said: string, id: string): Span {
        const line = w.line(said, id);
        asides.push({ kind: "buffer-note", ...line });
        nodes.push(part(id, "frame", line.from, line.to));
        return line;
    }

    /** Return `groups` with each laid out before in its place, any other after them, in its own order. */
    function kept(groups: Grouping[]): Grouping[] {
        const rank = (group: Grouping) => {
            const at = places.indexOf(placeOf(group.key));
            return at < 0 ? places.length : at;
        };
        return [...groups].sort((a, b) => rank(a) - rank(b));
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

    /**
     * Lay `solid`, the concerns this buffer holds as its own under one group or none, into `within`, each a block
     * (`layConcern`), under its parent where that's one of them, inside its parent's fold, else under what it's nested
     * in, dim, as context (`concernsNested`); `at` names where they're laid out, which a dim line is named by, as one may
     * be above several. Each block's fold reaches the last line of what's nested under it.
     */
    function layConcerns(solid: readonly ThreadRead[], within: Placed[], at: string): void {
        const here = new Set(solid.map((each) => each.thread.number));
        const open: { depth: number; laid: Opened }[] = [];
        const close = (depth: number) => {
            for (let top = open.at(-1); top !== undefined && top.depth >= depth; top = open.at(-1)) {
                open.pop();
                closeConcern(top.laid);
            }
        };
        for (const entry of concernsNested(solid, allConcerns)) {
            close(entry.depth);
            const laidHere = layConcern(entry, open.at(-1)?.laid.node.children ?? within, at, here);
            if (laidHere !== null) {
                open.push({ depth: entry.depth, laid: laidHere });
            }
        }
        close(0);
    }

    /** End `laid`, a concern's block, at the text's end now: it, its part and its fold reach there, what's nested under it among it. */
    function closeConcern(laid: Opened): void {
        const end = Math.max(w.at - 1, laid.block.header.to);
        laid.block.to = end;
        laid.node.to = end;
        if (end > laid.block.header.to) {
            const fold: Fold = { of: laid.node.id, kind: "concern", name: "", label: w.lineFrom(laid.block.header.from), closed: laid.closed, summary: laid.block.header, from: laid.block.header.to, to: end, scope: true, ...(laid.unlaid ? { unlaid: true } : {}) };
            laid.block.fold = fold;
        }
    }

    /**
     * Lay a concern as a block, set in by how deep it's nested (`entry`), into `within`, as an item is laid out: its
     * header saying what it is, who holds it or who left it, and its two marks (`concernSaid`), which a verb on it
     * reaches it from, Space d clearing it, Space x declining it, Space s sending it somewhere, a comment writing on it;
     * and folded under it, laid out only while it's open but where something's written on it: why it's parked; the
     * agent's account, where they said it's done; its body, set in, each message quoting lines of it under the last it
     * quotes (`layBody`); each passage of the operator's it came from, with what became of it; each item moved into it,
     * laid out whole, which its agent's group leaves a dim line for; what of what landed there asks the operator or is new
     * to them, a line each, Enter going to the item; each concern nested under it that isn't laid out here, a line each,
     * `gt` going to its own block; and what else is written on it. It starts open where it wants the operator's eyes,
     * said done or holding what asks them, else closed. Dim, it's one line, its words, context above one nested under it
     * held elsewhere. `here` is what this buffer lays out of them. Return it, open for what's nested under it, to end
     * with `closeConcern`; none for a dim line.
     */
    function layConcern(entry: Nested, within: Placed[], at: string, here: ReadonlySet<number>): Opened | null {
        const { read, depth, dim } = entry;
        const number = read.thread.number;
        const set = "  ".repeat(depth);
        if (dim) {
            const id = `concern ${number} context ${at}`;
            const line = w.line(`${set}${concernWords(read)}`, id);
            asides.push({ kind: "concern-context", ...line });
            within.push(part(id, "frame", line.from, line.to));
            concernLines.push({ ...line, header: line, read, dim: true, blocks: [], lines: [], fold: null, holder: null, passages: [], items: [] });
            return null;
        }
        const id = `concern ${number}`;
        const inner = `${set}${SET_IN}`;
        const answering = read.answering ?? null;
        const leaver = read.left_by ?? null;
        const holder = answering ?? leaver;
        const whom = answering !== null ? name(answering) : leaver !== null ? `left by ${name(leaver)}` : "nobody's";
        // Nobody running answering for it, who left it says it: its marks say nothing more of it.
        const said = concernSaid(read);
        const marksSaid = answering === null && said === "nobody running" ? "" : ` · ${said}`;
        const opening = `${set}§ ${concernWords(read)} · `;
        const header = w.line(`${opening}${whom}${marksSaid}`, id);
        asides.push({ kind: `concern-${concernReads(read).replaceAll(" ", "-")}`, ...header });
        const named = holder === null ? null : { from: header.from + opening.length + (answering === null ? "left by ".length : 0), to: header.from + opening.length + whom.length };
        const children: Placed[] = [];
        const blocks: Block[] = [];
        const laidHere: ConcernBlock = { from: header.from, to: header.to, header, read, dim: false, blocks, lines: [], fold: null, holder: named === null || holder === null ? null : { ...named, conversation: holder }, passages: [], items: [] };
        concernLines.push(laidHere);
        const node = part(id, "frame", header.from, header.to, { children });
        within.push(node);
        // Open where it wants the operator's eyes; what's written on it keeps it laid out, closed or not.
        const wants = concernReads(read) === "for your eyes" || (read.asks ?? []).length > 0 || asking(read);
        const onIt = letters.filter((each) => each.thread === number);
        const closed = deferring({ of: id, kind: "concern", name: "" }, !wants, false);
        if (closed && onIt.length === 0) {
            w.line(UNLAID, `${id} unlaid`);
            return { block: laidHere, node, closed: true, unlaid: true };
        }
        const status = read.status ?? null;
        if (concernReads(read) === "open" && status !== null && status.kind === "ledger:parked" && (status.why ?? "") !== "") {
            asides.push({ kind: "summary", ...w.line(`${inner}parked: ${status.why ?? ""}`, id) });
        }
        const done = read.done ?? null;
        if (done !== null) {
            const [first = "", ...rest] = done.to_try.split("\n");
            asides.push({ kind: "to-try", ...w.line(`${inner}done, they say: ${first}`, id) });
            for (const line of rest) {
                asides.push({ kind: "to-try-text", ...w.line(`${inner}${SET_IN}${line}`, id) });
            }
        }
        // Its body's lines, as it now stands; the messages on lines of it, each under the last of them, followed through
        // its rewrites; the rest, and those whose lines are gone with it, after it all.
        const body = read.body ?? null;
        if (body !== null && body.text !== "") {
            blockLines.set(bodyBlock(number), linesOf(body.text.split("\n"), body.at));
        }
        const onBody = new Map<number | null, Letter[]>();
        for (const letter of onIt) {
            const at = letter.quote == null ? null : seat(writtenId(letter), letter.quote, new Map([[bodyBlock(number), 0]]));
            onBody.set(at, [...(onBody.get(at) ?? []), letter]);
        }
        layBody(read, inner, onBody, laidHere, children);
        // Each passage of the operator's it came from: what became of it, then its first words, Enter going to what it was on.
        for (const passage of read.passages ?? []) {
            const words = (passage.words.split("\n").find((each) => each.trim() !== "") ?? "").trim();
            const became = passage.answer != null ? `answered in ${cited(passage.answer)}` : `open: waits on ${answering === null ? "whoever takes it" : name(answering)}`;
            const line = w.line(`${inner}you · ${cited(passage.spot.node)}.${passage.spot.part ?? 0} · ${became}`, id);
            asides.push({ kind: "by", ...line });
            asides.push({ kind: "you", ...w.line(`${inner}${SET_IN}${cutAt(words, 100)}`, id) });
            laidHere.passages.push({ ...line, passage });
        }
        // Each item moved into it, whole, as its agent's group would lay it out; one no longer waiting, a line.
        for (const number_ of read.moved ?? []) {
            const item = shown.items.get(number_);
            if (item !== undefined) {
                children.push(layItem(item));
                continue;
            }
            const line = w.line(`${inner}${cited(number_)} · moved here, answered or read since`, `${id} moved ${number_}`);
            asides.push({ kind: "concern-context", ...line });
        }
        // What of what landed there asks the operator or is new to them, where it's laid out in its agent's group.
        const landed = [...(read.asks ?? []).map((each) => ({ number: each.node, said: "asks you" })), ...(read.new ?? []).map((each) => ({ number: each, said: "new" }))].flatMap((each) => {
            const item = shown.items.get(each.number);
            return item === undefined ? [] : [{ ...each, said: `${itemKind(item)}, ${each.said}` }];
        });
        for (const each of landed) {
            const line = w.line(`${inner}${cited(each.number)} ${each.said}`, `${id} landed ${each.number}`);
            asides.push({ kind: "concern-nested", ...line });
            laidHere.items.push({ ...line, number: each.number });
        }
        for (const child of allConcerns.filter((each) => (each.thread.parent ?? null) === number && !here.has(each.thread.number) && each.bare !== true && concernReads(each) !== "gone")) {
            // Who holds it, or who left it where nobody running answers for it, which its marks say.
            const owner = taskOwner(child);
            const leaverOf = child.left_by ?? null;
            const whose_ = owner !== null ? [name(owner)] : leaverOf !== null ? [`left by ${name(leaverOf)}`] : [];
            const lineId = `concern ${child.thread.number} under ${number}`;
            const line = w.line([`${inner}↳ ${concernWords(child)}`, concernSaid(child), ...whose_].join(" · "), lineId);
            asides.push({ kind: "concern-nested", ...line });
            children.push(part(lineId, "frame", line.from, line.to));
            concernLines.push({ ...line, header: line, read: child, dim: true, blocks: [], lines: [], fold: null, holder: null, passages: [], items: [] });
        }
        for (const letter of onBody.get(null) ?? []) {
            writeWritten(letter, blocks, children);
        }
        return { block: laidHere, node, closed, unlaid: false };
    }

    /**
     * Lay concern `read`'s body into `concern`, a part of it among `within`, set in by `inner`, its words its own lines
     * (`ConcernBlock.lines`), a block of its own, versioned by when it was written (`bodyBlock`), so a message quoting them
     * is followed through its rewrites and says it's outdated where the lines it quotes changed; each of `onBody`, the
     * messages on it by the line they're under, under its line. A blank line is left blank. Nothing where it has none.
     */
    function layBody(read: ThreadRead, inner: string, onBody: ReadonlyMap<number | null, Letter[]>, concern: ConcernBlock, within: Placed[]): void {
        const body = read.body ?? null;
        if (body === null || body.text === "") {
            return;
        }
        const id = bodyBlock(read.thread.number);
        const own = body.text.split("\n");
        const at = startsOf(own);
        const from = w.at;
        const children: Placed[] = [];
        own.forEach((text, line) => {
            const shown = w.line(text === "" ? "" : `${inner}${text}`, id);
            concern.lines.push({ from: text === "" ? shown.from : shown.from + inner.length, to: shown.to, own: at[line] ?? 0, block: id, line });
            for (const letter of onBody.get(line) ?? []) {
                writeWritten(letter, concern.blocks, children);
            }
        });
        within.push(part(id, "frame", from, w.at - 1, { children }));
    }

    /**
     * Return the view of "since you approved" of `group`'s agent where it holds what waits on the operator; none else, or
     * where it isn't read.
     */
    function sinceWaits(group: Grouping): Mounted | null {
        const conversation = group.conversation;
        if (conversation === null || !drawers.has(group.key)) {
            return null;
        }
        const drawn = looks.drawers(conversation.repository).find((each) => each.view === "since");
        if (drawn === undefined) {
            return null;
        }
        const of = { runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null };
        const view = mount(conversation.repository, drawn.module, drawn.view, of, shown, remote);
        return view.answer?.blocks.waiting === true ? view : null;
    }

    /**
     * Lay the line a buffer's messages are written under, at its end, saying whom they reach, `saying`, under what's live
     * there, so what's written stays in view as it grows; then each message `of` the group `made`, at `node`, whose id is
     * `id`.
     */
    function layWriting(made: Group, node: Placed, id: string, saying: string, of: (letter: Letter) => boolean): void {
        const line = w.line(`── ${saying} ──`, `${id} writing`);
        asides.push({ kind: "writing", ...line });
        made.writing = line;
        const writtenParts: Placed[] = [part(`${id} writing`, "frame", line.from, line.to)];
        for (const letter of letters) {
            if (of(letter)) {
                writeWritten(letter, made.blocks, writtenParts);
            }
        }
        node.children.push(...writtenParts);
    }

    function layGroup(group: Grouping, depth: number, shape: GroupShape = "whole"): void {
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
        const place = placeOf(group.key);
        const id = `group ${place}`;
        const partsSaid = told.map((each) => each.text).join(" · ");
        const opening = w.line(banner(group.head, partsSaid), `${id} banner`);
        let partAt = placedIn(opening, partsSaid, true);
        for (const each of told) {
            drawnIn(partAt, each.drawn);
            partAt += each.text.length + " · ".length;
        }
        const data = conversation !== null ? drawers.get(group.key) : undefined;
        const blocks: Block[] = [];
        const writtenParts: Placed[] = [];
        const talksTo = (letter: Letter) => letter.to != null && letter.thread == null && whose(letter.to) === group.key;
        if (shape !== "own") {
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
            place,
            banner: opening,
            blocks,
            drawers: [],
            depth,
            fold: null,
            end: opening.to,
        };
        groups.push(made);
        const node = part(id, "group", opening.from, opening.to);
        nodes.push(node);
        node.children.push(
            part(`${id} banner`, "banner", opening.from, opening.to, { children: parts.map((each) => part(each.id, "view", opening.from, opening.to, { view: each })) }),
            ...writtenParts,
        );
        // Each of `list` of its drawers, one under the other: a label, folded until opened in place, but `live`, open.
        const layDrawers = (list: readonly { view: string; module: string }[], owner: string, live: boolean) => {
            if (conversation === null || of === null) {
                return;
            }
            let laidHere = false;
            for (const drawn of list) {
                const view = mount(repository, drawn.module, drawn.view, of, shown, remote);
                const drawer = layDrawer(drawn.view, conversation, view, "", live);
                if (drawer !== null) {
                    made.drawers.push(drawer);
                    laidDrawers.push(drawer);
                    node.children.push(drawer.node);
                    laidHere = true;
                }
            }
            const lastDrawer = made.drawers.at(-1);
            if (laidHere && lastDrawer !== undefined) {
                // The blank line after them is the last one's, as an item's is its own.
                lastDrawer.end = w.line("", owner).from;
            }
        };
        const declared = data === undefined && shape === "whole" ? [] : looks.drawers(repository);
        // Under the banner, before the items, each drawer; in the agent's own buffer, all but their conversation, which
        // comes after the items, live, what asks the operator and what's written to them under it.
        // What's live in their own buffer: the plain conversation where their repository's looks have one (`messages`), the
        // trace beside it a drawer as any other; else the trace.
        const liveView = declared.find((each) => each.view === "messages") ?? declared.find((each) => each.view === "conversation");
        layDrawers(shape === "own" ? declared.filter((each) => each !== liveView) : declared, `${id} drawers`, false);
        // Each item, but one moved into a concern, which leaves a dim line here saying where it went.
        for (const item of group.items) {
            const into = moved.get(item.number);
            node.children.push(into === undefined ? layItem(item) : layAway(item, into));
        }
        // The concerns this buffer lays out under them, each a block: in their own buffer, every one they answer for; in
        // what's for the operator, those wanting their eyes.
        const layOwn = () => layConcerns(concernsOf.get(group.key) ?? [], node.children, place);
        if (shape !== "own") {
            layOwn();
        }
        if (shape === "own") {
            const drawersBefore = made.drawers.length;
            layDrawers(liveView === undefined ? [] : [liveView], `${id} live`, true);
            // Never a buffer that looks empty: where their conversation isn't there, why.
            const talk = liveView;
            if (conversation !== null && of !== null && made.drawers.length === drawersBefore && talk !== undefined) {
                const read = mount(repository, talk.module, talk.view, of, shown, remote).answer !== null;
                const said = w.line(read ? "They haven't said anything yet." : "Reading their conversation…", `${id} live`);
                asides.push({ kind: "summary", ...said });
            }
            layOwn();
            if (conversation !== null) {
                layWriting(made, node, id, `to ${name(conversation)}`, talksTo);
            }
        } else if (concernsOf.has(group.key) || (group.items.length === 0 && made.drawers.length === 0 && blocks.length > 0)) {
            w.line("", `${id} end`);
        }
    }

    /** Lay the dim line `item`, moved into `into`, leaves in its agent's group: what it was, and where it went, which `gt` goes to. */
    function layAway(item: Item, into: ThreadRead): Placed {
        const id = `item ${item.number} away`;
        const line = w.line(`${cited(item.number)} ${itemKind(item)} → ${concernWords(into)}`, id);
        asides.push({ kind: "concern-context", ...line });
        aways.push({ ...line, item, into });
        return part(id, "frame", line.from, line.to);
    }

    function layItem(item: Item): Placed {
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
        const head = header(item, spoken.text);
        const headed = w.line(head, `${id} header`);
        drawnIn(placedIn(headed, spoken.text, false), spoken.drawn);
        children.push(part(`${id} header`, "header", headed.from, headed.to));
        writeBlocks(null);
        // The operator's words it answers, above its own, each after who wrote it.
        const theirs = above(item, around.answers, around.commented);
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
            // Closed, the line standing for its steps alone, which are laid out as it opens: read, never commented.
            const unlaid = context.lines.length > 0 && deferring({ of, kind: "context", name: "" }, true, false);
            const shownLines = unlaid
                ? [w.line(UNLAID, `${id} context`)]
                : context.lines.map((each) => {
                      const aside = { kind: each.kind, ...w.line(each.text, `${id} context`) };
                      into.asides.push(aside);
                      return aside;
                  });
            const last = shownLines.at(-1);
            if (last !== undefined) {
                into.folds.push({ of, kind: "context", name: "", label: "context", closed: true, summary: { from: line.from, to: line.to }, from: line.to, to: last.to, ...(unlaid ? { unlaid } : {}) });
            }
        }
        frame("context", contextFrom);
        // The item whole folds under its header, what folds within it inside: folded once it's marked done or declined,
        // or sent somewhere, but where it holds what the operator wrote, which stays in view until it's sent.
        const closed = settling.has(item.number) && into.blocks.length === 0;
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
     * isn't there, kept as a message to the agent. `live`, as a conversation in its agent's own buffer, it starts open.
     */
    function layDrawer(kind: DrawerKind, conversation: Conversation, view: Mounted, owner: string = "", live: boolean = false): (Drawer & { node: Placed }) | null {
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
        // The remarks this drawer shows: each on one of its blocks, to whoever wrote what it's on, and those to its agent
        // it takes from before quotes named their block.
        const mine = (taking: (remark: Remark) => boolean): Remark[] =>
            wrote.flatMap((each) => {
                if (!isRemark(each)) {
                    return [];
                }
                const block = each.quote.block ?? "";
                return (block === "" ? whose(each.to) === key && taking(each) : block.startsWith(ours)) ? [each] : [];
            });
        const reviewed: ReviewedLine[] = [];
        let settled: Span | null = null;
        const diffs = new Map<string, Filed>();
        const loads = new Map<string, Instance>();
        const toned: (Span & { tone: string })[] = [];
        const texts: Span[] = [];
        const writers = new Map<string, Conversation>();
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
        // What a fold of the view holds, as it's given or as the host last answered it; none where it isn't read yet.
        const held = (block: ViewBlock & { block: "fold" }): readonly ViewBlock[] | undefined => {
            if (Array.isArray(block.content)) {
                return block.content;
            }
            const answered = read(loaded(block.content));
            return answered === undefined ? undefined : (answered.blocks ?? []);
        };
        // How far the files counted among its own lines have gone, for a remark on a file's lines (`layCode`).
        let first = 0;
        const counting = new Set<string>(filedIn(blocks).map((each) => each.id));
        /**
         * Return `list`'s blocks as parts of the review where they aren't laid out, each on `at`, the line standing for
         * what holds them, a fold's own within it: what a verb on what holds them reaches, as every file of a closed
         * "since you approved" marked reviewed from its line; each file noted as one it shows. Where the drawer lays
         * out what's after them, `counted`, the files among its own lines go by as laid out (`first`), for a remark on
         * one after them; a drawer laid out closed lays out none, and none of its files' rows is made.
         */
        const shadowed = (list: readonly ViewBlock[], at: Span, counted: boolean): Placed[] =>
            list.map((block) => {
                if (block.block === "diff" || block.block === "code") {
                    diffs.set(block.id, block);
                    first += counted && counting.has(block.id) ? filedOnce(block).length : 0;
                }
                const children = block.block === "fold" ? shadowed(held(block) ?? [], at, counted) : [];
                return part(blockId(view.id, block.id), "block", at.from, at.to, { block, children });
            });
        const remarks = mine((each) => (each.step != null ? kind === "conversation" : kind === "since"));
        const markedRead = markedDone.has(view.id) && remarks.length === 0;
        // Closed, holding nothing the operator wrote: its summary line alone, one line standing for what it holds, laid out
        // as it opens, so a drawer costs a line however much it holds.
        if (blocks.length > 0 && remarks.length === 0 && deferring({ of, kind, name: "" }, !live || markedRead, live || markedRead)) {
            const holder = w.line(UNLAID, `${view.id} closed`);
            const drawerFold: Fold = { of, kind, name: "", label: `${said}${label}`, closed: !live || markedRead, summary, from: summary.to, to: holder.to, scope: true, unlaid: true };
            if (markedRead || live) {
                byMarks.add(drawerFold);
            }
            const node = part(view.id, "view", summary.from, holder.to, { view, children: shadowed(blocks, holder, false) });
            return {
                ...into,
                folds: [drawerFold],
                end: holder.to,
                kind,
                conversation,
                view,
                diffs,
                loads,
                toned,
                texts,
                writers,
                bars,
                files: [...(answer.files?.values() ?? [])],
                reviewed,
                settled,
                waiting: answer.blocks.waiting ?? false,
                of,
                header: summary,
                node,
            };
        }
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
                    // A line saying whom a comment on it reaches takes one, as a Markdown block's line does.
                    if (block.by != null) {
                        const said = lineOfView(block).text;
                        markdown.set(bid, [said]);
                        blockLines.set(bid, linesOf([said], block.version ?? null));
                    }
                } else if (block.block === "fold") {
                    walk(Array.isArray(block.content) ? block.content : (read(loaded(block.content))?.blocks ?? []));
                }
            }
        };
        walk(blocks);
        // A remark on a file's lines goes under the line it's on, each file's block its own, a file in a fold of the
        // view's, as a place of "since you approved", among them, in the order they're laid out.
        const topFiles = filedIn(blocks);
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
        // The blocks a remark is on, which every fold holding one keeps laid out, open or not.
        const remarked = new Set<string>();
        const holdsRemark = (list: readonly ViewBlock[]): boolean =>
            remarked.size > 0 && list.some((block) => remarked.has(blockId(view.id, block.id)) || (block.block === "fold" && holdsRemark(held(block) ?? [])));
        const place = (rid: string, remark: Written, quote: Quote) => {
            const block = quote.block ?? "";
            remarked.add(block);
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
        for (const remark of remarks) {
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
        const layBlocks = (list: readonly ViewBlock[], top: boolean, within: Placed[]) => {
            for (const block of list) {
                const id = blockId(view.id, block.id);
                switch (block.block) {
                    case "diff":
                    case "code": {
                        const lines = filedOnce(block);
                        const before = into.filed.length;
                        layCode(w, into, of, lines, first, starts, writeBlocks, () => id);
                        first += counting.has(block.id) ? lines.length : 0;
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
                        if (block.by != null) {
                            const last = into.lines.at(-1);
                            into.lines.push({ from: aside.from, to: aside.to, own: last === undefined ? 0 : last.own + (last.to - last.from) + 1, block: id, line: 0 });
                            writers.set(id, conversationOf(view.repository, block.by));
                            for (const comment of onWords.get(`${id} 0`) ?? []) {
                                writeWritten(comment, into.blocks, children);
                            }
                        }
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
                        if (block.by != null) {
                            writers.set(id, conversationOf(view.repository, block.by));
                        }
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
                        if (!Array.isArray(block.content)) {
                            // Read from another of its module's views as it opens, which opening the fold asks for.
                            loads.set(block.id, loaded(block.content));
                        }
                        const holds = held(block);
                        // What the host answered of it, or a line saying it's being read; one read from another view,
                        // closed, holding nothing the operator wrote, a line standing for it alone, what it holds laid
                        // out as it opens, as its view meant it to be read a fold at a time. What a view gives with it
                        // is laid out, closed or not, so a search finds it in a drawer open.
                        const unread = holds === undefined;
                        const unlaid = !Array.isArray(block.content) && !holdsRemark(holds ?? []) && deferring({ of, kind: block.kind, name: block.id }, !(block.open ?? false), false);
                        if (unlaid) {
                            inner.push(...shadowed(holds ?? [], w.line(UNLAID, `${id} closed`), true));
                        } else if (holds === undefined) {
                            into.asides.push({ kind: "plain", ...w.line("reading…", `${id} reading`) });
                        } else {
                            layBlocks(holds, false, inner);
                        }
                        const last = w.at - 1;
                        if (block.kind === "lines" && block.id.startsWith("reviewed")) {
                            settled ??= { from: head.from, to: head.to };
                        }
                        if (last > head.to) {
                            into.folds.push({ of, kind: block.kind, name: block.id, label: line.text, closed: !(block.open ?? false), summary: { from: head.from, to: head.to }, from: head.to, to: last, unread, ...(unlaid ? { unlaid } : {}) });
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
        const foldedByMark = markedDone.has(view.id) && into.blocks.length === 0;
        const drawerFold: Fold = { of, kind, name: "", label: `${said}${label}`, closed: !live || foldedByMark, summary, from: summary.to, to: last, scope: true };
        into.folds.push(drawerFold);
        if (foldedByMark || live) {
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
            writers,
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

/**
 * Return how many lines that matter a drawer laid out closed holds (`Fold.unlaid`), each a stop of `]c` and `[c` once it
 * opens (`Scope.stops`): those of its files, as `layCode` stops at them, through every fold of its view given with it; a
 * fold read from another view holds none of them till it's read, and lays out closed. None of a drawer laid out.
 */
export function stopsHeld(drawer: Drawer): number {
    if (drawer.folds.at(-1)?.unlaid !== true) {
        return 0;
    }
    const counted = (list: readonly ViewBlock[]): number =>
        list.reduce((sum, block) => sum + (isFiled(block) ? filedOnce(block).filter((each) => each.stop).length : block.block === "fold" && Array.isArray(block.content) ? counted(block.content) : 0), 0);
    return counted(drawer.view.answer?.blocks.blocks ?? []);
}

/** Return the stop after the line starting at `line`, or before it, of `stops`, in the text's order; none past the last, or before the first. */
export function stepped(stops: number[], line: number, forward: boolean): number | undefined {
    return forward ? stops.find((each) => each > line) : [...stops].reverse().find((each) => each < line);
}

/**
 * Whether an item is to answer rather than to read: one the host says needs the operator as it stands (`Item.asks`), a
 * question, a held change, an approval or a hold at landing; neither marked nor sent somewhere in `draft`, which settles
 * it until the reply is sent (`marked`); and in no pile, where it's set aside (`piledIn`).
 */
export function toAnswer(item: Item, draft: Draft, piled: ReadonlySet<number>): boolean {
    return item.asks && !marked(draft).has(item.number) && !piled.has(item.number);
}

/** Whether an item still waits where it stands, as each the inbox lists does: a thread's conversation shows those answered, done or decided too. */
export function waits(item: Item): boolean {
    return item.state.state === "waiting";
}

/**
 * Return the classes of an item's header line: new to the operator, news; struck through where the draft marks it done
 * or declined, which the next Ctrl+Enter does; and muted where it no longer waits, answered, read or decided, a thread's
 * history, never struck through, as a mark on it does nothing. Where the draft sends it somewhere, its line says where
 * (`sentSaid`), drawn as a mark is.
 */
export function headerClasses(item: Item, draft: Draft, seeing: Seeing): string {
    const number = item.number;
    const open = waits(item);
    return [
        "review-header",
        fresh(item, seeing) ? "is-new" : "",
        news(item) ? "is-news" : "",
        !open ? "is-past" : (draft.done ?? []).includes(number) ? "is-done" : "",
        open && (draft.declined ?? []).includes(number) ? "is-declined" : "",
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
    const walk = laidOut.regions.filter((each) => toAnswer(each.item, draft, laidOut.piled)).toSorted((a, b) => a.item.number - b.item.number);
    return forward ? walk.find((each) => each.item.number >= bound) : walk.findLast((each) => each.item.number <= bound);
}

/**
 * Say what waits below, for the header over the review, so the operator knows without the text moving to show it: how
 * many items are to answer (`toAnswer`), and how many are new to them, their groups not seen since (`fresh`), among
 * those neither marked read nor left for later; nothing where no item waits.
 */
export function tallied(items: Item[], draft: Draft, seeing: Seeing, piled: ReadonlySet<number>): string {
    if (items.length === 0) {
        return "";
    }
    const answering = items.filter((each) => waits(each) && toAnswer(each, draft, piled)).length;
    const reading = countToRead(items, draft, seeing, piled);
    return [`${answering} to answer`, ...(reading === 0 ? [] : [`${reading} to read`])].join(" · ");
}

/** Return the last of `spans`, in the text's order, starting at or before `position`. */
function lastFrom<T>(spans: T[], from: (each: T) => number, position: number): T | undefined {
    return spans.findLast((each) => from(each) <= position);
}

/** Return every scope, the items' and the drawers', in the text's order. */
function scopes(laidOut: Laid): Scope[] {
    return [...laidOut.regions, ...laidOut.drawers].sort((a, b) => a.header.from - b.header.from);
}

/** Return the item or the drawer `position` is in: its header, its lines, its comments, or the blank line after it; none on a group's banner or the messages under it, nor on a concern's block. */
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

/** Return the group `position` is on: on its banner, the messages under it, or the blank line after them, a thread's own lines among them; none on an item or a drawer. */
export function groupAt(laidOut: Laid, position: number): Group | undefined {
    return scopeAt(laidOut, position) === undefined ? groupAround(laidOut, position) : undefined;
}

/** Return the group `position` is in, on its banner, its items or its drawers; none on a line of the buffer's own. */
export function groupAround(laidOut: Laid, position: number): Group | undefined {
    return laidOut.groups.findLast((each) => each.banner.from <= position && position <= each.end);
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
        return [];
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
        const concern = laidOut.concerns.find((each) => each.read.thread.number === written.thread)?.read;
        return `to no one, kept on ${concern === undefined ? `@${written.thread}` : concernWords(concern)}`;
    }
    return "to no agent: no session's push asked it";
}

/** Return every comment, message and remark shown, as blocks of the editor's list of what's written. */
export function blocksOf(laidOut: Laid): Block[] {
    return [...laidOut.groups.flatMap((each) => each.blocks), ...laidOut.concerns.flatMap((each) => each.blocks), ...scopes(laidOut).flatMap((each) => each.blocks)];
}

/** Return the comment, message or remark shown at `position`, where it's in one; a comment's end counts, so an empty one can be typed in. */
export function blockAt(laidOut: Laid, position: number): Block | undefined {
    return blocksOf(laidOut).find((each) => position >= each.from && position <= each.to);
}

/** Return a message on `concern`, as it's opened, empty, to whoever answers for it, or to no one where nobody does: on lines of its body where `quote` says which, else on it whole. */
export function letterOn(concern: ConcernBlock, quote: Quote | null = null): Letter {
    return { id: "", to: concern.read.answering ?? null, thread: concern.read.thread.number, ...(quote === null ? {} : { quote }), text: "" };
}

/** Return the line of `concern`'s body `position` is on, its words or where it's set in before them; none elsewhere. */
export function bodyLineAt(laidOut: Laid, concern: ConcernBlock, position: number): OwnLine | undefined {
    return concern.lines.find((each) => position <= each.to && position >= laidOut.text.lastIndexOf("\n", each.from - 1) + 1);
}

/** Return a message to the agent `group` is of, as it's opened: empty; none for a group no message goes to. */
function letterTo(group: Group): Letter | undefined {
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
 * to answer now, from the banner of what's left for later too. On a concern's block, a message on it, quoting the line of
 * its body it's on, where it's on one with words. None on a line no comment is on, or on the banner of lup's approvals.
 */
export function opened(laidOut: Laid, position: number): Written | undefined {
    // On a concern, a message on it, to whoever answers for it, or to no one where nobody does: on a line of its body,
    // quoting it.
    const concern = concernAt(laidOut, position);
    if (concern !== undefined) {
        const line = bodyLineAt(laidOut, concern, position);
        const shown = line === undefined ? "" : laidOut.text.slice(line.from, line.to);
        const quote = line === undefined || shown === "" ? null : onLines(laidOut, line, line, 0, shown.length, shown);
        return letterOn(concern, quote);
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
    const to = writerOf(drawer, line);
    return quote === null || isNobody(to) ? undefined : { id: "", to, quote, text: "", ...coded(drawer, [line]) };
}

/** Return whom a remark on `line` of `drawer` goes to: whoever wrote what it's on, as its block says where that's another agent (`Markdown.by`), else the drawer's agent. */
function writerOf(drawer: Drawer, line: OwnLine): Conversation {
    return drawer.writers.get(line.block) ?? drawer.conversation;
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
 * message to a group's agent where it's on its banner, which no comment quotes; a remark on a passage of a drawer's; a
 * message on a concern, quoting the passage where it's on lines of its body (`quotedOn`); none where it isn't all inside
 * one item's lines, one drawer's, one concern's block, or one group's. It's anchored to the block of the line it ends on,
 * what it says the whole passage.
 */
export function quoted(laidOut: Laid, from: number, to: number): Written | undefined {
    const concern = concernAt(laidOut, from);
    if (concern !== undefined) {
        return concern === concernAt(laidOut, Math.max(to - 1, from)) ? quotedOn(laidOut, concern, from, to) : undefined;
    }
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

/** Return the message on the passage `from` to `to` selects in `concern`: quoting it where it's all on lines of its body, else on the concern whole. */
function quotedOn(laidOut: Laid, concern: ConcernBlock, from: number, to: number): Letter {
    const first = bodyLineAt(laidOut, concern, from);
    const last = bodyLineAt(laidOut, concern, Math.max(to - 1, from));
    if (first === undefined || last === undefined || to <= from) {
        return letterOn(concern);
    }
    const own = concern.lines.map((each) => laidOut.text.slice(each.from, each.to)).join("\n");
    const offsets = passage(own, first, last, from, to);
    return letterOn(concern, onLines(laidOut, first, last, offsets.start - first.own, offsets.end - first.own, offsets.text));
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
    const whom = writerOf(drawer, last);
    return quote === null || isNobody(whom) ? undefined : { id: "", to: whom, quote, text: "", ...coded(drawer, lines) };
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
 * banner, or the header of the concern it's on; the last character of the passage a comment, a remark or a message on
 * lines of a concern's body quotes, where reading carries on, as it's laid out now (`quotedAt`), or its item's header for
 * one on the item whole.
 */
export function aboutAt(laidOut: Laid, written: Written, block: Block): number | undefined {
    const concern = isLetter(written) && written.thread != null ? laidOut.concerns.find((each) => !each.dim && each.read.thread.number === written.thread) : undefined;
    if (concern !== undefined) {
        const shown = quotedAt(laidOut, concern, written);
        return shown === null ? concern.header.from : Math.max(shown.to - 1, shown.from);
    }
    if (isLetter(written)) {
        const group = groupAt(laidOut, block.from);
        return group?.writing?.from ?? group?.banner.from;
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
 * Return where the passage what's written quotes is in `scope`, an item, a drawer or a concern's block, as it's laid out
 * now: from where it starts in the first of its lines it's seated on (`Laid.seated`), to where it ends in the last, each
 * kept within its line; none for a message quoting nothing, what's on its item whole, one copies before kept on a reply,
 * or one not seated in `scope`.
 */
export function quotedAt(laidOut: Laid, scope: Pick<Scope, "lines">, written: Written): Span | null {
    // As it's laid out, anchored there where it was drafted before it was.
    const shown = laidOut.written.find((each) => writtenId(each) === writtenId(written)) ?? written;
    if (shown.quote == null || ("on" in shown && shown.on != null)) {
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

/**
 * Return the items a draft answers, as the host's `Draft.covered` reads them: each with a comment that says something
 * and goes to whoever sent it, marked done or declined. A comment going elsewhere (`goesTo`) answers nothing of its item.
 */
export function covered(draft: Draft): number[] {
    const mentioned = [
        ...(draft.comments ?? []).filter((each) => each.text.trim() !== "" && goesTo(draft, each) === null).map((each) => each.item),
        ...(draft.done ?? []),
        ...(draft.declined ?? []),
    ];
    return [...new Set(mentioned)].sort((a, b) => a - b);
}

/**
 * Return where what's written goes elsewhere than where it was written, as the host routes it (`going`,
 * `lup_dev.inbox.routing`): where the operator sent it with Space s; a comment where its item's sent, going with it;
 * none where it goes where it was written.
 */
export function goesTo(draft: Draft, each: Written): Destination | null {
    const sent = each.sent ?? null;
    if (sent !== null || !("item" in each)) {
        return sent;
    }
    return itemsSent(draft).get(each.item) ?? null;
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
