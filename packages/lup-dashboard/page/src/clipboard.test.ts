import { Vim, type CodeMirrorV, type Pos } from "@replit/codemirror-vim";
import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import { ClipboardRegister, defineClipboard, registerNamed, yanking, type Reach, type SystemClipboard } from "./clipboard";

/** A system clipboard holding `held`, each text written to it kept, refusing to be written or read where told to. */
function system(held = "", refuses: { write?: string; read?: string } = {}): SystemClipboard & { written: string[] } {
    const written: string[] = [];
    return {
        written,
        writeText: (text) => (refuses.write === undefined ? (written.push(text), Promise.resolve()) : Promise.reject(new Error(refuses.write))),
        readText: () => (refuses.read === undefined ? Promise.resolve(held) : Promise.reject(new Error(refuses.read))),
    };
}

/** What the register reaches: `clipboard`, none for a page that has none; and what the operator is told, kept. */
function reaching(clipboard: SystemClipboard | null): Reach & { told: string[] } {
    const told: string[] = [];
    return { told, clipboard: () => clipboard, tell: (text) => told.push(text) };
}

/** Let what the browser does with the clipboard settle. */
const settled = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("the system clipboard as `+` and `*`", () => {
    it("writes each yank into it to the system clipboard, whole, an appended one with what it's appended to", async () => {
        const clipboard = system();
        const reach = reaching(clipboard);
        const register = new ClipboardRegister(reach);
        register.setText("Let the change land?\n", true);
        register.pushText("And the next?\n", true);
        await settled();
        expect(clipboard.written).toEqual(["Let the change land?\n", "Let the change land?\nAnd the next?\n"]);
        expect([register.toString(), register.linewise, reach.told]).toEqual(["Let the change land?\nAnd the next?\n", true, []]);
    });

    it("keeps a yank on the page where it has no clipboard, as on plain HTTP, and says so", () => {
        const reach = reaching(null);
        const register = new ClipboardRegister(reach);
        register.setText("Let");
        expect(register.toString()).toBe("Let");
        expect(reach.told).toEqual([
            "Yanked on this page alone, not to the clipboard: the browser lets only a page on https or localhost reach the clipboard. Ctrl+C on a selection copies it.",
        ]);
    });

    it("says why where the browser refuses to write it", async () => {
        const reach = reaching(system("", { write: "Document is not focused." }));
        new ClipboardRegister(reach).setText("Let");
        await settled();
        expect(reach.told).toEqual([
            "Not copied: the browser refused to write the clipboard (Document is not focused.). Ctrl+C on a selection copies it.",
        ]);
    });

    it("puts what the system clipboard holds, a line's end making it lines, which it then holds", async () => {
        const reach = reaching(system("copied elsewhere\n"));
        const register = new ClipboardRegister(reach);
        register.setText("yanked here");
        expect(await register.pasted()).toBe("copied elsewhere\n");
        expect([register.toString(), register.linewise, reach.told]).toEqual(["copied elsewhere\n", true, []]);
    });

    it("puts what was yanked on the page where the clipboard can't be read, saying why, or nothing where nothing was", async () => {
        const unserved = reaching(null);
        const register = new ClipboardRegister(unserved);
        expect(await register.pasted()).toBe("");
        register.setText("yanked here");
        expect(await register.pasted()).toBe("yanked here");
        const refused = reaching(system("elsewhere", { read: "Read permission denied." }));
        const denied = new ClipboardRegister(refused);
        denied.setText("yanked here");
        expect(await denied.pasted()).toBe("yanked here");
        expect([unserved.told[0], unserved.told[2], refused.told[0]]).toEqual([
            'Nothing put: the browser lets only a page on https or localhost reach the clipboard, and nothing was yanked into "+ on this page. Ctrl+V in a comment pastes.',
            'Put what was yanked into "+ on this page: the browser lets only a page on https or localhost reach the clipboard. Ctrl+V in a comment pastes.',
            'Put what was yanked into "+ on this page: the browser refused to read the clipboard (Read permission denied.). Ctrl+V in a comment pastes.',
        ]);
    });

    it("is one register, `+` naming `*`", () => {
        expect([registerNamed("+"), registerNamed("*"), registerNamed("a"), registerNamed(undefined)]).toEqual(["*", "*", "a", undefined]);
    });

    it("is what vim's registers `+` and `*` are, a yank into either written to the clipboard and kept as vim's last", async () => {
        const clipboard = system();
        const register = defineClipboard(reaching(clipboard));
        const controller = Vim.getRegisterController();
        expect([controller.getRegister("*"), controller.getRegister("+")]).toEqual([register, register]);
        controller.pushText(registerNamed("+"), "yank", "Let the change land?", true);
        await settled();
        expect(clipboard.written).toEqual(["Let the change land?\n"]);
        expect(controller.unnamedRegister.toString()).toBe("Let the change land?\n");
        // Defined once: vim's registers can't be defined twice.
        expect(defineClipboard(reaching(null))).toBe(register);
    });

    it("says a yank into it was copied to the clipboard, naming no register, once the browser has written it, and nothing where it wasn't", async () => {
        const register = new ClipboardRegister(reaching(system()));
        register.setText("Let the change land?\n", true);
        expect(await register.yanked(1)).toBe("1 line copied to the clipboard");
        register.pushText("And the next?\n", true);
        expect(await register.yanked(2)).toBe("2 lines copied to the clipboard");
        const unserved = new ClipboardRegister(reaching(null));
        unserved.setText("Let");
        const refused = new ClipboardRegister(reaching(system("", { write: "Document is not focused." })));
        refused.setText("Let");
        expect([await unserved.yanked(1), await refused.yanked(1)]).toEqual([null, null]);
    });

    it("yanks as vim does, saying a yank into `+` or `*` was copied to the clipboard, and any other as vim says it", async () => {
        const register = defineClipboard(reaching(system()));
        const said: string[] = [];
        const yank = yanking(register, (_, text) => said.push(text));
        const at = (line: number, ch = 0): Pos => ({ line, ch });
        /** An editor holding `text` selected from line `from` to line `to`, in visual mode where it says. */
        const editor = (text: string, from: number, to: number, visualMode = false) =>
            ({
                state: { vim: { visualMode, visualBlock: false, sel: { anchor: at(to, 3), head: at(from, 1) } } },
                getSelection: () => text,
                getCursor: (which: string) => (which === "start" ? at(from) : at(to)),
            }) as unknown as CodeMirrorV;
        const controller = Vim.getRegisterController();
        expect(yank(editor("Let the change land?", 4, 4), { registerName: registerNamed("+") ?? null, linewise: true }, [{ anchor: at(4), head: at(4) }], at(4, 2))).toEqual(at(4, 2));
        expect(controller.getRegister("+").toString()).toBe("Let the change land?\n");
        // Two lines selected whole, in visual mode: the cursor goes to the selection's start.
        expect(yank(editor("Let\nthe\n", 2, 4, true), { registerName: "*" }, [{ anchor: at(2, 5), head: at(4) }], at(9))).toEqual(at(2, 1));
        yank(editor("Let", 2, 2), { registerName: "a" }, [{ anchor: at(2), head: at(2) }], at(2));
        yank(editor("Let", 2, 2), {}, [{ anchor: at(2), head: at(2) }], at(2));
        await settled();
        expect(said).toEqual(['1 lines yanked into "a', "1 lines yanked", "1 line copied to the clipboard", "2 lines copied to the clipboard"]);
        expect(controller.unnamedRegister.toString()).toBe("Let");
    });
});
