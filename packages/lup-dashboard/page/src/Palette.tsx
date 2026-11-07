// The command palette: every agent the host serves, typed for, each going to their
// group in the review. Ctrl+K opens it, Escape closes it.
import { Command } from "cmdk";
import { useEffect } from "react";

import { doing, type Agent } from "./agents";
import { feed } from "./editor";

interface Props {
    open: boolean;
    setOpen: (open: boolean) => void;
    agents: Agent[];
    /** Go to an agent's group, by their conversation's path. */
    select: (path: string) => void;
    now: Date;
}

export function Palette({ open, setOpen, agents, select, now }: Props) {
    useEffect(() => {
        function pressed(event: KeyboardEvent) {
            if (event.key === "k" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                setOpen(!open);
                if (open) {
                    requestAnimationFrame(() => feed([]));
                }
            }
        }
        document.addEventListener("keydown", pressed);
        return () => document.removeEventListener("keydown", pressed);
    }, [open, setOpen]);
    /** Open or close the palette as it asks, as Esc closes it, the keyboard going back to the review. */
    function closing(now: boolean) {
        setOpen(now);
        if (!now) {
            requestAnimationFrame(() => feed([]));
        }
    }
    return (
        <Command.Dialog
            open={open}
            onOpenChange={closing}
            label="Go to an agent"
            overlayClassName="palette-overlay"
            contentClassName="palette"
        >
            <Command.Input placeholder="Go to an agent…" />
            <Command.List>
                <Command.Empty>Nothing matches.</Command.Empty>
                <Command.Group heading="Agents">
                    {agents.map((agent) => (
                        <Command.Item
                            key={agent.talker.path}
                            value={agent.talker.path}
                            onSelect={() => {
                                select(agent.talker.path);
                                setOpen(false);
                            }}
                        >
                            <span className="mono">{agent.talker.path}</span>
                            <span className="state">{doing(agent.talker.activity, now)}</span>
                        </Command.Item>
                    ))}
                </Command.Group>
            </Command.List>
        </Command.Dialog>
    );
}
