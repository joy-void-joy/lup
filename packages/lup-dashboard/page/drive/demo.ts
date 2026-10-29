// The demo (`docs/dashboard.md`, *The demo*): the real page over stand-in data, served by `lup-dashboard demo` from the
// worktree's own environment, on a port it picks free, so two sessions' demos never collide.
import { execFile } from "node:child_process";
import { existsSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import { start } from "./program.ts";

/** The repository's root, where `uv run` finds the worktree's own environment. */
const ROOT = fileURLToPath(new URL("../../../../", import.meta.url));

/** The page's own project, whose sources the built page is made from. */
const PAGE = fileURLToPath(new URL("../", import.meta.url));

/** The page as the demo serves it, built into the dashboard's package (`packages/lup-dashboard/build.py`). */
const BUILT = fileURLToPath(new URL("../../src/lup_dashboard/page/index.html", import.meta.url));

/** The review's size and load, as `lup-dashboard demo --help` says each. */
export interface DemoOptions {
    /** How many flagged writes of a busy day the review holds beside the demo's own items: a busy day's unless given, 0 for the demo's own alone. */
    size?: number;
    /**
     * How many lines the approval's change holds beside its own files: 30000 makes the review the size of the
     * operator's on 2026-10-29 (`docs/field-notes.md`, *The dashboard's review at the operator's size*).
     */
    approvalLines?: number;
    /** How many stand-in hook calls a minute the workers make, each answering every watch again, as the host service does. */
    hooks?: number;
}

/** A demo running, until it's closed. */
export interface Demo extends AsyncDisposable {
    /** Where to open it, its token in the fragment. */
    url: string;
    close(): Promise<void>;
}

/**
 * Serve the demo on a free port, and return it once it listens; built again first where one of the page's sources is
 * newer than its build, saying so, since the demo serves the built page and a session looking at their change would
 * otherwise see the one before it.
 */
export async function demo(options: DemoOptions = {}): Promise<Demo> {
    const newer = newerThanBuilt();
    if (newer !== null) {
        console.error(`drive: building the page, ${newer === BUILT ? "never built" : `${newer} being newer than its build`}`);
        await promisify(execFile)("uv", ["run", "packages/lup-dashboard/build.py"], { cwd: ROOT, maxBuffer: 64 * 1024 * 1024 });
    }
    const args = ["run", "lup-dashboard", "demo", "--port", "0"];
    if (options.size !== undefined) {
        args.push("--size", String(options.size));
    }
    if (options.approvalLines !== undefined) {
        args.push("--approval-lines", String(options.approvalLines));
    }
    if (options.hooks !== undefined) {
        args.push("--hooks", String(options.hooks));
    }
    const served = await start("uv", args, { what: "`lup-dashboard demo`", cwd: ROOT });
    return { url: new URL(served.first).href, close: served.stop, [Symbol.asyncDispose]: served.stop };
}

/** Return the first of the page's sources newer than its build, the build itself where there's none, else null. */
function newerThanBuilt(): string | null {
    if (!existsSync(BUILT)) {
        return BUILT;
    }
    const built = statSync(BUILT).mtimeMs;
    const sources = [join(PAGE, "index.html"), ...readdirSync(join(PAGE, "src"), { recursive: true, encoding: "utf8" }).map((each) => join(PAGE, "src", each))];
    return sources.find((each) => statSync(each).mtimeMs > built) ?? null;
}
