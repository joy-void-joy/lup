import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import type { ChangedFile } from "./code";
import type { components } from "./generated/api";
import { blockId, canonical, instanceOf, whose, type AgentDrawers, type Answered, type Running, type Shown } from "./views";
import { producerOf } from "./views/index";

type Item = components["schemas"]["Item"];
type Conversation = components["schemas"]["Conversation"];
type Since = components["schemas"]["Since"];

/**
 * What a fixture gives a view, as JSON, so its module's Python, once it answers the view itself, is given the same:
 * the items waiting, each item's files as the host answered them, each agent's data, each conversation running, and
 * each conversation's path as the operator reads it named.
 */
interface Given {
    items?: Item[];
    files?: Record<string, Answered<ChangedFile[]>>;
    drawers?: Record<string, Partial<AgentDrawers>>;
    running?: Record<string, Running>;
    paths?: Record<string, string>;
}

/** One case of a view's: what it's named, of which repository, what it's given, and what it answers. */
interface Case {
    name: string;
    repository: string;
    argument: unknown;
    given: Given;
}

/** Return what the page has read, as `given` says it. */
function shownOf(given: Given): Shown {
    const paths = new Map(Object.entries(given.paths ?? {}));
    return {
        items: new Map((given.items ?? []).map((each) => [each.number, each])),
        beyond: { contexts: new Map(), files: new Map(Object.entries(given.files ?? {}).map(([number, each]) => [Number(number), each])) },
        drawers: new Map(
            Object.entries(given.drawers ?? {}).map(([key, each]) => [
                key,
                { tasks: [], usage: null, since: null, ...each },
            ]),
        ),
        running: new Map(Object.entries(given.running ?? {})),
        called: (party) => paths.get(whose(party)) ?? party.agent ?? party.session,
    };
}

const AT = "2026-10-27T09:00:00Z";
const REPOSITORY = "/r/lup.git";
const PARSER: Conversation = { party: "conversation", repository: REPOSITORY, runtime: "claude", session: "s1", agent: "a1" };
const AGENT = { runtime: "claude", session: "s1", agent: "a1" };
const WAITING: Item["rank"] = { name: "waiting on you", order: 0, notifies: true };
const NEWS: Item["rank"] = { name: "news", order: 1, notifies: false };

function item(number: number, reason: Item["reason"], rank: Item["rank"] = NEWS, sender: Item["sender"] = PARSER): Item {
    return { number, reason, sender, recipient: { party: "operator" }, replies: [], citations: [], edits: [], quiet: false, made: AT, state: { state: "waiting" }, rank };
}

const text = (value: string) => ({ kind: "text" as const, text: value });

/** A module's file with an `ignore` the judge holds, a finding it tells, and a test beside it: what a held change and an approval change. */
const FILES: ChangedFile[] = [
    {
        path: "reader.py",
        before: text("import json\n\n\ndef read(path):\n    return path.read_text()\n"),
        after: text("import json\n\n\ndef read(path):\n    # lup: ignore(\"x\", why=\"y\")\n    return path.read_text().split(\"\\n\")\n"),
        reading: {
            role: "production",
            asks: [{ name: "ignore", taken: "held", line: 5, side: "after" }],
            findings: [{ rule: "string-split", message: "splits a string\nto parse it", steer: "", start: 6, end: 6, taken: "told" }],
        },
    },
    { path: "test_reader.py", before: null, after: text("def test_read():\n    assert True\n"), reading: { role: "test", asks: [], findings: [] } },
    { path: "logo.png", before: null, after: { kind: "binary", size: 1150 } },
];

const HELD = item(55, { reason: "held", text: "Let the change to 2 files land?", summary: "reader.py adds an ignore", worktree: "/w/feat", landing: null }, WAITING);
const LANDING = item(
    56,
    { reason: "held", text: "Land feat?", summary: "landing waits on reader.py", worktree: "/w/feat", landing: { onto: "dev", tip: "c0ffee", path: "reader.py", branches: ["feat"], flags: [59] } },
    WAITING,
);
const FLAGGED = item(
    59,
    { reason: "flagged", text: "reader.py landed, flagged.", summary: "reader.py adds the class `Reader`", worktree: "/w/feat", path: "reader.py", writes: 1 },
    { name: "flag", order: 2, notifies: false },
);
const APPROVAL = item(
    54,
    { reason: "approval", repository: REPOSITORY, fingerprint: "4750cf6", text: "Approve the host zone of lup at 4750cf6?", summary: "\u001b[32m reader.py | 2 ++\u001b[m", first: false, typing: false },
    WAITING,
    { party: "operator" },
);
const FIRST = item(
    64,
    { reason: "approval", repository: REPOSITORY, fingerprint: "a1b2c3d", text: "Approve lup as it is?", summary: " 3 files", first: true, typing: true },
    WAITING,
    { party: "operator" },
);

