import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

/** The demo's first thread waiting on the operator, its header there: the parser subagent's reader, asking a question and a check. */
const READER = "━━ @transcript-reader · The transcript reader · lup-impl/parser holds · a question, a check ━━";
/** The same thread whole, in open. */
const READER_WHOLE = "━━ @transcript-reader · The transcript reader · lup-impl/parser holds · working · 2 waiting ━━";
/** explore-auth's survey, its header in new. */
const AUTH = "━━ @auth-survey · Where auth is checked · lup-impl/explore-auth holds · 2 new ━━";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    served = await demo({ size: 0 });
    dashboard = await open(served.url);
    review = await dashboard.review();
    // What waits on the operator and what's new in each thread read, and the review at rest.
    await review.holds(READER);
    await review.holds("── @51 question · lup-impl/parser");
    await review.holds("◆ to try: ");
    await review.holds("── @66 note · lup-impl/explore-auth");
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

/** What the line of keys says, the cursor where it is. */
const keys = async () => (await dashboard.page.locator(".keys").first().innerText()).replace(/\s+/g, " ");

/** Return whether the line after the one numbered `number` is hidden, as under a closed fold. */
const hidesNext = (number: number) =>
    review.evaluate((view, line) => {
        const at = view.state.doc.line(line);
        return view.lineBlockAt(at.to + 1).from !== at.to + 1;
    }, number);

/** The line the cursor is on. */
const line = () => review.line();

describe("the review grouped by thread, in headless Chromium", () => {
    it("lays out what waits on the operator and what's new by item, each under its thread's header, and every open thread in open", async () => {
        const lines = (await review.text()).split("\n");
        expect(lines.slice(0, 3)).toEqual(["waiting on you · 5", READER, lines[2]]);
        expect(lines[2]).toMatch(/^── @51 question · lup-impl\/parser · /);
        expect(lines.filter((each) => /^(waiting on you|new|open|to read|settled|agents) · /.test(each)).map((each) => each.split(" · ")[0])).toEqual([
            "waiting on you",
            "new",
            "open",
            "to read",
            "settled",
            "agents",
        ]);
        expect(lines).toContain("◆ to try: Read the voice section of AGENTS.md: each line says what is, and its examples are short.");
        // Open: every thread still open, a line each, folded, saying where it stands and how much waits on the operator or is new.
        expect(lines).toContain(READER_WHOLE);
        expect(lines.find((each) => each.startsWith("━━ @reader-names"))).toMatch(/^━━ @reader-names · The reader's names · lup-impl\/parser holds · parked until .+ ━━$/);
        expect(lines).toContain("━━ @clock-ticks · The clock's ticks · lup-impl/fix-clock held it, lup-impl answers · working ━━");
        expect(await hidesNext(lines.indexOf(READER_WHOLE) + 1)).toBe(true);
    });

    it("shows in new the latest read before what's new, folded to its header, then each new item", async () => {
        const lines = (await review.text()).split("\n");
        const at = lines.indexOf(AUTH);
        expect(lines[at + 1]).toMatch(/^── @64 note to lup-impl\/explore-auth · lup-impl · /);
        expect(await hidesNext(at + 2)).toBe(true);
        expect(lines.slice(at).find((each) => each.startsWith("── @65"))).toMatch(/^── @65 note to lup-impl · lup-impl\/explore-auth · new · /);
    });

    it("goes from an item waiting on the operator to its thread whole in open with gt, onto the line pointing back to it, and back with Ctrl-O", async () => {
        await review.goTo("── @51 question");
        await dashboard.keys.press(["g", "t"]);
        await review.until("on the line in open pointing to @51", (view) => view.state.doc.lineAt(view.state.selection.main.head).text === "↑ @51 question · in waiting on you · gd goes there");
        await review.holds("── @47 note · lup-impl/parser");
        await dashboard.keys.press(["Control+o"]);
        await review.until("back on @51", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.startsWith("── @51 question"));
        await dashboard.keys.press(["Control+i"]);
        await review.until("on the line pointing to @51 again", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.startsWith("↑ @51 question"));
        await dashboard.keys.press(["g", "d"]);
        await review.until("on @51 again, from the line pointing to it", (view) => view.state.doc.lineAt(view.state.selection.main.head).text.startsWith("── @51 question"));
        expect(await line()).toMatch(/^── @51 question/);
    });

    it("settles a thread done with Space d on its header, ticks a check with Space d, and writes on a thread, Space s sending it to no one and back", async () => {
        await review.goTo("━━ @guidance-voice");
        expect(await keys()).toContain("␣d settle it: it works");
        await dashboard.keys.press([" ", "d"]);
        await says("@guidance-voice settled");
        await review.goTo("◆ check @311");
        await dashboard.keys.press([" ", "d"]);
        await says("tick it: you tried it");
        await review.goTo(AUTH);
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

    it("sends it all with Ctrl+Enter: the thread settled under settled, the check answered, the message in its thread whole", async () => {
        await dashboard.keys.press(["Control+Enter"]);
        await review.until("the voice thread settled under settled", (view) => {
            const text = view.state.doc.toString();
            return text.indexOf("━━ @guidance-voice · the session's own · guidance-voice holds · settled") > text.indexOf("settled · ");
        });
        await review.holds("✓ check @311");
        await review.goTo("━━ @auth-survey · Where auth is checked · lup-impl/explore-auth holds · working");
        await dashboard.keys.press(["z", "o"]);
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
