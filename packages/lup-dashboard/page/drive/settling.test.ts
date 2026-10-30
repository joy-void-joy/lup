// Settling is the operator's, on any thread (`docs/dashboard.md`, *The page*): Space d on a thread's banner reads its
// news where there's some, then settles it, never while something in it waits on them; Space x declines it; and the
// roots of sessions that have ended are listed in open under a line of their own, `ended`, whose Space d settles each.
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

/** The docs pass's root, its session ended, in open. */
const DOCS = "━━ @docs-pass · the session's own · its session has ended · working ━━";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    served = await demo({ size: 0 });
    dashboard = await open(served.url);
    review = await dashboard.review();
    await review.holds(DOCS);
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

/** Return once the line under the review says `text`. */
const says = (text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".status")?.textContent?.includes(text) === true, text);

/** Return once the line of keys says `text`, the cursor where it is. */
const offers = (text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".keys")?.textContent?.includes(text) === true, text);

/** Return once the top bar says `text`. */
const said = (text: string) => dashboard.page.waitForFunction((text) => document.querySelector(".bar .said")?.textContent?.includes(text) === true, text);

describe("settling any thread, in headless Chromium", () => {
    it("lists the roots of sessions that have ended in open, after the others, under their own line", async () => {
        const lines = (await review.text()).split("\n");
        const open = lines.findIndex((line) => line.startsWith("open · "));
        const ended = lines.indexOf("ended · 1");
        const toRead = lines.findIndex((line) => line.startsWith("to read · "));
        expect(ended).toBeGreaterThan(open);
        expect(lines.slice(open + 1, ended).filter((line) => line.startsWith("━━ ")).length).toBeGreaterThan(5);
        expect(lines.slice(ended + 1, toRead).filter((line) => line.startsWith("━━ "))).toEqual([DOCS]);
    });

    it("never settles a thread where something waits on the operator, saying how many", async () => {
        await review.goTo("━━ @transcript-reader · The transcript reader · lup-impl/parser holds · a question, a check");
        await offers("␣d not settled while 2 wait on you");
        await dashboard.keys.press([" ", "d"]);
        await said("not settled while 2 wait on you");
    });

    it("reads a thread's news with Space d, then settles it with Space d again", async () => {
        await review.goTo("━━ @auth-survey · Where auth is checked · lup-impl/explore-auth holds · 2 new");
        await offers("␣d mark its news read, each item with it");
        await offers("␣x decline it: nothing more will be done");
        await dashboard.keys.press([" ", "d"]);
        await says("@auth-survey read");
        await offers("␣d settle it");
        await dashboard.keys.press([" ", "d"]);
        await says("@auth-survey settled");
        // Pressed again, it's settled no more, as a mark is, its news read still.
        await dashboard.keys.press([" ", "d"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("settled") === false);
        await says("@auth-survey read");
    });

    it("settles each ended session's root from its line with Space d, and sends it, the root going to what's settled", async () => {
        await review.goTo("ended · 1");
        await offers("␣d settle it");
        await dashboard.keys.press([" ", "d"]);
        await says("@docs-pass settled");
        await dashboard.keys.press(["Control+Enter"]);
        await said("@docs-pass settled");
        await review.until("lay the docs pass's root among what's settled", (view) => {
            const text = view.state.doc.toString();
            return !text.includes("ended · 1") && text.indexOf("━━ @docs-pass · the session's own · its session has ended · settled ━━") > text.indexOf("settled · ");
        });
    });
});
