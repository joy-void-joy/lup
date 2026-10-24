// The outline pane, a layout trial (`outline.ts`, `trials.ts`): beside the
// review, each repository, agent, subagent, item, drawer and the files of what's
// in view, each marked by how it stands; what's in view bracketed and the
// cursor's entry highlighted as the view moves, the pane scrolling to keep them
// shown. A click on an entry, or Enter on it, goes there in the review; `gO` in
// the review, or a click, takes the keyboard to it, where `j` and `k` move and
// Esc goes back. On a narrow screen it's an overlay `gO` or the bar's button
// opens, closing as it goes somewhere.
import { EditorView } from "@codemirror/view";
import { Vim } from "@replit/codemirror-vim";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import type { Following } from "./follow";
import { measured } from "./timing";
import { cursorRow, filedScopes, outlineOf, scopesSeen, type DraftMark, type OutlineMark, type OutlineRow, type Reading } from "./outline";
import type { Part, ReviewPlace } from "./keys";
import type { Laid } from "./review";

/** What `gO` does in the review: take the keyboard to the outline, where it's shown; else say it's off. */
let outlineFocus: (() => void) | null = null;
let outlineSay: ((text: string) => void) | null = null;
let outlineMapped = false;

/** Set what `gO` does, as the outline is shown or goes. */
export function setOutlineFocus(focus: (() => void) | null): void {
    outlineFocus = focus;
}

/** Map `gO`, Neovim's outline key, in the review's vim, once: it takes the keyboard to the outline. */
export function mapOutlineKey(say: (text: string) => void): void {
    outlineSay = say;
    if (outlineMapped) {
        return;
    }
    outlineMapped = true;
    Vim.defineAction("lupOutline", () => {
        if (outlineFocus === null) {
            outlineSay?.("The outline is off: Ctrl+K, then Layout: outline.");
        } else {
            outlineFocus();
        }
    });
    Vim.mapCommand("gO", "action", "lupOutline", {}, { context: "normal" });
}

/** The outline's keys, a part of the list of keys while an outline is shown (`keys.ts`). */
export const OUTLINE_KEYS: Part<ReviewPlace>[] = [
    {
        title: "The outline (a layout trial)",
        keys: [
            {
                keys: "]g [g",
                does: "next and previous agent's group, on its banner, a group's folds marked a in the margin",
                short: "agents",
                at: ["banner", "approvals", "item", "change", "drawer", "aside"],
            },
            { keys: "]i [i", does: "next and previous item, on its header", short: "items", at: [] },
            {
                keys: "]t [t ]s [s ]v [v",
                does: "next and previous drawer of that kind, by its letter: tasks, since you approved, the conversation",
                short: "drawers",
                at: ["banner", "drawer"],
            },
            { keys: "gO", does: "take the keyboard to the outline's pane, or open it on a phone; j k move, ⏎ goes, Esc back", short: "outline", at: [] },
        ],
    },
];

/** What `]` or `[` and a scope's letter does in the review, where an outline is shown: go to the next or previous scope of that kind. */
let scopeJump: ((kind: ScopeKey, forward: boolean) => void) | null = null;
let scopesMapped = false;

/** The scopes the outline's keys go by, each by the fold letter it's marked with: an agent's group, an item, each kind of drawer. */
export type ScopeKey = "group" | "item" | "tasks" | "since" | "conversation";

/** Each scope's key after `]` and `[`: its fold letter, but an agent's group's `g`, as `]a` goes to what's to answer. */
export const SCOPE_KEYS: readonly (readonly [letter: string, kind: ScopeKey])[] = [
    ["g", "group"],
    ["i", "item"],
    ["t", "tasks"],
    ["s", "since"],
    ["v", "conversation"],
];

/** Set what `]` or `[` and a scope's letter does, as an outline is shown or goes. */
export function setScopeJump(jump: ((kind: ScopeKey, forward: boolean) => void) | null): void {
    scopeJump = jump;
}

/** Map `]` and `[` with each scope's letter in the review's vim, once: next or previous scope of that kind, where an outline is shown. */
export function mapScopeKeys(): void {
    if (scopesMapped) {
        return;
    }
    scopesMapped = true;
    for (const [letter, kind] of SCOPE_KEYS) {
        for (const forward of [true, false]) {
            const name = `lupScope-${kind}-${forward ? "next" : "previous"}`;
            Vim.defineAction(name, () => {
                if (scopeJump === null) {
                    outlineSay?.("Going by the outline's scopes is a layout trial: Ctrl+K, then Layout: outline.");
                } else {
                    scopeJump(kind, forward);
                }
            });
            Vim.mapCommand(`${forward ? "]" : "["}${letter}`, "action", name, {}, { context: "normal" });
        }
    }
}

