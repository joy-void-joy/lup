import { pythonLanguage } from "@codemirror/lang-python";
import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import { highlighted, languageOf, lines, shown, tally, tokensOf, within, type ChangedFile, type Reading } from "./code";

function text(value: string): ChangedFile["after"] {
    return { kind: "text", text: value };
}

/** Lines `l1` to `l<count>`, each replaced where `changed` says. */
function numbered(count: number, changed: Record<number, string> = {}): string {
    return Array.from({ length: count }, (_, at) => changed[at + 1] ?? `l${at + 1}`).join("\n") + "\n";
}

describe("a changed file's lines", () => {
    it("breaks a text where the editor does, each line where it starts", () => {
        expect(lines("a\r\nb\rc\nd")).toEqual([
            { text: "a", offset: 0 },
            { text: "b", offset: 3 },
            { text: "c", offset: 5 },
            { text: "d", offset: 7 },
        ]);
        expect(lines("a\n")).toEqual([{ text: "a", offset: 0 }]);
        expect(lines("")).toEqual([]);
    });

    it("shows what a file becomes whole, each removed line in place before what replaces it", () => {
        const file: ChangedFile = { path: "a.py", before: text("a\nb\nc\n"), after: text("a\nB\nc\nd\n") };
        const laid = shown(file);
        expect(laid.header).toBe("a.py · changed · +2 −1");
        expect(laid.rows.map((row) => [row.change, row.side, row.number, row.text])).toEqual([
            ["same", "after", 1, "a"],
            ["removed", "before", 2, "b"],
            ["added", "after", 2, "B"],
            ["same", "after", 3, "c"],
            ["added", "after", 4, "d"],
        ]);
        expect(laid.rows.map((row) => row.offset)).toEqual([0, 2, 2, 4, 6]);
        expect(laid.runs).toEqual([]);
    });

    it("folds each run of unchanged lines three lines or more from a change, where it hides two lines or more", () => {
        const file: ChangedFile = {
            path: "a.py",
            before: text(numbered(30)),
            after: text(numbered(30, { 10: "ten", 21: "twenty-one" })),
        };
        const laid = shown(file);
        const run = (index: number) => {
            const each = laid.runs[index]!;
            return [each.summary, laid.rows[each.from]!.text, laid.rows[each.to - 1]!.text];
        };
        expect(laid.runs).toHaveLength(3);
        expect(run(0)).toEqual(["6 unchanged lines, 1–6", "l1", "l6"]);
        expect(run(1)).toEqual(["4 unchanged lines, 14–17", "l14", "l17"]);
        expect(run(2)).toEqual(["6 unchanged lines, 25–30", "l25", "l30"]);
        const near = shown({ ...file, after: text(numbered(30, { 10: "ten", 17: "seventeen" })) });
        expect(near.runs.map((each) => each.summary)).toEqual(["6 unchanged lines, 1–6", "10 unchanged lines, 21–30"]);
    });

    it("says a file created, deleted, unchanged in its lines, or binary, which shows no line", () => {
        expect(shown({ path: "n.md", before: null, after: text("# N\n\nNew.\n") })).toMatchObject({
            header: "n.md · created · 3 lines",
            runs: [],
        });
        const deleted = shown({ path: "o.py", before: text("old\n"), after: null });
        expect(deleted.header).toBe("o.py · deleted · 1 line");
        expect(deleted.rows).toEqual([{ change: "removed", side: "before", number: 1, offset: 0, text: "old" }]);
        const same = shown({ path: "s.py", before: text(numbered(5)), after: text(numbered(5)) });
        expect(same.header).toBe("s.py · changed · no line differs");
        expect(same.runs).toEqual([{ from: 0, to: 5, summary: "5 unchanged lines, 1–5", name: '["","l1"]' }]);
        expect(shown({ path: "i.png", before: null, after: { kind: "binary", size: 1150 } })).toMatchObject({
            header: "i.png · created · binary, not shown · 1,150 bytes",
            rows: [],
            runs: [],
        });
        expect(
            shown({ path: "i.png", before: { kind: "binary", size: 10 }, after: { kind: "binary", size: 12 } }).header,
        ).toBe("i.png · changed · binary, not shown · 10 bytes → 12 bytes");
    });
});

