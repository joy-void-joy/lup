// The line of keys under a view: what the cursor is on and what each verb
// would do to it there (`Here`), or, in a comment, the keys that end it; and at
// its end, but in a comment, `?`, which opens the list of them all, in parts;
// Esc, `q` or `?` closes it, the keyboard back where it was. Once a chord is
// begun, as with Space, a panel over the line lists the keys that may follow
// and what each does, after a moment, so a chord typed whole shows none
// (`keys.ts`; `docs/dashboard.md`, *The keys*).
import { useEffect, useState, type KeyboardEvent } from "react";
import { Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";

import { ENDING, WRITING, WRITING_HERE, chords, type Here, type Part } from "./keys";

interface Props {
    parts: Part[];
    /** What the cursor is on, and what each verb would do to it. */
    here: Here;
    /** Whether a comment is being written. */
    inserting: boolean;
    /** Whether the list of them all is open. */
    open: boolean;
    setOpen: (open: boolean) => void;
    /** The keys of a chord begun, as the list writes them (`␣`, `␣z`); none where none is. */
    pending?: string;
    /** How long a chord begun waits before what may follow is shown, in milliseconds. */
    waits?: number;
}

export function Keys({ parts, here, inserting, open, setOpen, pending = "", waits = 250 }: Props) {
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
    function pressed(event: KeyboardEvent) {
        if (event.key === "?" || event.key === "q") {
            event.preventDefault();
            setOpen(false);
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
                {/* In a comment, `?` is a question mark. */}
                {inserting ? null : (
                    <span className="keys-all">
                        <kbd>?</kbd> all keys
                    </span>
                )}
            </div>
            <ModalOverlay isOpen={open} onOpenChange={setOpen} isDismissable className="keys-overlay">
                <Modal className="keys-list">
                    {/* Around the dialog, which takes the keyboard as it opens, so its keys reach here. */}
                    <div onKeyDown={pressed}>
                        <Dialog aria-label="All keys">
                            {parts.map((part) => (
                                <section key={part.title}>
                                    <Heading level={2}>{part.title}</Heading>
                                    <dl>
                                        {part.keys.map((key) => (
                                            <div key={`${key.keys} ${key.does}`}>
                                                <dt>
                                                    <kbd>{key.keys}</kbd>
                                                </dt>
                                                <dd>{key.does}</dd>
                                            </div>
                                        ))}
                                    </dl>
                                </section>
                            ))}
                        </Dialog>
                    </div>
                </Modal>
            </ModalOverlay>
        </>
    );
}
