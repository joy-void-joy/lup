// Keys as the operator's keyboard sends them, for the page's promises: in Normal and Visual mode each goes to vim; in
// Insert mode a character, Enter or Backspace edits the text as the browser's input does, which vim leaves to the
// editor; an ex command (`:w`) runs as vim's command line runs it once Enter is pressed.

import { EditorSelection } from "@codemirror/state";
import { Vim, getCM } from "@replit/codemirror-vim";

import type { Shell } from "../shell/shell";

/**
 * Send `keys`, each as vim names it, or an ex command after its colon, to `shell`'s editor, as the keyboard does: each
 * a key event of its own, what one leaves for once it's handled (`queueMicrotask`) run before the next.
 */
export async function press(shell: Shell, keys: readonly string[]): Promise<void> {
    const cm = getCM(shell.view);
    if (cm === null) {
        throw new Error("the shell's editor has no vim mode");
    }
    for (const key of keys) {
        const inserting = (cm.state.vim as { insertMode?: boolean } | null)?.insertMode === true;
        if (key.startsWith(":") && key.length > 1) {
            Vim.handleEx(cm as Parameters<typeof Vim.handleEx>[0], key.slice(1));
        } else if (inserting && (key.length === 1 || key === "<CR>")) {
            typed(shell, key === "<CR>" ? "\n" : key);
        } else if (inserting && key === "<BS>") {
            const { from, to } = shell.view.state.selection.main;
            if (from === to && from > 0) {
                shell.view.dispatch({ changes: { from: from - 1, to }, selection: EditorSelection.cursor(from - 1), userEvent: "delete.backward" });
            }
        } else {
            Vim.handleKey(cm, key, "user");
        }
        await settled();
    }
}

/** Let what a key left for once it's handled run, as the browser does before the next key event. */
async function settled(): Promise<void> {
    await new Promise<void>((resolve) => {
        queueMicrotask(resolve);
    });
}

/** Type `text` at the cursor, as the browser's input does in Insert mode. */
function typed(shell: Shell, text: string): void {
    const { from, to } = shell.view.state.selection.main;
    shell.view.dispatch({ changes: { from, to, insert: text }, selection: EditorSelection.cursor(from + text.length), userEvent: "input.type" });
}
