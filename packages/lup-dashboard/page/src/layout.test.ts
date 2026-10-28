import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import { cursorRow, itemStanding, outlineOf, type Reading } from "./outline";
import { EMPTY, barsOf, laid, nested, ownerOf, rowLabel, whose, UNREAD, type AgentDrawers, type Around, type Conversation, type Head, type Item, type Placed } from "./review";
import { around, linesOver, pinned, stickies, type Geometry } from "./stack";
import { STANDING } from "./fixtures/looks";
import { merged } from "./looks";
import { blockId, instanceOf, type Blocks, type Remote } from "./views";

const AT = "2026-10-17T12:00:00Z";
const WAITING: Item["rank"] = { name: "waiting on you", order: 0, notifies: true };
const NEWS: Item["rank"] = { name: "news", order: 1, notifies: false };

function from(session: string, agent: string | null = null): Conversation {
    return { party: "conversation", repository: "/r/lup.git", runtime: "claude", session, agent };
}

function note(number: number, sender: Conversation, rank: Item["rank"] = NEWS): Item {
    return {
        number,
        reason: { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: `Note ${number}.\nSecond line.` },
        sender,
        recipient: { party: "operator" },
        replies: [],
        citations: [],
        edits: [],
        quiet: false,
        made: AT,
        state: { state: "waiting" },
        rank,
    };
}

const NOTHING: Around = { contexts: new Map(), files: new Map(), answers: [], commented: [] };
const header = (item: Item, parked: boolean) => `── @${item.number} note${parked ? " · later" : ""} ──`;
const banner = (head: Head) => {
    const party = "item" in head ? head.item.sender : head.conversation;
    return `━━ ${party.party === "conversation" ? (party.agent ?? party.session) : "lup"} ━━`;
};

const PARENT = from("s1");
const CHILD = from("s1", "a1");
const GRANDCHILD = from("s1", "a2");
const OTHER = from("s2");
/** The grandchild's parent, `a1`, as the host's tree has it; and `a1`'s, the session. */
const PARENTS = new Map([
    [whose(CHILD), whose(PARENT)],
    [whose(GRANDCHILD), whose(CHILD)],
]);
const TASKED: AgentDrawers = {
    ...UNREAD,
    tasks: [
        { id: "1", subject: "Read", status: "completed", active: null },
        { id: "2", subject: "Write", status: "in_progress", active: "Writing" },
    ],
};
/** The parent's conversation, as `Transcripts` answers it: the operator's words, and the agent's. */
const TALKED: Remote = new Map([
    [
        instanceOf("/r/lup.git", "transcripts", "conversation", { runtime: "claude", session: "s1", agent: null }),
        {
            summary: [{ text: "conversation · 2 steps", tone: "plain" }],
            waiting: false,
            count: 0,
            offers: [],
            blocks: [
                { block: "line", id: "step 0", version: null, offers: [], spans: [{ text: "you: Go.", tone: "operator" }] },
                { block: "markdown", id: "step 1", version: null, offers: [], text: "Going.", tone: "plain" },
            ],
        },
    ],
]);

describe("subagents nested under their parent", () => {
    it("lays each subagent's group under its nearest forebear with a group, after its items and drawers, set in by how deep it is", () => {
        const items = [note(1, CHILD), note(2, OTHER), note(3, GRANDCHILD), note(4, PARENT)];
        const drawers = new Map([[whose(PARENT), TASKED]]);
        const plain = laid(items, [PARENT], banner, header, EMPTY, NOTHING, [], drawers, undefined, { remote: TALKED });
        expect(plain.groups.map((each) => [banner(each.head), each.depth])).toEqual([
            ["━━ a1 ━━", 0],
            ["━━ s2 ━━", 0],
            ["━━ a2 ━━", 0],
            ["━━ s1 ━━", 0],
        ]);
        const out = laid(items, [PARENT], banner, header, EMPTY, NOTHING, [], drawers, undefined, { parents: PARENTS, remote: TALKED });
        expect(out.groups.map((each) => [banner(each.head), each.depth])).toEqual([
            ["━━ s2 ━━", 0],
            ["━━ s1 ━━", 0],
            ["━━ a1 ━━", 1],
            ["━━ a2 ━━", 2],
        ]);
        // After the parent's items and its drawers.
        expect(out.text.indexOf("━━ a1")).toBeGreaterThan(out.text.indexOf("conversation · 2 steps"));
        // A subagent whose parent has no group goes under its grandparent's.
        const skipped = nested(
            [
                { key: whose(GRANDCHILD), conversation: GRANDCHILD, head: { conversation: GRANDCHILD }, items: [] },
                { key: whose(PARENT), conversation: PARENT, head: { conversation: PARENT }, items: [] },
            ],
            PARENTS,
        );
        expect(skipped.map((each) => [each.group.key, each.depth])).toEqual([
            [whose(PARENT), 0],
            [whose(GRANDCHILD), 1],
        ]);
    });
});

