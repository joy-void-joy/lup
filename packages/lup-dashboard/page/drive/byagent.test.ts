// The review as the page opens it, grouped by agent, and grouped by thread only where its address asks (`docs/dashboard.md`,
// *The review*). The other tests drive the threads' layout, which `demo` asks for unless told otherwise.
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";
import { DEMO_ITEM } from "./typing.ts";

/** A line opening a section of the threads' layout, as it writes one. */
const SECTION = /^(waiting on you|new|open|to read|settled|agents) · /;

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    served = await demo({ size: 0, byAgent: true });
    dashboard = await open(served.url);
    review = await dashboard.review();
    await review.holds(DEMO_ITEM);
    await review.settled();
});

afterAll(async () => {
    await dashboard?.close();
    await served?.close();
});

describe("the review grouped by agent", () => {
    it("draws no section of the threads' layout, and throws nothing", async () => {
        const lines = (await review.text()).split("\n");
        expect(lines.filter((each) => SECTION.test(each))).toEqual([]);
        expect(dashboard.thrown).toEqual([]);
    });

    it("asks the host for no threads", async () => {
        const asked = await dashboard.page.evaluate(() => new URLSearchParams(location.search).has("threads"));
        expect(asked).toBe(false);
    });
});
