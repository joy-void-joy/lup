// The drawers pinned below, a layout trial (`trials.ts`, `drawers=sticky`): an
// agent's drawers stay footers at its group's end, and while the view is inside
// that group with its end below, they're pinned at the bottom of the view, as
// the stack pins headers at its top: side by side as labels, or a line each, as
// their summary lines say. As the group's end comes up into view, the pinned
// drawers ride on its first drawer's line until it shows whole, then give way to
// it. A click on one opens it at the group's end and goes there. Measured in
// CodeMirror's measuring as the view moves (`follow.ts`).
import { EditorView } from "@codemirror/view";
import { useEffect, useRef, useState, type MutableRefObject } from "react";

import { isFolded } from "./editor";
import type { Following } from "./follow";
import type { Drawer, Laid } from "./review";
import { measured } from "./timing";

interface Props {
    following: Following;
    laidOut: Laid;
    /** Side by side on one line, or a line each. */
    lines: boolean;
    /** Open a drawer at its group's end and go to it. */
    open: (drawer: Drawer) => void;
    /** Told how tall the drawers pinned below are, which a scroll to the cursor keeps clear. */
    tall: MutableRefObject<number>;
}

/** One drawer as pinned: its kind, what its summary line says, whether it's open, and whether it holds what waits on the operator. */
interface Pinned {
    of: string;
    kind: string;
    text: string;
    open: boolean;
    waiting: boolean;
}

interface Shown {
    drawers: Pinned[];
    /** Where the cursor is, and how far down the view its line ends, which the drawers pinned below never cover once it's moved. */
    head: number;
    cursor: number;
    /** How far down the view the pinned drawers start, riding on the group's end as it comes up. */
    top: number;
    left: number;
    right: number;
}

const NONE: Shown = { drawers: [], head: -1, cursor: 0, top: 0, left: 0, right: 0 };

/** Return where each group's own lines end, the last as deep or shallower than it ends it, its subagents' among them. */
function groupEnds(laidOut: Laid): number[] {
    return laidOut.groups.map((group, at) => {
        const next = laidOut.groups.findIndex((each, after) => after > at && each.depth <= group.depth);
        return next < 0 ? laidOut.text.length : (laidOut.groups[next]?.banner.from ?? laidOut.text.length) - 1;
    });
}

export function Footer({ following, laidOut, lines, open, tall }: Props) {
    const [shown, setShown] = useState<Shown>(NONE);
    // Where the cursor was at the last measure, and when it last moved: its line is kept clear of what's pinned below
    // for a moment after, as the scroll a search or a jump makes may come after it.
    const head = useRef({ at: -1, moved: 0 });
    const now = useRef({ laidOut, lines, ends: groupEnds(laidOut) });
    now.current = { laidOut, lines, ends: groupEnds(laidOut) };
    useEffect(() => {
        const measure = () => {
            const view = following.view;
            if (view === null) {
                return;
            }
            view.requestMeasure({
                key: "lup-footer",
                read: (read: EditorView): Shown => {
                    const began = performance.now();
                    const { laidOut, lines, ends } = now.current;
                    const scroller = read.scrollDOM.getBoundingClientRect();
                    const top = scroller.top - read.documentTop;
                    const height = read.scrollDOM.clientHeight;
                    const bottom = read.lineBlockAtHeight(Math.max(top + height - 1, 0)).from;
                    // The innermost group the view's bottom is in, but what's left for later, which has no drawers.
                    let at = -1;
                    laidOut.groups.forEach((group, index) => {
                        if (!group.later && group.banner.from <= bottom && bottom <= (ends[index] ?? 0)) {
                            at = index;
                        }
                    });
                    const group = laidOut.groups[at];
                    const first = group?.drawers[0];
                    if (group === undefined || first === undefined) {
                        return { ...NONE, head: read.state.selection.main.head };
                    }
                    const lineHeight = read.defaultLineHeight;
                    const tallness = (lines ? group.drawers.length : 1) * lineHeight;
                    // Where the group's first drawer is in the view: pinned at the bottom while it's below, riding on it
                    // as it comes up, gone once it shows whole above where they'd be pinned.
                    const real = read.lineBlockAt(first.header.from).top - top;
                    if (real < height - tallness) {
                        return { ...NONE, head: read.state.selection.main.head };
                    }
                    const drawers = group.drawers.map((drawer): Pinned => {
                        const own = drawer.folds.find((each) => each.kind === drawer.kind && each.name === "");
                        const text = laidOut.text.slice(drawer.header.from, drawer.header.to);
                        return {
                            of: drawer.of,
                            kind: drawer.kind,
                            text,
                            open: own !== undefined && !isFolded(read.state, own),
                            waiting: drawer.kind === "since" && / to review| flagged/.test(text),
                        };
                    });
                    measured("lup-footer", began);
                    const cursor = read.state.selection.main.head;
                    return {
                        drawers,
                        head: cursor,
                        cursor: read.lineBlockAt(cursor).bottom - top,
                        top: Math.min(real, height - tallness),
                        left: read.contentDOM.getBoundingClientRect().left - scroller.left,
                        right: read.scrollDOM.offsetWidth - read.scrollDOM.clientWidth,
                    };
                },
                write: (measured: Shown) => {
                    tall.current = measured.drawers.length === 0 ? 0 : Math.max(0, (following.view?.scrollDOM.clientHeight ?? 0) - measured.top);
                    // The cursor just moved under what's pinned, as a search or a jump puts it at the view's bottom: the
                    // view goes up so its line shows above them, as a scroll to it keeps clear of them from then on.
                    const now = performance.now();
                    if (measured.head !== head.current.at) {
                        head.current = { at: measured.head, moved: now };
                    }
                    if (now - head.current.moved < 600 && measured.drawers.length > 0 && measured.cursor > measured.top) {
                        following.view?.scrollDOM.scrollBy({ top: measured.cursor - measured.top });
                    }
                    setShown((before) => (JSON.stringify(before) === JSON.stringify(measured) ? before : measured));
                },
            });
        };
        measure();
        return following.listen(measure);
    }, [following, laidOut, lines, tall]);
    if (shown.drawers.length === 0) {
        return null;
    }
    const chosen = (of: string) => {
        const drawer = laidOut.drawers.find((each) => each.of === of);
        if (drawer !== undefined) {
            open(drawer);
        }
    };
    return (
        <div
            className={`buffer footer${lines ? " is-lines" : ""}`}
            style={{ top: shown.top, right: shown.right }}
            aria-label="The drawers of the group the view's bottom is in"
            onWheel={(event) => following.view?.scrollDOM.scrollBy({ top: event.deltaY, left: event.deltaX })}
        >
            <div className="cm-editor">
                <div className="cm-content" style={{ marginLeft: shown.left }}>
                    {lines ? (
                        shown.drawers.map((each) => (
                            <div key={each.of} className={`cm-line footer-line drawer-summary drawer-${each.kind}`} onClick={() => chosen(each.of)} title="open it at the group's end">
                                <span className="footer-fold">{each.open ? "▾" : "▸"}</span> {each.text}
                            </div>
                        ))
                    ) : (
                        <div className="cm-line footer-line drawer-row">
                            {shown.drawers.map((each) => (
                                <span
                                    key={each.of}
                                    className={`row-label row-${each.kind}${each.open ? " is-pulled" : ""}${each.waiting ? " is-waiting" : ""}`}
                                    onClick={() => chosen(each.of)}
                                    title="open it at the group's end"
                                >
                                    {each.open ? "▾" : "▸"} {each.text.replace(/ on \S+/, "")}
                                </span>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
