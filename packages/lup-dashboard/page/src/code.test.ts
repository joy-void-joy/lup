import { pythonLanguage } from "@codemirror/lang-python";
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
        expect(same.runs).toEqual([{ from: 0, to: 5, summary: "5 unchanged lines, 1–5" }]);
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
                    api: { kind: "signature-changed", name: "Client.ask" },
                },
            ],
            findings: [{ rule: "regex", message: "`re` parses\nwith a pattern", steer: "", start: 5, end: 6, taken: "told" }],
        };
        const laid = shown(changed(numbered(8, { 2: "two", 3: "three", 4: "four", 5: "five", 6: "six" }), reading));
        expect(laid.header).toBe("core.py · changed · +5 −5 · adds an ignore · public API: +Room ~Client.ask · told: regex");
        expect(laid.automatic).toBe(false);
        expect(laid.whole).toBe(false);
        expect(laid.matters.map((each) => [laid.rows[each.row]!.text, each.notes])).toEqual([
            ["two", [{ taken: "flagged", said: "public API: changes the signature of `Client.ask`" }]],
            ["three", [{ taken: "flagged", said: "public API: adds the class `Room`" }]],
            ["four", [{ taken: "held", said: "adds an ignore" }]],
            ["five", [{ taken: "told", said: "regex: `re` parses with a pattern" }]],
            ["six", []],
        ]);
    });

    it("keeps a line that matters out of the unchanged runs folding around it", () => {
        const reading: Reading = {
            ...PRODUCTION,
            asks: [{ name: "public-api", taken: "flagged", line: 20, side: "after", api: { kind: "signature-changed", name: "f" } }],
        };
        const laid = shown({ path: "a.py", before: text(numbered(30)), after: text(numbered(30, { 10: "ten" })), reading });
        expect(laid.runs.map((each) => each.summary)).toEqual([
            "6 unchanged lines, 1–6",
            "3 unchanged lines, 14–16",
            "7 unchanged lines, 24–30",
        ]);
    });

    it("places a name taken out of a package's root on the line it was, and what's on no line shown on the header", () => {
        const removed: Reading = {
            ...PRODUCTION,
            asks: [{ name: "public-api", taken: "flagged", line: 2, side: "before", api: { kind: "export-removed", name: "ask" } }],
        };
        const laid = shown({ path: "__init__.py", before: text("a\nb\nc\n"), after: text("a\nc\n"), reading: removed });
        expect(laid.header).toBe("__init__.py · changed · +0 −1 · public API: −ask");
        expect(laid.matters).toEqual([
            { row: 1, notes: [{ taken: "flagged", said: "public API: takes `ask` out of the package's root" }] },
        ]);
        expect(laid.whole).toBe(false);
        const created: Reading = { ...PRODUCTION, asks: [{ name: "new-file", taken: "flagged", side: "after" }] };
        const made = shown({ path: "n.py", before: null, after: text("x = 1\n"), reading: created });
        expect(made.header).toBe("n.py · created · 1 line · new file");
        expect([made.whole, made.matters]).toEqual([true, []]);
    });

    it("opens a production file with a real change, and marks automatic one that asks nothing else", () => {
        const real = shown(changed(numbered(8, { 3: "three" }), PRODUCTION));
        expect([real.header, real.automatic]).toEqual(["core.py · changed · +1 −1 · production", false]);
        const spacing = shown(changed(numbered(8, { 3: "    l3" }), PRODUCTION));
        expect([spacing.header, spacing.automatic]).toEqual(["core.py · changed · +1 −1 · automatic", true]);
        const test = shown({ ...changed(numbered(8, { 3: "three" }), { ...PRODUCTION, role: "test" }), path: "test_a.py" });
        expect([test.header, test.automatic]).toEqual(["test_a.py · changed · +1 −1 · automatic", true]);
        const unread = shown({ path: "a.py", before: text("a\n"), after: text("b\n") });
        expect([unread.header, unread.automatic, unread.reasons]).toEqual(["a.py · changed · +1 −1", false, []]);
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
});
