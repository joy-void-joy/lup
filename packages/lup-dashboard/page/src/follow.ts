// What follows the review's view, for the layout trials (`trials.ts`): the header
// stack and the outline are told each time the view scrolls, its geometry or
// its folds change, or the text is laid out again, and each measures what it
// needs in CodeMirror's own measuring, once a frame at most, so following the
// view costs a few lookups a frame, never a laying out of the review.
import { StateEffect } from "@codemirror/state";
import { EditorView } from "@codemirror/view";

/** Where the view is, in the text: the first and the last line at least partly in it, the cursor, and the view's top in pixels from the document's. */
export interface Seen {
    from: number;
    to: number;
    head: number;
    top: number;
}

/** Those told as the view moves, and the view they follow. */
export class Following {
    private readonly told = new Set<() => void>();
    private attached: EditorView | null = null;
    private readonly scrolled = () => this.tell();

    /** Follow `view`, once: its scroller's scrolling, and its updates that move what's seen. */
    attach(view: EditorView): void {
        if (this.attached === view) {
            return;
        }
        this.attached = view;
        view.scrollDOM.addEventListener("scroll", this.scrolled, { passive: true });
        view.dispatch({
            effects: StateEffect.appendConfig.of(
                EditorView.updateListener.of((update) => {
                    if (update.docChanged || update.geometryChanged || update.heightChanged || update.viewportChanged || update.selectionSet) {
                        this.tell();
                    }
                }),
            ),
        });
    }

    get view(): EditorView | null {
        return this.attached;
    }

    /** Be told each time what's seen may have changed; returns what stops it. */
    listen(listener: () => void): () => void {
        this.told.add(listener);
        return () => this.told.delete(listener);
    }

    tell(): void {
        for (const each of this.told) {
            each();
        }
    }
}

/** Return where `view` is: its top in pixels from the document's, the lines at its top and bottom, and the cursor; read in a measuring phase. */
export function seenIn(view: EditorView): Seen {
    const scroller = view.scrollDOM.getBoundingClientRect();
    const top = scroller.top - view.documentTop;
    const from = view.lineBlockAtHeight(Math.max(top, 0)).from;
    const to = view.lineBlockAtHeight(Math.max(top + view.scrollDOM.clientHeight - 1, 0)).to;
    return { from, to, head: view.state.selection.main.head, top };
}
