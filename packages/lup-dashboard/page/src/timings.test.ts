import { describe, expect, it } from "vitest";

import { Tally, anyKey, browserOf, fitted, invoked, stepped, type EventEntry, type Report, type Window } from "./timings";

/** Event Timing's entry of a key going down at `at`, painted `duration` after, its handlers starting `waited` after it went down and running `handled`. */
function keydown(at: number, duration: number, waited = 0, handled = 0): EventEntry {
    return { name: "keydown", startTime: at, duration, processingStart: at + waited, processingEnd: at + waited + handled };
}

const START = new Date("2026-10-30T09:00:00Z");
const END = new Date("2026-10-30T09:05:00Z");

describe("what the script counts", () => {
    it("matches each key's entry to the key by its time, in the kind the page named it as it went down", () => {
        const tally = new Tally(false);
        tally.pressed(100.25, "typing");
        tally.pressed(180.5, "motion");
        tally.entry(keydown(100.25, 24, 3.9, 12.2));
        tally.entry({ ...keydown(100.25, 40), name: "keyup" });
        tally.entry(keydown(180.5, 48, 20, 3));
        const window = tally.closed(1, START, END);
        expect(window?.keys).toEqual({
            typing: { painted: { 24: 1 }, waited: { 0: 1 }, handled: { 16: 1 }, under: 0 },
            motion: { painted: { 48: 1 }, waited: { 24: 1 }, handled: { 0: 1 }, under: 0 },
        });
        expect(window?.unmatched).toBe(0);
        expect(window?.frames).toBeNull();
    });

    it("takes the nearest key within a millisecond where a browser stamps the two apart, and counts an entry matching none", () => {
        const tally = new Tally(false);
        tally.pressed(100, "typing");
        tally.entry(keydown(100.6, 24));
        tally.entry(keydown(500, 32));
        expect(tally.closed(1, START, END)).toMatchObject({ keys: { typing: { painted: { 24: 1 } } }, unmatched: 1 });
    });

    it("counts a key under the floor once a later key's entry came, or once it's older than asked, the rest waiting on", () => {
        const tally = new Tally(false);
        tally.pressed(10, "typing");
        tally.pressed(20, "typing");
        tally.pressed(30, "typing");
        tally.pressed(5_000, "fold");
        tally.pressed(70_000, "motion");
        tally.entry(keydown(30, 16));
        tally.settled(10_000);
        const first = tally.closed(1, START, END);
        expect(first?.keys).toEqual({
            typing: { painted: { 16: 1 }, waited: { 0: 1 }, handled: { 0: 1 }, under: 2 },
            fold: { painted: {}, waited: {}, handled: {}, under: 1 },
        });
        // The motion's entry comes in the next window.
        tally.entry(keydown(70_000, 120));
        expect(tally.closed(2, END, END)?.keys).toEqual({ motion: { painted: { 120: 1 }, waited: { 0: 1 }, handled: { 0: 1 }, under: 0 } });
    });

    it("closes nothing where nothing was counted, keeping the keys waiting for their entry", () => {
        const tally = new Tally(true);
        tally.pressed(10, "typing");
        tally.sized({ lines: 100 });
        expect(tally.closed(1, START, END)).toBeNull();
        tally.entry(keydown(10, 16));
        expect(tally.closed(1, START, END)?.keys).toHaveProperty("typing");
    });

    it("keeps the largest of each of the page's measures seen in the window", () => {
        const tally = new Tally(false);
        tally.sized({ lines: 15_203, items: 40, "drawers open": 2 });
        tally.sized({ lines: 48_912, items: 38, "drawers open": 0 });
        tally.pressed(1, "typing");
        tally.entry(keydown(1, 16));
        expect(tally.closed(1, START, END)?.size).toEqual({ lines: 48_912, items: 40, "drawers open": 2 });
        tally.pressed(2, "typing");
        tally.entry(keydown(2, 16));
        expect(tally.closed(2, END, END)?.size).toEqual({});
    });

    it("counts long animation frames and what ran in them, the longest-running first, a few of them", () => {
        const tally = new Tally(true, 2);
        tally.frame({
            duration: 120.4,
            blockingDuration: 70.2,
            scripts: [
                { invoker: "WebSocket.onmessage", invokerType: "event-listener", duration: 80 },
                { invoker: "Window.requestAnimationFrame", invokerType: "user-callback", duration: 20 },
            ],
        });
        tally.frame({ duration: 60, scripts: [{ invoker: "DIV#someone.onkeydown", invokerType: "event-listener", duration: 50 }] });
        expect(tally.closed(1, START, END)?.frames).toEqual({
            count: 2,
            total: 180,
            blocking: 70,
            longest: 120,
            ran: { "event-listener onmessage": 80, "event-listener onkeydown": 50 },
        });
        // A browser reporting them says so in each window, though none came.
        tally.pressed(1, "typing");
        tally.entry(keydown(1, 16));
        expect(tally.closed(2, END, END)?.frames).toEqual({ count: 0, total: 0, blocking: 0, longest: 0, ran: {} });
    });
});

