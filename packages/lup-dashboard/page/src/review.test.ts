import { LOOKS } from "./fixtures/looks";
import { ANSWERED, DRAWER_ONLY } from "./fixtures/conversation";
import { ChangeSet, Text } from "@codemirror/state";
import { describe, expect, it } from "vitest";

import { above, outdated, spokenOf } from "./exchange";
import { levelled } from "./folds";
import { reconcile, runsOf } from "./reconcile";
import { marking, reachOf } from "./grammar";
import {
    EMPTY,
    aboutAt,
    answer,
    answerAfter,
    arrival,
    blockAt,
    blocksOf,
    body,
    calls,
    changing,
    citationsOf,
    covered,
    flag,
    foldAt,
    foldKey,
    foldsOf,
    following,
    fresh,
    groupAt,
    heading,
    isLetter,
    fileHeads,
    laid,
    messages,
    news,
    opened,
    ordered,
    plain,
    pruned,
    quoted,
    quotedAt,
    recipient,
    regionAt,
    shownAt,
    stepped,
    steps,
    tallied,
    threadsOf,
    toAnswer,
    toKeep,
    waited,
    whose,
    withWritten,
    written,
    sinceFileAt,
    rowLabel,
    sinceSummary,
    UNREAD,
    type AgentDrawers,
    type Around,
    type ChangedFile,
    type Comment,
    type Context,
    type Conversation,
    type Draft,
    type Drawers,
    type Fold,
    type Head,
    type Item,
    type Laid,
    type Naming,
    type Quote,
    type Remark,
    type Since,
    type Written,
} from "./review";

/** The verb named `name`, as lup's default declaration's looks declare it. */
function verb(name: string): (typeof LOOKS.verbs)[number] {
    const found = LOOKS.verbs.find((each) => each.name === name);
    if (found === undefined) {
        throw new Error(`no verb ${name}`);
    }
    return found;
}

/** Say what the verb named `name` reaches at `at` in `out`, as the line of keys says it: what it's on and what it does; none where nothing takes it. */
function reaches(out: Laid, at: number, name: string): string | null {
    const reach = reachOf(out, at, verb(name), { called: (each) => each.session });
    return reach.on === null ? null : `${reach.on}: ${reach.says}`;
}

const AT = "2026-10-17T12:00:00Z";

/** The ranks the host gives each item by its kind (`ranked`, `inbox/store.py`). */
const WAITING: Item["rank"] = { name: "waiting on you", order: 0, notifies: true };
const NEWS: Item["rank"] = { name: "news", order: 1, notifies: false };

function from(session: string, agent: string | null = null): Conversation {
    return { party: "conversation", repository: "/r/.git", runtime: "claude", session, agent };
}

const QUESTION: Item = {
    number: 51,
    reason: {
        reason: "question",
        text: "Which parser?",
        decisions: [
            { text: "Use lark", lean: "yes" },
            { text: "Keep the cache", lean: "no" },
        ],
    },
    sender: from("s1", "a1"),
    recipient: { party: "operator" },
    replies: [],
    citations: [],
    edits: [],
    quiet: false,
    made: AT,
    state: { state: "waiting" },
    rank: WAITING,
};

const NOTE: Item = {
    number: 52,
    reason: { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "I assumed UTF-8." },
    sender: from("s2"),
    recipient: { party: "operator" },
    replies: [],
    citations: [],
    edits: [],
    quiet: false,
    made: AT,
    state: { state: "waiting" },
    rank: WAITING,
};

const APPROVAL: Item = {
    number: 54,
    reason: {
        reason: "approval",
        text: "Approve?",
        summary: " a.py | 2 +-",
        repository: "/r/.git",
        fingerprint: "f",
        typing: false,
        first: false,
    },
    sender: { party: "operator" },
    recipient: { party: "operator" },
    replies: [],
    citations: [],
    edits: [],
    quiet: false,
    made: AT,
    state: { state: "waiting" },
    rank: WAITING,
};

const FLAGGED: Item = {
    number: 70,
    reason: {
        reason: "flagged",
        text: "a.py landed, flagged for the operator's review.",
        summary: "a.py is a new production file",
        worktree: "/w",
        path: "a.py",
        writes: 2,
    },
    sender: from("s2"),
    recipient: { party: "operator" },
    replies: [],
    citations: [],
    edits: [],
    quiet: false,
    made: AT,
    state: { state: "waiting" },
    rank: { name: "flag", order: 2, notifies: false },
};

const CONTEXT: Context = {
    kind: "inbox-context",
    number: 51,
    anchor: 5,
    entries: [
        { kind: "said", by: "operator", text: "Build the reader.\n\nAsk me first.", at: "2026-10-17T11:51:00Z" },
        { kind: "said", by: "agent", text: "Reading the records." },
        { kind: "called", tool: "Bash" },
        { kind: "called", tool: "Bash" },
        { kind: "called", tool: "Read" },
        { kind: "called", tool: "mcp__lup__ask", id: "call-51" },
        { kind: "called", tool: "Grep" },
    ],
};

const NOTHING: Around = { contexts: new Map(), files: new Map(), answers: [], commented: [] };

const header = (item: Item, parked: boolean) => `── #${item.number}${parked ? " · later" : ""} ──`;
const banner = (head: Head, parked: boolean) => {
    const party = "item" in head ? head.item.sender : head.conversation;
    return `━━ ${party.party === "conversation" ? party.session : "lup"}${parked ? " · later" : ""} ━━`;
};

/** What's written at a line, as a comment on an item: none where it's a message to an agent. */
/** A quote of `text`, at offsets `start` to `end` of its item's text whole, naming no block: as one kept from before quotes named theirs, which the host gives with its fields' defaults. */
function keptQuote(text: string, start: number, end: number): Quote {
    return { text, block: "", version: "", line: 0, lines: [], start, end };
}

/** Return the id of the block of `out`'s item `number`'s view laid out as its own text. */
function textOf(out: Laid, number: number): string {
    return `${out.regions.find((each) => each.item.number === number)!.body.id} text`;
}

/** Return the quote a comment opened on lines `first` to `last` of block `block` of `out` makes, from `start` to `end` in them, saying `text`. */
function onBlock(out: Laid, block: string, first: number, last: number, start: number, end: number, text: string): Quote {
    const lines = out.lines.get(block)!;
    return { text, block, version: lines.given ?? lines.version, line: first, lines: [...lines.lines.slice(first, last + 1)], start, end };
}

function onItem(written: Written | undefined): Comment | undefined {
    return written === undefined || isLetter(written) ? undefined : written;
}

/** The banners and headers of a layout, in order: its groups and items as laid out. */
function heads(out: { text: string }): string[] {
    return out.text.split("\n").filter((line) => line.startsWith("━━") || line.startsWith("──"));
}