/** The width under which the page is one column, as a phone's: the outline is an overlay there, and the stack two slots. */
const NARROW = "(max-width: 640px)";

/** Whether the screen is narrow, as a phone's, kept as it changes. */
export function useNarrow(): boolean {
    const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW).matches);
    useEffect(() => {
        const query = window.matchMedia(NARROW);
        const changed = () => setNarrow(query.matches);
        query.addEventListener("change", changed);
        return () => query.removeEventListener("change", changed);
    }, []);
    return narrow;
}

interface Props {
    following: Following;
    laidOut: Laid;
    reading: Omit<Reading, "open">;
    narrow: boolean;
    /** Whether it's open as an overlay, on a narrow screen. */
    open: boolean;
    setOpen: (open: boolean) => void;
    jump: (position: number) => void;
    /** Give the keyboard back to the review. */
    back: () => void;
    /** Set what `gO` in the review does: take the keyboard to the outline. */
    focusing: (focus: (() => void) | null) => void;
}

/** Where the view is, as the outline reads it: the items and drawers whose files it lists, the entries in view, and the cursor's, each by its key; drawn again only where one of them changed. */
interface Viewed {
    open: string[];
    seen: string[];
    cursor: string | null;
}

function sameViewed(a: Viewed, b: Viewed): boolean {
    return a.cursor === b.cursor && a.open.join("\n") === b.open.join("\n") && a.seen.join("\n") === b.seen.join("\n");
}

/** How an entry stands, a glyph each, in the state's own colour: what waits on the operator a diamond, solid for an item, hollow for a file. */
const GLYPHS: Partial<Record<OutlineMark, string>> = {
    waiting: "◆",
    news: "•",
    parked: "‖",
    "to-review": "◇",
    flagged: "⚑",
    folded: "·",
    calling: "▶",
    idle: "○",
    ended: "✕",
};

/** What the draft does with an item on the next Ctrl+Enter, said in the draft's colour. */
export const DRAFTED: Record<DraftMark, { glyph: string; word: string }> = {
    comment: { glyph: "»", word: "comment" },
    read: { glyph: "✓", word: "read" },
    approve: { glyph: "✓", word: "approve" },
};

/** Return the glyph an entry is marked with, by what it is and its first mark that has one. */
function glyphOf(row: OutlineRow): { glyph: string; mark: string } {
    if (row.kind === "drawer") {
        const kind = row.of?.split(" ")[0] ?? "";
        return { glyph: kind === "tasks" ? "t" : kind === "since" ? "s" : "v", mark: `drawer-${kind}${row.marks.includes("label") ? " is-label" : ""}` };
    }
    if (row.kind === "repository") {
        return { glyph: "▪", mark: "repository" };
    }
    if (row.kind === "approvals") {
        return { glyph: "⚑", mark: "approvals" };
    }
    const mark = row.marks.find((each) => GLYPHS[each] !== undefined);
    return mark === undefined ? { glyph: " ", mark: "none" } : { glyph: GLYPHS[mark] ?? " ", mark };
}

