import { syntaxTree } from "@codemirror/language";
import { EditorSelection, EditorState, type Range, type TransactionSpec } from "@codemirror/state";
import type { Decoration } from "@codemirror/view";
import { NodeProp } from "@lezer/common";
import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import type { Span } from "./comments";
import { brokenLine, decorate, hiddenOn, markdown, openedLine, revealing, shifted, source, sourced, sources, treeOf, unindented, without, type Source } from "./markdown";

/** The lines of `text` from the one holding `first` to the one holding `last`, each with its line break, as a source is read from them. */
function lined(text: string, first: string, last: string = first): Span[] {
    const start = text.lastIndexOf("\n", text.indexOf(first)) + 1;
    const end = text.indexOf("\n", text.indexOf(last, start));
    const found: Span[] = [];
    for (let at = start; at <= end; ) {
        const to = text.indexOf("\n", at);
        found.push({ from: at, to: Math.min(to + 1, text.length) });
        at = to + 1;
    }
    return found;
}

/** Return `text` laid out with `found` written in Markdown, as a view lays it out: the text and its sources in one transaction, read in it. */
function laid(text: string, found: Source[]): EditorState {
    const empty = EditorState.create({ extensions: markdown() });
    return empty.update({ changes: { from: 0, insert: text }, effects: sourced.of(found) }).state;
}

/** The names of the nodes around `position`, innermost first. */
function around(state: EditorState, position: number): string[] {
    const names: string[] = [];
    for (let node: ReturnType<typeof syntaxTree>["topNode"] | null = syntaxTree(state).resolveInner(position, 1); node !== null; node = node.parent) {
        names.push(node.name);
    }
    return names;
}

/** What `made` hides of `state`'s text, in order. */
function hidden(state: EditorState, made: Range<Decoration>[]): string[] {
    return made
        .filter((each) => each.from < each.to && each.value.spec.widget === undefined && each.value.spec.attributes === undefined)
        .sort((a, b) => a.from - b.from)
        .map((each) => state.sliceDoc(each.from, each.to));
}

/** What `made` draws beside `state`'s text, by where, in order: each widget's text, and whether it's drawn after what's there. */
function drawn(state: EditorState, made: Range<Decoration>[]): { at: string; text: string; after: boolean }[] {
    return made
        .filter((each) => each.value.spec.widget !== undefined)
        .sort((a, b) => a.from - b.from || a.value.startSide - b.value.startSide)
        .map((each) => ({
            at: state.sliceDoc(each.from, state.doc.lineAt(each.from).to),
            text: (each.value.spec.widget as { text: string }).text,
            after: each.value.spec.side > 0,
        }));
}

const WHOLE = [{ from: 0, to: 1_000_000 }];

describe("what's written in Markdown", () => {
    it("joins the lines that touch into one source, and keeps an empty comment as a source of one empty line", () => {
        expect(source("text", [{ from: 0, to: 5 }, { from: 5, to: 9 }, { from: 20, to: 24 }])).toEqual({
            kind: "text",
            from: 0,
            to: 24,
            lines: [{ from: 0, to: 9 }, { from: 20, to: 24 }],
        });
        expect(source("comment", [{ from: 7, to: 7 }])).toEqual({ kind: "comment", from: 7, to: 7, lines: [{ from: 7, to: 7 }] });
        expect(source("text", [])).toBeNull();
        expect(without({ from: 0, to: 10 }, [{ from: 3, to: 5 }, { from: 8, to: 12 }])).toEqual([{ from: 0, to: 3 }, { from: 5, to: 8 }]);
    });

    it("builds a tree of the sources, a comment under an item's lines inside the item's node", () => {
        const text: Source = { kind: "text", from: 10, to: 40, lines: [{ from: 10, to: 20 }, { from: 30, to: 40 }] };
        const comment: Source = { kind: "comment", from: 20, to: 29, lines: [{ from: 20, to: 29 }] };
        const tree = treeOf([comment, text, { kind: "comment", from: 50, to: 60, lines: [{ from: 50, to: 60 }] }], 70);
        const top = tree.topNode;
        expect(top.name).toBe("Text");
        expect(tree.length).toBe(70);
        const children = top.getChildren("Markdown").map((each) => [each.from, each.to]);
        expect(children).toEqual([[10, 40], [50, 60]]);
        expect(top.firstChild?.getChildren("Markdown").map((each) => [each.from, each.to])).toEqual([[20, 29]]);
    });
});