describe("groups folding whole", () => {
    it("folds each group under its banner up to the next as deep or shallower, a subagent's inside its parent's", () => {
        const items = [note(1, CHILD), note(4, PARENT), note(2, OTHER)];
        const out = laid(items, [PARENT], banner, header, EMPTY, NOTHING, [], new Map(), undefined, { parents: PARENTS });
        const folds = out.groups.map((each) => each.fold);
        expect(folds.map((each) => [each?.kind, each?.of, each?.closed])).toEqual([
            ["group", `group now ${whose(OTHER)}`, false],
            ["group", `group now ${whose(PARENT)}`, false],
            ["group", `group now ${whose(CHILD)}`, false],
        ]);
        const [, parent, child] = folds;
        // The parent's holds its subagent's, both ending where the text does.
        expect(parent!.from).toBeLessThan(child!.from);
        expect(parent!.to).toBe(child!.to);
        expect(out.text.slice(folds[0]!.summary.from, folds[0]!.summary.to)).toBe("━━ s2 ━━");
    });
});

describe("the review's tree", () => {
    it("keeps each part laid out by an id that stays across layouts: a group, its banner, a drawer, an item, a view of either, its blocks", () => {
        const drawers = new Map([[whose(PARENT), TASKED]]);
        const out = laid([note(4, PARENT), note(1, CHILD)], [PARENT], banner, header, EMPTY, NOTHING, [], drawers, undefined, { parents: PARENTS, remote: TALKED });
        const ids = (parts: Placed[]): unknown[] => parts.map((each) => (each.children.length === 0 ? `${each.kind} ${each.id}` : [`${each.kind} ${each.id}`, ids(each.children)]));
        const tasks = instanceOf("/r/lup.git", "adapters", "tasks", { runtime: "claude", session: "s1", agent: null });
        const conversation = instanceOf("/r/lup.git", "transcripts", "conversation", { runtime: "claude", session: "s1", agent: null });
        const body = (number: number) => instanceOf("/r/lup.git", "inbox", "message", { number });
        // The subagent's group came first, its item the earlier, but nests in its parent's.
        expect(ids(out.nodes)).toEqual([
            [
                `group group now ${whose(PARENT)}`,
                [
                    `banner group now ${whose(PARENT)} banner`,
                    [`view ${tasks}`, [`block ${blockId(tasks, "task 1")}`, `block ${blockId(tasks, "task 2")}`]],
                    [`view ${conversation}`, [`block ${blockId(conversation, "step 0")}`, `block ${blockId(conversation, "step 1")}`]],
                    [`item item 4`, [`header item 4 header`, [`view ${body(4)}`, [`block ${blockId(body(4), "text")}`]]]],
                    [`group group now ${whose(CHILD)}`, [`banner group now ${whose(CHILD)} banner`, [`item item 1`, [`header item 1 header`, [`view ${body(1)}`, [`block ${blockId(body(1), "text")}`]]]]]],
                ],
            ],
        ]);
        // Each part where it's laid out, from its first line to its last.
        const [group] = out.nodes;
        const item = group!.children.find((each) => each.id === "item 4")!;
        expect(out.text.slice(item.header.from, item.header.to)).toBe("── @4 note ──");
        expect(out.text.slice(item.from, item.to + 1)).toBe("── @4 note ──\nNote 4.\nSecond line.\n");
        // Laid out again, as a comment's key is typed, each part keeps its id.
        const again = laid([note(4, PARENT), note(1, CHILD)], [PARENT], banner, header, EMPTY, NOTHING, [], drawers, undefined, { parents: PARENTS, remote: TALKED });
        expect(ids(again.nodes)).toEqual(ids(out.nodes));
    });
});

