// What runs, as a row of the review's list and a buffer of its own (`docs/dashboard.md`, *What runs*): a box ticked goes in
// the draft as any mark does, and Ctrl+Enter sends every box as one pick; a comment on a branch reaches who landed it; a
// merge, a drop and a version run again work from there, each the host's own handler over the demo's state, with the
// host's restart cut (`lup_dashboard/handled.py`). No real switch runs here: a room has no podman.
import type { Request } from "playwright";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

/** What the list says, a line a row. */
const listText = () => dashboard.page.evaluate(() => [...document.querySelectorAll(".list-buffer .cm-line")].map((each) => each.textContent ?? ""));

/** Return once the line under the review says `text`. */
const says = (text: string) => dashboard.page.waitForFunction((text) => document.querySelector(".status")?.textContent?.includes(text) === true, text);

/** Return once the top bar says `text`, of what a send came to. */
const told = (text: string) => dashboard.page.waitForFunction((text) => document.querySelector(".bar .said")?.textContent?.includes(text) === true, text);

/** Send the reply with Ctrl+Enter, returning once it's sent: a second press while it's being sent sends nothing more. */
async function send(): Promise<void> {
    await dashboard.keys.press(["Control+Enter"]);
    await dashboard.page.waitForFunction(() => document.querySelector('.status [data-sending="sending"]') === null);
}

/** Open what runs from the list, by vim's search there. */
async function openWhatRuns(): Promise<void> {
    const { page } = dashboard;
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.querySelector(".panes")?.getAttribute("data-mode") === "pane");
    await page.keyboard.press("h");
    await page.keyboard.press("i");
    await page.waitForFunction(() => document.querySelector(".panes")?.getAttribute("data-mode") === "normal");
    await page.keyboard.press("g");
    await page.keyboard.press("g");
    await page.keyboard.press("/");
    await page.keyboard.type("what runs");
    await page.keyboard.press("Enter");
    await page.keyboard.press("Enter");
    await review.holds("[x] steady-list");
}

/** Each request of `kind` the page sends while `work` runs. */
async function sending(kind: string, work: () => Promise<void>): Promise<Record<string, unknown>[]> {
    const { page } = dashboard;
    const sent: Record<string, unknown>[] = [];
    const heard = (request: Request) => {
        const body = request.url().endsWith("/api/ask") ? request.postData() : null;
        const read = body === null ? null : (JSON.parse(body) as Record<string, unknown>);
        if (read?.kind === kind) {
            sent.push(read);
        }
    };
    page.on("request", heard);
    await work();
    page.off("request", heard);
    return sent;
}

beforeAll(async () => {
    served = await demo({ size: 0, panes: "opened" });
    dashboard = await open(served.url);
    review = await dashboard.review();
    await review.settled();
});

afterEach(() => {
    expect(dashboard.thrown).toEqual([]);
});

afterAll(async () => {
    await dashboard?.close();
    await served?.close();
});

