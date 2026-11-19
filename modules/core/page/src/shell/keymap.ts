// The keymaps' engines, and the shell's named commands they reach.
//
// A keymap is a module's data: the engine it runs, and its bindings from keys to the shell's commands. The engines
// are the page's own: vim's is CodeMirror's vim mode, the shell's commands threaded into it as its actions, a key's
// `{kind}` the fold kind's letter typed after it. A command is named once here and does the same wherever a binding
// reaches it.

import { Vim, getCM } from "@replit/codemirror-vim";

import type { FoldKind } from "../generated/read";
import { counted, every, foldKind, offsetOf } from "../document/tree";
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

/** Return the fold kind typed after a command's key; none, said on the status line, where no kind takes that letter. */
function typed(shell: Shell, given: Given): FoldKind | null {
    const kind = given.kind === null ? null : shell.kinds.byLetter(given.kind);
    if (kind === null) {
        shell.say(`no kind of fold is \`${given.kind ?? ""}\``);
    }
    return kind;
}

/** Return the keys of what an action acts on: every fold chosen, else the innermost fold the cursor is in. */
function reached(shell: Shell): readonly string[] {
    const chosen = shell.chosen();
    if (chosen.length > 0) {
        return chosen;
    }
    const node = shell.foldAt();
    return node === null ? [] : [node.key];
}

/**
 * Open or close every fold `keys` names, or toggle them together where `open` is none: open them all unless all are
 * open. Where they were chosen, nothing is chosen after, and the status line says what was done.
 */
function folded(shell: Shell, keys: readonly string[], open?: boolean): void {
    const nodes = keys.flatMap((key) => {
        const node = shell.document.node(key);
        return node === null ? [] : [node];
    });
    const opening = open ?? !nodes.every((node) => shell.isOpen(node));
    shell.fold(nodes.map((node) => node.key), opening);
    if (shell.chosen().length > 0) {
        shell.choose([]);
        shell.say(`${counted(nodes.length, "fold")} ${opening ? "opened" : "closed"}`);
    }
}

/** Choose the nearest fold of `kind` around the cursor; where there's none, say so and leave what's chosen. */
function nearest(shell: Shell, kind: FoldKind): boolean {
    const node = shell.foldAt(kind.name);
    if (node === null) {
        shell.say(`no ${kind.called} around the cursor`);
        return false;
    }
    shell.choose([node.key]);
    shell.say(null);
    return true;
}