const SINCE: Since = {
    kind: "policy-since",
    worktree: "/w/feat",
    branch: "feat",
    version: "v3",
    same: false,
    files: [
        { path: "reader.py", version: "b1", flags: [59], file: { ...FILES[0]!, reading: { role: "production", asks: [{ name: "new-file", taken: "flagged", side: "after" }], findings: [] }, before: null } },
        { path: "test_reader.py", version: "b2", flags: [], file: FILES[1]! },
        { path: "clock.py", version: "b3", flags: [60], since: 12 },
        { path: "notes.md", version: "b4", flags: [], reviewed: AT },
    ],
};

/** The cases each of the page's own views is pinned by, by its module and its name. */
const CASES: Record<string, Case[]> = {
    "core approval": [
        { name: "an approval of a change, its files read", repository: REPOSITORY, argument: { number: 54 }, given: { items: [APPROVAL], files: { "54": { shown: FILES } } } },
        { name: "a first approval, its files folded, its types still being read", repository: REPOSITORY, argument: { number: 64 }, given: { items: [FIRST], files: { "64": { shown: FILES.slice(0, 2) } } } },
        { name: "an approval whose files the host refused", repository: REPOSITORY, argument: { number: 54 }, given: { items: [APPROVAL], files: { "54": { refused: "the copy is gone" } } } },
    ],
    "judge held": [
        { name: "a held change, its files", repository: REPOSITORY, argument: { number: 55 }, given: { items: [HELD], files: { "55": { shown: FILES.slice(0, 1) } } } },
        { name: "a hold at landing, its files not read yet", repository: REPOSITORY, argument: { number: 56 }, given: { items: [LANDING] } },
    ],
    "judge flagged": [{ name: "a write that landed flagged", repository: REPOSITORY, argument: { number: 59 }, given: { items: [FLAGGED], files: { "59": { shown: FILES.slice(0, 1) } } } }],
    "judge since": [
        { name: "a branch's files since the operator approved it", repository: REPOSITORY, argument: AGENT, given: { drawers: { [whose(PARSER)]: { since: SINCE } } } },
        { name: "a branch that changed nothing", repository: REPOSITORY, argument: AGENT, given: { drawers: { [whose(PARSER)]: { since: { ...SINCE, files: [] } } } } },
    ],
    "judge banner": [
        { name: "an agent whose flagged writes are held", repository: REPOSITORY, argument: AGENT, given: { running: { [whose(PARSER)]: { launch: "l1", holding: true } } } },
        { name: "an agent whose flagged writes land", repository: REPOSITORY, argument: AGENT, given: { running: { [whose(PARSER)]: { launch: "l1", holding: false } } } },
    ],
    "inbox message": [
        { name: "a note", repository: REPOSITORY, argument: { number: 62 }, given: { items: [item(62, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "Read the records.\n\nFour kinds." })] } },
        {
            name: "a message to another conversation, named by its path",
            repository: REPOSITORY,
            argument: { number: 65 },
            given: {
                items: [item(65, { reason: "message", passages: [], answers: [], ending: false, kind: "note", text: "Over to you.", to: { ...PARSER, agent: "a2" } })],
                paths: { [whose({ ...PARSER, agent: "a2" })]: "lup-impl/explore-auth" },
            },
        },
        { name: "a turn's end", repository: REPOSITORY, argument: { number: 66 }, given: { items: [item(66, { reason: "message", passages: [], answers: [], ending: true, kind: "note", text: "Done." })] } },
    ],
    "inbox question": [
        {
            name: "a question of numbered decisions with their leans",
            repository: REPOSITORY,
            argument: { number: 51 },
            given: { items: [item(51, { reason: "question", text: "Which parser?", decisions: [{ text: "pydantic", lean: "yes" }, { text: "by hand", lean: "no" }] }, WAITING)] },
        },
    ],
    "inbox friction": [{ name: "a friction", repository: REPOSITORY, argument: { number: 57 }, given: { items: [item(57, { reason: "friction", text: "The gate printed nothing for four minutes." })] } }],
    "inbox how_it_felt": [{ name: "how it felt", repository: REPOSITORY, argument: { number: 58 }, given: { items: [item(58, { reason: "how it felt", text: "Steady." })] } }],
    "inbox stop": [{ name: "a stop by choice", repository: REPOSITORY, argument: { number: 67 }, given: { items: [item(67, { reason: "stop", why: "Nothing more is worth doing." })] } }],
    "adapters tasks": [
        {
            name: "a task list, one in progress",
            repository: REPOSITORY,
            argument: AGENT,
            given: {
                drawers: {
                    [whose(PARSER)]: {
                        tasks: [
                            { id: "1", subject: "Read the records", status: "completed", active: null },
                            { id: "2", subject: "Write the reader", status: "in_progress", active: "Writing the reader" },
                            { id: "3", subject: "Test each kind", status: "pending", active: null },
                        ],
                    },
                },
            },
        },
        { name: "no task list", repository: REPOSITORY, argument: AGENT, given: { drawers: { [whose(PARSER)]: { tasks: [] } } } },
    ],
    "adapters banner": [
        {
            name: "an agent at work, its context measured",
            repository: REPOSITORY,
            argument: AGENT,
            given: { drawers: { [whose(PARSER)]: { tasks: [{ id: "2", subject: "Write the reader", status: "in_progress", active: "Writing the reader" }], usage: { used: 112_000, window: 1_000_000, model: "opus" } } } },
        },
        { name: "an agent whose record says neither", repository: REPOSITORY, argument: AGENT, given: { drawers: { [whose(PARSER)]: {} } } },
    ],
};

