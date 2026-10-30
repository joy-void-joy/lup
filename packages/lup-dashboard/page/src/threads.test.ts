// The review grouped by thread (`docs/dashboard.md`, *The review*): its sections, each thread's banner and its
// conversation from where the operator read it, what came before folded and read as it opens, a check, the operator's
// words, a message between agents folded to its header, a thread's "since you approved", what the verbs do on a
// thread's banner, and where what's written there goes.
import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import { MOVE, implied, isMarked, listed, marking, movedInto, reachOf, reachedIn, threadsRead, type Act } from "./grammar";
import { toSend, waitingOn } from "./App";
import { partSaid } from "./brief";
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
    pileTitle,
    placeIn,
    ROOT_TITLE,
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
import { agentNamed, threadBanner, threadTarget } from "./Review";
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

function threading(whole: boolean = false, more: [number, ThreadShown][] = []): Threading {
    return {
        read: { kind: "inbox-threads-read", threads: [READER, VOICE, AUTH, DOCS_NOBODY, NAMES, CACHE], paths: [], working: [{ conversation: WORKER, thread: 302 }] },
        shown: new Map([
            [302, READER_SHOWN],
            [303, AUTH_SHOWN],
            [307, VOICE_SHOWN],
        ]),
        whole: new Map([...(whole ? [[302, READER_WHOLE] as [number, ThreadShown]] : []), ...more]),
        landing: new Map(),
        banner: (read, landing, section) => threadBanner(read, landing, called, section),
    };
}

function lay(draft: Draft = EMPTY, whole: boolean = false, places: string[] = []): Laid {
    return laid([QUESTION, LATE], [LEAD], banner, header, draft, NOTHING, places, new Map(), called, { threads: threading(whole) });
}

function lines(out: Laid): string[] {
    return out.text.split("\n");
}