export function Outline({ following, laidOut, reading, narrow, open, setOpen, jump, back, focusing }: Props) {
    const [viewed, setViewed] = useState<Viewed>({ open: [], seen: [], cursor: null });
    const filed = useMemo(() => filedScopes(laidOut), [laidOut]);
    const openKey = viewed.open.join("\n");
    const rows = useMemo(
        () => {
            const began = performance.now();
            const made = outlineOf(laidOut, { ...reading, open: new Set(viewed.open) });
            measured("lup-outline-rows", began);
            return made;
        },
        // The scopes whose files are listed, by what names them, not by the list made anew each frame.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [laidOut, reading, openKey],
    );
    const now = useRef({ filed, rows });
    now.current = { filed, rows };
    useEffect(() => {
        const measure = () => {
            const view = following.view;
            if (view === null) {
                return;
            }
            view.requestMeasure({
                key: "lup-outline",
                read: (read: EditorView): Viewed => {
                    const began = performance.now();
                    const scroller = read.scrollDOM.getBoundingClientRect();
                    const top = scroller.top - read.documentTop;
                    const from = read.lineBlockAtHeight(Math.max(top, 0)).from;
                    const to = read.lineBlockAtHeight(Math.max(top + read.scrollDOM.clientHeight - 1, 0)).to;
                    const { rows } = now.current;
                    const viewed = {
                        open: scopesSeen(now.current.filed, from, to),
                        seen: rows.flatMap((row) => (row.kind !== "repository" && row.from <= to && row.to >= from ? [row.key] : [])),
                        cursor: cursorRow(rows, read.state.selection.main.head)?.key ?? null,
                    };
                    measured("lup-outline", began);
                    return viewed;
                },
                write: (measured: Viewed) => setViewed((before) => (sameViewed(before, measured) ? before : measured)),
            });
        };
        measure();
        return following.listen(measure);
    }, [following, filed, rows]);

    const cursor = rows.find((row) => row.key === viewed.cursor);
    const seen = new Set(viewed.seen);
    const inView = (row: OutlineRow) => seen.has(row.key);
    const firstInView = viewed.seen[0] ?? null;
    const pane = useRef<HTMLDivElement>(null);
    const [selected, setSelected] = useState<number | null>(null);

    // The pane keeps what's in view and the cursor's entry shown as the view moves, unless the keyboard is in it.
    useLayoutEffect(() => {
        const host = pane.current;
        if (host === null || selected !== null) {
            return;
        }
        for (const key of [firstInView, cursor?.key ?? null]) {
            const element = key === null ? null : host.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`);
            if (element !== null) {
                const box = element.getBoundingClientRect();
                const within = host.getBoundingClientRect();
                if (box.top < within.top || box.bottom > within.bottom) {
                    element.scrollIntoView({ block: key === cursor?.key ? "nearest" : "start" });
                }
            }
        }
    }, [firstInView, cursor?.key, selected]);

    // `gO` in the review takes the keyboard here, onto the cursor's entry.
    useEffect(() => {
        focusing(() => {
            setOpen(true);
            const at = cursor === undefined ? 0 : rows.indexOf(cursor);
            setSelected(Math.max(at, 0));
            requestAnimationFrame(() => pane.current?.focus());
        });
        return () => focusing(null);
    }, [focusing, setOpen, cursor, rows]);

    const go = (row: OutlineRow) => {
        setSelected(null);
        if (narrow) {
            setOpen(false);
        }
        jump(row.at);
    };
    const pressed = (event: KeyboardEvent) => {
        const at = selected ?? (cursor === undefined ? 0 : rows.indexOf(cursor));
        const move = (by: number) => {
            event.preventDefault();
            const next = Math.min(Math.max(at + by, 0), rows.length - 1);
            setSelected(next);
            pane.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(rows[next]?.key ?? "")}"]`)?.scrollIntoView({ block: "nearest" });
        };
        if (event.key === "j" || event.key === "ArrowDown") {
            move(1);
        } else if (event.key === "k" || event.key === "ArrowUp") {
            move(-1);
        } else if (event.key === "Enter") {
            event.preventDefault();
            const row = rows[at];
            if (row !== undefined) {
                go(row);
            }
        } else if (event.key === "Escape" || event.key === "q") {
            event.preventDefault();
            setSelected(null);
            if (narrow) {
                setOpen(false);
            }
            back();
        }
    };
    if (narrow && !open) {
        return null;
    }
    return (
        <nav
            className={`outline${narrow ? " is-overlay" : ""}`}
            ref={pane}
            tabIndex={0}
            onKeyDown={pressed}
            onBlur={() => setSelected(null)}
            aria-label="Outline of the review"
        >
            {rows.map((row, at) => {
                const { glyph, mark } = glyphOf(row);
                const classes = [
                    "outline-row",
                    `outline-${row.kind}`,
                    inView(row) ? "is-in-view" : "",
                    row === cursor ? "is-cursor" : "",
                    at === selected ? "is-selected" : "",
                ].join(" ");
                return (
                    <div key={row.key} data-key={row.key} className={classes} style={{ paddingLeft: `calc(${row.depth * 2}ch + 1ch)` }} title={row.title} onClick={() => go(row)}>
                        <span className={`outline-glyph mark-${mark}`}>{glyph}</span>
                        <span className="outline-text">{row.text}</span>
                        {row.fresh ? <span className="outline-tag outline-fresh" title="new since you last sent">new</span> : null}
                        {row.draft.map((each) => (
                            <span key={each} className="outline-tag outline-draft" title="in your reply: goes with the next Ctrl+Enter">
                                {DRAFTED[each].glyph} {DRAFTED[each].word}
                            </span>
                        ))}
                    </div>
                );
            })}
            <div className="outline-hint">
                <kbd>gO</kbd> here · <kbd>j</kbd> <kbd>k</kbd> · <kbd>⏎</kbd> go · <kbd>Esc</kbd> back
            </div>
        </nav>
    );
}
