// Every launch's conversations as a tree: the session's own, each subagent under
// the conversation that spawned it, the ended ones folded under a count. Arrows
// move, Enter selects, Left and Right fold (React Aria's tree). `h` turns the
// operator's switch for the conversation it's on, "hold each flagged write",
// which its row shows; Space `l`, or Space `w` `l`, gives the keyboard to the
// view beside the tree (`treeKey`).
import { useRef, useState, type Key, type KeyboardEvent } from "react";
import { Button, Tree, TreeItem, TreeItemContent } from "react-aria-components";

import { doing, everyone, over, repositories, treeKey, type Agent, type Launch, type Leading } from "./agents";

interface Props {
    served: Launch[];
    selected: string | null;
    select: (key: string) => void;
    now: Date;
    /** Turn the operator's switch for a conversation: whether each flagged write of it is held for them. */
    hold: (agent: Agent) => void;
    /** Give the keyboard to the view beside the tree. */
    right: () => void;
}

/** Keys pressed with others, which never begin or end a chord. */
const MODIFIERS = ["Shift", "Control", "Alt", "Meta"];

export function AgentTree({ served, selected, select, now, hold, right }: Props) {
    const [folded, setFolded] = useState<Set<Key>>(new Set());
    const [opened, setOpened] = useState<Set<Key>>(new Set());
    const leading = useRef<Leading>("");
    const sessions = served.flatMap((each) => (each.session === null ? [] : [each.session]));
    const grouped = repositories(served);
    const parents = [...grouped.map((each) => repositoryKey(each.path)), ...sessions.flatMap(withChildren)];
    const ended = sessions.flatMap(withEnded).map(endedKey);
    const expanded = [...parents.filter((key) => !folded.has(key)), ...ended.filter((key) => opened.has(key))];
    if (served.length === 0) {
        return <p className="empty">No session runs. Start one with `lup-dev launch claude`.</p>;
    }

    function keyed(event: KeyboardEvent<HTMLDivElement>) {
        if (event.ctrlKey || event.metaKey || event.altKey || MODIFIERS.includes(event.key)) {
            return;
        }
        const next = treeKey(leading.current, event.key);
        leading.current = next.leading;
        if (!next.taken) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        if (next.act === "right") {
            right();
        }
        if (next.act === "hold") {
            // The row the key is pressed on: React Aria's rows are flat, each holding its own content alone.
            const row = event.target instanceof HTMLElement ? event.target.closest('[role="row"]') : null;
            const path = row?.querySelector("[data-path]")?.getAttribute("data-path");
            const agent = everyone(served).find((each) => each.talker.path === path);
            if (agent !== undefined) {
                hold(agent);
            }
        }
    }

    return (
        <div className="tree-keys" onKeyDownCapture={keyed}>
        <Tree
            aria-label="Agents"
            selectionMode="single"
            disallowEmptySelection
            selectedKeys={selected === null ? [] : [selected]}
            onSelectionChange={(keys) => {
                if (keys !== "all") {
                    const [key] = [...keys];
                    if (key !== undefined && !String(key).startsWith("ended:") && !String(key).startsWith("repo:")) {
                        select(String(key));
                    }
                }
            }}
            expandedKeys={expanded}
            onExpandedChange={(keys) => {
                setFolded(new Set(parents.filter((key) => !keys.has(key))));
                setOpened(new Set(ended.filter((key) => keys.has(key))));
            }}
        >
            {grouped.map((repository) => (
                <TreeItem key={repository.path} id={repositoryKey(repository.path)} textValue={repository.name}>
                    <TreeItemContent>
                        {({ isExpanded }) => (
                            <Row
                                label={`${repository.name}/`}
                                kind="repository"
                                state="repository"
                                said={`${repository.launches.length} running`}
                                chevron={isExpanded ? "▾" : "▸"}
                            />
                        )}
                    </TreeItemContent>
                    {repository.launches.map((each) =>
                        each.session === null ? (
                            <TreeItem key={each.launch.launch} id={`launch:${each.launch.launch}`} textValue={name(each)}>
                                <TreeItemContent>
                                    <Row label={name(each)} kind="session" state="unheard" said="its session hasn't started" />
                                </TreeItemContent>
                            </TreeItem>
                        ) : (
                            item(each.session, now)
                        ),
                    )}
                </TreeItem>
            ))}
        </Tree>
        </div>
    );
}

function item(agent: Agent, now: Date) {
    const { talker } = agent;
    const live = agent.children.filter((child) => !over(child));
    const gone = agent.children.filter(over);
    const kind = talker.agent == null ? "session" : over(agent) ? "ended" : "subagent";
    return (
        <TreeItem key={talker.path} id={talker.path} textValue={talker.path}>
            <TreeItemContent>
                {({ hasChildItems, isExpanded }) => (
                    <Row
                        label={talker.own}
                        kind={kind}
                        state={state(agent)}
                        said={doing(talker.activity, now)}
                        chevron={hasChildItems ? (isExpanded ? "▾" : "▸") : null}
                        path={talker.path}
                        holding={talker.holding === true}
                    />
                )}
            </TreeItemContent>
            {live.map((child) => item(child, now))}
            {gone.length === 0 ? null : (
                <TreeItem key={endedKey(talker.path)} id={endedKey(talker.path)} textValue={`${gone.length} ended`}>
                    <TreeItemContent>
                        {({ isExpanded }) => (
                            <Row
                                label={`${gone.length} ended`}
                                kind="ended"
                                state="ended"
                                said=""
                                chevron={isExpanded ? "▾" : "▸"}
                            />
                        )}
                    </TreeItemContent>
                    {gone.map((child) => item(child, now))}
                </TreeItem>
            )}
        </TreeItem>
    );
}

interface RowProps {
    label: string;
    kind: string;
    state: string;
    said: string;
    chevron?: string | null;
    /** The conversation's path, for a key pressed on its row; none for a row of no conversation. */
    path?: string;
    /** Whether the operator holds each flagged write of the conversation. */
    holding?: boolean;
}

function Row({ label, kind, state, said, chevron = null, path, holding = false }: RowProps) {
    return (
        <div className="agent-row" data-path={path}>
            {chevron === null ? (
                <span className="chevron" />
            ) : (
                <Button slot="chevron" className="chevron" aria-label="Fold or unfold">
                    {chevron}
                </Button>
            )}
            <span className={`label ${kind}`}>{label}</span>
            {holding ? (
                <span className="holding" title="Each flagged write of it is held for your answer: h turns it off">
                    holding
                </span>
            ) : null}
            <span className="state" data-state={state}>
                {said}
            </span>
        </div>
    );
}

/** The key of each conversation with subagents under it, it first: each is unfolded until the operator folds it. */
function withChildren(agent: Agent): string[] {
    const below = agent.children.flatMap(withChildren);
    return agent.children.length === 0 ? below : [agent.talker.path, ...below];
}

/** The path of each conversation with ended subagents under it. */
function withEnded(agent: Agent): string[] {
    const below = agent.children.flatMap(withEnded);
    return agent.children.some(over) ? [agent.talker.path, ...below] : below;
}

function repositoryKey(path: string): string {
    return `repo:${path}`;
}

function endedKey(path: string): string {
    return `ended:${path}`;
}

function state(agent: Agent): string {
    const activity = agent.talker.activity;
    if (activity == null) {
        return "unheard";
    }
    if (activity.state === "calling" && activity.lups) {
        return "asking";
    }
    return activity.state;
}

function name(launch: Launch): string {
    return launch.launch.name ?? launch.launch.launch;
}
