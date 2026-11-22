// The shell's promises: what the operator can count on of the document as they move through it, fold it and type,
// while views answer again under them. Each runs on the shell itself, headless, its keys sent as a keyboard sends
// them, with no real time, so how loaded the machine is can't change what happens.

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import fc from "fast-check";
import { expect, test } from "vitest";

import type { Block, Blocks, Fold, Line, Markdown, Offer, Viewing } from "../generated/read";
import { every, foldKind, nodeAt, offsetOf, section } from "../document/tree";
import { blocks, fold } from "../testing/blocks";
import { press } from "../testing/keys";
import { Memory, looks } from "../testing/memory";
import { law, scenario, type Machine } from "../testing/promise";
import { quotedIn } from "./comments";
import { bindVim, vimBindings } from "./keymap";
import { hiddenOn } from "./markdown";
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
    ..."j k l h w b $ 0 gg G za zo zc zr zm zR zM zfn zfb i a A o O x e s S cw cc vls dd >> << ]n [n A*em* A**b** A`c` A-_".split(" ").map((typed) => [...typed]),
    ["<Tab>"],
    ["<S-Tab>"],
    ["<Esc>"],
    ["<C-[>"],
    ["<CR>"],
    ["<BS>"],
    ["<C-CR>"],
    ["u"],
    ["<C-r>"],
    [":w"],
    ...["fn", "fb", "Fn", "Fb", "fz", "c", "x", "d", "t"].map((typed) => ["<Space>", ...typed]),
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
    /** Each fold the outline shows, as the document's key for it, with the one holding it there and whether it's open. */
    readonly outlined: readonly { readonly key: string; readonly under: string | null; readonly open: boolean }[];
    /** Whether vim's cursor rests on a mark the Markdown hides, where its line shows a character it could rest on instead. */
    readonly onHidden: boolean;
}

/** Say whether `shell`'s cursor rests on a mark the Markdown hides, where its line shows a character it could rest on instead. */
function restsOnHidden(shell: Shell): boolean {
    const { state } = shell.view;
    const head = state.selection.main.head;
    const line = state.doc.lineAt(head);
    const hidden = hiddenOn(state, head);
    const within = (at: number) => hidden.some((each) => at >= each.from && at < each.to);
    let shows = false;
    for (let at = line.from; at < line.to; at++) {
        shows ||= !within(at);
    }
    return shows && within(head);
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
    const outline = shell.outline?.shell ?? null;
    const outlined =
        outline === null
            ? []
            : every(outline.document.root).flatMap((node) => {
                  if (node.block?.block !== "fold") {
                      return [];
                  }
                  const holder = node.parent?.block?.block === "fold" ? node.parent.block.id : null;
                  return [{ key: node.block.id, under: holder, open: outline.isOpen(node) }];
              });
    return { ...shell.state(), folds, margin, tree: shell.document.text(), outside, drafted, outlined, onHidden: restsOnHidden(shell) };
}