describe("a table", () => {
    const text = ["── @61 note ──", "| kind | n |", "|---|---:|", "| `user` | 412 |", "a comment on the row", "| x | 3 |", ""].join("\n");
    const found = [
        source("text", [...lined(text, "| kind | n |", "| `user` | 412 |"), ...lined(text, "| x | 3 |")]),
        source("comment", [{ from: text.indexOf("a comment"), to: text.indexOf("a comment") + "a comment on the row".length }]),
    ].flatMap((each) => (each === null ? [] : [each]));

    it("is read as one past the comment under its row, which is read on its own, the header read as neither", () => {
        const state = laid(text, found);
        expect(around(state, text.indexOf("| x"))).toContain("Table");
        expect(around(state, text.indexOf("412"))).toContain("TableRow");
        expect(around(state, text.indexOf("comment"))).toEqual(["Paragraph", "Document", "Markdown", "Markdown", "Text"]);
        expect(around(state, text.indexOf("comment"))).not.toContain("Table");
        expect(around(state, 3)).toEqual(["Text"]);
    });

    it("is padded so its columns line up, each cell as wide as it shows, the row under the header drawn out, by decorations and never text", () => {
        const state = laid(text, found);
        const made = decorate(state, WHOLE, () => false);
        // ` kind ` and ` `user` `, shown without its backticks, fill the first column, 6 wide between its pipes, so
        // `x` is padded by 3 after it and the dashes under them by 3; ` 412 ` fills the second, right-aligned by its
        // colon, so `n` and `3` are padded before them, and its dashes by one before the colon.
        expect(drawn(state, made)).toEqual([
            { at: "n |", text: "  ", after: false },
            { at: "|---:|", text: "---", after: true },
            { at: ":|", text: "-", after: true },
            { at: " | 3 |", text: "   ", after: true },
            { at: "3 |", text: "  ", after: false },
        ]);
        expect(hidden(state, made)).toEqual(["`", "`"]);
        expect(state.doc.toString()).toBe(text);
    });
});

