// Space s's picker: where the thing at the cursor goes, chosen among what `choicesFor` offers (`picking.ts`), or a new pile
// by the words typed, which opens at the top of its repository, nobody holding it, as the draft is sent. Enter chooses,
// Esc closes, the keyboard back in the review. The choice is the draft's, nothing moving until Ctrl+Enter.
import { Command } from "cmdk";
import { useState } from "react";

import type { Choice } from "./picking";
import type { Destination } from "./review";

interface Props {
    /** What's sent, as the line of keys names it; none while the picker's closed. */
    on: string | null;
    choices: readonly Choice[];
    /** Send it to `to`, or nowhere, `to` none, where it goes where it is. */
    choose: (to: Destination | null) => void;
    /** Close it, choosing nothing. */
    close: () => void;
    /** Say why a choice can't be chosen yet. */
    say: (said: string) => void;
}

export function Picker({ on, choices, choose, close, say }: Props) {
    const [typed, setTyped] = useState("");
    const words = typed.trim();
    // A new pile by what's typed, where no choice is called so.
    const fresh = words !== "" && !choices.some((each) => each.label.toLowerCase() === words.toLowerCase());
    /** Choose `choice`, closing the picker: a choice still to come says so and chooses nothing. */
    function chosen(choice: Choice) {
        setTyped("");
        if (choice.to === "unbuilt") {
            say(`␣s ${choice.label}: ${choice.kind}.`);
            close();
            return;
        }
        choose(choice.to);
    }
    return (
        <Command.Dialog
            open={on !== null}
            onOpenChange={(open) => {
                if (!open) {
                    setTyped("");
                    close();
                }
            }}
            label={`Send ${on ?? ""} to`}
            overlayClassName="palette-overlay"
            contentClassName="palette picker"
        >
            <Command.Input placeholder={`Send ${on ?? "it"} to… (or type a new pile's name)`} value={typed} onValueChange={setTyped} />
            <Command.List>
                <Command.Empty>Nothing matches.</Command.Empty>
                <Command.Group heading="Send it to">
                    {choices.map((choice) => (
                        <Command.Item key={choice.key} value={`${choice.label} ${choice.kind} ${choice.key}`} onSelect={() => chosen(choice)} disabled={false}>
                            <span className="picker-label">{choice.label}</span>
                            <span className="state">{choice.kind}</span>
                        </Command.Item>
                    ))}
                    {fresh ? (
                        <Command.Item key="new pile" value={`${words} new pile`} onSelect={() => chosen({ key: "new pile", label: words, kind: "new pile", to: { pile: words } })}>
                            <span className="picker-label">{words}</span>
                            <span className="state">new pile, at the top, nobody holding it</span>
                        </Command.Item>
                    ) : null}
                </Command.Group>
            </Command.List>
        </Command.Dialog>
    );
}