/** A Python module: a function, then a class with a method of `count` lines, the `changed` one of them, then another function. */
function module(count: number, changed: Record<number, string> = {}): string {
    const body = Array.from({ length: count }, (_, at) => `        ${changed[at + 1] ?? `step${at + 1}()`}`);
    return [
        "import os",
        "",
        "",
        "def first():",
        "    a = 1",
        "    return a",
        "",
        "",
        "class Clock:",
        '    """The time."""',
        "",
        "    def sleep(self):",
        ...body,
        "",
        "",
        "def last():",
        "    b = 2",
        "    return b",
    ].join("\n") + "\n";
}

describe("a file's bodies", () => {
    it("reads each function's and class's body from the file's syntax, each named after the bodies it's in", () => {
        const laid = shown({ path: "clock.py", before: null, after: text(module(4)) });
        const rows = (body: { from: number; to: number }) => [laid.rows[body.from]!.text, laid.rows[body.to]!.text];
        expect(laid.bodies.map((each) => [each.names, ...rows(each)])).toEqual([
            [["first"], "def first():", "    return a"],
            [["Clock"], "class Clock:", "        step4()"],
            [["Clock", "sleep"], "    def sleep(self):", "        step4()"],
            [["last"], "def last():", "    return b"],
        ]);
        expect(new Set(laid.bodies.map((each) => each.name)).size).toBe(4);
    });

    it("reads JavaScript's and TypeScript's functions, methods, classes and callbacks, an unnamed one by its first line, a body hiding one line not folding", () => {
        const code = [
            "export function since(then: Date): string {",
            "    const x = 1;",
            "    return `${x}`;",
            "}",
            "class A {",
            "    m(x: number): void {",
            "        go();",
            "        go();",
            "    }",
            "    get y() { return 1; }",
            "}",
            "const f = (a: number) => {",
            "    a += 1;",
            "    return a;",
            "};",
            'describe("x", () => {',
            '    it("y", () => {',
            "        expect(1);",
            "    });",
            "});",
            "const g = () =>",
            "    1;",
        ].join("\n");
        const laid = shown({ path: "a.ts", before: null, after: text(code) });
        expect(laid.bodies.map((each) => each.names)).toEqual([
            ["since"],
            ["A"],
            ["A", "m"],
            ["f"],
            ['describe("x", () => {'],
            ['describe("x", () => {', 'it("y", () => {'],
        ]);
        expect(shown({ path: "a.md", before: null, after: text(code) }).bodies).toEqual([]);
    });

    it("counts a name given twice, so each names one body", () => {
        const code = "def f():\n    a = 1\n    return a\n\n\ndef f():\n    b = 2\n    return b\n";
        const [one, two] = shown({ path: "a.py", before: null, after: text(code) }).bodies;
        expect(one!.names).toEqual(two!.names);
        expect(one!.name).not.toBe(two!.name);
    });

    it("cuts a run where it crosses a body's edge, the line declaring a body around a change kept in view", () => {
        const laid = shown({ path: "clock.py", before: text(module(30)), after: text(module(30, { 15: "changed()" })) });
        const runs = laid.runs.map((each) => [each.summary, laid.rows[each.from]!.text.trim(), laid.rows[each.to - 1]!.text.trim()]);
        // Unchanged but for 3 lines around the change, 24–30; cut at the class's and the method's edges.
        expect(runs).toEqual([
            ["8 unchanged lines, 1–8", "import os", ""],
            ["2 unchanged lines, 10–11", '"""The time."""', ""],
            ["11 unchanged lines, 13–23", "step1()", "step11()"],
            ["12 unchanged lines, 31–42", "step19()", "step30()"],
            ["5 unchanged lines, 43–47", "", "return b"],
        ]);
        // The line declaring the method the change is in stays in view, between the runs before and inside it.
        expect(laid.runs.some((each) => laid.rows.slice(each.from, each.to).some((row) => row.text === "    def sleep(self):"))).toBe(false);
        const sleep = laid.bodies.find((each) => each.names.join(".") === "Clock.sleep")!;
        const clock = laid.bodies.find((each) => each.names.join(".") === "Clock")!;
        const inside = (run: { from: number; to: number }, body: { from: number; to: number }) => run.from > body.from && run.to - 1 <= body.to;
        const apart = (run: { from: number; to: number }, body: { from: number; to: number }) => run.to - 1 < body.from || run.from > body.to;
        const around = (run: { from: number; to: number }, body: { from: number; to: number }) => run.from <= body.from && run.to - 1 >= body.to;
        for (const run of laid.runs) {
            for (const body of laid.bodies) {
                expect(inside(run, body) || apart(run, body) || around(run, body)).toBe(true);
            }
        }
        // Each run is named by the body it's in and what it hides: the bodies it holds whole, else its first line with words.
        const first = laid.bodies.find((each) => each.names.join(".") === "first")!;
        const last = laid.bodies.find((each) => each.names.join(".") === "last")!;
        expect(laid.runs.map((each) => JSON.parse(each.name) as unknown)).toEqual([
            ["", [first.name]],
            [clock.name, '"""The time."""'],
            [sleep.name, "step1()"],
            [sleep.name, "step19()"],
            ["", [last.name]],
        ]);
    });
});

