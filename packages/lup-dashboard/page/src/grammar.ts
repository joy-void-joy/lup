// The review's verbs as one grammar (#247; `docs/dashboard.md`, *The keys*): Space and a verb's key acts on the
// innermost thing it applies to, from the cursor outward, through the tree the review is laid out as (`Laid.nodes`):
// a block offering the verb, as a file of "since you approved" offers done; a drawer, as a whole; an item, the host
// saying what it offers (`Item.offers`), each answer of its kind while it waits on the operator; and an agent's group,
// its banner's parts saying what hold means, done reaching the agent's own items and drawers. What a verb reaches is
// said before it's pressed, on the line of keys, in the palette and the stack, from the same walk (`reachOf`).
//
// Only the view changes at once. Everything that reaches an agent or the host is a mark in the draft (`marking`):
// an item done or declined, the inbox's own; where Space s sent something, an item, a concern or what was written
// (`sentTo`), which the picker it opens chooses (`Picker.tsx`); anything else a block offers, recorded as the offer
// (`Marked`), which the page applies as the draft is sent (`App.tsx`). Undone with `u`, as any change to the draft. An
// offer that runs at once (`Offer.runs`), a module's view key, is run as it's pressed. Pure.
import { newId } from "./anchors";
import { partSaid, type ReplyPart } from "./brief";
import type { components } from "./generated/api";
import { cited } from "./comments";
import { concernReads, concernsSent, concernWords, cutAt, EMPTY, goesTo, isLetter, isNobody, itemsSent, news, toAnswer, waits, writtenId, written, type Conversation, type Destination, type Draft, type Group, type Item, type Laid, type Placed, type Region, type ThreadRead, type Written } from "./review";
import type { Block as ViewBlock, Offer } from "./views";

export type Verb = components["schemas"]["Verb"];
export type Marked = components["schemas"]["Marked"];

/** Which of the draft's lists of items an item is marked in: done or declined. */
export type Listed = "done" | "declined";

/**
 * What Space s sends somewhere, choosing where in its picker (`Picker.tsx`): an item, into a concern or a pile; a concern,
 * to an agent, under another concern, into a pile or to `No agent`; or what the operator wrote, by its id, to an agent,
 * a concern or a pile. Each with the repository whose concerns and piles it may go to.
 */
export type Sendable =
    | { kind: "item"; number: number; repository: string }
    | { kind: "concern"; read: ThreadRead }
    | { kind: "written"; id: string; repository: string };

/**
 * One thing a verb does where it lands: an item marked in one of the draft's lists; an offer marked in the draft, on
 * the block it's shown on, at the version that block shows; an offer run at once, on what's of `conversation`; a
 * comment opened on the thing whole, which the editor opens; or the picker opened for what Space s sends somewhere.
 */
export type Act =
    | { kind: "item"; number: number; list: Listed }
    | { kind: "mark"; offer: Offer; block: string; version: string | null }
    | { kind: "once"; offer: Offer; conversation: Conversation | null }
    | { kind: "comment" }
    | { kind: "send"; what: Sendable };

/**
 * Where a verb lands at the cursor: what it's on, as the line of keys names it, the part of the review it is, what it
 * does there, in a few words, and its acts; what it does whole, where the few words count what it leaves rather than
 * name each, as the palette says it (`whole`); or why nothing there takes it.
 */
export type Reach = { on: string; node: Placed; says: string; whole?: string; acts: Act[] } | { on: null; says: null; why: string };

/**
 * Say what a verb on a thread or an agent's group leaves of what asks the operator there, after what it does: how many,
 * as the line of keys says it; and each by its number, as the palette does. Nothing where it leaves none.
 */
function leaving(left: readonly number[]): { short: string; whole: string } {
    if (left.length === 0) {
        return { short: "", whole: "" };
    }
    return { short: `, ${left.length} left to answer`, whole: `, ${left.map(cited).join(" ")} left to answer` };
}

/**
 * How the walk names what a verb lands on, an agent by their conversation as it's called, and whether an item is new to
 * the operator, its group not seen since it came (`fresh`): none new where it doesn't say. And the draft as it stands,
 * where a verb does one thing until that's marked, then the next: Space d on a thread's banner reading its news, then
 * settling it; none marked where it isn't given.
 */
export interface Naming {
    called: (conversation: Conversation) => string;
    fresh?: (item: Item) => boolean;
    draft?: Draft;
}

/** The core's module, whose review mark an agent's group's is (`lup_dev.inbox.marks.CORE`). */
export const CORE_MODULE = "core";

