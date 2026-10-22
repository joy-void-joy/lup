// The system clipboard as vim's registers `+` and `*`, one register, as a browser
// has one clipboard: a yank into it, as `"+yy` or `v`, a motion and `"*y`, writes
// the clipboard; a put from it, `"+p`, reads it, once the browser lets the page.
// Where the browser doesn't, as for a page served over plain HTTP, which has no
// clipboard to reach, or once it refused, the register keeps what was yanked into
// it on the page and puts that, and the operator is told why in the page's top
// line. Ctrl+C on a selection copies it wherever the page is served
// (`docs/dashboard.md`, *The keys*).
import { Vim, type ActionArgs, type CodeMirrorV, type InsertModeChanges, type vimState } from "@replit/codemirror-vim";

/** The system clipboard, as the browser gives it to the page. */
export interface SystemClipboard {
    writeText: (text: string) => Promise<void>;
    readText: () => Promise<string>;
}

/** What the register reaches: the system clipboard, none where the browser gives the page none; and the operator, told what it couldn't do. */
export interface Reach {
    clipboard: () => SystemClipboard | null;
    tell: (text: string) => void;
}

/** Why the clipboard can't be reached where the browser gives the page none. */
const UNSERVED = "the browser lets only a page on https or localhost reach the clipboard";

/** Return why the browser refused, from what it threw. */
function refusal(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
}

/**
 * The register `+` and `*` name, holding text as each of vim's registers does, each yank into it written to the system
 * clipboard as well: what vim's register controller takes, and what `defineRegister` defines.
 */
export class ClipboardRegister {
    keyBuffer: string[] = [""];
    insertModeChanges: InsertModeChanges[] = [];
    searchQueries: string[] = [];
    linewise = false;
    blockwise = false;

    constructor(private readonly reach: Reach) {}

    setText(text?: string, linewise?: boolean, blockwise?: boolean): void {
        this.keyBuffer = [text ?? ""];
        this.linewise = linewise === true;
        this.blockwise = blockwise === true;
        this.copied();
    }

    pushText(text: string, linewise?: boolean): void {
        // As vim's own: once text pushed is linewise, the whole is.
        if (linewise === true) {
            if (!this.linewise) {
                this.keyBuffer.push("\n");
            }
            this.linewise = true;
        }
        this.keyBuffer.push(text);
        this.copied();
    }

    pushInsertModeChanges(changes: InsertModeChanges): void {
        this.insertModeChanges.push(changes);
    }

    pushSearchQuery(query: string): void {
        this.searchQueries.push(query);
    }

    clear(): void {
        this.keyBuffer = [];
        this.insertModeChanges = [];
        this.searchQueries = [];
        this.linewise = false;
    }

    toString(): string {
        return this.keyBuffer.join("");
    }

    /** Write what it holds to the system clipboard, the operator told where it can't be. */
    private copied(): void {
        const clipboard = this.reach.clipboard();
        if (clipboard === null) {
            this.reach.tell(`Yanked into "+ on this page alone: ${UNSERVED}. Ctrl+C on a selection copies it.`);
            return;
        }
        clipboard.writeText(this.toString()).catch((error: unknown) => {
            this.reach.tell(`Not copied: the browser refused to write the clipboard (${refusal(error)}). Ctrl+C on a selection copies it.`);
        });
    }

    /**
     * Return what a put from it puts: the system clipboard, read, which it then holds; where the browser won't read
     * it, what was last yanked into it on the page, the operator told why.
     */
    async pasted(): Promise<string> {
        const clipboard = this.reach.clipboard();
        let why: string;
        if (clipboard === null) {
            why = UNSERVED;
        } else {
            try {
                const text = await clipboard.readText();
                this.keyBuffer = [text];
                this.linewise = text.endsWith("\n");
                this.blockwise = false;
                return text;
            } catch (error) {
                why = `the browser refused to read the clipboard (${refusal(error)})`;
            }
        }
        const kept = this.toString();
        this.reach.tell(
            kept === ""
                ? `Nothing put: ${why}, and nothing was yanked into "+ on this page. Ctrl+V in a comment pastes.`
                : `Put what was yanked into "+ on this page: ${why}. Ctrl+V in a comment pastes.`,
        );
        return kept;
    }
}

/** Return the register a name typed after `"` names: `+` names `*`, the one register the system clipboard is. */
export function registerNamed(name: string | undefined): string | undefined {
    return name === "+" ? "*" : name;
}

/** What vim's own actions hold that a put goes on with, once it has the text: the rest of its own `paste`. */
interface Pasting {
    continuePaste: (cm: CodeMirrorV, args: ActionArgs, vim: vimState, text: string, register: unknown) => void;
}

let defined: ClipboardRegister | null = null;

/**
 * Make `+` and `*` the system clipboard in vim's registers, once, returning the register they name. `*` is defined
 * with `defineRegister`; `+`, which vim's register controller holds already, is replaced in it. Vim's own `+` writes
 * and reads the clipboard itself, saying nothing where it can't and throwing where the page has none, so `"+` names
 * `*` (`registerNamed`, in vim's own `setRegister`), and a put from it reads the clipboard here, going on with vim's
 * own put once it's read.
 */
export function defineClipboard(reach: Reach): ClipboardRegister {
    if (defined !== null) {
        return defined;
    }
    const register = new ClipboardRegister(reach);
    defined = register;
    Vim.defineRegister("*", register);
    Vim.getRegisterController().registers["+"] = register;
    Vim.defineAction("setRegister", (_cm, args, vim) => {
        const named = registerNamed(args.selectedCharacter);
        if (named === undefined) {
            delete vim.inputState.registerName;
        } else {
            vim.inputState.registerName = named;
        }
    });
    Vim.defineAction("paste", function (this: Pasting, cm, args, vim) {
        const from = Vim.getRegisterController().getRegister(args.registerName);
        if (from !== register) {
            this.continuePaste(cm, args, vim, from.toString(), from);
            return;
        }
        void register.pasted().then((text) => this.continuePaste(cm, args, vim, text, register));
    });
    return register;
}
