// Every launch's conversations as a tree: the session's own, each subagent under
// the conversation that spawned it. Arrows move, Enter selects, Left and Right
// fold (React Aria's tree).
import { useState, type Key } from "react";
import { Button, Tree, TreeItem, TreeItemContent } from "react-aria-components";

import { doing, type Agent, type Launch } from "./agents";

interface Props {
    served: Launch[];
    selected: string | null;
    select: (key: string) => void;
    now: Date;
}

export function AgentTree({ served, selected, select, now }: Props) {
    const [folded, setFolded] = useState<Set<Key>>(new Set());
    const parents = served.flatMap((each) => (each.session === null ? [] : withChildren(each.session)));
    const expanded = parents.filter((key) => !folded.has(key));
    if (served.length === 0) {
        return <p className="empty">No session runs. Start one with `lup-dev launch claude`.</p>;
    }
    return (
        <Tree
            aria-label="Agents"
            selectionMode="single"
            disallowEmptySelection
            selectedKeys={selected === null ? [] : [selected]}
            onSelectionChange={(keys) => {
                if (keys !== "all") {
                    const [key] = [...keys];
                    if (key !== undefined) {
                        select(String(key));
                    }
                }
            }}
            expandedKeys={expanded}
            onExpandedChange={(keys) => setFolded(new Set(parents.filter((key) => !keys.has(key))))}
        >
            {served.map((each) =>
                each.session === null ? (
                    <TreeItem key={each.launch.launch} id={`launch:${each.launch.launch}`} textValue={name(each)}>
                        <TreeItemContent>
                            <Row label={name(each)} state="unheard" said="its session hasn't started" />
                        </TreeItemContent>
                    </TreeItem>
                ) : (
                    item(each.session, now)
                ),
            )}
        </Tree>
    );
}

function item(agent: Agent, now: Date) {
    const { talker } = agent;
    return (
        <TreeItem key={talker.path} id={talker.path} textValue={talker.path}>
            <TreeItemContent>
                {({ hasChildItems, isExpanded }) => (
                    <Row
                        label={talker.own}
                        state={state(agent)}
                        said={doing(talker.activity, now)}
                        chevron={hasChildItems ? (isExpanded ? "▾" : "▸") : null}
                    />
                )}
            </TreeItemContent>
            {agent.children.map((child) => item(child, now))}
        </TreeItem>
    );
}

function Row({ label, state, said, chevron = null }: { label: string; state: string; said: string; chevron?: string | null }) {
    return (
        <div className="agent-row">
            {chevron === null ? (
                <span className="chevron" />
            ) : (
                <Button slot="chevron" className="chevron" aria-label="Fold or unfold">
                    {chevron}
                </Button>
            )}
            <span className="label mono">{label}</span>
            <span className="state" data-state={state} title={said}>
                {said}
            </span>
        </div>
    );
}

/** The key of each conversation with subagents under it, it first. */
function withChildren(agent: Agent): string[] {
    if (agent.children.length === 0) {
        return [];
    }
    return [agent.talker.path, ...agent.children.flatMap(withChildren)];
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
