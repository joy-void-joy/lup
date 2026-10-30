// The review grouped by thread (`docs/dashboard.md`, *The review*): its sections, each thread's banner and its
// conversation from where the operator read it, what came before folded and read as it opens, a check, the operator's
// words, a message between agents folded to its header, a thread's "since you approved", what the verbs do on a
// thread's banner, and where what's written there goes.
import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import { marking, reachOf } from "./grammar";
import { toSend, waitingOn } from "./App";
import { outlineOf } from "./outline";
import {
    EMPTY,
    checkAt,
    groupAt,
    headerClasses,
    heading,
    laid,
    opened,
    scopeAt,
    threadPlace,
    untilCalled,
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
    return {
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
    };
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
        { node: 51, what: "a question", came: AT },
        { node: 311, what: "a check", came: AT },
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
    [NOTE, BETWEEN, QUESTION],
    { checks: [CHECK] },
);
const AUTH_SHOWN = shown(AUTH, [{ spot: { node: 70 }, came: AT, member: true, new: true }] as ThreadShown["entries"], [LATE]);
const VOICE_SHOWN = shown(VOICE, [{ spot: { node: 50, part: 3 }, came: AT, member: true, unanswered: true, said: "Put it on its branch.", to: LEAD }] as ThreadShown["entries"], []);

const NOTHING: Around = { contexts: new Map(), files: new Map(), answers: [], commented: [] };
const header = (shownItem: Item) => `── @${shownItem.number} ──`;
const banner = () => "━━ agent ━━";
const called = (party: Conversation) => (party.agent === null || party.agent === undefined ? party.session : `${party.session}/${party.agent}`);

function threading(whole: boolean = false): Threading {
    return {
        read: { kind: "inbox-threads-read", threads: [READER, VOICE, AUTH, DOCS_NOBODY, NAMES, CACHE], paths: [], working: [{ conversation: WORKER, thread: 302 }] },
        shown: new Map([
            [302, READER_SHOWN],
            [303, AUTH_SHOWN],
            [307, VOICE_SHOWN],
        ]),
        whole: whole ? new Map([[302, READER_WHOLE]]) : new Map(),
        landing: new Map(),
        banner: (read, landing) => threadBanner(read, landing, called),
    };
}

function lay(draft: Draft = EMPTY, whole: boolean = false, places: string[] = []): Laid {
    return laid([QUESTION, LATE], [LEAD], banner, header, draft, NOTHING, places, new Map(), called, { threads: threading(whole) });
}

function lines(out: Laid): string[] {
    return out.text.split("\n");
}