/**
 * Return marking `conversation`'s group seen up to item `upTo`, shown on its banner, `block`: the core's review mark on
 * it, moved as the reply is sent (`review-mark`), so its items after it are new to the operator.
 */
export function seenAct(conversation: Conversation, block: string, upTo: number): Act {
    const offer: Offer = {
        action: "review-mark",
        argument: {
            repository: conversation.repository,
            module: CORE_MODULE,
            key: { runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null },
            up_to: String(upTo),
        },
        verb: CORE.done,
        chord: null,
        runs: "send",
        commented: false,
        says: "mark them seen",
    };
    return { kind: "mark", offer, block, version: null };
}

/** The core's verbs, by name, which apply to anything (`lup.SHELL_VERBS`). */
export const CORE = { done: "done", decline: "decline", send: "send", comment: "comment" } as const;

/** Done, as a verb the walk asks for by name: what marks news read. */
const DONE_VERB = { name: CORE.done, key: "d", called: "done" } satisfies Verb;

/**
 * Why nothing takes a verb where nothing at the cursor or around it offers it, in a few words: the core's say what they
 * apply to; any other verb is its module's.
 */
function whyNot(verb: Verb): string {
    switch (verb.name) {
        case CORE.done:
            return "nothing here is marked done";
        case CORE.decline:
            return "only an approval, a held change, a file held at landing or a thread is declined";
        case CORE.send:
            return "only an item, a concern or what you wrote is sent somewhere";
        case CORE.comment:
            return "nothing here takes a comment";
        default:
            return `nothing here takes ${verb.called}`;
    }
}

/**
 * Return where send lands on what the operator wrote, laid out at `node`, in `laidOut`: the picker, sending it to an
 * agent, a concern or a pile; none for another verb.
 */
function writtenReach(laidOut: Laid, node: Placed, verb: Verb): Reach | null {
    if (verb.name !== CORE.send) {
        return null;
    }
    const each = laidOut.written.find((one) => `written ${writtenId(one)}` === node.id);
    if (each === undefined) {
        return null;
    }
    const on = isLetter(each) ? "your message" : "comment" in each || "item" in each ? "your comment" : "your remark";
    return { on, node, says: "send it to an agent, a concern or a pile", acts: [{ kind: "send", what: { kind: "written", id: writtenId(each), repository: repositoryOfWritten(laidOut, each) } }] };
}

/** Return the repository what the operator wrote is of: its item's, its concern's, or whom it's to. */
function repositoryOfWritten(laidOut: Laid, each: Written): string {
    if ("item" in each) {
        const item = laidOut.regions.find((region) => region.item.number === each.item)?.item;
        return item === undefined ? "" : repositoryOfItem(item);
    }
    const concern = "thread" in each && each.thread != null ? laidOut.concerns.find((one) => one.read.thread.number === each.thread)?.read : undefined;
    return concern?.thread.repository ?? each.to?.repository ?? "";
}

/** Return the repository an item is of: its sender's, else whom it's for, else what an approval's about. */
export function repositoryOfItem(item: Item): string {
    if (item.sender.party === "conversation") {
        return item.sender.repository;
    }
    if (item.recipient.party === "conversation") {
        return item.recipient.repository;
    }
    return item.reason.reason === "approval" ? (item.reason.repository ?? "") : "";
}

/**
 * Return the parts of `nodes` the position `at` is in, outermost first: an item's own blank line after it counting as
 * the item's, and the review's last lines, after its last group, that group's, as the header over the review has them.
 */
export function chainAt(nodes: readonly Placed[], at: number): Placed[] {
    const found: Placed[] = [];
    let level = nodes;
    for (;;) {
        const holding = level.findLast((each) => at >= each.from && at <= each.to + (each.kind === "item" ? 1 : 0));
        const inside = holding ?? (level === nodes ? level.findLast((each) => each.from <= at) : undefined);
        if (inside === undefined) {
            return found;
        }
        found.push(inside);
        level = inside.children;
    }
}

/** Return the part of `nodes` whose id is `id`, at any depth; none where none is. */
export function findNode(nodes: readonly Placed[], id: string): Placed | undefined {
    for (const each of nodes) {
        if (each.id === id) {
            return each;
        }
        const found = findNode(each.children, id);
        if (found !== undefined) {
            return found;
        }
    }
    return undefined;
}

/** Each part of a layout's tree by its id, the first in the tree's order where two share one, as `findNode` finds it. */
const indexed = new WeakMap<readonly Placed[], Map<string, Placed>>();