describe("laid", () => {
    it("folds each item whole under its header, folded once it's marked read, and nothing else", () => {
        const out = laid([QUESTION, NOTE], [], banner, header, { ...EMPTY, done: [52] }, NOTHING);
        const question = out.regions.find((each) => each.item.number === 51);
        const note = out.regions.find((each) => each.item.number === 52);
        expect(question!.folds.map((each) => [each.kind, each.closed])).toEqual([["item", false]]);
        const [read] = note!.folds;
        expect(note!.folds).toHaveLength(1);
        expect(read).toMatchObject({ kind: "item", name: "", closed: true });
        expect(out.text.slice(read!.summary.from, read!.summary.to)).toBe("── #52 ──");
        expect(out.text.slice(read!.from, read!.to)).toBe("\nI assumed UTF-8.");
    });

    it("folds an item left for later whole under its header, as one marked read, landing on its header", () => {
        const out = laid([QUESTION, NOTE], [], banner, header, { ...EMPTY, parked: [51] }, NOTHING);
        const question = out.regions.find((each) => each.item.number === 51)!;
        const [later] = question.folds;
        expect(later).toMatchObject({ kind: "item", closed: true });
        expect(out.text.slice(later!.summary.from, later!.summary.to)).toBe("── #51 · later ──");
        expect(out.text.slice(later!.from, later!.to)).toMatch(/^\nWhich parser\?\n.*lean: no$/s);
        expect(arrival(question)).toBe(question.header.from);
        const back = laid([QUESTION, NOTE], [], banner, header, EMPTY, NOTHING);
        expect(back.regions.flatMap((each) => each.folds).map((each) => each.closed)).toEqual([false, false]);
        // Its own fold is named the same, read, left for later or neither, which says how it's folded.
        expect(back.regions.map((each) => foldKey(each.folds[0]!))).toEqual(["51 item ", "52 item "]);
    });

    it("lays groups and items in the order they arrived: each group where its first item came, each item at the end of its group", () => {
        const later: Item = { ...QUESTION, number: 53, reason: { ...NOTE.reason } };
        const fourth: Item = { ...NOTE, number: 54 };
        const out = laid([fourth, QUESTION, NOTE, later], [], banner, header, EMPTY, NOTHING);
        expect(heads(out)).toEqual(["━━ s1 ━━", "── #51 ──", "── #53 ──", "━━ s2 ━━", "── #52 ──", "── #54 ──"]);
        // Given in any order, and however new, the first item's number places the group.
        const two = laid([{ ...NOTE, made: "2026-10-17T13:00:00Z" }, QUESTION], [], banner, header, EMPTY, NOTHING);
        expect(two.text.startsWith("━━ s1 ━━")).toBe(true);
    });

    it("lays news where it came, before what's to answer where it came first: its rank orders nothing", () => {
        const friction: Item = {
            ...NOTE,
            number: 50,
            reason: { reason: "friction", text: "`ls` failed" },
            sender: from("s1", "a1"),
            rank: NEWS,
        };
        const ended: Item = {
            ...NOTE,
            number: 61,
            reason: { reason: "message", passages: [], answers: [], ending: true, kind: "note", text: "Done." },
            sender: from("s3"),
            rank: NEWS,
        };
        const out = laid([friction, QUESTION, NOTE, ended], [], banner, header, EMPTY, NOTHING);
        expect(heads(out)).toEqual(["━━ s1 ━━", "── #50 ──", "── #51 ──", "━━ s2 ━━", "── #52 ──", "━━ s3 ━━", "── #61 ──"]);
        expect(news(friction)).toBe(true);
        expect(news(ended)).toBe(true);
        expect([news(QUESTION), news(NOTE), news(APPROVAL)]).toEqual([false, false, false]);
    });

    it("lays a flag where it came too, before news and what's to answer where it came first", () => {
        const flagged = (number: number, sender: Conversation): Item => ({ ...FLAGGED, number, sender });
        const ended: Item = {
            ...NOTE,
            number: 61,
            reason: { reason: "message", passages: [], answers: [], ending: true, kind: "note", text: "Done." },
            sender: from("s3"),
            rank: NEWS,
        };
        const went: Item = {
            ...NOTE,
            number: 62,
            reason: { reason: "how it went", text: "Good." },
            rank: NEWS,
        };
        const out = laid([flagged(50, from("s2")), flagged(71, from("s4")), went, NOTE, ended], [], banner, header, EMPTY, NOTHING);
        expect(heads(out)).toEqual([
            "━━ s2 ━━",
            "── #50 ──",
            "── #52 ──",
            "── #62 ──",
            "━━ s3 ━━",
            "── #61 ──",
            "━━ s4 ━━",
            "── #71 ──",
        ]);
        expect([flag(FLAGGED), flag(NOTE), news(FLAGGED)]).toEqual([true, false, false]);
    });

    it("moves nothing as items come, as an item's rank changes, or as one is marked read: parking alone moves one, to the end", () => {
        const first = laid([QUESTION, NOTE], [], banner, header, EMPTY, NOTHING);
        expect(heads(first)).toEqual(["━━ s1 ━━", "── #51 ──", "━━ s2 ━━", "── #52 ──"]);
        // A later item for s1, to answer, goes at the end of s1's group; one for a new agent, after every group.
        const later: Item = { ...QUESTION, number: 53 };
        const ninth: Item = { ...NOTE, number: 54, sender: from("s9") };
        const more = laid([later, ninth, QUESTION, NOTE], [], banner, header, EMPTY, NOTHING);
        expect(heads(more)).toEqual(["━━ s1 ━━", "── #51 ──", "── #53 ──", "━━ s2 ━━", "── #52 ──", "━━ s9 ━━", "── #54 ──"]);
        // The note's rank changed, and the question marked read: the same places.
        const changed = laid([later, ninth, QUESTION, { ...NOTE, rank: NEWS }], [], banner, header, { ...EMPTY, done: [51] }, NOTHING);
        expect(heads(changed)).toEqual(heads(more));
        expect(changed.regions[0]?.folds.find((each) => each.kind === "item")?.closed).toBe(true);
        // Parked, the question goes to the end, its group staying where it was this sitting.
        const places = more.groups.map((each) => each.place);
        const parked = laid([later, ninth, QUESTION, NOTE], [], banner, header, { ...EMPTY, parked: [51] }, NOTHING, places);
        expect(heads(parked)).toEqual([
            "━━ s1 ━━",
            "── #53 ──",
            "━━ s2 ━━",
            "── #52 ──",
            "━━ s9 ━━",
            "── #54 ──",
            "━━ s1 · later ━━",
            "── #51 · later ──",
        ]);
    });

    it("walks to what's to answer with ]a and [a, in the order it came, passing over news, flags and what's settled", () => {
        const friction: Item = { ...NOTE, number: 60, reason: { reason: "friction", text: "`ls` failed" }, sender: from("s1", "a1"), rank: NEWS };
        const out = laid([QUESTION, NOTE, friction, FLAGGED, APPROVAL], [], banner, header, EMPTY, NOTHING);
        expect(heads(out)).toEqual(["━━ s1 ━━", "── #51 ──", "── #60 ──", "━━ s2 ━━", "── #52 ──", "── #70 ──", "━━ lup ━━", "── #54 ──"]);
        const at = (text: string) => out.text.indexOf(text);
        const number = (region: ReturnType<typeof answerAfter>) => region?.item.number;
        expect([toAnswer(QUESTION, EMPTY), toAnswer(NOTE, EMPTY), toAnswer(friction, EMPTY), toAnswer(FLAGGED, EMPTY), toAnswer(APPROVAL, EMPTY)]).toEqual([
            true,
            true,
            false,
            false,
            true,
        ]);
        // From the top, each in turn, the news and the flag passed over, wherever they're laid out; then nothing.
        expect(number(answerAfter(out, EMPTY, 0, true))).toBe(51);
        expect(number(answerAfter(out, EMPTY, at("── #51"), true))).toBe(52);
        expect(number(answerAfter(out, EMPTY, at("Which parser?"), true))).toBe(52);
        expect(number(answerAfter(out, EMPTY, at("── #52"), true))).toBe(54);
        expect(number(answerAfter(out, EMPTY, at("── #54"), true))).toBeUndefined();
        // And back; none before the first.
        expect(number(answerAfter(out, EMPTY, at("── #54"), false))).toBe(52);
        expect(number(answerAfter(out, EMPTY, at("── #52"), false))).toBe(51);
        expect(number(answerAfter(out, EMPTY, at("── #51"), false))).toBeUndefined();
        // From news or a flag, the next that came after it, and the last that came before it.
        expect(number(answerAfter(out, EMPTY, at("── #60"), true))).toBeUndefined();
        expect(number(answerAfter(out, EMPTY, at("── #60"), false))).toBe(54);
        expect(number(answerAfter(out, EMPTY, at("── #70"), false))).toBe(54);
        // From a banner, the first item laid out after it counts, as the top's does.
        expect(number(answerAfter(out, EMPTY, at("━━ s2"), true))).toBe(52);
        expect(number(answerAfter(out, EMPTY, at("━━ lup"), true))).toBe(54);
        // Marked read or left for later, an item is passed over, as the draft settles it.
        expect(number(answerAfter(out, { ...EMPTY, done: [52] }, at("── #51"), true))).toBe(54);
        expect(number(answerAfter(out, { ...EMPTY, parked: [54] }, at("── #52"), true))).toBeUndefined();
        expect(toAnswer(NOTE, { ...EMPTY, done: [52] })).toBe(false);
    });

    it("counts what's to answer and what's new for the header over the review, those settled in the draft left out", () => {
        const friction: Item = { ...NOTE, number: 60, reason: { reason: "friction", text: "`ls` failed" }, rank: NEWS };
        const items = [QUESTION, NOTE, friction, FLAGGED];
        expect(tallied(items, EMPTY, null)).toBe("2 to answer");
        expect(tallied(items, EMPTY, "2026-10-17T11:00:00Z")).toBe("2 to answer · 4 new");
        expect(tallied(items, { ...EMPTY, done: [51], parked: [70] }, "2026-10-17T11:00:00Z")).toBe("1 to answer · 2 new");
        expect(tallied([friction], EMPTY, "2026-10-17T13:00:00Z")).toBe("0 to answer");
        expect(tallied([], EMPTY, "2026-10-17T11:00:00Z")).toBe("");
    });

    it("shows a friction, how the work went and a stop as written", () => {
        const friction: Item = {
            ...NOTE,
            number: 62,
            reason: { reason: "friction", text: "`uv run lup-dev check` printed: engine stale\nI was running the gate." },
        };
        const went: Item = {
            ...NOTE,
            number: 63,
            reason: { reason: "how it went", text: "The brief was clear, and it felt good." },
        };
        const stopped: Item = { ...NOTE, number: 65, reason: { reason: "stop", why: "Nothing more is worth doing." } };
        expect(body(friction)).toBe("`uv run lup-dev check` printed: engine stale\nI was running the gate.");
        expect(body(went)).toBe("The brief was clear, and it felt good.");
        expect(body(stopped)).toBe("Nothing more is worth doing.");
    });

    it("lays each item under its header in its sender's group, the parked ones last, each comment under its line", () => {
        const draft: Draft = {
            ...EMPTY,
            comments: [
                { id: "yes", item: 51, quote: keptQuote("Use lark", 17, 25), text: "Yes." },
                { id: "whole", item: 51, quote: null, text: "On the whole: fine." },
                { id: "noted", item: 52, quote: null, text: "Noted." },
            ],
            letters: [],
            done: [],
            parked: [52],
        };
        const out = laid([QUESTION, NOTE], [], banner, header, draft, NOTHING);
        expect(out.text).toBe(
            "━━ s1 ━━\n── #51 ──\nOn the whole: fine.\nWhich parser?\n1. Use lark\nYes.\n   lean: yes\n2. Keep the cache\n   lean: no\n\n" +
                "━━ s2 · later ━━\n── #52 · later ──\nNoted.\nI assumed UTF-8.\n\n",
        );
        const [question] = out.regions;
        expect(question!.blocks.map((each) => out.text.slice(each.from, each.to))).toEqual([
            "On the whole: fine.",
            "Yes.",
        ]);
        expect(question!.blocks.map((each) => each.comment)).toEqual(["whole", "yes"]);
        const lark = out.text.indexOf("Use lark");
        expect(shownAt(question!, 17)).toBe(lark);
    });

    it("goes back, as Ctrl+Enter ends a comment, to the last character of its passage, its item's header, or a message's banner", () => {
        const draft: Draft = {
            ...EMPTY,
            comments: [
                { id: "yes", item: 51, quote: keptQuote("Use lark", 17, 25), text: "Yes." },
                { id: "fine", item: 51, quote: null, text: "Fine." },
            ],
            letters: [{ id: "hi", to: from("s2"), text: "Hi." }],
        };
        const out = laid([QUESTION, NOTE], [], banner, header, draft, NOTHING);
        const block = (comment: string) => blocksOf(out).find((each) => each.comment === comment)!;
        const [yes, fine, hi] = written(draft);
        expect(aboutAt(out, yes!, block("yes"))).toBe(out.text.indexOf("Use lark") + "Use lar".length);
        expect(aboutAt(out, fine!, block("fine"))).toBe(out.text.indexOf("── #51"));
        expect(aboutAt(out, hi!, block("hi"))).toBe(out.text.indexOf("━━ s2"));
    });

    it("opens a comment on the line under the cursor, on the item from its header, or a message to its agent from its banner", () => {
        const out = laid([QUESTION, NOTE], [], banner, header, EMPTY, NOTHING);
        expect(opened(out, out.text.indexOf("Keep the cache"))).toEqual({
            id: "",
            item: 51,
            quote: onBlock(out, textOf(out, 51), 3, 3, 0, "2. Keep the cache".length, "2. Keep the cache"),
            text: "",
        });
        expect(opened(out, out.text.indexOf("── #51"))).toEqual({ id: "", item: 51, quote: null, text: "" });
        expect(opened(out, 2)).toEqual({ id: "", to: from("s1", "a1"), text: "" });
    });

    it("quotes a passage within one item's own lines, and not across items", () => {
        const draft: Draft = { ...EMPTY, comments: [{ id: "x", item: 51, quote: null, text: "x" }] };
        const out = laid([QUESTION, NOTE], [], banner, header, draft, NOTHING);
        const lark = out.text.indexOf("lark");
        expect(quoted(out, lark, lark + 4)).toEqual({
            id: "",
            item: 51,
            quote: onBlock(out, textOf(out, 51), 1, 1, "1. Use ".length, "1. Use lark".length, "lark"),
            text: "",
        });
        expect(quoted(out, lark, out.text.indexOf("UTF-8"))).toBeUndefined();
        expect(blockAt(out, out.text.indexOf("x\n"))?.comment).toBe("x");
        expect(regionAt(out, out.text.indexOf("UTF-8"))?.item.number).toBe(52);
    });

    it("quotes from the cursor to the line's end, as `C` covers, and nothing on a header, where `C` opens the line's comment", () => {
        const out = laid([QUESTION], [], banner, header, EMPTY, NOTHING);
        const keep = out.text.indexOf("the cache");
        const end = out.text.indexOf("\n", keep);
        expect(onItem(quoted(out, keep, end))?.quote?.text).toBe("the cache");
        const head = out.text.indexOf("── #51");
        expect(quoted(out, head + 3, out.text.indexOf("\n", head))).toBeUndefined();
        expect(opened(out, head + 3)).toEqual({ id: "", item: 51, quote: null, text: "" });
    });

    it("says what each verb reaches where the cursor is, the innermost thing it applies to, from the cursor outward", () => {
        const draft: Draft = { ...EMPTY, comments: [{ id: "fine", item: 51, quote: null, text: "Fine." }] };
        const files: Around = { contexts: new Map([[51, { shown: CONTEXT }]]), files: new Map([[54, { shown: [CHANGED] }]]), answers: [], commented: [] };
        const out = laid([QUESTION, APPROVAL], [from("s3")], banner, header, draft, files);
        const at = (text: string) => out.text.indexOf(text);
        // In a comment, what it's on; in an item, the item, done marking it read; an approval's kind saying what done and decline mean.
        expect(reaches(out, at("Fine."), "done")).toBe("@51 question: mark it read");
        expect(reaches(out, at("Keep the cache"), "done")).toBe("@51 question: mark it read");
        expect(reaches(out, at("Keep the cache"), "decline")).toBeNull();
        expect(reaches(out, at("Keep the cache"), "send")).toBe("@51 question: leave it for later");
        expect(reaches(out, at("context ·"), "done")).toBe("@51 question: mark it read");
        expect(reaches(out, at("Approve?"), "done")).toBe("@54 approval: approve");
        expect(reaches(out, at("Approve?"), "decline")).toBe("@54 approval: decline");
        // A file of an approval offers nothing of its own: the approval, whole.
        expect(reaches(out, at("a.py · changed"), "done")).toBe("@54 approval: approve");
        // On a banner, the agent: done reaching its own items; hold where its banner offers it, none here, not running.
        expect(reaches(out, at("━━ s1"), "done")).toBe("s1: mark its items and drawers done");
        expect(reaches(out, at("━━ s1"), "hold")).toBeNull();
        expect(reaches(out, at("━━ lup"), "done")).toBe("lup's approvals: mark its items and drawers done");
        expect(reaches(out, at("━━ s3"), "done")).toBeNull();
        expect(reaches(laid([], [], banner, header, EMPTY, NOTHING), 0, "done")).toBeNull();
        // Pause is declared, and nothing offers it: its key says so.
        const paused = reachOf(out, at("Keep the cache"), verb("pause"), { called: (each) => each.session });
        expect(paused.on === null ? paused.why : "").toBe("not built yet: its host side is designed beside #157");
    });

    it("shows an approval's diff without git's colours", () => {
        expect(plain("\u001b[32m+added\u001b[m")).toBe("+added");
    });
});

/** Twelve lines, `l1` to `l12`, the seventh `seventh` in place of `l7`. */
function twelve(seventh = "l7"): string {
    return Array.from({ length: 12 }, (_, at) => (at === 6 ? seventh : `l${at + 1}`)).join("\n") + "\n";
}

const CHANGED: ChangedFile = { path: "a.py", before: { kind: "text", text: twelve() }, after: { kind: "text", text: twelve("L7") } };

