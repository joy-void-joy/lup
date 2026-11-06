// The review in two panes (`?panes=agents`, `?panes=threads`, `page/src/panes.ts`): the three levels of the keys, moving
// between the panes, a comment written in one buffer and still anchored as another comes and goes, search within the
// buffer on screen, and what Ctrl+Enter sends from any of them.
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

/** The item the demo's guidance-voice session sent, whose group they're first in. */
const THEIR_ITEM = "@45 note";

/** Words the demo holds nowhere: what's written in these tests. */
const WORDS = "Keep this anchored across buffers";

/** The page in Pane mode, and the pane selected there, as the page marks them. */
const paneMode = (dashboard: Dashboard) => dashboard.page.evaluate(() => document.querySelector(".panes")?.getAttribute("data-mode"));
const selected = (dashboard: Dashboard) => dashboard.page.evaluate(() => (document.querySelector(".pane.is-selected")?.classList.contains("pane-list") ? "list" : "buffer"));
const inList = (dashboard: Dashboard) => dashboard.page.evaluate(() => document.activeElement?.closest(".list-buffer") !== null && document.activeElement?.closest(".list-buffer") !== undefined);
const listText = (dashboard: Dashboard) => dashboard.page.evaluate(() => [...document.querySelectorAll(".list-buffer .cm-line")].map((each) => each.textContent ?? ""));

/** Return once the page says the mode is `mode`. */
async function inPaneMode(dashboard: Dashboard, mode: "pane" | "normal"): Promise<void> {
    await dashboard.page.waitForFunction((wanted) => document.querySelector(".panes")?.getAttribute("data-mode") === wanted, mode, { polling: 50 });
}

/** Go from the buffer into the list, and onto the row saying `text`, by vim's search there. */
async function listRow(dashboard: Dashboard, text: string): Promise<void> {
    const { page } = dashboard;
    if (!(await inList(dashboard))) {
        await page.keyboard.press("Escape");
        await page.keyboard.press("Escape");
        await inPaneMode(dashboard, "pane");
        await page.keyboard.press("h");
        await page.keyboard.press("i");
        await inPaneMode(dashboard, "normal");
    }
    await page.keyboard.press("g");
    await page.keyboard.press("g");
    await page.keyboard.press("/");
    await page.keyboard.type(text);
    await page.keyboard.press("Enter");
}

