// The review: everything waiting for the operator laid out as one text to read
// and move through, their comments in it, each under the line it's on, and under
// each item what folds there: its context, and an approval's whole diff. Pure:
// the editor (`Review.tsx`) draws it, folds it and lets the comments be edited,
// and the host keeps the draft (`docs/dashboard.md`, *The review*).
import { since } from "./agents";
import type { components } from "./generated/api";

export type Item = components["schemas"]["Item"];
export type Draft = components["schemas"]["Draft"];
export type Comment = components["schemas"]["Comment"];
export type Quote = components["schemas"]["Quote"];
export type Context = components["schemas"]["Context"];

/** What the host answered, asked for more of an item than its own text: what it showed, or why it refused. */
export type Answered<T> = { shown: T } | { refused: string };

/** What the review shows of each item beyond its own text, by the item's number, once the host has answered: its context, and an approval's whole diff. */
export interface Around {
    contexts: Map<number, Answered<Context>>;
    diffs: Map<number, Answered<string>>;
}

/**
 * What a line under an item that isn't its own text shows: a fold's summary; a step of its context, the operator's
 * words, the agent's, a run of calls, or the call that made the item; a line of its whole diff; or why the host
 * showed none.
 */
export type Kind = "summary" | "you" | "agent" | "calls" | "anchor" | "diff" | "refused";

/** A line under an item that isn't its own text, so no comment is on it. */
export interface Aside extends Span {
    kind: Kind;
}

/** What folds under an item, folded by default: its context, or an approval's whole diff. It hides `from` to `to`, from the end of its summary line to the end of its last. */
export interface Fold extends Span {
    item: number;
    kind: "context" | "diff";
    summary: Span;
}

/** A stretch of the text, from its start to its end. */
export interface Span {
    from: number;
    to: number;
}

/** One line of an item's own text, where it's shown, and where it starts in that text. */
export interface Line extends Span {
    own: number;
}

/** One comment, where its lines are shown: `comment` is its place in the draft. */
export interface Block extends Span {
    comment: number;
}

/** One item, where it's shown: the banner of the group it opens, if it's the first of one; its header line, its own lines, and its comments among them; then the lines under it, and what of them folds. */
export interface Region {
    item: Item;
    banner: Span | null;
    header: Span;
    lines: Line[];
    blocks: Block[];
    asides: Aside[];
    folds: Fold[];
}

/** The review's text, and where each item is in it. */
export interface Laid {
    text: string;
    regions: Region[];
}

export const EMPTY: Draft = { comments: [], done: [], parked: [] };

/** Return an item's own text as the review shows it: a message's or a question's words with its decisions, an approval's question and summary. */
export function body(item: Item): string {
    const reason = item.reason;
    switch (reason.reason) {
        case "message":
            return reason.text;
        case "question": {
            const decisions = reason.decisions.map(
                (each, at) => `${at + 1}. ${each.text}\n   lean: ${each.lean}`,
            );
            return [reason.text, ...decisions].join("\n");
        }
        case "approval":
            return `${reason.text}\n${plain(reason.summary)}`;
        case "held":
            return `${reason.text}\n${reason.summary}`;
        case "answer":
            return reason.comment;
        case "review":
            return reason.comments.map((each) => each.text).join("\n");
    }
}