/** A reading of a production file that asks nothing and has no findings. */
const PRODUCTION: Reading = { role: "production", asks: [], findings: [] };

describe("the judge's reading", () => {
    const changed = (after: string, reading: Reading): ChangedFile => ({
        path: "core.py",
        before: text(numbered(8)),
        after: text(after),
        reading,
    });

    it("says why a file is open in its header, and places each line that matters, said on the first row of what it triggered", () => {
        const reading: Reading = {
            role: "production",
            asks: [
                { name: "ignore", taken: "held", line: 4, side: "after" },
                { name: "public-api", taken: "flagged", line: 3, side: "after", api: { kind: "class-added", name: "Room" } },
                {
                    name: "public-api",
                    taken: "flagged",
                    line: 2,
                    side: "after",
                    api: { kind: "function-added", name: "Client.tell" },
                },
                // A kind the judge no longer finds, which items from copies before keep.
                {
                    name: "public-api",
                    taken: "flagged",
                    line: 6,
                    side: "after",
                    api: { kind: "signature-changed", name: "Client.ask" },
                },
            ],
            findings: [{ rule: "regex", message: "`re` parses\nwith a pattern", steer: "", start: 5, end: 6, taken: "told" }],
        };
        const laid = shown(changed(numbered(8, { 2: "two", 3: "three", 4: "four", 5: "five", 6: "six" }), reading));
        expect(laid.header).toBe("core.py · changed · +5 −5 · adds an ignore · public API: +Room +Client.tell ~Client.ask · told: regex");
        expect(laid.automatic).toBe(false);
        expect(laid.whole).toBe(false);
        expect(laid.matters.map((each) => [laid.rows[each.row]!.text, each.notes])).toEqual([
            ["two", [{ taken: "flagged", said: "public API: adds the method `Client.tell`" }]],
            ["three", [{ taken: "flagged", said: "public API: adds the class `Room`" }]],
            ["four", [{ taken: "held", said: "adds an ignore" }]],
            ["five", [{ taken: "told", said: "regex: `re` parses with a pattern" }]],
            ["six", [{ taken: "flagged", said: "public API: changes the signature of `Client.ask`" }]],
        ]);
    });

    it("shows every change of a file, its unchanged lines alone folding, three kept around each change and each line that matters", () => {
        const reading: Reading = {
            ...PRODUCTION,
            asks: [{ name: "public-api", taken: "flagged", line: 20, side: "after", api: { kind: "function-added", name: "f" } }],
        };
        const file: ChangedFile = { path: "a.py", before: text(numbered(30)), after: text(numbered(30, { 10: "ten" })), reading };
        const laid = shown(file);
        expect(laid.runs.map((each) => each.summary)).toEqual(["6 unchanged lines, 1–6", "3 unchanged lines, 14–16", "7 unchanged lines, 24–30"]);
        // No changed line is among what a run hides, in a file that asks nothing either.
        const plain = shown({ ...file, reading: PRODUCTION });
        for (const { rows, runs } of [laid, plain]) {
            expect(runs.flatMap((run) => rows.slice(run.from, run.to)).every((row) => row.change === "same")).toBe(true);
        }
        expect(plain.folded).toBeNull();
    });

    it("places a name taken out of a package's root on the line it was, and what's on no line shown on the header", () => {
        const removed: Reading = {
            ...PRODUCTION,
            asks: [{ name: "public-api", taken: "flagged", line: 2, side: "before", api: { kind: "export-removed", name: "ask" } }],
        };
        const laid = shown({ path: "__init__.py", before: text("a\nb\nc\n"), after: text("a\nc\n"), reading: removed });
        expect(laid.header).toBe("__init__.py · changed · +0 −1 · public API: −ask");
        expect(laid.matters).toEqual([
            { row: 1, notes: [{ taken: "flagged", said: "public API: removes `ask` from the package's root" }] },
        ]);
        expect(laid.whole).toBe(false);
        const created: Reading = { ...PRODUCTION, asks: [{ name: "new-file", taken: "flagged", side: "after" }] };
        const made = shown({ path: "n.py", before: null, after: text("x = 1\n"), reading: created });
        expect(made.header).toBe("n.py · created · 1 line · new file");
        expect([made.whole, made.matters]).toEqual([true, []]);
    });

    it("marks automatic a file that asks nothing held or flagged, production code among them, its findings told said", () => {
        const real = shown(changed(numbered(8, { 3: "three" }), PRODUCTION));
        expect([real.header, real.automatic]).toEqual(["core.py · changed · +1 −1 · automatic", true]);
        const told: Reading = {
            ...PRODUCTION,
            findings: [{ rule: "regex", message: "parses with a regular expression", steer: "", start: 3, end: 3, taken: "told" }],
        };
        const informed = shown(changed(numbered(8, { 3: "three" }), told));
        expect([informed.header, informed.automatic]).toEqual(["core.py · changed · +1 −1 · automatic · told: regex", true]);
        const spacing = shown(changed(numbered(8, { 3: "    l3" }), PRODUCTION));
        expect([spacing.header, spacing.automatic]).toEqual(["core.py · changed · +1 −1 · automatic", true]);
        const unread = shown({ path: "a.py", before: text("a\n"), after: text("b\n") });
        expect([unread.header, unread.automatic, unread.folded, unread.reasons]).toEqual(["a.py · changed · +1 −1", false, null, []]);
    });

    it("folds whole a test and a data file, by its role, and any file of a first approval, its header saying why where `automatic` stood", () => {
        const file = (path: string, role: string, findings: Reading["findings"] = []) => changed(numbered(8, { 3: "three" }), { ...PRODUCTION, role, findings });
        const said = (laid: ReturnType<typeof shown>) => [laid.header, laid.automatic, laid.folded];
        expect(said(shown({ ...file("core.py", "test"), path: "test_a.py" }))).toEqual(["test_a.py · changed · +1 −1 · test", true, "test"]);
        expect(said(shown({ ...file("core.py", "data"), path: "lock.json" }))).toEqual(["lock.json · changed · +1 −1 · data", true, "data"]);
        expect(said(shown(file("core.py", "production"), true))).toEqual(["core.py · changed · +1 −1 · first approval", true, "first approval"]);
        // Its findings told are said after.
        const told: Reading["findings"] = [{ rule: "regex", message: "a pattern", steer: "", start: 3, end: 3, taken: "told" }];
        expect(shown({ ...file("core.py", "test", told), path: "t.py" }).header).toBe("t.py · changed · +1 −1 · test · told: regex");
        // What a file asks stays said first, the reason it folds after.
        const protectedData: Reading = { role: "data", asks: [{ name: "protected", taken: "held", side: "after" }], findings: [] };
        const asked = shown({ ...changed(numbered(8, { 3: "three" }), protectedData), path: "d.json" });
        expect([asked.header, asked.automatic, asked.folded]).toEqual(["d.json · changed · +1 −1 · protected · data", false, "data"]);
        // Docs, production and protected files open.
        expect(["docs", "production", "protected", "operator"].map((role) => shown(file("core.py", role)).folded)).toEqual([null, null, null, null]);
    });

    it("counts a new file's public names, and names four of another's changes at most", () => {
        const names = ["A", "B", "C", "D", "E", "F"];
        const api = (kind: "class-added" | "export-added") =>
            names.map((name, at) => ({ name: "public-api", taken: "flagged" as const, line: at + 1, side: "after" as const, api: { kind, name } }));
        const source = names.map((name) => `class ${name}: pass`).join("\n") + "\n";
        const created: Reading = { ...PRODUCTION, asks: [{ name: "new-file", taken: "flagged", side: "after" }, ...api("class-added")] };
        expect(shown({ path: "n.py", before: null, after: text(source), reading: created }).header).toBe(
            "n.py · created · 6 lines · new file · 6 public names",
        );
        const grown: Reading = { ...PRODUCTION, asks: api("export-added") };
        expect(shown({ path: "__init__.py", before: text("x\n"), after: text(source), reading: grown }).header).toContain(
            "public API: +A +B +C +D and 2 more",
        );
    });

    it("counts an item's files by the first reason each is open, the most first, and nothing where none was read", () => {
        const created: Reading = { ...PRODUCTION, asks: [{ name: "new-file", taken: "flagged", side: "after" }] };
        const api: Reading = {
            ...PRODUCTION,
            asks: [{ name: "public-api", taken: "flagged", line: 1, side: "after", api: { kind: "class-added", name: "A" } }],
        };
        const docs: Reading = { role: "docs", asks: [], findings: [] };
        const file = (path: string, reading?: Reading): ChangedFile => ({
            path,
            before: null,
            after: text("class A:\n    pass\n"),
            ...(reading === undefined ? {} : { reading }),
        });
        expect(
            tally([file("a.md", docs), file("n.py", created), file("b.md", docs), file("p.py", api), file("c.md", docs)]),
        ).toBe("3 automatic · 1 new file · 1 public API");
        expect(tally([file("n.py", created), file("m.py", created), file("x.py")])).toBe("2 new files · 1 unread");
        expect(tally([file("x.py"), file("y.py")])).toBe("");
        // Files folded whole, counted by why.
        const tests: Reading = { role: "test", asks: [], findings: [] };
        const data: Reading = { role: "data", asks: [], findings: [] };
        expect(tally([file("t.py", tests), file("u.py", tests), file("d.json", data), file("a.md", docs)])).toBe("2 tests · 1 data file · 1 automatic");
        expect(tally([file("a.md", docs), file("p.py", PRODUCTION)], true)).toBe("2 of a first approval");
    });
});