describe("a drawer its module answers itself", () => {
    // A repository whose module places a drawer of its own, which the page lays out from what the host answers.
    const notes = { module: "notes", view: "notes", place: { under: "agent" as const, letter: "n", called: "the notes", colour: "ok" as const } };
    const looks = merged({ "/r/lup.git": { ...STANDING, drawers: [...(STANDING.drawers ?? []), notes], tones: [...(STANDING.tones ?? []), { name: "warm", colour: "orange" }] } }, STANDING);
    const argument = { runtime: "claude", session: "s1", agent: null };
    const id = instanceOf("/r/lup.git", "notes", "notes", argument);
    const more = { runtime: "claude", session: "s1", agent: null, page: 2 };
    const answer: Blocks = {
        summary: [{ text: "notes · 2", tone: "plain" }],
        waiting: true,
        count: 2,
        offers: [],
        blocks: [
            { block: "line", id: "1", version: null, offers: [], spans: [{ text: "warm ", tone: "warm" }, { text: "words", tone: "plain" }] },
            { block: "fold", id: "older", version: null, offers: [], kind: "notes", summary: [{ text: "older notes", tone: "muted" }], open: false, barred: false, content: { view: "older", argument: more } },
        ],
    };
    const drawers = new Map([[whose(PARENT), TASKED]]);

    it("is drawn from what the host answered of it, its spans in their tones, a fold read as it opens saying so until it is", () => {
        const out = laid([], [PARENT], banner, header, EMPTY, NOTHING, [], drawers, undefined, { looks, remote: new Map([...TALKED, [id, answer]]) });
        const drawer = out.drawers.find((each) => each.kind === "notes")!;
        expect(out.text.slice(drawer.header.from)).toBe("notes · 2\nwarm words\nolder notes\nreading…\n\n");
        expect(drawer.waiting).toBe(true);
        expect(drawer.toned.map((each) => [out.text.slice(each.from, each.to), each.tone])).toEqual([
            ["warm ", "warm"],
            ["words", "plain"],
            ["older notes", "muted"],
        ]);
        expect([...drawer.loads]).toEqual([["older", { repository: "/r/lup.git", module: "notes", view: "older", argument: more }]]);
        expect(drawer.folds.map((each) => [each.kind, each.name, each.closed, each.unread ?? false])).toEqual([
            ["notes", "older", true, true],
            ["notes", "", true, false],
        ]);
        // Read, the fold holds what its view answered.
        const older: Blocks = { summary: [], waiting: false, count: 0, offers: [], blocks: [{ block: "line", id: "o1", version: null, offers: [], spans: [{ text: "an old note", tone: "plain" }] }] };
        const read = laid([], [PARENT], banner, header, EMPTY, NOTHING, [], drawers, undefined, {
            looks,
            remote: new Map([
                [id, answer],
                [instanceOf("/r/lup.git", "notes", "older", more), older],
            ]),
        });
        expect(read.text).toContain("older notes\nan old note\n");
        // Not answered yet, it isn't shown, the conversation among them; where the page lays it out itself, its own drawers'
        // toned spans aren't marked.
        expect(laid([], [PARENT], banner, header, EMPTY, NOTHING, [], drawers, undefined, { looks }).drawers.map((each) => each.kind)).toEqual(["tasks"]);
        expect(out.drawers.find((each) => each.kind === "tasks")?.toned).toEqual([]);
    });
});

describe("what a fold of a module's view sets off", () => {
    it("is set in under its summary line by how many such folds it's in, the innermost's bar beside it", () => {
        const id = instanceOf("/r/lup.git", "transcripts", "conversation", { runtime: "claude", session: "s1", agent: null });
        const line = (key: string, text: string) => ({ block: "line" as const, id: key, version: null, offers: [], spans: [{ text, tone: "plain" }] });
        const talked: Blocks = {
            summary: [{ text: "conversation · 3 steps", tone: "plain" }],
            waiting: false,
            count: 0,
            offers: [],
            blocks: [
                {
                    block: "fold",
                    id: "calls 1",
                    version: null,
                    offers: [],
                    kind: "calls",
                    summary: [{ text: "· called Bash x2", tone: "run" }],
                    open: true,
                    barred: true,
                    content: [
                        { block: "fold", id: "call b1", version: null, offers: [], kind: "call", summary: [{ text: "· Bash", tone: "call" }], open: true, barred: true, content: [line("input b1", "input:")] },
                        line("step 2", "· Bash"),
                    ],
                },
                line("step 3", "Done."),
            ],
        };
        const out = laid([], [PARENT], banner, header, EMPTY, NOTHING, [], new Map([[whose(PARENT), TASKED]]), undefined, { remote: new Map([[id, talked]]) });
        const drawer = out.drawers.find((each) => each.kind === "conversation")!;
        expect(drawer.bars.map((each) => [out.text.slice(each.from, each.to), each.kind])).toEqual([
            ["input:", "call"],
            ["· Bash\ninput:\n· Bash", "calls"],
        ]);
        const classes = barsOf(out.text, drawer.bars);
        const at = (text: string, from = 0) => out.text.indexOf(text, from);
        expect([...classes].map(([from, each]) => [out.text.slice(from, out.text.indexOf("\n", from)), each])).toEqual([
            ["· Bash", "bar-1 barred-calls"],
            ["input:", "bar-2 barred-call"],
            ["· Bash", "bar-1 barred-calls"],
        ]);
        expect(classes.has(at("Done."))).toBe(false);
    });
});

