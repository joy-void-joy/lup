// A thread's own buffer (`docs/dashboard.md`, *The panes*): its banner and whole conversation, a check, the operator's
// words, a message between agents folded to its header, what the verbs do on its banner, and where what's written there
// goes.
import { hosted } from "./fixtures/kinds";
import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import { implied, marking, reachOf, threadsRead } from "./grammar";
import { holdingOn, toSend, waitingOn } from "./App";
import { partSaid } from "./brief";
import { itemStanding, outlineOf } from "./outline";
import {
    EMPTY,
    checkAt,
    countToRead,
    groupAt,
    headerClasses,
    heading,
    laid,
    opened,
    scopeAt,
    threadPlace,
    toAnswer,
    UNSEEN,
    type Around,
    type Conversation,
    type Draft,
    type Item,
    type Laid,
    type ThreadRead,
    type ThreadShown,
    type Threading,
} from "./review";
import { agentNamed, threadBanner } from "./Review";
import { sightsOf } from "./seeing";
import { adopted } from "./looks";

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
const BETWEEN = note(67, WORKER, "Count each kind of line.", from("s1", "a3"));
const LATE = note(70, WORKER, "Built.");

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

const READER = thread(302, "reader", {
    state: "waiting on the operator",
    section: "waiting on you",
    asks: [
        { node: 51, what: "a question", came: AT, holds: true },
        { node: 311, what: "a check", came: AT, holds: false },
    ],
    members: 4,
    earlier: 2,
});
const VOICE = thread(307, "voice", {
    state: "done to confirm",
    section: "waiting on you",
    since: LATER,
    status: { kind: "ledger:done", target: 307, source: null, repository: REPOSITORY, by: LEAD, at: LATER, to_try: "Read the voice section." } as NonNullable<ThreadRead["status"]>,
    members: 1,
});
const AUTH = thread(303, "auth", { section: "new", new: [70], members: 1 });
const CACHE = thread(305, "cache", { state: "settled", section: "every thread" });
const DOCS = thread(304, "docs", { section: "every thread", holder: null, answering: LEAD } as Partial<ThreadRead>);
const DOCS_NOBODY = { ...DOCS, thread: { ...DOCS.thread, holder: null } } as ThreadRead;
const NAMES = (() => {
    const made = thread(306, "names", {
        state: "parked",
        section: "every thread",
        status: { kind: "ledger:parked", target: 306, source: null, repository: REPOSITORY, by: WORKER, at: AT, until: [{ trigger: "branch landed", branch: "reader" }], why: "named once the reader lands" } as NonNullable<ThreadRead["status"]>,
    });
    return { ...made, thread: { ...made.thread, parent: 304 } } as ThreadRead;
})();

const CHECK = { check: { kind: "ledger:check", number: 311, name: null, text: "Search a long record.", repository: REPOSITORY, by: WORKER, at: AT }, answer: null } as unknown as ThreadShown["checks"][number];

function shown(read: ThreadRead, entries: ThreadShown["entries"], items: Item[], extra: Partial<ThreadShown> = {}): ThreadShown {
    return { kind: "inbox-thread-shown", read, entries, left: 0, items, checks: [], references: [], under: [], on: [], paths: [], ...extra } as ThreadShown;
}

const READER_SHOWN = shown(
    READER,
    [
        { spot: { node: 51 }, came: AT, member: true },
        { spot: { node: 311 }, came: AT, member: true },
    ] as ThreadShown["entries"],
    [QUESTION],
    { left: 2, checks: [CHECK] },
);
const READER_WHOLE = shown(
    READER,
    [
        { spot: { node: 47 }, came: AT, member: true, earlier: true },
        { spot: { node: 48, part: 1 }, under: { node: 47 }, came: AT, member: false, earlier: true, said: "Keep the two apart." },
        { spot: { node: 67 }, came: AT, member: true, earlier: true },
        { spot: { node: 51 }, came: AT, member: true },
        { spot: { node: 311 }, came: AT, member: true },
    ] as ThreadShown["entries"],
    [hosted({ ...NOTE, state: { state: "done", at: AT } }), hosted({ ...BETWEEN, state: { state: "done", at: AT } }), QUESTION],
    { checks: [CHECK] },
);
const AUTH_SHOWN = shown(AUTH, [{ spot: { node: 70 }, came: AT, member: true, new: true }] as ThreadShown["entries"], [LATE]);
const VOICE_SHOWN = shown(VOICE, [{ spot: { node: 50, part: 3 }, came: AT, member: true, unanswered: true, said: "Put it on its branch.", to: LEAD }] as ThreadShown["entries"], []);

