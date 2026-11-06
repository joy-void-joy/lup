// The eye of what's read by being seen (`seeing.ts`; `docs/dashboard.md`, *Review marks*): what's in view, measured as
// the review's stack and overview measure it, and whether the operator is there to see it, added up a few times a second
// while anything's to be seen. Nothing here lays anything out, and no key does more than note the time it came (`docs/dashboard.md`, *Its timings*).
import { foldedRanges } from "@codemirror/language";
import { useEffect, useRef } from "react";

import { asked } from "./api";
import type { Following } from "./follow";
import { AWAY, Dwelling, EVERY, TICK, type Due, type Sighted, type Viewing } from "./seeing";

interface Seeing {
    following: Following;
    /** Each thing read by being on screen, as the review is laid out. */
    sights: readonly Sighted[];
    /** How many pixels of the stack are over a line once it's the first under it. */
    over: (position: number) => number;
    /** Map a place of the buffer to the layout's, and back. */
    toLaid: (position: number) => number;
    fromLaid: (position: number) => number;
    /** Whether they're writing: their eyes are on the comment. */
    typing: boolean;
    /** Whether something's drawn over the review, as the overview on a phone. */
    covered: boolean;
}

/** What of the buffer is in view, in its own places. */
interface Measured {
    from: number;
    to: number;
}

/** Tell the host of each of `due`, its mark moved; what wasn't kept is due again. */
function told(due: readonly Due[], dwelling: Dwelling): void {
    for (const each of due) {
        const { repository, module, key, up_to, through } = each.moves;
        void asked({ kind: "review-mark", repository, module, marks: [{ key, up_to: up_to ?? null, through: through ?? null, forward: true, seen: true }] })
            .then((kept) => {
                if (!kept) {
                    dwelling.failed(each);
                }
            })
            .catch(() => dwelling.failed(each));
    }
}

/** What's done with what's on screen: `left` says it's about to be gone from the screen, as another buffer takes its place. */
export interface Seen {
    left: () => void;
}

/** Follow what's on screen of what's read by being seen, and tell the host how far each mark moves as what's seen leaves the screen, or the tab goes. */
export function useSeeing(given: Seeing): Seen {
    const now = useRef(given);
    now.current = given;
    const dwelling = useRef(new Dwelling());
    const measured = useRef<Measured | null>(null);
    const touched = useRef<number | null>(null);
    const flushed = useRef(0);

    const viewing = (): Viewing | null => {
        const view = now.current.following.view;
        const seen = measured.current;
        if (view === null || seen === null) {
            return null;
        }
        const { toLaid, fromLaid } = now.current;
        const folded = foldedRanges(view.state);
        return {
            from: toLaid(seen.from),
            to: toLaid(seen.to),
            closedAt: (at) => {
                const place = fromLaid(at);
                let found: number | null = null;
                folded.between(place, place, (from, to) => {
                    if (from < place && place <= to) {
                        found = toLaid(from);
                        return false;
                    }
                    return undefined;
                });
                return found;
            },
        };
    };

    // They're there as long as they touched the page lately: a note's arrival on a page left open reads nothing.
    useEffect(() => {
        const noted = () => {
            touched.current = performance.now();
        };
        const events = ["keydown", "pointerdown", "pointermove", "wheel", "touchstart", "touchmove"];
        events.forEach((each) => window.addEventListener(each, noted, { passive: true, capture: true }));
        return () => events.forEach((each) => window.removeEventListener(each, noted, { capture: true }));
    }, []);

    // What's in view, in CodeMirror's own measuring, once a frame at most, under the stack.
    useEffect(() => {
        const { following } = now.current;
        const measure = () => {
            following.view?.requestMeasure({
                key: "lup-seeing",
                read: (read): Measured => {
                    const scroller = read.scrollDOM.getBoundingClientRect();
                    const top = Math.max(scroller.top - read.documentTop, 0);
                    const first = read.lineBlockAtHeight(top).from;
                    return {
                        from: read.lineBlockAtHeight(top + now.current.over(first)).from,
                        to: read.lineBlockAtHeight(Math.max(top + read.scrollDOM.clientHeight - 1, 0)).to,
                    };
                },
                write: (seen: Measured) => {
                    measured.current = seen;
                },
            });
        };
        measure();
        return following.listen(measure);
    }, []);

    // Added up a few times a second while anything's to be seen, each mark that may move told the host now and then.
    const any = given.sights.length > 0;
    useEffect(() => {
        if (!any) {
            return undefined;
        }
        const tick = () => {
            const at = performance.now();
            const { sights, typing, covered } = now.current;
            const view = viewing();
            const there = document.visibilityState === "visible" && document.hasFocus() && !typing && !covered && touched.current !== null && at - touched.current < AWAY;
            dwelling.current.advance(at, sights, view, there);
            if (at - flushed.current >= EVERY) {
                flushed.current = at;
                told(dwelling.current.due(sights, view, false), dwelling.current);
            }
        };
        const every = setInterval(tick, TICK);
        return () => clearInterval(every);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [any]);

    // As the tab goes, what's been seen is read, whatever's still on screen: they've moved on.
    useEffect(() => {
        const leaving = () => {
            const { sights } = now.current;
            told(dwelling.current.due(sights, viewing(), true), dwelling.current);
        };
        const hidden = () => {
            if (document.visibilityState === "hidden") {
                leaving();
            }
        };
        document.addEventListener("visibilitychange", hidden);
        window.addEventListener("pagehide", leaving);
        return () => {
            document.removeEventListener("visibilitychange", hidden);
            window.removeEventListener("pagehide", leaving);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // What's no longer to be seen, read since, is forgotten.
    useEffect(() => {
        dwelling.current.settled(given.sights);
    }, [given.sights]);

    return {
        // As what's seen leaves the screen by the buffer going, whatever's still in view of it, while the buffer's still there to say so.
        left: () => told(dwelling.current.due(now.current.sights, viewing(), true), dwelling.current),
    };
}
