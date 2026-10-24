// What follows the review's view (`docs/dashboard.md`, *The review*): the header
// stack and the overview are told each time the view scrolls, its geometry or
// its folds change, or the text is laid out again, and each measures what it
// needs in CodeMirror's own measuring, once a frame at most, so following the
// view costs a few lookups a frame, never a laying out of the review.
import { StateEffect } from "@codemirror/state";
import { EditorView } from "@codemirror/view";

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
