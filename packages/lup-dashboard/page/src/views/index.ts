// The views the page lays out itself, each named after the module it'll move to (`views.ts`): the core's, lup's
// approvals; the judge's, its items, "since you approved" and its banner part; the agent-facing inbox's items; and the
// runtime adapters' task list and banner part. `Transcripts`' conversation is its own view, asked of the host. And
// where each item's body is: its kind's view, by the module that kind will be (#113, step 4).
import type { components } from "../generated/api";
import { instanceOf, type Answer, type Blocks, type Mounted, type Remote, type Shown, type View } from "../views";
import { BANNER as WORKING, TASKS } from "./adapters";
import { APPROVAL } from "./core";
import { ANSWER, ENDED, FRICTION, HOW_IT_WENT, MESSAGE, QUESTION, REVIEW, STOP, UNRESOLVED } from "./inbox";
import { BANNER as HOLDING, FLAGGED, HELD, SINCE } from "./judge";

type Item = components["schemas"]["Item"];

/** Every view the page lays out itself. */
const PRODUCERS: readonly View<never>[] = [
    APPROVAL,
    HELD,
    FLAGGED,
    SINCE,
    HOLDING,
    MESSAGE,
    QUESTION,
    FRICTION,
    HOW_IT_WENT,
    STOP,
    ENDED,
    UNRESOLVED,
    ANSWER,
    REVIEW,
    TASKS,
    WORKING,
] as readonly View<never>[];

/** Return the producer of `module`'s `view`, where the page lays it out itself; none for a view its module serves. */
export function producerOf(module: string, view: string): View<unknown> | undefined {
    return PRODUCERS.find((each) => each.module === module && each.view === view) as View<unknown> | undefined;
}

/** The view each kind of item's body is, by its reason: its module's and its own name. */
const KINDS: Record<Item["reason"]["reason"], { module: string; view: string }> = {
    approval: { module: "core", view: "approval" },
    held: { module: "judge", view: "held" },
    flagged: { module: "judge", view: "flagged" },
    message: { module: "inbox", view: "message" },
    question: { module: "inbox", view: "question" },
    friction: { module: "inbox", view: "friction" },
    "how it went": { module: "inbox", view: "how_it_went" },
    stop: { module: "inbox", view: "stop" },
    ended: { module: "inbox", view: "ended" },
    unresolved: { module: "inbox", view: "unresolved" },
    answer: { module: "inbox", view: "answer" },
    review: { module: "inbox", view: "review" },
};

/** Return the view `item`'s body is, its kind's. */
export function kindView(item: Item): { module: string; view: string } {
    return KINDS[item.reason.reason];
}

/**
 * Mount `module`'s `view` of `argument`, of `repository`: answered by the page's own producer where there's one, else
 * by what the host last answered of it (`remote`), none before it has.
 */
export function mount(repository: string, module: string, view: string, argument: unknown, shown: Shown, remote: Remote): Mounted {
    const id = instanceOf(repository, module, view, argument);
    const producer = producerOf(module, view);
    const answer = producer !== undefined ? producer.answer(argument as never, shown, repository) : remotely(remote.get(id));
    return { id, repository, module, view, argument, answer };
}

/** Return what the host answered of a remote view as an answer; none before it has. */
function remotely(blocks: Blocks | undefined): Answer | null {
    return blocks === undefined ? null : { blocks };
}
