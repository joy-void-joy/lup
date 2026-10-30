// What a page measures of itself in the browser it's used in: how long each key takes to reach the screen, its long
// animation frames, and the page's size at the time. Timings and sizes only, never what's typed or shown
// (`docs/dashboard.md`, *Its timings*; the host keeps what it sends, `lup_dev/host/timings.py`, whose `Report` this
// file's types mirror). Standalone, with no React and nothing of the dashboard's, so a site's page under #292 runs the
// same script, given its own kinds of key, its own measures of size, and where it reports.
//
// - **Each key** is read from the browser's Event Timing API (`PerformanceObserver`, `type: "event"`): its `keydown`'s
//   entry, matched to the key the script saw go down by its time, `startTime` being the event's `timeStamp`, so the
//   kind the page named it as it went down is the entry's (`Tally.entry`). Event Timing says nothing of a key under
//   16 ms: a key seen going down whose entry never came while a later key's did, or within a minute, is counted under
//   the floor. Neither `interactionId` nor `keyup` is read, so how a browser groups a key's events doesn't matter.
// - **Long animation frames,** where the browser reports them (`long-animation-frame`), are counted with what ran in
//   them, by what began each script, never an element of the page's (`invoked`).
// - **What a browser doesn't report** is said in every report (`unmeasured`), read from
//   `PerformanceObserver.supportedEntryTypes`.
// - **Sent** every 5 minutes, and as the page's tab is hidden or closed, with `fetch`'s `keepalive`, which outlives
//   the page: each window measured since the last report was answered, numbered, so one sent twice is kept once.
// - **Switched off** per browser, kept in its local storage (`Measuring.switched`): off, nothing is measured or sent,
//   and what was measured and not yet sent is dropped.

/** An entry type of the browser's performance timeline the script reads: Event Timing's, and long animation frames'. */
export type EntryType = "event" | "long-animation-frame";

/** How many took how long, by the whole milliseconds each took, as JSON writes an object's keys. */
export type Histogram = Record<string, number>;

/** How long one kind of key took (`lup_dev.host.timings.Latencies`). */
export interface Latencies {
    /** From the key going down to the next paint: Event Timing's `duration`, in 8 ms steps. */
    painted: Histogram;
    /** From the key going down to the page's first handler of it starting. */
    waited: Histogram;
    /** The page's handlers of it. */
    handled: Histogram;
    /** The keys under the browser's floor, of which Event Timing says nothing. */
    under: number;
}

/** A page's long animation frames, each in whole milliseconds (`lup_dev.host.timings.Frames`). */
export interface Frames {
    count: number;
    total: number;
    blocking: number;
    longest: number;
    /** How long the scripts in them ran, by what began each (`invoked`). */
    ran: Record<string, number>;
}

/** What a page session measured over a stretch of it (`lup_dev.host.timings.Window`). */
export interface Window {
    sequence: number;
    start: string;
    end: string;
    /** The largest of each of the page's measures seen in it. */
    size: Record<string, number>;
    keys: Record<string, Latencies>;
    /** Event Timing's entries of a key going down that matched no key the script saw go down. */
    unmatched: number;
    /** None where the browser reports no long animation frames. */
    frames: Frames | null;
}

/** The browser a page session runs in, as the page reads it: never its whole user agent string. */
export interface Browser {
    name: string;
    version: string;
    system: string;
    device: "desktop" | "tablet" | "phone";
    cores: number | null;
}

/** What a page session sends (`lup_dev.host.timings.Report`). */
export interface Report {
    page: string;
    session: string;
    build: string | null;
    browser: Browser;
    unmeasured: EntryType[];
    windows: Window[];
}

/** Where reports go: posted as JSON to `address`, wrapped as `wrapped` says, the report itself where it says nothing. */
export interface Sending {
    address: string;
    wrapped?: (report: Report) => unknown;
}

