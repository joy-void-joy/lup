// Opening a comment (`docs/dashboard.md`, *The review*): each key that opens one, `o`, `S`, vim's change `c` and a
// motion, `C`, opens it with one layout of the review, the comment's line in it, and never another before the operator
// can write there (#341). Counted, not timed: the layouts the editor holds (`ahead`, `editor.ts`) as the key goes down,
// and as the comment's line first appears.
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
    await review.settled();
});

afterEach(() => {
    expect(dashboard.thrown).toEqual([]);
});

afterAll(async () => {
    await dashboard?.close();
    await served?.close();
});

/** What the page noted of a comment's opening: the layouts the editor held as the last key went down, and as the comment's line first appeared. */
interface Opening {
    atKey: number | null;
    opened: number | null;
}

/**
 * Note, in the page, how many layouts the editor holds as each key goes down, until a comment opens, and as its line
 * first appears: an empty line more than as the keys began, the cursor on it, in the transaction that puts it there.
 * The count is the editor's own (`ahead`), found among its state's values by its shape, as the page offers no handle.
 */
async function noting(): Promise<void> {
    await review.evaluate((view) => {
        const layouts = (): number => {
            for (const value of (view.state as unknown as { values: unknown[] }).values) {
                if (typeof value === "object" && value !== null && "layouts" in value && "changes" in value && typeof value.layouts === "number") {
                    return value.layouts;
                }
            }
            throw new Error("the editor's count of layouts (`ahead`, editor.ts) isn't among its state's values");
        };
        const lines = view.state.doc.lines;
        const noted: Opening = { atKey: null, opened: null };
        const down = () => {
            if (noted.opened === null) {
                noted.atKey = layouts();
            }
        };
        addEventListener("keydown", down, { capture: true });
        const editor = view as unknown as { dispatchTransactions: (trs: readonly unknown[], view: unknown) => void };
        const dispatching = editor.dispatchTransactions;
        editor.dispatchTransactions = (trs, on) => {
            dispatching(trs, on);
            const line = view.state.doc.lineAt(view.state.selection.main.head);
            if (noted.opened === null && view.state.doc.lines > lines && line.text === "") {
                noted.opened = layouts();
            }
        };
        Object.assign(globalThis, {
            lupDriveOpening: noted,
            lupDriveOpeningDone: () => {
                removeEventListener("keydown", down, { capture: true });
                editor.dispatchTransactions = dispatching;
            },
        });
    });
}

describe("opening a comment, in headless Chromium", () => {
    it.each(["o", "S", "cc", "cw", "C"])("opens one with %s in one layout of the review, the comment's line in it", async (keys) => {
        await review.goTo(DEMO_ITEM);
        await dashboard.page.keyboard.press("j");
        await review.inMode("normal");
        await noting();
        await dashboard.keys.press([...keys]);
        await review.inMode("insert");
        await review.until("opened the comment", () => (globalThis as unknown as { lupDriveOpening: Opening }).lupDriveOpening.opened !== null);
        const noted = await dashboard.page.evaluate(() => {
            const seen = globalThis as unknown as { lupDriveOpening: Opening; lupDriveOpeningDone: () => void };
            seen.lupDriveOpeningDone();
            return seen.lupDriveOpening;
        });
        expect(noted.atKey).not.toBeNull();
        expect((noted.opened ?? 0) - (noted.atKey ?? 0)).toBe(1);
        // Emptied, the comment is dropped as it ends.
        await dashboard.keys.press(["Escape"]);
        await review.inMode("normal");
        await review.until("dropped the emptied comment", (view) => view.state.doc.lineAt(view.state.selection.main.head).text !== "");
    });
});