/** Return `text` without the terminal's colour codes git colours a diff with. */
export function plain(text: string): string {
    return text.replace(/\u001b\[[0-9;]*m/g, "");
}

/** One line under an item, and what it shows. */
export interface Row {
    kind: Kind;
    text: string;
}

/** What shows under an item's own text: an approval's whole diff, then the item's context, each its summary line with the lines that fold under it; or, where the host refused one, a line saying why. */
interface Under {
    kind: Fold["kind"];
    summary: Row;
    lines: Row[];
}

/** Say a run of calls in a line, each tool once with how many times in a row: `· called Bash ×2, Read`. */
export function calls(tools: string[]): string {
    const runs: { tool: string; times: number }[] = [];
    for (const tool of tools) {
        const last = runs.at(-1);
        if (last?.tool === tool) {
            last.times += 1;
        } else {
            runs.push({ tool, times: 1 });
        }
    }
    return `· called ${runs.map(({ tool, times }) => (times === 1 ? tool : `${tool} ×${times}`)).join(", ")}`;
}

/** Return an item's context as the lines it's shown in: each thing said after who said it, its own lines kept; each run of calls in one line; and the call that made the item, marked. */
export function steps(context: Context): Row[] {
    const shown: Row[] = [];
    let run: string[] = [];
    const ran = () => {
        if (run.length > 0) {
            shown.push({ kind: "calls", text: calls(run) });
            run = [];
        }
    };
    context.entries.forEach((entry, at) => {
        if (entry.kind === "called" && at !== context.anchor) {
            run.push(entry.tool);
            return;
        }
        ran();
        if (entry.kind === "called") {
            shown.push({ kind: "anchor", text: `→ called ${entry.tool} · this item` });
            return;
        }
        const who: Kind = entry.by === "operator" ? "you" : "agent";
        const said = entry.text.split("\n").map((line) => line.trimEnd()).filter((line) => line.trim() !== "");
        const indent = " ".repeat(who.length + 2);
        shown.push({ kind: who, text: `${who}:${said.length === 0 ? "" : ` ${said[0]}`}` });
        shown.push(...said.slice(1).map((line) => ({ kind: who, text: `${indent}${line}` })));
    });
    ran();
    return shown;
}

/** Say what an item's context holds: how many steps, and from whose words and how long before the item. */
function told(item: Item, context: Context): string {
    const count = `context · ${context.entries.length} ${context.entries.length === 1 ? "step" : "steps"}`;
    const first = context.entries[0];
    const yours = first?.kind === "said" && first.by === "operator";
    const before = first?.at == null ? "" : ` ${since(new Date(first.at), new Date(item.made))} before this item`;
    if (!yours && before === "") {
        return count;
    }
    return `${count}, from${yours ? " your words" : ""}${before}`;
}

/** Return what shows under an item's own text, of what the host has answered: an approval's whole diff, then the item's context. */
function beneath(item: Item, around: Around): Under[] {
    const shown: Under[] = [];
    const diff = around.diffs.get(item.number);
    if ((item.reason.reason === "approval" || item.reason.reason === "held") && diff !== undefined) {
        const whole = "shown" in diff ? plain(diff.shown).replace(/\n+$/, "") : "";
        const lines = whole === "" ? [] : whole.split("\n");
        shown.push({
            kind: "diff",
            summary:
                "shown" in diff
                    ? { kind: "summary", text: `whole diff · ${lines.length} ${lines.length === 1 ? "line" : "lines"}` }
                    : { kind: "refused", text: `no whole diff: ${diff.refused}` },
            lines: lines.map((text) => ({ kind: "diff", text })),
        });
    }
    const context = around.contexts.get(item.number);
    if (context !== undefined) {
        shown.push({
            kind: "context",
            summary:
                "shown" in context
                    ? { kind: "summary", text: told(item, context.shown) }
                    : { kind: "refused", text: `no context: ${context.refused}` },
            lines: "shown" in context ? steps(context.shown) : [],
        });
    }
    return shown;
}

/** Return the line of `text` an offset is on, counting from 0. */
function lineOf(starts: number[], offset: number): number {
    const found = starts.findLastIndex((each) => each <= offset);
    return Math.max(found, 0);
}

/** Return `items` in groups, each under its banner, the groups in the banners' order and the items in theirs. */
function grouped(items: Item[], banner: (item: Item) => string): Item[][] {
    const groups = new Map<string, Item[]>();
    for (const item of items) {
        const key = banner(item);
        groups.set(key, [...(groups.get(key) ?? []), item]);
    }
    return [...groups.keys()].sort().map((key) => groups.get(key) ?? []);
}

/**
 * Lay `items` out as one text: those to answer now first, then the parked ones, each in the group its banner names
 * (the agent that sent it), each under a header naming it, each comment of the draft on it under the line it's on:
 * a comment on a passage under the passage's last line, one on the item whole under its header. Under each item's
 * own text, what the host has answered of it: an approval's whole diff, then the item's context, each a summary line
 * with the lines that fold under it, or a line saying why the host showed none.
 */
export function laid(
    items: Item[],
    banner: (item: Item, parked: boolean) => string,
    header: (item: Item, parked: boolean) => string,
    draft: Draft,
    around: Around,
): Laid {
    const parked = draft.parked ?? [];
    const comments = draft.comments ?? [];
    const now = grouped(items.filter((each) => !parked.includes(each.number)), (item) => banner(item, false));
    const later = grouped(items.filter((each) => parked.includes(each.number)), (item) => banner(item, true));
    let text = "";
    const regions: Region[] = [];
    for (const group of [...now, ...later]) {
        group.forEach((item, at) => {
            const isParked = parked.includes(item.number);
            let opening: Span | null = null;
            if (at === 0) {
                const said = banner(item, isParked);
                opening = { from: text.length, to: text.length + said.length };
                text += `${said}\n`;
            }
            layItem(item, opening, isParked);
        });
    }
    return { text, regions };

    function layItem(item: Item, opening: Span | null, isParked: boolean): void {
        const own = body(item).split("\n");
        const starts = own.map((_, at) => own.slice(0, at).reduce((sum, line) => sum + line.length + 1, 0));
        const mine = comments.flatMap((comment, at) => (comment.item === item.number ? [{ comment, at }] : []));
        const under = (line: number | null) =>
            mine.filter(({ comment }) =>
                comment.quote == null ? line === null : line !== null && lineOf(starts, Math.max(comment.quote.end - 1, comment.quote.start)) === line,
            );
        const blocks: Block[] = [];
        const lines: Line[] = [];
        const writeBlocks = (line: number | null) => {
            for (const { comment, at } of under(line)) {
                const from = text.length;
                text += `${comment.text}\n`;
                blocks.push({ comment: at, from, to: from + comment.text.length });
            }
        };
        const head = header(item, isParked);
        const headFrom = text.length;
        text += `${head}\n`;
        writeBlocks(null);
        own.forEach((line, at) => {
            const from = text.length;
            text += `${line}\n`;
            lines.push({ from, to: from + line.length, own: starts[at] ?? 0 });
            writeBlocks(at);
        });
        const asides: Aside[] = [];
        const folds: Fold[] = [];
        const writeAside = (row: Row): Aside => {
            const from = text.length;
            text += `${row.text}\n`;
            const aside = { kind: row.kind, from, to: from + row.text.length };
            asides.push(aside);
            return aside;
        };
        for (const each of beneath(item, around)) {
            const summary = writeAside(each.summary);
            const last = each.lines.map(writeAside).at(-1);
            if (last !== undefined) {
                const shown = { from: summary.from, to: summary.to };
                folds.push({ item: item.number, kind: each.kind, summary: shown, from: summary.to, to: last.to });
            }
        }
        text += "\n";
        regions.push({
            item,
            banner: opening,
            header: { from: headFrom, to: headFrom + head.length },
            lines,
            blocks,
            asides,
            folds,
        });
    }
}

/** Where a region starts: at the banner of the group it opens, else at its header. */
function start(region: Region): number {
    return region.banner?.from ?? region.header.from;
}

/** Return the region `position` is in: the banner of the group it opens, its header, its lines, its comments, or the blank line after it. */
export function regionAt(regions: Region[], position: number): Region | undefined {
    return regions.find((each, at) => {
        const next = regions[at + 1];
        return position >= start(each) && (next === undefined || position < start(next));
    });
}

/** Return whether `position` is on a group's banner, which no comment is on. */
export function onBanner(region: Region, position: number): boolean {
    return region.banner !== null && position >= region.banner.from && position <= region.banner.to;
}

/** Return the comment shown at `position`, where it's in one; a comment's end counts, so an empty one can be typed in. */
export function blockAt(laidOut: Laid, position: number): Block | undefined {
    return laidOut.regions.flatMap((each) => each.blocks).find((each) => position >= each.from && position <= each.to);
}

/** Return the item's own line shown at `position`, where it's on one. */
export function lineAt(region: Region, position: number): Line | undefined {
    return region.lines.find((each) => position >= each.from && position <= each.to);
}

/** Return the line under an item that isn't its own text shown at `position`, where it's on one. */
export function asideAt(region: Region, position: number): Aside | undefined {
    return region.asides.find((each) => position >= each.from && position <= each.to);
}

/** Return the fold `position` is on: on its summary line or the lines it hides. */
export function foldAt(laidOut: Laid, position: number): Fold | undefined {
    return laidOut.regions
        .flatMap((each) => each.folds)
        .find((each) => position >= each.summary.from && position <= each.to);
}

/** Return what names a fold across layouts: its item's number and what it holds. */
export function foldKey(fold: Fold): string {
    return `${fold.item} ${fold.kind}`;
}

/** Return where a comment opened on the line at `position` goes: on that line of its item, or on the item whole from its header or an empty line; none outside every item, or on a line that isn't the item's own. */
export function opened(laidOut: Laid, position: number): Comment | undefined {
    const region = regionAt(laidOut.regions, position);
    if (region === undefined || onBanner(region, position) || asideAt(region, position) !== undefined) {
        return undefined;
    }
    const line = lineAt(region, position);
    const shown = line === undefined ? "" : laidOut.text.slice(line.from, line.to);
    if (line === undefined || shown === "") {
        return { item: region.item.number, quote: null, text: "" };
    }
    return {
        item: region.item.number,
        quote: { text: shown, start: line.own, end: line.own + shown.length },
        text: "",
    };
}

/** Return a comment on the passage `from` to `to` selects, counted in its item's own text; none where it isn't all inside one item's own lines. */
export function quoted(laidOut: Laid, from: number, to: number): Comment | undefined {
    const region = regionAt(laidOut.regions, from);
    const first = region === undefined ? undefined : lineAt(region, from);
    const last = region === undefined ? undefined : lineAt(region, Math.max(to - 1, from));
    if (region === undefined || first === undefined || last === undefined || to <= from) {
        return undefined;
    }
    const start = first.own + (from - first.from);
    const end = last.own + (Math.min(to, last.to) - last.from);
    const own = region.lines.map((each) => laidOut.text.slice(each.from, each.to)).join("\n");
    return { item: region.item.number, quote: { text: own.slice(start, end), start, end }, text: "" };
}

/** Return where in the text an offset of an item's own text is shown. */
export function shownAt(region: Region, offset: number): number {
    const line = [...region.lines].reverse().find((each) => each.own <= offset) ?? region.lines[0];
    return line === undefined ? region.header.to : Math.min(line.from + (offset - line.own), line.to);
}

/** Return `draft` with `number` in `list` if it wasn't, and out of it if it was. */
export function toggled(draft: Draft, list: "done" | "parked", number: number): Draft {
    const present = draft[list] ?? [];
    const next = present.includes(number) ? present.filter((each) => each !== number) : [...present, number];
    return { ...draft, [list]: next };
}

/** Return the items a draft answers: each with a comment that says something, or marked done, but the parked ones. */
export function covered(draft: Draft): number[] {
    const parked = draft.parked ?? [];
    const mentioned = [
        ...(draft.comments ?? []).filter((each) => each.text.trim() !== "").map((each) => each.item),
        ...(draft.done ?? []),
    ];
    return [...new Set(mentioned)].filter((each) => !parked.includes(each)).sort((a, b) => a - b);
}

/** Return `draft` without the comments that say nothing. */
export function pruned(draft: Draft): Draft {
    return { ...draft, comments: (draft.comments ?? []).filter((each) => each.text.trim() !== "") };
}
