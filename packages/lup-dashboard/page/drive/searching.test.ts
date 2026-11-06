// `?` and `g?` in the review (`docs/dashboard.md`, *The keys*): `?` is vim's search backward, as `/` is its search
// forward but for the way it goes, a prompt of its own, `n` and `N` going on that way and back, and the folds around each
// match opening, said under the review; the palette of every key is `g?`, from a selection too, where vim's own would
// rewrite what's selected.
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

/** Return once the review, as the page has just made it, holds all it's going to at first. */
async function loaded(): Promise<void> {
    review = await dashboard.review();
    await review.holds("── @66 note · lup-impl/explore-auth");
    await review.settled(1500);
}

beforeAll(async () => {
    served = await demo({ size: 0 });
    dashboard = await open(served.url);
    await loaded();
});

afterEach(() => {
    expect(dashboard.thrown).toEqual([]);
});

afterAll(async () => {
    await dashboard?.close();
    await served?.close();
});

/** Where `text` stands in the review: which of its places the cursor is on, none being -1, how many are before the cursor, and whether a closed fold hides each. */
const found = (text: string) =>
    review.evaluate(
        (view, text) => {
            const whole = view.state.doc.toString();
            const head = view.state.selection.main.head;
            const places: number[] = [];
            for (let at = whole.indexOf(text); at !== -1; at = whole.indexOf(text, at + 1)) {
                places.push(at);
            }
            return {
                on: places.indexOf(head),
                before: places.filter((each) => each < head).length,
                hidden: places.map((each) => {
                    const line = view.state.doc.lineAt(each);
                    return view.lineBlockAt(line.from).from !== line.from;
                }),
            };
        },
        text,
    );

/** Return once the cursor is on the place of `text` numbered `place`, in the order they stand in the review. */
const onPlace = (text: string, place: number) =>
    review.until(
        `put the cursor on place ${place} of ${JSON.stringify(text)}`,
        (view, { text, place }) => {
            const whole = view.state.doc.toString();
            let at = whole.indexOf(text);
            for (let each = 0; each < place && at !== -1; each += 1) {
                at = whole.indexOf(text, at + 1);
            }
            return view.state.selection.main.head === at;
        },
        { text, place },
    );

/** Return once vim's line under the review says `pattern`: its prompt, or what a search opened. */
const below = (pattern: string) =>
    dashboard.page.waitForFunction(
        (pattern) => [...document.querySelectorAll(".cm-vim-panel")].some((each) => new RegExp(pattern).test(each.textContent ?? "")),
        pattern,
        { polling: 20 },
    );

/** Press `key`, which asks for a query in vim's prompt, once it has the keyboard, type `text` there, and make the search. */
async function search(key: string, text: string): Promise<void> {
    await dashboard.keys.press([key]);
    await dashboard.page.waitForSelector(".cm-vim-panel input:focus");
    await dashboard.keys.type(text);
    await dashboard.keys.press(["Enter"]);
}

/** Return once the palette has gone and the review has the keys again. */
const backInReview = () =>
    dashboard.page.waitForFunction(() => document.querySelector(".keys-palette") === null && document.activeElement?.closest(".review-buffer") != null, undefined, { polling: 20 });

/**
 * Three places, each under a closed fold as the review opens: an item's context, and two conversations in the agents'
 * section. None of what comes to the demo later holds it, unlike the parser's words, which the late question's context does.
 */
const LINE = "Rendering frames 1 to 600.";

/** What vim's line under the review says of the folds a search opened. */
const OPENED = "^opened (a fold|\\d+ folds) to reach it$";