describe("a construct's marks", () => {
    const text = ["# Title", "", "**bold** and *soft* and `code` and [a link](http://x) and ~~gone~~ and \\*kept\\*", "", "```python", "x = 1", "```", ""].join("\n");
    const found = [source("text", lined(text, "# Title", "```\n"))].flatMap((each) => (each === null ? [] : [each]));

    it("are hidden, the heading's with its space, a link's with its address, which its text says on hover", () => {
        const state = laid(text, found);
        const made = decorate(state, WHOLE, () => false);
        expect(hidden(state, made)).toEqual(["# ", "**", "**", "*", "*", "`", "`", "[", "]", "(", "http://x", ")", "~~", "~~", "\\", "\\", "```", "```"]);
        const titled = made.find((each) => each.value.spec.attributes?.title !== undefined);
        expect(titled === undefined ? null : state.sliceDoc(titled.from, titled.to)).toBe("[a link](http://x)");
        const barred = made.filter((each) => each.value.spec.class === "md-code").map((each) => state.doc.lineAt(each.from).text);
        expect(barred).toEqual(["```python", "x = 1", "```"]);
    });

    it("show on the line the cursor is on in a comment, and on no line of an item's text", () => {
        const comment = "**bold** here";
        const text = ["an item's **own** line", comment, "another *own* line", ""].join("\n");
        const found = [
            source("text", [...lined(text, "an item's **own** line"), ...lined(text, "another *own* line")]),
            source("comment", [{ from: text.indexOf(comment), to: text.indexOf(comment) + comment.length }]),
        ].flatMap((each) => (each === null ? [] : [each]));
        const state = laid(text, found);
        const inComment = state.update({ selection: { anchor: text.indexOf("here") } }).state;
        expect(revealing(inComment)).toBe(text.indexOf(comment));
        const revealed = revealing(inComment);
        expect(hidden(inComment, decorate(inComment, WHOLE, (line) => line === revealed))).toEqual(["**", "**", "*", "*"]);
        const inText = state.update({ selection: { anchor: text.indexOf("own") } }).state;
        expect(revealing(inText)).toBeNull();
        expect(hidden(inText, decorate(inText, WHOLE, () => false))).toEqual(["**", "**", "**", "**", "*", "*"]);
    });

    it("are what a cursor finds no character of on a line, in order, but on the line it reveals", () => {
        const comment = "**bold** here";
        const text = ["## Title", "an item's **own** *line*", comment, ""].join("\n");
        const found = [
            source("text", [...lined(text, "## Title"), ...lined(text, "an item's **own** *line*")]),
            source("comment", [{ from: text.indexOf(comment), to: text.indexOf(comment) + comment.length }]),
        ].flatMap((each) => (each === null ? [] : [each]));
        const state = laid(text, found);
        const spans = (at: number, where: EditorState = state) => hiddenOn(where, at).map((each) => where.sliceDoc(each.from, each.to));
        expect(spans(text.indexOf("Title"))).toEqual(["## "]);
        expect(spans(text.indexOf("own"))).toEqual(["**", "**", "*", "*"]);
        expect(spans(text.indexOf("here"))).toEqual(["**", "**"]);
        const inComment = state.update({ selection: { anchor: text.indexOf("here") } }).state;
        expect(spans(text.indexOf("here"), inComment)).toEqual([]);
        expect(spans(text.indexOf("own"), inComment)).toEqual(["**", "**", "*", "*"]);
    });
});

/**
 * What `act` makes of the comment `written` under the item's line `above`, its cursor where `|` is, or with `lines`
 * whole lines from the cursor's selected, as vim selects those `>>` or `>j` moves: the comment after, `|` where the
 * cursor is but with lines selected; none where it does nothing.
 */
function writing(written: string, act: (state: EditorState) => TransactionSpec | null, lines = 0, above = "an item's line"): string | null {
    const comment = written.replace("|", "");
    const text = `${above}\n${comment}\n`;
    const from = above.length + 1;
    const found = [source("text", lined(text, above)), source("comment", [{ from, to: from + comment.length }])].flatMap((each) =>
        each === null ? [] : [each],
    );
    const laidOut = laid(text, found);
    const at = laidOut.doc.lineAt(from + written.indexOf("|"));
    const after = lines === 0 ? undefined : laidOut.doc.line(at.number + lines);
    const selection = after === undefined ? EditorSelection.cursor(from + written.indexOf("|")) : EditorSelection.range(at.from, after.from);
    const state = laidOut.update({ selection }).state;
    const spec = act(state);
    if (spec === null) {
        return null;
    }
    const made = state.update(spec).state;
    const head = made.selection.main.head;
    const shown = lines === 0 ? `${made.sliceDoc(0, head)}|${made.sliceDoc(head)}` : made.doc.toString();
    return shown.slice(from, shown.length - 1);
}

describe("Enter in a comment", () => {
    const entered = (written: string) => writing(written, brokenLine);

    it("starts the next line at the indentation of the one it's broken from, with no bullet or number", () => {
        expect(entered("- a|")).toBe("- a\n|");
        expect(entered("- a\n  - b|")).toBe("- a\n  - b\n  |");
        expect(entered("1. a|\n2. b")).toBe("1. a\n|\n2. b");
        expect(entered("> quoted|")).toBe("> quoted\n|");
        expect(entered("- [x] done|")).toBe("- [x] done\n|");
    });

    it("never ends a list on an empty item, nor numbers the items after it", () => {
        expect(entered("- a\n- |")).toBe("- a\n- \n|");
        expect(entered("1. a\n2. |\n3. c")).toBe("1. a\n2. \n|\n3. c");
    });

    it("breaks a line inside it, the spaces after the cursor going, and empties a line left holding only spaces, as vim's autoindent does", () => {
        expect(entered("  - one| two")).toBe("  - one\n  |two");
        expect(entered("- a\n  |")).toBe("- a\n\n  |");
        expect(entered("  |- a")).toBe("\n  |- a");
        expect(entered("some |words")).toBe("some \n|words");
    });

    it("takes back an indentation nothing was typed after as the writing ends, and nothing else", () => {
        const ended = (written: string) => writing(written, (state) => unindented(state, state.selection.main.head));
        expect(ended("- a\n  - b\n  |")).toBe("- a\n  - b\n|");
        expect(ended("- a\n  |\n- b")).toBe("- a\n|\n- b");
        expect(ended("- a\n  - |b")).toBeNull();
        expect(ended("- a\n|")).toBeNull();
    });
});

