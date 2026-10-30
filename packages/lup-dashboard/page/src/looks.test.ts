import { describe, expect, it } from "vitest";

import { STANDING } from "./fixtures/looks";
import { merged, styled, type Looks } from "./looks";

/** Another repository's looks: the default's, with a module of its own whose fold kind takes `e`, which `earlier` has, and one taking a free letter. */
const OTHER: Looks = {
    ...STANDING,
    folds: [
        ...(STANDING.folds ?? []),
        { name: "episodes", letter: "e", called: "episodes", one: "the episode", level: 1, opens: "together", colour: "ok", chord: true, whole: false, counts: true, by_all: true },
        { name: "scenes", letter: "q", called: "scenes", one: "the scene", level: 2, opens: "together", colour: "purple", chord: true, whole: false, counts: true, by_all: true },
    ],
    drawers: [...(STANDING.drawers ?? []), { module: "reels", view: "reel", place: { under: "agent", letter: "r", called: "the reel", colour: "cyan" } }],
};

describe("the looks, merged across repositories", () => {
    it("knows each kind of fold by its name, the core's first, outermost first, a drawer's among them", () => {
        const looks = merged({}, STANDING);
        expect(looks.kinds.map((each) => `${each.letter}${each.drawer ? "·" : ""}`).join(" ")).toBe("w a i t· s· v· o f p l e b u k c m d");
        expect(looks.kinds.find((each) => each.name === "item")).toMatchObject({ chord: false, whole: true, counts: true });
        expect(looks.kinds.find((each) => each.name === "lines")).toMatchObject({ counts: false });
        expect(looks.drawers("/r/any.git").map((each) => each.view)).toEqual(["tasks", "since", "conversation"]);
        expect(looks.banners("/r/any.git").map((each) => `${each.module} ${each.view}`)).toEqual(["adapters banner", "judge banner"]);
        expect(looks.refused).toEqual([]);
    });

    it("refuses a later repository's kind the letter an earlier one took, said once, its folds left to the generic keys", () => {
        const looks = merged({ "/r/lup.git": STANDING, "/r/zoetrope.git": OTHER }, STANDING);
        expect(looks.kinds.find((each) => each.name === "episodes")).toMatchObject({ letter: null, level: 1, colour: "ok" });
        expect(looks.kinds.find((each) => each.name === "earlier")?.letter).toBe("e");
        expect(looks.kinds.find((each) => each.name === "scenes")?.letter).toBe("q");
        expect(looks.refused).toEqual(["zoetrope's fold kind `episodes` takes the letter e, which `earlier` has: za, zr and zm reach its folds, e doesn't."]);
        // Each repository's drawers its own; one whose process hasn't said, the stand-in's.
        expect(looks.drawers("/r/zoetrope.git").map((each) => each.view)).toEqual(["tasks", "since", "conversation", "reel"]);
        expect(looks.drawers("/r/new.git").map((each) => each.view)).toEqual(["tasks", "since", "conversation"]);
    });

    it("draws each kind in its colour and each tone in its look, through the tone it takes it from", () => {
        const css = styled(merged({}, STANDING));
        expect(css).toContain("--fold-since: var(--warn);");
        expect(css).toContain(".fold-item, .buffer .cm-editor .cm-foldPlaceholder.fold-item { color: var(--fold-item); }");
        expect(css).toContain(".buffer .cm-line.barred-items { border-left: 2px solid var(--fold-items); }");
        expect(css).toContain(".tone-strong { color: var(--fg); font-weight: 700; }");
        // `received` takes `operator`'s look, which is the operator's blue.
        expect(css).toContain(".tone-received { color: var(--info); }");
    });
});
