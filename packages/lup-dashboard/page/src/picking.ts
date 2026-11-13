// Where Space s sends a thing (`docs/dashboard.md`, *The keys*; `docs/inbox.md`, *Threads in the review*): the choices its
// picker offers, by what's sent. An item goes into a concern or a pile; a concern to an agent, who then holds it, under
// another concern, into a pile, or to `No agent`, nobody holding it; what the operator wrote to an agent, a concern or a
// pile. Nothing moves until Ctrl+Enter: a choice is kept in the draft (`sentTo`, `grammar.ts`). Pure: `Picker.tsx`
// draws it.
import type { Sendable } from "./grammar";
import { concernReads, concernWords, LATER, whose, type Conversation, type Destination, type ThreadRead } from "./review";

/** One choice of the picker: what names it, what it says, what it is, and where it sends the thing, or none for where it is, or `unbuilt` for a choice still to come. */
export interface Choice {
    /** What names it among the others, which the picker filters by what's typed. */
    key: string;
    label: string;
    /** What it is, said after it, muted: `agent`, `held by dev/parser`, `pile`. */
    kind: string;
    to: Destination | null | "unbuilt";
}

/** What the picker reads: every concern as the host reads it, the agents the review names, who's running, and how each agent is called. */
export interface Picking {
    concerns: readonly ThreadRead[];
    agents: readonly Conversation[];
    running: ReadonlyMap<string, unknown>;
    called: (party: Conversation) => string;
}

/** Return the repository `what` is of, whose concerns and piles it goes to: a concern's own; what's given else. */
export function repositoryOf(what: Sendable): string {
    return what.kind === "concern" ? what.read.thread.repository : what.repository;
}

/**
 * Return the concerns `what` may go into or under, of its repository: each open to the operator, not gone nor cleared,
 * that's no thing the host says is nothing to list; for a concern, never itself nor one nested under it, which the host
 * would refuse as a loop.
 */
function placesFor(what: Sendable, concerns: readonly ThreadRead[]): ThreadRead[] {
    const repository = repositoryOf(what);
    const byNumber = new Map(concerns.map((each) => [each.thread.number, each]));
    const under = (read: ThreadRead, number: number): boolean => {
        for (let at: ThreadRead | undefined = read; at !== undefined; at = byNumber.get(at.thread.parent ?? -1)) {
            if (at.thread.number === number) {
                return true;
            }
        }
        return false;
    };
    return concerns.filter(
        (each) =>
            each.thread.repository === repository &&
            each.bare !== true &&
            (each.cleared ?? null) === null &&
            concernReads(each) !== "gone" &&
            !(what.kind === "concern" && under(each, what.read.thread.number)),
    );
}

/**
 * Return the choices the picker offers for `what`, in order, `sent` where the draft sends it already: leaving it where it
 * is, where it's sent somewhere; each agent running it may go to, a concern of its own repository's, what's written any's;
 * `Later`; each concern of its repository it may go into or under, by its words, saying who holds it or that it's a pile;
 * `No agent`, for a concern; and a new agent, which spawn's third piece builds. A new pile by what's typed is the
 * picker's own (`Picker.tsx`).
 */
export function choicesFor(what: Sendable, picking: Picking, sent: Destination | null): Choice[] {
    const repository = repositoryOf(what);
    const stay: Choice[] = sent === null ? [] : [{ key: "where it is", label: "where it is", kind: "send it nowhere", to: null }];
    const agents: Choice[] =
        what.kind === "item"
            ? []
            : picking.agents
                  .filter((each) => picking.running.has(whose(each)) && (what.kind === "written" || each.repository === repository))
                  .map((each) => ({ key: `agent ${whose(each)}`, label: picking.called(each), kind: what.kind === "concern" ? "agent, who holds it" : "agent", to: { to: each } }));
    const places = placesFor(what, picking.concerns);
    const pile = (read: ThreadRead) => (read.answering ?? null) === null;
    const later = places.some((each) => pile(each) && (each.thread.parent ?? null) === null && each.thread.title === LATER);
    const concerns: Choice[] = places
        .filter((each) => !(later && pile(each) && (each.thread.parent ?? null) === null && each.thread.title === LATER))
        .map((each) => {
            const answering = each.answering ?? null;
            return { key: `concern ${each.thread.number}`, label: concernWords(each), kind: answering === null ? "pile" : `held by ${picking.called(answering)}`, to: { thread: each.thread.number } };
        });
    return [
        ...stay,
        ...agents,
        { key: "pile later", label: LATER, kind: "pile, for later", to: { pile: LATER } },
        ...concerns,
        ...(what.kind === "concern" ? [{ key: "no agent", label: "No agent", kind: "nobody holding it, at the top", to: {} }] : []),
        { key: "new agent", label: "new agent", kind: "to come with spawn's third piece", to: "unbuilt" as const },
    ];
}

/** Say where `to` sends a thing, as its tag on the thing says it, `→ dev/parser`, `→ Later`, by what `picking` knows. */
export function sentSaid(to: Destination, picking: Pick<Picking, "concerns" | "called">): string {
    if (to.to != null) {
        return `→ ${picking.called(to.to)}`;
    }
    if (to.thread != null) {
        const read = picking.concerns.find((each) => each.thread.number === to.thread);
        return `→ ${read === undefined ? `@${to.thread}` : concernWords(read)}`;
    }
    return `→ ${to.pile ?? "No agent"}`;
}
