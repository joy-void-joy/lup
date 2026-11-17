// The keymaps' engines, and the shell's named commands they reach.
//
// A keymap is a module's data: the engine it runs, and its bindings from keys to the shell's commands. The engines
// are the page's own: vim's is CodeMirror's vim mode, the shell's commands threaded into it as its actions, a key's
// `{kind}` the fold kind's letter typed after it. A command is named once here and does the same wherever a binding
// reaches it.

import { Vim, getCM } from "@replit/codemirror-vim";

import { every, foldKind } from "../document/tree";
import { shells, type Shell } from "./shell";

/** A mode a binding works in. */
export type Mode = "normal" | "visual" | "insert";

/** A key, or a sequence of them as vim writes them, bound to one of the shell's commands. */
export interface Bind {
    readonly keys: string;
    readonly command: string;
    readonly modes: readonly Mode[];
}

/** What a command is given: the fold kind typed after its key, where its key takes one. */
interface Given {
    readonly kind: string | null;
}

/** The shell's named commands, each doing the same wherever a binding reaches it. */
export const commands: Readonly<Record<string, (shell: Shell, given: Given) => void>> = {
    /** Open the innermost fold the cursor is in, or close it, as `za` does. */
    "fold-toggle": (shell) => {
        const node = shell.foldAt();
        if (node !== null) {
            shell.toggle(node.key);
        }
    },
    /** Open the innermost fold the cursor is in. */
    "fold-open": (shell) => {
        const node = shell.foldAt();
        if (node !== null) {
            shell.toggle(node.key, true);
        }
    },
    /** Close the innermost fold the cursor is in. */
    "fold-close": (shell) => {
        const node = shell.foldAt();
        if (node !== null) {
            shell.toggle(node.key, false);
        }
    },
    /** Open the nearest fold of the kind typed after the key, or close it: `zf` and its letter. */
    "fold-nearest": (shell, given) => {
        const kind = given.kind === null ? null : shell.kinds.byLetter(given.kind);
        const node = kind === null ? null : shell.foldAt(kind.name);
        if (node !== null) {
            shell.toggle(node.key);
        }
    },
    /** Open every fold, as `zR` does. */
    "open-all": (shell) => {
        shell.level(true);
    },
    /** Close every fold, as `zM` does. */
    "close-all": (shell) => {
        shell.level(false);
    },
    /** Open the next level of folds, as `zr` does: every fold whose kind's level is the shallowest still closed. */
    "open-more": (shell) => {
        const closed = levels(shell, false);
        if (closed.length > 0) {
            shell.level(true, Math.min(...closed));
        }
    },
    /** Close the deepest level of folds open, as `zm` does. */
    "close-more": (shell) => {
        const open = levels(shell, true);
        if (open.length > 0) {
            shell.level(false, Math.max(...open));
        }
    },
};

/** Return the levels of the folds open, or closed, in the shell's document. */
function levels(shell: Shell, open: boolean): number[] {
    return every(shell.document.root).flatMap((node) => {
        const kind = foldKind(node);
        const level = kind === null ? undefined : shell.kinds.folds.get(kind)?.level;
        return level !== undefined && shell.isOpen(node) === open ? [level] : [];
    });
}

/** vim's bindings of the shell's commands: what the `vim` keymap module binds, until its module sends them. */
export const vimBindings: readonly Bind[] = [
    { keys: "za", command: "fold-toggle", modes: ["normal"] },
    { keys: "zo", command: "fold-open", modes: ["normal"] },
    { keys: "zc", command: "fold-close", modes: ["normal"] },
    { keys: "zf{kind}", command: "fold-nearest", modes: ["normal"] },
    { keys: "zR", command: "open-all", modes: ["normal"] },
    { keys: "zM", command: "close-all", modes: ["normal"] },
    { keys: "zr", command: "open-more", modes: ["normal"] },
    { keys: "zm", command: "close-more", modes: ["normal"] },
];

/**
 * Thread `bindings` into vim's mode: each command an action of vim's, reached by its keys in its modes.
 *
 * vim's mappings are the page's, not one editor's, so a command finds the shell it runs in by its editor.
 */
export function bindVim(bindings: readonly Bind[]): void {
    for (const bind of bindings) {
        const run = commands[bind.command];
        if (run === undefined) {
            throw new Error(`a binding names \`${bind.command}\`, which isn't one of the shell's commands`);
        }
        const action = `lup:${bind.command}`;
        Vim.defineAction(action, (cm, args) => {
            const shell = (cm.cm6 as { state: { facet: (facet: typeof shells) => Shell | null } }).state.facet(shells);
            if (shell !== null) {
                run(shell, { kind: args.selectedCharacter ?? null });
            }
        });
        const keys = bind.keys.replace("{kind}", "<character>");
        for (const mode of bind.modes) {
            Vim.mapCommand(keys, "action", action, {}, { context: mode });
        }
    }
}

/** Say whether vim is in insert mode in `shell`'s editor. */
export function inserting(shell: Shell): boolean {
    const state = getCM(shell.view)?.state.vim as { insertMode?: boolean } | undefined;
    return state?.insertMode === true;
}