/**
 * Return the part of `nodes` whose id is `id`, as `findNode` does, from an index of them made once for each layout: each
 * mark the draft holds is drawn on its part's first line at every layout, and walking the whole tree for each, every
 * file of every "since you approved" among it, grew with the marks times the files.
 */
export function placedBy(nodes: readonly Placed[], id: string): Placed | undefined {
    let index = indexed.get(nodes);
    if (index === undefined) {
        const made = new Map<string, Placed>();
        const walk = (list: readonly Placed[]) => {
            for (const each of list) {
                if (!made.has(each.id)) {
                    made.set(each.id, each);
                }
                walk(each.children);
            }
        };
        walk(nodes);
        indexed.set(nodes, made);
        index = made;
    }
    return index.get(id);
}

/** Return the offers of `offers` answering `verb`. */
function answering(offers: readonly Offer[] | undefined, verb: Verb): Offer[] {
    return (offers ?? []).filter((each) => each.verb === verb.name);
}

/** The request running one of a module's actions (`lup.blocks.ACT`), which a mark of one is applied by. */
export const ACT = "module-act";

/** What a mark of one of a module's actions is given (`Offer.of`, `Offer.of_module`): whose action it is, and what it takes. */
export interface Acting {
    repository: string;
    module: string;
    action: string;
    argument: Marked["argument"];
}

/** Return the marks of `marks` the send asks of a module, in what order: each of its actions, every mark of one together, those that may move the host (`Offer.runs`) last, and one of those at most, the rest held back. */
export function actionsToRun<M extends Pick<Marked, "action" | "argument" | "runs">>(marks: readonly M[]): { run: { key: string; marks: M[]; last: boolean }[]; held: M[] } {
    const acting = new Map<string, { key: string; marks: M[]; last: boolean }>();
    for (const mark of marks.filter((each) => each.action === ACT)) {
        const argument = mark.argument as unknown as Acting;
        const key = JSON.stringify([argument.repository, argument.module, argument.action]);
        const was = acting.get(key) ?? { key, marks: [], last: mark.runs === "last" };
        acting.set(key, { ...was, marks: [...was.marks, mark] });
    }
    const each = [...acting.values()];
    const lasts = each.filter((one) => one.last);
    return { run: [...each.filter((one) => !one.last), ...lasts.slice(0, 1)], held: lasts.slice(1).flatMap((one) => one.marks) };
}

/** The actions of what an item offers (`lup_dev.inbox.store`): an answer marked in one of the draft's lists, and a comment on it whole, which the editor opens. */
const ITEM_MARKED = "inbox-mark";
const ITEM_COMMENTED = "inbox-comment";
const ITEM_SENT = "inbox-send-to";

/**
 * Return what an offer does as an act, marked on `block` at `version`, or run at once on `conversation`: an item's
 * answer, the inbox's own until item kinds' answers are their modules' actions, as the item marked in one of the draft's
 * lists; a comment on an item whole.
 */
function actOf(offer: Offer, block: string, version: string | null, conversation: Conversation | null): Act {
    switch (offer.action) {
        case ITEM_MARKED: {
            const argument = offer.argument as { number: number; list: Listed };
            return { kind: "item", number: argument.number, list: argument.list };
        }
        case ITEM_COMMENTED:
            return { kind: "comment" };
        case ITEM_SENT: {
            const argument = offer.argument as { number: number };
            return { kind: "send", what: { kind: "item", number: argument.number, repository: "" } };
        }
        default:
            return offer.runs === "once" ? { kind: "once", offer, conversation } : { kind: "mark", offer, block, version };
    }
}

/** Return the blocks within `node`, whatever it holds, that offer `verb`, each the outermost that does: what a verb on the whole of it reaches. */
function offering(node: Placed, verb: Verb): Placed[] {
    return node.children.flatMap((child) => {
        if (child.kind === "group") {
            return [];
        }
        if (child.kind === "block" && answering(child.block?.offers, verb).length > 0) {
            return [child];
        }
        return offering(child, verb);
    });
}

/** Return what names a block a verb lands on: a file by its path, a line by its words, a fold by its summary. */
function blockNamed(block: ViewBlock): string {
    switch (block.block) {
        case "diff":
        case "code":
            return block.path;
        case "line":
            // Cut, as the line of keys says it before what each key does: a long line's words would leave no room for them.
            return cutAt((block.spans ?? []).map((each) => each.text).join("").trim(), 48);
        case "fold":
            return block.summary.map((each) => each.text).join("").trim();
        case "markdown":
            return block.text.split("\n")[0] ?? "";
        default:
            return "";
    }
}

