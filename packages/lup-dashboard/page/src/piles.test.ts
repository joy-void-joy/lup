// Piles and Space s (`docs/dashboard.md`, *The panes*, *The keys*): a concern's block laid out as an item, folded and
// laid out only while it's open; an item moved into one, laid out there and a dim line in its group; `No agent` per
// repository, `Later` last; Space s's choices, by what's sent; and what the reply sends, by where it goes.
import "./fixtures/looks";
import { hosted } from "./fixtures/kinds";
import { describe, expect, it } from "vitest";

import { toSend } from "./App";
import { sentTo, sentWhere } from "./grammar";
import { adopted } from "./looks";
import { listedByAgent, listLaid, type ListReading } from "./panes";
import { choicesFor, sentSaid } from "./picking";
import { EMPTY, laid, noAgent, whose, type Around, type Conversation, type Draft, type Item, type Showing, type ThreadRead, type Threading } from "./review";

const AT = "2026-11-13T12:00:00Z";
const REPOSITORY = "/r/lup.git";
const ELSEWHERE = "/r/zoetrope.git";
const NEWS: Item["rank"] = { name: "news", order: 1, notifies: false };
const WAITING: Item["rank"] = { name: "waiting on you", order: 0, notifies: true };

function from(session: string, agent: string | null = null, repository: string = REPOSITORY): Conversation {
    return { party: "conversation", repository, runtime: "claude", session, agent };
}

const LEAD = from("s1");
const WORKER = from("s1", "a1");
const ZOE = from("z1", null, ELSEWHERE);

function note(number: number, sender: Conversation, text: string, rank: Item["rank"] = NEWS, asks: boolean = false): Item {
    return { ...hosted({ number, reason: { reason: "message", passages: [], answers: [], ending: false, kind: "note", text, to: null }, sender, recipient: { party: "operator" }, replies: [], citations: [], edits: [], quiet: false, made: AT, state: { state: "waiting" }, rank }), asks } as Item;
}

const NOTE = note(52, WORKER, "I assumed UTF-8.");
const ASKS = note(53, WORKER, "Which cache?", WAITING, true);
const BUILT = note(70, LEAD, "Built.");

/** A concern as the host reads it: `number`, titled `title`, of the lead's repository, answered for by `answering`, nobody else; what `read` says beside. */
function concern(number: number, title: string, answering: Conversation | null, read: Partial<ThreadRead> = {}): ThreadRead {
    return {
        thread: { kind: "ledger:thread", number, name: title.toLowerCase().replaceAll(" ", "-"), title, repository: REPOSITORY, by: { party: "operator" }, at: AT, parent: null, holder: answering },
        state: answering === null ? "nobody running" : "working",
        section: "every thread",
        since: AT,
        answering,
        ...read,
    } as ThreadRead;
}

/** `read`, nested under concern `parent`. */
function under(read: ThreadRead, parent: number): ThreadRead {
    return { ...read, thread: { ...read.thread, parent } } as ThreadRead;
}

const NOTHING: Around = { contexts: new Map(), files: new Map(), answers: [], commented: [] };
const called = (party: Conversation) => (party.agent == null ? party.session : `${party.session}/${party.agent}`);
const header = (shown: Item) => `── @${shown.number} ──`;
const banner = (head: { item: Item } | { conversation: Conversation }) => `━━ ${"item" in head ? (head.item.sender.party === "conversation" ? called(head.item.sender) : "lup") : called(head.conversation)} ━━`;
const running = new Map([LEAD, WORKER].map((each) => [whose(each), { launch: "l", holding: false }]));
const NOBODY = noAgent(REPOSITORY);

/** Lay the buffer `showing` out over `concerns`, folds left as `folds` says, none laying everything out. */
function buffer(showing: Showing, concerns: readonly ThreadRead[], items: Item[] = [NOTE, ASKS, BUILT], folds: ReadonlyMap<string, boolean> | null = new Map()) {
    return laid(items, [LEAD, WORKER], banner, header, EMPTY, NOTHING, [], new Map(), called, { showing, running, looks: adopted(), concerns, folds });
}

