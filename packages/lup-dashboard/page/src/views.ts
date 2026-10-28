// The views the review mounts (`docs/declaration.md`, *Views and blocks*; `docs/dashboard.md`, *The review*): each a
// module's, by the module's name and the view's, of what it's given, answering `Blocks`. An item's body is its kind's
// view of it, a drawer and a part of an agent's banner are views of the agent. Where the page lays a view out itself
// until its module serves it (#113, step 4), a producer named after that module answers it here (`views/*.ts`), from
// what the page has read (`Shown`), in the same generated block types the module's Python answers with, so moving it
// is moving code; each producer's answers are pinned by fixtures (`fixtures/views/`) its module's Python will match. A
// view no producer answers is its module's own, asked of the host (`module-view`) and kept live at its own triggers.
// Every view instance has an id that stays across layouts, its module, view and argument with its repository, and
// each of its blocks the instance's id and the block's own: what the review is kept by (`review.ts`). Pure.
import type { Laid as Talk } from "./conversation";
import type { components } from "./generated/api";

export type Blocks = components["schemas"]["Blocks"];
export type Block = components["schemas"]["Block"];
export type Line = components["schemas"]["Line"];
export type Markdown = components["schemas"]["Markdown"];
export type Fold = components["schemas"]["Fold"];
export type Span = components["schemas"]["Span"];
export type Offer = components["schemas"]["Offer"];
export type OfAgent = components["schemas"]["OfAgent"];
type Item = components["schemas"]["Item"];
type Conversation = components["schemas"]["Conversation"];
type Context = components["schemas"]["Context"];
type ChangedFile = components["schemas"]["ChangedFile"];
type Since = components["schemas"]["Since"];
type SinceFile = components["schemas"]["SinceFile"];
type Task = components["schemas"]["Task"];
type Usage = components["schemas"]["Usage"];
type Call = components["schemas"]["Call"];
type Entry = components["schemas"]["Entry"];
type Exchange = components["schemas"]["Exchange"];
type TalkComment = { step: number; quote: components["schemas"]["Quote"]; text: string };

/** What the host answered, asked for more of an item than its own text: what it showed, or why it refused. */
export type Answered<T> = { shown: T } | { refused: string };

/**
 * What one agent's views read of it, by its conversation (`whose`): its conversation's steps as read so far, each call
 * read whole once its fold was opened, its task list and what its context holds, the items it exchanged, and what its
 * branch changed since the operator last saw it. None of a view's before the host has answered.
 */
export interface AgentDrawers {
    entries: Entry[];
    calls: ReadonlyMap<string, Answered<Call>>;
    tasks: Task[];
    usage: Usage | null;
    exchanged: { sent: Exchange[]; received: Exchange[] } | null;
    since: Since | null;
}

/** Each agent's data, by `whose` its conversation is. */
export type Drawers = Map<string, AgentDrawers>;

export const UNREAD: AgentDrawers = { entries: [], calls: new Map(), tasks: [], usage: null, exchanged: null, since: null };

/** What the host has answered of each item beyond its own text, by its number: its context, and each file it changes. */
export interface Beyond {
    contexts: ReadonlyMap<number, Answered<Context>>;
    files: ReadonlyMap<number, Answered<ChangedFile[]>>;
}

/** One conversation running, as the host lists it: the launch it runs in, and whether the operator holds its flagged writes. */
export interface Running {
    launch: string;
    holding: boolean;
}

/** What the page has read, which its own producers answer from. */
export interface Shown {
    /** Each item waiting, by its number. */
    items: ReadonlyMap<number, Item>;
    beyond: Beyond;
    drawers: Drawers;
    /** Each conversation running, by `whose` it is. */
    running: ReadonlyMap<string, Running>;
    /** A conversation as the operator reads it named: by its path. */
    called: (party: Conversation) => string;
}

/** What a producer answers: the view's blocks, and what the page's own handling of it reads until the blocks say it all. */
export interface Answer {
    blocks: Blocks;
    /** For "since you approved": each file a block shows, by the block's id, and what the host answered of the drawer. */
    files?: ReadonlyMap<string, SinceFile>;
    since?: Since;
    /** For the conversation, which the page's own `conversation.ts` lays out until it's `Transcripts`' own view: its text, with the operator's remarks on it. */
    talk?: (remarks: TalkComment[]) => Talk;
}

/** A view the page lays out itself: whose module's it is, which view, and its answer of what it's given, from what the page has read of `repository`. */
export interface View<A> {
    module: string;
    view: string;
    answer: (argument: A, shown: Shown, repository: string) => Answer | null;
}

/** Return what names a conversation among others: its repository, runtime, session and subagent. */
export function whose(conversation: Conversation): string {
    return JSON.stringify([conversation.repository, conversation.runtime, conversation.session, conversation.agent ?? null]);
}

/** Return the conversation of the agent `of` names, of `repository`. */
export function conversationOf(repository: string, of: OfAgent): Conversation {
    return { party: "conversation", repository, runtime: of.runtime, session: of.session, agent: of.agent ?? null };
}

/** Return `value` as JSON with its objects' keys in order, so one argument is one id however it was built. */
export function canonical(value: unknown): string {
    if (Array.isArray(value)) {
        return `[${value.map(canonical).join(",")}]`;
    }
    if (value !== null && typeof value === "object") {
        const entries = Object.entries(value as Record<string, unknown>).filter(([, each]) => each !== undefined);
        return `{${entries
            .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
            .map(([key, each]) => `${JSON.stringify(key)}:${canonical(each)}`)
            .join(",")}}`;
    }
    return JSON.stringify(value);
}

/** One view mounted: the instance's id, its repository, module, view and argument, and, once answered, its answer. */
export interface Mounted {
    id: string;
    repository: string;
    module: string;
    view: string;
    argument: unknown;
    answer: Answer | null;
}

/** Return the id of the view instance `module`'s `view` of `argument`, of `repository`: the same however the argument was built. */
export function instanceOf(repository: string, module: string, view: string, argument: unknown): string {
    return canonical([repository, module, view, argument]);
}

/** Return the id of block `block` of the view instance `instance`: what keeps it across layouts. */
export function blockId(instance: string, block: string): string {
    return `${instance} ${block}`;
}

/** A view of a module's, of a repository, by its module's name and its own, of what it's given: what the page asks of the host (`module-view`). */
export interface Instance {
    repository: string;
    module: string;
    view: string;
    argument: unknown;
}

/** What a remote view answered, by its instance's id, as the host keeps the page told (`module-view`). */
export type Remote = ReadonlyMap<string, Blocks>;
