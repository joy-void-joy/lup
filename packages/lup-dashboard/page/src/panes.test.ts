// The review in panes (`docs/dashboard.md`, *The review*): each buffer a subset of the one layout, what's written kept
// and followed as another is on screen, and the list.
import "./fixtures/looks";
import { hosted } from "./fixtures/kinds";
import { describe, expect, it } from "vitest";

import { carried, implied, reachOf, type Marked, type Verb } from "./grammar";
import { adopted } from "./looks";
import { instanceOf, type Blocks, type Fold, type Line } from "./views";
import type { Merged } from "./looks";
import { arrivalIn, bufferKey, bufferSpans, listLaid, listedByAgent, nearestShown, panesAsked, pathTo, rowAt, spanAt, titled, type ListReading, type Row } from "./panes";
import { withWrittenDuring, EMPTY, NO_AGENT, PARTIES, aboutAt, checkOwner, followedFrom, groupAt, laid, opened, whose as whoseOf, type Around, type Conversation, type Draft, type Drawers, type Item, type Laid, type OwnedCheck, type Party, type Showing, type ThreadRead, type ThreadShown, type Threading } from "./review";
import { partyNamed, threadBanner } from "./Review";

const AT = "2026-10-30T12:00:00Z";
const WAITING: Item["rank"] = { name: "waiting on you", order: 0, notifies: true };
const NEWS: Item["rank"] = { name: "news", order: 1, notifies: false };
const REPOSITORY = "/r/lup.git";

function from(session: string, agent: string | null = null): Conversation {
    return { party: "conversation", repository: REPOSITORY, runtime: "claude", session, agent };
}

const LEAD = from("s1");
const WORKER = from("s1", "a1");
const GONE = from("s2");

function item(number: number, sender: Conversation, reason: Item["reason"], rank: Item["rank"] = NEWS): Item {
    return hosted({ number, reason, sender, recipient: { party: "operator" }, replies: [], citations: [], edits: [], quiet: false, made: AT, state: { state: "waiting" }, rank });
}

function note(number: number, sender: Conversation, text: string): Item {
    return item(number, sender, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text, to: null });
}

const QUESTION = item(51, WORKER, { reason: "question", text: "Which parser?", decisions: [{ text: "pydantic", lean: "yes" }] } as unknown as Item["reason"], WAITING);
const LEADS = note(70, LEAD, "Built.");
const LEFT = note(80, GONE, "What the one who ended left.");
const ITEMS = [QUESTION, LEADS, LEFT];

const DONE_VERB = { name: "done", key: "d", called: "done" } as Verb;
const NOTHING: Around = { contexts: new Map(), files: new Map(), answers: [], commented: [] };
const called = (party: Conversation) => (party.agent === null || party.agent === undefined ? party.session : `${party.session}/${party.agent}`);
const header = (shown: Item) => `── @${shown.number} ──`;
const banner = (head: { item: Item } | { conversation: Conversation }) => `━━ ${"item" in head ? (head.item.sender.party === "conversation" ? called(head.item.sender) : "lup") : called(head.conversation)} ━━`;

/** The conversations running, by what the layout names them by. */
function running(...conversations: Conversation[]): ReadonlyMap<string, { launch: string; holding: boolean }> {
    return new Map(conversations.map((each) => [whoseOf(each), { launch: "l", holding: false }]));
}

function buffer(showing: Showing | null, draft: Draft = EMPTY, previous: Laid | null = null, items: Item[] = ITEMS): Laid {
    return laid(items, [LEAD, WORKER], banner, header, draft, NOTHING, [], new Map(), called, { showing, previous, running: running(LEAD, WORKER), looks: adopted() });
}

function reading(draft: Draft = EMPTY): ListReading {
    return {
        items: ITEMS,
        draft,
        agents: [LEAD, WORKER],
        parents: new Map([[whoseOf(WORKER), whoseOf(LEAD)]]),
        called,
        banner: (shown) => banner({ item: shown }),
        drawers: new Map(),
        looks: adopted(),
        remote: new Map(),
        running: running(LEAD, WORKER),
        activities: new Map(),
        states: new Map([
            [whoseOf(LEAD), "calling"],
            [whoseOf(WORKER), "idle"],
        ]),
        threads: null,
    };
}

describe("the page's address", () => {
    it("opens in panes, and as one buffer where it asks that", () => {
        expect(panesAsked("")).toBe(true);
        expect(panesAsked("?panes=off")).toBe(false);
        // An address from when the review could go by thread opens it as it opens.
        expect(panesAsked("?panes=threads")).toBe(true);
        expect(panesAsked("?threads")).toBe(true);
    });
});

describe("one buffer at a time", () => {
    it("lays out an agent's own buffer: theirs alone, nobody nested under them, what's written to them last", () => {
        const out = buffer({ kind: "agent", key: whoseOf(LEAD) });
        expect(out.groups.map((each) => called(each.conversation as Conversation))).toEqual(["s1"]);
        expect(out.regions.map((each) => each.item.number)).toEqual([70]);
        const lines = out.text.trimEnd().split("\n");
        expect(lines.at(-1)).toBe("── to s1 ──");
    });

    it("lays out what's for the operator: each group with an item", () => {
        const out = buffer({ kind: "for you" });
        expect(out.regions.map((each) => each.item.number).toSorted()).toEqual([51, 70, 80]);
        const quiet = laid([LEFT], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { showing: { kind: "for you" }, looks: adopted() });
        expect(quiet.groups.map((each) => called(each.conversation as Conversation))).toEqual(["s2"]);
    });

    it("never looks empty while anyone's at work: nothing for the operator, each agent running under a line, their banner alone", () => {
        const out = laid([], [LEAD, WORKER], banner, header, EMPTY, NOTHING, [], new Map(), called, { showing: { kind: "for you" }, running: running(LEAD, WORKER), looks: adopted(), parents: new Map([[whoseOf(WORKER), whoseOf(LEAD)]]) });
        const lines = out.text.trimEnd().split("\n");
        expect(lines[0]).toBe("Nothing waits on you.");
        expect(lines[1]).toContain("also running · 2");
        expect(out.groups.map((each) => called(each.conversation as Conversation))).toEqual(["s1", "s1/a1"]);
        expect(out.drawers).toEqual([]);
    });

    it("says so where nothing's for the operator and nobody's running, or until what's there is read", () => {
        const quiet = laid([], [], banner, header, EMPTY, NOTHING, [], new Map(), called, { showing: { kind: "for you" }, looks: adopted() });
        expect(quiet.text.trimEnd()).toBe("Nothing waits on you, and nobody's running.");
        const reading = laid([], [], banner, header, EMPTY, NOTHING, [], new Map(), called, { showing: { kind: "for you" }, looks: adopted(), read: false });
        expect(reading.text.trimEnd()).toBe("Reading what's there…");
    });

    it("says why an agent's buffer has no conversation, under their banner and over what's written to them", () => {
        const out = buffer({ kind: "agent", key: whoseOf(LEAD) });
        expect(out.text).toContain("Reading their conversation…");
    });

    it("says something of a buffer whose agent's gone from what's read", () => {
        const out = buffer({ kind: "agent", key: "nobody" });
        expect(out.text.trimEnd()).toBe("Nothing here now: the list beside this says what there is.");
    });

    it("shows each agent's drawers in what's for the operator, whether or not they have items", () => {
        const drawers = new Map([
            [whoseOf(LEAD), { tasks: [{ id: "1", subject: "Build it", status: "in_progress" }], usage: null, since: null }],
            [whoseOf(WORKER), { tasks: [{ id: "1", subject: "Read it", status: "in_progress" }], usage: null, since: null }],
        ]) as unknown as Drawers;
        const out = laid([QUESTION], [LEAD, WORKER], banner, header, EMPTY, NOTHING, [], drawers, called, { showing: { kind: "for you" }, running: running(LEAD, WORKER), looks: adopted() });
        expect(out.drawers.map((each) => [called(each.conversation), each.kind])).toEqual([
            ["s1/a1", "tasks"],
            ["s1", "tasks"],
        ]);
        // Folded: a line each.
        expect(out.drawers.every((each) => each.folds.some((fold) => fold.kind === each.kind && fold.closed))).toBe(true);
    });

    it("lays out what nobody running answers under No agent", () => {
        const out = buffer({ kind: "party", name: "no agent" });
        expect(out.regions.map((each) => each.item.number)).toEqual([80]);
    });

    it("lays out nothing but the review whole, without a buffer", () => {
        const whole = buffer(null);
        expect(whole.groups).toHaveLength(3);
        expect(whole.text.split("\n").filter((each) => each.startsWith("── to "))).toEqual([]);
    });

    it("writes to an agent from their buffer's last line, under it, and goes back there", () => {
        const out = buffer({ kind: "agent", key: whoseOf(LEAD) });
        const writing = out.groups[0]?.writing;
        expect(writing).toBeDefined();
        const letter = opened(out, writing?.from ?? 0);
        expect(letter).toEqual({ id: "", to: LEAD, text: "" });
        const draft: Draft = { ...EMPTY, letters: [{ id: "m1", to: LEAD, text: "Go on." }] };
        const written = buffer({ kind: "agent", key: whoseOf(LEAD) }, draft);
        expect(written.text.trimEnd().split("\n").slice(-2)).toEqual(["── to s1 ──", "Go on."]);
        const block = written.groups[0]?.blocks[0];
        expect(block).toBeDefined();
        expect(groupAt(written, block?.from ?? 0)?.conversation).toEqual(LEAD);
        expect(aboutAt(written, { id: "m1", to: LEAD, text: "Go on." }, block ?? { comment: "", from: 0, to: 0 })).toBe(written.groups[0]?.writing?.from);
    });

    it("leaves what's written on what's off the screen in the draft, as it was", () => {
        const draft: Draft = { ...EMPTY, comments: [{ id: "c1", item: 51, quote: null, text: "Pydantic." }] };
        const off = buffer({ kind: "agent", key: whoseOf(LEAD) }, draft);
        expect(off.text).not.toContain("Pydantic.");
        expect(off.written).toEqual(draft.comments);
        expect(off.converted).toBeNull();
        const on = buffer({ kind: "agent", key: whoseOf(WORKER) }, draft);
        expect(on.text).toContain("Pydantic.");
    });

    it("follows a comment from where it was seated while another buffer was on screen", () => {
        const text = ["One.", "Two.", "Three."].join("\n");
        const long = note(90, LEAD, text);
        const quote = { text: "Two.", block: `inbox message {"number":90} `, version: "", line: 1, lines: ["Two."], start: 0, end: 4 };
        const first = buffer({ kind: "agent", key: whoseOf(LEAD) }, EMPTY, null, [long]);
        const block = [...first.lines.keys()].find((each) => each.includes("90")) ?? "";
        const draft: Draft = { ...EMPTY, comments: [{ id: "c1", item: 90, quote: { ...quote, block, version: first.lines.get(block)?.version ?? "" }, text: "On two." }] };
        const seated = buffer({ kind: "agent", key: whoseOf(LEAD) }, draft, null, [long]);
        const away = buffer({ kind: "agent", key: whoseOf(WORKER) }, draft, seated, [long]);
        // Laid out on another buffer, it isn't seated there, and what's followed still knows where it was.
        expect(away.seated.has("c1")).toBe(false);
        const followed = followedFrom(followedFrom(null, seated), away);
        expect(followed.seated.get("c1")?.first).toBe(1);
        expect(followed.lines.has(block)).toBe(true);
    });

    it("never lets a block not laid out say where a comment was", () => {
        const was = { seated: new Map([["c1", { block: "b", version: "v1", first: 3, last: 3, outdated: false }]]), lines: new Map([["b", { version: "v1", lines: ["a", "b", "c", "d"] }]]) } as unknown as Parameters<typeof followedFrom>[0];
        const now = { seated: new Map([["c1", { block: "b", version: "", first: 0, last: 0, outdated: true }]]), lines: new Map() } as unknown as Laid;
        expect(followedFrom(was, now).seated.get("c1")?.first).toBe(3);
    });

    it("lands a buffer first opened on what's to answer, else on its last line", () => {
        const asking = buffer({ kind: "agent", key: whoseOf(WORKER) });
        expect(arrivalIn(asking, EMPTY)).toBe(asking.regions[0]?.header.from);
        const told = buffer({ kind: "agent", key: whoseOf(LEAD) });
        expect(arrivalIn(told, EMPTY)).toBe(told.groups[0]?.writing?.from);
    });

    it("names each buffer apart, which the cursor's kept by", () => {
        const keys = [{ kind: "for you" }, { kind: "party", name: "no agent" }, { kind: "agent", key: "a" }, { kind: "agent", key: "b" }, { kind: "thread", number: 1 }, { kind: "thread", number: 2 }] as Showing[];
        expect(new Set(keys.map(bufferKey)).size).toBe(keys.length);
    });
});