describe("the review grouped by thread", () => {
    it("lays out each section under its line: waiting on you, what asks under each thread's header, new, open, every thread still open, to read, settled and agents", () => {
        const out = lay();
        expect(out.sections.map((each) => out.text.slice(each.header.from, each.header.to))).toEqual([
            "waiting on you · 2",
            "new · 1",
            "open · 5",
            "to read · 0 frictions, 0 how it felt",
            "settled · 1 settled · 0 declined",
            "agents · 1",
        ]);
        expect(out.groups.map((each) => [out.text.slice(each.banner.from, each.banner.to), each.depth])).toEqual([
            // Waiting on you: what asks the operator in each thread, under its header.
            ["━━ @reader · The reader · s1/a1 holds · a question, a check ━━", 0],
            ["━━ @voice · The voice · s1/a1 holds · done, to confirm ━━", 0],
            // New: what's new in each.
            ["━━ @auth · The auth · s1/a1 holds · 1 new ━━", 0],
            // Open: every thread still open, always, a line each, nested as threads nest, saying who holds it, where it
            // stands and how much of it waits on the operator or is new.
            ["━━ @reader · The reader · s1/a1 holds · working · 2 waiting ━━", 0],
            ["━━ @auth · The auth · s1/a1 holds · working · 1 new ━━", 0],
            ["━━ @docs · The docs · nobody holds it, s1 answers · working ━━", 0],
            ["━━ @names · The names · s1/a1 holds · parked until reader lands ━━", 1],
            ["━━ @voice · The voice · s1/a1 holds · done, to confirm ━━", 0],
            ["━━ @cache · The cache · s1/a1 holds · settled ━━", 0],
            ["━━ agent ━━", 0],
        ]);
        expect(out.groups.slice(0, 3).map((each) => each.place)).toEqual([placeIn("waiting", 302), placeIn("waiting", 307), placeIn("new", 303)]);
        // Open is open, each of its threads folded to its line; the pile, empty here, folds nothing; settled and the
        // agents fold whole.
        expect(out.sections.map((each) => each.fold?.closed ?? null)).toEqual([false, false, false, null, true, true]);
        expect(out.groups.filter((each) => each.place === threadPlace(each.thread?.thread.number ?? 0)).map((each) => each.fold?.closed)).toEqual([true, true, true, true, true, true]);
    });
    it("keeps each thread where it was laid out, a later one after, however its since changes", () => {
        const out = lay(EMPTY, false, [placeIn("waiting", 307), placeIn("waiting", 302)]);
        // Blocked on the operator first, whatever the order kept, then done; within each, the order kept.
        expect(out.groups.slice(0, 2).map((each) => each.thread?.thread.name)).toEqual(["reader", "voice"]);
    });

    it("lays what asks the operator under its thread's header, the thread whole in open read as it opens, each item laid out above a line pointing to it there", () => {
        const out = lay();
        const text = lines(out);
        expect(text.slice(1, 3)).toEqual(["━━ @reader · The reader · s1/a1 holds · a question, a check ━━", "── @51 ──"]);
        expect(text).toContain("◆ check @311: Search a long record.");
        // Each thread of open and settled is read whole as it opens.
        expect(out.loading.map((each) => [each.number, each.whole])).toEqual([
            [302, true],
            [303, true],
            [304, true],
            [306, true],
            [307, true],
            [305, true],
        ]);
        const whole = lay(EMPTY, true);
        const read = lines(whole);
        const at = read.indexOf("━━ @reader · The reader · s1/a1 holds · working · 2 waiting ━━");
        // Its whole conversation in order: an item, the operator's words on it inside it, a message between agents
        // folded to its header; what's laid out above a line pointing to it, which gd follows.
        expect(read.slice(at + 1, at + 9)).toEqual([
            "── @47 ──",
            "Two readers, one each.",
            "you · @48.1",
            "  Keep the two apart.",
            "",
            "── @67 ──",
            "Count each kind of line.",
            "",
        ]);
        expect(read.slice(at + 9, at + 11)).toEqual(["↑ @51 question · in waiting on you · gd goes there", "↑ @311 check · in waiting on you · gd goes there"]);
        expect(whole.pointers.map((each) => [each.node, each.section])).toEqual([
            [51, "waiting on you"],
            [311, "waiting on you"],
        ]);
        // Each item is laid out once: @51 in waiting on you alone.
        expect(whole.regions.filter((each) => each.item.number === 51)).toHaveLength(1);
        expect(whole.regions.find((each) => each.item.number === 67)?.folds.find((each) => each.kind === "item")?.closed).toBe(true);
        expect(threadTarget(whole, 302, 51)).toBe(whole.pointers[0]?.from);
        expect(threadTarget(whole, 302, null)).toBe(whole.groups.find((each) => each.place === threadPlace(302))?.banner.from);
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

    it("marks a thread's news read with Space d on its banner where there's some, then settles it, never where something waits on the operator", () => {
        const out = lay();
        const verbs = adopted().verbs;
        const done = verbs.find((each) => each.name === "done");
        const decline = verbs.find((each) => each.name === "decline");
        const on = (name: string, verb: typeof done, draft: Draft = EMPTY) => {
            const group = out.groups.find((each) => each.thread?.thread.name === name);
            return verb === undefined || group === undefined ? null : reachOf(out, group.banner.from, verb, { called, draft });
        };
        // The reader asks a question and a check, and has no news: it isn't settled, nor declined, and says why.
        expect(on("reader", done)).toMatchObject({ says: "not settled while 2 wait on you", acts: [] });
        expect(on("reader", decline)).toMatchObject({ says: "not declined while 2 wait on you", acts: [] });
        // Each answered in the draft, the question marked done and the check ticked, it settles.
        const answered: Draft = { ...EMPTY, done: [51], marks: [{ id: "c", action: "inbox-check-answer", argument: { number: 311 }, verb: "done", says: "tried", block: "check 311", version: null }] };
        expect(on("reader", done, answered)).toMatchObject({ says: "settle it", acts: [{ kind: "mark", offer: { action: "inbox-settle-thread", argument: { number: 302 } } }] });
        // The survey has news: Space d reads it, up to the newest, its news item with it; marked so, Space d settles it.
        const fresh = on("auth", done);
        expect(fresh).toMatchObject({
            says: "mark its news read, each item with it",
            acts: [{ kind: "mark", offer: { action: "review-mark", argument: { key: { node: 303 }, up_to: "70" } } }, { kind: "item", number: 70, list: "done" }],
        });
        const read = fresh === null || fresh.on === null ? EMPTY : marking(EMPTY, fresh.acts, "done");
        expect(on("auth", done, read)).toMatchObject({ says: "settle it", acts: [{ kind: "mark", offer: { action: "inbox-settle-thread", argument: { number: 303 } } }] });
        // Decline on it whenever, nothing waiting; settled, it's declined no more, the one taking the other's place.
        const declining = on("auth", decline);
        expect(declining).toMatchObject({ says: "decline it: nothing more will be done", acts: [{ kind: "mark", offer: { action: "inbox-decline-thread" } }] });
        const settling = on("auth", done, read);
        const settled = settling === null || settling.on === null ? read : marking(read, settling.acts, "done");
        const instead = declining === null || declining.on === null ? settled : marking(settled, declining.acts, "decline");
        expect((instead.marks ?? []).filter((each) => each.action.startsWith("inbox-")).map((each) => each.action)).toEqual(["inbox-decline-thread"]);
        // A thread settled already takes neither.
        expect(on("cache", done)?.on).toBeNull();
    });

    it("lists the roots of sessions that have ended in open after the others, under a line Space d settles them from", () => {
        const gone = from("s7");
        const root = (number: number, name: string, read: Partial<ThreadRead> = {}) => {
            const made = thread(number, name, { holder: gone, answering: null, ...read } as Partial<ThreadRead>);
            return { ...made, thread: { ...made.thread, title: ROOT_TITLE, holder: gone, by: gone }, answering: null } as ThreadRead;
        };
        const idle = root(320, "old-session");
        const asked = root(321, "older-session", { state: "waiting on the operator", section: "waiting on you", asks: [{ node: 51, what: "a question", came: AT }] });
        const under = { ...thread(322, "kept-on", {}), thread: { ...thread(322, "kept-on", {}).thread, parent: 320 } } as ThreadRead;
        const threads = threading();
        const reads = { ...threads.read, threads: [...threads.read.threads, idle, asked, under] };
        const out = laid([QUESTION, LATE], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { threads: { ...threads, read: reads } });
        const text = lines(out);
        const open = text.indexOf("open · 8");
        const ended = text.indexOf("ended · 2");
        expect(open).toBeGreaterThan(0);
        expect(ended).toBeGreaterThan(open);
        // Each root its own thread, a line each, after every other; a thread under one stays with the others.
        expect(text.slice(ended + 1).filter((line) => line.startsWith("━━ ")).slice(0, 2)).toEqual([
            "━━ @old-session · the session's own · its session has ended · working ━━",
            "━━ @older-session · the session's own · its session has ended · working · 1 waiting ━━",
        ]);
        expect(text.slice(open, ended).some((line) => line.startsWith("━━ @kept-on"))).toBe(true);
        // No thread's fold holds the line.
        const before = out.groups.filter((each) => each.banner.from < out.text.indexOf("ended · 2"));
        expect(before.every((each) => each.end < out.text.indexOf("ended · 2"))).toBe(true);
        // On it, Space d settles each, but one where something waits on the operator, counted; Space x declines.
        const at = out.text.indexOf("ended · 2");
        const verbs = adopted().verbs;
        const by = (name: string) => {
            const verb = verbs.find((each) => each.name === name);
            return verb === undefined ? null : reachOf(out, at, verb, { called });
        };
        expect(by("done")).toMatchObject({
            on: "ended sessions' roots",
            says: "settle it, 1 left: something in it waits on you",
            acts: [{ kind: "mark", offer: { action: "inbox-settle-thread", argument: { number: 320 } } }],
        });
        expect(by("decline")).toMatchObject({ says: "decline it, 1 left: something in it waits on you", acts: [{ kind: "mark", offer: { action: "inbox-decline-thread", argument: { number: 320 } } }] });
        expect(out.ended?.threads.map((each) => each.thread.name)).toEqual(["old-session", "older-session"]);
        // The overview says the line too, set in under open, the roots after it.
        const rows = outlineOf(out, { draft: EMPTY, seeing: UNSEEN, states: new Map(), called }).map((each) => `${each.depth} ${each.text}`);
        expect(rows.slice(rows.indexOf("1 ended"), rows.indexOf("1 ended") + 3)).toEqual(["1 ended", "1 @old-session", "1 @older-session"]);
    });

    it("settles a working thread whose holder has ended, its news none", () => {
        const out = lay(EMPTY, false);
        const done = adopted().verbs.find((each) => each.name === "done");
        const ticks = out.groups.find((each) => each.thread?.thread.name === "docs");
        const reach = done === undefined || ticks === undefined ? null : reachOf(out, ticks.banner.from, done, { called });
        expect(reach).toMatchObject({ on: "@docs", says: "settle it", acts: [{ kind: "mark", offer: { action: "inbox-settle-thread", argument: { number: 304 } } }] });
    });

    it("keeps a thread's banner to one row, a long title cut at a word, whole in the overview", () => {
        const title = "Containment's open holes in the room's walls, kept off public GitHub: CI through a push, pasta, the cache's level";
        const long = { ...DOCS, thread: { ...DOCS.thread, title } } as ThreadRead;
        expect(threadBanner(long, 0, called)).toBe("━━ @docs · Containment's open holes in the room's walls, kept off… · s1/a1 held it, s1 answers · working ━━");
        const threads = threading();
        const out = laid([], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, {
            threads: { ...threads, read: { ...threads.read, threads: threads.read.threads.map((each) => (each.thread.number === 304 ? long : each)) } },
        });
        const row = outlineOf(out, { draft: EMPTY, seeing: UNSEEN, states: new Map(), called }).find((each) => each.text === "@docs");
        expect(row?.title).toBe(`@docs · ${title}`);
    });

    it("leaves nothing on a thread's banner that no longer waits: a question answered is the thread's history", () => {
        const answered = { ...QUESTION, state: { state: "answered", at: AT, by: 60 } } as unknown as Item;
        const read = { ...READER, state: "working", section: "every thread", asks: [] } as ThreadRead;
        const threads = threading(false, [[302, shown(read, READER_WHOLE.entries.filter((each) => each.spot.node !== 311), [NOTE, BETWEEN, answered])]]);
        const reads = { ...threads.read, threads: threads.read.threads.map((each) => (each.thread.number === 302 ? read : each)) };
        const out = laid([], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { threads: { ...threads, read: reads, shown: new Map() } });
        const done = adopted().verbs.find((each) => each.name === "done");
        const reader = out.groups.find((each) => each.thread?.thread.name === "reader");
        expect(out.regions.some((each) => each.item.number === 51)).toBe(true);
        const reach = done === undefined || reader === undefined ? null : reachOf(out, reader.banner.from, done, { called });
        expect(reach).toMatchObject({ says: "mark its news read, each item with it" });
    });

    it("lays a part of the operator's words moved in after who wrote it, open, and writes on a thread to whoever answers for it", () => {
        const out = laid([QUESTION, LATE], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { threads: threading(false, [[307, VOICE_SHOWN]]) });
        expect(lines(out)).toContain("you · @50.3 to s1, moved here · open: waits on s1/a1");
        const voice = out.groups.find((each) => each.thread?.thread.name === "voice");
        const at = voice?.banner.from ?? 0;
        expect(groupAt(out, at)).toBe(voice);
        expect(scopeAt(out, at)).toBeUndefined();
        expect(opened(out, at)).toEqual({ id: "", to: WORKER, thread: 307, text: "" });
        const written = laid([QUESTION, LATE], [LEAD, WORKER], banner, header, { ...EMPTY, letters: [{ id: "m1", to: WORKER, thread: 307, text: "It still lags." }] }, NOTHING, [], new Map(), called, { threads: threading() });
        const voiceAfter = written.groups.find((each) => each.thread?.thread.name === "voice");
        // Under the first of its headers, waiting on you's.
        expect(written.text.slice(voiceAfter?.banner.from ?? 0).split("\n").slice(0, 2)).toEqual([
            "━━ @voice · The voice · s1/a1 holds · done, to confirm ━━",
            "It still lags.",
        ]);
        const block = voiceAfter?.blocks[0];
        expect(block).toBeDefined();
        // Laid out once, under the first of its headers, never again under the banner of whom it's to.
        expect(written.text.split("It still lags.").length).toBe(2);
        const where = heading(written, block?.from ?? 0, true, written.written, { group: () => "", item: () => "", party: called });
        expect(where[0]).toEqual({ kind: "to", text: "to s1/a1" });
        const nobody = lay({ ...EMPTY, letters: [{ id: "m2", to: null, thread: 307, text: "A note to myself." }] });
        const kept = nobody.groups.find((each) => each.thread?.thread.name === "voice")?.blocks[0];
        expect(heading(nobody, kept?.from ?? 0, true, nobody.written, { group: () => "", item: () => "", party: called })[0]).toEqual({ kind: "to", text: "to no one, kept in @voice" });
    });
    it("shows in new what's new in a thread they never read, the few read before it as context, folded to its header", () => {
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
        const threads = threading();
        const out = laid([LATE], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { threads: { ...threads, shown: new Map([[303, never]]) } });
        const text = lines(out);
        const at = text.indexOf("━━ @auth · The auth · s1/a1 holds · 1 new ━━");
        expect(text.slice(at + 1).filter((line) => line.startsWith("── @")).slice(0, 3)).toEqual(["── @47 ──", "── @67 ──", "── @70 ──"]);
        const closed = (number: number) => out.regions.find((each) => each.item.number === number)?.folds.find((each) => each.kind === "item")?.closed;
        expect([closed(47), closed(67), closed(70)]).toEqual([true, true, false]);
    });
    it("reads a thread up to what it shows as the operator acts in it, an item marked or commented on, a check ticked, a message on it, never past news left unread", () => {
        const upTo = (draft: Draft) =>
            threadsRead(lay(draft), draft).map((each) => {
                const argument = each.argument as { key: { node: number }; up_to: string };
                return [argument.key.node, argument.up_to, each.says];
            });
        expect(upTo(EMPTY)).toEqual([]);
        // An item marked read in @auth: it's read up to the last item it shows, as Space d on its banner reads it.
        expect(upTo({ ...EMPTY, done: [70] })).toEqual([[303, "70", "@auth read"]]);
        expect(upTo({ ...EMPTY, comments: [{ id: "c1", item: 70, text: "Thanks." }] as Draft["comments"] })).toEqual([[303, "70", "@auth read"]]);
        // A check ticked in @reader, and a message written on it.
        const tick = { id: "t1", action: "inbox-check-answer", argument: { number: 311 }, verb: "done", says: "tick it", block: "check 311", version: null };
        expect(upTo({ ...EMPTY, marks: [tick] })).toEqual([[302, "51", "@reader read"]]);
        expect(upTo({ ...EMPTY, letters: [{ id: "m1", to: WORKER, thread: 302, text: "Go on." }] })).toEqual([[302, "51", "@reader read"]]);
        // A message on @auth leaves its note unread: it's read no further than before it, so the note stays new.
        expect(upTo({ ...EMPTY, letters: [{ id: "m2", to: WORKER, thread: 303, text: "Go on." }] })).toEqual([]);
        // Read already by the operator's own mark, it's theirs alone.
        const out = lay({ ...EMPTY, done: [70] });
        const reach = reachOf(out, out.text.indexOf("━━ @auth"), { name: "done", key: "d" } as Parameters<typeof reachOf>[2], { called });
        const own = reach.on === null ? undefined : reach.acts.find((each) => each.kind === "mark");
        expect(own).toBeDefined();
        const marked = marking({ ...EMPTY, done: [70] }, own === undefined ? [] : [own], "done");
        expect(threadsRead(lay(marked), marked)).toEqual([]);
        // Among the marks a comment implies, shown and sent with them.
        expect(implied(lay({ ...EMPTY, done: [70] }), { ...EMPTY, done: [70] }).map((each) => each.action)).toEqual(["review-mark"]);
    });

    it("leaves what calls for nothing out of new, its thread in open alone", () => {
        const answered = { ...NOTE, state: { state: "done", at: AT } } as Item;
        const done = { ...LATE, state: { state: "done", at: AT } } as Item;
        const quiet = { ...AUTH, section: "every thread", new: [] } as ThreadRead;
        const threads = threading();
        const reads = { ...threads.read, threads: threads.read.threads.map((each) => (each.thread.number === 303 ? quiet : each)) };
        const out = laid([], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, {
            threads: { ...threads, read: reads, shown: new Map([[302, READER_SHOWN], [303, shown(quiet, [{ spot: { node: 47 }, came: AT, member: true }, { spot: { node: 70 }, came: AT, member: true }] as ThreadShown["entries"], [answered, done])]]) },
        });
        const fresh = out.sections.find((each) => each.name === "new");
        expect(fresh === undefined ? "" : out.text.slice(fresh.header.from, fresh.header.to)).toBe("new · 0");
        expect(out.regions.map((each) => each.item.number)).toEqual([51]);
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
        expect(text[at + 1]).toBe("── @47 ──");
        expect(out.regions.find((each) => each.item.number === 47)?.folds.find((each) => each.kind === "item")?.closed).toBe(true);
        expect(out.regions.find((each) => each.item.number === 70)?.folds.find((each) => each.kind === "item")?.closed).toBe(false);
    });
    it("folds what no longer waits in a thread's conversation to its header, its history", () => {
        const answered = { ...QUESTION, state: { state: "answered", at: AT, by: 60 } } as unknown as Item;
        const read = { ...READER, asks: [{ node: 311, what: "a check", came: AT }] } as ThreadRead;
        const threads = threading(false, [[302, shown(read, READER_WHOLE.entries, [NOTE, BETWEEN, answered], { checks: [CHECK] })]]);
        const reads = { ...threads.read, threads: threads.read.threads.map((each) => (each.thread.number === 302 ? read : each)) };
        const out = laid([], [LEAD], banner, header, EMPTY, NOTHING, [], new Map(), called, { threads: { ...threads, read: reads, shown: new Map([[302, shown(read, READER_SHOWN.entries, [answered], { checks: [CHECK] })]]) } });
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
        expect(toSend(draft, [], naming).map(partSaid)).toEqual(["to s1/a1: a message on @voice", "to no one: a message on @auth", "to the check: answering @311"]);
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
            "@reader",
            "@auth",
            "@docs",
            "@names",
            "@voice",
            "settled",
            "@cache",
            "agents",
        ]);
    });
});

