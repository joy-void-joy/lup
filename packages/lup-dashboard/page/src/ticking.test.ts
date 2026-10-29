import { EditorState } from "@codemirror/state";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ticked, ticking, type Tick } from "./ticking";

/** A tick at `at`, said the same at any time. */
const tick = (at: number): Tick => ({ at, said: () => " · 3m", look: "drawn-wait" });

afterEach(() => {
    vi.restoreAllMocks();
});

describe("what's drawn beside the review's text", () => {
    it("goes with the text as it changes", () => {
        const placed = EditorState.create({ doc: "an item", extensions: [ticking] }).update({ effects: ticked.of([tick(2), tick(7)]) }).state;
        const changed = placed.update({ changes: { from: 0, insert: "new " } }).state;
        expect(changed.field(ticking).ticks.map((each) => each.at)).toEqual([6, 11]);
    });

    it("leaves out, and says, what was placed past the text the editor holds, so the next change can't throw", () => {
        const said = vi.spyOn(console, "error").mockImplementation(() => undefined);
        const placed = EditorState.create({ doc: "short", extensions: [ticking] }).update({ effects: ticked.of([tick(3), tick(40)]) }).state;
        expect(placed.field(ticking).ticks.map((each) => each.at)).toEqual([3]);
        expect(said).toHaveBeenCalledWith("lup: 1 of what's drawn beside the review were placed outside its text; left out");
        const changed = placed.update({ changes: { from: 0, insert: "a " } }).state;
        expect(changed.field(ticking).ticks.map((each) => each.at)).toEqual([5]);
    });
});
