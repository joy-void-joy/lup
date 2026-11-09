import { describe, expect, it } from "vitest";

import { hosted, KINDS, type Said } from "./fixtures/kinds";
import "./fixtures/looks";
import { actionsToRun, chainAt, isMarked, listed, marking, markedPart, reachOf, seenAct, type Act, type Marked, type Verb } from "./grammar";
import { EMPTY, laid, type Around, type Conversation, type Item, type Placed } from "./review";
import type { Offer } from "./views";

const HOLD: Offer = { action: "set-holding", argument: { launch: "l1", session: "s1", agent: null, on: true }, verb: "hold", chord: null, runs: "send", commented: false, says: "hold their writes" };

describe("marking the draft", () => {
    it("puts an item in one list of the draft at most, done, declined or left for later, and takes it out of every one", () => {
        const done = listed(EMPTY, 51, "done");
        expect([done.done, done.declined, done.parked]).toEqual([[51], [], []]);
        const declined = listed(done, 51, "declined");
        expect([declined.done, declined.declined, declined.parked]).toEqual([[], [51], []]);
        const none = listed(declined, 51, null);
        expect([none.done, none.declined, none.parked]).toEqual([[], [], []]);
    });

    it("marks what a key reaches, and pressed again where it's all marked, takes the marks off", () => {
        const acts: Act[] = [
            { kind: "item", number: 51, list: "done" },
            { kind: "mark", offer: HOLD, block: "banner of s1", version: null },
        ];
        const once = marking(EMPTY, acts, "done");
        expect(once.done).toEqual([51]);
        expect(once.marks?.map((each) => [each.action, each.verb, each.block, each.says, each.argument])).toEqual([["set-holding", "done", "banner of s1", "hold their writes", HOLD.argument]]);
        expect(once.marks?.[0]?.id).not.toBe("");
        expect(acts.every((each) => isMarked(once, each, "done"))).toBe(true);
        const twice = marking(once, acts, "done");
        expect([twice.done, twice.marks]).toEqual([[], []]);
    });

    it("marks a file held at landing reviewed or its landing declined, never both: the later key replaces the other's mark", () => {
        const argument = { conversation: { party: "conversation", repository: "/r.git", runtime: "claude", session: "s1" }, worktree: "/w", branch: "feat", files: [{ path: "a.py", version: "a1" }] };
        const review: Offer = { action: "policy-review-since", argument, verb: "done", chord: null, runs: "send", commented: false, says: "mark it reviewed, letting it land" };
        const decline: Offer = { ...review, argument: { ...argument, decline: true }, verb: "decline", commented: true, says: "decline its landing" };
        const done = marking(EMPTY, [{ kind: "mark", offer: review, block: "file a.py", version: "a1" }], "done");
        const declined = marking(done, [{ kind: "mark", offer: decline, block: "file a.py", version: "a1" }], "decline");
        expect(declined.marks?.map((each) => [each.verb, each.says])).toEqual([["decline", "decline its landing"]]);
        // Pressed again, it's taken off, and nothing's marked.
        expect(marking(declined, [{ kind: "mark", offer: decline, block: "file a.py", version: "a1" }], "decline").marks).toEqual([]);
    });

    it("marks what's left unmarked where only some of it is, rather than taking the rest off", () => {
        const acts: Act[] = [
            { kind: "item", number: 51, list: "done" },
            { kind: "item", number: 52, list: "done" },
        ];
        const some = marking(EMPTY, acts.slice(0, 1), "done");
        expect(marking(some, acts, "done").done).toEqual([51, 52]);
    });

    it("leaves the draft as it is for what marks nothing: a comment, or what runs at once", () => {
        const acts: Act[] = [{ kind: "comment" }, { kind: "once", offer: { ...HOLD, runs: "once" }, conversation: null }];
        expect(marking(EMPTY, acts, "comment")).toBe(EMPTY);
    });
});

describe("the parts the cursor is in", () => {
    const part = (id: string, kind: Placed["kind"], from: number, to: number, children: Placed[] = []): Placed => ({ id, kind, from, to, header: { from, to: from }, children });

    it("finds them outermost first, an item's blank line after it counting as the item's", () => {
        const nodes = [part("group a", "group", 0, 40, [part("group a banner", "banner", 0, 5), part("item 1", "item", 6, 20, [part("item 1 header", "header", 6, 10)])])];
        expect(chainAt(nodes, 8).map((each) => each.id)).toEqual(["group a", "item 1", "item 1 header"]);
        expect(chainAt(nodes, 21).map((each) => each.id)).toEqual(["group a", "item 1"]);
        expect(chainAt(nodes, 30).map((each) => each.id)).toEqual(["group a"]);
        // Past the last group, the review's last lines are its.
        expect(chainAt(nodes, 50).map((each) => each.id)).toEqual(["group a"]);
        expect(chainAt([part("group b", "group", 10, 20)], 5)).toEqual([]);
    });
});

