import { foldEffect, foldState, unfoldEffect } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import type { CodeMirrorV } from "@replit/codemirror-vim";
import { describe, expect, it } from "vitest";

import type { Folding } from "./comments";
import {
    begun,
    chordOf,
    closedAs,
    deadPressed,
    deadTyped,
    keptFolds,
    nextWritten,
    ownOf,
    rewritten,
    SPACED,
    stepped,
    UNPRESSED,
    visit,
    went,
    type Dead,
    type History,
    type Pressed,
    type Typing,
} from "./editor";
import { REVIEW_KEYS } from "./keys";

describe("the draft's history", () => {
    const draft = (history: History<string>) => history.states[history.at]?.draft;

    it("undoes and redoes steps, a step being written one", () => {
        let history = stepped(begun(""), "a");
        history = rewritten(history, "ab");
        history = stepped(history, "ab c");
        expect(draft(went(history, "undo"))).toBe("ab");
        expect(draft(went(went(history, "undo"), "undo"))).toBe("");
        expect(draft(went(went(went(history, "undo"), "undo"), "redo"))).toBe("ab");
        expect(went(begun(""), "undo")).toEqual(begun(""));
        expect(went(history, "redo")).toEqual(history);
    });

    it("reaches with g- a state undone and left by a change after it, which Ctrl+R no longer does", () => {
        // Text written, undone, then a change made: vim's g- still reaches what was undone.
        let history = stepped(begun(""), "kept");
        history = stepped(history, "kept, lost");
        history = went(history, "undo");
        history = stepped(history, "kept, other");
        expect(went(history, "redo")).toEqual(history);
        expect(draft(went(history, "earlier"))).toBe("kept, lost");
        expect(draft(went(went(history, "earlier"), "later"))).toBe("kept, other");
        // `u` from the change goes back to what it was made from, and Ctrl+R to the change again.
        expect(draft(went(history, "undo"))).toBe("kept");
        expect(draft(went(went(history, "undo"), "redo"))).toBe("kept, other");
    });
});

describe("going between the comments one wrote", () => {
    // Three comments, at 10–15, 16–20 and 40–48.
    const blocks = [
        { from: 40, to: 48 },
        { from: 10, to: 15 },
        { from: 16, to: 20 },
    ];

    it("goes to the next and previous comment in the text's order, past the one the cursor is in, on its last character", () => {
        expect(nextWritten(blocks, 0, true, [])).toBe(14);
        expect(nextWritten(blocks, 12, true, [])).toBe(19);
        expect(nextWritten(blocks, 20, true, [])).toBe(47);
        expect(nextWritten(blocks, 30, false, [])).toBe(19);
        expect(nextWritten(blocks, 17, false, [])).toBe(14);
        expect(nextWritten(blocks, 44, true, [])).toBeUndefined();
        expect(nextWritten(blocks, 12, false, [])).toBeUndefined();
    });

    it("lands where the cursor last was in it, kept as it leaves each comment, one place a comment", () => {
        let visited = visit([], blocks, 12, 13);
        expect(visited).toEqual([]);
        visited = visit(visited, blocks, 11, 30);
        expect(visited).toEqual([11]);
        expect(nextWritten(blocks, 0, true, visited)).toBe(11);
        visited = visit(visited, blocks, 13, 44);
        expect(visited).toEqual([13]);
        visited = visit(visited, blocks, 42, 0);
        expect(visited).toEqual([13, 42]);
        expect(nextWritten(blocks, 20, true, visited)).toBe(42);
        // A place no comment is at any more is let go.
        expect(visit(visited, [{ from: 40, to: 48 }], 44, 0)).toEqual([44]);
        // Left past its last character, as writing ends, it lands on it.
        expect(nextWritten(blocks, 0, true, [15])).toBe(14);
    });
});

/**
 * What vim gets of a dead key's keys and the text the browser types, outside insert mode, in order: each key that goes
 * to it and each text given it; and each key the browser alone gets, to type what it composes. What lands is nothing.
 */
