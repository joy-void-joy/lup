// A virtual display of the driver's own, for a windowed Chromium to take real key events, which headless Chromium never
// sees and the DevTools protocol only imitates: a keyboard layout's dead keys among them (#95), which arrive as a
// composition. `Xvfb` on a free display, its layout set by `setxkbmap`, keys typed by `xdotool`.
//
// `DISPLAY` is set for the programs run on it alone, never for the driver's process: set for the whole room, it breaks
// headless Chromium's WebGL.
import { execFile } from "node:child_process";
import { promisify } from "node:util";

import { start } from "./program.ts";

/** A keyboard layout, as `setxkbmap` names it. */
export interface Layout {
    layout: string;
    variant?: string;
    model?: string;
}

/** US-International: `'`, `` ` ``, `"`, `~` and `^` dead keys, as the operator's keyboard has them. */
export const US_INTERNATIONAL: Layout = { layout: "us", variant: "intl" };

/** A virtual display running, until it's closed. */
export interface Display extends AsyncDisposable {
    /** Its name, as `DISPLAY` holds it: `:1`. */
    name: string;
    /** The environment a program runs on it with: the driver's, with `DISPLAY` naming it. */
    env: NodeJS.ProcessEnv;
    /**
     * Press each key, `gap` milliseconds apart, as the keyboard sends it, named by the keysym the layout gives it:
     * `dead_acute` for US-International's `'`, `Escape`, `ctrl+d`. A keysym the layout has on no key is typed on one
     * `xdotool` maps it to for the while, unlike any keyboard.
     */
    press(keys: string[], gap?: number): Promise<void>;
    /** Type `text`, `gap` milliseconds apart, each character on the key and level the layout has it, with no dead key. */
    type(text: string, gap?: number): Promise<void>;
    close(): Promise<void>;
}

/** The screen's size, in pixels, and the layout its keyboard has: US unless given. */
export interface DisplayOptions {
    width: number;
    height: number;
    layout?: Layout;
}

/**
 * Start a virtual display on a free display number, with `options.layout`, and return it once its layout is set.
 *
 * `-noreset`: without it, `Xvfb` resets as its last client disconnects, its keymap with it, which `setxkbmap` usually
 * is: the layout would be gone before the browser connects, with nothing said.
 */
export async function display(options: DisplayOptions): Promise<Display> {
    const screen = `${options.width}x${options.height}x24`;
    const served = await start("Xvfb", ["-displayfd", "1", "-screen", "0", screen, "-nolisten", "tcp", "-noreset"], { what: "`Xvfb`" });
    const name = `:${served.first}`;
    const env = { ...process.env, DISPLAY: name };
    const run = promisify(execFile);
    const layout = options.layout ?? { layout: "us" };
    try {
        await run("setxkbmap", ["-rules", "evdev", "-model", layout.model ?? "pc105", "-layout", layout.layout, ...(layout.variant === undefined ? [] : ["-variant", layout.variant])], { env });
    } catch (failed) {
        await served.stop();
        throw failed;
    }
    return {
        name,
        env,
        async press(keys, gap = 12) {
            await run("xdotool", ["key", "--delay", String(gap), "--", ...keys], { env });
        },
        async type(text, gap = 12) {
            await run("xdotool", ["type", "--delay", String(gap), "--", text], { env });
        },
        close: served.stop,
        [Symbol.asyncDispose]: served.stop,
    };
}