describe("review marks", () => {
    const parser: Conversation = { party: "conversation", repository: "/r/.git", runtime: "claude", session: "s1", agent: "a1" };
    const called = (each: Conversation) => (each.agent === null ? each.session : `${each.session}/${each.agent}`);
    const unnamed = () => null;

    it("marks an agent's group seen up to an item, the core's mark, said in the line under the review as its agent seen", () => {
        const act = seenAct(parser, "group 0", 57);
        const draft = marking(EMPTY, [act], "done");
        const [mark] = draft.marks ?? [];
        expect(mark).toMatchObject({ action: "review-mark", verb: "done", block: "group 0", says: "mark them seen" });
        expect(mark?.argument).toEqual({ repository: "/r/.git", module: "core", key: { runtime: "claude", session: "s1", agent: "a1" }, up_to: "57" });
        expect(markedPart(mark!, called, unnamed)).toEqual({ kind: "said", text: "s1/a1 seen" });
    });

    it("says any other module's mark on an agent by the agent and its offer's words, one on nothing of an agent's by its words alone", () => {
        const read: Offer = {
            action: "review-mark",
            argument: { repository: "/r/.git", module: "transcripts", key: { runtime: "claude", session: "s1", agent: null }, up_to: "40" },
            verb: "done",
            chord: null,
            runs: "send",
            commented: false,
            says: "mark it read",
        };
        const [mark] = marking(EMPTY, [{ kind: "mark", offer: read, block: "drawer", version: null }], "done").marks ?? [];
        expect(markedPart(mark!, called, unnamed)).toEqual({ kind: "said", text: "s1: mark it read" });
        const other = { ...mark!, argument: { ...mark!.argument, key: { page: "a" } } };
        expect(markedPart(other, called, unnamed)).toEqual({ kind: "said", text: "mark it read" });
    });

    it("says a concern read, cleared or declined by its number, named as the page knows it, as it was marked where it doesn't", () => {
        const mark = (action: string, argument: Marked["argument"], says: string): Marked => ({ id: action, action, argument, verb: "done", says, block: "group 1", version: null });
        const read = mark("review-mark", { repository: "/r/.git", module: "core", key: { node: 307 }, up_to: "60" }, "@voice read");
        const settled = mark("inbox-settle-thread", { number: 307 }, "@voice settled");
        const declined = mark("inbox-decline-thread", { number: 307 }, "@voice declined");
        const named = (number: number) => (number === 307 ? "voice-pass" : null);
        expect([read, settled, declined].map((each) => markedPart(each, called, named))).toEqual([
            { kind: "thread", name: "voice-pass", done: "read" },
            { kind: "thread", name: "voice-pass", done: "cleared" },
            { kind: "thread", name: "voice-pass", done: "declined" },
        ]);
        expect(markedPart(settled, called, unnamed)).toEqual({ kind: "said", text: "@voice settled" });
        // A mark of another's numbered the same marks no thread.
        expect(markedPart(mark("module-act", { number: 307 }, "merge it"), called, named)).toEqual({ kind: "said", text: "merge it" });
    });
});

/** An item of the kind `said` is of, as `kinds.json` has it. */
function written(said: Said): Item {
    const agent = { party: "conversation", repository: "/r", runtime: "claude", session: "s1" } as const;
    const party = (name: string) => (name === "operator" ? { party: "operator" as const } : agent);
    const state = said.state === "superseded" ? { state: "superseded", at: "2026-10-01T12:00:00Z", by: 9 } : said.state === "done" ? { state: "done", at: "2026-10-01T12:00:00Z" } : { state: "waiting" };
    return hosted({
        number: 7,
        reason: { reason: said.reason, kind: said.kind, to: said.to ? agent : null, text: ".", why: ".", passages: [], answers: [], ending: false, citations: [], covers: [], comments: [], decisions: [], rulings: [], comment: "", summary: "" } as unknown as Item["reason"],
        sender: party(said.sender),
        recipient: party(said.recipient),
        replies: [],
        citations: [],
        edits: [],
        quiet: false,
        made: "2026-10-01T12:00:00Z",
        state: state as Item["state"],
        rank: { name: "news", order: 1, notifies: false },
    });
}