const shell: Machine<Running, Seen, Event> = {
    name: "the shell",
    start(by) {
        const memory = new Memory();
        memory.set(root, answer(by.any(blocks(2, kinds))));
        const parent = document.createElement("div");
        const aside = document.createElement("div");
        parent.append(aside);
        document.body.append(parent);
        return { shell: new Shell(parent, root, looks, memory, { aside }), memory, parent };
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

law(shell, "In Normal mode, vim's cursor never rests on a mark the Markdown hides, where its line shows a character to rest on", (step) => step.after.mode !== "normal" || !step.after.onHidden);

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
        sighted: null, standing: null,
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

law(shell, "The outline holds every fold of an outlined kind the document lays out, under the nearest outlined fold holding it, open as the document has it", (step) => {
    const after = step.after;
    const outlinedKinds = new Set(looks.folds.filter((each) => each.kind.outlined).map((each) => each.kind.name));
    const shown = after.folds.filter((fold) => outlinedKinds.has(fold.kind));
    if (JSON.stringify(after.outlined.map((each) => each.key)) !== JSON.stringify(shown.map((fold) => fold.key))) {
        return false;
    }
    const spans = new Map(shown.map((fold) => [fold.key, fold]));
    return after.outlined.every((each) => {
        const fold = spans.get(each.key);
        const holders = shown.filter((other) => fold !== undefined && other.first < fold.first && fold.last <= other.last);
        const nearest = holders.at(-1)?.key ?? null;
        return each.under === nearest && each.open === !after.closed.includes(each.key);
    });
});

/** Return a shell on `content`, its document's root answered from memory with the review at its top. */
function shellOn(content: Blocks["blocks"]): { shell: Shell; memory: Memory; parent: HTMLElement } {
    const memory = new Memory();
    memory.set(root, answer(content));
    const parent = document.createElement("div");
    const aside = document.createElement("div");
    const main = document.createElement("div");
    parent.append(aside, main);
    document.body.append(parent);
    return { shell: new Shell(main, root, looks, memory, { aside, page: parent }), memory, parent };
}

/** Press `key` as the browser's keyboard does, a key event on `shell`'s editor, which the page's panes hear first. */
function keyed(shell: Shell, key: string): void {
    shell.view.contentDOM.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
}

scenario("Moving in the outline takes the document to that fold, and the document's cursor marks its fold in the outline", async (by) => {
    const content = by.any(blocks(2, kinds).filter((made) => made.some((block) => block.block === "fold" && block.kind === "note")));
    const { shell: opened, parent } = shellOn(content);
    try {
        const outline = opened.outline?.shell ?? null;
        expect(outline).not.toBeNull();
        if (outline === null) {
            return;
        }
        const folds = every(outline.document.root).filter((node) => node.block?.block === "fold");
        expect(folds.length).toBeGreaterThan(0);
        const chosen = folds[by.any(fc.integer({ min: 0, max: Math.max(folds.length - 1, 0) }))];
        if (chosen === undefined || chosen.block === null) {
            return;
        }
        outline.go(offsetOf(chosen));
        opened.outline?.went();
        expect(opened.foldAt()?.key).toBe(chosen.block.id);
        await press(opened, ["G"]);
        const marked = nodeAt(outline.document.root, outline.view.state.selection.main.head);
        let around = opened.foldAt();
        while (around !== null && !(around.block?.block === "fold" && around.block.kind === "note")) {
            around = around.parent;
        }
        expect(marked.block?.id).toBe(around?.key ?? marked.block?.id);
    } finally {
        opened.destroy();
        parent.remove();
    }
});

scenario("Esc twice in Normal mode enters pane mode, an Esc leaving insert mode not counted, and h then Enter goes into the outline", async (by) => {
    const content = by.any(blocks(1, kinds).filter((made) => made.some((block) => block.block === "line")));
    const { shell: opened, parent } = shellOn(content);
    try {
        await press(opened, ["G", "o", "x"]);
        keyed(opened, "Escape");
        keyed(opened, "Escape");
        expect(opened.panes?.chosen()).toBeNull();
        keyed(opened, "Escape");
        expect(opened.panes?.chosen()).toBe("document");
        keyed(opened, "h");
        expect(opened.panes?.chosen()).toBe("outline");
        keyed(opened, "Enter");
        expect(opened.panes?.chosen()).toBeNull();
    } finally {
        opened.destroy();
        parent.remove();
    }
});

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

/** Put `inner`'s cursor on the line of the review that's the part of the draft of id `id`, under the place keyed `place`. */
function onPart(inner: Shell, place: string, id: string): boolean {
    const part = inner.document.node(`root/${place}/${id}`);
    expect(part).not.toBeNull();
    if (part === null) {
        return false;
    }
    // vim's own motions there need the page laid out, which the harness isn't.
    inner.go(offsetOf(part));
    return true;
}

scenario("Space x on a comment's line in the review keeps it back, so a send leaves it in the draft as it is, and Space d there sends it", async (by) => {
    const content = by.any(blocks(1, kinds).filter((made) => made.some((block) => block.block === "line")));
    const { shell: opened, memory, parent } = shellOn(content);
    try {
        await press(opened, ["G", "o", "k", "e", "e", "p", "<Esc>", "<C-CR>"]);
        const id = memory.draft.comments[0]?.id ?? "";
        if (!onPart(windowOf(opened), "to to what it's on", id)) {
            return;
        }
        await press(windowOf(opened), ["<Space>", "x"]);
        expect(memory.draft.comments.map((each) => each.held)).toEqual([true]);
        await press(windowOf(opened), ["<C-CR>"]);
        expect(memory.draft.comments.map((each) => [each.words, each.held])).toEqual([["keep", true]]);
        await press(opened, ["<C-CR>"]);
        const inner = windowOf(opened);
        const part = inner.document.node(`root/held/${id}`);
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

scenario("Space s on a comment sends it to the party chosen in the window among those the document shows, Enter choosing its line", async (by) => {
    const name = by.any(fc.constantFrom("port-plan", "frictions"));
    const party: Fold = {
        block: "fold",
        id: name,
        version: null,
        offers: [],
        reaches: { party: "pile", repository: "harness", path: name },
        sighted: null, standing: null,
        kind: "party",
        summary: [{ text: name, tone: "strong", ticking: null, gauge: null, refers: null }],
        open: null,
        content: [{ block: "line", id: "said", version: null, offers: [], reaches: null, sighted: null, standing: null, spans: [{ text: "said", tone: "plain", ticking: null, gauge: null, refers: null }] }],
    };
    const other: Fold = { ...party, id: "other", reaches: { party: "pile", repository: "harness", path: "other" }, summary: [{ text: "other", tone: "strong", ticking: null, gauge: null, refers: null }] };
    const { shell: opened, memory, parent } = shellOn([other, party]);
    try {
        await press(opened, ["G", "o", "t", "o", "<Esc>", "<Space>", "s"]);
        expect(opened.window?.role()).toBe("pick");
        const inner = windowOf(opened);
        const line = every(inner.document.root).find((node) => node.block?.block === "line" && node.head[0] === name);
        expect(line).not.toBeUndefined();
        if (line === undefined) {
            return;
        }
        // The party's line, as `/` and its name would find it: vim's search needs the page laid out, which the harness isn't.
        inner.go(offsetOf(line));
        await press(inner, ["<CR>"]);
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

scenario("Ctrl+K lists every command with its keys in the window, and Enter on one runs it, as zR there opens every fold", async (by) => {
    const content = by.any(blocks(2, kinds).filter((made) => made.some((block) => block.block === "fold")));
    const { shell: opened, parent } = shellOn(content);
    try {
        await press(opened, ["z", "M", "<C-k>"]);
        expect(opened.window?.role()).toBe("pick");
        const inner = windowOf(opened);
        const line = every(inner.document.root).find((node) => node.block?.block === "line" && (node.head[0] ?? "").startsWith("zR "));
        expect(line).not.toBeUndefined();
        if (line === undefined) {
            return;
        }
        inner.go(offsetOf(line));
        await press(inner, ["<CR>"]);
        expect(opened.window?.role()).toBeNull();
        expect(opened.state().closed).toEqual([]);
    } finally {
        opened.destroy();
        parent.remove();
    }
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
        sighted: null, standing: null,
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

/** Return a Markdown block saying `text`, keyed `id`. */
function written(id: string, text: string): Markdown {
    return { block: "markdown", id, version: null, offers: [], reaches: null, sighted: null, standing: null, text, tone: "plain" };
}

/** Return where the Markdown hides marks on the line `number` of `shell`'s text, from 1, as stretches from the line's start. */
function hiddenOnLine(shell: Shell, number: number): { from: number; to: number }[] {
    const line = shell.view.state.doc.line(number);
    return hiddenOn(shell.view.state, line.from).map((each) => ({ from: each.from - line.from, to: each.to - line.from }));
}

scenario("A Markdown block shows its constructs, the marks that write them hidden, and its text is what the view answered", async (by) => {
    const word = by.any(fc.constantFrom("a", "bc", "def"));
    const text = `# ${word}\nsome *${word}* and **${word}**, \`${word}\`, [${word}](https://x.y)`;
    const opened = new Shell(document.createElement("div"), root, looks, single(answer([written("m", text)])));
    try {
        expect(opened.state().text).toBe(text);
        expect(hiddenOnLine(opened, 1)).toEqual([{ from: 0, to: 2 }]);
        const second = opened.view.state.doc.line(2).text;
        const hidden = hiddenOnLine(opened, 2).map((each) => second.slice(each.from, each.to));
        expect(hidden).toEqual(["*", "*", "**", "**", "`", "`", "[", "]", "(", "https://x.y", ")"]);
    } finally {
        opened.destroy();
    }
});

scenario("l pressed again and again along a line of Markdown goes past every hidden mark, one character shown at a time, to the line's last", async (by) => {
    const pieces = by.any(fc.array(fc.constantFrom("a", "*b*", "**c**", "`d`", "[e](f)", "~~g~~", " "), { minLength: 1, maxLength: 6 }));
    const text = `x${pieces.join("")}y`;
    const opened = new Shell(document.createElement("div"), root, looks, single(answer([written("m", text)])));
    try {
        const hidden = hiddenOnLine(opened, 1);
        const shown = [...text].flatMap((_, at) => (hidden.some((each) => at >= each.from && at < each.to) ? [] : [at]));
        const visited = [opened.view.state.selection.main.head];
        for (let pressed = 0; pressed < text.length; pressed++) {
            await press(opened, ["l"]);
            const head = opened.view.state.selection.main.head;
            if (head !== visited.at(-1)) {
                visited.push(head);
            }
        }
        expect(visited).toEqual(shown);
    } finally {
        opened.destroy();
    }
});

scenario("In a comment, the line the cursor is on shows its marks to be edited, and the comment's other lines hide theirs", async (by) => {
    const word = by.any(fc.constantFrom("a", "bc"));
    const opened = new Shell(document.createElement("div"), root, looks, single(answer([written("m", "text")])));
    try {
        await press(opened, ["o", ..."*", ...word, "*", "<CR>", "*", ...word, "*"]);
        expect(opened.state().mode).toBe("insert");
        expect(hiddenOnLine(opened, 3)).toEqual([]);
        expect(hiddenOnLine(opened, 2)).toEqual([
            { from: 0, to: 1 },
            { from: word.length + 1, to: word.length + 2 },
        ]);
    } finally {
        opened.destroy();
    }
});

scenario("Enter in a comment opens a line at the indentation of the one it's on, with no bullet; Tab nests it under the item above, Shift+Tab takes it out; an indentation left empty goes as the comment ends", async () => {
    const opened = new Shell(document.createElement("div"), root, looks, single(answer([written("m", "text")])));
    try {
        await press(opened, ["o", ..."- a", "<CR>"]);
        expect(opened.view.state.doc.line(3).text).toBe("");
        await press(opened, [..."- b", "<Tab>"]);
        expect(opened.view.state.doc.line(3).text).toBe("  - b");
        await press(opened, ["<CR>"]);
        expect(opened.view.state.doc.line(4).text).toBe("  ");
        await press(opened, ["<S-Tab>"]);
        expect(opened.view.state.doc.line(4).text).toBe("");
        await press(opened, ["<Tab>"]);
        expect(opened.view.state.doc.line(4).text).toBe("  ");
        await press(opened, ["<Esc>"]);
        expect(opened.state().mode).toBe("normal");
        expect(opened.state().text.split("\n").filter((line) => line.length > 0 && line.trim() === "")).toEqual([]);
    } finally {
        opened.destroy();
    }
});

scenario("A table's rows stay a line each, as the view answered them, its columns lined up by what's drawn beside its cells", async (by) => {
    const wide = by.any(fc.constantFrom("ccc", "dddd"));
    const text = `| a | bb |\n|---|---|\n| ${wide} | e |`;
    const parent = document.createElement("div");
    document.body.append(parent);
    const opened = new Shell(parent, root, looks, single(answer([written("m", text)])));
    try {
        expect(opened.state().text).toBe(text);
        const pads = [...parent.querySelectorAll(".lup-md-pad")].map((each) => each.textContent);
        expect(pads.length).toBeGreaterThan(0);
        const rows = [...parent.querySelectorAll(".cm-line")].map((each) => each.textContent ?? "");
        expect(new Set(rows.map((row) => row.length)).size).toBe(1);
    } finally {
        opened.destroy();
        parent.remove();
    }
});

/** What a block offers under each of `verbs`: a command of the root view's module, given the block's id. */
function offersOf(id: string, verbs: readonly string[]): Offer[] {
    return verbs.map((verb) => ({ command: `${verb}-it`, module: null, given: { id }, verb, says: `${verb} ${id}`, draws: null }));
}

/** A line saying `text`, of id `id`. */
function lineOf(id: string, text: string): Line {
    return { block: "line", id, version: null, offers: [], reaches: null, sighted: null, standing: null, spans: [{ text, tone: "plain", ticking: null, gauge: null, refers: null }] };
}

/** An open fold of the kind `note`, of id `id`, holding `content`. */
function foldOf(id: string, content: Block[]): Fold {
    return {
        block: "fold",
        id,
        version: null,
        offers: [],
        reaches: null,
        sighted: null,
        standing: null,
        kind: "note",
        summary: [{ text: `the fold ${id}`, tone: "plain", ticking: null, gauge: null, refers: null }],
        open: true,
        content,
    };
}

/** Return `made` with each block offering what `pick` says for it, folds' given content among them. */
function offering(made: readonly Block[], pick: (id: string) => readonly string[]): Block[] {
    return made.map((block) => {
        const offered = { ...block, offers: offersOf(block.id, pick(block.id)) };
        return offered.block === "fold" && Array.isArray(offered.content) ? { ...offered, content: offering(offered.content, pick) } : offered;
    });
}

scenario("Space d marks done on the innermost block at the cursor that offers it, Space x puts decline in its place there, and the second Ctrl+Enter sends what's marked", async (by) => {
    const item: Line = { ...lineOf("item", "an item"), offers: offersOf("item", ["done"]) };
    const body: Markdown = { block: "markdown", id: "body", version: null, offers: [], reaches: null, sighted: null, standing: null, text: by.any(fc.constantFrom("the body", "a\nb")), tone: "plain" };
    const concern: Fold = { ...foldOf("c", [item, body]), offers: offersOf("c", ["done", "decline"]) };
    const { shell: opened, memory, parent } = shellOn([concern]);
    try {
        const at = (key: string): void => {
            const node = opened.document.node(key);
            expect(node).not.toBeNull();
            opened.go(node === null ? 0 : offsetOf(node));
        };
        at("root/c/item");
        await press(opened, ["<Space>", "d"]);
        expect(memory.draft.marks.map((each) => [each.on.block, each.offer.verb])).toEqual([["item", "done"]]);
        await press(opened, ["<Space>", "d"]);
        expect(memory.draft.marks).toEqual([]);
        at("root/c/body");
        await press(opened, ["<Space>", "d"]);
        expect(memory.draft.marks.map((each) => [each.on.block, each.offer.verb])).toEqual([["c", "done"]]);
        const id = memory.draft.marks[0]?.id;
        await press(opened, ["<Space>", "x"]);
        expect(memory.draft.marks.map((each) => [each.id, each.on.block, each.offer.verb])).toEqual([[id, "c", "decline"]]);
        await press(opened, ["<Space>", "t"]);
        expect(memory.draft.marks.map((each) => each.offer.verb)).toEqual(["decline"]);
        await press(opened, ["<C-CR>"]);
        expect(opened.window?.role()).toBe("review");
        expect(memory.sent).toEqual([]);
        await press(windowOf(opened), ["<C-CR>"]);
        expect(memory.sent.map((each) => [each.on.block, each.offer.command])).toEqual([["c", "decline-it"]]);
        expect(memory.draft.marks).toEqual([]);
    } finally {
        opened.destroy();
        parent.remove();
    }
});

scenario("Space x on a mark's line in the review keeps it back from the send, and Space t there sends it the next time", async (by) => {
    const verb = by.any(fc.constantFrom("done", "decline"));
    const item: Line = { ...lineOf("item", "an item"), offers: offersOf("item", [verb]) };
    const { shell: opened, memory, parent } = shellOn([item]);
    try {
        opened.go(offsetOf(opened.document.node("root/item") ?? opened.document.root));
        await press(opened, ["<Space>", verb === "done" ? "d" : "x", "<C-CR>"]);
        const id = memory.draft.marks[0]?.id ?? "";
        if (!onPart(windowOf(opened), "marked", id)) {
            return;
        }
        await press(windowOf(opened), ["<Space>", "x", "<C-CR>"]);
        expect(memory.sent).toEqual([]);
        expect(memory.draft.marks.map((each) => each.held)).toEqual([true]);
        await press(opened, ["<C-CR>"]);
        if (!onPart(windowOf(opened), "held", id)) {
            return;
        }
        await press(windowOf(opened), ["<Space>", "t", "<C-CR>"]);
        expect(memory.sent.map((each) => each.id)).toEqual([id]);
    } finally {
        opened.destroy();
        parent.remove();
    }
});

/** The shell over blocks each offering some of the core's verbs, which Space and their keys mark. */
const marking: Machine<Running, { readonly marks: readonly { readonly block: string; readonly verb: string; readonly offered: boolean }[] }, Event> = {
    name: "the shell, its blocks offering verbs",
    start(by) {
        const memory = new Memory();
        const made = offering(by.any(blocks(2, kinds)), () => by.any(fc.subarray(["done", "decline", "toggle"])));
        memory.set(root, answer(made));
        const parent = document.createElement("div");
        document.body.append(parent);
        return { shell: new Shell(parent, root, looks, memory), memory, parent };
    },
    events: fc
        .constantFrom(..."j k G gg za zR zM zfn".split(" ").map((typed) => [...typed]), ...["d", "x", "t", "fn", "Fn", "Fb"].map((typed) => ["<Space>", ...typed]), ["<Esc>"])
        .map((typed): Event => ({ keys: typed })),
    async apply(running, event) {
        if ("keys" in event) {
            await press(running.shell, event.keys);
        }
    },
    state(running) {
        return {
            marks: running.memory.draft.marks.map((each) => {
                // The block the core acts on at the send: the first of the mark's id in its view's answer.
                const node = quotedIn(running.shell.document.root, each.on);
                return {
                    block: node?.key ?? "",
                    verb: each.offer.verb,
                    offered: node?.block?.offers.some((offer) => offer.verb === each.offer.verb) === true,
                };
            }),
        };
    },
    end(running) {
        running.shell.destroy();
        running.parent.remove();
    },
};

law(marking, "A verb is only ever marked on a block that offers it, and a block holds one mark at most", (step) =>
    step.after.marks.every((each) => each.offered) && new Set(step.after.marks.map((each) => each.block)).size === step.after.marks.length,
);