describe("what folds under an item", () => {
    const around: Around = {
        contexts: new Map([
            [51, { shown: CONTEXT }],
            [54, { refused: "item 54 was made by no agent's call" }],
        ]),
        files: new Map([[54, { shown: [CHANGED] }]]),
        answers: [],
        commented: [],
    };

    it("says each step of a context in a line, its words' own lines kept, a run of calls in one, the call that made the item marked", () => {
        expect(steps(CONTEXT)).toEqual([
            { kind: "you", text: "you: Build the reader." },
            { kind: "you", text: "     Ask me first." },
            { kind: "agent", text: "Reading the records." },
            { kind: "calls", text: "· called Bash ×2, Read" },
            { kind: "anchor", text: "→ called mcp__lup__ask · this item" },
            { kind: "calls", text: "· called Grep" },
        ]);
        expect(calls(["Read", "Read", "Bash", "Read"])).toBe("· called Read ×2, Bash, Read");
    });

    it("lays an approval's files, then the item's context, under its own text, a file's unchanged runs and the context folding", () => {
        const out = laid([QUESTION, APPROVAL], [], banner, header, EMPTY, around);
        expect(out.text).toBe(
            "━━ s1 ━━\n── #51 ──\nWhich parser?\n1. Use lark\n   lean: yes\n2. Keep the cache\n   lean: no\n" +
                "context · 7 steps, from your words 9m before this item\n" +
                "you: Build the reader.\n     Ask me first.\nReading the records.\n" +
                "· called Bash ×2, Read\n→ called mcp__lup__ask · this item\n· called Grep\n\n" +
                "━━ lup ━━\n── #54 ──\nApprove?\n a.py | 2 +-\n" +
                "a.py · changed · +1 −1\n" +
                "3 unchanged lines, 1–3\nl1\nl2\nl3\nl4\nl5\nl6\nl7\nL7\nl8\nl9\nl10\n" +
                "2 unchanged lines, 11–12\nl11\nl12\n" +
                "no context: item 54 was made by no agent's call\n\n",
        );
        const [question, approval] = out.regions;
        const shown = (from: number, to: number) => out.text.slice(from, to);

        const runs = approval!.folds.filter((each) => each.kind === "lines");
        const [top, bottom] = runs;
        expect(approval!.folds.map((each) => [each.kind, each.closed])).toEqual([
            ["lines", true],
            ["lines", true],
            ["file", false],
            ["item", false],
        ]);
        expect(top).toMatchObject({ of: "54", kind: "lines", name: 'a.py ["","l1"]', label: "3 unchanged lines, 1–3" });
        expect(shown(top!.summary.from, top!.summary.to)).toBe("3 unchanged lines, 1–3");
        expect(top!.from).toBe(top!.summary.to);
        expect(shown(top!.from, top!.to)).toBe("\nl1\nl2\nl3");
        expect(shown(bottom!.from, bottom!.to)).toBe("\nl11\nl12");
        expect(foldKey(top!)).not.toBe(foldKey(bottom!));
        expect(approval!.asides.map((each) => each.kind)).toEqual(["summary", "summary", "refused"]);
        expect(approval!.code.map((each) => [shown(each.from, each.to), each.row?.change ?? "header"])).toEqual([
            ["a.py · changed · +1 −1", "header"],
            ...["l1", "l2", "l3", "l4", "l5", "l6"].map((each) => [each, "same"]),
            ["l7", "removed"],
            ["L7", "added"],
            ...["l8", "l9", "l10", "l11", "l12"].map((each) => [each, "same"]),
        ]);

        const [context] = question!.folds;
        expect(context).toMatchObject({ of: "51", kind: "context", closed: true, label: "context" });
        expect(shown(context!.summary.from, context!.summary.to)).toBe(
            "context · 7 steps, from your words 9m before this item",
        );
        expect(shown(context!.from, context!.to)).toBe(
            "\nyou: Build the reader.\n     Ask me first.\nReading the records.\n" +
                "· called Bash ×2, Read\n→ called mcp__lup__ask · this item\n· called Grep",
        );
        expect(question!.asides.find((each) => each.kind === "anchor")).toMatchObject({
            from: out.text.indexOf("→ called"),
        });
    });

    it("folds a test file whole under its header, and keeps where each line that matters starts, landing on the first", () => {
        const read: Around = {
            contexts: new Map(),
            files: new Map([
                [
                    54,
                    {
                        shown: [
                            {
                                path: "t.py",
                                before: { kind: "text", text: "a\nb\n" },
                                after: { kind: "text", text: "a\nB\n" },
                                reading: { role: "test", asks: [], findings: [] },
                            },
                            {
                                path: "n.py",
                                before: null,
                                after: { kind: "text", text: "x = 1\nimport re\n" },
                                reading: {
                                    role: "production",
                                    asks: [{ name: "new-file", taken: "flagged", side: "after" }],
                                    findings: [{ rule: "regex", message: "a pattern", steer: "", start: 2, end: 2, taken: "told" }],
                                },
                            },
                        ],
                    },
                ],
            ]),
            answers: [],
            commented: [],
        };
        const out = laid([APPROVAL, NOTE], [], banner, header, EMPTY, read);
        const [note, approval] = out.regions;
        const shown = (from: number, to: number) => out.text.slice(from, to);
        const [file, created] = approval!.folds.filter((each) => each.kind === "file");
        expect(file).toMatchObject({ of: "54", kind: "file", name: "t.py", closed: true });
        expect(created).toMatchObject({ name: "n.py", closed: false });
        expect(shown(file!.summary.from, file!.summary.to)).toBe("t.py · changed · +1 −1 · test");
        expect(shown(file!.from, file!.to)).toBe("\na\nb\nB");
        expect(approval!.stops.map((each) => shown(each, out.text.indexOf("\n", each)))).toEqual([
            "n.py · created · 2 lines · new file · told: regex",
            "import re",
        ]);
        expect(approval!.code.find((each) => each.row?.text === "import re")?.matter).toEqual({
            row: 1,
            notes: [{ taken: "told", said: "regex: a pattern" }],
        });
        const commented = laid(
            [APPROVAL],
            [],
            banner,
            header,
            { ...EMPTY, comments: [{ id: "why", item: 54, quote: keptQuote("t.py", 15, 49), text: "Why?" }] },
            read,
        );
        const [kept] = commented.regions[0]!.folds.filter((each) => each.kind === "file");
        expect(commented.text.slice(kept!.summary.to, kept!.from)).toBe("\nWhy?");
        expect(commented.text.slice(kept!.from, kept!.to)).toBe("\na\nb\nB");
        expect(arrival(approval!)).toBe(approval!.stops[0]);
        expect(arrival(note!)).toBe(note!.header.from);
        const done = laid([APPROVAL], [], banner, header, { ...EMPTY, done: [54] }, read);
        expect(arrival(done.regions[0]!)).toBe(done.regions[0]!.header.from);
        expect(stepped([10, 20, 30], 20, true)).toBe(30);
        expect(stepped([10, 20, 30], 20, false)).toBe(10);
        expect(stepped([10, 20, 30], 30, true)).toBeUndefined();
        expect(stepped([10, 20, 30], 5, false)).toBeUndefined();
    });

    it("finds the fold the cursor is on, from its summary line to its last, and opens no comment on a line that isn't the item's own", () => {
        const out = laid([QUESTION, APPROVAL], [], banner, header, EMPTY, around);
        expect(foldAt(out, out.text.indexOf("context ·"))?.kind).toBe("context");
        expect(foldAt(out, out.text.indexOf("Ask me first"))?.kind).toBe("context");
        expect(foldAt(out, out.text.indexOf("l2\n"))?.kind).toBe("lines");
        expect(foldAt(out, out.text.indexOf("L7"))?.kind).toBe("file");
        expect(foldAt(out, out.text.indexOf("Keep the cache"))?.kind).toBe("item");
        expect(foldAt(out, out.text.indexOf("no context"))?.kind).toBe("item");
        expect(foldAt(out, out.text.indexOf("━━ s1"))).toBeUndefined();
        for (const line of ["context ·", "→ called", "3 unchanged", "no context"]) {
            expect(opened(out, out.text.indexOf(line))).toBeUndefined();
        }
        expect(onItem(opened(out, out.text.indexOf("lean: no")))?.item).toBe(51);
    });

    it("says where a context starts by its first step, and how long before the item", () => {
        const agents: Context = {
            ...CONTEXT,
            anchor: 1,
            entries: [
                { kind: "said", by: "agent", text: "Starting.", at: "2026-10-17T10:00:00Z" },
                { kind: "called", tool: "blocked", id: "call-51" },
            ],
        };
        const untimed: Context = { ...agents, entries: [{ kind: "called", tool: "blocked", id: "call-51" }], anchor: 0 };
        const summary = (context: Context) => {
            const out = laid([QUESTION], [], banner, header, EMPTY, { contexts: new Map([[51, { shown: context }]]), files: new Map(), answers: [], commented: [] });
            const [fold] = out.regions[0]!.folds.filter((each) => each.kind === "context");
            return out.text.slice(fold!.summary.from, fold!.summary.to);
        };
        expect(summary(agents)).toBe("context · 2 steps, from 2h before this item");
        expect(summary(untimed)).toBe("context · 1 step");
    });
});

/** A Python module whose `run` method, of `count` lines, holds a change at its tenth, after `head` lines of its own at the top. */
function clock(count: number, changed: boolean, head: string[] = []): string {
    const steps = Array.from({ length: count }, (_, at) => `        step${at + 1}()`);
    if (changed) {
        steps[9] = "        changed()";
    }
    return [...head, '"""A clock."""', "", "", "class Clock:", "    def run(self):", ...steps, "", "", "def after():", "    a = 1", "    return a"].join("\n") + "\n";
}

describe("typed folds", () => {
    const HELD: Item = {
        number: 56,
        reason: { reason: "held", text: "Let it land?", summary: "", worktree: "/w", key: "k" },
        sender: from("s1"),
        recipient: { party: "operator" },
        replies: [],
        citations: [],
        edits: [],
        quiet: false,
        made: AT,
        state: { state: "waiting" },
        rank: WAITING,
    };
    const AUTOMATIC: ChangedFile = {
        path: "t.py",
        before: { kind: "text", text: "a\nb\n" },
        after: { kind: "text", text: "a\nB\n" },
        reading: { role: "test", asks: [], findings: [] },
    };
    const held = (after: string): ChangedFile => ({
        path: "clock.py",
        before: { kind: "text", text: clock(30, false) },
        after: { kind: "text", text: after },
        reading: { role: "production", asks: [{ name: "protected", taken: "held", side: "after" }], findings: [] },
    });
    const around = (after: string): Around => ({
        contexts: new Map([[56, { shown: { ...CONTEXT, number: 56 } }]]),
        files: new Map([[56, { shown: [AUTOMATIC, held(after)] }]]),
        answers: [],
        commented: [],
    });
    const out = laid([HELD, QUESTION], [], banner, header, EMPTY, around(clock(30, true)));
    const region = out.regions.find((each) => each.item.number === 56)!;
    const said = (fold: Fold) => [fold.kind, fold.label, fold.closed];

    it("folds each kind as it's laid out: the item, a file and a body open, a test file, unchanged lines and the context folded", () => {
        // The change is on line 15, in `Clock.run`, whose lines declaring it stay in view, 4 and 5.
        expect(region.folds.map(said)).toEqual([
            ["file", "t.py", true],
            ["lines", "3 unchanged lines, 1–3", true],
            ["lines", "6 unchanged lines, 6–11", true],
            ["lines", "17 unchanged lines, 19–35", true],
            ["body", "Clock", false],
            ["body", "run", false],
            ["lines", "5 unchanged lines, 36–40", true],
            ["body", "after", false],
            ["file", "clock.py", false],
            ["context", "context", true],
            ["item", "── #56 ──", false],
        ]);
        // Marked read, the item folds whole, what's in it as it was.
        const read = laid([HELD], [], banner, header, { ...EMPTY, done: [56] }, around(clock(30, true)));
        expect(read.regions[0]!.folds.map(said).at(-1)).toEqual(["item", "── #56 ──", true]);
    });

    it("nests each fold whole inside another or beside it, never across one's edge", () => {
        const holds = (outer: Fold, inner: Fold) => outer.summary.from <= inner.summary.from && inner.to <= outer.to;
        const apart = (a: Fold, b: Fold) => a.to < b.summary.from || b.to < a.summary.from;
        for (const a of region.folds) {
            for (const b of region.folds) {
                expect(holds(a, b) || holds(b, a) || apart(a, b)).toBe(true);
            }
        }
    });

    it("names each fold by what it hides, so an item laid out again by a later write keeps each the operator left", () => {
        const keys = (laidOut: typeof out) => laidOut.regions.find((each) => each.item.number === 56)!.folds.map(foldKey);
        // A later write adds two lines at the file's top, moving every row and line under them.
        const later = laid([HELD, QUESTION], [], banner, header, EMPTY, around(clock(30, true, ["import os", "import re"])));
        const before = keys(out);
        const after = keys(later);
        for (const kind of ["item", "file", "body", "context"]) {
            expect(after.filter((each) => each.startsWith(`56 ${kind}`))).toEqual(before.filter((each) => each.startsWith(`56 ${kind}`)));
        }
        // Each run keeps its name but the one at the top, which the new lines' context takes: those in the method, and
        // the one holding the function after it, though they all start lower.
        const runs = (keys: string[]) => keys.filter((each) => each.startsWith("56 lines"));
        expect(runs(after)).toEqual(runs(before).slice(1));
        expect(runs(before)).toHaveLength(4);
    });

    it("reaches the folds of the item the cursor is in alone, for `zr`, `zm` and Space z", () => {
        const at = (text: string) => out.text.indexOf(text);
        expect(foldsOf(out, at("step3()")).map((each) => each.of)).toEqual(region.folds.map(() => "56"));
        expect(foldsOf(out, at("Which parser?")).every((each) => each.of === "51")).toBe(true);
        expect(foldsOf(out, at("━━ s1"))).toEqual([]);
        // zr from the held change opens its test file alone, then its runs and bodies, then its context.
        const closed = new Set(region.folds.filter((each) => each.closed));
        const step = (opening: boolean) => {
            const changed = levelled(foldsOf(out, at("step3()")), (fold) => closed.has(fold), opening, false);
            for (const fold of changed) {
                if (opening) {
                    closed.delete(fold);
                } else {
                    closed.add(fold);
                }
            }
            return changed.map((each) => each.kind);
        };
        expect(step(true)).toEqual(["file"]);
        expect(step(true)).toEqual(["lines", "lines", "lines", "lines"]);
        expect(step(true)).toEqual(["context"]);
        expect(step(true)).toEqual([]);
        expect(step(false)).toEqual(["context"]);
        expect(step(false)).toEqual(["lines", "lines", "lines", "body", "body", "lines", "body"]);
        expect(step(false)).toEqual(["file", "file"]);
        expect(step(false)).toEqual([]);
        expect([...closed].every((each) => each.of === "56")).toBe(true);
    });

    it("says in the header where the cursor is: the group, the item, the file and the folds it's in", () => {
        const draft: Draft = { ...EMPTY, comments: [{ id: "why", item: 56, quote: null, text: "Why?" }], letters: [{ id: "hi", to: from("s1", "a1"), text: "Hi." }] };
        const wrote = laid([HELD, QUESTION], [], banner, header, draft, around(clock(30, true)));
        const naming: Naming = {
            group: (group) => `group ${group.conversation?.session ?? "lup"}`,
            item: (each) => `#${each.item.number}`,
            party: (party) => `agent ${party.session}${party.agent === null ? "" : `/${party.agent}`}`,
        };
        const at = (text: string) => wrote.text.indexOf(text);
        const says = (position: number, writing = false) =>
            heading(wrote, position, writing, written(draft), naming).map((each) => `${each.kind}: ${each.text}`);
        expect(says(at("━━ s1"))).toEqual(["group: group s1"]);
        expect(says(at("Let it land?"))).toEqual(["group: group s1", "item: #56"]);
        expect(says(at("t.py · changed"))).toEqual(["group: group s1", "item: #56", "file: t.py"]);
        expect(says(at("step3()"))).toEqual([
            "group: group s1",
            "item: #56",
            "file: clock.py",
            "body: Clock",
            "body: run",
            "lines: 6 unchanged lines, 6–11",
        ]);
        expect(says(at("changed()"))).toEqual(["group: group s1", "item: #56", "file: clock.py", "body: Clock", "body: run"]);
        expect(says(at("→ called"))).toEqual(["group: group s1", "item: #56", "context: context"]);
        // While a comment is written, whom it goes to; a message, the agent it's to.
        expect(says(at("Why?"), true)).toEqual(["to: to agent s1", "group: group s1", "item: #56"]);
        expect(says(at("Hi."), true)).toEqual(["to: to agent s1/a1", "group: group s1"]);
        expect(says(0, true)).toEqual(["group: group s1"]);
        expect(heading(laid([], [], banner, header, EMPTY, NOTHING), 0, false, [], naming)).toEqual([]);
    });

    it("sends a comment on an approval to the session whose push asked it, and none where none did", () => {
        expect(recipient(APPROVAL)).toBeNull();
        expect(recipient({ ...APPROVAL, reason: { ...APPROVAL.reason, pushed_by: from("s9") } as Item["reason"] })).toEqual(from("s9"));
        expect(recipient(NOTE)).toEqual(from("s2"));
    });
});

