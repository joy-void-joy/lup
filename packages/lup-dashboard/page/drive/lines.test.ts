import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";
import { DEMO_ITEM } from "./typing.ts";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    // Nothing of the demo's own comes as the keys go down.
    served = await demo({ size: 0, arrives: 3600, grows: 3600 });
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

/**
 * Where the cursor is and where `key` should take it: the line it's on, by its number, and its text; the next line shown
 * after it, or before it for `k`, a line under a closed fold not shown, the fold's summary line standing for it, and the
 * empty line after the text's last line break not one, which no cursor rests on; and the text's length, which says whether
 * the review was laid out anew in between, as the demo's arrivals lay it out.
 */
const position = (key: "j" | "k") =>
    review.evaluate((view, forward) => {
        const doc = view.state.doc;
        const line = doc.lineAt(view.state.selection.main.head);
        let next: number | null = null;
        const last = doc.line(doc.lines).length === 0 ? doc.lines - 1 : doc.lines;
        for (let number = line.number + (forward ? 1 : -1); number >= 1 && number <= last; number += forward ? 1 : -1) {
            const each = doc.line(number);
            const block = view.lineBlockAt(each.from);
            if (block.from === each.from && !(block.from <= line.from && block.to >= line.from)) {
                next = number;
                break;
            }
        }
        const expected = next === null ? "" : doc.line(next).text;
        return { number: line.number, text: line.text, next, expected, length: doc.length };
    }, key === "j");

/** Say a line by its number and its words. */
const said = (number: number | null, text: string) => `${number} "${text.slice(0, 50)}"`;

/**
 * Press `key` from where the cursor is to the review's end, or its start, each press moving the cursor exactly one line
 * shown; return each step that moved otherwise, saying where from, where to, and where it should have gone. A step the
 * review was laid out anew during, as an item arriving, is taken again from where it landed.
 */
async function stepped(key: "j" | "k"): Promise<string[]> {
    const wrong: string[] = [];
    for (let step = 0; step < 5000; step += 1) {
        const from = await position(key);
        if (from.next === null) {
            return wrong;
        }
        await dashboard.keys.press([key]);
        const to = await position(key);
        if (to.length !== from.length || to.number === from.next) {
            continue;
        }
        wrong.push(`${key} from ${said(from.number, from.text)} went to ${said(to.number, to.text)}, not ${said(from.next, from.expected)} (step ${step + 1})`);
        // Go on from where it should have been.
        await review.evaluate((view, number) => view.dispatch({ selection: { anchor: view.state.doc.line(number).from } }), from.next);
    }
    return [...wrong, `${key} never reached the review's end`];
}

/** The line the cursor is on, by its number. */
const here = async () => (await position("j")).number;

/** Put the cursor on the review's first line, or its last. */
const to = async (end: "first" | "last") => {
    await dashboard.keys.press(end === "first" ? ["g", "g"] : ["G"]);
};

describe("moving through the review, line by line, in headless Chromium", () => {
    it("moves j and k exactly one line shown at a time from the first line to the last and back, the folds as they start", async () => {
        await to("first");
        expect(await stepped("j")).toEqual([]);
        await to("last");
        expect(await stepped("k")).toEqual([]);
    });

    it("goes ]g and [g to each group in turn, the first from the review's first line", async () => {
        // Walked again where the review was laid out anew meanwhile, what's been seen no longer saying it's new moving what's
        // below, a key going where its layout says before it's in the editor.
        let walked: { landings: number[]; forward: number[]; back: number[] } = { landings: [], forward: [], back: [] };
        for (let tried = 0; tried < 5; tried += 1) {
            const landings = await review.evaluate((view) => {
                const doc = view.state.doc;
                const found: number[] = [];
                for (let number = 1; number <= doc.lines; number += 1) {
                    const line = doc.line(number);
                    if (line.text.startsWith("━━ ")) {
                        found.push(doc.lineAt(view.lineBlockAt(line.from).from).number);
                    }
                }
                return [...new Set(found)];
            });
            await to("first");
            // The first group's banner is the first line.
            const forward: number[] = [];
            for (const _ of landings.slice(1)) {
                await dashboard.keys.press(["]", "g"]);
                forward.push(await here());
            }
            const back: number[] = [];
            for (const _ of landings.slice(1)) {
                await dashboard.keys.press(["[", "g"]);
                back.push(await here());
            }
            walked = { landings, forward, back };
            if (forward.join() === landings.slice(1).join() && back.join() === landings.toReversed().slice(1).join()) {
                break;
            }
            await review.settled(400, 0);
        }
        expect(walked.forward).toEqual(walked.landings.slice(1));
        expect(walked.back).toEqual(walked.landings.toReversed().slice(1));
    });

    it("moves j and k exactly one line shown at a time with an agent's drawers open", async () => {
        await review.goTo("━━ lup · dev · lup-impl/parser");
        for (const drawer of ["since you approved", "messages", "trace"]) {
            await dashboard.keys.press(["]", drawer === "since you approved" ? "s" : drawer === "messages" ? "M" : "v"]);
            await review.until(`go to the ${drawer}`, (view, wanted) => view.state.doc.lineAt(view.state.selection.main.head).text.startsWith(wanted), drawer);
            await dashboard.keys.press(["z", "o"]);
        }
        await to("first");
        expect(await stepped("j")).toEqual([]);
        await to("last");
        expect(await stepped("k")).toEqual([]);
    });

    it("moves j and k exactly one line shown at a time in an agent's own buffer, each concern of theirs a block in it", async () => {
        await dashboard.openRow("The transcript reader");
        await review.until("lay out the parser's own buffer, their concerns among it", (view) => view.state.doc.toString().includes("§ The transcript reader") && view.state.doc.toString().includes("§ The reader's names"));
        await to("first");
        expect(await stepped("j")).toEqual([]);
        await to("last");
        expect(await stepped("k")).toEqual([]);
    });
});
