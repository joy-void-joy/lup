// Where the operator's comments are, each anchored to a block of a view the review shows, by the block's id, the
// lines of it the comment is on and the version they were written on (`Quote`; `docs/dashboard.md`, *The review*):
// what the review lays each comment under as the block changes, following the block's own lines from one layout to
// the next, and what says a comment is outdated, where the lines it quotes aren't what stands under it. And the ids
// what's written is kept by. Pure.
import { hunks, type Hunk } from "./comments";
import type { components } from "./generated/api";

export type Quote = components["schemas"]["Quote"];

/**
 * A block's lines as the review laid them out, and what they are: `version`, a hash of them, which moves whenever what
 * the block shows does, what a comment is followed by; and the block's own version, where it gives one, as git names a
 * file's content, which a comment on it records.
 */
export interface Lines {
    version: string;
    lines: readonly string[];
    given?: string | null;
}

/** Where a comment is laid out on its block: the block, the version of its lines, and the first and last of them it's on. */
export interface Placement {
    block: string;
    version: string;
    first: number;
    last: number;
}

/** Where a comment goes on its block as laid out now: the first and last of its lines it's on, and whether those aren't the lines it quotes. */
export interface Placed {
    first: number;
    last: number;
    outdated: boolean;
}

/** Return a short hash of `lines`, the version of a block that gives none: the same lines, the same version. */
export function hashed(lines: readonly string[]): string {
    // FNV-1a over the lines, each followed by a line break, in 32 bits.
    let hash = 0x811c9dc5;
    for (const line of lines) {
        for (let at = 0; at < line.length; at += 1) {
            hash ^= line.charCodeAt(at);
            hash = Math.imul(hash, 0x01000193);
        }
        hash ^= 10;
        hash = Math.imul(hash, 0x01000193);
    }
    return `h${(hash >>> 0).toString(36)}`;
}

/** Return a block's lines as laid out, their version a hash of them (`Lines`), and the block's own version, `given`. */
export function linesOf(lines: readonly string[], given: string | null = null): Lines {
    return { version: hashed(lines), lines, given };
}

/**
 * Return where line `line` of a block is once its lines are changed by `made` (`hunks`), from one version to the next:
 * moved with the lines before it, where it's kept; where it's among lines replaced, the line of what replaces them at
 * its place, or their last where fewer replace them; where it's among lines removed with nothing for them, the line
 * before them, or the first where there's none.
 */
export function mappedLine(line: number, made: readonly Hunk[]): number {
    let shift = 0;
    for (const each of made) {
        if (line < each.from) {
            break;
        }
        if (line >= each.to) {
            shift += each.until - each.into - (each.to - each.from);
            continue;
        }
        if (each.until > each.into) {
            return each.into + Math.min(line - each.from, each.until - each.into - 1);
        }
        return Math.max(each.into - 1, 0);
    }
    return line + shift;
}

/** Return whether `lines` hold `quoted` from `first` on, in order. */
function standing(lines: readonly string[], quoted: readonly string[], first: number): boolean {
    return quoted.length > 0 && quoted.every((each, at) => lines[first + at] === each);
}

/**
 * Return where a comment quoting `quote` goes on its block, laid out now as `now`: where it was laid out last
 * (`before`, as the block then stood), followed through the block's change since, its lines' own diff; else, as the
 * review is first laid out, where it was written, where the lines it quotes stand there; else where they stand nearest
 * it; else where it was written, its last line kept within the block. Outdated where the lines under it aren't those
 * it quotes.
 */
export function placed(quote: Quote, now: Lines, before: { placement: Placement; lines: Lines } | null): Placed {
    const quoted = quote.lines ?? [];
    const length = Math.max(quoted.length, 1);
    const lines = now.lines;
    const last = Math.max(lines.length - 1, 0);
    const outdated = (first: number) => !standing(lines, quoted, first);
    const at = (first: number, end: number): Placed => {
        const from = Math.min(Math.max(first, 0), last);
        const to = Math.min(Math.max(end, from), last);
        return { first: from, last: to, outdated: outdated(from) };
    };
    if (before !== null && before.placement.version === before.lines.version) {
        if (before.lines.version === now.version) {
            return at(before.placement.first, before.placement.last);
        }
        const made = hunks([...before.lines.lines], [...lines]);
        return at(mappedLine(before.placement.first, made), mappedLine(before.placement.last, made));
    }
    const written = quote.line ?? 0;
    if (!outdated(written)) {
        return at(written, written + length - 1);
    }
    const nearest = nearestStanding(lines, quoted, written);
    if (nearest !== null) {
        return at(nearest, nearest + length - 1);
    }
    return at(written, written + length - 1);
}

/** Return the line nearest `near` from which `lines` hold `quoted`, the first of two as near; none where they're nowhere. */
function nearestStanding(lines: readonly string[], quoted: readonly string[], near: number): number | null {
    if (quoted.length === 0) {
        return null;
    }
    let found: number | null = null;
    for (let first = 0; first + quoted.length <= lines.length; first += 1) {
        if (standing(lines, quoted, first) && (found === null || Math.abs(first - near) < Math.abs(found - near))) {
            found = first;
        }
    }
    return found;
}

/**
 * Return the quote of the passage from `start` to `end`, counted in lines `first` to `last` of block `block` joined, as
 * it's laid out now (`now`), recording the block's own version where it gives one: what the agent reads of it, `text`.
 */
export function quoting(block: string, now: Lines, first: number, last: number, start: number, end: number, text: string): Quote {
    return { text, block, version: now.given ?? now.version, line: first, lines: now.lines.slice(first, last + 1), start, end };
}

/** Return where the passage `quote` quotes ends in the last of its lines: its end, less the lines before that one and their breaks. */
export function endInLast(quote: Quote): number {
    const before = quote.lines.slice(0, -1).reduce((at, each) => at + each.length + 1, 0);
    return quote.end - before;
}

/** Return the id of what's written that has none, kept from before what's written had ids: its kind and its place among them, the same each time the draft is read until it's kept again with its ids. */
export function keptId(kind: "comment" | "letter" | "remark", at: number): string {
    return `kept ${kind} ${at}`;
}

/** Return a new id for what's being written, unlike any other: random, from the browser's own source, which a page on plain http has too. */
export function newId(): string {
    const bytes = new Uint8Array(9);
    crypto.getRandomValues(bytes);
    return [...bytes].map((each) => each.toString(16).padStart(2, "0")).join("");
}
