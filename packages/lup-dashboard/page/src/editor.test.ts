import { describe, expect, it } from "vitest";

import { deadPressed, deadTyped, type Dead, type Pressed } from "./editor";

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
