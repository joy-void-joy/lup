// The review in two panes, as the page opens (`page/src/panes.ts`): the three levels
// of the keys, moving between the panes, a comment written in one buffer and still anchored as another comes and goes,
// search within the buffer on screen, what Ctrl+Enter sends from any of them, and what's read by being on screen.
import type { Request } from "playwright";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

/** The item the demo's guidance-voice session sent, whose group they're first in. */
const THEIR_ITEM = "── @45 note";

/** Words the demo holds nowhere: what's written in these tests. */
const WORDS = "Keep this anchored across buffers";

/** The page in Pane mode, and the pane selected there, as the page marks them. */
const paneMode = (dashboard: Dashboard) => dashboard.page.evaluate(() => document.querySelector(".panes")?.getAttribute("data-mode"));
const selected = (dashboard: Dashboard) => dashboard.page.evaluate(() => (document.querySelector(".pane.is-selected")?.classList.contains("pane-list") ? "list" : "buffer"));
const inList = (dashboard: Dashboard) => dashboard.page.evaluate(() => document.activeElement?.closest(".list-buffer") !== null && document.activeElement?.closest(".list-buffer") !== undefined);
const listText = (dashboard: Dashboard) => dashboard.page.evaluate(() => [...document.querySelectorAll(".list-buffer .cm-line")].map((each) => each.textContent ?? ""));

/** Return once the page says the mode is `mode`. */
async function inPaneMode(dashboard: Dashboard, mode: "pane" | "normal"): Promise<void> {
    await dashboard.page.waitForFunction((wanted) => document.querySelector(".panes")?.getAttribute("data-mode") === wanted, mode, { polling: 50 });
}

/** Go from the buffer into the list, and onto the row saying `text`, by vim's search there. */
async function listRow(dashboard: Dashboard, text: string): Promise<void> {
    const { page } = dashboard;
    if (!(await inList(dashboard))) {
        await page.keyboard.press("Escape");
        await page.keyboard.press("Escape");
        await inPaneMode(dashboard, "pane");
        await page.keyboard.press("h");
        await page.keyboard.press("i");
        await inPaneMode(dashboard, "normal");
    }
    await page.keyboard.press("g");
    await page.keyboard.press("g");
    await page.keyboard.press("/");
    await page.keyboard.type(text.replaceAll("/", "\\/"));
    await page.keyboard.press("Enter");
}

