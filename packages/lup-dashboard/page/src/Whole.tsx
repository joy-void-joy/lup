// What was said, whole: the panel `g<` opens over the review, as vim's own `g<` shows the last message whole. Every
// line of the page says one sentence on one row, a list of numbers counted (`brief.ts`); here is what each left out:
// the top bar's last words, an error's whole text among them; what the line under the review says of the reply, each
// part whole; and what's left for later, by number. Esc closes it, the keyboard back in the review (`docs/dashboard.md`,
// *The keys*).
import { Command } from "cmdk";
import { useEffect } from "react";

/** One part of what was said, whole: where it was said, and its lines, each whole; and, line by line, what Ctrl+Enter on one sends alone, none where it sends nothing apart. */
export interface Said {
    heading: string;
    lines: string[];
    sends?: readonly ((() => void) | null)[];
}

interface Props {
    open: boolean;
    setOpen: (open: boolean) => void;
    /** What was said, whole, each part where it was said; a part with no lines isn't shown. */
    said: readonly Said[];
    /** Give the keyboard back to the review, once the panel has let it go. */
    back: () => void;
}

export function Whole({ open, setOpen, said, back }: Props) {
    /** Open or close the panel as it asks, as Esc closes it, the keyboard going back to the review. */
    function closing(now: boolean) {
        setOpen(now);
        if (!now) {
            requestAnimationFrame(back);
        }
    }
    const shown = said.filter((each) => each.lines.length > 0);
    // Ctrl+Enter on a line that sends what goes there alone sends it, wherever the panel holds the keyboard: its
    // dialog takes keys before the list inside it does.
    useEffect(() => {
        if (!open) {
            return;
        }
        const pressed = (event: KeyboardEvent) => {
            if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) {
                return;
            }
            const selected = document.querySelector<HTMLElement>(".whole-palette [cmdk-item][data-selected='true']");
            const send = shown[Number(selected?.dataset.part ?? -1)]?.sends?.[Number(selected?.dataset.index ?? -1)] ?? null;
            if (send !== null) {
                event.preventDefault();
                event.stopPropagation();
                send();
                requestAnimationFrame(back);
            }
        };
        document.addEventListener("keydown", pressed, true);
        return () => document.removeEventListener("keydown", pressed, true);
    }, [open, shown, back]);
    return (
        <Command.Dialog
            open={open}
            onOpenChange={closing}
            label="What was said, whole"
            overlayClassName="palette-overlay"
            contentClassName="palette keys-palette whole-palette"
        >
            <Command.List>
                {shown.length === 0 ? <div className="whole-none">Nothing said.</div> : null}
                {shown.map((part, at) => (
                    <Command.Group key={part.heading} heading={part.heading}>
                        {part.lines.map((line, index) => (
                            <Command.Item key={`${part.heading} ${index}`} value={`${part.heading} ${index} ${line}`} data-part={at} data-index={index} onSelect={() => closing(false)}>
                                <span className="whole-line">{line}</span>
                            </Command.Item>
                        ))}
                    </Command.Group>
                ))}
            </Command.List>
        </Command.Dialog>
    );
}
