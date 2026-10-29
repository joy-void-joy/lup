// The review's editor, as a script reaches it: the page has no handle of its own for one.
import type { EditorView } from "@codemirror/view";
import type { Page } from "playwright";

/**
 * The review's `EditorView`, as an expression in the page: what `@codemirror/view`'s own `EditorView.findFromDOM`
 * finds, through `cmTile`, an internal property of the content element (6.43; it was `cmView` before). The driver's
 * tests reach the editor through it, so a version of CodeMirror that keeps the view elsewhere fails them, rather than
 * the scripts written on the driver: `findFromDOM` in `node_modules/@codemirror/view/dist/index.js` says where it went.
 */
const FOUND = `document.querySelector(".review-buffer .cm-content")?.cmTile?.root?.view`;

/** The review's `EditorView` as `FOUND` finds it, where a script waiting on it is told at once that it's gone. */
const VIEW = `(() => { const view = ${FOUND}; if (view === undefined) { throw new Error("the review's editor is gone from the page"); } return view; })()`;

/** Vim's mode in the review. */
export type Mode = "normal" | "insert" | "visual";

/** The review's editor on a page. */
export interface Review {
    /**
     * Run `fn` in the page with the review's `EditorView` and `arg`, and return what it returns, which the page must
     * be able to send back. It's sent as its source, an arrow function or a function expression: it reaches nothing
     * outside itself but its arguments.
     */
    evaluate<R, A = undefined>(fn: (view: EditorView, arg: A) => R, arg?: A): Promise<R>;
    /** Its text whole. */
    text(): Promise<string>;
    /** The line the cursor is on. */
    line(): Promise<string>;
    /** Vim's mode. */
    mode(): Promise<Mode>;
    /** Return once `fn`, run in the page as `evaluate` runs it, returns true; where it never does, the error says "the review never" `what`. */
    until<A = undefined>(what: string, fn: (view: EditorView, arg: A) => boolean, arg?: A): Promise<void>;
    /** Return once the review holds `text`. */
    holds(text: string): Promise<void>;
    /** Return once vim's mode is `mode`. */
    inMode(mode: Mode): Promise<void>;
    /**
     * Return once the review's length has stayed within `slack` characters for `quiet` milliseconds: it's been read
     * whole as the page loaded, which takes a second or two at the operator's size, long after the first item shows,
     * and a measure taken before it measures the loading. Hooks or an item arriving change it by far less.
     */
    settled(quiet?: number, slack?: number): Promise<void>;
    /**
     * Put the cursor on the first `text` after it, with vim's search, `/`, as the operator would, once the review holds
     * it, and return once it's there. A selection dispatched to the editor would move past a closed fold, as a motion
     * does; a search opens the folds around its match.
     */
    goTo(text: string): Promise<void>;
    /** Open a comment under the cursor's line with `o`, and return once it's being written, in insert mode. */
    comment(): Promise<void>;
    /**
     * How many ranges of the review's decorations carry `className`: each decoration set the editor's state holds
     * counted once, though a state field providing decorations is in `state.values` twice, its own value and the
     * facet's input it provides, which a count read there doubles.
     */
    decorated(className: string): Promise<number>;
}

/**
 * The review's editor on `page`, once the page has made it; throw where it's there but not reachable as `FOUND` says. A
 * wait that fails says what the page threw, `thrown`, which is most often why: an error uncaught in one of React's
 * effects takes the page's whole tree down, the review with it.
 */
