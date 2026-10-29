import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import { US_INTERNATIONAL } from "./display.ts";
import type { Review } from "./review.ts";
import { DEMO_ITEM } from "./typing.ts";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    served = await demo({ size: 0 });
    dashboard = await open(served.url, { windowed: US_INTERNATIONAL });
    review = await dashboard.review();
});

afterEach(() => {
    expect(dashboard.thrown).toEqual([]);
});

afterAll(async () => {
    await dashboard?.close();
    await served?.close();
});

describe("a windowed Chromium on a virtual display of its own, on US-International", () => {
    it("takes a dead key as the keyboard sends it, composed with the next into the comment", async () => {
        await dashboard.page.evaluate(() => {
            const composed: string[] = [];
            Object.assign(globalThis, { composed });
            addEventListener("compositionend", (event) => composed.push(event.data), { capture: true });
        });
        await review.goTo(DEMO_ITEM);
        await dashboard.page.keyboard.press("j");
        await review.comment();
        await dashboard.display?.press(["c", "a", "f", "dead_acute", "e"]);
        await review.until("held the composed key", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.endsWith("café"));
        expect(await dashboard.page.evaluate(() => (globalThis as unknown as { composed: string[] }).composed)).toEqual(["é"]);
    });

    it("types text on the keys and levels the layout has it on, with no dead key", async () => {
        await dashboard.display?.type(" it's 'plain'");
        await review.until("held what was typed", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.endsWith("café it's 'plain'"));
    });
});
