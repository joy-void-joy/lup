// The shell's promises: what the operator can count on of the document as they move through it, fold it and type,
// while views answer again under them. Each runs on the shell itself, headless, its keys sent as a keyboard sends
// them, with no real time, so how loaded the machine is can't change what happens.

import fc from "fast-check";
import { expect } from "vitest";

import type { Blocks, Fold, Viewing } from "../generated/read";
import { every, foldKind, offsetOf, section } from "../document/tree";
import { blocks, fold } from "../testing/blocks";
import { press } from "../testing/keys";
import { Memory, looks } from "../testing/memory";
import { law, scenario, type Machine } from "../testing/promise";
import { bindVim, vimBindings } from "./keymap";
import { beside, cursorFolds, type Beside } from "./margin";
import { Shell, type ShellState } from "./shell";

bindVim(vimBindings);

const root: Viewing = { module: "notes", view: "pile", given: { pile: "p" } };

/** What can happen to the shell: the operator's keys, each as vim names it, or a view answering again. */
type Event = { readonly keys: readonly string[] } | { readonly answer: Blocks };

/** The fold kinds the shell's runs lay their folds out in: a module's, and one of the core's. */
const kinds = ["note", "body"];

/**
 * What the operator types, each a whole command, as vim names its keys: moving, folding, choosing, entering and leaving
 * insert mode, commenting, sending, and text, which in insert mode each of a command's characters types.
 */
const keys = fc.constantFrom(
    ..."j k gg G za zo zc zr zm zR zM zfn zfb i a A o O x e s S cw cc vls dd ]n [n".split(" ").map((typed) => [...typed]),
    ["<Esc>"],
    ["<C-[>"],
    ["<CR>"],
    ["<BS>"],
    ["<C-CR>"],
    [":w"],
    ...["fn", "fb", "Fn", "Fb", "fz", "c"].map((typed) => ["<Space>", ...typed]),
);

/** The keys that leave insert mode: vim's own, and Ctrl+Enter, which ends the comment being written. */
const leaving = ["<Esc>", "<C-[>", "<C-c>", "<C-CR>"];

function answer(content: Blocks["blocks"]): Blocks {
    return { blocks: content, summary: [], offers: [] };
}

interface Running {
    readonly shell: Shell;
    readonly memory: Memory;
    readonly parent: HTMLElement;
}

/** One fold the document shows: its key, its kind, and the lines its summary and its end are on, from 1. */
interface Spanned {
    readonly key: string;
    readonly kind: string;
    readonly first: number;
    readonly last: number;
}

/** The shell's state, with what its margin shows beside each line, where each fold is, and what's written. */
interface Seen extends ShellState {
    readonly folds: readonly Spanned[];
    /** Beside each line, the first first. */
    readonly margin: readonly Beside[];
    /** The document's text as its tree lays it out. */
    readonly tree: string;
    /** The editor's text with every comment taken out: what the views answered. */
    readonly outside: string;
    /** What the draft holds of each comment, by its node's key. */
    readonly drafted: Readonly<Record<string, string>>;
}

/** Return what `shell` shows, its margin, its folds and its comments among it, and what `memory`'s draft holds. */
function seen(shell: Shell, memory: Memory): Seen {
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
            return { key: node.key, kind: foldKind(node) ?? "", first: doc.lineAt(start).number, last: doc.lineAt(start + node.size).number };
        });
    const text = doc.toString();
    const cut = every(shell.document.root)
        .filter((node) => node.kind === "comment")
        .map((node) => ({ from: offsetOf(node) - 1, to: offsetOf(node) + node.size }))
        .sort((one, other) => other.from - one.from);
    const outside = cut.reduce((kept, range) => kept.slice(0, range.from) + kept.slice(range.to), text);
    const drafted = Object.fromEntries(memory.draft.comments.map((comment) => [`comment:${comment.id}`, comment.words]));
    return { ...shell.state(), folds, margin, tree: shell.document.text(), outside, drafted };
}

const shell: Machine<Running, Seen, Event> = {
    name: "the shell",
    start(by) {
        const memory = new Memory();
        memory.set(root, answer(by.any(blocks(2, kinds))));
        const parent = document.createElement("div");
        document.body.append(parent);
        return { shell: new Shell(parent, root, looks, memory), memory, parent };
    },
    events: fc.oneof(
        { weight: 4, arbitrary: keys.map((typed): Event => ({ keys: typed })) },
        { weight: 1, arbitrary: blocks(1, kinds).map((content): Event => ({ answer: answer(content) })) },
    ),
    async apply(running, event) {
        if ("keys" in event) {
            await press(running.shell, event.keys);
        } else {
            running.memory.set(root, event.answer);
        }
    },
    state(running) {
        return seen(running.shell, running.memory);
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
    return "keys" in step.event && step.event.keys.some((key) => leaving.includes(key));
});

law(shell, "A view answering again leaves open what the operator opened and closed what they closed, of the folds it still shows as the same kind", (step) => {
    if (!("answer" in step.event)) {
        return true;
    }
    const kindBefore = new Map(step.before.folds.map((fold) => [fold.key, fold.kind]));
    const kept = new Set(step.after.closed);
    return step.after.folds.every((fold) => kindBefore.get(fold.key) !== fold.kind || step.before.closed.includes(fold.key) === kept.has(fold.key));
});