describe("the panes by agent", () => {
    let served: Demo;
    let dashboard: Dashboard;
    let review: Review;

    beforeAll(async () => {
        served = await demo({ size: 0, panes: "agents" });
        dashboard = await open(served.url);
        review = await dashboard.review();
        await review.holds(THEIR_ITEM);
        await review.settled();
    });

    afterAll(async () => {
        await dashboard?.close();
        await served?.close();
    });

    it("opens on what's for the operator, with the list beside it, by agent and with No agent", async () => {
        const list = await listText(dashboard);
        expect(list.some((each) => each.includes("what's for you"))).toBe(true);
        expect(list.some((each) => each.includes("guidance-voice"))).toBe(true);
        expect(list.some((each) => each.includes("No agent"))).toBe(true);
        expect(dashboard.thrown).toEqual([]);
    });

    it("goes Insert, Normal, Pane with Esc, and no key in Pane mode acts on anything", async () => {
        const { page } = dashboard;
        await review.goTo(THEIR_ITEM);
        await review.comment();
        await page.keyboard.type("first");
        await page.keyboard.press("Escape");
        await review.inMode("normal");
        expect(await paneMode(dashboard)).toBe("normal");
        await page.keyboard.press("Escape");
        await inPaneMode(dashboard, "pane");
        const before = await review.text();
        // A mark, a chord, a comment, a motion, a send: none does anything here.
        for (const key of ["Space", "d", "x", "o", "j", "G", "/", "z", "Control+Enter", "Escape", "Escape"]) {
            await page.keyboard.press(key);
        }
        expect(await paneMode(dashboard)).toBe("pane");
        expect(await review.text()).toBe(before);
        expect(await review.mode()).toBe("normal");
    });

    it("selects a pane with h and l, and goes into it in Normal mode with i or Enter", async () => {
        const { page } = dashboard;
        expect(await selected(dashboard)).toBe("buffer");
        await page.keyboard.press("h");
        await page.waitForFunction(() => document.querySelector(".pane.is-selected")?.classList.contains("pane-list") === true);
        await page.keyboard.press("l");
        await page.waitForFunction(() => document.querySelector(".pane.is-selected")?.classList.contains("pane-buffer") === true);
        await page.keyboard.press("h");
        await page.keyboard.press("i");
        await inPaneMode(dashboard, "normal");
        expect(await inList(dashboard)).toBe(true);
        await page.keyboard.press("Escape");
        await inPaneMode(dashboard, "pane");
        await page.keyboard.press("l");
        await page.keyboard.press("Enter");
        await inPaneMode(dashboard, "normal");
        expect(await inList(dashboard)).toBe(false);
        expect(await review.mode()).toBe("normal");
    });

    it("keeps vim's keys in the list, Enter opening a row's buffer and going into it", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "main");
        const row = await page.evaluate(() => document.querySelector(".list-buffer .cm-activeLine")?.textContent ?? "");
        expect(row).toContain("main");
        await page.keyboard.press("Enter");
        await review.holds("to main");
        await review.until("left what's for the operator", (view) => !view.state.doc.toString().includes("@45 note"));
        expect(await inList(dashboard)).toBe(false);
        const text = await review.text();
        // Their own: their item and their conversation, nobody else's.
        expect(text).toContain("@53 problem");
        expect(text).not.toContain("@54 approval");
    });

    it("searches the buffer on screen alone", async () => {
        const { page } = dashboard;
        await page.keyboard.press("g");
        await page.keyboard.press("g");
        const was = await review.evaluate((view) => view.state.selection.main.head);
        await page.keyboard.press("/");
        await page.keyboard.type("@54 approval");
        await page.keyboard.press("Enter");
        expect(await review.evaluate((view) => view.state.selection.main.head)).toBe(was);
    });

    it("keeps a comment on its block as another buffer comes and goes, saying whom it reaches", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "what's for you");
        await page.keyboard.press("Enter");
        await review.holds(THEIR_ITEM);
        await review.goTo("so a search never fails on one");
        await review.comment();
        await page.keyboard.type(WORDS);
        await page.keyboard.press("Escape");
        await review.inMode("normal");
        await listRow(dashboard, "main");
        await page.keyboard.press("Enter");
        await review.until("left what's for the operator", (view) => !view.state.doc.toString().includes("@45 note"));
        expect(await review.text()).not.toContain(WORDS);
        await listRow(dashboard, "guidance-voice");
        await page.keyboard.press("Enter");
        await review.holds(WORDS);
        const lines = (await review.text()).split("\n");
        const at = lines.indexOf(WORDS);
        expect(lines[at - 1]).toContain("so a search never fails on one");
        // The line under the review says who it goes to, whichever buffer's on screen.
        const status = await page.evaluate(() => document.querySelector(".status")?.textContent ?? "");
        expect(status).toContain("guidance-voice");
    });

    it("writes to the agent at the end of their buffer, under what's live", async () => {
        const { page } = dashboard;
        await page.keyboard.press("G");
        expect(await review.line()).toContain("to guidance-voice");
        await page.keyboard.press("o");
        await review.inMode("insert");
        await page.keyboard.type("A message to them");
        await page.keyboard.press("Escape");
        await review.inMode("normal");
        const lines = (await review.text()).split("\n");
        const at = lines.findIndex((each) => each.includes("to guidance-voice"));
        expect(lines[at + 1]).toBe("A message to them");
    });

    it("sends with Ctrl+Enter from Normal mode, from any buffer, the comment and the message going whole", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "main");
        await page.keyboard.press("Enter");
        await review.until("left their buffer", (view) => !view.state.doc.toString().includes("to guidance-voice"));
        await page.keyboard.press("Control+Enter");
        await page.waitForFunction(() => (document.querySelector(".bar .said")?.textContent ?? "").startsWith("Sent"), undefined, { polling: 100 });
        const said = await page.evaluate(() => document.querySelector(".bar .said")?.getAttribute("title") ?? "");
        expect(said).toContain("guidance-voice");
        await page.waitForFunction(() => (document.querySelector(".status")?.textContent ?? "").includes("No reply drafted"), undefined, { polling: 100 });
        await listRow(dashboard, "guidance-voice");
        await page.keyboard.press("Enter");
        await review.holds("to guidance-voice");
        expect(await review.text()).not.toContain(WORDS);
        expect(dashboard.thrown).toEqual([]);
    });
});

describe("the panes by thread", () => {
    let served: Demo;
    let dashboard: Dashboard;
    let review: Review;

    beforeAll(async () => {
        served = await demo({ size: 0, panes: "threads" });
        dashboard = await open(served.url);
        review = await dashboard.review();
        await review.holds("waiting on you ·");
        await review.settled();
    });

    afterAll(async () => {
        await dashboard?.close();
        await served?.close();
    });

    it("opens on what's for the operator, by thread, with no section that isn't", async () => {
        const text = await review.text();
        expect(text).toMatch(/^waiting on you · /m);
        expect(text).not.toMatch(/^(open|settled|agents) · /m);
        const list = await listText(dashboard);
        expect(list.some((each) => each.includes("@transcript-reader"))).toBe(true);
    });

    it("opens one thread's conversation, whole, saying whom the words reach", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "@transcript-reader");
        await page.keyboard.press("Enter");
        await review.until("read the thread whole", (view) => !view.state.doc.toString().includes("reading…") && view.state.doc.toString().includes("━━ @transcript-reader"));
        const text = await review.text();
        expect(text).not.toMatch(/^waiting on you · /m);
        expect(text).toContain("to lup-impl/parser on @transcript-reader");
        const whom = await page.evaluate(() => document.querySelector(".where-whom")?.textContent ?? "");
        expect(whom).toContain("lup-impl/parser");
        expect(dashboard.thrown).toEqual([]);
    });

    it("goes from an item of what's for the operator to its thread with gt, onto the item", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "what's for you");
        await page.keyboard.press("Enter");
        await review.goTo("── @51 question");
        await page.keyboard.press("g");
        await page.keyboard.press("t");
        await review.until("went to the thread", (view) => !/^waiting on you · /m.test(view.state.doc.toString()) && !view.state.doc.toString().includes("reading…"));
        await review.until("put the cursor on the item", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.includes("@51 question"));
    });
});