function through(events: ({ pressed: Pressed } | { typed: string; typing: Typing })[]): { vim: string[]; browser: string[]; dead: Dead["at"] } {
    let dead = UNPRESSED;
    const vim: string[] = [];
    const browser: string[] = [];
    for (const event of events) {
        if ("pressed" in event) {
            const step = deadPressed(dead, event.pressed);
            dead = step.dead;
            if (step.given !== "") {
                vim.push(step.given);
            }
            if (step.goes === "vim") {
                vim.push(event.pressed.key);
            } else if (step.goes === "browser") {
                browser.push(event.pressed.key);
            }
        } else {
            const step = deadTyped(dead, event.typing, event.typed);
            dead = step.dead;
            if (step.given) {
                vim.push(event.typed);
            }
        }
    }
    return { vim, browser, dead: dead.at };
}

const DEAD = { pressed: { key: "Dead", composing: false, printable: false } };
const key = (name: string, composing = false) => ({ pressed: { key: name, composing, printable: [...name].length === 1 } });
const PROCESS = key("Process");
const shown = (text: string) => ({ typed: text, typing: "composing" as const });
const typed = (text: string) => ({ typed: text, typing: "typed" as const });
const ended = (text: string) => ({ typed: text, typing: "ended" as const });

describe("a dead key outside insert mode", () => {
    it("gives vim what it types once completed, never what it shows while composed, as Chromium on Linux sends `\"` then Space", () => {
        // `"` shows `¨` while it waits; Space, "Process" to the page, has the browser type `"`; then `+yy` copies.
        const copied = through([DEAD, shown("¨"), PROCESS, typed('"'), key("+"), key("y"), key("y")]);
        expect(copied).toEqual({ vim: ['"', "+", "y", "y"], browser: [], dead: "none" });
        // `"` then `+`, on a layout that types both: vim gets both.
        expect(through([DEAD, shown("¨"), PROCESS, typed('"+'), key("y"), key("y")]).vim).toEqual(['"+', "y", "y"]);
        // On a layout that types nothing for the two, vim gets neither, and `yy` stays a yank of its own.
        expect(through([DEAD, shown("¨"), PROCESS, key("y"), key("y")]).vim).toEqual(["y", "y"]);
    });

    it("gives vim what a composition ends with once, though the browser types it again after", () => {
        expect(through([DEAD, shown("¨"), key(" ", true), shown('"'), ended('"'), typed('"'), key("+")])).toEqual({
            vim: ['"', "+"],
            browser: [],
            dead: "none",
        });
    });

    it("gives vim the dead key's own character where the browser dropped its composition, then the key after it but a Space", () => {
        // The composition dropped once the page took what it showed: the next key comes as itself, typing nothing composed.
        expect(through([DEAD, shown("¨"), key(" "), key("+"), key("y")])).toEqual({ vim: ['"', "+", "y"], browser: [], dead: "none" });
        expect(through([DEAD, shown("¨"), key("+"), key("y")]).vim).toEqual(['"', "+", "y"]);
        expect(through([DEAD, shown("´"), key(" "), key("a")]).vim).toEqual(["'", "a"]);
        expect(ownOf("`")).toBe("`");
    });

    it("leaves the key after it to the browser where it composes nothing, so it types what the two make", () => {
        // A dead key then the next key as itself, as Chromium sends them on Windows: Space types `"`.
        expect(through([DEAD, key(" "), typed('"'), key("+"), key("y")])).toEqual({ vim: ['"', "+", "y"], browser: [" "], dead: "none" });
        // `"` then `+` typing `"+` in two goes to vim whole.
        expect(through([DEAD, key("+"), typed('"'), typed("+"), key("y")]).vim).toEqual(['"', "+", "y"]);
    });

    it("waits through a key that only modifies another, and lets one that types nothing reach vim", () => {
        expect(through([DEAD, key("Shift"), key("+"), typed('"+')])).toEqual({ vim: ["Shift", '"+'], browser: ["+"], dead: "giving" });
        expect(through([DEAD, key("Escape"), key("j")])).toEqual({ vim: ["Escape", "j"], browser: [], dead: "none" });
    });

    it("jumps to a mark with `` ` `` then Space then its letter, the Space never reaching vim, which would begin a chord", () => {
        expect(through([DEAD, shown("`"), PROCESS, typed("`"), key("a")]).vim).toEqual(["`", "a"]);
    });

    it("gives vim nothing typed with no dead key pressed, as a paste, and takes no key from vim", () => {
        expect(through([typed("dd"), key(" "), key("j")])).toEqual({ vim: [" ", "j"], browser: [], dead: "none" });
    });

    it("keeps a key the browser composes from vim, and a dead key pressed again waits again", () => {
        expect(through([DEAD, PROCESS, typed("`"), DEAD, shown("´"), key(" ", true), ended("'")]).vim).toEqual(["`", "'"]);
    });
});