const FRICTION = item(80, WORKER, { reason: "friction", text: "The gate hung for four minutes.\nIt printed nothing.", title: "the gate hangs" } as Item["reason"]);
const UNTITLED = item(82, WORKER, { reason: "friction", text: "Typing lags in long comments.", title: "" } as Item["reason"]);
const FELT = item(81, LEAD, { reason: "how it felt", text: "Steady.\nThe brief named every file." } as Item["reason"]);

/** The review with frictions and how it felt in the pile: two in the reader's thread, one in auth's, and how they came in its conversation. */
function piling(draft: Draft = EMPTY): Laid {
    const threads = threading();
    // Auth read before, so its conversation shows whole.
    const read = { ...AUTH, pile: [81], mark: { key: { node: 303 }, up_to: "40", at: AT } } as ThreadRead;
    const reads = threads.read.threads.map((each) => (each.thread.number === 302 ? { ...each, pile: [80, 82] } : each.thread.number === 303 ? read : each));
    const auth = shown(
        read,
        [
            { spot: { node: 70 }, came: AT, member: true, new: true },
            { spot: { node: 81 }, came: AT, member: true },
            { spot: { node: 80 }, came: AT, member: true, moved: true },
        ] as unknown as ThreadShown["entries"],
        [LATE, FELT, FRICTION],
    );
    // Its whole conversation read, as the operator opened it in open.
    return laid([QUESTION, LATE, FRICTION, FELT, UNTITLED], [LEAD], banner, header, draft, NOTHING, [], new Map(), called, {
        threads: { ...threads, read: { ...threads.read, threads: reads }, shown: new Map([...threads.shown, [303, auth]]), whole: new Map([[303, auth]]) },
    });
}

