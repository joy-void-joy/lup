// The overview beside the review (`outline.ts`; `docs/dashboard.md`, *The
// review*): every agent, a subagent under its parent, and its items, each
// marked by how it stands and what the draft does with it, live; what's in
// view bracketed and the cursor's entry highlighted as the view moves, the pane
// scrolling to keep them shown, where the margin is the structure of what's in
// view. A click on an entry, or Enter on it, goes there in the review; `gO`
// takes the keyboard to it, where `j` and `k` move and Esc goes back; `\`
// hides it or shows it again. On a narrow screen it's an overlay `gO`, `\` or
// the bar's button opens, closing as it goes somewhere.
import { EditorView } from "@codemirror/view";
import { Vim } from "@replit/codemirror-vim";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import type { Following } from "./follow";
import type { Kind } from "./looks";
import { cursorRow, outlineOf, type DraftMark, type OutlineMark, type OutlineRow, type Reading } from "./outline";
import type { Laid } from "./review";

/** What `gO` does in the review: take the keyboard to the overview; and what `\` does: hide it or show it. */
let outlineFocus: (() => void) | null = null;
let outlineToggle: (() => void) | null = null;
let outlineMapped = false;

/** Set what `gO` does, as the overview is shown or goes. */
export function setOutlineFocus(focus: (() => void) | null): void {
    outlineFocus = focus;
}

/** Set what `\` does: hide the overview or show it. */
export function setOutlineToggle(toggle: (() => void) | null): void {
    outlineToggle = toggle;
}

/** Map `gO`, Neovim's outline key, and `\` in the review's vim, once: into the overview, and the overview hidden or shown. */
export function mapOutlineKey(): void {
    if (outlineMapped) {
        return;
    }
    outlineMapped = true;
    Vim.defineAction("lupOutline", () => outlineFocus?.());
    Vim.mapCommand("gO", "action", "lupOutline", {}, { context: "normal" });
    Vim.defineAction("lupOverview", () => outlineToggle?.());
    Vim.mapCommand("\\", "action", "lupOverview", {}, { context: "normal" });
}

/** What `]` or `[` and a scope's letter does in the review: go to the next or previous scope of that kind. */
let scopeJump: ((kind: ScopeKey, forward: boolean) => void) | null = null;

/** The scopes `]` and `[` go by, each by the fold letter it's marked with: an agent's group, an item, each kind of drawer, by its fold's kind. */
export type ScopeKey = "group" | "item" | (string & {});

/**
 * Return each scope's key after `]` and `[`, with the kinds of fold known now (`looks.ts`): its fold letter, but an
 * agent's group's `g`, as `]a` goes to what's to answer; an item's, then each drawer's, a kind with no letter none.
 */
export function scopeKeys(kinds: readonly Kind[]): (readonly [letter: string, kind: ScopeKey])[] {
    const item = kinds.find((each) => each.name === "item")?.letter ?? null;
    return [
        ["g", "group"],
        ...(item === null ? [] : [[item, "item"] as const]),
        ...kinds.flatMap((each) => (each.drawer && each.letter !== null ? [[each.letter, each.name] as const] : [])),
    ];
}

/** The keys `]` and `[` and a scope's letter took as last mapped, and the action each does. */
let scopesMapped = new Map<string, string>();

/** Set what `]` or `[` and a scope's letter does, with what's laid out now. */
export function setScopeJump(jump: ((kind: ScopeKey, forward: boolean) => void) | null): void {
    scopeJump = jump;
}

/** Map `]` and `[` with each scope's letter in the review's vim, as the kinds known change: next or previous scope of that kind. */
export function mapScopeKeys(kinds: readonly Kind[]): void {
    const wanted = new Map<string, string>();
    for (const [letter, kind] of scopeKeys(kinds)) {
        for (const forward of [true, false]) {
            const name = `lupScope-${kind}-${forward ? "next" : "previous"}`;
            Vim.defineAction(name, () => {
                scopeJump?.(kind, forward);
            });
            wanted.set(`${forward ? "]" : "["}${letter}`, name);
        }
    }
    const unmap = Vim.unmap as (keys: string, context?: string) => boolean;
    for (const [keys, name] of scopesMapped) {
        if (wanted.get(keys) !== name) {
            unmap(keys, "normal");
        }
    }
    for (const [keys, name] of wanted) {
        if (scopesMapped.get(keys) !== name) {
            Vim.mapCommand(keys, "action", name, {}, { context: "normal" });
        }
    }
    scopesMapped = wanted;
}

