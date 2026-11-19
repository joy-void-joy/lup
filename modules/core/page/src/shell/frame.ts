// The frame around the document, as the second lup's dashboard had it: the header over the document saying where the
// cursor is, the path of folds it's in from the outermost, each with its kind's letter in its colour; and the line of
// keys under it, the keys that do something where the cursor is, ending with the palette of every command. Both are
// said again as the cursor moves, the mode changes, or what's open or chosen does.

import { getCM } from "@replit/codemirror-vim";

import { foldKind, nodeAt, type Node } from "../document/tree";
import { standings } from "./palette";
import type { Shell } from "./shell";

/** One key and what it does where the cursor is, as the line of keys says it. */
export interface Keyed {
    readonly keys: string;
    readonly does: string;
}

/** Return the folds the document's cursor is in, outermost first. */
export function where(shell: Shell): Node[] {
    const path: Node[] = [];
    let node: Node | null = nodeAt(shell.document.root, shell.view.state.selection.main.head);
    while (node !== null) {
        if (foldKind(node) !== null) {
            path.unshift(node);
        }
        node = node.parent;
    }
    return path;
}

/** Return the keys that do something in `shell` where its cursor is, the palette of every command last. */
export function keysHere(shell: Shell): Keyed[] {
    const owner = shell.owner ?? shell;
    const every: Keyed = { keys: "Ctrl+K", does: "every command" };
    const role = owner.window?.shell() === shell ? owner.window.role() : null;
    if (role === "review") {
        return [
            { keys: "Space x", does: "hold back" },
            { keys: "Space d", does: "let go" },
            { keys: "Space s", does: "send elsewhere" },
            { keys: "Ctrl+Enter", does: "send" },
            { keys: "Esc", does: "close" },
            every,
        ];
    }
    if (role === "pick") {
        return [{ keys: "/", does: "search" }, { keys: "Enter", does: "choose" }, { keys: "Esc", does: "close" }, every];
    }
    if (owner.outline?.shell === shell) {
        return [{ keys: "j k", does: "move, the document following" }, { keys: "Enter", does: "go there" }, { keys: "Space w l", does: "the document" }, every];
    }
    const vim = getCM(shell.view)?.state.vim as { insertMode?: boolean } | null | undefined;
    if (vim?.insertMode === true) {
        return [
            { keys: "Esc", does: "end the comment" },
            { keys: "Ctrl+Enter", does: "end it" },
        ];
    }
    if (shell.comments.partAt() !== null) {
        return [
            { keys: "i", does: "write" },
            { keys: "dd", does: "take a line out" },
            { keys: "Space s", does: "send to" },
            { keys: "Space x", does: "hold back" },
            { keys: "]n", does: "next comment" },
            { keys: "Ctrl+Enter", does: "review the draft" },
            every,
        ];
    }
    const fold = shell.foldAt();
    const atSummary = fold !== null && nodeAt(shell.document.root, shell.view.state.selection.main.head) === fold;
    return [
        ...(atSummary ? [{ keys: "za", does: shell.isOpen(fold) ? "close" : "open" }] : []),
        { keys: "o", does: "comment" },
        { keys: "c", does: "comment on a passage" },
        { keys: "Space f", does: "choose a fold" },
        { keys: "Ctrl+Enter", does: "review the draft" },
        every,
    ];
}

/** Draw where `shell`'s cursor is in `header`, and the keys that do something there in `keys`. */
export function framed(shell: Shell, header: HTMLElement | null, keys: HTMLElement | null): void {
    if (header !== null) {
        const parts = where(shell).map((node) => {
            const kind = foldKind(node);
            const declared = kind === null ? undefined : shell.kinds.folds.get(kind);
            const part = document.createElement("span");
            part.className = "lup-where-part";
            const letter = document.createElement("b");
            letter.className = "lup-where-letter";
            letter.textContent = declared?.letter ?? "";
            letter.style.color = `var(--lup-${declared?.colour ?? "muted"})`;
            const said = document.createElement("span");
            said.textContent = node.head[0] ?? "";
            const standing = node.block?.standing ?? null;
            if (standing !== null) {
                const glyph = document.createElement("span");
                glyph.textContent = `${standings[standing]} `;
                glyph.style.color = `var(--lup-${standing})`;
                part.append(letter, glyph, said);
            } else {
                part.append(letter, said);
            }
            return part;
        });
        header.replaceChildren(...parts);
    }
    if (keys !== null) {
        keys.replaceChildren(
            ...keysHere(shell).map((each) => {
                const item = document.createElement("span");
                item.className = "lup-keys-item";
                const key = document.createElement("kbd");
                key.textContent = each.keys;
                item.append(key, ` ${each.does}`);
                return item;
            }),
        );
    }
}