describe("a concern's block, laid out as an item", () => {
    const LATER = concern(300, "Later", null, { moved: [52] });
    const HELD = concern(301, "The reader", LEAD, { body: { kind: "ledger:body", target: 301, repository: REPOSITORY, by: LEAD, at: AT, text: "It reads." } } as Partial<ThreadRead>);
    const PART = under(concern(302, "The part", LEAD), 301);

    it("folds whole under its header, laid out closed as one line until it opens, what's nested under it waiting with it", () => {
        const out = buffer({ kind: "agent", key: whose(LEAD) }, [HELD, PART]);
        expect(out.text).toContain("§ The reader · s1 · working\nopening…\n");
        expect(out.text).not.toContain("It reads.");
        expect(out.text).not.toContain("The part");
        const [block] = out.concerns;
        expect(block?.fold).toMatchObject({ kind: "concern", closed: true, unlaid: true });
        expect(out.deferred.get("concern 301 concern ")).toBe(true);
        // Opened, what it holds is laid out, what's nested under it a block of its own inside its fold.
        const opened = buffer({ kind: "agent", key: whose(LEAD) }, [HELD, PART], undefined, new Map([["concern 301 concern ", false]]));
        expect(opened.text).toContain("§ The reader · s1 · working\n  It reads.\n  § The part · s1 · working\nopening…\n");
        const [reader, part] = opened.concerns;
        expect(reader?.fold?.to).toBeGreaterThanOrEqual(part?.header.to ?? Infinity);
    });

    it("starts open where it, or one nested under it, wants the operator's eyes", () => {
        const done = under(concern(303, "The done part", LEAD, { reads: "for your eyes", done: { kind: "ledger:done", target: 303, repository: REPOSITORY, by: LEAD, at: AT, to_try: "Try it." } } as Partial<ThreadRead>), 301);
        const out = buffer({ kind: "agent", key: whose(LEAD) }, [HELD, done]);
        expect(out.text).toContain("§ The reader · s1 · working\n  It reads.\n  § The done part · s1 · done, for you to clear\n    done, they say: Try it.\n");
    });

    it("lays an item moved into a pile out in its block in No agent, its agent's group keeping a dim line where it was", () => {
        const party = buffer({ kind: "party", name: NOBODY.name }, [LATER], undefined, null);
        expect(party.text).toContain("§ Later · nobody's\n── @52 ──\nI assumed UTF-8.");
        expect(party.regions.map((each) => each.item.number)).toEqual([52]);
        const worker = buffer({ kind: "agent", key: whose(WORKER) }, [LATER], undefined, null);
        expect(worker.text).toContain("@52 note → Later\n── @53 ──");
        expect(worker.away.map((each) => [each.item.number, each.into.thread.number])).toEqual([[52, 300]]);
        // In a pile nobody answers for, it counts nowhere; nor in what's for the operator, the pile no block there.
        expect([...party.piled]).toEqual([52]);
        const forYou = buffer({ kind: "for you" }, [LATER], undefined, null);
        expect(forYou.concerns).toEqual([]);
        expect(forYou.text).not.toContain("── @52");
    });

    it("lays one holding an item that asks the operator out in what's for them, where someone answers for it", () => {
        const asking = concern(304, "The cache", LEAD, { moved: [53] });
        const out = buffer({ kind: "for you" }, [asking], undefined, null);
        expect(out.concerns.map((each) => each.read.thread.number)).toEqual([304]);
        expect(out.text).toContain("§ The cache · s1 · working\n── @53 ──");
    });

    it("says what landed there that asks or is new, a line each Enter follows to the item, and the passages it came from, Enter following each to what it was on", () => {
        const passages = [{ spot: { node: 90, part: 1 }, words: "Fix the cache.", answer: null, on: 53 }] as ThreadRead["passages"];
        const read = concern(305, "The landed", LEAD, { asks: [{ node: 53, what: "a note", came: AT, holds: false }], new: [52], passages } as Partial<ThreadRead>);
        const out = buffer({ kind: "agent", key: whose(LEAD) }, [read], undefined, null);
        expect(out.text).toContain("  @53 note, asks you\n  @52 note, new\n");
        const [block] = out.concerns;
        expect(block?.items.map((each) => [each.number, out.text.slice(each.from, each.to).trim()])).toEqual([
            [53, "@53 note, asks you"],
            [52, "@52 note, new"],
        ]);
        expect(block?.passages.map((each) => each.passage.on)).toEqual([53]);
        expect(block?.holder?.conversation).toEqual(LEAD);
        expect(out.text.slice(block?.holder?.from, block?.holder?.to)).toBe("s1");
    });
});

