// What's read by being on screen, and what it moves (`seeing.ts`): over a clock and a view the test moves, since no key
// nor scroll a real page makes is needed to say what a time in view does.
import { describe, expect, it } from "vitest";

import { AWAY, DWELL, Dwelling, EDGE, MOST_TICK, PER_LINE, dwellFor, shownOf, type Moving, type Sighted, type Viewing } from "./seeing";

function moves(up_to: string, key: Record<string, unknown> = { node: 1 }): Moving {
    return { repository: "/r.git", module: "core", key, up_to, forward: true, seen: true };
}

function sight(id: string, from: number, to: number, fields: Partial<Sighted> = {}): Sighted {
    return { id, mark: "thread", moves: moves(id), from, to, lines: 1, standing: false, held: false, ...fields };
}

/** What's in view: nothing hidden, or what `closed` says, each a closed fold's start and end. */
function view(from: number, to: number, closed: readonly [number, number][] = []): Viewing {
    return { from, to, closedAt: (at) => closed.find(([start, end]) => start < at && at <= end)?.[0] ?? null };
}

/** Run `dwelling`'s clock from `at` for `ms`, a tick at a time. */
function run(dwelling: Dwelling, sights: readonly Sighted[], viewing: Viewing | null, at: number, ms: number, there: boolean = true): number {
    let now = at;
    dwelling.advance(now, sights, viewing, there);
    while (now < at + ms) {
        now += 500;
        dwelling.advance(now, sights, viewing, there);
    }
    return now;
}

describe("how long a thing takes to be seen", () => {
    it("asks for longer of a long one", () => {
        expect(dwellFor(1)).toBe(DWELL);
        expect(dwellFor(100)).toBe(100 * PER_LINE);
    });

    it("leaves what was scrolled past quickly new", () => {
        const dwelling = new Dwelling();
        const one = sight("1", 10, 20);
        run(dwelling, [one], view(0, 100), 0, DWELL / 2);
        expect(dwelling.seen(one)).toBe(false);
        run(dwelling, [one], view(0, 100), DWELL / 2, DWELL);
        expect(dwelling.seen(one)).toBe(true);
    });

    it("asks a thing longer than the screen to have shown both its ends, for long enough, a jump to its end alone not reading it", () => {
        const dwelling = new Dwelling();
        const long = sight("1", 100, 900, { lines: 10 });
        // Its end alone, however long.
        let at = run(dwelling, [long], view(800, 1000), 0, 10_000);
        expect(dwelling.seen(long)).toBe(false);
        // Then its start, for long enough.
        at = run(dwelling, [long], view(50, 200), at, EDGE);
        expect(dwelling.seen(long)).toBe(true);
    });

    it("counts no time while they aren't there, nor a page asleep for an hour", () => {
        const dwelling = new Dwelling();
        const one = sight("1", 10, 20);
        const at = run(dwelling, [one], view(0, 100), 0, 60_000, false);
        expect(dwelling.seen(one)).toBe(false);
        // The first tick back after an hour asleep counts for a tick.
        dwelling.advance(at + 3_600_000, [one], view(0, 100), true);
        expect(dwelling.seen(one)).toBe(false);
        expect(MOST_TICK).toBeLessThan(DWELL);
        expect(AWAY).toBeGreaterThan(DWELL);
    });

    it("sees nothing a closed fold hides, what's left of one past its fold being its line", () => {
        const dwelling = new Dwelling();
        const under = sight("1", 50, 60);
        run(dwelling, [under], view(0, 100, [[40, 70]]), 0, 10_000);
        expect(dwelling.seen(under)).toBe(false);
        expect(shownOf(under, view(0, 100, [[40, 70]]))).toBeNull();
        // A closed fold within what it reads is that fold's line, and the rest counts.
        const around = sight("2", 30, 60);
        run(dwelling, [around], view(0, 35, [[35, 60]]), 0, 10_000);
        expect(dwelling.seen(around)).toBe(true);
    });
});

