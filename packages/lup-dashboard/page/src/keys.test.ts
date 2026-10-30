import { describe, expect, it } from "vitest";

import { LOOKS } from "./fixtures/looks";
import { ENDING, WRITING, chords, keyKind, measuringSaid, reviewKeys, runOf, searched, vimKeys, writtenKey, writtenVim } from "./keys";

const REVIEW_KEYS = reviewKeys(LOOKS.kinds, LOOKS.verbs);
const KINDS = LOOKS.kinds;

describe("the palette's table", () => {
    it("answers with each verb the looks declare, Space and its key, in their order, then undo and send", () => {
        const answering = REVIEW_KEYS.find((part) => part.title === "Answering")?.keys.map((key) => `${key.keys} ${key.short}`);
        expect(answering).toEqual(["␣d done", "␣x decline", "␣s send to", "␣c comment", "␣h hold", "␣p pause", "u undo", "^⏎ send"]);
        // Pause says it isn't built, as its key does where it's pressed.
        expect(REVIEW_KEYS.flatMap((part) => part.keys).find((key) => key.keys === "␣p")?.does).toContain("not built yet");
    });

    it("lists no key that changes meaning by where the cursor is: h, Space a and Space A are gone", () => {
        const keys = REVIEW_KEYS.flatMap((part) => part.keys).flatMap((key) => key.keys.split(" "));
        expect(keys.filter((each) => ["h", "␣a", "␣A"].includes(each))).toEqual([]);
    });

    it("says, while a comment is written, the keys that end it", () => {
        const writing = WRITING.flatMap((part) => part.keys).filter((key) => ENDING.includes(key.keys));
        expect(writing.map((key) => `${key.keys} ${key.short}`)).toEqual(["^⏎ end it", "Esc end it here", "Esc u drop it"]);
    });

    it("lists the clipboard's keys", () => {
        const part = REVIEW_KEYS.find((each) => each.title === "The clipboard");
        expect(part?.keys.map((key) => key.keys)).toEqual(['"+y "*y', '"+p "*p', "v… ^c"]);
    });

    it("lists every key once a part, each saying what it does", () => {
        for (const part of REVIEW_KEYS) {
            const keys = part.keys.map((key) => key.keys);
            expect(new Set(keys).size).toBe(keys.length);
            expect(part.keys.every((key) => key.does !== "" && key.short !== "")).toBe(true);
        }
    });
});

describe("what may follow a chord", () => {
    const following = (pressed: string) => chords(REVIEW_KEYS, pressed).map((each) => `${each.keys.join(" ")} ${each.short}`);

    it("lists the keys after Space, from the same table as the line of keys and the palette, once each: each verb, then the fold-wise selections", () => {
        expect(following("␣")).toEqual(["d done", "x decline", "s send to", "c comment", "h hold", "p pause", "f select by kind", "F select every one"]);
    });

    it("lists the keys after Space f and Space F, each kind of fold's letter but the item's own", () => {
        const kinds = [
            "a agents' groups",
            "t the tasks",
            "s since you approved",
            "v the conversation",
            "f files",
            "p branches",
            "l roles",
            "e earlier exchanges and steps",
            "b bodies",
            "u unchanged lines",
            "k runs of calls",
            "c context",
            "m items' text",
            "d calls' input and output",
        ];
        expect(following("␣f")).toEqual(kinds);
        expect(following("␣F")).toEqual(kinds);
        expect(following("␣z")).toEqual([]);
        expect(following("␣x")).toEqual([]);
        expect(following("")).toEqual([]);
    });

    it("lists the keys after z f, each kind of fold's letter closing the one the cursor is in, the item's own among them", () => {
        expect(following("zf")).toEqual([
            "a the agent's group",
            "i the item",
            "t the tasks",
            "s since you approved",
            "v the conversation",
            "f the file",
            "p the branch",
            "l the role",
            "e what came earlier",
            "b the body",
            "u the unchanged lines",
            "k the run of calls",
            "c the context",
            "m the item's text",
            "d the call's input and output",
        ]);
    });

    it("names each kind of fold by a letter of its own, Space f's beside every one but the item's own", () => {
        const letters = KINDS.map((each) => each.letter);
        expect(new Set(letters).size).toBe(letters.length);
        expect(following("␣f").map((each) => each.split(" ")[0])).toEqual(KINDS.filter((each) => each.chord).map((each) => each.letter));
        expect(following("zf").map((each) => each.split(" ")[0])).toEqual(letters);
        // Space f and Space F lead the fold-wise selections alone: f and F each follow Space once.
        expect(following("␣").filter((each) => each.startsWith("f ") || each.startsWith("F "))).toEqual(["f select by kind", "F select every one"]);
    });
});

