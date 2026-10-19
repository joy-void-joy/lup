import { describe, expect, it } from "vitest";

import { begun, deadPressed, deadTyped, nextWritten, rewritten, stepped, visit, went, type Dead, type History, type Pressed } from "./editor";

describe("the draft's history", () => {
    const draft = (history: History<string>) => history.states[history.at]?.draft;

    it("undoes and redoes steps, a step being written one", () => {
        let history = stepped(begun(""), "a");
        history = rewritten(history, "ab");
        history = stepped(history, "ab c");
        expect(draft(went(history, "undo"))).toBe("ab");
        expect(draft(went(went(history, "undo"), "undo"))).toBe("");
        expect(draft(went(went(went(history, "undo"), "undo"), "redo"))).toBe("ab");
        expect(went(begun(""), "undo")).toEqual(begun(""));
        expect(went(history, "redo")).toEqual(history);
    });

    it("reaches with g- a state undone and left by a change after it, which Ctrl+R no longer does", () => {
        // Text written, undone, then a change made: vim's g- still reaches what was undone.
        let history = stepped(begun(""), "kept");
        history = stepped(history, "kept, lost");
        history = went(history, "undo");
        history = stepped(history, "kept, other");
        expect(went(history, "redo")).toEqual(history);
        expect(draft(went(history, "earlier"))).toBe("kept, lost");
        expect(draft(went(went(history, "earlier"), "later"))).toBe("kept, other");
        // `u` from the change goes back to what it was made from, and Ctrl+R to the change again.
        expect(draft(went(history, "undo"))).toBe("kept");
        expect(draft(went(went(history, "undo"), "redo"))).toBe("kept, other");
    });
});

describe("going between the comments one wrote", () => {
    // Three comments, at 10–15, 16–20 and 40–48.
    const blocks = [
        { from: 40, to: 48 },
        { from: 10, to: 15 },
        { from: 16, to: 20 },
    ];

    it("goes to the next and previous comment in the text's order, past the one the cursor is in, on its last character", () => {
        expect(nextWritten(blocks, 0, true, [])).toBe(14);
        expect(nextWritten(blocks, 12, true, [])).toBe(19);
        expect(nextWritten(blocks, 20, true, [])).toBe(47);
        expect(nextWritten(blocks, 30, false, [])).toBe(19);
        expect(nextWritten(blocks, 17, false, [])).toBe(14);
        expect(nextWritten(blocks, 44, true, [])).toBeUndefined();
        expect(nextWritten(blocks, 12, false, [])).toBeUndefined();
    });

    it("lands where the cursor last was in it, kept as it leaves each comment, one place a comment", () => {
        let visited = visit([], blocks, 12, 13);
        expect(visited).toEqual([]);
        visited = visit(visited, blocks, 11, 30);
        expect(visited).toEqual([11]);
        expect(nextWritten(blocks, 0, true, visited)).toBe(11);
        visited = visit(visited, blocks, 13, 44);
        expect(visited).toEqual([13]);
        visited = visit(visited, blocks, 42, 0);
        expect(visited).toEqual([13, 42]);
        expect(nextWritten(blocks, 20, true, visited)).toBe(42);
        // A place no comment is at any more is let go.
        expect(visit(visited, [{ from: 40, to: 48 }], 44, 0)).toEqual([44]);
        // Left past its last character, as writing ends, it lands on it.
        expect(nextWritten(blocks, 0, true, [15])).toBe(14);
    });
});

/** What vim gets of a dead key's keys and the text they type, outside insert mode, in order: each key it's given and each text, and what lands, which is nothing. */
function through(events: ({ pressed: Pressed } | { typed: string })[]): { vim: string[]; dead: Dead } {
    let dead: Dead = "none";
    const vim: string[] = [];
    for (const event of events) {
        if ("pressed" in event) {
            const step = deadPressed(dead, event.pressed);
            dead = step.dead;
            if (!step.kept) {
                vim.push(event.pressed.key);
            }
        } else {
            const step = deadTyped(dead);
            dead = step.dead;
            if (step.given) {
                vim.push(event.typed);
            }
        }
    }
    return { vim, dead };
}

const DEAD = { pressed: { key: "Dead", composing: false } };
const key = (name: string, composing = false) => ({ pressed: { key: name, composing } });

describe("a dead key outside insert mode", () => {
    it("gives vim what it first types, once, and keeps the Space completing it from vim", () => {
        // `` ` `` composing shows `` ` ``, then Space commits it, then `a`: a jump to mark `a`.
        expect(through([DEAD, { typed: "`" }, key(" ", true), { typed: "`" }, key("a")])).toEqual({ vim: ["`", "a"], dead: "none" });
        // The browser ending the composition early: Space comes as a key of its own, then its text.
        expect(through([DEAD, { typed: "'" }, key(" "), { typed: "'" }, key("a")]).vim).toEqual(["'", "a"]);
    });

    it("lets the key after it reach vim where it isn't a Space, as `` ` `` then `a` jumps to mark `a`", () => {
        expect(through([DEAD, { typed: "`" }, key("a")])).toEqual({ vim: ["`", "a"], dead: "none" });
    });

    it("gives vim nothing typed with no dead key pressed, as a paste, and takes no key from vim", () => {
        expect(through([{ typed: "dd" }, key(" "), key("j")])).toEqual({ vim: [" ", "j"], dead: "none" });
    });

    it("keeps a key the browser composes from vim, and a dead key pressed again waits again", () => {
        expect(through([DEAD, key("Process"), { typed: "`" }, DEAD, { typed: "'" }, key(" ")]).vim).toEqual(["`", "'"]);
    });
});
