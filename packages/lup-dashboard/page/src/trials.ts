// Layout trials: where things sit in the review, each an independent switch, so
// the operator can try any combination live and choose before one is built for
// good. Read from the address's query (`?header=cursor-stack&outline=margin&drawers=sticky&frame=band&nest=on`)
// and changed from the palette (Ctrl+K, "Layout: …"), which writes the query
// back, so a reload keeps them. The page's own: neither the draft nor the host
// knows of them. Pure.

/** Where the header over the review is, and what it follows. */
export type HeaderTrial =
    /** Today's: one line over the review naming where the cursor is. */
    | "cursor"
    /** A stack following the view, as VS Code's sticky scroll: the headers of the scopes the top of the view is inside, pinned while their own lines are scrolled off. */
    | "stack"
    /** The stack, and a status line at the bottom, where vim keeps its own: the cursor's place and the counts. */
    | "stack-status"
    /** Today's line naming where the cursor is, on top, and the stack following the view under it. */
    | "cursor-stack";

/** Where the outline is: none, a pane beside the review, or the review's margin, line for line. */
export type OutlineTrial = "off" | "pane" | "margin";

/** Where an agent's drawers are. */
export type DrawersTrial =
    /** Today's: footers at the group's end. */
    | "footer"
    /** Under the banner, as labels that pull each out below them, or a line each. */
    | "row"
    /** Under the banner, pinned there in the header stack too. */
    | "stack"
    /** Footers at the group's end, pinned at the bottom of the view while it's inside the group, as the stack is at its top. */
    | "sticky";

/** How a group's drawers are said where they're labels: side by side on one line, or one on top of the other. */
export type LabelsTrial = "side" | "lines";

/** How an agent's group is framed: today's banner alone; or folding whole, its ends ruled, its banner a band of colour, or a box. */
export type FrameTrial = "off" | "band" | "box";

export interface Trials {
    header: HeaderTrial;
    outline: OutlineTrial;
    drawers: DrawersTrial;
    labels: LabelsTrial;
    /** Each subagent's group laid out under its parent's, after the parent's items and drawers, set in. */
    nest: boolean;
    frame: FrameTrial;
}

/** Today's layout: what the page shows with no switch in its address. */
export const TODAY: Trials = { header: "cursor", outline: "off", drawers: "footer", labels: "side", nest: false, frame: "off" };

const HEADERS: HeaderTrial[] = ["cursor", "stack", "stack-status", "cursor-stack"];
const OUTLINES: OutlineTrial[] = ["off", "pane", "margin"];
const DRAWER_TRIALS: DrawersTrial[] = ["footer", "row", "stack", "sticky"];
const LABELS: LabelsTrial[] = ["side", "lines"];
const FRAMES: FrameTrial[] = ["off", "band", "box"];

/** Return `value` where it's one of `among`, else `fallback`. */
function oneOf<T extends string>(value: string | null, among: readonly T[], fallback: T): T {
    return value !== null && (among as readonly string[]).includes(value) ? (value as T) : fallback;
}

/** Return the switches an address's query says, today's for any it leaves out or says wrong; `outline=on`, the first round's word, is the pane. */
export function trialsOf(search: string): Trials {
    const query = new URLSearchParams(search);
    const outline = query.get("outline");
    return {
        header: oneOf(query.get("header"), HEADERS, TODAY.header),
        outline: outline === "on" ? "pane" : oneOf(outline, OUTLINES, TODAY.outline),
        drawers: oneOf(query.get("drawers"), DRAWER_TRIALS, TODAY.drawers),
        labels: oneOf(query.get("labels"), LABELS, TODAY.labels),
        nest: query.get("nest") === "on",
        frame: oneOf(query.get("frame"), FRAMES, TODAY.frame),
    };
}

/** Return `search` saying `trials`, its other parameters kept, each switch left at today's left out. */
export function searchOf(trials: Trials, search: string): string {
    const query = new URLSearchParams(search);
    const set = (name: string, value: string, today: string) => (value === today ? query.delete(name) : query.set(name, value));
    set("header", trials.header, TODAY.header);
    set("outline", trials.outline, TODAY.outline);
    set("drawers", trials.drawers, TODAY.drawers);
    set("labels", trials.labels, TODAY.labels);
    set("nest", trials.nest ? "on" : "off", "off");
    set("frame", trials.frame, TODAY.frame);
    const said = query.toString();
    return said === "" ? "" : `?${said}`;
}

