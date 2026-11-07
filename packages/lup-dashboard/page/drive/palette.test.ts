// A palette is over the page wherever the page is: whole in the view, near its top, with the page behind it where it
// was, and the review has the keys again as it closes. cmdk's dialog puts the palette after the page rather than in the
// overlay, so nothing else places it.
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import { DEMO_ITEM } from "./typing.ts";

let served: Demo;
let dashboard: Dashboard;

beforeAll(async () => {
    served = await demo({ size: 0 });
    dashboard = await open(served.url);
    const review = await dashboard.review();
    await review.holds(DEMO_ITEM);
    await review.settled(1500);
});

afterEach(() => {
    expect(dashboard.thrown).toEqual([]);
});

afterAll(async () => {
    await dashboard?.close();
    await served?.close();
});

describe("a palette, in headless Chromium", () => {
    it.each([
        ["the agents' palette, Ctrl+K", ["Control+k"], ".palette"],
        ["what was said, whole, g<", ["g", "<"], ".whole-palette"],
    ])("%s is whole in the view, near its top, the page behind it not scrolled, and gives the keyboard back", async (_name, keys, selector) => {
        await dashboard.keys.press(keys);
        await dashboard.page.waitForSelector(selector);
        const placed = await dashboard.page.evaluate((selector) => {
            const box = document.querySelector(selector)?.getBoundingClientRect();
            return {
                top: box?.top ?? -1,
                bottom: box?.bottom ?? -1,
                left: box?.left ?? -1,
                right: box?.right ?? -1,
                width: window.innerWidth,
                height: window.innerHeight,
                scrolled: window.scrollY,
            };
        }, selector);
        expect(placed.scrolled).toBe(0);
        expect(placed.top).toBeGreaterThan(0);
        expect(placed.top).toBeLessThan(placed.height / 4);
        expect(placed.bottom).toBeLessThanOrEqual(placed.height);
        expect(Math.abs(placed.left - (placed.width - placed.right))).toBeLessThanOrEqual(1);
        await dashboard.keys.press(["Escape"]);
        await dashboard.page.waitForSelector(selector, { state: "detached" });
        // The review has the keys again: a palette closed with them elsewhere would leave every key after it going nowhere.
        await dashboard.page.waitForFunction(() => document.activeElement?.closest(".review-buffer") != null, undefined, { polling: 20 });
    });
});
