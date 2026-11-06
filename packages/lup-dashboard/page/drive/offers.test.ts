// What each item offers is the host's (`docs/dashboard.md`, *Answering is marking*): each answer of its kind while it
// waits on the operator, and a comment on it whatever it stands at, on the page as the host's table says it, whichever
// layout shows it; what the draft holds on one that's past waiting, the line under the review says before it's sent.
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

/** Return once the line of keys says `text`, the cursor where it is. */
const offers = (dashboard: Dashboard, text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".keys")?.textContent?.includes(text) === true, text);

/** Return once the line under the review says `text`. */
const says = (dashboard: Dashboard, text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".status")?.textContent?.includes(text) === true, text);

/** Return once the top line says `text`. */
const said = (dashboard: Dashboard, text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".bar .said")?.textContent?.includes(text) === true, text);

/** Return once the top bar says `text`. */
const counted = (dashboard: Dashboard, text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".bar")?.textContent?.includes(text) === true, text);

/** Ask the host what the page asks it, as the operator's terminal might meanwhile. */
const asked = (dashboard: Dashboard, request: unknown) =>
    dashboard.page.evaluate(async (request) => {
        const answer = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
        if (!answer.ok) {
            throw new Error(await answer.text());
        }
    }, request);

describe("what's offered, grouped by agent, in headless Chromium", () => {
    let served: Demo;
    let dashboard: Dashboard;
    let review: Review;

    beforeAll(async () => {
        served = await demo({ size: 0, byAgent: true });
        dashboard = await open(served.url);
        review = await dashboard.review();
        await review.holds("── @54 approval");
        await review.settled(1500);
    });

    afterEach(() => {
        expect(dashboard.thrown).toEqual([]);
    });

    afterAll(async () => {
        await dashboard?.close();
        await served?.close();
    });

    it("offers an approval's answers on it, and a note's on it", async () => {
        await review.goTo("── @54 approval");
        await offers(dashboard, "␣d approve");
        await offers(dashboard, "␣x decline");
        await offers(dashboard, "␣s leave it for later");
        await offers(dashboard, "␣c comment on it");
        await review.goTo("── @52 note");
        await offers(dashboard, "␣d mark it read");
        await offers(dashboard, "␣s leave it for later");
        expect(await dashboard.page.locator(".keys").first().innerText()).not.toContain("␣x decline");
    });

    it("counts an approval left for later as waiting no more", async () => {
        const count = async () => Number(/(\d+) waiting on you/.exec(await dashboard.page.locator(".bar").first().innerText())?.[1]);
        const before = await count();
        await review.goTo("── @54 approval");
        await dashboard.keys.press([" ", "s"]);
        await counted(dashboard, `${before - 1} waiting on you`);
        await review.goTo("── @54 approval");
        await dashboard.keys.press([" ", "s"]);
        await counted(dashboard, `${before} waiting on you`);
    });

    it("keeps a held change answered elsewhere in view with what's on it, says where the comment goes, and sends it", async () => {
        await review.goTo("── @55 held change");
        await review.comment();
        await dashboard.page.keyboard.type("And keep the file as it was.");
        await dashboard.keys.press(["Escape"]);
        await says(dashboard, "@55");
        await asked(dashboard, { kind: "inbox-answer-approval", number: 55, approved: false });
        await review.holds("decided");
        await says(dashboard, "the comment on @55 sent on @lup-impl");
        await review.goTo("── @55 held change");
        await offers(dashboard, "comment on it");
        expect(await dashboard.page.locator(".keys").first().innerText()).not.toContain("approve");
        await dashboard.keys.press(["Control+Enter"]);
        await said(dashboard, "the comment on @55 sent on @lup-impl");
        expect(await dashboard.page.locator(".bar .said").first().innerText()).not.toContain("approved");
        await review.until("lay it out no more once it's sent", (view) => !view.state.doc.toString().includes("── @55 held change"));
    });

    it("drops a mark on what's answered elsewhere, saying so where the reply says what's sent", async () => {
        await review.goTo("── @54 approval");
        await dashboard.keys.press([" ", "d"]);
        await says(dashboard, "approving @54");
        await asked(dashboard, { kind: "inbox-answer-approval", number: 54, approved: false });
        await says(dashboard, "@54 not approved: it's declined at");
        await dashboard.keys.press(["Control+Enter"]);
        await said(dashboard, "@54 not approved: it's declined at");
    });
});

describe("what's offered, grouped by thread, in headless Chromium", () => {
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

    afterEach(() => {
        expect(dashboard.thrown).toEqual([]);
    });

    afterAll(async () => {
        await dashboard?.close();
        await served?.close();
    });

    it("offers only a comment on what's past waiting, Space d going on to the thread it's in", async () => {
        // Read as its thread opens, in the thread's history.
        await review.goTo("━━ @transcript-reader · The transcript reader · lup-impl/parser holds · working");
        await dashboard.keys.press(["z", "a"]);
        await review.holds("── @47 note");
        await review.goTo("── @47 note");
        await offers(dashboard, "comment on it");
        const keys = await dashboard.page.locator(".keys").first().innerText();
        expect(keys).not.toContain("leave it for later");
        expect(keys).toContain("@transcript-reader");
    });
});
