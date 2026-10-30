// The pile to read (`docs/dashboard.md`, *The review*): each thread's frictions and how it felt by their titles, one
// marked read with Space d, the whole pile selected with Space f r and moved into a thread named in the palette, and
// sent with Ctrl+Enter.
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

/** The pile's section, as the demo of a busy day lays it out: the parser's friction, the voice session's how it felt, and each worker's friction. */
const PILE = "to read · 7 frictions, 1 how it felt";
/** The thread the pile is moved into, opened for it. */
const GATE = "━━ @the-gate-s-silent-rebuild · The gate's silent rebuild · nobody holds it, lup-impl answers · working ━━";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    served = await demo({ size: 6 });
    dashboard = await open(served.url);
    review = await dashboard.review();
    await review.holds(PILE);
    await review.settled(1500);
});

afterEach(() => {
    expect(dashboard.thrown).toEqual([]);
});

afterAll(async () => {
    await dashboard?.close();
    await served?.close();
});

/** Return once the line under the review, saying what the reply does, says `text`. */
const going = (text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".status")?.textContent?.includes(text) === true, text);

/** Return once what the page said last says `text`. */
const said = (text: string) => dashboard.page.waitForFunction((text) => document.querySelector(".said")?.textContent?.includes(text) === true, text);

/** What the line of keys says, the cursor where it is. */
const keys = async () => (await dashboard.page.locator(".keys").first().innerText()).replace(/\s+/g, " ");

describe("the pile to read, in headless Chromium", () => {
    it("lists each thread's frictions and how it felt by their titles, each in its thread's conversation folded, saying so", async () => {
        const lines = (await review.text()).split("\n");
        const at = lines.indexOf(PILE);
        expect(lines.slice(at + 1, at + 5)).toEqual([
            "@transcript-reader · The transcript reader · 1 friction",
            "friction @57 · lup-impl/parser · the gate rebuilds the engine without a word",
            "  `uv run lup-dev check` rebuilt the engine for four minutes before the tests ran, printing nothing until then. I was running the gate on the reader; a line saying the rebuild, and how long it takes, would have kept me from killing it.",
            "@guidance-voice · the session's own · 1 how it felt",
        ]);
        expect(lines.filter((line) => line.startsWith("friction @") || line.startsWith("how it felt @"))).toHaveLength(8);
        expect(lines.some((line) => line.startsWith("── @57 friction · in the pile to read · lup-impl/parser"))).toBe(true);
    });

    it("marks one read with Space d, and goes from a thread's line in the pile to its group with gd", async () => {
        await review.goTo("how it felt @58");
        expect(await keys()).toContain("␣d mark it read");
        await dashboard.keys.press([" ", "d"]);
        await going("read @58");
        await review.goTo("@guidance-voice · the session's own · 1 how it felt");
        await dashboard.keys.press(["g", "d"]);
        await review.until("on the voice session's thread", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.startsWith("━━ @guidance-voice · the session's own"));
    });

    it("selects the whole pile from its line with Space f r, and moves it with s into a thread opened with the title typed in the palette", async () => {
        await review.goTo(PILE);
        await dashboard.keys.press([" ", "f", "r"]);
        await review.inMode("visual");
        expect(await keys()).toContain("frictions and how it felt: 8 selected");
        await dashboard.keys.press(["s"]);
        await dashboard.page.waitForSelector(".palette input");
        await dashboard.keys.type("The gate's silent rebuild");
        await dashboard.page.locator(".palette [cmdk-item]", { hasText: "a new thread: The gate's silent rebuild" }).waitFor();
        await dashboard.keys.press(["Enter"]);
        await going("8 moved into a new thread: The gate's silent rebuild");
        await review.until("the keyboard back in the review", (view) => view.hasFocus);
        await dashboard.keys.press(["Escape"]);
        await review.inMode("normal");
        expect(await review.decorated("mark-send")).toBe(8);
    });

    it("sends it with Ctrl+Enter: the pile empty, the thread open under the root its holder answers for, each item saying where it went", async () => {
        await dashboard.keys.press(["Control+Enter"]);
        await said("8 items moved into a new thread, @the-gate-s-silent-rebuild, told to lup-impl");
        await review.holds("to read · 0 frictions, 0 how it felt");
        await review.holds(GATE);
        await review.holds("── @57 friction · moved to @the-gate-s-silent-rebuild · lup-impl/parser · done");
    });
});
