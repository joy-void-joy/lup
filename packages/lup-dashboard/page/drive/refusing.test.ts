// The demo runs the host's own rules (`docs/dashboard.md`, *The demo*): a draft the host refuses is refused here, the
// page saying the host's words and keeping the draft; and what the host drops and says of what's drafted on an item no
// reply answers, it drops and says here. Each draft is kept on the host as a page from before would have left it, since
// this page's own keys don't make it, and the page loaded on it.
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";

let served: Demo;
let dashboard: Dashboard;

beforeAll(async () => {
    served = await demo({ size: 0 });
    dashboard = await open(served.url);
});

afterEach(() => {
    expect(dashboard.thrown).toEqual([]);
});

afterAll(async () => {
    await dashboard?.close();
    await served?.close();
});

/** Keep `draft` on the host, and load the page on it, the review at rest. */
async function loadedOn(draft: { done?: number[]; declined?: number[] }): Promise<void> {
    await dashboard.page.evaluate(async (draft) => {
        const answer = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "inbox-keep-draft", draft }) });
        if (!answer.ok) {
            throw new Error(await answer.text());
        }
    }, draft);
    await dashboard.page.reload();
    const review = await dashboard.review();
    await review.holds("── @66 note · lup-impl/explore-auth");
    await review.settled(1500);
}

/** Return once the line under the review says `text`. */
const says = (text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".status")?.textContent?.includes(text) === true, text);

/** Return once the top line says `text`. */
const said = (text: string) => dashboard.page.waitForFunction((text) => document.querySelector(".bar .said")?.textContent?.includes(text) === true, text);

/** The draft as the host keeps it. */
const kept = () =>
    dashboard.page.evaluate(async () => {
        const answer = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "inbox-draft" }) });
        return ((await answer.json()) as { draft: { done: number[]; declined: number[] } }).draft;
    });

describe("a draft the host refuses or drops a part of, in headless Chromium", () => {
    it("refuses a draft declining what isn't an approval or a held change, saying the host's words, the draft kept", async () => {
        await loadedOn({ declined: [52], done: [66] });
        await dashboard.keys.press(["Control+Enter"]);
        await says("Not sent, your draft kept: the draft declines @52, a note: only an approval or a held change is declined");
        expect(await kept()).toMatchObject({ declined: [52], done: [66] });
    });

    it("drops a mark on the operator's own item and says so, the approval beside it approved", async () => {
        await loadedOn({ done: [50, 54] });
        await dashboard.keys.press(["Control+Enter"]);
        await said("Sent: approved @54");
        expect(await dashboard.page.locator(".bar .said").innerText()).toContain("not marked done");
        await dashboard.keys.press(["g", "<"]);
        await dashboard.page.waitForSelector(".whole-palette");
        expect((await dashboard.page.locator(".whole-palette").innerText()).replace(/\s+/g, " ")).toContain("@50 not marked done: it's a review from the operator, which a reply doesn't answer");
        await dashboard.keys.press(["Escape"]);
        expect(await kept()).toMatchObject({ declined: [], done: [] });
    });
});
