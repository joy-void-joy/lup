// The picker: a list at the bottom of the page to choose one of several by typing, as Space s chooses whom a comment
// reaches. What it offers is the core's: the parties the document shows, each a fold of the `party` kind naming whom a
// comment on it reaches (`Shown.reaches`), called by its summary. Typing narrows the list to those whose name holds
// what's typed, the arrows move along it, Enter chooses, and Esc leaves everything as it was.

import { StateEffect, StateField } from "@codemirror/state";
import { EditorView, showPanel, type Panel } from "@codemirror/view";

import type { JsonValue } from "../generated/read";
import { every, foldKind } from "../document/tree";
import type { Shell } from "./shell";

/** One of what the picker offers: what it's called, and the party it stands for, as its block names it. */
export interface Choice {
    readonly name: string;
    readonly party: { [key: string]: JsonValue };
}

/** What the picker is open for: what it offers, what it's asked, and what to do with what's chosen. */
interface Picking {
    readonly asking: string;
    readonly choices: readonly Choice[];
    readonly chosen: (choice: Choice) => void;
}

/** Opens the picker, or closes it where none. */
const pick = StateEffect.define<Picking | null>();

/** The picker, while it's open. */
export const picking = StateField.define<Picking | null>({
    create: () => null,
    update(value, transaction) {
        for (const effect of transaction.effects) {
            if (effect.is(pick)) {
                return effect.value;
            }
        }
        return value;
    },
    provide: (field) => showPanel.from(field, (open) => (open === null ? null : (view) => panel(view, open))),
});

/** Return the parties `shell`'s document shows, each once, in the order it shows them, called by their summary. */
export function parties(shell: Shell): Choice[] {
    const seen = new Set<string>();
    return every(shell.document.root).flatMap((node) => {
        const reaches = node.block?.reaches ?? null;
        if (foldKind(node) !== "party" || reaches === null || node.block?.block !== "fold") {
            return [];
        }
        const key = JSON.stringify(reaches);
        if (seen.has(key)) {
            return [];
        }
        seen.add(key);
        const name = node.block.summary[0]?.text.trim() ?? key;
        return [{ name, party: reaches as { [key: string]: JsonValue } }];
    });
}

/** Open the picker in `view`, asking `asking` among `choices`, handing the one chosen to `chosen`. */
export function open(view: EditorView, asking: string, choices: readonly Choice[], chosen: (choice: Choice) => void): void {
    view.dispatch({ effects: pick.of({ asking, choices, chosen }) });
}

/** Return the choices of `among` whose name holds `typed`, whatever its case. */
export function narrowed(among: readonly Choice[], typed: string): Choice[] {
    const wanted = typed.trim().toLowerCase();
    return among.filter((each) => each.name.toLowerCase().includes(wanted));
}

/** Draw the picker: what it asks, the field typed in, and the choices it narrows to, the one Enter takes marked. */
function panel(view: EditorView, open: Picking): Panel {
    const dom = document.createElement("div");
    dom.className = "lup-picker";
    const asking = document.createElement("div");
    asking.className = "lup-picker-asking";
    asking.textContent = open.asking;
    const field = document.createElement("input");
    field.className = "lup-picker-field";
    field.setAttribute("aria-label", open.asking);
    const list = document.createElement("ol");
    list.className = "lup-picker-list";
    dom.append(asking, field, list);
    let at = 0;
    let shown: Choice[] = [...open.choices];
    const draw = (): void => {
        shown = narrowed(open.choices, field.value);
        at = Math.min(at, Math.max(shown.length - 1, 0));
        list.replaceChildren(
            ...shown.map((choice, index) => {
                const item = document.createElement("li");
                item.textContent = choice.name;
                item.className = index === at ? "lup-picker-at" : "";
                return item;
            }),
        );
    };
    const close = (): void => {
        view.dispatch({ effects: pick.of(null) });
        view.focus();
    };
    field.addEventListener("input", draw);
    field.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            event.preventDefault();
            close();
        } else if (event.key === "ArrowDown" || (event.key === "n" && event.ctrlKey)) {
            event.preventDefault();
            at = Math.min(at + 1, shown.length - 1);
            draw();
        } else if (event.key === "ArrowUp" || (event.key === "p" && event.ctrlKey)) {
            event.preventDefault();
            at = Math.max(at - 1, 0);
            draw();
        } else if (event.key === "Enter") {
            event.preventDefault();
            const choice = shown[at];
            close();
            if (choice !== undefined) {
                open.chosen(choice);
            }
        }
    });
    draw();
    return {
        dom,
        top: false,
        mount: () => {
            field.focus();
        },
    };
}
