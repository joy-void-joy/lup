// What the host says of an item of each kind (`kinds.json`, which the dashboard's Python tests hold to its table of
// kinds, `lup_dev.inbox.store.kind_of`): what the page's tests give the items they lay out, so what a key does in them is
// what it does on the host's, with no table of the test's own beside it.
import type { components } from "../generated/api";
import declared from "./kinds.json";

type Item = components["schemas"]["Item"];

/** What the host says of one kind of item, from one party, standing one way. */
export interface Said {
    reason: string;
    kind: string | null;
    to: boolean;
    sender: string;
    recipient: string;
    state: string;
    asks: boolean;
    holds: boolean;
    offers: Item["offers"];
    spent: Item["spent"];
}

/** Each kind, by party and standing. */
export const KINDS = declared as unknown as Said[];

/** An item as a test writes it: all but what the host says of it. */
export type Written = Omit<Item, "asks" | "holds" | "offers" | "spent"> & Partial<Pick<Item, "asks" | "holds" | "offers" | "spent">>;

/** Say which of a message's kinds a kind's rows are of: a copy of one between agents, whichever kind it is, or its own kind; none for what's no message. */
function asking(kind: string | null, to: boolean): string | null {
    return to ? "copy" : kind;
}

/**
 * Return `item` with what the host says of it, numbered as it is: whether it asks, whether it holds, its offers, each answer of its kind
 * while it waits on the operator, and what's spent on one replaced, by the row of `kinds.json` of its kind and sender.
 */
export function hosted(item: Written): Item {
    const reason = item.reason;
    const message = asking("kind" in reason && typeof reason.kind === "string" ? reason.kind : null, "to" in reason && reason.to != null);
    const of = (sender: string, state: string) => KINDS.find((each) => each.reason === reason.reason && asking(each.kind, each.to) === message && each.sender === sender && each.recipient === "operator" && each.state === state);
    const found = of(item.sender.party, "waiting");
    if (found === undefined) {
        throw new Error(`no row of kinds.json is an item like ${JSON.stringify([reason.reason, message, item.sender.party])}`);
    }
    const state = item.state?.state ?? "waiting";
    const waits = item.recipient.party === "operator" && state === "waiting";
    const answered = found.offers.some((each) => each.verb !== "comment");
    const by = item.state?.state === "superseded" ? item.state.by : 9;
    const named = <T>(each: T) => JSON.parse(JSON.stringify(each).replaceAll('"number":7', `"number":${item.number}`).replaceAll("@9", `@${by}`)) as T;
    return {
        ...item,
        asks: waits && found.asks,
        holds: waits && found.holds,
        offers: named(waits ? found.offers : found.offers.filter((each) => each.verb === "comment")),
        spent: state === "superseded" && answered ? named(of("conversation", "superseded")?.spent ?? []) : [],
    };
}
