// The review's verbs as one grammar (#247; `docs/dashboard.md`, *The keys*): Space and a verb's key acts on the
// innermost thing it applies to, from the cursor outward, through the tree the review is laid out as (`Laid.nodes`):
// a block offering the verb, as a file of "since you approved" offers done; a drawer, as a whole; an item, its kind's
// view saying what done and decline mean for it, the core marking any item done otherwise; and an agent's group, its
// banner's parts saying what hold means, done reaching the agent's own items and drawers. What a verb reaches is said
// before it's pressed, on the line of keys, in the palette and the stack, from the same walk (`reachOf`).
//
// Only the view changes at once. Everything that reaches an agent or the host is a mark in the draft (`marking`):
// an item done, declined or left for later, the inbox's own; anything else a block offers, recorded as the offer
// (`Marked`), which the page applies as the draft is sent (`App.tsx`). Undone with `u`, as any change to the draft. An
// offer that runs at once (`Offer.runs`), a module's view key, is run as it's pressed. Pure.
import { newId } from "./anchors";
import type { components } from "./generated/api";
import { cited } from "./comments";
import { news, writtenId, type Conversation, type Draft, type Group, type Item, type Laid, type Placed, type Region } from "./review";
import type { Block as ViewBlock, Offer } from "./views";

export type Verb = components["schemas"]["Verb"];
export type Marked = components["schemas"]["Marked"];

/** Which of the draft's lists of items an item is marked in: done, declined, or left for later. */
export type Listed = "done" | "declined" | "parked";

/**
 * One thing a verb does where it lands: an item marked in one of the draft's lists; an offer marked in the draft, on
 * the block it's shown on, at the version that block shows; an offer run at once, on what's of `conversation`; or a
 * comment opened on the thing whole, which the editor opens.
 */
export type Act =
    | { kind: "item"; number: number; list: Listed }
    | { kind: "mark"; offer: Offer; block: string; version: string | null }
    | { kind: "once"; offer: Offer; conversation: Conversation | null }
    | { kind: "comment" };

/** Where a verb lands at the cursor: what it's on, as the line of keys names it, the part of the review it is, what it does there, and its acts; or why nothing there takes it. */
export type Reach = { on: string; node: Placed; says: string; acts: Act[] } | { on: null; says: null; why: string };

