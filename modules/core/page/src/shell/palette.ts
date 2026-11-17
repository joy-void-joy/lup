// The page's palette: the first lup's dark one, which the second lup's page drew in too. Claude Code's
// `dark-daltonized` colours beside VS Code's high-contrast dark theme, each text colour at 7:1 or more on the black it
// sits on. Blue says good where other themes use green, and red says bad. Structure comes from borders and bars, and
// emphasis from outlines rather than fills.
//
// Every colour is a CSS variable, `--lup-<name>`, set on the page's root as it starts (`painted`). What a module may
// name (a tone's, a fold kind's or a mark kind's colour) is keyed by the core's `Colour`, so a colour the core adds
// fails the type check here until the palette gives it a value.

import type { Colour } from "../generated/read";

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

/** Set every colour of the palette on `root`, as `--lup-<name>`. */
export function painted(root: HTMLElement): void {
    for (const [name, value] of [...Object.entries(colours), ...Object.entries(chrome)]) {
        root.style.setProperty(`--lup-${name}`, value);
    }
}
