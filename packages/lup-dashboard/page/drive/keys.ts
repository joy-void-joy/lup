// Keys sent to the page through the DevTools protocol as a keyboard sends them: each when its time comes, never waiting
// for the page to handle the one before. Playwright's own `keyboard.press` waits for each, which hides the keys queuing
// behind a busy page: typing that lagged by seconds for the operator read as 280 ms a key that way (#341).
//
// A dead key can't be sent this way as a keyboard sends it: a real one arrives as a composition, which the protocol only
// imitates. `Display` types those (`display.ts`).
import { setTimeout as sleep } from "node:timers/promises";
import type { CDPSession } from "playwright";

/** A key sent: what it was, and when, in milliseconds since the epoch, as the page's `performance.timeOrigin + performance.now()` counts. */
export interface Sent {
    key: string;
    at: number;
}

/** Keys sent to one page, never waiting on it. */
export interface Keys {
    /** Type each character of `text`, `gap` milliseconds apart, on a US keyboard, and return each as sent, once the page has taken every one. */
    type(text: string, gap?: number): Promise<Sent[]>;
    /**
     * Press each key, `gap` milliseconds apart, and return each as sent, once the page has taken every one: a character,
     * or a key by its name (`Escape`, `Enter`, `ArrowDown`), after the modifiers held with it (`Control+d`, `Shift+Tab`).
     */
    press(keys: string[], gap?: number): Promise<Sent[]>;
}

/** The keys sent through `session`, a DevTools session on the page. */
export function keys(session: CDPSession): Keys {
    const send = async (keys: string[], gap: number): Promise<Sent[]> => {
        const sent: Sent[] = [];
        const taken: Promise<unknown>[] = [];
        for (const [index, key] of keys.entries()) {
            if (index > 0 && gap > 0) {
                await sleep(gap);
            }
            const [down, up] = events(key);
            sent.push({ key, at: performance.timeOrigin + performance.now() });
            taken.push(session.send("Input.dispatchKeyEvent", down), session.send("Input.dispatchKeyEvent", up));
        }
        await Promise.all(taken);
        return sent;
    };
    return {
        type: (text, gap = 0) => send([...text], gap),
        press: (keys, gap = 0) => send(keys, gap),
    };
}

/** What a key down or up is sent as: the protocol's `Input.dispatchKeyEvent`'s parameters. */
export interface KeyEvent {
    /** `keyDown` for a key typing text, `rawKeyDown` for one that doesn't, as a browser's own input sends them. */
    type: "keyDown" | "rawKeyDown" | "keyUp";
    modifiers: number;
    key: string;
    code: string;
    windowsVirtualKeyCode: number;
    text?: string;
    unmodifiedText?: string;
}

/** The protocol's bit for each modifier held. */
const MODIFIERS: Record<string, number> = { Alt: 1, Control: 2, Meta: 4, Shift: 8 };

/** The keys a US keyboard types a character on with Shift, by the character, and the one it types without. */
const SHIFTED: Record<string, string> = {
    "~": "`",
    "!": "1",
    "@": "2",
    "#": "3",
    $: "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    _: "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
};

/** Each key but a letter's or a digit's: its `code`, its Windows key code, and the text it types, where it types one. */
const NAMED: Record<string, { code: string; keyCode: number; text?: string }> = {
    " ": { code: "Space", keyCode: 32, text: " " },
    "`": { code: "Backquote", keyCode: 192, text: "`" },
    "-": { code: "Minus", keyCode: 189, text: "-" },
    "=": { code: "Equal", keyCode: 187, text: "=" },
    "[": { code: "BracketLeft", keyCode: 219, text: "[" },
    "]": { code: "BracketRight", keyCode: 221, text: "]" },
    "\\": { code: "Backslash", keyCode: 220, text: "\\" },
    ";": { code: "Semicolon", keyCode: 186, text: ";" },
    "'": { code: "Quote", keyCode: 222, text: "'" },
    ",": { code: "Comma", keyCode: 188, text: "," },
    ".": { code: "Period", keyCode: 190, text: "." },
    "/": { code: "Slash", keyCode: 191, text: "/" },
    Enter: { code: "Enter", keyCode: 13, text: "\r" },
    Tab: { code: "Tab", keyCode: 9 },
    Escape: { code: "Escape", keyCode: 27 },
    Backspace: { code: "Backspace", keyCode: 8 },
    Delete: { code: "Delete", keyCode: 46 },
    ArrowLeft: { code: "ArrowLeft", keyCode: 37 },
    ArrowUp: { code: "ArrowUp", keyCode: 38 },
    ArrowRight: { code: "ArrowRight", keyCode: 39 },
    ArrowDown: { code: "ArrowDown", keyCode: 40 },
    Home: { code: "Home", keyCode: 36 },
    End: { code: "End", keyCode: 35 },
    PageUp: { code: "PageUp", keyCode: 33 },
    PageDown: { code: "PageDown", keyCode: 34 },
};

/**
 * Return the events a key is sent as, down then up, on a US keyboard: `chord` a character or a key's name, after the
 * modifiers held with it, each followed by `+`. A character no key of it types, as `é`, is sent as its text alone, as
 * an input method would give it.
 */
export function events(chord: string): [KeyEvent, KeyEvent] {
    const parts = chord.length > 1 ? chord.split(/\+(?!$)/) : [chord];
    const key = parts.pop() ?? chord;
    let modifiers = 0;
    for (const held of parts) {
        const bit = MODIFIERS[held];
        if (bit === undefined) {
            throw new Error(`${held} in ${chord} isn't a modifier: ${Object.keys(MODIFIERS).join(", ")}`);
        }
        modifiers |= bit;
    }
    const unshifted = SHIFTED[key] ?? (/^[A-Z]$/.test(key) ? key.toLowerCase() : key);
    if (unshifted !== key) {
        modifiers |= MODIFIERS["Shift"] ?? 0;
    }
    const named = NAMED[unshifted];
    let code: string;
    let keyCode: number;
    let text: string | undefined;
    if (named !== undefined) {
        ({ code, keyCode } = named);
        text = named.text === undefined ? undefined : key === unshifted ? named.text : key;
    } else if (/^[a-z]$/.test(unshifted)) {
        code = `Key${unshifted.toUpperCase()}`;
        keyCode = unshifted.toUpperCase().charCodeAt(0);
        text = key;
    } else if (/^[0-9]$/.test(unshifted)) {
        code = `Digit${unshifted}`;
        keyCode = unshifted.charCodeAt(0);
        text = key;
    } else if ([...key].length === 1) {
        code = "";
        keyCode = 0;
        text = key;
    } else {
        throw new Error(`${key} isn't a key this driver knows: a character, or one of ${Object.keys(NAMED).filter((each) => each.length > 1).join(", ")}`);
    }
    // A key held with Control, Alt or Meta types nothing: it's a command.
    if ((modifiers & ~(MODIFIERS["Shift"] ?? 0)) !== 0) {
        text = undefined;
    }
    const down: KeyEvent = { type: text === undefined ? "rawKeyDown" : "keyDown", modifiers, key, code, windowsVirtualKeyCode: keyCode };
    if (text !== undefined) {
        down.text = text;
        down.unmodifiedText = text;
    }
    return [down, { type: "keyUp", modifiers, key, code, windowsVirtualKeyCode: keyCode }];
}
