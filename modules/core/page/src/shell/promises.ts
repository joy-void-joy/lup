// The shell's promises: what the operator can count on of the document as they move through it, fold it and type,
// while views answer again under them. Each runs on the shell itself, headless, its keys sent as a keyboard sends
// them, with no real time, so how loaded the machine is can't change what happens.

import fc from "fast-check";
import { expect } from "vitest";
import { Vim, getCM } from "@replit/codemirror-vim";

import type { Blocks, Fold, Viewing } from "../generated/read";
import { every, foldKind, offsetOf, section } from "../document/tree";
import { blocks, fold } from "../testing/blocks";
import { Memory, looks } from "../testing/memory";
import { law, scenario, type Machine } from "../testing/promise";
import { bindVim, vimBindings } from "./keymap";
import { beside, cursorFolds, type Beside } from "./margin";
import { Shell, type ShellState } from "./shell";

bindVim(vimBindings);

const root: Viewing = { module: "notes", view: "pile", given: { pile: "p" } };

/** What can happen to the shell: the operator's key, or a view answering again. */
type Event = { readonly key: string } | { readonly answer: Blocks };

/** The keys the operator types, as vim names them: moving, folding, entering and leaving insert mode, and text. */
const keys = fc.constantFrom("j", "k", "gg", "G", "za", "zo", "zc", "zr", "zm", "zR", "zM", "zfn", "i", "a", "o", "x", "<Esc>", "<C-[>", "v", "<Space>");

/** The keys that leave insert mode, as vim has them. */
const leaving = ["<Esc>", "<C-[>", "<C-c>"];

function answer(content: Blocks["blocks"]): Blocks {
    return { blocks: content, summary: [], offers: [] };
}

/** Send `key`, as vim names it, to `shell`'s editor, as the keyboard does. */
function press(shell: Shell, key: string): void {
    const cm = getCM(shell.view);
    if (cm === null) {
        throw new Error("the shell's editor has no vim mode");
    }
    const named = key.startsWith("<") ? [key] : [...key];
    for (const each of named) {
        Vim.handleKey(cm, each, "user");
    }
}

interface Running {
    readonly shell: Shell;
    readonly memory: Memory;
    readonly parent: HTMLElement;
}

/** One fold the document shows: its key, and the lines its summary and its end are on, from 1. */
interface Spanned {
    readonly key: string;
    readonly first: number;
    readonly last: number;
}

/** The shell's state, with what its margin shows beside each line and where each fold is. */
interface Seen extends ShellState {
    readonly folds: readonly Spanned[];
    /** Beside each line, the first first. */
    readonly margin: readonly Beside[];
}

/** Return what `shell` shows, its margin and its folds among it. */
function seen(shell: Shell): Seen {
    const doc = shell.view.state.doc;
    const bright = cursorFolds(shell, shell.view.state);
    const margin: Beside[] = [];
    for (let number = 1; number <= doc.lines; number++) {
        const line = doc.line(number);
        margin.push(beside(shell, line.from, line.to, bright));
    }
    const folds = every(shell.document.root)
        .filter((node) => foldKind(node) !== null && node.lines > 0)
        .map((node) => {
            const start = offsetOf(node);
            return { key: node.key, first: doc.lineAt(start).number, last: doc.lineAt(start + node.size).number };
        });
    return { ...shell.state(), folds, margin };
}

const shell: Machine<Running, Seen, Event> = {
    name: "the shell",
    start(by) {
        const memory = new Memory();
        memory.set(root, answer(by.any(blocks(2))));
        const parent = document.createElement("div");
        document.body.append(parent);
        return { shell: new Shell(parent, root, looks, memory), memory, parent };
    },
    events: fc.oneof(
        { weight: 4, arbitrary: keys.map((key): Event => ({ key })) },
        { weight: 1, arbitrary: blocks(1).map((content): Event => ({ answer: answer(content) })) },
    ),
    apply(running, event) {
        if ("key" in event) {
            press(running.shell, event.key);
        } else {
            running.memory.set(root, event.answer);
        }
    },
    state(running) {
        return seen(running.shell);
    },
    end(running) {
        running.shell.destroy();
        running.parent.remove();
    },
};

