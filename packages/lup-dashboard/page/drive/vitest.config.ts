// The driver's tests: the room's Chromium driving the demo, as the gate's `drive` step runs them (`lup_project.py`),
// apart from the page's own, which run wherever the page is built, the host among them, where there's no Chromium.
//
// Each waits on what it checks, never on time: the bounds below are for a test that would otherwise hang.
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
    // The page's own, which git ignores, rather than one beside the driver's files.
    cacheDir: fileURLToPath(new URL("../node_modules/.vite", import.meta.url)),
    test: {
        root: fileURLToPath(new URL(".", import.meta.url)),
        include: ["*.test.ts"],
        testTimeout: 60_000,
        hookTimeout: 60_000,
        // Three files at a time: each runs a demo and a Chromium, about 230 processes and threads, and a room holds
        // 2,048 at most (#162), shared by every session and gate in it. All at once, one per core, 13 files reached
        // the limit: Chromium crashed, `xdotool` couldn't start, the demo answered 500. Three peaked at 722 and ran in
        // 29 s, faster than all at once (`docs/field-notes.md`, *The drive tests in a room*).
        maxWorkers: 3,
    },
});
