// Every line of the page on one row (`docs/dashboard.md`, *The keys*): the top bar, the line under the review and the
// line of keys say a sentence each at the demo's width, wherever the cursor is, a list of numbers counted; what each
// leaves out is shown whole by `g<`; and no key that isn't built is offered.
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

/** What the line under the review says. */
const status = async () => (await dashboard.page.locator(".status").first().innerText()).replace(/\s+/g, " ");

/** Return once the line under the review says `text`. */
const says = (text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".status")?.textContent?.includes(text) === true, text);

/** What the line of keys says, the cursor where it is. */
const keys = async () => (await dashboard.page.locator(".keys").first().innerText()).replace(/\s+/g, " ");

/**
 * Each line of the page that's to keep to one row and doesn't, said with its words: the top bar, the line under the
 * review and the line of keys, each wrapped onto a second row or cut at its end.
 */
const overrun = () =>
    dashboard.page.evaluate(() => {
        const row = parseFloat(getComputedStyle(document.querySelector(".keys") as Element).lineHeight);
        return [".bar", ".status", ".keys", ".keys-shown"].flatMap((selector) => {
            const line = document.querySelector(selector) as HTMLElement | null;
            if (line === null) {
                return [];
            }
            const wraps = line.getBoundingClientRect().height > row * 1.5;
            const cut = line.scrollWidth > line.clientWidth + 1;
            return wraps || cut ? [`${selector}${wraps ? " wraps" : " is cut"}: ${line.innerText.replace(/\s+/g, " ")}`] : [];
        });
    });

describe("every line of the page on one row, at the demo's width, in headless Chromium", () => {
    it("keeps the line of keys and the line under the review to one row on every drawer's line, banner and item header", async () => {
        // The demo's late question first, however fast this runs: it gives the lines around it, @66's the longest of them,
        // Space h on the parser, and nothing the demo brings after it makes a line longer.
        await review.holds("── @61 question");
        const wrong: string[] = [];
        let heads = 0;
        // Each found as it's gone to, by its place among them: the parser's two writes come later, and move the text.
        while (
            await review.evaluate((view, index) => {
                const found: number[] = [];
                for (let number = 1; number <= view.state.doc.lines; number += 1) {
                    const line = view.state.doc.line(number);
                    if (/^(━━ |── @|[a-z ]+ · )/.test(line.text)) {
                        found.push(line.from);
                    }
                }
                const anchor = found[index];
                if (anchor === undefined) {
                    return false;
                }
                view.dispatch({ selection: { anchor } });
                return true;
            }, heads)
        ) {
            heads += 1;
            await dashboard.page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
            for (const each of await overrun()) {
                wrong.push(`on ${(await review.line()).slice(0, 60)}: ${each}`);
            }
        }
        expect(heads).toBeGreaterThan(30);
        expect(wrong).toEqual([]);
    });

    it("says what's left to answer on a thread's banner by its count, each by its number in the palette", async () => {
        await dashboard.openRow("@lup-impl");
        await review.until("read the thread whole", (view) => view.state.doc.toString().startsWith("━━ @lup-impl") && !view.state.doc.toString().includes("reading…"));
        await review.goTo("━━ @lup-impl · the session's own · lup-impl holds");
        expect(await keys()).toContain("␣d mark its news read, each item with it, 1 left to answer");
        await dashboard.keys.press(["g", "?"]);
        await dashboard.page.waitForSelector(".keys-palette [cmdk-group-heading]");
        expect(await dashboard.page.locator(".keys-palette [cmdk-group]").first().innerText()).toContain("mark its news read, each item with it, @55 left to answer");
        await dashboard.keys.press(["Escape"]);
        await dashboard.page.waitForSelector(".keys-palette", { state: "detached" });
        await dashboard.openRow("what's for you");
        await review.holds("── @54 approval");
    });

    it("offers no key that isn't built: pause is on no line, in no palette", async () => {
        await review.goTo("━━ lup · dev · lup-impl/parser");
        expect(await keys()).not.toContain("pause");
        await dashboard.keys.press(["g", "?"]);
        await dashboard.page.waitForSelector(".keys-palette [cmdk-group-heading]");
        expect(await dashboard.page.locator(".keys-palette").innerText()).not.toContain("pause");
        await dashboard.keys.press(["Escape"]);
        await dashboard.page.waitForSelector(".keys-palette", { state: "detached" });
    });

    it("counts what the reply marks and what's left for later on one row, and shows each by its number with g<", async () => {
        // One item read is named; more are counted.
        for (const [header, read] of [
            ["── @52 note", "read @52"],
            ["── @56 turn", "read 2 items"],
            ["── @66 note", "read 3 items"],
        ] as const) {
            await review.goTo(header);
            await dashboard.keys.press([" ", "d"]);
            await says(read);
        }
        await review.goTo("── @62 note");
        await dashboard.keys.press([" ", "s"]);
        await says("1 for later");
        expect(await status()).toContain("read 3 items");
        expect(await overrun()).toEqual([]);
        // What's left out is a key away, and the line of keys says so.
        expect(await keys()).toContain("g< in full");
        await dashboard.keys.press(["g", "<"]);
        await dashboard.page.waitForSelector(".whole-palette");
        const whole = (await dashboard.page.locator(".whole-palette").innerText()).replace(/\s+/g, " ");
        expect(whole).toContain("read @52, @56, @66");
        expect(whole).toContain("Left for later @62");
        await dashboard.keys.press(["Escape"]);
        await dashboard.page.waitForSelector(".whole-palette", { state: "detached" });
        // The keyboard back in the review, its keys doing what they do there; the draft kept on the host after, so
        // nothing of this test's is still being kept as the next one refuses the keeping.
        const kept = dashboard.page.waitForResponse((response) => {
            const asked = JSON.parse(response.request().postData() ?? "null") as { kind?: string; draft?: { parked?: number[] } } | null;
            return asked?.kind === "inbox-keep-draft" && !(asked.draft?.parked ?? []).includes(62);
        });
        await dashboard.keys.press(["u"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("for later") === false);
        await kept;
    });

    it("says a refusal in its first sentence on one row, its whole with g<", async () => {
        // The draft is kept already (the test before waits for it): what's refused below is the send's own keeping.
        const why =
            "the draft writes to lup-impl/gone of /r/lup.git, which lup's inbox has never heard of. Write to an agent the dashboard shows running: " +
            "a conversation is known once one of its hooks is heard, and one whose session ended long ago, or that ran in another repository, " +
            "can't be reached by any reply, so the message would wait for good.";
        await dashboard.route("**/api/ask", async (route) => {
            if ((route.request().postData() ?? "").includes('"inbox-keep-draft"')) {
                await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ kind: "refused", error: why }) });
                return;
            }
            await route.continue();
        });
        try {
            await dashboard.keys.press(["Control+Enter"]);
            await says("Not sent, your draft kept: the draft writes to lup-impl/gone of /r/lup.git, which lup's inbox has never heard of.");
            expect(await status()).not.toContain("Write to an agent");
            expect(await overrun()).toEqual([]);
            await dashboard.keys.press(["g", "<"]);
            await dashboard.page.waitForSelector(".whole-palette");
            expect((await dashboard.page.locator(".whole-palette").innerText()).replace(/\s+/g, " ")).toContain("so the message would wait for good.");
            await dashboard.keys.press(["Escape"]);
            await dashboard.page.waitForSelector(".whole-palette", { state: "detached" });
        } finally {
            await dashboard.page.unrouteAll({ behavior: "ignoreErrors" });
        }
    });
});