/** Return the acts of each block of `blocks` offering `verb`, the first offer of each, on what's of `conversation`. */
function actsOf(blocks: readonly Placed[], verb: Verb, conversation: Conversation | null): Act[] {
    return blocks.flatMap((each) => {
        const offer = answering(each.block?.offers, verb)[0];
        return offer === undefined ? [] : [actOf(offer, each.id, each.block?.version ?? null, conversation)];
    });
}

/**
 * Return where `verb` lands with the cursor at `at` in `laidOut`: the innermost thing it applies to, from the cursor
 * outward (`chainAt`), and what it does there.
 *
 * - **A block** offering it: the file under the cursor in "since you approved" marked reviewed.
 * - **A fold or a drawer** offering it, as a whole: every block within it offering it, each the outermost, so each
 *   shows its mark; or its own offer where none within does.
 * - **An item:** what the host offers on it (`Item.offers`): each answer of its kind while it waits on the operator, as
 *   approving or declining an approval, done marking a note read, send leaving it for later; and a comment on it whole.
 *   One a later item replaced says so (`Item.spent`); any other past waiting goes on outward.
 * - **An agent's group,** on its banner or anywhere in it nothing nearer takes the verb: what its banner's parts offer,
 *   as hold; done marking it seen and reaching its own news and drawers, its subagents' left as they are, and an item
 *   asking something, which marking done would answer, left too; comment a message to it.
 * - **A concern,** on its block: done clearing it, decline declining it, comment writing on it (`concernReach`).
 */
export function reachOf(laidOut: Laid, at: number, verb: Verb, naming: Naming): Reach {
    const chain = chainAt(laidOut.nodes, at);
    const group = (node: Placed) => laidOut.groups.find((each) => `group ${each.place}` === node.id);
    const conversationOf = () => {
        const outer = chain.findLast((each) => each.kind === "group");
        return outer === undefined ? null : (group(outer)?.conversation ?? null);
    };
    // A module's own buffer isn't a drawer of anything: a verb on a line of it offering nothing reaches nothing, rather
    // than every row under it.
    const ownBuffer = chain.some((each) => each.kind === "view" && laidOut.drawers.some((one) => one.view.id === each.id && isNobody(one.conversation)));
    for (const node of chain.toReversed()) {
        switch (node.kind) {
            case "written": {
                const found = writtenReach(laidOut, node, verb);
                if (found !== null) {
                    return found;
                }
                break;
            }
            case "block": {
                const block = node.block;
                if (block === undefined) {
                    break;
                }
                const own = answering(block.offers, verb)[0];
                const within = block.block === "fold" && !ownBuffer ? offering(node, verb) : [];
                if (within.length > 0) {
                    return { on: blockNamed(block), node, says: own?.says ?? verb.called, acts: actsOf(within, verb, conversationOf()) };
                }
                if (own !== undefined) {
                    return { on: blockNamed(block), node, says: own.says, acts: [actOf(own, node.id, block.version ?? null, conversationOf())] };
                }
                break;
            }
            case "view": {
                // An item's body is its item's: the item says what its verbs do.
                const drawer = laidOut.drawers.find((each) => each.view.id === node.id);
                if (drawer === undefined || ownBuffer) {
                    break;
                }
                const own = answering(drawer.view.answer?.blocks.offers, verb)[0];
                const within = offering(node, verb);
                const label = laidOut.text.slice(drawer.header.from, drawer.header.to);
                if (within.length > 0) {
                    return { on: label, node, says: own?.says ?? verb.called, acts: actsOf(within, verb, drawer.conversation) };
                }
                if (own !== undefined) {
                    return { on: label, node, says: own.says, acts: [actOf(own, node.id, null, drawer.conversation)] };
                }
                break;
            }
            case "item": {
                const region = laidOut.regions.find((each) => `item ${each.item.number}` === node.id);
                if (region === undefined) {
                    break;
                }
                const found = itemReach(region, node, verb);
                if (found !== null) {
                    return found;
                }
                break;
            }
            case "frame": {
                const concern = laidOut.concerns.find((each) => !each.dim && `concern ${each.read.thread.number}` === node.id);
                if (concern !== undefined) {
                    const found = concernReach(concern.read, node, verb, naming);
                    if (found !== null) {
                        return found;
                    }
                }
                break;
            }
            case "group": {
                const made = group(node);
                if (made === undefined) {
                    break;
                }
                const found = groupReach(laidOut, node, made, verb, naming);
                if (found !== null) {
                    return found;
                }
                break;
            }
            default:
                break;
        }
    }
    return { on: null, says: null, why: whyNot(verb) };
}

