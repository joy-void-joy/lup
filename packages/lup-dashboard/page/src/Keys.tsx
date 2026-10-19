// The line of keys under a view: where the cursor is, the keys that apply there,
// and at its end, but in a comment, `?`, which opens the list of them all, in
// parts; Esc, `q` or `?` closes it, the keyboard back where it was (`keys.ts`;
// `docs/dashboard.md`, *The review*).
import type { KeyboardEvent } from "react";
import { Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";

import { barOf, type Part } from "./keys";

interface Props<P extends string> {
    parts: Part<P>[];
    /** Where the cursor is. */
    place: P;
    /** What the line says for each place, before its keys. */
    places: Record<P, string>;
    /** Whether the list of them all is open. */
    open: boolean;
    setOpen: (open: boolean) => void;
}

export function Keys<P extends string>({ parts, place, places, open, setOpen }: Props<P>) {
    function pressed(event: KeyboardEvent) {
        if (event.key === "?" || event.key === "q") {
            event.preventDefault();
            setOpen(false);
        }
    }
    return (
        <>
            <div className={place === "insert" ? "keys inserting" : "keys"}>
                <span className="keys-shown">
                    <span className="keys-place">{places[place]}</span>
                    {barOf(parts, place).map((key) => (
                        <span key={`${key.keys} ${key.short}`}>
                            <kbd>{key.keys}</kbd> {key.short}
                        </span>
                    ))}
                </span>
                {/* In a comment, `?` is a question mark. */}
                {place === "insert" ? null : (
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
