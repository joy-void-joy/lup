// What the page measures of itself in the room's Chromium (`page/src/timings.ts`; `docs/dashboard.md`, *Its timings*):
// each key in its kind, sent as the tab is hidden and as it closes, kept by the demo as the host keeps it, read back
// with the host's own reader (`lup-dev dashboard timings --kept`), and switched off from the palette.
import { execFile } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import type { Page } from "playwright";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import { DEMO_ITEM } from "./typing.ts";

/** The repository's root, where `uv run` finds the worktree's own environment. */
const ROOT = fileURLToPath(new URL("../../../../", import.meta.url));

/** One window as the host keeps it, as much of it as the tests read. */
interface Measured {
    session: string;
    build: string | null;
    browser: { name: string; system: string; device: string };
    unmeasured: string[];
    window: {
        sequence: number;
        size: Record<string, number>;
        keys: Record<string, { painted: Record<string, number>; under: number }>;
        frames: { count: number } | null;
    };
}

let kept: string;
let served: Demo;

beforeAll(async () => {
    kept = mkdtempSync(join(tmpdir(), "lup-timings-"));
    served = await demo({ size: 0, timings: kept });
});

afterAll(async () => {
    await served?.close();
    rmSync(kept, { recursive: true, force: true });
});

/** Each window the demo has kept, as it's written, a line each, one sent twice twice. */
function written(): Measured[] {
    const page = join(kept, "dashboard");
    const lines = existsSync(page) ? readdirSync(page).flatMap((each) => readFileSync(join(page, each), "utf8").split("\n")) : [];
    return lines.filter(Boolean).map((line) => JSON.parse(line) as Measured);
}

/** Each window of a session other than those of `before`. */
function since(before: readonly Measured[], windows: readonly Measured[]): Measured[] {
    return windows.filter((each) => !before.some((earlier) => earlier.session === each.session));
}

/** Return once the demo has kept a window of a session other than those of `before`; where it never does, say what it kept. */
async function keptAfter(before: readonly Measured[]): Promise<void> {
    for (let tried = 0; tried < 300 && since(before, written()).length === 0; tried += 1) {
        await new Promise((resolve) => setTimeout(resolve, 100));
    }
    expect(since(before, written()), "the demo kept no window of a session after those before").not.toEqual([]);
}

/** Run `lup-dev dashboard timings --kept` on what the demo kept, with `options`, and return what it printed. */
async function timings(...options: string[]): Promise<string> {
    const { stdout } = await promisify(execFile)("uv", ["run", "lup-dev", "dashboard", "timings", "--kept", kept, ...options], { cwd: ROOT });
    return stdout;
}

/** Each window the demo kept, as the host's own reader reads it, each one's last copy. */
async function read(): Promise<Measured[]> {
    return (await timings("--json"))
        .split("\n")
        .filter(Boolean)
        .map((line) => JSON.parse(line) as Measured);
}

/** How many keys of each kind a window counts, those under the floor among them. */
function counted(measured: Measured): Record<string, number> {
    return Object.fromEntries(Object.entries(measured.window.keys).map(([kind, each]) => [kind, each.under + Object.values(each.painted).reduce((a, b) => a + b, 0)]));
}

/**
 * Hide the page as a browser hides a tab another comes in front of: headless Chromium shows every page, so the page is
 * told it's hidden as the browser would tell it, and shown again after.
 */
async function hide(page: Page): Promise<void> {
    await page.evaluate(() => {
        Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
        document.dispatchEvent(new Event("visibilitychange"));
        delete (document as { visibilityState?: unknown }).visibilityState;
    });
}

/** Return once the keys pressed so far went down over a second ago: as the page is hidden, a key of the last second waits on for its frame. */
async function aSecondOn(page: Page): Promise<void> {
    const now = await page.evaluate(() => performance.now());
    await page.waitForFunction((then) => performance.now() - then > 1000, now, { polling: 100 });
}

/** Open the palette of every key, search it for the page's timings, and return what it says of them. */
async function timingsInPalette(dashboard: Dashboard): Promise<string> {
    await dashboard.keys.press(["?"]);
    await dashboard.page.waitForSelector(".keys-palette input");
    await dashboard.keys.type("timings");
    const item = dashboard.page.locator(".keys-palette [cmdk-item]", { hasText: "measuring" });
    await item.waitFor();
    return (await item.textContent()) ?? "";
}

/**
 * Wait until the palette has closed and the review has the keys again: a key pressed as the palette goes away, before
 * the review takes focus back, is counted as `other` rather than as the motion it is (#358).
 */