/**
 * Return where `verb` lands on `region`'s item, laid out at `node`: what the host offers on it, each answer of its kind
 * while it waits on the operator and a comment on it whole (`Item.offers`); on one a later item replaced, the host's
 * words on why not, doing nothing (`Item.spent`). None for anything else, the verb going on outward, to the thread or
 * the agent's group it's in, as on its banner.
 */
function itemReach(region: Region, node: Placed, verb: Verb): Reach | null {
    const on = region.named;
    const offered = answering(region.item.offers, verb)[0];
    if (offered !== undefined) {
        const act = actOf(offered, region.body.id, null, null);
        // Sent somewhere, it goes into its own repository's concerns and piles.
        const acts = act.kind === "send" && act.what.kind === "item" ? [{ ...act, what: { ...act.what, repository: repositoryOfItem(region.item) } }] : [act];
        return { on, node, says: offered.says, acts };
    }
    const spent = region.item.spent.find((each) => each.verb === verb.name);
    return spent === undefined ? null : { on, node, says: spent.says, acts: [] };
}

/**
 * Return where `verb` lands on `group`, laid out at `node`: what its banner's parts offer, as hold; done marking it
 * seen where it holds an item new to the operator, each of its own news read, and every block of its drawers offering
 * done, or each drawer whole where none in it does, its subagents' groups left as they are, and each item asking
 * something, a question, an approval or a held change, left and named; comment, a message to its agent. None where
 * nothing of it takes the verb, as on lup's approvals, which no agent is.
 */
function groupReach(laidOut: Laid, node: Placed, group: Group, verb: Verb, naming: Naming): Reach | null {
    const conversation = group.conversation;
    const on = conversation === null ? "lup's approvals" : naming.called(conversation);
    for (const part of group.parts) {
        const offer = answering(part.answer?.blocks.offers, verb)[0];
        if (offer !== undefined) {
            return { on, node, says: offer.says, acts: [actOf(offer, part.id, null, conversation)] };
        }
    }
    switch (verb.name) {
        case CORE.done: {
            // Its own news read, as #263's banner key has it: an item asking something, a question, an approval or a held
            // change, is left alone, since marking it done answers it or approves it, and said.
            const regions = node.children.flatMap((child) => {
                const region = child.kind === "item" ? laidOut.regions.find((each) => `item ${each.item.number}` === child.id) : undefined;
                return region === undefined ? [] : [{ region, child }];
            });
            const items = regions.flatMap(({ region, child }) => {
                const reached = news(region.item) ? itemReach(region, child, verb) : null;
                return reached === null || reached.on === null ? [] : reached.acts;
            });
            const left = leaving(regions.filter(({ region }) => region.item.asks).map(({ region }) => region.item.number));
            // Each drawer's blocks offering done, as the files of "since you approved"; else what the drawer offers as a
            // whole, as a conversation marked read.
            const drawers = group.drawers.flatMap((drawer) => {
                const placed = node.children.find((child) => child.id === drawer.view.id);
                if (placed === undefined) {
                    return [];
                }
                const within = actsOf(offering(placed, verb), verb, drawer.conversation);
                const own = answering(drawer.view.answer?.blocks.offers, verb)[0];
                return within.length > 0 || own === undefined ? within : [actOf(own, placed.id, null, drawer.conversation)];
            });
            // Its group seen, where it holds an item new to the operator: up to the last item the review shows, so
            // what comes after it is new to them, those it leaves among what's seen.
            const newest = Math.max(0, ...laidOut.regions.map((each) => each.item.number));
            const unseen = conversation !== null && regions.some(({ region }) => naming.fresh?.(region.item) === true);
            const seen = unseen && conversation !== null ? [seenAct(conversation, node.id, newest)] : [];
            const acts = [...seen, ...items, ...drawers];
            const what = [
                ...(seen.length === 0 ? [] : ["them seen"]),
                ...(items.length === 0 ? [] : ["their news read"]),
                ...(drawers.length === 0 ? [] : ["their drawers done"]),
            ].join(", ");
            return acts.length === 0 ? null : { on, node, says: `mark ${what}${left.short}`, whole: `mark ${what}${left.whole}`, acts };
        }
        case CORE.comment:
            return conversation === null ? null : { on, node, says: "write to them", acts: [{ kind: "comment" }] };
        default:
            return null;
    }
}

/**
 * Return where `verb` lands on a concern laid out as a block at `node`, the host reading it as `read`: done clears it,
 * settling it, and decline declines it, each the operator's mark, which leaves the agent's as it is and the concerns
 * nested under it as they stand, whatever waits on them in it, each still waiting where it's laid out; one cleared already
 * says so and does nothing. Comment writes on it, to whoever answers for it, or to no one where nobody does. None for
 * what else.
 */
