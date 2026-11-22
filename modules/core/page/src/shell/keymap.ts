// The keymaps' engines, and the shell's named commands they reach.
//
// A keymap is a module's data: the engine it runs, and its bindings from keys to the shell's commands. The engines
// are the page's own: vim's is CodeMirror's vim mode, the shell's commands threaded into it as its actions, a key's
// `{kind}` the fold kind's letter typed after it. A command is named once here and does the same wherever a binding
// reaches it.

import { Vim, getCM } from "@replit/codemirror-vim";

import type { FoldKind } from "../generated/read";
import { counted, every, foldKind, offsetOf } from "../document/tree";
import { bindIndenting } from "./markdown";
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

/** One of the shell's commands: what it does, as the palette of commands says it, and what runs it. */
export interface Command {
    readonly says: string;
    readonly run: (shell: Shell, given: Given) => void;
}

/** The shell's named commands, each doing the same wherever a binding reaches it. */
export const commands: Readonly<Record<string, Command>> = {
    /** Open or close what's chosen, or the innermost fold the cursor is in, as `za` does. */
    "fold-toggle": {
        says: "open or close the fold the cursor is in, or every fold chosen",
        run: (shell) => {
            folded(shell, reached(shell));
        },
    },
    /** Open what's chosen, or the innermost fold the cursor is in. */
    "fold-open": {
        says: "open the fold the cursor is in, or every fold chosen",
        run: (shell) => {
            folded(shell, reached(shell), true);
        },
    },
    /** Close what's chosen, or the innermost fold the cursor is in. */
    "fold-close": {
        says: "close the fold the cursor is in, or every fold chosen",
        run: (shell) => {
            folded(shell, reached(shell), false);
        },
    },
    /** Choose the nearest fold of the kind typed after the key, then open or close it: `zf` and its letter. */
    "fold-nearest": {
        says: "open or close the nearest fold of a kind",
        run: (shell, given) => {
            const kind = typed(shell, given);
            if (kind !== null && nearest(shell, kind)) {
                folded(shell, shell.chosen());
                shell.say(null);
            }
        },
    },
    /** Choose the nearest fold of the kind typed after the key around the cursor, in place of what was chosen. */
    "choose-nearest": {
        says: "choose the nearest fold of a kind",
        run: (shell, given) => {
            const kind = typed(shell, given);
            if (kind !== null) {
                nearest(shell, kind);
            }
        },
    },
    /**
     * Choose every fold of the kind typed after the key within what's chosen, or everywhere where nothing is; where
     * there's none, say so and leave what's chosen.
     */
    "choose-every": {
        says: "choose every fold of a kind within what's chosen, or everywhere",
        run: (shell, given) => {
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
    },
    /** Choose nothing and clear what the status line says; in the window, close it: Esc. */
    "choose-none": {
        says: "choose nothing; in the window, close it",
        run: (shell) => {
            if (shell.owner !== null) {
                if (shell.owner.window?.shell() === shell) {
                    shell.owner.window.close();
                }
                return;
            }
            shell.choose([]);
            shell.say(null);
        },
    },
    /**
     * End the comment being written, as leaving insert mode does; outside one, open the window on the review of what
     * the draft sends where; in the review, send the draft: Ctrl+Enter.
     */
    "send": {
        says: "end the comment written; open the review; in the review, send the draft",
        run: (shell) => {
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
    },
    /** In a picker, choose the line the cursor is on; elsewhere go down a line to its first character, as vim's Enter does. */
    "enter": {
        says: "in a picker, choose the line; elsewhere go down a line",
        run: (shell) => {
            if (shell.owner?.window?.choose(shell.lineId()) === true) {
                return;
            }
            if (shell.owner !== null && shell.owner.outline?.shell === shell) {
                shell.owner.view.focus();
                return;
            }
            const cm = getCM(shell.view);
            if (cm !== null) {
                Vim.handleKey(cm, "+", "mapping");
            }
        },
    },
    /** Enter pane mode, to move between the outline, the document and the window: Space w w, or Esc twice. */
    "panes": {
        says: "move between the outline, the document and the window, in pane mode",
        run: (shell) => {
            (shell.owner ?? shell).panes?.enter();
        },
    },
    "pane-left": {
        says: "go to the pane on the left",
        run: (shell) => {
            (shell.owner ?? shell).panes?.go(shell, "h");
        },
    },
    "pane-down": {
        says: "go to the pane below",
        run: (shell) => {
            (shell.owner ?? shell).panes?.go(shell, "j");
        },
    },
    "pane-up": {
        says: "go to the pane above",
        run: (shell) => {
            (shell.owner ?? shell).panes?.go(shell, "k");
        },
    },
    "pane-right": {
        says: "go to the pane on the right",
        run: (shell) => {
            (shell.owner ?? shell).panes?.go(shell, "l");
        },
    },
    /** Choose whom the comment at the cursor, or on its line in the review, reaches, or write one to whom's chosen: Space s. */
    "address": {
        says: "choose whom a comment reaches",
        run: (shell) => {
            (shell.owner ?? shell).comments.address(shell.owner === null ? null : shell.lineId());
        },
    },
    /** Comment on the innermost block at the cursor whole, rather than on one of its lines: Space `c`. */
    "comment-whole": {
        says: "comment on the block the cursor is in, whole",
        run: (shell) => {
            shell.comments.commentWhole();
        },
    },
    /** Go to the next comment after the cursor, opening what folds over it: `]n`. */
    "comment-next": {
        says: "go to the next comment",
        run: (shell) => {
            jumped(shell, true);
        },
    },
    /** Go to the comment before the cursor, opening what folds over it: `[n`. */
    "comment-previous": {
        says: "go to the comment before",
        run: (shell) => {
            jumped(shell, false);
        },
    },
    /** Write every comment changed since it was last written to the draft at once: `:w`. */
    "draft-write": {
        says: "write the draft now",
        run: (shell) => {
            shell.comments.flush();
            shell.say("draft written");
        },
    },
/** Open every fold, as `zR` does. */
    palette: {
        says: "list every command with its keys, to run one",
        run: (shell) => {
            const owner = shell.owner ?? shell;
            const window = owner.window;
            if (window === null) {
                return;
            }
            const choices = vimBindings
                .filter((bind) => bind.command !== "palette")
                .map((bind) => ({ name: `${said(bind.keys).padEnd(14)} ${commandOf(bind.command)?.says ?? ""}`, value: bind }));
            window.pick("Run a command…", choices, (bind) => {
                const command = commandOf(bind.command);
                if (command === undefined) {
                    return;
                }
                if (!bind.keys.includes("{kind}")) {
                    command.run(owner, { kind: null });
                    return;
                }
                const kinds = [...owner.kinds.folds.values()].map((kind) => ({ name: `${kind.letter}  ${kind.called}`, value: kind.letter }));
                window.pick(`${command.says}: which kind?`, kinds, (letter) => {
                    command.run(owner, { kind: letter });
                });
            });
        },
    },
    "open-all": {
        says: "open every fold",
        run: (shell) => {
            shell.level(true);
        },
    },
    /** Close every fold, as `zM` does. */
    "close-all": {
        says: "close every fold",
        run: (shell) => {
            shell.level(false);
        },
    },
    /** Open the next level of folds, as `zr` does: every fold whose kind's level is the shallowest still closed. */
    "open-more": {
        says: "open the next level of folds",
        run: (shell) => {
            const closed = levels(shell, false);
            if (closed.length > 0) {
                shell.level(true, Math.min(...closed));
            }
        },
    },
    /** Close the deepest level of folds open, as `zm` does. */
    "close-more": {
        says: "close the deepest level of folds open",
        run: (shell) => {
            const open = levels(shell, true);
            if (open.length > 0) {
                shell.level(false, Math.max(...open));
            }
        },
    },
};

/** What a verb's key does to the line of the review it's on: `done` sends the part, `decline` keeps it back, `toggle` flips which. */
const reviewing: Readonly<Record<string, boolean | null>> = { done: false, decline: true, toggle: null };

/**
 * Mark `verb` where `shell`'s cursor is, as Space and the verb's key does: in the document, on the innermost block
 * offering it, or every fold chosen that does; in the review, on the part of the draft its line is, sending it or
 * keeping it back.
 */
function marked(shell: Shell, verb: string): void {
    const owner = shell.owner;
    if (owner === null) {
        shell.marks.toggle(verb);
        return;
    }
    if (owner.window?.shell() !== shell || owner.window.role() !== "review") {
        shell.say("marks are made in the document");
        return;
    }
    const held = reviewing[verb];
    const id = shell.lineId();
    if (held === undefined || id === null) {
        shell.say(held === undefined ? `${verb} does nothing in the review: Space d sends a part, Space x keeps it back` : "no part of the draft here");
        return;
    }
    if (owner.marks.byId(id) !== null) {
        const now = owner.marks.hold(id, held);
        shell.say(now?.held === true ? "kept back: it stays in the draft" : "it goes at the next send");
        return;
    }
    owner.comments.hold(held, id);
}

/**
 * Return the command a binding names: one of the shell's own, or `verb:` and a verb's name, which marks that verb on
 * what offers it where the cursor is; none where it names neither.
 */
export function commandOf(name: string): Command | undefined {
    const own = commands[name];
    if (own !== undefined || !name.startsWith("verb:")) {
        return own;
    }
    const verb = name.slice("verb:".length);
    return {
        says: `mark ${verb} on what offers it here, again to unmark; in the review, ${reviewing[verb] === undefined ? "nothing" : reviewing[verb] === false ? "send the part" : reviewing[verb] === true ? "keep the part back" : "send it or keep it back"}`,
        run: (shell) => {
            marked(shell, verb);
        },
    };
}

/** Say `keys` as the palette of commands shows them: Space, Ctrl, Enter and Esc by name, a kind's letter as `‹kind›`. */
export function said(keys: string): string {
    const named: readonly (readonly [string, string])[] = [
        ["<Space>", "Space "],
        ["<C-CR>", "Ctrl+Enter"],
        ["<C-k>", "Ctrl+K"],
        ["<CR>", "Enter"],
        ["<Esc>", "Esc"],
        ["{kind}", "‹kind›"],
    ];
    return named.reduce((text, [vim, shown]) => text.replaceAll(vim, shown), keys);
}

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
    { keys: "<Space>d", command: "verb:done", modes: ["normal"] },
    { keys: "<Space>x", command: "verb:decline", modes: ["normal"] },
    { keys: "<Space>t", command: "verb:toggle", modes: ["normal"] },
    { keys: "<Space>s", command: "address", modes: ["normal"] },
    { keys: "<CR>", command: "enter", modes: ["normal"] },
    { keys: "<Space>wh", command: "pane-left", modes: ["normal"] },
    { keys: "<Space>wj", command: "pane-down", modes: ["normal"] },
    { keys: "<Space>wk", command: "pane-up", modes: ["normal"] },
    { keys: "<Space>wl", command: "pane-right", modes: ["normal"] },
    { keys: "<Space>ww", command: "panes", modes: ["normal"] },
    { keys: "<C-k>", command: "palette", modes: ["normal"] },
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
    bindIndenting();
    for (const bind of bindings) {
        const run = commandOf(bind.command)?.run;
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