describe("what runs, in the review", () => {
    it("lists a row saying what runs, after the piles, whose Enter opens it as an ordinary buffer", async () => {
        const list = await listText();
        const row = list.findIndex((each) => each.includes("what runs · dev + clearer-marks"));
        expect(row).toBeGreaterThan(list.findIndex((each) => each.includes("No agent")));
        expect(list[row]).toContain("◇1");
        await openWhatRuns();
        const text = await review.text();
        expect(text).toContain("[x] clearer-marks");
        expect(text).toContain("[ ] rival-marks");
        expect(text).toContain("conflicts with `clearer-marks`");
        expect(text).toContain("versions");
        expect(text).toContain(" *  dev d38dbd2 + clearer-marks steady-list");
    });

    it("says on the line of keys what each key would do on a branch, and what that takes, before it's pressed", async () => {
        await review.goTo("[x] clearer-marks");
        const line = await dashboard.page.locator(".keys-line, .keys").first().innerText();
        expect(line).toContain("take it out: moves the host in seconds");
        expect(line).toContain("merge it onto dev");
        expect(line).toContain("drop it");
    });

    it("keeps a box ticked in the draft, moving nothing until Ctrl+Enter, and takes it off with the key again", async () => {
        await review.goTo("[x] clearer-marks");
        const nothing = await sending("module-act", async () => {
            await dashboard.keys.press([" ", "r"]);
            await says("take it out");
        });
        expect(nothing).toEqual([]);
        expect(await review.text()).toContain("[x] clearer-marks");
        await dashboard.keys.press([" ", "r"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("take it out") !== true);
    });

    it("sends every box marked as one pick, the host moving there and the buffer saying so", async () => {
        await review.goTo("[x] clearer-marks");
        await dashboard.keys.press([" ", "r"]);
        await review.goTo("[x] steady-list");
        await dashboard.keys.press([" ", "r"]);
        await says("take it out");
        const sent = await sending("module-act", async () => {
            await send();
            await review.holds("[ ] steady-list");
        });
        expect(sent).toHaveLength(1);
        expect(sent[0]).toMatchObject({ action: "pick", arguments: [{ branch: "clearer-marks", on: false }, { branch: "steady-list", on: false }] });
        await review.holds("[ ] clearer-marks");
        const list = await listText();
        expect(list.some((each) => each.includes("what runs · dev"))).toBe(true);
        // `dev` alone has a copy kept: the star's on it, and nothing's left drafted.
        expect(await review.text()).toContain(" *  dev d38dbd2 ");
        await told("The host moves to 2c0ffee");
    });

    it("runs a version again from its line, as a mark like any other", async () => {
        await review.goTo("dev d38dbd2 + clearer-marks steady-list");
        await dashboard.keys.press([" ", "r"]);
        await says("run this version again");
        await send();
        await review.holds(" *  dev d38dbd2 + clearer-marks steady-list");
        await review.holds("[x] clearer-marks");
        // Each pick of a set is a commit of `live`, and one version to the operator.
        const versions = (await review.text()).split("\n").filter((each) => each.includes("dev d38dbd2 + clearer-marks steady-list"));
        expect(versions).toHaveLength(1);
    });

    it("keeps a pick the host refuses drafted, saying why in its words", async () => {
        await review.goTo("[ ] rival-marks");
        await dashboard.keys.press([" ", "r"]);
        await send();
        await told("can't be picked together");
        await review.holds("[ ] rival-marks");
        expect(await dashboard.page.evaluate(() => document.querySelector(".status")?.textContent ?? "")).toContain("put it in");
        await review.goTo("[ ] rival-marks");
        await dashboard.keys.press([" ", "r"]);
    });

    it("writes a comment on a branch to who landed it, sent as any remark", async () => {
        await review.goTo("[x] steady-list");
        await review.comment();
        await review.inMode("insert");
        await dashboard.keys.type("Why this list?");
        await dashboard.page.keyboard.press("Escape");
        await review.inMode("normal");
        await says("to lup-impl/parser: a remark");
        const sent = await sending("inbox-send-draft", async () => {
            await send();
            await says("No reply drafted");
        });
        expect(sent).toHaveLength(1);
        expect(await review.text()).not.toContain("Why this list?");
    });

    it("merges a branch from its line, off trial and with nothing restarting", async () => {
        await review.goTo("[x] steady-list");
        await dashboard.keys.press([" ", "d"]);
        await says("merge it onto dev");
        await send();
        await told("is on `dev`");
        await dashboard.page.waitForFunction(() => ![...document.querySelectorAll(".buffer .cm-line")].some((each) => each.textContent?.includes("[x] steady-list") === true));
    });

    it("drops a branch from its line, off trial", async () => {
        await review.goTo("[ ] quiet-banner");
        await dashboard.keys.press([" ", "x"]);
        await says("drop it");
        await send();
        await dashboard.page.waitForFunction(() => ![...document.querySelectorAll(".buffer .cm-line")].some((each) => each.textContent?.includes("[ ] quiet-banner") === true));
    });
});
