// What was said, whole: the panel `g<` opens over the review, as vim's own `g<` shows the last message whole. Every
// line of the page says one sentence on one row, a list of numbers counted (`brief.ts`); here is what each left out:
// the top bar's last words, an error's whole text among them; what the line under the review says of the reply, each
// part whole; and what's left for later, by number. Esc closes it, the keyboard back in the review (`docs/dashboard.md`,
// *The keys*).
import { Command } from "cmdk";

/** One part of what was said, whole: where it was said, and its lines, each whole. */
export interface Said {
    heading: string;
    lines: string[];
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
    return (
        <Command.Dialog open={open} onOpenChange={closing} label="What was said, whole" overlayClassName="palette-overlay" contentClassName="palette keys-palette whole-palette">
            <Command.List>
                {shown.length === 0 ? <div className="whole-none">Nothing said.</div> : null}
                {shown.map((part) => (
                    <Command.Group key={part.heading} heading={part.heading}>
                        {part.lines.map((line, index) => (
                            <Command.Item key={`${part.heading} ${index}`} value={`${part.heading} ${index} ${line}`} onSelect={() => closing(false)}>
                                <span className="whole-line">{line}</span>
                            </Command.Item>
                        ))}
                    </Command.Group>
                ))}
            </Command.List>
        </Command.Dialog>
    );
}
