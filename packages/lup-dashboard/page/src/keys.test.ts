import { describe, expect, it } from "vitest";

import { FOLD_KINDS, REVIEW_KEYS, barOf, chords, type ReviewPlace } from "./keys";

const shown = (place: ReviewPlace) => barOf(REVIEW_KEYS, place).map((key) => key.keys);

describe("the line of keys", () => {
    it("shows the keys that apply where the cursor is, in the list's order", () => {
        expect(shown("insert")).toEqual(["^⏎", "Esc", "Esc u"]);
        expect(shown("change")).toEqual(["␣a", "␣x", "␣d", "o", "c…", "␣c", "]a [a", "]c [c", "]f [f", "]n [n", "za"]);
        expect(shown("item")).toEqual(["␣d", "␣p", "o", "c…", "C", "␣c", "]] [[", "]a [a", "]n [n", "za"]);
        expect(shown("banner")).toEqual(["h", "o ␣c", "]] [[", "]a [a", "]n [n", "␣z"]);
        expect(shown("written")).toEqual(["i a A", "u ^r", "]] [[", "]a [a", "]n [n"]);
        expect(shown("aside")).toEqual(["]] [[", "]a [a", "za", "zr zm", "zR zM", "zf", "␣z", "zj zk"]);
        expect(shown("drawer")).toEqual(["]] [[", "]a [a", "za", "zr zm", "zR zM", "␣z", "zj zk"]);
        expect(shown("words")).toEqual(["o", "c…", "C", "]n [n", "za"]);
    });

    it("lists the jump to what's to answer beside the jump to any item, and shows it where either applies", () => {
        const moving = REVIEW_KEYS.find((part) => part.title === "Moving");
        const keys = moving?.keys.map((key) => key.keys) ?? [];
        expect(keys.indexOf("]a [a")).toBe(keys.indexOf("]] [[") + 1);
        const jump = moving?.keys.find((key) => key.keys === "]a [a");
        expect(jump?.short).toBe("to answer");
        expect(jump?.at).toEqual(["banner", "approvals", "item", "change", "aside", "written", "drawer"]);
        expect(shown("since")).not.toContain("]a [a");
    });

    it("offers a file since the operator approved marking it reviewed and every file shown reviewed, never declining", () => {
        expect(shown("since")).toEqual(["␣a", "␣A", "o", "c…", "]c [c", "]f [f", "]n [n", "za", "zr zm", "zf", "␣z"]);
        // A reviewed file's line takes no comment.
        expect(shown("reviewed")).toEqual(["␣a", "␣A", "]c [c", "]f [f", "]n [n", "za", "zr zm", "zf", "␣z"]);
        expect(shown("file")).toEqual(["␣a", "␣x", "o", "c…", "]c [c", "]f [f", "]n [n", "za", "zr zm", "zf", "␣z"]);
    });

    it("shows no key of insert mode outside it, and none of the others in it", () => {
        const places: ReviewPlace[] = ["written", "banner", "approvals", "item", "change", "file", "drawer", "words", "since", "reviewed", "aside", "nothing"];
        const writing = shown("insert");
        for (const place of places) {
            expect(shown(place).filter((key) => writing.includes(key) && key !== "^⏎")).toEqual([]);
        }
    });

    it("lists the clipboard's keys in the list alone", () => {
        const part = REVIEW_KEYS.find((each) => each.title === "The clipboard");
        expect(part?.keys.map((key) => key.keys)).toEqual(['"+y "*y', '"+p "*p', "v… ^c"]);
        expect(part?.keys.every((key) => key.at.length === 0)).toBe(true);
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
    const following = (pressed: string, place: ReviewPlace) =>
        chords(REVIEW_KEYS, pressed, place).map((each) => `${each.keys.join(" ")} ${each.short}`);

    it("lists the keys after Space, from the same table as the line of keys and the list, once each", () => {
        expect(following("␣", "item")).toEqual(["a approve", "x decline", "d read", "p park", "A all reviewed", "c on the item", "z by kind"]);
        // Of two keys alike, the one that applies where the cursor is: on a banner, Space c writes to its agent.
        expect(following("␣", "banner")).toContain("c message");
    });

    it("lists the keys after Space z, f opening by kind and F closing, then each kind of fold's letter, as vim's fold keys begin with z", () => {
        expect(following("␣z", "file")).toEqual(["f open by kind", "F close by kind"]);
        const kinds = [
            "t the tasks",
            "s since you approved",
            "v the conversation",
            "f files",
            "e earlier exchanges",
            "b bodies",
            "u unchanged lines",
            "k runs of calls",
            "c context",
            "d calls' input and output",
        ];
        expect(following("␣zf", "file")).toEqual(kinds);
        expect(following("␣zF", "file")).toEqual(kinds);
        expect(following("␣f", "file")).toEqual([]);
        expect(following("␣x", "file")).toEqual([]);
        expect(following("", "file")).toEqual([]);
    });

    it("lists the keys after z f, each kind of fold's letter closing the one the cursor is in, the item's own among them", () => {
        expect(following("zf", "file")).toEqual([
            "i the item",
            "t the tasks",
            "s since you approved",
            "v the conversation",
            "f the file",
            "e the earlier exchange",
            "b the body",
            "u the unchanged lines",
            "k the run of calls",
            "c the context",
            "d the call's input and output",
        ]);
    });

    it("names each kind of fold by a letter of its own, Space z's beside every one but the item's own", () => {
        const letters = FOLD_KINDS.map((each) => each.letter);
        expect(new Set(letters).size).toBe(letters.length);
        const spaced = following("␣zf", "file").map((each) => each.split(" ")[0]);
        expect(spaced).toEqual(FOLD_KINDS.filter((each) => each.chord).map((each) => each.letter));
        expect(following("zf", "file").map((each) => each.split(" ")[0])).toEqual(letters);
        // Space z leads the folds alone, the item left for later on Space p: z and p each follow Space once.
        expect(following("␣", "file").filter((each) => each.startsWith("z "))).toEqual(["z by kind"]);
        expect(following("␣", "item").filter((each) => each.startsWith("p ") || each.startsWith("z "))).toEqual(["p park", "z by kind"]);
    });
});
