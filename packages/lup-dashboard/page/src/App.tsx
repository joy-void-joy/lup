// The page: every agent the host serves on the left; everything waiting for the
// operator in the middle, as one review; their draft reply on the right.
// Selecting an agent narrows the review to what it and its subagents sent.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { everyone, launches, type Agent, type Launch } from "./agents";
import { AgentTree } from "./AgentTree";
import { ask } from "./api";
import { Details } from "./Details";
import { DraftPanel, reached } from "./DraftPanel";
import { useNow, useWatched } from "./hooks";
import { Palette } from "./Palette";
import { Review } from "./Review";
import { covered, EMPTY, type Draft, type Item } from "./review";

const SAID = {
    connecting: "connecting",
    live: "live",
    retrying: "out of reach, trying again",
};

export function App() {
    const { reply, connection } = useWatched({ kind: "list" });
    const inbox = useWatched({ kind: "inbox-list" });
    const now = useNow();
    const [selected, setSelected] = useState<string | null>(null);
    const [palette, setPalette] = useState(false);
    const [draft, setDraft] = useState<Draft>(EMPTY);
    const [diffs, setDiffs] = useState<Map<number, string>>(new Map());
    const [confirming, setConfirming] = useState(false);
    const [said, setSaid] = useState<string | null>(null);
    const keeping = useRef<ReturnType<typeof setTimeout> | null>(null);
    const served = reply?.kind === "listed" ? launches(reply) : [];
    const agents = everyone(served);
    const shown = found(served, agents, selected);
    const talkers = useMemo(() => agents.map((each) => each.talker), [agents]);

    const named = useCallback(
        (item: Item) => {
            const sender = item.sender;
            if (sender.party === "operator") {
                return "you";
            }
            const talker = talkers.find(
                (each) => each.session === sender.session && (each.agent ?? null) === (sender.agent ?? null),
            );
            return talker?.path ?? `${sender.runtime} ${sender.session}${sender.agent ? ` / ${sender.agent}` : ""}`;
        },
        [talkers],
    );

    const waiting = inbox.reply?.kind === "inbox-items" ? inbox.reply.items : [];
    const items = useMemo(
        () =>
            selected === null
                ? waiting
                : waiting.filter((each) => {
                      const path = named(each);
                      return path === selected || path.startsWith(`${selected}/`);
                  }),
        [waiting, selected, named],
    );

    useEffect(() => {
        void ask({ kind: "inbox-draft" }).then((answer) => {
            if (answer.kind === "inbox-drafted") {
                setDraft(answer.draft);
            }
        });
    }, []);

    const change = useCallback((next: Draft) => {
        setDraft(next);
        if (keeping.current !== null) {
            clearTimeout(keeping.current);
        }
        keeping.current = setTimeout(() => {
            void ask({ kind: "inbox-keep-draft", draft: next });
        }, 300);
    }, []);

    const open = useCallback((number: number) => {
        void ask({ kind: "inbox-show-diff", number }).then((answer) => {
            if (answer.kind === "inbox-diff") {
                setDiffs((before) => new Map(before).set(number, answer.text));
            }
        });
    }, []);

    const approve = useCallback((number: number, approved: boolean) => {
        void ask({ kind: "inbox-answer-approval", number, approved }).then((answer) => {
            setSaid(answer.kind === "refused" ? answer.error : `#${number} ${approved ? "approved" : "declined"}.`);
        });
    }, []);

    async function sent() {
        setConfirming(false);
        if (keeping.current !== null) {
            clearTimeout(keeping.current);
        }
        await ask({ kind: "inbox-keep-draft", draft });
        const answer = await ask({ kind: "inbox-send-draft" });
        if (answer.kind === "refused") {
            setSaid(answer.error);
            return;
        }
        if (answer.kind === "inbox-reviewed") {
            setSaid(`Sent: ${answer.items.map((each) => `#${each.number}`).join(", ") || "the draft"}.`);
        }
        const after = await ask({ kind: "inbox-draft" });
        if (after.kind === "inbox-drafted") {
            setDraft(after.draft);
        }
    }

    const to = reached(draft, waiting, named);
    return (
        <div className="layout">
            <header className="bar">
                <span className="name">lup</span>
                <span className="connection" data-state={connection}>
                    {SAID[connection]}
                </span>
                {reply?.kind === "refused" ? <span className="error">{reply.error}</span> : null}
                {said === null ? null : <span className="said">{said}</span>}
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
                {shown === null ? null : (
                    <div className="agent-details">
                        <Details launch={shown.launch} agent={shown.agent} now={now} />
                    </div>
                )}
            </nav>
            <main className="win">
                <div className="wb">
                    waiting on you <span className="count">{items.length}</span>
                    {selected === null ? null : (
                        <button type="button" className="all" onClick={() => setSelected(null)}>
                            from {selected} · show all
                        </button>
                    )}
                </div>
                <Review
                    items={items}
                    draft={draft}
                    change={change}
                    name={named}
                    diffs={diffs}
                    open={open}
                    send={() => setConfirming(covered(draft).length > 0)}
                    approve={approve}
                />
            </main>
            <aside className="win" aria-label="Your reply">
                <div className="wb">your reply</div>
                <div className="buf">
                    <DraftPanel draft={draft} change={change} items={waiting} name={named} />
                </div>
            </aside>
            {confirming ? (
                <div
                    className="confirm"
                    role="dialog"
                    aria-label="Send your reply"
                    tabIndex={-1}
                    ref={(box) => box?.focus()}
                    onKeyDown={(event) => {
                        if (event.key === "Enter") {
                            event.preventDefault();
                            void sent();
                        }
                        if (event.key === "Escape") {
                            setConfirming(false);
                        }
                    }}
                >
                    <p>
                        Send your reply on {covered(draft).map((each) => `#${each}`).join(", ")} to {to.join(", ")}?
                    </p>
                    <p className="muted">
                        Each gets all of it, its own items marked. <kbd>Enter</kbd> sends · <kbd>Esc</kbd> goes back.
                    </p>
                </div>
            ) : null}
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