describe("what a change shows open, as it's laid out", () => {
    /** Thirty lines, `l1` to `l30`, each replaced where `changed` says. */
    const thirty = (changed: Record<number, string> = {}) =>
        Array.from({ length: 30 }, (_, at) => changed[at + 1] ?? `l${at + 1}`).join("\n") + "\n";
    /** A file whose tenth line changes and whose twentieth adds a function, which asks on that line alone. */
    const signed: ChangedFile = {
        path: "a.py",
        before: { kind: "text", text: thirty() },
        after: { kind: "text", text: thirty({ 10: "ten" }) },
        reading: {
            role: "production",
            asks: [{ name: "public-api", taken: "flagged", line: 20, side: "after", api: { kind: "function-added", name: "f" } }],
            findings: [],
        },
    };
    const HELD: Item = {
        number: 57,
        reason: { reason: "held", text: "Let it land?", summary: "", worktree: "/w", key: "k" },
        sender: from("s1"),
        recipient: { party: "operator" },
        replies: [],
        citations: [],
        edits: [],
        quiet: false,
        made: AT,
        state: { state: "waiting" },
        rank: WAITING,
    };
    /** The runs of lines folded under `item`, changing `signed`, as it's laid out, and whether its change on line 10 is among what they hide. */
    const folded = (item: Item) => {
        const around: Around = { contexts: new Map(), files: new Map([[item.number, { shown: [signed] }]]), answers: [], commented: [] };
        const out = laid([item], [], banner, header, EMPTY, around);
        const runs = out.regions[0]!.folds.filter((each) => each.kind === "lines" && each.closed);
        const ten = out.text.indexOf("\nten\n") + 1;
        return { runs: runs.map((each) => each.label), hidden: runs.some((each) => ten > each.from && ten <= each.to) };
    };
    /** Unchanged lines alone folded, three kept around the change on line 10 and around the line that asks. */
    const everyChange = { runs: ["6 unchanged lines, 1–6", "3 unchanged lines, 14–16", "7 unchanged lines, 24–30"], hidden: false };

    it("opens every change of a held change, folding only unchanged lines, 3 kept around each change and each line that matters", () => {
        expect(folded(HELD)).toEqual(everyChange);
        expect(folded(FLAGGED)).toEqual(everyChange);
    });

    it("opens every change of an approval too, however many lines it changes", () => {
        expect(folded(APPROVAL)).toEqual(everyChange);
    });

    /** Whether each of `files` folds whole under `item`, by its path. */
    const whole = (item: Item, files: ChangedFile[]) => {
        const around: Around = { contexts: new Map(), files: new Map([[item.number, { shown: files }]]), answers: [], commented: [] };
        const out = laid([item], [], banner, header, EMPTY, around);
        return Object.fromEntries(out.regions[0]!.folds.filter((each) => each.kind === "file").map((each) => [each.name, each.closed]));
    };
    const read = (path: string, role: string): ChangedFile => ({ ...signed, path, reading: { role, asks: [], findings: [] } });
    const FILES = [read("a.py", "production"), read("t.py", "test"), read("d.json", "data"), read("n.md", "docs")];

    it("folds whole, in every kind of change, a file that asks nothing, a test and a data file, and opens one that asks", () => {
        const asking: ChangedFile = { ...read("f.py", "production"), reading: { role: "production", asks: [{ name: "new-file", taken: "flagged", side: "after" }], findings: [] } };
        const expected = { "a.py": true, "t.py": true, "d.json": true, "n.md": true, "f.py": false };
        expect(whole(HELD, [...FILES, asking])).toEqual(expected);
        expect(whole(APPROVAL, [...FILES, asking])).toEqual(expected);
    });

    it("folds each file of a first approval whole under its header, which says so, and counts them so in the item's", () => {
        const first: Item = { ...APPROVAL, reason: { ...APPROVAL.reason, first: true } as Item["reason"] };
        expect(Object.values(whole(first, FILES))).toEqual([true, true, true, true]);
        const around: Around = { contexts: new Map(), files: new Map([[54, { shown: [read("a.py", "production")] }]]), answers: [], commented: [] };
        const out = laid([first], [], banner, header, EMPTY, around);
        expect(out.text).toContain("a.py · changed · +1 −1 · first approval\n");
    });
});

describe("comments on a changed file's lines", () => {
    const HELD: Item = {
        number: 55,
        reason: { reason: "held", text: "Let the change to 2 files land?", summary: "a.py: asks", worktree: "/w", key: "k" },
        sender: from("s1"),
        recipient: { party: "operator" },
        replies: [],
        citations: [],
        edits: [],
        quiet: false,
        made: AT,
        state: { state: "waiting" },
        rank: WAITING,
    };
    const CREATED: ChangedFile = { path: "b.md", before: null, after: { kind: "text", text: "# B\n\nNew.\n" } };
    const around: Around = { contexts: new Map(), files: new Map([[55, { shown: [CHANGED, CREATED] }]]), answers: [], commented: [] };
    const out = laid([HELD], [], banner, header, EMPTY, around);
    const at = (line: string) => out.text.indexOf(`\n${line}\n`) + 1;

    it("quotes a line under its file's path and number, marked as a diff marks it, and shows the comment under it", () => {
        const added = onItem(opened(out, at("L7")));
        expect(added?.quote?.text).toBe("a.py:7\n+L7");
        expect(onItem(opened(out, at("l7")))?.quote?.text).toBe("a.py:7, as it was before the change\n-l7");
        expect(onItem(opened(out, at("l8")))?.quote?.text).toBe("a.py:8\n l8");
        expect(onItem(opened(out, at("a.py · changed · +1 −1")))?.quote?.text).toBe("a.py");
        expect(onItem(opened(out, at("b.md · created · 3 lines")))?.quote?.text).toBe("b.md");

        const comment = { ...added!, id: "why", text: "Why capitals?" };
        const commented = laid([HELD], [], banner, header, { ...EMPTY, comments: [comment] }, around);
        expect(commented.text).toContain("\nL7\nWhy capitals?\nl8\n");
        const [region] = commented.regions;
        const passage = quotedAt(commented, region!, comment)!;
        expect(commented.text.slice(passage.from, passage.to)).toBe("L7");
    });

    it("opens a comment on an empty line of a file, not on the item whole", () => {
        const empty = out.text.indexOf("# B\n\n") + "# B\n".length;
        expect(onItem(opened(out, empty))?.quote?.text).toBe("b.md:2\n+");
    });

    it("shows a flagged write's file under it as a held change's, where one is still laid out, its lines quoted the same", () => {
        const flagged = laid([FLAGGED], [], banner, header, EMPTY, { contexts: new Map(), files: new Map([[70, { shown: [CHANGED] }]]), answers: [], commented: [] });
        const line = (text: string) => flagged.text.indexOf(`\n${text}\n`) + 1;
        expect([changing(FLAGGED), changing(HELD), changing(NOTE)]).toEqual([true, true, false]);
        expect(flagged.text.startsWith("━━ s2 ━━\n── #70 ──\na.py landed, flagged for the operator's review.\n")).toBe(true);
        expect(flagged.regions[0]!.code.length).toBeGreaterThan(0);
        expect(onItem(opened(flagged, line("L7")))).toEqual({ id: "", item: 70, quote: expect.objectContaining({ text: "a.py:7\n+L7", lines: ["L7"] }), text: "" });
        // A flagged write is read, never declined, in its file as in its text.
        expect(reaches(flagged, line("L7"), "done")).toBe("@70 landed, flagged: mark it read");
        expect(reaches(flagged, flagged.text.indexOf("a.py landed"), "decline")).toBeNull();
    });


    it("quotes a passage across a file's lines, and across files, each under its path and the span of its lines", () => {
        const from = at("l6");
        expect(onItem(quoted(out, from, at("l8") - 1))?.quote?.text).toBe("a.py:6-7\n l6\n-l7\n+L7");
        expect(onItem(quoted(out, at("l12") + 1, at("New.") + 3))?.quote?.text).toBe("a.py:12\n 12\nb.md:1-3\n+# B\n+\n+New");
    });

    it("says an item's comments as one answer, each under what it quotes", () => {
        const comments: Comment[] = [
            { id: "fine", item: 55, quote: null, text: "Otherwise fine." },
            { id: "why", item: 55, quote: keptQuote("a.py:7\n+L7", 40, 42), text: "Why capitals?" },
            { id: "blank", item: 55, quote: keptQuote("a.py", 20, 24), text: " " },
        ];
        expect(answer(comments)).toBe("> a.py:7\n> +L7\n\nWhy capitals?\n\nOtherwise fine.");
    });
});

