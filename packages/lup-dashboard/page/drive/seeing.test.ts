// What's new is read by being on screen (`docs/dashboard.md`, *Review marks*): for long enough, in a tab they're in, their
// hands not on a comment, its mark moving on the host as what was seen leaves the screen or the tab goes. Over the
// page's own clock, which the test moves, each on a demo of its own, what one reads being gone for the next.
import type { Request } from "playwright";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

/** The header of an item of each agent's, which says it's new until it's read. */
const SURVEY = "── @66 note · new · ";
const VOICE = "── @56 turn ended · edited · new · ";
const LEAD = "── @62 note · new · ";

let served: Demo;
let dashboard: Dashboard;
let review: Review;
/** What the page told the host: each mark moved, as it went. */
let told: Record<string, unknown>[] = [];

beforeEach(async () => {
    told = [];
    // Nothing of the demo's own comes meanwhile: what's on screen stays there as the page's clock is moved.
    served = await demo({ size: 0, arrives: 3600, grows: 3600, typesRead: 0 });
    dashboard = await open(served.url, { clock: true });
    dashboard.page.on("request", (request: Request) => {
        if (request.method() === "POST" && request.url().endsWith("/api/ask")) {
            const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
            if (body.kind === "review-mark") {
                told.push(body);
            }
        }
    });
    review = await dashboard.review();
    await review.holds(SURVEY);
    await review.settled(1500);
});

afterEach(async () => {
    expect(dashboard.thrown).toEqual([]);
    await dashboard.close();
    await served.close();
});

/** Let the page's clock run on for `ms`, as a time in view, a tick at a time. */
const passes = (ms: number) => dashboard.page.clock.runFor(ms);

/** Go to `text`, in the middle of the view, all of what's under it there. */
const onScreen = async (text: string) => {
    await review.goTo(text);
    // Its line drawn first: `zz` asks vim where the line is on screen, which it can't say of one a search hasn't brought in yet.
    await review.until(
        "brought the line in",
        (view) => {
            const at = view.state.selection.main.head;
            return view.coordsAtPos(at) !== null;
        },
    );
    await dashboard.keys.press(["z", "z"]);
    await review.settled(300);
    await review.until("had the line in view", (view) => {
        const place = view.coordsAtPos(view.state.selection.main.head);
        const within = view.scrollDOM.getBoundingClientRect();
        return place !== null && place.top >= within.top && place.bottom <= within.bottom;
    });
};

/** Go to the end of the review, or its start, and give the page time to say what moved. */
const away = async (...keys: string[]) => {
    await dashboard.keys.press(keys);
    await review.settled(300);
    await passes(4000);
    await review.settled(300);
};

/** Each mark told the host, by what each is on. */
const moved = () => told.flatMap((each) => each.marks as { key: Record<string, unknown>; up_to: string; seen: boolean }[]);

/** Return once the review no longer holds `text`. */
const gone = (text: string) => review.until(`let go of ${text}`, (view, wanted) => !view.state.doc.toString().includes(wanted as string), text);

describe("what's new is read by being on screen, in headless Chromium", () => {
    it("reads nothing on a page nobody has touched, however long it stays open", async () => {
        await passes(10_000);
        expect(told).toEqual([]);
    });

    it("leaves what's on screen new while it's on screen, and reads it as it leaves", async () => {
        await onScreen("── @66 note");
        await passes(10_000);
        await review.settled(300);
        expect(moved()).toEqual([]);
        await review.holds(SURVEY);
        await away("g", "g");
        await expect.poll(() => moved().filter((each) => each.up_to === "66").length, { timeout: 15_000 }).toBeGreaterThan(0);
        const [mark] = moved().filter((each) => each.up_to === "66");
        expect(mark?.seen).toBe(true);
        // Their agent's mark, as what's listed reads threads and this isn't one's own buffer.
        expect(mark?.key.node).toBeUndefined();
        expect(mark?.key.session).toEqual(expect.any(String));
        // Read, it no longer says it's new, and the item stays where it can be read, still to mark done.
        await gone(SURVEY);
        await review.holds("@66 note");
    });

    it("moves the thread's own mark in its own buffer, as another takes the screen", async () => {
        await dashboard.openRow("@auth-survey");
        await review.until("read the thread whole", (view) => view.state.doc.toString().startsWith("━━ @auth-survey") && !view.state.doc.toString().includes("reading…"));
        await onScreen("── @66 note");
        await passes(10_000);
        await review.settled(300);
        await dashboard.openRow("what's for you");
        await review.holds("── @54 approval");
        await expect.poll(() => moved().filter((each) => typeof each.key.node === "number" && each.up_to === "66").length, { timeout: 15_000 }).toBeGreaterThan(0);
    });

    it("leaves what was scrolled past quickly new", async () => {
        await onScreen("── @56 turn ended");
        await passes(500);
        await away("G");
        expect(moved()).toEqual([]);
        await review.holds(VOICE);
    });

    it("counts no time while they're writing a comment, what's beside it staying new", async () => {
        await onScreen("── @62 note");
        await review.comment();
        await passes(10_000);
        await dashboard.keys.press(["Escape"]);
        await review.inMode("normal");
        await away("G");
        expect(moved().filter((each) => each.up_to === "62")).toEqual([]);
        await review.holds(LEAD);
    });

    it("reads nothing of a drawer closed, and what's been on screen of one open as it leaves", async () => {
        await onScreen("messages · 5 · 5 new");
        await passes(5000);
        await away("g", "g");
        const ofTheDrawer = () => moved().filter((each) => each.key.drawer === "messages");
        expect(ofTheDrawer()).toEqual([]);
        await onScreen("messages · 5 · 5 new");
        await dashboard.keys.press(["z", "o"]);
        await review.settled(300);
        await dashboard.keys.press(["z", "t"]);
        await review.settled(300);
        await passes(10_000);
        await away("g", "g");
        await expect.poll(() => ofTheDrawer().length, { timeout: 15_000 }).toBeGreaterThan(0);
        expect(ofTheDrawer().every((each) => each.seen)).toBe(true);
        await gone("messages · 5 · 5 new");
    });

    it("reads what's been seen as the tab is hidden, whatever's still on screen", async () => {
        await onScreen("── @66 note");
        await passes(10_000);
        const ofIt = () => moved().filter((each) => each.up_to === "66");
        expect(ofIt()).toEqual([]);
        await dashboard.page.evaluate(() => {
            Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
            document.dispatchEvent(new Event("visibilitychange"));
        });
        await review.settled(300);
        await expect.poll(() => ofIt().length, { timeout: 15_000 }).toBe(1);
    });
});