describe("the views the page lays out itself", () => {
    for (const [named, cases] of Object.entries(CASES)) {
        const [module = "", view = ""] = named.split(" ");
        it(`answers ${module}'s ${view} as its fixture pins it, for its module's Python to match`, async () => {
            const producer = producerOf(module, view);
            expect(producer).toBeDefined();
            const answered = cases.map((each) => ({ ...each, module, view, answer: producer?.answer(each.argument as never, shownOf(each.given), each.repository)?.blocks ?? null }));
            await expect(`${JSON.stringify(answered, null, 2)}\n`).toMatchFileSnapshot(`./fixtures/views/${module}.${view}.json`);
        });
    }

    it("lays out a summary in the item's header, and its body: its text, each file, what the host refused", () => {
        const approval = producerOf("core", "approval")?.answer({ number: 54 } as never, shownOf(CASES["core approval"]![0]!.given), REPOSITORY)?.blocks;
        expect((approval?.summary ?? []).map((each) => each.text).join("")).toBe("approval · 1 with an ignore · 1 test · 1 unread");
        expect(approval?.blocks.map((each) => each.id)).toEqual(["text", "file reader.py", "file test_reader.py", "file logo.png"]);
        expect(approval?.offers.map((each) => [each.verb, each.action, each.runs])).toEqual([
            ["done", "inbox-answer-approval", "send"],
            ["decline", "inbox-answer-approval", "send"],
        ]);
        const refused = producerOf("core", "approval")?.answer({ number: 54 } as never, shownOf(CASES["core approval"]![2]!.given), REPOSITORY)?.blocks;
        expect(refused?.blocks.at(-1)).toMatchObject({ id: "refused", spans: [{ text: "no files: the copy is gone", tone: "refused" }] });
    });

    it("offers each file of \"since you approved\" to be marked reviewed at its version, and every one not settled as the drawer's own", () => {
        const since = producerOf("judge", "since")?.answer(AGENT as never, shownOf(CASES["judge since"]![0]!.given), REPOSITORY);
        const blocks = since?.blocks;
        expect(blocks?.blocks.map((each) => each.id)).toEqual(["file reader.py", "file test_reader.py", "reviewed clock.py", "reviewed"]);
        expect(blocks?.count).toBe(1);
        expect(blocks?.waiting).toBe(true);
        expect(blocks?.blocks[0]?.offers[0]?.argument).toEqual({ conversation: PARSER, files: [{ path: "reader.py", version: "b1" }] });
        // A file reviewed already, settled under the drawer's last fold, offers nothing, and the drawer whole leaves it out.
        expect(blocks?.offers[0]?.argument).toMatchObject({ files: [{ path: "reader.py" }, { path: "test_reader.py" }, { path: "clock.py" }] });
        const settled = blocks?.blocks.at(-1);
        expect(settled?.block === "fold" && Array.isArray(settled.content) ? settled.content.map((each) => each.offers) : null).toEqual([[]]);
        expect([...(since?.files?.keys() ?? [])]).toEqual(["file reader.py", "file test_reader.py", "reviewed clock.py", "reviewed notes.md"]);
    });
});

describe("what keeps each part of the review", () => {
    it("names a view's instance by its repository, module, view and argument, however the argument was built", () => {
        const one = instanceOf(REPOSITORY, "judge", "since", { runtime: "claude", session: "s1", agent: null });
        const other = instanceOf(REPOSITORY, "judge", "since", { agent: null, session: "s1", runtime: "claude" });
        expect(one).toBe(other);
        expect(one).not.toBe(instanceOf("/r/other.git", "judge", "since", { runtime: "claude", session: "s1", agent: null }));
        expect(blockId(one, "file a.py")).toBe(`${one} file a.py`);
        expect(canonical({ b: [1, { d: 2, c: 3 }], a: null })).toBe('{"a":null,"b":[1,{"c":3,"d":2}]}');
    });
});
