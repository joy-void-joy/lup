// The review by agent, as the page opens and as one buffer beside the overview, the fallback its address may ask for
// (`?panes=off`; `docs/dashboard.md`, *The review*): what agents tell each other is in their messages drawers, each way alike.
// A fold-wise selection lasting as the review is laid out anew, and what only the one buffer does.
import type { Request } from "playwright";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo, type DemoOptions } from "./demo.ts";
import type { Review } from "./review.ts";
import { DEMO_ITEM } from "./typing.ts";

/** explore-auth's banner, over their drawers. */
const EXPLORE_AUTH = "━━ lup · dev · lup-impl/explore-auth";

/**
 * The line of explore-auth's drawer of `kind`, among theirs under their banner, as the review stands; null where they
 * have none. Another agent's drawer may say the same, as grep-tokens' messages do once the late question has come.
 */
const theirs = (review: Review, kind: string) =>
    review.evaluate(
        (view, { banner, kind }) => {
            const lines = view.state.doc.toString().split("\n");
            const at = lines.findIndex((each) => each.startsWith(banner));
            const after = at === -1 ? [] : lines.slice(at + 1);
            const end = after.findIndex((each) => each.startsWith("━━ "));
            return (end === -1 ? after : after.slice(0, end)).find((each) => each.startsWith(`${kind} · `)) ?? null;
        },
        { banner: EXPLORE_AUTH, kind },
    );

/** The banner of explore-auth's lead, lup-impl, whose own goes on past the name, over their drawers. */
const LUP_IMPL = "━━ lup · dev · lup-impl · ";

/** Open the drawer of `kind` under `banner`, once the host has answered its view: the next one after the banner may be another agent's until then. */
async function unfoldTheirs(review: Review, banner: string, kind: string): Promise<void> {
    await review.until(
        `lay out the ${kind} drawer under ${banner}`,
        (view, { banner, kind }) => {
            const lines = view.state.doc.toString().split("\n");
            const at = lines.findIndex((each) => each.startsWith(banner));
            const after = at === -1 ? [] : lines.slice(at + 1);
            const end = after.findIndex((each) => each.startsWith("━━ "));
            return (end === -1 ? after : after.slice(0, end)).some((each) => each.startsWith(`${kind} · `));
        },
        { banner, kind },
    );
    await review.goTo(banner);
    await review.unfold(`${kind} · `);
}

const ways: [string, DemoOptions][] = [
    ["as the page opens", { size: 0 }],
    ["as one buffer", { size: 0, oneBuffer: true }],
];

