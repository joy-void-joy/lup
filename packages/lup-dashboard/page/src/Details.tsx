// One conversation, as the tree's selection shows it: what it is, what it's doing,
// and the launch it runs in.
import { doing, type Agent, type Launch } from "./agents";

interface Props {
    launch: Launch;
    agent: Agent | null;
    now: Date;
}

export function Details({ launch, agent, now }: Props) {
    const { launch: registered } = launch;
    if (agent === null) {
        return (
            <section className="details" aria-label="Details">
                <h1 className="mono">{registered.name ?? registered.launch}</h1>
                <p className="hint">Its session hasn't reached lup yet.</p>
                <LaunchFacts launch={launch} />
            </section>
        );
    }
    const { talker } = agent;
    return (
        <section className="details" aria-label="Details">
            <h1 className="mono">{talker.path}</h1>
            <p>{doing(talker.activity, now)}</p>
            <dl>
                <dt>Kind</dt>
                <dd>{talker.agent == null ? "the session's own conversation" : (talker.kind ?? "a subagent")}</dd>
                <dt>Session</dt>
                <dd className="mono">{talker.session}</dd>
                {talker.agent == null ? null : (
                    <>
                        <dt>Subagent</dt>
                        <dd className="mono">{talker.agent}</dd>
                    </>
                )}
                <dt>Subagents</dt>
                <dd>{agent.children.length === 0 ? "none" : agent.children.map((each) => each.talker.own).join(", ")}</dd>
            </dl>
            <LaunchFacts launch={launch} />
        </section>
    );
}

function LaunchFacts({ launch }: { launch: Launch }) {
    const { launch: registered } = launch;
    return (
        <dl>
            <dt>Launch</dt>
            <dd className="mono">{registered.name ?? registered.launch}</dd>
            <dt>Runtime</dt>
            <dd>{registered.runtime}</dd>
            <dt>Worktree</dt>
            <dd className="mono">{registered.worktree}</dd>
            <dt>Id</dt>
            <dd className="mono">{registered.launch}</dd>
        </dl>
    );
}