describe("highlighting", () => {
    it("knows a file's language by its name", () => {
        expect(languageOf("src/a.py")).toBe(pythonLanguage);
        expect(languageOf("page/src/App.tsx")?.name).toBe("typescript");
        expect(languageOf("docs/dashboard.md")?.name).toBe("markdown");
        expect(languageOf("pyproject.toml")?.name).toBe("toml");
        expect(languageOf("uv.lock")?.name).toBe("toml");
        expect(languageOf("package.json")?.name).toBe("json");
        expect(languageOf("Makefile")).toBeNull();
    });

    it("highlights a text with its language's own parser, each token's classes as CodeMirror's class highlighter names them", () => {
        const code = "def f():\n    return 'x'\n";
        const tokens = highlighted(code, pythonLanguage);
        const at = (word: string) => tokens.find((each) => code.slice(each.from, each.to) === word)?.classes;
        expect(at("def")).toBe("tok-keyword");
        expect(at("return")).toBe("tok-keyword");
        expect(at("'x'")).toBe("tok-string");
    });

    it("finds a row's tokens counted from its start, and highlights each side of a file once", () => {
        const file: ChangedFile = { path: "a.toml", before: null, after: text('[project]\nname = "lup"\n') };
        const [, row] = shown(file).rows;
        const tokens = tokensOf(file, "after");
        expect(tokensOf(file, "after")).toBe(tokens);
        const found = within(tokens, row!);
        expect(found.map((each) => row!.text.slice(each.from, each.to))).toContain('"lup"');
        expect(found.every((each) => each.from >= 0 && each.to <= row!.text.length)).toBe(true);
        expect(tokensOf({ path: "a.bin", before: null, after: text("x") }, "after")).toEqual([]);
    });

    it("leaves out a token with no text in a row, which CodeMirror would refuse as a mark", () => {
        const row = { side: "after", number: 1, change: "same", text: "    return x", offset: 10 } as const;
        const tokens = [
            { from: 10, to: 10, classes: "tok-indent" },
            { from: 14, to: 20, classes: "tok-keyword" },
            { from: 22, to: 22, classes: "tok-empty" },
        ];
        expect(within(tokens, row)).toEqual([{ from: 4, to: 10, classes: "tok-keyword" }]);
        const code = "class A:\n    def f(self):\n        if x:\n            return 1\n\n    y = 2\n";
        const file: ChangedFile = { path: "a.py", before: null, after: text(code) };
        const marks = shown(file).rows.flatMap((each) => within(tokensOf(file, "after"), each));
        expect(marks.every((each) => each.to > each.from)).toBe(true);
    });
});