describe("what a comment implies, as another buffer is on screen", () => {
    const mark = (id: string, block: string): Marked => ({ id, action: "policy-review-since", argument: {}, verb: "done", says: "mark it reviewed", block, version: null });

    it("keeps a mark whose block is off the screen while its comment's in the draft", () => {
        const out = buffer({ kind: "agent", key: whoseOf(LEAD) });
        const draft: Draft = { ...EMPTY, remarks: [{ id: "r1", to: LEAD, quote: { text: "x", block: "off", version: "v", line: 0, lines: ["x"], start: 0, end: 1 }, text: "On x." }] };
        const off = mark("implied r1", "off");
        expect(carried([off], [], out, draft)).toEqual([off]);
        // Its comment gone, or emptied, the mark goes with it.
        expect(carried([off], [], out, EMPTY)).toEqual([]);
        // The draft marking it itself takes it over.
        expect(carried([off], [], out, { ...draft, marks: [off] })).toEqual([]);
    });

    it("lets a block on the screen say for itself", () => {
        const out = buffer({ kind: "agent", key: whoseOf(LEAD) });
        const onIt = mark("implied r1", out.nodes[0]?.id ?? "");
        const draft: Draft = { ...EMPTY, remarks: [{ id: "r1", to: LEAD, quote: { text: "x", block: "off", version: "v", line: 0, lines: ["x"], start: 0, end: 1 }, text: "On x." }] };
        expect(carried([onIt], implied(out, draft), out, draft).filter((each) => each.id === "implied r1")).toEqual([]);
    });
});

describe("the list by agent", () => {
    const rows = () => listedByAgent(reading());

    it("nests each item under its sender, marked as the overview marks it, what asks open, the rest folded until their own buffer's on screen", () => {
        const worker = rows().find((each) => each.id === `agent ${whoseOf(WORKER)}`);
        expect(worker?.under?.closed).toBe(false);
        const lead = rows().find((each) => each.id === `agent ${whoseOf(LEAD)}`);
        expect(lead?.under?.closed).toBe(true);
        const opened = listedByAgent({ ...reading(), showing: { kind: "agent", key: whoseOf(LEAD) } }).find((each) => each.id === `agent ${whoseOf(LEAD)}`);
        expect(opened?.under?.closed).toBe(false);
        expect(listLaid(rows()).text).toContain("◆ @51 question new Which parser?");
        expect(listLaid(rows()).text).toContain("• @70 note");
        expect(lead?.under?.rows[0]?.node).toBe(70);
        expect(lead?.under?.rows[0]?.opens).toEqual({ kind: "agent", key: whoseOf(LEAD) });
    });

    it("finds the rows holding a row, outermost first", () => {
        expect(pathTo(rows(), "item 70")?.map((each) => each.id)).toEqual([`agent ${whoseOf(LEAD)}`, "item 70"]);
        expect(pathTo(rows(), "nothing")).toBeNull();
    });

    it("opens a nest for what asks and the agent on screen alone: what's for the operator on screen, or another's, opens none", () => {
        const lead = (showing?: Showing) => listedByAgent({ ...reading(), ...(showing === undefined ? {} : { showing }) }).find((each) => each.id === `agent ${whoseOf(LEAD)}`);
        expect(lead()?.under?.closed).toBe(true);
        expect(lead({ kind: "for you" })?.under?.closed).toBe(true);
        expect(lead({ kind: "agent", key: whoseOf(WORKER) })?.under?.closed).toBe(true);
        expect(lead({ kind: "agent", key: whoseOf(LEAD) })?.under?.closed).toBe(false);
    });

    it("shows what's in a closed nest on the nearest row showing, and what's showing on its own", () => {
        const lead = `agent ${whoseOf(LEAD)}`;
        const closed = (row: Row) => row.id !== lead && row.id !== `agent ${whoseOf(WORKER)}`;
        expect(nearestShown(rows(), "item 70", closed)?.id).toBe(lead);
        expect(nearestShown(rows(), "item 70", () => false)?.id).toBe("item 70");
        expect(nearestShown(rows(), lead, closed)?.id).toBe(lead);
        expect(nearestShown(rows(), "nothing", closed)).toBeUndefined();
    });

    it("says which row the second pane's cursor is on, the deepest it knows", () => {
        const out = buffer({ kind: "for you" });
        const spans = bufferSpans(out, { kind: "for you" });
        const region = out.regions.find((each) => each.item.number === 70);
        expect(spanAt(spans, region?.header.from ?? 0, () => true)).toBe("item 70");
        expect(spanAt(spans, region?.header.from ?? 0, (id) => id !== "item 70")).toBe(`agent ${whoseOf(LEAD)}`);
        expect(spanAt(bufferSpans(out, { kind: "thread", number: 3 }), 5, () => true)).toBe("thread 3");
    });

    it("lists what's for the operator, who's running, a subagent under their parent, then No agent", () => {
        expect(rows().map((each) => each.id)).toEqual(["for you", "heading running", `agent ${whoseOf(LEAD)}`, `agent ${whoseOf(WORKER)}`, "party no agent", "item 80"]);
    });

    it("counts what's only to read as `toRead` does, falling as it's seen", () => {
        const seen = { groups: new Map([[whoseOf(LEAD), 70]]), commented: new Set<number>() };
        const lines = listLaid(listedByAgent({ ...reading(), seeing: seen })).text.split("\n");
        expect(lines.find((each) => each.includes("s1") && !each.includes("a1"))).not.toContain("•");
        expect(lines[0]).toContain("•1");
    });

    it("says how much of each waits on the operator, and what's for them across everyone", () => {
        const laidOut = listLaid(rows());
        const lines = laidOut.text.split("\n");
        expect(lines[0]).toContain("what's for you");
        expect(lines[0]).toContain("◆1");
        expect(lines[0]).toContain("•2");
        const worker = lines.find((each) => each.includes("a1"));
        expect(worker).toContain("◆1");
        expect(worker).not.toContain("•");
    });

    it("counts what's drafted to an agent or on their items", () => {
        const draft: Draft = { ...EMPTY, comments: [{ id: "c1", item: 51, quote: null, text: "Pydantic." }], letters: [{ id: "m1", to: WORKER, text: "Go on." }] };
        const laidOut = listLaid(listedByAgent(reading(draft)));
        expect(laidOut.text.split("\n").find((each) => each.includes("a1"))).toContain("¶2");
    });

    it("opens each row's buffer, and says which rows are written to", () => {
        const laidOut = listLaid(rows());
        const row = rowAt(laidOut, laidOut.text.indexOf("s1"));
        expect(row?.opens).toEqual({ kind: "agent", key: whoseOf(LEAD) });
        expect(row?.writes).toBe(true);
        expect(rowAt(laidOut, 0)?.opens).toEqual({ kind: "for you" });
        expect(rowAt(laidOut, 0)?.writes).toBe(false);
        expect(rowAt(laidOut, laidOut.text.indexOf("running"))?.opens).toBeNull();
    });

    it("keeps each line a row's, and marks each stretch where it is", () => {
        const laidOut = listLaid(rows());
        expect(laidOut.owners).toHaveLength(laidOut.text.trimEnd().split("\n").length);
        for (const each of laidOut.marks) {
            expect(laidOut.text.slice(each.from, each.to)).not.toContain("\n");
        }
    });
});

