// The window: the one place the page shows what isn't the document, under it, as vim's `:split` does, the document
// staying in view above with its cursor where it was. Every modal the page has is the window: the review of what the
// draft sends where (Ctrl+Enter), the picker of whom a comment reaches (Space s), and those to come (the palette of
// commands, Ctrl+K), so each is drawn and moved through alike. What it shows is a document of its own, drawn by a
// shell of its own as the page's is (its look, its margin, its folds), whose commands act for the page's shell; a
// picker narrows its list as a line at its top is typed into. Esc closes it.
//
// The status line is drawn here too: the page's one other line under the document. No other module draws a panel, a
// dialog or an overlay (`promises.ts` here holds the page to it).

import { StateEffect, StateField, type Extension } from "@codemirror/state";
import { showPanel, type EditorView, type Panel } from "@codemirror/view";

import type { Blocks, Comment, Delivered, Draft, JsonValue, Viewing } from "../generated/read";
import type { Shell, Source } from "./shell";

/** One of what a picker offers: what it's called, and what it stands for. */
export interface Choice {
    readonly name: string;
    readonly party: { [key: string]: JsonValue };
}

/** What the window is for: the review of the draft, or a picker. */
export type Role = "review" | "pick";

/** What the window shows while it's open. */
interface Showing {
    readonly role: Role;
    readonly title: string;
    readonly source: Given;
    /** For a picker: what it offers, what to do with what's chosen, and whether typing narrows it. */
    readonly picking: Picking | null;
}

interface Picking {
    readonly choices: readonly Choice[];
    readonly chosen: (choice: Choice) => void;
}

/** Makes a shell drawing the window's document, in `parent`, from `source`. */
export type Making = (parent: HTMLElement, source: Source) => Shell;

/** The window's own document: what it's given, answered as its root, and nothing kept as a draft. */
class Given implements Source {
    #blocks: Blocks;
    readonly #answered = new Set<(blocks: Blocks) => void>();

    constructor(blocks: Blocks) {
        this.#blocks = blocks;
    }

    /** Show `blocks` in place of what's shown. */
    set(blocks: Blocks): void {
        this.#blocks = blocks;
        for (const answered of this.#answered) {
            answered(blocks);
        }
    }

    watch(_viewing: Viewing, answered: (blocks: Blocks) => void): () => void {
        this.#answered.add(answered);
        answered(this.#blocks);
        return () => {
            this.#answered.delete(answered);
        };
    }

    write(_comment: Comment): void {}

    erase(_id: string): void {}

    send(): void {}

    drafts(_drafted: (draft: Draft) => void, _delivered: (delivered: Delivered) => void): () => void {
        return () => {};
    }

    reviews(_reviewed: (review: Blocks) => void): () => void {
        return () => {};
    }
}

/** Opens the window on what it shows, or closes it where none. */
const shown = StateEffect.define<Showing | null>();

/** Sets what the status line says; none clears it. */
export const say = StateEffect.define<string | null>();

/** What the page's status line last said: a command that found nothing to act on saying why, a send what it did. */
export const said = StateField.define<string | null>({
    create: () => null,
    update(value, transaction) {
        for (const effect of transaction.effects) {
            if (effect.is(say)) {
                return effect.value;
            }
        }
        return value;
    },
    provide: (field) =>
        showPanel.from(field, (text) =>
            text === null
                ? null
                : () => {
                      const dom = document.createElement("div");
                      dom.className = "lup-status";
                      dom.textContent = text;
                      return { dom, top: false };
                  },
        ),
});

/** Return the choices of `among` whose name holds `typed`, whatever its case. */
export function narrowed(among: readonly Choice[], typed: string): Choice[] {
    const wanted = typed.trim().toLowerCase();
    return among.filter((each) => each.name.toLowerCase().includes(wanted));
}

/** Return the lines a picker shows of `choices`: one each, keyed by where it is among `all`, so what's chosen is found again. */
function listed(choices: readonly Choice[], all: readonly Choice[], asking: string): Blocks {
    return {
        blocks: choices.map((choice) => ({
            block: "line",
            id: String(all.indexOf(choice)),
            version: null,
            offers: [],
            reaches: null,
            sighted: null,
            spans: [{ text: choice.name, tone: "strong", ticking: null, gauge: null, refers: null }],
        })),
        summary: [{ text: asking, tone: "plain", ticking: null, gauge: null, refers: null }],
        offers: [],
    };
}

/** The page's window, for the document's shell `owner`, its shell made by `making`. */
export class Window {
    readonly #owner: Shell;
    readonly #making: Making;
    #shell: Shell | null = null;
    /** The window's title while it's open, said again as what it shows changes. */
    #title: HTMLElement | null = null;
    /** The document's shell's own extensions, carrying the window's panel: in the document's editor, under its text. */
    readonly extension: Extension;

