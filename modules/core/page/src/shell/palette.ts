// The page's palette: the first lup's dark one, which the second lup's page drew in too. Claude Code's
// `dark-daltonized` colours beside VS Code's high-contrast dark theme, each text colour at 7:1 or more on the black it
// sits on. Blue says good where other themes use green, and red says bad. Structure comes from borders and bars, and
// emphasis from outlines rather than fills.
//
// Every colour is a CSS variable, `--lup-<name>`, set on the page's root as it starts (`painted`). What a module may
// name (a tone's, a fold kind's or a mark kind's colour) is keyed by the core's `Colour`, so a colour the core adds
// fails the type check here until the palette gives it a value.

import type { Colour, Standing } from "../generated/read";

/** The colours a module may name, each reading at 7:1 or more on the page's black. */
export const colours: Readonly<Record<Colour, string>> = {
    fg: "#ffffff",
    muted: "#b3b3b3",
    link: "#2facff",
    ok: "#53a9ff",
    err: "#ff7c7c",
    warn: "#ffcc00",
    info: "#99ccff",
    purple: "#b691ff",
    cyan: "#66cccc",
    orange: "#ff9933",
};

/** The page's own colours, which no module names. */
export const chrome = {
    /** The page's background. */
    bg: "#000000",
    /** What floats over the page: a panel, a palette. */
    float: "#0c141f",
    /** A window's frame. */
    border: "#6fc3df",
    /** Where the keys go: Normal mode's cursor, a focused control's outline. */
    focus: "#f38518",
    /** The page's own selection, outside the editor. */
    "sel-bg": "#f3f518",
    "sel-fg": "#000000",
    /** The editor's selection, lightening what's under it. */
    selection: "rgb(38, 79, 120)",
    /** A line a change adds, and one it removes. */
    "add-bg": "#001b29",
    "del-bg": "#3d0100",
    /** The margin's edge. */
    rule: "#1d3a44",
} as const;

/**
 * What a colour means wherever the page draws it, each one of the palette's, so one thing reads in one colour
 * everywhere: a comment's lines, the passage it quotes, its mark in the margin and a closed fold's count of them alike.
 */
export const meanings = {
    /** What the operator wrote and what it's on. */
    comment: "warn",
    /** What keeps something written from going as it is: lines it quotes that changed, a send that kept it back. */
    trouble: "err",
    /** How a block stands for the operator (`Shown.standing`): waiting on them, new to them, done, held back. */
    waiting: "orange",
    new: "link",
    done: "muted",
    held: "warn",
} as const satisfies Record<string, Colour>;

/** The glyph each way a block can stand for the operator is drawn with, in its meaning's colour, wherever it shows. */
export const standings: Readonly<Record<Standing, string>> = {
    waiting: "◆",
    new: "●",
    done: "✓",
    held: "‖",
};

/** Set every colour of the palette on `root`, as `--lup-<name>`, and each meaning as the colour it's drawn in. */
export function painted(root: HTMLElement): void {
    for (const [name, value] of [...Object.entries(colours), ...Object.entries(chrome)]) {
        root.style.setProperty(`--lup-${name}`, value);
    }
    for (const [meaning, colour] of Object.entries(meanings)) {
        root.style.setProperty(`--lup-${meaning}`, `var(--lup-${colour})`);
    }
}