const NOTHING: Around = { contexts: new Map(), files: new Map(), answers: [], commented: [] };
const header = (shownItem: Item) => `── @${shownItem.number} ──`;
const banner = () => "━━ agent ━━";
const called = (party: Conversation) => (party.agent === null || party.agent === undefined ? party.session : `${party.session}/${party.agent}`);

function threading(more: [number, ThreadShown][] = []): Threading {
    return {
        read: { kind: "inbox-threads-read", threads: [READER, VOICE, AUTH, DOCS_NOBODY, NAMES, CACHE], paths: [], working: [{ conversation: WORKER, thread: 302 }] },
        shown: new Map([
            [302, READER_SHOWN],
            [303, AUTH_SHOWN],
            [307, VOICE_SHOWN],
        ]),
        whole: new Map<number, ThreadShown>([[302, READER_WHOLE], [303, AUTH_SHOWN], [307, VOICE_SHOWN], ...more]),
        landing: new Map(),
        banner: (read, landing) => threadBanner(read, landing, called),
    };
}

/** Thread `number`'s own buffer, its conversation read whole. */
function lay(number: number, draft: Draft = EMPTY, threads: Threading = threading()): Laid {
    return laid([QUESTION, LATE], [LEAD], banner, header, draft, NOTHING, [], new Map(), called, { threads, showing: { kind: "thread", number } });
}

function lines(out: Laid): string[] {
    return out.text.split("\n");
}

/** Return what `name`, a verb's, reaches at `at` in `out`, `draft` as it stands. */
function reaching(out: Laid, at: number, name: string, draft: Draft = EMPTY) {
    const verb = adopted().verbs.find((each) => each.name === name);
    expect(verb).toBeDefined();
    return verb === undefined ? null : reachOf(out, at, verb, { called, draft });
}

/** What the verb `name` reaches on thread `number`'s banner, in its own buffer. */
function onBanner(number: number, name: string, draft: Draft = EMPTY, threads: Threading = threading()) {
    const out = lay(number, draft, threads);
    return reaching(out, out.groups[0]?.banner.from ?? 0, name, draft);
}

