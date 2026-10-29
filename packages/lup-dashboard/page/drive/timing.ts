// How long each key takes to reach the screen: from the moment it's sent to the end of the frame after the page handled
// it, so a key queued behind a busy page counts the time it waited (`docs/field-notes.md`, *The dashboard's review at
// the operator's size*).
import { errors, type Page } from "playwright";

import type { Sent } from "./keys.ts";

/** A key sent, and how long it took to reach the screen, in milliseconds: null where the page never saw it. */
export interface KeyTime {
    key: string;
    toFrame: number | null;
}

/** Keys sent and how each was drawn. */
export interface Timed {
    keys: KeyTime[];
    /** How many the page saw, by their `keydown`. */
    seen: number;
}

/** The middle of a measure's values, its 90th percentile, and its most, each in milliseconds. */
export interface Percentiles {
    median: number;
    p90: number;
    most: number;
}

/** What the page records of each key it sees, from its `keydown`. */
interface Recorded {
    key: string;
    /** When the frame after it was drawn, in milliseconds since the epoch. */
    drawn?: number;
}

/**
 * Send keys with `send`, and return how long each took to reach the screen, once the page has drawn every one, or
 * `within` milliseconds after the last was sent, those it never saw counted as such.
 *
 * Each key's `keydown`, as the page's window first sees it, waits for the next animation frame, whose callbacks run
 * before it's drawn, and then for the task after them, which runs once it is: the end of the frame drawing what the key
 * did. Keys are matched to what was sent in order.
 */
export async function timed(page: Page, send: () => Promise<Sent[]>, within = 30_000): Promise<Timed> {
    await page.evaluate(() => {
        const recorded: Recorded[] = [];
        const record = (event: KeyboardEvent) => {
            const key: Recorded = { key: event.key };
            recorded.push(key);
            requestAnimationFrame(() => setTimeout(() => (key.drawn = performance.timeOrigin + performance.now())));
        };
        const before = (globalThis as unknown as { lupDriveTiming?: (event: KeyboardEvent) => void }).lupDriveTiming;
        if (before !== undefined) {
            removeEventListener("keydown", before, { capture: true });
        }
        Object.assign(globalThis, { lupDriveTiming: record, lupDriveKeys: recorded });
        addEventListener("keydown", record, { capture: true });
    });
    const sent = await send();
    const recorded = () => (globalThis as unknown as { lupDriveKeys: Recorded[] }).lupDriveKeys;
    await page
        .waitForFunction((count) => { const keys = (globalThis as unknown as { lupDriveKeys: Recorded[] }).lupDriveKeys; return keys.length >= count && keys.every((key) => key.drawn !== undefined); }, sent.length, { polling: 100, timeout: within })
        .catch((failed: unknown) => {
            // What never came is counted as such.
            if (!(failed instanceof errors.TimeoutError)) {
                throw failed;
            }
        });
    const drawn = await page.evaluate(recorded);
    return {
        keys: sent.map((each, index) => {
            const at = drawn[index]?.drawn;
            return { key: each.key, toFrame: at === undefined ? null : at - each.at };
        }),
        seen: drawn.length,
    };
}

/** The median, the 90th percentile and the most of `values`, each one of them, the nearest rank's; null where there are none. */
export function percentiles(values: number[]): Percentiles | null {
    const sorted = values.toSorted((a, b) => a - b);
    const at = (rank: number) => sorted[Math.min(sorted.length - 1, Math.floor(rank * sorted.length))] ?? 0;
    return sorted.length === 0 ? null : { median: at(0.5), p90: at(0.9), most: at(1) };
}