async function backInReview(dashboard: Dashboard): Promise<void> {
    await dashboard.page.waitForFunction(
        () => document.querySelector(".keys-palette") === null && document.activeElement?.closest(".review-buffer") != null,
        undefined,
        { polling: 20 },
    );
}

describe("the page's timings, in headless Chromium", () => {
    it("measures each key in its kind, sending them as the tab is hidden, with the page's size, build and browser", async () => {
        await using dashboard = await open(served.url);
        const review = await dashboard.review();
        await review.holds(DEMO_ITEM);
        await review.settled();
        await dashboard.keys.press(["z", "a", "z", "a"], 50);
        await dashboard.keys.press(["?"]);
        await dashboard.page.waitForSelector(".keys-palette");
        await dashboard.keys.press(["Escape"]);
        await review.goTo(DEMO_ITEM);
        await dashboard.keys.press(["j", "k", "j"], 50);
        await review.comment();
        await dashboard.keys.type("kept", 40);
        await dashboard.keys.press(["Escape"]);
        await review.inMode("normal");
        await dashboard.keys.press(["u"]);
        await aSecondOn(dashboard.page);
        await hide(dashboard.page);
        await keptAfter([]);
        const [first, ...more] = await read();
        expect(more).toEqual([]);
        const keys = counted(first!);
        expect(keys).toMatchObject({ fold: 4, palette: 2, typing: 5, verb: 1 });
        // `/`, its query and Enter, then j, k and j.
        expect(keys["motion"]).toBeGreaterThanOrEqual(3 + DEMO_ITEM.length);
        expect(Object.keys(keys).sort()).toEqual(["fold", "motion", "other", "palette", "typing", "verb"]);
        expect(first!.window.size["lines"]).toBeGreaterThan(100);
        expect(first!.window.size["items"]).toBeGreaterThan(0);
        expect(first!.window.size).toHaveProperty("drawers open");
        const about = await dashboard.page.evaluate(async () => ((await (await fetch("/api/about")).json()) as { build: string }).build);
        expect(first!.build).toBe(about);
        expect(first!.browser).toMatchObject({ name: "Chrome", system: "Linux", device: "desktop" });
        expect(first!.unmeasured).toEqual([]);
        expect(first!.window.frames).not.toBeNull();
        const said = await timings();
        expect(said).toContain(`Build ${about}, `);
        expect(said).toMatch(/\n {4}kind +keys +p50 +p75 +p95 +p99 +max +waited p95 +handled p95\n/);
        expect(said).toMatch(/\n {4}typing +5 /);
    });

    it("sends what it measured as its tab closes, which the demo keeps once", async () => {
        const before = written();
        const dashboard = await open(served.url);
        try {
            const review = await dashboard.review();
            await review.holds(DEMO_ITEM);
            await dashboard.keys.press(["j", "k"], 50);
            await aSecondOn(dashboard.page);
            await dashboard.page.close();
            await keptAfter(before);
        } finally {
            await dashboard.close();
        }
        const closed = since(before, await read());
        expect(closed.map(counted)).toEqual([{ motion: 2 }]);
        // Hidden and gone at once, the page sends it once, its answer not yet come when it goes.
        expect(since(before, written())).toHaveLength(1);
    });

    it("measures nothing in a browser it's switched off in from the palette, until it's switched on there", async () => {
        const before = written();
        await using dashboard = await open(served.url);
        const review = await dashboard.review();
        await review.holds(DEMO_ITEM);
        expect(await timingsInPalette(dashboard)).toMatch(/^⏎ measuring how long each key takes to reach the screen in this browser/);
        await dashboard.keys.press(["Enter"]);
        expect(await dashboard.page.evaluate(() => localStorage.getItem("lup-timings"))).toBe("off");
        // Kept in the browser: the page loaded again stays switched off.
        await dashboard.page.reload();
        await (await dashboard.review()).holds(DEMO_ITEM);
        expect(await timingsInPalette(dashboard)).toMatch(/^⏎ not measuring how long keys take to reach the screen: switched off in this browser/);
        await dashboard.keys.press(["Escape"]);
        await backInReview(dashboard);
        await dashboard.keys.press(["j", "k", "j", "k"], 50);
        await aSecondOn(dashboard.page);
        await hide(dashboard.page);
        await timingsInPalette(dashboard);
        await dashboard.keys.press(["Enter"]);
        expect(await dashboard.page.evaluate(() => localStorage.getItem("lup-timings"))).toBeNull();
        await backInReview(dashboard);
        await dashboard.keys.press(["j"]);
        await aSecondOn(dashboard.page);
        await hide(dashboard.page);
        await keptAfter(before);
        expect(since(before, await read()).map(counted)).toEqual([{ motion: 1 }]);
    });
});
