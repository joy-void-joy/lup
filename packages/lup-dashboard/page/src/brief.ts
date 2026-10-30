// What the page says on one row: the top bar's words, the line under the review, and what's said after a key, each
// in a sentence, its whole a key away (`g<`, the panel of what was said whole; `docs/dashboard.md`, *The keys*). A line
// that wrapped pushed the review down, and one listing forty numbers said nothing a count doesn't. The reply, and what
// sending it did, are said from their parts as the page made them, never from their words, a line and its whole from
// the same parts; anything else said, a refusal's prose among it, is cut at its first sentence. Pure.
import { cited } from "./comments";

/**
 * One part of the reply, or of what sending it did, as the page knows it: what's done, to what. The line under the
 * review and the top bar count them (`partsSaid`); `g<` says each whole (`partSaid`).
 */
export type ReplyPart =
    /** Something done to items, by their numbers, `read @64, @65`: `then` is said after them. */
    | { kind: "items"; done: string; numbers: readonly number[]; then?: string }
    /** A thread marked, `@reader read`: read, settled or declined. */
    | { kind: "thread"; name: string; done: string }
    /** What reaches a party, `to lup-impl/parser: a message, comments on @62`. */
    | { kind: "to"; who: string; what: readonly string[] }
    /** What's said as it is, on one line as whole: a view's mark, what came of a switch, a refusal. */
    | { kind: "said"; text: string };

/** Say `part` whole, every number of it named. */
export function partSaid(part: ReplyPart): string {
    switch (part.kind) {
        case "items":
            return `${part.done} ${part.numbers.map(cited).join(", ")}${part.then ?? ""}`;
        case "thread":
            return `@${part.name} ${part.done}`;
        case "to":
            return `to ${part.who}: ${part.what.join(", ")}`;
        case "said":
            return part.text;
    }
}

/**
 * Say `parts` on one line, between `between`: two or more items done alike counted, `read 3 items`, one named; and two
 * or more threads marked alike, `@reader read` and `@auth read`, as `2 threads read`, said where the first of them was.
 */
export function partsSaid(parts: readonly ReplyPart[], between: string = " · "): string {
    const threads = new Map<string, number>();
    for (const part of parts) {
        if (part.kind === "thread") {
            threads.set(part.done, (threads.get(part.done) ?? 0) + 1);
        }
    }
    const said = new Set<string>();
    return parts
        .flatMap((part) => {
            if (part.kind === "items" && part.numbers.length > 1) {
                return [`${part.done} ${part.numbers.length} items${part.then ?? ""}`];
            }
            const count = part.kind === "thread" ? (threads.get(part.done) ?? 0) : 0;
            if (part.kind !== "thread" || count < 2) {
                return [partSaid(part)];
            }
            if (said.has(part.done)) {
                return [];
            }
            said.add(part.done);
            return [`${count} threads ${part.done}`];
        })
        .join(between);
}

/** Say whether `partsSaid` leaves anything of `parts` out: a count in place of numbers, or of threads. */
export function partsCounted(parts: readonly ReplyPart[]): boolean {
    return partsSaid(parts) !== parts.map(partSaid).join(" · ");
}

/** Say `text` on one line: its first sentence alone, ending where a full stop is followed by more; what's left out is in its whole, which `g<` shows. */
export function brief(text: string): string {
    const end = /[.!?](?=\s+\S)/.exec(text);
    const first = end === null ? text : text.slice(0, end.index + 1);
    return first.replace(/\s+/g, " ").trim();
}

/** Say whether `brief` leaves anything of `text` out but its spacing: a sentence after the first. */
export function shortened(text: string): boolean {
    return brief(text) !== text.replace(/\s+/g, " ").trim();
}
