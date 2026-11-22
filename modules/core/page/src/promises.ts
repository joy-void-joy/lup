// The page's own promises, apart from the shell's: what the operator can count on of opening the dashboard, in as
// many tabs as they like.

import fc from "fast-check";
import { expect } from "vitest";

import { remembered } from "./server";
import { scenario } from "./testing/promise";

/** A token as the server makes one, `secrets.token_urlsafe`'s alphabet. */
const tokens = fc.stringMatching(/^[A-Za-z0-9_-]{1,43}$/);

/** The storage every tab of the dashboard's address shares, as the page keeps its token in, emptied for a run. */
function fresh(): Storage {
    localStorage.clear();
    return localStorage;
}

scenario("A tab opened on the dashboard's address without its token says the token another tab was handed", (by) => {
    const storage = fresh();
    const handed = by.any(tokens);
    expect(remembered(`#${handed}`, storage)).toBe(handed);
    expect(remembered("", storage)).toBe(handed);
});

scenario("The token an address hands is the one said, over any kept before", (by) => {
    const storage = fresh();
    const before = by.any(tokens);
    const after = by.any(tokens);
    remembered(`#${before}`, storage);
    expect(remembered(`#${after}`, storage)).toBe(after);
    expect(remembered("", storage)).toBe(after);
});
