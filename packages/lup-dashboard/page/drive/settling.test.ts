// Settling is the operator's, on any thread (`docs/dashboard.md`, *The page*): from its own buffer, Space d on its banner
// reads its news where there's some, then settles it, never while something in it waits on them; Space x declines it; a
// check is ticked with Space d, a message is written on it, Space s sending that to no one and back; and it's all sent
// with Ctrl+Enter.
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";
import { DEMO_ITEM } from "./typing.ts";

/** explore-auth's survey, with news. */
const AUTH = "━━ @auth-survey · Where auth is checked · lup-impl/explore-auth holds · working · 1 new ━━";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    served = await demo({ size: 0 });
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

/** Return once the line under the review says `text`. */
const says = (text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".status")?.textContent?.includes(text) === true, text);

/** Return once the line of keys says `text`, the cursor where it is. */
const offers = (text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".keys")?.textContent?.includes(text) === true, text);

/** Return once the top bar says `text`. */
const said = (text: string) => dashboard.page.waitForFunction((text) => document.querySelector(".bar .said")?.textContent?.includes(text) === true, text);

/** The demo's threads' titles, which their rows say, by name. */
const TITLES: Record<string, string> = { "transcript-reader": "The transcript reader", "auth-survey": "Where auth is checked", "the-voice": "The guidance's voice" };

/** Open the thread named `name` from its row, nested under whoever owns it, and return once it's read, the cursor on its banner. */
async function thread(name: string): Promise<void> {
    await dashboard.openRow(TITLES[name] ?? name);
    await review.until(`read @${name} whole`, (view, wanted) => view.state.doc.toString().startsWith(`━━ @${wanted} `) && !view.state.doc.toString().includes("reading…"), name);
    await dashboard.keys.press(["g", "g"]);
}

describe("settling any thread, in headless Chromium", () => {
    it("never settles a thread where something waits on the operator, saying how many, its news read first", async () => {
        // A question, a check, and a question more once it has arrived, whichever the review holds as this goes there; and
        // the parser's friction, news that waits, in its conversation.
        await thread("transcript-reader");
        await offers("␣d mark its news read, each item with it");
        await dashboard.keys.press([" ", "d"]);
        await says("@transcript-reader read");
        await offers("␣d not settled while ");
        expect((await dashboard.page.locator(".keys").first().innerText()).replace(/\s+/g, " ")).toMatch(/␣d not settled while [23] wait on you/);
        await dashboard.keys.press([" ", "d"]);
        await said("not settled while ");
        expect(await dashboard.page.locator(".bar .said").innerText()).toMatch(/not settled while [23] wait on you/);
        // Undone: nothing of it is sent by what follows.
        await dashboard.keys.press(["u"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("@transcript-reader read") === false);
    });

    it("reads a thread's news with Space d, then settles it with Space d again", async () => {
        await thread("auth-survey");
        expect(await review.line()).toBe(AUTH);
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
        // Undone: nothing of it is sent by what follows.
        await dashboard.keys.press(["u", "u", "u"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("@auth-survey read") === false);
    });

    it("goes to a thread done from the line saying so, reads its news, settles it, ticks a check, and writes on a thread, Space s sending that to no one and back", async () => {
        await dashboard.openRow("what's for you");
        await review.goTo("◇ @the-voice is done, to confirm");
        await review.settled(300, 0);
        await dashboard.keys.press(["g", "t"]);
        await review.until("read the voice thread whole", (view) => view.state.doc.toString().startsWith("━━ @the-voice · The guidance's voice · guidance-voice holds · done, to confirm") && !view.state.doc.toString().includes("reading…"));
        await dashboard.keys.press(["g", "g"]);
        await offers("␣d mark its news read");
        await dashboard.keys.press([" ", "d"]);
        await says("@the-voice read");
        await offers("␣d settle it: it works");
        await dashboard.keys.press([" ", "d"]);
        await says("@the-voice settled");
        await thread("transcript-reader");
        await review.goTo("◇ check @311");
        await dashboard.keys.press([" ", "d"]);
        await says("tick it: you tried it");
        await thread("auth-survey");
        await dashboard.keys.press(["o"]);
        await review.inMode("insert");
        await dashboard.keys.type("Which runs as root?");
        await dashboard.keys.press(["Escape"]);
        await review.inMode("normal");
        await says("to lup-impl/explore-auth: a message on @auth-survey");
        await dashboard.keys.press([" ", "s"]);
        await says("to no one: a message on @auth-survey");
        await dashboard.keys.press([" ", "s"]);
        await says("to lup-impl/explore-auth: a message on @auth-survey");
    });

    it("sends it all with Ctrl+Enter: the thread settled, the check answered, the message in its thread", async () => {
        await dashboard.keys.press(["Control+Enter"]);
        await said("Sent");
        await review.until("hold the message, open, waiting on whoever answers", (view) => /you · @\d+\.1 to lup-impl\/explore-auth · open: waits on lup-impl\/explore-auth/.test(view.state.doc.toString()));
        await thread("transcript-reader");
        await review.holds("✓ check @311");
        // Done and cleared, it's gone from the list, under what's settled alone, which is folded.
        await dashboard.page.waitForFunction(() => ![...document.querySelectorAll(".list-buffer .cm-line")].some((each) => (each.textContent ?? "").includes("The guidance's voice")), undefined, { polling: 50 });
    });
});
