// The shell's promises: what the operator can count on of the document as they move through it, fold it and type,
// while views answer again under them. Each runs on the shell itself, headless, its keys sent as a keyboard sends
// them, with no real time, so how loaded the machine is can't change what happens.

import fc from "fast-check";
import { expect } from "vitest";
import { Vim, getCM } from "@replit/codemirror-vim";

import type { Blocks, Fold, Viewing } from "../generated/read";
import { every, foldKind, section } from "../document/tree";
import { blocks, fold } from "../testing/blocks";
import { Memory, looks } from "../testing/memory";
import { law, scenario, type Machine } from "../testing/promise";
import { bindVim, vimBindings } from "./keymap";
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

const shell: Machine<Running, ShellState, Event> = {
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
        return running.shell.state();
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