const VERBS: Verb[] = [
    { name: "done", key: "d", called: "done" },
    { name: "decline", key: "x", called: "decline" },
    { name: "send", key: "s", called: "send to" },
    { name: "comment", key: "c", called: "comment" },
];

describe("what the host offers on an item", () => {
    it("is what the host's table of kinds says of each kind, from each party, standing each way", () => {
        for (const said of KINDS) {
            const item = written(said);
            const name = JSON.stringify([said.reason, said.kind, said.to, said.sender, said.recipient, said.state]);
            expect([name, item.asks, item.offers, item.spent]).toEqual([name, said.asks, said.offers, said.spent]);
        }
    });

    it("reaches only what it offers, and says why on what a later item replaced, going on outward from anything else", () => {
        const around: Around = { contexts: new Map(), files: new Map(), answers: [], commented: [] };
        const called = (each: Conversation) => each.session;
        for (const said of KINDS) {
            const item = written(said);
            const out = laid([item], [], () => "━━ banner ━━", () => "── item ──", EMPTY, around);
            const at = out.text.indexOf("── item ──");
            for (const verb of VERBS) {
                const reach = reachOf(out, at, verb, { called });
                const name = JSON.stringify([said.reason, said.kind, said.to, said.sender, said.recipient, said.state, verb.name]);
                const offer = item.offers.find((each) => each.verb === verb.name);
                const spent = item.spent.find((each) => each.verb === verb.name);
                const on = reach.on === null ? null : reach.node.id;
                // What no longer offers a verb never reaches the item itself: it goes on to its group, or to nothing.
                expect([name, on === "item 7" ? reach.says : null]).toEqual([name, offer?.says ?? spent?.says ?? null]);
            }
        }
    });

    it("marks a key's answer in the draft's list the host names, and opens a comment", () => {
        const approval = KINDS.find((each) => each.reason === "approval" && each.sender === "operator" && each.state === "waiting");
        const item = written(approval as Said);
        const around: Around = { contexts: new Map(), files: new Map(), answers: [], commented: [] };
        const out = laid([item], [], () => "━━ banner ━━", () => "── item ──", EMPTY, around);
        const at = out.text.indexOf("── item ──");
        const acts = (name: string) => {
            const reach = reachOf(out, at, VERBS.find((each) => each.name === name) as Verb, { called: (each) => each.session });
            return reach.on === null ? null : reach.acts;
        };
        expect(acts("done")).toEqual([{ kind: "item", number: 7, list: "done" }]);
        expect(acts("decline")).toEqual([{ kind: "item", number: 7, list: "declined" }]);
        expect(acts("send")).toEqual([{ kind: "item", number: 7, list: "parked" }]);
        expect(acts("comment")).toEqual([{ kind: "comment" }]);
    });
});


describe("the order a send asks a module's actions in", () => {
    const mark = (id: string, action: string, runs: "last" | null = null, module: string = "versions"): Marked => ({
        id,
        action: "module-act",
        argument: { repository: "/r.git", module, action, argument: { id } },
        verb: "done",
        says: id,
        block: id,
        version: null,
        ...(runs === null ? {} : { runs }),
    });

    it("asks what may move the host last, whatever order the keys came in", () => {
        const { run } = actionsToRun([mark("run", "run_again", "last"), mark("merge", "merge")]);
        expect(run.map((each) => each.marks.map((one) => one.id))).toEqual([["merge"], ["run"]]);
        expect(run.map((each) => each.last)).toEqual([false, true]);
    });

    it("asks one that may move the host a send, the rest held back", () => {
        const { run, held } = actionsToRun([mark("pick", "pick", "last"), mark("run", "run_again", "last")]);
        expect(run.map((each) => each.marks.map((one) => one.id))).toEqual([["pick"]]);
        expect(held.map((each) => each.id)).toEqual(["run"]);
    });

    it("gathers every mark of an action into one asking, ticks of one box after another among them", () => {
        const { run, held } = actionsToRun([mark("a", "pick", "last"), mark("merge", "merge"), mark("b", "pick", "last")]);
        expect(run.map((each) => each.marks.map((one) => one.id))).toEqual([["merge"], ["a", "b"]]);
        expect(held).toEqual([]);
    });

    it("leaves out what's no module's action", () => {
        const other: Marked = { ...mark("x", "x"), action: "review-mark" };
        expect(actionsToRun([other]).run).toEqual([]);
    });
});