describe("the panes by agent", () => {
    let served: Demo;
    let dashboard: Dashboard;
    let review: Review;

    beforeAll(async () => {
        served = await demo({ size: 0 });
        dashboard = await open(served.url);
        review = await dashboard.review();
        await review.holds(THEIR_ITEM);
        await review.settled();
    });

    afterAll(async () => {
        await dashboard?.close();
        await served?.close();
    });

    it("opens on what's for the operator, with the list beside it, by agent and with No agent", async () => {
        const list = await listText(dashboard);
        expect(list.some((each) => each.includes("what's for you"))).toBe(true);
        expect(list.some((each) => each.includes("guidance-voice"))).toBe(true);
        expect(list.some((each) => each.includes("No agent"))).toBe(true);
        expect(dashboard.thrown).toEqual([]);
    });

    it("goes Insert, Normal, Pane with Esc, and no key in Pane mode acts on anything", async () => {
        const { page } = dashboard;
        await review.goTo(THEIR_ITEM);
        await review.comment();
        await page.keyboard.type("first");
        await page.keyboard.press("Escape");
        await review.inMode("normal");
        expect(await paneMode(dashboard)).toBe("normal");
        await page.keyboard.press("Escape");
        await inPaneMode(dashboard, "pane");
        const before = await review.text();
        // A mark, a chord, a comment, a motion, a send: none does anything here.
        for (const key of ["Space", "d", "x", "o", "j", "G", "/", "z", "Control+Enter", "Escape", "Escape"]) {
            await page.keyboard.press(key);
        }
        expect(await paneMode(dashboard)).toBe("pane");
        expect(await review.text()).toBe(before);
        expect(await review.mode()).toBe("normal");
    });

    it("selects a pane with h and l, and goes into it in Normal mode with i or Enter", async () => {
        const { page } = dashboard;
        expect(await selected(dashboard)).toBe("buffer");
        await page.keyboard.press("h");
        await page.waitForFunction(() => document.querySelector(".pane.is-selected")?.classList.contains("pane-list") === true);
        await page.keyboard.press("l");
        await page.waitForFunction(() => document.querySelector(".pane.is-selected")?.classList.contains("pane-buffer") === true);
        await page.keyboard.press("h");
        await page.keyboard.press("i");
        await inPaneMode(dashboard, "normal");
        expect(await inList(dashboard)).toBe(true);
        await page.keyboard.press("Escape");
        await inPaneMode(dashboard, "pane");
        await page.keyboard.press("l");
        await page.keyboard.press("Enter");
        await inPaneMode(dashboard, "normal");
        expect(await inList(dashboard)).toBe(false);
        expect(await review.mode()).toBe("normal");
    });

    it("goes between the panes with vim's window commands, under Space w, and without passing through Pane mode", async () => {
        const { page } = dashboard;
        await dashboard.keys.press([" ", "w", "h"]);
        await page.waitForFunction(() => document.activeElement?.closest(".list-buffer") != null, undefined, { polling: 50 });
        expect(await paneMode(dashboard)).toBe("normal");
        await dashboard.keys.press([" ", "w", "w"]);
        await page.waitForFunction(() => document.activeElement?.closest(".review-buffer") != null, undefined, { polling: 50 });
        expect(await review.mode()).toBe("normal");
        await dashboard.keys.press([" ", "w", "p"]);
        await page.waitForFunction(() => document.activeElement?.closest(".list-buffer") != null, undefined, { polling: 50 });
        await dashboard.keys.press([" ", "w", "l"]);
        await page.waitForFunction(() => document.activeElement?.closest(".review-buffer") != null, undefined, { polling: 50 });
    });

    it("takes Ctrl+W and the same keys where the browser lets it through, as an app window does", async () => {
        const { page } = dashboard;
        await dashboard.keys.press(["Control+w", "h"]);
        await page.waitForFunction(() => document.activeElement?.closest(".list-buffer") != null, undefined, { polling: 50 });
        await dashboard.keys.press(["Control+w", "Control+w"]);
        await page.waitForFunction(() => document.activeElement?.closest(".review-buffer") != null, undefined, { polling: 50 });
    });

    it("shows no cursor in a pane the keys don't go to, nor any in Pane mode", async () => {
        const { page } = dashboard;
        const cursors = () => page.evaluate(() => [...document.querySelectorAll(".cm-vimCursorLayer")].filter((each) => getComputedStyle(each).display !== "none" && each.children.length > 0).length);
        expect(await cursors()).toBe(1);
        await page.keyboard.press("Escape");
        await inPaneMode(dashboard, "pane");
        expect(await cursors()).toBe(0);
        await page.keyboard.press("i");
        await inPaneMode(dashboard, "normal");
        expect(await cursors()).toBe(1);
    });

    it("keeps what the second pane's cursor is on in sight in the list, a highlight and no cursor", async () => {
        const { page } = dashboard;
        const highlighted = () => page.evaluate(() => [...document.querySelectorAll(".list-buffer .cm-line.list-cursor")].map((each) => each.textContent ?? ""));
        await review.goTo("── @52 note");
        await page.waitForFunction(() => [...document.querySelectorAll(".list-buffer .cm-line.list-cursor")].some((each) => (each.textContent ?? "").includes("@52")), undefined, { polling: 50 });
        await review.goTo("── @53 problem");
        await page.waitForFunction(() => [...document.querySelectorAll(".list-buffer .cm-line.list-cursor")].some((each) => (each.textContent ?? "").includes("@53")), undefined, { polling: 50 });
        expect(await highlighted()).toHaveLength(1);
        // What's in view is bracketed, beside it; and no cursor's drawn in the list, the keys being here.
        expect(await page.evaluate(() => document.querySelectorAll(".list-buffer .cm-line.list-in-view").length)).toBeGreaterThan(0);
        expect(await page.evaluate(() => getComputedStyle(document.querySelector(".list-buffer .cm-vimCursorLayer") as Element).display)).toBe("none");
        // Going in, the list's cursor lands on that entry.
        await dashboard.keys.press([" ", "w", "h"]);
        await page.waitForFunction(() => document.activeElement?.closest(".list-buffer") != null, undefined, { polling: 50 });
        expect(await page.evaluate(() => document.querySelector(".list-buffer .cm-activeLine")?.textContent ?? "")).toContain("@53");
        // Enter on an item the buffer on screen holds goes to it there, the buffer as it was.
        await page.keyboard.press("Enter");
        await review.until("put the cursor on the item", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.includes("@53 problem"));
        expect(await review.text()).toContain("@54 approval");
    });

    it("moves no row for the second pane's cursor: what's folded in the list highlights the nearest row showing, a nest opening for the agent on screen alone", async () => {
        const { page } = dashboard;
        const highlighted = () => page.evaluate(() => [...document.querySelectorAll(".list-buffer .cm-line.list-cursor")].map((each) => each.textContent ?? ""));
        const until = (text: string) =>
            page.waitForFunction((wanted) => [...document.querySelectorAll(".list-buffer .cm-line.list-cursor")].some((each) => (each.textContent ?? "").includes(wanted)), text, { polling: 50 });
        const named = (lines: readonly string[]) => lines.findIndex((each) => each.includes("▶ parser"));
        // explore-auth's note: nothing of theirs asks the operator, so their nest's closed.
        const number = "@66";
        const before = await listText(dashboard);
        expect(before.some((each) => each.includes(`${number} `))).toBe(false);
        await review.goTo(`── ${number} note`);
        await until("explore-auth");
        // The row's there, and nothing under it opened: what follows it stays on its line.
        const after = await listText(dashboard);
        // Their row is two lines: their name, and what they're doing.
        expect(await highlighted()).toHaveLength(2);
        expect(after.some((each) => each.includes(`${number} `))).toBe(false);
        expect(named(after)).toBe(named(before));
        // Going in, the list's cursor lands on that row.
        await dashboard.keys.press([" ", "w", "h"]);
        await page.waitForFunction(() => document.activeElement?.closest(".list-buffer") != null, undefined, { polling: 50 });
        expect(await page.evaluate(() => document.querySelector(".list-buffer .cm-activeLine")?.textContent ?? "")).toContain("explore-auth");
        // Their own buffer on screen, their nest's open; another's, shut again.
        const listed = (wanted: string, is: boolean) =>
            page.waitForFunction(([text, there]) => [...document.querySelectorAll(".list-buffer .cm-line")].some((each) => (each.textContent ?? "").includes(text as string)) === there, [wanted, is] as const, { polling: 50 });
        await page.keyboard.press("Enter");
        await listed(`${number} `, true);
        await listRow(dashboard, "what's for you");
        await page.keyboard.press("Enter");
        await listed(`${number} `, false);
        // Opened by the operator, the row's its own, and the highlight goes there; closed, back.
        await review.goTo(`── ${number} note`);
        await until("explore-auth");
        await dashboard.keys.press([" ", "w", "h"]);
        await page.waitForFunction(() => document.activeElement?.closest(".list-buffer") != null, undefined, { polling: 50 });
        await page.keyboard.type("za");
        await until(`${number} `);
        await page.keyboard.type("za");
        await until("explore-auth");
        await page.keyboard.press("Enter");
        await listRow(dashboard, "what's for you");
        await page.keyboard.press("Enter");
        await review.holds(THEIR_ITEM);
    });

    it("draws each mark in its own colour, the theme's, and what's drafted muted, apart from them", async () => {
        const { page } = dashboard;
        /** What the first stretch of `look` saying `text` is drawn in, on the row saying `on`, once it's there. */
        const colourOf = async (look: string, text: string, on = "") => {
            const found = await page.waitForFunction(
                ([wanted, said, row]) => {
                    const lines = [...document.querySelectorAll(".list-buffer .cm-line")].filter((each) => (each.textContent ?? "").includes(row as string));
                    const stretch = lines.flatMap((each) => [...each.querySelectorAll(`.${wanted}`)]).find((each) => (each.textContent ?? "").includes(said as string));
                    return stretch === undefined ? null : { said: stretch.textContent, colour: getComputedStyle(stretch).color, weight: getComputedStyle(stretch).fontWeight };
                },
                [look, text, on] as const,
                { polling: 50 },
            );
            return (await found.jsonValue()) as { said: string; colour: string; weight: string };
        };
        const ORANGE = "rgb(255, 153, 51)";
        expect((await colourOf("mark-waiting", "◆")).colour).toBe(ORANGE);
        expect((await colourOf("mark-asking", "◇")).colour).toBe(ORANGE);
        // The theme's own cyan, as it's the agent's name's, apart from the blue of what's only to read.
        expect((await colourOf("mark-to-review", "◇")).colour).toBe("rgb(102, 204, 204)");
        expect((await colourOf("mark-news", "•")).colour).toBe("rgb(153, 204, 255)");
        const row = () => page.evaluate(() => [...document.querySelectorAll(".list-buffer .cm-line")].find((each) => (each.textContent ?? "").includes("explore-auth"))?.textContent ?? "");
        await page.waitForFunction(() => [...document.querySelectorAll(".list-buffer .cm-line")].some((each) => (each.textContent ?? "").includes("explore-auth") && (each.textContent ?? "").includes("◇1")), undefined, { polling: 50 });
        const bare = await row();
        await review.goTo("── @66 note");
        await review.comment();
        await page.keyboard.type("Drafted");
        await page.keyboard.press("Escape");
        const written = await colourOf("list-written", "¶", "explore-auth");
        expect(written.said).toBe("¶1");
        expect(written.colour).toBe("rgb(179, 179, 179)");
        expect(written.weight).toBe("400");
        // What stands stays where it was as they write.
        const after = await row();
        expect(after).toMatch(/¶1 {2}◇1 •\d$/);
        expect(after.length).toBe(bare.length);
        expect(after.slice(after.indexOf("◇"))).toBe(bare.slice(bare.indexOf("◇")));
        await page.keyboard.press("u");
        await page.waitForFunction(() => [...document.querySelectorAll(".list-buffer .cm-line")].some((each) => (each.textContent ?? "").includes("explore-auth") && !(each.textContent ?? "").includes("¶")), undefined, { polling: 50 });
    });

    it("keeps vim's keys in the list, Enter opening a row's buffer and going into it", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "main");
        const row = await page.evaluate(() => document.querySelector(".list-buffer .cm-activeLine")?.textContent ?? "");
        expect(row).toContain("main");
        await page.keyboard.press("Enter");
        await review.holds("to main");
        await review.until("left what's for the operator", (view) => !view.state.doc.toString().includes("── @45 note"));
        expect(await inList(dashboard)).toBe(false);
        const text = await review.text();
        // Their own: their item and their conversation, nobody else's.
        expect(text).toContain("@53 problem");
        expect(text).not.toContain("@54 approval");
    });

    it("searches the buffer on screen alone", async () => {
        const { page } = dashboard;
        await page.keyboard.press("g");
        await page.keyboard.press("g");
        const was = await review.evaluate((view) => view.state.selection.main.head);
        await page.keyboard.press("/");
        await page.keyboard.type("@54 approval");
        await page.keyboard.press("Enter");
        expect(await review.evaluate((view) => view.state.selection.main.head)).toBe(was);
    });

    it("keeps a comment on its block as another buffer comes and goes, saying whom it reaches", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "what's for you");
        await page.keyboard.press("Enter");
        await review.holds(THEIR_ITEM);
        await review.goTo("── @52 note");
        await review.goTo("so a search never fails on one");
        await review.comment();
        await page.keyboard.type(WORDS);
        await page.keyboard.press("Escape");
        await review.inMode("normal");
        await listRow(dashboard, "main");
        await page.keyboard.press("Enter");
        await review.until("left what's for the operator", (view) => !view.state.doc.toString().includes("── @45 note"));
        expect(await review.text()).not.toContain(WORDS);
        await listRow(dashboard, "guidance-voice");
        await page.keyboard.press("Enter");
        await review.holds(WORDS);
        const lines = (await review.text()).split("\n");
        const at = lines.indexOf(WORDS);
        expect(lines[at - 1]).toContain("so a search never fails on one");
        // The line under the review says who it goes to, whichever buffer's on screen.
        const status = await page.evaluate(() => document.querySelector(".status")?.textContent ?? "");
        expect(status).toContain("guidance-voice");
    });

    it("writes to the agent at the end of their buffer, under what's live", async () => {
        const { page } = dashboard;
        await page.keyboard.press("G");
        expect(await review.line()).toContain("to guidance-voice");
        await page.keyboard.press("o");
        await review.inMode("insert");
        await page.keyboard.type("A message to them");
        await page.keyboard.press("Escape");
        await review.inMode("normal");
        const lines = (await review.text()).split("\n");
        const at = lines.findIndex((each) => each.includes("to guidance-voice"));
        expect(lines[at + 1]).toBe("A message to them");
    });

    it("opens what nobody running answers, an ended agent's own buffer and lup's approvals, each from its row", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "No agent");
        await page.keyboard.press("Enter");
        await review.until("showed what's left by who's ended", (view) => view.state.doc.toString().includes("fix-clock"));
        expect(await review.text()).not.toContain("@54 approval");
        await listRow(dashboard, "lup-impl/fix-clock");
        await page.keyboard.press("Enter");
        await review.holds("to lup-impl/fix-clock");
        expect(await review.text()).toContain("since you approved");
        await listRow(dashboard, "lup's approvals");
        await page.keyboard.press("Enter");
        await review.holds("@54 approval");
        expect((await review.text()).split("\n").filter((each) => each.startsWith("━━"))).toHaveLength(1);
    });

    it("goes into the list with gO, hides it with \\ and shows it again, and to an agent's buffer with gd on their name", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "what's for you");
        await page.keyboard.press("Enter");
        await review.holds("@56 turn ended");
        await page.keyboard.press("g");
        await page.keyboard.press("O");
        await page.waitForFunction(() => document.activeElement?.closest(".list-buffer") != null, undefined, { polling: 50 });
        await page.keyboard.press("\\");
        await page.waitForFunction(() => document.querySelector(".pane-list") === null, undefined, { polling: 50 });
        expect(await review.mode()).toBe("normal");
        await page.keyboard.press("\\");
        await page.waitForFunction(() => document.querySelector(".list-buffer .cm-line") !== null, undefined, { polling: 50 });
        await review.goTo("guidance-voice · @56, its answer");
        await page.keyboard.press("g");
        await page.keyboard.press("d");
        await review.holds("to guidance-voice");
    });

    it("shows a check under whoever owns its thread, and answers it from there", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "parser");
        await page.keyboard.press("Enter");
        await review.holds("check @");
        const line = (await review.text()).split("\n").find((each) => each.startsWith("◇ check @")) ?? "";
        expect(line).toContain(" in @transcript-reader:");
        const number = /check @(\d+)/.exec(line)?.[1] ?? "";
        // Counted with what wants the operator's eyes, on its task's row, whose question holds apart from it.
        const taskSays = (flagged: boolean) => page.waitForFunction((wanted) => [...document.querySelectorAll(".list-buffer .cm-line")].some((each) => (each.textContent ?? "").includes("@transcript-reader") && (each.textContent ?? "").includes("◇1") === wanted), flagged, { polling: 50 });
        await taskSays(true);
        await review.goTo(`check @${number}`);
        await dashboard.keys.press([" ", "d"]);
        await page.waitForFunction(() => (document.querySelector(".status")?.textContent ?? "").includes("No reply drafted") === false, undefined, { polling: 50 });
        await taskSays(false);
        // Undone: nothing of it is sent by what follows.
        await page.keyboard.press("u");
        await taskSays(true);
    });

    it("lists tasks under whoever owns them, and reads one across agents from its row", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "@transcript-reader");
        const row = await page.evaluate(() => document.querySelector(".list-buffer .cm-activeLine")?.textContent ?? "");
        expect(row).toContain("@transcript-reader");
        await page.keyboard.press("Enter");
        await review.until("read the thread whole", (view) => !view.state.doc.toString().includes("reading…") && view.state.doc.toString().includes("━━ @transcript-reader"));
        // Whole, saying whom the words reach, over it and on the line they're written under.
        expect(await review.text()).toContain("to lup-impl/parser on @transcript-reader");
        // A friction in it folded to its header, saying where it's read.
        await review.goTo("── @57 friction · in the pile to read · lup-impl/parser");
        expect(await page.evaluate(() => document.querySelector(".where-whom")?.textContent ?? "")).toContain("lup-impl/parser");
        await listRow(dashboard, "what's for you");
        await page.keyboard.press("Enter");
        await review.holds("@54 approval");
        expect(dashboard.thrown).toEqual([]);
    });

    it("goes from an item of what's for the operator to its thread with gt, onto the item", async () => {
        const { page } = dashboard;
        await review.goTo("── @51 question");
        await review.settled(300, 0);
        await page.keyboard.press("g");
        await page.keyboard.press("t");
        await review.until("went to the thread", (view) => view.state.doc.toString().startsWith("━━ @transcript-reader") && !view.state.doc.toString().includes("reading…"));
        await review.until("put the cursor on the item", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.includes("@51 question"));
    });

    it("comes back with Ctrl+O, to where it went from", async () => {
        const { page } = dashboard;
        await page.keyboard.press("Control+o");
        await review.until("went back to what's for the operator", (view) => view.state.doc.toString().includes("@54 approval"));
        await review.until("put the cursor back on the item", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.includes("@51 question"));
        expect(dashboard.thrown).toEqual([]);
    });

    it("goes from an agent's name on a thread's banner to their own buffer with gd, and back with Ctrl+O", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "@auth-survey");
        await page.keyboard.press("Enter");
        await review.until("read the thread whole", (view) => view.state.doc.toString().startsWith("━━ @auth-survey") && !view.state.doc.toString().includes("reading…"));
        await review.goTo("lup-impl/explore-auth holds");
        await review.settled(300, 0);
        await page.keyboard.press("g");
        await page.keyboard.press("d");
        await review.holds("to lup-impl/explore-auth\u0020──");
        await page.keyboard.press("Control+o");
        await review.until("went back to the thread", (view) => view.state.doc.toString().startsWith("━━ @auth-survey"));
        await listRow(dashboard, "what's for you");
        await page.keyboard.press("Enter");
        await review.holds("@54 approval");
    });

    it("sends with Ctrl+Enter from Normal mode, from any buffer, the comment and the message going whole", async () => {
        const { page } = dashboard;
        await listRow(dashboard, "main");
        await page.keyboard.press("Enter");
        await review.until("left their buffer", (view) => !view.state.doc.toString().includes("to guidance-voice"));
        await page.keyboard.press("Control+Enter");
        await page.waitForFunction(() => (document.querySelector(".bar .said")?.textContent ?? "").startsWith("Sent"), undefined, { polling: 100 });
        const said = await page.evaluate(() => document.querySelector(".bar .said")?.getAttribute("title") ?? "");
        expect(said).toContain("guidance-voice");
        await page.waitForFunction(() => (document.querySelector(".status")?.textContent ?? "").includes("No reply drafted"), undefined, { polling: 100 });
        await listRow(dashboard, "guidance-voice");
        await page.keyboard.press("Enter");
        await review.holds("to guidance-voice");
        // Sent: nothing of it's drafted here any more, though their conversation now holds what they were sent.
        expect(await review.decorated("remark")).toBe(0);
        expect(dashboard.thrown).toEqual([]);
    });
});

