// What comes to the demo as it runs (`docs/dashboard.md`, *The demo*), through the host's own handlers: a question
// arriving from an agent, in the thread they work in, two writes to a branch, each flagged, and a landing done waiting once
// the file it waits on is answered. Each waits on what it checks, the demo's stand-in agents taking their seconds: fewer here
// than the demo's defaults, which leave a person time to watch, and still after the page has come to rest.
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";
import { DEMO_ITEM } from "./typing.ts";

/** The fix-clock subagent's drawer as the landing holds its file. */
const HELD = "since you approved · 1 held at landing";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    served = await demo({ size: 0, arrives: 3, grows: 4 });
    dashboard = await open(served.url);
    review = await dashboard.review();
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

/** Return once the top line says `text`. */
const said = (text: string) => dashboard.page.waitForFunction((text) => document.querySelector(".bar .said")?.textContent?.includes(text) === true, text);

describe("what comes to the demo as it runs, in headless Chromium", () => {
    it("brings a late question into the thread its asker works in, with its moment", async () => {
        await review.holds("── @61 question · new · ");
        await review.holds("→ called mcp__lup__ask · this item");
        // Counted on the row of the thread they work in, as what stops on the operator.
        await dashboard.page.waitForFunction(() => [...document.querySelectorAll(".list-buffer .cm-line")].some((each) => (each.textContent ?? "").includes("@transcript-reader") && (each.textContent ?? "").includes("◆2")));
    });

    it("brings two writes to a branch into its drawer, each flagged", async () => {
        await review.holds("since you approved · 2 flagged");
    });

    it("holds a file at landing in its writer's drawer, and ends the landing's wait once it's marked reviewed", async () => {
        await review.holds("landing `fix-clock` on `dev` waits on 1 file in lup-impl/fix-clock's drawer");
        await review.goTo(HELD);
        await dashboard.keys.press([" ", "d"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("files reviewed") !== true);
        await dashboard.keys.press(["Control+Enter"]);
        await said("Sent");
        await review.until("end the landing's wait", (view) => !view.state.doc.toString().includes("landing `fix-clock` on `dev` waits on 1 file"));
        expect(await review.text()).not.toContain(HELD);
    });
});