/** Return whether the header has a stack following the view. */
export function stacked(trials: Trials): boolean {
    return trials.header !== "cursor";
}

/** Return whether the drawers are under the banner, as labels or a line each, in the buffer as they are in the stack too. */
export function rowed(trials: Trials): boolean {
    return trials.drawers === "row" || trials.drawers === "stack";
}

/** Return whether each group folds whole under its banner: where it's framed, or nested, which a fold makes plain. */
export function grouped(trials: Trials): boolean {
    return trials.frame !== "off" || trials.nest;
}

/** One choice the palette offers: what it says, the switches it makes, and whether they're made already. */
export interface Choice {
    id: string;
    said: string;
    made: (trials: Trials) => Trials;
    chosen: (trials: Trials) => boolean;
}

/** A choice of one switch's value. */
function choice<K extends keyof Trials>(name: K, value: Trials[K], said: string, also: (trials: Trials) => Partial<Trials> = () => ({})): Choice {
    return {
        id: `${name}-${String(value)}`,
        said,
        made: (each) => ({ ...each, [name]: value, ...also(each) }),
        chosen: (each) => each[name] === value,
    };
}

/**
 * The palette's choices, a switch at a time. The drawers as a line of the stack turn the stack on, and the header
 * without a stack puts them back under the banner, since that line is the stack's.
 */
export const CHOICES: Choice[] = [
    choice("header", "cursor", "header: one line, following the cursor (today)", (each) => (each.drawers === "stack" ? { drawers: "row" } : {})),
    choice("header", "stack", "header: a stack following the view"),
    choice("header", "stack-status", "header: a stack following the view, a status line at the bottom"),
    choice("header", "cursor-stack", "header: the cursor's line on top, the stack following the view under it"),
    choice("outline", "off", "outline: none (today)"),
    choice("outline", "pane", "outline: a pane on the left"),
    choice("outline", "margin", "outline: in the margin, line for line"),
    choice("drawers", "footer", "drawers: footers at the group's end (today)"),
    choice("drawers", "row", "drawers: under the banner"),
    choice("drawers", "stack", "drawers: under the banner, pinned in the header stack", (each) => (each.header === "cursor" ? { header: "stack" } : {})),
    choice("drawers", "sticky", "drawers: footers, pinned at the view's bottom while it's in the group"),
    choice("labels", "side", "drawers' labels: side by side"),
    choice("labels", "lines", "drawers' labels: one per line"),
    choice("nest", true, "subagents: nested under their parent"),
    choice("nest", false, "subagents: beside their parent (today)"),
    choice("frame", "off", "groups: today's banner"),
    choice("frame", "band", "groups: framed, folding whole, the banner a band"),
    choice("frame", "box", "groups: framed, folding whole, the banner a box"),
    { id: "today", said: "today's, every switch off", made: () => TODAY, chosen: (each) => searchOf(each, "") === "" },
];

/** Say the switches in a few words, for the bar: `today` where none is on. */
export function trialsSaid(trials: Trials): string {
    const said = [
        ...(trials.header === "stack" ? ["stack"] : trials.header === "stack-status" ? ["stack + status"] : trials.header === "cursor-stack" ? ["line + stack"] : []),
        ...(trials.outline === "pane" ? ["outline"] : trials.outline === "margin" ? ["outline in the margin"] : []),
        ...(trials.drawers === "row" ? ["drawers under the banner"] : trials.drawers === "stack" ? ["drawers in the stack"] : trials.drawers === "sticky" ? ["drawers pinned below"] : []),
        ...(trials.drawers !== "footer" && trials.labels === "lines" ? ["a line each"] : []),
        ...(trials.nest ? ["nested"] : []),
        ...(trials.frame === "off" ? [] : [`framed (${trials.frame})`]),
    ];
    return said.length === 0 ? "today" : said.join(" · ");
}