describe("folds kept as the operator left them", () => {
    // Four lines, `a` to `d`: one fold over `b` and `c`, folded as it's laid out, and one over `d`, open.
    const doc = "a\nb\nc\nd";
    const folded: Folding = { key: "folded", closed: true, summary: { from: 0, to: 1 }, from: 1, to: 5 };
    const open: Folding = { key: "open", closed: false, summary: { from: 4, to: 5 }, from: 5, to: 7 };
    const folds = [folded, open];
    const laidOut = EditorState.create({ doc, extensions: [foldState] }).update({ effects: foldEffect.of(folded) }).state;

    it("keeps each fold the operator opened or closed, by its key, and none they left alone", () => {
        const opened = laidOut.update({ effects: unfoldEffect.of(folded) }).state;
        expect(keptFolds(folds, laidOut, opened, new Map())).toEqual(new Map([["folded", false]]));
        const closed = opened.update({ effects: foldEffect.of(open) }).state;
        expect(keptFolds(folds, opened, closed, new Map([["folded", false]]))).toEqual(
            new Map([
                ["folded", false],
                ["open", true],
            ]),
        );
        expect(keptFolds(folds, laidOut, laidOut, new Map())).toEqual(new Map());
    });

    it("folds each as the operator left it, else as it's laid out", () => {
        expect([closedAs(folded, new Map()), closedAs(open, new Map())]).toEqual([true, false]);
        expect([closedAs(folded, new Map([["folded", false]])), closedAs(open, new Map([["open", true]]))]).toEqual([false, true]);
    });
});

describe("a chord begun", () => {
    const held = (keys: string[], mode: { insertMode?: boolean; visualMode?: boolean } = {}) =>
        chordOf({
            state: { vim: { insertMode: false, visualMode: false, ...mode, inputState: { keyBuffer: keys } } },
        } as unknown as CodeMirrorV);

    it("says what vim holds of a chord begun with Space, as the list writes it, and nothing of any other", () => {
        expect(held(["<Space>"])).toBe("␣");
        expect(held(["<Space>", "z"])).toBe("␣z");
        expect(held([])).toBe("");
        expect(held(["z"])).toBe("");
        expect(held(["<Space>"], { insertMode: true })).toBe("");
    });
});

describe("the chords Space leads", () => {
    const mapped = new Map(SPACED);

    it("opens the folds of a kind with Space z and its letter, closing them with Shift and the letter, as vim's fold keys begin with z", () => {
        expect(["<Space>zf", "<Space>zb", "<Space>zu", "<Space>zc"].map((keys) => mapped.get(keys))).toEqual([
            "lupFoldOpen-file",
            "lupFoldOpen-body",
            "lupFoldOpen-lines",
            "lupFoldOpen-context",
        ]);
        expect(["<Space>zF", "<Space>zB", "<Space>zU", "<Space>zC"].map((keys) => mapped.get(keys))).toEqual([
            "lupFoldClose-file",
            "lupFoldClose-body",
            "lupFoldClose-lines",
            "lupFoldClose-context",
        ]);
        // Space z alone leads, doing nothing of its own, and Space f is no chord.
        expect([...mapped.keys()].filter((keys) => keys === "<Space>z" || keys.startsWith("<Space>f"))).toEqual([]);
    });

    it("parks an item with Space p, leaving it for later, which no other chord begins", () => {
        expect(mapped.get("<Space>p")).toBe("lupLater");
        expect([...mapped.keys()].filter((keys) => keys.startsWith("<Space>p"))).toEqual(["<Space>p"]);
        expect([...mapped.values()].filter((action) => action === "lupLater")).toHaveLength(1);
    });

    it("maps each chord the list of keys names, once, and leads each chord it names further", () => {
        expect(new Set(SPACED.map(([keys]) => keys)).size).toBe(SPACED.length);
        const listed = REVIEW_KEYS.flatMap((part) => part.keys)
            .flatMap((key) => key.keys.split(" "))
            .filter((keys) => keys.startsWith("␣"))
            .map((keys) => keys.replace("␣", "<Space>"));
        for (const keys of listed) {
            const leads = [...mapped.keys()].some((each) => each.startsWith(keys) && each !== keys);
            expect([keys, mapped.has(keys) || leads]).toEqual([keys, true]);
        }
    });
});
