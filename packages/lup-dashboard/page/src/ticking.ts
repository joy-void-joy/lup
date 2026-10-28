// What ticks in the review, or is drawn rather than read (`docs/dashboard.md`, *The review*, *The banner*): how long an
// item has waited, what an agent is doing and for how long, a span of a view's saying the time since a moment
// (`Ticking`), and a gauge, as a context's ring (`Gauge`). Each is drawn at its place on its block's line, said again as
// the time passes, repainted without touching the buffer's text, so neither the clock nor a hook lays the review out:
// the buffer holds what's read, and these are drawn beside it, never searched, yanked or quoted. Each layout says where
// each goes and how it's said (`ticked`); the clock says it again every few seconds.
import { StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, WidgetType, type DecorationSet } from "@codemirror/view";

/** One thing drawn on a line: where, how it's said as of a time, and the look it's drawn in, a class of the review's. */
export interface Tick {
    at: number;
    said: (now: Date) => string;
    look: string;
}

/** Says where each thing drawn goes, as a layout lays the review out, or as what's drawn changes, as an agent's activity. */
export const ticked = StateEffect.define<readonly Tick[]>();

/** Says the time, which each thing drawn is said as of. */
const struck = StateEffect.define<number>();

/** How often the clock says the time: a duration is told to the second, and nothing needs it sooner. */
const EVERY = 5000;

/** What's drawn of one thing: its words, in its look. */
class Drawn extends WidgetType {
    constructor(
        readonly text: string,
        readonly look: string,
    ) {
        super();
    }

    override eq(other: Drawn): boolean {
        return other.text === this.text && other.look === this.look;
    }

    override toDOM(): HTMLElement {
        const span = document.createElement("span");
        span.className = `drawn ${this.look}`;
        span.textContent = this.text;
        return span;
    }

    override ignoreEvent(): boolean {
        return false;
    }
}

/** Return what's drawn of `ticks` as of `now`, each where it goes: a widget after the character before it. */
function drawn(ticks: readonly Tick[], now: number, length: number): DecorationSet {
    const at = new Date(now);
    return Decoration.set(
        ticks
            .filter((each) => each.at >= 0 && each.at <= length)
            .map((each) => Decoration.widget({ widget: new Drawn(each.said(at), each.look), side: 1 }).range(each.at)),
        true,
    );
}

/** The things drawn, where each goes, carried with the text between layouts, and the time they're said as of. */
export const ticking = StateField.define<{ ticks: readonly Tick[]; now: number; marks: DecorationSet }>({
    create: () => ({ ticks: [], now: Date.now(), marks: Decoration.none }),
    update: (value, transaction) => {
        let { ticks, now } = value;
        let changed = false;
        if (transaction.docChanged) {
            ticks = ticks.map((each) => ({ ...each, at: transaction.changes.mapPos(each.at, -1) }));
            changed = true;
        }
        for (const effect of transaction.effects) {
            if (effect.is(ticked)) {
                ticks = effect.value;
                changed = true;
            } else if (effect.is(struck)) {
                now = effect.value;
                changed = true;
            }
        }
        return changed ? { ticks, now, marks: drawn(ticks, now, transaction.state.doc.length) } : value;
    },
    provide: (field) => EditorView.decorations.from(field, (value) => value.marks),
});

/** The clock: says the time every few seconds, so what's drawn says it again, and nothing else is laid out. */
export const clock = ViewPlugin.fromClass(
    class {
        readonly timer: ReturnType<typeof setInterval>;

        constructor(readonly view: EditorView) {
            this.timer = setInterval(() => this.view.dispatch({ effects: struck.of(Date.now()) }), EVERY);
        }

        destroy() {
            clearInterval(this.timer);
        }
    },
);
