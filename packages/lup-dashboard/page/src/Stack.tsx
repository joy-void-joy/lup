// The header stack over the review (`stack.ts`; `docs/dashboard.md`, *The
// review*): the headers of the scopes the top of the view is inside, pinned
// under the cursor's line, each drawn as the buffer draws its line, with its
// fold's letter and its label in the margin as the margin has them, and what
// settles it at its end; a click on one goes to it. Measured in CodeMirror's
// measuring as the view moves (`follow.ts`), and drawn again only where what
// it shows changed.
import { EditorView } from "@codemirror/view";
import { useEffect, useRef, useState, type CSSProperties } from "react";

import type { Following } from "./follow";
import type { Labelled } from "./rails";
import { narrowSlot, pinned, type Sticky } from "./stack";
import { measured } from "./timing";

interface Props {
    following: Following;
    roots: Sticky[];
    text: string;
    /** The classes each header's line is drawn with in the buffer. */
    classesOf: (sticky: Sticky) => string;
    /** The letter of the fold each header heads, in the margin's column for its depth, and its label, as the margin has them. */
    markOf: (sticky: Sticky) => Mark | null;
    /** What settles what a header heads, said at its end: the key approving a change's file, marking a drawer's reviewed. */
    hintOf: (sticky: Sticky) => string | null;
    narrow: boolean;
    jump: (position: number) => void;
}

/** A fold's letter beside a header pinned: its kind, its letter, how deep it is among the margin's columns, and its label. */
export interface Mark {
    kind: string;
    letter: string;
    depth: number;
    label: Labelled | null;
}

/** One line of the stack as drawn: its text, its classes, how far down it is, what a click on it goes to, its fold's letter, and what settles it. */
interface Drawn {
    key: string;
    text: string;
    classes: string;
    offset: number;
    at: number;
    mark: Mark | null;
    hint: string | null;
}

interface Shown {
    lines: Drawn[];
    /** Where the buffer's text starts, past its margin, and how wide its scrollbar is. */
    left: number;
    right: number;
    height: number;
}

const NONE: Shown = { lines: [], left: 0, right: 0, height: 0 };

export function Stack({ following, roots, text, classesOf, markOf, hintOf, narrow, jump }: Props) {
    const [shown, setShown] = useState<Shown>(NONE);
    // What's read in measuring is what's laid out now, whenever it's measured.
    const now = useRef({ roots, text, classesOf, markOf, hintOf, narrow });
    now.current = { roots, text, classesOf, markOf, hintOf, narrow };
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
                    const { roots, text, classesOf, markOf, hintOf, narrow } = now.current;
                    const scroller = read.scrollDOM.getBoundingClientRect();
                    const lineHeight = read.defaultLineHeight;
                    const geometry = {
                        top: scroller.top - read.documentTop,
                        lineHeight,
                        block: (position: number) => read.lineBlockAt(Math.min(position, read.state.doc.length)),
                        at: (height: number) => read.lineBlockAtHeight(height).from,
                    };
                    const lines = pinned(roots, geometry, narrow ? narrowSlot : undefined).map(
                        ({ sticky, offset }): Drawn => ({
                            key: `${sticky.kind} ${sticky.header.from}`,
                            text: text.slice(sticky.header.from, sticky.header.to),
                            classes: classesOf(sticky),
                            offset,
                            at: sticky.header.from,
                            mark: markOf(sticky),
                            hint: hintOf(sticky),
                        }),
                    );
                    const bottom = lines.reduce((most, each) => Math.max(most, each.offset + lineHeight), 0);
                    measured("lup-stack", began);
                    return {
                        lines,
                        left: read.contentDOM.getBoundingClientRect().left - scroller.left,
                        right: read.scrollDOM.offsetWidth - read.scrollDOM.clientWidth,
                        height: Math.max(bottom, 0),
                    };
                },
                write: (measured: Shown) => setShown((before) => (JSON.stringify(before) === JSON.stringify(measured) ? before : measured)),
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
                    {shown.lines.flatMap((line, at) =>
                        line.mark === null
                            ? []
                            : [
                                  <span
                                      key={line.key}
                                      className="stack-mark"
                                      style={{ "--depth": line.mark.depth, top: line.offset, zIndex: shown.lines.length - at } as CSSProperties}
                                      onClick={() => jump(line.at)}
                                  >
                                      <span className={`fold-mark fold-${line.mark.kind}`} style={{ "--depth": line.mark.depth } as CSSProperties}>
                                          {line.mark.letter}
                                      </span>
                                      {line.mark.label === null ? null : (
                                          <span className={`rail-label fold-${line.mark.kind}`} style={{ "--depth": line.mark.depth } as CSSProperties}>
                                              {line.mark.label.state === null ? null : <span className={`rail-state mark-${line.mark.label.state.mark}`}>{line.mark.label.state.glyph}</span>}
                                              {line.mark.label.text}
                                              {line.mark.label.fresh ? <span className="rail-fresh"> new</span> : null}
                                              {line.mark.label.draft === null ? null : <span className="rail-draft"> {line.mark.label.draft}</span>}
                                          </span>
                                      )}
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
                            onClick={() => jump(line.at)}
                            title="go to it"
                        >
                            <span className="stack-text">{line.text}</span>
                            {line.hint === null ? null : <span className="stack-hint">{line.hint}</span>}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