describe("the list's marks", () => {
    const AGENT = from("marked");
    const asking = (number: number, reason: unknown) => item(number, AGENT, reason as Item["reason"], WAITING);
    const message = (number: number, kind: string) => asking(number, { reason: "message", passages: [], answers: [], ending: false, kind, text: `A ${kind}.`, to: null });
    const change = (reason: string) => ({ reason, text: "?", summary: "", repository: REPOSITORY, fingerprint: "f", worktree: "/w", key: "k" });
    const reader = (shown: Item[], rest: Partial<ListReading> = {}): ListReading => ({ ...reading(), items: shown, agents: [AGENT], parents: new Map(), running: running(AGENT), states: new Map(), ...rest });
    const rowOf = (shown: Item[], rest: Partial<ListReading> = {}) => {
        const laidOut = listLaid(listedByAgent(reader(shown, rest)));
        const at = laidOut.text.indexOf("marked");
        const end = laidOut.text.indexOf("\n", at);
        return {
            text: laidOut.text.slice(at, end),
            marks: laidOut.marks.filter((each) => each.from >= at && each.to <= end && each.look !== "list-name").map((each) => [laidOut.text.slice(each.from, each.to), each.look]),
        };
    };

    it("marks what holds something stopped solid and orange: a question, a problem, a held change, an approval", () => {
        const items = [asking(51, { reason: "question", text: "Which?", decisions: [] }), message(52, "problem"), asking(53, change("held")), asking(54, change("approval"))];
        expect(rowOf(items).marks).toEqual([["◆4", "mark-waiting"]]);
        const list = listLaid(listedByAgent(reader(items))).text;
        expect(list).toContain("◆ @51 question");
        expect(list).toContain("◆ @52 problem");
    });

    it("marks what wants the operator's eyes with nothing stopped hollow and orange: a disagreement, a question that waits on no answer", () => {
        const items = [message(52, "disagreement"), message(53, "question")];
        expect(rowOf(items).marks).toEqual([["◇2", "mark-asking"]]);
        const laidOut = listLaid(listedByAgent(reader(items)));
        expect(laidOut.text).toContain("◇ @52 disagreement");
        // Their nest opens all the same: they ask.
        expect(listedByAgent(reader(items)).find((each) => each.id === `agent ${whoseOf(AGENT)}`)?.under?.closed).toBe(false);
    });

    describe("in what their \"since you approved\" holds", () => {
        const file = (path: string, rest: object) => ({ path, version: `${path}1`, flags: [], file: { path, before: null, after: { kind: "text", text: "x = 1\n" }, reading: { role: "production", asks: [], findings: [] } }, ...rest });
        const since = (...files: object[]) => new Map([[whoseOf(AGENT), { since: { kind: "policy-since", places: [{ worktree: "/w", branch: "feat", files }] } }]]) as unknown as Drawers;
        const HELD_FILE = { held: { lands: "feat", onto: "dev", at: AT } };

        it("counts each file once, by what it is: a landing's solid, a flagged one hollow and orange, the rest hollow and cyan", () => {
            const drawers = since(file("held.py", HELD_FILE), file("flagged.py", { flags: [70] }), file("seen.py", { flags: [71], file: null }), file("plain.py", {}), file("other.py", {}));
            expect(rowOf([], { drawers }).marks).toEqual([
                ["◆1", "mark-waiting"],
                ["◇2", "mark-asking"],
                ["◇2", "mark-to-review"],
            ]);
        });

        it("counts neither a file the judge's role folds, asking nothing, nor one reviewed", () => {
            const drawers = since(file("test_a.py", { level: "automatic" }), file("kept.py", { file: null }));
            expect(rowOf([], { drawers }).marks).toEqual([]);
        });
    });

    it("draws what they've drafted apart and muted, before what stands, which stays where it is as they write", () => {
        const items = [asking(51, { reason: "question", text: "Which?", decisions: [] }), note(52, AGENT, "News.")];
        const bare = rowOf(items);
        const draft: Draft = { ...EMPTY, comments: [{ id: "c1", item: 51, quote: null, text: "This." }], letters: [{ id: "m1", to: AGENT, text: "Go on." }] };
        const written = rowOf(items, { draft });
        expect(written.marks).toEqual([["¶2", "list-written"], ["◆1", "mark-waiting"], ["•1", "mark-news"]]);
        expect(written.text).toMatch(/¶2 {2}◆1 •1$/);
        expect(written.text.length).toBe(bare.text.length);
        expect(written.text.slice(written.text.indexOf("◆"))).toBe(bare.text.slice(bare.text.indexOf("◆")));
        // On the item's row, its comment is as quiet; the rest of the draft in its own colour.
        const laidOut = listLaid(listedByAgent(reader(items, { draft: { ...draft, done: [51] } })));
        const row = laidOut.text.indexOf("@51");
        expect(laidOut.marks.filter((each) => each.from >= row && each.to <= laidOut.text.indexOf("\n", row) && ["list-written", "outline-draft"].includes(each.look)).map((each) => [laidOut.text.slice(each.from, each.to), each.look])).toEqual([[" ¶", "list-written"], [" ✓", "outline-draft"]]);
    });

    it("draws no status for what's drafted alone, nor counts it among what waits", () => {
        const draft: Draft = { ...EMPTY, letters: [{ id: "m1", to: AGENT, text: "Go on." }] };
        expect(rowOf([], { draft }).marks).toEqual([["¶1", "list-written"]]);
    });
});

describe("where each agent stays in the list", () => {
    const ALPHA = from("alpha");
    const BRAVO = from("bravo");
    const CHARLIE = from("charlie");
    const NAMES = ["alpha", "bravo", "charlie"];
    /** The list, with those three running, in the order the host's tree has them, holding `items`. */
    const listing = (items: Item[], agents: Conversation[] = [ALPHA, BRAVO, CHARLIE]): ListReading => ({
        ...reading(),
        items,
        agents,
        parents: new Map(),
        running: running(ALPHA, BRAVO, CHARLIE),
        states: new Map(),
    });
    const runningNames = (rows: readonly Row[]) => {
        const from = rows.findIndex((each) => each.id === "heading running") + 1;
        const to = rows.findIndex((each) => each.id.startsWith("party "));
        return rows.slice(from, to < 0 ? undefined : to).map((each) => each.says);
    };

    it("keeps the running in the host's order, whatever they hold, gaining or losing an item moving nobody", () => {
        for (const items of [[], [note(10, CHARLIE, "c")], [note(10, CHARLIE, "c"), note(11, BRAVO, "b")], [note(11, BRAVO, "b")], [note(12, CHARLIE, "c"), note(13, BRAVO, "b"), note(14, ALPHA, "a")]]) {
            expect(runningNames(listedByAgent(listing(items)))).toEqual(NAMES);
        }
    });

    it("keeps a subagent under their parent there, whichever of them holds something", () => {
        const child = from("alpha", "child");
        const parents = new Map([[whoseOf(child), whoseOf(ALPHA)]]);
        const list = (items: Item[]) => runningNames(listedByAgent({ ...listing(items, [ALPHA, child, BRAVO, CHARLIE]), parents, running: running(ALPHA, child, BRAVO, CHARLIE) }));
        expect(list([])).toEqual(["alpha", "alpha/child", "bravo", "charlie"]);
        expect(list([note(10, child, "c")])).toEqual(["alpha", "alpha/child", "bravo", "charlie"]);
        expect(list([note(10, CHARLIE, "c"), note(11, child, "c")])).toEqual(["alpha", "alpha/child", "bravo", "charlie"]);
    });

    it("names each repository once, however what's held falls across them", () => {
        const elsewhere = { ...BRAVO, repository: "/r/other.git" };
        const agents = [ALPHA, CHARLIE, elsewhere];
        const list = listedByAgent({ ...listing([note(10, CHARLIE, "c"), note(11, elsewhere, "e"), note(12, ALPHA, "a")], agents), running: running(...agents) });
        expect(list.filter((each) => each.id.startsWith("repository ")).map((each) => each.says)).toEqual(["/r/lup.git", "/r/other.git"]);
    });

    it("keeps No agent's by name, what they hold, or when it came, moving nobody", () => {
        const [ENDED_A, ENDED_B, ENDED_C] = [from("ended-a"), from("ended-b"), from("ended-c")] as [Conversation, Conversation, Conversation];
        const held = (items: Item[], agents: Conversation[] = []) => {
            const rows = listedByAgent({ ...listing(items), agents: [ALPHA, BRAVO, CHARLIE, ...agents] });
            const from = rows.findIndex((each) => each.id === "party no agent") + 1;
            return rows.slice(from).map((each) => each.says);
        };
        // What they left by its number, then who's left nothing but what their drawer holds, by name.
        expect(held([note(22, ENDED_B, "b"), note(20, ENDED_C, "c"), note(21, ENDED_A, "a")])).toEqual(["@20 note, left by ended-c", "@21 note, left by ended-a", "@22 note, left by ended-b"]);
        // An item gone, as it's marked read, moves nobody else.
        expect(held([note(22, ENDED_B, "b"), note(21, ENDED_A, "a")])).toEqual(["@21 note, left by ended-a", "@22 note, left by ended-b"]);
        expect(held([], [ENDED_C, ENDED_A])).toEqual(["ended-a, ended", "ended-c, ended"]);
    });
});