/** What the page gives the script. */
export interface Options {
    /** Which page this is, as the host keeps its reports: `dashboard`. */
    page: string;
    /** The page's build, as its server names it, where it's known by now. */
    build: () => string | null;
    /** The kind of key `event` is, asked as it goes down before the page handles it; none leaves it out, as a modifier alone. */
    kind?: (event: KeyboardEvent) => string | null;
    /** The page's size now, by measures it names: `lines`, `items`, `drawers open`. */
    size?: () => Readonly<Record<string, number>>;
    send: Sending;
    /** How long a window lasts before it's sent, in milliseconds. */
    every?: number;
    /** Where the switch is kept: this browser's local storage, unless given. */
    kept?: Storage | null;
}

/** The script measuring a page, or switched off in this browser. */
export interface Measuring {
    /** Whether it measures in this browser. */
    readonly on: boolean;
    /** Switch it on or off in this browser, kept there: off, nothing is measured or sent, and what wasn't sent yet is dropped. */
    switched(on: boolean): void;
    /** Stop measuring this page, sending nothing more, as the page goes. */
    stop(): void;
}

/** What Event Timing says of one event (`PerformanceEventTiming`), as the script reads it. */
export interface EventEntry {
    name: string;
    startTime: number;
    duration: number;
    processingStart: number;
    processingEnd: number;
}

/** What a long animation frame's entry says (`PerformanceLongAnimationFrameTiming`), as the script reads it. */
export interface FrameEntry {
    duration: number;
    blockingDuration?: number;
    scripts?: readonly { invoker?: string; invokerType?: string; duration: number }[];
}

/** The local storage item the switch is kept in, `off` where it's switched off. */
export const SWITCH = "lup-timings";

/** The keys that, pressed alone, do nothing anyone waits on. */
const MODIFIERS = new Set(["Shift", "Control", "Alt", "Meta", "AltGraph", "CapsLock", "Fn", "Hyper", "Super", "OS"]);

/** Whether `event` is a modifier going down alone, which the default kind of key leaves out. */
export function modifierAlone(event: Pick<KeyboardEvent, "key">): boolean {
    return MODIFIERS.has(event.key);
}

/** The kind of key every key is where the page names none: `other`, a modifier alone left out. */
export function anyKey(event: Pick<KeyboardEvent, "key">): string | null {
    return modifierAlone(event) ? null : "other";
}

/** Round `value`, in milliseconds, to Event Timing's own 8 ms steps, so a window's histograms stay short. */
export function stepped(value: number): number {
    return Math.max(0, Math.round(value / 8) * 8);
}

/**
 * Say what began a script of a long animation frame: its invoker's type, and the event or the API that called it, an
 * element's name and id dropped from an event listener's (`DIV#name.onclick` is `event-listener onclick`), a script's
 * address from a script's.
 */
export function invoked(script: { invoker?: string; invokerType?: string }): string {
    const type = script.invokerType ?? "script";
    const invoker = script.invoker ?? "";
    // The host keeps 128 characters of it: an API's name is far shorter, and one longer cut, rather than the report refused.
    switch (type) {
        case "event-listener":
            return `${type} ${invoker.slice(invoker.lastIndexOf(".") + 1)}`.slice(0, 128);
        case "classic-script":
        case "module-script":
            return type;
        default:
            return invoker === "" ? type : `${type} ${invoker}`.slice(0, 128);
    }
}

/** A key seen going down, waiting for its entry: when, and the kind the page named it. */
interface Pressed {
    at: number;
    kind: string;
}

/**
 * What the script counts between two reports, pure: keys seen going down matched to their entries, the long animation
 * frames, and the page's size, closed into a window as a report is made (`closed`).
 */
export class Tally {
    private pending: Pressed[] = [];
    private keys = new Map<string, Latencies>();
    private unmatched = 0;
    private frames: Frames | null;
    private size: Record<string, number> = {};

    /** `framed`: whether the browser reports long animation frames; `most`: the most of them by what began them a window keeps. */
    constructor(
        private readonly framed: boolean,
        private readonly most = 8,
    ) {
        this.frames = framed ? emptyFrames() : null;
    }

    /** A key went down at `at`, of kind `kind`. */
    pressed(at: number, kind: string): void {
        this.pending.push({ at, kind });
    }

