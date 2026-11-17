// What a project's modules declare for their views to name, as the page reads it: each fold kind, tone and mark
// kind by its name, the core's among them. The page holds none of its own.

import type { FoldKind, Looks, MarkKind, Tone } from "../generated/read";

/** The kinds a project's modules declare, each by its name. */
export class Kinds {
    readonly folds: ReadonlyMap<string, FoldKind>;
    readonly tones: ReadonlyMap<string, Tone>;
    readonly marks: ReadonlyMap<string, MarkKind>;

    constructor(looks: Looks) {
        this.folds = new Map(looks.folds.map((each) => [each.kind.name, each.kind]));
        this.tones = new Map(looks.tones.map((each) => [each.kind.name, each.kind]));
        this.marks = new Map(looks.marks.map((each) => [each.kind.name, each.kind]));
    }

    /** Return the fold kind of `letter`, the key the fold keys take it by; none where no kind takes it. */
    byLetter(letter: string): FoldKind | null {
        for (const kind of this.folds.values()) {
            if (kind.letter === letter) {
                return kind;
            }
        }
        return null;
    }

    /** Say whether a fold of `kind` starts open, as its kind says; a kind nobody declares starts closed. */
    startsOpen(kind: string): boolean {
        return this.folds.get(kind)?.starts_open ?? false;
    }

    /** Return the colour a tone is drawn in, following what it takes the look of. */
    colour(tone: string): string | null {
        const seen = new Set<string>();
        let at = this.tones.get(tone);
        while (at !== undefined && !seen.has(at.name)) {
            seen.add(at.name);
            if (at.colour !== null) {
                return at.colour;
            }
            at = at.like === null ? undefined : this.tones.get(at.like);
        }
        return null;
    }

    /** Return how bold or dim a tone is drawn, following what it takes the look of. */
    weight(tone: string): "bold" | "dim" | null {
        const seen = new Set<string>();
        let at = this.tones.get(tone);
        while (at !== undefined && !seen.has(at.name)) {
            seen.add(at.name);
            if (at.weight !== null) {
                return at.weight;
            }
            at = at.like === null ? undefined : this.tones.get(at.like);
        }
        return null;
    }
}
