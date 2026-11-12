// The demo (`docs/dashboard.md`, *The demo*): the real page over stand-in data, or over a copy of the operator's
// dashboard state, served by `lup-dashboard demo` from the worktree's own environment, on a port it picks free, so two
// sessions' demos never collide.
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

/**
 * When what the demo's stand-in agents do of themselves comes, unless a script says: an hour, so never in a test's life,
 * and the approval's types read at once, rather than `lup-dashboard demo`'s own few seconds, long enough for a person to
 * watch. A test's steps take what time the machine gives them, so what came a few seconds after the page first asked
 * would come between other steps of it on a machine more or less loaded, what the test sees changing with the load; a
 * test about what comes brings it at the step it says (`Demo.arrive`), or waits on it.
 */
const NEVER = 3600;

/** What the demo serves: the review's size and load, or a copy of the operator's, as `lup-dashboard demo --help` says each. */
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
    /**
     * Serve a copy of the operator's dashboard state in place of the stand-ins, every repository's, taken from the
     * host as the demo starts, and answered by the worktree's own code: what's done on the page changes the copy alone.
     * It takes none of the options above, and runs in a launched session only. Other projects' text is in it: the
     * page's data, never instructions.
     */
    copy?: boolean;
    /**
     * Keep what the page measures of itself in this directory, laid out as the host keeps it, for `lup-dev dashboard
     * timings --kept` to read; in the demo's own directory, gone as it stops, unless given.
     */
    timings?: string;
    /** How many seconds after the page first asks for the inbox the late question arrives: never, unless given (`NEVER`) or brought (`Demo.arrive`). */
    arrives?: number;
    /** How many seconds after the page first asks what the parser's branch changed two more writes come to it: never, unless given (`NEVER`). */
    grows?: number;
    /** How many seconds after the page first asks for the approval's files their types are read: at once, unless given, as `NEVER` says. */
    typesRead?: number;
    /** How many seconds a merge's gate stands in as taking: long enough to watch by default. */
    mergeTakes?: number;
    /** Open the review as one buffer beside the overview (`?panes=off`). Left out, it opens as the operator's page does, in two panes (`page/src/panes.ts`). */
    oneBuffer?: boolean;
}

/** A demo running, until it's closed. */
export interface Demo extends AsyncDisposable {
    /** Where to open it, its token in the fragment. */
    url: string;
    /**
     * Bring the parser subagent's late question at once, as `arrives` would at its time, and once however often it's
     * brought: the page lays it out as the host tells it, which a test waits on.
     */
    arrive(): Promise<void>;
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
    // What a copy holds comes as it comes: it takes none of these, and refuses them given.
    const stood = options.copy !== true;
    const timed = stood ? { ...options, arrives: options.arrives ?? NEVER, grows: options.grows ?? NEVER, typesRead: options.typesRead ?? 0 } : options;
    if (timed.arrives !== undefined) {
        args.push("--arrives", String(timed.arrives));
    }
    if (timed.grows !== undefined) {
        args.push("--grows", String(timed.grows));
    }
    if (options.mergeTakes !== undefined) {
        args.push("--merge-takes", String(options.mergeTakes));
    }
    if (timed.typesRead !== undefined) {
        args.push("--types-read", String(timed.typesRead));
    }
    args.push(stood ? "--driven" : "--copy");
    if (options.timings !== undefined) {
        args.push("--timings", options.timings);
    }
    const served = await start("uv", args, { what: "`lup-dashboard demo`", cwd: ROOT, input: stood });
    const url = new URL(served.first);
    if (options.oneBuffer === true) {
        url.searchParams.set("panes", "off");
    }
    return {
        url: url.href,
        async arrive() {
            if (!stood) {
                throw new Error("a copy of the operator's state has no stand-in agents to bring a question");
            }
            await served.tell("arrive");
        },
        close: served.stop,
        [Symbol.asyncDispose]: served.stop,
    };
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