law(shell, "The cursor never leaves insert mode unless the operator leaves it, a view answering again among what can't", (step) => {
    if (step.before.mode !== "insert" || step.after.mode === "insert") {
        return true;
    }
    return "key" in step.event && leaving.includes(step.event.key);
});

law(shell, "A view answering again leaves open what the operator opened and closed what they closed, of the folds it still shows", (step) => {
    if (!("answer" in step.event)) {
        return true;
    }
    const kept = new Set(step.after.closed);
    const still = new Set(
        every(section("root", root, step.event.answer))
            .filter((node) => foldKind(node) !== null)
            .map((node) => node.key),
    );
    return step.before.closed.every((key) => !still.has(key) || kept.has(key));
});

law(shell, "The margin shows each fold's letter once, beside its summary, outlined exactly when it's closed, and a bar beside each line under it, bright exactly while the cursor's in it", (step) => {
    const after = step.after;
    const known = new Map(after.folds.map((fold) => [fold.key, fold]));
    for (const [at, shown] of after.margin.entries()) {
        const line = at + 1;
        for (const letter of shown.letters) {
            const fold = known.get(letter.key);
            if (fold === undefined || fold.first !== line || letter.closed !== after.closed.includes(letter.key)) {
                return false;
            }
        }
        for (const bar of shown.bars) {
            const fold = known.get(bar.key);
            if (fold === undefined || line <= fold.first || line > fold.last) {
                return false;
            }
            if (bar.bright !== (after.line >= fold.first && after.line <= fold.last) || bar.last !== (line === fold.last)) {
                return false;
            }
        }
    }
    return after.folds.every(
        (fold) =>
            after.margin[fold.first - 1]?.letters.some((letter) => letter.key === fold.key) === true &&
            after.margin.slice(fold.first, fold.last).every((shown) => shown.bars.some((bar) => bar.key === fold.key)),
    );
});

/** A source answering `root` with `blocks` alone. */
function single(blocks: Blocks): Memory {
    const memory = new Memory();
    memory.set(root, blocks);
    return memory;
}

scenario("A fold of a kind that starts closed shows its summary alone until it's opened, then shows what's under it", async (by) => {
    const content = by.any(fold("n", 1).filter((made) => Array.isArray(made.content) && made.content.length > 0));
    const parent = document.createElement("div");
    const opened = new Shell(parent, root, looks, single(answer([content])));
    try {
        const key = "root/n";
        const node = opened.document.node(key);
        expect(node === null ? null : foldKind(node)).toBe("note");
        expect(opened.state().closed).toContain(key);
        press(opened, "zfn");
        expect(opened.state().closed).not.toContain(key);
        press(opened, "zfn");
        expect(opened.state().closed).toContain(key);
    } finally {
        opened.destroy();
    }
});

scenario("A fold read as it opens reads its view once opened, and shows its answer under its summary", async (by) => {
    const reads: Viewing = { module: "notes", view: "note", given: { number: 1 } };
    const summary = by.any(fc.string({ maxLength: 8 }));
    const loading: Fold = {
        block: "fold",
        id: "n",
        version: null,
        offers: [],
        reaches: null,
        sighted: null,
        kind: "note",
        summary: [{ text: summary, tone: "plain", ticking: null, gauge: null, refers: null }],
        open: null,
        content: reads,
    };
    const memory = single(answer([loading]));
    const under = by.any(blocks(1).filter((made) => made.length > 0));
    memory.set(reads, answer(under));
    const opened = new Shell(document.createElement("div"), root, looks, memory);
    try {
        expect(opened.state().text).toBe(summary);
        press(opened, "zfn");
        expect(opened.state().text.startsWith(`${summary}\n`)).toBe(true);
        expect(opened.state().text.length).toBeGreaterThan(summary.length);
    } finally {
        opened.destroy();
    }
});
