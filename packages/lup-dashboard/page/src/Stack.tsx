// The header stack over the review, a layout trial (`stack.ts`, `trials.ts`):
// the headers of the scopes the top of the view is inside, pinned, each drawn as
// the buffer draws its line, a click on one going to it; the row of an agent's
// drawers under its banner where it's pinned too, a click on a label pulling the
// drawer out or putting it back. Measured in CodeMirror's measuring as the view
// moves (`follow.ts`), and drawn again only where what it shows changed.
import { EditorView } from "@codemirror/view";
import { useEffect, useRef, useState } from "react";

import type { Following } from "./follow";
import { measured } from "./timing";
import type { RowLabel } from "./review";
import { narrowSlot, pinned, type Sticky } from "./stack";

interface Props {
    following: Following;
    roots: Sticky[];
    text: string;
    /** The classes each header's line is drawn with in the buffer. */
    classesOf: (sticky: Sticky) => string;
    /** The labels of the row pinned under a group's banner, where one is. */
    labelsOf: (sticky: Sticky) => RowLabel[];
    /** The letter of the fold each header heads, in the margin's column for its depth, as the buffer's margin marks it; none for a banner. */
    markOf: (sticky: Sticky) => Mark | null;
    narrow: boolean;
    jump: (position: number) => void;
    pull: (label: RowLabel) => void;
}

/** A fold's letter beside a header pinned: its kind, its letter, and how deep it is among the margin's columns. */
export interface Mark {
    kind: string;
    letter: string;
    depth: number;
}

/** One line of the stack as drawn: its text, its classes, how far down it is, what a click on it goes to, and its fold's letter. */
interface Drawn {
    key: string;
    text: string;
    classes: string;
    offset: number;
    at: number;
    labels: RowLabel[] | null;
    mark: Mark | null;
}

interface Shown {
    lines: Drawn[];
    /** Where the buffer's text starts, past its margin, and how wide its scrollbar is. */
    left: number;
    right: number;
    height: number;
}

const NONE: Shown = { lines: [], left: 0, right: 0, height: 0 };

export function Stack({ following, roots, text, classesOf, labelsOf, markOf, narrow, jump, pull }: Props) {
    const [shown, setShown] = useState<Shown>(NONE);
    // What's read in measuring is what's laid out now, whenever it's measured.
    const now = useRef({ roots, text, classesOf, labelsOf, markOf, narrow });
    now.current = { roots, text, classesOf, labelsOf, markOf, narrow };
    useEffect(() => {
        const measure = () => {
            const view = following.view;
            if (view === null) {
                return;
            }
            view.requestMeasure({
                key: "lup-stack",
                read: (read: EditorView): Shown => {
                    const began = performance.now();
                    const { roots, text, classesOf, labelsOf, markOf, narrow } = now.current;
                    const scroller = read.scrollDOM.getBoundingClientRect();
                    const lineHeight = read.defaultLineHeight;
                    const geometry = {
                        top: scroller.top - read.documentTop,
                        lineHeight,
                        block: (position: number) => read.lineBlockAt(Math.min(position, read.state.doc.length)),
                        at: (height: number) => read.lineBlockAtHeight(height).from,
                    };
                    const found = pinned(roots, geometry, narrow ? narrowSlot : undefined);
                    const lines = found.flatMap(({ sticky, offset }): Drawn[] => {
                        const header: Drawn = {
                            key: `${sticky.kind} ${sticky.header.from}`,
                            text: text.slice(sticky.header.from, sticky.header.to),
                            classes: classesOf(sticky),
                            offset,
                            at: sticky.header.from,
                            labels: null,
                            mark: markOf(sticky),
                        };
                        if (sticky.under === null) {
                            return [header];
                        }
                        const under: Drawn = {
                            key: `row ${sticky.under.from}`,
                            text: text.slice(sticky.under.from, sticky.under.to),
                            classes: "drawer-row",
                            offset: offset + lineHeight,
                            at: sticky.under.from,
                            labels: labelsOf(sticky),
                            mark: null,
                        };
                        return [header, under];
                    });
                    const bottom = lines.reduce((most, each) => Math.max(most, each.offset + lineHeight), 0);
                    // What following the view costs, for the trials' report: `performance.getEntriesByName("lup-stack")`.
                    measured("lup-stack", began);
                    return {
                        lines,
                        left: read.contentDOM.getBoundingClientRect().left - scroller.left,
                        right: read.scrollDOM.offsetWidth - read.scrollDOM.clientWidth,
                        height: Math.max(bottom, 0),
                    };
                },
                write: (measured: Shown) => setShown((before) => (sameShown(before, measured) ? before : measured)),
            });
        };
        measure();
        return following.listen(measure);
    }, [following, roots, text, narrow]);
    if (shown.lines.length === 0) {
        return null;
    }
    return (
        <div
            className="buffer stack"
            style={{ height: shown.height, right: shown.right }}
            aria-label="Where the top of the view is"
            // The wheel over the stack scrolls the buffer under it.
            onWheel={(event) => following.view?.scrollDOM.scrollBy({ top: event.deltaY, left: event.deltaX })}
        >
            <div className="cm-editor">
                <div className="stack-margin" style={{ width: shown.left }}>
                    {shown.lines.flatMap((line) =>
                        line.mark === null
                            ? []
                            : [
                                  <span key={line.key} className={`fold-mark fold-${line.mark.kind}`} style={{ "--depth": line.mark.depth, top: line.offset + 1 } as React.CSSProperties}>
                                      {line.mark.letter}
                                  </span>,
                              ],
                    )}
                </div>
                <div className="cm-content" style={{ marginLeft: shown.left }}>
                    {shown.lines.map((line, at) => (
                        <div
                            key={line.key}
                            className={`cm-line stack-line ${line.classes}`}
                            // One pushed up goes under the one over it.
                            style={{ top: line.offset, zIndex: shown.lines.length - at }}
                            onClick={line.labels === null ? () => jump(line.at) : undefined}
                            title={line.labels === null ? "go to it" : undefined}
                        >
                            {line.labels === null ? line.text : labelled(line, pull)}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

/** Return a row's line with each of its labels a control pulling its drawer out or putting it back. */
export function labelled(line: { text: string; at: number; labels: RowLabel[] | null }, pull: (label: RowLabel) => void) {
    const labels = line.labels ?? [];
    const parts: (string | React.ReactElement)[] = [];
    let at = line.at;
    for (const label of labels) {
        if (label.from > at) {
            parts.push(line.text.slice(at - line.at, label.from - line.at));
        }
        parts.push(
            <span
                key={label.of}
                className={`row-label row-${label.kind}${label.pulled ? " is-pulled" : ""}${label.waiting ? " is-waiting" : ""}`}
                onClick={(event) => {
                    event.stopPropagation();
                    pull(label);
                }}
                title={label.pulled ? "put it back in the row" : "pull it out below the row"}
            >
                {line.text.slice(label.from - line.at, label.to - line.at)}
            </span>,
        );
        at = label.to;
    }
    parts.push(line.text.slice(at - line.at));
    return parts;
}

function sameShown(a: Shown, b: Shown): boolean {
    if (a.left !== b.left || a.right !== b.right || a.height !== b.height || a.lines.length !== b.lines.length) {
        return false;
    }
    return a.lines.every((each, at) => {
        const other = b.lines[at];
        return (
            other !== undefined &&
            other.key === each.key &&
            other.text === each.text &&
            other.classes === each.classes &&
            other.offset === each.offset &&
            JSON.stringify(other.mark) === JSON.stringify(each.mark) &&
            JSON.stringify(other.labels) === JSON.stringify(each.labels)
        );
    });
}