describe("the drawers under the banner", () => {
    const drawers = new Map([[whose(PARENT), TASKED]]);
    const tasks = ownerOf({ drawer: "tasks", conversation: PARENT });

    it("lays each drawer under the banner, one under the other, a short label folding what it holds, the items after them", () => {
        const out = laid([note(4, PARENT)], [PARENT], banner, header, EMPTY, NOTHING, [], drawers, undefined, { remote: TALKED });
        expect(out.text.split("\n").slice(0, 4)).toEqual(["━━ s1 ━━", "tasks 1/2", "✓ Read", "▶ Writing"]);
        // No line between them, one after the last.
        expect(out.text).toContain("▶ Writing\nconversation · 2 steps\n");
        expect(out.text).toContain("\n\n── @4 note ──");
        expect(out.drawers.map((each) => [each.kind, each.folds.at(-1)?.closed])).toEqual([
            ["tasks", true],
            ["conversation", true],
        ]);
        expect(out.drawers.map((each) => each.waiting)).toEqual([false, false]);
        const [group] = stickies(out);
        expect(group!.children.map((each) => each.kind)).toEqual(["drawer", "drawer", "item"]);
        // Left out where there's nothing for one to hold.
        expect(laid([note(4, PARENT)], [PARENT], banner, header, EMPTY, NOTHING, [], new Map([[whose(PARENT), UNREAD]])).text.split("\n").slice(0, 2)).toEqual(["━━ s1 ━━", "── @4 note ──"]);
    });

    it("says each label short, what waits in \"since you approved\" marking it, none for a drawer with nothing in it", () => {
        expect(rowLabel("tasks", UNREAD)).toBeNull();
        // A drawer its module answers says its own label: the page has none of its.
        expect(rowLabel("conversation", TASKED)).toBeNull();
        const since: AgentDrawers = {
            ...UNREAD,
            since: { kind: "policy-since", worktree: "/w", branch: "feat", version: "v", same: false, files: [{ path: "a.py", version: "a1", flags: [], reviewed: AT }] },
        };
        expect(rowLabel("since", since)).toEqual({ text: "since you approved · 1 reviewed", waiting: false });
    });
});

/** A view where each line is 10 pixels and nothing folds, its top at `top`. */
function geometry(text: string, top: number): Geometry {
    const starts = [0];
    for (let at = 0; at < text.length; at++) {
        if (text[at] === "\n") {
            starts.push(at + 1);
        }
    }
    const lineOf = (position: number) => {
        let line = 0;
        while (line + 1 < starts.length && (starts[line + 1] ?? Infinity) <= position) {
            line += 1;
        }
        return line;
    };
    return {
        top,
        lineHeight: 10,
        block: (position) => ({ top: lineOf(position) * 10, bottom: lineOf(position) * 10 + 10 }),
        at: (height) => starts[Math.min(Math.floor(height / 10), starts.length - 1)] ?? 0,
    };
}

