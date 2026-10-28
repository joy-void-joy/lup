import { describe, expect, it } from "vitest";

import { LOOKS } from "./fixtures/looks";
import { ENDING, WRITING, chords, reviewKeys } from "./keys";

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
