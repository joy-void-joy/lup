// The page: every agent the host serves on the left, the one selected on the right.
import { useState } from "react";

import { everyone, launches, type Agent, type Launch } from "./agents";
import { AgentTree } from "./AgentTree";
import { Details } from "./Details";
import { useNow, useWatched } from "./hooks";
import { Palette } from "./Palette";

const SAID = {
    connecting: "connecting",
    live: "live",
    retrying: "out of reach, trying again",
};

export function App() {
    const { reply, connection } = useWatched({ kind: "list" });
    const now = useNow();
    const [selected, setSelected] = useState<string | null>(null);
    const [palette, setPalette] = useState(false);
    const served = reply?.kind === "listed" ? launches(reply) : [];
    const agents = everyone(served);
    const shown = found(served, agents, selected);
    return (
        <div className="layout">
            <header className="bar">
                <span className="name">lup</span>
                <span className="connection" data-state={connection}>
                    {SAID[connection]}
                </span>
                {reply?.kind === "refused" ? <span className="error">{reply.error}</span> : null}
                <span className="spacer" />
                <button type="button" onClick={() => setPalette(true)}>
                    Go to <kbd>Ctrl</kbd> <kbd>K</kbd>
                </button>
            </header>
            <nav className="win" aria-label="Agents">
                <div className="wb">
                    agents <span className="count">{agents.length}</span>
                </div>
                <div className="buf">
                    <AgentTree served={served} selected={selected} select={setSelected} now={now} />
                </div>
            </nav>
            <main className="win">
                <div className="wb">{shown === null ? "details" : (shown.agent?.talker.path ?? name(shown.launch))}</div>
                <div className="buf">
                    {shown === null ? (
                        <p className="empty">Select an agent, or press Ctrl K to go to one.</p>
                    ) : (
                        <Details launch={shown.launch} agent={shown.agent} now={now} />
                    )}
                </div>
            </main>
            <Palette open={palette} setOpen={setPalette} agents={agents} select={setSelected} now={now} />
        </div>
    );
}

/** The launch and conversation `key` names: a conversation's path, or a launch whose session hasn't started. */
function found(
    served: Launch[],
    agents: Agent[],
    key: string | null,
): { launch: Launch; agent: Agent | null } | null {
    if (key === null) {
        return null;
    }
    const waiting = served.find((each) => `launch:${each.launch.launch}` === key);
    if (waiting !== undefined) {
        return { launch: waiting, agent: null };
    }
    const agent = agents.find((each) => each.talker.path === key);
    const launch = served.find((each) => agent !== undefined && each.session !== null && within(each.session, agent));
    return agent === undefined || launch === undefined ? null : { launch, agent };
}

function within(root: Agent, agent: Agent): boolean {
    return root === agent || root.children.some((child) => within(child, agent));
}

function name(launch: Launch): string {
    return launch.launch.name ?? launch.launch.launch;
}