    constructor(owner: Shell, making: Making) {
        this.#owner = owner;
        this.#making = making;
        this.extension = StateField.define<Showing | null>({
            create: () => null,
            update(value, transaction) {
                for (const effect of transaction.effects) {
                    if (effect.is(shown)) {
                        return effect.value;
                    }
                }
                return value;
            },
            provide: (field) => showPanel.from(field, (showing) => (showing === null ? null : (view) => this.#panel(view, showing))),
        });
    }

    /** Return the shell drawing the window's document while it's open; none while it's closed. */
    shell(): Shell | null {
        return this.#shell;
    }

    /** Return what the window is for while it's open; none while it's closed. */
    role(): Role | null {
        return this.#owner.view.state.field(this.extension as StateField<Showing | null>, false)?.role ?? null;
    }

    /** Open the window on the review of what the draft sends where, `review` as the core tells it. */
    review(review: Blocks): void {
        this.#owner.view.dispatch({ effects: shown.of({ role: "review", title: titleOf(review), source: new Given(review), picking: null }) });
    }

    /** Show `review`, the draft's review as the core tells it again, where the window shows the review. */
    reviewed(review: Blocks): void {
        const showing = this.#owner.view.state.field(this.extension as StateField<Showing | null>, false);
        if (showing?.role === "review") {
            showing.source.set(review);
            if (this.#title !== null) {
                this.#title.textContent = titleOf(review);
            }
        }
    }

    /** Open the window on a picker asking `asking` among `choices`, handing the one chosen to `chosen` once it's closed. */
    pick(asking: string, choices: readonly Choice[], chosen: (choice: Choice) => void): void {
        this.#owner.view.dispatch({
            effects: shown.of({ role: "pick", title: asking, source: new Given(listed(choices, choices, asking)), picking: { choices, chosen } }),
        });
    }

    /** Close the window, the cursor back in the document where it was. */
    close(): void {
        if (this.role() === null) {
            return;
        }
        const focused = this.#shell?.view.hasFocus === true || document.activeElement?.closest(".lup-window") !== null;
        this.#owner.view.dispatch({ effects: shown.of(null) });
        if (focused) {
            this.#owner.view.focus();
        }
    }

    /** Draw the window: its title, the line typed into where it's a picker, and its document, drawn by a shell of its own. */
    #panel(_view: EditorView, showing: Showing): Panel {
        const dom = document.createElement("div");
        dom.className = `lup-window lup-window-${showing.role}`;
        const title = document.createElement("div");
        title.className = "lup-window-title";
        title.textContent = showing.title;
        this.#title = title;
        dom.append(title);
        const field = showing.picking === null ? null : document.createElement("input");
        if (field !== null) {
            field.className = "lup-window-filter";
            field.setAttribute("aria-label", showing.title);
            dom.append(field);
        }
        const body = document.createElement("div");
        body.className = "lup-window-body";
        dom.append(body);
        const shell = this.#making(body, showing.source);
        this.#shell = shell;
        // The window takes the keys where the document had them, as the key opening it was pressed there.
        const focused = this.#owner.view.hasFocus;
        if (field !== null && showing.picking !== null) {
            this.#typed(field, shell, showing.source, showing.picking, showing.title);
        }
        return {
            dom,
            top: false,
            mount: () => {
                if (focused) {
                    (field ?? shell.view).focus();
                }
            },
            destroy: () => {
                shell.destroy();
                if (this.#shell === shell) {
                    this.#shell = null;
                }
            },
        };
    }

    /** Let `field` narrow the picker's list as it's typed into, its arrows move along it, Enter choose and Esc close. */
    #typed(field: HTMLInputElement, shell: Shell, source: Given, picking: Picking, asking: string): void {
        const byId = new Map(picking.choices.map((choice, at) => [String(at), choice]));
        const moved = (by: number): void => {
            const doc = shell.view.state.doc;
            const line = doc.lineAt(shell.view.state.selection.main.head).number + by;
            if (line >= 1 && line <= doc.lines) {
                shell.go(doc.line(line).from);
            }
        };
        field.addEventListener("input", () => {
            source.set(listed(narrowed(picking.choices, field.value), picking.choices, asking));
            shell.go(0);
        });
        field.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                event.preventDefault();
                this.close();
            } else if (event.key === "ArrowDown" || (event.key === "n" && event.ctrlKey)) {
                event.preventDefault();
                moved(1);
            } else if (event.key === "ArrowUp" || (event.key === "p" && event.ctrlKey)) {
                event.preventDefault();
                moved(-1);
            } else if (event.key === "Enter") {
                event.preventDefault();
                const id = shell.lineId();
                const choice = id === null ? undefined : byId.get(id);
                this.close();
                if (choice !== undefined) {
                    picking.chosen(choice);
                }
            }
        });
    }
}

/** Return the window's title for `review`: what its summary says, else that the draft holds nothing. */
function titleOf(review: Blocks): string {
    const summary = review.summary.map((span) => span.text).join("");
    return `${summary === "" ? "the draft holds nothing" : summary}  ·  Ctrl+Enter sends, Space x holds back, Space d lets go, Esc closes`;
}