describe("what's kept of what began a long frame", () => {
    it("is its invoker's type and the event or API, never an element or a script's address", () => {
        expect(invoked({ invoker: "BUTTON#delete-account.onclick", invokerType: "event-listener" })).toBe("event-listener onclick");
        expect(invoked({ invoker: "https://site.example/app.js", invokerType: "classic-script" })).toBe("classic-script");
        expect(invoked({ invoker: "Response.json.then", invokerType: "resolve-promise" })).toBe("resolve-promise Response.json.then");
        expect(invoked({})).toBe("script");
    });
});

describe("a key's time in Event Timing's steps", () => {
    it("rounds to 8 ms, never below 0", () => {
        expect([stepped(3.9), stepped(4.1), stepped(12.2), stepped(-0.3)]).toEqual([0, 8, 16, 0]);
    });
});

describe("the kind of key where the page names none", () => {
    it("is other, a modifier alone left out", () => {
        expect([anyKey({ key: "j" }), anyKey({ key: "Shift" }), anyKey({ key: "Dead" })]).toEqual(["other", null, "other"]);
    });
});

describe("the browser", () => {
    it("is read from its user agent's product tokens and its pointer, never kept whole", () => {
        const firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0";
        const chrome = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36";
        const safari = "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Mobile/15E148 Safari/604.1";
        const edge = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0";
        const headless = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/151.0.0.0 Safari/537.36";
        const desktop = { coarse: false, shorter: 1080, cores: 16 };
        expect(browserOf({ userAgent: firefox, ...desktop })).toEqual({ name: "Firefox", version: "144", system: "Linux", device: "desktop", cores: 16 });
        expect(browserOf({ userAgent: chrome, coarse: true, shorter: 412, cores: 8 })).toMatchObject({ name: "Chrome", version: "151", system: "Android", device: "phone" });
        expect(browserOf({ userAgent: safari, coarse: true, shorter: 390, cores: null })).toMatchObject({ name: "Safari", version: "19", system: "iOS", device: "phone", cores: null });
        expect(browserOf({ userAgent: edge, ...desktop })).toMatchObject({ name: "Edge", version: "151", system: "Windows" });
        expect(browserOf({ userAgent: headless, ...desktop })).toMatchObject({ name: "Chrome", version: "151", system: "Linux" });
        expect(browserOf({ userAgent: "curl/8", coarse: true, shorter: 800, cores: 4 })).toMatchObject({ name: "other", version: "", system: "other", device: "tablet" });
    });
});

describe("a report's length", () => {
    it("carries the latest windows that fit, the earlier left for the next report, at least one", () => {
        const window = (sequence: number): Window => ({
            sequence,
            start: START.toISOString(),
            end: END.toISOString(),
            size: {},
            keys: { typing: { painted: { 16: sequence }, waited: {}, handled: {}, under: 0 } },
            unmatched: 0,
            frames: null,
        });
        const report: Report = {
            page: "dashboard",
            session: "a1b2c3",
            build: null,
            browser: { name: "Firefox", version: "144", system: "Linux", device: "desktop", cores: 16 },
            unmeasured: [],
            windows: [1, 2, 3].map(window),
        };
        const wrapped = (each: Report) => ({ kind: "page-timings-keep", report: each });
        const one = JSON.stringify(wrapped({ ...report, windows: [window(3)] })).length;
        expect(fitted(report, wrapped).map((each) => each.sequence)).toEqual([1, 2, 3]);
        expect(fitted(report, wrapped, one + 200).map((each) => each.sequence)).toEqual([2, 3]);
        expect(fitted(report, wrapped, 10).map((each) => each.sequence)).toEqual([3]);
    });
});