describe("every agent's group, and the messages under its banner", () => {
    const S3 = from("s3");
    const S4 = from("s4");

    it("gives each agent running a group, empty after those with items in the agents' order, and the parked ones last", () => {
        const out = laid([QUESTION, NOTE], [S3, from("s2"), S4, from("s1", "a1")], banner, header, { ...EMPTY, parked: [52] }, NOTHING);
        expect(out.text).toBe(
            "━━ s1 ━━\n── #51 ──\nWhich parser?\n1. Use lark\n   lean: yes\n2. Keep the cache\n   lean: no\n\n" +
                "━━ s3 ━━\n━━ s2 ━━\n━━ s4 ━━\n" +
                "━━ s2 · later ━━\n── #52 · later ──\nI assumed UTF-8.\n\n",
        );
        expect(out.groups.map((each) => [each.conversation?.session ?? null, each.later])).toEqual([
            ["s1", false],
            ["s3", false],
            ["s2", false],
            ["s4", false],
            ["s2", true],
        ]);
        const approvals = laid([APPROVAL], [], banner, header, EMPTY, NOTHING);
        expect(approvals.groups.map((each) => each.conversation)).toEqual([null]);
    });

    it("writes each message under its agent's banner, after the comments in what's written, an empty group's set off by a blank line", () => {
        const S9 = from("s9");
        const draft: Draft = {
            ...EMPTY,
            comments: [{ id: "noted", item: 52, quote: null, text: "Noted." }],
            letters: [
                { id: "cache", to: S3, text: "Look at the cache too." },
                { id: "rename", to: from("s2"), text: "And rename it." },
                { id: "there", to: S9, text: "Still there?" },
            ],
        };
        const out = laid([NOTE], [S3, S4], banner, header, draft, NOTHING);
        expect(out.text).toBe(
            "━━ s2 ━━\nAnd rename it.\n── #52 ──\nNoted.\nI assumed UTF-8.\n\n" +
                "━━ s3 ━━\nLook at the cache too.\n\n━━ s4 ━━\n━━ s9 ━━\nStill there?\n\n",
        );
        const shown = (block: { from: number; to: number }) => out.text.slice(block.from, block.to);
        expect(out.groups.map((each) => each.blocks.map((block) => [block.comment, shown(block)]))).toEqual([
            [["rename", "And rename it."]],
            [["cache", "Look at the cache too."]],
            [],
            [["there", "Still there?"]],
        ]);
        expect(blockAt(out, out.text.indexOf("Still there?"))?.comment).toBe("there");
        expect(written(draft).map((each) => each.text)).toEqual(["Noted.", "Look at the cache too.", "And rename it.", "Still there?"]);
    });

    it("opens a message to a group's agent on its banner, a parked group's among them, but none to lup's approvals", () => {
        const draft: Draft = { ...EMPTY, parked: [51], letters: [{ id: "hi", to: S3, text: "Hi." }] };
        const out = laid([QUESTION, APPROVAL], [S3], banner, header, draft, NOTHING);
        const at = (line: string) => out.text.indexOf(line);
        expect(opened(out, at("━━ s3"))).toEqual({ id: "", to: S3, text: "" });
        expect(opened(out, at("Hi."))).toEqual({ id: "", to: S3, text: "" });
        expect(opened(out, at("━━ s1 · later"))).toEqual({ id: "", to: from("s1", "a1"), text: "" });
        expect(opened(out, at("━━ lup"))).toBeUndefined();
        expect(quoted(out, at("━━ s3"), at("━━ s3") + 4)).toEqual({ id: "", to: S3, text: "" });
        expect(quoted(out, at("━━ s1 · later"), at("Which parser?") + 5)).toBeUndefined();
        expect(regionAt(out, at("━━ s3"))).toBeUndefined();
        expect(regionAt(out, at("── #51"))?.item.number).toBe(51);
        expect(regionAt(out, at("Approve?"))?.item.number).toBe(54);
        expect(groupAt(out, at("Hi."))?.conversation).toEqual(S3);
        expect(groupAt(out, at("Approve?"))).toBeUndefined();
    });

    it("keeps each group where it was this sitting, items coming and going, and lays a new one after them", () => {
        const S1 = from("s1", "a1");
        const first = laid([QUESTION, NOTE], [S1, S3], banner, header, EMPTY, NOTHING);
        const heads = (out: typeof first) => out.text.split("\n").filter((line) => line.startsWith("━━"));
        expect(heads(first)).toEqual(["━━ s1 ━━", "━━ s2 ━━", "━━ s3 ━━"]);
        const places = first.groups.map((each) => each.place);
        // s2's note answered, its agent running, and a newer item for s1: they keep their places, and s4's comes after.
        const newer: Item = { ...QUESTION, number: 60, made: "2026-10-17T13:00:00Z" };
        const fourth: Item = { ...NOTE, number: 61, sender: S4 };
        const next = laid([QUESTION, newer, fourth], [S1, S3, from("s2")], banner, header, EMPTY, NOTHING, places);
        expect(heads(next)).toEqual(["━━ s1 ━━", "━━ s2 ━━", "━━ s3 ━━", "━━ s4 ━━"]);
        // Laid out anew from the items alone, as on reload: s4's where its first item came, the empty ones after.
        expect(heads(laid([QUESTION, newer, fourth], [S1, S3, from("s2")], banner, header, EMPTY, NOTHING))).toEqual([
            "━━ s1 ━━",
            "━━ s4 ━━",
            "━━ s3 ━━",
            "━━ s2 ━━",
        ]);
        // A group's first item answered: it keeps its place this sitting, though anew it would come after.
        const third: Item = { ...QUESTION, number: 53 };
        expect(heads(laid([third, NOTE], [S1], banner, header, EMPTY, NOTHING, places))).toEqual(["━━ s1 ━━", "━━ s2 ━━"]);
        expect(heads(laid([third, NOTE], [S1], banner, header, EMPTY, NOTHING))).toEqual(["━━ s2 ━━", "━━ s1 ━━"]);
        // What's left for later has places of its own.
        const parked = laid([QUESTION, NOTE], [S1, S3], banner, header, { ...EMPTY, parked: [52] }, NOTHING, places);
        expect(heads(parked)).toEqual(["━━ s1 ━━", "━━ s3 ━━", "━━ s2 · later ━━"]);
    });

    it("keeps each group where the operator saw it across a reload, from the order the host keeps, telling it what's gone", () => {
        const S1 = from("s1", "a1");
        const heads = (out: Laid) => out.text.split("\n").filter((line) => line.startsWith("━━"));
        const placesOf = (out: Laid) => out.groups.map((each) => each.place);
        // The host keeps no order yet: the page tells it every place it laid out.
        const first = laid([QUESTION, NOTE], [S1, S3], banner, header, EMPTY, NOTHING, ordered([], []));
        expect(toKeep(placesOf(first), [], [])).toEqual({ places: placesOf(first), gone: [] });
        const kept = placesOf(first);
        // s2's note answered, its agent running, and an item for s4: s4's place told, after the others.
        const newer: Item = { ...QUESTION, number: 60, made: "2026-10-17T13:00:00Z" };
        const fourth: Item = { ...NOTE, number: 61, sender: S4 };
        const now = [QUESTION, newer, fourth];
        const running = [S1, S3, from("s2")];
        const next = laid(now, running, banner, header, EMPTY, NOTHING, ordered(placesOf(first), kept));
        expect(heads(next)).toEqual(["━━ s1 ━━", "━━ s2 ━━", "━━ s3 ━━", "━━ s4 ━━"]);
        expect(toKeep(placesOf(next), placesOf(first), kept)).toEqual({ places: placesOf(next), gone: [] });
        const host = placesOf(next);
        // Reloaded, the page holding nothing: laid out from the host's order, the same, with nothing to tell; from the
        // items alone it would differ.
        const reloaded = laid(now, running, banner, header, EMPTY, NOTHING, ordered([], host));
        expect(heads(reloaded)).toEqual(heads(next));
        expect(heads(laid(now, running, banner, header, EMPTY, NOTHING))).toEqual(["━━ s1 ━━", "━━ s4 ━━", "━━ s3 ━━", "━━ s2 ━━"]);
        expect(toKeep(placesOf(reloaded), host, host)).toBeNull();
        // Nothing waiting, every agent running still: each keeps its place, not the agents' order.
        const nothing = laid([], [S3, from("s2"), S1, S4], banner, header, EMPTY, NOTHING, ordered(placesOf(reloaded), host));
        expect(heads(nothing)).toEqual(["━━ s1 ━━", "━━ s2 ━━", "━━ s3 ━━", "━━ s4 ━━"]);
        // s3 gone, no item and not running: its place is told gone, and back, it comes after the others.
        const without = laid([], [from("s2"), S1, S4], banner, header, EMPTY, NOTHING, ordered(placesOf(nothing), host));
        const told = toKeep(placesOf(without), placesOf(nothing), host);
        expect(told?.gone).toEqual([`now ${whose(S3)}`]);
        const left = host.filter((each) => !(told?.gone ?? []).includes(each));
        const back = laid([], [S3, from("s2"), S1, S4], banner, header, EMPTY, NOTHING, ordered(placesOf(without), left));
        expect(heads(back)).toEqual(["━━ s1 ━━", "━━ s2 ━━", "━━ s4 ━━", "━━ s3 ━━"]);
    });

    it("lays out what this page laid out first, then what the host keeps of others, and leaves another page's places to it", () => {
        // This page's order wins over the host's, which another page made, for what it lays out.
        expect(ordered(["now a", "now b"], ["now b", "now x", "now a"])).toEqual(["now a", "now b", "now x"]);
        // A place another page laid out and this one doesn't: told nothing of it, and nothing told at all.
        expect(toKeep(["now a"], ["now a"], ["now a", "now x"])).toBeNull();
        // As it first lays the review out from the host's order, every place it doesn't lay out is gone.
        expect(toKeep(["now a"], ["now a", "now x"], ["now a", "now x"])).toEqual({ places: ["now a"], gone: ["now x"] });
        // One it laid out that the host no longer keeps, gone already: nothing to tell.
        expect(toKeep(["now a"], ["now a", "now y"], ["now a"])).toBeNull();
    });

    it("keeps what the editor holds in the draft's two lists, and sends only the messages that say something", () => {
        const letter = { id: "hi", to: S3, text: "Hi." };
        const comment = { id: "yes", item: 51, quote: null, text: "Yes." };
        const draft = withWritten(EMPTY, [letter, comment, { id: "blank", to: S4, text: " " }]);
        expect(draft.comments).toEqual([comment]);
        expect(draft.letters).toEqual([letter, { id: "blank", to: S4, text: " " }]);
        expect(written(draft).indexOf(letter)).toBe(1);
        expect(messages(draft)).toEqual([letter]);
        expect(pruned(draft).letters).toEqual([letter]);
        expect(isLetter(letter)).toBe(true);
        expect(isLetter(comment)).toBe(false);
        expect(whose(from("s1", "a1"))).not.toBe(whose(from("s1")));
    });
});

describe("replies kept from before", () => {
    /** The operator's review that answered the note: a comment on its passage, and the agent's reply to it, kept on the review after its one part. */
    const REVIEW: Item = {
        number: 60,
        reason: {
            reason: "review",
            covers: [52],
            comments: [{ id: "", item: 52, quote: keptQuote("UTF-8", 10, 15), on: null, text: "Every one?" }],
            letters: [],
            remarks: [],
        },
        sender: { party: "operator" },
        recipient: from("s2"),
        replies: [{ number: 2, to: { item: 60, part: 1 }, text: "Every one I read.\nA stray byte is replaced.", at: AT }],
        citations: [],
        edits: [],
        quiet: false,
        made: AT,
        state: { state: "told", at: AT, how: "call" },
        rank: WAITING,
    };
    /** The operator's answer to the question: a ruling on each decision, and a comment on the whole, the second ruling replied to. */
    const ANSWER: Item = {
        number: 61,
        reason: {
            reason: "answer",
            question: 51,
            rulings: [
                { decision: 1, verdict: "leaning", comment: "" },
                { decision: 2, verdict: null, comment: "Drop it." },
            ],
            comment: "Go.",
        },
        sender: { party: "operator" },
        recipient: from("s1", "a1"),
        replies: [{ number: 4, to: { item: 61, part: 2 }, text: "Dropped.", at: AT }],
        citations: [],
        edits: [],
        quiet: false,
        made: AT,
        state: { state: "told", at: AT, how: "call" },
        rank: WAITING,
    };
    const around: Around = { contexts: new Map(), files: new Map(), answers: [REVIEW, ANSWER], commented: [] };

    it("reads them from the operator's items answering the item: each comment by its part's id, and the replies to them", () => {
        expect(threadsOf([REVIEW, ANSWER], 52)).toEqual({
            said: [{ id: { item: 60, part: 1 }, text: "Every one?", quote: keptQuote("UTF-8", 10, 15), on: null, decision: null }],
            replies: [{ id: { item: 60, part: 2 }, to: { item: 60, part: 1 }, text: "Every one I read.\nA stray byte is replaced." }],
        });
        expect(threadsOf([REVIEW, ANSWER], 51).said.map((each) => [each.id.part, each.text, each.decision])).toEqual([
            [1, "leaning", 1],
            [2, "Drop it.", 2],
            [3, "Go.", null],
        ]);
    });

    it("lays them after the item's own words, each after who wrote it, read and never commented", () => {
        const out = laid([QUESTION, NOTE], [], banner, header, EMPTY, around);
        expect(out.text).toBe(
            "━━ s1 ━━\n── #51 ──\nWhich parser?\n1. Use lark\n   lean: yes\n2. Keep the cache\n   lean: no\n" +
                "you · @61.1\n  leaning\nyou · @61.2\n  Drop it.\na1 · @61.4, a reply kept from before\n  Dropped.\nyou · @61.3\n  Go.\n\n" +
                "━━ s2 ━━\n── #52 ──\nI assumed UTF-8.\nyou · @60.1\n  on “UTF-8”\n  Every one?\ns2 · @60.2, a reply kept from before\n  Every one I read.\n  A stray byte is replaced.\n\n",
        );
        const [, note] = out.regions;
        expect(note!.asides.map((each) => each.kind)).toEqual(["by", "quoted", "you", "by", "agent", "agent"]);
        expect(opened(out, out.text.indexOf("A stray"))).toBeUndefined();
        expect(reaches(out, out.text.indexOf("A stray"), "done")).toBe("@52 note: mark it read");
    });

    it("puts a comment copies before kept on a reply under the item's header", () => {
        const comment: Comment = { id: "fine", item: 52, quote: keptQuote("stray", 20, 25), on: { item: 60, part: 2 }, text: "Fine." };
        const written = laid([NOTE], [], banner, header, { ...EMPTY, comments: [comment] }, around);
        expect(written.text.startsWith("━━ s2 ━━\n── #52 ──\nFine.\nI assumed UTF-8.\n")).toBe(true);
        const [block] = written.regions[0]!.blocks;
        expect(aboutAt(written, comment, block!)).toBe(written.regions[0]!.header.from);
    });
});