/** The shell's named commands, each doing the same wherever a binding reaches it. */
export const commands: Readonly<Record<string, (shell: Shell, given: Given) => void>> = {
    /** Open or close what's chosen, or the innermost fold the cursor is in, as `za` does. */
    "fold-toggle": (shell) => {
        folded(shell, reached(shell));
    },
    /** Open what's chosen, or the innermost fold the cursor is in. */
    "fold-open": (shell) => {
        folded(shell, reached(shell), true);
    },
    /** Close what's chosen, or the innermost fold the cursor is in. */
    "fold-close": (shell) => {
        folded(shell, reached(shell), false);
    },
    /** Choose the nearest fold of the kind typed after the key, then open or close it: `zf` and its letter. */
    "fold-nearest": (shell, given) => {
        const kind = typed(shell, given);
        if (kind !== null && nearest(shell, kind)) {
            folded(shell, shell.chosen());
            shell.say(null);
        }
    },
    /** Choose the nearest fold of the kind typed after the key around the cursor, in place of what was chosen. */
    "choose-nearest": (shell, given) => {
        const kind = typed(shell, given);
        if (kind !== null) {
            nearest(shell, kind);
        }
    },
    /**
     * Choose every fold of the kind typed after the key within what's chosen, or everywhere where nothing is; where
     * there's none, say so and leave what's chosen.
     */
    "choose-every": (shell, given) => {
        const kind = typed(shell, given);
        if (kind === null) {
            return;
        }
        const chosen = shell.chosen();
        const under =
            chosen.length === 0
                ? every(shell.document.root)
                : chosen.flatMap((key) => {
                      const node = shell.document.node(key);
                      return node === null ? [] : every(node).slice(1);
                  });
        const found = under.filter((node) => foldKind(node) === kind.name).map((node) => node.key);
        if (found.length === 0) {
            shell.say(`no ${kind.called} ${chosen.length === 0 ? "anywhere" : "in what's chosen"}`);
            return;
        }
        shell.choose(found);
        shell.say(`${kind.called}: ${new Set(found).size} chosen`);
    },
    /** Choose nothing and clear what the status line says; in the window, close it: Esc. */
    "choose-none": (shell) => {
        if (shell.owner !== null) {
            shell.owner.window?.close();
            return;
        }
        shell.choose([]);
        shell.say(null);
    },
    /**
     * End the comment being written, as leaving insert mode does; outside one, open the window on the review of what
     * the draft sends where; in the review, send the draft: Ctrl+Enter.
     */
    send: (shell) => {
        const cm = getCM(shell.view);
        if (shell.comments.writing() !== null && cm !== null) {
            Vim.handleKey(cm, "<Esc>", "mapping");
            return;
        }
        if (shell.owner !== null) {
            shell.owner.window?.close();
            shell.owner.comments.send();
            return;
        }
        shell.comments.flush();
        if (shell.review().blocks.length === 0) {
            shell.say("the draft holds nothing to send");
            return;
        }
        shell.window?.review(shell.review());
    },
    /** Hold the part of the draft at the cursor back from sends: Space x on a comment, or on its line in the review. */
    hold: (shell) => {
        (shell.owner ?? shell).comments.hold(true, shell.owner === null ? null : shell.lineId());
    },
    /** Let the part of the draft at the cursor go at the next send: Space d. */
    "let-go": (shell) => {
        (shell.owner ?? shell).comments.hold(false, shell.owner === null ? null : shell.lineId());
    },
    /** Choose whom the comment at the cursor, or on its line in the review, reaches, or write one to whom's chosen: Space s. */
    address: (shell) => {
        (shell.owner ?? shell).comments.address(shell.owner === null ? null : shell.lineId());
    },
    /** Comment on the innermost block at the cursor whole, rather than on one of its lines: Space `c`. */
    "comment-whole": (shell) => {
        shell.comments.commentWhole();
    },
    /** Go to the next comment after the cursor, opening what folds over it: `]n`. */
    "comment-next": (shell) => {
        jumped(shell, true);
    },
    /** Go to the comment before the cursor, opening what folds over it: `[n`. */
    "comment-previous": (shell) => {
        jumped(shell, false);
    },
    /** Write every comment changed since it was last written to the draft at once: `:w`. */
    "draft-write": (shell) => {
        shell.comments.flush();
        shell.say("draft written");
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

/** Move the cursor to the start of the next comment after it, or the last before it, opening every fold over it. */
function jumped(shell: Shell, forward: boolean): void {
    const head = shell.view.state.selection.main.head;
    const comments = every(shell.document.root).filter((node) => node.kind === "comment");
    const starts = comments.map((node) => ({ node, at: offsetOf(node) }));
    const found = forward ? starts.find((each) => each.at > head) : starts.filter((each) => each.at < head).at(-1);
    if (found === undefined) {
        shell.say(`no comment ${forward ? "after" : "before"} the cursor`);
        return;
    }
    const over: string[] = [];
    let at = found.node.parent;
    while (at !== null) {
        if (foldKind(at) !== null && !shell.isOpen(at)) {
            over.push(at.key);
        }
        at = at.parent;
    }
    if (over.length > 0) {
        shell.fold(over, true);
    }
    shell.go(offsetOf(found.node));
}

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
    { keys: "<Space>f{kind}", command: "choose-nearest", modes: ["normal"] },
    { keys: "<Space>F{kind}", command: "choose-every", modes: ["normal"] },
    { keys: "<Esc>", command: "choose-none", modes: ["normal"] },
    { keys: "<C-CR>", command: "send", modes: ["normal", "insert"] },
    { keys: "<Space>c", command: "comment-whole", modes: ["normal"] },
    { keys: "<Space>x", command: "hold", modes: ["normal"] },
    { keys: "<Space>d", command: "let-go", modes: ["normal"] },
    { keys: "<Space>s", command: "address", modes: ["normal"] },
    { keys: "]n", command: "comment-next", modes: ["normal"] },
    { keys: "[n", command: "comment-previous", modes: ["normal"] },
    { keys: ":w", command: "draft-write", modes: ["normal"] },
    { keys: "zR", command: "open-all", modes: ["normal"] },
    { keys: "zM", command: "close-all", modes: ["normal"] },
    { keys: "zr", command: "open-more", modes: ["normal"] },
    { keys: "zm", command: "close-more", modes: ["normal"] },
];

/**
 * Thread `bindings` into vim's mode: each command an action of vim's, reached by its keys in its modes.
 *
 * vim's mappings are the page's, not one editor's, so a command finds the shell it runs in by its editor. Where a
 * binding starts with Space, the shell's leader, vim's own Space (a character right) is unbound, since vim acts on a
 * key that's bound whole before waiting for the keys after it.
 */
export function bindVim(bindings: readonly Bind[]): void {
    if (bindings.some((bind) => bind.keys.startsWith("<Space>"))) {
        // vim's own Space is bound in no mode of its own, which `unmap` reaches with no mode given; its declared type
        // asks for one, though what it does compares the mode given with the binding's, none matching none.
        (Vim.unmap as (keys: string, mode?: string) => unknown)("<Space>");
    }
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
        if (bind.keys.startsWith(":")) {
            // An ex command, as vim's own `:w` is: its name after the colon, run however it's abbreviated.
            const name = bind.keys.slice(1);
            Vim.defineEx(name, name, (cm: { cm6: { state: { facet: (facet: typeof shells) => Shell | null } } }) => {
                const shell = cm.cm6.state.facet(shells);
                if (shell !== null) {
                    run(shell, { kind: null });
                }
            });
            continue;
        }
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