/** Return what `name`, a verb's, reaches at `at` in `out`. */
function reaching(out: Laid, at: number, name: string) {
    const verb = adopted().verbs.find((each) => each.name === name);
    expect(verb).toBeDefined();
    return verb === undefined ? null : reachOf(out, at, verb, { called });
}

describe("the pile to read", () => {
    it("lists each thread's frictions and how it felt under a line naming it, each by its title, its text folded under it", () => {
        const out = piling();
        const text = lines(out);
        const at = text.indexOf("to read · 2 frictions, 1 how it felt");
        expect(text.slice(at, at + 12)).toEqual([
            "to read · 2 frictions, 1 how it felt",
            "@reader · The reader · 2 frictions",
            "friction @80 · s1/a1 · the gate hangs",
            "  The gate hung for four minutes.",
            "  It printed nothing.",
            "friction @82 · s1/a1 · Typing lags in long comments.",
            "  Typing lags in long comments.",
            "@auth · The auth · 1 how it felt",
            "how it felt @81 · s1 · Steady.",
            "  Steady.",
            "  The brief named every file.",
            "settled · 1 settled · 0 declined",
        ]);
        expect(out.pile.map((run) => [run.thread.thread.name, run.entries.map((each) => each.item.number)])).toEqual([
            ["reader", [80, 82]],
            ["auth", [81]],
        ]);
        const folds = out.outer.filter((each) => each.kind === "pile");
        expect(folds.map((each) => [each.of, each.closed, out.text.slice(each.summary.from, each.summary.to)])).toEqual([
            ["pile 80", true, "friction @80 · s1/a1 · the gate hangs"],
            ["pile 82", true, "friction @82 · s1/a1 · Typing lags in long comments."],
            ["pile 81", true, "how it felt @81 · s1 · Steady."],
        ]);
        expect(out.sections.find((each) => each.name === "to read")?.fold?.closed).toBe(true);
    });

    it("titles an item of the pile with none of its own by its text's first sentence, cut at a word", () => {
        expect(pileTitle(FELT)).toBe("Steady.");
        expect(pileTitle(UNTITLED)).toBe("Typing lags in long comments.");
        const long = item(83, WORKER, { reason: "how it felt", text: "word ".repeat(30) } as Item["reason"]);
        expect(pileTitle(long)).toBe(`${"word ".repeat(16).trimEnd()}…`);
    });

    it("folds an item of the pile to its header in its thread's conversation, saying where it's read or where it went", () => {
        const out = piling();
        const headers = out.regions.filter((each) => [80, 81].includes(each.item.number));
        expect(headers.map((each) => [each.item.number, each.folds.find((fold) => fold.kind === "item")?.closed])).toEqual([
            [81, true],
            [80, true],
        ]);
        const said = (number: number) => out.text.slice(out.regions.find((each) => each.item.number === number)?.header.from ?? 0).split("\n")[0];
        // The test's header says only the number; the core's says what the view and the note say, which `laid` gives it.
        const told: string[] = [];
        const marked = { ...AUTH, mark: { key: { node: 303 }, up_to: "40", at: AT } } as ThreadRead;
        laid([FELT], [LEAD], banner, (shownItem, _, words) => {
            told.push(`${shownItem.number}: ${words}`);
            return header(shownItem);
        }, EMPTY, NOTHING, [], new Map(), called, { threads: { ...threading(), read: { ...threading().read, threads: threading().read.threads.map((each) => (each.thread.number === 303 ? marked : each)) }, whole: new Map([[303, shown(marked, [{ spot: { node: 81 }, came: AT, member: true }, { spot: { node: 80 }, came: AT, member: true, moved: true }, { spot: { node: 82 }, came: AT, member: true, went: 302 }] as unknown as ThreadShown["entries"], [FELT, FRICTION, UNTITLED])]]) } });
        // In @auth's whole conversation, beside what waits on the operator and what's new above.
        expect(told.filter((each) => /^8\d: /.test(each)).map((each) => each.replace(/^(\d+): .*? · /, "$1: "))).toEqual(["81: in the pile to read", "80: moved here", "82: moved to @reader"]);
        expect(said(81)).toBe("── @81 ──");
    });

    it("marks an item of the pile read with Space d, a thread's there each of its, and moves them with Space s into a thread named", () => {
        const out = piling();
        const entry = out.text.indexOf("friction @80");
        const run = out.text.indexOf("@reader · The reader · 2 frictions");
        expect(reaching(out, entry, "done")).toMatchObject({ on: "friction @80", says: "mark it read", acts: [{ kind: "item", number: 80, list: "done" }] });
        expect(reaching(out, run, "done")).toMatchObject({ on: "@reader's pile", says: "mark its 2 read", acts: [{ number: 80 }, { number: 82 }] });
        const moving = reaching(out, run, "send");
        expect(moving).toMatchObject({ says: "move its 2 into a thread, which you name", acts: [{ kind: "move", number: 80, block: "pile 80" }, { kind: "move", number: 82 }] });
        const acts = (moving !== null && moving.on !== null ? moving.acts : []).filter((each): each is Extract<Act, { kind: "move" }> => each.kind === "move");
        // Nothing's marked until the operator names where they go; then each says it, read no longer marked.
        const read = marking(EMPTY, [{ kind: "item", number: 80, list: "done" }], "done");
        expect(marking(read, acts, "send")).toBe(read);
        const moved = movedInto(read, acts, { thread: 303, name: "auth" });
        expect(moved.done).toEqual([]);
        expect((moved.marks ?? []).map((each) => [each.action, each.block, each.says, each.argument])).toEqual([
            [MOVE, "pile 80", "into @auth", { numbers: [80], repository: REPOSITORY, thread: 303, title: null }],
            [MOVE, "pile 82", "into @auth", { numbers: [82], repository: REPOSITORY, thread: 303, title: null }],
        ]);
        expect(acts.every((each) => isMarked(moved, each, "send"))).toBe(true);
        // Moved again, into a new thread, each mark replaced; Space s again takes them off; read, one is no longer moved.
        const opened = movedInto(moved, acts.slice(0, 1), { title: "The gate hangs" });
        expect((opened.marks ?? []).map((each) => each.says)).toEqual(["into @auth", "into a new thread: The gate hangs"]);
        expect(marking(moved, acts, "send").marks).toEqual([]);
        expect((listed(moved, 82, "done").marks ?? []).map((each) => each.block)).toEqual(["pile 80"]);
        const shownMoved = lines(piling(moved));
        expect(shownMoved).toContain("friction @80 · s1/a1 · the gate hangs");
    });

    it("selects the pile's entries fold-wise, Space d reading each and Space s moving each", () => {
        const out = piling();
        const folds = out.outer.filter((each) => each.kind === "pile");
        const verbs = adopted().verbs;
        const done = verbs.find((each) => each.name === "done");
        const send = verbs.find((each) => each.name === "send");
        expect(done === undefined ? [] : reachedIn(out, folds, done, { called })).toEqual([
            { kind: "item", number: 80, list: "done" },
            { kind: "item", number: 82, list: "done" },
            { kind: "item", number: 81, list: "done" },
        ]);
        expect((send === undefined ? [] : reachedIn(out, folds, send, { called })).map((each) => (each.kind === "move" ? each.number : null))).toEqual([80, 82, 81]);
    });

    it("says what's moved on the line under the review, and lists the pile in the overview, what the draft does with each", () => {
        const out = piling();
        const acts: Extract<Act, { kind: "move" }>[] = [80, 82].map((number) => ({ kind: "move", number, repository: REPOSITORY, block: `pile ${number}` }));
        const draft = listed(movedInto(EMPTY, acts, { title: "The gate hangs" }), 81, "done");
        const naming = { called: (party: Item["sender"]) => (party.party === "operator" ? "you" : called(party)), named: () => "", holder: () => null, checks: new Set<number>() };
        expect(toSend(draft, [FELT], naming).map(partSaid)).toEqual(["read @81", "2 moved into a new thread: The gate hangs"]);
        const rows = outlineOf(out, { draft, seeing: UNSEEN, states: new Map(), called });
        const at = rows.findIndex((each) => each.key === "section to read");
        expect(rows.slice(at, at + 6).map((each) => [each.text, each.marks, each.draft])).toEqual([
            ["to read", [], []],
            ["@reader", ["news"], []],
            ["@80 friction", [], ["move"]],
            ["@82 friction", [], ["move"]],
            ["@auth", ["news"], []],
            ["@81 how it felt", [], ["read"]],
        ]);
        expect(rows[at + 6]?.text).toBe("settled");
    });
});