describe("No agent, a party per repository", () => {
    it("lists each repository's apart, its piles under it with how much each holds, Later last", () => {
        const later = concern(300, "Later", null, { moved: [52] });
        const followups = concern(306, "Followups", null, { moved: [53] });
        const reading: ListReading = {
            items: [NOTE, ASKS, BUILT],
            draft: EMPTY,
            agents: [LEAD, WORKER],
            parents: new Map([[whose(WORKER), whose(LEAD)]]),
            called,
            banner: (shown) => banner({ item: shown }),
            drawers: new Map(),
            looks: adopted(),
            remote: new Map(),
            running,
            activities: new Map(),
            states: new Map(),
            threads: { read: { kind: "inbox-threads-read", threads: [later, followups], paths: [], working: [] }, landing: new Map() } as Threading,
        };
        const rows = listedByAgent(reading);
        const text = listLaid(rows).text.split("\n");
        const nobody = text.findIndex((each) => each.startsWith("No agent · lup"));
        expect(nobody).toBeGreaterThan(0);
        const followed = text.findIndex((each) => each.trim() === "Followups · 1");
        const last = text.findIndex((each) => each.trim() === "Later · 1");
        expect(nobody < followed && followed < last).toBe(true);
        // Each pile folds what's in it, its rows opening its block on the item.
        const pile = rows.find((each) => each.id === "thread 300");
        expect(pile?.under?.rows.map((each) => [each.id, each.opens])).toEqual([["item 52", { kind: "party", name: NOBODY.name }]]);
        // Moved, an item isn't under its agent's row.
        const worker = rows.find((each) => each.id === `agent ${whose(WORKER)}`);
        expect(worker?.under?.rows.map((each) => each.id) ?? []).not.toContain("item 52");
    });
});

describe("Space s's picker", () => {
    const picking = (concerns: readonly ThreadRead[]) => ({ concerns, agents: [LEAD, WORKER, ZOE], running: new Map([...running, [whose(ZOE), { launch: "z", holding: false }]]), called });
    const READER = concern(301, "The reader", LEAD);
    const PART = under(concern(302, "The part", LEAD), 301);
    const GONE = concern(307, "The gone", LEAD, { cleared: { kind: "ledger:settled" }, reads: "gone" } as Partial<ThreadRead>);

    it("sends an item into a concern or a pile, never to an agent, Later first, a new agent saying it's to come", () => {
        const choices = choicesFor({ kind: "item", number: 52, repository: REPOSITORY }, picking([READER, PART, GONE]), null);
        expect(choices.map((each) => [each.label, each.kind])).toEqual([
            ["Later", "pile, for later"],
            ["The reader", "held by s1"],
            ["The part", "held by s1"],
            ["new agent", "to come with spawn's third piece"],
        ]);
    });

    it("sends a concern to an agent of its repository, under another, never itself or one under it, or to No agent", () => {
        const choices = choicesFor({ kind: "concern", read: READER }, picking([READER, PART]), null);
        expect(choices.map((each) => each.label)).toEqual(["s1", "s1/a1", "Later", "No agent", "new agent"]);
        expect(choices.find((each) => each.label === "s1")?.to).toEqual({ to: LEAD });
        expect(choices.find((each) => each.label === "No agent")?.to).toEqual({});
    });

    it("sends what's written to any agent running, or a concern, offering where it is once it's sent elsewhere", () => {
        const choices = choicesFor({ kind: "written", id: "c1", repository: REPOSITORY }, picking([READER]), { pile: "Later" });
        expect(choices.map((each) => each.label)).toEqual(["where it is", "s1", "s1/a1", "z1", "Later", "The reader", "new agent"]);
        expect(choices[0]?.to).toBeNull();
    });

    it("says where a thing goes on it, as its tag does", () => {
        const at = { concerns: [READER], called };
        expect([sentSaid({ to: WORKER }, at), sentSaid({ thread: 301 }, at), sentSaid({ pile: "Later" }, at), sentSaid({}, at)]).toEqual(["→ s1/a1", "→ The reader", "→ Later", "→ No agent"]);
    });
});

describe("what the reply sends, by where it goes", () => {
    const naming = {
        called: (party: Item["sender"]) => (party.party === "conversation" ? called(party) : "operator"),
        named: (each: Item) => (each.sender.party === "conversation" ? called(each.sender) : "lup"),
        holder: () => null,
        concern: (number: number) => [concern(301, "The reader", LEAD)].find((each) => each.thread.number === number),
        pile: () => undefined,
    };

    it("says what goes where, each with where it reaches, a comment going with the item it's on", () => {
        const sent = sentTo(sentTo(EMPTY, { kind: "item", number: 52, repository: REPOSITORY }, { pile: "Later" }), { kind: "item", number: 53, repository: REPOSITORY }, { thread: 301 });
        const draft: Draft = { ...sent, comments: [{ id: "c1", item: 52, text: "Later, then." }, { id: "c2", item: 70, text: "Go on." }] };
        expect(sentWhere(draft, { kind: "item", number: 53, repository: REPOSITORY })).toEqual({ thread: 301 });
        const parts = toSend(draft, [NOTE, ASKS, BUILT], naming);
        expect(parts.filter((each) => each.kind === "to")).toEqual([
            { kind: "to", who: "Later", what: ["a comment on @52", "@52"], only: { pile: "Later" } },
            { kind: "to", who: "s1", what: ["@53 on The reader", "comments on @70"], only: { to: LEAD } },
        ]);
    });
});
