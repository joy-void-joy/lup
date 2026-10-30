// The line of keys under a view: what the cursor is on and what each verb
// would do to it there (`Here`), or, in a comment, the keys that end it; and at
// its end, but in a comment, `?`, which opens the palette of them all, searched
// by what one would do, what applies where the cursor is first, then each part,
// Enter running the one chosen where it's keys it runs (`runOf`), Esc closing
// it, the keyboard back where it was; at its end, whether the page's timings are measured in this browser, Enter
// switching them off or on (`timings.ts`); and, before `?`, `g<` where a line of the page leaves out what was said,
// which it shows whole (`Whole.tsx`). Once a chord is
// begun, as with Space, a panel over the line lists the keys that may follow
// and what each does, after a moment, so a chord typed whole shows none
// (`keys.ts`; `docs/dashboard.md`, *The keys*).
import { Command } from "cmdk";
import { useEffect, useState } from "react";

import { ENDING, WRITING, WRITING_HERE, chords, measuringSaid, runOf, searched, vimKeys, type Here, type Part } from "./keys";

interface Props {
    parts: Part[];
    /** What the cursor is on, and what each verb would do to it. */
    here: Here;
    /** Whether a comment is being written. */
    inserting: boolean;
    /** Whether the palette of them all is open. */
    open: boolean;
    setOpen: (open: boolean) => void;
    /** Run keys chosen in the palette, as vim's keymap names each, as if typed in the review, which takes the keyboard back: none, only that. */
    run: (keys: string[]) => void;
    /** The keys of a chord begun, as the list writes them (`␣`, `␣z`); none where none is. */
    pending?: string;
    /** How long a chord begun waits before what may follow is shown, in milliseconds. */
    waits?: number;
    /** Whether the page's timings are measured in this browser, and their switch (`timings.ts`); none before they're begun. */
    measuring?: { on: boolean; switched: (on: boolean) => void } | null;
    /** Whether a line of the page leaves out what was said, which `g<` shows whole: said at the line's end, so it's found. */
    cut?: boolean;
}

export function Keys({ parts, here, inserting, open, setOpen, run, pending = "", waits = 250, measuring = null, cut = false }: Props) {
    // The chord whose following keys are shown, once it has waited.
    const [shown, setShown] = useState("");
    useEffect(() => {
        if (pending === "") {
            setShown("");
            return;
        }
        const showing = setTimeout(() => setShown(pending), waits);
        return () => clearTimeout(showing);
    }, [pending, waits]);
    /** Close the palette, and run the keys chosen, where they're keys it runs, in the review, once it has the keyboard back. */
    function chose(keys: string[] | null) {
        setOpen(false);
        requestAnimationFrame(() => run(keys ?? []));
    }

    /** Open or close the palette as it asks, as Esc closes it, the keyboard going back to the review. */
    function closing(now: boolean) {
        setOpen(now);
        if (!now) {
            requestAnimationFrame(() => run([]));
        }
    }
    const following = shown === "" ? [] : chords(parts, shown);
    const ending = WRITING.flatMap((part) => part.keys).filter((key) => ENDING.includes(key.keys));
    // The key leading to these, saying what they do together, where the list has it, as `␣z` does.
    const leading = parts.flatMap((part) => part.keys).find((key) => key.keys.split(" ").includes(shown));
    return (
        <>
            {following.length === 0 ? null : (
                <div className="chords" role="status" aria-label={`Keys after ${shown}`}>
                    <div className="chords-title">
                        <kbd>{shown}</kbd> {leading === undefined ? "then" : leading.does}
                    </div>
                    <dl>
                        {following.map((each) => (
                            <div key={each.keys.join(" ")}>
                                <dt>
                                    {each.keys.map((key) => (
                                        <kbd key={key}>{key}</kbd>
                                    ))}
                                </dt>
                                <dd>{each.short}</dd>
                            </div>
                        ))}
                    </dl>
                </div>
            )}
            <div className={inserting ? "keys inserting" : "keys"}>
                {inserting ? (
                    <span className="keys-shown">
                        <span className="keys-place">{WRITING_HERE}</span>
                        {ending.map((key) => (
                            <span key={key.keys}>
                                <kbd>{key.keys}</kbd> {key.short}
                            </span>
                        ))}
                    </span>
                ) : (
                    <span className="keys-shown">
                        <span className="keys-place">{here.on}</span>
                        {here.reached.map((each) => (
                            <span key={each.keys}>
                                <kbd>{each.keys}</kbd> {each.on === null ? null : <span className="keys-on">{each.on}: </span>}
                                {each.says}
                            </span>
                        ))}
                    </span>
                )}
                {inserting || !cut ? null : (
                    <span className="keys-all">
                        <kbd>g&lt;</kbd> in full
                    </span>
                )}
                {/* In a comment, `?` is a question mark. */}
                {inserting ? null : (
                    <span className="keys-all">
                        <kbd>?</kbd> all keys
                    </span>
                )}
            </div>
            <Command.Dialog
                open={open}
                onOpenChange={closing}
                label="Every key"
                overlayClassName="palette-overlay"
                contentClassName="palette keys-palette"
                filter={(value, search, keywords) => searched(value, search, keywords ?? [])}
            >
                <Command.Input placeholder="What would you do? Every key, searchable…" />
                <Command.List>
                    <Command.Empty>No key does that.</Command.Empty>
                    {here.reached.length === 0 ? null : (
                        <Command.Group heading={`Here: ${here.on}`}>
                            {here.reached.map((each) => (
                                <Command.Item key={`here ${each.keys}`} value={`here ${each.keys} ${each.whole ?? each.says} ${each.on ?? ""}`} onSelect={() => chose(vimKeys(each.keys.split(" ")[0] ?? ""))}>
                                    <span>
                                        <kbd>{each.keys}</kbd> {each.on === null ? null : <span className="keys-on">{each.on}: </span>}
                                        {each.whole ?? each.says}
                                    </span>
                                </Command.Item>
                            ))}
                        </Command.Group>
                    )}
                    {parts.map((part) => (
                        <Command.Group key={part.title} heading={part.title}>
                            {part.keys.map((key) => (
                                <Command.Item
                                    key={`${part.title} ${key.keys}`}
                                    value={`${key.keys} ${key.short} · ${part.title}`}
                                    keywords={[key.does]}
                                    onSelect={() => chose(runOf(parts, part.title, key))}
                                >
                                    <span className="keys-entry">
                                        <kbd>{key.keys}</kbd> <span className="keys-does">{key.does}</span>
                                    </span>
                                </Command.Item>
                            ))}
                        </Command.Group>
                    ))}
                    {measuring === null ? null : (
                        <Command.Group heading="This page's timings">
                            <Command.Item
                                value={`timings ${measuringSaid(measuring.on).short}`}
                                keywords={[measuringSaid(measuring.on).does]}
                                onSelect={() => {
                                    measuring.switched(!measuring.on);
                                    chose(null);
                                }}
                            >
                                <span className="keys-entry">
                                    <kbd>{measuringSaid(measuring.on).keys}</kbd> <span className="keys-does">{measuringSaid(measuring.on).does}</span>
                                </span>
                            </Command.Item>
                        </Command.Group>
                    )}
                </Command.List>
            </Command.Dialog>
        </>
    );
}
