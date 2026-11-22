// The window: the one place the page shows what isn't the document, under it, as vim's `:split` does, the document
// staying in view above with its cursor where it was. Every modal the page has is the window: the review of what the
// draft sends where (Ctrl+Enter), the picker of whom a comment reaches (Space s), and those to come (the palette of
// commands, Ctrl+K), so each is drawn and moved through alike. What it shows is a document of its own, drawn by a
// shell of its own as the page's is (its look, its margin, its folds), whose commands act for the page's shell, and
// which is moved through and searched as the document is (`/`, `n`); in a picker, Enter chooses the line the cursor is
// on. Esc closes it.
//
// The status line is drawn here too: the page's one other line under the document. No other module draws a panel, a
// dialog or an overlay (`promises.ts` here holds the page to it).

import { StateEffect, StateField, type Extension } from "@codemirror/state";
import { showPanel, type EditorView, type Panel } from "@codemirror/view";

import type { Blocks } from "../generated/read";
import { Given } from "./given";
import type { Shell, Source } from "./shell";

/** One of what a picker offers: what it's called, and what it stands for. */
export interface Choice<T> {
    readonly name: string;
    readonly value: T;
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
    /** What each line says, in order. */
    readonly names: readonly string[];
    /** Hand on what the line at `at` stands for. */
    readonly choose: (at: number) => void;
}

/** Makes a shell drawing the window's document, in `parent`, from `source`. */
export type Making = (parent: HTMLElement, source: Source) => Shell;

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

/** Return the lines a picker shows of `names`: one each, keyed by where it is among them, so what's chosen is found again. */
function listed(names: readonly string[], asking: string): Blocks {
    return {
        blocks: names.map((name, at) => ({
            block: "line",
            id: String(at),
            version: null,
            offers: [],
            reaches: null,
            sighted: null, standing: null,
            spans: [{ text: name, tone: "strong", ticking: null, gauge: null, refers: null }],
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

    /** Open the window on a picker asking `asking` among `choices`, handing what the one chosen stands for to `chosen` once it's closed. */
    pick<T>(asking: string, choices: readonly Choice<T>[], chosen: (value: T) => void): void {
        const names = choices.map((choice) => choice.name);
        const choose = (at: number): void => {
            const choice = choices[at];
            if (choice !== undefined) {
                chosen(choice.value);
            }
        };
        this.#owner.view.dispatch({
            effects: shown.of({
                role: "pick",
                title: `${asking}  ·  Enter chooses, / searches, Esc closes`,
                source: new Given(listed(names, asking)),
                picking: { names, choose },
            }),
        });
    }

    /** Choose what the line of id `id` stands for, where the window is a picker: close it, and hand it what it was asked for. */
    choose(id: string | null): boolean {
        const picking = this.#owner.view.state.field(this.extension as StateField<Showing | null>, false)?.picking ?? null;
        const at = picking === null || id === null ? undefined : new Map(picking.names.map((_, index) => [String(index), index])).get(id);
        if (picking === null || at === undefined) {
            return false;
        }
        this.close();
        picking.choose(at);
        return true;
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
        const body = document.createElement("div");
        body.className = "lup-window-body";
        dom.append(body);
        const shell = this.#making(body, showing.source);
        this.#shell = shell;
        // The window takes the keys where the document had them, as the key opening it was pressed there.
        const focused = this.#owner.view.hasFocus;
        return {
            dom,
            top: false,
            mount: () => {
                if (focused) {
                    shell.view.focus();
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
}

/** Return the window's title for `review`: what its summary says, else that the draft holds nothing. */
function titleOf(review: Blocks): string {
    const summary = review.summary.map((span) => span.text).join("");
    return `${summary === "" ? "the draft holds nothing" : summary}  ·  Ctrl+Enter sends what's ticked, Space d ticks, Space x unticks, Space h either, Esc closes`;
}