function concernReach(read: ThreadRead, node: Placed, verb: Verb, naming: Naming): Reach | null {
    const on = concernWords(read);
    const cleared = (read.cleared ?? null) !== null;
    switch (verb.name) {
        case CORE.done:
            if (cleared) {
                return { on, node, says: "cleared already", acts: [] };
            }
            return { on, node, says: concernReads(read) === "for your eyes" ? "clear it: it's done" : "clear it", acts: [threadAct(read, node.id, SETTLE)] };
        case CORE.decline:
            if (cleared) {
                return { on, node, says: "cleared already", acts: [] };
            }
            return { on, node, says: "decline it: nothing more will be done", acts: [threadAct(read, node.id, DECLINE)] };
        case CORE.comment: {
            const answering = read.answering ?? null;
            return { on, node, says: answering === null ? "write on it, to no one" : `write on it, to ${naming.called(answering)}`, acts: [{ kind: "comment" }] };
        }
        case CORE.send:
            return { on, node, says: "send it to an agent, under a concern, into a pile or to No agent", acts: [{ kind: "send", what: { kind: "concern", read } }] };
        default:
            return null;
    }
}

/** The host's requests settling and declining a thread, the operator's (`docs/inbox.md`, *Threads in the review*). */
export const SETTLE = "inbox-settle-thread";
export const DECLINE = "inbox-decline-thread";

/**
 * What a mark on a thread does to it, by its action, as the reply says it after the thread's name, `@auth settled`:
 * the host's requests settling and declining it, and the core's review mark on its node, reading it.
 */
const THREAD_DONE = { [SETTLE]: "cleared", [DECLINE]: "declined", "review-mark": "read" } as const;

/** Return an act on thread `read`, shown on its banner, `block`: `action`, the host's, settling or declining it, saying so, `@auth settled`. */
function threadAct(read: ThreadRead, block: string, action: typeof SETTLE | typeof DECLINE): Act {
    const says = partSaid({ kind: "thread", name: cutAt(concernWords(read), 40), done: THREAD_DONE[action] });
    const offer: Offer = { action, argument: { number: read.thread.number }, verb: null, chord: null, runs: "send", commented: false, says };
    return { kind: "mark", offer, block, version: null };
}

/**
 * Return the acts `verb` reaches on each of `folds`, a visual selection's, each from its summary line outward but never
 * past it, so a run of unchanged lines reaches nothing where its file would: each act once, in their order.
 */
export function reachedIn(laidOut: Laid, folds: readonly { summary: { from: number }; to: number }[], verb: Verb, naming: Naming): Act[] {
    const acts = new Map<string, Act>();
    for (const fold of folds) {
        const reach = reachOf(laidOut, fold.summary.from, verb, naming);
        if (reach.on === null || reach.node.from < fold.summary.from || reach.node.to > fold.to + 1) {
            continue;
        }
        for (const act of reach.acts) {
            const key =
                act.kind === "item"
                    ? `item ${act.number} ${act.list}`
                    : act.kind === "mark"
                      ? `mark ${act.block} ${act.offer.action}`
                      : `${act.kind} ${acts.size}`;
            if (!acts.has(key)) {
                acts.set(key, act);
            }
        }
    }
    return [...acts.values()];
}

/** Return whether `act` is marked in `draft` already, by the verb `verb`. */
export function isMarked(draft: Draft, act: Act, verb: string): boolean {
    switch (act.kind) {
        case "item":
            return (draft[act.list] ?? []).includes(act.number);
        case "mark":
            return (draft.marks ?? []).some((each) => each.block === act.block && each.verb === verb && each.action === act.offer.action);
        default:
            return false;
    }
}

/**
 * Return `draft` with what `acts` mark marked by `verb`, or, where each is marked already, unmarked: as a key pressed
 * again undoes what it did. An item is in one of the draft's lists at most: marked done, it's no longer declined nor
 * left for later. Acts that mark nothing, a comment or what runs at once, leave it as it is.
 */
export function marking(draft: Draft, acts: readonly Act[], verb: string): Draft {
    const marks = acts.filter((each) => each.kind === "item" || each.kind === "mark");
    if (marks.length === 0) {
        return draft;
    }
    const unmarking = marks.every((each) => isMarked(draft, each, verb));
    let next = draft;
    for (const act of marks) {
        if (isMarked(next, act, verb) !== unmarking) {
            continue;
        }
        next = act.kind === "item" ? listed(next, act.number, unmarking ? null : act.list) : offered(next, act, verb, unmarking);
    }
    return next;
}