/** How the walk names what a verb lands on, an agent by their conversation as it's called, and whether an item is new to the operator, its group not seen since it came (`fresh`): none new where it doesn't say. */
export interface Naming {
    called: (conversation: Conversation) => string;
    fresh?: (item: Item) => boolean;
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

/** What pause, which the runtime adapters declare and nothing offers yet, says wherever it's pressed. */
export const PAUSE_UNBUILT = "not built yet: its host side is designed beside #157";

/**
 * Why nothing takes a verb where nothing at the cursor or around it offers it: the core's say what they apply to;
 * pause, which the runtime adapters declare, isn't built (#157); any other verb is its module's.
 */
function whyNot(verb: Verb): string {
    switch (verb.name) {
        case CORE.done:
            return "nothing here is marked done";
        case CORE.decline:
            return "only an approval, a held change or a file held at landing is declined; a flagged write has landed, and is declined once a landing waits on it";
        case CORE.send:
            return "an item is left for later; sending to an agent or a named pile comes with piles (#312)";
        case CORE.comment:
            return "nothing here takes a comment";
        case "pause":
            return PAUSE_UNBUILT;
        default:
            return `nothing here takes ${verb.called}`;
    }
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

/** Return the offers of `offers` answering `verb`. */
function answering(offers: readonly Offer[] | undefined, verb: Verb): Offer[] {
    return (offers ?? []).filter((each) => each.verb === verb.name);
}

/**
 * Return what an offer does as an act, marked on `block` at `version`, or run at once on `conversation`: an item's
 * answer, the inbox's own until item kinds' answers are their modules' actions, as the item marked done or declined.
 */
function actOf(offer: Offer, block: string, version: string | null, conversation: Conversation | null): Act {
    if (offer.action === "inbox-answer-approval") {
        const argument = offer.argument as { number: number; approved: boolean };
        return { kind: "item", number: argument.number, list: argument.approved ? "done" : "declined" };
    }
    return offer.runs === "once" ? { kind: "once", offer, conversation } : { kind: "mark", offer, block, version };
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
            return (block.spans ?? []).map((each) => each.text).join("").trim();
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
 * - **An item:** what its kind's view offers, as approving or declining an approval; else the core's, done marking it
 *   read, send leaving it for later, comment opening a comment on it whole.
 * - **An agent's group,** on its banner or anywhere in it nothing nearer takes the verb: what its banner's parts offer,
 *   as hold; done marking it seen and reaching its own news and drawers, its subagents' left as they are, and an item
 *   asking something, which marking done would answer, left too; comment a message to it.
 */
export function reachOf(laidOut: Laid, at: number, verb: Verb, naming: Naming): Reach {
    const chain = chainAt(laidOut.nodes, at);
    const group = (node: Placed) => laidOut.groups.find((each) => `group ${each.place}` === node.id);
    const conversationOf = () => {
        const outer = chain.findLast((each) => each.kind === "group");
        return outer === undefined ? null : (group(outer)?.conversation ?? null);
    };
    for (const node of chain.toReversed()) {
        switch (node.kind) {
            case "block": {
                const block = node.block;
                if (block === undefined) {
                    break;
                }
                const own = answering(block.offers, verb)[0];
                const within = block.block === "fold" ? offering(node, verb) : [];
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
                if (drawer === undefined) {
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

/** Return where `verb` lands on `region`'s item, laid out at `node`: what its kind's view offers, else the core's done, send and comment; none where neither takes it. */
function itemReach(region: Region, node: Placed, verb: Verb): Reach | null {
    const on = region.named;
    const number = region.item.number;
    const offered = answering(region.body.answer?.blocks.offers, verb)[0];
    if (offered !== undefined) {
        return { on, node, says: offered.says, acts: [actOf(offered, region.body.id, null, null)] };
    }
    switch (verb.name) {
        case CORE.done:
            return { on, node, says: "mark it read", acts: [{ kind: "item", number, list: "done" }] };
        case CORE.send:
            return { on, node, says: "leave it for later", acts: [{ kind: "item", number, list: "parked" }] };
        case CORE.comment:
            return { on, node, says: "comment on it", acts: [{ kind: "comment" }] };
        default:
            return null;
    }
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
            const left = regions.filter(({ region }) => !news(region.item)).map(({ region }) => cited(region.item.number));
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
            const leaving = left.length === 0 ? "" : `, ${left.join(" ")} left`;
            return acts.length === 0 ? null : { on, node, says: `mark ${what}${leaving}`, acts };
        }
        case CORE.comment:
            return conversation === null ? null : { on, node, says: "write to them", acts: [{ kind: "comment" }] };
        default:
            return null;
    }
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
            const key = act.kind === "item" ? `item ${act.number} ${act.list}` : act.kind === "mark" ? `mark ${act.block} ${act.offer.action}` : `${act.kind} ${acts.size}`;
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
        next = act.kind === "item" ? listed(next, act.number, unmarking ? null : act.list) : offered(next, act as Extract<Act, { kind: "mark" }>, verb, unmarking);
    }
    return next;
}

/** Return `draft` with item `number` in `list`, out of the others; or in none, `list` none. */
export function listed(draft: Draft, number: number, list: Listed | null): Draft {
    const without = (each: Listed) => (draft[each] ?? []).filter((one) => one !== number);
    const put = (each: Listed) => (each === list ? [...without(each), number] : without(each));
    return { ...draft, done: put("done"), declined: put("declined"), parked: put("parked") };
}

/**
 * Return `draft` with the mark `act` makes by `verb` added, or taken away (`unmarking`): added, it replaces the block's
 * mark of the same action by another verb, as a file held at landing is marked reviewed or declined, never both.
 */
function offered(draft: Draft, act: Extract<Act, { kind: "mark" }>, verb: string, unmarking: boolean): Draft {
    const marks = (draft.marks ?? []).filter((each) => !(each.block === act.block && each.action === act.offer.action && (unmarking ? each.verb === verb : each.verb !== verb)));
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
        const offers = findNode(laidOut.nodes, block)?.block?.offers ?? [];
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

/** What moving a review mark is given (`MoveMarks`, one of its marks): the repository, the module, its key and how far. */
export interface Moved {
    repository: string;
    module: string;
    key: Record<string, unknown>;
    up_to?: string | null;
}

/**
 * Say what moving the review mark `mark` does, in the line under the review and once sent: an agent's group seen, the
 * core's; any other on what its key names, an agent where it names one, as its offer says it (`lup-impl/parser: mark it
 * read`).
 */
export function movedSaid(mark: Marked, called: (conversation: Conversation) => string): string {
    const argument = mark.argument as unknown as Moved;
    const key = argument.key;
    const agent =
        typeof key.runtime === "string" && typeof key.session === "string"
            ? called({ party: "conversation", repository: argument.repository, runtime: key.runtime, session: key.session, agent: typeof key.agent === "string" ? key.agent : null })
            : null;
    if (argument.module === CORE_MODULE && agent !== null) {
        return `${agent} seen`;
    }
    return agent === null ? mark.says : `${agent}: ${mark.says}`;
}

/** Return the marks of `draft` shown on the block `block`. */
export function marksOn(draft: Draft, block: string): Marked[] {
    return (draft.marks ?? []).filter((each) => each.block === block);
}
