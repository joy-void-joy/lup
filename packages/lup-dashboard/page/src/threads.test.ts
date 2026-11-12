// What asks the operator and what's only to read, as the overview and the top bar count them, what's read by being on
// screen, and the review as one buffer (`docs/dashboard.md`, *The page*).
import { hosted } from "./fixtures/kinds";
import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import { holdingOn, toSend, waitingOn } from "./App";
import { partSaid } from "./brief";
import { itemStanding, outlineOf } from "./outline";
import { EMPTY, countToRead, laid, UNSEEN, type Around, type Conversation, type Draft, type Item } from "./review";
import { agentNamed } from "./Review";
import { sightsOf } from "./seeing";

const AT = "2026-10-30T12:00:00Z";
const LATER = "2026-10-30T12:05:00Z";
const WAITING: Item["rank"] = { name: "waiting on you", order: 0, notifies: true };
const NEWS: Item["rank"] = { name: "news", order: 1, notifies: false };
const REPOSITORY = "/r/lup.git";

function from(session: string, agent: string | null = null): Conversation {
    return { party: "conversation", repository: REPOSITORY, runtime: "claude", session, agent };
}

const LEAD = from("s1");
const WORKER = from("s1", "a1");

function item(number: number, sender: Conversation, reason: Item["reason"], rank: Item["rank"] = NEWS, made: string = AT): Item {
    return hosted({
        number,
        reason,
        sender,
        recipient: { party: "operator" },
        replies: [],
        citations: [],
        edits: [],
        quiet: false,
        made,
        state: { state: "waiting" },
        rank,
    });
}

function note(number: number, sender: Conversation, text: string, to: Conversation | null = null): Item {
    return item(number, sender, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text, to });
}

const QUESTION = item(
    51,
    WORKER,
    { reason: "question", text: "Which parser?", decisions: [{ text: "pydantic", lean: "yes" }] } as unknown as Item["reason"],
    WAITING,
);
const NOTE = note(47, WORKER, "Two readers, one each.");
const LATE = note(70, WORKER, "Built.");

const NOTHING: Around = { contexts: new Map(), files: new Map(), answers: [], commented: [] };
const header = (shownItem: Item) => `── @${shownItem.number} ──`;
const banner = () => "━━ agent ━━";
const called = (party: Conversation) => (party.agent === null || party.agent === undefined ? party.session : `${party.session}/${party.agent}`);
/** The worker's group as seen up to `number`. */
const seenUpTo = (number: number) => ({ ...UNSEEN, groups: new Map([[JSON.stringify([REPOSITORY, "claude", "s1", "a1"]), number]]) });

describe("what asks the operator, and what's only to read, in the overview and the top bar", () => {
    const reading = (draft: Draft = EMPTY) => ({ draft, seeing: UNSEEN, states: new Map(), called });

    it("says so of each item, by the host's asks, a seen one saying neither", () => {
        const out = laid([QUESTION, LATE], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called);
        const rows = outlineOf(out, reading());
        expect(rows.find((each) => each.text.startsWith("@51"))?.marks).toEqual(["waiting"]);
        const seen = seenUpTo(70);
        const region = out.regions.find((each) => each.item.number === 70);
        expect(region === undefined ? null : itemStanding(region, EMPTY, UNSEEN).marks).toEqual(["news"]);
        expect(region === undefined ? null : itemStanding(region, EMPTY, seen).marks).toEqual([]);
        // What a kind asks is the host's word, whatever its rank says.
        const asking = { ...LATE, asks: true } as Item;
        expect(region === undefined ? null : itemStanding({ ...region, item: asking }, EMPTY, seen).marks).toEqual(["asking"]);
        expect(region === undefined ? null : itemStanding({ ...region, item: { ...asking, holds: true } }, EMPTY, seen).marks).toEqual(["waiting"]);
    });

    it("counts an agent's own apart", () => {
        const out = laid([QUESTION, LATE, NOTE], [WORKER], banner, header, EMPTY, NOTHING, [], new Map(), called);
        const row = outlineOf(out, reading()).find((each) => each.kind === "agent");
        expect(row?.counts).toEqual({ holds: 1, flagged: 0, review: 0, toRead: 2 });
        const later = outlineOf(out, reading({ ...EMPTY, parked: [51], done: [47] })).find((each) => each.kind === "agent");
        expect(later?.counts).toEqual({ holds: 0, flagged: 0, review: 0, toRead: 1 });
    });

    it("counts what's only to read", () => {
        const felt = item(83, LEAD, { reason: "how it felt", text: "Fine." } as unknown as Item["reason"]);
        const items = [QUESTION, LATE, felt];
        expect(countToRead(items, EMPTY, UNSEEN)).toBe(2);
        expect(countToRead(items, EMPTY, { ...UNSEEN, commented: new Set([70]) })).toBe(1);
    });

    it("counts what waits on the operator, what's left for later not among it: they said not now", () => {
        const approval = { ...QUESTION, number: 54, sender: { party: "operator" } } as Item;
        expect(waitingOn([QUESTION, approval])).toBe(2);
        expect(waitingOn([QUESTION, approval], [approval.number])).toBe(1);
    });

    it("says of what it counts what holds something stopped, the rest wanting the operator's eyes alone", () => {
        const flagged = { ...QUESTION, number: 54, asks: true, holds: false } as Item;
        expect(holdingOn([QUESTION, flagged])).toBe(1);
        expect(holdingOn([QUESTION, flagged], [QUESTION.number])).toBe(0);
        expect(waitingOn([QUESTION, flagged])).toBe(2);
    });
});

