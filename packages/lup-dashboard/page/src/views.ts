// The views the review mounts (`docs/declaration.md`, *Views and blocks*; `docs/dashboard.md`, *The review*): each a
// module's, by the module's name and the view's, of what it's given, answering `Blocks`. An item's body is its kind's
// view of it, a drawer and a part of an agent's banner are views of the agent. Where the page lays a view out itself
// until its module serves it (#113, step 4), a producer named after that module answers it here (`views/*.ts`), from
// what the page has read (`Shown`), in the same generated block types the module's Python answers with, so moving it
// is moving code; each producer's answers are pinned by fixtures (`fixtures/views/`) its module's Python will match. A
// view no producer answers is its module's own, asked of the host (`module-view`) and kept live at its own triggers.
// Every view instance has an id that stays across layouts, its module, view and argument with its repository, and
// each of its blocks the instance's id and the block's own: what the review is kept by (`review.ts`). Pure.
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
type SincePlace = components["schemas"]["SincePlace"];
type Wait = components["schemas"]["Wait"];
type Task = components["schemas"]["Task"];
type Usage = components["schemas"]["Usage"];

/** What the host answered, asked for more of an item than its own text: what it showed, or why it refused. */
export type Answered<T> = { shown: T } | { refused: string };

/**
 * What one agent's views the page lays out itself read of them, by their conversation (`whose`): their task list and
 * what their context holds, read with their runtime's record (`inbox-show-conversation`), and what their branch changed
 * since the operator last saw it. None of a view's before the host has answered. Their conversation is `Transcripts`'
 * own view, asked of the host.
 */
export interface AgentDrawers {
    tasks: Task[];
    usage: Usage | null;
    since: Since | null;
    /** Why the host refused what their branch changed, which their drawer says in its place, as a copy of the operator's dashboard state refuses it (`lup_dashboard/copied.py`); none where it answered, or hasn't yet. */
    unread?: string | null;
}

/** Each agent's data, by `whose` their conversation is. */
export type Drawers = Map<string, AgentDrawers>;

export const UNREAD: AgentDrawers = { tasks: [], usage: null, since: null };

/** What the host has answered of each item beyond its own text, by its number: its context, and each file it changes. */
export interface Beyond {
    contexts: ReadonlyMap<number, Answered<Context>>;
    files: ReadonlyMap<number, Answered<ChangedFile[]>>;
}

/** One conversation running, as the host lists them: the launch they run in, and whether the operator holds the conversation's flagged writes. */
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
    /** Each conversation running, by `whose` they are. */
    running: ReadonlyMap<string, Running>;
    /** The landings waiting on the operator, the oldest first (`policy-show-landings`). */
    landings: readonly Wait[];
    /** A conversation as the operator reads them named: by their path. */
    called: (party: Conversation) => string;
}

/** A file of "since you approved" as a block shows it: the file, the place of the agent's it's in, and the block's id. */
export interface PlacedFile {
    file: SinceFile;
    place: SincePlace;
    block: string;
}

/** What a producer answers: the view's blocks, and what the page's own handling of it reads until the blocks say it all. */
export interface Answer {
    blocks: Blocks;
    /** For "since you approved": each file a block shows, by the block's id, and what the host answered of the drawer. */
    files?: ReadonlyMap<string, PlacedFile>;
    since?: Since;
}

/** A view the page lays out itself: whose module's it is, which view, and its answer of what it's given, from what the page has read of `repository`. */
export interface View<A> {
    module: string;
    view: string;
    answer: (argument: A, shown: Shown, repository: string) => Answer | null;
}

/** Return what names a conversation among others: their repository, runtime, session and subagent. */
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