export async function review(page: Page, thrown: readonly Error[] = []): Promise<Review> {
    await page.waitForSelector(".review-buffer .cm-content", { state: "attached" });
    if (!(await page.evaluate(`Boolean(${FOUND})`))) {
        throw new Error(
            "the review's editor is on the page, but not where the driver reaches it (`FOUND`, `drive/review.ts`): " +
                "CodeMirror keeps its view elsewhere now, as `EditorView.findFromDOM` in node_modules/@codemirror/view says",
        );
    }
    const called = <R, A>(fn: (view: EditorView, arg: A) => R, arg?: A) => `(${fn.toString()})(${VIEW}, ${JSON.stringify(arg)})`;
    const evaluate = async <R, A>(fn: (view: EditorView, arg: A) => R, arg?: A): Promise<R> => (await page.evaluate(called(fn, arg))) as R;
    const until = async (expression: string, what: string) => {
        try {
            await page.waitForFunction(expression, undefined, { polling: 100 });
        } catch (failed) {
            const threw = thrown.length === 0 ? "" : `; the page threw ${thrown.map((each) => each.stack ?? each.message).join("\nand ")}`;
            throw new Error(`the review never ${what}${threw}`, { cause: failed });
        }
    };
    // Vim's state, on the adapter `@replit/codemirror-vim` keeps on the view, as its `getCM` reads it.
    const mode = `(() => { const vim = (${VIEW}).cm.state.vim; return vim.insertMode ? "insert" : vim.visualMode ? "visual" : "normal"; })()`;
    const keyboard = async (...keys: string[]) => {
        await evaluate((view) => view.focus());
        for (const key of keys) {
            await page.keyboard.press(key);
        }
    };
    const inMode = (wanted: Mode) => until(`${mode} === ${JSON.stringify(wanted)}`, `went into ${wanted} mode`);
    const holds = (text: string) => until(`(${VIEW}).state.doc.toString().includes(${JSON.stringify(text)})`, `held ${JSON.stringify(text)}`);
    return {
        evaluate,
        text: () => evaluate((view) => view.state.doc.toString()),
        line: () => evaluate((view) => view.state.doc.lineAt(view.state.selection.main.head).text),
        mode: async () => (await page.evaluate(mode)) as Mode,
        until: (what, fn, arg) => until(called(fn, arg), what),
        holds,
        inMode,
        async settled(quiet = 1500, slack = 2000) {
            await page.evaluate(() => Object.assign(globalThis, { lupDriveSettling: null }));
            await until(
                `(() => { const length = (${VIEW}).state.doc.length; const now = performance.now(); const was = globalThis.lupDriveSettling; ` +
                    `if (was === null || Math.abs(length - was.length) > ${slack}) { globalThis.lupDriveSettling = { length, since: now }; return false; } ` +
                    `return now - was.since >= ${quiet}; })()`,
                `settled, its length moving by more than ${slack} characters within ${quiet} ms`,
            );
        },
        async goTo(text) {
            if (text.includes("\n")) {
                throw new Error(`a search finds a line's text, and ${JSON.stringify(text)} is more than one`);
            }
            await holds(text);
            await keyboard("Escape", "/");
            // The review's vim searches with JavaScript's regular expressions (`pcre`), each of their own characters
            // escaped so the text is matched as written, and the search's own `/`.
            await page.keyboard.type(text.replaceAll(/[\\^$.*+?()[\]{}|/]/g, "\\$&"));
            await page.keyboard.press("Enter");
            await until(
                `(() => { const view = ${VIEW}; const at = view.state.selection.main.head; return view.state.doc.sliceString(at, at + ${text.length}) === ${JSON.stringify(text)}; })()`,
                `put the cursor on ${JSON.stringify(text)}`,
            );
        },
        async comment() {
            await keyboard("o");
            await inMode("insert");
        },
        decorated: (className) =>
            evaluate((view, wanted) => {
                const counted = new Set<unknown>();
                let count = 0;
                for (const value of (view.state as unknown as { values: unknown[] }).values) {
                    const ranges = value as { between?: (from: number, to: number, each: (from: number, to: number, value: { spec?: { class?: string } }) => void) => void };
                    if (counted.has(value) || typeof ranges?.between !== "function") {
                        continue;
                    }
                    counted.add(value);
                    ranges.between(0, view.state.doc.length, (_from, _to, decoration) => {
                        if ((decoration.spec?.class ?? "").split(" ").includes(wanted)) {
                            count += 1;
                        }
                    });
                }
                return count;
            }, className),
    };
}