describe("the parties beside the agents", () => {
    const OURS: Party = {
        name: "later",
        called: "For later",
        says: "For later: what you've put by",
        whom: "what you write here waits",
        holds: (group) => group.key === whoseOf(LEAD),
        holdsTask: () => false,
    };

    it("lists each the same, after those running, what it holds with it, and opens its buffer", () => {
        const rows = listedByAgent({ ...reading(), parties: [NO_AGENT, OURS] });
        const ids = rows.map((each) => each.id);
        expect(ids.slice(ids.indexOf("party no agent"))).toEqual(["party no agent", "item 80", "party later", "item 70", `agent ${whoseOf(LEAD)}`]);
        expect(rows.find((each) => each.id === "party later")?.opens).toEqual({ kind: "party", name: "later" });
        expect(listLaid(rows).text).toContain("For later · 2");
        // Listed once, under the party, not among those running as well.
        expect(ids.filter((each) => each === `agent ${whoseOf(LEAD)}`)).toHaveLength(1);
    });

    it("lays out each party's buffer by what it holds, and says over it what it says", () => {
        const out = laid(ITEMS, [LEAD, WORKER], banner, header, EMPTY, NOTHING, [], new Map(), called, { showing: { kind: "party", name: "later" }, parties: [NO_AGENT, OURS], running: running(LEAD, WORKER), looks: adopted() });
        expect(out.regions.map((each) => each.item.number)).toEqual([70]);
        expect(titled({ kind: "party", name: "later" }, { ...reading(), parties: [NO_AGENT, OURS] })).toEqual({ name: "For later", whom: "what you write here waits" });
        expect(bufferKey({ kind: "party", name: "later" })).toBe("party later");
    });

    it("lists no party that holds nothing", () => {
        const none = { ...OURS, holds: () => false };
        expect(listedByAgent({ ...reading(), parties: [none] }).map((each) => each.id)).not.toContain("party later");
    });

    it("declares No agent as one of them, holding what each agent who's ended left and each task the host says nobody running answers for", () => {
        expect(PARTIES).toContain(NO_AGENT);
        const runs = running(LEAD);
        expect(NO_AGENT.holds({ key: whoseOf(LEAD), conversation: LEAD }, runs)).toBe(false);
        expect(NO_AGENT.holds({ key: whoseOf(GONE), conversation: GONE }, runs)).toBe(true);
        expect(NO_AGENT.holds({ key: "lup", conversation: null }, runs)).toBe(false);
        // Who held it says nothing: who answers for it, as the host reads it, does.
        const read = (answering: Conversation | null) => ({ thread: { holder: GONE }, answering }) as ThreadRead;
        expect(NO_AGENT.holdsTask(read(null), runs)).toBe(true);
        expect(NO_AGENT.holdsTask(read(LEAD), runs)).toBe(false);
    });
});

describe("the checks, going by agent", () => {
    const THREAD = {
        thread: { kind: "ledger:thread", number: 302, name: "reader", title: "The reader", repository: REPOSITORY, by: LEAD, at: AT, parent: null, holder: GONE },
        state: "waiting on the operator",
        section: "waiting on you",
        since: AT,
        asks: [{ node: 311, what: "a check", came: AT, holds: false }],
        answering: null,
        left_by: GONE,
    } as unknown as ThreadRead;
    const CHECKED = { check: { kind: "ledger:check", number: 311, name: null, text: "Search a long record.", repository: REPOSITORY, by: WORKER, at: AT }, answer: null } as unknown as OwnedCheck["check"];
    const CHECK: OwnedCheck = { thread: { ...THREAD, checks: [CHECKED] } as ThreadRead, check: CHECKED };
    const answering = { ...THREAD, answering: LEAD, left_by: null } as ThreadRead;
    const noHolder = { ...THREAD, left_by: null, thread: { ...THREAD.thread, holder: null } } as ThreadRead;
    const heldByLead = { ...CHECK.thread, answering: LEAD, thread: { ...THREAD.thread, holder: LEAD } } as ThreadRead;

    function checked(showing: Showing, checks: readonly OwnedCheck[] = [CHECK]): Laid {
        return laid(ITEMS, [LEAD, WORKER], banner, header, EMPTY, NOTHING, [], new Map(), called, { showing, running: running(LEAD, WORKER), looks: adopted(), concerns: checks.map((each) => each.thread) });
    }

    it("belongs to whoever answers for its thread, else who left it, else whoever asked it", () => {
        expect(checkOwner(CHECK)).toEqual(GONE);
        expect(checkOwner({ ...CHECK, thread: answering })).toEqual(LEAD);
        expect(checkOwner({ ...CHECK, thread: { ...noHolder, answering: LEAD } as ThreadRead })).toEqual(LEAD);
        expect(checkOwner({ ...CHECK, thread: noHolder })).toEqual(WORKER);
    });

    it("sits in its concern's block, in its owner's own buffer, and where they've ended, under No agent", () => {
        const own = checked({ kind: "agent", key: whoseOf(LEAD) }, [{ ...CHECK, thread: heldByLead }]);
        expect(own.text).toContain("§ The reader · working\n  ◇ check @311: Search a long record.");
        expect(own.checks.map((each) => each.check.check.number)).toEqual([311]);
        expect(checked({ kind: "party", name: "no agent" }).text).toContain("check @311");
        expect(checked({ kind: "agent", key: whoseOf(LEAD) }).text).not.toContain("check @311");
    });

    it("counts in what's for the operator, wherever it sits, as its owner's group does", () => {
        const out = checked({ kind: "for you" });
        expect(out.text).toContain("check @311");
        const list = listLaid(listedByAgent({ ...reading(), checks: [CHECK] }));
        // A check stops nobody: it's flagged, beside the worker's question, which holds.
        expect(list.text.split("\n")[0]).toContain("◆1 ◇1");
        expect(list.text.split("\n").find((each) => each.includes("No agent"))).toContain("◇1");
        // No row of its own: it's its task's, which counts it.
        expect(list.text).not.toContain("check @311");
    });

    it("gives who left it a group in No agent's buffer where they have none, and counts there in the list, with no row of theirs", () => {
        const stranger = from("s9");
        const held = { ...CHECK, thread: { ...CHECK.thread, left_by: stranger, thread: { ...THREAD.thread, holder: stranger } } as ThreadRead };
        const out = checked({ kind: "party", name: "no agent" }, [held]);
        expect(out.groups.map((each) => called(each.conversation as Conversation))).toContain("s9");
        const list = listLaid(listedByAgent({ ...reading(), checks: [held] })).text.split("\n");
        expect(list.find((each) => each.includes("No agent"))).toContain("◇1");
        expect(list.some((each) => each.includes("s9"))).toBe(false);
    });

    it("stops counting as the draft answers it", () => {
        const ticked: Draft = { ...EMPTY, marks: [{ id: "m", action: "inbox-check-answer", argument: { number: 311 }, verb: "done", says: "tick it", block: "check 311", version: null }] };
        const list = listLaid(listedByAgent({ ...reading(ticked), checks: [CHECK] }));
        expect(list.text.split("\n").find((each) => each.includes("No agent"))).not.toContain("◇");
    });

    it("is what a buffer lands on first, whichever comes first of what asks", () => {
        const out = checked({ kind: "agent", key: whoseOf(LEAD) }, [{ ...CHECK, thread: heldByLead }]);
        // An item to answer first; else their last line, the checks right over it, what's live right over those.
        expect(arrivalIn(out, EMPTY)).toBe(out.groups[0]?.writing?.from);
        const lines = out.text.trimEnd().split("\n");
        expect(lines.at(-2)).toContain("check @311");
        const asked = checked({ kind: "agent", key: whoseOf(WORKER) });
        expect(arrivalIn(asked, EMPTY)).toBe(asked.regions[0]?.header.from);
    });

    it("makes several of a thread's one row saying how many, folded, opening to the list, a verb on it reaching each", () => {
        const second: OwnedCheck = { ...CHECK, check: { ...CHECK.check, check: { ...CHECK.check.check, number: 312, text: "Search a short one." } } as OwnedCheck["check"] };
        const out = checked({ kind: "agent", key: whoseOf(LEAD) }, [{ ...CHECK, thread: { ...heldByLead, checks: [CHECK.check, second.check], asks: [...(heldByLead.asks ?? []), { node: 312, what: "a check", came: AT, holds: false }] } as ThreadRead }]);
        expect(out.text).toContain("  ◇ 2 checks");
        const fold = out.outer.find((each) => each.of === "checks 302");
        expect(fold?.closed).toBe(true);
        expect(out.text.slice(fold?.from, fold?.to)).toContain("check @311: Search a long record.");
        expect(out.text.slice(fold?.from, fold?.to)).toContain("check @312: Search a short one.");
        expect(out.concerns.map((each) => each.read.thread.number)).toEqual([302]);
        expect(out.checks).toHaveLength(2);
        const reach = reachOf(out, fold?.summary.from ?? 0, DONE_VERB, { called });
        expect(reach.on).toContain("2 checks");
        expect(reach.on === null ? [] : reach.acts).toHaveLength(2);
    });

    it("leaves the review without panes unaware of it", () => {
        const whole = laid(ITEMS, [LEAD, WORKER], banner, header, EMPTY, NOTHING, [], new Map(), called, { running: running(LEAD, WORKER), looks: adopted() });
        expect(whole.checks).toEqual([]);
    });
});

