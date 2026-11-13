// Space s says where a thing goes (`docs/dashboard.md`, *The keys*): an item into a concern or a pile, `Later` among
// them, or one opened by the words typed; a concern to an agent, under another or to `No agent`. Nothing moves until
// Ctrl+Enter: the thing says where it goes meanwhile, the line under the review says what goes where, and `g<` sends one
// place alone. An item moved leaves its agent's group, a dim line where it was; a concern's block is laid out as an item,
// folded until it's opened.
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

/** Return once the line under the review says `text`. */
const says = (text: string) =>
    dashboard.page.waitForFunction((text) => document.querySelector(".status")?.textContent?.includes(text) === true, text);

/** Return once the top bar says `text`. */
const said = (text: string) => dashboard.page.waitForFunction((text) => document.querySelector(".bar .said")?.textContent?.includes(text) === true, text);

/** Return the list's lines, as drawn: a closed nest's rows aren't. */
const listed = () => dashboard.page.evaluate(() => [...document.querySelectorAll(".list-buffer .cm-line")].map((each) => each.textContent ?? ""));

/** Return once the list has a line saying `text`. */
const lists = (text: string) =>
    dashboard.page.waitForFunction((text) => [...document.querySelectorAll(".list-buffer .cm-line")].some((each) => (each.textContent ?? "").includes(text)), text, { polling: 50 });

/** Press Space s, choose `choice` in the picker it opens by typing it and Enter, and return once it's closed. */
async function send(choice: string): Promise<void> {
    await dashboard.keys.press([" ", "s"]);
    await dashboard.page.waitForSelector(".picker");
    await dashboard.page.keyboard.type(choice);
    await dashboard.page.keyboard.press("Enter");
    await dashboard.page.waitForSelector(".picker", { state: "detached" });
}

/** Send the reply with Ctrl+Enter, and return once the top bar says what it sent. */
async function sent(): Promise<void> {
    await dashboard.keys.press(["Control+Enter"]);
    await said("Sent:");
}

describe("where Space s sends a thing, in headless Chromium", () => {
    it("offers where an item goes, Later first, and draws where it goes on its header until it's sent", async () => {
        await review.goTo("── @52 note");
        await dashboard.keys.press([" ", "s"]);
        await dashboard.page.waitForSelector(".picker");
        const choices = await dashboard.page.locator(".picker").innerText();
        // An item goes into a concern or a pile, never to an agent; a new agent is spawn's third piece's.
        expect(choices).toMatch(/Later\s+pile, for later/);
        expect(choices).toContain("The transcript reader");
        expect(choices).toContain("to come with spawn's third piece");
        expect(choices).not.toContain("No agent");
        await dashboard.page.keyboard.press("Enter");
        await dashboard.page.waitForSelector(".picker", { state: "detached" });
        await says("to Later: @52");
        expect(await review.decorated("is-sent")).toBe(1);
        // Sent nowhere, it's where it was.
        await send("where it is");
        await dashboard.page.waitForFunction(() => document.querySelector(".status")?.textContent?.includes("Later") === false);
        expect(await review.decorated("is-sent")).toBe(0);
    });

    it("moves it into Later with Ctrl+Enter, out of its agent's group, a dim line where it was that Enter follows", async () => {
        await review.goTo("── @52 note");
        await send("Later");
        await sent();
        await said("@52 into @later");
        await review.holds("@52 note → Later");
        expect(await review.text()).not.toContain("── @52 note");
        // Listed under No agent, the pile saying how much it holds.
        await lists("Later · 1");
        // Enter on the dim line goes to its block in No agent's buffer, which lays the item out.
        await review.goTo("@52 note → Later");
        await dashboard.keys.press(["Enter"]);
        await review.until("land on Later's block", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.startsWith("§ Later"));
        await review.unfold("§ Later");
        await review.holds("── @52 note");
    });

    it("opens a new pile by the words typed, at the top, nobody holding it", async () => {
        await dashboard.openRow("what's for you");
        await review.goTo("── @58 how it felt");
        await send("Reader followups");
        await says("to Reader followups: @58");
        await sent();
        await lists("Reader followups · 1");
    });

    it("gives a concern nobody holds to an agent, who then holds it", async () => {
        await dashboard.openRow("The docs sweep");
        await review.until("land on the docs sweep's block", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.startsWith("§ The docs sweep"));
        await dashboard.keys.press([" ", "s"]);
        await dashboard.page.waitForSelector(".picker");
        // A concern goes to an agent of its repository, under a concern, into a pile, or to No agent.
        const choices = await dashboard.page.locator(".picker").innerText();
        expect(choices).toMatch(/lup-impl\s+agent, who holds it/);
        expect(choices).toContain("No agent");
        expect(choices).not.toContain("main");
        await dashboard.page.keyboard.type("lup-impl");
        await dashboard.page.keyboard.press("Enter");
        await dashboard.page.waitForSelector(".picker", { state: "detached" });
        await says("to lup-impl: § The docs sweep");
        await sent();
        await said("@docs-sweep to lup-impl");
        // Under lup-impl now, out of No agent.
        await dashboard.page.waitForFunction(
            () => {
                const lines = [...document.querySelectorAll(".list-buffer .cm-line")].map((each) => each.textContent ?? "");
                const nobody = lines.findIndex((each) => each.startsWith("No agent"));
                const docs = lines.findIndex((each) => each.includes("The docs sweep"));
                return docs >= 0 && (nobody < 0 || docs < nobody);
            },
            undefined,
            { polling: 50 },
        );
    });

    it("sends one place alone with Ctrl+Enter on its line in g<, the rest staying drafted", async () => {
        await dashboard.openRow("what's for you");
        await review.goTo("── @56 turn");
        await send("Later");
        await review.goTo("── @45 note");
        await review.comment();
        await dashboard.page.keyboard.type("Keep this one.");
        await dashboard.keys.press(["Escape"]);
        await review.inMode("normal");
        await says("g< one place alone");
        await dashboard.keys.press(["g", "<"]);
        await dashboard.page.waitForSelector(".whole-palette");
        // On the line saying what goes to Later.
        await dashboard.page.locator(".whole-palette [cmdk-item]", { hasText: "to Later" }).hover();
        await dashboard.page.waitForFunction(() => document.querySelector(".whole-palette [data-selected='true']")?.textContent?.includes("to Later") === true);
        await dashboard.page.keyboard.press("Control+Enter");
        await dashboard.page.waitForSelector(".whole-palette", { state: "detached" });
        await said("@56 into @later");
        // The comment on @45 stays drafted, for the reply whole.
        await says("to guidance-voice: comments on @45");
        expect(await dashboard.page.locator(".status").first().innerText()).not.toContain("Later");
        await lists("Later · 2");
    });
});