describe.each(ways)("the review by agent, %s", (_way, options) => {
    let served: Demo;
    let dashboard: Dashboard;
    let review: Review;

    beforeAll(async () => {
        served = await demo(options);
        dashboard = await open(served.url);
        review = await dashboard.review();
        await review.holds(DEMO_ITEM);
        await review.settled();
    });

    afterAll(async () => {
        await dashboard?.close();
        await served?.close();
    });

    it("shows what agents tell each other in both their messages drawers, and no copy of it among the operator's items", async () => {
        const lines = (await review.text()).split("\n");
        // What one agent told another is no item of the review's; what they told the operator is.
        expect(lines.filter((each) => /^── @(64|65|67|70)\b/.test(each))).toEqual([]);
        expect(lines.some((each) => each.startsWith("── @66 note"))).toBe(true);
        expect(lines.some((each) => each.startsWith("── @57 friction"))).toBe(true);
        // The message itself, in the sender's drawer and the recipient's, saying who's talking to whom: each opened in
        // turn, what a closed drawer holds not being laid out, and closed again.
        const told: string[] = [];
        for (const banner of [LUP_IMPL, EXPLORE_AUTH]) {
            await unfoldTheirs(review, banner, "messages");
            told.push(...(await review.text()).split("\n").filter((each) => each.startsWith("@72 lup-impl/explore-auth → lup-impl · note")));
            await dashboard.keys.press(["z", "c"]);
            await review.until("closed the drawer", (view) => !view.state.doc.toString().includes("@72 lup-impl/explore-auth → lup-impl · note"));
        }
        expect(told).toHaveLength(2);
        // Each drawer called what it is, the messages over the trace.
        const summaries = lines.filter((each) => /^(messages|trace) · /.test(each));
        expect(summaries[0]).toMatch(/^messages · /);
        expect(summaries[1]).toMatch(/^trace · /);
        expect(dashboard.thrown).toEqual([]);
    });

    it("writes a comment on what another agent wrote to them, whichever drawer it's written in, saying so", async () => {
        await unfoldTheirs(review, LUP_IMPL, "messages");
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
        // Each mark the page moves on the host, as it asks.
        const marked: { key: Record<string, unknown> }[] = [];
        const asked = (request: Request) => {
            const body = request.method() === "POST" && request.url().endsWith("/api/ask") ? (JSON.parse(request.postData() ?? "{}") as Record<string, unknown>) : {};
            if (body.kind === "review-mark") {
                marked.push(...(body.marks as { key: Record<string, unknown> }[]));
            }
        };
        dashboard.page.on("request", asked);
        await review.goTo(EXPLORE_AUTH);
        await dashboard.keys.press(["]", "M"]);
        await review.until("go to the next messages drawer", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.startsWith("messages · "));
        const before = await review.line();
        expect(before).toMatch(/ new$/);
        expect(await theirs(review, "messages")).toBe(before);
        await dashboard.keys.press([" ", "d"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("mark their messages read") === true);
        await dashboard.keys.press(["Control+Enter"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".bar .said")?.textContent?.startsWith("Sent") === true);
        dashboard.page.off("request", asked);
        // What's been read is no longer new, and the comment on another's words went to them.
        expect(await dashboard.page.locator(".bar .said").innerText()).toContain("lup-impl/explore-auth");
        await expect.poll(() => theirs(review, "messages"), { timeout: 30_000 }).toMatch(/^messages · \d+$/);
        // The messages' mark alone: their trace's says it's new no more all the same, the operator's words to them
        // reading what had reached them as they were sent (`docs/dashboard.md`, *Review marks*).
        expect(marked.filter((each) => each.key.drawer === "messages")).not.toEqual([]);
        expect(marked.filter((each) => each.key.drawer !== "messages")).toEqual([]);
        expect(dashboard.thrown).toEqual([]);
    });
});

describe("the review as one buffer", () => {
    let served: Demo;
    let dashboard: Dashboard;
    let review: Review;

    /** The overview's rows, as it draws them. */
    const rows = () => dashboard.page.evaluate(() => [...document.querySelectorAll(".outline .outline-row")].map((each) => each.textContent ?? ""));

    beforeAll(async () => {
        served = await demo({ size: 0, oneBuffer: true });
        dashboard = await open(served.url);
        review = await dashboard.review();
        await review.holds(DEMO_ITEM);
        await review.settled();
    });

    afterAll(async () => {
        await dashboard?.close();
        await served?.close();
    });

    it("lies beside the overview, every agent and their items in the review's order, and no list", async () => {
        expect(await dashboard.page.locator(".panes").count()).toBe(0);
        const listed = await rows();
        expect(listed.some((each) => each.includes("lup-impl/parser") || each.includes("parser"))).toBe(true);
        expect(listed.some((each) => each.includes("@66 note"))).toBe(true);
        expect(listed.some((each) => each.startsWith("▪"))).toBe(true);
        expect(dashboard.thrown).toEqual([]);
    });

    it("goes there from a click on an entry, or with gO and Enter, the keyboard back in the review", async () => {
        await dashboard.page.locator(".outline-row", { hasText: "@66 note" }).click();
        await review.until("put the cursor on the item", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.startsWith("── @66 note"));
        await dashboard.keys.press(["g", "O"]);
        await dashboard.page.waitForFunction(() => document.activeElement?.closest(".outline") != null, undefined, { polling: 50 });
        await dashboard.keys.press(["k", "Enter"]);
        await review.until("put the cursor on the entry above", (view) => !view.state.doc.lineAt(view.state.selection.main.head).text.startsWith("── @66 note"));
        await dashboard.page.waitForFunction(() => document.activeElement?.closest(".review-buffer") != null, undefined, { polling: 50 });
    });

    it("goes from an agent's name to their own views with gd, their conversation opened, and back with Ctrl+O", async () => {
        await review.goTo(EXPLORE_AUTH);
        const banner = await review.line();
        await review.evaluate((view, name) => {
            const at = view.state.doc.lineAt(view.state.selection.main.head);
            view.dispatch({ selection: { anchor: at.from + at.text.indexOf(name) + 2 } });
        }, "lup-impl/explore-auth");
        await review.settled(300, 0);
        await dashboard.keys.press(["g", "d"]);
        await review.until("on explore-auth's conversation", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.startsWith("trace ·"));
        await dashboard.keys.press(["Control+o"]);
        await review.until("back on their banner", (view, was) => view.state.doc.lineAt(view.state.selection.main.head).text === was, banner);
    });

    it("says gt has nowhere to go, reading no concerns", async () => {
        await review.goTo("── @51 question");
        await review.settled(300, 0);
        await dashboard.keys.press(["g", "t"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".bar .said")?.textContent?.startsWith("gt: no concern here") === true);
        expect(await review.line()).toContain("@51 question");
    });
});

describe("a fold-wise selection as the review is laid out anew, in headless Chromium", () => {
    it("is kept, its head under a closed fold, and acts as it did", async () => {
        await using served = await demo({ size: 6 });
        await using dashboard = await open(served.url);
        const review = await dashboard.review();
        await review.holds(DEMO_ITEM);
        await review.settled(1500);
        await dashboard.keys.press([" ", "F", "M"]);
        await review.inMode("visual");
        const before = await review.text();
        // The late question arriving once the selection's made, as what arrives does on the host.
        await served.arrive();
        await review.until("was laid out anew", (view, was) => view.state.doc.toString() !== was, before);
        await dashboard.page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
        expect(await review.mode()).toBe("visual");
        await dashboard.keys.press(["d"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("mark their messages read") === true);
        expect(await review.decorated("mark-done")).toBeGreaterThan(1);
        expect(dashboard.thrown).toEqual([]);
    });
});
