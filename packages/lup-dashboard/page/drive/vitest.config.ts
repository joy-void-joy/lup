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
    },
});
