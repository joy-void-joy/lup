// The programs the driver starts beside the browser, the demo and a virtual display: each stopped as the driver's own
// process ends, however it ends, so a script that throws or is interrupted leaves none running in the room.
import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";

/** A program the driver started, once it printed its first line. */
export interface Program {
    /** Its first line of output: where it listens, or the display it took. */
    first: string;
    /** Stop it, and return once it's gone. */
    stop(): Promise<void>;
}

/** What `start` runs a program with. */
export interface Starting {
    /** What the program is, as an error names it. */
    what: string;
    cwd?: string;
    env?: NodeJS.ProcessEnv;
}

/** The programs running, each stopped as the process ends. */
const running = new Set<ChildProcess>();

/**
 * Start `command`, and return it once it prints its first line, which `Program.first` holds; throw where it ends or
 * can't start first, with what it said on its error output.
 */
export async function start(command: string, args: string[], starting: Starting): Promise<Program> {
    stopWithProcess();
    const child = spawn(command, args, { cwd: starting.cwd, env: starting.env ?? process.env, stdio: ["ignore", "pipe", "pipe"] });
    running.add(child);
    const gone = new Promise<void>((resolve) => {
        const ended = () => {
            running.delete(child);
            resolve();
        };
        child.once("exit", ended);
        child.once("error", ended);
    });
    const said: string[] = [];
    const saying = (chunk: string) => said.push(chunk);
    child.stderr.setEncoding("utf8").on("data", saying);
    const lines = createInterface({ input: child.stdout });
    const first = await new Promise<string | Error>((resolve) => {
        lines.once("line", resolve);
        child.once("error", resolve);
        child.once("exit", () => resolve(new Error(`${starting.what} ended before saying it was ready:\n${said.join("")}`)));
    });
    if (first instanceof Error) {
        throw first;
    }
    // What it says from now on is read and let go, so a full pipe never holds it up.
    child.stderr.off("data", saying).resume();
    lines.on("line", () => undefined);
    return {
        first,
        async stop() {
            if (child.exitCode === null && child.signalCode === null) {
                child.kill("SIGTERM");
            }
            await gone;
        },
    };
}

/** Whether `stopWithProcess` has registered its handlers. */
let stopping = false;

/**
 * Stop every program still running as the process exits, and as it's interrupted or terminated, which would otherwise
 * end it without its exit handlers: the signal is raised again once they're stopped, so the process ends as it would
 * have.
 */
function stopWithProcess(): void {
    if (stopping) {
        return;
    }
    stopping = true;
    const stopAll = () => {
        for (const child of running) {
            child.kill("SIGTERM");
        }
    };
    process.on("exit", stopAll);
    for (const signal of ["SIGINT", "SIGTERM"] as const) {
        process.once(signal, () => {
            stopAll();
            process.kill(process.pid, signal);
        });
    }
}