/** Return `draft` with item `number` in `list`, out of the others; or in none, `list` none. An item marked so is sent nowhere. */
export function listed(draft: Draft, number: number, list: Listed | null): Draft {
    const without = (each: Listed) => (draft[each] ?? []).filter((one) => one !== number);
    const put = (each: Listed) => (each === list ? [...without(each), number] : without(each));
    const moves = list === null ? (draft.moves ?? []) : (draft.moves ?? []).filter((each) => each.item !== number);
    return { ...draft, done: put("done"), declined: put("declined"), moves };
}

/**
 * Return `draft` with `what` sent to `to`, as the picker chose, or sent nowhere, `to` none, where it goes where it is:
 * an item into a concern or a pile, marked neither done nor declined then; a concern where it goes; what's written
 * where it's sent. One sent again goes where it was sent last.
 */
export function sentTo(draft: Draft, what: Sendable, to: Destination | null): Draft {
    switch (what.kind) {
        case "item": {
            const others = (draft.moves ?? []).filter((each) => each.item !== what.number);
            return to === null ? { ...draft, moves: others } : { ...listed(draft, what.number, null), moves: [...others, { id: newId(), item: what.number, to }] };
        }
        case "concern": {
            const number = what.read.thread.number;
            const others = (draft.moves ?? []).filter((each) => each.thread !== number);
            return { ...draft, moves: to === null ? others : [...others, { id: newId(), thread: number, to }] };
        }
        case "written": {
            const resent = <W extends Written>(list: readonly W[] | undefined) => (list ?? []).map((each) => (writtenId(each) === what.id ? { ...each, sent: to } : each));
            return { ...draft, comments: resent(draft.comments), letters: resent(draft.letters), remarks: resent(draft.remarks) };
        }
    }
}

/** Return where `draft` sends `what`, as Space s chose; none where it goes where it is. */
export function sentWhere(draft: Draft, what: Sendable): Destination | null {
    switch (what.kind) {
        case "item":
            return itemsSent(draft).get(what.number) ?? null;
        case "concern":
            return concernsSent(draft).get(what.read.thread.number) ?? null;
        case "written": {
            const each = written(draft).find((one) => writtenId(one) === what.id);
            return each === undefined ? null : goesTo(draft, each);
        }
    }
}

/**
 * Return `draft` with the mark `act` makes by `verb` added, or taken away (`unmarking`): added, it replaces the block's
 * mark of the same action by another verb, as a file held at landing is marked reviewed or declined, never both.
 */
function offered(draft: Draft, act: Extract<Act, { kind: "mark" }>, verb: string, unmarking: boolean): Draft {
    // A thread is settled or declined, never both: either marked takes the other's mark off.
    const status = (action: string) => action === SETTLE || action === DECLINE;
    const marks = (draft.marks ?? []).filter(
        (each) =>
            !(each.block === act.block && each.action === act.offer.action && (unmarking ? each.verb === verb : each.verb !== verb)) &&
            !(!unmarking && each.block === act.block && status(act.offer.action) && status(each.action) && each.action !== act.offer.action),
    );
    if (unmarking) {
        return { ...draft, marks };
    }
    const made: Marked = {
        id: newId(),
        action: act.offer.action,
        argument: act.offer.argument ?? {},
        verb,
        says: act.offer.says,
        block: act.block,
        version: act.version,
        ...(act.offer.runs === "last" ? { runs: "last" as const } : {}),
        ...(act.offer.draws == null ? {} : { draws: act.offer.draws }),
    };
    return { ...draft, marks: [...marks, made] };
}

/**
 * Return the marks the operator's comments imply, a comment counting as a review (`Offer.commented`): for each comment
 * or remark written on a block offering what a comment on it implies, as a file of "since you approved" offers marking
 * it reviewed, or a file held at landing offers declining its landing, that offer marked by its verb on the block, at the
 * version the comment was written on, the latest written on it; none where the draft marks the block by that offer's
 * action already, by any verb, the operator's own mark the later word.
 * Shown as the draft's own marks are, and kept in the draft as it's sent, so Ctrl+Enter applies them with the rest.
 */