describe("what asks the operator, and what's only to read, in the overview and the top bar", () => {
    const reading = (draft: Draft = EMPTY) => ({ draft, seeing: UNSEEN, states: new Map(), called });

    it("says so of each item, by the host's asks, a seen one saying neither", () => {
        const out = laid([QUESTION, LATE], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called);
        const rows = outlineOf(out, reading());
        expect(rows.find((each) => each.text.startsWith("@51"))?.marks).toEqual(["waiting"]);
        const seen = { ...UNSEEN, groups: new Map(), threaded: new Set<number>() };
        const region = out.regions.find((each) => each.item.number === 70);
        expect(region === undefined ? null : itemStanding(region, EMPTY, { ...UNSEEN, threaded: new Set([70]) }).marks).toEqual(["news"]);
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
    const read = threading().read.threads;

    it("reads a thread's news and what asks them in its own buffer, each moving its thread's mark", () => {
        const news = sightsOf(lay(303), UNSEEN, EMPTY, new Map(), read).find((each) => each.id === "item 70");
        expect(news?.moves).toEqual({ repository: REPOSITORY, module: "core", key: { node: 303 }, up_to: "70", forward: true, seen: true });
        expect(news?.asks).toBe(false);
        const asks = sightsOf(lay(302), UNSEEN, EMPTY, new Map(), read).find((each) => each.id === "item 51");
        expect(asks?.asks).toBe(true);
        expect(asks?.moves?.key).toEqual({ node: 302 });
    });

    it("leaves what the draft marks to the draft, and holds the mark back from what holds their words", () => {
        expect(sightsOf(lay(303), UNSEEN, { ...EMPTY, done: [70] }, new Map(), read).some((each) => each.id === "item 70")).toBe(false);
        const written = { ...EMPTY, comments: [{ id: "c1", item: 70, quote: { text: "", block: "", version: "", line: 0, lines: [], start: 0, end: 0 }, text: "Why?" }] } as unknown as Draft;
        expect(sightsOf(lay(303), UNSEEN, written, new Map(), read).find((each) => each.id === "item 70")?.held).toBe(true);
    });

    it("holds a thread's mark at what's new in it that's laid out nowhere", () => {
        const late = { ...AUTH, new: [70, 71] } as ThreadRead;
        const [first, second] = sightsOf(lay(303), UNSEEN, EMPTY, new Map(), [late]);
        expect(first?.id).toBe("item 70");
        expect(second?.id).toBe("item 71");
        expect(second?.held).toBe(true);
    });

    it("reads an agent's group by its own mark, where no thread's buffer is on screen", () => {
        const out = laid([LATE], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called);
        const [sight] = sightsOf(out, UNSEEN, EMPTY, new Map(), null);
        expect(sight?.moves).toEqual({ repository: REPOSITORY, module: "core", key: { runtime: "claude", session: "s1", agent: "a1" }, up_to: "70", forward: true, seen: true });
        // Seen since it came, it's no longer new, and nothing's left to read of it.
        expect(sightsOf(out, { ...UNSEEN, groups: new Map([[JSON.stringify([REPOSITORY, "claude", "s1", "a1"]), 70]]) }, EMPTY, new Map(), null)).toEqual([]);
    });
});

describe("a thread's own buffer", () => {
    it("says what its banner says of each: who holds it, where it stands, and how much of it waits on the operator or is new", () => {
        const said = (read: ThreadRead, landing: number = 0) => threadBanner(read, landing, called);
        expect(said(READER)).toBe("━━ @reader · The reader · s1/a1 holds · working · 2 waiting ━━");
        expect(said(VOICE)).toBe("━━ @voice · The voice · s1/a1 holds · done, to confirm ━━");
        expect(said(AUTH)).toBe("━━ @auth · The auth · s1/a1 holds · working · 1 new ━━");
        expect(said(DOCS_NOBODY)).toBe("━━ @docs · The docs · nobody holds it, s1 answers · working ━━");
        expect(said(NAMES)).toBe("━━ @names · The names · s1/a1 holds · parked until reader lands ━━");
        expect(said(CACHE)).toBe("━━ @cache · The cache · s1/a1 holds · settled ━━");
        // A landing waiting on files there is one more that waits.
        expect(said(AUTH, 2)).toBe("━━ @auth · The auth · s1/a1 holds · working · 1 waiting, 1 new ━━");
    });

    it("says what it's parked until", () => {
        expect(lines(lay(306))[1]).toBe("parked: named once the reader lands");
    });

    it("says working of nothing nobody running answers for, whatever waits on the operator in it", () => {
        const made = thread(320, "left", { holder: from("s7"), answering: null, state: "nobody running" } as Partial<ThreadRead>);
        const left = { ...made, thread: { ...made.thread, holder: from("s7") } } as ThreadRead;
        expect(threadBanner(left, 0, called)).toBe("━━ @left · The left · s7 held it · nobody running ━━");
        const asking = { ...left, state: "waiting on the operator", asks: [{ node: 51, what: "a question", came: AT, holds: true }] } as ThreadRead;
        expect(threadBanner(asking, 0, called)).toBe("━━ @left · The left · s7 held it · nobody running · 1 waiting ━━");
    });

    it("lays its whole conversation out in the order it came, under its banner, open: an item, the operator's words on it inside it, a message between agents folded to its header", () => {
        const out = lay(302);
        const read = lines(out);
        expect(read.slice(0, 9)).toEqual([
            "━━ @reader · The reader · s1/a1 holds · working · 2 waiting ━━",
            "── @47 ──",
            "Two readers, one each.",
            "you · @48.1",
            "  Keep the two apart.",
            "",
            "── @67 ──",
            "Count each kind of line.",
            "",
        ]);
        expect(read.slice(9, 12)).toEqual(["── @51 ──", "Which parser?", "1. pydantic"]);
        expect(out.groups.map((each) => [each.place, each.fold?.closed])).toEqual([[threadPlace(302), false]]);
        expect(out.regions.find((each) => each.item.number === 67)?.folds.find((each) => each.kind === "item")?.closed).toBe(true);
    });

    it("says it's being read until the host has answered", () => {
        const out = lay(302, EMPTY, { ...threading(), whole: new Map() });
        expect(lines(out)[1]).toBe("reading…");
        expect(out.groups[0]?.fold?.unread).toBe(true);
    });

    it("lays a check where it came, what's to try waiting on the operator, Space d ticking it, a comment under it their answer in words", () => {
        const out = lay(302);
        const at = out.text.indexOf("◇ check @311: Search a long record.");
        expect(at).toBeGreaterThan(0);
        expect(checkAt(out, at)?.check.check.number).toBe(311);
        expect(reaching(out, at, "done")).toMatchObject({ says: "tick it: you tried it" });
        expect(opened(out, at)).toEqual({ id: "", item: 311, quote: null, text: "" });
        const answering = lay(302, { ...EMPTY, comments: [{ id: "c1", item: 311, quote: null, text: "Found it in a second." }] });
        expect(lines(answering)).toContain("Found it in a second.");
    });

    it("settles one done with Space d on its banner and declines it with Space x, as marks sent with the reply", () => {
        expect(onBanner(307, "done")).toMatchObject({ says: "settle it: it works", acts: [{ kind: "mark", offer: { action: "inbox-settle-thread", argument: { number: 307 } } }] });
        expect(onBanner(307, "decline")).toMatchObject({ acts: [{ kind: "mark", offer: { action: "inbox-decline-thread" } }] });
        expect(onBanner(307, "comment")).toMatchObject({ says: "write on it, to s1/a1" });
    });

    it("marks a thread's news read with Space d on its banner where there's some, then settles it, never where something waits on the operator", () => {
        // The reader asks a question and a check, and has no news: it isn't settled, nor declined, and says why.
        expect(onBanner(302, "done")).toMatchObject({ says: "not settled while 2 wait on you", acts: [] });
        expect(onBanner(302, "decline")).toMatchObject({ says: "not declined while 2 wait on you", acts: [] });
        // Each answered in the draft, the question marked done and the check ticked, it settles.
        const answered: Draft = { ...EMPTY, done: [51], marks: [{ id: "c", action: "inbox-check-answer", argument: { number: 311 }, verb: "done", says: "tried", block: "check 311", version: null }] };
        expect(onBanner(302, "done", answered)).toMatchObject({ says: "settle it", acts: [{ kind: "mark", offer: { action: "inbox-settle-thread", argument: { number: 302 } } }] });
        // The survey has news: Space d reads it, up to the newest, its news item with it; marked so, Space d settles it.
        const fresh = onBanner(303, "done");
        expect(fresh).toMatchObject({
            says: "mark its news read, each item with it",
            acts: [{ kind: "mark", offer: { action: "review-mark", argument: { key: { node: 303 }, up_to: "70" } } }, { kind: "item", number: 70, list: "done" }],
        });
        const read = fresh === null || fresh.on === null ? EMPTY : marking(EMPTY, fresh.acts, "done");
        expect(onBanner(303, "done", read)).toMatchObject({ says: "settle it", acts: [{ kind: "mark", offer: { action: "inbox-settle-thread", argument: { number: 303 } } }] });
        // Decline on it whenever, nothing waiting; settled, it's declined no more, the one taking the other's place.
        const declining = onBanner(303, "decline");
        expect(declining).toMatchObject({ says: "decline it: nothing more will be done", acts: [{ kind: "mark", offer: { action: "inbox-decline-thread" } }] });
        const settling = onBanner(303, "done", read);
        const settled = settling === null || settling.on === null ? read : marking(read, settling.acts, "done");
        const instead = declining === null || declining.on === null ? settled : marking(settled, declining.acts, "decline");
        expect((instead.marks ?? []).filter((each) => each.action.startsWith("inbox-")).map((each) => each.action)).toEqual(["inbox-decline-thread"]);
        // A thread settled already takes neither.
        expect(onBanner(305, "done")?.on).toBeNull();
    });

    it("settles a working thread whose holder has ended, its news none", () => {
        expect(onBanner(304, "done")).toMatchObject({ on: "@docs", says: "settle it", acts: [{ kind: "mark", offer: { action: "inbox-settle-thread", argument: { number: 304 } } }] });
    });

    it("keeps a thread's banner to one row, a long title cut at a word", () => {
        const title = "Containment's open holes in the room's walls, kept off public GitHub: CI through a push, pasta, the cache's level";
        const long = { ...DOCS, thread: { ...DOCS.thread, title } } as ThreadRead;
        expect(threadBanner(long, 0, called)).toBe("━━ @docs · Containment's open holes in the room's walls, kept off… · s1/a1 held it, s1 answers · working ━━");
    });

    it("leaves nothing on a thread's banner that no longer waits: a question answered is the thread's history", () => {
        const answered = hosted({ ...QUESTION, state: { state: "answered", at: AT, answer: 60 } });
        const read = { ...READER, state: "working", section: "every thread", asks: [] } as ThreadRead;
        const conversation = shown(read, READER_WHOLE.entries.filter((each) => each.spot.node !== 311), [NOTE, BETWEEN, answered]);
        const threads = threading([[302, conversation]]);
        const reads = { ...threads, read: { ...threads.read, threads: threads.read.threads.map((each) => (each.thread.number === 302 ? read : each)) } };
        const out = lay(302, EMPTY, reads);
        expect(out.regions.some((each) => each.item.number === 51)).toBe(true);
        expect(reaching(out, out.groups[0]?.banner.from ?? 0, "done")).toMatchObject({ says: "mark its news read, each item with it" });
    });

    it("lays a part of the operator's words moved in after who wrote it, open, and writes on a thread to whoever answers for it, at its end", () => {
        const out = lay(307);
        expect(lines(out)).toContain("you · @50.3 to s1, moved here · open: waits on s1/a1");
        const voice = out.groups[0];
        const at = voice?.banner.from ?? 0;
        expect(groupAt(out, at)).toBe(voice);
        expect(scopeAt(out, at)).toBeUndefined();
        expect(opened(out, at)).toEqual({ id: "", to: WORKER, thread: 307, text: "" });
        const written = lay(307, { ...EMPTY, letters: [{ id: "m1", to: WORKER, thread: 307, text: "It still lags." }] });
        // Under the line saying whom it reaches, under what's live, laid out once.
        expect(written.text.trimEnd().split("\n").slice(-2)).toEqual(["── to s1/a1 on @voice ──", "It still lags."]);
        expect(written.text.split("It still lags.").length).toBe(2);
        const block = written.groups[0]?.blocks[0];
        expect(block).toBeDefined();
        const where = heading(written, block?.from ?? 0, true, written.written, { group: () => "", item: () => "", party: called });
        expect(where[0]).toEqual({ kind: "to", text: "to s1/a1" });
        const nobody = lay(307, { ...EMPTY, letters: [{ id: "m2", to: null, thread: 307, text: "A note to myself." }] });
        const kept = nobody.groups[0]?.blocks[0];
        expect(heading(nobody, kept?.from ?? 0, true, nobody.written, { group: () => "", item: () => "", party: called })[0]).toEqual({ kind: "to", text: "to no one, kept in @voice" });
    });

    it("reads a thread up to what it shows as the operator acts in it, an item marked or commented on, a check ticked, a message on it, never past news left unread", () => {
        const upTo = (number: number, draft: Draft) =>
            threadsRead(lay(number, draft), draft).map((each) => {
                const argument = each.argument as { key: { node: number }; up_to: string };
                return [argument.key.node, argument.up_to, each.says];
            });
        expect(upTo(303, EMPTY)).toEqual([]);
        // An item marked read in @auth: it's read up to the last item it shows, as Space d on its banner reads it.
        expect(upTo(303, { ...EMPTY, done: [70] })).toEqual([[303, "70", "@auth read"]]);
        expect(upTo(303, { ...EMPTY, comments: [{ id: "c1", item: 70, text: "Thanks." }] as Draft["comments"] })).toEqual([[303, "70", "@auth read"]]);
        // A check ticked in @reader, and a message written on it: read up to what it shows, what's asked not holding it back.
        const tick = { id: "t1", action: "inbox-check-answer", argument: { number: 311 }, verb: "done", says: "tick it", block: "check 311", version: null };
        expect(upTo(302, { ...EMPTY, marks: [tick] })).toEqual([[302, "67", "@reader read"]]);
        expect(upTo(302, { ...EMPTY, letters: [{ id: "m1", to: WORKER, thread: 302, text: "Go on." }] })).toEqual([[302, "67", "@reader read"]]);
        // A message on @auth leaves its note unread: it's read no further than before it, so the note stays new.
        expect(upTo(303, { ...EMPTY, letters: [{ id: "m2", to: WORKER, thread: 303, text: "Go on." }] })).toEqual([]);
        // Read already by the operator's own mark, it's theirs alone.
        const out = lay(303, { ...EMPTY, done: [70] });
        const reach = reaching(out, out.text.indexOf("━━ @auth"), "done", EMPTY);
        const own = reach === null || reach.on === null ? undefined : reach.acts.find((each) => each.kind === "mark");
        expect(own).toBeDefined();
        const marked = marking({ ...EMPTY, done: [70] }, own === undefined ? [] : [own], "done");
        expect(threadsRead(lay(303, marked), marked)).toEqual([]);
        // Among the marks a comment implies, shown and sent with them.
        expect(implied(lay(303, { ...EMPTY, done: [70] }), { ...EMPTY, done: [70] }).map((each) => each.action)).toEqual(["review-mark"]);
    });

    it("strikes an item's header through only where the draft marks it, muting what no longer waits as the thread's history", () => {
        const answered = { ...NOTE, state: { state: "done", at: AT } } as Item;
        const classes = (item: Item, draft: Draft) => headerClasses(item, draft, UNSEEN).split(" ");
        expect(classes(answered, EMPTY)).toContain("is-past");
        expect(classes(answered, EMPTY)).not.toContain("is-done");
        expect(classes(LATE, { ...EMPTY, done: [70] })).toContain("is-done");
        expect(classes(LATE, EMPTY)).not.toContain("is-past");
    });

    it("folds each of the few read entries shown before what's new to its header, as context", () => {
        const read = { ...AUTH, mark: { key: { node: 303 }, up_to: "47", at: AT, seen: false } } as ThreadRead;
        const seen = shown(
            read,
            [
                { spot: { node: 47 }, came: AT, member: true, earlier: true, seen: true },
                { spot: { node: 70 }, came: AT, member: true, new: true },
            ] as unknown as ThreadShown["entries"],
            [NOTE, LATE],
            { left: 4 },
        );
        const threads = threading([[303, seen]]);
        const out = lay(303, EMPTY, { ...threads, read: { ...threads.read, threads: threads.read.threads.map((each) => (each.thread.number === 303 ? read : each)) } });
        expect(lines(out)[1]).toBe("── @47 ──");
        expect(out.regions.find((each) => each.item.number === 47)?.folds.find((each) => each.kind === "item")?.closed).toBe(true);
        expect(out.regions.find((each) => each.item.number === 70)?.folds.find((each) => each.kind === "item")?.closed).toBe(false);
    });

    it("folds what no longer waits in a thread's conversation to its header, its history", () => {
        const answered = hosted({ ...QUESTION, state: { state: "answered", at: AT, answer: 60 } });
        const read = { ...READER, asks: [{ node: 311, what: "a check", came: AT, holds: false }] } as ThreadRead;
        const threads = threading([[302, shown(read, READER_WHOLE.entries, [NOTE, BETWEEN, answered], { checks: [CHECK] })]]);
        const out = lay(302, EMPTY, { ...threads, read: { ...threads.read, threads: threads.read.threads.map((each) => (each.thread.number === 302 ? read : each)) } });
        expect(out.regions.find((each) => each.item.number === 51)?.folds.find((each) => each.kind === "item")?.closed).toBe(true);
    });

    it("sends a message written on a thread to no one with Space s, and back to whoever answers for it", () => {
        const draft = { ...EMPTY, letters: [{ id: "m1", to: WORKER, thread: 307, text: "It still lags." }] };
        const out = lay(307, draft);
        const block = out.groups[0]?.blocks[0];
        const reach = block === undefined ? null : reaching(out, block.from, "send");
        expect(reach).toMatchObject({ says: "send it to no one: it stays on the thread, waking nobody", acts: [{ kind: "readdress", id: "m1", to: null }] });
        const nobody = reach === null || reach.on === null ? draft : marking(draft, reach.acts, "send");
        expect(nobody.letters?.[0]?.to).toBeNull();
        const back = lay(307, nobody);
        const again = back.groups[0]?.blocks[0];
        expect(again === undefined ? null : reaching(back, again.from, "send")).toMatchObject({ says: "send it to s1/a1", acts: [{ kind: "readdress", to: WORKER }] });
    });

    it("says on the line under the review where each message on a thread goes, and a check answered in words", () => {
        const draft = {
            ...EMPTY,
            letters: [
                { id: "m1", to: WORKER, thread: 307, text: "It still lags." },
                { id: "m2", to: null, thread: 303, text: "A note to myself." },
            ],
            comments: [{ id: "c1", item: 311, quote: null, text: "Found it." }],
        };
        const naming = { called: (party: Item["sender"]) => (party.party === "operator" ? "you" : called(party)), named: () => "", holder: () => null, thread: (number: number) => (number === 307 ? "voice" : "auth"), checks: new Set([311]) };
        expect(toSend(draft, [], naming).map(partSaid)).toEqual(["to s1/a1: a message on @voice", "to no one: a message on @auth", "to the check: answering @311"]);
    });

    it("folds a friction and how it felt in its conversation to its header, saying where each is", () => {
        const friction = item(80, WORKER, { reason: "friction", text: "The gate hung.", title: "the gate hangs" } as Item["reason"]);
        const untitled = item(82, WORKER, { reason: "friction", text: "Typing lags.", title: "" } as Item["reason"]);
        const felt = item(81, LEAD, { reason: "how it felt", text: "Steady." } as Item["reason"]);
        const conversation = shown(AUTH, [{ spot: { node: 81 }, came: AT, member: true }, { spot: { node: 80 }, came: AT, member: true, moved: true }, { spot: { node: 82 }, came: AT, member: true, went: 302 }] as unknown as ThreadShown["entries"], [felt, friction, untitled]);
        const told: string[] = [];
        const out = laid([felt], [LEAD], banner, (shownItem, _, words) => {
            told.push(`${shownItem.number}: ${words}`);
            return header(shownItem);
        }, EMPTY, NOTHING, [], new Map(), called, { threads: threading([[303, conversation]]), showing: { kind: "thread", number: 303 } });
        expect(told.map((each) => each.replace(/^(\d+): .*? · /, "$1: "))).toEqual(["81: in the pile to read", "80: moved here", "82: moved to @reader"]);
        expect(out.regions.map((each) => each.folds.find((fold) => fold.kind === "item")?.closed)).toEqual([true, true, true]);
    });

    it("never marks the operator's own words in a thread done, declined or left for later: Space d goes on to the thread and reads it, as on its banner", () => {
        // Their review, moved into @auth as an agent moves one with `thread`: the host ranks it waiting on them, but a reply
        // never answers it, and refused a mark on it, the whole reply.
        const own = {
            ...item(
                90,
                LEAD,
                { reason: "review", covers: [], comments: [], letters: [{ id: "", to: LEAD, thread: null, text: "Ship the parser first." }], remarks: [] } as unknown as Item["reason"],
                WAITING,
            ),
            sender: { party: "operator" },
            recipient: LEAD,
        } as Item;
        const moved = shown(
            AUTH,
            [
                { spot: { node: 90 }, came: AT, member: true },
                { spot: { node: 70 }, came: AT, member: true, new: true },
            ] as ThreadShown["entries"],
            [own, LATE],
        );
        const out = lay(303, EMPTY, threading([[303, moved]]));
        const region = out.regions.find((each) => each.item.number === 90);
        expect(region).toBeDefined();
        const at = region?.header.from ?? 0;
        const marked = (name: string) => {
            const reach = reaching(out, at, name);
            return reach === null || reach.on === null ? [] : reach.acts.filter((each) => each.kind === "item" && each.number === 90);
        };
        expect(marked("done")).toEqual([]);
        expect(marked("decline")).toEqual([]);
        expect(marked("send")).toEqual([]);
        expect(reaching(out, at, "done")).toMatchObject({ on: "@auth", says: "mark its news read, each item with it" });
        // Nor are they ever to answer, which `]a` stops at and a thread's banner counts as left.
        expect(toAnswer(own, EMPTY)).toBe(false);
        // A comment on them is opened still: the host writes it on their thread, to whoever answers for it.
        expect(reaching(out, at, "comment")).toMatchObject({ on: region?.named, says: "comment on it" });
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