describe("the tasks", () => {
    function thread(number: number, name: string, read: Partial<ThreadRead>): ThreadRead {
        return {
            thread: { kind: "ledger:thread", number, name, title: `The ${name}`, repository: REPOSITORY, by: LEAD, at: AT, parent: null, holder: WORKER },
            state: "working",
            section: "every thread",
            since: AT,
            asks: [],
            new: [],
            pile: [],
            unanswered: [],
            members: 0,
            earlier: 0,
            answering: WORKER,
            ...read,
        } as ThreadRead;
    }
    const READER = thread(302, "reader", { state: "waiting on the operator", section: "waiting on you", asks: [{ node: 51, what: "a question", came: AT, holds: true }] as ThreadRead["asks"] });
    const CHILD = (() => {
        const made = thread(303, "child", { new: [70] });
        return { ...made, thread: { ...made.thread, parent: 302 } } as ThreadRead;
    })();
    const NOBODY = (() => {
        const made = thread(304, "nobody", { answering: null } as Partial<ThreadRead>);
        return { ...made, thread: { ...made.thread, holder: GONE } } as ThreadRead;
    })();
    const SETTLED = { kind: "ledger:settled", target: 305, repository: REPOSITORY, by: { party: "operator" }, at: AT, why: "" } as unknown as NonNullable<ThreadRead["cleared"]>;
    const DONE = thread(305, "done", { state: "settled", cleared: SETTLED, reads: "gone" });
    const SHOWN: ThreadShown = { kind: "inbox-thread-shown", read: READER, entries: [{ spot: { node: 51 }, came: AT, member: true }], left: 0, items: [QUESTION], checks: [], references: [], under: [], on: [], paths: [] } as unknown as ThreadShown;
    const threads: Threading = {
        read: { kind: "inbox-threads-read", threads: [READER, CHILD, NOBODY, DONE], paths: [], working: [] },
        shown: new Map([[302, SHOWN]]),
        whole: new Map([[302, SHOWN]]),
        landing: new Map(),
        banner: (read, landing) => threadBanner(read, landing, called),
    };
    const withThreads = (): ListReading => ({ ...reading(), threads });

    /** A concern `lead` holds, as the host reads it. */
    const held = (number: number, name: string, read: Partial<ThreadRead>) => {
        const made = thread(number, name, { answering: LEAD, ...read });
        return { ...made, thread: { ...made.thread, holder: LEAD } } as ThreadRead;
    };
    const SAID_DONE = { kind: "ledger:done", target: 0, repository: REPOSITORY, by: LEAD, at: AT, to_try: "Read the voice section." } as unknown as NonNullable<ThreadRead["done"]>;
    const leads = (rows: readonly Row[]) => rows.find((each) => each.id === `agent ${whoseOf(LEAD)}`)?.under?.rows ?? [];

    it("says what a concern is by its title, never its name, in a look of its own, and quotes what one whose title reads as a name is about", () => {
        const revamp = { ...held(340, "revamp", {}), thread: { ...held(340, "revamp", {}).thread, title: "The full revamp, as #123 orders it" } } as ThreadRead;
        const slugged = held(341, "close-wall-gaps-2", { about: "On resolving the path, then checking it." });
        const named = { ...slugged, thread: { ...slugged.thread, title: "close-wall-gaps" } } as ThreadRead;
        const laidOut = listLaid(listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [revamp, named] } } }));
        const lines = laidOut.text.split("\n");
        expect(lines.some((each) => each.includes("@revamp") || each.includes("close-wall-gaps"))).toBe(false);
        expect(lines.find((each) => each.includes("The full revamp"))?.trim()).toBe("The full revamp, as #123 orders it");
        expect(lines.find((each) => each.includes("“On resolving"))?.trim()).toBe("“On resolving the path, then checking it.”");
        // Drawn unlike an agent's name.
        const look = (text: string) => laidOut.marks.find((each) => each.from === laidOut.text.indexOf(text))?.look;
        expect(look("The full revamp")).toBe("list-concern");
        expect(laidOut.marks.filter((each) => each.look === "list-name").map((each) => laidOut.text.slice(each.from, each.to))).toEqual(["s1", "a1", " s2:"]);
    });

    it("reads each concern by its two marks: done, for the operator's eyes, counted; cleared while someone's on it, quiet and counting nothing; done and cleared, gone but under what's settled", () => {
        const eyes = held(350, "eyes", { state: "done to confirm", reads: "for your eyes", done: SAID_DONE });
        const quiet = held(351, "quiet", { state: "settled", reads: "quiet", cleared: SETTLED, asks: [{ node: 311, what: "a check", came: AT, holds: false }] as ThreadRead["asks"] });
        const gone = held(352, "gone", { state: "settled", reads: "gone", cleared: SETTLED, done: SAID_DONE });
        const rows = listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [eyes, quiet, gone] } } });
        expect(leads(rows).map((each) => each.id)).toEqual(["item 70", "thread 350", "thread 351"]);
        const lines = listLaid(rows).text.split("\n");
        expect(lines.find((each) => each.includes("The eyes"))).toMatch(/The eyes done +◇1$/);
        expect(lines.find((each) => each.includes("The quiet"))?.trim()).toBe("The quiet cleared");
        expect(leads(rows).find((each) => each.id === "thread 351")?.writes).toBe(false);
        // Only what's for their eyes counts: the lead's row and what's for them say the one.
        expect(lines.find((each) => each.includes(called(LEAD)) && !each.includes("/"))).toMatch(/◇1/);
        expect(lines[0]).toContain("◆1 ◇1");
        expect(rows.at(-1)?.under?.rows.map((each) => each.id)).toEqual(["thread 351", "thread 352"]);
        expect(lines.find((each) => each.includes("The gone"))).toContain("done, settled");
    });

    it("leaves a concern cleared with nobody running on it out of everything but what's settled", () => {
        const left = { ...thread(353, "left", { answering: null, left_by: GONE, state: "settled", reads: "gone", cleared: SETTLED } as Partial<ThreadRead>), thread: { ...thread(353, "left", {}).thread, holder: GONE } } as ThreadRead;
        const rows = listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [left] } } });
        const from = rows.findIndex((each) => each.id === "party no agent");
        expect(rows.slice(from + 1, -1).map((each) => each.id)).not.toContain("thread 353");
        expect(rows.at(-1)?.under?.rows.map((each) => each.id)).toEqual(["thread 353"]);
    });

    it("nests a concern solid under its holder, and where it's under one held by someone else, that one dim above it, counting nothing, Enter going to its own row", () => {
        // The operator's sketch: the lead's redesign, two of its five done, the worker's part of it done under the worker.
        const titled = (read: ThreadRead, title: string, parent: number | null = null) => ({ ...read, thread: { ...read.thread, title, parent } }) as ThreadRead;
        const redesign = titled(held(360, "redesign", {}), "redesign the workflow");
        const ledger = titled({ ...thread(361, "ledger", { answering: WORKER, state: "done to confirm", reads: "for your eyes", done: SAID_DONE }) }, "concerns in the ledger", 360);
        const parts = [362, 363, 364, 365].map((number, at) => titled(held(number, `part-${at}`, at === 0 ? { state: "done to confirm", reads: "for your eyes", done: SAID_DONE } : {}), `part ${at}`, 360));
        const rows = listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [redesign, ledger, ...parts] } } });
        expect(leads(rows).map((each) => each.id)).toEqual(["item 70", "thread 360", "thread 362", "thread 363", "thread 364", "thread 365"]);
        const worker = rows.find((each) => each.id === `agent ${whoseOf(WORKER)}`);
        const context = `context ${whoseOf(WORKER)} 360`;
        expect(worker?.under?.rows.map((each) => each.id)).toEqual(["item 51", context, "thread 361"]);
        const dim = worker?.under?.rows.find((each) => each.id === context);
        expect(dim?.goes).toBe("thread 360");
        expect(dim?.opens).toBeNull();
        const lines = listLaid(rows).text.split("\n");
        expect(lines.find((each) => each.includes("redesign the workflow"))).toMatch(/^ {2}redesign the workflow 2 of 5$/);
        expect(lines.filter((each) => each.includes("redesign the workflow"))[1]).toBe("    redesign the workflow");
        expect(lines.find((each) => each.includes("concerns in the ledger"))).toMatch(/^ {6}concerns in the ledger done +◇1$/);
        // The worker's row counts their question and their part done, nothing of what's dim.
        expect(lines.find((each) => each.includes(" a1"))).toMatch(/◆1 ◇1$/);
        const laidOut = listLaid(rows);
        const at = laidOut.text.indexOf("    redesign the workflow\n");
        expect(laidOut.marks.find((each) => each.from === at + 4)?.look).toBe("list-context");
    });

    it("lists what's settled folded", () => {
        const rows = listedByAgent(withThreads());
        expect(rows.at(-1)?.id).toBe("heading settled");
        expect(rows.at(-1)?.under?.rows.map((each) => each.id)).toEqual(["thread 305"]);
        const laidOut = listLaid(rows);
        const fold = laidOut.folds.find((each) => each.key === "list settled");
        expect(fold?.closed).toBe(true);
        expect(laidOut.text.slice(fold?.from, fold?.to)).toContain("The done");
    });

    it("lists each task, by agent, under whoever owns it, a line each, quiet but for what waits on the operator", () => {
        const owner = (agent: Conversation) => {
            const made = thread(310, "owned", { answering: agent, asks: [{ node: 51, what: "a question", came: AT, holds: true }] as ThreadRead["asks"], state: "waiting on the operator" });
            return { ...made, thread: { ...made.thread, holder: agent } } as ThreadRead;
        };
        const quietly = thread(311, "quiet", { answering: LEAD });
        const quiet = { ...quietly, thread: { ...quietly.thread, holder: LEAD } } as ThreadRead;
        const all = { ...threads, read: { ...threads.read, threads: [owner(LEAD), quiet, NOBODY, DONE] } };
        const rows = listedByAgent({ ...reading(), threads: all });
        const lead = rows.find((each) => each.id === `agent ${whoseOf(LEAD)}`);
        expect(lead?.under?.rows.map((each) => each.id)).toEqual(["item 70", "thread 310", "thread 311"]);
        expect(lead?.under?.rows.find((each) => each.id === "thread 311")?.lines).toHaveLength(1);
        // What's new is said on the item's row, read by being seen there, never on the task's, whose mark doesn't move so.
        const newsy = { ...quiet, new: [70] } as ThreadRead;
        const withNews = listLaid(listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [newsy] } } }));
        expect(withNews.text.split("\n").find((each) => each.includes("The quiet"))).not.toContain("•");
        const laidOut = listLaid(rows);
        expect(laidOut.text.split("\n").find((each) => each.includes("The owned"))).toContain("◆1");
        expect(laidOut.text.split("\n").find((each) => each.includes("The quiet"))).not.toContain("◆");
        // Opening one goes to its block in its holder's own buffer.
        const opened = lead?.under?.rows.find((each) => each.id === "thread 310");
        expect([opened?.opens, opened?.node]).toEqual([{ kind: "agent", key: whoseOf(LEAD) }, 310]);
    });

    it("keeps a nested task whose holder ended under whoever answers for it, under its parent, saying so, and out of No agent", () => {
        const parent = thread(320, "parent", { answering: LEAD });
        const parented = { ...parent, thread: { ...parent.thread, holder: LEAD } } as ThreadRead;
        const fell = thread(316, "fallen", { answering: LEAD });
        const held = { ...fell, thread: { ...fell.thread, holder: GONE, parent: 320 } } as ThreadRead;
        const rows = listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [parented, held] } } });
        const lead = rows.find((each) => each.id === `agent ${whoseOf(LEAD)}`)?.under?.rows ?? [];
        expect(lead.map((each) => each.id)).toEqual(["item 70", "thread 320", "thread 316"]);
        expect(lead.find((each) => each.id === "thread 316")?.lines[0]?.stretches[0]?.text).toBe("    ");
        expect(rows.some((each) => each.id === `agent ${whoseOf(GONE)}`)).toBe(false);
        expect(rows.slice(rows.findIndex((each) => each.id === "party no agent")).map((each) => each.id)).toEqual(["party no agent", "item 80"]);
        expect(listLaid(rows).text.split("\n").find((each) => each.includes("The fallen"))).toContain("holder ended");
    });

    it("takes what's live in an agent's own buffer from the plain conversation where the looks have one, the trace a drawer folded above it", () => {
        const looks = adopted();
        const withMessages = { ...looks, drawers: () => [...looks.drawers(""), { module: "transcripts", view: "messages" }] } as typeof looks;
        const out = laid(ITEMS, [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { showing: { kind: "agent", key: whoseOf(LEAD) }, running: running(LEAD), looks: withMessages });
        // Neither read yet, it says it's reading the live one, under the items and over what's written to them.
        const lines = out.text.trimEnd().split("\n");
        expect(lines.at(-2)).toBe("Reading their conversation…");
    });

    describe("what nobody running answers for", () => {
        /** A thread nobody running answers for, left by `left`, as the host reads it. */
        const orphan = (number: number, name: string, left: Conversation | null, read: Partial<ThreadRead> = {}) => {
            const made = thread(number, name, { answering: null, left_by: left, state: "nobody running", ...read } as Partial<ThreadRead>);
            return { ...made, thread: { ...made.thread, holder: left } } as ThreadRead;
        };
        const listed = (read: readonly ThreadRead[], over: Partial<ListReading> = {}) => listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [...read] } }, ...over });
        const inNoAgent = (rows: readonly Row[]) => {
            const from = rows.findIndex((each) => each.id === "party no agent");
            return from < 0 ? [] : rows.slice(from + 1).filter((each) => each.id.startsWith("thread ") || each.id.startsWith("item ") || each.id.startsWith("agent "));
        };

        it("lists it flat in No agent: never under the name of who left it, whose row isn't there", () => {
            const rows = listed([orphan(330, "revamp", GONE)]);
            expect(inNoAgent(rows).map((each) => each.id)).toEqual(["thread 330", "item 80"]);
            expect(rows.some((each) => each.id === `agent ${whoseOf(GONE)}`)).toBe(false);
            expect(listLaid(rows).text).toContain("No agent · 2");
        });

        it("says who left each row: a concern, in place of nobody running or waiting on you, which its marks say, beside any other word, and an item", () => {
            const rows = listed([orphan(330, "revamp", GONE), orphan(331, "parked", GONE, { state: "parked" }), orphan(332, "asks", GONE, { state: "waiting on the operator", asks: [{ node: 311, what: "a check", came: AT, holds: false }] as ThreadRead["asks"] })]);
            const text = listLaid(rows).text.split("\n");
            expect(text.find((each) => each.includes("The revamp"))).toContain("The revamp left by s2");
            expect(text.find((each) => each.includes("The parked"))).toContain("parked, left by s2");
            // What waits on the operator there, its marks say.
            expect(text.find((each) => each.includes("The asks"))).toContain("The asks left by s2");
            expect(text.find((each) => each.includes("The asks"))).toContain("◇1");
            expect(text.find((each) => each.includes("@80"))).toContain("s2: What the one who ended");
            expect(rows.find((each) => each.id === "item 80")?.says).toBe("@80 note, left by s2");
            expect(rows.find((each) => each.id === "thread 330")?.says).toBe("The revamp, left by s2");
        });

        it("says who left it by a subagent's own name, cutting a long name of the concern rather than who", () => {
            const rows = listed([orphan(330, "what-the-by-agent-review-should-become-now", from("s2", "close-wall-gaps"))], { called: (party) => (party.agent == null ? party.session : `${party.session}/${party.agent}`) });
            const line = listLaid(rows).text.split("\n").find((each) => each.includes("The what-"));
            expect(line).toContain("left by close-wall-gaps");
            expect(line).not.toContain("s2/");
            expect([...(line ?? "")].length).toBeLessThanOrEqual(46);
        });

        it("says nobody running of one nobody left, the operator having opened it", () => {
            const line = listLaid(listed([orphan(330, "gathered", null)])).text.split("\n").find((each) => each.includes("The gathered"));
            expect(line).toContain("The gathered nobody running");
        });

        it("keeps what's nested under a concern nested there", () => {
            const child = orphan(331, "child", GONE);
            const rows = listed([orphan(330, "parent", GONE), { ...child, thread: { ...child.thread, parent: 330 } } as ThreadRead]);
            expect(inNoAgent(rows).map((each) => each.id)).toEqual(["thread 330", "thread 331", "item 80"]);
            const text = listLaid(rows).text.split("\n");
            expect(text.find((each) => each.includes("The parent"))?.startsWith("The parent")).toBe(true);
            expect(text.find((each) => each.includes("The child"))?.startsWith("  The child")).toBe(true);
        });

        it("lists none the host says is nothing to list", () => {
            const rows = listed([orphan(330, "empty", GONE, { bare: true })]);
            expect(inNoAgent(rows).map((each) => each.id)).toEqual(["item 80"]);
        });

        it("names an agent who ended only where their drawers hold what waits, flat, with nothing nested", () => {
            const rows = listedByAgent({ ...reading(), agents: [LEAD, WORKER, GONE] });
            const row = rows.find((each) => each.id === `agent ${whoseOf(GONE)}`);
            expect(inNoAgent(rows).map((each) => each.id)).toEqual(["item 80", `agent ${whoseOf(GONE)}`]);
            expect(row?.under).toBeUndefined();
            expect(row?.says).toBe("s2, ended");
        });

        it("doesn't list No agent where it holds nothing", () => {
            const rows = listedByAgent({ ...reading(), items: [QUESTION, LEADS], threads: { ...threads, read: { ...threads.read, threads: [orphan(330, "empty", GONE, { bare: true })] } } });
            expect(rows.map((each) => each.id)).not.toContain("party no agent");
        });

        it("says working of nothing, nobody running answering for it or someone on it, which is a row's own way", () => {
            const rows = listed([orphan(330, "revamp", null)]);
            expect(listLaid(rows).text).not.toContain("working");
            const running = thread(331, "held", { answering: LEAD });
            const held = { ...running, thread: { ...running.thread, holder: LEAD } } as ThreadRead;
            expect(listLaid(listed([held])).text.split("\n").find((each) => each.includes("The held"))?.trim()).toBe("The held");
        });
    });

    it("says a concern's done, for the operator's eyes, in its block, with the agent's account, under whoever owns it, and counts it", () => {
        const finished = thread(315, "finished", { answering: LEAD, state: "done to confirm", reads: "for your eyes", done: { ...SAID_DONE, to_try: "Read the voice section.\nThen the next." } });
        const done = { ...finished, thread: { ...finished.thread, holder: LEAD } } as ThreadRead;
        const out = laid(ITEMS, [LEAD, WORKER], banner, header, EMPTY, NOTHING, [], new Map(), called, { showing: { kind: "agent", key: whoseOf(LEAD) }, running: running(LEAD, WORKER), looks: adopted(), concerns: [done] });
        expect(out.text).toContain("§ The finished · done, for you to clear\n  done, they say: Read the voice section.\n    Then the next.");
        expect(out.concerns.map((each) => each.read.thread.number)).toEqual([315]);
        const rows = listLaid(listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [done] } } }));
        expect(rows.text.split("\n")[0]).toContain("◆1 ◇1");
    });

    describe("a concern's block, where a click on its row goes", () => {
        const verb = (name: string) => ({ name, key: name[0], called: name }) as Verb;
        const laidIn = (showing: Showing, concerns: readonly ThreadRead[], draft: Draft = EMPTY) =>
            laid(ITEMS, [LEAD, WORKER], banner, header, draft, NOTHING, [], new Map(), called, { showing, running: running(LEAD, WORKER), looks: adopted(), concerns });
        const OWN = { kind: "agent", key: whoseOf(LEAD) } as const;
        const passages = [
            { spot: { node: 90, part: 2 }, words: "Make it one buffer.\nAnd more.", answer: 92 },
            { spot: { node: 91, part: 1 }, words: "Keep the marks apart.", answer: null },
        ] as unknown as ThreadRead["passages"];
        const redesign = held(360, "redesign", { passages });
        const part = { ...thread(361, "part", { answering: WORKER }), thread: { ...thread(361, "part", {}).thread, parent: 360, title: "The worker's part" } } as ThreadRead;

        it("shows the title and both marks, the passages it came from with what became of each, and what's nested under it held elsewhere", () => {
            const out = laidIn(OWN, [redesign, part]);
            expect(out.text).toContain(
                [
                    "§ The redesign · working",
                    "  you · @90.2 · answered in @92",
                    "    Make it one buffer.",
                    "  you · @91.1 · open: waits on s1",
                    "    Keep the marks apart.",
                    "  ↳ The worker's part · working · s1/a1",
                ].join("\n"),
            );
            expect(out.concerns.map((each) => [each.read.thread.number, each.dim])).toEqual([
                [360, false],
                [361, true],
            ]);
            // One nobody running answers for says who left it, its marks saying nobody's running.
            const leftHere = { ...thread(367, "left", { answering: null, left_by: GONE, state: "nobody running" } as Partial<ThreadRead>), thread: { ...thread(367, "left", {}).thread, holder: GONE, parent: 360 } } as ThreadRead;
            expect(laidIn(OWN, [redesign, leftHere]).text).toContain("  ↳ The left · nobody running · left by s2");
            // In the worker's own buffer, theirs solid, what it's under dim above it, as context.
            const worker = laidIn({ kind: "agent", key: whoseOf(WORKER) }, [redesign, part]);
            expect(worker.text).toContain("The redesign\n  § The worker's part · working");
            expect(worker.concerns.map((each) => [each.read.thread.number, each.dim])).toEqual([
                [360, true],
                [361, false],
            ]);
        });

        it("lays one out in what's for the operator only where it wants their eyes, said done or with a check waiting", () => {
            const eyes = held(362, "eyes", { state: "done to confirm", reads: "for your eyes", done: SAID_DONE });
            const out = laidIn({ kind: "for you" }, [redesign, eyes]);
            expect(out.concerns.map((each) => each.read.thread.number)).toEqual([362]);
            expect(out.text).toContain("§ The eyes · done, for you to clear\n  done, they say: Read the voice section.");
        });

        it("lays what nobody running answers for in its party's buffer, under who left it, and what nobody left after a line saying so; and each cleared under what's settled", () => {
            const left = { ...thread(363, "left", { answering: null, left_by: GONE, state: "nobody running" } as Partial<ThreadRead>), thread: { ...thread(363, "left", {}).thread, holder: GONE } } as ThreadRead;
            const opened = { ...thread(364, "opened", { answering: null, left_by: null, state: "nobody running" } as Partial<ThreadRead>), thread: { ...thread(364, "opened", {}).thread, holder: null } } as ThreadRead;
            const party = laidIn({ kind: "party", name: "no agent" }, [left, opened, redesign]);
            expect(party.groups.map((each) => (each.conversation === null ? null : called(each.conversation)))).toContain("s2");
            expect(party.concerns.map((each) => each.read.thread.number)).toEqual([363, 364]);
            expect(party.text).toContain("── opened by you, nobody's taken them ──\n§ The opened · nobody running");
            const gone = held(365, "gone", { state: "settled", reads: "gone", cleared: SETTLED, done: SAID_DONE });
            const settled = laidIn({ kind: "settled" }, [gone, redesign]);
            expect(settled.text).toContain("§ The gone · done, cleared");
            expect(settled.concerns.map((each) => each.read.thread.number)).toEqual([365]);
        });

        it("clears it with Space d, declines it with Space x, one cleared doing nothing, and writes on it to whoever answers for it", () => {
            const out = laidIn(OWN, [redesign]);
            const at = out.concerns[0]?.header.from ?? -1;
            const done = reachOf(out, at, verb("done"), { called });
            expect(done.on === null ? null : [done.says, done.acts.map((each) => (each.kind === "mark" ? [each.offer.action, each.offer.argument] : each.kind))]).toEqual(["clear it", [["inbox-settle-thread", { number: 360 }]]]);
            const declined = reachOf(out, at + 4, verb("decline"), { called });
            expect(declined.on === null ? null : declined.acts.map((each) => (each.kind === "mark" ? each.offer.action : each.kind))).toEqual(["inbox-decline-thread"]);
            // From a passage's line too, the concern its block is.
            const passage = out.text.indexOf("  you · @91.1");
            expect(reachOf(out, passage, verb("done"), { called }).on).toBe("The redesign");
            const quiet = held(366, "quiet", { state: "settled", reads: "quiet", cleared: SETTLED });
            const cleared = laidIn(OWN, [quiet]);
            const again = reachOf(cleared, cleared.concerns[0]?.header.from ?? -1, verb("done"), { called });
            expect(again.on === null ? null : [again.says, again.acts]).toEqual(["cleared already", []]);
            expect(opened(out, at)).toEqual({ id: "", to: LEAD, thread: 360, text: "" });
            // Written there, it's laid out under the block, Space s sending it to no one and back.
            const draft = { ...EMPTY, letters: [{ id: "m1", to: LEAD, thread: 360, text: "Go on." }] };
            const written = laidIn(OWN, [redesign], draft);
            const block = written.concerns[0]?.blocks[0];
            expect(written.text.slice(block?.from, block?.to)).toBe("Go on.");
            const send = reachOf(written, block?.from ?? -1, verb("send"), { called });
            expect(send.on === null ? null : send.acts).toEqual([{ kind: "readdress", id: "m1", to: null }]);
        });

        it("is where its row goes: its holder's own buffer, its party's, or what's settled, on its block", () => {
            const left = { ...thread(363, "left", { answering: null, left_by: GONE, state: "nobody running" } as Partial<ThreadRead>), thread: { ...thread(363, "left", {}).thread, holder: GONE } } as ThreadRead;
            const gone = held(365, "gone", { state: "settled", reads: "gone", cleared: SETTLED, done: SAID_DONE });
            const rows = listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [redesign, left, gone] } } });
            const row = (id: string) => pathTo(rows, id)?.at(-1);
            expect([row("thread 360")?.opens, row("thread 360")?.node]).toEqual([{ kind: "agent", key: whoseOf(LEAD) }, 360]);
            expect(row("thread 363")?.opens).toEqual({ kind: "party", name: "no agent" });
            expect(row("thread 365")?.opens).toEqual({ kind: "settled" });
            expect(rows.at(-1)?.opens).toEqual({ kind: "settled" });
            // The list follows the cursor in the block: the concern's row.
            const out = laidIn(OWN, [redesign]);
            const spans = bufferSpans(out, OWN);
            expect(spanAt(spans, out.text.indexOf("Keep the marks apart."), () => true)).toBe("thread 360");
        });
    });

    it("lays out one thread's own buffer: open, whoever answers named on its last line", () => {
        const out = laid(ITEMS, [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { threads, showing: { kind: "thread", number: 302 }, looks: adopted() });
        expect(out.groups.map((each) => each.thread?.thread.number)).toEqual([302]);
        expect(out.groups[0]?.fold?.closed).toBe(false);
        expect(out.text.trimEnd().split("\n").at(-1)).toBe("── to s1/a1 on @reader ──");
    });

    it("lays out no thread outside its own buffer, whatever threads are read", () => {
        const out = laid(ITEMS, [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { threads, showing: { kind: "for you" }, looks: adopted() });
        expect(out.groups.map((each) => each.thread)).toEqual(out.groups.map(() => null));
    });

    it("says whom the words reach from a thread's buffer, and where nobody answers for it", () => {
        const named = (number: number) => titled({ kind: "thread", number }, withThreads());
        expect(named(302)).toEqual({ name: "@reader", whom: "your words reach s1/a1" });
        expect(named(304).whom).toContain("nobody answers");
    });
});

