// The command palette: every place the page can go and everything it can do,
// typed for: the review, and each agent's conversation. Ctrl+K opens it, Escape
// closes it.
import { Command } from "cmdk";
import { useEffect } from "react";

import { doing, type Agent } from "./agents";

interface Props {
    open: boolean;
    setOpen: (open: boolean) => void;
    agents: Agent[];
    select: (key: string) => void;
    /** Bring the review back, and how many items wait in it. */
    review: () => void;
    waiting: number;
    now: Date;
}

export function Palette({ open, setOpen, agents, select, review, waiting, now }: Props) {
    useEffect(() => {
        function pressed(event: KeyboardEvent) {
            if (event.key === "k" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                setOpen(!open);
            }
        }
        document.addEventListener("keydown", pressed);
        return () => document.removeEventListener("keydown", pressed);
    }, [open, setOpen]);
    return (
        <Command.Dialog
            open={open}
            onOpenChange={setOpen}
            label="Go to or do"
            overlayClassName="palette-overlay"
            contentClassName="palette"
        >
            <Command.Input placeholder="Go to an agent…" />
            <Command.List>
                <Command.Empty>Nothing matches.</Command.Empty>
                <Command.Group heading="Go to">
                    <Command.Item
                        value="review waiting on you"
                        onSelect={() => {
                            review();
                            setOpen(false);
                        }}
                    >
                        <span className="mono">the review</span>
                        <span className="state">{waiting} waiting on you</span>
                    </Command.Item>
                </Command.Group>
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
