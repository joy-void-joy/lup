import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import type { Review } from "./review.ts";

let served: Demo;
let dashboard: Dashboard;
let review: Review;

beforeAll(async () => {
    served = await demo({ size: 0 });
    dashboard = await open(served.url);
    review = await dashboard.review();
    await review.holds("agents · ");
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
 * after it, or before it for `k`, a line under a closed fold not shown, the fold's summary line standing for it; and the
 * text's length, which says whether the review was laid out anew in between, as the demo's arrivals lay it out.
 */
const position = (key: "j" | "k") =>
    review.evaluate((view, forward) => {
        const doc = view.state.doc;
        const line = doc.lineAt(view.state.selection.main.head);
        let next: number | null = null;
        for (let number = line.number + (forward ? 1 : -1); number >= 1 && number <= doc.lines; number += forward ? 1 : -1) {
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

/**
 * Where the cursor's line is, by its number; each line a group's key lands on, a closed fold's line standing for the
 * groups under it; and the text's length, which says whether the review was laid out anew in between.
 */
const groups = () =>
    review.evaluate((view) => {
        const doc = view.state.doc;
        const found: number[] = [];
        for (let number = 1; number <= doc.lines; number += 1) {
            const line = doc.line(number);
            if (line.text.startsWith("━━ ")) {
                found.push(doc.lineAt(view.lineBlockAt(line.from).from).number);
            }
        }
        return { here: doc.lineAt(view.state.selection.main.head).number, landings: [...new Set(found)], length: doc.length };
    });

/**
 * Press `keys`, `]g` or `[g`, from where the cursor is until no group is left that way, each press going to the next;
 * return what went otherwise. A step the review was laid out anew during, as an item arriving, is taken again from where
 * it landed, the lines having moved.
 */
async function grouped(keys: ["]" | "[", "g"]): Promise<string[]> {
    for (let step = 0; step < 500; step += 1) {
        const from = await groups();
        const next = keys[0] === "]" ? from.landings.find((each) => each > from.here) : from.landings.findLast((each) => each < from.here);
        if (next === undefined) {
            return [];
        }
        await dashboard.keys.press(keys);
        const to = await groups();
        if (to.length === from.length && to.here !== next) {
            return [`${keys.join("")} from line ${from.here} went to ${to.here}, not ${next} (step ${step + 1})`];
        }
    }
    return [`${keys.join("")} never reached the last group`];
}

/** Put the cursor on the review's first line, or its last. */
const to = async (end: "first" | "last") => {
    await dashboard.keys.press(end === "first" ? ["g", "g"] : ["G"]);
};

/** Open the fold of the section whose line starts with `name`, its line the cursor's. */
async function opened(name: string): Promise<void> {
    await review.goTo(`${name} · `);
    await dashboard.keys.press(["z", "o"]);
}

describe("moving through the review grouped by thread, line by line, in headless Chromium", () => {
    it("moves j and k exactly one line shown at a time from the first line to the last and back, the sections as they start", async () => {
        await to("first");
        expect(await stepped("j")).toEqual([]);
        await to("last");
        expect(await stepped("k")).toEqual([]);
    });

    it("goes ]g and [g to each group in turn across the sections, a closed fold's line standing for the groups under it", async () => {
        await to("first");
        expect(await grouped(["]", "g"])).toEqual([]);
        expect(await grouped(["[", "g"])).toEqual([]);
    });

    it("moves j and k exactly one line shown at a time with every section open, and a thread whole in open, its lines pointing to items above among it", async () => {
        for (const name of ["to read", "settled", "agents"]) {
            await opened(name);
        }
        await review.goTo("━━ @transcript-reader · The transcript reader · lup-impl/parser holds · working");
        await dashboard.keys.press(["z", "o"]);
        await review.holds("↑ @51 question · in waiting on you · gd goes there");
        await to("first");
        expect(await stepped("j")).toEqual([]);
        await to("last");
        expect(await stepped("k")).toEqual([]);
    });
});
