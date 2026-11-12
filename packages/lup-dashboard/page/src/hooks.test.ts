import { describe, expect, it } from "vitest";

import { paced, rewatching, type Paced } from "./hooks";

describe("what the host answers, taken no more often than every so often", () => {
    it("takes a value at once where it's been that long, else holds what it shows until the value is due", () => {
        let kept: Paced<string> = { shown: "a", at: 0 };
        const taken = (value: string, now: number) => {
            const next = paced(kept, value, now, 250);
            kept = next.paced;
            return [kept.shown, next.due];
        };
        expect(taken("b", 1000)).toEqual(["b", null]);
        expect(taken("c", 1100)).toEqual(["b", 150]);
        expect(taken("d", 1200)).toEqual(["b", 50]);
        expect(taken("d", 1250)).toEqual(["d", null]);
        expect(taken("d", 1260)).toEqual(["d", null]);
    });

    it("takes nothing as time alone passes, in a render nothing it depends on asked for, its timer due at once", () => {
        const kept: Paced<string> = { shown: "a", at: 1000 };
        expect(paced(kept, "b", 1100, 250, false)).toEqual({ paced: kept, due: 150 });
        expect(paced(kept, "b", 2000, 250, false)).toEqual({ paced: kept, due: 0 });
        expect(paced(kept, "a", 2000, 250, false)).toEqual({ paced: kept, due: null });
        expect(paced(kept, "b", 2000, 250).paced).toEqual({ shown: "b", at: 2000 });
    });
});

describe("the views watched", () => {
    it("starts watching what's newly asked and stops what's no longer, leaving every other view watched as it was", () => {
        expect(rewatching(new Set(), new Set(["a", "b"]))).toEqual({ start: ["a", "b"], stop: [] });
        // A fold's view read as it opens, then let go as it closes: the drawers' own asked nothing again.
        expect(rewatching(new Set(["a", "b"]), new Set(["a", "b", "call"]))).toEqual({ start: ["call"], stop: [] });
        expect(rewatching(new Set(["a", "b", "call"]), new Set(["a", "b"]))).toEqual({ start: [], stop: ["call"] });
        expect(rewatching(new Set(["a"]), new Set(["a"]))).toEqual({ start: [], stop: [] });
    });
});
