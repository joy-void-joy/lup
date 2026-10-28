import { foldEffect, foldState, unfoldEffect } from "@codemirror/language";
import { EditorSelection, EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { Vim, type CodeMirrorV } from "@replit/codemirror-vim";
import { describe, expect, it } from "vitest";

import type { Folding } from "./comments";
import {
    begun,
    chordOf,
    closedAs,
    deadPressed,
    deadTyped,
    INDENTING,
    keptFolds,
    lettersOf,
    nextWritten,
    openedSaid,
    ownOf,
    pastFolds,
    scrollAfterKey,
    stopAt,
    pastHidden,
    reaching,
    rewritten,
    stepped,
    verbKeys,
    UNPRESSED,
    visit,
    went,
    type Dead,
    type History,
    type Pressed,
    type Typing,
} from "./editor";
import { LOOKS } from "./fixtures/looks";
import { reviewKeys } from "./keys";
import { lettered } from "./looks";

import { markdown, source, sourced } from "./markdown";

const REVIEW_KEYS = reviewKeys(LOOKS.kinds, LOOKS.verbs);

describe("vim's cursor and the marks the Markdown hides", () => {
    const comment = "a **comment** line";
    const text = ["# Title", "see **bold** here, *soft*", comment, ""].join("\n");
    const at = (needle: string, offset = 0) => text.indexOf(needle) + offset;
    const lineOf = (needle: string) => ({ from: at(needle), to: text.indexOf("\n", at(needle)) + 1 });
    const found = [
        source("text", [lineOf("# Title"), lineOf("see **bold**")]),
        source("comment", [{ from: at(comment), to: at(comment) + comment.length }]),
    ].flatMap((each) => (each === null ? [] : [each]));
    const laid = EditorState.create({ extensions: markdown() }).update({ changes: { from: 0, insert: text }, effects: sourced.of(found) }).state;
    /** What the cursor rests on once put at `head` from `was`: the character under it, or the text a selection from `anchor` covers; none where it stays. */
    const rests = (head: number, was: number, visual = false, anchor = head) => {
        const moved = pastHidden(laid.update({ selection: EditorSelection.single(anchor, head) }).state, was, visual);
        return moved === null ? null : moved.main.empty ? text[moved.main.head] : text.slice(moved.main.from, moved.main.to);
    };

    it("rests past a mark the way the cursor came, on the next character shown", () => {
        expect(rests(at("**bold"), at("**bold") - 1)).toBe("b");
        expect(rests(at("** here", 1), at("** here", 2))).toBe("d");
        expect(rests(at("see"), at("see") + 1)).toBeNull();
    });

    it("rests back where going on would leave the line, and on where coming back would, the line's end only in visual mode", () => {
        expect(rests(at("# Title"), at("Title"))).toBe("T");
        expect(rests(at("*soft*", 5), at("soft"))).toBe("t");
        expect(rests(at("*soft*", 6), at("soft"), true, at("soft"))).toBe("soft*\n");
    });

    it("moves a visual selection's head past the mark, the mark inside the selection whole, and keeps its anchor", () => {
        expect(rests(at("**bold**", 7), at("**bold**", 6), true, at("bold"))).toBe("bold** ");
        expect(rests(at("** here", 1), at("** here", 2), true, at("here") + 1)).toBe("d** h");
    });

    it("leaves the cursor in a comment, whose line shows its marks", () => {
        expect(rests(at("**comment"), at("**comment") - 1)).toBeNull();
    });
});

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

describe("motions past a closed fold, which counts as its summary line", () => {
    // `head` folds `h1` and `h2` away under it, from its end to `h2`'s; `h1` folds `h2` away, inside.
    const text = "head\nh1\nh2\nafter";
    const at = (needle: string, offset = 0) => text.indexOf(needle) + offset;
    const outer = { from: at("\nh1"), to: at("\nafter") };
    const inner = { from: at("\nh2"), to: at("\nafter") };
    const folded = (doc: string, ...folds: { from: number; to: number }[]) =>
        EditorState.create({ doc, extensions: [foldState] }).update({ effects: folds.map((each) => foldEffect.of(each)) }).state;
    const state = folded(text, outer);
    /** Where the cursor rests once a motion from `was` puts the selection at `head`, from `anchor` in visual mode: the text it's on, or the selection; none where it stays. */
    const rests = (on: EditorState, head: number, was: number, anchor = head) => {
        const moved = pastFolds(on, EditorSelection.single(anchor, head), was);
        const doc = on.doc.toString();
        return moved === null ? null : moved.main.empty ? doc.slice(moved.main.head) : doc.slice(moved.main.from, moved.main.to);
    };

    it("goes on past the fold onto the line after it, going on past the summary line, as `w` does", () => {
        expect(rests(state, at("h1", 1), at("head"))).toBe("after");
        expect(rests(state, at("h2"), at("ad"))).toBe("after");
    });

    it("comes back onto the summary line's last character, coming back into it, as `b` does, or where no line follows", () => {
        expect(rests(state, at("h2", 1), at("after"))).toBe("d\nh1\nh2\nafter");
        const last = "head\nh1\nh2";
        expect(rests(folded(last, { from: 4, to: last.length }), at("h2"), 0)).toBe("d\nh1\nh2");
        expect(rests(folded("\nh1\nafter", { from: 0, to: 3 }), 2, 6)).toBe("\nh1\nafter");
    });

    it("passes the outermost fold folded, and leaves the cursor where no closed fold hides it, its summary line's end and the fold's own end among them", () => {
        expect(rests(folded(text, outer, inner), at("h2", 1), at("head"))).toBe("after");
        expect(rests(folded(text, inner), at("h2", 1), at("head"))).toBe("after");
        expect(rests(state, at("ad", 1), at("head"))).toBeNull();
        expect(rests(state, outer.from, at("head"))).toBeNull();
        expect(rests(state, outer.to, at("after"))).toBeNull();
        expect(rests(state, at("after"), at("head"))).toBeNull();
    });

    it("keeps a visual selection's anchor, its head past the character the cursor is on where it runs forward, as vim draws it", () => {
        expect(rests(state, at("h1", 1), at("head"), at("ead"))).toBe("ead\nh1\nh2\na");
        // Selecting to the summary line's end, as `v$` does, stops on its last character, the line break being the fold's.
        expect(rests(state, outer.from + 1, at("ad"), 0)).toBe("head");
        expect(rests(state, at("h1"), at("after"), at("fter"))).toBe("d\nh1\nh2\na");
    });
});

describe("a jump's own scroll", () => {
    it("is asked once the key is done, after vim's scroll of the cursor into view, so it's the one CodeMirror takes", async () => {
        const asked: unknown[] = [];
        const view = { dispatch: (...specs: unknown[]) => void asked.push(...specs) };
        const top = EditorView.scrollIntoView(0, { y: "start" });
        scrollAfterKey(view, top);
        expect(asked).toEqual([]);
        // Vim ends its key by scrolling the cursor into view.
        const vims = { scrollIntoView: true };
        view.dispatch(vims);
        await Promise.resolve();
        expect(asked).toEqual([vims, { effects: top }]);
    });
});

describe("a key held down, or a page scroll, stopping at each file", () => {
    const text = ["a.py · changed", "a1", "a2", "b.py · created", "b1", "b2", "c.py · changed", "c1", ""].join("\n");
    const at = (needle: string, offset = 0) => text.indexOf(needle) + offset;
    const heads = [at("a.py"), at("b.py"), at("c.py")];
    const state = EditorState.create({ doc: text, extensions: [foldState] });

    it("stops on the first file's header after the line it left, up to where it lands, its own line passed", () => {
        expect(stopAt(state, heads, at("a2"), at("b1"))).toBe(at("b.py"));
        expect(stopAt(state, heads, at("a1", 1), at("c1"))).toBe(at("b.py"));
        expect(stopAt(state, heads, at("a2"), at("b.py", 3))).toBe(at("b.py"));
        // From a header, pressed afresh, it goes on to the next one.
        expect(stopAt(state, heads, at("b.py", 2), at("b2"))).toBeUndefined();
        expect(stopAt(state, heads, at("b1"), at("b2"))).toBeUndefined();
    });

    it("going back, stops at the top of the file it was in, then of the one before", () => {
        expect(stopAt(state, heads, at("b1"), at("a2"))).toBe(at("b.py"));
        expect(stopAt(state, heads, at("c1"), at("a1"))).toBe(at("c.py"));
        // From a header, it goes on into the file before, and stops at its top.
        expect(stopAt(state, heads, at("b.py", 4), at("a1"))).toBeUndefined();
        expect(stopAt(state, heads, at("b.py", 4), at("a.py", 2))).toBe(at("a.py"));
    });

    it("passes over a header a closed fold hides, the fold counting as its summary line", () => {
        const folded = state.update({ effects: foldEffect.of({ from: at("a2") - 1, to: at("b2") + 2 }) }).state;
        expect(stopAt(folded, heads, at("a1"), at("c1"))).toBe(at("c.py"));
    });
});

describe("a search or a jump to what a closed fold hides", () => {
    const text = "head\nh1\nh2\nafter";
    const outer = { from: 4, to: text.indexOf("\nafter") };
    const inner = { from: text.indexOf("\nh2"), to: outer.to };
    const state = EditorState.create({ doc: text, extensions: [foldState] }).update({ effects: [foldEffect.of(outer), foldEffect.of(inner)] }).state;

    it("opens the folds around where it goes, those alone, one ending there among them", () => {
        expect(reaching(state, text.indexOf("h2")).length).toBe(2);
        expect(reaching(state, text.indexOf("h1")).length).toBe(1);
        expect(reaching(state, outer.to).length).toBe(2);
        expect(reaching(state, outer.from).length).toBe(0);
        expect(reaching(state, text.indexOf("after")).length).toBe(0);
    });

    it("says how many folds it opened", () => {
        expect([openedSaid(1), openedSaid(2)]).toEqual(["opened a fold to reach it", "opened 2 folds to reach it"]);
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
        expect(held(["<Space>", "z", "F"])).toBe("␣zF");
        expect(held([])).toBe("");
        expect(held(["<Space>"], { insertMode: true })).toBe("");
    });

    it("says `zf` waiting for a kind's letter, and nothing of `z` alone, which begins vim's own keys too", () => {
        expect(held(["z", "f"])).toBe("zf");
        expect(held(["z"])).toBe("");
        expect(held(["z", "f"], { visualMode: true })).toBe("");
    });
});

describe("the chords Space leads", () => {
    const LETTERS = lettersOf(LOOKS.kinds);
    const VERBS = verbKeys(LOOKS.verbs);
    const mapped = new Map([...VERBS, ...LETTERS.filter(([keys]) => keys.startsWith("<Space>"))]);
    // The kind of fold each letter's action finds as it's pressed.
    const kindOfAction = (action: string | undefined) => (action === undefined ? undefined : `${action.split("-")[0]}-${lettered(action.split("-")[1] ?? "")?.name}`);

    it("opens the folds of a kind with Space z f and its letter, closing them with Space z F and the letter, as vim's fold keys begin with z", () => {
        expect(["<Space>zff", "<Space>zfb", "<Space>zfu", "<Space>zfc", "<Space>zfs"].map((keys) => kindOfAction(mapped.get(keys)))).toEqual([
            "lupFoldOpen-file",
            "lupFoldOpen-body",
            "lupFoldOpen-lines",
            "lupFoldOpen-context",
            "lupFoldOpen-since",
        ]);
        expect(["<Space>zFf", "<Space>zFb", "<Space>zFu", "<Space>zFc", "<Space>zFs"].map((keys) => kindOfAction(mapped.get(keys)))).toEqual([
            "lupFoldClose-file",
            "lupFoldClose-body",
            "lupFoldClose-lines",
            "lupFoldClose-context",
            "lupFoldClose-since",
        ]);
        // Space z, Space z f and Space z F lead, doing nothing of their own; a kind's letter right after Space z, Shift
        // and the letter among them, and Space f, are no chord.
        const keys = [...mapped.keys()];
        expect(keys.filter((each) => ["<Space>z", "<Space>zf", "<Space>zF"].includes(each) || each.startsWith("<Space>f"))).toEqual([]);
        expect(keys.filter((each) => each.startsWith("<Space>z") && !each.startsWith("<Space>zf") && !each.startsWith("<Space>zF"))).toEqual([]);
    });

    it("closes the fold of a kind the cursor is in with z f and its letter, every kind's, the item's own among them", () => {
        const around = new Map(LETTERS.filter(([keys]) => keys.startsWith("zf")));
        expect([...around.keys()]).toEqual(LOOKS.kinds.map((each) => `zf${each.letter}`));
        expect(["zfi", "zff", "zfu", "zfe", "zfk", "zfd"].map((keys) => kindOfAction(around.get(keys)))).toEqual([
            "lupFoldAround-item",
            "lupFoldAround-file",
            "lupFoldAround-lines",
            "lupFoldAround-earlier",
            "lupFoldAround-calls",
            "lupFoldAround-call",
        ]);
        // No trace drawer any more, so no `r`.
        expect(around.has("zfr")).toBe(false);
        // Each is in the list of keys, and plain zF stays vim's, unmapped.
        const listed = new Set(REVIEW_KEYS.flatMap((part) => part.keys).flatMap((key) => key.keys.split(" ")));
        expect([...around.keys()].every((keys) => listed.has(keys))).toBe(true);
        expect([...around.keys(), ...VERBS.map(([keys]) => keys)].some((keys) => keys.startsWith("zF"))).toBe(false);
    });

    it("gives each verb Space and its key, the core's and those the modules declare, and no key of vim's", () => {
        expect(VERBS).toEqual([
            ["<Space>d", "lupVerb-done"],
            ["<Space>x", "lupVerb-decline"],
            ["<Space>s", "lupVerb-send"],
            ["<Space>c", "lupVerb-comment"],
            ["<Space>h", "lupVerb-hold"],
            ["<Space>p", "lupVerb-pause"],
        ]);
        // Space a and Space A answered at once before the verbs; they're gone, and `h` is vim's again.
        expect(["<Space>a", "<Space>A", "h"].filter((keys) => mapped.has(keys))).toEqual([]);
    });

    it("maps each chord the list of keys names, once, and leads each chord it names further", () => {
        expect(new Set(VERBS.map(([keys]) => keys)).size).toBe(VERBS.length);
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

describe("Tab and Shift+Tab in a comment", () => {
    // What vim names a browser's keydown of Tab, with Shift or without.
    const named = (shiftKey: boolean) =>
        Vim.vimKeyFromEvent({ key: "Tab", code: "Tab", shiftKey, ctrlKey: false, altKey: false, metaKey: false } as KeyboardEvent);

    it("are vim's own Ctrl+T and Ctrl+D, under the names vim gives the keys a browser sends it", () => {
        expect(INDENTING).toEqual([
            [named(false), "<C-t>"],
            [named(true), "<C-d>"],
        ]);
    });

    it("are in the list of keys, just before Ctrl+T and Ctrl+D", () => {
        const writing = REVIEW_KEYS.find((part) => part.title === "Writing a comment")?.keys.map((key) => key.keys) ?? [];
        expect(writing).toContain("Tab ⇧Tab");
        expect(writing.indexOf("^t ^d")).toBe(writing.indexOf("Tab ⇧Tab") + 1);
    });
});
