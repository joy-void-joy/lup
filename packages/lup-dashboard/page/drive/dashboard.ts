// The dashboard open in the room's Chromium: headless, or with a window on a virtual display of its own for real key
// events, its review's editor, keys sent without waiting on the page, and its CPU slowed.
import { chromium, errors, type Browser, type CDPSession, type Page, type Route } from "playwright";

import { display, type Display, type Layout } from "./display.ts";
import { keys, type Keys } from "./keys.ts";
import { review, type Review } from "./review.ts";

/** The room's Chromium, a package of its image: Playwright's own browser isn't installed. */
const CHROMIUM = "/usr/sbin/chromium";

/** Where `Dashboard.route` asks whether the page's requests reach a route, which answers 204: the server answers nothing here. */
const ROUTED = "/lup-drive-routed";

/** How the dashboard is opened. */
export interface OpenOptions {
    /**
     * A window on a virtual display of its own whose keyboard has this layout, for real key events through
     * `Dashboard.display`; headless where it isn't given.
     */
    windowed?: Layout;
    /** The page's size, in pixels: 1600 by 1000 unless given, as #341's measures took it. */
    viewport?: { width: number; height: number };
    /** A clock a script moves, Playwright's (`page.clock.runFor`), which goes on by itself until then: as what's timed on the page is, a time on screen among it. */
    clock?: boolean;
}

/** The dashboard open in the room's Chromium, until it's closed. */
export interface Dashboard extends AsyncDisposable {
    page: Page;
    browser: Browser;
    /** A DevTools session on the page, for what the driver doesn't offer. */
    session: CDPSession;
    /** Keys sent through the DevTools protocol, never waiting on the page. */
    keys: Keys;
    /** Where it's windowed, its display, which types as a keyboard does; null where it's headless. */
    display: Display | null;
    /**
     * What the page threw and didn't catch, as it came: an error in one of React's effects takes the page's whole tree
     * down, the review with it, so a script that waits on the review is told it.
     */
    thrown: Error[];
    /** The review's editor, once the page has made it. */
    review(): Promise<Review>;
    /** In panes, go into the list, open the first row saying `text`, found by vim's search there, and return once the keyboard's in its buffer. */
    openRow(text: string): Promise<void>;
    /**
     * Route what the page asks of `url` through `handler`, as `page.route` does, and return once the page's requests
     * reach a route. `page.route` returns before that's so: a key pressed straight after it, on a loaded machine, can
     * make a request that goes past the route to the server, as if there were none, and Playwright reports no such
     * request (`docs/field-notes.md`, *A route just set in Chromium*).
     */
    route(url: string, handler: (route: Route) => unknown): Promise<void>;
    /** Slow the page's CPU `rate` times, standing for a slower machine or browser; 1 for its own speed. */
    slow(rate: number): Promise<void>;
    close(): Promise<void>;
}

/**
 * Open the dashboard at `url`, its token in the fragment, as the operator's browser does, and return it once the page
 * has loaded: the demo's (`demo.ts`), or any other a room can reach.
 */
export async function open(url: string, options: OpenOptions = {}): Promise<Dashboard> {
    const viewport = options.viewport ?? { width: 1600, height: 1000 };
    const screen = options.windowed === undefined ? null : await display({ ...viewport, layout: options.windowed });
    let browser: Browser;
    try {
        browser =
            screen === null
                ? await chromium.launch({ executablePath: CHROMIUM })
                : await chromium.launch({
                      executablePath: CHROMIUM,
                      headless: false,
                      // The room names a Wayland display, for its clipboard, which Chromium would take over the virtual one.
                      args: ["--ozone-platform=x11", "--window-position=0,0", `--window-size=${viewport.width},${viewport.height}`],
                      env: screen.env,
                  });
    } catch (failed) {
        await screen?.close();
        throw failed;
    }
    const close = async () => {
        await browser.close();
        await screen?.close();
    };
    try {
        const page = await browser.newPage({ viewport });
        const thrown: Error[] = [];
        page.on("pageerror", (error) => thrown.push(error));
        const session = await page.context().newCDPSession(page);
        if (options.clock ?? false) {
            await page.clock.install();
        }
        await page.goto(url);
        if (screen !== null) {
            await keyboardReached(page, screen);
        }
        return {
            page,
            browser,
            session,
            keys: keys(session),
            display: screen,
            thrown,
            review: () => review(page, thrown),
            async openRow(text) {
                await keys(session).press([" ", "w", "h"]);
                await page.waitForFunction(() => document.activeElement?.closest(".list-buffer") != null, undefined, { polling: 50 });
                await page.keyboard.press("g");
                await page.keyboard.press("g");
                await page.keyboard.press("/");
                await page.keyboard.type(text.replaceAll("/", "\\/"));
                await page.keyboard.press("Enter");
                await page.keyboard.press("Enter");
                await page.waitForFunction(() => document.activeElement?.closest(".review-buffer") != null, undefined, { polling: 50 });
            },
            route: (url, handler) => routed(page, url, handler),
            async slow(rate) {
                await session.send("Emulation.setCPUThrottlingRate", { rate });
            },
            close,
            [Symbol.asyncDispose]: close,
        };
    } catch (failed) {
        await close();
        throw failed;
    }
}

/** Route what `page` asks of `url` through `handler`, and return once a request of the page's has reached a route, asking until one does. */
async function routed(page: Page, url: string, handler: (route: Route) => unknown): Promise<void> {
    await page.route(url, handler);
    await page.route(`**${ROUTED}`, (route) => route.fulfill({ status: 204 }));
    for (let asked = 0; asked < 100; asked += 1) {
        if (await page.evaluate(async (at) => (await fetch(at)).status === 204, ROUTED)) {
            await page.unroute(`**${ROUTED}`);
            return;
        }
    }
    throw new Error("the page's requests never reached a route set on it");
}

/**
 * Return once the page takes the display's keys: a windowed Chromium drops the first X key event it's sent, whatever it
 * is, so Shift is pressed, which types nothing, until the page has seen one.
 */
async function keyboardReached(page: Page, screen: Display): Promise<void> {
    await page.evaluate(() => {
        const seen = { shift: false };
        Object.assign(globalThis, { lupDriveShift: seen });
        addEventListener("keydown", (event) => (seen.shift ||= event.key === "Shift"), { capture: true });
    });
    const taken = () => (globalThis as unknown as { lupDriveShift: { shift: boolean } }).lupDriveShift.shift;
    for (let pressed = 0; pressed < 50; pressed += 1) {
        await screen.press(["shift"]);
        const reached = await page.waitForFunction(taken, undefined, { polling: 20, timeout: 100 }).then(
            () => true,
            // Not taken yet: pressed again.
            (failed: unknown) => {
                if (failed instanceof errors.TimeoutError) {
                    return false;
                }
                throw failed;
            },
        );
        if (reached) {
            return;
        }
    }
    throw new Error(`the page never took a key pressed on the display ${screen.name}`);
}
