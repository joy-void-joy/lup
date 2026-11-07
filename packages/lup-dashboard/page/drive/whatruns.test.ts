// What runs, as a row of the review's list and a buffer of its own (`docs/dashboard.md`, *What runs*): Space d takes a box
// in and Space x leaves it out, as marks, every box of a send one change; Space m merges, apart, the send not waiting; a
// comment on a branch reaches who landed it; a version runs again from its line. Each is the host's own handler over the
// demo's state, with what stands in for git and a room (`lup_dashboard/trialed.py`), and the host's restart cut
// (`lup_dashboard/handled.py`). No real switch runs here: a room has no podman.
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

/** Return once no line of the buffer on screen holds `text`. */
const gone = (text: string) => dashboard.page.waitForFunction((text) => ![...document.querySelectorAll(".buffer .cm-line")].some((each) => each.textContent?.includes(text) === true), text);

/** The body of each request of `kind` the page sends while `work` runs. */
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

/** What's drawn in place of each mark's line's first characters, as the page has it now. */
const drawn = () => dashboard.page.evaluate(() => [...document.querySelectorAll(".mark-drawn")].map((each) => each.textContent ?? ""));

describe("what runs, in the review", () => {
    beforeAll(async () => {
        served = await demo({ size: 0, panes: "opened", mergeTakes: 5 });
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

    it("lists a row saying what runs, whose Enter opens it as an ordinary buffer, what's left out folded", async () => {
        const list = await listText();
        const row = list.findIndex((each) => each.includes("what runs · dev + clearer-marks"));
        expect(row).toBeGreaterThan(list.findIndex((each) => each.includes("what's for you")));
        expect(list[row]).toContain("◇1");
        await openWhatRuns();
        const text = await review.text();
        expect(text).toContain("[x] clearer-marks");
        expect(text).toContain("[ ] rival-marks");
        expect(text).toContain("conflicts with `clearer-marks`");
        expect(text).toContain("out · 1");
        expect(text).toContain(" *  dev d38dbd2 + clearer-marks steady-list");
    });

    it("says on the line of keys what each key would do on a box, and what that takes, before it's pressed", async () => {
        await review.goTo("[x] clearer-marks");
        await dashboard.page.waitForFunction(() => document.querySelector(".keys")?.textContent?.includes("[x] clearer-marks") === true);
        const line = (await dashboard.page.locator(".keys").first().textContent()) ?? "";
        expect(line).toContain("␣x leave it out");
        expect(line).toContain("␣m merge it onto dev");
        // Ticked, it takes no yes: only what could change it.
        expect(line).not.toContain("␣d");
    });

    it("draws Space x as the box changing, moving nothing until Ctrl+Enter, and takes it off with the key again", async () => {
        await review.goTo("[x] clearer-marks");
        const nothing = await sending("module-act", async () => {
            await dashboard.keys.press([" ", "x"]);
            await says("leave it out");
        });
        expect(nothing).toEqual([]);
        expect(await drawn()).toEqual(["[ ]"]);
        // The box is the mark: the line isn't struck through.
        expect(await dashboard.page.locator(".buffer .cm-line.is-marked.mark-decline").count()).toBe(0);
        expect(await review.text()).toContain("[x] clearer-marks");
        await dashboard.keys.press([" ", "x"]);
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("leave it out") !== true);
        expect(await drawn()).toEqual([]);
    });

    it("marks nothing with a key saying what a box says already", async () => {
        await review.goTo("[x] steady-list");
        await dashboard.keys.press([" ", "d"]);
        await says("No reply drafted");
        expect(await drawn()).toEqual([]);
    });

    it("sends a box as a change of it alone, and what it alone kept out comes in", async () => {
        await review.goTo("[x] clearer-marks");
        await dashboard.keys.press([" ", "x"]);
        await says("leave it out");
        const sent = await sending("module-act", async () => {
            await send();
            await review.holds("[x] rival-marks");
        });
        expect(sent).toHaveLength(1);
        expect(sent[0]).toMatchObject({ action: "pick", arguments: [{ branch: "clearer-marks", on: false }] });
        await review.holds("waits on your yes");
        await says("No reply drafted");
    });

    it("sends every box of a send as one change, the host moving there and the buffer saying so", async () => {
        await review.goTo("[x] rival-marks");
        await dashboard.keys.press([" ", "x"]);
        await review.goTo("[x] steady-list");
        await dashboard.keys.press([" ", "x"]);
        await says("leave it out");
        const sent = await sending("module-act", async () => {
            await send();
            await review.holds("what runs · dev\n");
        });
        expect(sent).toHaveLength(1);
        expect(sent[0]).toMatchObject({ action: "pick", arguments: [{ branch: "rival-marks", on: false }, { branch: "steady-list", on: false }] });
        await says("No reply drafted");
    });

    it("runs a version again with Space d, its star drawn, and the boxes follow", async () => {
        await review.goTo("dev d38dbd2 + clearer-marks steady-list");
        await dashboard.keys.press([" ", "d"]);
        await says("run this version again");
        expect(await drawn()).toEqual([" *  "]);
        await send();
        await review.holds(" *  dev d38dbd2 + clearer-marks steady-list");
        await review.holds("[x] clearer-marks");
        await review.holds("[x] steady-list");
    });

    it("goes one a send with what may move the host, the other kept drafted, said, and what went going no more", async () => {
        await review.goTo("dev d38dbd2 + steady-list");
        await dashboard.keys.press([" ", "d"]);
        await review.goTo("[x] clearer-marks");
        await dashboard.keys.press([" ", "x"]);
        const sent = await sending("module-act", async () => {
            await send();
            await told("what moves the host goes one a send");
        });
        expect(sent).toHaveLength(1);
        expect(sent[0]).toMatchObject({ action: "run_again" });
        await review.holds(" *  dev d38dbd2 + steady-list");
        await says("leave it out");
        const again = await sending("module-act", async () => {
            await send();
            await says("No reply drafted");
        });
        expect(again).toHaveLength(1);
        expect(again[0]).toMatchObject({ action: "pick", arguments: [{ branch: "clearer-marks", on: false }] });
    });

    it("keeps a change the host refuses drafted, saying why in its words, and sends it once it's put right", async () => {
        await review.goTo("[ ] rival-marks");
        await dashboard.keys.press([" ", "d"]);
        await review.goTo("[ ] clearer-marks");
        await dashboard.keys.press([" ", "d"]);
        await says("take it in");
        await send();
        await told("can't be picked together");
        await says("take it in");
        await review.goTo("[ ] rival-marks");
        await dashboard.keys.press([" ", "d"]);
        await send();
        await review.holds("[x] clearer-marks");
        await says("No reply drafted");
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

    it("merges apart with Space m: the send goes at once, words typed and another send carrying on while it runs", async () => {
        await review.goTo("[x] steady-list");
        await dashboard.keys.press([" ", "m"]);
        await says("merge it onto dev");
        await send();
        await review.holds("merging: its gate runs");
        // The send's done, and what's written now is kept through the merge's end.
        await review.goTo("[x] clearer-marks");
        await review.comment();
        await review.inMode("insert");
        await dashboard.keys.type("Typed while it merges");
        await dashboard.page.keyboard.press("Escape");
        await review.inMode("normal");
        const asked = await sending("inbox-send-draft", async () => {
            await send();
            await says("No reply drafted");
        });
        expect(asked).toHaveLength(1);
        await gone("merging: its gate runs");
        await review.holds("Landed `steady-list` on `dev`");
    });

    it("keeps what moves the host drafted while a merge runs, as a restart would stop its gate", async () => {
        await review.goTo("[x] clearer-marks");
        await dashboard.keys.press([" ", "m"]);
        await send();
        await review.holds("merging: its gate runs");
        await review.goTo("[ ] rival-marks");
        await dashboard.keys.press([" ", "d"]);
        await send();
        await told("moving the host now would stop it");
        await says("take it in");
        await review.goTo("[ ] rival-marks");
        await dashboard.keys.press([" ", "d"]);
        await says("No reply drafted");
        await gone("merging: its gate runs");
    });

    it("says on its line what stopped a merge, in the host's words, which Space m tries again", async () => {
        await review.goTo("[ ] rival-marks");
        await dashboard.keys.press([" ", "m"]);
        await send();
        await review.holds("Not landed: the gate failed on the merge of `rival-marks`");
        await review.holds("1 failed, 3808 passed");
        await review.goTo("Not landed: the gate failed");
        await dashboard.page.waitForFunction(() => document.querySelector(".keys")?.textContent?.includes("␣m") === true);
    });
});

describe("what's done while a reply is being sent", () => {
    beforeAll(async () => {
        served = await demo({ size: 0, panes: "opened" });
        dashboard = await open(served.url);
        review = await dashboard.review();
        await review.settled();
        await openWhatRuns();
    });

    afterAll(async () => {
        await dashboard?.close();
        await served?.close();
    });

    it("keeps words being typed and marks made while an action is asked, and asks nothing twice", async () => {
        const { page } = dashboard;
        // An action the host is slow to answer, held here so the test decides when it does.
        let release: () => void = () => undefined;
        const held = new Promise<void>((resolve) => {
            release = resolve;
        });
        await dashboard.route("**/api/ask", async (route) => {
            if (route.request().postData()?.includes('"module-act"') === true) {
                await held;
            }
            await route.continue();
        });
        /** What the host keeps of the draft: each remark's words, and what each mark says. */
        const kept = () =>
            page.evaluate(async () => {
                const answer = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "inbox-draft" }) });
                const read = (await answer.json()) as { draft?: { remarks?: { text: string }[]; marks?: { says: string }[] } };
                return { remarks: (read.draft?.remarks ?? []).map((each) => each.text), marks: (read.draft?.marks ?? []).map((each) => each.says) };
            });
        await review.goTo("[x] clearer-marks");
        await dashboard.keys.press([" ", "x"]);
        await says("leave it out");
        await dashboard.keys.press(["Control+Enter"]);
        await says("Sending your reply");
        // Marked, and words begun, before the answer comes, the words too recent for the page to have laid them out.
        await review.goTo("[x] steady-list");
        await dashboard.keys.press([" ", "m"]);
        await review.comment();
        await review.inMode("insert");
        await dashboard.keys.type("first part");
        release();
        await page.waitForFunction(() => document.querySelector('.status [data-sending="sending"]') === null);
        await review.holds("first part");
        await dashboard.keys.type(" second part");
        await page.keyboard.press("Escape");
        await review.inMode("normal");
        await review.holds("first part second part");
        await says("to lup-impl/parser: a remark");
        await says("merge it onto dev");
        // What was sent went: it's nowhere in what's drafted now, for the next send to do again.
        expect(await page.locator(".status").first().innerText()).not.toContain("leave it out");
        await expect.poll(async () => (await kept()).remarks, { timeout: 10000 }).toEqual(["first part second part"]);
        const draft = await kept();
        expect(draft.remarks).toEqual(["first part second part"]);
        expect(draft.marks.some((each) => each.includes("merge it onto dev"))).toBe(true);
        expect(draft.marks.some((each) => each.includes("leave it out"))).toBe(false);
        expect(dashboard.thrown).toEqual([]);
    });
});
