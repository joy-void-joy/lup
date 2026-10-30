// The command palette: every agent the host serves, typed for, each going to their
// group in the review. Ctrl+K opens it, Escape closes it. And the palette naming
// the thread what Space s moves from the pile to read goes to (`ThreadPalette`).
import { Command } from "cmdk";
import { useEffect, useState } from "react";

import { doing, type Agent } from "./agents";
import type { Destination } from "./grammar";
import { searched } from "./keys";
import { about, type ThreadRead } from "./review";

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
            </Command.List>
        </Command.Dialog>
    );
}

interface Moving {
    /** What's being moved, by number, while the operator names where; none while nothing is. */
    moving: readonly number[] | null;
    /** The threads it may go to. */
    threads: readonly ThreadRead[];
    /** Go on with where it goes, or none where the operator closed the palette. */
    choose: (to: Destination | null) => void;
}

/**
 * The palette naming the thread what Space s moves from the pile to read goes to: the threads it may go to, by name
 * and what each is about, those matching what's typed first; and, where what's typed names none of them, a thread
 * opened with it as its title, first. Enter goes on with the one chosen, Escape with none.
 */
export function ThreadPalette({ moving, threads, choose }: Moving) {
    const [typed, setTyped] = useState("");
    // Each time it opens, nothing typed yet.
    const open = moving !== null;
    useEffect(() => {
        if (open) {
            setTyped("");
        }
    }, [open]);
    const title = typed.trim();
    const matching = threads
        .map((read) => ({ read, score: searched(`@${read.thread.name} ${about(read.thread)}`, title) }))
        .filter((each) => each.score > 0)
        .toSorted((a, b) => b.score - a.score)
        .map((each) => each.read);
    const named = threads.some((each) => each.thread.name === title.replace(/^@/, ""));
    const count = moving?.length ?? 0;
    return (
        <Command.Dialog
            open={open}
            onOpenChange={(open) => {
                if (!open) {
                    choose(null);
                }
            }}
            label="Move into a thread"
            overlayClassName="palette-overlay"
            contentClassName="palette"
            shouldFilter={false}
        >
            <Command.Input value={typed} onValueChange={setTyped} placeholder={`Move ${count === 1 ? "it" : `these ${count}`} into a thread, or type a new one's title…`} />
            <Command.List>
                <Command.Empty>No thread here takes them: type a title to open one.</Command.Empty>
                {title === "" || named ? null : (
                    <Command.Item value={`new ${title}`} onSelect={() => choose({ title })}>
                        <span>a new thread: {title}</span>
                    </Command.Item>
                )}
                <Command.Group heading="Threads">
                    {matching.map((read) => (
                        <Command.Item key={read.thread.number} value={`@${read.thread.name}`} onSelect={() => choose({ thread: read.thread.number, name: read.thread.name })}>
                            <span className="mono">@{read.thread.name}</span>
                            <span className="state">{about(read.thread)}</span>
                        </Command.Item>
                    ))}
                </Command.Group>
            </Command.List>
        </Command.Dialog>
    );
}