describe("what's read by being on screen, in panes", () => {
    let served: Demo;
    let dashboard: Dashboard;
    let review: Review;
    let told: Record<string, unknown>[] = [];

    beforeEach(async () => {
        told = [];
        served = await demo({ size: 0 });
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
        await review.holds(THEIR_ITEM);
        await review.settled(1500);
    });

    afterEach(async () => {
        expect(dashboard.thrown).toEqual([]);
        await dashboard.close();
        await served.close();
    });

    const moved = () => told.flatMap((each) => each.marks as { key: Record<string, unknown>; up_to: string; seen: boolean }[]);
    /** Each mark moved as far as the voice session's turn's end, or the how it felt in view just after it. */
    const movedTo56 = () => moved().filter((each) => each.up_to === "56" || each.up_to === "58");
    const passes = (ms: number) => dashboard.page.clock.runFor(ms);
    const row = (text: string) => dashboard.page.evaluate((wanted) => [...document.querySelectorAll(".list-buffer .cm-line")].find((each) => (each.textContent ?? "").includes(wanted))?.textContent ?? "", text);

    it("moves their agent's mark as what's been seen scrolls off, the list's count falling", async () => {
        await review.goTo("── @56 turn ended");
        await dashboard.keys.press(["z", "z"]);
        await review.settled(300);
        await passes(10_000);
        await review.settled(300);
        const was = await row("guidance-voice");
        expect(was).toContain("•");
        await dashboard.keys.press(["G"]);
        await review.settled(300);
        await passes(4000);
        await review.settled(300);
        await expect.poll(() => movedTo56().length, { timeout: 15_000 }).toBeGreaterThan(0);
        const [mark] = movedTo56();
        expect(mark?.seen).toBe(true);
        // Their agent's, never a thread's, though the list reads threads.
        expect(mark?.key.node).toBeUndefined();
        expect(mark?.key.session).toEqual(expect.any(String));
        await review.until("let go of its word that it's new", (view) => !/── @56 turn ended[^\n]* new /.test(view.state.doc.toString()));
        expect(await row("@56 turn ended")).not.toContain(" new ");
    });

    it("moves it as another buffer takes the screen, what was seen there leaving with it", async () => {
        await review.goTo("── @56 turn ended");
        await dashboard.keys.press(["z", "z"]);
        await review.settled(300);
        await passes(10_000);
        await review.settled(300);
        expect(movedTo56()).toEqual([]);
        await listRow(dashboard, "main");
        await dashboard.page.keyboard.press("Enter");
        await review.until("left what's for the operator", (view) => !view.state.doc.toString().includes("── @45 note"));
        await review.settled(300);
        await expect.poll(() => movedTo56().length, { timeout: 15_000 }).toBeGreaterThan(0);
        const [mark] = movedTo56();
        expect(mark?.seen).toBe(true);
    });

    it("reads nothing of a page nobody has touched, in panes as without them", async () => {
        await passes(10_000);
        expect(told).toEqual([]);
    });
});

describe("the panes on a phone", () => {
    let served: Demo;
    let dashboard: Dashboard;

    beforeAll(async () => {
        served = await demo({ size: 0 });
        dashboard = await open(served.url, { viewport: { width: 400, height: 800 } });
        const review = await dashboard.review();
        await review.settled();
    });

    afterAll(async () => {
        await dashboard?.close();
        await served?.close();
    });

    const shown = (which: string) => dashboard.page.waitForFunction((pane) => {
        const box = document.querySelector(pane)?.getBoundingClientRect();
        return box !== undefined && box.width > 0;
    }, which, { polling: 50 });
    const hidden = (which: string) => dashboard.page.waitForFunction((pane) => {
        const box = document.querySelector(pane)?.getBoundingClientRect();
        return box === undefined || box.width === 0;
    }, which, { polling: 50 });

    it("gets one pane at a time, the list first, the bar's button going back to it", async () => {
        const { page } = dashboard;
        await shown(".pane-list");
        await hidden(".pane-buffer");
        await page.click(".list-buffer .cm-line:first-child");
        await shown(".pane-buffer");
        await hidden(".pane-list");
        await page.click(".overview-button");
        await shown(".pane-list");
        expect(dashboard.thrown).toEqual([]);
    });
});