export function implied(laidOut: Laid, draft: Draft): Marked[] {
    const found = new Map<string, Marked>();
    for (const each of laidOut.written) {
        const quote = "quote" in each ? each.quote : null;
        const block = quote?.block ?? "";
        if (block === "" || each.text.trim() === "") {
            continue;
        }
        const offers = placedBy(laidOut.nodes, block)?.block?.offers ?? [];
        for (const offer of offers) {
            const verb = offer.verb ?? null;
            if (offer.commented !== true || verb === null) {
                continue;
            }
            if ((draft.marks ?? []).some((mark) => mark.block === block && mark.action === offer.action)) {
                continue;
            }
            found.set(`${block} ${offer.action}`, {
                id: `implied ${writtenId(each)}`,
                action: offer.action,
                argument: offer.argument ?? {},
                verb,
                says: offer.says,
                block,
                version: quote?.version ?? null,
            });
        }
    }
    return [...found.values()];
}

/**
 * Return `now`, what the operator's comments imply as the review is laid out (`implied`), with each of `before`, what they
 * implied as it was last laid out, whose comment or thread another buffer has off the screen (`Showing`), so what's sent
 * doesn't depend on which buffer is on screen as it's sent: a mark on a block not laid out now, its comment still in
 * the draft and the draft not marking it itself.
 */
export function carried(before: readonly Marked[], now: readonly Marked[], laidOut: Laid, draft: Draft): Marked[] {
    const named = (mark: Marked) => `${mark.block} ${mark.action}`;
    const ids = new Set(now.map((each) => each.id));
    const places = new Set(now.map(named));
    const said = (each: { text: string }) => each.text.trim() !== "";
    const writtenNow = new Map([...(draft.comments ?? []), ...(draft.letters ?? []), ...(draft.remarks ?? [])].map((each): [string, { text: string }] => [each.id ?? "", each]));
    return [
        ...now,
        ...before.filter((mark) => {
            if (ids.has(mark.id) || places.has(named(mark))) {
                return false;
            }
            const comment = writtenNow.get(mark.id.slice("implied ".length));
            return placedBy(laidOut.nodes, mark.block) === undefined && comment !== undefined && said(comment) && !(draft.marks ?? []).some((each) => each.block === mark.block && each.action === mark.action);
        }),
    ];
}

/** What moving a review mark is given (`MoveMarks`, one of its marks): the repository, the module, its key and how far. */
export interface Moved {
    repository: string;
    module: string;
    key: Record<string, unknown>;
    up_to?: string | null;
    /** What had come by there, as the view showing it said; none reads by when it moved. */
    through?: string | null;
    /** Whether it only goes forward. */
    forward?: boolean;
}

/**
 * Return what the mark `mark` does, as a part of the reply, in the line under the review and once sent: a thread read,
 * settled or declined, by its name as `thread` gives it, as it was marked where it gives none; an agent's group seen,
 * the core's review mark; any other review mark on what its key names, an agent where it names one, as its offer says
 * it (`lup-impl/parser: mark it read`); anything else as its offer says it.
 */
export function markedPart(mark: Marked, called: (conversation: Conversation) => string, thread: (number: number) => string | null): ReplyPart {
    const marked = threadMarked(mark);
    const name = marked === null ? null : thread(marked.number);
    if (marked !== null && name !== null) {
        return { kind: "thread", name, done: marked.done };
    }
    if (mark.action !== "review-mark") {
        return { kind: "said", text: mark.says };
    }
    const argument = mark.argument as unknown as Moved;
    const key = argument.key;
    const agent =
        typeof key.runtime === "string" && typeof key.session === "string"
            ? called({ party: "conversation", repository: argument.repository, runtime: key.runtime, session: key.session, agent: typeof key.agent === "string" ? key.agent : null })
            : null;
    if (argument.module === CORE_MODULE && agent !== null) {
        return { kind: "said", text: `${agent} seen` };
    }
    return { kind: "said", text: agent === null ? mark.says : `${agent}: ${mark.says}` };
}

/** Return the thread `mark` marks, by its number, and what it does to it (`THREAD_DONE`); none where it marks no thread. */
function threadMarked(mark: Marked): { number: number; done: string } | null {
    const argument = mark.argument as { number?: unknown; module?: unknown; key?: { node?: unknown } };
    if ((mark.action === SETTLE || mark.action === DECLINE) && typeof argument.number === "number") {
        return { number: argument.number, done: THREAD_DONE[mark.action] };
    }
    if (mark.action === "review-mark" && argument.module === CORE_MODULE && typeof argument.key?.node === "number") {
        return { number: argument.key.node, done: THREAD_DONE["review-mark"] };
    }
    return null;
}

/** Return the marks of `draft` shown on the block `block`. */
export function marksOn(draft: Draft, block: string): Marked[] {
    return (draft.marks ?? []).filter((each) => each.block === block);
}
