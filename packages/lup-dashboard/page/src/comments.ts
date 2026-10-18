// What the review and a conversation share as laid-out text: the lines the
// operator's comments may be on, the comments written under them, the passages
// they quote, and how a step of a conversation is said. Pure: each view lays its
// own text out with these (`review.ts`, `conversation.ts`), and the editor they
// share (`editor.ts`) lets the comments be written.
import type { components } from "./generated/api";

export type Quote = components["schemas"]["Quote"];

/** A stretch of the text, from its start to its end. */
export interface Span {
    from: number;
    to: number;
}

/** One line of a text comments may be on, where it's shown, and where it starts in that text. */
export interface Line extends Span {
    own: number;
}

/** One comment, where its lines are shown: `comment` is its place in the draft. */
export interface Block extends Span {
    comment: number;
}

/** What folds, folded by default: it hides `from` to `to`, from the end of its summary line to the end of its last; `key` names it across layouts. */
export interface Folding extends Span {
    key: string;
    summary: Span;
}

/** One row of a thing said: its text, where its words start in it, and where they start in the words kept. */
export interface Spoken {
    text: string;
    words: number;
    own: number;
    /** Whether it's a blank line between paragraphs, which no comment is on. */
    blank: boolean;
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

/** Return the lines of `text` kept to show it: each without its trailing space; blank ones dropped, or, where `blanks`, kept one between paragraphs. */
export function kept(text: string, blanks: boolean): string[] {
    const lines = text.split("\n").map((line) => line.trimEnd());
    if (!blanks) {
        return lines.filter((line) => line.trim() !== "");
    }
    const shown: string[] = [];
    for (const line of lines) {
        const blank = line.trim() === "";
        if (!blank || (shown.length > 0 && shown.at(-1) !== "")) {
            shown.push(blank ? "" : line);
        }
    }
    return shown.at(-1) === "" ? shown.slice(0, -1) : shown;
}

/** Say one thing said after who said it: its first line after `who:`, the others set in under it, as `kept` keeps them. */
export function spoken(who: string, text: string, blanks: boolean): Spoken[] {
    const lines = kept(text, blanks);
    if (lines.length === 0) {
        return [{ text: `${who}:`, words: who.length + 1, own: 0, blank: true }];
    }
    const indent = " ".repeat(who.length + 2);
    let own = 0;
    return lines.map((line, at) => {
        const prefix = at === 0 ? `${who}: ` : indent;
        const row = { text: line === "" ? "" : `${prefix}${line}`, words: prefix.length, own, blank: line === "" };
        own += line.length + 1;
        return row;
    });
}

/** Return the line of a text an offset is on, by where each of its lines starts, counting from 0. */
export function lineOf(starts: number[], offset: number): number {
    const found = starts.findLastIndex((each) => each <= offset);
    return Math.max(found, 0);
}

/** Return where each line of `lines` starts in them joined. */
export function starts(lines: string[]): number[] {
    return lines.map((_, at) => lines.slice(0, at).reduce((sum, line) => sum + line.length + 1, 0));
}

/** Return the line, of those starting at `starts`, a comment's quote is shown under: the one its passage ends on; none for a comment on the whole. */
export function under(starts: number[], quote: Quote | null | undefined): number | null {
    return quote == null ? null : lineOf(starts, Math.max(quote.end - 1, quote.start));
}

/** Return the passage `from` to `to` selects, from its first line to its last, counted in the text `own` they're lines of; a start before the first line's words counts from them. */
export function passage(own: string, first: Line, last: Line, from: number, to: number): Quote {
    const start = first.own + Math.max(from - first.from, 0);
    const end = last.own + Math.max(Math.min(to, last.to) - last.from, 0);
    return { text: own.slice(start, end), start, end };
}

/** Return where in the text an offset of the text `lines` show is shown; `none` where no line is. */
export function shownIn(lines: Line[], offset: number, none: number): number {
    const line = [...lines].reverse().find((each) => each.own <= offset) ?? lines[0];
    return line === undefined ? none : Math.min(line.from + (offset - line.own), line.to);
}

/** Return the comments that say something. */
export function saying<C extends { text: string }>(comments: C[]): C[] {
    return comments.filter((each) => each.text.trim() !== "");
}