describe("whom a buffer's words reach", () => {
    it("says so of an agent running, one who's ended, what's for the operator and lup's approvals", () => {
        const read = reading();
        expect(titled({ kind: "agent", key: whoseOf(LEAD) }, read)).toEqual({ name: "s1", whom: "your words reach s1" });
        expect(titled({ kind: "agent", key: whoseOf(GONE) }, read).whom).toContain("has ended");
        expect(titled({ kind: "for you" }, read).name).toBe("what's for you");
        expect(titled({ kind: "agent", key: "lup ━━ lup ━━" }, read).name).toBe("lup's approvals");
    });

    it("follows the name under the cursor to that party, the longest there first", () => {
        const text = "── to s1/a1 ──\n";
        expect(partyNamed(text, text.indexOf("s1/a1") + 1, [LEAD, WORKER], called)).toEqual(WORKER);
        expect(partyNamed(text, 0, [LEAD, WORKER], called)).toBeUndefined();
    });
});


describe("a module's row and its own buffer", () => {
    const PLACE = { under: "repository" as const, letter: "V", called: "what runs", colour: "cyan" as const };
    const DRAWN = { module: "versions", view: "what_runs", place: PLACE };
    const ROW: Showing = { kind: "view", repository: REPOSITORY, module: "versions", view: "what_runs", called: "what runs" };
    const FIX_A: Line = { block: "line", id: "branch fix-a", offers: [], spans: [{ text: "[x] fix-a  on trial", tone: "plain" }], by: { runtime: "claude", session: "lead" } };
    const NOBODY: Line = { block: "line", id: "takes", offers: [], spans: [{ text: "what a set takes", tone: "plain" }] };
    const OFFER = (verb: string, says: string) => ({ action: "module-act", argument: { repository: REPOSITORY, module: "versions", action: verb, argument: {} }, verb, runs: "send" as const, commented: false, says });
    const OUT: Fold = { block: "fold", id: "out", kind: "group", summary: [{ text: "out · 1", tone: "muted" }], open: false, barred: false, offers: [], content: [{ ...NOBODY, id: "left out", offers: [OFFER("done", "take it in")] }] };
    const ANSWER: Blocks = {
        summary: [{ text: "what runs · dev + fix-a", tone: "plain" }],
        waiting: false,
        offers: [],
        tally: { holds: 0, flagged: 1, review: 0 },
        blocks: [{ ...FIX_A, offers: [OFFER("decline", "leave it out"), OFFER("merge", "merge it")] }, NOBODY, OUT],
    };
    const REMOTE = new Map([[instanceOf(REPOSITORY, "versions", "what_runs", {}), ANSWER]]);
    const placing = (rows: Merged["rows"]) => ({ ...reading(), looks: { ...adopted(), rows }, remote: REMOTE });

    it("lists no row where no repository's modules place one", () => {
        expect(listedByAgent(reading()).some((each) => each.id.startsWith("view "))).toBe(false);
    });

    it("lists what the view says of itself, with its marks, straight under what's for the operator and opening its buffer", () => {
        const rows = listedByAgent(placing([{ repository: REPOSITORY, drawn: DRAWN }]));
        const row = rows.find((each) => each.id === bufferKey(ROW));
        expect(row?.opens).toEqual(ROW);
        const said = row?.lines[0]?.stretches.map((each) => each.text).join("") ?? "";
        expect(said).toContain("what runs · dev + fix-a");
        expect(said).toContain("◇1");
        expect(rows.findIndex((each) => each.id === bufferKey(ROW))).toBe(rows.findIndex((each) => each.id === "for you") + 1);
        expect(titled(ROW, { ...reading() }).name).toBe("what runs");
    });

    it("says its name until its view answers, and names the repository where several place one", () => {
        const unread = listedByAgent({ ...placing([{ repository: "/r/zoetrope.git", drawn: DRAWN }, { repository: REPOSITORY, drawn: DRAWN }]) });
        const said = unread.filter((each) => each.id.startsWith("view ")).map((each) => each.lines[0]?.stretches.map((one) => one.text).join("").trim());
        expect(said[0]).toBe("zoetrope what runs");
        expect(said[1]).toMatch(/^lup what runs · dev \+ fix-a +◇1$/);
    });

    const inBuffer = (draft: Draft = EMPTY) => laid([], [], banner, header, draft, NOTHING, [], new Map(), called, { showing: ROW, looks: adopted(), remote: REMOTE, read: true });

    it("lays out only that view, open, whichever agents there are", () => {
        const laidOut = inBuffer();
        expect(laidOut.text).toContain("what runs · dev + fix-a\n[x] fix-a  on trial\nwhat a set takes\nout · 1");
        expect(laidOut.groups).toEqual([]);
        expect(bufferSpans(laidOut, ROW).map((each) => each.id)).toEqual([bufferKey(ROW)]);
    });

    it("reaches a verb on the block offering it, and nothing from a line offering none", () => {
        const laidOut = inBuffer();
        const verbs = (name: string): Verb => ({ name, key: name[0] ?? "", called: name });
        const onBranch = reachOf(laidOut, laidOut.text.indexOf("[x] fix-a"), verbs("decline"), { called });
        expect(onBranch).toMatchObject({ says: "leave it out" });
        const onNote = reachOf(laidOut, laidOut.text.indexOf("what a set takes"), verbs("decline"), { called });
        expect(onNote.on).toBe(null);
        const onSummary = reachOf(laidOut, 0, verbs("merge"), { called });
        expect(onSummary.on).toBe(null);
        // A line folding rows reaches none of them from its own line, as the summary line doesn't.
        const onOut = reachOf(laidOut, laidOut.text.indexOf("out · 1"), verbs("done"), { called });
        expect(onOut.on).toBe(null);
    });

    it("takes a comment on a line saying whom it reaches, and none on one that doesn't", () => {
        const laidOut = inBuffer();
        expect(opened(laidOut, laidOut.text.indexOf("[x] fix-a"))).toMatchObject({ to: { session: "lead" } });
        expect(opened(laidOut, laidOut.text.indexOf("what a set takes"))).toBeUndefined();
    });

    it("keeps a comment on a branch under its line as what the view says comes and goes", () => {
        const first = inBuffer();
        const remark = opened(first, first.text.indexOf("[x] fix-a"));
        expect(remark).toBeDefined();
        const written = { ...(remark as object), id: "r1", text: "why this?" };
        const draft: Draft = { ...EMPTY, remarks: [written as never] };
        const laidOut = inBuffer(draft);
        expect(laidOut.text).toContain("[x] fix-a  on trial\nwhy this?\nwhat a set takes");
        // Laid out whole, as a send does, or with another buffer on screen, it's on nobody's group but whom it reaches.
        const whole = laid([], [], banner, header, draft, NOTHING, [], new Map(), called, { looks: adopted(), remote: REMOTE, read: true });
        expect(whole.groups.map((each) => each.conversation?.session)).toEqual(["lead"]);
    });
});


