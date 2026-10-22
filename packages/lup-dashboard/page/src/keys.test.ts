import { describe, expect, it } from "vitest";

import { CONVERSATION_KEYS, FOLD_KINDS, REVIEW_KEYS, barOf, chords, type ReviewPlace } from "./keys";

const shown = (place: ReviewPlace) => barOf(REVIEW_KEYS, place).map((key) => key.keys);

describe("the line of keys", () => {
    it("shows the keys that apply where the cursor is, in the list's order", () => {
        expect(shown("insert")).toEqual(["^⏎", "Esc", "Esc u"]);
        expect(shown("change")).toEqual(["␣a", "␣x", "␣d", "o", "c…", "␣c", "]c [c", "]n [n", "za"]);
        expect(shown("item")).toEqual(["␣d", "␣p", "o", "c…", "C", "␣c", "]] [[", "]n [n", "za"]);
        expect(shown("banner")).toEqual(["o ␣c", "]] [[", "]n [n", "␣h"]);
        expect(shown("written")).toEqual(["i a A", "u ^r", "]] [[", "]n [n"]);
        expect(shown("aside")).toEqual(["]] [[", "za", "zr zm", "zR zM", "␣z", "zj zk"]);
        expect(barOf(CONVERSATION_KEYS, "normal").map((key) => key.keys)).toEqual(["o", "c…", "␣c", "]] [[", "]n [n", "␣r", "za"]);
    });

    it("offers a flagged write's file reading it, never approving or declining it", () => {
        expect(shown("flagged")).toEqual(["␣d", "o", "c…", "]c [c", "]n [n", "za", "zr zm", "␣z"]);
        expect(shown("file")).toEqual(["␣a", "␣x", "o", "c…", "]c [c", "]n [n", "za", "zr zm", "␣z"]);
    });

    it("shows no key of insert mode outside it, and none of the others in it", () => {
        const places: ReviewPlace[] = ["written", "banner", "approvals", "item", "change", "file", "flagged", "aside", "nothing"];
        const writing = shown("insert");
        for (const place of places) {
            expect(shown(place).filter((key) => writing.includes(key) && key !== "^⏎")).toEqual([]);
        }
    });

    it("lists the clipboard's keys in each view, in the list alone", () => {
        for (const parts of [REVIEW_KEYS, CONVERSATION_KEYS]) {
            const part = parts.find((each) => each.title === "The clipboard");
            expect(part?.keys.map((key) => key.keys)).toEqual(['"+y "*y', '"+p "*p', "v… ^c"]);
            expect(part?.keys.every((key) => key.at.length === 0)).toBe(true);
        }
    });

    it("lists every key once a part, each saying what it does", () => {
        for (const parts of [REVIEW_KEYS, CONVERSATION_KEYS]) {
            for (const part of parts) {
                const keys = part.keys.map((key) => key.keys);
                expect(new Set(keys).size).toBe(keys.length);
                expect(part.keys.every((key) => key.does !== "" && key.short !== "")).toBe(true);
            }
        }
    });
});

describe("what may follow a chord", () => {
    const following = (pressed: string, place: ReviewPlace) =>
        chords(REVIEW_KEYS, pressed, place).map((each) => `${each.keys.join(" ")} ${each.short}`);

    it("lists the keys after Space, from the same table as the line of keys and the list, once each", () => {
        expect(following("␣", "item")).toEqual(["a approve", "x decline", "d read", "p park", "c on the item", "h agents", "z by kind"]);
        // Of two keys alike, the one that applies where the cursor is: on a banner, Space c writes to its agent.
        expect(following("␣", "banner")).toContain("c message");
        expect(chords(CONVERSATION_KEYS, "␣", "normal").map((each) => each.keys.join(" "))).toEqual(["c", "r", "h"]);
    });

    it("lists the keys after Space z, as vim's fold keys begin with z, each kind of fold's letter opening it and Shift and the letter closing it", () => {
        expect(following("␣z", "file")).toEqual(["f F files", "b B bodies", "u U unchanged lines", "c C context"]);
        expect(following("␣f", "file")).toEqual([]);
        expect(following("␣x", "file")).toEqual([]);
        expect(following("", "file")).toEqual([]);
    });

    it("names each kind of fold by a letter of its own, Space z's beside every one but the item's own", () => {
        const letters = FOLD_KINDS.map((each) => each.letter);
        expect(new Set(letters).size).toBe(letters.length);
        const spaced = following("␣z", "file").map((each) => each.split(" ")[0]);
        expect(spaced).toEqual(FOLD_KINDS.filter((each) => each.chord).map((each) => each.letter));
        // Space z leads the folds alone, the item left for later on Space p: z and p each follow Space once.
        expect(following("␣", "file").filter((each) => each.startsWith("z "))).toEqual(["z by kind"]);
        expect(following("␣", "item").filter((each) => each.startsWith("p ") || each.startsWith("z "))).toEqual(["p park", "z by kind"]);
    });
});