describe("the header stack", () => {
    const items = [note(1, PARENT), note(2, PARENT), note(3, OTHER)];
    const out = laid(items, [], banner, header, EMPTY, NOTHING);
    const roots = stickies(out);
    const shown = (top: number) => pinned(roots, geometry(out.text, top)).map((each) => `${each.offset} ${out.text.slice(each.sticky.header.from, each.sticky.header.to)}`);

    it("pins the headers of the scopes the top of the view is inside once their own lines are scrolled off, the next pushing each up as its scope ends", () => {
        // ━━ s1 ━━ / ── @1 / Note 1. / Second line. / (blank) / ── @2 / Note 2. / Second line. / (blank) / ━━ s2 ━━ …
        expect(shown(0)).toEqual([]);
        // The banner half scrolled off is pinned, and so the item's header it then half covers.
        expect(shown(5)).toEqual(["0 ━━ s1 ━━", "10 ── @1 note ──"]);
        expect(shown(15)).toEqual(["0 ━━ s1 ━━", "10 ── @1 note ──"]);
        // @1's last line, the blank one, ends at 50: its header is pushed up as @2's comes under the stack.
        expect(shown(35)).toEqual(["0 ━━ s1 ━━", "5 ── @1 note ──"]);
        // Once it's wholly under the banner's, it's gone.
        expect(shown(40)).toEqual(["0 ━━ s1 ━━"]);
        expect(shown(45)).toEqual(["0 ━━ s1 ━━", "10 ── @2 note ──"]);
        // The group pushed up by the next group's banner, its item gone once what's under the stack is past it.
        expect(shown(75)).toEqual(["0 ━━ s1 ━━", "5 ── @2 note ──"]);
        expect(shown(85)).toEqual(["-5 ━━ s1 ━━"]);
        expect(shown(91)).toEqual(["0 ━━ s2 ━━", "10 ── @3 note ──"]);
    });

    it("pins a subagent's banner under its parent's, then its item's header", () => {
        const nestedOut = laid([note(1, CHILD), note(4, PARENT)], [PARENT, CHILD], banner, header, EMPTY, NOTHING, [], new Map(), undefined, { parents: PARENTS });
        const nestedRoots = stickies(nestedOut);
        const deep = nestedOut.text.indexOf("Second line.", nestedOut.text.indexOf("@1"));
        const lines = nestedOut.text.slice(0, deep).split("\n").length - 1;
        // The line under the stack is @1's second line: the parent's banner, the subagent's, @1's header.
        const found = pinned(nestedRoots, geometry(nestedOut.text, lines * 10 - 30));
        expect(found.map((each) => nestedOut.text.slice(each.sticky.header.from, each.sticky.header.to))).toEqual(["━━ s1 ━━", "━━ a1 ━━", "── @1 note ──"]);
        expect(linesOver(nestedRoots, deep, false)).toBe(3);
        expect(linesOver(nestedRoots, deep, true)).toBe(2);
    });

    it("keeps the cursor's line clear of what it pins over it, two slots on a narrow screen", () => {
        const at = out.text.indexOf("Second line.", out.text.indexOf("@2"));
        expect(around(roots, at).map((each) => each.kind)).toEqual(["group", "item"]);
        expect(linesOver(roots, at, false)).toBe(2);
        expect(linesOver(roots, out.text.indexOf("── @2"), false)).toBe(1);
        expect(linesOver(roots, 0, false)).toBe(0);
    });
});

describe("the overview", () => {
    const items = [note(1, CHILD, WAITING), note(2, OTHER), note(4, PARENT)];
    const drawers = new Map([[whose(PARENT), TASKED]]);
    const reading: Reading = {
        draft: { ...EMPTY, done: [2], comments: [{ id: "why", item: 1, text: "Why?" }] },
        reviewed: null,
        states: new Map([[whose(PARENT), "calling"]]),
        called: (party) => (party.agent === null ? party.session : `${party.session}/${party.agent}`),
    };
    const said = (rows: ReturnType<typeof outlineOf>) =>
        rows.map((each) => `${"  ".repeat(each.depth)}${each.text} [${each.marks.join(",")}]${each.draft.length === 0 ? "" : ` {${each.draft.join(",")}}`}`);

    it("lists each agent and its items in the review's own order, nested as the review nests them, each marked", () => {
        const out = laid(items, [PARENT], banner, header, EMPTY, NOTHING, [], drawers, undefined, { parents: PARENTS, remote: TALKED });
        const rows = outlineOf(out, reading);
        // How each stands, then, apart, what the draft does with it on the next Ctrl+Enter.
        expect(said(rows)).toEqual([
            "lup []",
            "  s2 [ended]",
            "    @2 note [] {read}",
            "  s1 [calling]",
            "    @4 note [news]",
            "    a1 [ended]",
            "      @1 note [waiting] {comment}",
        ]);
        // As the groups are laid out, never another order.
        expect(rows.filter((each) => each.kind === "agent").map((each) => each.from)).toEqual(out.groups.map((each) => each.banner.from));
        // The cursor's entry is the deepest holding it.
        expect(cursorRow(rows, out.text.indexOf("Note 1."))?.text).toBe("@1 note");
        expect(cursorRow(rows, out.text.indexOf("━━ s1"))?.text).toBe("s1");
        expect(itemStanding(out.regions.find((each) => each.item.number === 1)!, { ...EMPTY, parked: [1], comments: [{ id: "x", item: 1, text: "x" }] }, null)).toEqual({ marks: ["parked"], draft: [], fresh: false });
    });

    it("follows the review where it doesn't nest, a subagent's group where its first item put it", () => {
        const out = laid(items, [PARENT], banner, header, EMPTY, NOTHING, [], drawers, undefined, { remote: TALKED });
        expect(said(outlineOf(out, reading))).toEqual([
            "lup []",
            "  s1/a1 [ended]",
            "    @1 note [waiting] {comment}",
            "  s2 [ended]",
            "    @2 note [] {read}",
            "  s1 [calling]",
            "    @4 note [news]",
        ]);
    });
});
