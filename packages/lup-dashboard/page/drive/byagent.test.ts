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

    it("shows what agents tell each other in both their messages drawers, and no copy of it among the operator's items", async () => {
        const lines = (await review.text()).split("\n");
        // What one agent told another is no item of the review's; what they told the operator is.
        expect(lines.filter((each) => /^── @(64|65|67|70)\b/.test(each))).toEqual([]);
        expect(lines.some((each) => each.startsWith("── @66 note"))).toBe(true);
        expect(lines.some((each) => each.startsWith("── @57 friction"))).toBe(true);
        // The message itself, in the sender's drawer and the recipient's, saying who's talking to whom.
        expect(lines.filter((each) => each.startsWith("@72 lup-impl/explore-auth → lup-impl · note"))).toHaveLength(2);
        // Each drawer called what it is, the messages over the trace.
        const summaries = lines.filter((each) => /^(messages|trace) · /.test(each));
        expect(summaries[0]).toMatch(/^messages · /);
        expect(summaries[1]).toMatch(/^trace · /);
    });

    it("writes a comment on what another agent wrote to them, whichever drawer it's written in, saying so", async () => {
        await review.goTo("@72 lup-impl/explore-auth → lup-impl · note");
        await dashboard.keys.press(["j"]);
        await review.comment();
        await dashboard.page.keyboard.type("Which of the three?");
        await dashboard.page.waitForFunction(() => document.querySelector(".cm-line.remark-to")?.getAttribute("data-to") === "to lup-impl/explore-auth");
        await dashboard.keys.press(["Escape"]);
        await review.inMode("normal");
        expect(await review.line()).toContain("Which of the three?");
        expect(dashboard.thrown).toEqual([]);
    });

    it("reaches a messages drawer by its letter, and marks it read with Space d as the reply is sent, the trace's mark as it was", async () => {
        await review.goTo("━━ lup · dev · lup-impl/explore-auth");
        await dashboard.keys.press(["]", "M"]);
        await review.until("go to the next messages drawer", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.startsWith("messages · "));
        const before = await review.line();
        expect(before).toMatch(/ new$/);
        const trace = (await review.text()).split("\n").find((each, at, lines) => lines[at - 1] !== undefined && each.startsWith("trace · ") && lines.slice(0, at).lastIndexOf(before) >= 0);
        await dashboard.keys.press([" ", "d"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("mark their messages read") === true);
        await dashboard.keys.press(["Control+Enter"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".bar .said")?.textContent?.startsWith("Sent") === true);
        // What's been read is no longer new, and the comment on another's words went to them.
        expect(await dashboard.page.locator(".bar .said").innerText()).toContain("lup-impl/explore-auth");
        await review.until("say the drawer holds nothing new", (view, was) => !view.state.doc.toString().includes(was), before);
        expect((await review.text()).split("\n").filter((each) => each === trace).length).toBeGreaterThan(0);
        expect(dashboard.thrown).toEqual([]);
    });
});
