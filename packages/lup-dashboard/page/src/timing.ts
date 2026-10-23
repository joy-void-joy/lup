// What the layout trials cost, measured where the address asks it (`?timing=on`):
// each laying out of the review and each frame the stack and the outline follow
// the view, as User Timing measures (`performance.getEntriesByName("lup-stack")`),
// which a page left open would otherwise gather without end.

/** Whether this page measures: its address says `timing=on`. */
const MEASURING = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("timing") === "on";

/** Measure under `name` what took from `began`, where the page measures. */
export function measured(name: string, began: number): void {
    if (MEASURING) {
        performance.measure(name, { start: began });
    }
}

/** Return what `made` makes, measuring how long it took under `name`, where the page measures. */
export function timed<T>(name: string, made: () => T): T {
    const began = performance.now();
    const out = made();
    measured(name, began);
    return out;
}
