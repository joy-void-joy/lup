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
        // A test that runs out of its time stops, and takes nothing of itself into the next (`stopping.ts`).
        setupFiles: ["stopping.ts"],
        testTimeout: 60_000,
        hookTimeout: 60_000,
        // Six files at a time: each runs a demo and a Chromium, about 230 processes and threads, so this peaks near 1,400
        // of a room's limit (`Podman.pids_limit`), which every session and gate in it shares, and takes the 18 files from
        // 60 s on three to 32 s. All at once, one per core, the first 13 files reached podman's default of 2,048 and
        // crashed (`docs/field-notes.md`, *The drive tests in a room*). Gates' runs at once share the room's cores too,
        // so `pnpm run drive` takes the room's lock first (`package.json`), and waits its turn.
        maxWorkers: 6,
    },
});