describe("what's read by being on screen", () => {
    const out = () => laid([LATE], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called);

    it("reads an agent's group by its own mark", () => {
        const [sight] = sightsOf(out(), UNSEEN, EMPTY, new Map());
        expect(sight?.moves).toEqual({ repository: REPOSITORY, module: "core", key: { runtime: "claude", session: "s1", agent: "a1" }, up_to: "70", forward: true, seen: true });
        // Seen since it came, it's no longer new, and nothing's left to read of it.
        expect(sightsOf(out(), seenUpTo(70), EMPTY, new Map())).toEqual([]);
    });

    it("leaves what the draft marks to the draft, and holds the mark back from what holds their words", () => {
        expect(sightsOf(out(), UNSEEN, { ...EMPTY, done: [70] }, new Map()).some((each) => each.id === "item 70")).toBe(false);
        const written = { ...EMPTY, comments: [{ id: "c1", item: 70, quote: null, text: "Why?" }] } as unknown as Draft;
        expect(sightsOf(out(), UNSEEN, written, new Map()).find((each) => each.id === "item 70")?.held).toBe(true);
    });
});

describe("where what's written goes, on the line under the review", () => {
    it("says where each message on a concern goes, by what it's called", () => {
        const draft = {
            ...EMPTY,
            letters: [
                { id: "m1", to: WORKER, thread: 307, text: "It still lags." },
                { id: "m2", to: null, thread: 303, text: "A note to myself." },
            ],
        };
        const naming = { called: (party: Item["sender"]) => (party.party === "operator" ? "you" : called(party)), named: () => "", holder: () => null, thread: (number: number) => (number === 307 ? "The voice" : "The auth") };
        expect(toSend(draft, [], naming).map(partSaid)).toEqual(["to s1/a1: a message on The voice", "to no one: a message on The auth"]);
    });
});

describe("the review as one buffer", () => {
    it("goes from an agent's name on a line to their own views with gd", () => {
        const out = laid([QUESTION], [LEAD, WORKER], (head) => ("item" in head && head.item.sender.party === "conversation" ? `━━ lup · ${called(head.item.sender)} ━━` : "━━ agent ━━"), header, EMPTY, NOTHING, [], new Map(), called);
        const named = out.groups.find((each) => each.conversation === WORKER || (each.conversation?.agent ?? null) === "a1");
        const line = out.text.slice(named?.banner.from ?? 0, named?.banner.to ?? 0);
        const at = (named?.banner.from ?? 0) + line.indexOf("s1/a1") + 2;
        expect(agentNamed(out, at, called)?.conversation).toEqual(WORKER);
        expect(agentNamed(out, named?.banner.from ?? 0, called)).toBeUndefined();
    });
});
