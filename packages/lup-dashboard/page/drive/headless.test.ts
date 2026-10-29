import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";
import { timed } from "./timing.ts";
import { DEMO_ITEM, typing } from "./typing.ts";

/** A line of the demo's under a fold as the page loads: an item's context, in a conversation's drawer. */
const FOLDED = "→ @58 how it felt to you · unread";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    served = await demo({ size: 0 });
    dashboard = await open(served.url);
    review = await dashboard.review();
    await review.holds(DEMO_ITEM);
});

afterEach(() => {
    expect(dashboard.thrown).toEqual([]);
});

afterAll(async () => {
    await dashboard?.close();
    await served?.close();
});

/** Whether a line the review draws holds `text`: false where a fold hides every such line. */
const drawn = (text: string) =>
    dashboard.page.evaluate((text) => [...document.querySelectorAll(".review-buffer .cm-line")].some((line) => line.textContent?.includes(text)), text);

describe("the review's editor, in headless Chromium", () => {
    it("is reached, in vim's normal mode, holding the demo's items", async () => {
        expect(await review.mode()).toBe("normal");
        expect(await review.text()).toContain(DEMO_ITEM);
    });

    it("goes to a line a fold hides with vim's search, which opens the folds around it", async () => {
        expect(await drawn(FOLDED)).toBe(false);
        await review.goTo(FOLDED);
        expect(await review.line()).toContain(FOLDED);
        await dashboard.page.waitForFunction((text) => [...document.querySelectorAll(".review-buffer .cm-line")].some((line) => line.textContent?.includes(text)), FOLDED);
    });

    it("takes keys sent all at once, never waiting on the page, each counted and drawn, the CPU slowed or not", async () => {
        for (const rate of [4, 1]) {
            await dashboard.slow(rate);
            await review.goTo(DEMO_ITEM);
            await dashboard.page.keyboard.press("j");
            await review.comment();
            const keys = await timed(dashboard.page, () => dashboard.keys.type(`sent at once ${rate}`));
            expect(keys.seen).toBe(keys.keys.length);
            expect(keys.keys.map((each) => each.key).join("")).toBe(`sent at once ${rate}`);
            for (const each of keys.keys) {
                expect(each.toFrame).toBeGreaterThan(0);
            }
            await review.until("held what was typed", (view, typed) => view.state.doc.lineAt(view.state.selection.main.head).text.endsWith(typed), `sent at once ${rate}`);
            await dashboard.keys.press(["Escape", "u"]);
            await review.until("took the comment back", (view, typed) => !view.state.doc.toString().includes(typed), `sent at once ${rate}`);
        }
    });

    it("measures typing into a comment: every key landed, the host kept it, and the comment taken back after", async () => {
        const typed = await typing(dashboard, { text: "kept on the host", gap: 10 });
        expect(typed).toMatchObject({ text: "kept on the host", landed: "kept on the host", lost: 0, kept: true });
        expect(typed.timed.seen).toBe("kept on the host".length);
        expect(await review.text()).not.toContain("kept on the host");
    });

    it("counts a mark once, though the editor's state holds its decorations twice", async () => {
        const held = await review.evaluate((view) => {
            let count = 0;
            for (const value of (view.state as unknown as { values: unknown[] }).values) {
                const ranges = value as { between?: (from: number, to: number, each: (from: number, to: number, value: { spec?: { class?: string } }) => void) => void };
                ranges?.between?.(0, view.state.doc.length, (_from, _to, decoration) => {
                    count += (decoration.spec?.class ?? "").split(" ").includes("tone-run") ? 1 : 0;
                });
            }
            return count;
        });
        const counted = await review.decorated("tone-run");
        expect(counted).toBeGreaterThan(0);
        expect(held).toBe(2 * counted);
    });

    it("says at once that the review is gone, and what the page threw, rather than waiting it out", async () => {
        await using broken = await open(served.url);
        const gone = await broken.review();
        await broken.page.evaluate(() => {
            setTimeout(() => {
                document.querySelector(".review-buffer")?.remove();
                throw new Error("an effect threw");
            });
        });
        await expect(gone.holds("never")).rejects.toThrow(/the review never held "never"; the page threw Error: an effect threw/);
        expect(broken.thrown.map((each) => each.message)).toContain("the review's editor is gone from the page");
    });
});
