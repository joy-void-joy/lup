// The header stack (`docs/dashboard.md`, *The review*): over the review, the headers of
// the scopes the top of the view is inside, each pinned while its own line is
// scrolled off, as VS Code's sticky scroll does: an agent's banner, a subagent's
// under their parent's where groups nest, an item's header or a drawer's summary
// line, a file's header. Each is the line the buffer shows at that level, drawn
// as it's drawn there. A scope's header is pushed up by the next one as its scope
// ends, so the stack slides rather than jumps. It follows the view: the cursor
// doesn't change it. On a narrow screen it keeps two slots, the innermost group
// and the innermost scope within it. Pure: the review measures and draws it
// (`Stack.tsx`).
import type { Span } from "./comments";
import type { Laid, Placed } from "./review";

/** One scope a header is pinned for: where its header line is, how far it reaches, what it is, and the scopes in it. */
export interface Sticky {
    kind: "group" | "item" | "drawer" | "file";
    /** Its header line: a banner, an item's header, a drawer's summary line, a file's header. */
    header: Span;
    /** From its header to its last position, the blank line after it among it. */
    from: number;
    to: number;
    children: Sticky[];
}

/**
 * Return the scopes of `laidOut` a header is pinned for, outermost first, each holding those in it, read from its tree
 * (`Laid.nodes`): each group, a subagent's inside their parent's, to the next one as deep or shallower; each of its
 * drawers and items to the next scope or group; each file of an item or a drawer over its lines.
 */
export function stickies(laidOut: Laid): Sticky[] {
    const end = Math.max(laidOut.text.length - 1, 0);
    const flat: Sticky[] = [];
    const scopes: { kind: "item" | "drawer"; part: Placed }[] = [];
    const banners: number[] = [];
    const files = (part: Placed) => {
        for (const each of part.children) {
            if (each.kind === "block" && (each.block?.block === "diff" || each.block?.block === "code")) {
                flat.push({ kind: "file", header: each.header, from: each.from, to: each.to, children: [] });
            }
            files(each);
        }
    };
    const walk = (parts: readonly Placed[]) => {
        for (const part of parts) {
            if (part.kind !== "group") {
                continue;
            }
            banners.push(part.from);
            flat.push({ kind: "group", header: part.header, from: part.from, to: Math.min(part.to, end), children: [] });
            for (const each of part.children) {
                if (each.kind === "view" || each.kind === "item") {
                    scopes.push({ kind: each.kind === "view" ? "drawer" : "item", part: each });
                    files(each);
                }
            }
            walk(part.children);
        }
    };
    walk(laidOut.nodes);
    scopes.sort((a, b) => a.part.from - b.part.from);
    scopes.forEach(({ kind, part }, at) => {
        const nextScope = scopes[at + 1]?.part.from ?? Infinity;
        const nextGroup = banners.find((each) => each > part.from) ?? Infinity;
        const stop = Math.min(nextScope, nextGroup);
        flat.push({ kind, header: part.header, from: part.from, to: stop === Infinity ? end : stop - 1, children: [] });
    });
    flat.sort((a, b) => a.from - b.from || b.to - a.to);
    const roots: Sticky[] = [];
    const holding: Sticky[] = [];
    for (const each of flat) {
        while (holding.length > 0 && (holding.at(-1)?.to ?? 0) < each.from) {
            holding.pop();
        }
        const parent = holding.at(-1);
        if (parent === undefined) {
            roots.push(each);
        } else {
            parent.children.push(each);
        }
        holding.push(each);
    }
    return roots;
}

/** Return the one of `stickies`, in the text's order, holding `position`; none where it's between them. */
export function holding(stickies: readonly Sticky[], position: number): Sticky | undefined {
    let low = 0;
    let high = stickies.length;
    while (low < high) {
        const middle = (low + high) >> 1;
        if ((stickies[middle]?.from ?? 0) <= position) {
            low = middle + 1;
        } else {
            high = middle;
        }
    }
    const found = stickies[low - 1];
    return found !== undefined && position <= found.to ? found : undefined;
}

/** Return the scopes `position` is inside, outermost first, but one whose header line it's on: the headers the stack holds once `position`'s line is the first under it. */
export function around(stickies: readonly Sticky[], position: number): Sticky[] {
    const found: Sticky[] = [];
    let level = stickies;
    for (;;) {
        const inside = holding(level, position);
        if (inside === undefined || position <= inside.header.to) {
            return found;
        }
        found.push(inside);
        level = inside.children;
    }
}

/** What the view says of where things are, in pixels from the document's top: where its top is, and each line's block. */
export interface Geometry {
    top: number;
    lineHeight: number;
    /** The line's block holding `position`, a folded fold's summary line holding what it hides. */
    block: (position: number) => { top: number; bottom: number };
    /** Where the line at `height` starts. */
    at: (height: number) => number;
}

/** One header in the stack: its scope, and how far below the stack's top it's drawn, pushed up as its scope ends. */
export interface Pinned {
    sticky: Sticky;
    offset: number;
}

/**
 * Return the headers pinned over the view `geometry` says: from the outermost, each scope the line under the stack
 * so far is inside whose own header is scrolled off above it, each drawn under the last, or pushed up so it ends where
 * its scope does. `slot` says which line of the stack each goes on, by how deep it is and what it is: one deeper
 * replaces what's on its slot, as on a narrow screen, which keeps the innermost group and the innermost scope.
 */
export function pinned(roots: readonly Sticky[], geometry: Geometry, slot: (sticky: Sticky, depth: number) => number = (_, depth) => depth): Pinned[] {
    const { top, lineHeight } = geometry;
    const stack: { sticky: Sticky; slot: number }[] = [];
    let level = roots;
    let depth = 0;
    for (;;) {
        const height = stack.length * lineHeight;
        const position = geometry.at(top + height);
        const inside = holding(level, position);
        if (inside === undefined || geometry.block(inside.header.from).top >= top + height - 0.5) {
            break;
        }
        const at = slot(inside, depth);
        while (stack.length > 0 && (stack.at(-1)?.slot ?? 0) >= at) {
            stack.pop();
        }
        stack.push({ sticky: inside, slot: at });
        level = inside.children;
        depth += 1;
    }
    // Each drawn under the last, or pushed up so its bottom is where its scope ends.
    const placed: Pinned[] = [];
    let y = 0;
    for (const { sticky } of stack) {
        const offset = Math.min(y, geometry.block(sticky.to).bottom - top - lineHeight);
        placed.push({ sticky, offset });
        y = offset + lineHeight;
    }
    return placed;
}

/** On a narrow screen, two slots: the groups' and the rest's. */
export function narrowSlot(sticky: Sticky): number {
    return sticky.kind === "group" ? 0 : 1;
}


/** Return how many lines of the stack are over the line `position` is on once it's the first line under the stack: the headers of the scopes it's inside, as a narrow screen's two slots keep them. */
export function linesOver(roots: readonly Sticky[], position: number, narrow: boolean): number {
    const inside = around(roots, position);
    if (!narrow) {
        return inside.length;
    }
    return (inside.some((each) => each.kind === "group") ? 1 : 0) + (inside.some((each) => each.kind !== "group") ? 1 : 0);
}
