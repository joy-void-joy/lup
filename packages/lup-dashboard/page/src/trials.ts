// Layout trials: where things sit in the review, each an independent switch, so
// the operator can try any combination live and choose before one is built for
// good. Read from the address's query (`?header=stack&outline=on&drawers=row&nest=on`)
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
    | "stack-status";

/** Where an agent's drawers are. */
export type DrawersTrial =
    /** Today's: footers at the group's end. */
    | "footer"
    /** A compact row under the banner, each drawer a label that pulls it out below. */
    | "row"
    /** The row, pinned under the banner as a line of the header stack. */
    | "stack";

export interface Trials {
    header: HeaderTrial;
    /** A narrow pane on the left mirroring the review: repositories, agents, their items, drawers and files. */
    outline: boolean;
    drawers: DrawersTrial;
    /** Each subagent's group laid out under its parent's, after the parent's items and drawers, its banner set in. */
    nest: boolean;
}

/** Today's layout: what the page shows with no switch in its address. */
export const TODAY: Trials = { header: "cursor", outline: false, drawers: "footer", nest: false };

const HEADERS: HeaderTrial[] = ["cursor", "stack", "stack-status"];
const DRAWER_TRIALS: DrawersTrial[] = ["footer", "row", "stack"];

/** Return the switches an address's query says, today's for any it leaves out or says wrong. */
export function trialsOf(search: string): Trials {
    const query = new URLSearchParams(search);
    const header = query.get("header") as HeaderTrial | null;
    const drawers = query.get("drawers") as DrawersTrial | null;
    return {
        header: header !== null && HEADERS.includes(header) ? header : TODAY.header,
        outline: query.get("outline") === "on",
        drawers: drawers !== null && DRAWER_TRIALS.includes(drawers) ? drawers : TODAY.drawers,
        nest: query.get("nest") === "on",
    };
}

/** Return `search` saying `trials`, its other parameters kept, each switch left at today's left out. */
export function searchOf(trials: Trials, search: string): string {
    const query = new URLSearchParams(search);
    const set = (name: string, value: string, today: string) => (value === today ? query.delete(name) : query.set(name, value));
    set("header", trials.header, TODAY.header);
    set("outline", trials.outline ? "on" : "off", "off");
    set("drawers", trials.drawers, TODAY.drawers);
    set("nest", trials.nest ? "on" : "off", "off");
    const said = query.toString();
    return said === "" ? "" : `?${said}`;
}

/** Return whether the header is a stack following the view. */
export function stacked(trials: Trials): boolean {
    return trials.header !== "cursor";
}

/** Return whether the drawers are a row under the banner, in the buffer, as they are in the stack too. */
export function rowed(trials: Trials): boolean {
    return trials.drawers !== "footer";
}

/** One choice the palette offers: what it says, the switches it makes, and whether they're made already. */
export interface Choice {
    id: string;
    said: string;
    made: (trials: Trials) => Trials;
    chosen: (trials: Trials) => boolean;
}

/**
 * The palette's choices, a switch at a time. The drawers as a line of the stack turn the stack on, and the header
 * following the cursor puts them back in a row, since that line is the stack's.
 */
export const CHOICES: Choice[] = [
    {
        id: "header-cursor",
        said: "header: one line, following the cursor (today)",
        made: (each) => ({ ...each, header: "cursor", drawers: each.drawers === "stack" ? "row" : each.drawers }),
        chosen: (each) => each.header === "cursor",
    },
    { id: "header-stack", said: "header: a stack following the view", made: (each) => ({ ...each, header: "stack" }), chosen: (each) => each.header === "stack" },
    {
        id: "header-stack-status",
        said: "header: a stack following the view, a status line at the bottom",
        made: (each) => ({ ...each, header: "stack-status" }),
        chosen: (each) => each.header === "stack-status",
    },
    { id: "outline-on", said: "outline: a pane on the left", made: (each) => ({ ...each, outline: true }), chosen: (each) => each.outline },
    { id: "outline-off", said: "outline: none (today)", made: (each) => ({ ...each, outline: false }), chosen: (each) => !each.outline },
    { id: "drawers-footer", said: "drawers: footers at the group's end (today)", made: (each) => ({ ...each, drawers: "footer" }), chosen: (each) => each.drawers === "footer" },
    { id: "drawers-row", said: "drawers: a row under the banner", made: (each) => ({ ...each, drawers: "row" }), chosen: (each) => each.drawers === "row" },
    {
        id: "drawers-stack",
        said: "drawers: a row pinned in the header stack",
        made: (each) => ({ ...each, drawers: "stack", header: each.header === "cursor" ? "stack" : each.header }),
        chosen: (each) => each.drawers === "stack",
    },
    { id: "nest-on", said: "subagents: nested under their parent", made: (each) => ({ ...each, nest: true }), chosen: (each) => each.nest },
    { id: "nest-off", said: "subagents: beside their parent (today)", made: (each) => ({ ...each, nest: false }), chosen: (each) => !each.nest },
    { id: "today", said: "today's, every switch off", made: () => TODAY, chosen: (each) => searchOf(each, "") === "" },
];

/** Say the switches in a few words, for the bar: `today` where none is on. */
export function trialsSaid(trials: Trials): string {
    const said = [
        ...(trials.header === "stack" ? ["stack"] : trials.header === "stack-status" ? ["stack + status"] : []),
        ...(trials.outline ? ["outline"] : []),
        ...(trials.drawers === "row" ? ["drawers in a row"] : trials.drawers === "stack" ? ["drawers in the stack"] : []),
        ...(trials.nest ? ["nested"] : []),
    ];
    return said.length === 0 ? "today" : said.join(" · ");
}
