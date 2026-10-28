// How the review's views look, as each repository's process says it and the host lists it (`Listed.looks`), lup's
// default declaration's standing in for a repository whose process hasn't said (`Listed.standing`): the kinds of fold,
// each drawer's among them, the tones, and the drawers and banner parts each repository's agents have, the core's
// first (`docs/declaration.md`, *Views and blocks*). Merged across repositories into one table, since the review is
// one buffer with one set of keys: a kind is known by its name, the first to declare it keeping it; a later kind
// taking a letter an earlier one took keeps its colour and its level, but not the letter, said under the review, its
// folds left to the generic fold keys. The page holds no kind of its own: until the listing is read it knows none.
// Applied as it's merged (`adopt`): each kind's colour a CSS variable and class, each tone a class, and what the keys
// read of the kinds (`kinds`, `kindOf`), which vim's keys, the margin and the fold keys look up as they act.
import type { components } from "./generated/api";

export type Looks = components["schemas"]["Looks"];
export type Drawn = components["schemas"]["Drawn"];
export type Bannered = components["schemas"]["Bannered"];
export type Tone = components["schemas"]["Tone"];
type Declared = components["schemas"]["FoldKind"];

/**
 * One kind of fold as the page's keys know it: its name, the letter `zf` and Space `z` `f` take after them (none where
 * another kind took it first), what its folds are called together and the one the cursor is in, the level `zr` and
 * `zm` open and close it at, how it opens, its colour, whether Space `z` `f` reaches it, whether it holds its scope
 * whole, whether one folded says how many lines it hides, and whether it's a drawer's, which `]` and `[` and its letter
 * go to.
 */
export interface Kind {
    name: string;
    letter: string | null;
    called: string;
    one: string;
    level: number;
    opens: "together" | "back" | "deep";
    colour: string;
    chord: boolean;
    whole: boolean;
    counts: boolean;
    drawer: boolean;
}

/** The looks merged: every kind, every tone, each repository's drawers and banner parts, and what was refused, each said once. */
export interface Merged {
    kinds: Kind[];
    tones: Tone[];
    /** The drawers under the banner of an agent of `repository`, by its git directory, in the order they're laid out. */
    drawers: (repository: string) => Drawn[];
    /** The parts of the banner of an agent of `repository`, in the order they're said. */
    banners: (repository: string) => Bannered[];
    refused: string[];
}

export const UNLOOKED: Merged = { kinds: [], tones: [], drawers: () => [], banners: () => [], refused: [] };

/** Return the kind of fold a drawer is, named for its view: folded under its summary line under the banner, its scope whole. */
function drawerKind(drawn: Drawn): Declared {
    const place = drawn.place;
    return { name: drawn.view, letter: place.letter, called: place.called, one: place.called, level: 0, opens: "together", colour: place.colour, chord: true, whole: true, counts: true };
}

/** Return the last part of a path: a repository's name, as the page says it. */
function named(path: string): string {
    const name = path.split("/").filter((each) => each !== "").at(-1) ?? path;
    return name.endsWith(".git") ? name.slice(0, -".git".length) : name;
}

/**
 * Return the looks of every repository merged, `standing` first, then each repository's in the order the host lists
 * them: each kind by its name, the first to declare it keeping it, a drawer's after the folds of its looks; a later one
 * of another name taking a letter already taken keeps no letter, which `refused` says; the kinds outermost first, by
 * their level, in that order within one; each tone by its name, the first keeping it; each repository's drawers and
 * banner parts its own, or the stand-in's where it has none.
 */
