import { describe, expect, it } from "vitest";

import { CONVERSATION_KEYS, REVIEW_KEYS, barOf, type ReviewPlace } from "./keys";

const shown = (place: ReviewPlace) => barOf(REVIEW_KEYS, place).map((key) => key.keys);

describe("the line of keys", () => {
    it("shows the keys that apply where the cursor is, in the list's order", () => {
        expect(shown("insert")).toEqual(["^⏎", "Esc", "Esc u"]);
        expect(shown("change")).toEqual(["␣a", "␣x", "␣d", "o", "c…", "␣c", "]c [c", "]n [n", "za"]);
        expect(shown("item")).toEqual(["␣d", "␣z", "o", "c…", "C", "␣c", "]] [[", "]n [n", "za"]);
        expect(shown("banner")).toEqual(["o ␣c", "]] [[", "]n [n", "␣h"]);
        expect(shown("written")).toEqual(["i a A", "u ^r", "]] [[", "]n [n"]);
        expect(shown("aside")).toEqual(["]] [[", "za", "zr zm", "zR zM", "␣f", "zj zk"]);
        expect(barOf(CONVERSATION_KEYS, "normal").map((key) => key.keys)).toEqual(["o", "c…", "␣c", "]] [[", "]n [n", "␣r", "za"]);
    });

    it("offers a flagged write's file reading it, never approving or declining it", () => {
        expect(shown("flagged")).toEqual(["␣d", "o", "c…", "]c [c", "]n [n", "za", "zr zm", "␣f"]);
        expect(shown("file")).toEqual(["␣a", "␣x", "o", "c…", "]c [c", "]n [n", "za", "zr zm", "␣f"]);
    });

    it("shows no key of insert mode outside it, and none of the others in it", () => {
        const places: ReviewPlace[] = ["written", "banner", "approvals", "item", "change", "file", "flagged", "aside", "nothing"];
        const writing = shown("insert");
        for (const place of places) {
            expect(shown(place).filter((key) => writing.includes(key) && key !== "^⏎")).toEqual([]);
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