describe("o and O in a comment", () => {
    const opening = (written: string, below: boolean) => writing(written, (state) => openedLine(state, state.selection.main.head, below));

    it("open a line below or above at the line's indentation, with no bullet or number", () => {
        expect(opening("- |a\n- b", true)).toBe("- a\n|\n- b");
        expect(opening("- a\n- |b", false)).toBe("- a\n|\n- b");
        expect(opening("- a\n  - |b\n- c", true)).toBe("- a\n  - b\n  |\n- c");
        expect(opening("- a\n  - |b\n- c", false)).toBe("- a\n  |\n  - b\n- c");
    });

    it("leave the numbers, a task's box and a quote's mark as they are", () => {
        expect(opening("1. |a\n2. b\n3. c", true)).toBe("1. a\n|\n2. b\n3. c");
        expect(opening("1. a\n2. |b\n3. c", false)).toBe("1. a\n|\n2. b\n3. c");
        expect(opening("- [x] |done", true)).toBe("- [x] done\n|");
        expect(opening("> |quoted", false)).toBe("|\n> quoted");
        expect(opening("- a\n  |more", true)).toBe("- a\n  more\n  |");
    });
});

describe("moving a comment's line in and out", () => {
    const moved = (written: string, inward: boolean, lines = 0, above?: string) => writing(written, (state) => shifted(state, inward), lines, above);

    it("moves a line in to where the words of the item above it begin, nesting it under that item", () => {
        expect(moved("- a\n- |b", true)).toBe("- a\n  - |b");
        expect(moved("1. a\n2. |b", true)).toBe("1. a\n   2. |b");
        expect(moved("10. a\n- |b", true)).toBe("10. a\n    - |b");
        expect(moved("- a\n  - b\n    - c\n  - |d", true)).toBe("- a\n  - b\n    - c\n    - |d");
    });

    it("moves a line in by one indent unit past the item's words, or with no item above it in its comment", () => {
        expect(moved("- a\n  - |b", true)).toBe("- a\n    - |b");
        expect(moved("|plain", true)).toBe("  |plain");
        expect(moved("- |b", true, 0, "1. an item's line")).toBe("  - |b");
        // A block of code holds no item.
        expect(moved("```\n1. x\n```\n|y", true)).toBe("```\n1. x\n```\n  |y");
    });

    it("moves a line out to the item it's nested in, then to where that item begins", () => {
        expect(moved("- a\n  - b\n    - |c", false)).toBe("- a\n  - b\n  - |c");
        expect(moved("- a\n  - b\n  - |c", false)).toBe("- a\n  - b\n- |c");
        expect(moved("1. a\n   2. |b", false)).toBe("1. a\n2. |b");
        expect(moved("- a\n      |deep", false)).toBe("- a\n  |deep");
        expect(moved("    |plain", false)).toBe("  |plain");
        expect(moved("- |a", false)).toBeNull();
    });

    it("keeps the cursor on what it was on, and after the indentation where it was in it, as on a line just begun", () => {
        expect(moved("- a\n|", true)).toBe("- a\n  |");
        expect(moved("- a\n|- b", true)).toBe("- a\n  |- b");
        expect(moved("- a\n  |", false)).toBe("- a\n|");
    });

    it("moves each line selected by as much as the first, an item's own items with it, an empty line staying empty", () => {
        expect(moved("- a\n- |b\n  - c", true, 2)).toBe("- a\n  - b\n    - c");
        expect(moved("1. a\n2. |b\n   - c", true, 2)).toBe("1. a\n   2. b\n      - c");
        expect(moved("|- a\n\n- b", true, 3)).toBe("  - a\n\n  - b");
        expect(moved("- a\n  - |b\n    - c", false, 2)).toBe("- a\n- b\n  - c");
    });
});