    /**
     * Count Event Timing's entry of an event, a key going down's alone: matched to the key it's of, by its time, the
     * nearest within a millisecond where none is the same, as a browser that rounds one of them; every key before it
     * still waiting is under the floor, its entry, had it one, coming first. One matching no key is counted unmatched.
     */
    entry(entry: EventEntry): void {
        if (entry.name !== "keydown") {
            return;
        }
        let index = this.pending.findIndex((each) => each.at === entry.startTime);
        if (index === -1) {
            const near = this.pending.map((each) => Math.abs(each.at - entry.startTime));
            const least = Math.min(...near);
            index = least <= 1 ? near.indexOf(least) : -1;
        }
        const key = this.pending[index];
        if (key === undefined) {
            this.unmatched += 1;
            return;
        }
        for (const earlier of this.pending.slice(0, index)) {
            this.of(earlier.kind).under += 1;
        }
        this.pending = this.pending.slice(index + 1);
        const latencies = this.of(key.kind);
        add(latencies.painted, Math.round(entry.duration));
        add(latencies.waited, stepped(entry.processingStart - entry.startTime));
        add(latencies.handled, stepped(entry.processingEnd - entry.processingStart));
    }

    /** Count every key still waiting that went down before `before` under the floor: its entry, had it one, would have come. */
    settled(before: number): void {
        for (const each of this.pending.filter((key) => key.at < before)) {
            this.of(each.kind).under += 1;
        }
        this.pending = this.pending.filter((key) => key.at >= before);
    }

    /** Count a long animation frame, and how long each script in it ran, by what began it. */
    frame(entry: FrameEntry): void {
        const frames = this.frames;
        if (frames === null) {
            return;
        }
        const duration = Math.round(entry.duration);
        frames.count += 1;
        frames.total += duration;
        frames.blocking += Math.round(entry.blockingDuration ?? 0);
        frames.longest = Math.max(frames.longest, duration);
        for (const script of entry.scripts ?? []) {
            const what = invoked(script);
            frames.ran[what] = (frames.ran[what] ?? 0) + Math.round(script.duration);
        }
    }

    /** Keep the page's size now, each measure the largest seen in the window. */
    sized(size: Readonly<Record<string, number>>): void {
        for (const [name, value] of Object.entries(size)) {
            this.size[name] = Math.max(this.size[name] ?? 0, Math.round(value));
        }
    }

    /**
     * Close what's counted into window `sequence`, from `start` to `end`, and begin the next; none where nothing was
     * counted, a key's entry or a long frame, and what's counted goes on. Keys still waiting for their entry wait on.
     */
    closed(sequence: number, start: Date, end: Date): Window | null {
        const frames = this.frames;
        if (this.keys.size === 0 && this.unmatched === 0 && (frames === null || frames.count === 0)) {
            return null;
        }
        const ran = Object.entries(frames?.ran ?? {})
            .sort(([, a], [, b]) => b - a)
            .slice(0, this.most);
        const window: Window = {
            sequence,
            start: start.toISOString(),
            end: end.toISOString(),
            size: this.size,
            keys: Object.fromEntries(this.keys),
            unmatched: this.unmatched,
            frames: frames === null ? null : { ...frames, ran: Object.fromEntries(ran) },
        };
        this.keys = new Map();
        this.unmatched = 0;
        this.frames = this.framed ? emptyFrames() : null;
        this.size = {};
        return window;
    }

    private of(kind: string): Latencies {
        const found = this.keys.get(kind);
        if (found !== undefined) {
            return found;
        }
        const made: Latencies = { painted: {}, waited: {}, handled: {}, under: 0 };
        this.keys.set(kind, made);
        return made;
    }
}

function emptyFrames(): Frames {
    return { count: 0, total: 0, blocking: 0, longest: 0, ran: {} };
}

function add(histogram: Histogram, value: number): void {
    histogram[value] = (histogram[value] ?? 0) + 1;
}

/** What the browser says of itself and its screen, as the script reads it. */
export interface Seen {
    userAgent: string;
    /** Whether its main pointer is coarse, a finger's. */
    coarse: boolean;
    /** Its screen's shorter side, in CSS pixels. */
    shorter: number;
    cores: number | null;
}

