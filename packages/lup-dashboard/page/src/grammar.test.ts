import { describe, expect, it } from "vitest";

import "./fixtures/looks";
import { chainAt, isMarked, listed, marking, markedPart, seenAct, type Act, type Marked } from "./grammar";
import { EMPTY, type Conversation, type Placed } from "./review";
import type { Offer } from "./views";

const HOLD: Offer = { action: "set-holding", argument: { launch: "l1", session: "s1", agent: null, on: true }, verb: "hold", chord: null, runs: "send", commented: false, says: "hold their flagged writes" };

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
        expect(once.marks?.map((each) => [each.action, each.verb, each.block, each.says, each.argument])).toEqual([["set-holding", "done", "banner of s1", "hold their flagged writes", HOLD.argument]]);
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

    it("says a thread read, settled or declined by its number, named as the page knows it, as it was marked where it doesn't", () => {
        const mark = (action: string, argument: Marked["argument"], says: string): Marked => ({ id: action, action, argument, verb: "done", says, block: "group 1", version: null });
        const read = mark("review-mark", { repository: "/r/.git", module: "core", key: { node: 307 }, up_to: "60" }, "@voice read");
        const settled = mark("inbox-settle-thread", { number: 307 }, "@voice settled");
        const declined = mark("inbox-decline-thread", { number: 307 }, "@voice declined");
        const named = (number: number) => (number === 307 ? "voice-pass" : null);
        expect([read, settled, declined].map((each) => markedPart(each, called, named))).toEqual([
            { kind: "thread", name: "voice-pass", done: "read" },
            { kind: "thread", name: "voice-pass", done: "settled" },
            { kind: "thread", name: "voice-pass", done: "declined" },
        ]);
        expect(markedPart(settled, called, unnamed)).toEqual({ kind: "said", text: "@voice settled" });
        // A check ticked marks no thread.
        expect(markedPart(mark("inbox-check-answer", { number: 311 }, "tick it"), called, named)).toEqual({ kind: "said", text: "tick it" });
    });
});
