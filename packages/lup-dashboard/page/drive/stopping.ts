// A test that runs out of its time stops (#379). vitest moves on to the next test, but the one that ran out goes on, and on
// a page the next test shares, its keys would reach the next test's: one timeout read as several failures, the next tests'
// having nothing to do with them. So as its time runs out every dashboard open is ended (`endAll`), what it goes on doing
// failing at once, and each test after it is skipped while a dashboard it shared is ended and still open. What it opened
// for itself goes with it (`forget`), so a test after it with a page of its own runs.
import { afterEach, beforeEach } from "vitest";

import { endAll, ended, forget, owning } from "./dashboard.ts";

beforeEach(({ signal, skip, task }) => {
    const why = ended();
    if (why !== null) {
        skip(why);
    }
    owning(task.id);
    signal.addEventListener("abort", () => void endAll(`"${task.name}" ran out of its time, and the page it shared went with it`), { once: true });
});

afterEach(({ task }) => {
    owning(null);
    forget(task.id);
});
