// What the layout trials draw in the review's margin, right of the fold
// letters, line for line with the text (`trials.ts`): the outline there, each
// scope (an agent's group, an item, a drawer, a file) a bar its full height in
// its kind's colour, with a short label where it starts, marked by how it stands
// and what the draft does with it, a click on it going there; or, where groups
// are framed without that outline, a rail down each group, a subagent's set in
// beside its parent's. CodeMirror gutters, whose rows are as tall as the lines
// beside them, so the outline's heights are the text's by construction.
import { StateEffect, type Extension } from "@codemirror/state";
import { GutterMarker, gutter, type BlockInfo, type EditorView } from "@codemirror/view";

import { holding, type Sticky } from "./stack";
import { measured } from "./timing";

/** One scope's label in the margin: what it says, its kind's class, and the marks before and after it. */
export interface Labelled {
    text: string;
    kind: string;
    /** How it stands, a glyph in its own colour before the label: waiting on the operator, news, parked, a file to review. */
    state: { glyph: string; mark: string } | null;
    /** What the draft does with it on the next Ctrl+Enter, a glyph in the draft's colour after it. */
    draft: string | null;
    /** Whether it's new to the operator since they last sent. */
    fresh: boolean;
}

/** What the outline in the margin reads, as the review last laid out: the scopes, and each one's label. */
export interface Outlined {
    roots: readonly Sticky[];
    label: (sticky: Sticky) => Labelled;
    /** Go to a scope's header, as a click on its label does. */
    jump: (position: number) => void;
}

/** Marks a transaction after which the margin's outline or rails are drawn again, what they say having changed with nothing laid out anew. */
export const redrawn = StateEffect.define<null>();

/** One scope's bar beside a line: how deep it is, its kind, whether the line is its first or its last, and its label where it's its first. */
interface Bar {
    depth: number;
    kind: string;
    first: boolean;
    last: boolean;
    at: number;
    label: Labelled | null;
}

class Bars extends GutterMarker {
    constructor(readonly bars: Bar[]) {
        super();
    }

    override eq(other: Bars): boolean {
        return JSON.stringify(this.bars) === JSON.stringify(other.bars);
    }

    override toDOM(): Node {
        const cell = document.createElement("span");
        cell.className = "rail-cell";
        for (const bar of this.bars) {
            const drawn = document.createElement("span");
            drawn.className = ["rail", `rail-${bar.kind}`, bar.first ? "is-first" : "", bar.last ? "is-last" : ""].join(" ");
            drawn.style.setProperty("--depth", `${bar.depth}`);
            cell.append(drawn);
            if (bar.label !== null) {
                const label = document.createElement("span");
                label.className = `rail-label rail-${bar.kind}`;
                label.style.setProperty("--depth", `${bar.depth}`);
                label.dataset["at"] = `${bar.at}`;
                if (bar.label.state !== null) {
                    const state = document.createElement("span");
                    state.className = `rail-state mark-${bar.label.state.mark}`;
                    state.textContent = bar.label.state.glyph;
                    label.append(state);
                }
                label.append(bar.label.text);
                if (bar.label.fresh) {
                    const fresh = document.createElement("span");
                    fresh.className = "rail-fresh";
                    fresh.textContent = "*";
                    label.append(fresh);
                }
                if (bar.label.draft !== null) {
                    const draft = document.createElement("span");
                    draft.className = "rail-draft";
                    draft.textContent = bar.label.draft;
                    label.append(draft);
                }
                label.title = `${bar.label.text}: go to it`;
                cell.append(label);
            }
        }
        return cell;
    }
}

/** Return the scopes holding the line `line` is, outermost first, each with how deep it is. */
function chainOf(roots: readonly Sticky[], line: BlockInfo): { sticky: Sticky; depth: number }[] {
    const chain: { sticky: Sticky; depth: number }[] = [];
    let level = roots;
    for (let depth = 0; ; depth += 1) {
        const inside = holding(level, line.from);
        if (inside === undefined) {
            return chain;
        }
        chain.push({ sticky: inside, depth });
        level = inside.children;
    }
}

/** Return the bars beside `line`: each scope holding it, its label where the line is its header's. */
function barsOf(outlined: Outlined, line: BlockInfo, labels: boolean): Bars | null {
    const bars = chainOf(outlined.roots, line).map(({ sticky, depth }): Bar => {
        const first = sticky.header.from >= line.from && sticky.header.from <= line.to;
        return {
            depth,
            kind: outlined.label(sticky).kind,
            first,
            last: line.to >= sticky.to,
            at: sticky.header.from,
            label: first && labels ? outlined.label(sticky) : null,
        };
    });
    return bars.length === 0 ? null : new Bars(bars);
}

/**
 * Return the outline in the margin, read from `outlined` as it stands when each line is drawn: each scope a bar its
 * full height, labelled where it starts, a click on a label going to the scope; `labels` where there's room for them,
 * as there isn't on a phone.
 */
export function outlineMargin(outlined: () => Outlined, labels: boolean): Extension {
    return gutter({
        class: labels ? "outline-margin" : "outline-margin is-bare",
        lineMarker: (_, line) => {
            const began = performance.now();
            const bars = barsOf(outlined(), line, labels);
            measured("lup-margin", began);
            return bars;
        },
        lineMarkerChange: (update) => update.docChanged || update.transactions.some((each) => each.effects.some((effect) => effect.is(redrawn))),
        initialSpacer: () => new Bars([]),
        domEventHandlers: {
            mousedown: (_, __, event) => {
                const at = event.target instanceof HTMLElement ? event.target.closest<HTMLElement>("[data-at]")?.dataset["at"] : undefined;
                if (at === undefined) {
                    return false;
                }
                event.preventDefault();
                outlined().jump(Number(at));
                return true;
            },
        },
    });
}

/** One group's rail: where its banner and its end are, and how deep it's nested. */
export interface Railed {
    from: number;
    to: number;
    depth: number;
}

/** Return a rail down each group of `groups`, as they stand when each line is drawn, a subagent's beside its parent's, a corner at its banner and at its end. */
export function groupRails(groups: () => readonly Railed[]): Extension {
    return gutter({
        class: "group-rails",
        lineMarker: (_, line) => {
            const bars = groups().flatMap((group): Bar[] =>
                line.to < group.from || line.from > group.to
                    ? []
                    : [{ depth: group.depth, kind: "group", first: line.from <= group.from, last: line.to >= group.to, at: group.from, label: null }],
            );
            return bars.length === 0 ? null : new Bars(bars);
        },
        lineMarkerChange: (update) => update.docChanged || update.transactions.some((each) => each.effects.some((effect) => effect.is(redrawn))),
        initialSpacer: () => new Bars([{ depth: 2, kind: "group", first: false, last: false, at: 0, label: null }]),
    });
}

export type { EditorView };
