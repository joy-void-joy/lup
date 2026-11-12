import { describe, expect, it } from "vitest";

import { events } from "./keys.ts";
import { percentiles } from "./timing.ts";
import { common } from "./typing.ts";

describe("a key as the DevTools protocol sends it, on a US keyboard", () => {
    it("types a letter, a digit or a space as itself, with its code", () => {
        expect(events("a")[0]).toEqual({ type: "keyDown", modifiers: 0, key: "a", code: "KeyA", windowsVirtualKeyCode: 65, text: "a", unmodifiedText: "a" });
        expect(events("7")[0]).toMatchObject({ code: "Digit7", text: "7" });
        expect(events(" ")[0]).toMatchObject({ code: "Space", text: " " });
    });

    it("holds Shift for a capital or a shifted character, on the key that types it", () => {
        expect(events("A")[0]).toMatchObject({ modifiers: 8, key: "A", code: "KeyA", text: "A" });
        expect(events("!")[0]).toMatchObject({ modifiers: 8, key: "!", code: "Digit1", text: "!" });
        expect(events('"')[0]).toMatchObject({ modifiers: 8, code: "Quote", text: '"' });
    });

    it("types nothing for a key held with Control, or a key that types nothing", () => {
        const [down, up] = events("Control+d");
        expect(down).toEqual({ type: "rawKeyDown", modifiers: 2, key: "d", code: "KeyD", windowsVirtualKeyCode: 68 });
        expect(up).toEqual({ type: "keyUp", modifiers: 2, key: "d", code: "KeyD", windowsVirtualKeyCode: 68 });
        expect(events("Escape")[0]).toMatchObject({ type: "rawKeyDown", code: "Escape" });
        expect(events("Shift+Tab")[0]).toMatchObject({ type: "rawKeyDown", modifiers: 8, code: "Tab" });
        expect(events("Control++")[0]).toMatchObject({ modifiers: 10, code: "Equal" });
    });

    it("sends a character no key types as its text alone, and refuses a name it doesn't know", () => {
        expect(events("é")[0]).toMatchObject({ type: "keyDown", key: "é", code: "", text: "é" });
        expect(() => events("Hyper+a")).toThrow("isn't a modifier");
        expect(() => events("Launch")).toThrow("isn't a key");
    });
});

describe("what a measure says", () => {
    it("takes the median, the 90th percentile and the most by the nearest rank", () => {
        expect(percentiles([5, 1, 4, 2, 3, 10, 9, 8, 7, 6])).toEqual({ median: 6, p90: 10, most: 10 });
        expect(percentiles([])).toBeNull();
    });

    it("counts the keys typed that landed in order, wherever some were lost", () => {
        expect(common("hello", "hello")).toBe(5);
        expect(common("hello", "hllo")).toBe(4);
        expect(common("hello", "")).toBe(0);
        expect(common("abc", "xaybzc")).toBe(3);
    });
});
