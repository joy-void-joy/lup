// The dashboard open in the room's Chromium: headless, or with a window on a virtual display of its own for real key
// events, its review's editor, keys sent without waiting on the page, its CPU slowed, and in view of someone reading it
// only as a script says.
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
    /**
     * In view of someone reading it all along, as the operator's tab is. Left out, it's in view of no one but as
     * `Dashboard.looks` puts it there: what's new on the page is read by being on screen for a time (`page/src/seeing.ts`),
     * a script's keys are nobody's eyes, and a page in view would read what a test's steps leave on screen as the time
     * they take goes by, as long as the machine's load makes it, a test's assertions changing with it.
     */
    inView?: boolean;
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
    /**
     * Put the page in view of someone reading it for `ms` of its clock, from now, and run the clock on as far
     * (`OpenOptions.clock`, which it needs), the page out of view again once that time is up, unless it's opened in
     * view: what's on screen is read by that time alone, however long the steps around it take.
     */
    looks(ms: number): Promise<void>;
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
    const opening: Opened = {
        end: async () => {
            await browser.close();
            await screen?.close();
        },
        ended: null,
        owner,
    };
    opened.add(opening);
    const close = async () => {
        opened.delete(opening);
        await opening.end();
    };
    try {
        const page = await browser.newPage({ viewport });
        const thrown: Error[] = [];
        page.on("pageerror", (error) => thrown.push(error));
        const session = await page.context().newCDPSession(page);
        await inViewOnlyAsLooked(page, options.inView ?? false);
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
            async looks(ms) {
                if (!(options.clock ?? false)) {
                    throw new Error("`looks` runs the page's clock, which a page opened without `clock` doesn't have");
                }
                await page.evaluate((ms) => {
                    (globalThis as unknown as { lupDriveInView: InView }).lupDriveInView.until = performance.now() + ms;
                }, ms);
                await page.clock.runFor(ms);
            },
            close,
            [Symbol.asyncDispose]: close,
        };
    } catch (failed) {
        await close();
        throw failed;
    }
}

/** A dashboard open, as `endAll` ends it: why it was ended, where it was, and what opened it (`owning`). */
interface Opened {
    end: () => Promise<void>;
    ended: string | null;
    owner: string | null;
}

/** Each dashboard open in this process and not yet closed by whoever opened it, or forgotten with its owner (`forget`). */
const opened = new Set<Opened>();

/** What the dashboards opened from now on are opened by (`owning`): none for what's shared, opened outside any test. */
let owner: string | null = null;

/** Say that the dashboards opened from now on are `by`'s own, a test's, or shared, where it's none (`forget`). */
export function owning(by: string | null): void {
    owner = by;
}

/**
 * Forget each dashboard `by` opened that was ended (`endAll`): a test that ran out of its time never closes what it
 * opened for itself, which no other test shares.
 */
export function forget(by: string): void {
    for (const each of [...opened]) {
        if (each.owner === by && each.ended !== null) {
            opened.delete(each);
        }
    }
}

/**
 * End every dashboard open in this process, saying `why`: its browser closed, so what a test goes on doing on its page
 * after vitest has moved on, the test having run out of its time, fails at once rather than reaching the next test's
 * (`drive/stopping.ts`). Each stays ended (`ended`) until whoever opened it closes it.
 */
export async function endAll(why: string): Promise<void> {
    const ending = [...opened].filter((each) => each.ended === null);
    for (const each of ending) {
        each.ended = why;
    }
    await Promise.all(ending.map((each) => each.end()));
}

/** Why a dashboard still open was ended (`endAll`); none where none was. */
export function ended(): string | null {
    return [...opened].find((each) => each.ended !== null)?.ended ?? null;
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

/** Whether a page is in view, as the driver holds it in the page: all along, or until a time of its clock. */
interface InView {
    always: boolean;
    /** Until when, as the page's `performance.now` counts it, as `Dashboard.looks` put it in view. */
    until: number;
}

/**
 * Have each document `page` loads read itself as in view only where `always` says so, or until the time
 * `Dashboard.looks` gives: else `document.visibilityState` says `hidden`, and `document.hidden` true, as for a tab behind
 * another, which is all the page's eye asks of it (`page/src/useSeeing.ts`), where headless Chromium shows every page.
 * No `visibilitychange` is sent as it goes out of view: the page would take it as the tab going, and read what's on
 * screen.
 *
 * Until a time of the page's own clock, rather than as long as a switch is on: the clock goes on by itself between the
 * driver's calls, so a page put in view just before `runFor` starts would count that time too, as long as the
 * machine's load makes it, where a span of the clock counts the same whenever it runs.
 */
async function inViewOnlyAsLooked(page: Page, always: boolean): Promise<void> {
    await page.addInitScript((always: boolean) => {
        const inView: InView = { always, until: -Infinity };
        Object.assign(globalThis, { lupDriveInView: inView });
        const shown = () => inView.always || performance.now() < inView.until;
        const visibility = Object.getOwnPropertyDescriptor(Document.prototype, "visibilityState")?.get;
        const hidden = Object.getOwnPropertyDescriptor(Document.prototype, "hidden")?.get;
        if (visibility === undefined || hidden === undefined) {
            throw new Error("the driver keeps the page out of view through `Document.prototype.visibilityState`, which this browser doesn't have");
        }
        Object.defineProperty(Document.prototype, "visibilityState", {
            configurable: true,
            enumerable: true,
            get(this: Document) {
                return shown() ? (visibility.call(this) as DocumentVisibilityState) : "hidden";
            },
        });
        Object.defineProperty(Document.prototype, "hidden", {
            configurable: true,
            enumerable: true,
            get(this: Document) {
                return shown() ? (hidden.call(this) as boolean) : true;
            },
        });
    }, always);
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
