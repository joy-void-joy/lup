// The command palette: every agent the host serves, typed for, each going to its
// group in the review; and the layout trials, a switch at a time (`trials.ts`).
// Ctrl+K opens it, Escape closes it.
import { Command } from "cmdk";
import { useEffect } from "react";

import { doing, type Agent } from "./agents";
import { CHOICES, type Trials } from "./trials";

interface Props {
    open: boolean;
    setOpen: (open: boolean) => void;
    agents: Agent[];
    /** Go to an agent's group, by its conversation's path. */
    select: (path: string) => void;
    now: Date;
    /** The layout trials as they stand, and how to change them. */
    trials: Trials;
    choose: (trials: Trials) => void;
}

export function Palette({ open, setOpen, agents, select, now, trials, choose }: Props) {
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
                <Command.Group heading="Layout trials">
                    {CHOICES.map((choice) => (
                        <Command.Item
                            key={choice.id}
                            value={`Layout: ${choice.said}`}
                            onSelect={() => {
                                choose(choice.made(trials));
                                setOpen(false);
                            }}
                        >
                            <span>Layout: {choice.said}</span>
                            <span className="state">{choice.chosen(trials) ? "● on" : ""}</span>
                        </Command.Item>
                    ))}
                </Command.Group>
            </Command.List>
        </Command.Dialog>
    );
}
