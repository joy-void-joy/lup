// The shell's promises: what the operator can count on of the document as they move through it, fold it and type,
// while views answer again under them. Each runs on the shell itself, headless, its keys sent as a keyboard sends
// them, with no real time, so how loaded the machine is can't change what happens.

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import fc from "fast-check";
import { expect, test } from "vitest";

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
    ["u"],
    ["<C-r>"],
    [":w"],
    ...["fn", "fb", "Fn", "Fb", "fz", "c", "x", "d"].map((typed) => ["<Space>", ...typed]),
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

scenario("A view answering again keeps what an open fold read under it, the fold naming no module but its view's", async (by) => {
    const reads: Viewing = { module: null, view: "note", given: { number: 1 } };
    const loading: Fold = {
        block: "fold",
        id: "n",
        version: null,
        offers: [],
        reaches: null,
        sighted: null,
        kind: "note",
        summary: [{ text: "note", tone: "plain", ticking: null, gauge: null, refers: null }],
        open: true,
        content: reads,
    };
    const memory = single(answer([loading]));
    const under = by.any(blocks(1).filter((made) => made.length > 0));
    memory.set({ ...reads, module: root.module }, answer(under));
    const parent = document.createElement("div");
    const opened = new Shell(parent, root, looks, memory);
    try {
        const read = opened.state().text;
        expect(read.length).toBeGreaterThan("note".length);
        memory.set(root, answer([loading, ...by.any(blocks(1))]));
        expect(opened.state().text.startsWith(read)).toBe(true);
    } finally {
        opened.destroy();
    }
});

/** Return a shell on `content`, its document's root answered from memory with the review at its top. */
function shellOn(content: Blocks["blocks"]): { shell: Shell; memory: Memory; parent: HTMLElement } {
    const memory = new Memory();
    memory.set(root, answer(content));
    const parent = document.createElement("div");
    document.body.append(parent);
    return { shell: new Shell(parent, root, looks, memory), memory, parent };
}

/** Return the shell drawing `opened`'s window, which a scenario expects open. */
function windowOf(opened: Shell): Shell {
    const inner = opened.window?.shell() ?? null;
    expect(inner).not.toBeNull();
    if (inner === null) {
        throw new Error("the window isn't open");
    }
    return inner;
}

scenario("Ctrl+Enter opens the window on the review of what the draft sends, Esc closes it, and Ctrl+Enter in it sends", async (by) => {
    const content = by.any(blocks(1, kinds).filter((made) => made.some((block) => block.block === "line")));
    const { shell: opened, memory, parent } = shellOn(content);
    try {
        await press(opened, ["G", "o", "h", "i", "<Esc>"]);
        expect(memory.draft.comments.map((each) => each.words)).toEqual(["hi"]);
        const before = opened.view.state.selection.main.head;
        await press(opened, ["<C-CR>"]);
        expect(opened.window?.role()).toBe("review");
        expect(windowOf(opened).state().text).toContain("hi");
        await press(windowOf(opened), ["<Esc>"]);
        expect(opened.window?.role()).toBeNull();
        expect(opened.view.state.selection.main.head).toBe(before);
        await press(opened, ["<C-CR>"]);
        await press(windowOf(opened), ["<C-CR>"]);
        expect(memory.draft.comments).toEqual([]);
        expect(opened.window?.role()).toBeNull();
        expect(opened.state().said).toBe("sent 1");
    } finally {
        opened.destroy();
        parent.remove();
    }
});

scenario("Space x holds a comment back, so a send leaves it in the draft as it is, and Space d on its line in the review lets it go", async (by) => {
    const content = by.any(blocks(1, kinds).filter((made) => made.some((block) => block.block === "line")));
    const { shell: opened, memory, parent } = shellOn(content);
    try {
        await press(opened, ["G", "o", "k", "e", "e", "p", "<Esc>", "<Space>", "x"]);
        expect(memory.draft.comments.map((each) => each.held)).toEqual([true]);
        await press(opened, ["<C-CR>"]);
        await press(windowOf(opened), ["<C-CR>"]);
        expect(memory.draft.comments.map((each) => [each.words, each.held])).toEqual([["keep", true]]);
        await press(opened, ["<C-CR>"]);
        const inner = windowOf(opened);
        const part = inner.document.node(`root/held/${memory.draft.comments[0]?.id ?? ""}`);
        expect(part).not.toBeNull();
        if (part === null) {
            return;
        }
        // The review's line for the comment: vim's own motions there need the page laid out, which the harness isn't.
        inner.go(offsetOf(part));
        await press(inner, ["<Space>", "d"]);
        expect(memory.draft.comments.map((each) => each.held)).toEqual([false]);
        await press(windowOf(opened), ["<C-CR>"]);
        expect(memory.draft.comments).toEqual([]);
    } finally {
        opened.destroy();
        parent.remove();
    }
});

scenario("Space s on a comment sends it to the party chosen among those the document shows, as typing narrows them", async (by) => {
    const name = by.any(fc.constantFrom("port-plan", "frictions"));
    const party: Fold = {
        block: "fold",
        id: name,
        version: null,
        offers: [],
        reaches: { party: "pile", repository: "harness", path: name },
        sighted: null,
        kind: "party",
        summary: [{ text: name, tone: "strong", ticking: null, gauge: null, refers: null }],
        open: null,
        content: [{ block: "line", id: "said", version: null, offers: [], reaches: null, sighted: null, spans: [{ text: "said", tone: "plain", ticking: null, gauge: null, refers: null }] }],
    };
    const other: Fold = { ...party, id: "other", reaches: { party: "pile", repository: "harness", path: "other" }, summary: [{ text: "other", tone: "strong", ticking: null, gauge: null, refers: null }] };
    const { shell: opened, memory, parent } = shellOn([other, party]);
    try {
        await press(opened, ["G", "o", "t", "o", "<Esc>", "<Space>", "s"]);
        expect(opened.window?.role()).toBe("pick");
        const field = parent.querySelector<HTMLInputElement>(".lup-window-filter");
        expect(field).not.toBeNull();
        if (field === null) {
            return;
        }
        field.value = name.slice(0, 3);
        field.dispatchEvent(new Event("input"));
        field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
        expect(memory.draft.comments.map((each) => each.to)).toEqual([party.reaches]);
        expect(opened.window?.role()).toBeNull();
    } finally {
        opened.destroy();
        parent.remove();
    }
});

test("Every modal the page draws is the window: no module but its own draws a panel, a dialog or an overlay", () => {
    // The gate runs the promises from the page's directory, its sources under `src`.
    const sources = join(process.cwd(), "src");
    const drawing = /showPanel|showDialog|<dialog|role="dialog"|position: ?"?fixed/;
    const files = readdirSync(sources, { recursive: true, encoding: "utf8" }).filter(
        (file) => /\.tsx?$/.test(file) && !file.startsWith("generated") && !file.endsWith("promises.ts"),
    );
    const drawn = files.filter((file) => drawing.test(readFileSync(join(sources, file), "utf8")));
    expect(drawn).toEqual(["shell/window.ts"]);
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
