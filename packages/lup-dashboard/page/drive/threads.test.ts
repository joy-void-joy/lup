import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

/** The demo's first thread waiting on the operator: the parser subagent's reader, asking a question and a check. */
const READER = "━━ @transcript-reader · The transcript reader";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    served = await demo({ size: 0 });
    dashboard = await open(served.url);
    review = await dashboard.review();
    await review.holds(READER);
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

/** What the line of keys says, the cursor where it is. */
const keys = async () => (await dashboard.page.locator(".keys").first().innerText()).replace(/\s+/g, " ");

describe("the review grouped by thread, in headless Chromium", () => {
    it("lays the demo's threads out in sections, what waits on the operator first, each a group under its banner", async () => {
        const lines = (await review.text()).split("\n");
        expect(lines.slice(0, 2)).toEqual(["waiting on you · 5", `${READER} · lup-impl/parser holds · a question, a check ━━`]);
        expect(lines.filter((line) => /^(waiting on you|new|to read|every thread|agents) · /.test(line)).map((line) => line.split(" · ")[0])).toEqual([
            "waiting on you",
            "new",
            "to read",
            "every thread",
            "agents",
        ]);
        expect(lines).toContain("◆ to try: Read the voice section of AGENTS.md: each line says what is, and its examples are short.");
    });

    it("reads what came before where the operator read a thread from the host as its fold opens", async () => {
        await review.goTo("6 earlier, read");
        await dashboard.keys.press(["z", "o"]);
        await review.holds("── @47 note · lup-impl/parser");
        // A message between agents, folded to its header.
        await review.holds("── @67 note to lup-impl/parser/grep-tokens · lup-impl/parser");
    });

    it("settles a thread done with Space d on its banner, ticks a check with Space d, and writes on a thread, Space s sending it to no one and back", async () => {
        await review.goTo("━━ @guidance-voice");
        expect(await keys()).toContain("␣d settle it: it works");
        await dashboard.keys.press([" ", "d"]);
        await says("@guidance-voice settled");
        await review.goTo("◆ check @311");
        await dashboard.keys.press([" ", "d"]);
        await says("tick it: you tried it");
        await review.goTo("━━ @auth-survey");
        await dashboard.keys.press(["o"]);
        await review.inMode("insert");
        await dashboard.keys.type("Which runs as root?");
        await dashboard.keys.press(["Escape"]);
        await review.inMode("normal");
        await says("to lup-impl/explore-auth: a message on @auth-survey");
        await dashboard.keys.press([" ", "s"]);
        await says("to no one: a message on @auth-survey");
        await dashboard.keys.press([" ", "s"]);
        await says("to lup-impl/explore-auth: a message on @auth-survey");
    });

    it("sends it all with Ctrl+Enter: the thread settled folds into every thread, the check answered, the message on its thread", async () => {
        await dashboard.keys.press(["Control+Enter"]);
        await review.until("the voice thread settled under every thread", (view) => {
            const text = view.state.doc.toString();
            return text.indexOf("━━ @guidance-voice · the session's own · guidance-voice holds · settled") > text.indexOf("every thread · ");
        });
        await review.holds("✓ check @311");
        await review.holds("you · @101.1 to lup-impl/explore-auth · open: waits on lup-impl/explore-auth");
    });

    it("goes from an agent's name to their own views among the agents with gd", async () => {
        await review.goTo("lup-impl/explore-auth holds");
        await dashboard.keys.press(["g", "d"]);
        await review.until("on explore-auth's conversation among the agents", (view) => {
            const text = view.state.doc.toString();
            const head = view.state.selection.main.head;
            return head > text.indexOf("agents · ") && view.state.doc.lineAt(head).text.startsWith("conversation ·");
        });
    });
});
