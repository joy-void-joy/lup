import type { Route } from "playwright";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    served = await demo({ size: 0 });
    dashboard = await open(served.url);
    review = await dashboard.review();
    await review.holds("── @66 note · lup-impl/explore-auth");
    await review.settled(1500);
});

afterEach(async () => {
    await dashboard.page.unrouteAll({ behavior: "ignoreErrors" });
    expect(dashboard.thrown).toEqual([]);
});

afterAll(async () => {
    await dashboard?.close();
    await served?.close();
});

/** Return once the line under the review says `text`. */
const says = (text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".status")?.textContent?.includes(text) === true, text);

/** What the line under the review says. */
const status = async () => (await dashboard.page.locator(".status").first().innerText()).replace(/\s+/g, " ");

/** Mark the item whose header starts `header` read with Space d, and return once the reply says so and the draft's kept. */
async function read(header: string, number: number): Promise<void> {
    await review.goTo(header);
    await dashboard.keys.press([" ", "d"]);
    await says(`read @${number}`);
    // The draft is kept on the host 300 ms after it changes: what's held below is the send's own asking alone.
    await dashboard.page.waitForTimeout(600);
}

describe("Ctrl+Enter, in headless Chromium", () => {
    it("says there's nothing to send where nothing is drafted", async () => {
        await dashboard.keys.press(["Control+Enter"]);
        await says("Nothing to send: no reply drafted.");
    });

    it("says at once that the reply is being sent, and sends it once however often it's pressed while the host takes its time", async () => {
        await read("── @66 note", 66);
        // The host answering slowly, as it does for seconds just after the page loads at the operator's size.
        const held: Route[] = [];
        let sends = 0;
        await dashboard.page.route("**/api/ask", async (route) => {
            const body = route.request().postData() ?? "";
            if (body.includes('"inbox-send-draft"')) {
                sends += 1;
            }
            if (body.includes('"inbox-keep-draft"') && held.length === 0) {
                held.push(route);
                return;
            }
            await route.continue();
        });
        await dashboard.keys.press(["Control+Enter"]);
        await says("Sending your reply…");
        await dashboard.keys.press(["Control+Enter"]);
        await says("Still sending your reply");
        expect(held).toHaveLength(1);
        await held[0]!.continue();
        await dashboard.page.waitForFunction(() => document.querySelector(".bar .said")?.textContent?.startsWith("Sent: read @66") === true);
        await dashboard.page.waitForFunction(() => document.querySelector(".status .sending") === null);
        expect(sends).toBe(1);
        expect(await status()).not.toContain("read @66");
    });

    it("says the host can't be reached, the draft kept, and sends it at the next Ctrl+Enter", async () => {
        await read("── @62 note", 62);
        // The dashboard gone with the host service, as while lup restarts.
        await dashboard.page.route("**/api/ask", (route) => route.abort("connectionrefused"));
        await dashboard.keys.press(["Control+Enter"]);
        await says("Not sent, your draft kept: the dashboard can't be reached: the host is restarting, or out of reach.");
        expect(await status()).toContain("Your reply: read @62");
        // The dashboard there, the host behind it not.
        await dashboard.page.unrouteAll({ behavior: "ignoreErrors" });
        await dashboard.page.route("**/api/ask", (route) =>
            route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "lup's host service isn't listening" }) }),
        );
        await dashboard.keys.press(["Control+Enter"]);
        await says("Not sent, your draft kept: the host is restarting, or out of reach (lup's host service isn't listening).");
        await dashboard.page.unrouteAll({ behavior: "ignoreErrors" });
        await dashboard.keys.press(["Control+Enter"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".bar .said")?.textContent?.startsWith("Sent: read @62") === true);
        expect(await status()).not.toContain("Not sent");
    });
});