describe("an answer in a turn's last words", () => {
    const SESSION = from("s2");
    /** The operator's review the turn's end answers: a comment on the session's note, one on another agent's, and a message to the session. */
    const REVIEW: Item = {
        number: 70,
        reason: {
            reason: "review",
            covers: [52, 90],
            comments: [
                { id: "", item: 52, quote: keptQuote("UTF-8", 10, 15), on: null, text: "Every one? Even a stray byte?" },
                { id: "", item: 90, quote: null, on: null, text: "Not yours." },
            ],
            letters: [{ id: "", to: SESSION, text: "Then split the reader\nout of the parser." }],
            remarks: [],
        },
        sender: { party: "operator" },
        recipient: SESSION,
        replies: [],
        citations: [],
        edits: [],
        quiet: false,
        made: AT,
        state: { state: "told", at: AT, how: "call" },
        rank: WAITING,
    };
    const OTHERS: Item = { ...NOTE, number: 90, sender: from("s9") };
    const END: Item = {
        ...NOTE,
        number: 72,
        reason: {
            reason: "message",
            passages: [],
            answers: [70],
            ending: true,
            kind: "note",
            text: "Every one, @70.1[Even a stray byte?].\nSplitting it @70[nothing] next.",
        },
        rank: NEWS,
        citations: [
            {
                said: "@70.1[Even a stray byte?]",
                start: 11,
                end: 36,
                item: 70,
                part: 1,
                words: "Even a stray byte?",
                found: { part: { item: 70, part: 1 }, start: 11, end: 29, text: "Even a stray byte?" },
                candidates: [],
            },
            { said: "@70[nothing]", start: 51, end: 63, item: 70, part: null, words: "nothing", found: null, candidates: [] },
        ],
        edits: [{ at: "2026-10-17T12:05:00Z", before: "Every one.\nSplitting it @70[nothing] next." }],
    };
    const around: Around = { contexts: new Map(), files: new Map(), answers: [REVIEW], commented: [NOTE, OTHERS] };

    it("lays the operator's words it answers above it, its own after the agent's name, each passage it cites folded under its line", () => {
        const out = laid([END], [], banner, header, EMPTY, around);
        expect(out.text).toBe(
            "━━ s2 ━━\n── #72 ──\n" +
                "you · @70, your review\n  Then split the reader\n  out of the parser.\n  on @52: “UTF-8”\n  Every one? Even a stray byte?\n" +
                "s2 · @72, its answer\n" +
                "edited 5m after it was sent · 1 line changed\n− Every one.\n+ Every one, @70.1[Even a stray byte?].\n" +
                "Every one, @70.1[Even a stray byte?].\nyou, @70.1: Even a stray byte?\nSplitting it @70[nothing] next.\n\n",
        );
        const [region] = out.regions;
        // The operator's words above it are theirs, by part, where its citations' passages are marked.
        expect(region!.said.map((each) => [out.text.slice(each.from, each.to), each.part.part, each.own])).toEqual([
            ["  Then split the reader", 3, -2],
            ["  out of the parser.", 3, 20],
            ["  Every one? Even a stray byte?", 1, -2],
        ]);
        expect(region!.changed).toEqual([out.text.indexOf("\nEvery one, @70.1") + 1]);
        expect(region!.folds.map((each) => [each.kind, each.name, each.closed])).toEqual([
            ["context", "you", false],
            ["context", "edited", true],
            ["context", "cited 0", true],
            ["item", "", false],
        ]);
        // Nothing but its own words takes a comment.
        expect(opened(out, out.text.indexOf("Then split"))).toBeUndefined();
        expect(opened(out, out.text.indexOf("you, @70.1:"))).toBeUndefined();
        expect(onItem(opened(out, out.text.indexOf("Splitting")))?.quote?.text).toBe("Splitting it @70[nothing] next.");
    });

    it("places each citation where it's shown, the passage it marks above, and follows one to the other", () => {
        const out = laid([END], [], banner, header, EMPTY, around);
        const [found, unresolved] = citationsOf(out);
        const slice = (span: { from: number; to: number }) => out.text.slice(span.from, span.to);
        expect([slice(found!.written), slice(found!.marker), found!.passages.map(slice), found!.fold?.name]).toEqual([
            "@70.1[Even a stray byte?]",
            "@70.1",
            ["Even a stray byte?"],
            "cited 0",
        ]);
        expect([slice(unresolved!.written), slice(unresolved!.marker), unresolved!.passages, unresolved!.fold]).toEqual(["@70[nothing]", "@70[nothing]", [], null]);
        // gd goes from the citation to the passage it cites, and back; nowhere from elsewhere.
        expect(following(citationsOf(out), found!.marker.from + 2)).toBe(found!.passages[0]!.from);
        expect(following(citationsOf(out), found!.passages[0]!.from + 3)).toBe(found!.written.from);
        expect(following(citationsOf(out), unresolved!.written.from)).toBeUndefined();
        expect(following(citationsOf(out), out.text.indexOf("Splitting"))).toBeUndefined();
    });

    it("numbers the operator's words as the host does, after replies kept from before, and shows an agent the parts that were its own", () => {
        const kept: Item = { ...REVIEW, replies: [{ number: 3, to: { item: 70, part: 1 }, text: "Old.", at: AT }] };
        expect(spokenOf(REVIEW).map((each) => [each.id.part, each.text])).toEqual([
            [1, "Every one? Even a stray byte?"],
            [2, "Not yours."],
            [3, "Then split the reader\nout of the parser."],
        ]);
        expect(spokenOf(kept).map((each) => each.id.part)).toEqual([1, 2, 4]);
        expect(spokenOf(NOTE)).toEqual([]);
        expect(above(END, [REVIEW], [NOTE, OTHERS]).map((each) => each.text)).toEqual([
            "you · @70, your review",
            "  Then split the reader",
            "  out of the parser.",
            "  on @52: “UTF-8”",
            "  Every one? Even a stray byte?",
        ]);
    });

    it("says a comment outdated where an edit changed the passage it quotes", () => {
        const edited: Item = { ...NOTE, reason: { ...NOTE.reason, text: "I assumed ASCII." } as Item["reason"], edits: [{ at: AT, before: "I assumed UTF-8." }] };
        expect([outdated(NOTE, { text: "UTF-8", start: 10, end: 15 }), outdated(edited, { text: "UTF-8", start: 10, end: 15 }), outdated(edited, { text: "I assumed", start: 0, end: 9 })]).toEqual([
            false,
            true,
            false,
        ]);
        const later = laid([END], [], banner, header, EMPTY, { ...around, commented: [edited, OTHERS] });
        expect(later.text).toContain("  on @52: “UTF-8” · outdated: the passage changed\n");
    });
});

describe("the draft", () => {
    it("says what it covers, items marked done or declined among it, but those parked, and drops comments that say nothing", () => {
        const draft: Draft = { ...EMPTY, done: [52], declined: [55], comments: [{ id: "x", item: 53, text: "x" }, { id: "blank", item: 54, text: "  " }] };
        expect(covered(draft)).toEqual([52, 53, 55]);
        expect(covered({ ...draft, parked: [53] })).toEqual([52, 55]);
        expect(pruned(draft).comments).toEqual([{ id: "x", item: 53, text: "x" }]);
        expect(pruned({ ...draft, comments: [{ id: "x", item: 53, text: "x \n\n" }] }).comments).toEqual([{ id: "x", item: 53, text: "x" }]);
    });
});

describe("waited and fresh", () => {
    it("says how long an item has waited, to the minute", () => {
        const now = new Date("2026-10-17T14:00:30Z");
        expect(waited("2026-10-17T14:00:00Z", now)).toBe("just in");
        expect(waited("2026-10-17T13:55:00Z", now)).toBe("waiting 5m");
        expect(waited("2026-10-15T14:00:00Z", now)).toBe("waiting 2d");
    });

    it("marks what came after the operator last settled an item, and nothing before they first did", () => {
        expect(fresh(QUESTION, "2026-10-17T11:00:00Z")).toBe(true);
        expect(fresh(QUESTION, "2026-10-17T12:30:00Z")).toBe(false);
        expect(fresh(QUESTION, null)).toBe(false);
    });
});