/**
 * Return the browser a page runs in: its name and major version and its system, from its user agent's product tokens,
 * `other` for what none names; and its device's kind, from its pointer and its screen, since a tablet may say it's a
 * desktop: a coarse pointer on a screen under 600 pixels a side is a phone's, on a larger one a tablet's.
 */
export function browserOf(seen: Seen): Browser {
    const agent = seen.userAgent;
    const named: [string, RegExp][] = [
        ["Edge", /Edg(?:e|A|iOS)?\/(\d+)/],
        ["Firefox", /(?:Firefox|FxiOS)\/(\d+)/],
        ["Chrome", /(?:Chrome|CriOS)\/(\d+)/],
        ["Safari", /Version\/(\d+)[^ ]* (?:Mobile\/\S+ )?Safari\//],
    ];
    const found = named.map(([name, pattern]) => [name, pattern.exec(agent)?.[1]] as const).find(([, version]) => version !== undefined);
    const systems: [string, RegExp][] = [
        ["Android", /Android/],
        ["iOS", /iPhone|iPad|iPod/],
        ["ChromeOS", /CrOS/],
        ["Windows", /Windows/],
        ["macOS", /Macintosh|Mac OS X/],
        ["Linux", /Linux|X11/],
    ];
    const system = systems.find(([, pattern]) => pattern.test(agent))?.[0] ?? "other";
    const device = !seen.coarse ? "desktop" : seen.shorter < 600 ? "phone" : "tablet";
    return { name: found?.[0] ?? "other", version: found?.[1] ?? "", system, device, cores: seen.cores };
}

/** The longest body a report is sent with: a request that outlives its page carries 64 KB at most. */
const LONGEST = 60_000;

/** The most windows waiting to be sent: the oldest past them dropped, as when the page's server is out of reach for an hour. */
const WAITING = 12;

/**
 * Return the windows of `report` it carries in under `longest` characters, wrapped as `wrapped` says: the latest that
 * fit, at least one, the earlier left for the next report.
 */
export function fitted(report: Report, wrapped: (report: Report) => unknown, longest = LONGEST): Window[] {
    let windows = report.windows;
    while (windows.length > 1 && JSON.stringify(wrapped({ ...report, windows })).length > longest) {
        windows = windows.slice(1);
    }
    return windows;
}

/** Make a page session's id: random, 12 hexadecimal digits, from `crypto.getRandomValues`, which a page on plain http has too. */
function sessionId(): string {
    return [...crypto.getRandomValues(new Uint8Array(6))].map((each) => each.toString(16).padStart(2, "0")).join("");
}

/** Return this browser's local storage, or none where it refuses the page one. */
function storage(): Storage | null {
    try {
        return window.localStorage;
    } catch (refused) {
        console.warn("lup's timings: no local storage, so switching them off lasts for this page alone", refused);
        return null;
    }
}

/**
 * Measure the page as `options` says, unless it's switched off in this browser, and return the switch: on, every key
 * going down is asked its kind, each window is sent every `every` milliseconds and as the page's tab is hidden or the
 * page goes, and a window with nothing measured isn't sent.
 */
export function measure(options: Options): Measuring {
    const kept = options.kept === undefined ? storage() : options.kept;
    const every = options.every ?? 5 * 60_000;
    const kind = options.kind ?? anyKey;
    const wrapped = options.send.wrapped ?? ((report: Report) => report);
    let on = kept?.getItem(SWITCH) !== "off";
    let running: (() => void) | null = null;

    function start(): () => void {
        const supported = PerformanceObserver.supportedEntryTypes ?? [];
        const unmeasured = (["event", "long-animation-frame"] as const).filter((each) => !supported.includes(each));
        const tally = new Tally(supported.includes("long-animation-frame"));
        const session = sessionId();
        const browser = browserOf({
            userAgent: navigator.userAgent,
            coarse: matchMedia("(pointer: coarse)").matches,
            shorter: Math.min(screen.width, screen.height),
            cores: navigator.hardwareConcurrency || null,
        });
        let sequence = 0;
        let opened = new Date();
        let waiting: Window[] = [];
        // The windows sent and not yet answered, by number: not sent again meanwhile, as when the tab is hidden and the
        // page goes at once, and sent with the next report where their answer says they weren't kept.
        const flying = new Set<number>();
        let lastSized = -Infinity;
        const observers: PerformanceObserver[] = [];

        const pressed = (event: KeyboardEvent) => {
            const named = kind(event);
            if (named === null) {
                return;
            }
            tally.pressed(event.timeStamp, named);
            if (options.size !== undefined && event.timeStamp - lastSized > 1000) {
                lastSized = event.timeStamp;
                tally.sized(options.size());
            }
        };
        const read = (entries: PerformanceEntryList) => {
            for (const entry of [...entries].sort((a, b) => a.startTime - b.startTime)) {
                if (entry.entryType === "event") {
                    tally.entry(entry as PerformanceEventTiming);
                } else if (entry.entryType === "long-animation-frame") {
                    tally.frame(entry as unknown as FrameEntry);
                }
            }
        };
        if (supported.includes("event")) {
            const observer = new PerformanceObserver((list) => read(list.getEntries()));
            observer.observe({ type: "event", durationThreshold: 16 } as PerformanceObserverInit);
            observers.push(observer);
        }
        if (supported.includes("long-animation-frame")) {
            const observer = new PerformanceObserver((list) => read(list.getEntries()));
            observer.observe({ type: "long-animation-frame" });
            observers.push(observer);
        }

        /** Close the window and send every one waiting; `going`, as the tab is hidden, keys of the last second wait on, their frame perhaps still to come. */
        const report = (going: boolean) => {
            read(observers.flatMap((each) => each.takeRecords()));
            tally.settled(performance.now() - (going ? 1000 : 60_000));
            if (options.size !== undefined) {
                tally.sized(options.size());
            }
            const closing = new Date();
            const window = tally.closed(sequence + 1, opened, closing);
            opened = closing;
            if (window !== null) {
                sequence += 1;
                waiting = [...waiting, window].slice(-WAITING);
            }
            const unsent = waiting.filter((each) => !flying.has(each.sequence));
            if (unsent.length === 0) {
                return;
            }
            const whole: Report = { page: options.page, session, build: options.build(), browser, unmeasured, windows: unsent };
            const windows = fitted(whole, wrapped);
            const sent = windows.map((each) => each.sequence);
            for (const each of sent) {
                flying.add(each);
            }
            const landed = () => {
                for (const each of sent) {
                    flying.delete(each);
                }
            };
            void fetch(options.send.address, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(wrapped({ ...whole, windows })),
                keepalive: true,
            }).then(
                async (response) => {
                    landed();
                    if (response.ok || response.status === 400 || response.status === 422) {
                        // Kept, or never to be: what the server refused to read it would refuse again.
                        waiting = waiting.filter((each) => !sent.includes(each.sequence));
                    }
                    if (!response.ok) {
                        console.warn("lup's timings: a report wasn't kept", response.status, await response.text());
                    }
                },
                (failed: unknown) => {
                    landed();
                    console.warn("lup's timings: a report wasn't sent, and goes with the next", failed);
                },
            );
        };
        const hidden = () => {
            if (document.visibilityState === "hidden") {
                report(true);
            }
        };
        const gone = () => report(true);
        addEventListener("keydown", pressed, { capture: true });
        document.addEventListener("visibilitychange", hidden);
        addEventListener("pagehide", gone);
        const ticking = setInterval(() => report(false), every);
        return () => {
            removeEventListener("keydown", pressed, { capture: true });
            document.removeEventListener("visibilitychange", hidden);
            removeEventListener("pagehide", gone);
            clearInterval(ticking);
            for (const each of observers) {
                each.disconnect();
            }
        };
    }

    if (on) {
        running = start();
    }
    return {
        get on() {
            return on;
        },
        switched(now: boolean) {
            on = now;
            if (now) {
                kept?.removeItem(SWITCH);
                running ??= start();
            } else {
                kept?.setItem(SWITCH, "off");
                running?.();
                running = null;
            }
        },
        stop() {
            running?.();
            running = null;
        },
    };
}
