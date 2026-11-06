// The review in panes (`docs/dashboard.md`, *The review*): each buffer a subset of the one layout, what's written kept
// and followed as another is on screen, and the list by agent and by thread.
import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import { carried, implied, type Marked } from "./grammar";
import { adopted } from "./looks";
import { arrivalIn, bufferKey, bufferSpans, listLaid, listedByAgent, listedByThread, panesAsked, pathTo, rowAt, spanAt, titled, type ListReading } from "./panes";
import { EMPTY, ROOT_TITLE, aboutAt, checkOwner, followedFrom, groupAt, laid, opened, whose as whoseOf, type Around, type Conversation, type Draft, type Item, type Laid, type OwnedCheck, type Showing, type ThreadRead, type ThreadShown, type Threading } from "./review";
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
    return { number, reason, sender, recipient: { party: "operator" }, replies: [], citations: [], edits: [], quiet: false, made: AT, state: { state: "waiting" }, rank };
}

function note(number: number, sender: Conversation, text: string): Item {
    return item(number, sender, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text, to: null });
}

const QUESTION = item(51, WORKER, { reason: "question", text: "Which parser?", decisions: [{ text: "pydantic", lean: "yes" }] } as unknown as Item["reason"], WAITING);
const LEADS = note(70, LEAD, "Built.");
const LEFT = note(80, GONE, "What the one who ended left.");
const ITEMS = [QUESTION, LEADS, LEFT];

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
    it("asks for panes by agent or by thread, and for nothing else", () => {
        expect(panesAsked("?panes=agents")).toBe("agents");
        expect(panesAsked("?panes=threads")).toBe("threads");
        expect(panesAsked("?threads")).toBeNull();
        expect(panesAsked("?panes=forum")).toBeNull();
        expect(panesAsked("")).toBeNull();
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

    it("lays out what nobody running answers under No agent", () => {
        const out = buffer({ kind: "no agent" });
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
        const keys = [{ kind: "for you" }, { kind: "no agent" }, { kind: "agent", key: "a" }, { kind: "agent", key: "b" }, { kind: "thread", number: 1 }, { kind: "thread", number: 2 }] as Showing[];
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

    it("nests each item under its sender, marked as the overview marks it, what asks open, the rest folded until the second pane's cursor comes to it", () => {
        const worker = rows().find((each) => each.id === `agent ${whoseOf(WORKER)}`);
        expect(worker?.under?.closed).toBe(false);
        const lead = rows().find((each) => each.id === `agent ${whoseOf(LEAD)}`);
        expect(lead?.under?.closed).toBe(true);
        const opened = listedByAgent({ ...reading(), opened: new Set([`agent ${whoseOf(LEAD)}`]) }).find((each) => each.id === `agent ${whoseOf(LEAD)}`);
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

    it("says which row the second pane's cursor is on, the deepest it knows", () => {
        const out = buffer({ kind: "for you" });
        const spans = bufferSpans(out, { kind: "for you" });
        const region = out.regions.find((each) => each.item.number === 70);
        expect(spanAt(spans, region?.header.from ?? 0, () => true)).toBe("item 70");
        expect(spanAt(spans, region?.header.from ?? 0, (id) => id !== "item 70")).toBe(`agent ${whoseOf(LEAD)}`);
        expect(spanAt(bufferSpans(out, { kind: "thread", number: 3 }), 5, () => true)).toBe("thread 3");
    });

    it("lists what's for the operator, who's running, a subagent under their parent, then No agent", () => {
        expect(rows().map((each) => each.id)).toEqual(["for you", "heading running", `agent ${whoseOf(LEAD)}`, `agent ${whoseOf(WORKER)}`, "heading no agent", `agent ${whoseOf(GONE)}`]);
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
        expect(laidOut.text.split("\n").find((each) => each.includes("a1"))).toContain("»2");
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

describe("the checks, going by agent", () => {
    const THREAD = {
        thread: { kind: "ledger:thread", number: 302, name: "reader", title: "The reader", repository: REPOSITORY, by: LEAD, at: AT, parent: null, holder: GONE },
        state: "waiting on the operator",
        section: "waiting on you",
        since: AT,
        asks: [{ node: 311, what: "a check", came: AT }],
        answering: null,
    } as unknown as ThreadRead;
    const CHECK: OwnedCheck = { thread: THREAD, check: { check: { kind: "ledger:check", number: 311, name: null, text: "Search a long record.", repository: REPOSITORY, by: WORKER, at: AT }, answer: null } as unknown as OwnedCheck["check"] };
    const answering = { ...THREAD, answering: LEAD } as ThreadRead;
    const noHolder = { ...THREAD, thread: { ...THREAD.thread, holder: null } } as ThreadRead;

    function checked(showing: Showing, checks: readonly OwnedCheck[] = [CHECK]): Laid {
        return laid(ITEMS, [LEAD, WORKER], banner, header, EMPTY, NOTHING, [], new Map(), called, { showing, running: running(LEAD, WORKER), looks: adopted(), checks });
    }

    it("belongs to whoever answers for its thread, else whoever holds it, else whoever asked it", () => {
        expect(checkOwner(CHECK)).toEqual(GONE);
        expect(checkOwner({ ...CHECK, thread: answering })).toEqual(LEAD);
        expect(checkOwner({ ...CHECK, thread: noHolder })).toEqual(WORKER);
    });

    it("sits in its owner's own buffer, naming its thread, and where they've ended, under No agent", () => {
        const own = checked({ kind: "agent", key: whoseOf(LEAD) }, [{ ...CHECK, thread: answering }]);
        expect(own.text).toContain("◆ check @311 in @reader: Search a long record.");
        expect(own.checks.map((each) => each.check.check.number)).toEqual([311]);
        expect(checked({ kind: "no agent" }).text).toContain("check @311");
        expect(checked({ kind: "agent", key: whoseOf(LEAD) }).text).not.toContain("check @311");
    });

    it("counts in what's for the operator, wherever it sits, as its owner's group does", () => {
        const out = checked({ kind: "for you" });
        expect(out.text).toContain("check @311");
        const list = listLaid(listedByAgent({ ...reading(), checks: [CHECK] }));
        expect(list.text.split("\n")[0]).toContain("◆2");
        expect(list.text.split("\n").find((each) => each.includes("s2"))).toContain("◆1");
    });

    it("gives its owner a group where they have none, and a row under No agent", () => {
        const stranger = from("s9");
        const held = { ...CHECK, thread: { ...THREAD, thread: { ...THREAD.thread, holder: stranger } } as ThreadRead };
        const out = checked({ kind: "no agent" }, [held]);
        expect(out.groups.map((each) => called(each.conversation as Conversation))).toContain("s9");
        expect(listLaid(listedByAgent({ ...reading(), checks: [held] })).text).toContain("s9");
    });

    it("stops counting as the draft answers it", () => {
        const ticked: Draft = { ...EMPTY, marks: [{ id: "m", action: "inbox-check-answer", argument: { number: 311 }, verb: "done", says: "tick it", block: "check 311", version: null }] };
        const list = listLaid(listedByAgent({ ...reading(ticked), checks: [CHECK] }));
        expect(list.text.split("\n").find((each) => each.includes("s2"))).not.toContain("◆");
    });

    it("is what a buffer lands on first, whichever comes first of what asks", () => {
        const out = checked({ kind: "agent", key: whoseOf(LEAD) }, [{ ...CHECK, thread: answering }]);
        expect(arrivalIn(out, EMPTY)).toBe(out.checks[0]?.from);
    });

    it("leaves the review without panes unaware of it", () => {
        const whole = laid(ITEMS, [LEAD, WORKER], banner, header, EMPTY, NOTHING, [], new Map(), called, { running: running(LEAD, WORKER), looks: adopted() });
        expect(whole.checks).toEqual([]);
    });
});

describe("the list by thread", () => {
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
    const READER = thread(302, "reader", { state: "waiting on the operator", section: "waiting on you", asks: [{ node: 51, what: "a question", came: AT }] as ThreadRead["asks"] });
    const CHILD = (() => {
        const made = thread(303, "child", { new: [70] });
        return { ...made, thread: { ...made.thread, parent: 302 } } as ThreadRead;
    })();
    const NOBODY = thread(304, "nobody", { answering: null } as Partial<ThreadRead>);
    const DONE = thread(305, "done", { state: "settled" });
    const SHOWN: ThreadShown = { kind: "inbox-thread-shown", read: READER, entries: [{ spot: { node: 51 }, came: AT, member: true }], left: 0, items: [QUESTION], checks: [], references: [], under: [], on: [], paths: [] } as unknown as ThreadShown;
    const threads: Threading = {
        read: { kind: "inbox-threads-read", threads: [READER, CHILD, NOBODY, DONE], paths: [], working: [] },
        shown: new Map([[302, SHOWN]]),
        whole: new Map([[302, SHOWN]]),
        landing: new Map(),
        banner: (read, landing, section) => threadBanner(read, landing, called, section),
    };
    const byThread = (): ListReading => ({ ...reading(), threads });

    it("lists what's for the operator, who's running, each thread open under its parent, No agent, and what's settled folded", () => {
        const rows = listedByThread(byThread());
        expect(rows.map((each) => each.id)).toEqual([
            "for you",
            "heading running",
            `agent ${whoseOf(LEAD)}`,
            `agent ${whoseOf(WORKER)}`,
            "heading threads",
            "thread 302",
            "thread 303",
            "heading no agent",
            "thread 304",
            "heading settled",
        ]);
        expect(rows.at(-1)?.under?.rows.map((each) => each.id)).toEqual(["thread 305"]);
        const laidOut = listLaid(rows);
        expect(laidOut.folds).toHaveLength(1);
        expect(laidOut.text.slice(laidOut.folds[0]?.from, laidOut.folds[0]?.to)).toContain("@done");
        expect(laidOut.text.split("\n").find((each) => each.includes("@reader"))).toContain("◆1");
    });

    it("lists each task, by agent, under whoever owns it, a line each, quiet but for what waits on the operator", () => {
        const owner = (agent: Conversation) => thread(310, "owned", { answering: agent, asks: [{ node: 51, what: "a question", came: AT }] as ThreadRead["asks"], state: "waiting on the operator" });
        const quiet = thread(311, "quiet", { answering: LEAD });
        const all = { ...threads, read: { ...threads.read, threads: [owner(LEAD), quiet, NOBODY, DONE] } };
        const rows = listedByAgent({ ...reading(), threads: all });
        const lead = rows.find((each) => each.id === `agent ${whoseOf(LEAD)}`);
        expect(lead?.under?.rows.map((each) => each.id)).toEqual(["item 70", "thread 310", "thread 311"]);
        expect(lead?.under?.rows.find((each) => each.id === "thread 311")?.lines).toHaveLength(1);
        const laidOut = listLaid(rows);
        expect(laidOut.text.split("\n").find((each) => each.includes("@owned"))).toContain("◆1");
        expect(laidOut.text.split("\n").find((each) => each.includes("@quiet"))).not.toContain("◆");
        // Opening one reads it across agents, as a conversation.
        expect(lead?.under?.rows.find((each) => each.id === "thread 310")?.opens).toEqual({ kind: "thread", number: 310 });
    });

    it("says of a task fallen to who answers for its holder, ended, that nobody's working on it", () => {
        const fell = thread(316, "fallen", { answering: LEAD });
        const rows = listLaid(listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [fell] } } }));
        expect(rows.text.split("\n").find((each) => each.includes("@fallen"))).toContain("holder ended");
    });

    it("lists a task whose owner's ended under No agent, under them, and one nobody ever held on its own there", () => {
        const heldByGone = thread(312, "gone", { answering: null } as Partial<ThreadRead>);
        const gone = { ...heldByGone, thread: { ...heldByGone.thread, holder: GONE } } as ThreadRead;
        const nobody = { ...heldByGone, thread: { ...heldByGone.thread, number: 313, name: "unheld", holder: null, by: { party: "operator" } } } as unknown as ThreadRead;
        const all = { ...threads, read: { ...threads.read, threads: [gone, nobody] } };
        const rows = listedByAgent({ ...reading(), threads: all });
        const at = rows.findIndex((each) => each.id === "heading no agent");
        expect(rows[at + 1]?.id).toBe("thread 313");
        expect(rows.find((each) => each.id === `agent ${whoseOf(GONE)}`)?.under?.rows.map((each) => each.id)).toContain("thread 312");
    });

    it("lists no session's own root a second time, but where something in it asks", () => {
        const root = (read: Partial<ThreadRead>) => {
            const made = thread(314, "root", { answering: LEAD, ...read });
            return { ...made, thread: { ...made.thread, title: ROOT_TITLE } } as ThreadRead;
        };
        const quiet = listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [root({})] } } });
        expect(quiet.find((each) => each.id === `agent ${whoseOf(LEAD)}`)?.under?.rows.map((each) => each.id)).toEqual(["item 70"]);
        const asking = listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [root({ new: [70] })] } } });
        expect(asking.find((each) => each.id === `agent ${whoseOf(LEAD)}`)?.under?.rows.map((each) => each.id)).toContain("thread 314");
    });

    it("says a thread's done, for the operator to confirm, under whoever owns it, and counts it", () => {
        const done = thread(315, "finished", { answering: LEAD, state: "done to confirm", status: { kind: "ledger:done", to_try: "Read the voice section.\nThen the next." } as NonNullable<ThreadRead["status"]> });
        const out = laid(ITEMS, [LEAD, WORKER], banner, header, EMPTY, NOTHING, [], new Map(), called, { showing: { kind: "agent", key: whoseOf(LEAD) }, running: running(LEAD, WORKER), looks: adopted(), confirming: [done] });
        expect(out.text).toContain("◆ @finished is done, to confirm: Read the voice section. · gt goes there");
        expect(out.confirms.map((each) => each.thread.thread.number)).toEqual([315]);
        const rows = listLaid(listedByAgent({ ...reading(), threads: { ...threads, read: { ...threads.read, threads: [done] } } }));
        expect(rows.text.split("\n")[0]).toContain("◆2");
    });

    it("lays out one thread's own buffer: open, whoever answers named on its last line", () => {
        const out = laid(ITEMS, [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { threads, showing: { kind: "thread", number: 302 }, looks: adopted() });
        expect(out.sections).toEqual([]);
        expect(out.groups.map((each) => each.thread?.thread.number)).toEqual([302]);
        expect(out.groups[0]?.fold?.closed).toBe(false);
        expect(out.text.trimEnd().split("\n").at(-1)).toBe("── to s1/a1 on @reader ──");
    });

    it("lays out what's for the operator without the front or what's settled", () => {
        const out = laid(ITEMS, [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { threads, showing: { kind: "for you" }, looks: adopted() });
        // Nothing to read here: no section says so. Its banners never fold: nothing here is what looks empty.
        expect(out.sections.map((each) => each.name)).toEqual(["waiting on you", "new", "agents"]);
        expect(out.sections.find((each) => each.name === "agents")?.fold?.closed).toBe(false);
    });

    it("says whom the words reach from a thread's buffer, and where nobody answers for it", () => {
        const named = (number: number) => titled({ kind: "thread", number }, byThread());
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
