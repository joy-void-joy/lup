import { pythonLanguage } from "@codemirror/lang-python";
import { describe, expect, it } from "vitest";

import { highlighted, languageOf, lines, shown, tokensOf, within, type ChangedFile } from "./code";

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
        expect(shown({ path: "i.png", before: null, after: { kind: "binary", size: 1150 } })).toEqual({
            header: "i.png · created · binary, not shown · 1,150 bytes",
            rows: [],
            runs: [],
        });
        expect(
            shown({ path: "i.png", before: { kind: "binary", size: 10 }, after: { kind: "binary", size: 12 } }).header,
        ).toBe("i.png · changed · binary, not shown · 10 bytes → 12 bytes");
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