describe("what's done to the draft while a reply is being sent", () => {
    const REMARK = { id: "sent", item: 1, text: "sent with it" };
    const MARK = (id: string) => ({ id, action: "module-act", argument: {}, verb: "done", says: "it", block: `block ${id}`, version: null });

    it("keeps what's written or marked meanwhile, and leaves out what the send took", () => {
        const before: Draft = { ...EMPTY, comments: [REMARK], marks: [MARK("applied")], done: [1] };
        const typedMeanwhile = { id: "new", item: 2, text: "typed while it went" };
        const during: Draft = { ...before, comments: [REMARK, typedMeanwhile], marks: [MARK("applied"), MARK("made meanwhile")], done: [1, 7] };
        const left = withWrittenDuring(before, during, EMPTY);
        expect(left.comments?.map((each) => each.text)).toEqual(["typed while it went"]);
        expect(left.marks?.map((each) => each.id)).toEqual(["made meanwhile"]);
        expect(left.done).toEqual([7]);
    });

    it("takes the words as they are now, of a comment the send left where it edited it meanwhile", () => {
        const before: Draft = { ...EMPTY, comments: [REMARK] };
        const during: Draft = { ...EMPTY, comments: [{ ...REMARK, text: "sent with it, and more" }] };
        expect(withWrittenDuring(before, during, before).comments?.map((each) => each.text)).toEqual(["sent with it, and more"]);
    });

    it("leaves as it is what the send left, nothing having been done meanwhile", () => {
        const before: Draft = { ...EMPTY, marks: [MARK("refused")] };
        expect(withWrittenDuring(before, before, before).marks?.map((each) => each.id)).toEqual(["refused"]);
    });
});
