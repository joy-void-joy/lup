// Clearing is the operator's, on any concern (`docs/dashboard.md`, *The panes*): on its block, in its holder's own
// buffer, its party's or what's for them, Space d clears it and Space x declines it, whatever waits on them in it; a message
// is written on it, Space s sending that to no one and back; and it's all sent with Ctrl+Enter.
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";
import { DEMO_ITEM } from "./typing.ts";

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

/** Return the list's lines, as drawn: a closed nest's rows aren't. */
const listed = () => dashboard.page.evaluate(() => [...document.querySelectorAll(".list-buffer .cm-line")].map((each) => each.textContent ?? ""));

/** Open the concern called `title` from its row, nested under whoever owns it, and return once the cursor's on its block, where it's held. */
async function concern(title: string): Promise<void> {
    await dashboard.openRow(title);
    await review.until(`land on the block of ${title}`, (view, wanted) => view.state.doc.lineAt(view.state.selection.main.head).text.trimStart().startsWith(`§ ${wanted}`), title);
    await review.settled(300, 0);
}

describe("clearing any concern, in headless Chromium", () => {
    it("clears a concern with Space d on its block, whatever waits on the operator in it, and declines it with Space x instead, either taking the other's mark off", async () => {
        // A question waits on the operator in it: it stays waiting where it's laid out.
        await concern("The transcript reader");
        await offers("␣d clear it");
        await offers("␣x decline it: nothing more will be done");
        await dashboard.keys.press([" ", "d"]);
        await says("The transcript reader cleared");
        await dashboard.keys.press([" ", "x"]);
        await says("The transcript reader declined");
        expect(await dashboard.page.locator(".status").first().innerText()).not.toContain("cleared");
        // Pressed again, it's declined no more, as a mark is.
        await dashboard.keys.press([" ", "x"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("The transcript reader") === false);
    });

    it("clears one said done from its block in what's for the operator, and writes on a concern, Space s sending that to no one and back", async () => {
        await dashboard.openRow("what's for you");
        await review.goTo("§ The guidance's voice · done, for you to clear");
        await review.settled(300, 0);
        await offers("␣d clear it: it's done");
        await dashboard.keys.press([" ", "d"]);
        await says("The guidance's voice cleared");
        await concern("Where auth is checked");
        await dashboard.keys.press(["o"]);
        await review.inMode("insert");
        await dashboard.keys.type("Which runs as root?");
        await dashboard.keys.press(["Escape"]);
        await review.inMode("normal");
        await says("to lup-impl/explore-auth: a message on Where auth is checked");
        await dashboard.keys.press([" ", "s"]);
        await says("to no one: a message on Where auth is checked");
        await dashboard.keys.press([" ", "s"]);
        await says("to lup-impl/explore-auth: a message on Where auth is checked");
    });

    it("sends it all with Ctrl+Enter: the concern cleared, the message on its concern", async () => {
        await dashboard.keys.press(["Control+Enter"]);
        await said("Sent");
        // The message, a passage of the operator's in the concern now, open until the agent answers it.
        await review.until("hold the message on its block, open, waiting on whoever answers", (view) => /you · @\d+\.1 · open: waits on lup-impl\/explore-auth/.test(view.state.doc.toString()));
        // Done and cleared, it's gone from the list, under what's settled alone, which is folded; and read there.
        await dashboard.page.waitForFunction(() => ![...document.querySelectorAll(".list-buffer .cm-line")].some((each) => (each.textContent ?? "").includes("The guidance's voice")), undefined, { polling: 50 });
        expect((await listed()).some((each) => each.startsWith("settled · "))).toBe(true);
        await dashboard.openRow("settled · ");
        await review.holds("§ The guidance's voice · done, cleared");
    });
});