describe("searching the review backward with ?, in headless Chromium", () => {
    // The page made afresh, every fold closed as the review opens: each test opens those around a match.
    beforeEach(async () => {
        await dashboard.page.reload();
        await loaded();
    });

    it("asks in a prompt of its own, goes to the match before the cursor opening the folds around it, and n goes on back and N forward", async () => {
        await dashboard.keys.press(["G"]);
        expect(await found(LINE)).toMatchObject({ before: 3, hidden: [true, true, true] });

        await dashboard.keys.press(["?"]);
        await dashboard.page.waitForSelector(".cm-vim-panel input:focus");
        expect(await dashboard.page.locator(".cm-vim-panel").innerText()).toMatch(/^\?/);
        expect(await dashboard.page.locator(".keys-palette").count()).toBe(0);
        await dashboard.keys.type(LINE.replace(".", "\\."));
        await dashboard.keys.press(["Enter"]);

        await onPlace(LINE, 2);
        await below(OPENED);
        expect(await found(LINE)).toMatchObject({ on: 2, hidden: [true, true, false] });

        await dashboard.keys.press(["n"]);
        await onPlace(LINE, 1);
        expect((await found(LINE)).hidden).toEqual([true, false, false]);
        await dashboard.keys.press(["N"]);
        await onPlace(LINE, 2);
        await dashboard.keys.press(["n", "n"], 50);
        await onPlace(LINE, 0);
        expect((await found(LINE)).hidden).toEqual([false, false, false]);
        // Back from the first, it goes round to the last, as vim's does.
        await dashboard.keys.press(["n"]);
        await onPlace(LINE, 2);
    });

    it("leaves / going forward, n going on forward and N back", async () => {
        await dashboard.keys.press(["g", "g"]);
        expect(await found(LINE)).toMatchObject({ before: 0, hidden: [true, true, true] });
        await search("/", LINE.replace(".", "\\."));
        await onPlace(LINE, 0);
        await below(OPENED);
        expect((await found(LINE)).hidden).toEqual([false, true, true]);
        await dashboard.keys.press(["n"]);
        await onPlace(LINE, 1);
        expect((await found(LINE)).hidden).toEqual([false, false, true]);
        await dashboard.keys.press(["N"]);
        await onPlace(LINE, 0);
    });

    it("stays where it was as Esc leaves the prompt, the keyboard back in the review", async () => {
        const before = await review.evaluate((view) => view.state.selection.main.head);
        await dashboard.keys.press(["?"]);
        await dashboard.page.waitForSelector(".cm-vim-panel input:focus");
        await dashboard.keys.type("harbour");
        await dashboard.keys.press(["Escape"]);
        await dashboard.page.waitForSelector(".cm-vim-panel input", { state: "detached" });
        await backInReview();
        expect(await review.evaluate((view) => view.state.selection.main.head)).toBe(before);
    });
});

describe("the palette of every key, g?, in headless Chromium", () => {
    it("opens as the line of keys says, listing itself and ? as a search, the keyboard back in the review as it closes", async () => {
        expect((await dashboard.page.locator(".keys").first().innerText()).replace(/\s+/g, " ")).toContain("g? all keys");
        await dashboard.keys.press(["g", "?"]);
        await dashboard.page.waitForSelector(".keys-palette [cmdk-group-heading]");
        expect(await dashboard.page.locator(".cm-vim-panel input").count()).toBe(0);
        const entry = (keys: string) => dashboard.page.locator(".keys-palette [cmdk-item]").filter({ has: dashboard.page.locator(`kbd:text-is("${keys}")`) });
        expect(await entry("g?").innerText()).toContain("every key searchable");
        expect(await entry("/ ? n N").innerText()).toContain("search forward or back");
        await dashboard.keys.press(["Escape"]);
        await backInReview();
        expect(await review.mode()).toBe("normal");
    });

    it("is what it types in a comment, and opens the palette from a selection of it, rewriting nothing", async () => {
        const said = "why g? and ?";
        await review.goTo("── @66 note");
        await review.comment();
        await dashboard.keys.type(said);
        await review.until("held what was typed", (view, said) => view.state.doc.lineAt(view.state.selection.main.head).text === said, said);
        expect(await dashboard.page.locator(".keys-palette").count()).toBe(0);
        expect(await dashboard.page.locator(".cm-vim-panel input").count()).toBe(0);

        await dashboard.keys.press(["Escape"]);
        await review.inMode("normal");
        await dashboard.keys.press(["0", "v", "$", "g", "?"]);
        await dashboard.page.waitForSelector(".keys-palette [cmdk-group-heading]");
        expect(await review.line()).toBe(said);

        await dashboard.keys.press(["Escape"]);
        await backInReview();
        expect(await review.mode()).toBe("visual");
        expect(await review.line()).toBe(said);
        await dashboard.keys.press(["Escape"]);
        await review.inMode("normal");
    });
});