describe("the sources' trees as the text changes", () => {
    it("keep each source's node, with the Markdown tree mounted on it, where the edit didn't touch the source, reading anew the one it did", () => {
        const comment = "a *comment*";
        // Lezer keeps no fragment of a stretch under 128 characters between an edit and the text's edge, so the
        // item before the comment is long, as items are.
        const first = `first *item*, ${"with words enough to be kept as a fragment, ".repeat(4)}`;
        const text = `${first}\n${comment}\nsecond *item*\n`;
        const found = [
            source("text", lined(text, first)),
            source("comment", [{ from: text.indexOf(comment), to: text.indexOf(comment) + comment.length }]),
            source("text", lined(text, "second *item*")),
        ].flatMap((each) => (each === null ? [] : [each]));
        const state = laid(text, found);
        // The source's node holding `word`, at where the word is in that state's text.
        const node = (of: EditorState, word: string) => {
            let found = syntaxTree(of).resolveInner(of.doc.toString().indexOf(word), 1);
            while (found.parent !== null && found.name !== "Markdown") {
                found = found.parent;
            }
            return found;
        };
        const mounted = (of: EditorState, word: string) => node(of, word).tree?.prop(NodeProp.mounted)?.tree;
        const typed = state.update({ changes: { from: text.indexOf(comment) + comment.length, insert: "!" } }).state;
        for (const word of ["first", "second"]) {
            expect(node(typed, word).tree).toBe(node(state, word).tree);
            expect(mounted(typed, word)).toBe(mounted(state, word));
        }
        expect(node(typed, comment).tree).not.toBe(node(state, comment).tree);
        expect(around(typed, text.indexOf("comment"))).toEqual(["Emphasis", "Paragraph", "Document", "Markdown", "Text"]);
        expect(typed.sliceDoc(text.indexOf(comment), text.indexOf(comment) + comment.length + 1)).toBe(`${comment}!`);
    });

    it("read a comment opened empty once something is typed in it", () => {
        const text = "a line\n\nanother line\n";
        const found = [source("text", [{ from: 0, to: 7 }]), source("comment", [{ from: 7, to: 7 }]), source("text", [{ from: 8, to: 21 }])].flatMap(
            (each) => (each === null ? [] : [each]),
        );
        const state = laid(text, found);
        expect(around(state, 7)).toEqual(["Text"]);
        const typed = state.update({ changes: { from: 7, insert: "- a" } }).state;
        expect(typed.field(sources)[1]).toEqual({ kind: "comment", from: 7, to: 10, lines: [{ from: 7, to: 10 }] });
        expect(around(typed, 9)).toContain("ListItem");
    });

    it("carry what's typed at a comment's end into it, and what's typed at a text's end out of it", () => {
        const text = "a line\na comment\nanother line\n";
        const found = [
            source("text", [{ from: 0, to: 7 }]),
            source("comment", [{ from: 7, to: 16 }]),
            source("text", [{ from: 17, to: 30 }]),
        ].flatMap((each) => (each === null ? [] : [each]));
        const state = laid(text, found);
        const typed = state.update({ changes: [{ from: 16, insert: "!" }, { from: 7, insert: "<" }] }).state;
        expect(typed.field(sources)).toEqual([
            { kind: "text", from: 0, to: 7, lines: [{ from: 0, to: 7 }] },
            { kind: "comment", from: 7, to: 18, lines: [{ from: 7, to: 18 }] },
            { kind: "text", from: 19, to: 32, lines: [{ from: 19, to: 32 }] },
        ]);
        expect(typed.sliceDoc(7, 18)).toBe("<a comment!");
    });
});
