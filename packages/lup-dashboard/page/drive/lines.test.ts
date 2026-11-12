import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { open, type Dashboard } from "./dashboard.ts";
import { demo, type Demo } from "./demo.ts";
import { UNLAID, type Review } from "./review.ts";
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

/** Where the cursor was as a key went down, and where that key should take it (`noting`). */
interface Step {
    number: number;
    text: string;
    next: number | null;
    expected: string;
    /** The text's length, which says whether the review was laid out anew in between. */
    length: number;
}

/**
 * Note in the page, as each `key` goes down, before anything of the page's handles it, where the cursor is and where the
 * key should take it: the next line shown after it, or before it for `k`, a line under a closed fold not shown, the fold's
 * summary line standing for it, and the empty line after the text's last line break not one, which no cursor rests on.
 * Return how many lines shown there are to go, the keys a walk to the end takes.
 */
const noting = (key: "j" | "k") =>
    review.evaluate((view, forward) => {
        /** The next line shown from line `number` the way the key goes, as the review is laid out now; none at the end. */
        const shownFrom = (number: number): number | null => {
            const doc = view.state.doc;
            const last = doc.line(doc.lines).length === 0 ? doc.lines - 1 : doc.lines;
            const line = doc.line(number);
            for (let at = number + (forward ? 1 : -1); at >= 1 && at <= last; at += forward ? 1 : -1) {
                const block = view.lineBlockAt(doc.line(at).from);
                if (block.from === doc.line(at).from && !(block.from <= line.from && block.to >= line.from)) {
                    return at;
                }
            }
            return null;
        };
        const where = (): Step => {
            const doc = view.state.doc;
            const line = doc.lineAt(view.state.selection.main.head);
            const next = shownFrom(line.number);
            return { number: line.number, text: line.text, next, expected: next === null ? "" : doc.line(next).text, length: doc.length };
        };
        const steps: Step[] = [];
        const noted = (event: KeyboardEvent) => {
            if (event.key === (forward ? "j" : "k")) {
                steps.push(where());
            }
        };
        addEventListener("keydown", noted, { capture: true });
        Object.assign(globalThis, { lupDriveWalk: { steps, where, stop: () => removeEventListener("keydown", noted, { capture: true }) } });
        let count = 0;
        for (let at = shownFrom(where().number); at !== null; at = shownFrom(at)) {
            count += 1;
        }
        return count;
    }, key === "j");

/** Say a line by its number and its words. */
const said = (number: number | null, text: string) => `${number} "${text.slice(0, 50)}"`;

/**
 * Press `key` from where the cursor is to the review's end, or its start, each press moving the cursor exactly one line
 * shown; return each step that moved otherwise, saying where from, where to, and where it should have gone.
 *
 * Every key goes at once, as a held key's repeats do, and the page notes each step as its key goes down (`noting`): where
 * one key landed is where the next found the cursor. A walk of hundreds of keys asks nothing of the page between them,
 * so what it takes is the page's own work on each key, not a round trip each at the machine's speed. A step the review
 * was laid out anew during is left unjudged; one that went wrong leaves the next to start where it landed.
 */
async function stepped(key: "j" | "k"): Promise<string[]> {
    const count = await noting(key);
    await dashboard.keys.press(Array<string>(count).fill(key));
    const { steps, last } = await review.evaluate(() => {
        const walk = (globalThis as unknown as { lupDriveWalk: { steps: Step[]; where: () => Step; stop: () => void } }).lupDriveWalk;
        walk.stop();
        return { steps: walk.steps, last: walk.where() };
    });
    const wrong: string[] = [];
    if (steps.length !== count) {
        wrong.push(`${count} ${key} were sent and the page saw ${steps.length}`);
    }
    steps.forEach((from, at) => {
        const landed = steps[at + 1] ?? last;
        if (from.next !== null && landed.length === from.length && landed.number !== from.next) {
            wrong.push(`${key} from ${said(from.number, from.text)} went to ${said(landed.number, landed.text)}, not ${said(from.next, from.expected)} (step ${at + 1})`);
        }
    });
    if (last.next !== null) {
        wrong.push(`${key} never reached the review's end, stopping on ${said(last.number, last.text)}`);
    }
    return wrong;
}

/** The line the cursor is on, by its number. */
const here = () => review.evaluate((view) => view.state.doc.lineAt(view.state.selection.main.head).number);

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
        // Walked again where the review was laid out anew meanwhile, a key going where its layout says before it's in the
        // editor.
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
            // What it holds laid out as it opens, in place of the line standing for it, before a walk counts its lines.
            await review.until(
                `lay out the ${drawer}`,
                (view, unlaid) => {
                    const doc = view.state.doc;
                    const line = doc.lineAt(view.state.selection.main.head);
                    return line.number < doc.lines && doc.line(line.number + 1).text !== unlaid;
                },
                UNLAID,
            );
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