describe("what moves a mark", () => {
    it("moves as a seen thing leaves the screen, never while it's on it, or as the tab goes", () => {
        const dwelling = new Dwelling();
        const one = sight("1", 10, 20);
        run(dwelling, [one], view(0, 100), 0, DWELL);
        expect(dwelling.due([one], view(0, 100), false)).toEqual([]);
        expect(dwelling.due([one], view(200, 300), false)).toMatchObject([{ moves: { up_to: "1" } }]);
    });

    it("moves as the tab goes, what's still on screen among it", () => {
        const dwelling = new Dwelling();
        const one = sight("1", 10, 20);
        run(dwelling, [one], view(0, 100), 0, DWELL);
        expect(dwelling.due([one], view(0, 100), true)).toMatchObject([{ moves: { up_to: "1" } }]);
    });

    it("stops at the first thing not seen: what's seen past it waits, however long", () => {
        const dwelling = new Dwelling();
        const first = sight("1", 10, 20);
        const second = sight("2", 110, 120);
        const third = sight("3", 210, 220);
        const all = [first, second, third];
        // `G`: the last read, the others passed by.
        run(dwelling, all, view(200, 300), 0, DWELL);
        expect(dwelling.due(all, view(1000, 1100), false)).toEqual([]);
        // Reading the first moves it there, no further, the second not seen.
        run(dwelling, all, view(0, 100), 10_000, DWELL);
        expect(dwelling.due(all, view(1000, 1100), false)).toMatchObject([{ moves: { up_to: "1" } }]);
        // The second read, it goes on to the last, what was seen past the gap counting.
        run(dwelling, all, view(100, 150), 20_000, DWELL);
        expect(dwelling.due(all, view(1000, 1100), false)).toMatchObject([{ moves: { up_to: "3" } }]);
    });

    it("holds at what a closed fold holds of what's new, and goes on once it's open, what it holds saying so itself", () => {
        const dwelling = new Dwelling();
        const fold = sight("fold", 11, 50, { standing: true });
        const after = sight("after", 60, 70);
        const all = [fold, after];
        run(dwelling, all, view(0, 100, [[10, 50]]), 0, DWELL);
        expect(dwelling.seen(after)).toBe(true);
        expect(dwelling.due(all, view(200, 300, [[10, 50]]), false)).toEqual([]);
        expect(dwelling.due(all, view(200, 300), false)).toMatchObject([{ moves: { up_to: "after" } }]);
    });

    it("holds at what holds what they wrote, and at what's laid out nowhere", () => {
        const dwelling = new Dwelling();
        const writing = sight("1", 10, 20, { held: true });
        run(dwelling, [writing], view(0, 100), 0, DWELL);
        expect(dwelling.due([writing], view(200, 300), false)).toEqual([]);
    });

    it("goes past what asks them unseen, which waits on them wherever the mark is", () => {
        const dwelling = new Dwelling();
        const asks = sight("1", 10, 20, { asks: true });
        const news = sight("2", 110, 120);
        const all = [asks, news];
        run(dwelling, all, view(100, 200), 0, DWELL);
        expect(dwelling.due(all, view(1000, 1100), false)).toMatchObject([{ moves: { up_to: "2" } }]);
    });

    it("keeps each mark apart", () => {
        const dwelling = new Dwelling();
        const a = sight("a", 10, 20, { mark: "one", moves: moves("a", { node: 1 }) });
        const b = sight("b", 30, 40, { mark: "two", moves: moves("b", { node: 2 }) });
        const all = [a, b];
        run(dwelling, all, view(0, 100), 0, DWELL);
        expect(dwelling.due(all, view(200, 300), false)).toEqual([
            { ids: ["a"], moves: a.moves },
            { ids: ["b"], moves: b.moves },
        ]);
    });

    it("says each once, and again where it wasn't kept", () => {
        const dwelling = new Dwelling();
        const one = sight("1", 10, 20);
        run(dwelling, [one], view(0, 100), 0, DWELL);
        const [due] = dwelling.due([one], view(200, 300), false);
        expect(due).toBeDefined();
        expect(dwelling.due([one], view(200, 300), false)).toEqual([]);
        if (due !== undefined) {
            dwelling.failed(due);
        }
        expect(dwelling.due([one], view(200, 300), false)).toHaveLength(1);
    });

    it("forgets what's read since, what's no longer to be seen", () => {
        const dwelling = new Dwelling();
        const one = sight("1", 10, 20);
        run(dwelling, [one], view(0, 100), 0, DWELL);
        dwelling.settled([]);
        expect(dwelling.seen(one)).toBe(false);
    });
});