export function merged(looks: Readonly<Record<string, Looks>>, standing: Looks): Merged {
    const kinds = new Map<string, Kind>();
    const letters = new Map<string, string>();
    const tones = new Map<string, Tone>();
    const refused: string[] = [];
    const take = (declared: Declared, whose: string | null, drawer: boolean) => {
        if (kinds.has(declared.name)) {
            return;
        }
        const holder = letters.get(declared.letter);
        if (holder !== undefined && whose !== null) {
            refused.push(
                `${named(whose)}'s fold kind \`${declared.name}\` takes the letter ${declared.letter}, which \`${holder}\` has: za, zr and zm reach its folds, ${declared.letter} doesn't.`,
            );
        }
        const letter = holder === undefined ? declared.letter : null;
        if (letter !== null) {
            letters.set(letter, declared.name);
        }
        kinds.set(declared.name, {
            name: declared.name,
            letter,
            called: declared.called,
            one: declared.one,
            level: declared.level,
            opens: declared.opens,
            colour: declared.colour,
            chord: declared.chord,
            whole: declared.whole,
            counts: declared.counts,
            drawer,
        });
    };
    const read = (each: Looks, whose: string | null) => {
        for (const declared of each.folds ?? []) {
            take(declared, whose, false);
        }
        for (const drawn of each.drawers ?? []) {
            take(drawerKind(drawn), whose, true);
        }
        for (const tone of each.tones ?? []) {
            if (!tones.has(tone.name)) {
                tones.set(tone.name, tone);
            }
        }
    };
    read(standing, null);
    for (const [repository, each] of Object.entries(looks)) {
        read(each, repository);
    }
    const own = (repository: string): Looks => looks[repository] ?? standing;
    return {
        kinds: [...kinds.values()].sort((a, b) => a.level - b.level),
        tones: [...tones.values()],
        drawers: (repository) => own(repository).drawers ?? [],
        banners: (repository) => own(repository).banners ?? [],
        refused,
    };
}

/** What's merged now, which the keys, the margin and the fold keys read as they act. */
let current: Merged = UNLOOKED;

/** Return what's merged now: every kind, tone, drawer and banner part known. */
export function adopted(): Merged {
    return current;
}

/** Return every kind of fold known now, in the order declared, the core's first. */
export function kinds(): readonly Kind[] {
    return current.kinds;
}

/** Return what's known now of the kind of fold named `name`; none for a kind none declares. */
export function kindOf(name: string | undefined): Kind | undefined {
    return name === undefined ? undefined : current.kinds.find((each) => each.name === name);
}

/** Return the kind of fold the letter `letter` names now; none where none takes it. */
export function lettered(letter: string): Kind | undefined {
    return current.kinds.find((each) => each.letter === letter);
}

/** Return the colour a tone is drawn in, as a CSS colour of the page's palette, and its weight, through the tones it takes its look from. */
function look(tone: Tone, tones: ReadonlyMap<string, Tone>, seen: Set<string> = new Set()): { colour: string | null; weight: string | null } {
    const like = tone.like == null || seen.has(tone.like) ? undefined : tones.get(tone.like);
    seen.add(tone.name);
    const taken = like === undefined ? { colour: null, weight: null } : look(like, tones, seen);
    return { colour: tone.colour ?? taken.colour, weight: tone.weight ?? taken.weight };
}

/** Return `name` as CSS writes it in a selector or a variable's name: each character but a letter, a digit, `-` and `_` escaped by its code. */
function ident(name: string): string {
    return name.replace(/[^A-Za-z0-9_-]/g, (char) => `\\${(char.codePointAt(0) ?? 0).toString(16)} `);
}

/** Return the CSS the looks are drawn by: each kind's colour as a variable, its class, and the bar beside what a fold of its sets off; each tone's class, its colour and weight. */
export function styled(looks: Merged): string {
    const rules: string[] = [];
    const variables = looks.kinds.map((each) => `--fold-${ident(each.name)}: var(--${ident(each.colour)});`);
    rules.push(`:root { ${variables.join(" ")} }`);
    for (const each of looks.kinds) {
        const name = ident(each.name);
        rules.push(`.fold-${name}, .buffer .cm-editor .cm-foldPlaceholder.fold-${name} { color: var(--fold-${name}); }`);
        rules.push(`.buffer .cm-line.barred-${name} { border-left: 2px solid var(--fold-${name}); }`);
    }
    const tones = new Map(looks.tones.map((each) => [each.name, each]));
    for (const tone of looks.tones) {
        const { colour, weight } = look(tone, tones);
        const said = [colour === null ? null : `color: var(--${ident(colour)});`, weight === "bold" ? "font-weight: 700;" : weight === "dim" ? "opacity: 0.7;" : null];
        rules.push(`.tone-${ident(tone.name)} { ${said.filter((each) => each !== null).join(" ")} }`);
    }
    return rules.join("\n");
}

/** Take `looks` as what's merged now, and draw the page by it: its CSS in a style element of its own, written again where it changed. */
export function adopt(looks: Merged): void {
    current = looks;
    if (typeof document === "undefined") {
        return;
    }
    const found = document.getElementById("lup-looks");
    const style = found ?? document.head.appendChild(Object.assign(document.createElement("style"), { id: "lup-looks" }));
    const css = styled(looks);
    if (style.textContent !== css) {
        style.textContent = css;
    }
}
