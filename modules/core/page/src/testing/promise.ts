// The page's promises, declared as a module's are in Python (`lup.testing`): a
// sentence saying what someone can count on, and its check, a law or a scenario.
//
// A scenario is a story that asserts, drawing what it explores from the harness
// (`by.any`), which fast-check generates and shrinks to the smallest values that
// break it. A law is a statement about every moment of a machine, the shell
// among them: a predicate over each step of every run, a scenario's and those
// fast-check generates, checked after every step, a run that breaks one shrunk to
// the shortest that does. Each runs as a test of vitest's under its sentence, the
// gate's runs repeatable, each seeded from its sentence; `LUP_EXPLORE` set to a
// number of runs draws at random instead, apart from the gate.

import fc from "fast-check";
import { test } from "vitest";

/** What a scenario is handed: the harness, drawing what it explores. */
export interface Testing {
    /** Return a value `arbitrary` generates: each run draws another, and one that breaks the promise is shrunk to the smallest that does. */
    any<T>(arbitrary: fc.Arbitrary<T>): T;
}

/** One step of a machine's run, as a law reads it: its state before, what happened, its state after. */
export interface Step<S, E> {
    readonly before: S;
    readonly event: E;
    readonly after: S;
}

/** A thing a law holds over: how it starts, what can happen to it, and its state as a law reads it. */
export interface Machine<M, S, E> {
    /** Say what's checked: the machine's name, as a law's test is grouped under it. */
    readonly name: string;
    /** Start one, for one run. */
    start(by: Testing): M | Promise<M>;
    /** What can happen to it, as fast-check draws it. */
    readonly events: fc.Arbitrary<E>;
    /** Make `event` happen to it. */
    apply(machine: M, event: E): void | Promise<void>;
    /** Its state as a law reads it, a value of its own that later events don't change. */
    state(machine: M): S;
    /** End it, once a run is done. */
    end?(machine: M): void;
}

/** A law broken: the step it didn't hold over. */
export class BrokenLaw extends Error {
    constructor(law: string, step: Step<unknown, unknown>) {
        super(`the law \`${law}\` doesn't hold over this step: ${JSON.stringify(step)}`);
        this.name = "BrokenLaw";
    }
}

const runs = Number(process.env["LUP_EXPLORE"] ?? 0);

/**
 * How long a promise's runs, its shrinking among them, may take before it's failed for taking it, in milliseconds. Runs
 * make no real time of their own, so this is a ceiling on work, not a wait.
 */
const ceiling = 60_000;

/** Return how a promise's property is run: seeded from its sentence in the gate, so a run is repeatable; at random, as many times as `LUP_EXPLORE` says, apart from it. */
function settings(sentence: string): fc.Parameters<unknown> {
    const limits = { interruptAfterTimeLimit: ceiling, markInterruptAsFailure: true };
    if (runs > 0) {
        return { ...limits, numRuns: runs };
    }
    let seed = 0;
    for (const char of sentence) {
        seed = (Math.imul(seed, 31) + (char.codePointAt(0) ?? 0)) | 0;
    }
    return { ...limits, seed, numRuns: 100 };
}

/**
 * Let what a run left queued run: an editor schedules its own work (measuring, observing) on the page's timers, each
 * holding the editor, and a run that only awaits promises never gives those timers a turn. Shrinking runs thousands
 * back to back, which kept every one's editor and ran out of memory before saying what broke.
 */
async function drained(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 0));
}

class Drawing implements Testing {
    readonly #draw: fc.GeneratorValue;

    constructor(draw: fc.GeneratorValue) {
        this.#draw = draw;
    }

    any<T>(arbitrary: fc.Arbitrary<T>): T {
        return this.#draw(() => arbitrary);
    }
}

/** Declare a scenario: `sentence`, what someone can count on, checked by `story`, which asserts. */
export function scenario(sentence: string, story: (by: Testing) => void | Promise<void>): void {
    test(sentence, async () => {
        await fc.assert(
            fc.asyncProperty(fc.gen(), async (draw) => {
                try {
                    await story(new Drawing(draw));
                } finally {
                    await drained();
                }
            }),
            settings(sentence),
        );
    });
}

/**
 * Declare a law of `machine`: `sentence`, what holds at every moment, checked by `holds` over each step of every run
 * fast-check generates of what can happen to it.
 */
export function law<M, S, E>(machine: Machine<M, S, E>, sentence: string, holds: (step: Step<S, E>) => boolean): void {
    test(`${machine.name}: ${sentence}`, async () => {
        await fc.assert(
            fc.asyncProperty(fc.gen(), fc.array(machine.events, { maxLength: 20 }), async (draw, events) => {
                const running = await machine.start(new Drawing(draw));
                try {
                    let before = machine.state(running);
                    for (const event of events) {
                        await machine.apply(running, event);
                        const after = machine.state(running);
                        const step = { before, event, after };
                        if (!holds(step)) {
                            throw new BrokenLaw(sentence, step);
                        }
                        before = after;
                    }
                } finally {
                    machine.end?.(running);
                    await drained();
                }
            }),
            settings(sentence),
        );
    });
}