/** Return the folds `seen` shows of `kind` under one of the folds keyed in `chosen`, or anywhere where none is. */
function under(seen: Seen, chosen: readonly string[], kind: string): string[] {
    const outer = seen.folds.filter((fold) => chosen.includes(fold.key));
    return seen.folds
        .filter((fold) => fold.kind === kind && (chosen.length === 0 || outer.some((each) => each.first < fold.first && fold.last <= each.last)))
        .map((fold) => fold.key);
}

/** Return the keys typed, where the step is the operator typing them in Normal mode. */
function typedInNormal(step: { readonly before: Seen; readonly event: Event }): readonly string[] | null {
    return "keys" in step.event && step.before.mode === "normal" ? step.event.keys : null;
}

law(shell, "Space F and a fold kind's letter chooses every fold of the kind within what was chosen, or anywhere where nothing was; where there's none, it says so and leaves what was chosen", (step) => {
    const typed = typedInNormal(step);
    if (typed === null || typed.length !== 3 || typed[0] !== "<Space>" || typed[1] !== "F") {
        return true;
    }
    const kind = looks.folds.find((each) => each.kind.letter === typed[2])?.kind.name;
    const found = kind === undefined ? [] : under(step.before, step.before.chosen, kind);
    if (found.length === 0) {
        return step.after.said !== null && JSON.stringify(step.after.chosen) === JSON.stringify(step.before.chosen);
    }
    return JSON.stringify(step.after.chosen) === JSON.stringify(found);
});

law(shell, "Space f and a fold kind's letter chooses the nearest fold of the kind around the cursor alone; where there's none, it says so and leaves what was chosen", (step) => {
    const typed = typedInNormal(step);
    if (typed === null || typed.length !== 3 || typed[0] !== "<Space>" || typed[1] !== "f") {
        return true;
    }
    const kind = looks.folds.find((each) => each.kind.letter === typed[2])?.kind.name;
    const around = step.before.folds.filter((fold) => fold.kind === kind && fold.first <= step.before.line && step.before.line <= fold.last);
    const nearest = around.at(-1);
    if (nearest === undefined) {
        return step.after.said !== null && JSON.stringify(step.after.chosen) === JSON.stringify(step.before.chosen);
    }
    return JSON.stringify(step.after.chosen) === JSON.stringify([nearest.key]);
});

law(shell, "za, zo or zc on what's chosen opens or closes every fold chosen alike, then nothing is chosen", (step) => {
    const typed = typedInNormal(step);
    if (typed === null || typed[0] !== "z" || !["a", "o", "c"].includes(typed[1] ?? "") || typed.length !== 2 || step.before.chosen.length === 0) {
        return true;
    }
    const still = step.before.chosen.filter((key) => step.after.folds.some((fold) => fold.key === key));
    const closed = still.filter((key) => step.after.closed.includes(key));
    const wanted = typed[1] === "o" ? "open" : typed[1] === "c" ? "closed" : step.before.chosen.every((key) => !step.before.closed.includes(key)) ? "closed" : "open";
    return step.after.chosen.length === 0 && closed.length === (wanted === "closed" ? still.length : 0);
});

law(shell, "What's chosen changes only as the operator chooses, acts on it or leaves it with Esc, and a view answering again drops only what it no longer shows", (step) => {
    if ("answer" in step.event) {
        const shown = new Set(step.after.folds.map((fold) => fold.key));
        return JSON.stringify(step.after.chosen) === JSON.stringify(step.before.chosen.filter((key) => shown.has(key)));
    }
    const typed = step.event.keys;
    const choosing = step.before.mode === "normal" && (typed[0] === "<Space>" || typed[0] === "<Esc>" || typed[0] === "z");
    return choosing || JSON.stringify(step.after.chosen) === JSON.stringify(step.before.chosen);
});

law(shell, "The editor's text is always the document's, whatever the operator types and however views answer", (step) => step.after.text === step.after.tree);

law(shell, "The operator's keys change nothing but comments: what the views answered reads the same around them", (step) => "answer" in step.event || step.before.outside === step.after.outside);

law(shell, "Insert mode is only ever in a comment, one opened where the operator went into it outside one", (step) => step.after.mode !== "insert" || "answer" in step.event || step.after.writing !== null);

law(shell, "Out of insert mode, every comment shown says something, and the draft holds what it says", (step) => {
    if (step.after.mode === "insert") {
        return true;
    }
    return Object.entries(step.after.comments).every(([key, text]) => text.trim() !== "" && step.after.drafted[key] === text);
});

law(shell, "A view answering again leaves what each comment it still shows says as it was", (step) => {
    if (!("answer" in step.event)) {
        return true;
    }
    return Object.entries(step.after.comments).every(([key, text]) => step.before.comments[key] === undefined || step.before.comments[key] === text);
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
        await press(opened, ["z", "f", "n"]);
        expect(opened.state().closed).not.toContain(key);
        await press(opened, ["z", "f", "n"]);
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
        await press(opened, ["z", "f", "n"]);
        expect(opened.state().text.startsWith(`${summary}\n`)).toBe(true);
        expect(opened.state().text.length).toBeGreaterThan(summary.length);
    } finally {
        opened.destroy();
    }
});