/** The width under which the page is one column, as a phone's: the overview is an overlay there, and the stack two slots. */
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
    reading: Reading;
    narrow: boolean;
    /** Whether it's shown: beside the review, or over it on a narrow screen. */
    open: boolean;
    setOpen: (open: boolean) => void;
    jump: (position: number) => void;
    /** Give the keyboard back to the review. */
    back: () => void;
    /** Set what `gO` in the review does: take the keyboard to the overview. */
    focusing: (focus: (() => void) | null) => void;
}

/** Where the view is, as the overview reads it: the entries in view, and the cursor's, each by its key; drawn again only where one of them changed. */
interface Viewed {
    seen: string[];
    cursor: string | null;
}

function sameViewed(a: Viewed, b: Viewed): boolean {
    return a.cursor === b.cursor && a.seen.join("\n") === b.seen.join("\n");
}

/** How an entry stands, a glyph each, in the state's own colour: what waits on the operator a diamond, solid for an item, hollow for a file. */
export const GLYPHS: Partial<Record<OutlineMark, string>> = {
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
    approve: { glyph: "✔", word: "approve" },
    decline: { glyph: "✗", word: "decline" },
};

/** Return the glyph an entry is marked with, by what it is and its first mark that has one. */
function glyphOf(row: OutlineRow): { glyph: string; mark: string } {
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
    const [viewed, setViewed] = useState<Viewed>({ seen: [], cursor: null });
    const rows = useMemo(() => outlineOf(laidOut, reading), [laidOut, reading]);
    const now = useRef(rows);
    now.current = rows;
    useEffect(() => {
        if (!open) {
            return undefined;
        }
        const measure = () => {
            const view = following.view;
            if (view === null) {
                return;
            }
            view.requestMeasure({
                key: "lup-outline",
                read: (read: EditorView): Viewed => {
                    const scroller = read.scrollDOM.getBoundingClientRect();
                    const top = scroller.top - read.documentTop;
                    const from = read.lineBlockAtHeight(Math.max(top, 0)).from;
                    const to = read.lineBlockAtHeight(Math.max(top + read.scrollDOM.clientHeight - 1, 0)).to;
                    const rows = now.current;
                    const viewed = {
                        seen: rows.flatMap((row) => (row.kind !== "repository" && row.from <= to && row.to >= from ? [row.key] : [])),
                        cursor: cursorRow(rows, read.state.selection.main.head)?.key ?? null,
                    };
                    return viewed;
                },
                write: (measured: Viewed) => setViewed((before) => (sameViewed(before, measured) ? before : measured)),
            });
        };
        measure();
        return following.listen(measure);
    }, [following, rows, open]);

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
    if (!open) {
        return null;
    }
    return (
        <nav
            className={`outline${narrow ? " is-overlay" : ""}`}
            ref={pane}
            tabIndex={0}
            onKeyDown={pressed}
            onBlur={() => setSelected(null)}
            aria-label="Overview of every agent and item"
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
                        {row.tag === null ? null : (
                            <span className="outline-tag mark-to-review" title="files to review in its since you approved">
                                {row.tag}
                            </span>
                        )}
                        {row.fresh ? <span className="outline-tag outline-fresh" title="new: its group not seen since it came">new</span> : null}
                        {row.draft.length === 0 ? null : (
                            <span className="outline-tag outline-draft" title={`in your reply, with the next Ctrl+Enter: ${row.draft.map((each) => DRAFTED[each].word).join(", ")}`}>
                                {row.draft.map((each) => DRAFTED[each].glyph).join("")}
                            </span>
                        )}
                    </div>
                );
            })}
            <div className="outline-hint">
                <kbd>gO</kbd> here · <kbd>j</kbd> <kbd>k</kbd> · <kbd>⏎</kbd> go · <kbd>Esc</kbd> back
                <br />
                <span className="mark-waiting">◆</span> waiting on you · <span className="mark-to-review">◇</span> to review · <span className="mark-news">•</span> news
                <br />
                <span className="outline-draft">» ✓ ✔</span> in your next <kbd>^⏎</kbd>: comment, read, approve
            </div>
        </nav>
    );
}
