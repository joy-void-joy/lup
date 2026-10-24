// What's still open in the review's layout, each a switch the operator tries
// before one is chosen (`docs/dashboard.md`, *The review*): how an agent's
// drawers are said under its banner, how the overview of every agent sits
// beside the review, and how a subagent's group is set apart from its parent's.
// Read from the address's query (`?labels=side&overview=zoom&frame=panel`) and
// changed from the palette (Ctrl+K, "Layout: …"), which writes the query back,
// so a reload keeps them. The page's own: neither the draft nor the host knows
// of them. Pure.

/** How an agent's drawers are said under its banner: a line each, each folding in place; or side by side, labels on one line, each pulled out below it. */
export type LabelsTrial = "lines" | "side";

/** How the overview of every agent and item sits: a pane beside the review, collapsible; or the review itself zoomed out to its headers. */
export type OverviewTrial = "pane" | "zoom";

/** How a subagent's group is set apart from its parent's: its banner a lighter band; or its whole group a panel, tinted. */
export type FrameTrial = "band" | "panel";

export interface Trials {
    labels: LabelsTrial;
    overview: OverviewTrial;
    frame: FrameTrial;
}

/** What the page shows with no switch in its address. */
export const DEFAULTS: Trials = { labels: "lines", overview: "pane", frame: "band" };

const LABELS: LabelsTrial[] = ["lines", "side"];
const OVERVIEWS: OverviewTrial[] = ["pane", "zoom"];
const FRAMES: FrameTrial[] = ["band", "panel"];

/** Return `value` where it's one of `among`, else `fallback`. */
function oneOf<T extends string>(value: string | null, among: readonly T[], fallback: T): T {
    return value !== null && (among as readonly string[]).includes(value) ? (value as T) : fallback;
}

/** Return the switches an address's query says, the defaults for any it leaves out or says wrong. */
export function trialsOf(search: string): Trials {
    const query = new URLSearchParams(search);
    return {
        labels: oneOf(query.get("labels"), LABELS, DEFAULTS.labels),
        overview: oneOf(query.get("overview"), OVERVIEWS, DEFAULTS.overview),
        frame: oneOf(query.get("frame"), FRAMES, DEFAULTS.frame),
    };
}

/** Return `search` saying `trials`, its other parameters kept, each switch left at its default left out. */
export function searchOf(trials: Trials, search: string): string {
    const query = new URLSearchParams(search);
    const set = (name: string, value: string, fallback: string) => (value === fallback ? query.delete(name) : query.set(name, value));
    set("labels", trials.labels, DEFAULTS.labels);
    set("overview", trials.overview, DEFAULTS.overview);
    set("frame", trials.frame, DEFAULTS.frame);
    const said = query.toString();
    return said === "" ? "" : `?${said}`;
}

/** One choice the palette offers: what it says, the switches it makes, and whether they're made already. */
export interface Choice {
    id: string;
    said: string;
    made: (trials: Trials) => Trials;
    chosen: (trials: Trials) => boolean;
}

/** A choice of one switch's value. */
function choice<K extends keyof Trials>(name: K, value: Trials[K], said: string): Choice {
    return {
        id: `${name}-${value}`,
        said,
        made: (each) => ({ ...each, [name]: value }),
        chosen: (each) => each[name] === value,
    };
}

/** The palette's choices, a switch at a time. */
export const CHOICES: Choice[] = [
    choice("labels", "lines", "drawers: a line each under the banner, each folding in place"),
    choice("labels", "side", "drawers: side by side under the banner, each pulled out below"),
    choice("overview", "pane", "overview: a pane beside the review, \\ hides it"),
    choice("overview", "zoom", "overview: the review zoomed out to its headers, \\ zooms"),
    choice("frame", "band", "subagents: a lighter band"),
    choice("frame", "panel", "subagents: a tinted panel"),
    { id: "defaults", said: "the defaults", made: () => DEFAULTS, chosen: (each) => searchOf(each, "") === "" },
];

/** Say the switches in a few words, for the bar. */
export function trialsSaid(trials: Trials): string {
    return [
        trials.labels === "lines" ? "drawers a line each" : "drawers side by side",
        trials.overview === "pane" ? "overview pane" : "overview zoom",
        trials.frame === "band" ? "subagents banded" : "subagents paneled",
    ].join(" · ");
}