describe("the review grouped by thread", () => {
    it("lays out each section under its line: waiting on you, those blocked on the operator before those done, new, the front open, to read, settled and agents", () => {
        const out = lay();
        expect(out.sections.map((each) => out.text.slice(each.header.from, each.header.to))).toEqual([
            "waiting on you · 2",
            "new · 1",
            "open · 2",
            "to read · 0 frictions, 0 how it felt",
            "settled · 1 settled · 0 declined",
            "agents · 1",
        ]);
        expect(out.groups.map((each) => [out.text.slice(each.banner.from, each.banner.to), each.depth])).toEqual([
            ["━━ @reader · The reader · s1/a1 holds · a question, a check ━━", 0],
            ["━━ @voice · The voice · s1/a1 holds · done, to confirm ━━", 0],
            ["━━ @auth · The auth · s1/a1 holds · 1 new ━━", 0],
            // The front: each thread still open, a line each, nested as threads nest, saying who holds it and where it stands.
            ["━━ @docs · The docs · nobody holds it, s1 answers · working ━━", 0],
            ["━━ @names · The names · s1/a1 holds · parked until reader lands ━━", 1],
            ["━━ @cache · The cache · s1/a1 holds · settled ━━", 0],
            ["━━ agent ━━", 0],
        ]);
        // The front is open, each of its threads folded to its banner; the pile, what's settled and the agents fold whole.
        expect(out.sections.map((each) => each.fold?.closed ?? null)).toEqual([false, false, false, true, true, true]);
        expect(out.groups.filter((each) => ["docs", "names", "cache"].includes(each.thread?.thread.name ?? "")).map((each) => each.fold?.closed)).toEqual([true, true, true]);
    });

    it("keeps each thread where it was laid out, a later one after, however its since changes", () => {
        const out = lay(EMPTY, false, [threadPlace(307), threadPlace(302)]);
        // Blocked on the operator first, whatever the order kept, then done; within each, the order kept.
        expect(out.groups.slice(0, 2).map((each) => each.thread?.thread.name)).toEqual(["reader", "voice"]);
    });

    it("lays a thread's conversation from where the operator read it, what came before under one line read whole as it opens", () => {
        const out = lay();
        const text = lines(lay());
        expect(text.slice(1, 4)).toEqual(["━━ @reader · The reader · s1/a1 holds · a question, a check ━━", "2 earlier, read", "reading…"]);
        const earlier = out.outer.find((each) => each.kind === "read");
        expect(earlier).toMatchObject({ closed: true, unread: true, label: "2 earlier" });
        expect(out.loading.map((each) => [each.number, each.whole])).toEqual([
            [302, true],
            [304, false],
            [306, false],
            [305, false],
        ]);
        const whole = lay(EMPTY, true);
        const read = lines(whole);
        // The earlier entries, under the line: an item, the operator's words on it inside it, a message between
        // agents folded to its header.
        expect(read.slice(2, 9)).toEqual(["2 earlier, read", "── @47 ──", "Two readers, one each.", "you · @48.1", "  Keep the two apart.", "", "── @67 ──"]);
        const between = whole.regions.find((each) => each.item.number === 67);
        expect(between?.folds.find((each) => each.kind === "item")?.closed).toBe(true);
        expect(whole.loading.map((each) => each.number)).toEqual([304, 306, 305]);
    });

    it("lays a check where it came, what's to try waiting on the operator, Space d ticking it, a comment under it their answer in words", () => {
        const out = lay();
        const at = out.text.indexOf("◆ check @311: Search a long record.");
        expect(at).toBeGreaterThan(0);
        expect(checkAt(out, at)?.check.check.number).toBe(311);
        const done = adopted().verbs.find((each) => each.name === "done");
        expect(done).toBeDefined();
        const reach = done === undefined ? null : reachOf(out, at, done, { called });
        expect(reach).toMatchObject({ says: "tick it: you tried it" });
        expect(opened(out, at)).toEqual({ id: "", item: 311, quote: null, text: "" });
        const answering = lay({ ...EMPTY, comments: [{ id: "c1", item: 311, quote: null, text: "Found it in a second." }] });
        expect(lines(answering)).toContain("Found it in a second.");
    });

    it("lays what's to try under a thread done, Space d settling it and Space x declining it, as marks sent with the reply", () => {
        const out = lay();
        expect(lines(out)).toContain("◆ to try: Read the voice section.");
        const voice = out.groups.find((each) => each.thread?.thread.name === "voice");
        expect(voice).toBeDefined();
        const at = voice?.banner.from ?? 0;
        const verbs = adopted().verbs;
        const by = (name: string) => {
            const verb = verbs.find((each) => each.name === name);
            return verb === undefined ? null : reachOf(out, at, verb, { called });
        };
        expect(by("done")).toMatchObject({ says: "settle it: it works", acts: [{ kind: "mark", offer: { action: "inbox-settle-thread", argument: { number: 307 } } }] });
        expect(by("decline")).toMatchObject({ acts: [{ kind: "mark", offer: { action: "inbox-decline-thread" } }] });
        expect(by("comment")).toMatchObject({ says: "write on it, to s1/a1" });
    });

    it("marks a thread read up to the last item shown with Space d on its banner, its news with it, what asks left", () => {
        const out = lay();
        const done = adopted().verbs.find((each) => each.name === "done");
        const reader = out.groups.find((each) => each.thread?.thread.name === "reader");
        const reach = done === undefined || reader === undefined ? null : reachOf(out, reader.banner.from, done, { called });
        expect(reach).toMatchObject({
            says: "mark it read, @51 left",
            acts: [{ kind: "mark", offer: { action: "review-mark", argument: { module: "core", key: { node: 302 }, up_to: "51" } } }],
        });
        const auth = out.groups.find((each) => each.thread?.thread.name === "auth");
        const fresh = done === undefined || auth === undefined ? null : reachOf(out, auth.banner.from, done, { called });
        expect(fresh).toMatchObject({ says: "mark it read, its news with it", acts: [{ kind: "mark" }, { kind: "item", number: 70, list: "done" }] });
    });

    it("lays a part of the operator's words moved in after who wrote it, open, and writes on a thread to whoever answers for it", () => {
        const out = lay();
        expect(lines(out)).toContain("you · @50.3 to s1, moved here · open: waits on s1/a1");
        const voice = out.groups.find((each) => each.thread?.thread.name === "voice");
        const at = voice?.banner.from ?? 0;
        expect(groupAt(out, at)).toBe(voice);
        expect(scopeAt(out, at)).toBeUndefined();
        expect(opened(out, at)).toEqual({ id: "", to: WORKER, thread: 307, text: "" });
        const written = laid([QUESTION, LATE], [LEAD, WORKER], banner, header, { ...EMPTY, letters: [{ id: "m1", to: WORKER, thread: 307, text: "It still lags." }] }, NOTHING, [], new Map(), called, { threads: threading() });
        const voiceAfter = written.groups.find((each) => each.thread?.thread.name === "voice");
        expect(written.text.slice(voiceAfter?.banner.from ?? 0).split("\n").slice(0, 2)).toEqual([
            "━━ @voice · The voice · s1/a1 holds · done, to confirm ━━",
            "It still lags.",
        ]);
        const block = voiceAfter?.blocks[0];
        expect(block).toBeDefined();
        // Laid out once, on the thread, never again under the banner of whom it's to.
        expect(written.text.split("It still lags.").length).toBe(2);
        const where = heading(written, block?.from ?? 0, true, written.written, { group: () => "", item: () => "", party: called });
        expect(where[0]).toEqual({ kind: "to", text: "to s1/a1" });
        const nobody = lay({ ...EMPTY, letters: [{ id: "m2", to: null, thread: 307, text: "A note to myself." }] });
        const kept = nobody.groups.find((each) => each.thread?.thread.name === "voice")?.blocks[0];
        expect(heading(nobody, kept?.from ?? 0, true, nobody.written, { group: () => "", item: () => "", party: called })[0]).toEqual({ kind: "to", text: "to no one, kept in @voice" });
    });

    it("shows only what calls for the operator in a thread they never read, with what it's under, the rest folding with what came before", () => {
        const answered = { ...NOTE, state: { state: "done", at: AT } } as Item;
        const never = shown(
            AUTH,
            [
                { spot: { node: 47 }, came: AT, member: true },
                { spot: { node: 67 }, came: AT, member: true },
                { spot: { node: 70 }, under: { node: 67 }, came: AT, member: true, new: true },
            ] as ThreadShown["entries"],
            [answered, BETWEEN, LATE],
        );
        const split = untilCalled(never, AUTH);
        expect(split.before.map((each) => each.spot.node)).toEqual([47]);
        expect(split.after.map((each) => each.spot.node)).toEqual([67, 70]);
        // Read once, whatever came since shows.
        const marked = { ...AUTH, mark: { key: { node: 303 }, up_to: "40", at: AT } } as ThreadRead;
        expect(untilCalled(never, marked).before).toEqual([]);
    });

    it("folds the whole of a thread they never read once nothing in it calls for them, what they answered never coming back", () => {
        const answered = { ...NOTE, state: { state: "done", at: AT } } as Item;
        const done = { ...LATE, state: { state: "done", at: AT } } as Item;
        const quiet = { ...AUTH, section: "every thread", new: [] } as ThreadRead;
        const never = shown(
            quiet,
            [
                { spot: { node: 47 }, came: AT, member: true },
                { spot: { node: 70 }, came: AT, member: true },
            ] as ThreadShown["entries"],
            [answered, done],
        );
        const split = untilCalled(never, quiet);
        expect(split.before.map((each) => each.spot.node)).toEqual([47, 70]);
        expect(split.after).toEqual([]);
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
        const read = { ...AUTH, mark: { key: { node: 303 }, up_to: "47", at: AT } } as ThreadRead;
        const seen = shown(
            read,
            [
                { spot: { node: 47 }, came: AT, member: true, earlier: true, seen: true },
                { spot: { node: 70 }, came: AT, member: true, new: true },
            ] as unknown as ThreadShown["entries"],
            [NOTE, LATE],
            { left: 4 },
        );
        const threads = threading();
        const reads = { ...threads.read, threads: threads.read.threads.map((each) => (each.thread.number === 303 ? read : each)) };
        const out = laid([LATE], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { threads: { ...threads, read: reads, shown: new Map([[303, seen]]) } });
        const text = lines(out);
        const at = text.indexOf("━━ @auth · The auth · s1/a1 holds · 1 new ━━");
        expect(text.slice(at + 1, at + 4)).toEqual(["4 earlier, read", "reading…", "── @47 ──"]);
        expect(out.regions.find((each) => each.item.number === 47)?.folds.find((each) => each.kind === "item")?.closed).toBe(true);
        expect(out.regions.find((each) => each.item.number === 70)?.folds.find((each) => each.kind === "item")?.closed).toBe(false);
    });

    it("folds what no longer waits in a thread's conversation to its header, its history", () => {
        const answered = { ...QUESTION, state: { state: "answered", at: AT, by: 60 } } as unknown as Item;
        const read = { ...READER, asks: [{ node: 311, what: "a check", came: AT }] } as ThreadRead;
        const threads = threading();
        const out = laid([], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, {
            threads: { ...threads, shown: new Map([[302, shown(read, READER_SHOWN.entries, [answered], { checks: [CHECK] })]]) },
        });
        const region = out.regions.find((each) => each.item.number === 51);
        expect(region?.folds.find((each) => each.kind === "item")?.closed).toBe(true);
    });

    it("sends a message written on a thread to no one with Space s, and back to whoever answers for it", () => {
        const draft = { ...EMPTY, letters: [{ id: "m1", to: WORKER, thread: 307, text: "It still lags." }] };
        const out = lay(draft);
        const block = out.groups.find((each) => each.thread?.thread.name === "voice")?.blocks[0];
        const send = adopted().verbs.find((each) => each.name === "send");
        expect(send).toBeDefined();
        const reach = send === undefined || block === undefined ? null : reachOf(out, block.from, send, { called });
        expect(reach).toMatchObject({ says: "send it to no one: it stays on the thread, waking nobody", acts: [{ kind: "readdress", id: "m1", to: null }] });
        const nobody = reach === null || reach.on === null ? draft : marking(draft, reach.acts, "send");
        expect(nobody.letters?.[0]?.to).toBeNull();
        const back = lay(nobody);
        const again = back.groups.find((each) => each.thread?.thread.name === "voice")?.blocks[0];
        const returned = send === undefined || again === undefined ? null : reachOf(back, again.from, send, { called });
        expect(returned).toMatchObject({ says: "send it to s1/a1", acts: [{ kind: "readdress", to: WORKER }] });
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
        expect(toSend(draft, [], naming)).toEqual(["to s1/a1: a message on @voice", "to no one: a message on @auth", "to the check: answering @311"]);
    });

    it("goes from an agent's name to their own views among the agents with gd", () => {
        const out = laid([QUESTION], [LEAD, WORKER], banner, header, EMPTY, NOTHING, [], new Map(), called, { threads: threading() });
        const reader = out.groups.find((each) => each.thread?.thread.name === "reader");
        const line = out.text.slice(reader?.banner.from ?? 0, reader?.banner.to ?? 0);
        const at = (reader?.banner.from ?? 0) + line.indexOf("s1/a1") + 2;
        const group = agentNamed(out, at, called);
        expect(group?.thread).toBeNull();
        expect(group?.conversation).toEqual(WORKER);
        expect(agentNamed(out, reader?.banner.from ?? 0, called)).toBeUndefined();
    });

    it("counts the threads waiting on the operator, and what asks them in no thread by whom it's from", () => {
        const approval = { ...QUESTION, number: 54, sender: { party: "operator" } } as Item;
        expect(waitingOn(threading().read, new Map(), [QUESTION, approval])).toBe(3);
        expect(waitingOn(null, new Map(), [QUESTION, approval])).toBe(2);
    });

    it("lists each section and thread in the overview, nested as the review is", () => {
        const out = lay();
        const rows = outlineOf(out, { draft: EMPTY, seeing: UNSEEN, states: new Map(), called });
        expect(rows.filter((each) => each.kind === "repository" || each.kind === "thread").map((each) => each.text)).toEqual([
            "waiting on you",
            "@reader",
            "@voice",
            "new",
            "@auth",
            "open",
            "@docs",
            "@names",
            "settled",
            "@cache",
            "agents",
        ]);
    });
});
