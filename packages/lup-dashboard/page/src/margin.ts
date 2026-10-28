// The review's folds' placeholders: a folded fold's, at its summary line's end,
// drawn in its kind's colour, saying how many lines a group, a file, a body or
// an item hides. The margin beside the folds, their letters and the review's
// structure, is `rails.ts` (`editor.ts`; `docs/dashboard.md`, *The review*).
import { codeFolding } from "@codemirror/language";
import type { EditorState, Extension } from "@codemirror/state";
import type { ViewUpdate } from "@codemirror/view";

import type { Folding } from "./comments";
import { kindOf } from "./looks";

/** Where the margin reads what folds and when to draw again: the view's folds, and whether an update laid them out anew. */
export interface Margined {
    folds: (state: EditorState) => readonly Folding[];
    redrawn: (update: ViewUpdate) => boolean;
}

/**
 * Return CodeMirror's folding, each placeholder drawn by the kind of the fold it stands for, of those `margined` says:
 * `⋯`, and how many lines it hides where its kind says so (`Kind.counts`), as a file's, a body's or an item's, whose
 * summary line doesn't say what it hides, but for one whose content isn't read yet; a fold of no kind's as `…`.
 */
export function placeheld(margined: Margined): Extension {
    return codeFolding({
        preparePlaceholder: (state, range) => {
            const fold = margined.folds(state).find((each) => each.from === range.from && each.to === range.to);
            if (fold?.kind === undefined) {
                return "";
            }
            const hidden = fold.unread === true ? null : state.doc.lineAt(range.to).number - state.doc.lineAt(range.from).number;
            return JSON.stringify({ kind: fold.kind, hidden });
        },
        placeholderDOM: (_, onclick, prepared: string) => {
            const shown = document.createElement("span");
            shown.className = "cm-foldPlaceholder";
            shown.title = "unfold";
            shown.onclick = onclick;
            if (prepared === "") {
                shown.textContent = "…";
                return shown;
            }
            const { kind, hidden } = JSON.parse(prepared) as { kind: string; hidden: number | null };
            shown.classList.add("fold-placeholder", `fold-${kind}`);
            shown.textContent = kindOf(kind)?.counts === true && hidden !== null ? `⋯ ${hidden} ${hidden === 1 ? "line" : "lines"}` : "⋯";
            return shown;
        },
    });
}