describe("the drawers under each agent's banner", () => {
    // Its conversation is `Transcripts`' answer of its record (`fixtures/conversation.json`): the operator's words
    // `Build the reader.` opening an earlier exchange, the agent's `Reading the records.` and two calls in it, read as its
    // fold opens; then their words `Ask me first.`, the agent's two paragraphs, and a call.
    const S1 = from("s1", "a1");
    const READER = '"""Reader."""\n\n\nclass Reader:\n    def turns(self):\n        a = 1\n        b = 2\n        return a + b\n';
    const SINCE: Since = {
        kind: "policy-since",
        worktree: "/w/feat",
        branch: "feat",
        version: "t1 0",
        same: false,
        files: [
            {
                path: "reader.py",
                file: {
                    path: "reader.py",
                    before: null,
                    after: { kind: "text", text: READER },
                    reading: { role: "production", asks: [{ name: "new-file", taken: "flagged", side: "after" }], findings: [] },
                },
                version: "b1",
                flags: [70],
                since: null,
            },
        ],
    };
    const DATA: AgentDrawers = {
        tasks: [
            { id: "1", subject: "Write the sampler", status: "completed", active: null },
            { id: "2", subject: "Write the models", status: "in_progress", active: "Writing the models" },
            { id: "3", subject: "Measure", status: "pending", active: null },
        ],
        usage: { used: 112_000, window: 1_000_000, model: null },
        since: SINCE,
    };
    const drawers: Drawers = new Map([[whose(S1), DATA]]);
    // What the host answered of the agent's views the page doesn't lay out itself: its conversation, and its earlier exchange.
    const remote = ANSWERED;
    const out = laid([QUESTION, NOTE], [S1], banner, header, EMPTY, NOTHING, [], drawers, undefined, { remote });
    const at = (text: string) => out.text.indexOf(text);
    const lines = (from: number, to: number) => out.text.slice(from, to).split("\n");

    it("lays the drawers under the banner, before the items, each its own fold, folded, a new module's bodies folded too", () => {
        const [group] = out.groups;
        expect(group?.drawers.map((each) => each.kind)).toEqual(["tasks", "since", "conversation"]);
        expect(out.groups[1]?.drawers).toEqual([]);
        const texts = out.drawers.map((each) => lines(each.header.from, each.folds.at(-1)!.to));
        expect(texts[0]).toEqual(["tasks 1/3", "✓ Write the sampler", "▶ Writing the models", "· Measure"]);
        expect(texts[1]?.slice(0, 2)).toEqual(["since you approved · 1 to review · 1 flagged", "reader.py · created · 8 lines · new file"]);
        expect(texts[2]).toEqual([
            "conversation · 7 steps",
            "you: Build the reader.",
            "Reading the records.",
            "· Bash",
            "· Read",
            "you: Ask me first.",
            "Twenty kinds of line.",
            "",
            "Four carry what was said.",
            "· Grep",
        ]);
        // Each drawer is its own fold, folded until opened, a line under the banner; the new module's bodies fold
        // until opened, its file open.
        const own = out.drawers.map((each) => each.folds.at(-1)!);
        expect(own.map((each) => [each.kind, each.closed, each.of])).toEqual([
            ["tasks", true, `tasks ${whose(S1)}`],
            ["since", true, `since ${whose(S1)}`],
            ["conversation", true, `conversation ${whose(S1)}`],
        ]);
        // In the conversation, `Transcripts`' view drawn, each exchange before the operator's last words folds under
        // their words, read from its own view as it opens; the agent's words are its own lines, each of its block.
        const talked = out.drawers[2]!;
        expect(talked.folds.map((each) => [each.kind, each.label, each.closed])).toEqual([
            ["earlier", "you: Build the reader.", true],
            ["conversation", "conversation · 7 steps", true],
        ]);
        expect(foldKey(talked.folds[0]!)).toBe(`conversation ${whose(S1)} earlier exchange 0`);
        expect([...talked.loads.values()].map((each) => [each.module, each.view, (each.argument as { step: number }).step])).toEqual([["transcripts", "exchange", 0]]);
        expect(talked.lines.map((each) => [out.text.slice(each.from, each.to), each.block.slice(each.block.lastIndexOf("step")), each.line])).toEqual([
            ["Reading the records.", "step 1", 0],
            ["Twenty kinds of line.", "step 5", 0],
            ["", "step 5", 1],
            ["Four carry what was said.", "step 5", 2],
        ]);
        expect(talked.texts.map((each) => out.text.slice(each.from, each.to))).toEqual(["Reading the records.", "Twenty kinds of line.\n\nFour carry what was said."]);
        expect(talked.toned.map((each) => [out.text.slice(each.from, each.to), each.tone]).slice(0, 2)).toEqual([
            ["you: Build the reader.", "operator"],
            ["· Bash", "call"],
        ]);
        const since = out.drawers[1]!;
        expect(since.folds.map((each) => [each.kind, each.label, each.closed])).toEqual([
            ["body", "Reader", true],
            ["body", "turns", true],
            ["file", "reader.py", false],
            ["since", "since you approved · 1 to review · 1 flagged", true],
        ]);
        expect(foldKey(since.folds[1]!)).toBe(`since ${whose(S1)} body reader.py ["Reader","turns"]`);
        // The drawers under the banner, before the items, the group after them where it is.
        expect(at("tasks 1/3")).toBeLessThan(at("── #51"));
        expect(at("conversation · 7 steps")).toBeLessThan(at("━━ s2"));
        // An agent the host hasn't answered of has no drawers; nor is a drawer with nothing under its summary line shown,
        // which would say only that it's empty.
        expect(laid([QUESTION], [S1], banner, header, EMPTY, NOTHING).drawers).toEqual([]);
        const bare = laid([QUESTION], [S1], banner, header, EMPTY, NOTHING, [], new Map([[whose(S1), UNREAD]]));
        expect(bare.drawers).toEqual([]);
        expect(bare.text).not.toContain("tasks ");
        const empty = laid([QUESTION], [S1], banner, header, EMPTY, NOTHING, [], new Map([[whose(S1), { ...DATA, tasks: [], since: { ...SINCE, files: [] } }]]), undefined, { remote });
        expect(empty.drawers.map((each) => each.kind)).toEqual(["conversation"]);
        expect(empty.text).not.toContain("since you approved");
        // The conversation under the banner, the item after it.
        expect(empty.text.indexOf("· Grep\n\n")).toBeLessThan(empty.text.indexOf("── #51"));
        const without = laid([QUESTION], [S1], banner, header, EMPTY, NOTHING);
        expect(bare.text).toBe(without.text);
    });

    it("opens a remark on the agent's words in the conversation, and on a file's line since you approved, recording the version", () => {
        const twenty = opened(out, at("Twenty"));
        expect(twenty).toMatchObject({ id: "", to: S1, quote: { text: "Twenty kinds of line.", line: 0, start: 0, end: 21 }, text: "" });
        expect(twenty !== undefined && "quote" in twenty ? twenty.quote?.block.endsWith(" step 5") : false).toBe(true);
        expect(twenty !== undefined && "code" in twenty).toBe(false);
        // On the agent's words read as its fold opened, on that step's block; on a passage of two of its lines, both quoted.
        const reading = opened(out, at("Reading the records."));
        expect(reading !== undefined && "quote" in reading ? [reading.quote?.block.endsWith(" step 1"), reading.quote?.lines] : null).toEqual([true, ["Reading the records."]]);
        const passage = quoted(out, at("kinds"), at("Four carry") + 4);
        expect(passage !== undefined && "quote" in passage ? [passage.quote?.text, passage.quote?.line, passage.quote?.lines] : null).toEqual([
            "kinds of line.\n\nFour",
            0,
            ["Twenty kinds of line.", "", "Four carry what was said."],
        ]);
        expect(opened(out, at("        a = 1"))).toEqual({
            id: "",
            to: S1,
            quote: expect.objectContaining({ text: "reader.py:6\n+        a = 1", version: "b1", lines: ["        a = 1"] }),
            text: "",
            code: { worktree: "/w/feat", path: "reader.py", version: "b1", first: 6, lines: ["        a = 1"] },
        });
        const from = at("        a = 1");
        const to = at("        return") + 8;
        const across = quoted(out, from, to);
        expect(across !== undefined && "code" in across ? across.code : null).toEqual({ worktree: "/w/feat", path: "reader.py", version: "b1", first: 6, lines: ["        a = 1", "        b = 2", "        return a + b"] });
        for (const line of ["tasks 1/3", "✓ Write", "· Grep", "conversation ·", "since you approved", "you: Build", "line.\n\n"]) {
            expect(opened(out, at(line) + (line === "line.\n\n" ? 6 : 0))).toBeUndefined();
        }
        expect(opened(out, at("━━ s1"))).toEqual({ id: "", to: S1, text: "" });
    });

    it("places each remark under its line in the conversation, before the operator's last words or since, and says whom it goes to", () => {
        const onCode = opened(out, at("        a = 1"));
        const quote = onCode !== undefined && "quote" in onCode && onCode.quote != null ? onCode.quote : keptQuote("", 0, 0);
        const remarks: Remark[] = [
            { id: "twenty", to: S1, quote: keptQuote("Twenty kinds of line.", 0, 21), text: "Which twenty?", step: 5 },
            { id: "good", to: S1, quote: keptQuote("Reading the records.", 0, 20), text: "Good.", step: 1 },
            { id: "name", to: S1, quote, text: "Name it.", code: { worktree: "/w/feat", path: "reader.py", version: "b1", first: 6, lines: ["        a = 1"] } },
        ];
        const draft: Draft = { ...EMPTY, remarks };
        const wrote = laid([QUESTION, NOTE], [S1], banner, header, draft, NOTHING, [], drawers, undefined, { remote });
        const text = wrote.text;
        expect(text.split("Which twenty?").length).toBe(2);
        expect(text).toContain("Twenty kinds of line.\nWhich twenty?\n\nFour carry what was said.\n· Grep");
        expect(text).toContain("Reading the records.\nGood.\n");
        expect(text.indexOf("Good.")).toBeGreaterThan(text.indexOf("conversation · 7 steps"));
        // Opened on a line of the earlier exchange, it's there, under that line, and the header says it's in that exchange.
        expect(blockAt(wrote, text.indexOf("Good."))?.comment).toBe("good");
        expect(heading(wrote, text.indexOf("Good."), true, written(draft), { group: () => "g", item: () => "i", party: () => "p" }).map((each) => each.kind)).toEqual([
            "to",
            "group",
            "conversation",
            "earlier",
        ]);
        expect(text).toContain("        a = 1\nName it.\n");
        const naming: Naming = { group: () => "g", item: (each) => `#${each.item.number}`, party: (party) => `agent ${party.session}/${party.agent}` };
        expect(heading(wrote, text.indexOf("Name it."), true, written(draft), naming).map((each) => `${each.kind}: ${each.text}`)).toEqual([
            "to: to agent s1/a1",
            "group: g",
            "since: since",
            "file: reader.py",
            "body: Reader",
            "body: turns",
        ]);
        expect(blockAt(wrote, text.indexOf("Name it."))?.comment).toBe("name");
        expect(written(draft)[2]).toBe(remarks[2]);
        expect(withWritten(EMPTY, remarks).remarks).toEqual(remarks);
    });

    it("keeps a remark on a step under a fold not read yet under the drawer's line until it's read, then under its line", () => {
        const on = opened(out, at("Reading the records.")) as Remark;
        const draft: Draft = { ...EMPTY, remarks: [{ ...on, id: "read", text: "Which records?" }] };
        const unread = laid([QUESTION, NOTE], [S1], banner, header, draft, NOTHING, [], drawers, undefined, { remote: DRAWER_ONLY });
        expect(unread.text).toContain("conversation · 7 steps\nWhich records?\nyou: Build the reader.\nreading…\n");
        const read = laid([QUESTION, NOTE], [S1], banner, header, draft, NOTHING, [], drawers, undefined, { remote, previous: unread });
        expect(read.text).toContain("you: Build the reader.\nReading the records.\nWhich records?\n· Bash");
        expect(read.seated.get("read")?.outdated).toBe(false);
        // One drafted before quotes named their block waits there unconverted until its step is laid out.
        const old: Remark = { id: "old", to: S1, quote: keptQuote("Reading the records.", 0, 20), text: "Which records?", step: 1 };
        const waiting = laid([QUESTION, NOTE], [S1], banner, header, { ...EMPTY, remarks: [old] }, NOTHING, [], drawers, undefined, { remote: DRAWER_ONLY });
        expect(waiting.text).toContain("conversation · 7 steps\nWhich records?\n");
        expect(waiting.converted).toBeNull();
        const placed = laid([QUESTION, NOTE], [S1], banner, header, { ...EMPTY, remarks: [old] }, NOTHING, [], drawers, undefined, { remote });
        expect(placed.converted?.map((each) => ("quote" in each ? [each.quote?.block.endsWith(" step 1"), each.quote?.line] : "letter"))).toEqual([[true, 0]]);
    });

    it("keeps a remark drafted before quotes named their block on a step of no words of the agent's as a message to it", () => {
        const old: Remark = { id: "", to: S1, quote: keptQuote("Ask me first.", 0, 13), text: "And?", step: 4 };
        const wrote = laid([QUESTION, NOTE], [S1], banner, header, { ...EMPTY, remarks: [old] }, NOTHING, [], drawers, undefined, { remote });
        expect(wrote.converted).toEqual([{ id: "kept remark 0", to: S1, text: "> Ask me first.\nAnd?" }]);
    });

    it("keeps each remark under its line as the agent writes above it, in its own file or one before it, its lines untouched by the changes (#311)", () => {
        const TEST = "from reader import Reader\n\n\ndef test_turns():\n    assert Reader().turns() == 3\n";
        const reader = SINCE.files![0]!;
        const test = { path: "test_reader.py", file: { path: "test_reader.py", before: null, after: { kind: "text" as const, text: TEST }, reading: null }, version: "t1", flags: [], since: null };
        const two: Since = { ...SINCE, files: [reader, test] };
        const laidWith = (since: Since, draft: Draft, previous: Laid | null) =>
            laid([QUESTION, NOTE], [S1], banner, header, draft, NOTHING, [], new Map([[whose(S1), { ...DATA, since }]]), undefined, { previous, remote });
        const first = laidWith(two, EMPTY, null);
        const on = (text: string, id: string, said: string): Remark => ({ ...(opened(first, first.text.indexOf(text)) as Remark), id, text: said });
        const draft: Draft = { ...EMPTY, remarks: [on("    assert Reader()", "test", "Why 3?"), on("        return a + b", "sum", "Why a sum?")] };
        const before = laidWith(two, draft, first);
        expect(before.text).toContain("    assert Reader().turns() == 3\nWhy 3?\n");
        expect(before.text).toContain("        b = 2\n        return a + b\nWhy a sum?\n");
        // The agent writes: a method above the one remarked on, ending as it ends, and a file before both.
        const GROWN = '"""Reader."""\n\n\nclass Reader:\n    def kinds(self):\n        return a + b\n\n    def turns(self):\n        a = 1\n        b = 2\n        return a + b\n';
        const clock = { path: "clock.py", file: { path: "clock.py", before: null, after: { kind: "text" as const, text: "NOW = 0\n" }, reading: null }, version: "c1", flags: [], since: null };
        const grown: Since = { ...two, files: [clock, { ...reader, file: { ...reader.file!, after: { kind: "text", text: GROWN } }, version: "b2" }, test] };
        const after = laidWith(grown, draft, before);
        expect(after.text).toContain("    assert Reader().turns() == 3\nWhy 3?\n");
        expect(after.text).toContain("    def kinds(self):\n        return a + b\n\n");
        expect(after.text).toContain("        b = 2\n        return a + b\nWhy a sum?\n");
        expect([after.seated.get("test")?.outdated, after.seated.get("sum")?.outdated]).toEqual([false, false]);
        // Whose each line is, run by run, as the editor keeps it, read from the lines as they're written.
        expect(after.runs).toEqual(runsOf(after.text, after.owners));
        expect(after.owners.length).toBe(after.text.split("\n").length - 1);
        // The editor's changes make the new layout and leave each remark's line as it was.
        const doc = Text.of(before.text.split("\n"));
        const made = reconcile(doc, before.owners, after.text, after.owners, (owner) => (owner.startsWith("written ") ? 1e6 : 1));
        const changes = ChangeSet.of(made.changes, doc.length);
        expect(changes.apply(doc).toString()).toBe(after.text);
        for (const said of ["Why 3?", "Why a sum?"]) {
            const from = before.text.indexOf(said);
            const to = from + said.length;
            let touched = false;
            changes.iterChangedRanges((fromA, toA) => {
                touched ||= (fromA < to && toA > from) || (fromA === toA && fromA > from && fromA < to);
            });
            expect(touched).toBe(false);
        }
    });

    it("keeps a remark on a file the drawer no longer shows whole under the file's line as the operator last saw it, outdated", () => {
        const remark = { ...(opened(out, at("        b = 2")) as Remark), id: "b", text: "Rename b." };
        const settled: Since = { ...SINCE, files: [{ ...SINCE.files![0]!, file: null, flags: [] }] };
        const wrote = laid([QUESTION, NOTE], [S1], banner, header, { ...EMPTY, remarks: [remark] }, NOTHING, [], new Map([[whose(S1), { ...DATA, since: settled }]]));
        const line = wrote.drawers.find((each) => each.kind === "since")!.reviewed[0]!;
        expect(wrote.text.slice(line.to + 1)).toMatch(/^Rename b\.\n/);
        expect(wrote.seated.get("b")?.outdated).toBe(true);
    });

    it("anchors a remark drafted before quotes named their block, by the lines its code names, or keeps it as a message where they're gone", () => {
        const kept: Remark = { id: "", to: S1, quote: keptQuote("reader.py:7\n+        b = 2", 999, 1010), text: "Rename b.", code: { worktree: "/w/feat", path: "reader.py", version: "b0", first: 7, lines: ["        b = 2"] } };
        const gone: Remark = { id: "", to: S1, quote: keptQuote("old.py:1\n+x", 0, 3), text: "And this?", code: { worktree: "/w/feat", path: "old.py", version: "o0", first: 1, lines: ["x"] } };
        const wrote = laid([QUESTION, NOTE], [S1], banner, header, { ...EMPTY, remarks: [kept, gone] }, NOTHING, [], drawers);
        expect(wrote.text).toContain("        b = 2\nRename b.\n");
        const converted = wrote.converted!;
        expect(converted.map((each) => ("quote" in each ? (each.quote?.block.endsWith(" file reader.py") ?? false) : "letter"))).toEqual([true, "letter"]);
        expect(converted[1]).toEqual({ id: "kept remark 1", to: S1, text: "> old.py:1\n> +x\nAnd this?" });
        expect(converted.every((each) => each.id !== "")).toBe(true);
        expect(laid([QUESTION, NOTE], [S1], banner, header, withWritten(EMPTY, converted), NOTHING, [], drawers).converted).toBeNull();
    });

    it("draws what measures on a banner beside its words, never writing it in the text, where it goes among its parts", () => {
        const running = new Map([[whose(S1), { launch: "l1", holding: false }]]);
        const withParts = (head: Head, parked: boolean, parts: string) => `━━ ${"item" in head ? "?" : head.conversation.session}${parts === "" ? "" : ` · ${parts}`} ━━`;
        const out = laid([], [S1], withParts, header, EMPTY, NOTHING, [], drawers, undefined, { running });
        const [group] = out.groups;
        expect(out.text.slice(group!.banner.from, group!.banner.to)).toBe("━━ s1 · ▶ Writing the models ·  ━━");
        expect(out.drawn.map((each) => [out.text.slice(group!.banner.from, each.at), each.span.text, each.span.gauge])).toEqual([
            ["━━ s1 · ▶ Writing the models · ", "○ 112k/1M", { used: 112_000, of: 1_000_000 }],
        ]);
    });

    it("marks a file of since you approved reviewed in the draft, folding it, and the drawer whole as each of its files", () => {
        const reach = reachOf(out, at("        a = 1"), verb("done"), { called: (each) => each.session });
        const marked = marking(EMPTY, reach.on === null ? [] : reach.acts, "done");
        expect(marked.marks?.map((each) => [each.action, each.verb, each.block.endsWith(" file reader.py"), each.version, each.says])).toEqual([
            ["policy-review-since", "done", true, "b1", "mark it reviewed"],
        ]);
        // Laid out with the mark, its file folds under its header, which says what Ctrl+Enter does with it.
        const folded = laid([QUESTION, NOTE], [S1], banner, header, marked, NOTHING, [], drawers, undefined, { remote });
        const file = folded.drawers.find((each) => each.kind === "since")?.folds.find((each) => each.kind === "file");
        expect(file?.closed).toBe(true);
        // On the drawer's line, each file its own mark, the same as on the file: every one marked, it takes them off.
        const whole = reachOf(folded, folded.text.indexOf("since you approved ·"), verb("done"), { called: (each) => each.session });
        const blocks = (each: typeof reach) => (each.on === null ? [] : each.acts.map((act) => (act.kind === "mark" ? act.block : "")));
        expect(blocks(whole)).toEqual(blocks(reach));
        expect(marking(marked, whole.on === null ? [] : whole.acts, "done").marks).toEqual([]);
        // A file holding a remark of the operator's stays open, marked, until it's sent.
        const remark: Remark = { id: "r", to: S1, quote: { text: "a = 1", block: marked.marks![0]!.block, version: "b1", line: 5, lines: ["        a = 1"], start: 0, end: 13 }, text: "Name it." };
        const writing = laid([QUESTION, NOTE], [S1], banner, header, { ...marked, remarks: [remark] }, NOTHING, [], drawers, undefined, { remote });
        expect(writing.drawers.find((each) => each.kind === "since")?.folds.find((each) => each.kind === "file")?.closed).toBe(false);
    });

    it("marks an agent's own items and drawers done from its banner, its subagents' left as they are", () => {
        const reach = reachOf(out, at("━━ s1"), verb("done"), { called: (each) => each.session });
        expect(reach.on === null ? [] : reach.acts.map((each) => (each.kind === "item" ? `item ${each.number} ${each.list}` : each.kind === "mark" ? `mark ${each.offer.action}` : each.kind))).toEqual([
            "item 51 done",
            "mark policy-review-since",
        ]);
    });

    it("says what each verb reaches in a drawer: a file of since you approved, the drawer on its line, the agent elsewhere", () => {
        expect(reaches(out, at("        a = 1"), "done")).toBe("reader.py: mark it reviewed");
        expect(reaches(out, at("reader.py · created"), "done")).toBe("reader.py: mark it reviewed");
        expect(reaches(out, at("reader.py · created"), "decline")).toBeNull();
        expect(reaches(out, at("since you approved ·"), "done")).toBe("since you approved · 1 to review · 1 flagged: mark every file reviewed");
        // A task list and a conversation offer nothing of their own: done reaches the agent, its items and drawers.
        expect(reaches(out, at("✓ Write"), "done")).toBe("s1: mark its items and drawers done");
        expect(reaches(out, at("Twenty"), "done")).toBe("s1: mark its items and drawers done");
    });

    it("says in each summary line what the drawer holds: in since you approved, the files changed and those standing as reviewed", () => {
        expect(rowLabel("tasks", { ...DATA, tasks: [] })).toBeNull();
        expect(rowLabel("tasks", DATA)).toEqual({ text: "tasks 1/3", waiting: false });
        // A drawer its module answers says its own: none the page lays out.
        expect(rowLabel("conversation", DATA)).toBeNull();
        expect(rowLabel("since", DATA)).toEqual({ text: "since you approved · 1 to review · 1 flagged", waiting: true });
        expect(sinceSummary(null)).toBe("since you approved · not read yet");
        expect(sinceSummary(SINCE)).toBe("since you approved on feat · 1 to review · 1 flagged");
        expect(sinceSummary({ ...SINCE, files: [] })).toBe("since you approved on feat · nothing");
        const kept = { path: "a.py", version: "a1", flags: [], reviewed: "2026-10-17T12:00:00Z" };
        expect(sinceSummary({ ...SINCE, files: [kept, ...SINCE.files] })).toBe("since you approved on feat · 1 to review · 1 flagged · 1 reviewed");
        const unflagged = SINCE.files.map((each) => ({ ...each, flags: [] }));
        expect(sinceSummary({ ...SINCE, files: [kept, ...unflagged] })).toBe("since you approved on feat · 1 to review · 1 reviewed");
        expect(sinceSummary({ ...SINCE, branch: null, files: [kept] })).toBe("since you approved · 1 reviewed");
        const unread = (path: string, role: string) => ({
            path,
            file: { path, before: null, after: { kind: "text" as const, text: "x = 1\n" }, reading: { role, asks: [], findings: [] } },
            version: `${path}1`,
            flags: [],
        });
        const tests = [unread("test_reader.py", "test"), unread("reader.test.ts", "test"), unread("fixture.json", "data")];
        expect(sinceSummary({ ...SINCE, files: [...SINCE.files, ...tests, kept] })).toBe(
            "since you approved on feat · 1 to review · 1 flagged · 2 tests · 1 data file · 1 reviewed",
        );
        expect(sinceSummary({ ...SINCE, files: tests.slice(0, 1) })).toBe("since you approved on feat · 1 test");
    });

    it("folds each file reviewed under one line at the drawer's end, one with flagged writes waiting staying a line in its place, which Space d takes", () => {
        const kept = { path: "a.py", version: "a1b2c3d4e5f6", flags: [], reviewed: "2026-10-17T12:00:00Z" };
        const also = { path: "b.py", version: null, flags: [], reviewed: "2026-10-17T12:00:00Z" };
        const seen = { path: "z.py", version: "f6e5", flags: [71], since: 12 };
        const shown: Since = { ...SINCE, files: [kept, ...SINCE.files, seen, also] };
        const laidOut = laid([QUESTION], [S1], banner, header, EMPTY, NOTHING, [], new Map([[whose(S1), { ...DATA, since: shown }]]));
        const [, since] = laidOut.drawers;
        const text = laidOut.text.slice(since!.header.from, since!.folds.at(-1)!.to).split("\n");
        expect(text.slice(0, 2)).toEqual(["since you approved · 1 to review · 2 flagged · 2 reviewed", "reader.py · created · 8 lines · new file"]);
        expect(text.slice(-4)).toEqual(["z.py · as you saw it in @12 · flagged @71", "2 reviewed", "a.py · reviewed at a1b2c3d", "b.py · deleted · reviewed"]);
        const on = (line: string) => laidOut.text.indexOf(line);
        expect(since!.reviewed.map((each) => each.file)).toEqual([seen, kept, also]);
        const line = on("\n2 reviewed\n") + 1;
        expect(since!.settled).toEqual({ from: line, to: line + "2 reviewed".length });
        expect(sinceFileAt(since!, on("a.py · reviewed"))).toBe(kept);
        expect(sinceFileAt(since!, on("        a = 1"))).toBe(shown.files[1]);
        expect(sinceFileAt(since!, on("z.py ·"))).toBe(seen);
        // A settled file is reviewed already: done on it reaches the drawer, every file still to review or flagged; one
        // with flagged writes waiting is marked reviewed on its own line, which approves them.
        expect(reaches(laidOut, on("a.py · reviewed"), "done")).toBe("since you approved · 1 to review · 2 flagged · 2 reviewed: mark every file reviewed");
        expect(reaches(laidOut, on("z.py ·"), "done")).toBe("z.py · as you saw it in @12 · flagged @71: mark it reviewed");
        // The header over the review names the file a reviewed line is, as it does one whose lines the cursor is on.
        const naming: Naming = { group: () => "g", item: (each) => `#${each.item.number}`, party: () => "" };
        expect(heading(laidOut, on("a.py · reviewed"), false, [], naming).map((each) => `${each.kind}: ${each.text}`)).toEqual([
            "group: g",
            "since: since",
            "file: a.py",
            "lines: 2 reviewed",
        ]);
        // The settled files fold under their line, folded; the reader's folds are as they were.
        expect(since!.folds.map((each) => [each.kind, each.label, each.closed])).toEqual([
            ["body", "Reader", true],
            ["body", "turns", true],
            ["file", "reader.py", false],
            ["lines", "2 reviewed", true],
            ["since", "since you approved · 1 to review · 2 flagged · 2 reviewed", true],
        ]);
        // None settled, no line for them.
        const none = laid([QUESTION], [S1], banner, header, EMPTY, NOTHING, [], new Map([[whose(S1), { ...DATA, since: { ...SINCE, files: [...SINCE.files, seen] } }]]));
        expect(none.drawers[1]?.settled).toBeNull();
        expect(none.text).not.toContain("reviewed\n");
    });

    it("says where each file's header is, where ]f and [f go and a key held down stops: a test folded whole among them, never a reviewed file's line", () => {
        const kept = { path: "a.py", version: "a1b2c3d4e5f6", flags: [], reviewed: "2026-10-17T12:00:00Z" };
        const test = {
            path: "test_reader.py",
            file: { path: "test_reader.py", before: null, after: { kind: "text" as const, text: "x = 1\n" }, reading: { role: "test", asks: [], findings: [] } },
            version: "t1",
            flags: [],
        };
        const shown: Since = { ...SINCE, files: [kept, ...SINCE.files, test] };
        const laidOut = laid([QUESTION], [S1], banner, header, EMPTY, NOTHING, [], new Map([[whose(S1), { ...DATA, since: shown }]]));
        const on = (line: string) => laidOut.text.indexOf(line);
        expect(fileHeads(laidOut)).toEqual([on("reader.py · created"), on("test_reader.py · created")]);
        expect(fileHeads(laid([QUESTION], [S1], banner, header, EMPTY, NOTHING, [], new Map([[whose(S1), { ...DATA, since: { ...SINCE, files: [kept] } }]])))).toEqual([]);
    });
});