describe("what the palette runs", () => {
    const run = (title: string, keys: string) => {
        const key = REVIEW_KEYS.find((part) => part.title === title)?.keys.find((each) => each.keys === keys);
        return key === undefined ? "no key" : runOf(REVIEW_KEYS, title, key);
    };

    it("names each key pressed as vim's keymap does, Space and Ctrl among them, and none for what's no plain sequence", () => {
        expect(vimKeys("␣d")).toEqual(["<Space>", "d"]);
        expect(vimKeys("]]")).toEqual(["]", "]"]);
        expect(vimKeys("^d")).toEqual(["<C-d>"]);
        expect(vimKeys("\\")).toEqual(["\\"]);
        expect([vimKeys("c…"), vimKeys("^⏎"), vimKeys("◆"), vimKeys("")]).toEqual([null, null, null, null]);
    });

    it("runs a key's first whole way of being pressed, never one leading a chord, nor a comment's or the clipboard's", () => {
        expect(run("Answering", "␣d")).toEqual(["<Space>", "d"]);
        expect(run("Answering", "^⏎")).toBeNull();
        expect(run("Moving", "]] [[")).toEqual(["]", "]"]);
        expect(run("Moving", "^d ^u ^f ^b")).toEqual(["<C-d>"]);
        expect(run("Folds", "zR zM")).toEqual(["z", "R"]);
        expect(run("Folds", "zf")).toBeNull();
        expect(run("Folds", "␣f")).toBeNull();
        expect(run("Folds", "zff")).toEqual(["z", "f", "f"]);
        expect(run("The clipboard", '"+y "*y')).toBeNull();
        expect(run("Writing a comment", "Esc")).toBeNull();
    });
});

describe("searching the palette", () => {
    it("finds an entry by every word, those in its keys and short name first, never by letters scattered through its words", () => {
        const pause = searched("␣p pause · Answering", "next item", ["pause the agent at their next call until they're resumed"]);
        const items = searched("]] [[ items · Moving", "next item", ["next and previous item, on its first line that matters"]);
        expect(pause).toBe(0);
        expect(items).toBeGreaterThan(0.5);
        expect(searched("]f [f files · Moving", "next item", ["next and previous file's header"])).toBe(0);
        expect(searched("anything", "")).toBe(1);
    });
});

describe("the kind of each key, as the page's timings group them", () => {
    const kind = (...pressed: string[]) => keyKind(REVIEW_KEYS, pressed);

    it("is the part of the table holding the keys whole: a verb, a motion, a fold, the palette", () => {
        expect([kind("␣", "d"), kind("u"), kind("^⏎")]).toEqual(["verb", "verb", "verb"]);
        expect([kind("]", "]"), kind("^d"), kind("/"), kind("^k")]).toEqual(["motion", "motion", "motion", "motion"]);
        expect([kind("z", "a"), kind("z", "f", "i"), kind("␣", "f"), kind("z", "j")]).toEqual(["fold", "fold", "fold", "fold"]);
        expect([kind("?"), kind("o"), kind("\\")]).toEqual(["palette", "other", "other"]);
    });

    it("is vim's own motion where the table leaves it to vim, a character after f and t among them", () => {
        expect([kind("j"), kind("g", "g"), kind("$"), kind("f", "x"), kind("z", "z"), kind("↓")]).toEqual(Array(6).fill("motion"));
    });

    it("is the part of a key a chord begins, as Space a verb and z a fold", () => {
        expect([kind("␣"), kind("z"), kind("]"), kind("f")]).toEqual(["verb", "fold", "motion", "motion"]);
    });

    it("is other for the rest", () => {
        expect([kind("Esc"), kind("q"), kind("3")]).toEqual(["other", "other", "other"]);
    });

    it("reads a key going down, and a key vim holds, as the list writes them", () => {
        expect([" ", "j", "Enter", "ArrowDown"].map((key) => writtenKey({ key, ctrlKey: false, metaKey: false }))).toEqual(["␣", "j", "⏎", "↓"]);
        expect([writtenKey({ key: "D", ctrlKey: true, metaKey: false }), writtenKey({ key: "Enter", ctrlKey: true, metaKey: false })]).toEqual(["^d", "^⏎"]);
        expect(["<Space>", "z", "<C-d>"].map(writtenVim)).toEqual(["␣", "z", "^d"]);
    });
});

describe("what the palette says of the page's timings", () => {
    it("says it's measuring and how to switch it off, or that it's switched off and how to switch it on", () => {
        expect(measuringSaid(true).does).toMatch(/^measuring how long each key takes.*never what's typed or shown; ⏎ switches it off in this browser$/);
        expect(measuringSaid(false).does).toMatch(/switched off in this browser; ⏎ switches it on again$/);
    });
});
